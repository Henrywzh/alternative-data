"""Build the Index & ETF Allocation Monitor dashboard artifact.

Read-only: consumes latest normalized/derived market_monitor snapshots and
packages them into the shared Asia Markets artifact contract so the same
portable renderer / Streamlit surface can display the exposure and wrapper
views without touching the live data sources at build time.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from src.market_monitor.config import (
    DERIVED_DIR,
    EXPOSURES,
    NORMALIZED_DIR,
    charted_exposures,
    exposures_by_price_source,
    investable_exposures,
)
from src.market_monitor.metadata import build_metadata_frame
from src.market_monitor.freshness import (
    BLOCKING_FRESHNESS_STATUSES,
    classify_daily_groups,
    classify_daily_observation,
    classify_intraday_quote,
)
from src.market_monitor.pipeline import coverage_regressions  # noqa: E402
from src.market_monitor.ranking import rank_wrappers
from src.market_monitor.storage import load_lineage_history, load_latest_with_lineage  # noqa: E402
from src.market_monitor.wrapper import filter_premium_history_to_sessions  # noqa: E402
from history_policy import history_window  # noqa: E402

# Charts read a date window, not a row count: with a row count the displayed
# history depends on how many series share the slice and on how many sessions
# each venue happened to trade.  Two years is what the pipeline fetches, so
# this ships everything collected rather than silently halving it.
CHART_HISTORY_YEARS = 2


# Fields render_southbound_market_flow actually reads (KPI strip + dual-axis
# chart). Add one here when the renderer starts needing it.
SOUTHBOUND_ARTIFACT_COLUMNS: tuple[str, ...] = (
    "trade_date",
    "net_buy_yi",
    "balance_yi",
    "holding_market_value",
)


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    out = frame.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    return json.loads(out.to_json(orient="records", date_format="iso", default_handler=str))


def _chart_series(
    frame: pd.DataFrame,
    id_column: str,
    value_column: str,
    *,
    years: int = CHART_HISTORY_YEARS,
    id_as: str | None = None,
    keep: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Rows for a line chart: the latest ``years`` of ``date``/id/value only.

    Everything else the normalized store carries -- OHLC, volume, turnover,
    the second and third identifier for the same fund -- is dropped, because
    no renderer reads it and each unread field is paid for in every row of
    every daily artifact.  Add a column here when a chart starts needing it.

    ``id_as`` renames the identifier so that every dataset a renderer joins
    keys on the same value.  The ETF datasets previously disagreed: the price
    series carried the exchange-qualified ``159919.SZ`` while wrapper metrics
    and premium history carried the bare ``159919``, so the join that draws
    every ETF on an index matched nothing and the chart silently never drew.
    """
    if frame is None or frame.empty:
        return []
    if not {"date", id_column, value_column}.issubset(frame.columns):
        return []
    windowed = history_window(frame, "date", years=years)
    if windowed.empty:
        return []
    columns = ["date", id_column, value_column]
    columns += [name for name in keep if name in windowed.columns and name not in columns]
    projected = windowed[columns].sort_values(["date", id_column])
    if id_as and id_as != id_column:
        projected = projected.rename(columns={id_column: id_as})
    return _records(projected)


@dataclass(frozen=True)
class ProviderDelivery:
    """What each price provider actually delivered this run.

    build_artifact used to derive the source-health rows from about thirty
    loose locals scattered across a hundred lines, which is why nothing tested
    the status rules: there was no way to call them. Gathering the counts here
    lets _source_health_rows be a pure function of this record.
    """

    spot_status: str
    spot_notes: str
    spot_latest: str
    spot_observed: int
    csindex_count: int
    csindex_expected: int
    csindex_rows: int
    csindex_latest: str
    sina_hk_count: int
    sina_hk_expected: int
    sina_hk_rows: int
    sina_hk_latest: str
    sina_status: str
    sina_actual_count: int
    sina_expected: int
    sina_records: int
    sina_latest: str
    yfinance_status: str
    yahoo_labels: str
    yahoo_actual_count: int
    yahoo_expected: int
    yahoo_records: int
    yahoo_latest: str
    southbound_rows: int
    southbound_latest: str


