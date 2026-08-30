"""Pipeline for HK Population & Migration Sector Data Ingestion."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .sources.immd_daily_traffic import fetch_immd_daily_traffic
from .sources.csd_population import fetch_csd_population_estimates
from .sources.mpfa_claims import fetch_mpfa_permanent_departure_claims
from .sources.ugc_students import fetch_ugc_nonlocal_students
from .sources.td_cross_border import fetch_td_cross_border_traffic
from .sources.ia_premiums import fetch_ia_mainland_visitor_premiums
from .sources.censtatd_visitor_arrivals import fetch_visitor_arrivals_by_region
from .storage import save_normalized_dataset

logger = logging.getLogger(__name__)


def run_stage_1_pipeline(*, raise_on_failure: bool = False) -> dict[str, Any]:
    """Execute Stage 1 ingestion for HK Population & Migration Sector."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results = {}

    def ingest(dataset_name: str, label: str, fetcher) -> None:
        try:
            logger.info("Ingesting %s...", label)
            frame = fetcher()
            save_normalized_dataset(
                dataset_name,
                frame,
                run_id=run_id,
                source_url=frame.attrs.get("source_url"),
            )
            results[dataset_name] = frame
        except Exception as exc:
            logger.exception("%s ingestion failed", label)
            results[dataset_name] = {"error": str(exc)}

    ingest("immd_daily_traffic", "ImmD daily passenger traffic", fetch_immd_daily_traffic)
    ingest("csd_population_estimates", "C&SD population estimates", fetch_csd_population_estimates)
    ingest("mpfa_departure_claims", "MPFA permanent departure claims", fetch_mpfa_permanent_departure_claims)
    ingest("ugc_nonlocal_students", "UGC non-local student enrollment", fetch_ugc_nonlocal_students)
    ingest("td_cross_border_traffic", "Transport Dept cross-border traffic", fetch_td_cross_border_traffic)
    ingest(
        "censtatd_visitor_arrivals",
        "C&SD visitor arrivals by region",
        fetch_visitor_arrivals_by_region,
    )

    try:
        logger.info("Ingesting Insurance Authority Mainland Visitor premiums...")
        results["ia_mainland_visitor_premiums"] = fetch_ia_mainland_visitor_premiums()
    except Exception as exc:
        logger.exception("Insurance Authority premiums ingestion failed")
        results["ia_mainland_visitor_premiums"] = {"error": str(exc)}

    failures = {
        dataset_name: result
        for dataset_name, result in results.items()
        if isinstance(result, dict) and result.get("error")
    }
    if raise_on_failure and failures:
        failed_names = ", ".join(sorted(failures))
        raise RuntimeError(f"Population/migration ingestion failed: {failed_names}")
    return results
