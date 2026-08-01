"""Stage 1 execution pipeline for HK Commercial Aerospace Sector."""

from __future__ import annotations

import logging
from typing import Any

from .sources.launch_library import fetch_upcoming_launches, fetch_chinese_commercial_launches
from .sources.sse_ipo_status import fetch_all_ipo_statuses
from .sources.celestrak_satellites import fetch_all_constellations
from .sources.google_patents import fetch_all_patent_counts
from .sources.szse_ipo_status import fetch_aerospace_ipo_projects
from .sources.faa_commercial_space import fetch_faa_commercial_space_kpis
from .sources.usaspending import fetch_commercial_space_contracts
from .sources.global_space_benchmark import fetch_global_objects_launched
from .sources.sec_space_companies import fetch_sec_space_company_filings
from .sources.wikimedia_pageviews import fetch_wikipedia_aerospace_pageviews

logger = logging.getLogger(__name__)

QUALITY_SPECS = {
    "ipo_status": {
        "kind": "status_table",
        "required": ["name_en", "name_zh", "status", "fetched_at"],
        "max_age_days": 7,
    },
    "upcoming_launches": {
        "kind": "event_feed",
        "required": ["launch_id", "name", "net_time", "provider_name"],
        "max_age_days": 3,
    },
    "chinese_commercial_launches": {
        "kind": "event_feed",
        "required": ["launch_id", "name", "provider_name"],
        "max_age_days": 7,
    },
    "satellite_counts": {
        "kind": "measure",
        "required": ["constellation", "satellite_count"],
        "max_age_days": 30,
    },
    "patent_counts": {
        "kind": "measure",
        "required": ["assignee_query", "fetched_at"],
        "max_age_days": 30,
    },
    "szse_ipo_projects": {
        "kind": "status_table",
        "required": ["company_name", "status", "industry", "fetched_at"],
        "max_age_days": 7,
    },
    "faa_commercial_space": {
        "kind": "measure",
        "required": ["metric", "value", "observed_date", "fetched_at"],
        "max_age_days": 30,
    },
    "usaspending_contracts": {
        "kind": "event_feed",
        "required": ["award_id", "recipient_name", "award_amount", "fetched_at"],
        "max_age_days": 30,
    },
    "global_space_benchmark": {
        "kind": "measure",
        "required": ["entity", "year", "objects_launched", "fetched_at"],
        "max_age_days": 365,
    },
    "sec_space_filings": {
        "kind": "event_feed",
        "required": ["ticker", "form", "filing_date", "fetched_at"],
        "max_age_days": 14,
    },
    "wikipedia_pageviews": {
        "kind": "measure",
        "required": ["page_id", "agent", "month", "views", "fetched_at"],
        "max_age_days": 45,
    },
}


def _validate_ipo_status(result: dict) -> bool:
    """Validate that known companies return their expected status."""
    # Assuming result is a dict with records or a pandas dataframe. 
    # Usually in the pipeline, result is a DataFrame.
    # The prompt says: _validate_ipo_status(result: dict) -> bool
    # We will assume result is a dict representation of the IPO DataFrame.
    try:
        # if it's a dict of records (list of dicts)
        if isinstance(result, list):
            records = result
        elif isinstance(result, dict) and "error" not in result:
            # Maybe it's a dict with keys?
            records = result.get("data", [])
        else:
            return False
            
        landspace_found = False
        cas_found = False
        for r in records:
            if r.get("name_en") == "LandSpace" and r.get("status") == "已问询":
                landspace_found = True
            if r.get("name_en") == "CAS Space" and r.get("status") == "已问询":
                cas_found = True
                
        return landspace_found and cas_found
    except Exception:
        return False


def run_stage_1_pipeline() -> dict[str, Any]:
    """Execute Stage 1 ready-to-build ingestion for HK Commercial Aerospace."""
    results = {}

    try:
        logger.info("Ingesting IPO Statuses...")
        df = fetch_all_ipo_statuses()
        results["ipo_status"] = df
    except Exception as exc:
        logger.exception("IPO Statuses ingestion failed")
        results["ipo_status"] = {"error": str(exc)}

    try:
        logger.info("Ingesting Upcoming Launches...")
        df = fetch_upcoming_launches()
        results["upcoming_launches"] = df
    except Exception as exc:
        logger.exception("Upcoming Launches ingestion failed")
        results["upcoming_launches"] = {"error": str(exc)}

    try:
        logger.info("Ingesting Chinese Commercial Launches...")
        df_dict = fetch_chinese_commercial_launches()
        results["chinese_commercial_launches"] = df_dict
    except Exception as exc:
        logger.exception("Chinese Commercial Launches ingestion failed")
        results["chinese_commercial_launches"] = {"error": str(exc)}

    try:
        logger.info("Ingesting Satellite Counts...")
        df = fetch_all_constellations()
        results["satellite_counts"] = df
    except Exception as exc:
        logger.exception("Satellite Counts ingestion failed")
        results["satellite_counts"] = {"error": str(exc)}

    try:
        logger.info("Ingesting Patent Counts...")
        df = fetch_all_patent_counts()
        results["patent_counts"] = df
    except Exception as exc:
        logger.exception("Patent Counts ingestion failed")
        results["patent_counts"] = {"error": str(exc)}

    try:
        logger.info("Ingesting SZSE aerospace IPO projects...")
        results["szse_ipo_projects"] = fetch_aerospace_ipo_projects()
    except Exception as exc:
        logger.exception("SZSE aerospace IPO ingestion failed")
        results["szse_ipo_projects"] = {"error": str(exc)}

    return results


def run_stage_2_pipeline() -> dict[str, Any]:
    """Execute Stage 2 global contracts, regulatory and company-event feeds."""
    results: dict[str, Any] = {}
    fetchers = {
        "faa_commercial_space": fetch_faa_commercial_space_kpis,
        "usaspending_contracts": fetch_commercial_space_contracts,
        "global_space_benchmark": fetch_global_objects_launched,
        "sec_space_filings": fetch_sec_space_company_filings,
        "wikipedia_pageviews": fetch_wikipedia_aerospace_pageviews,
    }
    for key, fetcher in fetchers.items():
        try:
            logger.info("Ingesting %s...", key)
            results[key] = fetcher()
        except Exception as exc:
            logger.exception("%s ingestion failed", key)
            results[key] = {"error": str(exc)}
    return results