def _source_health_rows(delivery: ProviderDelivery) -> list[dict[str, Any]]:
    """The per-provider health rows, from delivery alone.

    Run-level diagnostics -- coverage regression, upstream fetch errors, run
    consistency -- are appended by the caller, because they come from lineage
    rather than from what a provider returned.
    """
    d = delivery
    return [
        {
            "source": "Eastmoney ETF spot (premium / turnover / IOPV)",
            "status": d.spot_status,
            "latest_observation": f"run {d.spot_latest}Z" if d.spot_latest != "—" else "—",
            "records": d.spot_observed,
            "notes": d.spot_notes,
        },
        {
            "source": "CSI index daily (Hong Kong Connect thematics)",
            "status": "Healthy" if d.csindex_count >= d.csindex_expected else "Degraded",
            "latest_observation": d.csindex_latest,
            "records": d.csindex_rows,
            "notes": f"Daily OHLCV for {d.csindex_count} of {d.csindex_expected} CSI-served exposures.",
        },
        {
            "source": "Sina HK index daily (Hang Seng / CSI Hong Kong)",
            "status": "Healthy" if d.sina_hk_count >= d.sina_hk_expected else "Degraded",
            "latest_observation": d.sina_hk_latest,
            "records": d.sina_hk_rows,
            "notes": f"Daily OHLCV for {d.sina_hk_count} of {d.sina_hk_expected} Hong Kong exposures.",
        },
        {
            "source": "Sina index daily (CN)",
            "status": d.sina_status,
            "latest_observation": d.sina_latest,
            "records": d.sina_records,
            "notes": (
                f"Covering {d.sina_actual_count} of {d.sina_expected} Sina-owned exposures (CN/HK)."
                if d.sina_actual_count < d.sina_expected
                else f"Daily OHLCV for all {d.sina_actual_count} Sina-owned exposures (CN/HK)."
            ),
        },
        {
            "source": f"Yahoo Finance ({d.yahoo_labels})",
            "status": d.yfinance_status,
            "latest_observation": d.yahoo_latest,
            # Counted over every exposure Yahoo actually serves. This was
            # len(sp500 rows) even after Nasdaq 100 was added to the label.
            "records": d.yahoo_records,
            "notes": (
                f"US session history for {d.yahoo_actual_count} of {d.yahoo_expected} Yahoo-served exposures."
                if d.yahoo_actual_count >= d.yahoo_expected
                else f"Only {d.yahoo_actual_count} of {d.yahoo_expected} Yahoo-served indexes returned data."
            ),
        },
        # Southbound shipped to the browser with no health row at all, so an
        # empty fetch would have looked identical to a quiet market. Every
        # dataset in the artifact gets a row that can say "Unavailable".
        {
            "source": "Eastmoney aggregate southbound Stock Connect flow",
            "status": "Healthy" if d.southbound_rows else "Unavailable",
            "latest_observation": d.southbound_latest,
            "records": d.southbound_rows,
            "notes": (
                f"Daily aggregate southbound net buy / holding value, {d.southbound_rows} sessions "
                f"through {d.southbound_latest}."
                if d.southbound_rows
                else "Southbound flow fetch returned no rows; the panel has no data this run."
            ),
        },
    ]


def _apply_daily_source_freshness(
    rows: list[dict[str, Any]],
    daily_by_source: dict[str, dict[str, Any]],
    southbound: dict[str, Any],
) -> list[dict[str, Any]]:
    """Make source-health status reflect source-specific observation dates."""
    source_prefixes = {
        "CSI index daily": "csindex",
        "Sina HK index daily": "sina_hk",
        "Sina index daily": "sina",
        "Yahoo Finance": "yfinance",
    }
    out = [dict(row) for row in rows]
    for row in out:
        source = str(row.get("source") or "")
        group = next(
            (group for prefix, group in source_prefixes.items() if source.startswith(prefix)),
            None,
        )
        record = southbound if source.startswith("Eastmoney aggregate southbound") else (
            daily_by_source.get(group, {}) if group else {}
        )
        if not record:
            continue
        status = str(record.get("status") or "Unavailable")
        if status in BLOCKING_FRESHNESS_STATUSES:
            row["status"] = "Unavailable" if status == "Unavailable" else "Degraded"
        observation_date = record.get("observation_date")
        if observation_date:
            row["latest_observation"] = str(observation_date)
        detail = f" Freshness: {status}"
        if observation_date:
            detail += f" through {observation_date}."
        row["notes"] = f"{row.get('notes', '').rstrip()} {detail}".strip()
    return out


