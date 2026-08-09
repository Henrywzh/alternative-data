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
DRIVERS_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
SECTOR_TREND_PATH = NORMALIZED_DIR / "airline_sector_trend_snapshot.csv"
VALUATION_BANDS_PATH = NORMALIZED_DIR / "airline_historical_valuation_bands.csv"
ASSUMPTION_PATH = NORMALIZED_DIR / "airline_forecast_assumptions.csv"
FUEL_PATH = NORMALIZED_DIR / "airline_fuel_sensitivity_scenarios.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_company_financial_forecast_bridge.csv"

COMPANIES = (
    "Spring Airlines",
    "Juneyao Airlines",
    "China Southern Airlines",
    "China Eastern Airlines",
    "Air China",
    "Hainan Airlines Holdings",
    "9 Air",
)
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


def _get_official_driver(drivers: pd.DataFrame, company: str, metric: str) -> tuple[float | None, float | None]:
    if drivers.empty or "company" not in drivers.columns:
        return None, None
    sub = drivers[(drivers["company"].eq(company)) & (drivers["statement_period"].eq("FY2025")) & (drivers["metric"].eq(metric))]
    if sub.empty:
        return None, None
    row = sub.iloc[0]
    return _num(row.get("value_native")), _num(row.get("value_usd"))


def _get_official_source_url(drivers: pd.DataFrame, company: str, metric: str) -> str:
    if drivers.empty or "company" not in drivers.columns:
        return ""
    sub = drivers[
        (drivers["company"].eq(company))
        & (drivers["statement_period"].eq("FY2025"))
        & (drivers["metric"].eq(metric))
    ]
    if sub.empty:
        return ""
    return str(sub.iloc[0].get("source_url", ""))


def _select_expectation(expectations: pd.DataFrame, company: str) -> pd.Series:
    """Select the latest expectation row, preferring the A-share leg for mainland names."""
    if expectations.empty or "company" not in expectations.columns:
        return pd.Series(dtype=object)
    rows = expectations[expectations["company"].eq(company)].copy()
    if rows.empty:
        return pd.Series(dtype=object)
    if company != "Cathay Pacific" and "market" in rows.columns:
        a_share = rows[rows["market"].eq("CN_A")]
        if not a_share.empty:
            rows = a_share
    sort_columns = [column for column in ("snapshot_date", "retrieved_at") if column in rows.columns]
    if sort_columns:
        rows = rows.sort_values(sort_columns, ascending=False, kind="stable")
    return rows.iloc[0]


def _h1_cargo_growth(sector_trend: pd.DataFrame, company: str) -> float | None:
    """Return a usable H1 cargo-tonne growth proxy, excluding flagged anomalies."""
    if sector_trend.empty or "company" not in sector_trend.columns:
        return None
    rows = sector_trend[
        sector_trend["company"].eq(company)
        & sector_trend.get("metric", pd.Series(index=sector_trend.index, dtype=object)).eq("cargo_tonnes")
        & sector_trend.get("current_period", pd.Series(index=sector_trend.index, dtype=object)).eq("2026H1")
    ]
    if rows.empty:
        return None
    row = rows.iloc[0]
    quality_flag = str(row.get("quality_flag", ""))
    if "review" in quality_flag or "anomaly" in quality_flag:
        return None
    return _num(row.get("yoy_change_pct"))


def _historical_ps_median(
    valuation_bands: pd.DataFrame,
    company: str,
    selected_market: str,
    window: str = "3y",
) -> tuple[float | None, str, str]:
    """Return a historical P/S median and make cross-market fallback explicit."""
    if valuation_bands.empty or "company" not in valuation_bands.columns:
        return None, "", "missing_historical_ps_band"
    rows = valuation_bands[
        valuation_bands["company"].eq(company)
        & valuation_bands["metric"].eq("ps_annual_period_end")
        & valuation_bands["window"].eq(window)
    ].copy()
    if rows.empty:
        return None, "", "missing_historical_ps_band"
    same_market = rows[rows["market"].eq(selected_market)] if selected_market else pd.DataFrame()
    if not same_market.empty:
        row = same_market.iloc[0]
        return _num(row.get("median_value")), str(row.get("market", "")), "same_market_historical_ps_band"
    row = rows.iloc[0]
    return _num(row.get("median_value")), str(row.get("market", "")), "same_company_cross_market_historical_ps_band"


