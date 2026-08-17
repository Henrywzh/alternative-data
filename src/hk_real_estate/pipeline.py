"""Orchestration and data-quality gates for HK real-estate ingestion."""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping
from urllib.parse import unquote, urlparse

import pandas as pd

from .sources.midland import (
    build_midland_field_dictionary,
    run_midland_ingestion,
    run_midland_monthly_ingestion,
    run_midland_snapshot_ingestion,
)
from .sources.centaline import fetch_centaline_ccl, fetch_centaline_index_bundle
from .sources.hse28 import fetch_28hse_new_projects
from .sources.hse28 import fetch_28hse_transaction_pilot
from .sources.midland_transactions import fetch_midland_transaction_pilot
from .sources.centaline_transactions import fetch_centaline_transaction_pilot
from .sources.epi import fetch_28hse_epi_eri
from .sources.rvd import run_rvd_ingestion, fetch_rvd_office_rental_index, fetch_rvd_retail_rental_index
from .sources.commercial_controls import (
    fetch_cnsd_retail_sales_control,
    fetch_rvd_commercial_forecast_completions,
    fetch_rvd_commercial_stock_vacancy_district,
    fetch_rvd_office_stock_vacancy_district,
    fetch_rvd_office_vacancy_annual,
    fetch_tourism_hotel_adr_category,
    fetch_tourism_hotel_occupancy_category,
    fetch_tourism_hotel_rooms_category,
)
from .sources.landreg import fetch_landreg_monthly_sp, fetch_landreg_monthly_statistics
from .sources.srpe import fetch_srpe_project_documents, fetch_srpe_firsthand_sales_digest
from .sources.buildings_dept import fetch_buildings_dept_digests, fetch_buildings_dept_monthly_stats
from .sources.hkma import fetch_hkma_residential_mortgage_survey
from .sources.bd_projects import fetch_bd_project_lifecycle_events, fetch_bd_supply_leading_indicators
from .sources.bd_history import (
    fetch_bd_project_lifecycle_history,
    fetch_bd_project_lifecycle_history_audit,
    fetch_bd_supply_pipeline_history,
    reparse_bd_project_lifecycle_history_from_local_snapshots,
)
from .sources.policy_events import build_primary_policy_sources_catalog, validate_developer_project_registry
from .mapping.developer_registry import REGISTRY_CSV_PATH
from .dedup.transaction_dedup import deduplicate_agency_transactions
from .storage import NORMALIZED_DIR, load_latest_normalized, save_normalized_dataset, save_raw_snapshot
from .shkp_commercial import (
    build_shkp_commercial_asset_master,
    build_shkp_quarterly_events,
)
from .sources.shkp_quarterly import fetch_shkp_quarterly_numeric_facts
from .sources.shkp import fetch_shkp_corporate_documents, fetch_shkp_property_catalog


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hk_real_estate_pipeline")