def build_artifact() -> tuple[dict[str, Any], dict[str, Any]]:
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat()
    technicals, tech_lineage = load_latest_with_lineage(DERIVED_DIR, "exposure_technicals", scope="full")
    regime, regime_lineage = load_latest_with_lineage(DERIVED_DIR, "relative_regime", scope="full")
    wrappers, wrap_lineage = load_latest_with_lineage(DERIVED_DIR, "wrapper_metrics", scope="full")
    index_px, index_lineage = load_latest_with_lineage(NORMALIZED_DIR, "index_price_daily", scope="full")
    premium_hist, premium_lineage = load_latest_with_lineage(DERIVED_DIR, "premium_history", scope="full")
    pairs, _pairs_lineage = load_latest_with_lineage(DERIVED_DIR, "relative_pairs", scope="full")
    pair_hist, _pair_hist_lineage = load_latest_with_lineage(DERIVED_DIR, "relative_pair_history", scope="full")
    etf_px, etf_px_lineage = load_latest_with_lineage(NORMALIZED_DIR, "etf_price_daily", scope="full")
    southbound, southbound_lineage = load_latest_with_lineage(NORMALIZED_DIR, "southbound_market_flow", scope="full")

    # Re-validate the persisted history at the artifact boundary as well as in
    # the close pipeline. This protects a rebuild from an older derived file
    # that predates the ETF-session gate.
    premium_hist = filter_premium_history_to_sessions(premium_hist, etf_px)

    # Add bilingual labels from config
    label_zh_map = {e["exposure_id"]: e.get("label_zh", e["label"]) for e in EXPOSURES}
    index_zh_map = {e["exposure_id"]: e.get("index_id", "") for e in EXPOSURES}
    if not technicals.empty and "exposure_id" in technicals.columns:
        technicals = technicals.copy()
        technicals["label_zh"] = technicals["exposure_id"].map(label_zh_map).fillna(technicals["label"])
        technicals["index_id"] = technicals["exposure_id"].map(index_zh_map)

    # Average premium (30D) per exposure from premium_history
    if not premium_hist.empty and not technicals.empty:
        wrapper_exp = wrappers[["fund_id", "exposure_id"]].drop_duplicates() if not wrappers.empty and "fund_id" in wrappers.columns else pd.DataFrame()
        if not wrapper_exp.empty:
            ph = premium_hist.merge(wrapper_exp, on="fund_id", how="left")
            ph["date"] = pd.to_datetime(ph["date"], errors="coerce")
            cutoff = ph["date"].max() - pd.Timedelta(days=30)
            recent = ph[ph["date"] >= cutoff]
            if not recent.empty and "exposure_id" in recent.columns:
                avg_prem = recent.groupby("exposure_id")["premium_pct"].mean().round(2)
                technicals["avg_premium_30d"] = technicals["exposure_id"].map(avg_prem)
                # How many distinct observation days actually went into that
                # mean. The label used to read "30D" whatever the answer was,
                # and the shipped artifact held one observation per fund on a
                # single date -- a point-in-time premium presented as a
                # thirty-day average. The renderer names the real window.
                days = recent.groupby("exposure_id")["date"].nunique()
                technicals["avg_premium_days"] = technicals["exposure_id"].map(days).fillna(0).astype(int)
            else:
                technicals["avg_premium_30d"] = float("nan")
                technicals["avg_premium_days"] = 0

    # --- Run consistency check: all datasets must come from the same run ---
    lineages = {
        "exposure_technicals": tech_lineage,
        "relative_regime": regime_lineage,
        "wrapper_metrics": wrap_lineage,
        "index_price_daily": index_lineage,
    }
    run_ids = {name: (li or {}).get("run_id") for name, li in lineages.items()}
    unique_run_ids = {rid for rid in run_ids.values() if rid}
    run_consistent = len(unique_run_ids) == 1 and all(run_ids.values())
    latest_run_id = max(unique_run_ids, key=str) if unique_run_ids else None
    if not run_consistent:
        stale_datasets = [name for name, rid in run_ids.items() if not rid or rid != latest_run_id]
    else:
        stale_datasets = []

    data_as_of = "—"
    if not technicals.empty and "date" in technicals.columns:
        data_as_of = str(pd.to_datetime(technicals["date"], errors="coerce").max().date())

    investable_ids = [spec["exposure_id"] for spec in investable_exposures()]
    datasets: dict[str, list[dict[str, Any]]] = {
        "exposure_technicals": _records(technicals),
        "relative_regime": _records(regime),
        "wrapper_metrics": _records(wrappers),
        # ``basis`` rides along because the series mixes two measurements:
        # published NAV for history, IOPV for the days NAV has not caught up
        # to. A chart that draws them as one line should be able to say so.
        "premium_history": _chart_series(premium_hist, "ticker", "premium_pct", keep=("basis",)),
        "relative_pairs": _records(pairs),
        # The ratio is charted over the same two-year window as the prices;
        # the five years behind it exist so the z-score has a full trailing
        # year of baseline on the first day shown, not so all five are drawn.
        "relative_pair_history": _chart_series(pair_hist, "pair_id", "ratio", keep=("ratio_ma", "zscore")),
        "etf_price_daily_tail": _chart_series(etf_px, "fund_id", "close", id_as="ticker"),
        # Only the four fields render_southbound_market_flow reads. The full
        # 17-column dump was 1.5 MB of a 3.7 MB artifact, of which source_id /
        # source_url / retrieved_at_utc / flow were one constant value repeated
        # across 2,698 rows. Lineage belongs in the sources block, once.
        "southbound_market_flow": _records(
            southbound.loc[:, [c for c in SOUTHBOUND_ARTIFACT_COLUMNS if c in southbound.columns]]
            if southbound is not None and not southbound.empty
            else southbound
        ),
        # Price series for every exposure a regional tab charts. This was an
        # inline set literal that had drifted from the tabs it was meant to
        # serve: us_growth, us_small and us_value were listed in the US tab but
        # missing here, so that tab silently offered four of its seven indices.
        "index_price_daily_tail": _chart_series(
            index_px[index_px["exposure_id"].isin(charted_exposures())] if not index_px.empty else index_px,
            "exposure_id",
            "close",
        ),
    }
    # Source-specific latest observations (do not share across sources).
    # Split on the declared price_source, not on "is it sp500" -- Nasdaq 100
    # also comes from Yahoo, and dating it as a Sina observation would report
    # a US session close as the CN/HK feed's freshness.
    sina_ids = list(exposures_by_price_source("sina"))
    sina_hk_ids = list(exposures_by_price_source("sina_hk"))
    csindex_ids = list(exposures_by_price_source("csindex"))
    yahoo_ids = list(exposures_by_price_source("yfinance"))
    if not index_px.empty and "date" in index_px.columns:
        cn_index = index_px[index_px["exposure_id"].isin(sina_ids)]
        sina_latest = str(pd.to_datetime(cn_index["date"], errors="coerce").max().date()) if not cn_index.empty else "—"
        us_index = index_px[index_px["exposure_id"].isin(yahoo_ids)]
        yahoo_latest = str(pd.to_datetime(us_index["date"], errors="coerce").max().date()) if not us_index.empty else "—"
        # Same reasoning as Yahoo above, extended to the two feeds that were
        # still borrowing the mainland Sina date: a source-health row has to
        # date itself by its own observations, or a stalled HK/CSI feed reads
        # as fresh for as long as the mainland one keeps updating.
        hk_index = index_px[index_px["exposure_id"].isin(sina_hk_ids)]
        sina_hk_latest = str(pd.to_datetime(hk_index["date"], errors="coerce").max().date()) if not hk_index.empty else "—"
        csi_index = index_px[index_px["exposure_id"].isin(csindex_ids)]
        csindex_latest = str(pd.to_datetime(csi_index["date"], errors="coerce").max().date()) if not csi_index.empty else "—"
        latest_obs = str(pd.to_datetime(index_px["date"], errors="coerce").max().date())
    else:
        sina_latest = yahoo_latest = latest_obs = "—"
        sina_hk_latest = csindex_latest = "—"
    # Use the source-layer retrieval timestamp when the persisted wrapper rows
    # have one. Never substitute this artifact's generation time: it is not a
    # quote observation and would make an old snapshot look current.
    spot_retrieved_at = None
    if not wrappers.empty and "retrieved_at_utc" in wrappers.columns:
        retrieved_values = wrappers["retrieved_at_utc"].dropna().astype(str)
        spot_retrieved_at = retrieved_values.iloc[0] if not retrieved_values.empty else None
    # Older committed wrapper snapshots do not carry row-level retrieval time;
    # those are intentionally reported as unknown rather than being treated as
    # current because the artifact happened to be rebuilt today.
    has_quote_rows = (
        not wrappers.empty
        and "premium_pct" in wrappers.columns
        and pd.to_numeric(wrappers["premium_pct"], errors="coerce").notna().any()
    )
    spot_freshness = classify_intraday_quote(
        retrieved_at_utc=spot_retrieved_at,
        source_observed_at_utc=None,
        quote_available=has_quote_rows,
    )
    # Older wrapper snapshots may contain a premium but no row-level quote
    # provenance. Do not let that value look current merely because the JSON
    # artifact was rebuilt today. The row keeps its raw value for auditability,
    # while the renderer/ranker sees it as unavailable unless the quote
    # snapshot itself has a valid fresh retrieval timestamp.
    if not wrappers.empty:
        wrappers = wrappers.copy()
        has_premium = (
            pd.to_numeric(wrappers["premium_pct"], errors="coerce").notna()
            if "premium_pct" in wrappers.columns
            else pd.Series(False, index=wrappers.index)
        )
        if "quote_basis" not in wrappers.columns:
            wrappers["quote_basis"] = has_premium.map(
                lambda value: "intraday_quote"
                if value and spot_freshness["status"] in {"Fresh", "Unverified"}
                else None
            )
        last_close = wrappers["quote_basis"].astype(str).eq("last_close")
        wrappers["quote_status"] = has_premium.map(
            lambda value: spot_freshness["status"] if value else "Unavailable"
        )
        wrappers.loc[last_close, "quote_status"] = "Unavailable"
        # Recompute the derived entry fields after stamping freshness. A
        # previously persisted artifact can contain FAIR/rank values from a
        # run whose quote timestamp is no longer available; carrying those
        # numbers forward would make a raw JSON consumer see stale advice.
        wrappers = rank_wrappers(wrappers)
        # ``datasets`` was initialized before the provenance gate so the
        # wrapper JSON keeps the row-level status, too.
        datasets["wrapper_metrics"] = _records(wrappers)
    # Do not fall back to the derived-run creation time: that is when the
    # artifact was written, not when the ETF quote was observed.
    spot_latest = (
        str(spot_freshness.get("retrieved_at_utc"))[:16].replace("T", " ")
        if spot_freshness.get("retrieved_at_utc")
        else "—"
    )

    # Compact KPI row for the Overview pulse card. ONE WIDE ROW, one column per
    # metric: latest_metric_reading takes latest_row(frame) and reads
    # row[field], so it has no way to pick a row by metric name. This was a
    # long-form table of three rows all carrying the reading in a column called
    # "value", and both configured pulse metrics resolved to the same row --
    # the overview showed "Small / Large z 42.9", which was the CSI 300 RSI,
    # while the real z-score sat in the artifact at 1.66.
    kpi_row: dict[str, Any] = {}
    if not technicals.empty and "exposure_id" in technicals.columns:
        for exposure_id, field in (("csi300", "csi300_rsi"), ("sp500", "sp500_rsi")):
            row = technicals[technicals["exposure_id"].eq(exposure_id)]
            if row.empty:
                continue
            value = row.iloc[-1].get("rsi")
            kpi_row[field] = float(value) if value is not None and not pd.isna(value) else None
    if regime is not None and not regime.empty and "label" in regime.columns:
        small_large = regime[regime["label"].eq("Small / Large")]
        if not small_large.empty:
            value = small_large.iloc[-1].get("spread_20d_zscore")
            kpi_row["small_large_z"] = float(value) if value is not None and not pd.isna(value) else None
    if kpi_row:
        kpi_row["observation_date"] = data_as_of
    datasets["kpi_market"] = [kpi_row] if kpi_row else []
    if not index_px.empty and "date" in index_px.columns:
        latest_obs = str(pd.to_datetime(index_px["date"], errors="coerce").max().date())
    else:
        latest_obs = "—"

    # Source ownership comes from each exposure's declared price_source, not
    # from a hard-coded exclusion. "Everything except sp500 is Sina" was true
    # until Nasdaq 100 arrived on yfinance, after which Sina was credited with
    # 501 rows and an exposure it does not serve, while Yahoo reported 501 rows
    # for the two indexes it actually fetched.
    sina_expected = sina_ids
    yahoo_expected = yahoo_ids
    # Delivery is counted from the price series, not from the technical cards.
    # Benchmarks -- the relative-strength legs -- are fetched from the same
    # providers but get no card, so counting cards would report a provider as
    # Degraded for series it delivered in full.
    served = (
        index_px["exposure_id"].astype(str)
        if not index_px.empty and "exposure_id" in index_px.columns
        else pd.Series(dtype=str)
    )
    sina_actual_count = served[served.isin(sina_expected)].nunique()
    sina_hk_count = served[served.isin(sina_hk_ids)].nunique()
    sina_hk_rows = int(served.isin(sina_hk_ids).sum()) if len(served) else 0
    csindex_count = served[served.isin(csindex_ids)].nunique()
    csindex_rows = int(served.isin(csindex_ids).sum()) if len(served) else 0
    expected_count = len(EXPOSURES)
    actual_exposures = served.nunique()
    expected_wrappers = len(build_metadata_frame())
    if not wrappers.empty and "premium_pct" in wrappers.columns:
        spot_observed = int(pd.to_numeric(wrappers["premium_pct"], errors="coerce").notna().sum())
    else:
        spot_observed = 0
    yahoo_rows = (
        index_px[index_px["exposure_id"].isin(yahoo_expected)]
        if not index_px.empty and "exposure_id" in index_px.columns
        else pd.DataFrame()
    )
    yahoo_actual_count = yahoo_rows["exposure_id"].nunique() if not yahoo_rows.empty else 0
    sp500_ok = yahoo_actual_count >= len(yahoo_expected)

    if spot_observed == expected_wrappers and expected_wrappers > 0 and spot_freshness["status"] == "Fresh":
        spot_status = "Healthy"
        spot_notes = f"Eastmoney ETF spot: all {spot_observed} / {expected_wrappers} wrappers observed; {spot_freshness['timestamp_basis']} timestamp."
    elif spot_observed > 0:
        spot_status = "Degraded"
        spot_notes = f"Eastmoney ETF spot: {spot_observed} / {expected_wrappers} wrappers observed; freshness={spot_freshness['status']} ({spot_freshness['timestamp_basis']})."
    else:
        spot_status = "Unavailable"
        spot_notes = f"Eastmoney ETF spot snapshot failed (0 / {expected_wrappers} wrappers observed)."

    sina_status = "Healthy" if sina_actual_count >= len(sina_expected) else "Degraded"
    sina_records = (
        len(index_px[index_px["exposure_id"].isin(sina_expected)])
        if not index_px.empty and "exposure_id" in index_px.columns
        else 0
    )
    yfinance_status = "Healthy" if sp500_ok else "Degraded"
    # Name the headline exposures and count the rest. Listing all thirteen
    # produced a source-health row whose title ran to a full line of text.
    _yahoo_named = [
        next((e["label"] for e in EXPOSURES if e["exposure_id"] == exposure_id), exposure_id)
        for exposure_id in yahoo_expected
        if exposure_id in investable_ids
    ]
    _yahoo_extra = len(yahoo_expected) - len(_yahoo_named)
    yahoo_labels = ", ".join(_yahoo_named)
    if _yahoo_extra:
        yahoo_labels += f" + {_yahoo_extra} relative-strength benchmarks"
    southbound_rows = int(len(southbound)) if southbound is not None and not southbound.empty else 0
    if southbound_rows and "trade_date" in southbound.columns:
        southbound_latest = str(pd.to_datetime(southbound["trade_date"], errors="coerce").max().date())
    else:
        southbound_latest = "—"

    latest_by_exposure = {}
    if not technicals.empty and {"exposure_id", "date"}.issubset(technicals.columns):
        latest_by_exposure = {
            str(row["exposure_id"]): row["date"]
            for row in technicals.to_dict("records")
        }
    daily_close_by_region = classify_daily_groups(
        latest_by_exposure,
        EXPOSURES,
        group_key="region",
    )
    daily_close_by_source = classify_daily_groups(
        latest_by_exposure,
        EXPOSURES,
        group_key="price_source",
    )
    daily_freshness = classify_daily_observation(data_as_of, observation_type="daily_close")
    southbound_freshness = classify_daily_observation(
        southbound_latest if southbound_latest != "—" else None,
        observation_type="published_data",
    )

    overall_healthy = (
        actual_exposures >= expected_count
        and spot_status == "Healthy"
        and sp500_ok
        and run_consistent
        and all(
            record.get("status") not in BLOCKING_FRESHNESS_STATUSES
            for group_records in (daily_close_by_region, daily_close_by_source)
            for record in group_records.values()
        )
    )

    source_health_rows = _source_health_rows(
        ProviderDelivery(
            spot_status=spot_status,
            spot_notes=spot_notes,
            spot_latest=spot_latest,
            spot_observed=spot_observed,
            csindex_count=int(csindex_count),
            csindex_expected=len(csindex_ids),
            csindex_rows=csindex_rows,
            csindex_latest=csindex_latest,
            sina_hk_count=int(sina_hk_count),
            sina_hk_expected=len(sina_hk_ids),
            sina_hk_rows=sina_hk_rows,
            sina_hk_latest=sina_hk_latest,
            sina_status=sina_status,
            sina_actual_count=int(sina_actual_count),
            sina_expected=len(sina_expected),
            sina_records=sina_records,
            sina_latest=sina_latest,
            yfinance_status=yfinance_status,
            yahoo_labels=yahoo_labels,
            yahoo_actual_count=int(yahoo_actual_count),
            yahoo_expected=len(yahoo_expected),
            yahoo_records=int(len(yahoo_rows)),
            yahoo_latest=yahoo_latest,
            southbound_rows=southbound_rows,
            southbound_latest=southbound_latest,
        )
    )
    datasets["source_health"] = _apply_daily_source_freshness(
        source_health_rows,
        daily_close_by_source,
        southbound_freshness,
    )
    datasets["freshness"] = [
        {"scope": "ETF spot", **spot_freshness},
        {"scope": "Index technicals", **daily_freshness},
        {"scope": "Southbound flow", **southbound_freshness},
        *(
            {"scope": f"Region · {group}", **record}
            for group, record in sorted(daily_close_by_region.items())
        ),
        *(
            {"scope": f"Source · {group}", **record}
            for group, record in sorted(daily_close_by_source.items())
        ),
    ]
    # --- Coverage regression check -------------------------------------
    # run_scope reports intent, not receipt: it is derived from the CLI
    # arguments, so a run that asked for everything and got a third of the
    # history is still "full", and load_latest selects it over the complete
    # earlier one purely because its run_id sorts later. That happened on
    # 2026-08-19: 5,541 rows across 7 exposures at 11:25, 3,416 rows at 12:28,
    # both labelled full, all three sources reported Healthy. Compare what
    # arrived against the previous run and say so when it shrank.
    history = load_lineage_history(NORMALIZED_DIR, "index_price_daily", scope="full", limit=2)
    current_cov = (history[0].get("coverage") if history else None) or {}
    previous_cov = (history[1].get("coverage") if len(history) > 1 else None) or {}
    coverage_notes = coverage_regressions(current_cov, previous_cov)
    current_rows = current_cov.get("rows_by_exposure") or {}
    coverage_ok = not coverage_notes
    if not coverage_ok:
        datasets["source_health"].append(
            {
                "source": "Index history coverage",
                "status": "Degraded",
                "latest_observation": current_cov.get("last_date") or "—",
                "records": int(sum(current_rows.values())),
                "notes": (
                    "Coverage shrank against the previous run: "
                    + "; ".join(coverage_notes)
                    + ". run_scope reports intent, not receipt -- check the ingestion start date."
                ),
            }
        )

    reported = current_cov.get("fetch_errors") or []
    # Entries marked as events are things that happened upstream and are worth
    # seeing -- a fund cutting its management fee -- not calls that failed.
    # Only real failures may degrade the run.
    fetch_errors = [err for err in reported if err.get("severity") != "event"]
    upstream_events = [err for err in reported if err.get("severity") == "event"]
    if fetch_errors:
        detail = "; ".join(
            f"{err.get('exposure_id') or err.get('dataset')}: {err.get('error')}"
            for err in fetch_errors[:6]
        )
        datasets["source_health"].append(
            {
                "source": "Upstream fetch errors",
                "status": "Degraded",
                "latest_observation": current_cov.get("last_date") or "—",
                "records": len(fetch_errors),
                "notes": f"{len(fetch_errors)} source call(s) failed this run: {detail}",
            }
        )
    if upstream_events:
        detail = "; ".join(
            f"{err.get('exposure_id') or err.get('dataset')}: {err.get('error')}"
            for err in upstream_events[:6]
        )
        datasets["source_health"].append(
            {
                "source": "Upstream events",
                "status": "Healthy",
                "latest_observation": current_cov.get("last_date") or "—",
                "records": len(upstream_events),
                "notes": f"{len(upstream_events)} upstream change(s) observed this run: {detail}",
            }
        )

    if stale_datasets:
        datasets["source_health"].append(
            {
                "source": "Pipeline run consistency",
                "status": "Degraded",
                "latest_observation": "—",
                "records": 0,
                "notes": f"Datasets from different pipeline runs: {', '.join(sorted(stale_datasets))}. Do not mix timelines.",
            }
        )
    sources = [
        {"id": "eastmoney_etf_spot", "label": "Eastmoney ETF snapshot (premium / spread / turnover / IOPV)", "href": "https://quote.eastmoney.com/center/gridlist.html#fund_etf", "query": {"engine": "akshare fund_etf_spot_em"}},
        {"id": "eastmoney_hsgt_southbound", "label": "Eastmoney aggregate southbound Stock Connect flow", "href": "https://data.eastmoney.com/hsgt/hsgtV2.html", "query": {"engine": "akshare stock_hsgt_hist_em(南向资金)"}},
        {"id": "sina_index_daily", "label": "Sina Finance index / ETF daily OHLCV", "href": "https://finance.sina.com.cn/", "query": {"engine": "akshare stock_zh_index_daily / fund_etf_hist_sina"}},
        {"id": "yfinance_spx", "label": "Yahoo Finance S&P 500 index", "href": "https://finance.yahoo.com/quote/%5EGSPC/", "query": {"engine": "yfinance ^GSPC"}},
    ]

    charts: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []

    # --- Market Leadership table (exposure technicals) ---
    tables.append(
        {
            "id": "market_leadership_table",
            "title": "Exposure Leadership",
            "dataset": "exposure_technicals",
            "columns": [
                {"field": "label", "label": "Exposure", "format": "text"},
                {"field": "rsi", "label": "RSI", "format": "number"},
                {"field": "ma20_pct", "label": "MA20 %", "format": "pct"},
                {"field": "ma60_pct", "label": "MA60 %", "format": "pct"},
                {"field": "drawdown_60d", "label": "DD60 %", "format": "pct"},
            ],
        }
    )
    blocks.append({"id": "market_leadership_block", "type": "table", "tableId": "market_leadership_table"})

    # --- Relative regime table ---
    tables.append(
        {
            "id": "relative_regime_table",
            "title": "Relative Regime",
            "dataset": "relative_regime",
            "columns": [
                {"field": "label", "label": "Spread", "format": "text"},
                {"field": "spread_20d_zscore", "label": "20D z", "format": "number"},
                {"field": "spread_5d_pct", "label": "5D %", "format": "pct"},
                {"field": "spread_20d_pct", "label": "20D %", "format": "pct"},
                {"field": "trend", "label": "Trend", "format": "text"},
            ],
        }
    )
    blocks.append({"id": "relative_regime_block", "type": "table", "tableId": "relative_regime_table"})

    # --- Sparkline data for the Overview pulse card (Small vs Large spread) ---
    charts.append(
        {
            "id": "small_large_regime_chart",
            "title": "Small vs Large relative strength",
            "dataset": "relative_regime",
            "encodings": {
                "x": {"field": "label", "type": "nominal", "label": "Spread"},
                "y": {"field": "spread_20d_zscore", "type": "quantitative", "label": "20D z"},
                "color": {"field": "label", "type": "nominal"},
            },
        }
    )

    # --- Wrapper selection table ---
    tables.append(
        {
            "id": "wrapper_selection_table",
            "title": "Wrapper Selection (Entry Status / Peer Rank / Hold Rank)",
            "dataset": "wrapper_metrics",
            "columns": [
                {"field": "ticker", "label": "Ticker", "format": "text"},
                {"field": "fund_name", "label": "Fund", "format": "text"},
                {"field": "premium_pct", "label": "Premium %", "format": "pct"},
                {"field": "relative_premium_pct", "label": "Rel Premium %", "format": "pct"},
                {"field": "entry_status", "label": "Entry Status", "format": "text"},
                {"field": "entry_cost_bp", "label": "Entry Cost (bp)", "format": "number"},
                {"field": "spread_bp", "label": "Spread (bp)", "format": "number"},
                {"field": "liquidity_score", "label": "Liquidity", "format": "number"},
                {"field": "aum_proxy", "label": "Market Cap Proxy (CNY)", "format": "number"},
                {"field": "peer_rank", "label": "Peer Rank", "format": "number"},
                {"field": "hold_rank", "label": "Hold Rank", "format": "number"},
            ],
        }
    )
    blocks.append({"id": "wrapper_selection_block", "type": "table", "tableId": "wrapper_selection_table"})

    overall_healthy = overall_healthy and coverage_ok and not fetch_errors

    snapshot_id = hashlib.sha1(json.dumps(datasets, sort_keys=True, default=str).encode()).hexdigest()[:16]
    artifact: dict[str, Any] = {
        "manifest": {"version": 1, "generatedAt": generated_at, "cards": [], "charts": charts, "tables": tables, "blocks": blocks},
        # Was the literal "ready" regardless of health: the real verdict lived
        # in the status dict below, which the artifact never carries, so a
        # consumer reading the artifact alone could not see a degraded build.
        # "partial" matches build_hk_population_migration_artifact.py, which
        # already makes this field conditional; the Streamlit surface reads the
        # source_health rows rather than this field, but a consumer that only
        # has the artifact should not be told everything is fine.
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready" if overall_healthy else "partial", "datasets": datasets},
        "sources": sources,
        "package_info": {
            "snapshotId": snapshot_id,
            "dataAsOf": data_as_of,
            "pipelineRunId": latest_run_id,
            "runConsistent": run_consistent,
            "freshness": {
                "quote": spot_freshness,
                "daily_close": daily_freshness,
                "daily_close_by_region": daily_close_by_region,
                "daily_close_by_source": daily_close_by_source,
                "southbound": southbound_freshness,
            },
        },
    }
    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": data_as_of,
        "overall_status": "Healthy" if overall_healthy else "Degraded",
        # Counted, not asserted: this was the literal 3 even when one of the
        # three was reporting Unavailable.
        "live_sources": sum(1 for row in datasets["source_health"] if row["status"] == "Healthy"),
        "planned_sources": 0,
        "sources": datasets["source_health"],
        "attachment_filename": f"market-monitor-dashboard-{now.date().isoformat()}.html",
    }
    return artifact, status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--status-output", type=Path, default=None, help="Optional status JSON (Cloudflare surface only; Streamlit does not use this)")
    args = parser.parse_args()
    artifact, status = build_artifact()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    # Streamlit loads per-language artifacts (english default + *-zh.json for
    # the Chinese UI) and crashes with FileNotFoundError when the zh file is
    # absent. The market-monitor tables are bilingual by id already, so emit
    # an identical -zh.json alongside the english artifact. The later
    # package-dashboard.mjs pass may produce a fancier localized copy; this
    # guarantees a usable artifact for the Streamlit surface either way.
    zh_path = args.output.with_name(args.output.name.replace("-artifact.json", "-artifact-zh.json"))
    zh_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if args.status_output:
        args.status_output.parent.mkdir(parents=True, exist_ok=True)
        args.status_output.write_text(json.dumps(status, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "artifact": str(args.output), "snapshot_id": status["snapshot_id"], "data_as_of": status["data_as_of"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