def _assumption_source(assumptions: pd.DataFrame, expectations: pd.DataFrame, company: str, driver: str) -> str:
    if not assumptions.empty and {"entity", "driver"}.issubset(assumptions.columns):
        if not assumptions[
            assumptions["entity"].eq(company) & assumptions["driver"].eq(driver)
        ].empty:
            return "company_assumption_file"
    if driver in {"ask_growth_pct", "rpk_growth_pct"} and not _select_expectation(expectations, company).empty:
        return "h1_issuer_operating_anchor_proxy"
    return "transparent_unit_economics_proxy"


def _assumption_value(
    assumptions: pd.DataFrame,
    expectations: pd.DataFrame,
    company: str,
    scenario: str,
    driver: str,
) -> float | None:
    if not assumptions.empty and {"entity", "scenario", "driver"}.issubset(assumptions.columns):
        rows = assumptions[
            assumptions["entity"].eq(company)
            & assumptions["scenario"].eq(scenario)
            & assumptions["driver"].eq(driver)
        ]
        if not rows.empty and pd.notna(rows.iloc[0]["assumption_value"]):
            return _num(rows.iloc[0]["assumption_value"])

    latest_exp = _select_expectation(expectations, company)

    if driver == "rpk_growth_pct":
        h1_rpk = _num(latest_exp.get("h1_rpk_yoy_pct"))
        if h1_rpk is not None:
            delta = {"bear": -3.0, "base": 0.0, "bull": 3.0}[scenario]
            return h1_rpk + delta
        if not assumptions.empty:
            sector_rows = assumptions[
                assumptions["entity"].eq("China mainland listed airlines")
                & assumptions["scenario"].eq(scenario)
                & assumptions["driver"].eq("demand_rpk_growth_pct")
            ]
            if not sector_rows.empty:
                return _num(sector_rows.iloc[0]["assumption_value"])

    if driver == "ask_growth_pct":
        h1_ask = _num(latest_exp.get("h1_ask_yoy_pct"))
        if h1_ask is not None:
            delta = {"bear": 3.0, "base": 0.0, "bull": -3.0}[scenario]
            return h1_ask + delta
        if not assumptions.empty:
            sector_rows = assumptions[
                assumptions["entity"].eq("China mainland listed airlines")
                & assumptions["scenario"].eq(scenario)
                & assumptions["driver"].eq("capacity_ask_growth_pct")
            ]
            if not sector_rows.empty:
                return _num(sector_rows.iloc[0]["assumption_value"])

    if driver == "rask_growth_pct_vs_fy2025":
        return {"bear": -2.0, "base": 0.0, "bull": 2.0}[scenario]

    if driver == "cask_growth_pct_vs_fy2025":
        return {"bear": 2.0, "base": 0.0, "bull": -1.0}[scenario]

    return None


