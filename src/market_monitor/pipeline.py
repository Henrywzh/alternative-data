"""Run the daily market_monitor pipeline.

Flow:
    raw observations (immutable) -> normalized time series -> derived signals
         -> dashboard artifact -> daily Gmail report
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .config import EXPOSURES, DERIVED_DIR, NORMALIZED_DIR, RAW_DIR
from .metadata import build_metadata_frame
from .ranking import rank_wrappers
from .relative_strength import build_relative_regime, compute_spread_metrics
from .sources import akshare_etf, yfinance
from .storage import load_latest_normalized, new_run_id, prune_runs, save_derived, save_normalized, save_raw
from .technicals import compute_technicals
from .wrapper import merge_premium


# How many immutable run snapshots to keep per dataset. Each one holds the
# full history, so this is a retention window on redundant copies, not on data.
RUN_RETENTION = 5


def _last_2y_start() -> str:
    return (date.today() - timedelta(days=730)).strftime("%Y%m%d")


def _iso_start() -> str:
    return (date.today() - timedelta(days=730)).strftime("%Y-%m-%d")


def _build_premium_history(meta: pd.DataFrame) -> pd.DataFrame:
    """Build a per-fund premium time series from historical raw etf_spot snapshots."""
    tracked = set(meta["ticker"].astype(str).str.split(".").str[0].str.zfill(6))
    spot_dir = RAW_DIR / "etf_spot"
    if not spot_dir.is_dir():
        return pd.DataFrame(columns=["date", "fund_id", "ticker", "premium_pct", "spread_bp"])

    import json as _json
    rows = []
    for run_dir in sorted(spot_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        parquet = run_dir / "etf_spot.parquet"
        lineage = run_dir / "lineage.json"
        if not parquet.exists() or not lineage.exists():
            continue
        try:
            lin = _json.loads(lineage.read_text(encoding="utf-8"))
            snapshot_date = str(lin.get("created_at", ""))[:10]
            if not snapshot_date:
                continue
            spot = pd.read_parquet(parquet)
            if spot.empty or "ticker" not in spot.columns:
                continue
            spot["ticker"] = spot["ticker"].astype(str).str.zfill(6)
            sub = spot[spot["ticker"].isin(tracked)]
            if sub.empty:
                continue
            for _, row in sub.iterrows():
                rows.append(
                    {
                        "date": snapshot_date,
                        "ticker": row["ticker"],
                        "premium_pct": pd.to_numeric(row.get("premium_pct"), errors="coerce"),
                        "spread_bp": pd.to_numeric(row.get("spread_bp"), errors="coerce"),
                        "market_price": pd.to_numeric(row.get("market_price"), errors="coerce"),
                    }
                )
        except Exception:
            continue

    if not rows:
        return pd.DataFrame(columns=["date", "fund_id", "ticker", "premium_pct", "spread_bp"])
    frame = pd.DataFrame(rows)
    fund_map = dict(
        zip(
            meta["ticker"].astype(str).str.split(".").str[0].str.zfill(6),
            meta["fund_id"],
        )
    )
    frame["fund_id"] = frame["ticker"].map(fund_map)
    frame = frame.drop_duplicates(subset=["date", "ticker"], keep="last")
    return frame.sort_values(["ticker", "date"]).reset_index(drop=True)


def fetch_all_raw(*, start_date: str | None = None, limit_exposures: tuple[str, ...] | None = None, etf_only: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Call the source layers; return raw frames keyed by dataset name."""
    start = start_date or _last_2y_start()
    raw: dict[str, Any] = {}
    # A source that fails used to be printed and nothing else, so an exposure
    # simply stopped appearing downstream with no record of why. Collected here
    # and carried into lineage, they turn "this exposure is missing" into "this
    # exposure is missing because Sina timed out".
    fetch_errors: list[dict[str, str]] = []
    raw["_fetch_errors"] = fetch_errors
    meta = build_metadata_frame()

    # --- index closes (S&P 500 via yfinance, others via akshare) ---
    index_frames: dict[str, pd.DataFrame] = {}
    for spec in EXPOSURES:
        exposure = spec["exposure_id"]
        if limit_exposures and exposure not in limit_exposures:
            continue
        idx = spec["index_id"]
        try:
            if exposure in ("sp500", "ndx"):
                # yfinance expects ISO dates; honour the caller's start_date
                # (EM format) by converting, defaulting to the 2y ISO start.
                if start_date and "-" not in start_date and len(start_date) >= 8:
                    us_start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
                else:
                    us_start = start_date or _iso_start()
                yf_symbol = "^GSPC" if exposure == "sp500" else "^NDX"
                frame = yfinance.fetch_daily(yf_symbol, start_date=us_start)
                if frame is not None and not frame.empty:
                    frame["index_id"] = idx
            else:
                frame = akshare_etf.fetch_index_daily(idx, start_date=start)
                if frame is not None and not frame.empty:
                    frame["index_id"] = idx
            if frame is not None and not frame.empty:
                index_frames[exposure] = frame
        except Exception as exc:  # noqa: BLE001
            print(f"  [market_monitor] index fetch failed {exposure} ({idx}): {exc}")
            fetch_errors.append(
                {"dataset": "index_close", "exposure_id": exposure, "index_id": str(idx),
                 "error": f"{type(exc).__name__}: {exc}"}
            )
    raw["index_close"] = pd.concat(index_frames.values(), ignore_index=True) if index_frames else pd.DataFrame()

    # --- ETF daily closes ---
    # Re-enabled: the per-index view now charts every ETF wrapper rebased to
    # 100 alongside the index, which requires wrapper price history.
    etf_frames: list[pd.DataFrame] = []
    for _, row in meta.iterrows():
        exposure = row["exposure_id"]
        if limit_exposures and exposure not in limit_exposures:
            continue
        if etf_only and row["ticker"] not in etf_only:
            continue
        try:
            frame = akshare_etf.fetch_etf_daily(row["ticker"], start_date=start)
            if frame is not None and not frame.empty:
                frame = frame.copy()
                frame["fund_id"] = row["fund_id"]
                frame["ticker"] = row["ticker"]
                frame["exposure_id"] = exposure
                etf_frames.append(frame)
        except Exception as exc:  # noqa: BLE001
            print(f"  [market_monitor] etf fetch failed {row['ticker']} ({row['fund_name']}): {exc}")
    raw["etf_close"] = pd.concat(etf_frames, ignore_index=True) if etf_frames else pd.DataFrame()

    # --- ETF spot / premium snapshot ---
    try:
        raw["etf_spot"] = akshare_etf.fetch_etf_spot()
    except Exception as exc:  # noqa: BLE001
        print(f"  [market_monitor] etf spot fetch failed: {exc}")
        raw["etf_spot"] = pd.DataFrame()
        fetch_errors.append({"dataset": "etf_spot", "error": f"{type(exc).__name__}: {exc}"})

    return raw


