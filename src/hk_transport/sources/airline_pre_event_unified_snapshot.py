"""Unified pre-event reconciliation snapshot for the 1H2026 airline event.

This is a read-only reconciliation layer, not a new forecast engine.  It puts
the locked v3 financial baseline, the frozen v4 H1 forecast, the consensus
sanity layer and the separate decision-evaluation layer on one row per
carrier.  Each source vintage is retained explicitly so the composite cannot
be mistaken for a single point-in-time model when its inputs were frozen on
different days.

The output is written once.  After the reports, actuals and market reactions
belong in the validation playbook/post-earnings tracker rather than in this
pre-event snapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


DATASET_ID = "airline_pre_event_unified_snapshot"
OUTPUT_PATH = NORMALIZED_DIR / f"{DATASET_ID}.csv"
V4_LIVE_PATH = NORMALIZED_DIR / "airline_earnings_model_v4_live_forecast.csv"
V3_BASELINE_PATH = NORMALIZED_DIR / "airline_pre_event_locked_baseline.csv"
DECISION_PATH = NORMALIZED_DIR / "airline_forecast_decision_eval.csv"
CONSENSUS_SANITY_PATH = NORMALIZED_DIR / "airline_consensus_reverse_v2_sanity.csv"

COMPANIES = [
    "Air China",
    "China Eastern Airlines",
    "China Southern Airlines",
    "Hainan Airlines Holdings",
    "Juneyao Airlines",
    "Spring Airlines",
]

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "ticker",
    "forecast_horizon",
    "forecast_type",
    "unified_model_version",
    "unified_snapshot_date",
    "lock_status",
    "v4_forecast_asof",
    "v4_data_cutoff",
    "v3_snapshot_date",
    "v3_lock_status",
    "v3_model_version",
    "v3_h1_ask_yoy_pct",
    "v3_h1_rpk_yoy_pct",
    "v3_h1_flat_yield_revenue_native_mn",
    "v3_fy2026_net_profit_usd_mn",
    "v3_consensus_fy2026_profit_usd_mn",
    "v3_model_vs_consensus_gap_pct",
    "v4_model_version",
    "v4_h1_revenue_native_mn",
    "v4_h1_eps_rmb",
    "v4_fy_eps_annualised_rmb",
    "v4_fy_eps_season_adjusted_rmb",
    "v4_consensus_eps_fy2026_rmb",
    "v4_surprise_x2_pct",
    "v4_surprise_season_adjusted_pct",
    "decision_model_version",
    "decision_h1_net_profit_native_mn",
    "decision_fy_net_profit_annualised_native_mn",
    "decision_consensus_net_profit_native_mn",
    "decision_beat_probability_pct",
    "decision_revenue_mae_pct",
    "decision_cost_mae_pct",
    "consensus_as_of_date",
    "consensus_age_days",
    "consensus_freshness",
    "one_off_flagged",
    "source_vintage_status",
    "source_note",
    "retrieved_at",
]


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _row(frame: pd.DataFrame, **criteria: object) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=object)
    mask = pd.Series(True, index=frame.index)
    for column, value in criteria.items():
        if column not in frame.columns:
            return pd.Series(dtype=object)
        mask &= frame[column].eq(value)
    rows = frame.loc[mask]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _latest_v4_snapshot() -> tuple[pd.DataFrame, str]:
    paths = sorted((NORMALIZED_DIR / "snapshots").glob("airline_v4_pre_event_*.csv"))
    if not paths:
        return pd.DataFrame(), "no_frozen_v4_snapshot"
    path = paths[-1]
    return _read(path), f"frozen_v4_snapshot:{path.name}"


def _vintage_status(v3: pd.Series, v4: pd.Series) -> str:
    v3_date = str(v3.get("snapshot_date", ""))
    v4_asof = str(v4.get("forecast_asof", ""))
    if v3_date and v4_asof and v3_date == v4_asof:
        return "source_vintages_aligned"
    if v3_date or v4_asof:
        return "mixed_source_vintages_explicit"
    return "source_vintage_missing"


def build_airline_pre_event_unified_snapshot(
    *,
    overwrite: bool = False,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build the locked composite view without changing any forecast layer."""
    if OUTPUT_PATH.exists() and not overwrite:
        return pd.read_csv(OUTPUT_PATH)

    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    v4, v4_source = _latest_v4_snapshot()
    if v4.empty:
        v4 = _read(V4_LIVE_PATH)
        v4_source = "live_v4_fallback_snapshot_not_available"
    v3 = _read(V3_BASELINE_PATH)
    decision = _read(DECISION_PATH)
    consensus = _read(CONSENSUS_SANITY_PATH)

    if v4.empty or v3.empty:
        result = pd.DataFrame(columns=OUTPUT_COLUMNS)
        result.to_csv(OUTPUT_PATH, index=False)
        return result

    forecast_asof = str(v4.get("forecast_asof", pd.Series(dtype=object)).dropna().iloc[0]) if "forecast_asof" in v4 and v4["forecast_asof"].notna().any() else None
    data_cutoff = str(v4.get("data_cutoff", pd.Series(dtype=object)).dropna().iloc[0]) if "data_cutoff" in v4 and v4["data_cutoff"].notna().any() else None
    unified_date = max(
        [date for date in [forecast_asof, *v3.get("snapshot_date", pd.Series(dtype=object)).dropna().astype(str).tolist()] if date]
    ) if (forecast_asof or "snapshot_date" in v3) else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    rows: list[dict[str, Any]] = []
    for company in COMPANIES:
        v4_row = _row(v4, company=company)
        v3_row = _row(v3, company=company)
        decision_row = _row(decision, company=company)
        consensus_row = _row(consensus, company=company)
        if v4_row.empty and v3_row.empty:
            continue
        v3_snapshot_date = str(v3_row.get("snapshot_date", "")) if not v3_row.empty else None
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "ticker": v4_row.get("ticker", v3_row.get("ticker", "")),
                "forecast_horizon": v4_row.get("forecast_horizon", "H1_2026"),
                "forecast_type": "pre_event_reconciliation",
                "unified_model_version": "v3_baseline_plus_v4_live_plus_decision_eval_v1",
                "unified_snapshot_date": unified_date,
                "lock_status": "locked_composite_read_only",
                "v4_forecast_asof": v4_row.get("forecast_asof"),
                "v4_data_cutoff": v4_row.get("data_cutoff"),
                "v3_snapshot_date": v3_snapshot_date,
                "v3_lock_status": v3_row.get("lock_status") if not v3_row.empty else None,
                "v3_model_version": "v3_base_financial_bridge",
                "v3_h1_ask_yoy_pct": _num(v3_row.get("h1_2026_ask_yoy_pct")),
                "v3_h1_rpk_yoy_pct": _num(v3_row.get("h1_2026_rpk_yoy_pct")),
                "v3_h1_flat_yield_revenue_native_mn": _num(v3_row.get("h1_2026_flat_yield_revenue_native_mn")),
                "v3_fy2026_net_profit_usd_mn": _num(v3_row.get("v3_base_fy2026_net_profit_usd_mn")),
                "v3_consensus_fy2026_profit_usd_mn": _num(v3_row.get("consensus_fy2026_profit_usd_mn")),
                "v3_model_vs_consensus_gap_pct": _num(v3_row.get("model_vs_consensus_gap_pct")),
                "v4_model_version": v4_row.get("model_version"),
                "v4_h1_revenue_native_mn": _num(v4_row.get("revenue_overlay_native_mn")),
                "v4_h1_eps_rmb": _num(v4_row.get("eps_overlay_rmb")),
                "v4_fy_eps_annualised_rmb": _num(v4_row.get("eps_v4_fy_annualised_rmb")),
                "v4_fy_eps_season_adjusted_rmb": _num(consensus_row.get("v4_fy_eps_season_adj_rmb")),
                "v4_consensus_eps_fy2026_rmb": _num(v4_row.get("consensus_eps_fy2026_rmb")),
                "v4_surprise_x2_pct": _num(v4_row.get("surprise_v4_vs_consensus_pct")),
                "v4_surprise_season_adjusted_pct": _num(consensus_row.get("surprise_vs_consensus_season_adj_pct")),
                "decision_model_version": "walk_forward_integrated_mc_v1",
                "decision_h1_net_profit_native_mn": _num(decision_row.get("model_net_profit_native_mn")),
                "decision_fy_net_profit_annualised_native_mn": _num(decision_row.get("model_net_profit_annualised_native_mn")),
                "decision_consensus_net_profit_native_mn": _num(decision_row.get("consensus_net_profit_native_mn")),
                "decision_beat_probability_pct": _num(decision_row.get("beat_probability_pct")),
                "decision_revenue_mae_pct": _num(decision_row.get("revenue_mae_pct")),
                "decision_cost_mae_pct": _num(decision_row.get("cost_mae_pct")),
                "consensus_as_of_date": consensus_row.get("consensus_as_of_date"),
                "consensus_age_days": _num(consensus_row.get("consensus_age_days")),
                "consensus_freshness": consensus_row.get("consensus_freshness"),
                "one_off_flagged": consensus_row.get("one_off_flagged"),
                "source_vintage_status": _vintage_status(v3_row, v4_row),
                "source_note": (
                    "Locked pre-event reconciliation only; it does not create a new forecast. "
                    f"v4 source={v4_source}; v3, v4 and decision layers remain separately modelled. "
                    "Actual interim results, revisions and T+1/T+5 returns belong in the validation tracker."
                ),
                "retrieved_at": retrieved,
            }
        )

    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS).sort_values("company").reset_index(drop=True)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "build_airline_pre_event_unified_snapshot",
    "source_path",
]
