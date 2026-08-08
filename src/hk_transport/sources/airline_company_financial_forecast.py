"""Non-directional company financial forecast bridge for airline research.

The bridge converts observed FY2025 unit economics and preliminary H1 2026
operating anchors into transparent FY2026 bear/base/bull driver cases. It is
not issuer guidance, a broker forecast, or a long/short construction layer.
Juneyao rows are consolidated-group rows and therefore include the unresolved
9 Air scope. 9 Air is retained as a pending row because standalone financial
inputs are not disclosed in the covered source set.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

MODEL_INPUTS_PATH = NORMALIZED_DIR / "airline_core_pair_model_inputs.csv"
EXPECTATION_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
ASSUMPTION_PATH = NORMALIZED_DIR / "airline_forecast_assumptions.csv"
FUEL_PATH = NORMALIZED_DIR / "airline_fuel_sensitivity_scenarios.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_company_financial_forecast_bridge.csv"

COMPANIES = ("Spring Airlines", "Juneyao Airlines", "9 Air")
SCENARIOS = ("bear", "base", "bull")
FUEL_SHOCK = {"bear": 5.0, "base": 0.0, "bull": -5.0}


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _latest_date(frames: list[pd.DataFrame | None]) -> str:
    dates: list[str] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for column in ("as_of_date", "snapshot_date", "source_as_of_date"):
            if column in frame.columns:
                dates.extend(str(value)[:10] for value in frame[column].dropna())
    valid = [date for date in dates if len(date) == 10 and date[4] == "-" and date[7] == "-"]
    return max(valid) if valid else "pending"


def _assumption_value(
    assumptions: pd.DataFrame,
    company: str,
    scenario: str,
    driver: str,
) -> float | None:
    rows = assumptions[
        assumptions["entity"].eq(company)
        & assumptions["scenario"].eq(scenario)
        & assumptions["driver"].eq(driver)
    ]
    return _num(rows.iloc[0]["assumption_value"]) if not rows.empty else None


def _fuel_impact(fuel: pd.DataFrame, company: str, shock: float) -> tuple[float, str]:
    if shock == 0:
        return 0.0, "explicit_zero_base_case"
    rows = fuel[
        fuel["company"].eq(company)
        & pd.to_numeric(fuel["scenario_fuel_price_change_pct"], errors="coerce").eq(shock)
    ]
    if rows.empty:
        return 0.0, "missing_fuel_sensitivity_row_treated_as_zero_only_for_pending_output"
    row = rows.iloc[0]
    return _num(row.get("pre_tax_profit_impact_usd_mn")) or 0.0, str(row.get("source_quality", "derived"))


def _pending_row(company: str, scenario: str, as_of: str, retrieved: str, exp: pd.Series) -> dict[str, object]:
    parent = "Juneyao Airlines" if company == "9 Air" else company
    return {
        "dataset_id": "airline_company_financial_forecast_bridge",
        "entity_scope": "subsidiary_operating_scope_pending_financials" if company == "9 Air" else "group_consolidated",
        "company": company,
        "parent_group": parent,
        "ticker": str(exp.get("market_ticker", "603885.SH")) if company == "9 Air" else str(exp.get("market_ticker", "")),
        "scenario": scenario,
        "forecast_horizon": "FY2026_pre_interim",
        "as_of_date": as_of,
        "forecast_status": "pending_standalone_financial_disclosure",
        "actual_fy2025_source_path": str(MODEL_INPUTS_PATH),
        "consensus_source_path": str(EXPECTATION_PATH),
        "assumption_source_path": str(ASSUMPTION_PATH),
        "fuel_source_path": str(FUEL_PATH),
        "source_quality": "pending_scope_data",
        "source_note": "9 Air operating KPIs and route capacity exist, but no standalone revenue, operating cost, RASK/CASK or profit forecast is available in the covered source set; do not infer zero.",
        "retrieved_at": retrieved,
    }


def build_airline_company_financial_forecast_bridge(
    *,
    model_inputs: pd.DataFrame | None = None,
    expectations: pd.DataFrame | None = None,
    assumptions: pd.DataFrame | None = None,
    fuel: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build three mechanical FY2026 scenarios for Spring, Juneyao and 9 Air."""
    model_inputs = model_inputs if model_inputs is not None else pd.read_csv(MODEL_INPUTS_PATH)
    expectations = expectations if expectations is not None else pd.read_csv(EXPECTATION_PATH)
    assumptions = assumptions if assumptions is not None else pd.read_csv(ASSUMPTION_PATH)
    fuel = fuel if fuel is not None else pd.read_csv(FUEL_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    as_of = _latest_date([model_inputs, expectations, assumptions, fuel])
    rows: list[dict[str, object]] = []

    for company in COMPANIES:
        model_match = model_inputs[model_inputs["company"].eq(company)]
        exp_match = expectations[expectations["company"].eq(company)]
        model = model_match.iloc[0] if not model_match.empty else pd.Series(dtype=object)
        exp = exp_match.iloc[0] if not exp_match.empty else pd.Series(dtype=object)
        if company == "9 Air" or model.empty:
            for scenario in SCENARIOS:
                rows.append(_pending_row(company, scenario, as_of, retrieved, exp))
            continue

        fy_revenue_usd = _num(model.get("fy2025_revenue_usd_mn"))
        fy_profit_usd = _num(model.get("fy2025_attributable_profit_usd_mn"))
        fy_cost_usd = _num(model.get("fy2025_operating_cost_usd_mn"))
        fy_ask = _num(model.get("fy2025_ask_mn_seat_km"))
        fy_rpk = _num(model.get("fy2025_rpk_mn_passenger_km"))
        fy_rask = _num(model.get("fy2025_rask_proxy_rmb_per_ask"))
        fy_cask = _num(model.get("fy2025_cask_rmb_per_ask"))
        native_revenue = _num(exp.get("latest_report_revenue_native_mn"))
        fx_native_per_usd = native_revenue / fy_revenue_usd if native_revenue and fy_revenue_usd else None
        actual_operating_profit = fy_revenue_usd - fy_cost_usd if fy_revenue_usd is not None and fy_cost_usd is not None else None
        net_to_operating = fy_profit_usd / actual_operating_profit if fy_profit_usd is not None and actual_operating_profit and actual_operating_profit > 0 else None

        consensus_revenue = _num(exp.get("fy2026_revenue_avg_usd_mn"))
        consensus_profit = _num(exp.get("fy2026_net_profit_avg_usd_mn"))
        consensus_margin = _num(exp.get("fy2026_consensus_net_margin_pct"))
        actual_lf = 100.0 * fy_rpk / fy_ask if fy_rpk and fy_ask else None

        for scenario in SCENARIOS:
            rpk_growth = _assumption_value(assumptions, company, scenario, "rpk_growth_pct")
            ask_growth = _assumption_value(assumptions, company, scenario, "ask_growth_pct")
            rask_growth = _assumption_value(assumptions, company, scenario, "rask_growth_pct_vs_fy2025")
            cask_growth = _assumption_value(assumptions, company, scenario, "cask_growth_pct_vs_fy2025")
            forecast_ask = fy_ask * (1.0 + ask_growth / 100.0) if fy_ask is not None and ask_growth is not None else None
            forecast_rpk = fy_rpk * (1.0 + rpk_growth / 100.0) if fy_rpk is not None and rpk_growth is not None else None
            forecast_lf = 100.0 * forecast_rpk / forecast_ask if forecast_rpk is not None and forecast_ask else None
            forecast_rask = fy_rask * (1.0 + rask_growth / 100.0) if fy_rask is not None and rask_growth is not None else None
            forecast_cask = fy_cask * (1.0 + cask_growth / 100.0) if fy_cask is not None and cask_growth is not None else None
            revenue_native = forecast_ask * forecast_rask if forecast_ask is not None and forecast_rask is not None else None
            cost_native = forecast_ask * forecast_cask if forecast_ask is not None and forecast_cask is not None else None
            operating_profit_native = revenue_native - cost_native if revenue_native is not None and cost_native is not None else None
            revenue_usd = revenue_native / fx_native_per_usd if revenue_native is not None and fx_native_per_usd else None
            cost_usd = cost_native / fx_native_per_usd if cost_native is not None and fx_native_per_usd else None
            operating_profit_usd = operating_profit_native / fx_native_per_usd if operating_profit_native is not None and fx_native_per_usd else None
            earnings_before_fuel = operating_profit_usd * net_to_operating if operating_profit_usd is not None and net_to_operating is not None else None
            fuel_impact_pre_tax, fuel_quality = _fuel_impact(fuel, company, FUEL_SHOCK[scenario])
            fuel_impact_earnings = fuel_impact_pre_tax * net_to_operating if net_to_operating is not None else None
            earnings_after_fuel = earnings_before_fuel + fuel_impact_earnings if earnings_before_fuel is not None and fuel_impact_earnings is not None else None
            rows.append({
                "dataset_id": "airline_company_financial_forecast_bridge",
                "entity_scope": "group_consolidated",
                "company": company,
                "parent_group": company,
                "ticker": str(model.get("ticker", exp.get("market_ticker", ""))),
                "scenario": scenario,
                "forecast_horizon": "FY2026_pre_interim",
                "as_of_date": as_of,
                "forecast_status": "mechanical_driver_bridge_not_issuer_forecast",
                "fy2025_revenue_usd_mn": fy_revenue_usd,
                "fy2025_attributable_profit_usd_mn": fy_profit_usd,
                "fy2025_operating_cost_usd_mn": fy_cost_usd,
                "fy2025_ask_mn_seat_km": fy_ask,
                "fy2025_rpk_mn_passenger_km": fy_rpk,
                "fy2025_load_factor_pct": actual_lf,
                "fy2025_rask_proxy_rmb_per_ask": fy_rask,
                "fy2025_cask_rmb_per_ask": fy_cask,
                "actual_operating_profit_usd_mn": actual_operating_profit,
                "net_to_operating_profit_conversion": net_to_operating,
                "rpk_growth_assumption_pct": rpk_growth,
                "ask_growth_assumption_pct": ask_growth,
                "rask_growth_assumption_pct_vs_fy2025": rask_growth,
                "cask_growth_assumption_pct_vs_fy2025": cask_growth,
                "forecast_ask_mn_seat_km": forecast_ask,
                "forecast_rpk_mn_passenger_km": forecast_rpk,
                "forecast_load_factor_pct": forecast_lf,
                "forecast_load_factor_change_pp": forecast_lf - actual_lf if forecast_lf is not None and actual_lf is not None else None,
                "forecast_rask_proxy_rmb_per_ask": forecast_rask,
                "forecast_cask_rmb_per_ask": forecast_cask,
                "forecast_revenue_native_mn": revenue_native,
                "forecast_operating_cost_native_mn": cost_native,
                "forecast_operating_profit_native_mn": operating_profit_native,
                "forecast_revenue_usd_mn": revenue_usd,
                "forecast_operating_cost_usd_mn": cost_usd,
                "forecast_operating_profit_usd_mn": operating_profit_usd,
                "earnings_proxy_before_fuel_usd_mn": earnings_before_fuel,
                "fuel_shock_pct": FUEL_SHOCK[scenario],
                "fuel_overlay_pre_tax_usd_mn": fuel_impact_pre_tax,
                "fuel_overlay_earnings_usd_mn": fuel_impact_earnings,
                "earnings_proxy_after_fuel_usd_mn": earnings_after_fuel,
                "consensus_fy2026_revenue_usd_mn": consensus_revenue,
                "consensus_fy2026_profit_usd_mn": consensus_profit,
                "consensus_fy2026_net_margin_pct": consensus_margin,
                "revenue_gap_to_consensus_pct": 100.0 * revenue_usd / consensus_revenue - 100.0 if revenue_usd is not None and consensus_revenue else None,
                "earnings_gap_to_consensus_pct": 100.0 * earnings_after_fuel / consensus_profit - 100.0 if earnings_after_fuel is not None and consensus_profit else None,
                "implied_earnings_margin_pct": 100.0 * earnings_after_fuel / revenue_usd if earnings_after_fuel is not None and revenue_usd else None,
                "consensus_revenue_analyst_count": _num(exp.get("fy2026_revenue_analyst_count")),
                "consensus_revenue_freshness": str(exp.get("revenue_consensus_freshness_band", "pending")),
                "consensus_profit_freshness": str(exp.get("profit_consensus_freshness_band", "pending")),
                "consensus_profit_age_days": _num(exp.get("profit_consensus_age_days")),
                "formal_report_scheduled_date": str(exp.get("formal_report_scheduled_date", "")),
                "actual_fx_native_per_usd": fx_native_per_usd,
                "fx_observation_date": "2025-12-31",
                "fx_translation_method": "FY2025 reported native revenue divided by FY2025 USD translation; held constant for display and not a forward-FX view",
                "model_scope_note": "Juneyao financials are consolidated and include 9 Air; RASK/CASK are group proxies, not mainline standalone metrics",
                "profit_proxy_note": "Earnings proxy applies FY2025 net-profit/operating-profit conversion to modelled operating profit; fuel overlay is pre-tax sensitivity converted by the same ratio; not net-income guidance",
                "actual_fy2025_source_path": str(MODEL_INPUTS_PATH),
                "actual_fy2025_source_url": str(model.get("official_fy2025_source_url", "")),
                "consensus_source_path": str(EXPECTATION_PATH),
                "assumption_source_path": str(ASSUMPTION_PATH),
                "fuel_source_path": str(FUEL_PATH),
                "fuel_source_quality": fuel_quality,
                "source_quality": "derived_multi_source_mechanical_bridge",
                "source_note": str(model.get("source_note", "")),
                "retrieved_at": retrieved,
            })
    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_company_financial_forecast_bridge() -> pd.DataFrame:
    return build_airline_company_financial_forecast_bridge()