def run_pipeline(*, limit_exposures: tuple[str, ...] | None = None, etf_only: tuple[str, ...] | None = None, start_date: str | None = None, write: bool = True) -> dict[str, Any]:
    """Fetch raw, normalize, derive signals, and persist run snapshots."""
    raw = fetch_all_raw(start_date=start_date, limit_exposures=limit_exposures, etf_only=etf_only)
    meta = build_metadata_frame()
    results: dict[str, Any] = {}
    run_scope = "partial" if (limit_exposures or etf_only) else "full"
    shared_run_id = new_run_id()

    # Persist raw observations first so the raw -> normalized -> derived chain
    # is not missing its bottom layer on disk (PIT discipline). Note this layer
    # is local only: data/raw/* is gitignored, so a run reconstructed from the
    # repository starts at "normalized" and cannot re-derive from source grain.
    raw_write: dict[str, dict[str, str] | None] = {}
    if write:
        for dataset_name in ("index_close", "etf_close", "etf_spot"):  # not _fetch_errors
            raw_write[dataset_name] = save_raw(dataset_name, raw[dataset_name], metadata={"type": "raw", "run_scope": run_scope}, run_id=shared_run_id) if dataset_name in raw and not raw[dataset_name].empty else None
        results["_raw_run"] = raw_write

    # Normalized: index prices (close from OHLCV).
    index_close_rows = []
    for spec in EXPOSURES:
        exposure = spec["exposure_id"]
        if limit_exposures and exposure not in limit_exposures:
            continue
        sub = raw["index_close"]
        if sub.empty:
            continue
        rows = sub[sub["index_id"].eq(spec["index_id"])].copy()
        if rows.empty:
            continue
        rows["exposure_id"] = exposure
        rows["close"] = pd.to_numeric(rows["close"], errors="coerce")
        index_close_rows.append(rows[["date", "exposure_id", "index_id", "close", "open", "high", "low", "volume"]])
    normalized_index = pd.concat(index_close_rows, ignore_index=True) if index_close_rows else pd.DataFrame()
    results["index_price_daily"] = normalized_index

    # What this run actually received, recorded beside what it set out to get.
    # run_scope is derived from the CLI arguments, so it reports intent: a run
    # that asked for every exposure and got a third of the history is still
    # labelled "full", and load_latest happily selects it over a complete
    # earlier one. This block is what lets a consumer notice that.
    expected_exposures = [
        spec["exposure_id"]
        for spec in EXPOSURES
        if not limit_exposures or spec["exposure_id"] in limit_exposures
    ]
    if normalized_index.empty:
        rows_by_exposure: dict[str, int] = {}
        first_date = last_date = None
    else:
        rows_by_exposure = {
            str(k): int(v) for k, v in normalized_index.groupby("exposure_id").size().items()
        }
        first_date = str(normalized_index["date"].min())
        last_date = str(normalized_index["date"].max())
    coverage = {
        "expected_exposures": expected_exposures,
        "observed_exposures": sorted(rows_by_exposure),
        "missing_exposures": sorted(set(expected_exposures) - set(rows_by_exposure)),
        "rows_by_exposure": rows_by_exposure,
        "first_date": first_date,
        "last_date": last_date,
        "requested_start_date": start_date,
        "fetch_errors": raw.get("_fetch_errors") or [],
    }
    results["_coverage"] = coverage

    # Normalized: ETF prices.
    normalized_etf = raw["etf_close"].copy() if not raw["etf_close"].empty else pd.DataFrame()
    results["etf_price_daily"] = normalized_etf

    # Derived: per-exposure technical snapshot (latest row).
    tech_rows: list[dict[str, Any]] = []
    for spec in EXPOSURES:
        exposure = spec["exposure_id"]
        if limit_exposures and exposure not in limit_exposures:
            continue
        sub = normalized_index[normalized_index["exposure_id"].eq(exposure)] if not normalized_index.empty else pd.DataFrame()
        if sub.empty or "close" not in sub.columns:
            continue
        close = sub.sort_values("date")["close"]
        tech = compute_technicals(close)
        tech["exposure_id"] = exposure
        tech["label"] = spec["label"]
        tech["date"] = sub["date"].max()
        tech_rows.append(tech)
    results["exposure_technicals"] = pd.DataFrame(tech_rows)

    # Derived: relative regime.
    close_by_exposure: dict[str, pd.Series] = {}
    if not normalized_index.empty:
        for exposure, sub in normalized_index.groupby("exposure_id"):
            # Keep the monotonic date index; compute_spread_metrics aligns the
            # two legs by date (join=inner) so cross-market calendars
            # (e.g. CSI vs S&P 500) never misalign by position.
            ordered = sub.sort_values("date")
            close_by_exposure[exposure] = pd.Series(
                ordered["close"].to_numpy(),
                index=pd.to_datetime(ordered["date"]),
                name=exposure,
            )
    results["relative_regime"] = pd.DataFrame(build_relative_regime(close_by_exposure))

    # Derived: wrapper metrics + ranking.
    wrapper = merge_premium(raw.get("etf_spot", pd.DataFrame()), meta)
    # Guarantee the optional EM columns exist (they may be absent when the
    # spot endpoint is unavailable); missing values stay NaN on the dashboard.
    for optional in ("aum", "market_price", "iopv", "turnover", "premium_pct", "spread_bp"):
        if optional not in wrapper.columns:
            wrapper[optional] = float("nan")
    if "turnover" in wrapper.columns:
        wrapper["turnover"] = pd.to_numeric(wrapper["turnover"], errors="coerce")
    if "inception_date" in wrapper.columns:
        wrapper["fund_age_days"] = pd.to_datetime(date.today()) - pd.to_datetime(wrapper["inception_date"], errors="coerce")
        wrapper["fund_age_days"] = wrapper["fund_age_days"].dt.days
    ranked = rank_wrappers(wrapper)
    # cross-border caveat flag for the dashboard
    ranked["premium_caveat"] = ranked["is_cross_border"].map(
        lambda v: "cross-border wrapper; premium interpretation differs from domestic ETF" if v else ""
    )
    results["wrapper_metrics"] = ranked

    # Premium history from accumulated raw etf_spot snapshots.
    premium_history = _build_premium_history(meta)
    results["premium_history"] = premium_history

    if write:
        run_id = shared_run_id
        run_info: dict[str, Any] = {}
        run_info["index_price_daily"] = save_normalized("index_price_daily", normalized_index, metadata={"type": "normalized", "run_scope": run_scope, "coverage": coverage}, run_id=run_id) if not normalized_index.empty else None
        run_info["etf_price_daily"] = save_normalized("etf_price_daily", normalized_etf, metadata={"type": "normalized", "run_scope": run_scope}, run_id=run_id) if not normalized_etf.empty else None
        run_info["exposure_technicals"] = save_derived("exposure_technicals", results["exposure_technicals"], metadata={"type": "derived", "run_scope": run_scope}, run_id=run_id) if not results["exposure_technicals"].empty else None
        run_info["relative_regime"] = save_derived("relative_regime", results["relative_regime"], metadata={"type": "derived", "run_scope": run_scope}, run_id=run_id) if not results["relative_regime"].empty else None
        run_info["wrapper_metrics"] = save_derived("wrapper_metrics", ranked, metadata={"type": "derived", "run_scope": run_scope}, run_id=run_id) if not ranked.empty else None
        run_info["premium_history"] = save_derived("premium_history", premium_history, metadata={"type": "derived", "run_scope": run_scope}, run_id=run_id) if not premium_history.empty else None
        results["_run"] = run_info
        # Bounded retention. Every run writes the complete history rather than
        # a delta, so old snapshots are pure duplication; see prune_runs.
        pruned: dict[str, list[str]] = {}
        for root, datasets in ((NORMALIZED_DIR, ("index_price_daily", "etf_price_daily")),
                               (DERIVED_DIR, ("exposure_technicals", "relative_regime", "wrapper_metrics")),
                               (RAW_DIR, ("index_close", "etf_close", "etf_spot"))):
            for dataset_name in datasets:
                dropped = prune_runs(root, dataset_name, keep=RUN_RETENTION)
                if dropped:
                    pruned[dataset_name] = dropped
        results["_pruned"] = pruned
    return results
