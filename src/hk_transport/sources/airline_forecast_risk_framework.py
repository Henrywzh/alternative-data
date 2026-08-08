"""Sector/company forecast assumptions and risk-invalidation framework.

This research-only layer separates observed KPI anchors from analyst stress
assumptions. It does not select a pair, construct a hedge, or produce a trade
recommendation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR

TREND_PATH = NORMALIZED_DIR / "airline_sector_trend_snapshot.csv"
SECTOR_PATH = NORMALIZED_DIR / "airline_sector_expectation_snapshot.csv"
EXPECTATION_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
PRE_H1_PATH = NORMALIZED_DIR / "airline_pre_h1_scenario_bridge.csv"
OPERATING_PATH = NORMALIZED_DIR / "airline_operating_diagnostics.csv"
FUEL_PATH = NORMALIZED_DIR / "airline_fuel_sensitivity_scenarios.csv"
CALENDAR_PATH = NORMALIZED_DIR / "airline_sector_event_calendar.csv"
FUNDAMENTALS_PATH = NORMALIZED_DIR / "airline_company_fundamentals.csv"
MODEL_INPUTS_PATH = NORMALIZED_DIR / "airline_core_pair_model_inputs.csv"
ASSUMPTIONS_PATH = NORMALIZED_DIR / "airline_forecast_assumptions.csv"
RISKS_PATH = NORMALIZED_DIR / "airline_risk_invalidation_matrix.csv"

SCENARIOS = ("bear", "base", "bull")


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _latest_date(frames: list[pd.DataFrame | None]) -> str:
    values: list[str] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for column in ("snapshot_date", "as_of_date", "source_as_of_date"):
            if column in frame.columns:
                values.extend(str(v)[:10] for v in frame[column].dropna())
    return max((v for v in values if len(v) == 10 and v[4] == "-" and v[7] == "-"), default="pending")


def _trend_row(trend: pd.DataFrame, company: str, metric: str) -> pd.Series:
    rows = trend[
        trend["company"].eq(company)
        & trend["scope_type"].eq("company")
        & trend["region"].eq("Total")
        & trend["metric"].eq(metric)
        & trend["current_period"].eq("2026H1")
    ]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _scenario_value(anchor: float | None, scenario: str, *, bear_delta: float, bull_delta: float) -> float | None:
    if anchor is None:
        return None
    delta = bear_delta if scenario == "bear" else bull_delta if scenario == "bull" else 0.0
    return round(anchor + delta, 4)


def build_airline_forecast_assumptions(
    *,
    trend: pd.DataFrame | None = None,
    sector: pd.DataFrame | None = None,
    expectations: pd.DataFrame | None = None,
    pre_h1: pd.DataFrame | None = None,
    operating: pd.DataFrame | None = None,
    fuel: pd.DataFrame | None = None,
    model_inputs: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build observed-anchor plus bear/base/bull assumption rows."""
    trend = trend if trend is not None else pd.read_csv(TREND_PATH)
    sector = sector if sector is not None else pd.read_csv(SECTOR_PATH)
    expectations = expectations if expectations is not None else pd.read_csv(EXPECTATION_PATH)
    pre_h1 = pre_h1 if pre_h1 is not None else pd.read_csv(PRE_H1_PATH)
    operating = operating if operating is not None else pd.read_csv(OPERATING_PATH)
    fuel = fuel if fuel is not None else pd.read_csv(FUEL_PATH)
    model_inputs = model_inputs if model_inputs is not None else pd.read_csv(MODEL_INPUTS_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    as_of = _latest_date([trend, sector, expectations, pre_h1, operating, fuel])
    rows: list[dict[str, object]] = []

    sector_row = sector[sector["scope_type"].eq("sector_aggregate")]
    sector_row = sector_row.iloc[0] if not sector_row.empty else pd.Series(dtype=object)
    sector_anchors = {
        "demand_rpk_growth_pct": _num(sector_row.get("h1_rpk_yoy_pct")),
        "capacity_ask_growth_pct": _num(sector_row.get("h1_ask_yoy_pct")),
        "rpk_minus_ask_gap_pp": _num(sector_row.get("h1_rpk_minus_ask_growth_gap_pp")),
        "fuel_yoy_pct": _num(sector_row.get("h1_jet_fuel_avg_yoy_pct")),
    }
    sector_specs = [
        ("demand_rpk_growth_pct", "% YoY", sector_anchors["demand_rpk_growth_pct"], -3.0, 3.0, "RPK growth remains positive but sensitive to June softness", "July operating release and 1H2026 interim traffic"),
        ("capacity_ask_growth_pct", "% YoY", sector_anchors["capacity_ask_growth_pct"], 3.0, -2.0, "Bear assumes extra capacity absorbs demand; bull assumes discipline", "ASK/RPK gap and load factor"),
        ("fuel_price_overlay_pct", "% shock", 0.0, 5.0, -5.0, "Mechanical overlay around the current fuel regime; not a forward commodity forecast", "Jet fuel spot and fuel-cost share"),
    ]
    for driver, unit, anchor, bear_delta, bull_delta, rationale, validation in sector_specs:
        for scenario in SCENARIOS:
            value = _scenario_value(anchor, scenario, bear_delta=bear_delta, bull_delta=bull_delta)
            rows.append({
                "dataset_id": "airline_forecast_assumptions", "scope_type": "sector",
                "entity": "China mainland listed airlines", "parent_group": "sector",
                "scenario": scenario, "forecast_horizon": "2026H2_pre_interim",
                "driver": driver, "assumption_value": value, "unit": unit,
                "observed_anchor_value": anchor, "anchor_period": "2026H1",
                "assumption_status": "analyst_stress_around_observed_anchor",
                "assumption_rationale": rationale, "validation_kpi": validation,
                "invalidation_trigger": "Observed H1/July demand-capacity direction is opposite to scenario",
                "source_path": str(SECTOR_PATH), "source_quality": str(sector_row.get("source_quality", "pending")),
                "source_as_of_date": str(sector_row.get("snapshot_date", as_of)), "retrieved_at": retrieved,
            })

    company_specs = {
        "Spring Airlines": {"bear_rpk": -3.0, "bull_rpk": 3.0, "bear_ask": 3.0, "bull_ask": -2.0, "bear_lf": -1.0, "bull_lf": 1.0},
        "Juneyao Airlines": {"bear_rpk": -3.0, "bull_rpk": 3.0, "bear_ask": 3.0, "bull_ask": -2.0, "bear_lf": -1.0, "bull_lf": 1.0},
        "9 Air": {"bear_rpk": -3.0, "bull_rpk": 3.0, "bear_ask": 3.0, "bull_ask": -2.0, "bear_lf": -1.0, "bull_lf": 1.0},
    }
    entity_ticker = {"Spring Airlines": "601021.SH", "Juneyao Airlines": "603885.SH", "9 Air": "603885.SH"}
    for company, deltas in company_specs.items():
        rpk_row = _trend_row(trend, company, "rpk")
        ask_row = _trend_row(trend, company, "ask")
        lf_row = _trend_row(trend, company, "passenger_load_factor_pct")
        rpk = _num(rpk_row.get("yoy_change_pct"))
        ask = _num(ask_row.get("yoy_change_pct"))
        lf = _num(lf_row.get("yoy_change_pct"))
        company_source_date = str(rpk_row.get("snapshot_date", as_of)) if rpk is not None else as_of
        exp = expectations[expectations["company"].eq(company if company != "9 Air" else "Juneyao Airlines")]
        exp_row = exp.iloc[0] if not exp.empty else pd.Series(dtype=object)
        pre = pre_h1[pre_h1["company"].eq(company if company != "9 Air" else "Juneyao Airlines")]
        for driver, anchor, bear_delta, bull_delta, unit, rationale, validation, trigger in [
            ("rpk_growth_pct", rpk, deltas["bear_rpk"], deltas["bull_rpk"], "% YoY", "Company demand growth is stressed around the preliminary H1 issuer-release trend", "Monthly RPK/passengers and formal 1H2026 report", "RPK growth falls below ASK growth for the H1/July validation window"),
            ("ask_growth_pct", ask, deltas["bear_ask"], deltas["bull_ask"], "% YoY", "Bear assumes additional capacity pressure; bull assumes capacity discipline", "Monthly ASK and load factor", "ASK growth exceeds RPK growth and load factor deteriorates"),
            ("passenger_load_factor_change_pp", lf, deltas["bear_lf"], deltas["bull_lf"], "pp YoY", "Load-factor sensitivity is an operating diagnostic, not a fare forecast", "Passenger load factor and yield in formal report", "Load factor and yield both deteriorate versus consensus context"),
        ]:
            for scenario in SCENARIOS:
                value = _scenario_value(anchor, scenario, bear_delta=bear_delta, bull_delta=bull_delta)
                rows.append({
                    "dataset_id": "airline_forecast_assumptions", "scope_type": "company",
                    "entity": company, "parent_group": "Juneyao Airlines" if company == "9 Air" else company,
                    "ticker": entity_ticker[company], "scenario": scenario, "forecast_horizon": "2026H2_pre_interim",
                    "driver": driver, "assumption_value": value, "unit": unit,
                    "observed_anchor_value": anchor, "anchor_period": "2026H1_preliminary_monthly_releases" if anchor is not None else "pending_operator_level_data",
                    "assumption_status": "analyst_stress_around_observed_anchor" if anchor is not None else "pending_operator_level_forecast",
                    "assumption_rationale": rationale, "validation_kpi": validation,
                    "invalidation_trigger": trigger, "source_path": str(TREND_PATH),
                    "source_quality": "issuer_monthly_operating_release" if anchor is not None else "pending",
                    "source_as_of_date": company_source_date if anchor is not None else as_of,
                    "retrieved_at": retrieved,
                })

        profit_consensus = _num(exp_row.get("fy2026_net_profit_avg_usd_mn"))
        margin = _num(exp_row.get("fy2026_consensus_net_margin_pct"))
        for scenario in SCENARIOS:
            pre_row = pre[pre["scenario"].eq(scenario)].iloc[0] if not pre[pre["scenario"].eq(scenario)].empty else pd.Series(dtype=object)
            rows.append({
                "dataset_id": "airline_forecast_assumptions", "scope_type": "company",
                "entity": company, "parent_group": "Juneyao Airlines" if company == "9 Air" else company,
                "ticker": entity_ticker[company], "scenario": scenario, "forecast_horizon": "FY2026_consensus_pre_interim",
                "driver": "consensus_profit_usd_mn", "assumption_value": _num(pre_row.get("scenario_profit_after_fuel_usd_mn")) if company != "9 Air" else None,
                "unit": "USD million", "observed_anchor_value": profit_consensus, "anchor_period": "FY2026 consensus",
                "assumption_status": "derived_from_pre_h1_bridge" if company != "9 Air" else "pending_unlisted_subsidiary_consensus",
                "assumption_rationale": "Uses the non-directional pre-H1 bridge; not an independent forecast", "validation_kpi": "Formal interim profit and post-result consensus revision",
                "invalidation_trigger": "Formal result materially outside the scenario range or consensus revision moves opposite to the scenario",
                "source_path": str(PRE_H1_PATH), "source_quality": "derived_multi_source_stress_test" if company != "9 Air" else "pending",
                "source_as_of_date": as_of, "retrieved_at": retrieved,
            })

        model_match = model_inputs[model_inputs["company"].eq(company)]
        model_row = model_match.iloc[0] if not model_match.empty else pd.Series(dtype=object)
        unit_economic_specs = [
            (
                "rask_growth_pct_vs_fy2025",
                _num(model_row.get("fy2025_rask_proxy_rmb_per_ask")),
                -2.0, 2.0, "% vs FY2025",
                "Scenario applies a transparent yield/mix stress around FY2025 total-revenue-per-ASK proxy; it is not passenger yield guidance",
                "Formal interim RASK or revenue divided by ASK",
                "Reported revenue/ASK or disclosed RASK proxy moves outside the scenario interpretation",
            ),
            (
                "cask_growth_pct_vs_fy2025",
                _num(model_row.get("fy2025_cask_rmb_per_ask")),
                2.0, -1.0, "% vs FY2025",
                "Scenario applies a transparent total-cost-per-ASK stress around FY2025 CASK; fuel overlay is kept separately",
                "Formal interim CASK, fuel cost per ASK and non-fuel cost per ATK/ASK",
                "Reported cost per ASK and fuel/non-fuel costs contradict the scenario",
            ),
        ]
        for driver, observed_unit_value, bear_delta, bull_delta, unit, rationale, validation, trigger in unit_economic_specs:
            for scenario in SCENARIOS:
                rows.append({
                    "dataset_id": "airline_forecast_assumptions", "scope_type": "company",
                    "entity": company, "parent_group": "Juneyao Airlines" if company == "9 Air" else company,
                    "ticker": entity_ticker[company], "scenario": scenario, "forecast_horizon": "FY2026_pre_interim",
                    "driver": driver,
                    "assumption_value": _scenario_value(0.0, scenario, bear_delta=bear_delta, bull_delta=bull_delta) if observed_unit_value is not None else None,
                    "unit": unit, "observed_anchor_value": observed_unit_value,
                    "anchor_period": "FY2025 reported unit economics" if observed_unit_value is not None else "pending_standalone_unit_economics",
                    "assumption_status": "analyst_stress_around_fy2025_unit_economics" if observed_unit_value is not None else "pending_standalone_unit_economics",
                    "assumption_rationale": rationale, "validation_kpi": validation,
                    "invalidation_trigger": trigger, "source_path": str(MODEL_INPUTS_PATH),
                    "source_quality": str(model_row.get("source_quality", "pending")) if observed_unit_value is not None else "pending",
                    "source_as_of_date": str(model_row.get("as_of_date", as_of)) if observed_unit_value is not None else as_of,
                    "retrieved_at": retrieved,
                })
    return pd.DataFrame(rows)


def build_airline_risk_invalidation_matrix(
    *,
    trend: pd.DataFrame | None = None,
    sector: pd.DataFrame | None = None,
    expectations: pd.DataFrame | None = None,
    pre_h1: pd.DataFrame | None = None,
    fuel: pd.DataFrame | None = None,
    calendar: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build a research risk register with observable triggers and invalidation rules."""
    trend = trend if trend is not None else pd.read_csv(TREND_PATH)
    sector = sector if sector is not None else pd.read_csv(SECTOR_PATH)
    expectations = expectations if expectations is not None else pd.read_csv(EXPECTATION_PATH)
    pre_h1 = pre_h1 if pre_h1 is not None else pd.read_csv(PRE_H1_PATH)
    fuel = fuel if fuel is not None else pd.read_csv(FUEL_PATH)
    calendar = calendar if calendar is not None else pd.read_csv(CALENDAR_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    as_of = _latest_date([trend, sector, expectations, pre_h1, fuel, calendar])
    sector_row = sector[sector["scope_type"].eq("sector_aggregate")]
    sector_row = sector_row.iloc[0] if not sector_row.empty else pd.Series(dtype=object)
    rows: list[dict[str, object]] = []

    specs = [
        ("sector", "demand", "Macro travel demand slows", "RPK growth and passenger volume", "H1 RPK +4.8% YoY; June softness remains a watch item", "RPK growth below ASK growth for the validation window", "Demand slowdown can pressure load factor, yield and consensus revenue", str(SECTOR_PATH), "derived_sector_aggregate"),
        ("sector", "capacity", "Industry capacity outruns demand", "ASK growth versus RPK growth; load factor", "H1 ASK +2.6% versus RPK +4.8%", "Sector RPK−ASK gap turns negative or load factor falls", "Overcapacity causes fare discounting and margin pressure", str(TREND_PATH), "issuer_monthly_operating_release"),
        ("sector", "fuel", "Fuel regime remains elevated", "Jet fuel spot, fuel-cost share, surcharge", "H1 jet fuel average +50.4% YoY; fuel hedge anchors missing for Spring/Juneyao", "Fuel +5% overlay is not recovered by yield/surcharge", "Fuel cost compresses profit and may create consensus misses", str(FUEL_PATH), "derived_scenario"),
        ("Spring Airlines", "demand_capacity", "Spring demand advantage fades", "Spring RPK−ASK gap and load factor", "Spring H1 RPK +18.0% versus ASK +15.4%", "H1/July RPK−ASK gap <= 0 or LF declines", "Pure-LCC earnings sensitivity shifts from volume to pricing/margin", str(TREND_PATH), "issuer_monthly_operating_release"),
        ("Spring Airlines", "international", "International mix/yield disappoints", "International RPK/ASK, yield and passenger growth", "International exposure is growing but current KPI is preliminary", "International RPK or yield underperforms domestic trend", "Mix benefit and revenue growth assumption weakens", str(TREND_PATH), "issuer_monthly_operating_release"),
        ("Juneyao Airlines", "warning_recovery", "FY2026 H2 recovery implied by consensus is too high", "H1 warning, implied H2 profit, post-warning revisions", "RMB752m midpoint H2 implied from RMB140–210m H1 warning", "Formal H1 result below warning range or consensus remains unrevised despite miss", "Consensus profit and valuation can reset lower", str(PRE_H1_PATH), "derived_multi_source_stress_test"),
        ("Juneyao Airlines", "scope_mix", "Group scope obscures mainline economics", "Juneyao Air versus 9 Air operating scope", "Group operating table includes 9 Air; financials are consolidated", "Mainline/9 Air mix cannot be reconciled to revenue or margin", "Company forecast may misattribute LCC versus network economics", str(NORMALIZED_DIR / "airline_scope_reconciliation.csv"), "primary_issuer"),
        ("Juneyao Airlines", "fuel_international", "B787/international exposure amplifies fuel and FX risk", "International ASK/RPK, fuel share, FX", "Fuel cost share about 32.9%; no numeric hedge anchor", "International RPK/yield weakens while fuel/FX stays adverse", "Margin and cash-flow forecast misses despite passenger volume", str(EXPECTATION_PATH), "derived_company_bridge"),
        ("9 Air", "disclosure", "Subsidiary P&L remains unavailable", "9 Air standalone profit, CASK, fuel and revenue disclosure", "Passenger/fleet and route capacity are available; standalone P&L pending", "Interim report does not provide enough 9 Air standalone economics", "Parent-level thesis cannot cleanly value or forecast subsidiary", str(PRE_H1_PATH), "issuer_subsidiary_disclosures_plus_route_capacity"),
        ("9 Air", "hsr", "Regional HSR substitution proxy is incomplete", "Route-level rail time/fare and 9 Air ASK proxy", "Some route ASK is modelled; several rail legs remain pending", "New route evidence cannot be matched to dated rail observations", "HSR impact remains unquantified rather than zero", str(NORMALIZED_DIR / "airline_hsr_route_query_queue.csv"), "derived_route_observations"),
    ]
    for entity, category, risk, indicator, evidence, trigger, impact, source_path, source_quality in specs:
        rows.append({
            "dataset_id": "airline_risk_invalidation_matrix", "as_of_date": as_of,
            "entity": entity, "risk_category": category, "risk": risk,
            "leading_indicator": indicator, "current_evidence": evidence,
            "invalidation_trigger": trigger, "earnings_impact_channel": impact,
            "current_status": "monitor_before_formal_1h2026", "is_modelled_analysis": True,
            "source_path": source_path, "source_quality": source_quality,
            "source_as_of_date": as_of, "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows)


def fetch_airline_forecast_risk_framework() -> tuple[pd.DataFrame, pd.DataFrame]:
    assumptions = build_airline_forecast_assumptions()
    risks = build_airline_risk_invalidation_matrix()
    assumptions.to_csv(ASSUMPTIONS_PATH, index=False)
    risks.to_csv(RISKS_PATH, index=False)
    return assumptions, risks
