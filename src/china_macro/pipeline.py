"""Independent source failures retain history without disguising it as fresh."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import uuid

import pandas as pd

from .config import DATA_DIR
from .calendar import release_calendar
from .normalize import clean, derive, missing_months
from .pbc import afre, comparable_m1, loan_balances
from .press import releases
from .sources import Fetcher, EM_REPORTS, NBS_CATALOGS, bond_yields, eastmoney, nbs_catalog, rates_json, safe_fixing
from .storage import load_current, save_current


def needs_history_backfill(prior, metrics):
    return any((history := prior[prior["metric"].eq(metric)]).empty
               or missing_months(history, metric) for metric in metrics)


def run_pipeline(*, backfill=False, write=True, root=DATA_DIR, jobs=None):
    if jobs is not None and write and Path(root).resolve() == DATA_DIR.resolve():
        raise ValueError("Injected/partial jobs cannot publish the production snapshot")
    captured = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    prior, _, previous_manifest = load_current(root)
    fetch = Fetcher(run_id)
    calendar = previous_manifest.get("publication_calendar", [])
    calendar_error = None
    if jobs is None:
        try:
            calendar = release_calendar(fetch, captured)
        except Exception as error:
            calendar_error = type(error).__name__
    nbs_start = "1990-01-01" if backfill or prior.empty else f"{pd.Timestamp(captured).year - 1}-01-01"
    bonds = prior[prior["metric"].isin(["cgb_1y", "cgb_10y"])]
    bond_start = "2010-01-01" if backfill or bonds.empty else (pd.Timestamp(bonds["date"].max()) - pd.Timedelta(days=14)).strftime("%Y-%m-%d")
    if jobs is None:
        jobs = {f"eastmoney:{report}": lambda report=report: eastmoney(fetch, report, captured) for report in EM_REPORTS}
        jobs.update({f"nbs:{path}": lambda path=path: nbs_catalog(fetch, path, captured, nbs_start) for path in NBS_CATALOGS
                     if backfill or prior.empty or "(2012-2017)" not in path})
        jobs.update({"pbc:afre": lambda: afre(fetch, captured, backfill=backfill or previous_manifest.get("schema_version", 0) < 2 or needs_history_backfill(prior, ["tsf_flow", "tsf_stock", "tsf_stock_yoy", "tsf_rmb_loans"])),
                     "pbc:loan_balances": lambda: loan_balances(fetch, captured, backfill=backfill or needs_history_backfill(prior, ["household_loan_balance", "corporate_loan_balance"])),
                     "nbs:official_releases": lambda: releases(fetch, captured, backfill=backfill or prior.empty),
                     "pbc:m1_comparable": lambda: comparable_m1(fetch, captured),
                     "rates:shibor": lambda: rates_json(fetch, "shibor", captured),
                     "rates:fx": lambda: safe_fixing(fetch, captured),
                     "chinabond:yields": lambda: bond_yields(fetch, captured, bond_start)})
    frames, results = {}, []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(job): key for key, job in jobs.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                frame = clean(future.result())
                if frame.empty:
                    raise ValueError("Source returned no usable observations")
                frames[key] = frame
                result = dict(source=key, status="success", records=len(frame), metrics=sorted(frame["metric"].unique().tolist()), error=None)
            except Exception as error:
                result = dict(source=key, status="failed", records=0, metrics=[], error=f"{type(error).__name__}: {str(error)[:240]}")
            results.append(result)
            print(f"{key}: {result['status']} ({result['records']} rows)", flush=True)
    if not frames:
        raise RuntimeError("All China macro fetches failed; previous snapshot preserved")
    # Sort successful frames for reproducible source priority. Revised official
    # M1 back data is a distinct id, never overwrites the legacy series.
    # Official releases override same-period mirrored and databank records;
    # completion order of concurrent HTTP requests must not choose the value.
    keys = sorted(frames, key=lambda key: (key == "nbs:official_releases", key))
    new = clean(pd.concat([frames[key] for key in keys], ignore_index=True))
    # A successfully reparsed annual PBC workbook replaces its prior rows,
    # including rows an old parser mistakenly read from appended ratio tables.
    replaced_pbc_rows = 0
    if not prior.empty:
        archival = new[new["source"].isin(["People's Bank of China", "People's Bank of China (RMB credit funds)"])]
        replaced = prior["source_url"].isin(archival["source_url"].unique())
        replaced_pbc_rows = int(replaced.sum())
        prior = prior.loc[~replaced]
    # Reparsed official releases supersede their earlier wrongly dated records.
    # Limit this to article URLs: mirror URLs cover many legitimate periods.
    corrected_periods = 0
    if not prior.empty:
        official = new[new["source"].eq("National Bureau of Statistics (official release)")]
        periods = {(r.metric, r.source_url): r.date for r in official.itertuples()}
        keep = [periods.get((r.metric, r.source_url), r.date) == r.date for r in prior.itertuples()]
        corrected_periods = len(prior) - sum(keep)
        prior = prior.loc[keep]
    observations = clean(pd.concat([prior, new], ignore_index=True)) if not prior.empty else new
    signals = derive(observations, captured)
    manifest = dict(run_id=run_id, created_at=captured, scope="full", source_results=sorted(results, key=lambda x: x["source"]),
                    refreshed_metrics=sorted(new["metric"].unique().tolist()), schema_version=2,
                    publication_calendar=calendar, calendar_error=calendar_error, fetch_warnings=fetch.failures,
                    corrected_release_periods=corrected_periods, replaced_pbc_archival_rows=replaced_pbc_rows)
    if write:
        save_current(observations, signals, manifest, root)
    return observations, signals, manifest
