"""Compact model-input table for the Spring–Juneyao thesis draft."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR


COMPANY_NAMES = ("Spring Airlines", "Juneyao Airlines")
DRIVER_PATH = NORMALIZED_DIR / "airline_earnings_driver_comparability.csv"
BRIDGE_PATH = NORMALIZED_DIR / "airline_historical_earnings_bridge.csv"
PAIR_HISTORICAL_PATH = NORMALIZED_DIR / "airline_pair_historical_bridge.csv"
PAIR_SCENARIO_PATH = NORMALIZED_DIR / "airline_pair_scenario_inputs.csv"
EXPECTATIONS_PATH = NORMALIZED_DIR / "airline_market_expectations_snapshot.csv"
MARKET_SNAPSHOT_PATH = NORMALIZED_DIR / "airline_market_snapshot.csv"
DETAILED_CONSENSUS_PATH = NORMALIZED_DIR / "airline_consensus_ashare_detailed.csv"
RECON_PATH = NORMALIZED_DIR / "airline_primary_financial_reconciliation.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_core_pair_model_inputs.csv"

DRIVER_METRICS = {
    "revenue_usd_mn": "total_revenue",
    "attributable_profit_usd_mn": "attributable_profit",
    "operating_cash_flow_usd_mn": "operating_cash_flow",
    "operating_cost_usd_mn": "operating_cost",
    "fuel_cost_usd_mn": "fuel_cost",
    "fuel_cost_share_pct": "fuel_cost_share_pct",
    "ask_mn_seat_km": "ask",
    "rpk_mn_passenger_km": "rpk",
    "passenger_load_factor_pct": "passenger_load_factor_pct",
    "passenger_yield_rmb_per_rpk": "passenger_yield",
    "cask_rmb_per_ask": "cask",
    "rask_proxy_rmb_per_ask": "rask_proxy",
    "fuel_cost_per_ask_rmb": "fuel_cost_per_ask",
    "fleet_total": "fleet_total",
    "daily_utilization_hours": "daily_utilization",
}

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "as_of_date",
    "fy2025_revenue_usd_mn", "fy2025_attributable_profit_usd_mn", "fy2025_operating_cash_flow_usd_mn",
    "fy2025_operating_cost_usd_mn", "fy2025_fuel_cost_usd_mn", "fy2025_fuel_cost_share_pct",
    "fy2025_ask_mn_seat_km", "fy2025_rpk_mn_passenger_km", "fy2025_passenger_load_factor_pct",
    "fy2025_passenger_yield_rmb_per_rpk", "fy2025_cask_rmb_per_ask", "fy2025_rask_proxy_rmb_per_ask",
    "fy2025_fuel_cost_per_ask_rmb", "fy2025_fleet_total", "fy2025_daily_utilization_hours",
    "h1_2025_revenue_usd_mn", "h1_2025_attributable_profit_usd_mn", "h1_2025_operating_cash_flow_usd_mn",
    "h1_2025_operating_cost_usd_mn", "h1_2025_fuel_cost_usd_mn", "h1_2025_fuel_cost_share_pct",
    "h1_2025_ask_mn_seat_km", "h1_2025_rpk_mn_passenger_km", "h1_2025_passenger_load_factor_pct",
    "h1_2025_passenger_yield_rmb_per_rpk", "h1_2025_cask_rmb_per_ask", "h1_2025_rask_proxy_rmb_per_ask",
    "h1_2025_fuel_cost_per_ask_rmb", "h1_2025_fleet_total", "h1_2025_daily_utilization_hours",
    "q1_2026_provider_revenue_usd_mn", "q1_2026_provider_net_margin_pct", "q1_2026_ask_mn_seat_km",
    "q1_2026_rpk_mn_passenger_km", "q1_2026_passenger_load_factor_pct", "q1_2026_demand_capacity_gap_pp",
    "q1_2026_jet_fuel_avg_usd_per_gallon", "q1_2026_operating_anomaly_flag",
    "fy2026_consensus_revenue_usd_mn", "fy2026_consensus_revenue_growth_pct",
    "fy2026_consensus_net_profit_usd_mn", "fy2026_consensus_net_profit_low_usd_mn",
    "fy2026_consensus_net_profit_high_usd_mn", "fy2026_consensus_net_margin_pct",
    "fy2026_market_cap_usd_mn", "fy2026_market_cap_to_consensus_revenue",
    "fy2026_profit_range_crosses_zero", "scenario_bear_profit_usd_mn", "scenario_base_profit_usd_mn",
    "scenario_bull_profit_usd_mn", "primary_fy2025_operating_cost_status",
    "primary_h1_2025_operating_cost_status", "official_fy2025_source_url", "official_h1_2025_source_url",
    "consensus_source_url", "market_snapshot_source_url", "source_quality", "source_note", "retrieved_at",
]


def _number(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _driver_row(drivers: pd.DataFrame, company: str, period: str, metric: str) -> pd.Series:
    rows = drivers.loc[
        drivers["company"].eq(company)
        & drivers["statement_period"].eq(period)
        & drivers["canonical_metric"].eq(metric)
    ]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _driver_values(drivers: pd.DataFrame, company: str, period: str) -> dict[str, object]:
    values: dict[str, object] = {}
    for output, metric in DRIVER_METRICS.items():
        row = _driver_row(drivers, company, period, metric)
        values[output] = _number(row.get("value_usd")) if output.endswith("usd_mn") else _number(row.get("value_native"))
        values[f"{output}_source_url"] = row.get("source_url")
    return values


def _pair_leg_row(pair: pd.Series, company: str, field: str) -> object:
    if str(pair.get("company_a")) == company:
        return pair.get(f"{field}_a")
    if str(pair.get("company_b")) == company:
        return pair.get(f"{field}_b")
    return None


def build_airline_core_pair_model_inputs(
    *,
    drivers: pd.DataFrame | None = None,
    bridge: pd.DataFrame | None = None,
    pair_historical: pd.DataFrame | None = None,
    pair_scenarios: pd.DataFrame | None = None,
    expectations: pd.DataFrame | None = None,
    market_snapshot: pd.DataFrame | None = None,
    detailed_consensus: pd.DataFrame | None = None,
    reconciliation: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    drivers = drivers if drivers is not None else pd.read_csv(DRIVER_PATH)
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    pair_historical = pair_historical if pair_historical is not None else pd.read_csv(PAIR_HISTORICAL_PATH)
    pair_scenarios = pair_scenarios if pair_scenarios is not None else pd.read_csv(PAIR_SCENARIO_PATH)
    expectations = expectations if expectations is not None else pd.read_csv(EXPECTATIONS_PATH)
    market_snapshot = market_snapshot if market_snapshot is not None else pd.read_csv(MARKET_SNAPSHOT_PATH)
    detailed_consensus = detailed_consensus if detailed_consensus is not None else pd.read_csv(DETAILED_CONSENSUS_PATH)
    reconciliation = reconciliation if reconciliation is not None else pd.read_csv(RECON_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    pair = pair_historical.loc[pair_historical["pair_selection_bucket"].eq("core_candidate")].iloc[0]
    rows: list[dict[str, object]] = []
    for company in COMPANY_NAMES:
        fy = _driver_values(drivers, company, "FY2025")
        h1 = _driver_values(drivers, company, "1H2025")
        q1_rows = bridge.loc[bridge["company"].eq(company) & bridge["period_end"].eq("2026-03-31")]
        q1 = q1_rows.iloc[0] if not q1_rows.empty else pd.Series(dtype=object)
        expectation_rows = expectations.loc[expectations["company"].eq(company)]
        expectation = expectation_rows.iloc[0] if not expectation_rows.empty else pd.Series(dtype=object)
        market_rows = market_snapshot.loc[market_snapshot["company"].eq(company)]
        market_row = market_rows.iloc[0] if not market_rows.empty else pd.Series(dtype=object)
        detailed_rows = detailed_consensus.loc[
            detailed_consensus["company"].eq(company)
            & pd.to_numeric(detailed_consensus["fiscal_year"], errors="coerce").eq(2026)
            & detailed_consensus["metric"].eq("revenue")
        ]
        detailed_row = detailed_rows.iloc[0] if not detailed_rows.empty else pd.Series(dtype=object)
        scenario_rows = pair_scenarios.loc[pair_scenarios["scenario"].isin(["bear", "base", "bull"]) & pair_scenarios["company_a"].eq(pair["company_a"]) & pair_scenarios["company_b"].eq(pair["company_b"])]
        scenario_by_name = {
            scenario: _number(_pair_leg_row(row, company, "scenario_net_profit_usd_mn"))
            for scenario, row in ((s, scenario_rows.loc[scenario_rows["scenario"].eq(s)].iloc[0]) for s in ("bear", "base", "bull") if not scenario_rows.loc[scenario_rows["scenario"].eq(s)].empty)
        }
        recon = reconciliation.loc[reconciliation["company"].eq(company) & reconciliation["metric"].eq("operating_cost")]
        recon_fy = recon.loc[recon["statement_period"].eq("FY2025"), "reconciliation_status"]
        recon_h1 = recon.loc[recon["statement_period"].eq("1H2025"), "reconciliation_status"]
        row: dict[str, object] = {
            "dataset_id": "airline_core_pair_model_inputs",
            "company": company,
            "ticker": _driver_row(drivers, company, "FY2025", "total_revenue").get("ticker"),
            "market": "CN_A",
            "as_of_date": "2026-08-07",
        }
        for prefix, values in (("fy2025", fy), ("h1_2025", h1)):
            for key in DRIVER_METRICS:
                row[f"{prefix}_{key}"] = values.get(key)
        row.update({
            "q1_2026_provider_revenue_usd_mn": _number(q1.get("revenue_usd_mn")),
            "q1_2026_provider_net_margin_pct": _number(q1.get("net_margin_pct")),
            "q1_2026_ask_mn_seat_km": _number(q1.get("ask_mn_seat_km")),
            "q1_2026_rpk_mn_passenger_km": _number(q1.get("rpk_mn_passenger_km")),
            "q1_2026_passenger_load_factor_pct": _number(q1.get("passenger_load_factor_pct")),
            "q1_2026_demand_capacity_gap_pp": _number(_pair_leg_row(pair, company, "q1_2026_demand_capacity_gap_pp")),
            "q1_2026_jet_fuel_avg_usd_per_gallon": _number(q1.get("jet_fuel_avg_usd_per_gallon")),
            "q1_2026_operating_anomaly_flag": q1.get("operating_anomaly_flag"),
            "fy2026_consensus_revenue_usd_mn": _number(expectation.get("fy2026_revenue_avg_usd_mn")),
            "fy2026_consensus_revenue_growth_pct": _number(expectation.get("fy2026_revenue_growth_pct")),
            "fy2026_consensus_net_profit_usd_mn": _number(expectation.get("fy2026_net_profit_avg_usd_mn")),
            "fy2026_consensus_net_profit_low_usd_mn": _number(expectation.get("fy2026_net_profit_low_usd_mn")),
            "fy2026_consensus_net_profit_high_usd_mn": _number(expectation.get("fy2026_net_profit_high_usd_mn")),
            "fy2026_consensus_net_margin_pct": _number(expectation.get("fy2026_consensus_net_margin_pct")),
            "fy2026_market_cap_usd_mn": _number(expectation.get("market_cap_usd_mn")),
            "fy2026_market_cap_to_consensus_revenue": _number(expectation.get("market_cap_to_consensus_revenue_usd")),
            "fy2026_profit_range_crosses_zero": expectation.get("fy2026_profit_range_crosses_zero"),
            "scenario_bear_profit_usd_mn": scenario_by_name.get("bear"),
            "scenario_base_profit_usd_mn": scenario_by_name.get("base"),
            "scenario_bull_profit_usd_mn": scenario_by_name.get("bull"),
            "primary_fy2025_operating_cost_status": recon_fy.iloc[0] if not recon_fy.empty else None,
            "primary_h1_2025_operating_cost_status": recon_h1.iloc[0] if not recon_h1.empty else None,
            "official_fy2025_source_url": _driver_row(drivers, company, "FY2025", "total_revenue").get("source_url"),
            "official_h1_2025_source_url": _driver_row(drivers, company, "1H2025", "total_revenue").get("source_url"),
            "consensus_source_url": detailed_row.get("source_url"),
            "market_snapshot_source_url": market_row.get("market_cap_source_url"),
            "source_quality": "derived_core_pair_model_inputs",
            "source_note": (
                "Compact Spring–Juneyao model input table. FY2025/1H2025 driver values prefer official issuer reports; "
                "Q1 2026 financial values are provider discovery context while monthly operating data remains issuer-released. "
                "FY2026 expectations are current asynchronous snapshots; scenario values are mechanical stress tests. "
                "Operating-cost reconciliation mismatches are retained and should not be used as final CASK anchors."
            ),
            "retrieved_at": retrieved,
        })
        rows.append(row)
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_core_pair_model_inputs() -> pd.DataFrame:
    result = build_airline_core_pair_model_inputs()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
