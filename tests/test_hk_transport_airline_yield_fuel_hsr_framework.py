from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_yield_fuel_hsr_framework import (
    MAINLAND_COMPANIES,
    build_airline_fuel_pass_through_hedge_matrix,
    build_airline_hsr_research_coverage,
    build_airline_yield_fuel_research_queue,
    build_airline_yield_pricing_matrix,
)


def test_yield_pricing_matrix_expands_to_six_mainland_airlines() -> None:
    frame = build_airline_yield_pricing_matrix()
    assert len(frame) == 12
    assert set(frame.company) == {company for company, _ in MAINLAND_COMPANIES}
    spring = frame[(frame.company == "Spring Airlines") & frame.statement_period.eq("FY2025")].iloc[0]
    assert spring["reported_passenger_yield_native"] == pytest.approx(0.37)
    assert spring["passenger_revenue_mix_pct"] > 90
    juneyao_h1 = frame[(frame.company == "Juneyao Airlines") & frame.statement_period.eq("1H2025")].iloc[0]
    assert juneyao_h1["rask_proxy_native"] == pytest.approx(0.425867, abs=1e-5)
    assert juneyao_h1["pricing_data_status"] in {"reported_yield_plus_mix_available", "reported_yield_only", "derived_yield_only"}
    assert frame["pricing_research_caveat"].notna().all()


def test_fuel_matrix_separates_surcharge_hedge_and_sensitivity() -> None:
    frame = build_airline_fuel_pass_through_hedge_matrix()
    assert len(frame) == 12
    spring = frame[(frame.company == "Spring Airlines") & frame.statement_period.eq("FY2025")].iloc[0]
    eastern = frame[(frame.company == "China Eastern Airlines") & frame.statement_period.eq("FY2025")].iloc[0]
    assert spring["surcharge_gt800_current_cny"] == pytest.approx(100.0)
    assert spring["pass_through_status"] == "schedule_context_only_no_realized_recovery"
    assert not bool(spring["numeric_hedge_anchor_available"])
    assert bool(eastern["numeric_hedge_anchor_available"])
    assert eastern["hedge_notional_unit"] == "barrels"
    assert eastern["hedge_notional_native"] == pytest.approx(500000.0)
    assert eastern["hedge_fair_value_change_native"] == pytest.approx(3.75)
    assert eastern["hedge_fair_value_end_native"] == pytest.approx(3.75)
    assert pd.isna(frame[frame.statement_period.eq("1H2025")]["plus5_pre_tax_profit_impact_usd_mn"]).all()


def test_research_queue_and_hsr_coverage_make_missingness_actionable() -> None:
    yield_matrix = build_airline_yield_pricing_matrix()
    fuel_matrix = build_airline_fuel_pass_through_hedge_matrix()
    queue = build_airline_yield_fuel_research_queue(yield_matrix=yield_matrix, fuel_matrix=fuel_matrix)
    hsr = build_airline_hsr_research_coverage()
    assert len(queue) == 48
    assert set(queue.category) == {"yield_pricing", "fuel_pass_through", "fuel_hedging"}
    assert len(hsr) == 6
    air_china = hsr[hsr.company.eq("Air China")].iloc[0]
    # CAAC seasonal new-route licence intake added Air China's first candidates.
    assert air_china["candidate_route_count"] > 0
    assert air_china["query_leg_count"] > 0
    spring = hsr[hsr.company.eq("Spring Airlines")].iloc[0]
    assert spring["candidate_route_count"] > 0
    assert spring["verified_observation_count"] > 0
    assert "missing" in spring["coverage_status"] or "partial" in spring["coverage_status"]
