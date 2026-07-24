"""Orchestration and data-quality gates for HK real-estate ingestion."""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping

import pandas as pd

from .sources.midland import run_midland_ingestion
from .sources.centaline import fetch_centaline_ccl
from .sources.hse28 import fetch_28hse_new_projects
from .sources.hse28 import fetch_28hse_transaction_pilot
from .sources.epi import fetch_28hse_epi_eri
from .sources.rvd import run_rvd_ingestion
from .sources.landreg import fetch_landreg_monthly_sp, fetch_landreg_monthly_statistics
from .sources.srpe import fetch_srpe_project_documents, fetch_srpe_firsthand_sales_digest
from .sources.buildings_dept import fetch_buildings_dept_digests, fetch_buildings_dept_monthly_stats
from .sources.hkma import fetch_hkma_residential_mortgage_survey
from .sources.bd_projects import fetch_bd_project_lifecycle_events, fetch_bd_supply_leading_indicators
from .dedup.transaction_dedup import deduplicate_agency_transactions
from .storage import save_normalized_dataset, NORMALIZED_DIR


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hk_real_estate_pipeline")


class PipelineRunError(RuntimeError):
    """Raised after a run has been fully audited and one or more datasets failed."""

    def __init__(self, message: str, results: Dict[str, Any], manifest_path: str):
        super().__init__(message)
        self.results = results
        self.manifest_path = manifest_path


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
    "srpe_firsthand_sales_digest": {"kind": "catalog", "required": ["document_category", "endpoint_url", "source_agency", "development_id", "document_id"]},
    "buildings_dept_monthly_digests_catalog": {"kind": "catalog", "required": ["date", "digest_url"]},
    "hse28_epi_eri_weekly": {"kind": "measure", "required": ["date", "period_start", "period_end", "index_type", "index_value"], "max_age_days": 400},
    "hse28_transaction_pilot": {"kind": "measure", "required": ["date", "transaction_date", "source_record_id", "price_hkd"], "max_age_days": 400},
    "unified_agency_transactions_deduped": {"kind": "measure", "required": ["transaction_date", "dedup_transaction_id"], "max_age_days": 400},
    "landreg_monthly_facts": {"kind": "measure", "required": ["date", "statistic_name", "units"], "max_age_days": 400},
    "landreg_asp_series": {"kind": "measure", "required": ["date", "all_building_units_asp", "residential_units_asp"], "max_age_days": 400},
    "buildings_dept_monthly_stats": {"kind": "catalog", "required": ["date", "table_id", "numeric_values"]},
    "bd_supply_leading_indicators": {"kind": "measure", "required": ["date", "permit_stage", "region"], "max_age_days": 400},
    "hkma_residential_mortgage_survey": {"kind": "measure", "required": ["observation_date", "approved_loans_amount_mhkd"], "max_age_days": 400},
    "bd_project_lifecycle_events": {"kind": "catalog", "required": ["permit_stage", "site_address"]},
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
        date_col = "observation_date" if "observation_date" in df.columns else "date"
        dates = pd.to_datetime(df[date_col], errors="coerce", utc=True)
        if dates.isna().any():
            return [f"{date_col} contains invalid values"]
        duplicate_key = [date_col]
        for candidate in ("index_type", "statistic_name", "table_id", "source_record_id", "dedup_transaction_id", "permit_stage", "region", "property_category"):
            if candidate in df.columns:
                duplicate_key.append(candidate)
        if df.duplicated(subset=duplicate_key).any():
            return [f"{date_col} contains duplicate observations"]
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
    manifest_data["status"] = "success" if flattened and all(item.get("status") in ("success", "skipped") for item in flattened) else "failed"
    manifest_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    return str(manifest_path)


def _error_result(error: Exception | str) -> Dict[str, Any]:
    return {"status": "error", "records": 0, "error": str(error)}


def _skip_result(reason: str) -> Dict[str, Any]:
    return {"status": "skipped", "records": 0, "reason": reason}


# Midland's WAF blocks GitHub Actions' datacenter IP range (confirmed 403,
# reproducible from a residential IP) with no known bypass. Rather than
# attempting the fetch and relying on --tolerate-errors to absorb the
# failure, CI skips it outright and keeps the last committed snapshot;
# run this pipeline locally (this env var unset) to refresh Midland data.
SKIP_MIDLAND_ENV_VAR = "HK_RE_SKIP_MIDLAND"


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
    failures = {name: value for name, value in results.items() if value["status"] not in ("success", "skipped")}
    if failures and raise_on_failure:
        raise PipelineRunError(f"{group_name} ingestion failed; manifest: {manifest_path}", results, manifest_path)
    return results


def _record_many(run_id: str, results: Dict[str, Any], datasets: Mapping[str, pd.DataFrame]) -> None:
    for dataset_name, df in datasets.items():
        try:
            results[dataset_name] = _store_dataset(run_id, dataset_name, df)
        except Exception as exc:
            logger.exception("Failed to store %s", dataset_name)
            results[dataset_name] = _error_result(exc)


def run_group_a_pipeline(run_id: str | None = None, *, _raise_on_failure: bool = True) -> Dict[str, Any]:
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    if os.environ.get(SKIP_MIDLAND_ENV_VAR):
        logger.info("Skipping Midland Market Insight ingestion (%s set) — WAF blocks this environment's IP range.", SKIP_MIDLAND_ENV_VAR)
        for name in ("midland_mhpi_weekly", "midland_confidence_weekly", "midland_top_estates_volume"):
            results[name] = _skip_result(f"{SKIP_MIDLAND_ENV_VAR} set; run locally to refresh Midland data")
    else:
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


