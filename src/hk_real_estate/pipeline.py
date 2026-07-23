"""Orchestration and data-quality gates for HK real-estate ingestion."""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping

import pandas as pd

from .sources.midland import run_midland_ingestion
from .sources.centaline import fetch_centaline_ccl
from .sources.hse28 import fetch_28hse_new_projects
from .sources.rvd import run_rvd_ingestion
from .sources.landreg import fetch_landreg_monthly_sp
from .sources.srpe import fetch_srpe_project_documents
from .sources.buildings_dept import fetch_buildings_dept_digests
from .storage import save_normalized_dataset, NORMALIZED_DIR


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hk_real_estate_pipeline")


class PipelineRunError(RuntimeError):
    """Raised after a run has been fully audited and one or more datasets failed."""

    def __init__(self, message: str, results: Dict[str, Any], manifest_path: str):
        super().__init__(message)
        self.results = results
        self.manifest_path = manifest_path


# Measures require a usable time key and critical numeric fields.  Catalogues
# are deliberately lighter-weight: they describe discoverable endpoints, not
# transaction or official-statistic facts, but cannot silently succeed empty.
QUALITY_SPECS: Dict[str, Dict[str, Any]] = {
    "midland_mhpi_weekly": {"kind": "measure", "required": ["date", "mhpi_overall"], "max_age_days": 400},
    "midland_confidence_weekly": {"kind": "measure", "required": ["date", "confidence_index"], "max_age_days": 400},
    "midland_top_estates_volume": {"kind": "catalog", "required": ["estate_id", "estate_name", "transaction_count"]},
    "centaline_ccl_weekly": {"kind": "measure", "required": ["date", "ccl_index"], "max_age_days": 400},
    "hse28_new_projects_catalog": {"kind": "catalog", "required": ["project_name"]},
    "rvd_price_index_monthly": {"kind": "measure", "required": ["date", "overall", "is_provisional"], "max_age_days": 400},
    "rvd_rental_index_monthly": {"kind": "measure", "required": ["date", "overall", "is_provisional"], "max_age_days": 400},
    "landreg_press_releases_catalog": {"kind": "catalog", "required": ["date", "release_title", "release_url"]},
    "srpe_document_endpoints_catalog": {"kind": "catalog", "required": ["action_endpoint"]},
    "buildings_dept_monthly_digests_catalog": {"kind": "catalog", "required": ["date", "digest_url"]},
}


def _quality_errors(dataset_name: str, df: pd.DataFrame) -> list[str]:
    spec = QUALITY_SPECS[dataset_name]
    if df.empty:
        return ["dataset yielded 0 records"]
    missing = [column for column in spec["required"] if column not in df.columns]
    if missing:
        return [f"missing required columns: {', '.join(missing)}"]
    null_columns = [column for column in spec["required"] if df[column].isna().any()]
    if null_columns:
        return [f"required columns contain null values: {', '.join(null_columns)}"]

    if spec["kind"] == "measure":
        dates = pd.to_datetime(df["date"], errors="coerce", utc=True)
        if dates.isna().any():
            return ["date contains invalid values"]
        if dates.duplicated().any():
            return ["date contains duplicate observations"]
        latest = dates.max()
        now = pd.Timestamp.now(tz="UTC")
        if latest > now + pd.Timedelta(days=7):
            return [f"latest observation is implausibly in the future: {latest.date()}"]
        if latest < now - pd.Timedelta(days=spec["max_age_days"]):
            return [f"latest observation is stale: {latest.date()}"]
    return []


def write_run_manifest(run_id: str, group_name: str, results_summary: Dict[str, Any]) -> str:
    """Persist an append-safe, run-scoped audit manifest for successful and failed runs."""
    manifest_dir = NORMALIZED_DIR / "runs" / run_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            manifest_data = json.load(f)
    else:
        manifest_data = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(), "groups": {}}
    manifest_data["groups"][group_name] = results_summary
    flattened = [item for group in manifest_data["groups"].values() for item in group.values()]
    manifest_data["status"] = "success" if flattened and all(item.get("status") == "success" for item in flattened) else "failed"
    manifest_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    return str(manifest_path)


def _error_result(error: Exception | str) -> Dict[str, Any]:
    return {"status": "error", "records": 0, "error": str(error)}


def _store_dataset(run_id: str, dataset_name: str, df: pd.DataFrame) -> Dict[str, Any]:
    errors = _quality_errors(dataset_name, df)
    if errors:
        status = "empty" if df.empty else "invalid"
        return {"status": status, "records": len(df), "errors": errors}
    stored = save_normalized_dataset(
        dataset_name,
        df,
        run_id=run_id,
        raw_snapshot=df.attrs.get("raw_snapshot"),
        source_url=df.attrs.get("source_url"),
    )
    return {**stored, "records": len(df), "status": "success"}


