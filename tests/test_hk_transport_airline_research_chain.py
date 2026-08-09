from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources.airline_research_chain import build_airline_research_chain


def test_research_chain_covers_all_seven_companies_and_stages() -> None:
    result = build_airline_research_chain(retrieved_at="2026-08-07T00:00:00+00:00")

    assert len(result) == 808
    assert result["company"].nunique() == 7
    assert set(result["chain_stage"]) == {"supply", "demand", "revenue", "cost", "earnings", "expectations", "catalyst", "risk", "forecast"}
    assert result["source_field"].notna().all()
    assert result["as_of_date"].notna().all()
    assert result["source_quality"].eq("derived_join_with_source_lineage").all()
    forecast = result.loc[result["chain_stage"].eq("forecast")]
    assert len(forecast) == 180
    assert set(forecast["company"]) == {"Spring Airlines", "Juneyao Airlines", "China Southern Airlines", "China Eastern Airlines", "Air China", "Hainan Airlines Holdings"}
    assert forecast["canonical_metric"].str.contains("base_forecast_revenue_usd_mn").any()
    assert forecast["source_field"].str.startswith("airline_company_financial_forecast_bridge.").all()
    public_rows = result.loc[result["canonical_metric"].eq("public_report_evidence_row_count")]
    assert len(public_rows) == 7
    assert public_rows["value_numeric"].ge(0).all()
    assert result.loc[result["canonical_metric"].eq("public_report_latest_date"), "value_text"].notna().all()
    eligibility_rows = result.loc[result["canonical_metric"].eq("short_eligibility_status")]
    assert len(eligibility_rows) == 7
    assert eligibility_rows["value_text"].notna().all()
    for metric in (
        "latest_report_ask_mn_seat_km", "latest_report_rpk_mn_passenger_km",
        "latest_report_passenger_load_factor_pct", "latest_report_rask_native",
    ):
        assert result.loc[result["canonical_metric"].eq(metric), "value_numeric"].notna().all()
    for metric in (
        "latest_report_cargo_revenue_native_mn",
        "latest_report_cargo_yield_native",
        "latest_report_cargo_load_factor_pct",
        "latest_report_fuel_cost_per_ask_native",
        "latest_report_operating_cash_flow_native_mn",
        "latest_report_fleet_total",
    ):
        rows = result.loc[result["canonical_metric"].eq(metric)]
        assert not rows.empty
        assert rows["value_numeric"].notna().all()
        assert rows["source_field"].str.startswith("airline_earnings_driver_comparability.").all()
    hedge = result.loc[result["canonical_metric"].eq("latest_report_fuel_hedge_native_mn")]
    assert set(hedge["company"]) == {"Cathay Pacific", "China Eastern Airlines"}
    assert hedge["value_numeric"].notna().all()
    for metric in ("yahoo_eps_revision_up_30d", "yahoo_eps_revision_down_30d"):
        signals = result.loc[result["canonical_metric"].eq(metric)]
        assert len(signals) == 6
        assert signals["value_numeric"].notna().all()
    surcharge = result.loc[result["canonical_metric"].eq("fuel_surcharge_context")]
    assert len(surcharge) == 7
    assert surcharge["value_text"].notna().all()
    assert surcharge["as_of_date"].notna().all()
    leverage = result.loc[result["canonical_metric"].eq("latest_discovery_debt_to_assets_pct")]
    assert len(leverage) == 6
    assert leverage["value_numeric"].between(0, 100).all()
    assert leverage["as_of_date"].eq("2026-03-31").all()
    cash = result.loc[result["canonical_metric"].eq("latest_report_cash_and_cash_equivalents_native_mn")]
    assert len(cash) == 5
    assert cash["value_numeric"].gt(0).all()
    assert cash["as_of_date"].notna().all()
    liabilities = result.loc[result["canonical_metric"].eq("latest_report_total_liabilities_native_mn")]
    leverage_primary = result.loc[result["canonical_metric"].eq("latest_report_liabilities_to_assets_pct")]
    assert len(liabilities) == 5
    assert len(leverage_primary) == 5
    assert leverage_primary["value_numeric".between(0, 100).all() if False else "value_numeric"].between(0, 100).all()
    debt = result.loc[result["canonical_metric"].eq("latest_report_interest_bearing_debt_native_mn")]
    capex = result.loc[result["canonical_metric"].eq("latest_report_capex_cash_paid_native_mn")]
    assert len(debt) == 3
    assert len(capex) == 3
    assert debt["value_numeric"].gt(0).all()
    assert capex["value_numeric"].gt(0).all()
    net_borrowings = result.loc[result["canonical_metric"].eq("latest_report_net_borrowings_native_mn")]
    liquidity = result.loc[result["canonical_metric"].eq("latest_report_available_unrestricted_liquidity_native_mn")]
    assert len(net_borrowings) == 1
    assert len(liquidity) == 1
    assert net_borrowings["value_numeric"].gt(0).all()
    assert liquidity["value_numeric"].gt(0).all()
    for metric in (
        "unified_estimate_revision_count", "unified_up_revision_count",
        "unified_down_revision_count",
    ):
        assert result.loc[result["canonical_metric"].eq(metric), "value_numeric"].notna().all()
    revision_dates = result.loc[
        result["canonical_metric"].eq("unified_latest_estimate_revision_date"), "as_of_date"
    ]
    assert revision_dates.notna().any()
    alignment = result.loc[
        result["canonical_metric"].isin({
            "hk_profit_consensus_usd_mn", "a_profit_consensus_usd_mn",
            "profit_gap_a_minus_hk_usd_mn", "profit_sign_disagreement_hk_vs_a",
            "forecast_warning_alignment",
        })
    ]
    assert alignment["company"].nunique() == 3
    assert alignment["source_field"].str.startswith("airline_consensus_dispersion").all()
    assert result.loc[
        result["canonical_metric"].eq("profit_sign_disagreement_hk_vs_a"), "value_text"
    ].eq("True").all()
    h1_bridge = result.loc[
        result["canonical_metric"].eq("implied_h2_profit_at_h1_warning_mid_native_mn")
    ]
    assert set(h1_bridge["company"]) == {
        "Air China", "China Southern Airlines", "China Eastern Airlines", "Juneyao Airlines"
    }
    assert h1_bridge["unit"].eq("RMB million").all()
    assert h1_bridge["source_field"].eq("airline_expectation_bridge.fy2026_net_profit_avg_native_mn").all()
    historical_h2 = result.loc[
        result["canonical_metric"].eq("historical_2h2025_profit_native_mn")
    ]
    assert set(historical_h2["company"]) == {
        "Air China", "China Southern Airlines", "China Eastern Airlines", "Juneyao Airlines"
    }
    assert historical_h2["unit"].eq("RMB million").all()
    demand_gap = result.loc[result["canonical_metric"].eq("rpk_minus_ask_growth_gap_pp")]
    assert len(demand_gap) == 7
    assert demand_gap["unit"].eq("percentage points").all()
    southern_gap = demand_gap.loc[demand_gap["company"].eq("China Southern Airlines"), "value_numeric"].item()
    assert southern_gap == pytest.approx(-0.764785)
    for metric in (
        "latest_event_metric", "latest_event_value_min", "latest_event_value_max",
        "latest_event_native_unit", "latest_event_source_url",
    ):
        assert result.loc[result["canonical_metric"].eq(metric), "value_text" if metric in {"latest_event_metric", "latest_event_native_unit", "latest_event_source_url"} else "value_numeric"].notna().all()
    for metric in (
        "fuel_plus_5pct_profit_impact_usd_mn", "fuel_minus_5pct_profit_impact_usd_mn",
        "fuel_plus_5pct_scenario_method", "fuel_minus_5pct_scenario_method",
        "fuel_scenario_fx_observation_date",
    ):
        values = result.loc[result["canonical_metric"].eq(metric)]
        assert not values.empty
        assert values["value_numeric"].notna().all() if metric.endswith("usd_mn") else values["value_text"].notna().all()
    for metric in (
        "news_event_count_in_window", "news_direct_headline_count_in_window",
    ):
        assert result.loc[result["canonical_metric"].eq(metric), "value_numeric"].notna().all()
    for metric in (
        "news_latest_published_at", "news_latest_title", "news_latest_source_url",
    ):
        assert result.loc[result["canonical_metric"].eq(metric), "value_text"].notna().all()


def test_research_chain_preserves_the_valuation_guard_and_revision_band() -> None:
    result = build_airline_research_chain()

    air_china = result.loc[result["company"].eq("Air China")]
    valuation = air_china.loc[air_china["canonical_metric"].eq("consensus_valuation_quality"), "value_text"].item()
    revision = air_china.loc[air_china["canonical_metric"].eq("revision_evidence_band"), "value_text"].item()
    assert valuation == "unstable_profit_base"
    assert revision == "dated_estimate_revision_proxy"
    risk = air_china.loc[air_china["canonical_metric"].eq("borrow_data_available"), "value_text"].item()
    assert risk == "False"
