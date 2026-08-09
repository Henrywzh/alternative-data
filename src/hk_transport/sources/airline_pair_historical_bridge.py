"""Pair-level historical differentials for airline long/short thesis work.

This layer is intentionally complementary to the current pair-screening
matrix.  It summarizes equal-period historical financial and operating
differences from the synchronized company-period bridge and carries forward
the existing current expectation/risk fields.  It does not assign a long or
short direction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR


BRIDGE_PATH = NORMALIZED_DIR / "airline_historical_earnings_bridge.csv"
PAIR_MATRIX_PATH = NORMALIZED_DIR / "airline_pair_screening_matrix.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_historical_bridge.csv"

COMPANY_NAMES = {
    "Air China", "China Southern Airlines", "China Eastern Airlines", "Spring Airlines",
    "Hainan Airlines Holdings", "Juneyao Airlines",
}
CATHAY_COMPANY = "Cathay Pacific"

PERIODS = {
    "fy2019": ("2019-12-31", "FY"),
    "fy2024": ("2024-12-31", "FY"),
    "fy2025": ("2025-12-31", "FY"),
    "q1_2025": ("2025-03-31", "Q1_or_1Q"),
    "q1_2026": ("2026-03-31", "Q1_or_1Q"),
}

LEG_METRICS = [
    "fy2019_revenue_usd_mn", "fy2025_revenue_usd_mn", "fy2025_revenue_cagr_pct",
    "fy2019_net_margin_pct", "fy2024_net_margin_pct", "fy2025_net_margin_pct",
    "fy2025_net_margin_change_from_2019_pp", "fy2025_operating_cash_flow_to_revenue_pct",
    "fy2025_passenger_load_factor_pct", "q1_2025_passenger_load_factor_pct",
    "q1_2026_passenger_load_factor_pct", "q1_2026_passenger_load_factor_change_pp",
    "q1_2025_ask_growth_yoy_pct", "q1_2025_rpk_growth_yoy_pct",
    "q1_2026_ask_growth_yoy_pct", "q1_2026_rpk_growth_yoy_pct",
    "q1_2025_demand_capacity_gap_pp", "q1_2026_demand_capacity_gap_pp",
    "q1_2026_demand_capacity_gap_change_pp", "fy2025_jet_fuel_avg_usd_per_gallon",
    "q1_2026_jet_fuel_avg_usd_per_gallon", "q1_2026_jet_fuel_change_pct",
    "current_ashare_detailed_fy2026_net_profit_usd_mn",
    "current_hk_broker_fy2026_net_profit_usd_mn",
    "historical_anomaly_period_count", "historical_operating_coverage_status",
    "historical_operating_anomaly_periods",
]

OUTPUT_COLUMNS = [
    "dataset_id", "pair_id", "asset_a", "company_a", "market_a", "asset_b", "company_b", "market_b",
    "same_market", "screen_snapshot_date", "pair_selection_bucket", "historical_bridge_status",
    "historical_divergence_status", "expectation_dispersion_status",
]
for suffix in ("a", "b"):
    OUTPUT_COLUMNS.extend(f"{metric}_{suffix}" for metric in LEG_METRICS)
for metric in (
    "fy2025_net_margin_gap_a_minus_b_pp", "fy2025_revenue_cagr_gap_a_minus_b_pp",
    "fy2025_operating_cash_flow_to_revenue_gap_a_minus_b_pp",
    "q1_2026_passenger_load_factor_gap_a_minus_b_pp",
    "q1_2026_demand_capacity_gap_a_minus_b_pp",
    "q1_2026_demand_capacity_gap_change_a_minus_b_pp",
    "q1_2026_jet_fuel_change_gap_a_minus_b_pp",
    "current_ashare_detailed_consensus_net_profit_gap_a_minus_b_usd_mn",
    "current_hk_broker_consensus_net_profit_gap_a_minus_b_usd_mn",
):
    OUTPUT_COLUMNS.append(metric)
OUTPUT_COLUMNS.extend([
    "current_consensus_net_margin_gap_a_minus_b_pct", "valuation_revenue_gap_a_minus_b",
    "correlation_a_b", "beta_a_to_b", "beta_b_to_a", "hedged_spread_vol_a_minus_beta_b_pct",
    "hedged_spread_max_drawdown_a_minus_beta_b_pct", "fuel_plus_5pct_profit_impact_usd_mn_a",
    "fuel_plus_5pct_profit_impact_usd_mn_b", "readiness_status_a", "readiness_status_b",
    "profit_base_status", "catalyst_status", "operating_anomaly_flag_a", "operating_anomaly_flag_b",
    "thesis_input_note", "source_quality", "source_note", "retrieved_at",
])


def _number(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _row(frame: pd.DataFrame, company: str, period_end: str) -> pd.Series:
    rows = frame.loc[frame["company"].eq(company) & frame["period_end"].eq(period_end)]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _growth(current: object, prior: object) -> float | None:
    current_value, prior_value = _number(current), _number(prior)
    if current_value is None or prior_value in (None, 0):
        return None
    return 100.0 * (current_value / prior_value - 1.0)


def _gap(first: object, second: object) -> float | None:
    a, b = _number(first), _number(second)
    return a - b if a is not None and b is not None else None


def _leg_summary(bridge: pd.DataFrame, company: str) -> dict[str, object]:
    period_rows = {label: _row(bridge, company, period_end) for label, (period_end, _) in PERIODS.items()}
    fy2019 = period_rows["fy2019"]
    fy2024 = period_rows["fy2024"]
    fy2025 = period_rows["fy2025"]
    q1_2025 = period_rows["q1_2025"]
    q1_2026 = period_rows["q1_2026"]

    q1_2025_ask_growth = _growth(q1_2025.get("ask_mn_seat_km"), _row(bridge, company, "2024-03-31").get("ask_mn_seat_km"))
    q1_2025_rpk_growth = _growth(q1_2025.get("rpk_mn_passenger_km"), _row(bridge, company, "2024-03-31").get("rpk_mn_passenger_km"))
    q1_2026_ask_growth = _growth(q1_2026.get("ask_mn_seat_km"), q1_2025.get("ask_mn_seat_km"))
    q1_2026_rpk_growth = _growth(q1_2026.get("rpk_mn_passenger_km"), q1_2025.get("rpk_mn_passenger_km"))
    anomalies = bridge.loc[
        bridge["company"].eq(company) & bridge["operating_anomaly_flag"].notna(),
        ["period_end", "operating_anomaly_flag"],
    ]
    anomaly_periods = ";".join(f"{row.period_end}:{row.operating_anomaly_flag}" for row in anomalies.itertuples()) or None
    company_rows = bridge.loc[bridge["company"].eq(company)].copy()
    coverage = pd.to_numeric(company_rows.get("operating_month_count"), errors="coerce")
    expected = company_rows.get("period_type", pd.Series(dtype=object)).map({"Q1_or_1Q": 3, "H1_or_2Q": 6, "Q3_or_9M": 9, "FY": 12})
    if coverage.empty:
        coverage_status = "not_available_in_six_company_bridge"
    elif coverage.notna().all() and coverage.reset_index(drop=True).eq(expected.reset_index(drop=True)).all():
        coverage_status = "complete_for_bridge_periods"
    else:
        coverage_status = "partial_or_anomalous"

    result = {
        "fy2019_revenue_usd_mn": fy2019.get("revenue_usd_mn"),
        "fy2025_revenue_usd_mn": fy2025.get("revenue_usd_mn"),
        "fy2025_revenue_cagr_pct": (100.0 * ((_number(fy2025.get("revenue_usd_mn")) / _number(fy2019.get("revenue_usd_mn"))) ** (1 / 6) - 1.0)
            if _number(fy2019.get("revenue_usd_mn")) and _number(fy2025.get("revenue_usd_mn")) and _number(fy2019.get("revenue_usd_mn")) > 0 else None),
        "fy2019_net_margin_pct": fy2019.get("net_margin_pct"),
        "fy2024_net_margin_pct": fy2024.get("net_margin_pct"),
        "fy2025_net_margin_pct": fy2025.get("net_margin_pct"),
        "fy2025_net_margin_change_from_2019_pp": _gap(fy2025.get("net_margin_pct"), fy2019.get("net_margin_pct")),
        "fy2025_operating_cash_flow_to_revenue_pct": (100.0 * _number(fy2025.get("operating_cash_flow_usd_mn")) / _number(fy2025.get("revenue_usd_mn"))
            if _number(fy2025.get("operating_cash_flow_usd_mn")) is not None and _number(fy2025.get("revenue_usd_mn")) not in (None, 0) else None),
        "fy2025_passenger_load_factor_pct": fy2025.get("passenger_load_factor_pct"),
        "q1_2025_passenger_load_factor_pct": q1_2025.get("passenger_load_factor_pct"),
        "q1_2026_passenger_load_factor_pct": q1_2026.get("passenger_load_factor_pct"),
        "q1_2026_passenger_load_factor_change_pp": _gap(q1_2026.get("passenger_load_factor_pct"), q1_2025.get("passenger_load_factor_pct")),
        "q1_2025_ask_growth_yoy_pct": q1_2025_ask_growth,
        "q1_2025_rpk_growth_yoy_pct": q1_2025_rpk_growth,
        "q1_2026_ask_growth_yoy_pct": q1_2026_ask_growth,
        "q1_2026_rpk_growth_yoy_pct": q1_2026_rpk_growth,
        "q1_2025_demand_capacity_gap_pp": _gap(q1_2025_rpk_growth, q1_2025_ask_growth),
        "q1_2026_demand_capacity_gap_pp": _gap(q1_2026_rpk_growth, q1_2026_ask_growth),
        "q1_2026_demand_capacity_gap_change_pp": _gap(_gap(q1_2026_rpk_growth, q1_2026_ask_growth), _gap(q1_2025_rpk_growth, q1_2025_ask_growth)),
        "fy2025_jet_fuel_avg_usd_per_gallon": fy2025.get("jet_fuel_avg_usd_per_gallon"),
        "q1_2026_jet_fuel_avg_usd_per_gallon": q1_2026.get("jet_fuel_avg_usd_per_gallon"),
        "q1_2026_jet_fuel_change_pct": _growth(q1_2026.get("jet_fuel_avg_usd_per_gallon"), fy2025.get("jet_fuel_avg_usd_per_gallon")),
        "current_ashare_detailed_fy2026_net_profit_usd_mn": q1_2026.get("current_ashare_detailed_fy2026_net_profit_usd_mn"),
        "current_hk_broker_fy2026_net_profit_usd_mn": q1_2026.get("current_hk_broker_fy2026_net_profit_usd_mn"),
        "historical_anomaly_period_count": int(len(anomalies)),
        "historical_operating_coverage_status": coverage_status,
        "historical_operating_anomaly_periods": anomaly_periods,
    }
    if fy2025.empty:
        result = {key: None for key in LEG_METRICS}
        result["historical_operating_coverage_status"] = "not_available_in_six_company_bridge"
    return result


def _pair_bucket(company_a: str, company_b: str) -> str:
    pair = {company_a, company_b}
    if pair == {"Spring Airlines", "Juneyao Airlines"}:
        return "core_candidate"
    if pair == {"China Southern Airlines", "China Eastern Airlines"}:
        return "backup_candidate"
    if "Cathay Pacific" in pair:
        return "cross_market_backup"
    return "monitor"


def _divergence_status(a: dict[str, object], b: dict[str, object], bucket: str) -> str:
    margin_gap = _gap(a.get("fy2025_net_margin_pct"), b.get("fy2025_net_margin_pct"))
    demand_gap = _gap(a.get("q1_2026_demand_capacity_gap_pp"), b.get("q1_2026_demand_capacity_gap_pp"))
    if bucket == "cross_market_backup" and (a.get("historical_bridge_status") != "available" or b.get("historical_bridge_status") != "available"):
        return "historical_bridge_incomplete"
    if margin_gap is None or demand_gap is None:
        return "insufficient_historical_bridge"
    if abs(margin_gap) >= 4 or abs(demand_gap) >= 3:
        return "material_historical_divergence"
    if abs(margin_gap) <= 1 and abs(demand_gap) <= 1:
        return "historical_convergence"
    return "mixed_historical_signal"


def build_airline_pair_historical_bridge(
    *,
    bridge: pd.DataFrame | None = None,
    pair_matrix: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    pair_matrix = pair_matrix if pair_matrix is not None else pd.read_csv(PAIR_MATRIX_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    summaries = {company: _leg_summary(bridge, company) for company in pair_matrix["company_a"].tolist() + pair_matrix["company_b"].tolist()}
    rows: list[dict[str, object]] = []
    for _, pair in pair_matrix.iterrows():
        company_a, company_b = str(pair["company_a"]), str(pair["company_b"])
        a = summaries[company_a] if company_a in summaries else {key: None for key in LEG_METRICS}
        b = summaries[company_b] if company_b in summaries else {key: None for key in LEG_METRICS}
        bucket = _pair_bucket(company_a, company_b)
        def _bridge_status(company: str) -> str:
            if company in COMPANY_NAMES:
                return "available"
            if company == CATHAY_COMPANY:
                # Cathay now has official FY2025/1H2024/1H2025/1H2026 rows,
                # but not the FY2019/FY2024/Q1 periods used by the mainland
                # bridge. Keep the pair gate partial rather than implying a
                # like-for-like historical panel.
                return "partial_cross_region_period_history"
            return "not_available_in_six_company_bridge"

        a["historical_bridge_status"] = _bridge_status(company_a)
        b["historical_bridge_status"] = _bridge_status(company_b)
        row: dict[str, object] = {
            "dataset_id": "airline_pair_historical_bridge",
            "pair_id": pair["pair_id"],
            "asset_a": pair["asset_a"], "company_a": company_a, "market_a": pair["market_a"],
            "asset_b": pair["asset_b"], "company_b": company_b, "market_b": pair["market_b"],
            "same_market": pair["same_market"], "screen_snapshot_date": pair["screen_snapshot_date"],
            "pair_selection_bucket": bucket,
            "historical_bridge_status": "complete" if a["historical_bridge_status"] == b["historical_bridge_status"] == "available" else "partial",
            "historical_divergence_status": _divergence_status(a, b, bucket),
            "expectation_dispersion_status": "high" if abs(_number(pair.get("consensus_net_margin_gap_a_minus_b_pct")) or 0) >= 3 else "moderate",
        }
        for suffix, summary in (("a", a), ("b", b)):
            for metric in LEG_METRICS:
                row[f"{metric}_{suffix}"] = summary.get(metric)
        pair_gaps = {
            "fy2025_net_margin_gap_a_minus_b_pp": _gap(a.get("fy2025_net_margin_pct"), b.get("fy2025_net_margin_pct")),
            "fy2025_revenue_cagr_gap_a_minus_b_pp": _gap(a.get("fy2025_revenue_cagr_pct"), b.get("fy2025_revenue_cagr_pct")),
            "fy2025_operating_cash_flow_to_revenue_gap_a_minus_b_pp": _gap(a.get("fy2025_operating_cash_flow_to_revenue_pct"), b.get("fy2025_operating_cash_flow_to_revenue_pct")),
            "q1_2026_passenger_load_factor_gap_a_minus_b_pp": _gap(a.get("q1_2026_passenger_load_factor_pct"), b.get("q1_2026_passenger_load_factor_pct")),
            "q1_2026_demand_capacity_gap_a_minus_b_pp": _gap(a.get("q1_2026_demand_capacity_gap_pp"), b.get("q1_2026_demand_capacity_gap_pp")),
            "q1_2026_demand_capacity_gap_change_a_minus_b_pp": _gap(a.get("q1_2026_demand_capacity_gap_change_pp"), b.get("q1_2026_demand_capacity_gap_change_pp")),
            "q1_2026_jet_fuel_change_gap_a_minus_b_pp": _gap(a.get("q1_2026_jet_fuel_change_pct"), b.get("q1_2026_jet_fuel_change_pct")),
            "current_ashare_detailed_consensus_net_profit_gap_a_minus_b_usd_mn": _gap(a.get("current_ashare_detailed_fy2026_net_profit_usd_mn"), b.get("current_ashare_detailed_fy2026_net_profit_usd_mn")),
            "current_hk_broker_consensus_net_profit_gap_a_minus_b_usd_mn": _gap(a.get("current_hk_broker_fy2026_net_profit_usd_mn"), b.get("current_hk_broker_fy2026_net_profit_usd_mn")),
        }
        row.update(pair_gaps)
        for field in (
            "consensus_net_margin_gap_a_minus_b_pct", "valuation_revenue_gap_a_minus_b", "correlation_a_b", "beta_a_to_b",
            "beta_b_to_a", "hedged_spread_vol_a_minus_beta_b_pct", "hedged_spread_max_drawdown_a_minus_beta_b_pct",
            "fuel_plus_5pct_profit_impact_usd_mn_a", "fuel_plus_5pct_profit_impact_usd_mn_b", "readiness_status_a",
            "readiness_status_b", "profit_base_status", "catalyst_status",
        ):
            row[field] = pair.get(field)
        row["operating_anomaly_flag_a"] = a.get("historical_operating_anomaly_periods")
        row["operating_anomaly_flag_b"] = b.get("historical_operating_anomaly_periods")
        if bucket == "core_candidate":
            note = "Core candidate: test whether the persistent historical profitability and Q1 demand-capacity divergence is reflected in current valuation and consensus."
        elif bucket == "backup_candidate":
            note = "Backup candidate: test whether the two large carriers are converging or diverging after the 2025 loss/recovery cycle; formal 1H2026 results are the key catalyst."
        elif bucket == "cross_market_backup":
            note = "Cross-market backup: Cathay now contributes official FY2025/1H driver rows, but its international/group scope and missing FY2019/FY2024/Q1 periods keep the historical bridge explicitly partial; use primary-driver and risk layers for comparability."
        else:
            note = "Monitor pair: retain as a comparator until the core and backup thesis workstreams resolve."
        row["thesis_input_note"] = note
        row["source_quality"] = "derived_pair_historical_bridge"
        row["source_note"] = (
            "Pair-level descriptive differential layer derived from the synchronized company-period bridge and current pair-screening matrix. "
            "It does not assign long/short direction, does not neutralize Barra factors and does not establish borrow feasibility. "
            "Financial history lacks issuer announcement dates; current consensus fields are snapshots, not historical vintages."
        )
        row["retrieved_at"] = retrieved
        rows.append(row)
    result = pd.DataFrame(rows)
    for column in OUTPUT_COLUMNS:
        if column not in result:
            result[column] = None
    return result[OUTPUT_COLUMNS]


def fetch_airline_pair_historical_bridge() -> pd.DataFrame:
    result = build_airline_pair_historical_bridge()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