def _select_landsd_consent_urls(
    document_urls: list[str] | tuple[str, ...],
    *,
    priority_districts: list[str] | tuple[str, ...] | None = None,
    max_urls: int = 5,
) -> list[str]:
    """Select a bounded, district-diverse LandsD consent PDF set.

    LandsD publishes both image-only PDFs and text-accessible ``wac_e``
    variants for many districts.  This helper keeps at most one document per
    district, prefers the accessible variant, and applies an explicit
    priority order.  It is only a fetch-budget selector; it does not infer a
    project, ownership, or coverage status from a missing district.
    """
    if max_urls < 0:
        raise ValueError("max_urls must be non-negative")
    urls = [str(url).strip() for url in document_urls if str(url).strip()]
    if not urls or max_urls == 0:
        return []

    aliases = {
        "ke": "kowloon east",
        "kowlooneast": "kowloon east",
        "kw": "kowloon west",
        "kowloonwest": "kowloon west",
        "he": "hong kong east",
        "hongeast": "hong kong east",
        "hw": "hong kong west",
        "hongkongwest": "hong kong west",
    }

    def district_key(url: str) -> str:
        filename = unquote(urlparse(url).path.rsplit("/", 1)[-1]).casefold()
        filename = re.sub(r"\[from\s*\d{4}\].*$", "", filename)
        filename = re.sub(r"\(pre\s*\d{4}\).*$", "", filename)
        filename = re.sub(r"wac_e\.pdf$|\.pdf$", "", filename)
        compact = re.sub(r"[^a-z0-9]+", "", filename)
        if compact in aliases:
            return aliases[compact]
        return re.sub(r"\s+", " ", re.sub(r"[_-]+", " ", filename)).strip()

    def is_accessible(url: str) -> bool:
        path = unquote(urlparse(url).path).casefold()
        return "/accessible/" in path or "wac_e" in path

    by_district: dict[str, list[str]] = {}
    for url in urls:
        key = district_key(url)
        by_district.setdefault(key, [])
        if url not in by_district[key]:
            by_district[key].append(url)
    for key, candidates in by_district.items():
        by_district[key] = sorted(
            candidates,
            key=lambda candidate: (not is_accessible(candidate), urls.index(candidate)),
        )

    ordered_keys: list[str] = []
    if priority_districts:
        for district in priority_districts:
            normalized = re.sub(r"\s+", " ", str(district).casefold().strip())
            normalized = aliases.get(re.sub(r"[^a-z0-9]+", "", normalized), normalized)
            if normalized in by_district and normalized not in ordered_keys:
                ordered_keys.append(normalized)
    if not priority_districts:
        for key in by_district:
            if key not in ordered_keys:
                ordered_keys.append(key)

    selected: list[str] = []
    for key in ordered_keys:
        if len(selected) >= max_urls:
            break
        candidates = by_district[key]
        if candidates:
            selected.append(candidates[0])
    return selected


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
    "centaline_cci_monthly": {"kind": "measure", "required": ["date", "series_id", "metric", "index_value"], "numeric": ["index_value"], "nonnegative": ["index_value"], "lineage_required": True, "max_age_days": 400},
    "centaline_cri_monthly": {"kind": "measure", "required": ["date", "series_id", "metric", "index_value"], "numeric": ["index_value"], "nonnegative": ["index_value"], "lineage_required": True, "max_age_days": 400},
    "centaline_cri_yield_monthly": {"kind": "measure", "required": ["date", "series_id", "metric", "index_value"], "numeric": ["index_value"], "nonnegative": ["index_value"], "lineage_required": True, "max_age_days": 400},
    "centaline_csi_weekly": {"kind": "measure", "required": ["date", "series_id", "metric", "index_value"], "numeric": ["index_value"], "nonnegative": ["index_value"], "bounds": {"index_value": (0, 100)}, "lineage_required": True, "max_age_days": 400},
    "centaline_index_current_snapshots": {"kind": "catalog", "required": ["date", "series_id", "metric", "index_value"], "numeric": ["index_value"], "nonnegative": ["index_value"], "lineage_required": True},
    "midland_mhpi_monthly": {"kind": "measure", "required": ["date", "mhpi_overall", "transaction_count_total"], "numeric": ["mhpi_overall", "transaction_count_total"], "nonnegative": ["mhpi_overall", "transaction_count_total"], "lineage_required": True, "max_age_days": 400},
    "midland_economic_indicators_monthly": {"kind": "measure", "required": ["date", "indicator_name", "value", "unit"], "numeric": ["value"], "lineage_required": True, "max_age_days": 400},
    "midland_field_dictionary": {"kind": "catalog", "required": ["dataset", "field_name", "metric_group", "unit", "source_field"], "lineage_required": True},
    "rvd_office_rental_index_monthly": {"kind": "measure", "required": ["date", "segment", "metric", "value", "is_provisional"], "numeric": ["value"], "nonnegative": ["value"], "lineage_required": True, "max_age_days": 400},
    "rvd_retail_index_monthly": {"kind": "measure", "required": ["date", "segment", "metric", "value", "is_provisional"], "numeric": ["value"], "nonnegative": ["value"], "lineage_required": True, "max_age_days": 400},
    "rvd_office_vacancy_annual": {"kind": "measure", "required": ["date", "segment", "metric", "value", "frequency"], "numeric": ["value"], "nonnegative": ["value"], "lineage_required": True, "max_age_days": 800},
    "rvd_office_stock_vacancy_district_annual": {"kind": "measure", "required": ["date", "district", "segment", "metric", "value", "frequency"], "numeric": ["value"], "nonnegative": ["value"], "lineage_required": True, "max_age_days": 800},
    "rvd_commercial_stock_vacancy_district_annual": {"kind": "measure", "required": ["date", "district", "segment", "metric", "value", "frequency"], "numeric": ["value"], "nonnegative": ["value"], "lineage_required": True, "max_age_days": 800},
    # Forecast completion rows legitimately carry future observation years;
    # keep them as a catalog/snapshot contract so the generic measure gate
    # does not reject a forecast for being ahead of today's date.
    "rvd_commercial_forecast_completions_annual": {"kind": "catalog", "required": ["date", "district", "segment", "metric", "value", "frequency"], "numeric": ["value"], "nonnegative": ["value"], "lineage_required": True},
    "cnsd_retail_sales_control_monthly": {"kind": "measure", "required": ["date", "category", "metric", "value", "is_provisional"], "numeric": ["value"], "nonnegative": ["value"], "lineage_required": True, "max_age_days": 400},
    "tourism_hotel_occupancy_category_monthly": {"kind": "measure", "required": ["date", "category", "metric", "value", "is_provisional"], "numeric": ["value"], "nonnegative": ["value"], "lineage_required": True, "max_age_days": 400},
    "tourism_hotel_adr_category_monthly": {"kind": "measure", "required": ["date", "category", "metric", "value", "is_provisional"], "numeric": ["value"], "nonnegative": ["value"], "lineage_required": True, "max_age_days": 400},
    # The public room-supply file can lag the occupancy/ADR files by several
    # releases.  Keep the returned vintage as an explicit catalog snapshot
    # rather than rejecting it as a fabricated current measure.
    "tourism_hotel_rooms_category_monthly": {"kind": "catalog", "required": ["date", "category", "metric", "value", "is_provisional"], "numeric": ["value"], "nonnegative": ["value"], "lineage_required": True},
    "shkp_quarterly_events": {"kind": "catalog", "required": ["event_id", "event_date", "title", "event_type", "property_relevance"], "lineage_required": True},
    "shkp_quarterly_numeric_facts": {"kind": "catalog", "required": ["fact_id", "event_id", "fact_type", "value", "unit", "source_url"], "numeric": ["value"], "nonnegative": ["value"], "lineage_required": True},
    "shkp_commercial_asset_master": {"kind": "catalog", "required": ["asset_id", "canonical_name", "source_layer", "status"], "lineage_required": True},
    "midland_market_snapshots": {"kind": "measure", "required": ["date", "scope_type", "scope_id", "period_type", "metric", "value", "unit"], "numeric": ["value"], "nonnegative": ["value"], "lineage_required": True, "max_age_days": 400},
    "midland_transaction_summary_snapshot": {"kind": "catalog", "required": ["date", "as_of_date", "asset_class", "metric", "value", "unit"], "numeric": ["value"], "lineage_required": True},
    "midland_property_event_hints": {"kind": "catalog", "required": ["event_date", "event_id", "description", "status"], "lineage_required": True},
    "primary_policy_sources_catalog": {"kind": "catalog", "required": ["source_id", "source_agency", "source_url", "status"], "lineage_required": True},
    "developer_project_registry_audit": {"kind": "catalog", "required": ["registry_path", "registry_rows", "registry_errors", "status"], "lineage_required": True},
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
    "landreg_monthly_facts": {"kind": "measure", "required": ["date", "statistic_name", "units", "comparison_type"], "max_age_days": 400},
    "landreg_asp_series": {"kind": "measure", "required": ["date", "all_building_units_asp", "residential_units_asp"], "max_age_days": 400},
    "buildings_dept_monthly_stats": {"kind": "catalog", "required": ["date", "table_id", "numeric_values"]},
    "bd_supply_leading_indicators": {"kind": "measure", "required": ["date", "permit_stage", "region"], "max_age_days": 400},
    # A historical backfill may intentionally be stored in bounded year
    # chunks.  It still has a dated observation contract, but a partial
    # archival batch must not be rejected merely because its final month is
    # older than the current date.
    "bd_supply_pipeline_history": {"kind": "catalog", "required": ["date", "permit_stage", "property_category", "revision_status", "parser_confidence"]},
    "bd_project_lifecycle_history": {"kind": "catalog", "required": ["digest_month", "observation_month", "permit_stage", "site_address", "parser_confidence", "source_url"], "lineage_required": True},
    "bd_project_lifecycle_history_audit": {"kind": "catalog", "required": ["observation_month", "permit_stage", "reconciliation_status", "detail_row_count", "summary_row_count"], "lineage_required": True},
    "shkp_bd_history_crosswalk": {
        "kind": "catalog",
        "required": ["bd_match_method", "bd_match_status", "project_identity_status", "ownership_promotion_status"],
        "lineage_required": True,
    },
    "shkp_phase_role_evidence": {
        "kind": "catalog",
        "required": [
            "evidence_id",
            "srpe_development_id",
            "phase_label",
            "role_scope",
            "source_url",
            "promotion_status",
        ],
    },
    "shkp_indicative_ownership_roster": {
        "kind": "catalog",
        "required": [
            "registry_key",
            "srpe_development_id",
            "indicative_owner_status",
            "indicative_numeric_consistency_status",
            "strict_ownership_attribution_ready",
        ],
        "lineage_required": True,
    },
    "shkp_bd_phase_group_evidence": {
        "kind": "catalog",
        "required": [
            "phase_group_id",
            "group_resolution_status",
            "srpe_phase_ids",
            "bd_permit_numbers",
            "ownership_promotion_status",
            "permit_attribution_status",
            "research_only",
        ],
        "lineage_required": True,
    },
    "shkp_bd_phase_permit_candidate_evidence": {
        "kind": "catalog",
        "required": [
            "phase_group_id",
            "candidate_context_key",
            "candidate_phase_count",
            "bd_pdf_token_coverage_status",
            "phase_context_review_status",
            "indicative_ownership_context_status",
            "indicative_ownership_role_alignment_status",
            "resolution_status",
            "resolution_priority",
            "ownership_promotion_status",
            "permit_attribution_status",
            "research_only",
        ],
        "numeric": ["candidate_phase_count", "bd_history_row_count", "schedule_candidate_count"],
        "nonnegative": ["candidate_phase_count", "bd_history_row_count", "schedule_candidate_count"],
        "lineage_required": True,
    },
    # Address-only SHKP/BD entity review remains a research queue.  The
    # required fields are decision-status fields that are non-null even for
    # unmatched or malformed candidate rows; nullable dates and identifiers
    # are intentionally excluded from the generic gate.
    "shkp_bd_history_entity_resolution_review_queue": {
        "kind": "catalog",
        "required": [
            "entity_resolution_status",
            "review_priority",
            "ownership_promotion_status",
            "permit_attribution_status",
            "research_only",
        ],
        "lineage_required": True,
    },
    "shkp_bd_phase_permit_reconciliation": {
        "kind": "catalog",
        "required": [
            "reconciliation_id",
            "phase_group_id",
            "candidate_context_key",
            "bd_pdf_token_coverage_status",
            "phase_context_review_status",
            "indicative_ownership_context_status",
            "indicative_ownership_role_alignment_status",
            "reconciliation_status",
            "permit_assignment_status",
            "ownership_promotion_status",
            "permit_attribution_status",
            "research_only",
        ],
        "lineage_required": True,
    },
    "shkp_bd_phase_ownership_review": {
        "kind": "catalog",
        "required": [
            "srpe_development_id",
            "phase_context_review_status",
            "indicative_ownership_context_status",
            "ownership_review_status",
            "ownership_promotion_status",
            "permit_attribution_status",
            "research_only",
        ],
        "numeric": [
            "bd_candidate_row_count",
            "bd_history_row_count",
            "bd_distinct_permit_number_count",
            "phase_context_supported_row_count",
            "phase_context_other_group_row_count",
            "phase_context_same_family_variant_row_count",
            "phase_context_unresolved_row_count",
            "phase_role_evidence_count",
            "indicative_evidence_source_count",
        ],
        "nonnegative": [
            "bd_candidate_row_count",
            "bd_history_row_count",
            "bd_distinct_permit_number_count",
            "phase_context_supported_row_count",
            "phase_context_other_group_row_count",
            "phase_context_same_family_variant_row_count",
            "phase_context_unresolved_row_count",
            "phase_role_evidence_count",
            "indicative_evidence_source_count",
        ],
        "lineage_required": True,
    },
    "shkp_bd_history_entity_resolution_summary": {
        "kind": "catalog",
        "required": [
            "candidate_phase_count",
            "ownership_promotion_status",
            "permit_attribution_status",
            "research_only",
        ],
        "numeric": ["candidate_phase_count"],
        "nonnegative": ["candidate_phase_count"],
        "lineage_required": True,
    },
    "shkp_bd_phase_resolution_candidates": {
        "kind": "catalog",
        "required": [
            "phase_resolution_status",
            "phase_resolution_priority",
            "permit_identity_status",
            "ownership_promotion_status",
            "permit_attribution_status",
            "research_only",
        ],
        "lineage_required": True,
    },
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
    blank_columns = [
        column
        for column in spec["required"]
        if df[column].astype("string").str.strip().eq("").any()
    ]
    if blank_columns:
        return [f"required columns contain blank values: {', '.join(blank_columns)}"]

    for column in spec.get("numeric", []):
        values = pd.to_numeric(df[column], errors="coerce")
        if values.isna().any():
            return [f"{column} contains non-numeric values"]
    for column in spec.get("nonnegative", []):
        values = pd.to_numeric(df[column], errors="coerce")
        # Change-rate rows are signed by definition.  For long-form tables,
        # apply the non-negative gate only to level metrics.
        if column == "value" and "metric" in df.columns:
            level_mask = ~df["metric"].astype("string").str.endswith("_chg")
            values = values[level_mask]
        if (values < 0).any():
            return [f"{column} contains negative values"]
    for column, (lower, upper) in spec.get("bounds", {}).items():
        values = pd.to_numeric(df[column], errors="coerce")
        if ((values < lower) | (values > upper)).any():
            return [f"{column} is outside the allowed range [{lower}, {upper}]"]

    if spec["kind"] == "measure":
        date_col = next(
            (candidate for candidate in ("observation_date", "as_of_date", "date") if candidate in df.columns),
            "date",
        )
        dates = pd.to_datetime(df[date_col], errors="coerce", utc=True)
        if dates.isna().any():
            return [f"{date_col} contains invalid values"]
        duplicate_key = [date_col]
        for candidate in ("index_type", "series_id", "metric", "indicator_name", "segment", "category", "district", "geography", "scope_type", "scope_id", "period_type", "asset_class", "as_of_date", "statistic_name", "table_id", "source_record_id", "dedup_transaction_id", "permit_stage", "region", "property_category", "comparison_type", "revision_status", "source_url"):
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


