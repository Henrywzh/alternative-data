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
from .sources.airline_cargo_demand import fetch_airline_cargo_demand_proxies
from .sources.airline_postal_demand import fetch_airline_postal_demand_proxies
from .sources.airline_nbs_demand import fetch_airline_nbs_demand
from .sources.airline_travel_demand_events import fetch_airline_travel_demand_events
from .sources.airline_airport_traffic import fetch_airline_airport_traffic
from .sources.airline_cargo_airport_bridge import build_airline_cargo_airport_bridge
from .sources.airline_cargo_yield_bridge import build_airline_cargo_yield_bridge
from .sources.airline_forward_assumptions import build_airline_forward_assumptions
from .sources.airline_forward_net_income_bridge import build_airline_forward_net_income_bridge
from .sources.airline_unit_economics import build_airline_unit_economics
from .sources.airline_yield_pressure import build_airline_yield_pressure_index
from .sources.airline_capacity_pipeline import build_airline_capacity_pipeline
from .sources.airline_consensus_reverse import build_airline_consensus_reverse
from .sources.airline_earnings_sensitivity import build_airline_earnings_sensitivity
from .sources.airline_valuation_snapshot import build_airline_valuation_snapshot
from .sources.airline_trade_construction import build_airline_trade_construction
from .sources.airline_residual_yield_model import build_airline_residual_yield_model
from .sources.airline_cask_driver_model import build_airline_cask_driver_model
from .sources.airline_forecast_decision_eval import build_airline_forecast_decision_eval
from .sources.airline_pair_spread_model import build_airline_pair_spread_model
from .sources.airline_catalyst_calendar import build_airline_catalyst_calendar
from .sources.airline_h1_2026_validation_playbook import build_airline_h1_2026_validation_playbook
from .sources.airline_post_earnings_tracker import build_airline_post_earnings_tracker
from .sources.airline_pre_event_locked_baseline import build_airline_pre_event_locked_baseline
from .sources.airline_earnings_model_v4 import build_airline_earnings_model_v4
from .sources.airline_cargo_bridge_backtest import build_airline_cargo_bridge_backtest
from .sources.airline_caac_sector_monthly import fetch_caac_sector_monthly_kpis
from .sources.airline_caac_sector_proxy_validation import fetch_airline_caac_sector_proxy_validation
from .sources.airline_caac_route_licence import fetch_caac_route_licence_events
from .sources.airline_earnings_model_v3 import fetch_airline_earnings_model_v3
from .sources.airline_fleet_wikipedia import fetch_airline_fleet_wikipedia
from .sources.airline_fuel_surcharge_recovery import build_airline_fuel_surcharge_recovery
from .sources.airline_weather_risk import fetch_airline_weather_risk
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
    "airline_cargo_demand_proxies": {
        "kind": "measure",
        "required": [
            "observation_month",
            "period_end",
            "total_trade_value_usd_100m",
            "export_value_usd_100m",
            "import_value_usd_100m",
            "source_release_date_status",
            "point_in_time_status",
            "source_snapshot_date",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_postal_demand_proxies": {
        "kind": "measure",
        "required": [
            "observation_period",
            "period_type",
            "observation_month",
            "period_end",
            "metric",
            "value",
            "unit",
            "yoy_pct",
            "source_release_date",
            "point_in_time_status",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 60,
    },
    "airline_travel_demand_events": {
        "kind": "event",
        "required": [
            "event_id",
            "event_family",
            "event_duration_days",
            "metric",
            "value",
            "value_per_day",
            "source_release_date",
            "point_in_time_status",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 180,
    },
    "airline_nbs_demand": {
        "kind": "measure",
        "required": [
            "release_id",
            "release_family",
            "metric",
            "value",
            "unit",
            "scope",
            "source_release_date",
            "point_in_time_status",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 60,
    },
    "airline_airport_traffic": {
        "kind": "measure",
        "required": [
            "observation_month",
            "airport",
            "metric",
            "scope",
            "value",
            "unit",
            "yoy_pct",
            "source_release_date",
            "point_in_time_status",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_weather_risk": {
        "kind": "measure",
        "required": [
            "airport",
            "observation_date",
            "precipitation_sum_mm",
            "wind_speed_10m_max_kmh",
            "weather_code",
            "point_in_time_status",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_fleet_wikipedia_snapshot": {
        "kind": "measure",
        "required": [
            "company",
            "aircraft_type",
            "snapshot_date",
            "revision_id",
            "point_in_time_status",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_cargo_airport_bridge": {
        "kind": "measure",
        "required": [
            "company",
            "period",
            "hub_airports",
            "airport_cargo_tonnes",
            "company_cargo_tonnes",
            "bridge_status",
            "source_note",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_cargo_yield_bridge": {
        "kind": "measure",
        "required": [
            "company",
            "period",
            "revenue_anchor_period",
            "h1_2025_cargo_revenue_native_mn",
            "h1_2026_cargo_tonnes",
            "h1_2026_cargo_revenue_bridge_native_mn",
            "bridge_status",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_forward_assumptions": {
        "kind": "measure",
        "required": [
            "company",
            "fy2025_profit_before_tax_native_mn",
            "fy2025_income_tax_expense_native_mn",
            "tax_assumption_status",
            "forward_fx_usd_cny",
            "forward_fx_status",
            "retrieved_at",
        ],
        "max_age_days": 60,
    },
    "airline_forward_net_income_bridge": {
        "kind": "measure",
        "required": [
            "company",
            "horizon",
            "model_name",
            "forward_profit_before_tax_native_mn",
            "forward_income_tax_native_mn",
            "forward_net_income_total_native_mn",
            "forward_attributable_net_income_native_mn",
            "forward_basic_eps_rmb_per_share",
            "bridge_status",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_unit_economics": {
        "kind": "measure",
        "required": [
            "company",
            "period",
            "ask_mn",
            "rask_native",
            "cask_native",
            "unit_profit_proxy",
            "cask_ex_fuel_native",
            "component_status",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_yield_pressure_index": {
        "kind": "measure",
        "required": [
            "company",
            "month",
            "rpk_minus_ask_gap_pp",
            "yield_pressure_score",
            "yield_pressure_label",
            "validation_status",
            "retrieved_at",
        ],
        "max_age_days": 60,
    },
    "airline_capacity_pipeline": {
        "kind": "event",
        "required": [
            "company",
            "event_date",
            "horizon",
            "event_category",
            "event_detail",
            "capacity_impact_direction",
            "confidence",
            "retrieved_at",
        ],
        "max_age_days": 60,
    },
    "airline_consensus_reverse": {
        "kind": "measure",
        "required": [
            "company",
            "fiscal_year",
            "consensus_revenue_native_mn",
            "consensus_net_margin_pct",
            "implied_rask_native",
            "model_rask_native",
            "rask_gap_pct",
            "reverse_method",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_earnings_sensitivity": {
        "kind": "measure",
        "required": [
            "company",
            "horizon",
            "yield_shock_pct",
            "fuel_shock_pct",
            "fx_shock_pct",
            "shocked_net_income_native_mn",
            "shocked_eps_rmb",
            "vs_consensus_status",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_valuation_snapshot": {
        "kind": "measure",
        "required": [
            "company",
            "snapshot_date",
            "market_cap_native_mn",
            "pe_ttm",
            "ps_ttm",
            "pb_mrq",
            "ev_ebitdar_status",
            "retrieved_at",
        ],
        "max_age_days": 7,
    },
    "airline_trade_construction": {
        "kind": "snapshot",
        "required": [
            "pair_id",
            "direction",
            "cask_advantage_pct",
            "sensitivity_robust_combinations",
            "sensitivity_total_combinations",
            "beta_hedge_ratio",
            "loss_budget_pct_nav",
            "catalyst_window",
            "trade_status",
            "retrieved_at",
        ],
        "max_age_days": 7,
    },
    "airline_residual_yield_model": {
        "kind": "measure",
        "required": [
            "company",
            "period",
            "target_year",
            "row_status",
            "flat_yield_revenue_native_mn",
            "yield_pressure_bucket",
            "yield_adjustment_pct",
            "adjusted_revenue_native_mn",
            "retrieved_at",
        ],
        "max_age_days": 60,
    },
    "airline_cask_driver_model": {
        "kind": "measure",
        "required": [
            "company",
            "period",
            "fuel_price_usd_per_gallon",
            "fuel_efficiency_implied",
            "fuel_cask_forecast",
            "cask_forecast",
            "retrieved_at",
        ],
        "max_age_days": 30,
    },
    "airline_forecast_decision_eval": {
        "kind": "measure",
        "required": [
            "company",
            "model_eps",
            "consensus_net_profit_native_mn",
            "beat_probability_pct",
            "retrieved_at",
        ],
        "max_age_days": 30,
    },
    "airline_pair_spread_model": {
        "kind": "measure",
        "required": [
            "pair_id",
            "period",
            "target_year",
            "spread_actual_native_mn",
            "spread_predicted_native_mn",
            "spread_direction_correct",
            "model_status",
            "retrieved_at",
        ],
        "max_age_days": 60,
    },
    "airline_h1_2026_validation_playbook": {
        "kind": "snapshot",
        "required": [
            "company",
            "filing_scheduled_date",
            "h1_2026_ask_yoy_pct",
            "h1_2026_rpk_yoy_pct",
            "fy2026_v3_base_net_profit_usd_mn",
            "consensus_fy2026_profit_usd_mn",
            "validation_status",
            "retrieved_at",
        ],
        "max_age_days": 60,
    },
    "airline_catalyst_calendar": {
        "kind": "event",
        "required": [
            "event_id",
            "event_category",
            "event_name",
            "event_window_start",
            "affected_companies",
            "kpi_link",
            "earnings_link",
            "source",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_post_earnings_tracker": {
        "kind": "measure",
        "required": [
            "company",
            "report_period",
            "pre_event_model_fy2026_net_profit_usd_mn",
            "pre_event_consensus_fy2026_net_profit_usd_mn",
            "validation_status",
            "retrieved_at",
        ],
        "max_age_days": 30,
    },
    "airline_pre_event_locked_baseline": {
        "kind": "snapshot",
        "required": [
            "company",
            "filing_scheduled_date",
            "h1_2026_flat_yield_revenue_native_mn",
            "v3_base_fy2026_net_profit_usd_mn",
            "consensus_fy2026_profit_usd_mn",
            "snapshot_date",
            "lock_status",
            "retrieved_at",
        ],
        "max_age_days": 15,
    },
    "airline_earnings_model_v4": {
        "kind": "measure",
        "required": [
            "company",
            "period",
            "target_year",
            "revenue_base_decomposition_native_mn",
            "revenue_recovery_overlay_native_mn",
            "error_recovery_overlay_pct",
            "retrieved_at",
        ],
        "max_age_days": 30,
    },
    "airline_cargo_bridge_backtest": {
        "kind": "measure",
        "required": [
            "company",
            "fy2025_cargo_revenue_native_mn",
            "fy2025_revenue_per_tonne_native",
            "predicted_h1_2025_cargo_revenue_native_mn",
            "actual_h1_2025_cargo_revenue_native_mn",
            "h1_2025_revenue_error_pct",
            "backtest_status",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_caac_sector_monthly": {
        "kind": "measure",
        "required": [
            "observation_month",
            "period_type",
            "scope",
            "metric",
            "value",
            "yoy_pct",
            "source_release_date",
            "source_release_date_status",
            "point_in_time_status",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_caac_route_licence_events": {
        "kind": "event",
        "required": [
            "source_release_date",
            "schedule_season",
            "table_type",
            "event_type",
            "airline_short_name",
            "route_text",
            "point_in_time_status",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 180,
    },
    "airline_caac_sector_proxy_validation": {
        "kind": "measure",
        "required": [
            "company",
            "target_year",
            "period",
            "company_passenger_yoy_pct",
            "caac_passenger_volume_yoy_pct",
            "validation_status",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_caac_sector_proxy_validation_summary": {
        "kind": "snapshot",
        "required": [
            "target_year",
            "period",
            "passenger_mae_pp",
            "cargo_mae_pp",
            "source_quality",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_earnings_model_v3": {
        "kind": "measure",
        "required": [
            "company",
            "scenario",
            "v3_revenue_usd_mn",
            "v3_operating_profit_usd_mn",
            "v3_net_profit_proxy_usd_mn",
            "cargo_proxy_status",
            "point_in_time_status",
            "retrieved_at",
        ],
        "max_age_days": 45,
    },
    "airline_earnings_model_v3_kpi_coverage": {
        "kind": "snapshot",
        "required": [
            "kpi",
            "coverage_status",
            "current_source_or_method",
            "research_caveat",
            "retrieved_at",
        ],
        "max_age_days": 45,
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
    "airline_fuel_surcharge_recovery": {
        "kind": "measure",
        "required": [
            "carrier_scope",
            "effective_from",
            "previous_value",
            "current_value",
            "surcharge_change_pct",
            "fuel_change_pct",
            "recovery_proxy_status",
            "retrieved_at",
        ],
        "max_age_days": 60,
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
        logger.info("Ingesting free MOFCOM monthly trade/cargo-demand proxy...")
        results["airline_cargo_demand_proxies"] = fetch_airline_cargo_demand_proxies()
    except Exception as exc:
        logger.exception("MOFCOM monthly trade/cargo-demand ingestion failed")
        results["airline_cargo_demand_proxies"] = {"error": str(exc)}

    try:
        logger.info("Ingesting State Post Bureau postal/express demand proxy...")
        results["airline_postal_demand_proxies"] = fetch_airline_postal_demand_proxies()
    except Exception as exc:
        logger.exception("State Post Bureau postal/express ingestion failed")
        results["airline_postal_demand_proxies"] = {"error": str(exc)}

    try:
        logger.info("Ingesting official MOT/MCT holiday travel-demand event controls...")
        results["airline_travel_demand_events"] = fetch_airline_travel_demand_events()
    except Exception as exc:
        logger.exception("MOT/MCT holiday travel-demand ingestion failed")
        results["airline_travel_demand_events"] = {"error": str(exc)}

    try:
        logger.info("Ingesting NBS monthly demand-side controls...")
        results["airline_nbs_demand"] = fetch_airline_nbs_demand()
    except Exception as exc:
        logger.exception("NBS demand-control ingestion failed")
        results["airline_nbs_demand"] = {"error": str(exc)}

    try:
        logger.info("Ingesting issuer airport monthly production statistics...")
        results["airline_airport_traffic"] = fetch_airline_airport_traffic()
    except Exception as exc:
        logger.exception("Issuer airport monthly production-statistics ingestion failed")
        results["airline_airport_traffic"] = {"error": str(exc)}

    try:
        logger.info("Ingesting Open-Meteo airline hub weather-risk layer...")
        daily, _monthly = fetch_airline_weather_risk()
        results["airline_weather_risk"] = daily
    except Exception as exc:
        logger.exception("Airline hub weather-risk ingestion failed")
        results["airline_weather_risk"] = {"error": str(exc)}

    try:
        logger.info("Ingesting Wikipedia airline fleet-table snapshots...")
        results["airline_fleet_wikipedia_snapshot"] = fetch_airline_fleet_wikipedia()
    except Exception as exc:
        logger.exception("Wikipedia airline fleet snapshot ingestion failed")
        results["airline_fleet_wikipedia_snapshot"] = {"error": str(exc)}

    try:
        logger.info("Building airport-cargo versus company-cargo bridge layer...")
        results["airline_cargo_airport_bridge"] = build_airline_cargo_airport_bridge()
    except Exception as exc:
        logger.exception("Airline cargo-airport bridge build failed")
        results["airline_cargo_airport_bridge"] = {"error": str(exc)}

    try:
        logger.info("Building forward cargo-revenue yield bridge...")
        results["airline_cargo_yield_bridge"] = build_airline_cargo_yield_bridge()
    except Exception as exc:
        logger.exception("Airline cargo-yield bridge build failed")
        results["airline_cargo_yield_bridge"] = {"error": str(exc)}

    try:
        logger.info("Building forward tax/FX assumption table...")
        results["airline_forward_assumptions"] = build_airline_forward_assumptions()
    except Exception as exc:
        logger.exception("Airline forward-assumptions build failed")
        results["airline_forward_assumptions"] = {"error": str(exc)}

    try:
        logger.info("Building forward H1-2026 net-income bridge...")
        results["airline_forward_net_income_bridge"] = (
            build_airline_forward_net_income_bridge()
        )
    except Exception as exc:
        logger.exception("Airline forward net-income bridge build failed")
        results["airline_forward_net_income_bridge"] = {"error": str(exc)}

    try:
        logger.info("Building airline unit-economics (RASK-CASK) bridge...")
        results["airline_unit_economics"] = build_airline_unit_economics()
    except Exception as exc:
        logger.exception("Airline unit-economics bridge build failed")
        results["airline_unit_economics"] = {"error": str(exc)}

    try:
        logger.info("Building airline yield-pressure index...")
        results["airline_yield_pressure_index"] = build_airline_yield_pressure_index()
    except Exception as exc:
        logger.exception("Airline yield-pressure index build failed")
        results["airline_yield_pressure_index"] = {"error": str(exc)}

    try:
        logger.info("Building airline future capacity pipeline...")
        results["airline_capacity_pipeline"] = build_airline_capacity_pipeline()
    except Exception as exc:
        logger.exception("Airline capacity pipeline build failed")
        results["airline_capacity_pipeline"] = {"error": str(exc)}

    try:
        logger.info("Building airline consensus reverse engineering...")
        results["airline_consensus_reverse"] = build_airline_consensus_reverse()
    except Exception as exc:
        logger.exception("Airline consensus reverse build failed")
        results["airline_consensus_reverse"] = {"error": str(exc)}

    try:
        logger.info("Building airline earnings sensitivity surface...")
        results["airline_earnings_sensitivity"] = build_airline_earnings_sensitivity()
    except Exception as exc:
        logger.exception("Airline earnings sensitivity build failed")
        results["airline_earnings_sensitivity"] = {"error": str(exc)}

    try:
        logger.info("Building airline valuation snapshot...")
        results["airline_valuation_snapshot"] = build_airline_valuation_snapshot()
    except Exception as exc:
        logger.exception("Airline valuation snapshot build failed")
        results["airline_valuation_snapshot"] = {"error": str(exc)}

    try:
        logger.info("Building airline trade-construction card...")
        results["airline_trade_construction"] = build_airline_trade_construction()
    except Exception as exc:
        logger.exception("Airline trade construction build failed")
        results["airline_trade_construction"] = {"error": str(exc)}

    try:
        logger.info("Building airline residual yield model...")
        results["airline_residual_yield_model"] = build_airline_residual_yield_model()
    except Exception as exc:
        logger.exception("Airline residual yield model build failed")
        results["airline_residual_yield_model"] = {"error": str(exc)}

    try:
        logger.info("Building airline driver-based CASK model...")
        results["airline_cask_driver_model"] = build_airline_cask_driver_model()
    except Exception as exc:
        logger.exception("Airline CASK driver model build failed")
        results["airline_cask_driver_model"] = {"error": str(exc)}

    try:
        logger.info("Building airline forecast decision evaluation...")
        eval_df, _ens, _unc = build_airline_forecast_decision_eval()
        results["airline_forecast_decision_eval"] = eval_df
    except Exception as exc:
        logger.exception("Airline forecast decision eval build failed")
        results["airline_forecast_decision_eval"] = {"error": str(exc)}

    try:
        logger.info("Building airline pair-spread model...")
        results["airline_pair_spread_model"] = build_airline_pair_spread_model()
    except Exception as exc:
        logger.exception("Airline pair-spread model build failed")
        results["airline_pair_spread_model"] = {"error": str(exc)}

    try:
        logger.info("Building H1-2026 validation playbook...")
        results["airline_h1_2026_validation_playbook"] = build_airline_h1_2026_validation_playbook()
    except Exception as exc:
        logger.exception("Airline H1-2026 validation playbook build failed")
        results["airline_h1_2026_validation_playbook"] = {"error": str(exc)}

    try:
        logger.info("Building airline catalyst & risk calendar...")
        results["airline_catalyst_calendar"] = build_airline_catalyst_calendar()
    except Exception as exc:
        logger.exception("Airline catalyst calendar build failed")
        results["airline_catalyst_calendar"] = {"error": str(exc)}

    try:
        logger.info("Building airline post-earnings tracker...")
        results["airline_post_earnings_tracker"] = build_airline_post_earnings_tracker()
    except Exception as exc:
        logger.exception("Airline post-earnings tracker build failed")
        results["airline_post_earnings_tracker"] = {"error": str(exc)}

    try:
        logger.info("Building airline pre-event locked baseline...")
        results["airline_pre_event_locked_baseline"] = build_airline_pre_event_locked_baseline()
    except Exception as exc:
        logger.exception("Airline pre-event locked baseline build failed")
        results["airline_pre_event_locked_baseline"] = {"error": str(exc)}

    try:
        logger.info("Building airline v4 decomposition revenue model...")
        results["airline_earnings_model_v4"] = build_airline_earnings_model_v4()
    except Exception as exc:
        logger.exception("Airline v4 earnings model build failed")
        results["airline_earnings_model_v4"] = {"error": str(exc)}

    try:
        logger.info("Building cargo-bridge backtest...")
        results["airline_cargo_bridge_backtest"] = build_airline_cargo_bridge_backtest()
    except Exception as exc:
        logger.exception("Airline cargo-bridge backtest build failed")
        results["airline_cargo_bridge_backtest"] = {"error": str(exc)}

    try:
        logger.info("Ingesting CAAC monthly civil-aviation sector KPIs...")
        results["airline_caac_sector_monthly"] = fetch_caac_sector_monthly_kpis()
    except Exception as exc:
        logger.exception("CAAC monthly sector-KPI ingestion failed")
        results["airline_caac_sector_monthly"] = {"error": str(exc)}

    try:
        logger.info("Ingesting CAAC seasonal route-licence events...")
        results["airline_caac_route_licence_events"] = fetch_caac_route_licence_events()
    except Exception as exc:
        logger.exception("CAAC route-licence ingestion failed")
        results["airline_caac_route_licence_events"] = {"error": str(exc)}

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
        logger.info("Building airline fuel-surcharge recovery proxy...")
        results["airline_fuel_surcharge_recovery"] = build_airline_fuel_surcharge_recovery()
    except Exception as exc:
        logger.exception("Airline fuel-surcharge recovery build failed")
        results["airline_fuel_surcharge_recovery"] = {"error": str(exc)}

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
