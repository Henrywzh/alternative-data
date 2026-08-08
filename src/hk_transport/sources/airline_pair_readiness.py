"""Non-directional readiness gate for airline pair research."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


BRIDGE_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
REVISION_PATH = NORMALIZED_DIR / "airline_revision_coverage.csv"
RISK_PATH = NORMALIZED_DIR / "airline_market_risk_metrics.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_readiness.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "snapshot_date",
    "latest_financial_period", "latest_report_announcement_date",
    "formal_report_status", "formal_report_scheduled_date", "latest_event_type",
    "revision_evidence_band", "has_official_latest_financial_actual",
    "unified_consensus_event_count", "unified_estimate_revision_count",
    "unified_rating_event_count", "unified_up_revision_count",
    "unified_down_revision_count", "unified_latest_event_date",
    "unified_latest_estimate_revision_date",
    "has_h1_demand_trend", "has_fuel_cost_driver", "has_market_expectation",
    "has_revision_evidence", "has_catalyst_date", "profit_base_stable",
    "market_cap_to_consensus_revenue_usd", "fy2026_consensus_net_margin_pct",
    "has_market_risk_metrics", "beta_to_benchmark", "annualized_volatility_pct",
    "max_drawdown_pct", "median_daily_turnover_usd_mn_60d", "borrow_data_available",
    "risk_caveat",
    "pair_readiness_status", "blocking_reason", "source_quality", "source_note",
    "retrieved_at",
]


def _present(row: pd.Series, *columns: str) -> bool:
    return all(column in row.index and pd.notna(row[column]) for column in columns)


def _company_rows(bridge: pd.DataFrame) -> pd.DataFrame:
    cathay = bridge.loc[bridge["company"].eq("Cathay Pacific")]
    mainland = bridge.loc[bridge["market"].eq("CN_A")]
    return pd.concat([cathay, mainland], ignore_index=True).drop_duplicates("company")


def build_airline_pair_readiness(
    *,
    bridge: pd.DataFrame | None = None,
    revision_coverage: pd.DataFrame | None = None,
    risk_metrics: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    revision_coverage = revision_coverage if revision_coverage is not None else pd.read_csv(REVISION_PATH)
    risk_metrics = risk_metrics if risk_metrics is not None else pd.read_csv(RISK_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for _, row in _company_rows(bridge).iterrows():
        company = str(row["company"])
        revision = revision_coverage.loc[revision_coverage["company"].eq(company)]
        revision_row = revision.iloc[0] if not revision.empty else pd.Series(dtype=object)
        risk = risk_metrics.loc[risk_metrics["company"].eq(company)]
        risk_row = risk.iloc[0] if not risk.empty else pd.Series(dtype=object)
        has_actual = _present(row, "latest_financial_period", "latest_report_announcement_date")
        has_demand = _present(row, "h1_ask_yoy_pct", "h1_rpk_yoy_pct", "h1_passengers_yoy_pct", "h1_passenger_lf_change_pp")
        has_fuel = _present(row, "latest_report_fuel_cost_native_mn", "latest_report_fuel_cost_share_pct", "jet_fuel_spot_usd_per_gallon")
        has_market = _present(row, "market_cap_usd_mn", "fy2026_revenue_avg_usd_mn", "fy2026_net_profit_avg_usd_mn", "consensus_valuation_quality")
        revision_band = revision_row.get("revision_evidence_band")
        has_revision = revision_band in {
            "dated_estimate_revision_proxy", "dated_rating_events_only", "dated_public_report_markers"
        }
        has_catalyst = _present(row, "formal_report_status") and (
            pd.notna(row.get("formal_report_scheduled_date"))
            or pd.notna(row.get("formal_report_actual_disclosure_date"))
        )
        stable_profit = row.get("consensus_valuation_quality") == "profit_based_multiple_usable"
        has_risk = _present(risk_row, "beta_to_benchmark", "annualized_volatility_pct", "max_drawdown_pct", "median_daily_turnover_usd_mn_60d")
        borrow_available = (
            bool(risk_row.get("borrow_data_available"))
            if "borrow_data_available" in risk_row.index and pd.notna(risk_row.get("borrow_data_available"))
            else None
        )
        missing: list[str] = []
        if not has_actual:
            missing.append("latest_formal_actual")
        if not has_demand:
            missing.append("demand_trend")
        if not has_fuel:
            missing.append("fuel_driver")
        if not has_market:
            missing.append("market_expectation")
        if not has_revision:
            missing.append("estimate_revision_history")
        if not has_catalyst:
            missing.append("catalyst_date")
        if not stable_profit:
            missing.append("unstable_profit_base")

        if not all((has_actual, has_demand, has_fuel, has_market, has_catalyst)):
            status = "blocked_by_missing_core_data"
        elif row.get("formal_report_status") == "scheduled":
            status = "monitor_until_formal_1H2026"
        elif not has_revision or not stable_profit:
            status = "thesis_ready_with_revision_or_valuation_caveat"
        else:
            status = "thesis_ready_for_deep_dive"
        rows.append({
            "dataset_id": "airline_pair_readiness",
            "company": company,
            "ticker": row["market_ticker"],
            "market": row["market"],
            "snapshot_date": row["snapshot_date"],
            "latest_financial_period": row["latest_financial_period"],
            "latest_report_announcement_date": row["latest_report_announcement_date"],
            "formal_report_status": row["formal_report_status"],
            "formal_report_scheduled_date": row["formal_report_scheduled_date"],
            "latest_event_type": row["latest_event_type"],
            "revision_evidence_band": revision_band,
            "has_official_latest_financial_actual": has_actual,
            "unified_consensus_event_count": revision_row.get("unified_consensus_event_count"),
            "unified_estimate_revision_count": revision_row.get("unified_estimate_revision_count"),
            "unified_rating_event_count": revision_row.get("unified_rating_event_count"),
            "unified_up_revision_count": revision_row.get("unified_up_revision_count"),
            "unified_down_revision_count": revision_row.get("unified_down_revision_count"),
            "unified_latest_event_date": revision_row.get("unified_latest_event_date"),
            "unified_latest_estimate_revision_date": revision_row.get("unified_latest_estimate_revision_date"),
            "has_h1_demand_trend": has_demand,
            "has_fuel_cost_driver": has_fuel,
            "has_market_expectation": has_market,
            "has_revision_evidence": has_revision,
            "has_catalyst_date": has_catalyst,
            "profit_base_stable": stable_profit,
            "market_cap_to_consensus_revenue_usd": row["market_cap_to_consensus_revenue_usd"],
            "fy2026_consensus_net_margin_pct": row["fy2026_consensus_net_margin_pct"],
            "has_market_risk_metrics": has_risk,
            "beta_to_benchmark": risk_row.get("beta_to_benchmark"),
            "annualized_volatility_pct": risk_row.get("annualized_volatility_pct"),
            "max_drawdown_pct": risk_row.get("max_drawdown_pct"),
            "median_daily_turnover_usd_mn_60d": risk_row.get("median_daily_turnover_usd_mn_60d"),
            "borrow_data_available": borrow_available,
            "risk_caveat": "borrow_data_unavailable" if borrow_available is False else None,
            "pair_readiness_status": status,
            "blocking_reason": ";".join(missing) if missing else None,
            "source_quality": "derived_readiness_gate",
            "source_note": (
                "Readiness is a data-availability gate, not a directional trade recommendation. "
                "Revenue multiple remains usable even when profit base is unstable, but the latter is flagged separately."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_pair_readiness() -> pd.DataFrame:
    result = build_airline_pair_readiness()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
