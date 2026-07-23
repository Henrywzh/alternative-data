"""Stage 1 execution pipeline for HK Transport Sector."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .sources.cathay_traffic import fetch_cathay_traffic
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

    return results
