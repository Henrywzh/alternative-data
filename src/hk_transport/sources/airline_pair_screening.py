"""Non-directional pair-screening matrix for airline thesis preparation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR


PAIR_RISK_PATH = NORMALIZED_DIR / "airline_pair_risk_metrics.csv"
READINESS_PATH = NORMALIZED_DIR / "airline_pair_readiness.csv"
SHORT_PROXY_PATH = NORMALIZED_DIR / "airline_short_side_proxies.csv"
BRIDGE_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
DISPERSION_PATH = NORMALIZED_DIR / "airline_consensus_dispersion_all.csv"
SHORT_ELIGIBILITY_PATH = NORMALIZED_DIR / "airline_short_eligibility.csv"
HK_SHORT_POSITION_PATH = NORMALIZED_DIR / "airline_hk_short_positions.csv"
STOCK_CONNECT_SHORT_PATH = NORMALIZED_DIR / "airline_stock_connect_short_selling.csv"
RESEARCH_CHAIN_PATH = NORMALIZED_DIR / "airline_research_chain.csv"
OPERATING_DIAGNOSTICS_PATH = NORMALIZED_DIR / "airline_operating_diagnostics.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_screening_matrix.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "pair_id", "asset_a", "company_a", "market_a", "asset_b", "company_b", "market_b",
    "same_market", "screen_snapshot_date", "data_comparability_status",
    "expectation_comparability_status", "profit_base_status", "catalyst_status",
    "readiness_status_a", "readiness_status_b", "revision_evidence_band_a",
    "revision_evidence_band_b", "unified_estimate_revision_count_a",
    "unified_estimate_revision_count_b", "unified_up_revision_count_a",
    "unified_up_revision_count_b", "unified_down_revision_count_a",
    "unified_down_revision_count_b", "unified_revision_balance_a",
    "unified_revision_balance_b", "unified_latest_estimate_revision_date_a",
    "unified_latest_estimate_revision_date_b", "market_cap_to_consensus_revenue_a_usd",
    "market_cap_to_consensus_revenue_b_usd", "valuation_revenue_gap_a_minus_b",
    "consensus_net_margin_a_pct", "consensus_net_margin_b_pct",
    "consensus_net_margin_gap_a_minus_b_pct", "correlation_a_b", "beta_a_to_b", "beta_b_to_a",
    "public_eps_count_a", "public_eps_count_b", "public_eps_median_a_rmb_per_share",
    "public_eps_median_b_rmb_per_share", "public_eps_range_width_pct_a",
    "public_eps_range_width_pct_b", "public_net_profit_count_a", "public_net_profit_count_b",
    "public_net_profit_median_a_rmb_100m", "public_net_profit_median_b_rmb_100m",
    "public_net_profit_range_width_pct_a", "public_net_profit_range_width_pct_b",
    "public_revenue_count_a", "public_revenue_count_b", "public_revenue_median_a_rmb_100m",
    "public_revenue_median_b_rmb_100m", "public_revenue_range_width_pct_a",
    "public_revenue_range_width_pct_b", "public_report_latest_date_a", "public_report_latest_date_b",
    "short_eligibility_status_a", "short_eligibility_status_b",
    "short_eligibility_effective_date_a", "short_eligibility_effective_date_b",
    "short_eligibility_source_quality_a", "short_eligibility_source_quality_b",
    "sfc_short_position_shares_a", "sfc_short_position_shares_b",
    "sfc_short_position_value_hkd_a", "sfc_short_position_value_hkd_b",
    "sfc_short_position_reporting_date_a", "sfc_short_position_reporting_date_b",
    "sfc_short_position_history_count_a", "sfc_short_position_history_count_b",
    "stock_connect_remaining_available_display_a", "stock_connect_remaining_available_display_b",
    "stock_connect_remaining_available_shares_a", "stock_connect_remaining_available_shares_b",
    "stock_connect_short_turnover_shares_a", "stock_connect_short_turnover_shares_b",
    "stock_connect_short_turnover_value_rmb_a", "stock_connect_short_turnover_value_rmb_b",
    "stock_connect_short_pct_today_a", "stock_connect_short_pct_today_b",
    "stock_connect_short_pct_10d_a", "stock_connect_short_pct_10d_b",
    "stock_connect_observation_date_a", "stock_connect_observation_date_b",
    "stock_connect_history_count_a", "stock_connect_history_count_b",
    "rpk_minus_ask_growth_gap_pp_a", "rpk_minus_ask_growth_gap_pp_b",
    "implied_h2_profit_mid_native_mn_a", "implied_h2_profit_mid_native_mn_b",
    "historical_2h2025_profit_native_mn_a", "historical_2h2025_profit_native_mn_b",
    "implied_h2_mid_minus_historical_2h2025_native_mn_a",
    "implied_h2_mid_minus_historical_2h2025_native_mn_b",
    "q2_rpk_minus_ask_gap_pp_a", "q2_rpk_minus_ask_gap_pp_b",
    "q2_passengers_yoy_pct_a", "q2_passengers_yoy_pct_b",
    "q2_passenger_lf_minus_q1_pp_a", "q2_passenger_lf_minus_q1_pp_b",
    "june_rpk_minus_ask_gap_pp_a", "june_rpk_minus_ask_gap_pp_b",
    "june_passenger_lf_yoy_pp_a", "june_passenger_lf_yoy_pp_b",
    "latest_driver_period_a", "latest_driver_period_b",
    "latest_driver_as_of_a", "latest_driver_as_of_b",
    "latest_driver_metric_count_a", "latest_driver_metric_count_b",
    "latest_cargo_yield_a", "latest_cargo_yield_b",
    "latest_cargo_yield_unit_a", "latest_cargo_yield_unit_b",
    "latest_cargo_yield_currency_a", "latest_cargo_yield_currency_b",
    "latest_cargo_load_factor_pct_a", "latest_cargo_load_factor_pct_b",
    "latest_cargo_load_factor_pct_unit_a", "latest_cargo_load_factor_pct_unit_b",
    "latest_fuel_cost_per_ask_a", "latest_fuel_cost_per_ask_b",
    "latest_fuel_cost_per_ask_unit_a", "latest_fuel_cost_per_ask_unit_b",
    "latest_fuel_cost_per_ask_currency_a", "latest_fuel_cost_per_ask_currency_b",
    "latest_cost_per_atk_ex_fuel_a", "latest_cost_per_atk_ex_fuel_b",
    "latest_cost_per_atk_ex_fuel_unit_a", "latest_cost_per_atk_ex_fuel_unit_b",
    "latest_cost_per_atk_ex_fuel_currency_a", "latest_cost_per_atk_ex_fuel_currency_b",
    "latest_operating_cash_flow_native_mn_a", "latest_operating_cash_flow_native_mn_b",
    "latest_operating_cash_flow_native_mn_unit_a", "latest_operating_cash_flow_native_mn_unit_b",
    "latest_operating_cash_flow_native_mn_currency_a", "latest_operating_cash_flow_native_mn_currency_b",
    "latest_fuel_intensity_a", "latest_fuel_intensity_b",
    "latest_fuel_intensity_unit_a", "latest_fuel_intensity_unit_b",
    "latest_fuel_hedging_loss_gain_native_mn_a", "latest_fuel_hedging_loss_gain_native_mn_b",
    "latest_fuel_hedging_loss_gain_native_mn_unit_a", "latest_fuel_hedging_loss_gain_native_mn_unit_b",
    "latest_fuel_hedging_loss_gain_native_mn_currency_a", "latest_fuel_hedging_loss_gain_native_mn_currency_b",
    "fuel_plus_5pct_profit_impact_usd_mn_a", "fuel_plus_5pct_profit_impact_usd_mn_b",
    "fuel_minus_5pct_profit_impact_usd_mn_a", "fuel_minus_5pct_profit_impact_usd_mn_b",
    "fuel_plus_5pct_scenario_method_a", "fuel_plus_5pct_scenario_method_b",
    "fuel_minus_5pct_scenario_method_a", "fuel_minus_5pct_scenario_method_b",
    "fuel_surcharge_context_a", "fuel_surcharge_context_b",
    "fuel_scenario_fx_observation_date_a", "fuel_scenario_fx_observation_date_b",
    "debt_to_assets_a_pct", "debt_to_assets_b_pct", "debt_to_assets_gap_a_minus_b_pct",
    "primary_liabilities_to_assets_a_pct", "primary_liabilities_to_assets_b_pct",
    "primary_liabilities_to_assets_gap_a_minus_b_pct",
    "hedged_spread_vol_a_minus_beta_b_pct", "hedged_spread_max_drawdown_a_minus_beta_b_pct",
    "median_turnover_a_usd_mn_60d", "median_turnover_b_usd_mn_60d",
    "borrow_data_available_a", "borrow_data_available_b", "screen_status",
    "short_proxy_status_a", "short_proxy_status_b", "short_proxy_observation_date_a",
    "short_proxy_observation_date_b",
    "source_quality", "source_note", "retrieved_at",
]


def _row(frame: pd.DataFrame, company: str) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=object)
    rows = frame.loc[frame["company"].eq(company)]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _proxy_row(frame: pd.DataFrame, company: str, market: str) -> pd.Series:
    if frame.empty or not {"company", "market"}.issubset(frame.columns):
        return pd.Series(dtype=object)
    rows = frame.loc[frame["company"].eq(company) & frame["market"].eq(market)]
    return rows.sort_values("observation_date").iloc[-1] if not rows.empty else pd.Series(dtype=object)


def _bridge_row(frame: pd.DataFrame, company: str, market: str) -> pd.Series:
    if frame.empty or not {"company", "market"}.issubset(frame.columns):
        return pd.Series(dtype=object)
    rows = frame.loc[frame["company"].eq(company) & frame["market"].eq(market)]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _dispersion_row(frame: pd.DataFrame, company: str) -> pd.Series:
    if frame.empty or "company" not in frame.columns:
        return pd.Series(dtype=object)
    rows = frame.loc[frame["company"].eq(company)]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _eligibility_row(frame: pd.DataFrame, company: str, market: str) -> pd.Series:
    if frame.empty or not {"company", "market"}.issubset(frame.columns):
        return pd.Series(dtype=object)
    rows = frame.loc[frame["company"].eq(company) & frame["market"].eq(market)]
    return rows.sort_values("eligibility_effective_date").iloc[-1] if not rows.empty else pd.Series(dtype=object)


def _hk_short_position_row(frame: pd.DataFrame, company: str, market: str) -> pd.Series:
    if frame.empty or market != "HK" or "company" not in frame.columns:
        return pd.Series(dtype=object)
    rows = frame.loc[frame["company"].eq(company)].copy()
    if rows.empty:
        return pd.Series(dtype=object)
    rows["_reporting_date"] = pd.to_datetime(rows["reporting_date"], errors="coerce")
    return rows.sort_values("_reporting_date").iloc[-1]


def _stock_connect_short_row(frame: pd.DataFrame, company: str, market: str) -> pd.Series:
    if frame.empty or market != "CN_A" or "company" not in frame.columns:
        return pd.Series(dtype=object)
    rows = frame.loc[frame["company"].eq(company)].copy()
    if rows.empty:
        return pd.Series(dtype=object)
    rows["_observation_date"] = pd.to_datetime(rows["observation_date"], errors="coerce")
    return rows.sort_values("_observation_date").iloc[-1]


def _chain_metric(frame: pd.DataFrame, company: str, metric: str) -> object:
    if frame.empty or not {"company", "canonical_metric"}.issubset(frame.columns):
        return None
    rows = frame.loc[frame["company"].eq(company) & frame["canonical_metric"].eq(metric)]
    if rows.empty:
        return None
    row = rows.sort_values("as_of_date").iloc[-1]
    return row.get("value_numeric") if pd.notna(row.get("value_numeric")) else row.get("value_text")


def _chain_metric_row(frame: pd.DataFrame, company: str, metric: str) -> pd.Series:
    if frame.empty or not {"company", "canonical_metric"}.issubset(frame.columns):
        return pd.Series(dtype=object)
    rows = frame.loc[frame["company"].eq(company) & frame["canonical_metric"].eq(metric)].copy()
    if rows.empty:
        return pd.Series(dtype=object)
    rows["_as_of"] = pd.to_datetime(rows.get("as_of_date"), errors="coerce")
    return rows.sort_values("_as_of").iloc[-1]


PAIR_DRIVER_METRICS = (
    ("latest_cargo_yield", "latest_report_cargo_yield_native"),
    ("latest_cargo_load_factor_pct", "latest_report_cargo_load_factor_pct"),
    ("latest_fuel_cost_per_ask", "latest_report_fuel_cost_per_ask_native"),
    ("latest_cost_per_atk_ex_fuel", "latest_report_cost_per_atk_ex_fuel_native"),
    ("latest_operating_cash_flow_native_mn", "latest_report_operating_cash_flow_native_mn"),
    ("latest_fuel_intensity", "latest_report_fuel_intensity_native"),
    ("latest_fuel_hedging_loss_gain_native_mn", "latest_report_fuel_hedging_loss_gain_native_mn"),
)


def _latest_driver_fields(
    frame: pd.DataFrame,
    company: str,
    readiness_row: pd.Series,
    suffix: str,
) -> dict[str, object]:
    fields: dict[str, object] = {
        f"latest_driver_period_{suffix}": readiness_row.get("latest_financial_period"),
        f"latest_driver_as_of_{suffix}": None,
        f"latest_driver_metric_count_{suffix}": 0,
    }
    driver_rows = frame.loc[
        frame.get("company", pd.Series(dtype=object)).eq(company)
        & frame.get("source_field", pd.Series(dtype=object)).astype(str).str.startswith(
            "airline_earnings_driver_comparability."
        )
    ].copy() if not frame.empty else pd.DataFrame()
    as_of = pd.to_datetime(driver_rows.get("as_of_date"), errors="coerce") if not driver_rows.empty else pd.Series(dtype="datetime64[ns]")
    if not as_of.dropna().empty:
        fields[f"latest_driver_as_of_{suffix}"] = as_of.max().strftime("%Y-%m-%d")
    for output_name, chain_metric in PAIR_DRIVER_METRICS:
        row = _chain_metric_row(frame, company, chain_metric)
        fields[f"{output_name}_{suffix}"] = row.get("value_numeric") if not row.empty else None
        fields[f"{output_name}_unit_{suffix}"] = row.get("unit") if not row.empty else None
        fields[f"{output_name}_currency_{suffix}"] = row.get("native_currency") if not row.empty else None
        if not row.empty and pd.notna(row.get("value_numeric")):
            fields[f"latest_driver_metric_count_{suffix}"] += 1
    return fields


def _operating_diagnostic_row(frame: pd.DataFrame, company: str, market: str) -> pd.Series:
    # The operating diagnostic is company-level and can be shown on either an
    # H-share or A-share leg of the same issuer pair.
    if frame.empty or "company" not in frame.columns:
        return pd.Series(dtype=object)
    rows = frame.loc[frame["company"].eq(company)].copy()
    if rows.empty:
        return pd.Series(dtype=object)
    return rows.sort_values("snapshot_date").iloc[-1]


def _range_width_vs_median(row: pd.Series, low: str, median: str, high: str) -> float | None:
    low_value = pd.to_numeric(row.get(low), errors="coerce")
    median_value = pd.to_numeric(row.get(median), errors="coerce")
    high_value = pd.to_numeric(row.get(high), errors="coerce")
    if pd.isna(low_value) or pd.isna(median_value) or pd.isna(high_value) or median_value == 0:
        return None
    return float(100 * (high_value - low_value) / abs(median_value))


def build_airline_pair_screening_matrix(
    *,
    pair_risk: pd.DataFrame | None = None,
    readiness: pd.DataFrame | None = None,
    short_proxies: pd.DataFrame | None = None,
    bridge: pd.DataFrame | None = None,
    dispersion: pd.DataFrame | None = None,
    short_eligibility: pd.DataFrame | None = None,
    hk_short_positions: pd.DataFrame | None = None,
    stock_connect_short_selling: pd.DataFrame | None = None,
    research_chain: pd.DataFrame | None = None,
    operating_diagnostics: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    pair_risk = pair_risk if pair_risk is not None else pd.read_csv(PAIR_RISK_PATH)
    readiness = readiness if readiness is not None else pd.read_csv(READINESS_PATH)
    short_proxies = short_proxies if short_proxies is not None else (
        pd.read_csv(SHORT_PROXY_PATH) if SHORT_PROXY_PATH.exists() else pd.DataFrame()
    )
    bridge = bridge if bridge is not None else (
        pd.read_csv(BRIDGE_PATH) if BRIDGE_PATH.exists() else pd.DataFrame()
    )
    dispersion = dispersion if dispersion is not None else (
        pd.read_csv(DISPERSION_PATH) if DISPERSION_PATH.exists() else pd.DataFrame()
    )
    short_eligibility = short_eligibility if short_eligibility is not None else (
        pd.read_csv(SHORT_ELIGIBILITY_PATH) if SHORT_ELIGIBILITY_PATH.exists() else pd.DataFrame()
    )
    hk_short_positions = hk_short_positions if hk_short_positions is not None else (
        pd.read_csv(HK_SHORT_POSITION_PATH) if HK_SHORT_POSITION_PATH.exists() else pd.DataFrame()
    )
    stock_connect_short_selling = stock_connect_short_selling if stock_connect_short_selling is not None else (
        pd.read_csv(STOCK_CONNECT_SHORT_PATH) if STOCK_CONNECT_SHORT_PATH.exists() else pd.DataFrame()
    )
    research_chain = research_chain if research_chain is not None else (
        pd.read_csv(RESEARCH_CHAIN_PATH) if RESEARCH_CHAIN_PATH.exists() else pd.DataFrame()
    )
    operating_diagnostics = operating_diagnostics if operating_diagnostics is not None else (
        pd.read_csv(OPERATING_DIAGNOSTICS_PATH) if OPERATING_DIAGNOSTICS_PATH.exists() else pd.DataFrame()
    )
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    for _, pair in pair_risk.iterrows():
        company_a = str(pair["company_a"])
        company_b = str(pair["company_b"])
        ready_a = _row(readiness, company_a)
        ready_b = _row(readiness, company_b)
        proxy_a = _proxy_row(short_proxies, company_a, str(pair["market_a"]))
        proxy_b = _proxy_row(short_proxies, company_b, str(pair["market_b"]))
        bridge_a = _bridge_row(bridge, company_a, str(pair["market_a"]))
        bridge_b = _bridge_row(bridge, company_b, str(pair["market_b"]))
        dispersion_a = _dispersion_row(dispersion, company_a)
        dispersion_b = _dispersion_row(dispersion, company_b)
        eligibility_a = _eligibility_row(short_eligibility, company_a, str(pair["market_a"]))
        eligibility_b = _eligibility_row(short_eligibility, company_b, str(pair["market_b"]))
        sfc_a = _hk_short_position_row(hk_short_positions, company_a, str(pair["market_a"]))
        sfc_b = _hk_short_position_row(hk_short_positions, company_b, str(pair["market_b"]))
        stock_connect_a = _stock_connect_short_row(
            stock_connect_short_selling, company_a, str(pair["market_a"])
        )
        stock_connect_b = _stock_connect_short_row(
            stock_connect_short_selling, company_b, str(pair["market_b"])
        )
        operating_a = _operating_diagnostic_row(
            operating_diagnostics, company_a, str(pair["market_a"])
        )
        operating_b = _operating_diagnostic_row(
            operating_diagnostics, company_b, str(pair["market_b"])
        )
        driver_fields_a = _latest_driver_fields(research_chain, company_a, ready_a, "a")
        driver_fields_b = _latest_driver_fields(research_chain, company_b, ready_b, "b")
        chain_metrics = {
            "rpk_minus_ask_growth_gap_pp": "rpk_minus_ask_growth_gap_pp",
            "implied_h2_profit_mid_native_mn": "implied_h2_profit_at_h1_warning_mid_native_mn",
            "historical_2h2025_profit_native_mn": "historical_2h2025_profit_native_mn",
            "implied_h2_mid_minus_historical_2h2025_native_mn": "implied_h2_mid_minus_historical_2h2025_native_mn",
        }
        core_fields = [
            "has_official_latest_financial_actual", "has_h1_demand_trend",
            "has_fuel_cost_driver", "has_market_expectation",
        ]
        core_a = all(bool(ready_a.get(field)) for field in core_fields)
        core_b = all(bool(ready_b.get(field)) for field in core_fields)
        data_status = "both_core_data_ready" if core_a and core_b else "missing_core_data_on_one_or_both_legs"
        evidence_a = bool(ready_a.get("has_revision_evidence"))
        evidence_b = bool(ready_b.get("has_revision_evidence"))
        expectation_status = (
            "both_have_dated_expectation_evidence" if evidence_a and evidence_b
            else "asymmetric_expectation_evidence" if evidence_a != evidence_b
            else "neither_has_dated_expectation_evidence"
        )
        stable_a = bool(ready_a.get("profit_base_stable"))
        stable_b = bool(ready_b.get("profit_base_stable"))
        profit_status = "both_stable" if stable_a and stable_b else "both_unstable" if not stable_a and not stable_b else "mixed_stability"
        catalyst_a = str(ready_a.get("formal_report_status"))
        catalyst_b = str(ready_b.get("formal_report_status"))
        catalyst_status = "both_disclosed_or_same_stage" if catalyst_a == catalyst_b else "asymmetric_report_stage"
        if data_status != "both_core_data_ready":
            screen_status = "monitor_data_gap"
        elif expectation_status == "asymmetric_expectation_evidence":
            screen_status = "monitor_expectation_gap"
        elif profit_status != "both_stable":
            screen_status = "monitor_profit_base_caveat"
        else:
            screen_status = "eligible_for_deep_dive_review"
        pair_id = "__".join(sorted([str(pair["asset_a"]), str(pair["asset_b"])]))
        rows.append({
            "dataset_id": "airline_pair_screening_matrix",
            "pair_id": pair_id,
            "asset_a": pair["asset_a"], "company_a": company_a, "market_a": pair["market_a"],
            "asset_b": pair["asset_b"], "company_b": company_b, "market_b": pair["market_b"],
            "same_market": pair["same_market"],
            "screen_snapshot_date": pair["snapshot_date"],
            "data_comparability_status": data_status,
            "expectation_comparability_status": expectation_status,
            "profit_base_status": profit_status,
            "catalyst_status": catalyst_status,
            "readiness_status_a": ready_a.get("pair_readiness_status"),
            "readiness_status_b": ready_b.get("pair_readiness_status"),
            "revision_evidence_band_a": ready_a.get("revision_evidence_band"),
            "revision_evidence_band_b": ready_b.get("revision_evidence_band"),
            "unified_estimate_revision_count_a": ready_a.get("unified_estimate_revision_count"),
            "unified_estimate_revision_count_b": ready_b.get("unified_estimate_revision_count"),
            "unified_up_revision_count_a": ready_a.get("unified_up_revision_count"),
            "unified_up_revision_count_b": ready_b.get("unified_up_revision_count"),
            "unified_down_revision_count_a": ready_a.get("unified_down_revision_count"),
            "unified_down_revision_count_b": ready_b.get("unified_down_revision_count"),
            "unified_revision_balance_a": (
                pd.to_numeric(ready_a.get("unified_up_revision_count"), errors="coerce")
                - pd.to_numeric(ready_a.get("unified_down_revision_count"), errors="coerce")
            ),
            "unified_revision_balance_b": (
                pd.to_numeric(ready_b.get("unified_up_revision_count"), errors="coerce")
                - pd.to_numeric(ready_b.get("unified_down_revision_count"), errors="coerce")
            ),
            "unified_latest_estimate_revision_date_a": ready_a.get("unified_latest_estimate_revision_date"),
            "unified_latest_estimate_revision_date_b": ready_b.get("unified_latest_estimate_revision_date"),
            "market_cap_to_consensus_revenue_a_usd": ready_a.get("market_cap_to_consensus_revenue_usd"),
            "market_cap_to_consensus_revenue_b_usd": ready_b.get("market_cap_to_consensus_revenue_usd"),
            "valuation_revenue_gap_a_minus_b": (
                pd.to_numeric(ready_a.get("market_cap_to_consensus_revenue_usd"), errors="coerce")
                - pd.to_numeric(ready_b.get("market_cap_to_consensus_revenue_usd"), errors="coerce")
            ),
            "consensus_net_margin_a_pct": ready_a.get("fy2026_consensus_net_margin_pct"),
            "consensus_net_margin_b_pct": ready_b.get("fy2026_consensus_net_margin_pct"),
            "consensus_net_margin_gap_a_minus_b_pct": (
                pd.to_numeric(ready_a.get("fy2026_consensus_net_margin_pct"), errors="coerce")
                - pd.to_numeric(ready_b.get("fy2026_consensus_net_margin_pct"), errors="coerce")
            ),
            "public_eps_count_a": dispersion_a.get("public_eps_count"),
            "public_eps_count_b": dispersion_b.get("public_eps_count"),
            "public_eps_median_a_rmb_per_share": dispersion_a.get("public_eps_median_native"),
            "public_eps_median_b_rmb_per_share": dispersion_b.get("public_eps_median_native"),
            "public_eps_range_width_pct_a": _range_width_vs_median(
                dispersion_a, "public_eps_low_native", "public_eps_median_native", "public_eps_high_native"
            ),
            "public_eps_range_width_pct_b": _range_width_vs_median(
                dispersion_b, "public_eps_low_native", "public_eps_median_native", "public_eps_high_native"
            ),
            "public_net_profit_count_a": dispersion_a.get("public_net_profit_count"),
            "public_net_profit_count_b": dispersion_b.get("public_net_profit_count"),
            "public_net_profit_median_a_rmb_100m": dispersion_a.get("public_net_profit_median_native"),
            "public_net_profit_median_b_rmb_100m": dispersion_b.get("public_net_profit_median_native"),
            "public_net_profit_range_width_pct_a": _range_width_vs_median(
                dispersion_a,
                "public_net_profit_low_native",
                "public_net_profit_median_native",
                "public_net_profit_high_native",
            ),
            "public_net_profit_range_width_pct_b": _range_width_vs_median(
                dispersion_b,
                "public_net_profit_low_native",
                "public_net_profit_median_native",
                "public_net_profit_high_native",
            ),
            "public_revenue_count_a": dispersion_a.get("public_revenue_count"),
            "public_revenue_count_b": dispersion_b.get("public_revenue_count"),
            "public_revenue_median_a_rmb_100m": dispersion_a.get("public_revenue_median_native"),
            "public_revenue_median_b_rmb_100m": dispersion_b.get("public_revenue_median_native"),
            "public_revenue_range_width_pct_a": _range_width_vs_median(
                dispersion_a, "public_revenue_low_native", "public_revenue_median_native", "public_revenue_high_native"
            ),
            "public_revenue_range_width_pct_b": _range_width_vs_median(
                dispersion_b, "public_revenue_low_native", "public_revenue_median_native", "public_revenue_high_native"
            ),
            "public_report_latest_date_a": dispersion_a.get("public_net_profit_latest_report_date"),
            "public_report_latest_date_b": dispersion_b.get("public_net_profit_latest_report_date"),
            "short_eligibility_status_a": eligibility_a.get("eligibility_status"),
            "short_eligibility_status_b": eligibility_b.get("eligibility_status"),
            "short_eligibility_effective_date_a": eligibility_a.get("eligibility_effective_date"),
            "short_eligibility_effective_date_b": eligibility_b.get("eligibility_effective_date"),
            "short_eligibility_source_quality_a": eligibility_a.get("source_quality"),
            "short_eligibility_source_quality_b": eligibility_b.get("source_quality"),
            "sfc_short_position_shares_a": sfc_a.get("short_position_shares"),
            "sfc_short_position_shares_b": sfc_b.get("short_position_shares"),
            "sfc_short_position_value_hkd_a": sfc_a.get("short_position_value_hkd"),
            "sfc_short_position_value_hkd_b": sfc_b.get("short_position_value_hkd"),
            "sfc_short_position_reporting_date_a": sfc_a.get("reporting_date"),
            "sfc_short_position_reporting_date_b": sfc_b.get("reporting_date"),
            "sfc_short_position_history_count_a": (
                int(hk_short_positions.loc[hk_short_positions["company"].eq(company_a)].shape[0])
                if not sfc_a.empty else None
            ),
            "sfc_short_position_history_count_b": (
                int(hk_short_positions.loc[hk_short_positions["company"].eq(company_b)].shape[0])
                if not sfc_b.empty else None
            ),
            "stock_connect_remaining_available_display_a": stock_connect_a.get("remaining_available_display"),
            "stock_connect_remaining_available_display_b": stock_connect_b.get("remaining_available_display"),
            "stock_connect_remaining_available_shares_a": stock_connect_a.get("remaining_available_shares"),
            "stock_connect_remaining_available_shares_b": stock_connect_b.get("remaining_available_shares"),
            "stock_connect_short_turnover_shares_a": stock_connect_a.get("short_selling_turnover_shares"),
            "stock_connect_short_turnover_shares_b": stock_connect_b.get("short_selling_turnover_shares"),
            "stock_connect_short_turnover_value_rmb_a": stock_connect_a.get("short_selling_turnover_value_rmb"),
            "stock_connect_short_turnover_value_rmb_b": stock_connect_b.get("short_selling_turnover_value_rmb"),
            "stock_connect_short_pct_today_a": stock_connect_a.get("short_selling_pct_today"),
            "stock_connect_short_pct_today_b": stock_connect_b.get("short_selling_pct_today"),
            "stock_connect_short_pct_10d_a": stock_connect_a.get("short_selling_pct_10d"),
            "stock_connect_short_pct_10d_b": stock_connect_b.get("short_selling_pct_10d"),
            "stock_connect_observation_date_a": stock_connect_a.get("observation_date"),
            "stock_connect_observation_date_b": stock_connect_b.get("observation_date"),
            "stock_connect_history_count_a": (
                int(stock_connect_short_selling.loc[stock_connect_short_selling["company"].eq(company_a)].shape[0])
                if not stock_connect_a.empty else None
            ),
            "stock_connect_history_count_b": (
                int(stock_connect_short_selling.loc[stock_connect_short_selling["company"].eq(company_b)].shape[0])
                if not stock_connect_b.empty else None
            ),
            **{
                f"{output_name}_a": _chain_metric(research_chain, company_a, metric)
                for output_name, metric in chain_metrics.items()
            },
            **{
                f"{output_name}_b": _chain_metric(research_chain, company_b, metric)
                for output_name, metric in chain_metrics.items()
            },
            "q2_rpk_minus_ask_gap_pp_a": operating_a.get("q2_rpk_minus_ask_gap_pp"),
            "q2_rpk_minus_ask_gap_pp_b": operating_b.get("q2_rpk_minus_ask_gap_pp"),
            "q2_passengers_yoy_pct_a": operating_a.get("q2_passengers_yoy_pct"),
            "q2_passengers_yoy_pct_b": operating_b.get("q2_passengers_yoy_pct"),
            "q2_passenger_lf_minus_q1_pp_a": operating_a.get("q2_passenger_lf_minus_q1_pp"),
            "q2_passenger_lf_minus_q1_pp_b": operating_b.get("q2_passenger_lf_minus_q1_pp"),
            "june_rpk_minus_ask_gap_pp_a": operating_a.get("june_rpk_minus_ask_gap_pp"),
            "june_rpk_minus_ask_gap_pp_b": operating_b.get("june_rpk_minus_ask_gap_pp"),
            "june_passenger_lf_yoy_pp_a": operating_a.get("june_passenger_lf_yoy_pp"),
            "june_passenger_lf_yoy_pp_b": operating_b.get("june_passenger_lf_yoy_pp"),
            **driver_fields_a,
            **driver_fields_b,
            "fuel_plus_5pct_profit_impact_usd_mn_a": _chain_metric(
                research_chain, company_a, "fuel_plus_5pct_profit_impact_usd_mn"
            ),
            "fuel_plus_5pct_profit_impact_usd_mn_b": _chain_metric(
                research_chain, company_b, "fuel_plus_5pct_profit_impact_usd_mn"
            ),
            "fuel_minus_5pct_profit_impact_usd_mn_a": _chain_metric(
                research_chain, company_a, "fuel_minus_5pct_profit_impact_usd_mn"
            ),
            "fuel_minus_5pct_profit_impact_usd_mn_b": _chain_metric(
                research_chain, company_b, "fuel_minus_5pct_profit_impact_usd_mn"
            ),
            "fuel_plus_5pct_scenario_method_a": _chain_metric(
                research_chain, company_a, "fuel_plus_5pct_scenario_method"
            ),
            "fuel_plus_5pct_scenario_method_b": _chain_metric(
                research_chain, company_b, "fuel_plus_5pct_scenario_method"
            ),
            "fuel_minus_5pct_scenario_method_a": _chain_metric(
                research_chain, company_a, "fuel_minus_5pct_scenario_method"
            ),
            "fuel_minus_5pct_scenario_method_b": _chain_metric(
                research_chain, company_b, "fuel_minus_5pct_scenario_method"
            ),
            "fuel_surcharge_context_a": _chain_metric(
                research_chain, company_a, "fuel_surcharge_context"
            ),
            "fuel_surcharge_context_b": _chain_metric(
                research_chain, company_b, "fuel_surcharge_context"
            ),
            "fuel_scenario_fx_observation_date_a": _chain_metric(
                research_chain, company_a, "fuel_scenario_fx_observation_date"
            ),
            "fuel_scenario_fx_observation_date_b": _chain_metric(
                research_chain, company_b, "fuel_scenario_fx_observation_date"
            ),
            "debt_to_assets_a_pct": bridge_a.get("latest_discovery_debt_to_assets_pct"),
            "debt_to_assets_b_pct": bridge_b.get("latest_discovery_debt_to_assets_pct"),
            "debt_to_assets_gap_a_minus_b_pct": (
                pd.to_numeric(bridge_a.get("latest_discovery_debt_to_assets_pct"), errors="coerce")
                - pd.to_numeric(bridge_b.get("latest_discovery_debt_to_assets_pct"), errors="coerce")
            ),
            "primary_liabilities_to_assets_a_pct": bridge_a.get("latest_report_liabilities_to_assets_pct"),
            "primary_liabilities_to_assets_b_pct": bridge_b.get("latest_report_liabilities_to_assets_pct"),
            "primary_liabilities_to_assets_gap_a_minus_b_pct": (
                pd.to_numeric(bridge_a.get("latest_report_liabilities_to_assets_pct"), errors="coerce")
                - pd.to_numeric(bridge_b.get("latest_report_liabilities_to_assets_pct"), errors="coerce")
            ),
            "correlation_a_b": pair.get("correlation_a_b"),
            "beta_a_to_b": pair.get("beta_a_to_b"),
            "beta_b_to_a": pair.get("beta_b_to_a"),
            "hedged_spread_vol_a_minus_beta_b_pct": pair.get("hedged_spread_vol_a_minus_beta_b_pct"),
            "hedged_spread_max_drawdown_a_minus_beta_b_pct": pair.get("hedged_spread_max_drawdown_a_minus_beta_b_pct"),
            "median_turnover_a_usd_mn_60d": pair.get("median_turnover_a_usd_mn_60d"),
            "median_turnover_b_usd_mn_60d": pair.get("median_turnover_b_usd_mn_60d"),
            "borrow_data_available_a": pair.get("borrow_data_available_a"),
            "borrow_data_available_b": pair.get("borrow_data_available_b"),
            "screen_status": screen_status,
            "short_proxy_status_a": proxy_a.get("short_proxy_status"),
            "short_proxy_status_b": proxy_b.get("short_proxy_status"),
            "short_proxy_observation_date_a": proxy_a.get("observation_date"),
            "short_proxy_observation_date_b": proxy_b.get("observation_date"),
            "source_quality": "derived_screening_matrix",
            "source_note": (
                "Non-directional pair screening matrix. It combines data-readiness, expectation evidence, "
                "profit-base and catalyst comparability with mechanical pair-risk diagnostics; it is not a "
                "long/short recommendation, factor-neutral portfolio or borrow-feasibility assessment. "
                "Debt-to-assets fields are optional A-share provider discovery context; primary-liabilities-to-assets "
                "fields are separately sourced from issuer reports and retain missingness where the report-period "
                "balance-sheet anchor is not available or scopes are not comparable. "
                "Public-report dispersion fields are per-leg institution ranges in native RMB; EPS is RMB/share, "
                "profit and revenue are RMB 100m. Revenue evidence is page-snapshot-only and all fields are "
                "descriptive expectation dispersion, not directional signals. "
                "Short-eligibility fields record exchange-list or margin-detail evidence only and do not establish "
                "locatable borrow. "
                "SFC short-position fields are HK-only aggregate reportable-position crowding proxies; they are "
                "not total short interest or locatable borrow. "
                "Stock Connect fields are A-share HKEX dissemination proxies; a literal 'Available' is not a "
                "numeric balance and these fields do not establish locatable borrow or broker execution access. "
                "Demand-capacity and implied-2H fields are descriptive chain diagnostics; the latter subtracts "
                "a preliminary H1 warning from FY2026 consensus and is not a forecast. "
                "Q2/June operating diagnostics come from equal-period monthly issuer releases and do not infer yield. "
                "Latest driver fields are joined from the comparable-period issuer-driver layer; native values "
                "must be read with their per-leg unit, currency, period and as-of metadata, and disclosed/derived "
                "status is not converted into a directional signal. Fuel-shock impacts are mechanical USD "
                "scenario proxies and surcharge fields are policy/route context, not realized recovery. "
                "Short-side proxy fields are public turnover/margin observations, not locatable borrow."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_pair_screening_matrix() -> pd.DataFrame:
    result = build_airline_pair_screening_matrix()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