def _fuel_impact(fuel: pd.DataFrame, company: str, shock: float) -> tuple[float, str]:
    if shock == 0:
        return 0.0, "explicit_zero_base_case"
    if fuel.empty or "company" not in fuel.columns:
        return 0.0, "missing_fuel_sensitivity_data"
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
    drivers: pd.DataFrame | None = None,
    sector_trend: pd.DataFrame | None = None,
    valuation_bands: pd.DataFrame | None = None,
    assumptions: pd.DataFrame | None = None,
    fuel: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build three mechanical FY2026 scenarios across 6 mainland carriers and pending 9 Air."""
    model_inputs = model_inputs if model_inputs is not None else (pd.read_csv(MODEL_INPUTS_PATH) if MODEL_INPUTS_PATH.exists() else pd.DataFrame())
    expectations = expectations if expectations is not None else (pd.read_csv(EXPECTATION_PATH) if EXPECTATION_PATH.exists() else pd.DataFrame())
    drivers = drivers if drivers is not None else (pd.read_csv(DRIVERS_PATH) if DRIVERS_PATH.exists() else pd.DataFrame())
    sector_trend = sector_trend if sector_trend is not None else (pd.read_csv(SECTOR_TREND_PATH) if SECTOR_TREND_PATH.exists() else pd.DataFrame())
    valuation_bands = valuation_bands if valuation_bands is not None else (pd.read_csv(VALUATION_BANDS_PATH) if VALUATION_BANDS_PATH.exists() else pd.DataFrame())
    assumptions = assumptions if assumptions is not None else (pd.read_csv(ASSUMPTION_PATH) if ASSUMPTION_PATH.exists() else pd.DataFrame())
    fuel = fuel if fuel is not None else (pd.read_csv(FUEL_PATH) if FUEL_PATH.exists() else pd.DataFrame())
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    as_of = _latest_date([model_inputs, expectations, drivers, sector_trend, valuation_bands, assumptions, fuel])
    rows: list[dict[str, object]] = []

    for company in COMPANIES:
        model_match = model_inputs[model_inputs["company"].eq(company)] if not model_inputs.empty and "company" in model_inputs.columns else pd.DataFrame()
        exp = _select_expectation(expectations, company)

        if company == "9 Air":
            for scenario in SCENARIOS:
                rows.append(_pending_row(company, scenario, as_of, retrieved, exp))
            continue

        model = model_match.iloc[0] if not model_match.empty else pd.Series(dtype=object)

        fy_revenue_usd = _num(model.get("fy2025_revenue_usd_mn"))
        fy_profit_usd = _num(model.get("fy2025_attributable_profit_usd_mn"))
        fy_cost_usd = _num(model.get("fy2025_operating_cost_usd_mn"))
        fy_ask = _num(model.get("fy2025_ask_mn_seat_km"))
        fy_rpk = _num(model.get("fy2025_rpk_mn_passenger_km"))
        fy_rask = _num(model.get("fy2025_rask_proxy_rmb_per_ask"))
        fy_cask = _num(model.get("fy2025_cask_rmb_per_ask"))

        native_revenue = _num(exp.get("latest_report_revenue_native_mn"))
        native_cost = _num(exp.get("latest_report_operating_cost_native_mn"))
        native_profit = _num(exp.get("latest_report_attributable_profit_native_mn"))

        official_revenue_native, official_revenue_usd = _get_official_driver(drivers, company, "total_revenue")
        if official_revenue_native is not None:
            native_revenue = official_revenue_native
        if official_revenue_usd is not None:
            fy_revenue_usd = official_revenue_usd

        if fy_revenue_usd is None:
            fy_revenue_usd = official_revenue_usd
            if native_revenue is None:
                native_revenue = official_revenue_native

        if fy_cost_usd is None:
            cost_n, cost_u = _get_official_driver(drivers, company, "operating_cost")
            fy_cost_usd = cost_u
            if native_cost is None:
                native_cost = cost_n

        if fy_profit_usd is None:
            profit_n, profit_u = _get_official_driver(drivers, company, "attributable_net_income")
            fy_profit_usd = profit_u
            if native_profit is None:
                native_profit = profit_n

        if fy_ask is None:
            ask_n, _ = _get_official_driver(drivers, company, "ask")
            fy_ask = ask_n

        if fy_rpk is None:
            rpk_n, _ = _get_official_driver(drivers, company, "rpk")
            fy_rpk = rpk_n

        if fy_cask is None:
            cask_n, _ = _get_official_driver(drivers, company, "cask_derived")
            fy_cask = cask_n

        if fy_rask is None:
            rask_n, _ = _get_official_driver(drivers, company, "rask_derived")
            if rask_n is None and native_revenue is not None and fy_ask:
                rask_n = native_revenue / fy_ask
            fy_rask = rask_n

        passenger_revenue_native, _ = _get_official_driver(drivers, company, "passenger_revenue")
        passenger_yield_native, _ = _get_official_driver(drivers, company, "passenger_yield")
        passenger_revenue_method = "issuer_reported_passenger_revenue"
        if passenger_revenue_native is None and passenger_yield_native is not None and fy_rpk is not None:
            passenger_revenue_native = passenger_yield_native * fy_rpk
            passenger_revenue_method = "derived_passenger_yield_times_rpk"
        if passenger_revenue_native is None and fy_rask is not None and fy_ask is not None:
            passenger_revenue_native = fy_rask * fy_ask
            passenger_revenue_method = "derived_passenger_rask_times_ask"
        nonpassenger_revenue_native = (
            native_revenue - passenger_revenue_native
            if native_revenue is not None and passenger_revenue_native is not None
            else None
        )
        total_revenue_per_ask = (
            native_revenue / fy_ask if native_revenue is not None and fy_ask else None
        )

        if fy_revenue_usd is None or fy_ask is None or fy_rask is None or fy_cask is None:
            for scenario in SCENARIOS:
                rows.append(_pending_row(company, scenario, as_of, retrieved, exp))
            continue

        fx_native_per_usd = native_revenue / fy_revenue_usd if native_revenue and fy_revenue_usd else 7.00
        actual_operating_profit_usd = fy_revenue_usd - fy_cost_usd if fy_revenue_usd is not None and fy_cost_usd is not None else None

        actual_margin = fy_profit_usd / fy_revenue_usd if fy_profit_usd is not None and fy_revenue_usd else None
        consensus_revenue = _num(exp.get("fy2026_revenue_avg_usd_mn"))
        consensus_profit = _num(exp.get("fy2026_net_profit_avg_usd_mn"))
        consensus_margin = _num(exp.get("fy2026_consensus_net_margin_pct"))
        selected_market = str(exp.get("market", ""))
        market_cap_usd = _num(exp.get("market_cap_usd_mn"))
        market_cap_to_consensus_revenue = _num(exp.get("market_cap_to_consensus_revenue_usd"))
        historical_ps_median, historical_ps_market, historical_ps_status = _historical_ps_median(
            valuation_bands, company, selected_market, window="3y"
        )
        market_implied_revenue_usd = (
            market_cap_usd / historical_ps_median
            if market_cap_usd is not None and historical_ps_median and historical_ps_median > 0
            else None
        )
        actual_lf = 100.0 * fy_rpk / fy_ask if fy_rpk and fy_ask else None

        if fy_profit_usd is not None and fy_profit_usd > 0 and actual_operating_profit_usd and actual_operating_profit_usd > 0:
            profit_proxy_method = "positive_FY2025_operating_to_net_conversion"
            net_to_operating = fy_profit_usd / actual_operating_profit_usd
        elif consensus_margin is not None:
            profit_proxy_method = "consensus_margin_fallback_unprofitable_FY2025"
            net_to_operating = consensus_margin / 100.0
        elif actual_margin is not None:
            profit_proxy_method = "actual_margin_carry_unprofitable_FY2025"
            net_to_operating = actual_margin
        else:
            profit_proxy_method = "profit_proxy_unavailable"
            net_to_operating = None

        for scenario in SCENARIOS:
            rpk_growth = _assumption_value(assumptions, expectations, company, scenario, "rpk_growth_pct")
            ask_growth = _assumption_value(assumptions, expectations, company, scenario, "ask_growth_pct")
            rask_growth = _assumption_value(assumptions, expectations, company, scenario, "rask_growth_pct_vs_fy2025")
            cask_growth = _assumption_value(assumptions, expectations, company, scenario, "cask_growth_pct_vs_fy2025")

            forecast_ask = fy_ask * (1.0 + ask_growth / 100.0) if fy_ask is not None and ask_growth is not None else None
            forecast_rpk = fy_rpk * (1.0 + rpk_growth / 100.0) if fy_rpk is not None and rpk_growth is not None else None
            forecast_lf = 100.0 * forecast_rpk / forecast_ask if forecast_rpk is not None and forecast_ask else None
            forecast_rask = fy_rask * (1.0 + rask_growth / 100.0) if fy_rask is not None and rask_growth is not None else None
            forecast_cask = fy_cask * (1.0 + cask_growth / 100.0) if fy_cask is not None and cask_growth is not None else None

            nonpassenger_growth = _h1_cargo_growth(sector_trend, company)
            if nonpassenger_growth is None:
                nonpassenger_growth = 0.0
                nonpassenger_growth_source = "neutral_cargo_other_revenue_proxy"
            else:
                nonpassenger_growth_source = "issuer_h1_cargo_tonnes_proxy"
            nonpassenger_delta = {"bear": -3.0, "base": 0.0, "bull": 3.0}[scenario]
            nonpassenger_growth += nonpassenger_delta

            passenger_revenue_forecast_native = (
                forecast_ask * forecast_rask
                if forecast_ask is not None and forecast_rask is not None
                else None
            )
            nonpassenger_revenue_forecast_native = (
                nonpassenger_revenue_native * (1.0 + nonpassenger_growth / 100.0)
                if nonpassenger_revenue_native is not None
                else None
            )
            revenue_native = (
                passenger_revenue_forecast_native + nonpassenger_revenue_forecast_native
                if passenger_revenue_forecast_native is not None and nonpassenger_revenue_forecast_native is not None
                else None
            )
            cost_native = forecast_ask * forecast_cask if forecast_ask is not None and forecast_cask is not None else None
            operating_profit_native = revenue_native - cost_native if revenue_native is not None and cost_native is not None else None

            revenue_usd = revenue_native / fx_native_per_usd if revenue_native is not None and fx_native_per_usd else None
            cost_usd = cost_native / fx_native_per_usd if cost_native is not None and fx_native_per_usd else None
            operating_profit_usd = operating_profit_native / fx_native_per_usd if operating_profit_native is not None and fx_native_per_usd else None

            if profit_proxy_method == "positive_FY2025_operating_to_net_conversion" and operating_profit_usd is not None and net_to_operating is not None:
                earnings_before_fuel = operating_profit_usd * net_to_operating
            elif profit_proxy_method == "consensus_margin_fallback_unprofitable_FY2025" and revenue_usd is not None and consensus_margin is not None:
                earnings_before_fuel = revenue_usd * (consensus_margin / 100.0)
            elif profit_proxy_method == "actual_margin_carry_unprofitable_FY2025" and revenue_usd is not None and actual_margin is not None:
                earnings_before_fuel = revenue_usd * actual_margin
            elif operating_profit_usd is not None and net_to_operating is not None:
                earnings_before_fuel = operating_profit_usd * net_to_operating
            else:
                earnings_before_fuel = None

            fuel_impact_pre_tax, fuel_quality = _fuel_impact(fuel, company, FUEL_SHOCK[scenario])
            fuel_overlay_applied = (
                profit_proxy_method == "positive_FY2025_operating_to_net_conversion"
                and net_to_operating is not None
                and net_to_operating > 0
            )
            fuel_impact_earnings = fuel_impact_pre_tax * net_to_operating if fuel_overlay_applied else None
            earnings_after_fuel = (
                earnings_before_fuel + fuel_impact_earnings
                if earnings_before_fuel is not None and fuel_impact_earnings is not None
                else earnings_before_fuel
            )

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
                "fy2025_passenger_revenue_native_mn": passenger_revenue_native,
                "fy2025_nonpassenger_revenue_native_mn": nonpassenger_revenue_native,
                "fy2025_total_revenue_per_ask_rmb_per_ask": total_revenue_per_ask,
                "passenger_revenue_method": passenger_revenue_method,
                "actual_operating_profit_usd_mn": actual_operating_profit_usd,
                "net_to_operating_profit_conversion": net_to_operating,
                "profit_proxy_method": profit_proxy_method,
                "rpk_growth_assumption_pct": rpk_growth,
                "ask_growth_assumption_pct": ask_growth,
                "rask_growth_assumption_pct_vs_fy2025": rask_growth,
                "cask_growth_assumption_pct_vs_fy2025": cask_growth,
                "rpk_assumption_source": _assumption_source(assumptions, expectations, company, "rpk_growth_pct"),
                "ask_assumption_source": _assumption_source(assumptions, expectations, company, "ask_growth_pct"),
                "passenger_rask_assumption_source": _assumption_source(assumptions, expectations, company, "rask_growth_pct_vs_fy2025"),
                "nonpassenger_revenue_growth_assumption_pct": nonpassenger_growth,
                "nonpassenger_revenue_assumption_source": nonpassenger_growth_source,
                "cask_assumption_source": _assumption_source(assumptions, expectations, company, "cask_growth_pct_vs_fy2025"),
                "forecast_ask_mn_seat_km": forecast_ask,
                "forecast_rpk_mn_passenger_km": forecast_rpk,
                "forecast_load_factor_pct": forecast_lf,
                "forecast_load_factor_change_pp": forecast_lf - actual_lf if forecast_lf is not None and actual_lf is not None else None,
                "forecast_rask_proxy_rmb_per_ask": forecast_rask,
                "forecast_cask_rmb_per_ask": forecast_cask,
                "forecast_passenger_revenue_native_mn": passenger_revenue_forecast_native,
                "forecast_nonpassenger_revenue_native_mn": nonpassenger_revenue_forecast_native,
                "forecast_total_revenue_per_ask_rmb_per_ask": revenue_native / forecast_ask if revenue_native is not None and forecast_ask else None,
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
                "fuel_overlay_applied_to_net_profit": fuel_overlay_applied,
                "earnings_proxy_after_fuel_usd_mn": earnings_after_fuel,
                "consensus_fy2026_revenue_usd_mn": consensus_revenue,
                "consensus_fy2026_profit_usd_mn": consensus_profit,
                "consensus_fy2026_net_margin_pct": consensus_margin,
                "market_cap_usd_mn": market_cap_usd,
                "market_cap_to_consensus_revenue_usd": market_cap_to_consensus_revenue,
                "historical_ps_window": "3y",
                "historical_ps_median": historical_ps_median,
                "historical_ps_market": historical_ps_market,
                "historical_ps_status": historical_ps_status,
                "market_implied_revenue_usd_mn_at_historical_ps_median": market_implied_revenue_usd,
                "forecast_revenue_vs_market_implied_historical_ps_pct": (
                    100.0 * revenue_usd / market_implied_revenue_usd - 100.0
                    if revenue_usd is not None and market_implied_revenue_usd
                    else None
                ),
                "revenue_gap_to_consensus_pct": 100.0 * revenue_usd / consensus_revenue - 100.0 if revenue_usd is not None and consensus_revenue else None,
                "earnings_gap_to_consensus_pct": 100.0 * earnings_after_fuel / consensus_profit - 100.0 if earnings_after_fuel is not None and consensus_profit else None,
                "implied_earnings_margin_pct": 100.0 * earnings_after_fuel / revenue_usd if earnings_after_fuel is not None and revenue_usd else None,
                "consensus_revenue_analyst_count": _num(exp.get("fy2026_revenue_analyst_count")),
                "consensus_revenue_freshness": str(exp.get("revenue_consensus_freshness_band", "pending")),
                "consensus_profit_freshness": str(exp.get("profit_consensus_freshness_band", "pending")),
                "consensus_profit_age_days": _num(exp.get("profit_consensus_age_days")),
                "selected_consensus_market": selected_market,
                "selected_consensus_scope": str(exp.get("consensus_scope", "")),
                "formal_report_scheduled_date": str(exp.get("formal_report_scheduled_date", "")),
                "actual_fx_native_per_usd": fx_native_per_usd,
                "fx_observation_date": "2025-12-31",
                "fx_translation_method": "FY2025 reported native revenue divided by FY2025 USD translation; held constant for display and not a forward-FX view",
                "model_scope_note": "Juneyao financials are consolidated and include 9 Air; RASK/CASK are group proxies, not mainline standalone metrics" if company == "Juneyao Airlines" else "",
                "profit_proxy_note": "Earnings proxy uses FY2025 operating-to-net conversion when FY2025 net profit and operating profit are both positive; otherwise it uses dated consensus margin as an explicit normalization fallback. Fuel overlay remains pre-tax unless conversion is available; not net-income guidance",
                "actual_fy2025_source_path": str(MODEL_INPUTS_PATH) if not model.empty else str(DRIVERS_PATH),
                "actual_fy2025_source_url": _get_official_source_url(drivers, company, "total_revenue") or str(model.get("official_fy2025_source_url", exp.get("official_fy2025_source_url", ""))),
                "consensus_source_path": str(EXPECTATION_PATH),
                "valuation_source_path": str(VALUATION_BANDS_PATH),
                "assumption_source_path": str(ASSUMPTION_PATH),
                "fuel_source_path": str(FUEL_PATH),
                "fuel_source_quality": fuel_quality,
                "source_quality": "derived_multi_source_mechanical_bridge",
                "source_note": "Revenue bridge = passenger RASK x ASK + non-passenger revenue proxy; non-passenger proxy uses usable H1 cargo-tonne growth where available, otherwise neutral. Market-implied revenue is current market cap divided by the free 3-year historical P/S median; cross-market fallback remains labelled. " + str(model.get("source_note", exp.get("source_note", ""))),
                "retrieved_at": retrieved,
            })

    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_company_financial_forecast_bridge() -> pd.DataFrame:
    return build_airline_company_financial_forecast_bridge()
