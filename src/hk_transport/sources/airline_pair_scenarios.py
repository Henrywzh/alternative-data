"""Transparent FY2026 scenario inputs for airline pair thesis work.

The scenarios stress the current A-share detailed expectation snapshot. They
are not independent forecasts: revenue is set at consensus +/- 5% and net
margin at implied consensus margin +/- 2 percentage points. The assumptions
are explicit so the analyst can replace them after primary H1 results.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR


BRIDGE_PATH = NORMALIZED_DIR / "airline_historical_earnings_bridge.csv"
DETAILED_CONSENSUS_PATH = NORMALIZED_DIR / "airline_consensus_ashare_detailed.csv"
PAIR_HISTORICAL_PATH = NORMALIZED_DIR / "airline_pair_historical_bridge.csv"
PAIR_MATRIX_PATH = NORMALIZED_DIR / "airline_pair_screening_matrix.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_scenario_inputs.csv"

SCENARIOS = {
    "bear": {"revenue_delta_vs_consensus_pct": -5.0, "margin_delta_vs_consensus_pp": -2.0},
    "base": {"revenue_delta_vs_consensus_pct": 0.0, "margin_delta_vs_consensus_pp": 0.0},
    "bull": {"revenue_delta_vs_consensus_pct": 5.0, "margin_delta_vs_consensus_pp": 2.0},
}

OUTPUT_COLUMNS = [
    "dataset_id", "pair_id", "scenario", "pair_selection_bucket", "company_a", "company_b",
    "historical_divergence_status", "historical_bridge_status", "scenario_revenue_delta_vs_consensus_pct",
    "scenario_margin_delta_vs_consensus_pp", "actual_fy2025_revenue_usd_mn_a",
    "actual_fy2025_revenue_usd_mn_b", "consensus_fy2026_revenue_usd_mn_a",
    "consensus_fy2026_revenue_usd_mn_b", "consensus_fy2026_net_profit_usd_mn_a",
    "consensus_fy2026_net_profit_usd_mn_b", "implied_consensus_net_margin_pct_a",
    "implied_consensus_net_margin_pct_b", "scenario_revenue_usd_mn_a",
    "scenario_revenue_usd_mn_b", "scenario_net_profit_usd_mn_a", "scenario_net_profit_usd_mn_b",
    "scenario_net_margin_pct_a", "scenario_net_margin_pct_b", "scenario_profit_gap_a_minus_b_usd_mn",
    "scenario_margin_gap_a_minus_b_pp", "scenario_revenue_gap_a_minus_b_usd_mn",
    "current_valuation_revenue_gap_a_minus_b", "consensus_snapshot_date_a", "consensus_snapshot_date_b",
    "consensus_forecast_date_max_a", "consensus_forecast_date_max_b", "source_quality", "source_note",
    "retrieved_at",
]


def _number(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _detailed_usd_mn(row: pd.Series | None) -> float | None:
    if row is None or row.empty:
        return None
    value = _number(row.get("value_avg_usd_at_snapshot"))
    if value is None:
        return None
    return value * 100.0 if str(row.get("native_unit")) == "RMB 100 million" else value


def _company_detailed(detailed: pd.DataFrame, company: str) -> dict[str, object]:
    rows = detailed.loc[detailed["company"].eq(company) & detailed["fiscal_year"].eq(2026)]
    result: dict[str, object] = {}
    for metric in ("revenue", "revenue_growth", "net_profit_detailed"):
        row = rows.loc[rows["metric"].eq(metric)]
        if row.empty:
            continue
        source = row.iloc[0]
        result[metric] = _detailed_usd_mn(source) if metric != "revenue_growth" else _number(source.get("value_avg_native"))
        result[f"{metric}_snapshot_date"] = source.get("snapshot_date")
        result[f"{metric}_forecast_date_min"] = source.get("forecast_date_min")
        result[f"{metric}_forecast_date_max"] = source.get("forecast_date_max")
    if _number(result.get("revenue")) not in (None, 0) and _number(result.get("net_profit_detailed")) is not None:
        result["implied_net_margin_pct"] = 100.0 * _number(result["net_profit_detailed"]) / _number(result["revenue"])
    return result


def _actual_fy2025(bridge: pd.DataFrame, company: str) -> dict[str, object]:
    rows = bridge.loc[bridge["company"].eq(company) & bridge["period_end"].eq("2025-12-31")]
    if rows.empty:
        return {}
    row = rows.iloc[0]
    return {
        "revenue_usd_mn": _number(row.get("revenue_usd_mn")),
        "net_margin_pct": _number(row.get("net_margin_pct")),
    }


def build_airline_pair_scenario_inputs(
    *,
    bridge: pd.DataFrame | None = None,
    detailed: pd.DataFrame | None = None,
    pair_historical: pd.DataFrame | None = None,
    pair_matrix: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    detailed = detailed if detailed is not None else pd.read_csv(DETAILED_CONSENSUS_PATH)
    pair_historical = pair_historical if pair_historical is not None else pd.read_csv(PAIR_HISTORICAL_PATH)
    pair_matrix = pair_matrix if pair_matrix is not None else pd.read_csv(PAIR_MATRIX_PATH)
    detailed = detailed.copy()
    detailed["fiscal_year"] = pd.to_numeric(detailed["fiscal_year"], errors="coerce")
    detailed_by_company = {company: _company_detailed(detailed, company) for company in detailed["company"].dropna().unique()}
    actual_by_company = {company: _actual_fy2025(bridge, company) for company in bridge["company"].dropna().unique()}
    pair_historical_by_id = pair_historical.set_index("pair_id").to_dict(orient="index")
    pair_matrix_by_id = pair_matrix.set_index("pair_id").to_dict(orient="index")
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []

    for _, pair in pair_matrix.iterrows():
        pair_id = pair["pair_id"]
        historical = pair_historical_by_id.get(pair_id, {})
        company_a, company_b = str(pair["company_a"]), str(pair["company_b"])
        a, b = detailed_by_company.get(company_a, {}), detailed_by_company.get(company_b, {})
        actual_a, actual_b = actual_by_company.get(company_a, {}), actual_by_company.get(company_b, {})
        for scenario, assumption in SCENARIOS.items():
            revenue_delta = assumption["revenue_delta_vs_consensus_pct"]
            margin_delta = assumption["margin_delta_vs_consensus_pp"]
            revenue_a = _number(a.get("revenue"))
            revenue_b = _number(b.get("revenue"))
            margin_a = _number(a.get("implied_net_margin_pct"))
            margin_b = _number(b.get("implied_net_margin_pct"))
            scenario_revenue_a = revenue_a * (1.0 + revenue_delta / 100.0) if revenue_a is not None else None
            scenario_revenue_b = revenue_b * (1.0 + revenue_delta / 100.0) if revenue_b is not None else None
            scenario_margin_a = margin_a + margin_delta if margin_a is not None else None
            scenario_margin_b = margin_b + margin_delta if margin_b is not None else None
            scenario_profit_a = scenario_revenue_a * scenario_margin_a / 100.0 if scenario_revenue_a is not None and scenario_margin_a is not None else None
            scenario_profit_b = scenario_revenue_b * scenario_margin_b / 100.0 if scenario_revenue_b is not None and scenario_margin_b is not None else None
            row = {
                "dataset_id": "airline_pair_scenario_inputs",
                "pair_id": pair_id,
                "scenario": scenario,
                "pair_selection_bucket": historical.get("pair_selection_bucket"),
                "company_a": company_a, "company_b": company_b,
                "historical_divergence_status": historical.get("historical_divergence_status"),
                "historical_bridge_status": historical.get("historical_bridge_status"),
                "scenario_revenue_delta_vs_consensus_pct": revenue_delta,
                "scenario_margin_delta_vs_consensus_pp": margin_delta,
                "actual_fy2025_revenue_usd_mn_a": actual_a.get("revenue_usd_mn"),
                "actual_fy2025_revenue_usd_mn_b": actual_b.get("revenue_usd_mn"),
                "consensus_fy2026_revenue_usd_mn_a": revenue_a,
                "consensus_fy2026_revenue_usd_mn_b": revenue_b,
                "consensus_fy2026_net_profit_usd_mn_a": a.get("net_profit_detailed"),
                "consensus_fy2026_net_profit_usd_mn_b": b.get("net_profit_detailed"),
                "implied_consensus_net_margin_pct_a": margin_a,
                "implied_consensus_net_margin_pct_b": margin_b,
                "scenario_revenue_usd_mn_a": scenario_revenue_a,
                "scenario_revenue_usd_mn_b": scenario_revenue_b,
                "scenario_net_profit_usd_mn_a": scenario_profit_a,
                "scenario_net_profit_usd_mn_b": scenario_profit_b,
                "scenario_net_margin_pct_a": scenario_margin_a,
                "scenario_net_margin_pct_b": scenario_margin_b,
                "scenario_profit_gap_a_minus_b_usd_mn": scenario_profit_a - scenario_profit_b if scenario_profit_a is not None and scenario_profit_b is not None else None,
                "scenario_margin_gap_a_minus_b_pp": scenario_margin_a - scenario_margin_b if scenario_margin_a is not None and scenario_margin_b is not None else None,
                "scenario_revenue_gap_a_minus_b_usd_mn": scenario_revenue_a - scenario_revenue_b if scenario_revenue_a is not None and scenario_revenue_b is not None else None,
                "current_valuation_revenue_gap_a_minus_b": pair.get("valuation_revenue_gap_a_minus_b"),
                "consensus_snapshot_date_a": a.get("revenue_snapshot_date"),
                "consensus_snapshot_date_b": b.get("revenue_snapshot_date"),
                "consensus_forecast_date_max_a": a.get("revenue_forecast_date_max"),
                "consensus_forecast_date_max_b": b.get("revenue_forecast_date_max"),
                "source_quality": "derived_scenario_stress_test",
                "source_note": (
                    "Mechanical FY2026 stress test from the A-share detailed average-only snapshot. "
                    "Bear/base/bull revenue is consensus -5%/0%/+5%; net margin is implied consensus margin "
                    "-2pp/0pp/+2pp. This is not an independent forecast, historical consensus vintage or trade direction."
                ),
                "retrieved_at": retrieved,
            }
            rows.append(row)
    result = pd.DataFrame(rows)
    for column in OUTPUT_COLUMNS:
        if column not in result:
            result[column] = None
    return result[OUTPUT_COLUMNS]


def fetch_airline_pair_scenario_inputs() -> pd.DataFrame:
    result = build_airline_pair_scenario_inputs()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
