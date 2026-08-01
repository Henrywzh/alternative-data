"""Stage 1 execution pipeline for HK Utilities Sector."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .sources.clp_electricity import fetch_clp_electricity
from .sources.dsd_sewage_flow_lab import fetch_dsd_sewage_flow_lab
from .sources.hko_temperature import fetch_hko_temperature
from .sources.power_assets_segments import fetch_power_assets_segments
from .sources.towngas_proxy import fetch_towngas_proxy
from .sources.wsd_water_suspension import fetch_wsd_water_suspension

logger = logging.getLogger(__name__)

QUALITY_SPECS = {
    "clp_electricity_quarterly": {
        "kind": "measure",
        "required": ["quarter", "date", "commercial_gwh", "total_local_gwh"],
        "max_age_days": 400,
    },
    "towngas_proxy_gas_monthly": {
        "kind": "measure",
        "required": ["date", "month", "domestic_gas_tj", "total_gas_tj"],
        "max_age_days": 400,
    },
    "hko_mean_temperature_daily": {
        "kind": "measure",
        "required": ["date", "month", "mean_temp_c", "month_avg_temp_c"],
        "max_age_days": 400,
    },
    "power_assets_segments_semiannual": {
        "kind": "measure",
        "required": ["period", "date", "revenue_total_hkdm", "segment_profit_total_hkdm"],
        # Semi-annual disclosure (H1 interim + FY annual), each filed with a
        # multi-week lag -- much wider tolerance than the daily/monthly
        # sources above, since a "stale" gap of several months is normal.
        "max_age_days": 300,
    },
    "dsd_sewage_flow_lab_daily": {
        "kind": "measure",
        "required": ["date", "plant", "daily_flow_cum_d"],
        # DSD publishes this source monthly and the latest observation can
        # legitimately lag the fetch date by several weeks.
        "max_age_days": 120,
    },
    "wsd_water_suspension_events": {
        "kind": "event",
        "required": ["suspension_id", "suspension_start", "status"],
        "max_age_days": 1,
    },
}


def run_stage_1_pipeline() -> dict[str, Any]:
    """Execute Stage 1 ready-to-build ingestion for HK Utilities."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results = {}

    try:
        logger.info("Ingesting CLP Power quarterly electricity sales...")
        results["clp_electricity_quarterly"] = fetch_clp_electricity()
    except Exception as exc:
        logger.exception("CLP electricity ingestion failed")
        results["clp_electricity_quarterly"] = {"error": str(exc)}

    try:
        logger.info("Ingesting Towngas proxy (CenStatD monthly gas consumption)...")
        results["towngas_proxy_gas_monthly"] = fetch_towngas_proxy()
    except Exception as exc:
        logger.exception("Towngas proxy gas consumption ingestion failed")
        results["towngas_proxy_gas_monthly"] = {"error": str(exc)}

    try:
        logger.info("Ingesting HKO daily mean temperature...")
        results["hko_mean_temperature_daily"] = fetch_hko_temperature()
    except Exception as exc:
        logger.exception("HKO mean temperature ingestion failed")
        results["hko_mean_temperature_daily"] = {"error": str(exc)}

    try:
        logger.info("Ingesting Power Assets geographic segment reporting...")
        results["power_assets_segments_semiannual"] = fetch_power_assets_segments()
    except Exception as exc:
        logger.exception("Power Assets segment reporting ingestion failed")
        results["power_assets_segments_semiannual"] = {"error": str(exc)}

    try:
        logger.info("Ingesting DSD daily sewage flow and effluent laboratory data...")
        results["dsd_sewage_flow_lab_daily"] = fetch_dsd_sewage_flow_lab()
    except Exception as exc:
        logger.exception("DSD sewage flow/laboratory ingestion failed")
        results["dsd_sewage_flow_lab_daily"] = {"error": str(exc)}

    try:
        logger.info("Ingesting WSD temporary water-suspension notices...")
        results["wsd_water_suspension_events"] = fetch_wsd_water_suspension()
    except Exception as exc:
        logger.exception("WSD water-suspension ingestion failed")
        results["wsd_water_suspension_events"] = {"error": str(exc)}

    return results
