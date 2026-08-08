"""Six-company forward earnings bridge and direction-neutral pair scorecard.

The bridge is deliberately separate from the earlier Spring/Juneyao-only
mechanical model.  It uses company traffic run-rates as the operating anchor,
keeps market consensus as an expectations comparator, and leaves fuel shocks
as a separate overlay rather than silently adding them to base earnings.

It is a research model, not issuer guidance or an investment recommendation.
Missing standalone 9 Air economics are preserved as a Juneyao scope caveat;
no 9 Air revenue, cost or profit is allocated from consolidated disclosures.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

DRIVERS_PATH = NORMALIZED_DIR / "airline_earnings_driver_comparability.csv"
EXPECTATION_PATH = NORMALIZED_DIR / "airline_sector_expectation_snapshot.csv"
OPERATING_PATH = NORMALIZED_DIR / "airline_operating_diagnostics.csv"
YIELD_PATH = NORMALIZED_DIR / "airline_yield_pricing_matrix.csv"
FUEL_PATH = NORMALIZED_DIR / "airline_fuel_pass_through_hedge_matrix.csv"
ASSUMPTION_PATH = NORMALIZED_DIR / "airline_forecast_assumptions.csv"
HSR_PATH = NORMALIZED_DIR / "airline_hsr_research_coverage.csv"
SCOPE_PATH = NORMALIZED_DIR / "airline_juneyao_9air_scope_reconciliation.csv"
PAIR_SCREEN_PATH = NORMALIZED_DIR / "airline_pair_screening_matrix.csv"
PAIR_SCENARIO_PATH = NORMALIZED_DIR / "airline_pair_scenario_inputs.csv"
PAIR_RISK_PATH = NORMALIZED_DIR / "airline_pair_risk_metrics.csv"

FORWARD_OUTPUT_PATH = NORMALIZED_DIR / "airline_forward_earnings_bridge.csv"
PAIR_OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_scorecard.csv"
RISK_OUTPUT_PATH = NORMALIZED_DIR / "airline_forward_invalidation_rules.csv"

MAINLAND_COMPANIES = (
    ("Air China", "601111.SH"),
    ("China Southern Airlines", "600029.SH"),
    ("China Eastern Airlines", "600115.SH"),
    ("Spring Airlines", "601021.SH"),
    ("Hainan Airlines Holdings", "600221.SH"),
    ("Juneyao Airlines", "603885.SH"),
)
SCENARIOS = ("bear", "base", "bull")
FUEL_SHOCK = {"bear": 5.0, "base": 0.0, "bull": -5.0}
SCENARIO_DELTA = {"bear": -1.0, "base": 0.0, "bull": 1.0}


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _date(value: object) -> str:
    text = str(value)[:10]
    return text if len(text) == 10 and text[4] == "-" and text[7] == "-" else "pending"


def _latest_date(frames: list[pd.DataFrame | None]) -> str:
    values: list[str] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for column in (
            "snapshot_date", "information_date", "source_as_of_date", "as_of_date",
            "energy_observation_date", "effective_from",
        ):
            if column in frame.columns:
                values.extend(_date(value) for value in frame[column].dropna())
    valid = [value for value in values if value != "pending"]
    return max(valid) if valid else "pending"


def _row(frame: pd.DataFrame, company: str, **criteria: object) -> pd.Series:
    if frame.empty or "company" not in frame.columns:
        return pd.Series(dtype=object)
    mask = frame["company"].eq(company)
    for column, value in criteria.items():
        if column in frame.columns:
            mask &= frame[column].eq(value)
        else:
            return pd.Series(dtype=object)
    rows = frame.loc[mask]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _metric(frame: pd.DataFrame, company: str, period: str, metric: str, column: str = "value_native") -> float | None:
    row = _row(frame, company, statement_period=period, canonical_metric=metric)
    return _num(row.get(column)) if not row.empty else None


def _assumption(frame: pd.DataFrame, company: str, scenario: str, driver: str) -> float | None:
    if frame.empty or not {"entity", "scenario", "driver"}.issubset(frame.columns):
        return None
    rows = frame[
        frame["entity"].eq(company)
        & frame["scenario"].eq(scenario)
        & frame["driver"].eq(driver)
    ]
    row = rows.iloc[0] if not rows.empty else pd.Series(dtype=object)
    return _num(row.get("assumption_value")) if not row.empty else None


def _company_expectation(expectations: pd.DataFrame, company: str) -> pd.Series:
    rows = expectations[
        expectations.get("scope_type", pd.Series(dtype=object)).eq("company")
        & expectations.get("company", pd.Series(dtype=object)).eq(company)
    ]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _fuel_row(fuel: pd.DataFrame, company: str, shock: float) -> pd.Series:
    rows = fuel[
        fuel.get("company", pd.Series(dtype=object)).eq(company)
        & fuel.get("statement_period", pd.Series(dtype=object)).eq("FY2025")
    ]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _scope_summary(scope: pd.DataFrame) -> dict[str, object]:
    rows = scope[scope.get("statement_period", pd.Series(dtype=object)).eq("FY2025")]
    result: dict[str, object] = {
        "nine_air_passenger_share_pct": None,
        "nine_air_fleet_share_pct": None,
        "nine_air_scope_status": "not_applicable_non_juneyao",
        "nine_air_scope_note": "",
        "nine_air_scope_adjustment_applied": False,
        "nine_air_scope_adjustment_type": "not_applicable",
    }
    if rows.empty:
        return result
    for metric, output in (("passengers", "nine_air_passenger_share_pct"), ("fleet_total", "nine_air_fleet_share_pct")):
        row = rows[rows.get("canonical_metric", pd.Series(dtype=object)).eq(metric)]
        if not row.empty:
            result[output] = _num(row.iloc[0].get("nine_air_share_pct"))
    result["nine_air_scope_status"] = "group_consolidated_including_9air_component_mix_only"
    result["nine_air_scope_note"] = (
        "Juneyao revenue, ASK/RPK, fuel, cost and profit remain consolidated; "
        "9 Air passenger/fleet shares are disclosed scope context only and are not allocated into earnings."
    )
    result["nine_air_scope_adjustment_applied"] = False
    result["nine_air_scope_adjustment_type"] = "passenger_fleet_mix_context_only_no_financial_allocation"
    return result


def _fallback_assumptions(
    scenario: str,
    expectation: pd.Series,
    operating: pd.Series,
) -> dict[str, object]:
    base_rpk = _num(expectation.get("h1_rpk_yoy_pct"))
    base_ask = _num(expectation.get("h1_ask_yoy_pct"))
    if base_rpk is None:
        base_rpk = _num(operating.get("q2_rpk_yoy_pct"))
    if base_ask is None:
        base_ask = _num(operating.get("q2_ask_yoy_pct"))
    base_rpk = base_rpk if base_rpk is not None else 0.0
    base_ask = base_ask if base_ask is not None else 0.0
    delta = 3.0 * SCENARIO_DELTA[scenario]
    return {
        "rpk_growth_pct": base_rpk + delta,
        "ask_growth_pct": base_ask + delta,
        "rask_growth_pct_vs_fy2025": 2.0 * SCENARIO_DELTA[scenario],
        "cask_growth_pct_vs_fy2025": 2.0 - SCENARIO_DELTA[scenario],
        "assumption_source": "company_H1_traffic_run_rate_with_explicit_stress",
        "assumption_status": "mechanical_company_run_rate_fallback",
    }


def _assumptions_for(
    assumptions: pd.DataFrame,
    company: str,
    scenario: str,
    expectation: pd.Series,
    operating: pd.Series,
) -> dict[str, object]:
    drivers = ("rpk_growth_pct", "ask_growth_pct", "rask_growth_pct_vs_fy2025", "cask_growth_pct_vs_fy2025")
    values = {driver: _assumption(assumptions, company, scenario, driver) for driver in drivers}
    if all(value is not None for value in values.values()):
        values["assumption_source"] = "airline_forecast_assumptions"
        values["assumption_status"] = "existing_company_explicit_assumption"
        return values
    return _fallback_assumptions(scenario, expectation, operating)


def build_airline_forward_earnings_bridge(
    *,
    drivers: pd.DataFrame | None = None,
    expectations: pd.DataFrame | None = None,
    operating: pd.DataFrame | None = None,
    yields: pd.DataFrame | None = None,
    fuel: pd.DataFrame | None = None,
    assumptions: pd.DataFrame | None = None,
    hsr: pd.DataFrame | None = None,
    scope: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    drivers = drivers if drivers is not None else pd.read_csv(DRIVERS_PATH)
    expectations = expectations if expectations is not None else pd.read_csv(EXPECTATION_PATH)
    operating = operating if operating is not None else pd.read_csv(OPERATING_PATH)
    yields = yields if yields is not None else pd.read_csv(YIELD_PATH)
    fuel = fuel if fuel is not None else pd.read_csv(FUEL_PATH)
    assumptions = assumptions if assumptions is not None else pd.read_csv(ASSUMPTION_PATH)
    hsr = hsr if hsr is not None else pd.read_csv(HSR_PATH)
    scope = scope if scope is not None else pd.read_csv(SCOPE_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    snapshot = _latest_date([drivers, expectations, operating, yields, fuel, assumptions, hsr, scope])
    juneyao_scope = _scope_summary(scope)
    rows: list[dict[str, object]] = []

    for company, ticker in MAINLAND_COMPANIES:
        expectation = _company_expectation(expectations, company)
        op = _row(operating, company)
        actual_revenue = _metric(drivers, company, "FY2025", "total_revenue")
        actual_profit = _metric(drivers, company, "FY2025", "attributable_profit")
        actual_cost = _metric(drivers, company, "FY2025", "operating_cost")
        actual_ask = _metric(drivers, company, "FY2025", "ask")
        actual_rpk = _metric(drivers, company, "FY2025", "rpk")
        actual_rask = _metric(drivers, company, "FY2025", "rask_proxy")
        actual_cask = _metric(drivers, company, "FY2025", "cask")
        actual_fuel_share = _metric(drivers, company, "FY2025", "fuel_cost_share_pct")
        actual_fuel_per_ask = _metric(drivers, company, "FY2025", "fuel_cost_per_ask")
        actual_nonfuel_cask = actual_cask - actual_fuel_per_ask if actual_cask is not None and actual_fuel_per_ask is not None else None
        actual_yield = _metric(yields, company, "FY2025", "reported_passenger_yield_native")
        if actual_yield is None:
            actual_yield = _metric(drivers, company, "FY2025", "passenger_yield")
        actual_fy_lf = 100.0 * actual_rpk / actual_ask if actual_rpk is not None and actual_ask else None
        actual_revenue_usd = _metric(drivers, company, "FY2025", "total_revenue", "value_usd")
        actual_profit_usd = _metric(drivers, company, "FY2025", "attributable_profit", "value_usd")
        fx_native_per_usd = actual_revenue / actual_revenue_usd if actual_revenue and actual_revenue_usd else None
        h1_ask = _metric(drivers, company, "1H2025", "ask")
        h1_rpk = _metric(drivers, company, "1H2025", "rpk")
        h1_lf = 100.0 * h1_rpk / h1_ask if h1_rpk is not None and h1_ask else None
        hsr_row = _row(hsr, company)
        scope_fields = juneyao_scope if company == "Juneyao Airlines" else {
            "nine_air_passenger_share_pct": None,
            "nine_air_fleet_share_pct": None,
            "nine_air_scope_status": "not_applicable_non_juneyao",
            "nine_air_scope_note": "",
            "nine_air_scope_adjustment_applied": False,
            "nine_air_scope_adjustment_type": "not_applicable",
        }
        for scenario in SCENARIOS:
            a = _assumptions_for(assumptions, company, scenario, expectation, op)
            rpk_growth = _num(a.get("rpk_growth_pct"))
            ask_growth = _num(a.get("ask_growth_pct"))
            rask_growth = _num(a.get("rask_growth_pct_vs_fy2025"))
            cask_growth = _num(a.get("cask_growth_pct_vs_fy2025"))
            forecast_ask = actual_ask * (1.0 + ask_growth / 100.0) if actual_ask is not None and ask_growth is not None else None
            forecast_rpk = actual_rpk * (1.0 + rpk_growth / 100.0) if actual_rpk is not None and rpk_growth is not None else None
            forecast_lf = 100.0 * forecast_rpk / forecast_ask if forecast_rpk is not None and forecast_ask else None
            forecast_rask = actual_rask * (1.0 + rask_growth / 100.0) if actual_rask is not None and rask_growth is not None else None
            forecast_cask = actual_cask * (1.0 + cask_growth / 100.0) if actual_cask is not None and cask_growth is not None else None
            forecast_revenue = forecast_ask * forecast_rask if forecast_ask is not None and forecast_rask is not None else None
            forecast_cost = forecast_ask * forecast_cask if forecast_ask is not None and forecast_cask is not None else None
            forecast_operating_profit = forecast_revenue - forecast_cost if forecast_revenue is not None and forecast_cost is not None else None
            forecast_fuel_cost = actual_fuel_per_ask * forecast_ask if actual_fuel_per_ask is not None and forecast_ask is not None else None
            forecast_nonfuel_cost = forecast_cost - forecast_fuel_cost if forecast_cost is not None and forecast_fuel_cost is not None else None
            consensus_revenue_usd = _num(expectation.get("fy2026_revenue_consensus_avg_usd_mn"))
            consensus_profit_usd = _num(expectation.get("fy2026_net_profit_consensus_avg_usd_mn"))
            consensus_margin = 100.0 * consensus_profit_usd / consensus_revenue_usd if consensus_profit_usd is not None and consensus_revenue_usd else None
            actual_margin = 100.0 * actual_profit / actual_revenue if actual_profit is not None and actual_revenue else None
            if actual_margin is not None and actual_margin > 0:
                profit_method = "positive_FY2025_net_margin_carry"
                forecast_net_profit = forecast_revenue * actual_margin / 100.0 if forecast_revenue is not None else None
            elif consensus_margin is not None:
                profit_method = "consensus_margin_fallback_negative_FY2025_profit"
                forecast_net_profit = forecast_revenue * consensus_margin / 100.0 if forecast_revenue is not None else None
            else:
                profit_method = "profit_proxy_unavailable"
                forecast_net_profit = None
            revenue_usd = forecast_revenue / fx_native_per_usd if forecast_revenue is not None and fx_native_per_usd else None
            cost_usd = forecast_cost / fx_native_per_usd if forecast_cost is not None and fx_native_per_usd else None
            operating_profit_usd = forecast_operating_profit / fx_native_per_usd if forecast_operating_profit is not None and fx_native_per_usd else None
            net_profit_usd = forecast_net_profit / fx_native_per_usd if forecast_net_profit is not None and fx_native_per_usd else None
            shock = FUEL_SHOCK[scenario]
            fuel_row = _fuel_row(fuel, company, shock)
            if shock > 0:
                fuel_impact = _num(fuel_row.get("plus5_pre_tax_profit_impact_usd_mn")) if not fuel_row.empty else None
            elif shock < 0:
                fuel_impact = _num(fuel_row.get("minus5_pre_tax_profit_impact_usd_mn")) if not fuel_row.empty else None
            else:
                fuel_impact = 0.0
            rows.append({
                "dataset_id": "airline_forward_earnings_bridge",
                "company": company, "parent_group": company, "ticker": ticker,
                "entity_scope": "group_consolidated_including_9air" if company == "Juneyao Airlines" else "group_consolidated",
                "scenario": scenario, "forecast_horizon": "FY2026_pre_interim",
                "snapshot_as_of_date": snapshot, "forecast_status": "research_model_not_issuer_guidance",
                "fy2025_revenue_native_mn": actual_revenue, "fy2025_revenue_usd_mn": actual_revenue_usd,
                "fy2025_attributable_profit_native_mn": actual_profit, "fy2025_attributable_profit_usd_mn": actual_profit_usd,
                "fy2025_operating_cost_native_mn": actual_cost, "fy2025_ask_mn_seat_km": actual_ask,
                "fy2025_rpk_mn_passenger_km": actual_rpk, "fy2025_load_factor_pct": actual_fy_lf,
                "fy2025_passenger_yield_native": actual_yield, "fy2025_rask_native_per_ask": actual_rask,
                "fy2025_cask_native_per_ask": actual_cask, "fy2025_fuel_cost_share_pct": actual_fuel_share,
                "fy2025_fuel_cost_native_per_ask": actual_fuel_per_ask, "fy2025_nonfuel_cask_native_per_ask": actual_nonfuel_cask,
                "h1_2025_ask_mn_seat_km": h1_ask,
                "h1_2025_rpk_mn_passenger_km": h1_rpk, "h1_2025_load_factor_pct": h1_lf,
                "h1_2026_ask_yoy_pct": _num(expectation.get("h1_ask_yoy_pct")),
                "h1_2026_rpk_yoy_pct": _num(expectation.get("h1_rpk_yoy_pct")),
                "h1_2026_passenger_lf_change_pp": _num(expectation.get("h1_passenger_lf_change_pp")),
                "rpk_growth_assumption_pct": rpk_growth, "ask_growth_assumption_pct": ask_growth,
                "rask_growth_assumption_pct": rask_growth, "cask_growth_assumption_pct": cask_growth,
                "forecast_ask_mn_seat_km": forecast_ask, "forecast_rpk_mn_passenger_km": forecast_rpk,
                "forecast_load_factor_pct": forecast_lf,
                "forecast_load_factor_change_pp": forecast_lf - actual_fy_lf if forecast_lf is not None and actual_fy_lf is not None else None,
                "forecast_passenger_yield_native": actual_yield * (1.0 + rask_growth / 100.0) if actual_yield is not None and rask_growth is not None else None,
                "forecast_rask_native_per_ask": forecast_rask, "forecast_cask_native_per_ask": forecast_cask,
                "forecast_revenue_native_mn": forecast_revenue, "forecast_operating_cost_native_mn": forecast_cost,
                "forecast_fuel_cost_native_mn": forecast_fuel_cost, "forecast_nonfuel_operating_cost_native_mn": forecast_nonfuel_cost,
                "forecast_operating_profit_native_mn": forecast_operating_profit, "forecast_revenue_usd_mn": revenue_usd,
                "forecast_operating_cost_usd_mn": cost_usd, "forecast_operating_profit_usd_mn": operating_profit_usd,
                "profit_proxy_method": profit_method, "forecast_net_profit_proxy_native_mn": forecast_net_profit,
                "forecast_net_profit_proxy_usd_mn": net_profit_usd,
                "fuel_shock_pct": shock, "fuel_overlay_pre_tax_usd_mn": fuel_impact,
                "fuel_overlay_included_in_core_earnings": False,
                "consensus_fy2026_revenue_usd_mn": consensus_revenue_usd,
                "consensus_fy2026_profit_usd_mn": consensus_profit_usd,
                "consensus_fy2026_net_margin_pct": consensus_margin,
                "revenue_gap_to_consensus_pct": 100.0 * revenue_usd / consensus_revenue_usd - 100.0 if revenue_usd is not None and consensus_revenue_usd else None,
                "earnings_gap_to_consensus_pct": 100.0 * net_profit_usd / consensus_profit_usd - 100.0 if net_profit_usd is not None and consensus_profit_usd else None,
                "consensus_revenue_analyst_count": _num(expectation.get("fy2026_revenue_consensus_coverage_n")),
                "consensus_profit_analyst_count": _num(expectation.get("fy2026_net_profit_consensus_coverage_n")),
                "consensus_snapshot_date": _date(expectation.get("snapshot_date")),
                "consensus_revenue_as_of_date": _date(expectation.get("revenue_consensus_as_of_date")),
                "consensus_profit_as_of_date": _date(expectation.get("profit_consensus_as_of_date")),
                "formal_report_scheduled_date": _date(expectation.get("formal_report_scheduled_date")),
                "assumption_source": a.get("assumption_source"), "assumption_status": a.get("assumption_status"),
                "assumption_note": "Traffic uses company H1 run-rate; RASK is the pricing/mix proxy; fuel overlay is a separate stress and not added to core earnings.",
                "fuel_pass_through_status": "schedule_context_only_no_realized_recovery",
                "hsr_coverage_status": hsr_row.get("coverage_status", "pending") if not hsr_row.empty else "pending",
                "hsr_candidate_route_count": _num(hsr_row.get("candidate_route_count")) if not hsr_row.empty else None,
                "hsr_verified_observation_count": _num(hsr_row.get("verified_observation_count")) if not hsr_row.empty else None,
                **scope_fields,
                "fx_native_per_usd": fx_native_per_usd,
                "source_quality": "derived_multi_source_research_bridge",
                "source_paths": ";".join(str(path) for path in (DRIVERS_PATH, EXPECTATION_PATH, OPERATING_PATH, YIELD_PATH, FUEL_PATH, ASSUMPTION_PATH, HSR_PATH, SCOPE_PATH)),
                "source_note": "Primary FY2025/1H2025 issuer drivers plus company H1 traffic diagnostics, current consensus and explicit scenario assumptions; not a broker forecast.",
                "retrieved_at": retrieved,
            })
    result = pd.DataFrame(rows)
    result.to_csv(FORWARD_OUTPUT_PATH, index=False)
    return result


def _score_value(value: object, default: float = 0.0) -> float:
    parsed = _num(value)
    return default if parsed is None else parsed


def _bridge_lookup(bridge: pd.DataFrame, company: str, scenario: str) -> pd.Series:
    return _row(bridge, company, scenario=scenario)


def _historical_status(pair_scenarios: pd.DataFrame, pair_id: str) -> str:
    row = pair_scenarios[
        pair_scenarios.get("pair_id", pd.Series(dtype=object)).eq(pair_id)
        & pair_scenarios.get("scenario", pd.Series(dtype=object)).eq("base")
    ]
    return str(row.iloc[0].get("historical_divergence_status", "incomplete")) if not row.empty else "incomplete"


def _prior_pair_bucket(pair_scenarios: pd.DataFrame, pair_id: str) -> str:
    rows = pair_scenarios[pair_scenarios.get("pair_id", pd.Series(dtype=object)).eq(pair_id)]
    return str(rows.iloc[0].get("pair_selection_bucket", "")) if not rows.empty else ""


def build_airline_pair_scorecard(
    *,
    bridge: pd.DataFrame | None = None,
    pair_screen: pd.DataFrame | None = None,
    pair_scenarios: pd.DataFrame | None = None,
    pair_risk: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    bridge = bridge if bridge is not None else pd.read_csv(FORWARD_OUTPUT_PATH) if FORWARD_OUTPUT_PATH.exists() else build_airline_forward_earnings_bridge()
    pair_screen = pair_screen if pair_screen is not None else pd.read_csv(PAIR_SCREEN_PATH)
    pair_scenarios = pair_scenarios if pair_scenarios is not None else pd.read_csv(PAIR_SCENARIO_PATH)
    pair_risk = pair_risk if pair_risk is not None else pd.read_csv(PAIR_RISK_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    for _, screen in pair_screen.iterrows():
        pair_id = str(screen["pair_id"])
        a_name, b_name = str(screen["company_a"]), str(screen["company_b"])
        a_base, b_base = _bridge_lookup(bridge, a_name, "base"), _bridge_lookup(bridge, b_name, "base")
        a_bear, b_bear = _bridge_lookup(bridge, a_name, "bear"), _bridge_lookup(bridge, b_name, "bear")
        a_bull, b_bull = _bridge_lookup(bridge, a_name, "bull"), _bridge_lookup(bridge, b_name, "bull")
        a_gap, b_gap = _num(a_base.get("earnings_gap_to_consensus_pct")), _num(b_base.get("earnings_gap_to_consensus_pct"))
        a_rev_gap, b_rev_gap = _num(a_base.get("revenue_gap_to_consensus_pct")), _num(b_base.get("revenue_gap_to_consensus_pct"))
        a_spread = abs(_score_value(a_bull.get("earnings_gap_to_consensus_pct")) - _score_value(a_bear.get("earnings_gap_to_consensus_pct")))
        b_spread = abs(_score_value(b_bull.get("earnings_gap_to_consensus_pct")) - _score_value(b_bear.get("earnings_gap_to_consensus_pct")))
        forecast_asymmetry = abs(_score_value(a_gap) - _score_value(b_gap))
        scenario_asymmetry = abs(a_spread - b_spread)
        historical = _historical_status(pair_scenarios, pair_id)
        data_points = 20 if screen.get("data_comparability_status") == "both_core_data_ready" else 10
        expectation_points = 15 if screen.get("expectation_comparability_status") == "both_have_dated_expectation_evidence" else 5 if screen.get("expectation_comparability_status") == "asymmetric_expectation_evidence" else 0
        operating_points = 15 if not a_base.empty and not b_base.empty and pd.notna(a_base.get("h1_2026_rpk_yoy_pct")) and pd.notna(b_base.get("h1_2026_rpk_yoy_pct")) else 8 if not a_base.empty or not b_base.empty else 0
        variant_points = min(15.0, forecast_asymmetry * 1.5) + min(5.0, scenario_asymmetry * 0.5)
        historical_points = 15 if historical == "material_historical_divergence" else 8 if historical == "mixed_historical_signal" else 0
        catalyst_points = 10 if screen.get("catalyst_status") == "both_disclosed_or_same_stage" else 5
        corr = _num(screen.get("correlation_a_b"))
        risk_points = 5 if corr is not None and 0.30 <= corr <= 0.85 else 2 if corr is not None and 0.20 <= corr <= 0.90 else 0
        score = round(data_points + expectation_points + operating_points + variant_points + historical_points + catalyst_points + risk_points, 2)
        rows.append({
            "dataset_id": "airline_pair_scorecard", "pair_id": pair_id,
            "company_a": a_name, "company_b": b_name,
            "asset_a": screen.get("asset_a"), "asset_b": screen.get("asset_b"),
            "prior_selection_bucket": _prior_pair_bucket(pair_scenarios, pair_id),
            "screen_status": screen.get("screen_status"), "historical_divergence_status": historical,
            "hsr_candidate_route_count_a": _num(a_base.get("hsr_candidate_route_count")),
            "hsr_candidate_route_count_b": _num(b_base.get("hsr_candidate_route_count")),
            "hsr_verified_observation_count_a": _num(a_base.get("hsr_verified_observation_count")),
            "hsr_verified_observation_count_b": _num(b_base.get("hsr_verified_observation_count")),
            "hsr_coverage_status_a": a_base.get("hsr_coverage_status", "pending"),
            "hsr_coverage_status_b": b_base.get("hsr_coverage_status", "pending"),
            "nine_air_scope_status_a": a_base.get("nine_air_scope_status", "not_applicable_non_juneyao"),
            "nine_air_scope_status_b": b_base.get("nine_air_scope_status", "not_applicable_non_juneyao"),
            "nine_air_passenger_share_pct_a": _num(a_base.get("nine_air_passenger_share_pct")),
            "nine_air_passenger_share_pct_b": _num(b_base.get("nine_air_passenger_share_pct")),
            "nine_air_fleet_share_pct_a": _num(a_base.get("nine_air_fleet_share_pct")),
            "nine_air_fleet_share_pct_b": _num(b_base.get("nine_air_fleet_share_pct")),
            "base_earnings_gap_a_pct": a_gap, "base_earnings_gap_b_pct": b_gap,
            "base_earnings_gap_a_minus_b_pct": a_gap - b_gap if a_gap is not None and b_gap is not None else None,
            "base_revenue_gap_a_pct": a_rev_gap, "base_revenue_gap_b_pct": b_rev_gap,
            "base_revenue_gap_a_minus_b_pct": a_rev_gap - b_rev_gap if a_rev_gap is not None and b_rev_gap is not None else None,
            "earnings_scenario_spread_a_pct": a_spread, "earnings_scenario_spread_b_pct": b_spread,
            "forecast_asymmetry_pct": forecast_asymmetry, "scenario_asymmetry_pct": scenario_asymmetry,
            "correlation_a_b": corr, "hedged_spread_max_drawdown_pct": _num(screen.get("hedged_spread_max_drawdown_a_minus_beta_b_pct")),
            "data_completeness_points": data_points, "expectation_comparability_points": expectation_points,
            "operating_anchor_points": operating_points, "variant_asymmetry_points": round(variant_points, 2),
            "historical_divergence_points": historical_points, "catalyst_points": catalyst_points,
            "risk_points": risk_points, "selection_score": score,
            "selection_method": "transparent_100_point_research_score_not_trade_signal",
            "source_quality": "derived_from_forward_bridge_and_existing_pair_layers",
            "source_paths": ";".join(str(path) for path in (FORWARD_OUTPUT_PATH, PAIR_SCREEN_PATH, PAIR_SCENARIO_PATH, PAIR_RISK_PATH)),
            "retrieved_at": retrieved,
        })
    result = pd.DataFrame(rows)
    result = result.sort_values(["selection_score", "forecast_asymmetry_pct"], ascending=False).reset_index(drop=True)
    result["rank"] = range(1, len(result) + 1)
    result["selection_bucket"] = "monitor"
    eligible = result["historical_divergence_status"].ne("historical_bridge_incomplete")
    core_candidates = result[eligible]
    if not core_candidates.empty:
        core_index = core_candidates.index[0]
        result.loc[core_index, "selection_bucket"] = "core_candidate"
        backup_indices = [index for index in result.index if index != core_index and bool(eligible.loc[index])][:3]
        result.loc[backup_indices, "selection_bucket"] = "backup_candidate"
    result["selection_note"] = result.apply(
        lambda row: "Highest-scoring direction-neutral candidate" if row["selection_bucket"] == "core_candidate"
        else "Next highest-scoring direction-neutral monitor" if row["selection_bucket"] == "backup_candidate"
        else "Monitor until forecast or source gaps improve", axis=1,
    )
    result.to_csv(PAIR_OUTPUT_PATH, index=False)
    return result


def build_airline_forward_invalidation_rules(
    *,
    bridge: pd.DataFrame | None = None,
    expectations: pd.DataFrame | None = None,
    operating: pd.DataFrame | None = None,
    fuel: pd.DataFrame | None = None,
    hsr: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    bridge = bridge if bridge is not None else pd.read_csv(FORWARD_OUTPUT_PATH) if FORWARD_OUTPUT_PATH.exists() else build_airline_forward_earnings_bridge()
    expectations = expectations if expectations is not None else pd.read_csv(EXPECTATION_PATH)
    operating = operating if operating is not None else pd.read_csv(OPERATING_PATH)
    fuel = fuel if fuel is not None else pd.read_csv(FUEL_PATH)
    hsr = hsr if hsr is not None else pd.read_csv(HSR_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    risk_templates = (
        ("demand_capacity", "Demand fails capacity", "H1 RPK versus ASK growth and passenger load factor", "RPK−ASK gap turns <= 0 or passenger load factor declines in the next validation window", "traffic volume and load-factor operating leverage"),
        ("pricing", "Pricing/mix fails the bridge", "Reported passenger yield/RASK versus the base assumption", "Realized yield/RASK is below the base case by more than 2 percentage points", "revenue per ASK and operating margin"),
        ("fuel_cost", "Fuel/cost shock is not absorbed", "Fuel cost share, +5% fuel sensitivity and surcharge policy", "Fuel +5% overlay is not offset by realized yield, surcharge recovery or non-fuel CASK control", "fuel expense, CASK and earnings sensitivity"),
        ("profit_scope", "Profit bridge or scope breaks", "FY2025 profit-base method, 9 Air scope and current consensus", "Formal interim result invalidates the profit proxy, or disclosed scope/mix cannot support the bridge", "net-profit conversion, consolidated margin and expectations gap"),
    )
    for company, ticker in MAINLAND_COMPANIES:
        base = _bridge_lookup(bridge, company, "base")
        expectation = _company_expectation(expectations, company)
        op = _row(operating, company)
        fuel_row = _fuel_row(fuel, company, 5.0)
        hsr_row = _row(hsr, company)
        rpk_growth = _num(base.get("h1_2026_rpk_yoy_pct"))
        ask_growth = _num(base.get("h1_2026_ask_yoy_pct"))
        gap = rpk_growth - ask_growth if rpk_growth is not None and ask_growth is not None else None
        evidence = {
            "demand_capacity": f"H1 RPK growth={rpk_growth:.2f}% vs ASK growth={ask_growth:.2f}%; gap={gap:.2f}pp" if gap is not None else "H1 traffic gap missing",
            "pricing": f"FY2025 yield={_num(base.get('fy2025_passenger_yield_native'))}; base RASK growth={_num(base.get('rask_growth_assumption_pct')):.2f}%" if _num(base.get("rask_growth_assumption_pct")) is not None else "yield/RASK anchor missing",
            "fuel_cost": f"FY2025 fuel share={_num(base.get('fy2025_fuel_cost_share_pct'))}; +5% pre-tax sensitivity={_num(fuel_row.get('plus5_pre_tax_profit_impact_usd_mn')) if not fuel_row.empty else None} USD mn",
            "profit_scope": f"profit method={base.get('profit_proxy_method', 'missing')}; consensus net margin={_num(base.get('consensus_fy2026_net_margin_pct'))}",
        }
        if company == "Juneyao Airlines":
            evidence["profit_scope"] += f"; 9 Air passenger share={_num(base.get('nine_air_passenger_share_pct'))}%; fleet share={_num(base.get('nine_air_fleet_share_pct'))}%"
        for category, risk, leading, trigger, channel in risk_templates:
            rows.append({
                "dataset_id": "airline_forward_invalidation_rules",
                "company": company, "parent_group": company, "ticker": ticker,
                "risk_category": category, "risk": risk, "leading_indicator": leading,
                "current_evidence": evidence[category], "invalidation_trigger": trigger,
                "earnings_impact_channel": channel, "current_status": "monitor_before_formal_1H2026",
                "is_modelled_analysis": True,
                "hsr_coverage_status": hsr_row.get("coverage_status", "pending") if not hsr_row.empty else "pending",
                "formal_report_scheduled_date": _date(expectation.get("formal_report_scheduled_date")),
                "source_as_of_date": _date(expectation.get("snapshot_date")),
                "source_quality": "derived_multi_source_invalidation_contract",
                "source_paths": ";".join(str(path) for path in (FORWARD_OUTPUT_PATH, EXPECTATION_PATH, OPERATING_PATH, FUEL_PATH, HSR_PATH)),
                "retrieved_at": retrieved,
            })
    result = pd.DataFrame(rows)
    result.to_csv(RISK_OUTPUT_PATH, index=False)
    return result


def fetch_airline_forward_earnings_and_pair_scorecard() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bridge = build_airline_forward_earnings_bridge()
    scorecard = build_airline_pair_scorecard(bridge=bridge)
    risks = build_airline_forward_invalidation_rules(bridge=bridge)
    return bridge, scorecard, risks