def _finalize_group(run_id: str, group_name: str, results: Dict[str, Any], raise_on_failure: bool) -> Dict[str, Any]:
    manifest_path = write_run_manifest(run_id, group_name, results)
    failures = {name: value for name, value in results.items() if value["status"] != "success"}
    if failures and raise_on_failure:
        raise PipelineRunError(f"{group_name} ingestion failed; manifest: {manifest_path}", results, manifest_path)
    return results


def _record_many(run_id: str, results: Dict[str, Any], datasets: Mapping[str, pd.DataFrame]) -> None:
    for dataset_name, df in datasets.items():
        try:
            results[dataset_name] = _store_dataset(run_id, dataset_name, df)
        except Exception as exc:  # storage errors must be visible in the manifest
            logger.exception("Failed to store %s", dataset_name)
            results[dataset_name] = _error_result(exc)


def run_group_a_pipeline(run_id: str | None = None, *, _raise_on_failure: bool = True) -> Dict[str, Any]:
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    try:
        logger.info("Ingesting Midland Market Insight data...")
        mhpi, confidence, estates = run_midland_ingestion()
        _record_many(run_id, results, {
            "midland_mhpi_weekly": mhpi,
            "midland_confidence_weekly": confidence,
            "midland_top_estates_volume": estates,
        })
    except Exception as exc:
        logger.exception("Midland ingestion failed")
        for name in ("midland_mhpi_weekly", "midland_confidence_weekly", "midland_top_estates_volume"):
            results[name] = _error_result(exc)
    try:
        logger.info("Ingesting Centaline CCL data...")
        _record_many(run_id, results, {"centaline_ccl_weekly": fetch_centaline_ccl()})
    except Exception as exc:
        logger.exception("Centaline ingestion failed")
        results["centaline_ccl_weekly"] = _error_result(exc)
    try:
        logger.info("Ingesting 28Hse new-project catalogue...")
        _record_many(run_id, results, {"hse28_new_projects_catalog": fetch_28hse_new_projects()})
    except Exception as exc:
        logger.exception("28Hse ingestion failed")
        results["hse28_new_projects_catalog"] = _error_result(exc)
    return _finalize_group(run_id, "group_a", results, _raise_on_failure)


def run_group_b_pipeline(run_id: str | None = None, *, _raise_on_failure: bool = True) -> Dict[str, Any]:
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    try:
        logger.info("Ingesting RVD official monthly indices...")
        price, rental = run_rvd_ingestion()
        _record_many(run_id, results, {"rvd_price_index_monthly": price, "rvd_rental_index_monthly": rental})
    except Exception as exc:
        logger.exception("RVD ingestion failed")
        results["rvd_price_index_monthly"] = _error_result(exc)
        results["rvd_rental_index_monthly"] = _error_result(exc)
    try:
        logger.info("Ingesting Land Registry press-release catalogue...")
        _record_many(run_id, results, {"landreg_press_releases_catalog": fetch_landreg_monthly_sp()})
    except Exception as exc:
        logger.exception("Land Registry ingestion failed")
        results["landreg_press_releases_catalog"] = _error_result(exc)
    return _finalize_group(run_id, "group_b", results, _raise_on_failure)


def run_group_c_pipeline(run_id: str | None = None, *, _raise_on_failure: bool = True) -> Dict[str, Any]:
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    try:
        logger.info("Ingesting SRPE endpoint catalogue...")
        _record_many(run_id, results, {"srpe_document_endpoints_catalog": fetch_srpe_project_documents()})
    except Exception as exc:
        logger.exception("SRPE ingestion failed")
        results["srpe_document_endpoints_catalog"] = _error_result(exc)
    try:
        logger.info("Ingesting Buildings Department digest catalogue...")
        _record_many(run_id, results, {"buildings_dept_monthly_digests_catalog": fetch_buildings_dept_digests()})
    except Exception as exc:
        logger.exception("Buildings Department ingestion failed")
        results["buildings_dept_monthly_digests_catalog"] = _error_result(exc)
    return _finalize_group(run_id, "group_c", results, _raise_on_failure)


def run_all_pipelines() -> Dict[str, Any]:
    run_id = str(uuid.uuid4())
    merged: Dict[str, Any] = {}
    for runner in (run_group_a_pipeline, run_group_b_pipeline, run_group_c_pipeline):
        merged.update(runner(run_id, _raise_on_failure=False))
    manifest_path = write_run_manifest(run_id, "all", merged)
    failures = {name: value for name, value in merged.items() if value["status"] != "success"}
    if failures:
        raise PipelineRunError(f"Full ingestion failed; manifest: {manifest_path}", merged, manifest_path)
    return merged


if __name__ == "__main__":
    run_all_pipelines()
