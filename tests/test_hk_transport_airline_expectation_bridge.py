from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources.airline_expectation_bridge import (
    BRIDGE_COLUMNS,
    build_airline_expectation_bridge,
)


def test_expectation_bridge_joins_demand_financials_consensus_market_and_energy() -> None:
    result = build_airline_expectation_bridge(retrieved_at="2026-08-06T00:00:00+00:00")

    assert list(result.columns) == BRIDGE_COLUMNS
    assert len(result) == 10
    assert result[["h1_ask_yoy_pct", "h1_rpk_yoy_pct", "fy2026_revenue_avg_native_mn", "jet_fuel_spot_usd_per_gallon"]].notna().all().all()
    assert result["source_quality"].eq("derived_join_with_source_lineage").all()
    assert result.loc[result["market"].eq("CN_A"), "profit_consensus_freshness_band"].notna().all()
    assert result["revenue_consensus_freshness_band"].notna().all()
    assert result["revenue_consensus_source_layer"].notna().all()
    assert result["fy2026_net_profit_avg_usd_mn"].notna().all()
    assert result["fy2026_revenue_avg_usd_mn"].notna().all()
    assert result.loc[result["market"].eq("CN_A"), "a_share_consensus_em_snapshot_date"].notna().all()
    assert result.loc[result["market"].eq("CN_A"), "a_share_eps_2026_usd"].notna().all()
    assert result.loc[result["market"].eq("CN_A"), "a_share_rating_total_count"].gt(0).all()
    assert result.loc[result["market"].eq("CN_A"), "a_share_buy_add_pct"].eq(100.0).all()
    assert result.loc[result["market"].eq("CN_A"), "latest_discovery_debt_to_assets_pct"].between(0, 100).all()
    assert result.loc[result["market"].eq("CN_A"), "latest_discovery_debt_to_assets_period_end"].eq("2026-03-31").all()
    mainland_cash = result.loc[result["market"].eq("CN_A"), "latest_report_cash_and_cash_equivalents_native_mn"]
    assert mainland_cash.notna().sum() == 5
    mainland_liabilities = result.loc[result["market"].eq("CN_A"), "latest_report_total_liabilities_native_mn"]
    assert mainland_liabilities.notna().sum() == 5
    mainland_leverage = result.loc[result["market"].eq("CN_A"), "latest_report_liabilities_to_assets_pct"]
    assert mainland_leverage.notna().sum() == 5
    assert mainland_leverage.dropna().between(0, 100).all()
    mainland_debt = result.loc[result["market"].eq("CN_A"), "latest_report_interest_bearing_debt_native_mn"]
    assert mainland_debt.notna().sum() == 3
    mainland_capex = result.loc[result["market"].eq("CN_A"), "latest_report_capex_cash_paid_native_mn"]
    assert mainland_capex.notna().sum() == 3
    eastern = result.loc[result["market_ticker"].eq("0670.HK")]
    assert pd.isna(eastern["latest_report_cash_and_cash_equivalents_native_mn"].iloc[0])
    assert result.loc[result["market"].eq("CN_A"), "cninfo_rating_event_count"].gt(0).all()
    assert result.loc[result["market"].eq("CN_A"), "cninfo_rating_history_scope"].eq("queried_public_report_dates").all()
    sell_side_companies = {
        "Air China", "China Southern Airlines", "China Eastern Airlines",
        "Spring Airlines", "Juneyao Airlines",
    }
    sell_side = result.loc[result["company"].isin(sell_side_companies)]
    assert sell_side["latest_sell_side_revenue_native_mn"].notna().all()
    assert sell_side["latest_sell_side_revenue_source_quality"].eq("sell_side_pdf_extracted").all()

    cathay = result.loc[result["market_ticker"].eq("0293.HK")].iloc[0]
    assert cathay["latest_financial_period"] == "1H2026"
    assert cathay["latest_report_announcement_date"] == "2026-08-05"
    assert cathay["latest_event_type"] == "financial_results"
    assert cathay["latest_event_value_min"] == 6243.0
    assert cathay["latest_report_revenue_native_mn"] == 68061.0
    assert cathay["latest_report_fuel_cost_native_mn"] == 23224.0
    assert cathay["latest_report_cost_per_atk_native"] == 3.87
    assert cathay["latest_report_operating_cash_flow_native_mn"] == 13673.0
    assert pd.isna(cathay["latest_report_cash_and_cash_equivalents_native_mn"])
    assert cathay["latest_report_net_borrowings_native_mn"] == 47267.0
    assert cathay["latest_report_available_unrestricted_liquidity_native_mn"] == 23575.0
    assert pd.isna(cathay["latest_report_total_liabilities_native_mn"])
    assert cathay["latest_report_ask_mn_seat_km"] == 74662.0
    assert cathay["latest_report_rpk_mn_passenger_km"] == 65334.0
    assert cathay["latest_report_passenger_load_factor_pct"] == 87.5
    assert cathay["formal_report_status"] == "disclosed"
    assert cathay["formal_report_actual_disclosure_date"] == "2026-08-05"
    assert cathay["hk_broker_observation_count"] == 24
    assert cathay["hk_broker_latest_report_date"] == "2026-08-05"
    assert cathay["hk_broker_true_revision_count"] == 0
    assert cathay["hk_broker_forecast_currency"] == "HKD"
    assert cathay["hk_broker_target_price_currency"] == "HKD"
    assert pd.notna(cathay["hk_broker_latest_net_profit_usd_mn"])
    assert cathay["hk_broker_forecast_fx_pair"] == "USD_HKD"
    assert cathay["hk_broker_consensus_freshness_band"] == "fresh"
    assert cathay["hk_broker_consensus_source_layer"] == "hk_broker_profit_consensus"
    assert pd.isna(cathay["profit_consensus_freshness_band"])

    air_china = result.loc[result["market_ticker"].isin(["0753.HK", "601111.SH"])]
    assert air_china["fy2026_revenue_avg_native_mn"].nunique() == 1
    assert air_china["latest_report_fuel_cost_share_pct"].notna().all()
    assert air_china["formal_report_status"].eq("scheduled").all()
    assert air_china["formal_report_scheduled_date"].eq("2026-08-31").all()
    assert air_china["formal_report_evidence_source_quality"].eq("cninfo_official_query").all()
    assert air_china["formal_report_evidence_source_url"].str.contains("cninfo.com.cn").all()
    assert air_china["yahoo_eps_revision_signal_count"].gt(0).all()
    assert air_china["yahoo_analyst_source_quality"].eq("yfinance_discovery").all()
    assert air_china["profit_consensus_freshness_band"].eq("recent").all()

    mainland = result.loc[result["market"].eq("CN_A")]
    assert mainland["latest_report_rask_native"].notna().all()
    assert mainland["latest_report_ask_mn_seat_km"].notna().all()
    assert mainland["latest_report_rpk_mn_passenger_km"].notna().all()
    assert mainland["latest_report_passenger_load_factor_pct"].notna().all()

    hainan = result.loc[result["market_ticker"].eq("600221.SH")].iloc[0]
    assert hainan["revenue_consensus_source_layer"] == "ashare_detailed_consensus"
    assert hainan["revenue_consensus_freshness_band"] == "stale"
    assert hainan["latest_report_passenger_yield_native"] == pytest.approx(60_219.702 / 134_484.36)


def test_expectation_bridge_keeps_missing_latest_events_explicit() -> None:
    result = build_airline_expectation_bridge(retrieved_at="2026-08-06T00:00:00+00:00")
    spring = result.loc[result["market_ticker"].eq("601021.SH")].iloc[0]
    hainan = result.loc[result["market_ticker"].eq("600221.SH")].iloc[0]
    assert spring["latest_event_date"] == "2026-04-30"
    assert spring["latest_event_type"] == "earnings_guidance"
    assert spring["latest_event_metric"] == "planned_fleet_additions"
    assert hainan["latest_event_date"] == "2026-05-07"
    assert hainan["latest_event_type"] == "earnings_guidance"
    assert hainan["latest_event_metric"] == "fleet_net_growth_target"
