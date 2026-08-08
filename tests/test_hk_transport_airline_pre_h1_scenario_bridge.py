from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_pre_h1_scenario_bridge import (
    build_airline_pre_h1_scenario_bridge,
)


def test_pre_h1_bridge_has_three_scenarios_per_company() -> None:
    frame = build_airline_pre_h1_scenario_bridge()
    assert len(frame) == 6
    assert set(frame["company"]) == {"Spring Airlines", "Juneyao Airlines"}
    assert set(frame["scenario"]) == {"bear", "base", "bull"}
    assert frame.groupby("company").size().eq(3).all()
    assert frame["scenario_status"].eq("mechanical_pre_h1_stress_test_not_forecast").all()


def test_pre_h1_bridge_preserves_freshness_and_scheduled_catalysts() -> None:
    frame = build_airline_pre_h1_scenario_bridge()
    spring = frame[(frame.company == "Spring Airlines") & (frame.scenario == "base")].iloc[0]
    juneyao = frame[(frame.company == "Juneyao Airlines") & (frame.scenario == "base")].iloc[0]
    assert spring["consensus_fy2026_revenue_analyst_count"] == 12.0
    assert spring["profit_consensus_freshness"] == "fresh"
    assert juneyao["consensus_fy2026_revenue_analyst_count"] == 1.0
    assert juneyao["profit_consensus_freshness"] == "stale"
    assert spring["formal_report_scheduled_date"] == "2026-08-29"
    assert juneyao["formal_report_scheduled_date"] == "2026-08-31"
    assert spring["operating_data_status"] == "preliminary_monthly_release_pending_formal_1h2026"
    assert spring["sector_h1_jet_fuel_yoy_pct"] == pytest.approx(50.43631, abs=1e-4)


def test_pre_h1_bridge_fuel_overlay_is_separate_and_units_are_usd() -> None:
    frame = build_airline_pre_h1_scenario_bridge()
    spring_base = frame[(frame.company == "Spring Airlines") & (frame.scenario == "base")].iloc[0]
    spring_bear = frame[(frame.company == "Spring Airlines") & (frame.scenario == "bear")].iloc[0]
    spring_bull = frame[(frame.company == "Spring Airlines") & (frame.scenario == "bull")].iloc[0]
    assert spring_base["fuel_shock_pct"] == 0.0
    assert spring_base["fuel_profit_impact_usd_mn"] == 0.0
    assert pd.notna(spring_base["pair_profit_gap_spring_minus_juneyao_usd_mn"])
    assert spring_bear["fuel_shock_pct"] == 5.0
    assert spring_bull["fuel_shock_pct"] == -5.0
    assert spring_bear["fuel_profit_impact_usd_mn"] < 0
    assert spring_bull["fuel_profit_impact_usd_mn"] > 0
    assert spring_bear["source_quality"] == "derived_multi_source_stress_test"
    assert spring_bear["pair_profit_gap_spring_minus_juneyao_usd_mn"] == pytest.approx(
        spring_bear["scenario_profit_after_fuel_usd_mn"]
        - frame[(frame.company == "Juneyao Airlines") & (frame.scenario == "bear")].iloc[0]["scenario_profit_after_fuel_usd_mn"]
    )


def test_pre_h1_bridge_uses_injected_inputs() -> None:
    expectations = pd.DataFrame([
        {
            "company": "Spring Airlines", "market_ticker": "601021.SH",
            "fy2026_revenue_avg_usd_mn": 1000.0, "fy2026_revenue_low_usd_mn": 900.0,
            "fy2026_revenue_high_usd_mn": 1100.0, "fy2026_revenue_analyst_count": 2,
            "fy2026_net_profit_avg_usd_mn": 100.0, "fy2026_net_profit_low_usd_mn": 80.0,
            "fy2026_net_profit_high_usd_mn": 120.0, "revenue_consensus_freshness_band": "fresh",
            "profit_consensus_freshness_band": "fresh", "formal_report_scheduled_date": "2026-08-29",
        },
        {
            "company": "Juneyao Airlines", "market_ticker": "603885.SH",
            "fy2026_revenue_avg_usd_mn": 900.0, "fy2026_revenue_low_usd_mn": 800.0,
            "fy2026_revenue_high_usd_mn": 1000.0, "fy2026_revenue_analyst_count": 1,
            "fy2026_net_profit_avg_usd_mn": 90.0, "fy2026_net_profit_low_usd_mn": 70.0,
            "fy2026_net_profit_high_usd_mn": 110.0, "revenue_consensus_freshness_band": "fresh",
            "profit_consensus_freshness_band": "stale", "formal_report_scheduled_date": "2026-08-31",
        },
    ])
    frame = build_airline_pre_h1_scenario_bridge(expectations=expectations)
    spring_base = frame[(frame.company == "Spring Airlines") & (frame.scenario == "base")].iloc[0]
    assert spring_base["consensus_fy2026_revenue_usd_mn"] == 1000.0


def test_warning_to_fy_consensus_implies_h2_only_when_warning_exists() -> None:
    frame = build_airline_pre_h1_scenario_bridge()
    juneyao = frame[(frame.company == "Juneyao Airlines") & (frame.scenario == "base")].iloc[0]
    spring = frame[(frame.company == "Spring Airlines") & (frame.scenario == "base")].iloc[0]

    assert juneyao["warning_profit_low_native_mn"] == 140.0
    assert juneyao["warning_profit_high_native_mn"] == 210.0
    assert juneyao["implied_h2_profit_mid_native_mn"] == 752.0
    assert juneyao["warning_to_consensus_status"] == "warning_after_latest_profit_consensus_observation"
    assert juneyao["implied_h2_mid_minus_historical_h2_2025_usd_mn"] > 0

    assert pd.isna(spring["implied_h2_profit_mid_native_mn"])
    assert spring["warning_to_consensus_status"] == "no_earnings_warning_available"
