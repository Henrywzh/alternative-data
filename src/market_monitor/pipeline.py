"""Run the daily market_monitor pipeline.

Flow:
    raw observations (immutable) -> normalized time series -> derived signals
         -> dashboard artifact -> daily Gmail report
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .config import EXPOSURES, DERIVED_DIR, NORMALIZED_DIR, RAW_DIR, investable_exposures
from .metadata import build_metadata_frame, reconcile_registry_names
from .ranking import rank_wrappers
from .relative_strength import (
    build_pair_history,
    build_pair_summary,
    build_relative_regime,
    compute_spread_metrics,
)
from .sources import akshare_etf, eastmoney_nav, yfinance
from .storage import (
    load_latest_derived,
    load_latest_normalized,
    new_run_id,
    prune_runs,
    save_derived,
    save_normalized,
    save_raw,
)
from .technicals import compute_technicals
from .wrapper import fill_premium_from_last_close, merge_premium


# How many immutable run snapshots to keep per dataset. Each one holds the
# full history, so this is a retention window on redundant copies, not on data.
RUN_RETENTION = 5

# yfinance ticker per exposure. Keyed off exposure_id rather than inlined in a
# conditional so a new US index is a one-line addition beside its price_source
# declaration instead of another branch to remember.
# yfinance symbols are declared on the exposure itself; this map is derived so
# that adding a US series means editing one place.
YFINANCE_SYMBOLS = {
    spec["exposure_id"]: spec.get("yf_symbol") or spec["index_id"]
    for spec in EXPOSURES
    if spec["price_source"] == "yfinance"
}

# Index history runs deeper than the ETF history on purpose. The relative
# regime z-scores measure a ratio against its own trailing year, so a two-year
# store yields only about one year of z-score -- the first year is spent
# filling the baseline. Five years gives the pair charts a z-score over their
# whole displayed window. Indices are a handful of thin series, so the extra
# depth is cheap; ETF prices stay at two years.
INDEX_HISTORY_DAYS = 1825
ETF_HISTORY_DAYS = 730


def _last_2y_start() -> str:
    return (date.today() - timedelta(days=ETF_HISTORY_DAYS)).strftime("%Y%m%d")


def _index_start() -> str:
    return (date.today() - timedelta(days=INDEX_HISTORY_DAYS)).strftime("%Y%m%d")


def _iso_start() -> str:
    return (date.today() - timedelta(days=INDEX_HISTORY_DAYS)).strftime("%Y-%m-%d")


PREMIUM_HISTORY_COLUMNS = ["date", "fund_id", "ticker", "premium_pct", "spread_bp", "market_price", "basis"]


def _premium_rows_from_raw_snapshots(tracked: set[str]) -> list[dict]:
    """Backfill from whatever local raw etf_spot snapshots happen to exist.

    Only ever a bootstrap: data/raw/ is gitignored, so a fresh checkout has
    none, and prune_runs keeps five. It is the accumulated derived snapshot
    below that carries the history.
    """
    spot_dir = RAW_DIR / "etf_spot"
    if not spot_dir.is_dir():
        return []
    rows: list[dict] = []
    for run_dir in sorted(spot_dir.iterdir()):
        parquet = run_dir / "etf_spot.parquet"
        lineage = run_dir / "lineage.json"
        if not run_dir.is_dir() or not parquet.exists() or not lineage.exists():
            continue
        try:
            snapshot_date = str(json.loads(lineage.read_text(encoding="utf-8")).get("created_at", ""))[:10]
            if not snapshot_date:
                continue
            spot = pd.read_parquet(parquet)
            if spot.empty or "ticker" not in spot.columns:
                continue
            spot = spot.copy()
            spot["ticker"] = spot["ticker"].astype(str).str.zfill(6)
            rows.extend(_premium_rows(spot[spot["ticker"].isin(tracked)], snapshot_date))
        except Exception as exc:  # noqa: BLE001 - a bad snapshot must not stop the run
            print(f"  [market_monitor] skipped raw spot snapshot {run_dir.name}: {exc}")
    return rows


def _premium_rows(spot: pd.DataFrame, observation_date: str) -> list[dict]:
    if spot is None or spot.empty or "ticker" not in spot.columns:
        return []
    frame = spot.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.zfill(6)
    return [
        {
            "date": observation_date,
            "ticker": str(row["ticker"]),
            "premium_pct": pd.to_numeric(row.get("premium_pct"), errors="coerce"),
            "spread_bp": pd.to_numeric(row.get("spread_bp"), errors="coerce"),
            "market_price": pd.to_numeric(row.get("market_price"), errors="coerce"),
        }
        for _, row in frame.iterrows()
    ]


# How far back a first run reconstructs premium from published NAV. Matches
# the price window, so the premium series and the price series cover the same
# ground instead of one silently ending earlier than the other.
NAV_BACKFILL_DAYS = 730
# Re-fetch a short tail on every run rather than only strictly-new dates: a
# fund can publish a late or corrected NAV for a day already stored, and an
# overlap picks the correction up.
NAV_REFRESH_TAIL_DAYS = 10


def _nav_premium_rows(
    meta: pd.DataFrame,
    prices: pd.DataFrame,
    previous: pd.DataFrame | None,
) -> list[dict]:
    """Premium reconstructed from published NAV, for every tracked wrapper.

    IOPV only ever yields today, so a snapshot-fed series grows one row per
    run and a fresh deployment has a flat line. Published NAV goes back years,
    so this recovers the whole history in one pass and then only tops up.
    """
    if prices is None or prices.empty or "fund_id" not in prices.columns:
        return []

    already: dict[str, str] = {}
    if previous is not None and not previous.empty and "basis" in previous.columns:
        nav_rows = previous[previous["basis"].eq("nav")]
        if not nav_rows.empty:
            already = nav_rows.groupby("ticker")["date"].max().astype(str).to_dict()

    default_start = (date.today() - timedelta(days=NAV_BACKFILL_DAYS)).strftime("%Y-%m-%d")
    end = date.today().strftime("%Y-%m-%d")
    session = requests.Session()

    rows: list[dict] = []
    for record in meta.to_dict("records"):
        fund_id = str(record["fund_id"]).zfill(6)
        stored = already.get(fund_id)
        if stored:
            start = (
                pd.Timestamp(stored) - pd.Timedelta(days=NAV_REFRESH_TAIL_DAYS)
            ).strftime("%Y-%m-%d")
        else:
            start = default_start
        try:
            nav = eastmoney_nav.fetch_nav_history(fund_id, start, end, session=session)
        except Exception as exc:  # noqa: BLE001 - one fund must not stop the run
            print(f"  [market_monitor] nav fetch failed {fund_id}: {exc}")
            continue
        fund_prices = prices[prices["fund_id"].astype(str).str.zfill(6).eq(fund_id)]
        premium = eastmoney_nav.premium_from_nav(fund_prices, nav)
        if premium.empty and not fund_prices.empty and not stored:
            # A fund that trades but returns no NAV at all is a fetch problem,
            # not an absence. Left silent it shows up as one fund with a flat
            # two-day line next to twenty-two with two years.
            print(f"  [market_monitor] no NAV history resolved for {fund_id}")
        for row in premium.to_dict("records"):
            rows.append(
                {
                    "date": row["date"],
                    "ticker": fund_id,
                    "premium_pct": row["premium_pct"],
                    "spread_bp": float("nan"),
                    "market_price": float("nan"),
                    "basis": "nav",
                }
            )
    return rows


def _build_premium_history(
    meta: pd.DataFrame,
    spot: pd.DataFrame,
    observation_date: str,
    prices: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Accumulate a per-fund premium series across runs.

    The history is carried by the derived snapshot itself: each run loads the
    previous one, appends today's observation, and writes the whole series back,
    the same way index_price_daily carries its own history. That is what makes
    it survive both the retention window and a fresh checkout.

    It was previously rebuilt from scratch out of ``data/raw/etf_spot`` on every
    run, which could not accumulate at all. data/raw is gitignored, so CI starts
    with none and writes exactly one; prune_runs then caps local runs at five.
    The shipped artifact carried a single observation per fund, on one date,
    behind a chart captioned as a growing history.
    """
    tracked = set(meta["ticker"].astype(str).str.split(".").str[0].str.zfill(6))
    fund_map = dict(
        zip(meta["ticker"].astype(str).str.split(".").str[0].str.zfill(6), meta["fund_id"])
    )

    previous = load_latest_derived("premium_history")
    rows = _premium_rows_from_raw_snapshots(tracked)
    rows.extend(row for row in _premium_rows(spot, observation_date) if row["ticker"] in tracked)
    for row in rows:
        row.setdefault("basis", "iopv")

    # NAV rows are appended after the IOPV rows so that, where both describe
    # the same day, the fund's own end-of-day valuation wins the de-duplication
    # below. IOPV still carries the days NAV has not published yet -- today,
    # and the extra session a QDII lags by.
    nav_rows = _nav_premium_rows(meta, prices, previous) if prices is not None else []
    rows.extend(row for row in nav_rows if row["ticker"] in tracked)

    frames = [frame for frame in (previous, pd.DataFrame(rows)) if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame(columns=PREMIUM_HISTORY_COLUMNS)
    history = pd.concat(frames, ignore_index=True)
    history = history[[c for c in PREMIUM_HISTORY_COLUMNS if c in history.columns]]
    history["ticker"] = history["ticker"].astype(str).str.zfill(6)
    if "basis" not in history.columns:
        history["basis"] = "iopv"
    history["basis"] = history["basis"].fillna("iopv")
    history["fund_id"] = history["ticker"].map(fund_map)
    # A fund that has left the tracked universe keeps its past observations out
    # of the series rather than sitting in it with a null fund_id.
    history = history[history["ticker"].isin(tracked)]
    # Today's reading supersedes an earlier one for the same day.
    history = history.drop_duplicates(subset=["date", "ticker"], keep="last")
    return history.sort_values(["ticker", "date"]).reset_index(drop=True)


def fetch_all_raw(*, start_date: str | None = None, limit_exposures: tuple[str, ...] | None = None, etf_only: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Call the source layers; return raw frames keyed by dataset name."""
    # Indices reach back five years for the z-score baseline; the ETF loop
    # below keeps its own two-year window.
    start = start_date or _index_start()
    etf_start = start_date or _last_2y_start()
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
            if spec["price_source"] == "yfinance":
                # yfinance expects ISO dates; honour the caller's start_date
                # (EM format) by converting, defaulting to the 2y ISO start.
                if start_date and "-" not in start_date and len(start_date) >= 8:
                    us_start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
                else:
                    us_start = start_date or _iso_start()
                yf_symbol = YFINANCE_SYMBOLS[exposure]
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
            frame = akshare_etf.fetch_etf_daily(row["ticker"], start_date=etf_start)
            if frame is not None and not frame.empty:
                frame = frame.copy()
                frame["fund_id"] = row["fund_id"]
                frame["ticker"] = row["ticker"]
                frame["exposure_id"] = exposure
                etf_frames.append(frame)
        except Exception as exc:  # noqa: BLE001
            print(f"  [market_monitor] etf fetch failed {row['ticker']} ({row['fund_name']}): {exc}")
            fetch_errors.append(
                {"dataset": "etf_close", "exposure_id": str(exposure), "ticker": str(row["ticker"]),
                 "error": f"{type(exc).__name__}: {exc}"}
            )
    raw["etf_close"] = pd.concat(etf_frames, ignore_index=True) if etf_frames else pd.DataFrame()

    # --- ETF spot / premium snapshot ---
    try:
        raw["etf_spot"] = akshare_etf.fetch_etf_spot()
    except Exception as exc:  # noqa: BLE001
        print(f"  [market_monitor] etf spot fetch failed: {exc}")
        raw["etf_spot"] = pd.DataFrame()
        fetch_errors.append({"dataset": "etf_spot", "error": f"{type(exc).__name__}: {exc}"})

    # --- Registry reconciliation ---
    # The wrapper universe is hand-maintained, so the only thing that had been
    # checking it against reality was someone looking at a chart. Compare it
    # to the venue's own fund names on every run and report a contradiction
    # the same way a failed fetch is reported, so it reaches Source Health.
    for problem in reconcile_registry_names(meta, raw["etf_spot"]):
        message = (
            f"registry says {problem['fund_id']} is {problem['registry_name']} "
            f"under {problem['exposure_id']}, exchange says {problem['exchange_name']}"
        )
        print(f"  [market_monitor] registry mismatch: {message}")
        fetch_errors.append(
            {
                "dataset": "etf_spot",
                "exposure_id": problem["exposure_id"],
                "ticker": problem["fund_id"],
                "error": f"RegistryMismatch: {message}",
            }
        )

    return raw


def run_pipeline(*, limit_exposures: tuple[str, ...] | None = None, etf_only: tuple[str, ...] | None = None, start_date: str | None = None, write: bool = True) -> dict[str, Any]:
    """Fetch raw, normalize, derive signals, and persist run snapshots."""
    raw = fetch_all_raw(start_date=start_date, limit_exposures=limit_exposures, etf_only=etf_only)
    meta = build_metadata_frame()
    results: dict[str, Any] = {}
    run_scope = "partial" if (limit_exposures or etf_only) else "full"
    as_of_date = date.today().isoformat()
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
    # Investable exposures only: a benchmark exists to be one leg of a ratio,
    # has no ETF wrapper behind it, and would show up on the ETF monitor as an
    # index you cannot buy.
    tech_rows: list[dict[str, Any]] = []
    for spec in investable_exposures():
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
    # The ratio behind each pair, not only today's z-score. A bar chart of one
    # number cannot say whether -0.3 is the end of a year-long slide or the
    # end of a bounce.
    pair_history = build_pair_history(close_by_exposure)
    results["relative_pair_history"] = pair_history
    results["relative_pairs"] = build_pair_summary(close_by_exposure, pair_history)

    # Derived: wrapper metrics + ranking.
    wrapper = merge_premium(raw.get("etf_spot", pd.DataFrame()), meta)
    # A fund the spot feed did not refresh today still has a last traded price
    # in our own series; use it rather than dropping the row to UNAVAILABLE.
    wrapper = fill_premium_from_last_close(wrapper, normalized_etf)
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

    # Premium history, accumulated across runs (see _build_premium_history).
    premium_history = _build_premium_history(
        meta, raw.get("etf_spot", pd.DataFrame()), as_of_date, prices=normalized_etf
    )
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
        run_info["relative_pairs"] = save_derived("relative_pairs", results["relative_pairs"], metadata={"type": "derived", "run_scope": run_scope}, run_id=run_id) if not results["relative_pairs"].empty else None
        run_info["relative_pair_history"] = save_derived("relative_pair_history", results["relative_pair_history"], metadata={"type": "derived", "run_scope": run_scope}, run_id=run_id) if not results["relative_pair_history"].empty else None
        results["_run"] = run_info
        # Bounded retention. Every run writes the complete history rather than
        # a delta, so old snapshots are pure duplication; see prune_runs.
        pruned: dict[str, list[str]] = {}
        for root, datasets in ((NORMALIZED_DIR, ("index_price_daily", "etf_price_daily")),
                               # premium_history was missing here, so the one
                               # dataset that carries a full 11k-row series
                               # kept every run it had ever written while the
                               # small ones were capped at five.
                               (DERIVED_DIR, ("exposure_technicals", "relative_regime", "wrapper_metrics",
                                              "premium_history", "relative_pairs", "relative_pair_history")),
                               (RAW_DIR, ("index_close", "etf_close", "etf_spot"))):
            for dataset_name in datasets:
                dropped = prune_runs(root, dataset_name, keep=RUN_RETENTION)
                if dropped:
                    pruned[dataset_name] = dropped
        results["_pruned"] = pruned
    return results
