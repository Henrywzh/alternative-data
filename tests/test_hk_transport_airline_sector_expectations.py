from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources.airline_sector_expectations import (
    build_airline_sector_expectation_snapshot,
)


def test_sector_expectation_snapshot_keeps_native_scope_and_coverage_flags() -> None:
    result = build_airline_sector_expectation_snapshot(retrieved_at="2026-08-06T00:00:00+00:00")

    assert len(result) == 8
    assert len(result.columns) == 96
    assert list(result.columns)
    assert result["source_quality"].isin({"derived_sector_aggregate", "derived_company_bridge"}).all()

    sector = result.loc[result["scope_type"].eq("sector_aggregate")].iloc[0]
    assert sector["native_currency"] == "RMB"
    assert sector["company_count"] == 6
    assert sector["h1_ask_yoy_pct"] == pytest.approx(2.597445, abs=1e-6)
    assert sector["h1_rpk_yoy_pct"] == pytest.approx(4.790668, abs=1e-6)
    assert sector["h1_passenger_lf_change_pp"] == pytest.approx(1.7942258009539813, abs=1e-9)
    assert sector["fy2026_revenue_consensus_coverage_n"] == 6
    assert sector["latest_report_profit_coverage_n"] == 6
    assert sector["latest_report_ask_coverage_n"] == 6
    assert sector["latest_report_rpk_coverage_n"] == 6
    assert sector["latest_report_passenger_load_factor_pct"] == pytest.approx(100.0 * sector["latest_report_rpk_mn_passenger_km"] / sector["latest_report_ask_mn_seat_km"])
    assert sector["latest_report_passenger_yield_native"] > 0
    assert sector["latest_report_rask_native"] > 0
    assert sector["latest_report_cask_native"] > 0
    assert sector["latest_report_cash_coverage_n"] == 5
    assert sector["latest_report_total_liabilities_coverage_n"] == 5
    assert sector["latest_report_interest_bearing_debt_coverage_n"] == 3
    assert sector["latest_report_capex_cash_paid_coverage_n"] == 3
    assert sector["latest_report_cash_and_cash_equivalents_native_mn"] > 0
    assert sector["latest_report_total_liabilities_native_mn"] > 0
    assert sector["latest_report_interest_bearing_debt_native_mn"] > 0
    assert sector["latest_report_capex_cash_paid_native_mn"] > 0
    assert pd.isna(sector["latest_report_liabilities_to_assets_pct"])
    assert sector["formal_report_status"] == "scheduled"
    assert sector["formal_report_scheduled_date"] == "2026-08-25"
    assert sector["h1_earnings_warning_company_count"] == 4
    assert sector["hk_broker_true_revision_count"] == 0
    assert sector["unified_estimate_revision_count"] == 162
    assert sector["unified_up_revision_count"] == 38
    assert sector["unified_down_revision_count"] == 89
    assert sector["unified_revision_balance"] == -51
    assert sector["unified_revision_company_coverage_n"] == 5
    assert sector["unified_latest_estimate_revision_date"] == "2026-05-05"
    assert sector["energy_observation_date"] == "2026-07-31"
    assert sector["jet_fuel_spot_usd_per_gallon"] > 0
    assert sector["brent_spot_usd_per_barrel"] > 0
    assert sector["h1_2025_jet_fuel_avg_usd_per_gallon"] == pytest.approx(2.108598360655738)
    assert sector["h1_2026_jet_fuel_avg_usd_per_gallon"] == pytest.approx(3.1720975609756104)
    assert sector["h1_jet_fuel_avg_yoy_pct"] == pytest.approx(50.43631046773558)
    assert sector["h1_brent_avg_yoy_pct"] == pytest.approx(27.01845835364093)
    assert sector["h1_wti_avg_yoy_pct"] == pytest.approx(23.737956120371126)
    assert sector["h1_rpk_minus_ask_growth_gap_pp"] == pytest.approx(2.193222)
    assert sector["fy2026_revenue_consensus_avg_usd_mn"] > 0
    assert sector["fy2026_net_profit_consensus_avg_usd_mn"] > 0
    assert sector["market_cap_to_consensus_revenue_usd"] > 0
    assert sector["consensus_valuation_quality"] == "unstable_profit_base"

    cathay = result.loc[result["ticker"].eq("0293.HK")].iloc[0]
    assert cathay["latest_financial_period"] == "1H2026"
    assert cathay["formal_report_status"] == "disclosed"
    assert cathay["fy2026_revenue_consensus_avg_usd_mn"] > 0
    assert cathay["energy_observation_date"] == "2026-07-31"
    # FY2026 full-year consensus must not be compared to a 1H2026 actual.
    assert pd.isna(cathay["fy2026_revenue_growth_vs_latest_actual_pct"])
    assert pd.isna(cathay["fy2026_net_profit_delta_vs_latest_actual_native_mn"])
    assert cathay["latest_report_ask_coverage_n"] == 1
    assert cathay["latest_report_rask_native"] > 0
    assert cathay["latest_report_net_borrowings_native_mn"] == 47267.0
    assert cathay["latest_report_available_unrestricted_liquidity_native_mn"] == 23575.0
    assert cathay["unified_estimate_revision_count"] == 0