# Midland is refreshed by a separate, independently-scheduled weekly
# automation outside this repo's CI, so this pipeline's own CI runs skip it
# outright rather than attempting a redundant fetch. This also happens to
# route around a real WAF block on GitHub Actions' datacenter IP range
# (confirmed 403, reproducible from a residential IP), but that's no longer
# the primary reason to skip it.
SKIP_MIDLAND_ENV_VAR = "HK_RE_SKIP_MIDLAND"


def _store_dataset(run_id: str, dataset_name: str, df: pd.DataFrame) -> Dict[str, Any]:
    errors = _quality_errors(dataset_name, df)
    if errors:
        status = "empty" if df.empty else "invalid"
        return {"status": status, "records": len(df), "errors": errors}
    spec = QUALITY_SPECS[dataset_name]
    raw_snapshot = df.attrs.get("raw_snapshot")
    raw_snapshots = df.attrs.get("raw_snapshots")
    source_url = df.attrs.get("source_url")
    source_urls = df.attrs.get("source_urls")
    if spec.get("lineage_required") and not (raw_snapshot or raw_snapshots):
        return {"status": "invalid", "records": len(df), "errors": ["missing raw snapshot lineage"]}
    if spec.get("lineage_required") and not (source_url or source_urls):
        return {"status": "invalid", "records": len(df), "errors": ["missing source URL lineage"]}
    stored = save_normalized_dataset(
        dataset_name,
        df,
        run_id=run_id,
        raw_snapshot=raw_snapshot,
        source_url=source_url,
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        lineage_metadata=df.attrs.get("lineage_metadata"),
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


def _ingest_centaline_index_families(run_id: str, results: Dict[str, Any]) -> None:
    """Ingest the contract-gated CCI/CRI/CSI families as one tranche."""
    centaline_snapshots: list[pd.DataFrame] = []
    for index_code, history_dataset, yield_dataset in (
        ("CCI", "centaline_cci_monthly", None),
        ("CRI", "centaline_cri_monthly", "centaline_cri_yield_monthly"),
        ("CSI", "centaline_csi_weekly", None),
    ):
        try:
            logger.info("Ingesting Centaline %s index family...", index_code)
            history, snapshots = fetch_centaline_index_bundle(index_code)
            if index_code == "CRI":
                _record_many(
                    run_id,
                    results,
                    {
                        history_dataset: history[history["metric"].eq("rental_index")].copy(),
                        yield_dataset: history[history["metric"].eq("rental_yield")].copy(),
                    },
                )
            else:
                _record_many(run_id, results, {history_dataset: history})
            centaline_snapshots.append(snapshots)
        except Exception as exc:
            logger.exception("Centaline %s ingestion failed", index_code)
            results[history_dataset] = _error_result(exc)
            if yield_dataset:
                results[yield_dataset] = _error_result(exc)
    if centaline_snapshots:
        combined_snapshots = pd.concat(centaline_snapshots, ignore_index=True)
        raw_snapshots = [
            frame.attrs["raw_snapshot"]
            for frame in centaline_snapshots
            if frame.attrs.get("raw_snapshot")
        ]
        source_urls = [
            frame.attrs["source_url"]
            for frame in centaline_snapshots
            if frame.attrs.get("source_url")
        ]
        # A combined dataset has multiple parents.  Keep an explicit array in
        # lineage instead of serializing it into the scalar URL field.
        combined_snapshots.attrs["raw_snapshots"] = raw_snapshots
        combined_snapshots.attrs["source_urls"] = source_urls
        combined_snapshots.attrs["lineage_metadata"] = {"lineage_type": "combined_snapshot"}
        _record_many(
            run_id,
            results,
            {"centaline_index_current_snapshots": combined_snapshots},
        )
    else:
        results["centaline_index_current_snapshots"] = _error_result("all Centaline index families failed")


def run_centaline_indices_pipeline(run_id: str | None = None, *, _raise_on_failure: bool = True) -> Dict[str, Any]:
    """Run Tranche 1 only: CCI, CRI/CRI yield and CSI plus current snapshots."""
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    _ingest_centaline_index_families(run_id, results)
    return _finalize_group(run_id, "tranche_1_centaline", results, _raise_on_failure)


def run_midland_monthly_pipeline(run_id: str | None = None, *, _raise_on_failure: bool = True) -> Dict[str, Any]:
    """Run Tranche 2 only: Midland monthly price-volume and macro indicators."""
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    try:
        logger.info("Ingesting Midland monthly price-volume and economic indicators...")
        monthly, indicators = run_midland_monthly_ingestion()
        field_dictionary = build_midland_field_dictionary()
        field_dictionary.attrs.update(
            raw_snapshot=monthly.attrs.get("raw_snapshot"),
            source_url=monthly.attrs.get("source_url"),
            lineage_metadata={"lineage_type": "source_field_dictionary"},
        )
        _record_many(
            run_id,
            results,
            {
                "midland_mhpi_monthly": monthly,
                "midland_economic_indicators_monthly": indicators,
                "midland_field_dictionary": field_dictionary,
            },
        )
    except Exception as exc:
        logger.exception("Midland monthly ingestion failed")
        results["midland_mhpi_monthly"] = _error_result(exc)
        results["midland_economic_indicators_monthly"] = _error_result(exc)
        results["midland_field_dictionary"] = _error_result(exc)
    return _finalize_group(run_id, "tranche_2_midland_monthly", results, _raise_on_failure)


def run_rvd_commercial_pipeline(run_id: str | None = None, *, _raise_on_failure: bool = True) -> Dict[str, Any]:
    """Run Tranche 3 only: official RVD office and retail series."""
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    try:
        logger.info("Ingesting RVD commercial rental/index files...")
        _record_many(
            run_id,
            results,
            {
                "rvd_office_rental_index_monthly": fetch_rvd_office_rental_index(),
                "rvd_retail_index_monthly": fetch_rvd_retail_rental_index(),
            },
        )
    except Exception as exc:
        logger.exception("RVD commercial ingestion failed")
        results["rvd_office_rental_index_monthly"] = _error_result(exc)
        results["rvd_retail_index_monthly"] = _error_result(exc)
    return _finalize_group(run_id, "tranche_3_rvd_commercial", results, _raise_on_failure)


def run_hk_commercial_controls_pipeline(run_id: str | None = None, *, _raise_on_failure: bool = True) -> Dict[str, Any]:
    """Refresh SHKP Quarterly events and free HK commercial control layers.

    This tranche is intentionally separate from the Mainland project work and
    from the existing residential index tranches.  Each source is recorded
    independently so a tourism or C&SD outage cannot erase the last valid RVD
    or issuer-event snapshot.
    """
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}

    # Derived SHKP issuer layers.  Prefer the durable catalog snapshots; a
    # fresh fetch is only used when the local source contract is absent.
    try:
        corporate = load_latest_normalized("shkp_corporate_documents")
        if corporate.empty:
            corporate = fetch_shkp_corporate_documents(timeout=60)
        catalog = load_latest_normalized("shkp_property_catalog")
        if catalog.empty:
            catalog = fetch_shkp_property_catalog(timeout=60, max_pages=None)
        events = build_shkp_quarterly_events(corporate, property_catalog=catalog)
        events.attrs["raw_snapshots"] = list(dict.fromkeys(
            [str(value) for value in corporate.attrs.get("raw_snapshots", []) if value]
            + [str(value) for value in catalog.attrs.get("raw_snapshots", []) if value]
        ))
        events.attrs["source_urls"] = list(dict.fromkeys(
            [str(value) for value in corporate.attrs.get("source_urls", []) if value]
            + [str(value) for value in catalog.attrs.get("source_urls", []) if value]
            + ["https://www.shkp.com/en-US/investor-relations/shkp-quarterly"]
        ))
        _record_many(run_id, results, {"shkp_quarterly_events": events})
        try:
            facts = fetch_shkp_quarterly_numeric_facts(
                corporate_documents=corporate,
                quarterly_events=events,
                max_documents=24,
            )
            facts.attrs["raw_snapshots"] = list(dict.fromkeys(
                [str(value) for value in facts.attrs.get("raw_snapshots", []) if value]
                + [str(value) for value in corporate.attrs.get("raw_snapshots", []) if value]
            ))
            facts.attrs["source_urls"] = list(dict.fromkeys(
                [str(value) for value in facts.attrs.get("source_urls", []) if value]
                + [str(value) for value in corporate.attrs.get("source_urls", []) if value]
                + ["https://www.shkp.com/en-US/investor-relations/shkp-quarterly"]
            ))
            _record_many(run_id, results, {"shkp_quarterly_numeric_facts": facts})
        except Exception as exc:
            logger.exception("SHKP Quarterly numeric fact layer failed")
            results["shkp_quarterly_numeric_facts"] = _error_result(exc)
    except Exception as exc:
        logger.exception("SHKP Quarterly event layer failed")
        results["shkp_quarterly_events"] = _error_result(exc)
        results["shkp_quarterly_numeric_facts"] = _error_result(exc)

    try:
        catalog = load_latest_normalized("shkp_property_catalog")
        if catalog.empty:
            catalog = fetch_shkp_property_catalog(timeout=60, max_pages=None)
        completed = load_latest_normalized("shkp_completed_properties")
        completion = load_latest_normalized("shkp_completion_schedule_projects")
        assets = build_shkp_commercial_asset_master(
            property_catalog=catalog,
            completed_properties=completed,
            completion_schedule=completion,
        )
        assets.attrs["raw_snapshots"] = list(dict.fromkeys(
            [str(value) for frame in (catalog, completed, completion) for value in frame.attrs.get("raw_snapshots", []) if value]
        ))
        assets.attrs["source_urls"] = list(dict.fromkeys(
            [str(value) for frame in (catalog, completed, completion) for value in frame.attrs.get("source_urls", []) if value]
            + ["https://www.shkp.com/en-US/our-business/hong-kong-properties", "https://www.shkp.com/en-US/investor-relations"]
        ))
        _record_many(run_id, results, {"shkp_commercial_asset_master": assets})
    except Exception as exc:
        logger.exception("SHKP commercial asset master failed")
        results["shkp_commercial_asset_master"] = _error_result(exc)

    source_fetchers = {
        "rvd_office_vacancy_annual": fetch_rvd_office_vacancy_annual,
        "rvd_office_stock_vacancy_district_annual": fetch_rvd_office_stock_vacancy_district,
        "rvd_commercial_stock_vacancy_district_annual": fetch_rvd_commercial_stock_vacancy_district,
        "rvd_commercial_forecast_completions_annual": fetch_rvd_commercial_forecast_completions,
        "cnsd_retail_sales_control_monthly": fetch_cnsd_retail_sales_control,
        "tourism_hotel_occupancy_category_monthly": fetch_tourism_hotel_occupancy_category,
        "tourism_hotel_adr_category_monthly": fetch_tourism_hotel_adr_category,
        "tourism_hotel_rooms_category_monthly": fetch_tourism_hotel_rooms_category,
    }
    for dataset_name, fetcher in source_fetchers.items():
        try:
            _record_many(run_id, results, {dataset_name: fetcher()})
        except Exception as exc:
            logger.exception("Commercial control source failed: %s", dataset_name)
            results[dataset_name] = _error_result(exc)
    return _finalize_group(run_id, "hk_commercial_controls", results, _raise_on_failure)


