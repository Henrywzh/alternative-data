"""Stage 1 execution pipeline for HK Telecom Sector."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .sources.hkt_operating_drivers import fetch_hkt_operating_drivers
from .sources.hutchison_telecom_operating_drivers import fetch_hutchison_telecom_operating_drivers
from .sources.numbering_plan import fetch_numbering_plan
from .sources.smartone_operating_drivers import fetch_smartone_operating_drivers

logger = logging.getLogger(__name__)

QUALITY_SPECS = {
    "hkt_operating_drivers_semi_annual": {
        "kind": "measure",
        "required": ["period", "date", "mobile_postpaid_subscribers_thousands", "mobile_postpaid_arpu_hkd"],
        "max_age_days": 400,
    },
    "smartone_operating_drivers_semi_annual": {
        "kind": "measure",
        "required": ["period", "date", "postpaid_subscribers_thousands", "postpaid_arpu_hkd"],
        "max_age_days": 400,
    },
    "hutchison_telecom_operating_drivers_semi_annual": {
        "kind": "measure",
        "required": ["period", "date", "postpaid_customers_thousands", "postpaid_gross_arpu_hkd"],
        "max_age_days": 400,
    },
    "numbering_plan_snapshot": {
        "kind": "context",
        "required": ["allocatee", "num_blocks", "total_numbers_allocated"],
        "max_age_days": 400,
    },
}


def run_stage_1_pipeline() -> dict[str, Any]:
    """Execute Stage 1 ready-to-build ingestion for HK Telecom."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results = {}

    try:
        logger.info("Ingesting HKT Trust key operating drivers & ARPU...")
        results["hkt_operating_drivers_semi_annual"] = fetch_hkt_operating_drivers()
    except Exception as exc:
        logger.exception("HKT operating drivers ingestion failed")
        results["hkt_operating_drivers_semi_annual"] = {"error": str(exc)}

    try:
        logger.info("Ingesting SmarTone operating drivers & ARPU...")
        results["smartone_operating_drivers_semi_annual"] = fetch_smartone_operating_drivers()
    except Exception as exc:
        logger.exception("SmarTone operating drivers ingestion failed")
        results["smartone_operating_drivers_semi_annual"] = {"error": str(exc)}

    try:
        logger.info("Ingesting Hutchison Telecom HK Holdings (3 HK) KPIs...")
        results["hutchison_telecom_operating_drivers_semi_annual"] = fetch_hutchison_telecom_operating_drivers()
    except Exception as exc:
        logger.exception("Hutchison Telecom operating drivers ingestion failed")
        results["hutchison_telecom_operating_drivers_semi_annual"] = {"error": str(exc)}

    try:
        logger.info("Ingesting OFCA numbering plan snapshot...")
        results["numbering_plan_snapshot"] = fetch_numbering_plan()
    except Exception as exc:
        logger.exception("Numbering plan ingestion failed")
        results["numbering_plan_snapshot"] = {"error": str(exc)}

    return results
