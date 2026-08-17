"""Pre-event bottom-up independent forecast view for the core airline pair.

This layer is deliberately separate from the consensus stress bridge.  It
records an analyst view before the 1H2026 reports: ASK/RPK, revenue-per-ASK
mix/yield, fuel and non-fuel cost assumptions are explicit, while the issuer
result is a later test of the view.  Juneyao's cost and profit remain
consolidated and include unresolved 9 Air economics. The numbers are a working
research stance, not an automatic trade signal or investment advice.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR


EXPECTATION_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
PRE_H1_PATH = NORMALIZED_DIR / "airline_pre_h1_scenario_bridge.csv"
OPERATING_PATH = NORMALIZED_DIR / "airline_operating_diagnostics.csv"
MODEL_INPUTS_PATH = NORMALIZED_DIR / "airline_core_pair_model_inputs.csv"
FUEL_SENSITIVITY_PATH = NORMALIZED_DIR / "airline_fuel_sensitivity_scenarios.csv"
SECTOR_OUTLOOK_PATH = NORMALIZED_DIR / "airline_sector_external_outlook.csv"
SECTOR_TREND_PATH = NORMALIZED_DIR / "airline_sector_trend_snapshot.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_independent_forecast_view.csv"

SCENARIOS = ("bear", "base", "bull")

# These are the initial analyst assumptions as of the current pre-event
# snapshot. They are intentionally visible and easy to revise after new
# traffic/fare evidence; they are not copied from consensus. Revenue growth is
# an output of ASK growth and revenue-per-ASK mix/yield growth. Net profit is
# derived from the operating bridge, not typed in as a margin target.
VIEW_ASSUMPTIONS = {
    "Spring Airlines": {
        "ticker": "601021.SH",
        "ask_growth_pct": {"bear": 13.0, "base": 15.3644, "bull": 18.0},
        "rpk_growth_pct": {"bear": 13.0, "base": 18.0099, "bull": 21.0},
        "yield_mix_growth_pct": {"bear": 0.0, "base": 1.417768, "bull": 1.694915},
        "fuel_price_shock_pct": {"bear": 10.0, "base": 0.0, "bull": -10.0},
        "nonfuel_cost_per_ask_growth_pct": {"bear": 5.0, "base": 4.800259, "bull": 3.0},
        "assumption_rationale": (
            "Base case follows observed H1 capacity/demand, allows a modest revenue-per-ASK mix lift, "
            "keeps fuel flat and assumes non-fuel cost per ASK rises 4.8%; Spring retains a structural margin edge."
        ),
        "view_direction": "long_candidate",
        "variant_perception": (
            "Consensus likely overstates Spring's FY2026 top-line growth but may understate "
            "the persistence of its structural low-cost margin advantage."
        ),
        "evidence": (
            "FY2025 net margin 10.80%; 1H2026 RPK +18.01% versus ASK +15.36%; "
            "H1 passenger load factor improved; June demand-capacity gap turned slightly negative."
        ),
        "invalidation": (
            "Reported yield/RASK and net margin fall materially below the base view, or "
            "RPK-minus-ASK remains negative while the margin premium compresses."
        ),
    },
    "Juneyao Airlines": {
        "ticker": "603885.SH",
        "ask_growth_pct": {"bear": 0.0, "base": 1.1305, "bull": 2.0},
        "rpk_growth_pct": {"bear": 0.0, "base": 2.7314, "bull": 8.0},
        "yield_mix_growth_pct": {"bear": 0.0, "base": 2.837423, "bull": 5.882353},
        "fuel_price_shock_pct": {"bear": 10.0, "base": 0.0, "bull": -10.0},
        "nonfuel_cost_per_ask_growth_pct": {"bear": 10.0, "base": 10.9, "bull": 8.0},
        "assumption_rationale": (
            "Base case follows observed H1 capacity/demand but applies 10.9% non-fuel cost-per-ASK pressure "
            "to reflect consolidated 9 Air/international scope; positive traffic does not become full margin recovery."
        ),
        "view_direction": "short_candidate",
        "variant_perception": (
            "Consensus likely extrapolates a recovery that is not yet visible in traffic: "
            "the group can grow, but H1 demand and the warning imply a lower FY2026 profit base."
        ),
        "evidence": (
            "FY2025 net margin 4.62%; 1H2026 RPK +2.73% versus ASK +1.13%; "
            "passengers declined; H1 warning and unresolved 9 Air economics remain material."
        ),
        "invalidation": (
            "Reported revenue/yield accelerates toward consensus, H1/H2 margin recovers above "
            "the base view, and 9 Air scope does not dilute group economics."
        ),
    },
}


OUTPUT_COLUMNS = [
    "dataset_id",
    "pair_id",
    "company",
    "ticker",
    "scenario",
    "forecast_horizon",
    "as_of_date",
    "actual_fy2025_revenue_usd_mn",
    "actual_fy2025_profit_usd_mn",
    "actual_fy2025_margin_pct",
    "actual_fy2025_ask_mn_seat_km",
    "actual_fy2025_rpk_mn_passenger_km",
    "actual_fy2025_load_factor_pct",
    "actual_fy2025_revenue_per_ask_native",
    "actual_fy2025_operating_cost_per_ask_native",
    "actual_fy2025_fuel_cost_per_ask_native",
    "actual_fy2025_nonfuel_cost_per_ask_native",
    "net_to_operating_profit_conversion",
    "consensus_fy2026_revenue_usd_mn",
    "consensus_fy2026_profit_usd_mn",
    "consensus_fy2026_margin_pct",
    "independent_revenue_growth_pct",
    "ask_growth_assumption_pct",
    "rpk_growth_assumption_pct",
    "yield_mix_growth_assumption_pct",
    "fuel_price_shock_assumption_pct",
    "nonfuel_cost_per_ask_growth_assumption_pct",
    "independent_net_margin_pct",
    "independent_revenue_native_mn",
    "independent_operating_cost_native_mn",
    "independent_fuel_cost_native_mn",
    "independent_nonfuel_cost_native_mn",
    "independent_operating_profit_native_mn",
    "independent_revenue_per_ask_native",
    "independent_cask_native_per_ask",
    "independent_load_factor_pct",
    "independent_revenue_usd_mn",
    "independent_profit_usd_mn",
    "independent_fuel_overlay_pre_tax_usd_mn",
    "fuel_sensitivity_crosscheck_pre_tax_usd_mn",
    "fx_native_per_usd",
    "fx_translation_method",
    "revenue_gap_vs_consensus_pct",
    "profit_gap_vs_consensus_pct",
    "view_direction",
    "variant_perception",
    "assumption_rationale",
    "sector_view_status",
    "sector_apac_rpk_forecast_pct",
    "sector_apac_ask_forecast_pct",
    "sector_apac_q1_rpk_actual_pct",
    "sector_apac_q1_ask_actual_pct",
    "sector_cn_h1_rpk_growth_pct",
    "sector_cn_h1_ask_growth_pct",
    "sector_cn_h1_lf_change_pp",
    "sector_h1_jet_fuel_yoy_pct",
    "sector_view",
    "primary_evidence",
    "invalidation_rule",
    "catalyst",
    "forecast_status",
    "forecast_method",
    "source_paths",
    "retrieved_at",
]


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _row(frame: pd.DataFrame, company: str) -> pd.Series:
    if frame.empty or "company" not in frame.columns:
        return pd.Series(dtype=object)
    rows = frame.loc[frame["company"].eq(company)]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _as_of(*frames: pd.DataFrame) -> str:
    values: list[str] = []
    for frame in frames:
        for column in ("snapshot_date", "as_of_date", "retrieved_at"):
            if column in frame.columns:
                values.extend(str(value)[:10] for value in frame[column].dropna())
    valid = [value for value in values if len(value) == 10 and value[4] == "-" and value[7] == "-"]
    return max(valid) if valid else datetime.now(timezone.utc).date().isoformat()


def _outlook_metric(
    outlook: pd.DataFrame,
    *,
    period: str,
    scope: str,
    metric: str,
    status: str | None = None,
) -> float | None:
    if outlook.empty or not {"period", "scope", "metric", "value"}.issubset(outlook.columns):
        return None
    rows = outlook[
        outlook["period"].eq(period)
        & outlook["scope"].eq(scope)
        & outlook["metric"].eq(metric)
    ]
    if status is not None and "status" in outlook.columns:
        rows = rows[rows["status"].eq(status)]
    return _num(rows.iloc[0].get("value")) if not rows.empty else None


def _trend_metric(trend: pd.DataFrame, metric: str) -> float | None:
    if trend.empty or not {"scope_type", "metric", "yoy_change_pct"}.issubset(trend.columns):
        return None
    rows = trend[trend["scope_type"].eq("sector") & trend["metric"].eq(metric)]
    return _num(rows.iloc[0].get("yoy_change_pct")) if not rows.empty else None


def build_airline_independent_forecast_view(
    *,
    expectations: pd.DataFrame | None = None,
    pre_h1: pd.DataFrame | None = None,
    operating: pd.DataFrame | None = None,
    model_inputs: pd.DataFrame | None = None,
    fuel_sensitivity: pd.DataFrame | None = None,
    sector_outlook: pd.DataFrame | None = None,
    sector_trend: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build transparent bottom-up pre-event analyst forecasts."""

    expectations = expectations if expectations is not None else pd.read_csv(EXPECTATION_PATH)
    pre_h1 = pre_h1 if pre_h1 is not None else pd.read_csv(PRE_H1_PATH)
    operating = operating if operating is not None else pd.read_csv(OPERATING_PATH)
    model_inputs = model_inputs if model_inputs is not None else pd.read_csv(MODEL_INPUTS_PATH)
    fuel_sensitivity = fuel_sensitivity if fuel_sensitivity is not None else pd.read_csv(FUEL_SENSITIVITY_PATH)
    sector_outlook = sector_outlook if sector_outlook is not None else pd.read_csv(SECTOR_OUTLOOK_PATH)
    sector_trend = sector_trend if sector_trend is not None else pd.read_csv(SECTOR_TREND_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    as_of = _as_of(expectations, pre_h1, operating, model_inputs, fuel_sensitivity, sector_outlook, sector_trend)
    sector_apac_rpk_forecast = _outlook_metric(
        sector_outlook, period="2026", scope="Asia Pacific", metric="passenger_demand_rpk_growth", status="forecast"
    )
    sector_apac_ask_forecast = _outlook_metric(
        sector_outlook, period="2026", scope="Asia Pacific", metric="capacity_ask_growth", status="forecast"
    )
    sector_apac_q1_rpk_actual = _outlook_metric(
        sector_outlook, period="2026Q1", scope="Asia Pacific", metric="passenger_demand_rpk_growth", status="actual"
    )
    sector_apac_q1_ask_actual = _outlook_metric(
        sector_outlook, period="2026Q1", scope="Asia Pacific", metric="capacity_ask_growth", status="actual"
    )
    sector_cn_h1_rpk = _outlook_metric(
        sector_outlook, period="2026H1", scope="China", metric="passenger_rpk_yoy", status="actual"
    )
    sector_cn_h1_ask = _trend_metric(sector_trend, "ask")
    sector_cn_h1_lf_change = _outlook_metric(
        sector_outlook, period="2026H1", scope="China", metric="scheduled_passenger_load_factor_change_pp", status="actual"
    )
    rows: list[dict[str, object]] = []

    for company, config in VIEW_ASSUMPTIONS.items():
        expectation = _row(expectations, company)
        actuals = _row(pre_h1, company)
        operating_row = _row(operating, company)
        model = _row(model_inputs, company)
        actual_revenue = _num(actuals.get("actual_fy2025_revenue_usd_mn"))
        actual_profit = _num(actuals.get("actual_fy2025_profit_usd_mn"))
        actual_margin = _num(actuals.get("actual_fy2025_margin_pct"))
        consensus_revenue = _num(expectation.get("fy2026_revenue_avg_usd_mn"))
        consensus_profit = _num(expectation.get("fy2026_net_profit_avg_usd_mn"))
        consensus_margin = _num(expectation.get("fy2026_consensus_net_margin_pct"))
        catalyst = str(expectation.get("formal_report_scheduled_date", ""))
        native_revenue = _num(expectation.get("latest_report_revenue_native_mn"))
        fx_native_per_usd = native_revenue / actual_revenue if native_revenue and actual_revenue else None
        actual_ask = _num(model.get("fy2025_ask_mn_seat_km"))
        actual_rpk = _num(model.get("fy2025_rpk_mn_passenger_km"))
        actual_revenue_native = native_revenue if native_revenue is not None else (
            actual_revenue * fx_native_per_usd if actual_revenue is not None and fx_native_per_usd else None
        )
        actual_cost_usd = _num(model.get("fy2025_operating_cost_usd_mn"))
        actual_fuel_usd = _num(model.get("fy2025_fuel_cost_usd_mn"))
        actual_cost_native = actual_cost_usd * fx_native_per_usd if actual_cost_usd is not None and fx_native_per_usd else None
        actual_fuel_native = actual_fuel_usd * fx_native_per_usd if actual_fuel_usd is not None and fx_native_per_usd else None
        actual_nonfuel_native = (
            actual_cost_native - actual_fuel_native
            if actual_cost_native is not None and actual_fuel_native is not None
            else None
        )
        actual_lf = 100.0 * actual_rpk / actual_ask if actual_rpk is not None and actual_ask else None
        actual_revenue_per_ask = (
            actual_revenue_native / actual_ask
            if actual_revenue_native is not None and actual_ask
            else None
        )
        actual_cost_per_ask = actual_cost_native / actual_ask if actual_cost_native is not None and actual_ask else None
        actual_fuel_per_ask = actual_fuel_native / actual_ask if actual_fuel_native is not None and actual_ask else None
        actual_nonfuel_per_ask = actual_nonfuel_native / actual_ask if actual_nonfuel_native is not None and actual_ask else None
        actual_operating_profit = actual_revenue - actual_cost_usd if actual_revenue is not None and actual_cost_usd is not None else None
        net_to_operating = (
            actual_profit / actual_operating_profit
            if actual_profit is not None and actual_operating_profit and actual_operating_profit > 0
            else None
        )
        sector_fuel_yoy = _num(actuals.get("sector_h1_jet_fuel_yoy_pct"))
        sector_view = (
            f"APAC sector forecast RPK +{sector_apac_rpk_forecast:.1f}% versus ASK +{sector_apac_ask_forecast:.1f}%; "
            f"China six-company H1 ASK +{sector_cn_h1_ask:.1f}% and RPK +{_trend_metric(sector_trend, 'rpk'):.1f}%, "
            f"with scheduled passenger LF change {sector_cn_h1_lf_change:+.1f}pp. Demand is positive but pricing and cost pass-through remain the earnings swing factors."
            if all(value is not None for value in (sector_apac_rpk_forecast, sector_apac_ask_forecast, sector_cn_h1_ask, _trend_metric(sector_trend, 'rpk'), sector_cn_h1_lf_change))
            else "Sector context is incomplete; company forecast remains based on issuer operating data and explicit assumptions."
        )
        for scenario in SCENARIOS:
            ask_growth = config["ask_growth_pct"][scenario]
            rpk_growth = config["rpk_growth_pct"][scenario]
            yield_mix_growth = config["yield_mix_growth_pct"][scenario]
            fuel_shock = config["fuel_price_shock_pct"][scenario]
            nonfuel_growth = config["nonfuel_cost_per_ask_growth_pct"][scenario]
            forecast_ask = actual_ask * (1.0 + ask_growth / 100.0) if actual_ask is not None else None
            forecast_rpk = actual_rpk * (1.0 + rpk_growth / 100.0) if actual_rpk is not None else None
            forecast_lf = 100.0 * forecast_rpk / forecast_ask if forecast_rpk is not None and forecast_ask else None
            forecast_revenue_per_ask = (
                actual_revenue_per_ask * (1.0 + yield_mix_growth / 100.0)
                if actual_revenue_per_ask is not None
                else None
            )
            revenue_native = (
                forecast_ask * forecast_revenue_per_ask
                if forecast_ask is not None and forecast_revenue_per_ask is not None
                else None
            )
            fuel_native = (
                actual_fuel_native * (1.0 + ask_growth / 100.0) * (1.0 + fuel_shock / 100.0)
                if actual_fuel_native is not None
                else None
            )
            nonfuel_native = (
                actual_nonfuel_native * (1.0 + ask_growth / 100.0) * (1.0 + nonfuel_growth / 100.0)
                if actual_nonfuel_native is not None
                else None
            )
            cost_native = fuel_native + nonfuel_native if fuel_native is not None and nonfuel_native is not None else None
            operating_profit_native = revenue_native - cost_native if revenue_native is not None and cost_native is not None else None
            revenue = revenue_native / fx_native_per_usd if revenue_native is not None and fx_native_per_usd else None
            cost_usd = cost_native / fx_native_per_usd if cost_native is not None and fx_native_per_usd else None
            operating_profit_usd = operating_profit_native / fx_native_per_usd if operating_profit_native is not None and fx_native_per_usd else None
            profit = operating_profit_usd * net_to_operating if operating_profit_usd is not None and net_to_operating is not None else None
            margin = 100.0 * profit / revenue if profit is not None and revenue else None
            growth = 100.0 * revenue / actual_revenue - 100.0 if revenue is not None and actual_revenue else None
            revenue_gap = (100.0 * revenue / consensus_revenue - 100.0) if revenue is not None and consensus_revenue else None
            profit_gap = (100.0 * profit / consensus_profit - 100.0) if profit is not None and consensus_profit else None
            baseline_volume_fuel_native = (
                actual_fuel_native * (1.0 + ask_growth / 100.0)
                if actual_fuel_native is not None
                else None
            )
            fuel_overlay_pre_tax_usd = (
                -(fuel_native - baseline_volume_fuel_native) / fx_native_per_usd
                if fuel_native is not None and baseline_volume_fuel_native is not None and fx_native_per_usd
                else None
            )
            fuel_rows = fuel_sensitivity[
                fuel_sensitivity.get("company", pd.Series(dtype=object)).eq(company)
                & pd.to_numeric(
                    fuel_sensitivity.get("scenario_fuel_price_change_pct", pd.Series(dtype=object)),
                    errors="coerce",
                ).eq(fuel_shock)
            ] if not fuel_sensitivity.empty else pd.DataFrame()
            fuel_crosscheck = _num(fuel_rows.iloc[0].get("pre_tax_profit_impact_usd_mn")) if not fuel_rows.empty else None
            rows.append(
                {
                    "dataset_id": "airline_independent_forecast_view",
                    "pair_id": "601021.SH__603885.SH",
                    "company": company,
                    "ticker": config["ticker"],
                    "scenario": scenario,
                    "forecast_horizon": "FY2026_pre_1H2026_results",
                    "as_of_date": as_of,
                    "actual_fy2025_revenue_usd_mn": actual_revenue,
                    "actual_fy2025_profit_usd_mn": actual_profit,
                    "actual_fy2025_margin_pct": actual_margin,
                    "actual_fy2025_ask_mn_seat_km": actual_ask,
                    "actual_fy2025_rpk_mn_passenger_km": actual_rpk,
                    "actual_fy2025_load_factor_pct": actual_lf,
                    "actual_fy2025_revenue_per_ask_native": actual_revenue_per_ask,
                    "actual_fy2025_operating_cost_per_ask_native": actual_cost_per_ask,
                    "actual_fy2025_fuel_cost_per_ask_native": actual_fuel_per_ask,
                    "actual_fy2025_nonfuel_cost_per_ask_native": actual_nonfuel_per_ask,
                    "net_to_operating_profit_conversion": net_to_operating,
                    "consensus_fy2026_revenue_usd_mn": consensus_revenue,
                    "consensus_fy2026_profit_usd_mn": consensus_profit,
                    "consensus_fy2026_margin_pct": consensus_margin,
                    "independent_revenue_growth_pct": growth,
                    "ask_growth_assumption_pct": ask_growth,
                    "rpk_growth_assumption_pct": rpk_growth,
                    "yield_mix_growth_assumption_pct": yield_mix_growth,
                    "fuel_price_shock_assumption_pct": fuel_shock,
                    "nonfuel_cost_per_ask_growth_assumption_pct": nonfuel_growth,
                    "independent_net_margin_pct": margin,
                    "independent_revenue_native_mn": revenue_native,
                    "independent_operating_cost_native_mn": cost_native,
                    "independent_fuel_cost_native_mn": fuel_native,
                    "independent_nonfuel_cost_native_mn": nonfuel_native,
                    "independent_operating_profit_native_mn": operating_profit_native,
                    "independent_revenue_per_ask_native": forecast_revenue_per_ask,
                    "independent_cask_native_per_ask": cost_native / forecast_ask if cost_native is not None and forecast_ask else None,
                    "independent_load_factor_pct": forecast_lf,
                    "independent_revenue_usd_mn": revenue,
                    "independent_profit_usd_mn": profit,
                    "independent_fuel_overlay_pre_tax_usd_mn": fuel_overlay_pre_tax_usd,
                    "fuel_sensitivity_crosscheck_pre_tax_usd_mn": fuel_crosscheck,
                    "fx_native_per_usd": fx_native_per_usd,
                    "fx_translation_method": "FY2025 reported native revenue divided by FY2025 USD translation; held constant and not a forward-FX forecast",
                    "revenue_gap_vs_consensus_pct": revenue_gap,
                    "profit_gap_vs_consensus_pct": profit_gap,
                    "view_direction": config["view_direction"],
                    "variant_perception": config["variant_perception"],
                    "assumption_rationale": config["assumption_rationale"],
                    "sector_view_status": "sector_context_snapshot_not_company_forecast",
                    "sector_apac_rpk_forecast_pct": sector_apac_rpk_forecast,
                    "sector_apac_ask_forecast_pct": sector_apac_ask_forecast,
                    "sector_apac_q1_rpk_actual_pct": sector_apac_q1_rpk_actual,
                    "sector_apac_q1_ask_actual_pct": sector_apac_q1_ask_actual,
                    "sector_cn_h1_rpk_growth_pct": _trend_metric(sector_trend, "rpk"),
                    "sector_cn_h1_ask_growth_pct": sector_cn_h1_ask,
                    "sector_cn_h1_lf_change_pp": sector_cn_h1_lf_change,
                    "sector_h1_jet_fuel_yoy_pct": sector_fuel_yoy,
                    "sector_view": sector_view,
                    "primary_evidence": (
                        f"{config['evidence']} Q2 RPK/ASK gap={_num(operating_row.get('q2_rpk_minus_ask_gap_pp'))}; "
                        f"June RPK/ASK gap={_num(operating_row.get('june_rpk_minus_ask_gap_pp'))}; "
                        f"base bridge uses explicit ASK/RPK, revenue-per-ASK mix, fuel shock and non-fuel cost-per-ASK assumptions. "
                        f"Sector context: {sector_view}"
                    ),
                    "invalidation_rule": config["invalidation"],
                    "catalyst": catalyst,
                    "forecast_status": "analyst_pre_event_base_view" if scenario == "base" else "analyst_pre_event_scenario",
                    "forecast_method": "FY2025_actual_ASK_times_explicit_growth_then_revenue_per_ASK_mix_and_fuel_nonfuel_cost_bridge_with_net_to_operating_conversion",
                    "source_paths": f"{PRE_H1_PATH};{EXPECTATION_PATH};{OPERATING_PATH};{MODEL_INPUTS_PATH};{FUEL_SENSITIVITY_PATH};{SECTOR_OUTLOOK_PATH};{SECTOR_TREND_PATH}",
                    "retrieved_at": retrieved,
                }
            )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_independent_forecast_view() -> pd.DataFrame:
    result = build_airline_independent_forecast_view()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