def run_midland_snapshot_pipeline(run_id: str | None = None, *, _raise_on_failure: bool = True) -> Dict[str, Any]:
    """Run Tranche 4 only: current rolling market and registration snapshots."""
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    try:
        logger.info("Ingesting Midland market and transaction snapshots...")
        market, transactions, event_hints = run_midland_snapshot_ingestion()
        _record_many(
            run_id,
            results,
            {
                "midland_market_snapshots": market,
                "midland_transaction_summary_snapshot": transactions,
                "midland_property_event_hints": event_hints,
            },
        )
    except Exception as exc:
        logger.exception("Midland snapshot ingestion failed")
        results["midland_market_snapshots"] = _error_result(exc)
        results["midland_transaction_summary_snapshot"] = _error_result(exc)
        results["midland_property_event_hints"] = _error_result(exc)
    return _finalize_group(run_id, "tranche_4_midland_snapshots", results, _raise_on_failure)


def run_policy_event_research_pipeline(run_id: str | None = None, *, _raise_on_failure: bool = True) -> Dict[str, Any]:
    """Run Tranche 5 research contracts without promoting broker events."""
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    try:
        registry_bytes = REGISTRY_CSV_PATH.read_bytes()
        registry_raw = save_raw_snapshot(
            "developer_project_registry",
            registry_bytes,
            file_ext="csv",
            source_url=str(REGISTRY_CSV_PATH),
            run_id=run_id,
        )
        registry = pd.read_csv(REGISTRY_CSV_PATH, dtype=str)
        _, errors = validate_developer_project_registry(registry)
        audit = pd.DataFrame(
            [
                {
                    "registry_path": str(REGISTRY_CSV_PATH),
                    "registry_rows": int(len(registry)),
                    "registry_errors": "; ".join(errors) if errors else "none",
                    "status": "validated" if not errors else "invalid",
                }
            ]
        )
        catalog = build_primary_policy_sources_catalog()
        catalog_raw = save_raw_snapshot(
            "primary_policy_sources_catalog",
            catalog.to_json(orient="records", force_ascii=False),
            file_ext="json",
            source_url="static://primary-policy-sources-catalog",
            run_id=run_id,
        )
        catalog.attrs.update(
            raw_snapshot=str(catalog_raw),
            source_url="static://primary-policy-sources-catalog",
            raw_snapshots=[str(catalog_raw)],
            source_urls=catalog["source_url"].dropna().drop_duplicates().tolist(),
            lineage_metadata={"lineage_type": "static_catalog"},
        )
        audit.attrs.update(
            raw_snapshot=str(registry_raw),
            source_url=str(REGISTRY_CSV_PATH),
            raw_snapshots=[str(registry_raw)],
            source_urls=[str(REGISTRY_CSV_PATH)],
            lineage_metadata={"lineage_type": "local_registry_audit"},
        )
        _record_many(run_id, results, {
            "primary_policy_sources_catalog": catalog,
            "developer_project_registry_audit": audit,
        })
    except Exception as exc:
        logger.exception("Policy/event research contract failed")
        results["primary_policy_sources_catalog"] = _error_result(exc)
        results["developer_project_registry_audit"] = _error_result(exc)
    return _finalize_group(run_id, "tranche_5_policy_event_research", results, _raise_on_failure)


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
    _ingest_centaline_index_families(run_id, results)
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


