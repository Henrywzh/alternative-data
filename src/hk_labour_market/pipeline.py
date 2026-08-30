"""Stage 1 full-history ingestion for official Hong Kong labour-market data."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from .quality import validate_frame, validate_policy_frame
from .source_registry import (
    CORE_CENSTATD_TABLES,
    STAGE_2_CENSTATD_TABLES,
    STAGE_3_CENSTATD_TABLES,
    CenstatdTableSpec,
)
from .sources.censtatd import CenstatdFetchError, fetch_censtatd_table
from .sources.labour_department import ESLS_KEY_STATISTICS_URL, ESLS_SOURCE_ID, fetch_esls_key_statistics
from .sources.immigration_employment import EMPLOYMENT_POLICY_SOURCES, fetch_employment_policy_source
from .storage import (
    save_normalized_dataset,
    save_raw_snapshot,
    write_latest_run_pointer,
    write_run_manifest,
)

logger = logging.getLogger(__name__)


class LabourMarketRunError(RuntimeError):
    """Raised only when callers opt into failure on any source error."""


def _ingest_table(run_id: str, spec: CenstatdTableSpec) -> dict[str, Any]:
    try:
        payload, frame = fetch_censtatd_table(spec)
    except CenstatdFetchError as exc:
        if exc.payload is None:
            raise
        raw_snapshot = save_raw_snapshot(spec.dataset_id, exc.payload, source_url=spec.source_url, run_id=run_id)
        return {
            "status": "invalid",
            "records": 0,
            "errors": [str(exc)],
            "source_table_id": spec.table_id,
            "source_url": spec.source_url,
            "raw_snapshot": str(raw_snapshot),
        }
    # Preserve every HTTP-successful source response, even if its shape or
    # freshness subsequently fails our quality gate.  A rejected vintage is
    # still evidence needed to investigate a provider change.
    raw_snapshot = save_raw_snapshot(spec.dataset_id, payload, source_url=spec.source_url, run_id=run_id)
    errors = validate_frame(frame, spec)
    if errors:
        return {
            "status": "invalid",
            "records": len(frame),
            "errors": errors,
            "raw_snapshot": str(raw_snapshot),
        }
    stored = save_normalized_dataset(
        spec.dataset_id,
        frame,
        run_id=run_id,
        raw_snapshot=raw_snapshot,
        source_url=spec.source_url,
    )
    numeric = frame[frame["value"].notna()]
    return {
        "status": "success",
        "records": len(frame),
        "numeric_records": len(numeric),
        "first_period": frame["period"].min(),
        "latest_period": numeric["period"].max(),
        "source_table_id": spec.table_id,
        "source_url": spec.source_url,
        "raw_snapshot": str(raw_snapshot),
        **stored,
    }


def _run_tables(
    group_name: str,
    specs: tuple[CenstatdTableSpec, ...],
    run_id: str | None = None,
    *,
    raise_on_failure: bool = False,
) -> dict[str, Any]:
    """Backfill one explicit group of official C&SD tables and write its manifest."""
    run_id = run_id or str(uuid.uuid4())
    results: dict[str, Any] = {}
    for spec in specs:
        try:
            logger.info("Ingesting C&SD table %s (%s)", spec.table_id, spec.dataset_id)
            results[spec.dataset_id] = _ingest_table(run_id, spec)
        except Exception as exc:
            logger.exception("C&SD ingestion failed for %s", spec.table_id)
            results[spec.dataset_id] = {
                "status": "error",
                "records": 0,
                "source_table_id": spec.table_id,
                "source_url": spec.source_url,
                "error": str(exc),
            }
    manifest_path = write_run_manifest(run_id, results)
    failures = {key: value for key, value in results.items() if value["status"] != "success"}
    if not failures:
        write_latest_run_pointer(group_name, run_id, manifest_path)
    if failures and raise_on_failure:
        raise LabourMarketRunError(f"{group_name} failed; manifest: {manifest_path}")
    return {"run_id": run_id, "manifest": str(manifest_path), "results": results}


def run_stage_1_pipeline(run_id: str | None = None, *, raise_on_failure: bool = False) -> dict[str, Any]:
    """Backfill the nine core official C&SD full-history tables."""
    return _run_tables("stage_1", CORE_CENSTATD_TABLES, run_id, raise_on_failure=raise_on_failure)


def run_stage_2_pipeline(run_id: str | None = None, *, raise_on_failure: bool = False) -> dict[str, Any]:
    """Backfill detailed industry, occupation and construction labour history."""
    return _run_tables("stage_2", STAGE_2_CENSTATD_TABLES, run_id, raise_on_failure=raise_on_failure)


def run_stage_3_pipeline(run_id: str | None = None, *, raise_on_failure: bool = False) -> dict[str, Any]:
    """Backfill annual earnings, hourly-wage and working-hours distribution history."""
    return _run_tables("stage_3", STAGE_3_CENSTATD_TABLES, run_id, raise_on_failure=raise_on_failure)


def run_stage_4_pipeline(run_id: str | None = None, *, raise_on_failure: bool = False) -> dict[str, Any]:
    """Backfill reliable official labour-supply policy histories."""
    run_id = run_id or str(uuid.uuid4())
    results: dict[str, Any] = {}
    source_jobs = [
        ("esls_applications_annual", ESLS_KEY_STATISTICS_URL, fetch_esls_key_statistics, "xml", ESLS_SOURCE_ID),
    ]
    for source in EMPLOYMENT_POLICY_SOURCES:
        source_jobs.append((source["dataset_id"], source["url"], lambda s=source: fetch_employment_policy_source(s), "csv", source["source_table_id"]))
    for dataset_id, source_url, fetcher, file_type, source_table_id in source_jobs:
        try:
            raw_body, frame = fetcher()
            errors = validate_policy_frame(frame, expected_source_table_id=source_table_id)
            raw_snapshot = save_raw_snapshot(dataset_id, {"source_format": file_type, "body": raw_body}, source_url=source_url, run_id=run_id)
            if errors:
                results[dataset_id] = {"status": "invalid", "records": len(frame), "errors": errors, "raw_snapshot": str(raw_snapshot)}
                continue
            stored = save_normalized_dataset(
                dataset_id,
                frame,
                run_id=run_id,
                raw_snapshot=raw_snapshot,
                source_url=source_url,
                data_source=str(frame["data_source"].dropna().iloc[0]) if frame["data_source"].notna().any() else "official_labour_supply_open_data",
            )
            results[dataset_id] = {
                "status": "success", "records": len(frame), "numeric_records": int(frame["value"].notna().sum()),
                "first_period": frame["period"].min(), "latest_period": frame["period"].max(),
                "source_url": source_url, "raw_snapshot": str(raw_snapshot), **stored,
            }
        except Exception as exc:
            logger.exception("Labour-supply ingestion failed for %s", dataset_id)
            raw_snapshot = None
            raw_body = getattr(exc, "raw_body", None)
            if raw_body is not None:
                raw_snapshot = save_raw_snapshot(
                    dataset_id,
                    {"source_format": file_type, "body": raw_body},
                    source_url=source_url,
                    run_id=run_id,
                )
            results[dataset_id] = {
                "status": "error",
                "records": 0,
                "source_url": source_url,
                "error": str(exc),
                **({"raw_snapshot": str(raw_snapshot)} if raw_snapshot else {}),
            }
    manifest_path = write_run_manifest(run_id, results)
    failures = {key: value for key, value in results.items() if value["status"] != "success"}
    if not failures:
        write_latest_run_pointer("stage_4", run_id, manifest_path)
    if failures and raise_on_failure:
        raise LabourMarketRunError(f"Stage 4 failed; manifest: {manifest_path}")
    return {"run_id": run_id, "manifest": str(manifest_path), "results": results}


def run_update_pipeline(*, raise_on_failure: bool = False, build_marts: bool = True) -> dict[str, Any]:
    """Refresh every official source group and optionally rebuild the marts.

    The providers expose small full-history files/APIs.  Refreshing the full
    series is safer than guessing a delta window; each run remains immutable,
    while ``latest_runs.json`` moves only after an all-successful group.
    """
    stage_results = {
        "stage_1": run_stage_1_pipeline(raise_on_failure=raise_on_failure),
        "stage_2": run_stage_2_pipeline(raise_on_failure=raise_on_failure),
        "stage_3": run_stage_3_pipeline(raise_on_failure=raise_on_failure),
        "stage_4": run_stage_4_pipeline(raise_on_failure=raise_on_failure),
    }
    result: dict[str, Any] = {"stages": stage_results}
    stage_success = {
        stage_name: bool(stage_result.get("results"))
        and all(item.get("status") == "success" for item in stage_result["results"].values())
        for stage_name, stage_result in stage_results.items()
    }
    result["stage_success"] = stage_success
    # The Streamlit marts consume Stage 1 core series and Stage 3 annual
    # distributions. Stage 2 is deeper drill-down data and Stage 4 policy
    # sources are already optional inside the policy mart. A transient failure
    # in either optional group must remain visible in the audit, but must not
    # freeze otherwise-current headline labour data.
    mart_inputs_ready = stage_success["stage_1"] and stage_success["stage_3"]
    if build_marts and mart_inputs_ready:
        from .marts import build_analysis_marts

        result["marts"] = build_analysis_marts()
        from .audit import run_labour_market_audit

        result["audit"] = run_labour_market_audit()
        if raise_on_failure and result["audit"]["status"] != "pass":
            raise LabourMarketRunError("Labour-market audit failed after update")
    elif build_marts:
        result["marts_skipped_reason"] = (
            "Stage 1 and Stage 3 must both complete successfully before marts are rebuilt"
        )
    return result
