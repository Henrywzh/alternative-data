"""Aviation alternative data source classification and registry module.

This module systematically classifies external aviation data sources
(Flightradar24, FlightAware AeroAPI, FlightConnections, Planespotters, Cirium/OAG,
CAAC releases, Ctrip SSR, 9 Air Fleet Page, and Issuer Annual Reports)
by access tier, reproducibility, measurement granularity, point-in-time reliability,
and source-conflict management policies.
"""

from __future__ import annotations

import pandas as pd

from ..config import NORMALIZED_DIR

REGISTRY_PATH = NORMALIZED_DIR / "airline_aviation_source_registry.csv"

AVIATION_SOURCES: list[dict[str, str | bool]] = [
    {
        "source_id": "issuer_annual_report_filing",
        "source_name": "Issuer Annual Reports & Prospectuses (CNINFO / HKEX)",
        "source_tier": "primary_official",
        "access_method": "public_pdf_http_get",
        "cost_type": "free_official",
        "data_granularity": "company_fleet_cabin_seat_disclosures",
        "time_semantics": "point_in_time_historical",
        "reproducibility_score": "high_100pct_reproducible",
        "seat_layout_coverage": "official_disclosed_cabin_seats",
        "route_frequency_coverage": "disclosed_route_additions",
        "bot_block_risk": "none",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-04-23/1225151299.PDF",
        "source_note": "Primary official filing for Juneyao Mainline (180-seat A320/A321, Page 13-15), 9 Air B737 series limit text (189 seats, Page 15), and Spring Airlines (186-seat A320). Filing date: 2026-04-23.",
    },
    {
        "source_id": "9air_official_fleet_page",
        "source_name": "9 Air Official Fleet & Cabin Disclosure Page",
        "source_tier": "primary_official",
        "access_method": "public_web_html",
        "cost_type": "free_official",
        "data_granularity": "operational_fleet_seat_configuration",
        "time_semantics": "live_operational_state",
        "reproducibility_score": "high_100pct_reproducible",
        "seat_layout_coverage": "operational_188_seat_lcc_layout",
        "route_frequency_coverage": "route_network_promotions",
        "bot_block_risk": "none",
        "source_url": "https://www.9air.com/cmsProvider/info/1011/1431.htm",
        "source_note": "Primary official page for 9 Air operational B737 seat layout (188 seats). Published date: 2026-05-26. Analytical inference: 188 seats represents current operational seat-selection layout, while annual report 189 seats reflects generic B737 series limit description.",
    },
    {
        "source_id": "ctrip_ssr_train_booking",
        "source_name": "Ctrip Train Search SSR Payload",
        "source_tier": "secondary_aggregator",
        "access_method": "public_html_ssr_next_data",
        "cost_type": "free_public",
        "data_granularity": "train_level_schedules_fares_seats",
        "time_semantics": "point_in_time_dated_snapshot",
        "reproducibility_score": "high_100pct_reproducible",
        "seat_layout_coverage": "train_seat_classes_second_first_business",
        "route_frequency_coverage": "daily_g_d_train_frequency",
        "bot_block_risk": "low_ssr_html",
        "source_url": "https://trains.ctrip.com/trainbooking/search",
        "source_note": "Verified fallback for dated HSR timetables, train codes, run times, and 2nd-class fares.",
    },
    {
        "source_id": "osrm_routing_engine",
        "source_name": "OSRM Open Source Routing Machine",
        "source_tier": "secondary_derived",
        "access_method": "public_json_rest_api",
        "cost_type": "free_open_source",
        "data_granularity": "hub_to_cbd_driving_duration_distance",
        "time_semantics": "static_road_network_routing",
        "reproducibility_score": "high_100pct_reproducible",
        "seat_layout_coverage": "not_applicable",
        "route_frequency_coverage": "not_applicable",
        "bot_block_risk": "none",
        "source_url": "http://router.project-osrm.org/route/v1/driving",
        "source_note": "Calculates airport-vs-station CBD driving time deltas without key restrictions or hardcoded numbers.",
    },
    {
        "source_id": "caac_official_bulletin",
        "source_name": "CAAC Civil Aviation Administration of China Releases",
        "source_tier": "primary_official",
        "access_method": "public_web_http_get",
        "cost_type": "free_official",
        "data_granularity": "macro_passenger_volume_season_routes",
        "time_semantics": "monthly_seasonal_releases",
        "reproducibility_score": "high_100pct_reproducible",
        "seat_layout_coverage": "macro_capacity_only",
        "route_frequency_coverage": "seasonal_weekly_flight_quotas",
        "bot_block_risk": "none",
        "source_url": "https://www.caac.gov.cn/",
        "source_note": "Official seasonal route allocation and macro civil aviation passenger statistics.",
    },
    {
        "source_id": "flightconnections_discovery",
        "source_name": "FlightConnections Route Map & Schedule Discovery",
        "source_tier": "discovery_only",
        "access_method": "public_web_html",
        "cost_type": "free_limited_paid",
        "data_granularity": "route_network_destinations_weekly_freq",
        "time_semantics": "current_schedule_discovery",
        "reproducibility_score": "medium_web",
        "seat_layout_coverage": "not_applicable",
        "route_frequency_coverage": "indicative_weekly_schedules",
        "bot_block_risk": "medium_web",
        "source_url": "https://www.flightconnections.com/",
        "source_note": "Discovery tool for interactive route maps; does not provide audited historical capacity or seat configuration data.",
    },
    {
        "source_id": "flightradar24_public",
        "source_name": "Flightradar24 Public Airline & Flight Data",
        "source_tier": "discovery_only",
        "access_method": "public_web_html",
        "cost_type": "free_limited_paid_api",
        "data_granularity": "realtime_adsb_flight_tracking",
        "time_semantics": "realtime_live_tracking",
        "reproducibility_score": "medium_requires_session_key",
        "seat_layout_coverage": "aircraft_tail_type_only",
        "route_frequency_coverage": "recent_7day_flight_history",
        "bot_block_risk": "high_cloudflare_waf",
        "source_url": "https://www.flightradar24.com/data/airlines/aq-9air",
        "source_note": "Discovery tool for observed flight operations, tail registrations, and aircraft types; does not disclose cabin seat layout.",
    },
    {
        "source_id": "flightaware_aeroapi",
        "source_name": "FlightAware AeroAPI Commercial Flight Data",
        "source_tier": "commercial_grade",
        "access_method": "commercial_rest_api",
        "cost_type": "paid_api_subscription",
        "data_granularity": "flight_by_flight_tracking_tail_schedules",
        "time_semantics": "realtime_and_historical_flight_history",
        "reproducibility_score": "high_paid_api",
        "seat_layout_coverage": "aircraft_type_code_only",
        "route_frequency_coverage": "historical_flight_counts",
        "bot_block_risk": "none_paid_credentials",
        "source_url": "https://flightaware.com/commercial/aeroapi/",
        "source_note": "Commercial flight-tracking API for audited tail operations and actual flight histories; requires paid API key.",
    },
    {
        "source_id": "planespotters_net",
        "source_name": "Planespotters.net Civil Aviation Fleet Database",
        "source_tier": "discovery_only",
        "access_method": "public_web_database",
        "cost_type": "free_rate_limited",
        "data_granularity": "aircraft_tail_msn_age_operator",
        "time_semantics": "historical_current_fleet_status",
        "reproducibility_score": "medium_web_rate_limited",
        "seat_layout_coverage": "historical_cabin_config_notes",
        "route_frequency_coverage": "not_applicable",
        "bot_block_risk": "high_http_403_waf",
        "source_url": "https://www.planespotters.net/",
        "source_note": "Web database discovery source for aircraft tail registrations, MSN, and operator history; subject to strict terms and WAF rate limits.",
    },
    {
        "source_id": "cirium_oag_schedules",
        "source_name": "Cirium / OAG Global Airline Schedules",
        "source_tier": "commercial_grade",
        "access_method": "commercial_api_subscription",
        "cost_type": "paid_enterprise",
        "data_granularity": "flight_by_flight_scheduled_seats_ask",
        "time_semantics": "point_in_time_historical_schedules",
        "reproducibility_score": "high_paid_api",
        "seat_layout_coverage": "exact_flight_seat_counts",
        "route_frequency_coverage": "complete_global_schedules",
        "bot_block_risk": "none_paid_credentials",
        "source_url": "https://www.cirium.com/",
        "source_note": "Gold standard commercial schedule database with exact flight-by-flight seat capacity; requires paid enterprise API subscription.",
    },
]


def fetch_airline_aviation_source_registry() -> pd.DataFrame:
    """Build and persist the aviation data source classification registry."""
    df = pd.DataFrame(AVIATION_SOURCES)
    df.insert(0, "dataset_id", "airline_aviation_source_registry")
    df["retrieved_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    df.to_csv(REGISTRY_PATH, index=False)
    return df
