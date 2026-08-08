"""Stage 1 execution pipeline for HK Transport Sector."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .sources.cathay_traffic import fetch_cathay_traffic
from .sources.cathay_fleet import fetch_cathay_fleet_history
from .sources.censtatd_boundary_movements import fetch_censtatd_boundary_movements
from .sources.mttd_passenger_journeys import fetch_mttd_passenger_journeys
from .sources.td_carpark_occupancy import fetch_td_carpark_occupancy
from .sources.td_first_registered_vehicle_details import fetch_td_first_registered_vehicle_details
from .sources.td_parking_vacancy import fetch_td_parking_vacancy
from .sources.td_private_car_first_reg import fetch_td_private_car_first_reg
from .sources.td_private_car_net_registration import fetch_td_private_car_net_registration
from .sources.td_vehicle_fleet_stock import fetch_td_vehicle_fleet_stock
from .sources.mtr_patronage import fetch_mtr_patronage
from .sources.energy_prices import fetch_eia_airline_energy_prices
from .sources.fuel_surcharge import fetch_fuel_surcharge_snapshots
from .sources.fx_rates import fetch_ecb_airline_fx_rates

logger = logging.getLogger(__name__)

QUALITY_SPECS = {
    "mtr_patronage_monthly": {
        "kind": "measure",
        "required": ["date", "month", "domestic_service_thousands", "total_mtr_patronage_thousands"],
        "max_age_days": 400,
    },
    "cathay_hkia_traffic_monthly": {
        "kind": "measure",
        "required": ["date", "month", "hkia_passengers", "cathay_passengers"],
        "max_age_days": 400,
    },
    "cathay_fleet_profile_history": {
        "kind": "measure",
        "required": ["date", "scope", "fleet_total_aircraft"],
        "max_age_days": 800,
    },
    "airline_energy_prices": {
        "kind": "measure",
        "required": [
            "frequency",
            "observation_date",
            "series_id",
            "value",
            "unit",
            "source_release_date",
            "retrieved_at",
        ],
        "max_age_days": 10,
    },
    "airline_fx_rates": {
        "kind": "measure",
        "required": [
            "frequency",
            "observation_date",
            "pair",
            "base_currency",
            "quote_currency",
            "value",
            "retrieved_at",
        ],
        "max_age_days": 10,
    },
    "airline_fuel_surcharges": {
        "kind": "snapshot",
        "required": [
            "carrier_scope",
            "route_band",
            "currency",
            "current_value",
            "effective_from",
            "retrieved_at",
        ],
        "max_age_days": 30,
    },
    "airline_fuel_sensitivity_scenarios": {
        "kind": "snapshot",
        "required": [
            "company",
            "baseline_period",
            "fuel_cost_native_mn",
            "scenario_fuel_price_change_pct",
            "pre_tax_profit_impact_native_mn",
            "scenario_method",
            "jet_fuel_observation_date",
            "fx_pair",
            "fx_observation_date",
            "fx_value_quote_per_usd",
            "fuel_cost_usd_mn",
            "pre_tax_profit_impact_usd_mn",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 31,
    },
    "airline_monthly_operating_kpis": {
        "kind": "measure",
        "required": [
            "month",
            "date",
            "airline_code",
            "region",
            "metric",
            "value",
            "announcement_date",
            "announcement_id",
            "source_pdf_url",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_operating_release_registry": {
        "kind": "event",
        "required": [
            "month",
            "airline_code",
            "announcement_date",
            "announcement_id",
            "source_pdf_url",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_financial_actuals_akshare": {
        "kind": "measure",
        "required": [
            "ticker",
            "period_end",
            "metric",
            "value_native",
            "native_unit",
            "source_quality",
            "announcement_date_available",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_financial_history_trend": {
        "kind": "measure",
        "required": [
            "ticker",
            "period_end",
            "period_type",
            "metric",
            "value_native",
            "native_unit",
            "source_quality",
            "announcement_date_available",
            "point_in_time_status",
            "as_of_date",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_historical_earnings_bridge": {
        "kind": "measure",
        "required": [
            "company",
            "period_end",
            "period_type",
            "financial_point_in_time_status",
            "operating_month_count",
            "jet_fuel_avg_usd_per_gallon",
            "usd_cny_avg",
            "current_ashare_detailed_snapshot_date",
            "source_quality",
            "point_in_time_status",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_pair_historical_bridge": {
        "kind": "measure",
        "required": [
            "pair_id",
            "company_a",
            "company_b",
            "pair_selection_bucket",
            "historical_bridge_status",
            "historical_divergence_status",
            "source_quality",
            "source_note",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_pair_scenario_inputs": {
        "kind": "measure",
        "required": [
            "pair_id",
            "scenario",
            "pair_selection_bucket",
            "scenario_revenue_delta_vs_consensus_pct",
            "scenario_margin_delta_vs_consensus_pp",
            "source_quality",
            "source_note",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_primary_financial_reconciliation": {
        "kind": "measure",
        "required": [
            "company",
            "statement_period",
            "metric",
            "reconciliation_status",
            "official_source_url",
            "source_quality",
            "source_note",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_core_pair_model_inputs": {
        "kind": "measure",
        "required": [
            "company",
            "as_of_date",
            "fy2025_revenue_usd_mn",
            "fy2026_consensus_net_profit_usd_mn",
            "scenario_base_profit_usd_mn",
            "source_quality",
            "source_note",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_consensus_ashare_akshare": {
        "kind": "snapshot",
        "required": [
            "ticker",
            "snapshot_date",
            "fiscal_year",
            "metric",
            "value_avg_native",
            "forecast_count",
            "source_quality",
            "revision_history_available",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_consensus_ashare_detailed": {
        "kind": "snapshot",
        "required": [
            "ticker",
            "snapshot_date",
            "fiscal_year",
            "metric",
            "value_avg_native",
            "native_unit",
            "source_quality",
            "revision_history_available",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_public_report_evidence": {
        "kind": "event",
        "required": [
            "ticker",
            "snapshot_date",
            "institution",
            "fiscal_year",
            "metric",
            "forecast_value_native",
            "information_scope",
            "source_quality",
            "source_url",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_revenue_consensus_yfinance": {
        "kind": "snapshot",
        "required": [
            "ticker",
            "snapshot_date",
            "forecast_period",
            "fiscal_year",
            "revenue_avg_native_mn",
            "revenue_low_native_mn",
            "revenue_high_native_mn",
            "analyst_count",
            "source_quality",
            "revision_history_available",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_sell_side_reports_akshare": {
        "kind": "event",
        "required": [
            "ticker",
            "report_date",
            "report_title",
            "institution",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_sell_side_forecast_revisions": {
        "kind": "event",
        "required": [
            "ticker",
            "institution",
            "fiscal_year",
            "report_date",
            "eps_native",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_consensus_events": {
        "kind": "event",
        "required": [
            "company",
            "ticker",
            "event_date",
            "event_type",
            "direction",
            "source_quality",
            "source_url",
            "information_scope",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_consensus_revision_pulse": {
        "kind": "event",
        "required": [
            "company",
            "ticker",
            "event_date",
            "estimate_metric",
            "public_revision_sample_count",
            "current_value_median_native",
            "source_scope",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_revision_evidence": {
        "kind": "event",
        "required": [
            "company",
            "ticker",
            "evidence_date",
            "evidence_type",
            "metric",
            "direction",
            "source_quality",
            "source_url",
            "information_scope",
            "revision_history_available",
            "source_note",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_revenue_consensus_coverage": {
        "kind": "snapshot",
        "required": [
            "company",
            "ticker",
            "snapshot_date",
            "fiscal_year",
            "coverage_scope",
            "source_quality",
            "forecast_row_count",
            "native_unit",
            "revision_history_available",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_guidance_coverage": {
        "kind": "event",
        "required": [
            "company",
            "ticker",
            "snapshot_date",
            "guidance_coverage_status",
            "formal_report_status",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_sector_external_outlook": {
        "kind": "event",
        "required": [
            "source_organization",
            "source_document_date",
            "source_url",
            "period",
            "scope",
            "metric",
            "value",
            "unit",
            "status",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 180,
    },
    "airline_pair_screening_matrix": {
        "kind": "snapshot",
        "required": [
            "pair_id",
            "asset_a",
            "asset_b",
            "data_comparability_status",
            "expectation_comparability_status",
            "screen_status",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_pair_factor_diagnostics": {
        "kind": "snapshot",
        "required": [
            "pair_id",
            "asset_a",
            "asset_b",
            "beta_gap_a_minus_b",
            "log_size_gap_a_minus_b",
            "momentum_3m_gap_a_minus_b_pct",
            "volatility_gap_a_minus_b_pct",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_sell_side_revenue_forecasts": {
        "kind": "event",
        "required": [
            "ticker",
            "report_date",
            "institution",
            "fiscal_year",
            "revenue_forecast_native_mn",
            "source_quality",
            "source_page",
            "retrieved_at",
        ],
        "max_age_days": 31,
    },
    "airline_sell_side_revenue_revisions": {
        "kind": "event",
        "required": [
            "ticker",
            "institution",
            "fiscal_year",
            "report_date",
            "revenue_forecast_native_mn",
            "prior_report_date",
            "revenue_change_native_mn",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 31,
    },
    "airline_filing_calendar": {
        "kind": "event",
        "required": [
            "ticker",
            "statement_period",
            "snapshot_date",
            "first_scheduled_date",
            "calendar_status",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_official_filing_watch": {
        "kind": "event",
        "required": [
            "ticker",
            "statement_period",
            "snapshot_date",
            "official_report_found",
            "source_quality",
            "source_url",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_market_snapshot": {
        "kind": "snapshot",
        "required": [
            "ticker",
            "snapshot_date",
            "latest_price_native",
            "price_currency",
            "market_cap_native_mn",
            "market_cap_currency",
            "market_cap_usd_mn",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 5,
    },
    "airline_market_expectations_snapshot": {
        "kind": "snapshot",
        "required": [
            "ticker",
            "snapshot_date",
            "latest_price_native",
            "market_cap_usd_mn",
            "fy2026_net_profit_avg_usd_mn",
            "fy2026_revenue_avg_usd_mn",
            "market_cap_to_consensus_revenue_usd",
            "consensus_valuation_quality",
            "consensus_source_quality",
            "retrieved_at",
        ],
        "max_age_days": 5,
    },
    "airline_hk_sell_side_forecasts": {
        "kind": "event",
        "required": [
            "ticker",
            "fiscal_year",
            "report_date",
            "institution",
            "eps_native",
            "target_price_hkd",
            "forecast_currency",
            "target_price_currency",
            "net_profit_usd_mn_at_report",
            "eps_usd_at_report",
            "target_price_usd_at_report",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_hk_forecast_revisions": {
        "kind": "event",
        "required": [
            "ticker",
            "fiscal_year",
            "institution",
            "report_date",
            "eps_native",
            "forecast_currency",
            "target_price_currency",
            "net_profit_usd_mn_at_report",
            "eps_usd_at_report",
            "target_price_usd_at_report",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_consensus_freshness": {
        "kind": "snapshot",
        "required": [
            "dataset_id",
            "company",
            "ticker",
            "source_layer",
            "as_of_date",
            "latest_observation_date",
            "age_days",
            "freshness_band",
            "observation_count",
            "prior_comparison_count",
            "revision_history_available",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_consensus_dispersion": {
        "kind": "snapshot",
        "required": [
            "dataset_id",
            "pair_id",
            "company",
            "snapshot_date",
            "hk_ticker",
            "a_ticker",
            "hk_profit_consensus_usd_mn",
            "a_profit_consensus_usd_mn",
            "profit_gap_a_minus_hk_usd_mn",
            "eps_revision_count",
            "revenue_revision_count",
            "forecast_warning_alignment",
            "vintage_status",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_consensus_em": {
        "kind": "snapshot",
        "required": [
            "ticker",
            "company",
            "snapshot_date",
            "fiscal_year",
            "eps_avg_native",
            "rating_total_count",
            "buy_add_pct",
            "source_quality",
            "revision_history_available",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_yahoo_analyst_snapshot": {
        "kind": "snapshot",
        "required": [
            "ticker",
            "company",
            "snapshot_date",
            "metric",
            "period",
            "source_quality",
            "revision_history_available",
            "source_url",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_operating_freshness": {
        "kind": "snapshot",
        "required": [
            "company",
            "airline_code",
            "snapshot_date",
            "target_month",
            "target_release_status",
            "latest_observation_month",
            "source_quality",
            "source_url",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_operating_diagnostics": {
        "kind": "snapshot",
        "required": [
            "company",
            "ticker",
            "market",
            "airline_code",
            "snapshot_date",
            "current_period",
            "prior_period",
            "q2_ask_yoy_pct",
            "q2_rpk_yoy_pct",
            "q2_rpk_minus_ask_gap_pp",
            "june_rpk_minus_ask_gap_pp",
            "source_quality",
            "source_path",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_short_side_proxies": {
        "kind": "snapshot",
        "required": [
            "company",
            "ticker",
            "market",
            "observation_date",
            "short_proxy_type",
            "short_proxy_status",
            "borrow_data_available",
            "source_quality",
            "source_url",
            "retrieved_at",
        ],
        "max_age_days": 7,
    },
    "airline_short_eligibility": {
        "kind": "snapshot",
        "required": [
            "company",
            "ticker",
            "market",
            "security_code",
            "snapshot_date",
            "eligibility_effective_date",
            "eligibility_status",
            "eligibility_scope",
            "evidence_type",
            "borrow_data_available",
            "source_quality",
            "source_url",
            "retrieved_at",
        ],
        "max_age_days": 90,
    },
    "airline_hk_short_positions": {
        "kind": "measure",
        "required": [
            "company",
            "ticker",
            "market",
            "security_code",
            "reporting_date",
            "snapshot_date",
            "short_position_shares",
            "short_position_value_hkd",
            "borrow_data_available",
            "source_quality",
            "source_url",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_stock_connect_short_selling": {
        "kind": "measure",
        "required": [
            "company",
            "ticker",
            "market",
            "security_code",
            "exchange_board",
            "observation_date",
            "remaining_available_display",
            "short_selling_turnover_shares",
            "short_selling_turnover_value_rmb",
            "short_selling_pct_today",
            "short_selling_pct_10d",
            "borrow_data_available",
            "source_quality",
            "source_url",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_research_data_completeness": {
        "kind": "snapshot",
        "required": [
            "scope",
            "company",
            "domain",
            "required_for_thesis",
            "coverage_status",
            "coverage_count",
            "source_dataset",
            "source_quality",
            "point_in_time_status",
            "limitation",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_cninfo_rating_events": {
        "kind": "event",
        "required": [
            "ticker",
            "company",
            "report_date",
            "institution",
            "rating",
            "rating_change",
            "rating_direction",
            "source_quality",
            "history_scope",
            "retrieved_at",
        ],
        "max_age_days": 30,
    },
    "airline_revision_coverage": {
        "kind": "snapshot",
        "required": [
            "company",
            "snapshot_date",
            "hk_broker_observation_count",
            "ashare_eps_revision_proxy_count",
            "mainland_revenue_revision_proxy_count",
            "cninfo_rating_event_count",
            "yahoo_coverage_status",
            "yahoo_source_quality",
            "revision_evidence_band",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_pair_readiness": {
        "kind": "snapshot",
        "required": [
            "company",
            "ticker",
            "snapshot_date",
            "has_official_latest_financial_actual",
            "has_h1_demand_trend",
            "has_fuel_cost_driver",
            "has_market_expectation",
            "pair_readiness_status",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_news_events": {
        "kind": "event",
        "required": [
            "ticker",
            "company",
            "published_at",
            "news_title",
            "news_url",
            "event_category",
            "history_scope",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 7,
    },
    "airline_research_chain": {
        "kind": "measure",
        "required": [
            "company",
            "ticker",
            "snapshot_date",
            "chain_stage",
            "canonical_metric",
            "source_field",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_consensus_dispersion_all": {
        "kind": "snapshot",
        "required": [
            "company",
            "snapshot_date",
            "vintage_status",
            "dispersion_status",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_market_risk_metrics": {
        "kind": "snapshot",
        "required": [
            "company",
            "ticker",
            "snapshot_date",
            "beta_to_benchmark",
            "annualized_volatility_pct",
            "max_drawdown_pct",
            "median_daily_turnover_usd_mn_60d",
            "borrow_data_available",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 7,
    },
    "airline_pair_risk_metrics": {
        "kind": "snapshot",
        "required": [
            "asset_a",
            "asset_b",
            "snapshot_date",
            "observations",
            "correlation_a_b",
            "beta_a_to_b",
            "beta_b_to_a",
            "hedged_spread_vol_a_minus_beta_b_pct",
            "borrow_data_available_a",
            "borrow_data_available_b",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 7,
    },
    "airline_sector_trend_snapshot": {
        "kind": "measure",
        "required": [
            "scope_type",
            "airline_code",
            "region",
            "metric",
            "current_period",
            "prior_period",
            "current_value",
            "prior_value",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 31,
    },
    "airline_cathay_sector_trend_snapshot": {
        "kind": "measure",
        "required": [
            "scope_type",
            "airline_code",
            "region",
            "metric",
            "current_period",
            "prior_period",
            "current_value",
            "prior_value",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 31,
    },
    "airline_expectation_bridge": {
        "kind": "snapshot",
        "required": [
            "company",
            "market_ticker",
            "snapshot_date",
            "h1_ask_yoy_pct",
            "latest_financial_period",
            "fy2026_revenue_avg_native_mn",
            "fy2026_net_profit_avg_native_mn",
            "latest_event_source_quality",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 14,
    },
    "airline_official_report_registry": {
        "kind": "event",
        "required": [
            "report_id",
            "ticker",
            "statement_period",
            "announcement_date",
            "source_quality",
            "source_url",
            "parse_status",
            "retrieved_at",
        ],
        "max_age_days": 30,
    },
    "airline_official_report_drivers": {
        "kind": "measure",
        "required": [
            "report_id",
            "ticker",
            "period_end",
            "announced_at",
            "metric",
            "value_native",
            "source_quality",
            "source_page",
            "retrieved_at",
        ],
        "max_age_days": 30,
    },
    "airline_hedging_disclosures": {
        "kind": "event",
        "required": [
            "report_id",
            "ticker",
            "statement_period",
            "hedge_scope",
            "disclosure_type",
            "hedge_status",
            "source_quality",
            "source_url",
            "scan_scope",
            "parse_status",
            "retrieved_at",
        ],
        "max_age_days": 30,
    },
    "airline_earnings_driver_comparability": {
        "kind": "measure",
        "required": [
            "company",
            "ticker",
            "statement_period",
            "canonical_metric",
            "metric_definition",
            "value_type",
            "point_in_time_status",
            "retrieved_at",
        ],
        "max_age_days": 30,
    },
    "airline_cathay_annual_driver_snapshot": {
        "kind": "measure",
        "required": [
            "ticker",
            "statement_period",
            "period_end",
            "metric",
            "value_native",
            "source_quality",
            "source_url",
            "source_page",
            "retrieved_at",
        ],
        "max_age_days": 120,
    },
    "td_private_car_first_reg_monthly": {
        "kind": "measure",
        "required": ["date", "month", "make", "fuel_type", "first_reg"],
        "max_age_days": 120,
    },
    "td_first_registered_vehicle_details_monthly": {
        "kind": "snapshot",
        "required": ["observation_date", "vehicle_make", "vehicle_model", "fuel_type"],
        "max_age_days": 120,
    },
    "td_parking_vacancy_current": {
        "kind": "snapshot",
        "required": ["snapshot_at", "park_id", "vehicle_type", "vacancy_type", "vacancy"],
        "max_age_days": 1,
    },
    "td_carpark_occupancy": {
        "kind": "measure",
        "required": ["snapshot_at", "district", "occupancy_rate", "sample_size"],
        "max_age_days": 1,
    },
    "mttd_passenger_journeys_monthly": {
        "kind": "measure",
        "required": ["date", "month", "bus_rail", "total_passenger_journeys_k"],
        "max_age_days": 150,
    },
    "censtatd_boundary_movements_monthly": {
        "kind": "measure",
        "required": ["date", "month", "aircraft_total", "goods_vehicles_total", "passenger_vehicles_total"],
        "max_age_days": 150,
    },
    "td_vehicle_fleet_stock_monthly": {
        "kind": "measure",
        "required": ["date", "electric_total_registered", "all_fuel_total_registered"],
        "max_age_days": 120,
    },
    "td_private_car_net_registration_monthly": {
        "kind": "measure",
        "required": ["date", "gross_first_registrations", "deregistrations", "net_first_registrations"],
        "max_age_days": 120,
    },
}


def run_stage_1_pipeline() -> dict[str, Any]:
    """Execute Stage 1 ready-to-build ingestion for HK Transport."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results = {}

    try:
        logger.info("Ingesting MTR Corporation monthly patronage...")
        results["mtr_patronage_monthly"] = fetch_mtr_patronage()
    except Exception as exc:
        logger.exception("MTR patronage ingestion failed")
        results["mtr_patronage_monthly"] = {"error": str(exc)}

    try:
        logger.info("Ingesting Cathay Pacific & HKIA aviation traffic...")
        results["cathay_hkia_traffic_monthly"] = fetch_cathay_traffic()
    except Exception as exc:
        logger.exception("Cathay & HKIA traffic ingestion failed")
        results["cathay_hkia_traffic_monthly"] = {"error": str(exc)}

    try:
        logger.info("Ingesting EIA daily and weekly crude/jet-fuel benchmarks...")
        results["airline_energy_prices"] = fetch_eia_airline_energy_prices()
    except Exception as exc:
        logger.exception("EIA airline energy-price ingestion failed")
        results["airline_energy_prices"] = {"error": str(exc)}

    try:
        logger.info("Ingesting ECB daily USD/CNY and USD/HKD reference rates...")
        results["airline_fx_rates"] = fetch_ecb_airline_fx_rates()
    except Exception as exc:
        logger.exception("ECB airline FX-rate ingestion failed")
        results["airline_fx_rates"] = {"error": str(exc)}

    try:
        logger.info("Ingesting official airline fuel-surcharge schedules...")
        results["airline_fuel_surcharges"] = fetch_fuel_surcharge_snapshots()
    except Exception as exc:
        logger.exception("Airline fuel-surcharge ingestion failed")
        results["airline_fuel_surcharges"] = {"error": str(exc)}

    try:
        logger.info("Ingesting Cathay Group official fleet profiles...")
        results["cathay_fleet_profile_history"] = fetch_cathay_fleet_history()
    except Exception as exc:
        logger.exception("Cathay fleet-profile ingestion failed")
        results["cathay_fleet_profile_history"] = {"error": str(exc)}

    try:
        logger.info("Ingesting TD monthly private-car first registrations by make/fuel...")
        results["td_private_car_first_reg_monthly"] = fetch_td_private_car_first_reg()
    except Exception as exc:
        logger.exception("TD private-car first-registration ingestion failed")
        results["td_private_car_first_reg_monthly"] = {"error": str(exc)}

    try:
        logger.info("Ingesting latest TD private-car first-registration make/model details...")
        results["td_first_registered_vehicle_details_monthly"] = fetch_td_first_registered_vehicle_details()
    except Exception as exc:
        logger.exception("TD first-registration detail ingestion failed")
        results["td_first_registered_vehicle_details_monthly"] = {"error": str(exc)}

    try:
        logger.info("Ingesting TD current parking-vacancy snapshot...")
        results["td_parking_vacancy_current"] = fetch_td_parking_vacancy()
    except Exception as exc:
        logger.exception("TD parking-vacancy ingestion failed")
        results["td_parking_vacancy_current"] = {"error": str(exc)}

    try:
        logger.info("Ingesting TD metered-space parking occupancy...")
        results["td_carpark_occupancy"] = fetch_td_carpark_occupancy()
    except Exception as exc:
        logger.exception("TD car-park occupancy ingestion failed")
        results["td_carpark_occupancy"] = {"error": str(exc)}

    try:
        logger.info("Ingesting TD MTTD Table 2.3 passenger journeys...")
        results["mttd_passenger_journeys_monthly"] = fetch_mttd_passenger_journeys()
    except Exception as exc:
        logger.exception("MTTD passenger-journeys ingestion failed")
        results["mttd_passenger_journeys_monthly"] = {"error": str(exc)}

    try:
        logger.info("Ingesting C&SD Table E705 boundary movements...")
        results["censtatd_boundary_movements_monthly"] = fetch_censtatd_boundary_movements()
    except Exception as exc:
        logger.exception("C&SD boundary-movements ingestion failed")
        results["censtatd_boundary_movements_monthly"] = {"error": str(exc)}

    try:
        logger.info("Ingesting TD private-car fleet stock...")
        results["td_vehicle_fleet_stock_monthly"] = fetch_td_vehicle_fleet_stock()
    except Exception as exc:
        logger.exception("TD vehicle-fleet ingestion failed")
        results["td_vehicle_fleet_stock_monthly"] = {"error": str(exc)}

    try:
        logger.info("Ingesting TD private-car net registration...")
        results["td_private_car_net_registration_monthly"] = fetch_td_private_car_net_registration()
    except Exception as exc:
        logger.exception("TD private-car net-registration ingestion failed")
        results["td_private_car_net_registration_monthly"] = {"error": str(exc)}

    return results