def run_bd_history_backfill(
    run_id: str | None = None,
    *,
    start_year: int = 2005,
    end_year: int | None = None,
    _raise_on_failure: bool = True,
) -> Dict[str, Any]:
    """Run the explicit, archive-backed Md52--Md56 history backfill.

    This runner is deliberately separate from routine ingestion because the
    official PDF archive is large and historical parsing is not a daily feed.
    """
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    try:
        logger.info("Backfilling Buildings Department Md52--Md56 history (%s-%s)...", start_year, end_year or "latest")
        _record_many(
            run_id,
            results,
            {"bd_supply_pipeline_history": fetch_bd_supply_pipeline_history(start_year=start_year, end_year=end_year)},
        )
    except Exception as exc:
        logger.exception("Buildings Department historical backfill failed")
        results["bd_supply_pipeline_history"] = _error_result(exc)
    return _finalize_group(run_id, "bd_history_backfill", results, _raise_on_failure)


def run_bd_project_history_backfill(
    run_id: str | None = None,
    *,
    start_year: int = 2005,
    end_year: int | None = None,
    months: list[int] | tuple[int, ...] | None = None,
    _raise_on_failure: bool = True,
) -> Dict[str, Any]:
    """Run the explicit detailed Md52--Md56 project-history backfill.

    This is separate from the stable Section-1 aggregate backfill because the
    detailed PDF layout is more fragile and should be expanded only after a
    bounded year/month QA sample passes.
    """
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    try:
        logger.info(
            "Backfilling detailed Buildings Department Md52--Md56 project history (%s-%s; months=%s)...",
            start_year,
            end_year or "latest",
            months or "all",
        )
        _record_many(
            run_id,
            results,
            {
                "bd_project_lifecycle_history": fetch_bd_project_lifecycle_history(
                    start_year=start_year,
                    end_year=end_year,
                    months=months,
                )
            },
        )
    except Exception as exc:
        logger.exception("Buildings Department detailed project history failed")
        results["bd_project_lifecycle_history"] = _error_result(exc)
    return _finalize_group(run_id, "bd_project_history_backfill", results, _raise_on_failure)


