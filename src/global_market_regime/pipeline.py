"""Daily pipeline for the global market-regime radar.

Flow:
    FRED + Atlanta MPT raw observations
        -> normalized daily panel
        -> derived threshold states
        -> optional Gmail on state change
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .config import (
    CFTC_DISAGG_CONTRACTS,
    CFTC_TFF_CONTRACTS,
    COT_STALE_AFTER_CALENDAR_DAYS,
    CONDITION_RULES,
    CROSS_ASSET_EXPOSURES,
    SECTOR_LEADERSHIP_BENCHMARK,
    SECTOR_LEADERSHIP_EXPOSURES,
    DERIVED_DIR,
    FOMC_STALE_AFTER_CALENDAR_DAYS,
    FRED_SERIES,
    FRESH_CONDITION_STATUSES,
    NORMALIZED_DIR,
    STALE_AFTER_CALENDAR_DAYS,
    STATE_SEVERITY,
)
from .cot import fetch_cot_panel, latest_cot_snapshot
from .prediction_markets import (
    classify_fomc_states,
    fetch_fomc_event,
    fetch_token_history,
    fomc_probability_history,
    parse_fomc_snapshot,
)
from .signals import build_indicator_states, latest_state_row, overall_state
from .sources import (
    fetch_atlanta_mpt,
    fetch_fred_observations,
    hike_probability_history,
    safe_error_message,
)
from .storage import new_run_id, prune_runs, save_derived, save_normalized, utc_now
from .treasury import build_treasury_curve_snapshots, build_treasury_yield_changes
from .sector_leadership import build_sector_leadership


def _iso(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return None
    return stamp.strftime("%Y-%m-%d")


def classify_freshness(latest_date: Any, *, now: datetime | None = None, stale_after: int | None = None) -> str:
    if latest_date is None or (isinstance(latest_date, float) and pd.isna(latest_date)):
        return "Unavailable"
    stamp = pd.Timestamp(latest_date)
    if pd.isna(stamp):
        return "Unavailable"
    today = (now or datetime.now(timezone.utc)).date()
    age = (today - stamp.date()).days
    if age < 0:
        return "Invalid"
    limit = STALE_AFTER_CALENDAR_DAYS if stale_after is None else stale_after
    if age > limit:
        return "Stale"
    if age == 0:
        return "Current session"
    if age <= 3:
        return "Last session"
    return "Recent"


def fresh_state_map(snapshot: pd.DataFrame) -> dict[str, str]:
    """Return only current, usable condition states for aggregate decisions."""
    if snapshot is None or snapshot.empty:
        return {}
    required = {"indicator_id", "state", "freshness"}
    if not required.issubset(snapshot.columns):
        return {}
    usable = snapshot[
        snapshot["freshness"].isin(FRESH_CONDITION_STATUSES)
        & snapshot["indicator_id"].isin(CONDITION_RULES)
        & snapshot["state"].notna()
        & snapshot["state"].isin(STATE_SEVERITY)
    ]
    return {
        str(row["indicator_id"]): str(row["state"])
        for row in usable.to_dict("records")
        if row.get("indicator_id")
    }


def _indicator_frame(fred: pd.DataFrame, indicator_id: str) -> pd.DataFrame:
    if fred is None or fred.empty or "indicator_id" not in fred.columns:
        return pd.DataFrame(columns=["date", "value"])
    subset = fred[fred["indicator_id"].eq(indicator_id)][["date", "value"]].copy()
    return subset


def build_condition_panel(states: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for indicator_id, history in states.items():
        if history is None or history.empty:
            continue
        frame = history.copy()
        frame["indicator_id"] = indicator_id
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        rows.append(frame)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True, sort=False)


def latest_condition_snapshot(states: dict[str, pd.DataFrame], *, now: datetime | None = None) -> pd.DataFrame:
    labels = {
        "brent": ("Brent crude", "布伦特原油"),
        "us10y": ("US 10-year yield", "美国10年期国债收益率"),
        "hike_prob": ("Near-term SOFR above target", "近端SOFR高于目标区间概率"),
        "fomc_hike": ("Next FOMC hike odds", "下次FOMC加息赔率"),
        "credit_vix": ("HY OAS + VIX sync stress", "高收益债利差与VIX同步压力"),
    }
    rows: list[dict[str, Any]] = []
    for indicator_id, history in states.items():
        latest = latest_state_row(history)
        label_en, label_zh = labels.get(indicator_id, (indicator_id, indicator_id))
        observation_date = latest.get("date") if latest else None
        rows.append(
            {
                "indicator_id": indicator_id,
                "label_en": label_en,
                "label_zh": label_zh,
                "state": (latest or {}).get("state") or "Unavailable",
                "value": (latest or {}).get("value"),
                "observation_date": observation_date,
                "freshness": classify_freshness(observation_date, now=now),
                "reference_start": _iso((latest or {}).get("reference_start")),
                "target_range": (latest or {}).get("target_range"),
                "cut_prob": (latest or {}).get("cut_prob"),
                "hold_prob": (latest or {}).get("hold_prob"),
                "hy_z": (latest or {}).get("hy_z"),
                "vix_z": (latest or {}).get("vix_z"),
                "consecutive_breach": (latest or {}).get("consecutive_breach"),
            }
        )
    return pd.DataFrame(rows)


def source_health_rows(
    *,
    fred: pd.DataFrame,
    mpt: pd.DataFrame,
    fred_errors: dict[str, str],
    mpt_error: str | None,
    now: datetime | None = None,
    hike: pd.DataFrame | None = None,
    cot: pd.DataFrame | None = None,
    cot_error: str | None = None,
    fomc: pd.DataFrame | None = None,
    fomc_error: str | None = None,
    cross_asset: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for spec in FRED_SERIES:
        subset = _indicator_frame(fred, spec["indicator_id"])
        latest = subset["date"].max() if not subset.empty else None
        error = fred_errors.get(spec["series_id"])
        if error:
            status = "Unavailable"
            notes = error
        elif subset.empty:
            status = "Unavailable"
            notes = "No observations returned."
        else:
            status = classify_freshness(latest, now=now)
            if status in {"Stale", "Invalid"}:
                status = "Degraded" if status == "Stale" else "Unavailable"
            else:
                status = "Healthy"
            notes = f"Daily {spec['label_en']} through {_iso(latest)}."
        rows.append(
            {
                "source": spec["source"],
                "series_id": spec["series_id"],
                "status": status,
                "latest_observation": _iso(latest) or "—",
                "records": int(len(subset)),
                "notes": notes,
            }
        )
    panel = hike if hike is not None and not hike.empty else mpt
    mpt_latest = panel["date"].max() if panel is not None and not panel.empty else None
    if mpt_error:
        mpt_status, mpt_notes, mpt_records = "Unavailable", mpt_error, 0
    elif panel is None or panel.empty:
        mpt_status, mpt_notes, mpt_records = "Unavailable", "Atlanta MPT returned no rows.", 0
    else:
        freshness = classify_freshness(mpt_latest, now=now)
        mpt_status = "Healthy" if freshness in FRESH_CONDITION_STATUSES else ("Degraded" if freshness == "Stale" else "Unavailable")
        mpt_notes = f"Nearest remaining 3-month SOFR window through {_iso(mpt_latest)}."
        mpt_records = int(len(panel))
    rows.append(
        {
            "source": "Atlanta Fed Market Probability Tracker",
            "series_id": "atlanta_mpt",
            "status": mpt_status,
            "latest_observation": _iso(mpt_latest) or "—",
            "records": mpt_records,
            "notes": mpt_notes,
        }
    )
    expected_contracts = {
        str(spec["contract_id"])
        for spec in (*CFTC_TFF_CONTRACTS, *CFTC_DISAGG_CONTRACTS)
    }
    cot_frame = cot.copy() if cot is not None else pd.DataFrame()
    if not cot_frame.empty and {"date", "contract_id"}.issubset(cot_frame.columns):
        cot_frame["date"] = pd.to_datetime(cot_frame["date"], errors="coerce")
        cot_frame = cot_frame.dropna(subset=["date", "contract_id"])
        cot_latest_by_contract = cot_frame.groupby("contract_id")["date"].max()
    else:
        cot_latest_by_contract = pd.Series(dtype="datetime64[ns]")
    observed_contracts = {
        str(contract_id) for contract_id in cot_latest_by_contract.index
    }
    cot_latest = (
        cot_latest_by_contract.max()
        if not cot_latest_by_contract.empty
        else None
    )
    if cot_error:
        cot_status, cot_notes, cot_records = "Unavailable", cot_error, 0
    elif cot is None or cot.empty:
        cot_status, cot_notes, cot_records = "Unavailable", "CFTC COT returned no rows.", 0
    else:
        stale_contracts = {
            str(contract_id)
            for contract_id, latest_date in cot_latest_by_contract.items()
            if classify_freshness(
                latest_date,
                now=now,
                stale_after=COT_STALE_AFTER_CALENDAR_DAYS,
            )
            not in FRESH_CONDITION_STATUSES
        }
        complete = expected_contracts <= observed_contracts
        cot_status = (
            "Healthy"
            if complete and not stale_contracts
            else "Degraded"
        )
        cot_notes = (
            "CFTC leveraged/managed-money net positions through "
            f"{_iso(cot_latest)}; "
            f"{len(observed_contracts & expected_contracts)}/"
            f"{len(expected_contracts)} registered contracts observed."
        )
        if stale_contracts:
            cot_notes += " Stale: " + ", ".join(sorted(stale_contracts)) + "."
        cot_records = int(len(observed_contracts))
    rows.append(
        {
            "source": "CFTC Commitments of Traders",
            "series_id": "cftc_cot",
            "status": cot_status,
            "latest_observation": _iso(cot_latest) or "—",
            "records": cot_records,
            "notes": cot_notes,
        }
    )
    fomc_latest = fomc["date"].max() if fomc is not None and not fomc.empty else None
    fomc_distribution_complete = bool(
        fomc is not None
        and not fomc.empty
        and "distribution_complete" in fomc.columns
        and fomc["distribution_complete"].fillna(False).astype(bool).all()
    )
    if fomc_error:
        fomc_status, fomc_notes, fomc_records = "Unavailable", fomc_error, 0
    elif fomc is None or fomc.empty:
        fomc_status, fomc_notes, fomc_records = "Unavailable", "Polymarket FOMC market returned no rows.", 0
    else:
        freshness = classify_freshness(fomc_latest, now=now, stale_after=FOMC_STALE_AFTER_CALENDAR_DAYS)
        if not fomc_distribution_complete:
            fomc_status = "Degraded"
            fomc_notes = (
                "Polymarket FOMC distribution is incomplete; "
                "no policy state should be inferred."
            )
        else:
            fomc_status = "Healthy" if freshness in FRESH_CONDITION_STATUSES else ("Degraded" if freshness == "Stale" else "Unavailable")
            fomc_notes = "Polymarket next-meeting hike/hold/cut prices; not CME FedWatch."
        fomc_records = int(len(fomc))
    rows.append(
        {
            "source": "Polymarket FOMC",
            "series_id": "polymarket_fomc",
            "status": fomc_status,
            "latest_observation": _iso(fomc_latest) or "—",
            "records": fomc_records,
            "notes": fomc_notes,
        }
    )
    expected_assets = {str(value) for value in CROSS_ASSET_EXPOSURES}
    asset_frame = cross_asset.copy() if cross_asset is not None else pd.DataFrame()
    if (
        asset_frame.empty
        or not {"date", "exposure_id", "close"}.issubset(asset_frame.columns)
    ):
        asset_status = "Unavailable"
        asset_latest = None
        observed_assets: set[str] = set()
        stale_assets: set[str] = set()
        asset_records = 0
    else:
        asset_frame["date"] = pd.to_datetime(asset_frame["date"], errors="coerce")
        asset_frame["close"] = pd.to_numeric(asset_frame["close"], errors="coerce")
        asset_frame = asset_frame.dropna(subset=["date", "exposure_id", "close"])
        latest_by_asset = asset_frame.groupby("exposure_id", sort=False)["date"].max()
        observed_assets = {str(value) for value in latest_by_asset.index}
        stale_assets = {
            str(exposure_id)
            for exposure_id, latest_date in latest_by_asset.items()
            if classify_freshness(latest_date, now=now)
            not in FRESH_CONDITION_STATUSES
        }
        asset_latest = latest_by_asset.max() if not latest_by_asset.empty else None
        asset_records = int(len(asset_frame))
        if not observed_assets:
            asset_status = "Unavailable"
        elif expected_assets <= observed_assets and not stale_assets:
            asset_status = "Healthy"
        else:
            asset_status = "Degraded"
    asset_notes = (
        "Existing market-monitor daily closes: "
        f"{len(observed_assets & expected_assets)}/{len(expected_assets)} "
        "expected exposures observed."
    )
    if stale_assets:
        asset_notes += " Stale: " + ", ".join(sorted(stale_assets)) + "."
    rows.append(
        {
            "source": "Asia Markets index monitor",
            "series_id": "market_monitor_prices",
            "status": asset_status,
            "latest_observation": _iso(asset_latest) or "—",
            "records": asset_records,
            "notes": asset_notes,
        }
    )
    return pd.DataFrame(rows)


def load_cross_asset_prices() -> pd.DataFrame:
    """Reuse the existing market-monitor index history; never refetch a second copy."""
    try:
        from market_monitor.config import NORMALIZED_DIR as MARKET_NORMALIZED
        from market_monitor.storage import load_latest_with_lineage
    except Exception:
        return pd.DataFrame()
    try:
        prices, lineage = load_latest_with_lineage(
            MARKET_NORMALIZED,
            "index_price_daily",
            scope="full",
        )
    except Exception:
        return pd.DataFrame()
    if prices.empty or "exposure_id" not in prices.columns:
        return pd.DataFrame()
    wanted = set(CROSS_ASSET_EXPOSURES) | set(SECTOR_LEADERSHIP_EXPOSURES) | {SECTOR_LEADERSHIP_BENCHMARK}
    keep = prices[prices["exposure_id"].isin(wanted)].copy()
    keep["date"] = pd.to_datetime(keep["date"], errors="coerce")
    keep["close"] = pd.to_numeric(keep["close"], errors="coerce")
    result = (
        keep.dropna(subset=["date", "close"])
        .loc[lambda frame: frame["close"].gt(0)]
        .sort_values(["exposure_id", "date"], kind="mergesort")
        .drop_duplicates(["exposure_id", "date"], keep="last")
        .reset_index(drop=True)
    )
    if lineage:
        result.attrs["upstream_market_monitor_run_id"] = lineage.get("run_id")
        result.attrs["upstream_market_monitor_run_scope"] = lineage.get(
            "run_scope"
        )
    return result


def run_pipeline(
    *,
    write: bool = True,
    fred_frame: pd.DataFrame | None = None,
    mpt_frame: pd.DataFrame | None = None,
    cot_frame: pd.DataFrame | None = None,
    fomc_history_frame: pd.DataFrame | None = None,
    skip_external: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    run_id = new_run_id()
    retrieved_at = utc_now()
    fred_errors: dict[str, str] = {}
    mpt_error: str | None = None
    if fred_frame is None:
        fred_frame, fred_errors = fetch_fred_observations()
    else:
        fred_frame = fred_frame.copy()

    if mpt_frame is None:
        try:
            mpt_frame, _ = fetch_atlanta_mpt()
        except Exception as exc:
            mpt_error = safe_error_message(exc)
            mpt_frame = pd.DataFrame()
    else:
        mpt_frame = mpt_frame.copy()

    hike = hike_probability_history(mpt_frame)
    hike_input = hike.copy() if not hike.empty else pd.DataFrame(columns=["date", "value", "window_key"])
    states = build_indicator_states(
        brent=_indicator_frame(fred_frame, "brent"),
        us10y=_indicator_frame(fred_frame, "us10y"),
        hike=hike_input,
        hy_oas=_indicator_frame(fred_frame, "hy_oas"),
        vix=_indicator_frame(fred_frame, "vix"),
    )
    cot_error: str | None = None
    fomc_error: str | None = None
    cot_history = cot_frame.copy() if cot_frame is not None else pd.DataFrame()
    fomc_history = fomc_history_frame.copy() if fomc_history_frame is not None else pd.DataFrame()
    fomc_snapshot: dict[str, Any] | None = None
    if cot_frame is None and not skip_external:
        try:
            cot_history = fetch_cot_panel()
        except Exception as exc:
            cot_error = safe_error_message(exc)
            cot_history = pd.DataFrame()
    if fomc_history_frame is None and not skip_external:
        try:
            event = fetch_fomc_event()
            if event is None:
                fomc_error = "No open Fed Decision event found."
            else:
                fomc_snapshot = parse_fomc_snapshot(event)
                if not fomc_snapshot.get("distribution_complete"):
                    fomc_error = (
                        "Polymarket FOMC distribution is incomplete; "
                        "no policy state was derived."
                    )
                else:
                    token_histories = {
                        key: (
                            fetch_token_history(
                                str(fomc_snapshot.get(token_field) or "")
                            )
                            if fomc_snapshot.get(token_field)
                            else pd.DataFrame()
                        )
                        for key, token_field in {
                            "hold": "token_hold",
                            "hike_25": "token_hike_25",
                            "hike_50": "token_hike_50",
                            "cut_25": "token_cut_25",
                            "cut_50": "token_cut_50",
                        }.items()
                    }
                    fomc_history = fomc_probability_history(
                        fomc_snapshot,
                        token_histories["hold"],
                        token_histories["hike_25"],
                        hike50_history=token_histories["hike_50"],
                        cut25_history=token_histories["cut_25"],
                        cut50_history=token_histories["cut_50"],
                    )
                    if fomc_history.empty:
                        fomc_error = (
                            "Polymarket FOMC token history is incomplete; "
                            "no policy state was derived."
                        )
        except Exception as exc:
            fomc_error = safe_error_message(exc)
            fomc_history = pd.DataFrame()
    if not fomc_history.empty:
        states["fomc_hike"] = classify_fomc_states(fomc_history)

    snapshot = latest_condition_snapshot(states, now=now)
    if fomc_snapshot and not snapshot.empty:
        mask = snapshot["indicator_id"].eq("fomc_hike")
        if mask.any():
            snapshot.loc[mask, "meeting_date"] = fomc_snapshot.get("meeting_date")
            snapshot.loc[mask, "cut_prob"] = fomc_snapshot.get("cut_prob")
            snapshot.loc[mask, "hold_prob"] = fomc_snapshot.get("hold_prob")
            snapshot.loc[mask, "event_slug"] = fomc_snapshot.get("slug")
    panel = build_condition_panel(states)
    cross_asset = load_cross_asset_prices()
    sector_leadership = build_sector_leadership(cross_asset)
    curve_snapshots = build_treasury_curve_snapshots(fred_frame)
    yield_changes = build_treasury_yield_changes(fred_frame)
    health = source_health_rows(
        fred=fred_frame,
        mpt=mpt_frame,
        fred_errors=fred_errors,
        mpt_error=mpt_error,
        now=now,
        hike=hike,
        cot=cot_history,
        cot_error=cot_error,
        fomc=fomc_history,
        fomc_error=fomc_error,
        cross_asset=cross_asset,
    )
    current_states = fresh_state_map(snapshot)
    expected_conditions = set(CONDITION_RULES)
    observed_conditions = (
        set(snapshot["indicator_id"].dropna().astype(str))
        if not snapshot.empty and "indicator_id" in snapshot.columns
        else set()
    )
    all_expected_rows_fresh = bool(
        expected_conditions <= observed_conditions
        and snapshot["state"].isin(STATE_SEVERITY).all()
        and snapshot["freshness"].isin(FRESH_CONDITION_STATUSES).all()
    )
    results: dict[str, Any] = {
        "run_id": run_id,
        "retrieved_at": retrieved_at,
        "fred_observations": fred_frame,
        "atlanta_mpt": mpt_frame,
        "hike_probability": hike,
        "cot_history": cot_history,
        "cot_latest": latest_cot_snapshot(cot_history),
        "fomc_history": fomc_history,
        "fomc_snapshot": fomc_snapshot,
        "condition_states": panel,
        "latest_conditions": snapshot,
        "source_health": health,
        "cross_asset_prices": cross_asset,
        "treasury_curve_snapshots": curve_snapshots,
        "treasury_yield_changes": yield_changes,
        "sector_leadership": sector_leadership,
        "overall_state": overall_state(current_states) if current_states else "Unavailable",
        "fred_errors": fred_errors,
        "mpt_error": mpt_error,
        "cot_error": cot_error,
        "fomc_error": fomc_error,
        "freshness_ok": bool(
            all_expected_rows_fresh
            and health["status"].ne("Unavailable").any()
        ),
    }
    if write:
        metadata = {"run_scope": "full", "retrieved_at": retrieved_at}
        if not fred_frame.empty:
            save_normalized("fred_observations", fred_frame, metadata=metadata, run_id=run_id)
            prune_runs(NORMALIZED_DIR, "fred_observations")
        # The full Atlanta workbook is fetched in memory only; no raw copy is
        # persisted. Git keeps just the nearest-window daily probability panel,
        # so reproducibility requires re-fetching the workbook.
        if not hike.empty:
            save_normalized("hike_probability", hike, metadata=metadata, run_id=run_id)
            prune_runs(NORMALIZED_DIR, "hike_probability")
        if not cot_history.empty:
            save_normalized("cot_history", cot_history, metadata=metadata, run_id=run_id)
            prune_runs(NORMALIZED_DIR, "cot_history")
            latest_cot = latest_cot_snapshot(cot_history)
            if not latest_cot.empty:
                save_derived("cot_latest", latest_cot, metadata=metadata, run_id=run_id)
                prune_runs(DERIVED_DIR, "cot_latest")
        if not fomc_history.empty:
            save_normalized("fomc_history", fomc_history, metadata=metadata, run_id=run_id)
            prune_runs(NORMALIZED_DIR, "fomc_history")
        if not panel.empty:
            save_derived("condition_states", panel, metadata=metadata, run_id=run_id)
            prune_runs(DERIVED_DIR, "condition_states")
        if not snapshot.empty:
            save_derived("latest_conditions", snapshot, metadata=metadata, run_id=run_id)
            prune_runs(DERIVED_DIR, "latest_conditions")
        if not health.empty:
            save_derived("source_health", health, metadata=metadata, run_id=run_id)
            prune_runs(DERIVED_DIR, "source_health")
        if not sector_leadership.empty:
            save_derived(
                "sector_leadership",
                sector_leadership,
                metadata=metadata,
                run_id=run_id,
            )
            prune_runs(DERIVED_DIR, "sector_leadership")
        if not curve_snapshots.empty:
            save_derived(
                "treasury_curve_snapshots",
                curve_snapshots,
                metadata=metadata,
                run_id=run_id,
            )
            prune_runs(DERIVED_DIR, "treasury_curve_snapshots")
        if not yield_changes.empty:
            save_derived(
                "treasury_yield_changes",
                yield_changes,
                metadata=metadata,
                run_id=run_id,
            )
            prune_runs(DERIVED_DIR, "treasury_yield_changes")
        if not cross_asset.empty:
            cross_asset_metadata = {
                **metadata,
                "upstream_market_monitor_run_id": cross_asset.attrs.get(
                    "upstream_market_monitor_run_id"
                ),
                "upstream_market_monitor_run_scope": cross_asset.attrs.get(
                    "upstream_market_monitor_run_scope"
                ),
            }
            save_derived(
                "cross_asset_prices",
                cross_asset,
                metadata=cross_asset_metadata,
                run_id=run_id,
            )
            prune_runs(DERIVED_DIR, "cross_asset_prices")
    return results
