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