def run_stage_2_pipeline(run_id: str | None = None, *, _raise_on_failure: bool = False) -> Dict[str, Any]:
    """Run Stage 2: Credit Baseline & Project Stock Attribution."""
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    try:
        logger.info("Ingesting HKMA Residential Mortgage Survey (RMS) API...")
        _record_many(run_id, results, {"hkma_residential_mortgage_survey": fetch_hkma_residential_mortgage_survey()})
    except Exception as exc:
        logger.exception("HKMA RMS API ingestion failed")
        results["hkma_residential_mortgage_survey"] = _error_result(exc)
    try:
        logger.info("Ingesting BD Project Lifecycle Events (Tables 5.3-5.6) with Stock Attribution...")
        _record_many(run_id, results, {"bd_project_lifecycle_events": fetch_bd_project_lifecycle_events()})
    except Exception as exc:
        logger.exception("BD project-level ingestion failed")
        results["bd_project_lifecycle_events"] = _error_result(exc)
    return _finalize_group(run_id, "stage_2", results, _raise_on_failure)


def run_all_incomplete_pipelines(run_id: str | None = None, *, _raise_on_failure: bool = False) -> Dict[str, Any]:
    """Run digestion pipeline for all 5 incomplete HK Real Estate data sources."""
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    
    # 1. SRPE First-hand Sales Digest
    try:
        logger.info("Ingesting SRPE First-hand Sales Digest...")
        _record_many(run_id, results, {"srpe_firsthand_sales_digest": fetch_srpe_firsthand_sales_digest()})
    except Exception as exc:
        logger.exception("SRPE firsthand sales digest failed")
        results["srpe_firsthand_sales_digest"] = _error_result(exc)

    # 2. Land Registry Deed Facts
    try:
        logger.info("Ingesting Land Registry Deed Facts...")
        facts, series = fetch_landreg_monthly_statistics()
        _record_many(run_id, results, {"landreg_monthly_facts": facts, "landreg_asp_series": series})
    except Exception as exc:
        logger.exception("Land Registry deed facts failed")
        results["landreg_monthly_facts"] = _error_result(exc)

    # 3. Buildings Department Supply Leading Indicators
    try:
        logger.info("Ingesting BD Supply Leading Indicators...")
        _record_many(run_id, results, {"bd_supply_leading_indicators": fetch_bd_supply_leading_indicators()})
    except Exception as exc:
        logger.exception("BD supply leading indicators failed")
        results["bd_supply_leading_indicators"] = _error_result(exc)

    # 4. 28Hse EPI / ERI Weekly Indices
    try:
        logger.info("Ingesting 28Hse EPI / ERI weekly index history...")
        _record_many(run_id, results, {"hse28_epi_eri_weekly": fetch_28hse_epi_eri()})
    except Exception as exc:
        logger.exception("28Hse EPI / ERI ingestion failed")
        results["hse28_epi_eri_weekly"] = _error_result(exc)

    # 5. Unified Agency Transactions (Deduplicated)
    try:
        logger.info("Ingesting bounded agency transaction feeds & deduplicating...")
        hse28_tx = fetch_28hse_transaction_pilot()
        deduped_tx = deduplicate_agency_transactions([hse28_tx])
        _record_many(run_id, results, {"unified_agency_transactions_deduped": deduped_tx})
    except Exception as exc:
        logger.exception("Unified agency transaction dedup failed")
        results["unified_agency_transactions_deduped"] = _error_result(exc)

    return _finalize_group(run_id, "incomplete_5", results, _raise_on_failure)


def run_stage_1_pipeline(run_id: str | None = None, *, _raise_on_failure: bool = False) -> Dict[str, Any]:
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    try:
        logger.info("Ingesting 28Hse EPI / ERI history...")
        _record_many(run_id, results, {"hse28_epi_eri_weekly": fetch_28hse_epi_eri()})
    except Exception as exc:
        logger.exception("28Hse EPI / ERI ingestion failed")
        results["hse28_epi_eri_weekly"] = _error_result(exc)
    try:
        logger.info("Ingesting bounded 28Hse transaction pilot...")
        _record_many(run_id, results, {"hse28_transaction_pilot": fetch_28hse_transaction_pilot()})
    except Exception as exc:
        logger.exception("28Hse transaction pilot failed")
        results["hse28_transaction_pilot"] = _error_result(exc)
    try:
        logger.info("Ingesting Land Registry monthly facts...")
        facts, series = fetch_landreg_monthly_statistics()
        _record_many(run_id, results, {"landreg_monthly_facts": facts, "landreg_asp_series": series})
    except Exception as exc:
        logger.exception("Land Registry monthly ingestion failed")
        results["landreg_monthly_facts"] = _error_result(exc)
        results["landreg_asp_series"] = _error_result(exc)
    try:
        logger.info("Ingesting Buildings Department monthly tables...")
        _record_many(run_id, results, {"buildings_dept_monthly_stats": fetch_buildings_dept_monthly_stats()})
    except Exception as exc:
        logger.exception("Buildings Department monthly ingestion failed")
        results["buildings_dept_monthly_stats"] = _error_result(exc)
    return _finalize_group(run_id, "stage_1", results, _raise_on_failure)


def run_all_pipelines() -> Dict[str, Any]:
    run_id = str(uuid.uuid4())
    merged: Dict[str, Any] = {}
    for runner in (run_group_a_pipeline, run_group_b_pipeline, run_group_c_pipeline, run_stage_2_pipeline, run_all_incomplete_pipelines):
        merged.update(runner(run_id, _raise_on_failure=False))
    manifest_path = write_run_manifest(run_id, "all", merged)
    failures = {name: value for name, value in merged.items() if value["status"] not in ("success", "skipped")}
    if failures:
        raise PipelineRunError(f"Full ingestion failed; manifest: {manifest_path}", merged, manifest_path)
    return merged


if __name__ == "__main__":
    run_all_pipelines()
