"""Stage 1 execution pipeline for HK Telecom Sector."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .sources.hkt_operating_drivers import fetch_hkt_operating_drivers

logger = logging.getLogger(__name__)

QUALITY_SPECS = {
    "hkt_operating_drivers_semi_annual": {
        "kind": "measure",
        "required": ["period", "date", "mobile_postpaid_subscribers_thousands", "mobile_postpaid_arpu_hkd"],
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

    return results