def run_bd_project_history_local_reparse(
    run_id: str | None = None,
    *,
    _raise_on_failure: bool = True,
) -> Dict[str, Any]:
    """Reparse the latest BD detail history from existing local raw PDFs.

    This is the safe follow-up to a parser correction: it does not download
    the official archive again and refuses to persist a partial replacement if
    any referenced raw snapshot is missing or unreadable.
    """
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    try:
        previous = load_latest_normalized("bd_project_lifecycle_history")
        if previous.empty:
            raise RuntimeError("bd_project_lifecycle_history is required and must contain rows")
        reparsed = reparse_bd_project_lifecycle_history_from_local_snapshots(previous, strict=True)
        _record_many(run_id, results, {"bd_project_lifecycle_history": reparsed})
    except Exception as exc:
        logger.exception("Buildings Department local detail reparse failed")
        results["bd_project_lifecycle_history"] = _error_result(exc)
    return _finalize_group(run_id, "bd_project_history_local_reparse", results, _raise_on_failure)


def run_bd_project_history_audit_backfill(
    run_id: str | None = None,
    *,
    start_year: int = 2005,
    end_year: int | None = None,
    _raise_on_failure: bool = True,
) -> Dict[str, Any]:
    """Persist the bounded detailed-vs-summary Buildings Department audit."""
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    try:
        logger.info(
            "Auditing detailed Buildings Department Md52--Md56 rows against Section 1 aggregates (%s-%s)...",
            start_year,
            end_year or "latest",
        )
        _record_many(
            run_id,
            results,
            {
                "bd_project_lifecycle_history_audit": fetch_bd_project_lifecycle_history_audit(
                    start_year=start_year,
                    end_year=end_year,
                )
            },
        )
    except Exception as exc:
        logger.exception("Buildings Department detailed project history audit failed")
        results["bd_project_lifecycle_history_audit"] = _error_result(exc)
    return _finalize_group(run_id, "bd_project_history_audit", results, _raise_on_failure)


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
    # Feeds all three agencies that publish a genuine per-transaction record
    # (estate/floor/unit/price/date), not just an index -- 28Hse, Midland
    # (data.midland.com.hk/info/v1/transactions/buildings), and Centaline
    # (findproperty/api/Transaction/Search). Each source is fetched
    # independently so one agency's failure doesn't blank out the others;
    # the dedup pass still runs (and is genuinely exercised across
    # multiple sources) on whichever feeds succeeded.
    try:
        logger.info("Ingesting bounded agency transaction feeds & deduplicating...")
        agency_transaction_frames = []
        try:
            agency_transaction_frames.append(fetch_28hse_transaction_pilot())
        except Exception:
            logger.exception("28Hse transaction feed failed (dedup will proceed without it)")
        try:
            agency_transaction_frames.append(fetch_midland_transaction_pilot())
        except Exception:
            logger.exception("Midland transaction feed failed (dedup will proceed without it)")
        try:
            agency_transaction_frames.append(fetch_centaline_transaction_pilot())
        except Exception:
            logger.exception("Centaline transaction feed failed (dedup will proceed without it)")
        deduped_tx = deduplicate_agency_transactions(agency_transaction_frames)
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
    runners = (
        run_group_a_pipeline,
        run_group_b_pipeline,
        run_group_c_pipeline,
        run_stage_2_pipeline,
        run_all_incomplete_pipelines,
        run_midland_monthly_pipeline,
        run_rvd_commercial_pipeline,
        run_hk_commercial_controls_pipeline,
        run_midland_snapshot_pipeline,
        run_policy_event_research_pipeline,
    )
    midland_skips = {
        run_midland_monthly_pipeline: (
            "tranche_2_midland_monthly",
            ("midland_mhpi_monthly", "midland_economic_indicators_monthly", "midland_field_dictionary"),
        ),
        run_midland_snapshot_pipeline: (
            "tranche_4_midland_snapshots",
            ("midland_market_snapshots", "midland_transaction_summary_snapshot", "midland_property_event_hints"),
        ),
    }
    for runner in runners:
        if os.environ.get(SKIP_MIDLAND_ENV_VAR) and runner in midland_skips:
            group_name, dataset_names = midland_skips[runner]
            skipped = {
                name: _skip_result(f"{SKIP_MIDLAND_ENV_VAR} set; run locally to refresh Midland data")
                for name in dataset_names
            }
            write_run_manifest(run_id, group_name, skipped)
            merged.update(skipped)
            continue
        merged.update(runner(run_id, _raise_on_failure=False))
    manifest_path = write_run_manifest(run_id, "all", merged)
    failures = {name: value for name, value in merged.items() if value["status"] not in ("success", "skipped")}
    if failures:
        raise PipelineRunError(f"Full ingestion failed; manifest: {manifest_path}", merged, manifest_path)
    return merged


if __name__ == "__main__":
    run_all_pipelines()
