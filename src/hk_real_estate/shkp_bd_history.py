"""Research-only SHKP/SRPE to historical Buildings Department crosswalk.

The input project rows are official BD monthly-digest observations.  The join
is intentionally address-only (exact/contains after conservative
normalization), so a hit is evidence that an SRPE phase and a BD row share a
site address; it is not a legal ownership or phase-to-permit attribution.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import pdfplumber

from .sources.shkp import _normalized_address
from .storage import load_latest_normalized, save_normalized_dataset


DATASET_NAME = "shkp_bd_history_crosswalk"
ENTITY_RESOLUTION_REVIEW_QUEUE_DATASET = "shkp_bd_history_entity_resolution_review_queue"
ENTITY_RESOLUTION_REVIEW_SUMMARY_DATASET = "shkp_bd_history_entity_resolution_summary"
PHASE_RESOLUTION_CANDIDATE_DATASET = "shkp_bd_phase_resolution_candidates"
PHASE_GROUP_EVIDENCE_DATASET = "shkp_bd_phase_group_evidence"
PHASE_PERMIT_CANDIDATE_EVIDENCE_DATASET = "shkp_bd_phase_permit_candidate_evidence"
PHASE_PERMIT_RECONCILIATION_DATASET = "shkp_bd_phase_permit_reconciliation"
PHASE_OWNERSHIP_REVIEW_DATASET = "shkp_bd_phase_ownership_review"
CROSSWALK_COLUMNS = [
    "srpe_development_id",
    "marketing_name",
    "srpe_phase_name",
    "srpe_address_en",
    "crosswalk_match_status",
    "digest_month",
    "observation_month",
    "revision_status",
    "bd_permit_stage",
    "bd_permit_number",
    "bd_site_address",
    "bd_domestic_units_count",
    "bd_usable_floor_area_sqm",
    "bd_applicant",
    "bd_parser_confidence",
    "bd_parser_quality_flag",
    "bd_source_pdf_page",
    "bd_match_method",
    "bd_match_status",
    "bd_candidate_count",
    "bd_phase_candidate_count",
    "project_identity_status",
    "ownership_promotion_status",
    "shkp_source_url",
    "srpe_source_url",
    "bd_source_url",
    "matched_at",
]

ENTITY_RESOLUTION_REVIEW_QUEUE_COLUMNS = [
    "srpe_development_id",
    "marketing_name",
    "srpe_phase_name",
    "srpe_address_en",
    "crosswalk_match_status",
    "developer_identity_status",
    "developer_identity_action",
    "shkp_site_match_status",
    "shkp_site_probe_match_status",
    "shkp_corporate_role_evidence_status",
    "shkp_site_fetch_status",
    "shkp_site_vendor",
    "shkp_site_holding_companies",
    "shkp_site_sales_agent",
    "shkp_site_url",
    "entity_resolution_status",
    "review_priority",
    "review_queue_rank",
    "entity_resolution_action",
    "project_identity_status",
    "ownership_promotion_status",
    "permit_attribution_status",
    "review_scope",
    "bd_match_methods",
    "bd_history_row_count",
    "bd_candidate_count",
    "bd_phase_candidate_count",
    "bd_distinct_permit_number_count",
    "bd_permit_stages",
    "bd_permit_numbers",
    "bd_site_addresses",
    "bd_digest_month_first_observed",
    "bd_digest_month_last_observed",
    "bd_parser_confidences",
    "bd_parser_quality_flags",
    "bd_source_urls",
    "phase_group_id",
    "phase_group_member_count",
    "phase_group_member_ids",
    "phase_group_resolution_status",
    "phase_group_evidence_status",
    "phase_group_permit_years",
    "phase_group_phase_order_context_json",
    "official_schedule_evidence_status",
    "schedule_phase_group_sets",
    "schedule_group_context_json",
    "research_only",
    "review_caveat",
]

ENTITY_RESOLUTION_REVIEW_SUMMARY_COLUMNS = [
    "candidate_phase_count",
    "phase_with_bd_address_hit_count",
    "ambiguous_phase_count",
    "matched_needs_review_phase_count",
    "unmatched_phase_count",
    "site_evidence_phase_count",
    "corporate_role_evidence_phase_count",
    "site_named_shkp_phase_count",
    "page_named_shkp_phase_count",
    "site_no_shkp_keyword_phase_count",
    "site_not_evaluated_phase_count",
    "matched_bd_history_row_count",
    "distinct_bd_permit_number_count",
    "blocked_address_only_phase_count",
    "research_only",
    "ownership_promotion_status",
    "permit_attribution_status",
    "summary_caveat",
]

PHASE_RESOLUTION_CANDIDATE_COLUMNS = [
    "srpe_development_id",
    "marketing_name",
    "srpe_phase_name",
    "srpe_address_en",
    "crosswalk_match_status",
    "developer_identity_status",
    "shkp_site_match_status",
    "shkp_site_probe_match_status",
    "shkp_corporate_role_evidence_status",
    "shkp_site_url",
    "shkp_site_vendor",
    "shkp_site_holding_companies",
    "shkp_site_sales_agent",
    "phase_resolution_status",
    "phase_resolution_priority",
    "phase_resolution_action",
    "permit_identity_status",
    "bd_match_method",
    "bd_permit_stage",
    "bd_permit_number",
    "bd_site_address",
    "bd_applicants",
    "bd_applicant_quality_status",
    "bd_history_row_count",
    "bd_phase_candidate_count",
    "bd_digest_month_first_observed",
    "bd_digest_month_last_observed",
    "bd_parser_confidences",
    "bd_parser_quality_flags",
    "bd_source_urls",
    "phase_group_id",
    "phase_group_member_count",
    "phase_group_member_ids",
    "phase_group_resolution_status",
    "phase_group_evidence_status",
    "phase_group_permit_years",
    "phase_group_phase_order_context_json",
    "official_schedule_evidence_status",
    "schedule_phase_group_sets",
    "schedule_group_context_json",
    "ownership_promotion_status",
    "permit_attribution_status",
    "research_only",
    "review_caveat",
]

PHASE_GROUP_EVIDENCE_COLUMNS = [
    "phase_group_id",
    "group_resolution_status",
    "group_evidence_status",
    "srpe_address_en",
    "srpe_phase_count",
    "srpe_phase_ids",
    "srpe_phase_names",
    "srpe_phase_order_context_json",
    "bd_history_row_count",
    "bd_match_methods",
    "bd_permit_stages",
    "bd_permit_numbers",
    "bd_permit_years",
    "bd_applicants",
    "bd_site_addresses",
    "bd_distinct_permit_number_count",
    "official_schedule_evidence_status",
    "schedule_phase_group_count",
    "schedule_phase_group_sets",
    "schedule_lot_descriptions",
    "schedule_project_labels",
    "schedule_group_interest_raw",
    "schedule_group_interest_pct",
    "schedule_ownership_status",
    "schedule_group_context_json",
    "source_urls",
    "review_action",
    "ownership_promotion_status",
    "permit_attribution_status",
    "research_only",
    "review_caveat",
]

# A bounded, primary-document review view.  Each row is a phase-group ×
# official completion-schedule context × BD permit/applicant cluster.  The
# schedule context narrows the phase set for manual review, but it is not a
# phase-to-permit assignment; every row therefore keeps both attribution gates
# blocked.  ``schedule_group_interest_pct`` is the issuer's reported Group's
# Interest context and is not copied into an ownership field.
PHASE_PERMIT_CANDIDATE_EVIDENCE_COLUMNS = [
    "phase_group_id",
    "srpe_address_en",
    "group_resolution_status",
    "group_evidence_status",
    "candidate_context_key",
    "candidate_context_status",
    "candidate_phase_ids",
    "candidate_phase_names",
    "candidate_phase_nos",
    "candidate_phase_count",
    "schedule_date",
    "schedule_project_row_no",
    "schedule_lot_description",
    "schedule_project_label",
    "schedule_completion_window",
    "schedule_group_interest_raw",
    "schedule_group_interest_pct",
    "schedule_match_status",
    "schedule_candidate_count",
    "schedule_source_urls",
    "bd_pdf_phase_context_status",
    "bd_pdf_phase_tokens",
    "bd_pdf_unmatched_phase_tokens",
    "bd_pdf_token_coverage_status",
    "bd_pdf_phase_candidate_ids",
    "bd_pdf_group_phase_candidate_ids",
    "bd_pdf_phase_snippets",
    "bd_pdf_context_source_urls",
    "bd_pdf_context_pages",
    "phase_context_concordance_status",
    "phase_context_review_status",
    "phase_context_review_basis",
    "phase_context_reviewed_candidate_ids",
    "phase_context_reviewed_candidate_count",
    "phase_role_evidence_status",
    "phase_role_evidence_ids",
    "phase_role_labels",
    "phase_role_vendors",
    "phase_role_holding_companies",
    "phase_role_source_urls",
    "phase_role_evidence_count",
    "indicative_ownership_context_status",
    "indicative_phase_ownership_context_json",
    "indicative_ownership_pct",
    "indicative_ownership_pct_low",
    "indicative_ownership_pct_high",
    "indicative_numeric_consistency_status",
    "indicative_evidence_basis",
    "indicative_evidence_level",
    "indicative_evidence_source_count",
    "indicative_sales_use_status",
    "indicative_ownership_role_alignment_status",
    "bd_match_method",
    "bd_permit_stage",
    "bd_permit_number",
    "bd_permit_year",
    "bd_site_address",
    "bd_applicants",
    "bd_applicant_quality_status",
    "bd_history_row_count",
    "bd_digest_month_first_observed",
    "bd_digest_month_last_observed",
    "bd_parser_confidences",
    "bd_parser_quality_flags",
    "bd_source_urls",
    "bd_source_pdf_pages",
    "temporal_context_status",
    "temporal_context_detail",
    "resolution_status",
    "resolution_priority",
    "review_action",
    "ownership_promotion_status",
    "permit_attribution_status",
    "research_only",
    "source_urls",
    "review_caveat",
]

# Research-only reconciliation layer built from the candidate evidence above.
# It records what the primary BD page and official schedule jointly support:
# a single phase, a phase set, a narrowed subset, a conflict, or no usable
# token.  It never turns that context into a permit assignment.
PHASE_PERMIT_RECONCILIATION_COLUMNS = [
    "reconciliation_id",
    "phase_group_id",
    "candidate_context_key",
    "srpe_address_en",
    "candidate_phase_ids",
    "candidate_phase_names",
    "candidate_phase_nos",
    "candidate_phase_count",
    "resolved_phase_candidate_ids",
    "resolved_phase_candidate_count",
    "bd_permit_stage",
    "bd_permit_number",
    "bd_permit_year",
    "bd_applicants",
    "schedule_project_label",
    "schedule_lot_description",
    "schedule_group_interest_raw",
    "schedule_group_interest_pct",
    "candidate_context_status",
    "bd_pdf_phase_tokens",
    "bd_pdf_unmatched_phase_tokens",
    "bd_pdf_token_coverage_status",
    "bd_pdf_phase_candidate_ids",
    "bd_pdf_group_phase_candidate_ids",
    "phase_context_concordance_status",
    "phase_context_review_status",
    "phase_context_review_basis",
    "phase_context_reviewed_candidate_ids",
    "phase_context_reviewed_candidate_count",
    "phase_role_evidence_count",
    "indicative_ownership_context_status",
    "indicative_phase_ownership_context_json",
    "indicative_ownership_pct",
    "indicative_ownership_pct_low",
    "indicative_ownership_pct_high",
    "indicative_numeric_consistency_status",
    "indicative_evidence_basis",
    "indicative_evidence_level",
    "indicative_evidence_source_count",
    "indicative_sales_use_status",
    "indicative_ownership_role_alignment_status",
    "reconciliation_status",
    "evidence_strength",
    "permit_assignment_status",
    "review_action",
    "source_urls",
    "ownership_promotion_status",
    "permit_attribution_status",
    "research_only",
    "review_caveat",
]

# One row per SHKP/SRPE phase, combining the permit-context review counts with
# indicative ownership/JV and official-role evidence.  This is the compact
# phase-level work surface for a rough model; it is deliberately not a legal
# ownership or permit-attribution table.
PHASE_OWNERSHIP_REVIEW_COLUMNS = [
    "srpe_development_id",
    "marketing_name",
    "srpe_phase_name",
    "srpe_address_en",
    "phase_group_id",
    "phase_group_member_ids",
    "entity_resolution_status",
    "review_priority",
    "bd_candidate_row_count",
    "bd_history_row_count",
    "bd_distinct_permit_number_count",
    "phase_context_supported_row_count",
    "phase_context_other_group_row_count",
    "phase_context_same_family_variant_row_count",
    "phase_context_unresolved_row_count",
    "phase_context_review_status",
    "phase_context_reviewed_candidate_ids",
    "phase_role_evidence_count",
    "phase_role_labels",
    "phase_role_vendors",
    "phase_role_holding_companies",
    "phase_role_source_urls",
    "indicative_ownership_context_status",
    "indicative_phase_ownership_context_json",
    "indicative_ownership_pct",
    "indicative_ownership_pct_low",
    "indicative_ownership_pct_high",
    "indicative_numeric_consistency_status",
    "indicative_evidence_basis",
    "indicative_evidence_level",
    "indicative_evidence_source_count",
    "indicative_sales_use_status",
    "indicative_ownership_role_alignment_status",
    "ownership_review_status",
    "ownership_review_next_evidence",
    "permit_review_next_evidence",
    "ownership_promotion_status",
    "permit_attribution_status",
    "research_only",
    "source_urls_json",
    "review_caveat",
]


def _text(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    value = str(value).strip()
    return value or None


def _address_key(value: Any) -> str:
    return _normalized_address(value)


def _unique_texts(values: pd.Series) -> list[str]:
    """Return stable, non-empty text values without treating missing as a fact."""
    result: list[str] = []
    for value in values:
        text = _text(value)
        if text and text not in result:
            result.append(text)
    return result


def _month_bounds(values: pd.Series) -> tuple[str | None, str | None]:
    """Return published digest-month bounds, never an inferred permit date."""
    parsed = pd.to_datetime(values, errors="coerce").dropna()
    if parsed.empty:
        return None, None
    return parsed.min().date().isoformat(), parsed.max().date().isoformat()


def _applicant_quality_status(value: str | None) -> str:
    """Flag obvious suffix-only applicant extracts before human matching.

    Several older BD layouts leave only a trailing ``Ltd``/``Development Ltd``
    token after the PDF column parser spills across the address/applicant
    boundary.  This is a parser-quality warning, not evidence of a legal
    applicant identity.
    """
    text = _text(value)
    if not text:
        return "missing_or_not_published"
    normalized = text.replace(".", "").strip().upper()
    suffix_only = {
        "LTD",
        "LIMITED",
        "DEVELOPMENT LTD",
        "CORPORATION LTD",
        "INVESTMENT LTD",
        "ENTERPRISE LTD",
    }
    if normalized in suffix_only:
        return "likely_truncated_suffix_only"
    return "observed_text_requires_review"


def _entity_resolution_status(group: pd.DataFrame) -> str:
    statuses = set(_unique_texts(group.get("bd_match_status", pd.Series(dtype=object))))
    methods = set(_unique_texts(group.get("bd_match_method", pd.Series(dtype=object))))
    if "ambiguous" in statuses:
        return "ambiguous"
    if "matched_needs_review" in statuses or methods.intersection({"address_exact", "address_contains"}):
        return "matched_needs_review"
    return "unmatched"


def _review_policy(status: str) -> tuple[str, str]:
    """Map the crosswalk status to a human review order without promotion."""
    if status == "ambiguous":
        return "P0", "resolve_shared_address_to_phase_before_any_permit_use"
    if status == "matched_needs_review":
        return "P1", "review_address_and_permit_identity_evidence"
    return "P2", "retain_unmatched_no_bd_address_evidence"


_SITE_MATCH_PRIORITY = {
    "site_named_shkp": 5,
    "corporate_role_evidence": 4,
    "page_named_shkp": 3,
    "site_no_shkp_keyword": 1,
    "not_evaluated": 0,
}


def _site_evidence_by_phase(site_evidence: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    """Choose the strongest available official-site evidence for each phase.

    The ordinary HTTP probe and the rendered fallback can both contain a row
    for the same SRPE ID.  Prefer role-field evidence over a generic page
    keyword, and keep the selected row as context; this does not alter the
    address-based phase ambiguity or the ownership gate.
    """
    if site_evidence is None or site_evidence.empty or "srpe_development_id" not in site_evidence.columns:
        return {}
    source = site_evidence.copy()
    source["_phase_key"] = source["srpe_development_id"].map(_text)
    source = source.loc[source["_phase_key"].notna()].copy()
    if source.empty:
        return {}
    for column in ("shkp_match_status", "fetch_status", "fetched_at"):
        if column not in source.columns:
            source[column] = None
    source["_match_priority"] = source.get("shkp_match_status", pd.Series(index=source.index, dtype=object)).map(_SITE_MATCH_PRIORITY).fillna(-1)
    source["_fetch_priority"] = source.get("fetch_status", pd.Series(index=source.index, dtype=object)).map(
        {"ok": 2, "rendered_ok": 2, "ok_short_or_js": 1, "rendered_ok_short": 1, "error": 0, "rendered_error": 0}
    ).fillna(-1)
    source = source.sort_values(
        ["_phase_key", "_match_priority", "_fetch_priority", "fetched_at"],
        ascending=[True, False, False, False],
        na_position="last",
    )
    return {
        str(key): group.iloc[0].to_dict()
        for key, group in source.groupby("_phase_key", sort=False)
    }


def _site_probe_evidence_by_phase(site_evidence: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    """Return only ordinary/rendered project-site probe rows.

    Curated issuer-role rows are intentionally excluded so the review summary
    can report raw probe coverage separately from later primary-source role
    evidence.
    """
    if site_evidence is None or site_evidence.empty or "shkp_match_status" not in site_evidence.columns:
        return {}
    return _site_evidence_by_phase(
        site_evidence.loc[site_evidence["shkp_match_status"].ne("corporate_role_evidence")].copy()
    )


def _corporate_role_evidence_by_phase(site_evidence: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    """Return curated official role rows by phase for transparent coverage."""
    if site_evidence is None or site_evidence.empty or "shkp_match_status" not in site_evidence.columns:
        return {}
    return _site_evidence_by_phase(
        site_evidence.loc[site_evidence["shkp_match_status"].eq("corporate_role_evidence")].copy()
    )


def _developer_identity_fields(
    site: dict[str, Any] | None,
    *,
    site_probe_status: str | None = None,
    corporate_role_present: bool = False,
) -> dict[str, Any]:
    """Map site-probe evidence to a non-ownership developer identity label."""
    status = _text((site or {}).get("shkp_match_status")) or "not_available"
    mapping = {
        "site_named_shkp": (
            "shkp_role_evidence",
            "retain_shkp_role_evidence_but_keep_phase_review",
        ),
        "corporate_role_evidence": (
            "shkp_corporate_role_evidence",
            "official_corporate_role_evidence_routes_phase_review",
        ),
        "page_named_shkp": (
            "shkp_page_evidence",
            "review_role_fields_before_any_attribution",
        ),
        "site_no_shkp_keyword": (
            "no_shkp_keyword_observed",
            "seek_role_fields_or_other_primary_evidence",
        ),
        "not_evaluated": (
            "site_not_evaluated",
            "run_rendered_or_manual_site_review",
        ),
        "not_available": (
            "site_evidence_not_available",
            "run_official_site_probe",
        ),
    }
    identity_status, action = mapping.get(status, ("site_evidence_unclassified", "manual_site_review"))
    return {
        "developer_identity_status": identity_status,
        "developer_identity_action": action,
        "shkp_site_match_status": status,
        "shkp_site_probe_match_status": _text(site_probe_status) or "not_available",
        "shkp_corporate_role_evidence_status": "observed" if corporate_role_present else "not_observed",
        "shkp_site_fetch_status": _text((site or {}).get("fetch_status")),
        "shkp_site_vendor": _text((site or {}).get("vendor_name")),
        "shkp_site_holding_companies": _text((site or {}).get("holding_companies")),
        "shkp_site_sales_agent": _text((site or {}).get("sales_agent")),
        "shkp_site_url": _text((site or {}).get("resolved_url") or (site or {}).get("source_url")),
    }


def _official_role_evidence_as_site_evidence(role_evidence: pd.DataFrame | None) -> pd.DataFrame:
    """Adapt curated official role rows to the site-evidence review shape.

    This adapter only improves developer-identity context. It does not turn a
    vendor/holding-company notice into numeric ownership or a permit mapping.
    """
    if role_evidence is None or role_evidence.empty or "srpe_development_id" not in role_evidence.columns:
        return pd.DataFrame()
    source = role_evidence.copy()
    source["shkp_match_status"] = "corporate_role_evidence"
    source["fetch_status"] = "official_role"
    source["vendor_name"] = source.get("vendor_or_owner")
    source["holding_companies"] = source.get("holding_companies")
    source["sales_agent"] = None
    source["resolved_url"] = source.get("source_url")
    source["source_url"] = source.get("source_url")
    source["fetched_at"] = source.get("last_verified_at")
    source["evidence_context"] = source.get("caveat")
    return source


def build_shkp_bd_history_crosswalk(
    shkp_crosswalk: pd.DataFrame,
    srpe_index: pd.DataFrame,
    bd_history: pd.DataFrame,
) -> pd.DataFrame:
    """Build one conservative candidate row per SHKP phase and BD match.

    Unmatched SHKP candidates are retained as one explicit ``unmatched`` row,
    which makes denominator/coverage visible without treating absence as zero
    construction activity.
    """
    srpe_by_id = {
        str(row.get("development_id")): row
        for row in srpe_index.to_dict("records")
        if row.get("development_id") is not None
    }
    address_groups: dict[str, set[str]] = {}
    for srpe_id, row in srpe_by_id.items():
        key = _address_key(row.get("address_en"))
        if key:
            address_groups.setdefault(key, set()).add(srpe_id)

    bd_records = bd_history.to_dict("records") if not bd_history.empty else []
    rows: list[dict[str, Any]] = []
    matched_at = datetime.now(timezone.utc).isoformat()
    bd_source_url = _text(bd_history.attrs.get("source_url")) or (
        "https://www.bd.gov.hk/en/whats-new/monthly-digests/index.html"
    )
    for candidate in shkp_crosswalk.to_dict("records"):
        development_id = _text(candidate.get("srpe_development_id"))
        srpe = srpe_by_id.get(development_id or "", {})
        srpe_address = _text(srpe.get("address_en"))
        srpe_key = _address_key(srpe_address)
        matches: list[tuple[dict[str, Any], str]] = []
        if srpe_key:
            for event in bd_records:
                bd_key = _address_key(event.get("site_address"))
                if not bd_key:
                    continue
                if bd_key == srpe_key:
                    matches.append((event, "address_exact"))
                elif len(srpe_key) >= 10 and (srpe_key in bd_key or bd_key in srpe_key):
                    matches.append((event, "address_contains"))
        candidate_count = len(matches)
        phase_candidate_count = len(address_groups.get(srpe_key, set())) if srpe_key else 0
        if not matches:
            matches = [({}, "none")]
        for event, method in matches:
            # ``candidate_count`` is the number of matching BD detail rows;
            # one phase naturally produces many rows across months and
            # lifecycle stages.  It must not turn a time-series hit into an
            # entity ambiguity.  Ambiguity is reserved for an address shared
            # by multiple SRPE phase IDs; every address-only hit remains
            # blocked for ownership promotion.
            status = "unmatched" if method == "none" else (
                "ambiguous" if phase_candidate_count > 1 else "matched_needs_review"
            )
            rows.append(
                {
                    "srpe_development_id": development_id,
                    "marketing_name": candidate.get("marketing_name"),
                    "srpe_phase_name": candidate.get("srpe_phase_name") or srpe.get("phase_name_en"),
                    "srpe_address_en": srpe_address,
                    "crosswalk_match_status": candidate.get("match_status"),
                    "digest_month": event.get("digest_month"),
                    "observation_month": event.get("observation_month"),
                    "revision_status": event.get("revision_status"),
                    "bd_permit_stage": event.get("permit_stage"),
                    "bd_permit_number": event.get("permit_number"),
                    "bd_site_address": event.get("site_address"),
                    "bd_domestic_units_count": event.get("domestic_units_count"),
                    "bd_usable_floor_area_sqm": event.get("usable_floor_area_sqm"),
                    "bd_applicant": event.get("applicant"),
                    "bd_parser_confidence": event.get("parser_confidence"),
                    "bd_parser_quality_flag": event.get("parser_quality_flag"),
                    "bd_source_pdf_page": event.get("source_pdf_page"),
                    "bd_match_method": method,
                    "bd_match_status": status,
                    "bd_candidate_count": candidate_count,
                    "bd_phase_candidate_count": phase_candidate_count,
                    "project_identity_status": "address_candidate_only" if method != "none" else "not_observed",
                    "ownership_promotion_status": "blocked_address_only",
                    "shkp_source_url": candidate.get("shkp_source_url"),
                    "srpe_source_url": candidate.get("srpe_source_url"),
                    "bd_source_url": event.get("source_url") or bd_source_url,
                    "matched_at": matched_at,
                }
            )
    result = pd.DataFrame(rows, columns=CROSSWALK_COLUMNS)
    if not result.empty:
        result = result.drop_duplicates(
            subset=["srpe_development_id", "digest_month", "bd_permit_stage", "bd_permit_number", "bd_match_method"],
            keep="first",
        ).reset_index(drop=True)
    result.attrs.update(
        raw_snapshots=list(dict.fromkeys(
            [str(value) for value in bd_history.attrs.get("raw_snapshots", []) if value]
            + [str(value) for value in shkp_crosswalk.attrs.get("raw_snapshots", []) if value]
            + [str(value) for value in srpe_index.attrs.get("raw_snapshots", []) if value]
        )),
        source_urls=list(dict.fromkeys(
            [str(value) for value in bd_history.attrs.get("source_urls", []) if value]
            + [str(value) for value in shkp_crosswalk.attrs.get("source_urls", []) if value]
            + [str(value) for value in srpe_index.attrs.get("source_urls", []) if value]
            + [bd_source_url]
        )),
        lineage_metadata={
            "lineage_type": "research_shkp_srpe_to_bd_history_address_crosswalk",
            "ownership_promotion": "blocked_address_only",
            "candidate_phase_count": int(len(shkp_crosswalk)),
            "matched_phase_count": int(result.loc[result["bd_match_method"].ne("none"), "srpe_development_id"].nunique()) if not result.empty else 0,
        },
    )
    return result


def _permit_year(value: Any) -> int | None:
    """Extract the year token from an official BD permit identifier."""
    text = _text(value)
    if not text:
        return None
    for token in text.split("/"):
        token = token.strip()
        if len(token) == 4 and token.isdigit() and token.startswith("20"):
            return int(token)
    return None


def _phase_group_key(phase_id: Any, address: Any, row_index: Any = "") -> str:
    address_key = _address_key(address)
    if address_key:
        return f"srpe-address:{address_key}"
    phase_key = _text(phase_id)
    if phase_key:
        return f"srpe-phase:{phase_key}"
    return f"missing-phase:{row_index}"


def build_shkp_bd_phase_group_evidence(
    crosswalk: pd.DataFrame,
    srpe_index: pd.DataFrame | None = None,
    schedule_crosswalk: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a conservative shared-address phase-group evidence table.

    This layer is intentionally one level above a phase-to-permit mapping. It
    records which SRPE phases share an address, which BD permit/applicant
    clusters are observed at that address, and the publication-order context
    available from SRPE. Publication order is descriptive only: a phase's
    first sales-file date is not a permit start bound, so no phase is assigned
    a permit and all attribution gates stay blocked.
    """
    source = crosswalk.copy() if crosswalk is not None else pd.DataFrame()
    srpe = srpe_index.copy() if srpe_index is not None else pd.DataFrame()
    schedule = schedule_crosswalk.copy() if schedule_crosswalk is not None else pd.DataFrame()
    srpe_by_id = {
        _text(row.get("development_id")): row
        for row in srpe.to_dict("records")
        if _text(row.get("development_id"))
    }
    lineage = {
        "lineage_type": "research_shkp_bd_shared_address_phase_group_evidence",
        "source_dataset": DATASET_NAME,
        "source_datasets": [
            DATASET_NAME,
            *(["srpe_development_index"] if srpe_index is not None else []),
            *(["shkp_completion_schedule_crosswalk"] if schedule_crosswalk is not None else []),
        ],
        "ownership_promotion": "blocked_address_only",
        "permit_attribution": "blocked_address_only",
        "external_fetch": False,
        "group_policy": "shared_srpe_address_with_bd_permit_applicant_context_no_phase_assignment",
    }
    raw_snapshots = list(dict.fromkeys(
        [str(value) for value in (source.attrs.get("raw_snapshots", []) if crosswalk is not None else []) if value]
        + [str(value) for value in (srpe.attrs.get("raw_snapshots", []) if srpe_index is not None else []) if value]
    ))
    source_urls = list(dict.fromkeys(
        [str(value) for value in (source.attrs.get("source_urls", []) if crosswalk is not None else []) if value]
        + [str(value) for value in (srpe.attrs.get("source_urls", []) if srpe_index is not None else []) if value]
        + [str(value) for value in (schedule.attrs.get("source_urls", []) if schedule_crosswalk is not None else []) if value]
    ))
    schedule_by_phase: dict[str, pd.DataFrame] = {}
    if not schedule.empty and "srpe_development_id" in schedule.columns:
        for phase_id, phase_rows in schedule.groupby(schedule["srpe_development_id"].map(_text), dropna=True, sort=False):
            if phase_id:
                schedule_by_phase[str(phase_id)] = phase_rows.copy()
    if source.empty:
        result = pd.DataFrame(columns=PHASE_GROUP_EVIDENCE_COLUMNS)
        result.attrs.update(raw_snapshots=raw_snapshots, source_urls=source_urls, lineage_metadata=lineage)
        return result

    source["_group_key"] = [
        _phase_group_key(
            row.get("srpe_development_id"),
            row.get("srpe_address_en"),
            index,
        )
        for index, row in source.iterrows()
    ]
    rows: list[dict[str, Any]] = []
    for group_key, group in source.groupby("_group_key", sort=True, dropna=False):
        matched = group.loc[group.get("bd_match_method", pd.Series(index=group.index, dtype=object)).isin(
            ["address_exact", "address_contains"]
        )].copy()
        # The crosswalk repeats one BD history row once for every SRPE phase
        # sharing the address.  Group evidence must count distinct source
        # observations, not phase×observation copies, or LOHAS/NOVO-style
        # groups would look artificially larger than the underlying history.
        dedup_columns = [
            column
            for column in (
                "digest_month",
                "bd_permit_stage",
                "bd_permit_number",
                "bd_site_address",
                "bd_applicant",
                "bd_match_method",
            )
            if column in matched.columns
        ]
        if not matched.empty and dedup_columns:
            matched = matched.drop_duplicates(subset=dedup_columns, keep="first")
        phase_ids = _unique_texts(group.get("srpe_development_id", pd.Series(dtype=object)))
        phase_records: list[dict[str, Any]] = []
        for phase_id in phase_ids:
            metadata = srpe_by_id.get(phase_id, {})
            phase_rows = group.loc[group.get("srpe_development_id", pd.Series(index=group.index, dtype=object)).map(_text).eq(phase_id)]
            phase_name = _text(metadata.get("phase_name_en")) or next(
                iter(_unique_texts(phase_rows.get("srpe_phase_name", pd.Series(dtype=object)))),
                None,
            )
            publication = _text(metadata.get("srpe_earliest_publication"))
            if not publication:
                publication = _text(metadata.get("brochure_first_print_date"))
            phase_records.append(
                {
                    "srpe_development_id": phase_id,
                    "phase_name": phase_name,
                    "phase_no": _text(metadata.get("phase_no")),
                    "first_publication": publication,
                    "official_website": _text(metadata.get("official_website")),
                }
            )
        phase_records.sort(key=lambda item: (item.get("first_publication") or "9999-99-99", item["srpe_development_id"]))
        permit_numbers = _unique_texts(matched.get("bd_permit_number", pd.Series(dtype=object)))
        permit_years = sorted({year for year in (_permit_year(value) for value in permit_numbers) if year is not None})
        phase_context: list[dict[str, Any]] = []
        for phase in phase_records:
            publication = phase.get("first_publication")
            publication_year = None
            if publication:
                parsed = pd.to_datetime(publication, errors="coerce")
                if not pd.isna(parsed):
                    publication_year = int(parsed.year)
            if not permit_years:
                order_status = "no_observed_permit_year"
            elif publication_year is None:
                order_status = "no_srpe_publication_date"
            elif publication_year <= max(permit_years):
                order_status = "published_by_observed_permit_year"
            else:
                order_status = "published_after_observed_permit_year_context_only"
            phase_context.append({**phase, "publication_year": publication_year, "publication_order_status": order_status})

        address_values = _unique_texts(group.get("srpe_address_en", pd.Series(dtype=object)))
        srpe_address = address_values[0] if address_values else None
        if not matched.empty:
            group_status = "shared_address_group" if len(phase_ids) > 1 else "single_phase_address_group"
            evidence_status = "address_and_bd_cluster_observed" if permit_numbers else "address_only_no_permit_number"
        else:
            group_status = "unmatched_phase_group"
            evidence_status = "no_bd_address_match"
        group_urls = _unique_texts(pd.concat([
            group.get("shkp_source_url", pd.Series(dtype=object)),
            group.get("srpe_source_url", pd.Series(dtype=object)),
            matched.get("bd_source_url", pd.Series(dtype=object)),
        ], ignore_index=True))
        schedule_rows = pd.concat(
            [schedule_by_phase.get(phase_id, pd.DataFrame()) for phase_id in phase_ids],
            ignore_index=True,
        ) if schedule_by_phase else pd.DataFrame()
        schedule_context: list[dict[str, Any]] = []
        if not schedule_rows.empty:
            def _schedule_phase_ids(schedule_group: pd.DataFrame) -> list[str]:
                raw_text = " ".join(
                    _unique_texts(pd.concat([
                        schedule_group.get("lot_description", pd.Series(dtype=object)),
                        schedule_group.get("project_label", pd.Series(dtype=object)),
                    ], ignore_index=True))
                ).casefold()
                matched_ids: list[str] = []
                for phase in phase_records:
                    phase_no = _text(phase.get("phase_no"))
                    if not phase_no:
                        continue
                    short_no = re.sub(r"[^a-z0-9]+", "", phase_no.casefold()).replace("phase", "")
                    if not short_no:
                        continue
                    if re.search(rf"\bphases?\s*{re.escape(short_no)}\b", raw_text):
                        matched_ids.append(phase["srpe_development_id"])
                        continue
                    # Lists such as ``Phases 1 & 2`` place a separator between
                    # the phase word and the second number.  Keep the window
                    # short and stop at punctuation so lot numbers elsewhere
                    # in the description do not become phase matches.
                    if re.search(rf"\bphases?\b[^.;]{{0,24}}\b{re.escape(short_no)}\b", raw_text):
                        matched_ids.append(phase["srpe_development_id"])
                        continue
                    # Some notices write ``1A(2)`` while the SRPE phase number
                    # is stored as ``1A(2)`` or ``Phase 1A``.  A normalized
                    # fallback keeps the grouped evidence useful without
                    # treating it as a legal phase mapping.
                    normalized_text = re.sub(r"[^a-z0-9]+", "", raw_text)
                    # Do not use a bare numeric/one-letter substring fallback:
                    # lot numbers such as ``33`` or ordinary words containing
                    # ``b`` would create false phase matches.  The fallback is
                    # reserved for alphanumeric labels such as ``1A2``.
                    if (any(character.isalpha() for character in short_no) and len(short_no) > 1) and short_no in normalized_text:
                        matched_ids.append(phase["srpe_development_id"])
                return matched_ids

            schedule_key_columns = [
                column
                for column in ("schedule_date", "project_row_no", "lot_description", "project_label")
                if column in schedule_rows.columns
            ]
            if schedule_key_columns:
                for schedule_key, schedule_group in schedule_rows.groupby(schedule_key_columns, dropna=False, sort=True):
                    if not isinstance(schedule_key, tuple):
                        schedule_key = (schedule_key,)
                    key_values = dict(zip(schedule_key_columns, schedule_key))
                    schedule_phase_ids = _schedule_phase_ids(schedule_group)
                    if not schedule_phase_ids:
                        schedule_phase_ids = _unique_texts(schedule_group.get("srpe_development_id", pd.Series(dtype=object)))
                    phase_name_by_id = {
                        phase["srpe_development_id"]: phase.get("phase_name")
                        for phase in phase_records
                    }
                    schedule_context.append(
                        {
                            **{key: _text(value) for key, value in key_values.items()},
                            "srpe_phase_ids": schedule_phase_ids,
                            "srpe_phase_names": [phase_name_by_id.get(phase_id) for phase_id in schedule_phase_ids if phase_name_by_id.get(phase_id)],
                            "match_status": "; ".join(_unique_texts(schedule_group.get("match_status", pd.Series(dtype=object)))) or None,
                            "match_confidence": "; ".join(_unique_texts(schedule_group.get("match_confidence", pd.Series(dtype=object)))) or None,
                            "lot_match_status": "; ".join(_unique_texts(schedule_group.get("lot_match_status", pd.Series(dtype=object)))) or None,
                            "group_interest_raw": "; ".join(_unique_texts(schedule_group.get("group_interest_raw", pd.Series(dtype=object)))) or None,
                            "group_interest_pct": "; ".join(_unique_texts(schedule_group.get("group_interest_pct", pd.Series(dtype=object)))) or None,
                            "ownership_status": "; ".join(_unique_texts(schedule_group.get("ownership_status", pd.Series(dtype=object)))) or None,
                            "evidence_level": "; ".join(_unique_texts(schedule_group.get("evidence_level", pd.Series(dtype=object)))) or None,
                        }
                    )
        if schedule_context:
            exact_schedule = any(
                str(context.get("match_status") or "").casefold().find("matched") >= 0
                and len(context.get("srpe_phase_ids") or []) == 1
                for context in schedule_context
            )
            schedule_status = "phase_label_exact_observed" if exact_schedule else "official_schedule_grouped"
            schedule_sets = [
                ",".join(context.get("srpe_phase_ids") or [])
                for context in schedule_context
                if context.get("srpe_phase_ids")
            ]
            schedule_sets = list(dict.fromkeys(schedule_sets))
        else:
            schedule_status = "not_observed"
            schedule_sets = []
        phase_names = [record["phase_name"] for record in phase_records if record.get("phase_name")]
        schedule_urls = _unique_texts(pd.concat([
            schedule_rows.get("source_url", pd.Series(dtype=object)),
            schedule_rows.get("document_url", pd.Series(dtype=object)),
        ], ignore_index=True)) if not schedule_rows.empty else []
        source_urls.extend(url for url in [*group_urls, *schedule_urls] if url not in source_urls)
        rows.append(
            {
                "phase_group_id": group_key,
                "group_resolution_status": group_status,
                "group_evidence_status": evidence_status,
                "srpe_address_en": srpe_address,
                "srpe_phase_count": int(len(phase_ids)),
                "srpe_phase_ids": "; ".join(phase_ids) or None,
                "srpe_phase_names": "; ".join(phase_names) or None,
                "srpe_phase_order_context_json": json.dumps(phase_context, ensure_ascii=False, sort_keys=True),
                "bd_history_row_count": int(len(matched)),
                "bd_match_methods": "; ".join(_unique_texts(matched.get("bd_match_method", pd.Series(dtype=object)))) or "none",
                "bd_permit_stages": "; ".join(_unique_texts(matched.get("bd_permit_stage", pd.Series(dtype=object)))) or None,
                "bd_permit_numbers": "; ".join(permit_numbers) or "none_observed",
                "bd_permit_years": "; ".join(str(year) for year in permit_years) or None,
                "bd_applicants": "; ".join(_unique_texts(matched.get("bd_applicant", pd.Series(dtype=object)))) or None,
                "bd_site_addresses": "; ".join(_unique_texts(matched.get("bd_site_address", pd.Series(dtype=object)))) or None,
                "bd_distinct_permit_number_count": int(len(permit_numbers)),
                "official_schedule_evidence_status": schedule_status,
                "schedule_phase_group_count": int(len(schedule_context)),
                "schedule_phase_group_sets": "; ".join(schedule_sets) or None,
                "schedule_lot_descriptions": "; ".join(_unique_texts(schedule_rows.get("lot_description", pd.Series(dtype=object)))) or None,
                "schedule_project_labels": "; ".join(_unique_texts(schedule_rows.get("project_label", pd.Series(dtype=object)))) or None,
                "schedule_group_interest_raw": "; ".join(_unique_texts(schedule_rows.get("group_interest_raw", pd.Series(dtype=object)))) or None,
                "schedule_group_interest_pct": "; ".join(_unique_texts(schedule_rows.get("group_interest_pct", pd.Series(dtype=object)))) or None,
                "schedule_ownership_status": "; ".join(_unique_texts(schedule_rows.get("ownership_status", pd.Series(dtype=object)))) or None,
                "schedule_group_context_json": json.dumps(schedule_context, ensure_ascii=False, sort_keys=True),
                "source_urls": "; ".join([*group_urls, *schedule_urls]) or None,
                "review_action": (
                    "resolve each BD permit to a phase using SRPE lot/phase and primary BD documents; "
                    "publication order is context only and cannot assign a permit"
                ),
                "ownership_promotion_status": "blocked_address_only",
                "permit_attribution_status": "blocked_address_only",
                "research_only": True,
                "review_caveat": (
                    "This is a shared-address group, not a phase-to-permit mapping. SRPE first-publication dates "
                    "and BD permit-number years are descriptive context only; no permit date, phase ownership, "
                    "JV percentage or attributable units are inferred."
                ),
            }
        )
    result = pd.DataFrame(rows, columns=PHASE_GROUP_EVIDENCE_COLUMNS)
    phase_count_total = sum(
        len([value for value in str(row.get("srpe_phase_ids") or "").split("; ") if value])
        for row in rows
    )
    result.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=list(dict.fromkeys(source_urls)),
        lineage_metadata={
            **lineage,
            "group_count": int(len(result)),
            "phase_count": int(phase_count_total),
        },
    )
    return result


def _json_records(value: Any) -> list[dict[str, Any]]:
    """Decode a JSON list of object records without trusting malformed input."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        raw = value
    else:
        try:
            raw = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _schedule_context_key(group_id: str, index: int) -> str:
    """Return a stable key for one schedule grouping within an address group."""
    return f"{group_id}::schedule-{index + 1}"


def _role_context_by_phase(role_evidence: pd.DataFrame | None) -> dict[str, list[dict[str, Any]]]:
    """Group curated role observations by phase, preserving all source rows."""
    if role_evidence is None or role_evidence.empty or "srpe_development_id" not in role_evidence.columns:
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for row in role_evidence.to_dict("records"):
        phase_id = _text(row.get("srpe_development_id"))
        if phase_id:
            result.setdefault(phase_id, []).append(row)
    return result


def _schedule_urls_by_phase(schedule_crosswalk: pd.DataFrame | None) -> dict[str, list[str]]:
    """Collect official schedule/PDF URLs by SRPE phase for review provenance."""
    if schedule_crosswalk is None or schedule_crosswalk.empty or "srpe_development_id" not in schedule_crosswalk.columns:
        return {}
    result: dict[str, list[str]] = {}
    for row in schedule_crosswalk.to_dict("records"):
        phase_id = _text(row.get("srpe_development_id"))
        if not phase_id:
            continue
        urls = [
            _text(row.get("document_url")),
            _text(row.get("source_url")),
        ]
        values = result.setdefault(phase_id, [])
        for url in urls:
            if url and url not in values:
                values.append(url)
    return result


def _page_key(value: Any) -> str | None:
    """Normalize PDF page values such as ``30`` and ``30.0`` for joins."""
    text = _text(value)
    if not text:
        return None
    try:
        numeric = float(text)
        if numeric.is_integer():
            return str(int(numeric))
    except (TypeError, ValueError):
        pass
    return text


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", _text(value) or "").casefold()


_PDF_PHASE_CONTEXT_RE = re.compile(
    r"\bphases?\s*([0-9]+[A-Z]?(?:\([0-9]+\))?(?:-\d+)?"
    r"(?:\s*(?:and|&|,|/|-)\s*[0-9]+[A-Z]?(?:\([0-9]+\))?(?:-\d+)?){0,8})",
    re.IGNORECASE,
)
_PDF_PHASE_TOKEN_RE = re.compile(r"\d+[A-Z]?(?:\(\d+\))?(?:-\d+)?", re.IGNORECASE)


def _pdf_phase_mentions(page_text: str) -> tuple[list[str], list[str]]:
    """Extract conservative ``phase`` snippets/tokens from one PDF page."""
    snippets: list[str] = []
    tokens: list[str] = []
    for match in _PDF_PHASE_CONTEXT_RE.finditer(page_text or ""):
        snippet = re.sub(r"\s+", " ", match.group(0)).strip()
        if snippet and snippet not in snippets:
            snippets.append(snippet)
        for token in _PDF_PHASE_TOKEN_RE.findall(match.group(1) or ""):
            normalized = token.upper()
            if normalized not in tokens:
                tokens.append(normalized)
    return tokens, snippets


def _phase_no_key(value: Any) -> str | None:
    """Normalize an SRPE phase number without turning ``1A(1)`` into ``1A``."""
    text = _text(value)
    if not text:
        return None
    text = re.sub(r"^phase\s*", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", "", text).upper()


def _phase_family_key(value: Any) -> str | None:
    """Return a coarse comparable family (e.g. ``1A(2)`` -> ``1A``)."""
    key = _phase_no_key(value)
    if not key:
        return None
    match = re.match(r"\d+[A-Z]?", key)
    return match.group(0) if match else key


def _history_pdf_context_match(
    history_row: Mapping[str, Any],
    *,
    page_text: str,
    tokens: list[str],
    snippets: list[str],
) -> dict[str, Any]:
    """Create one source-page phase-token context row for a BD observation."""
    permit = _text(history_row.get("permit_number"))
    permit_seen = bool(permit and _compact_text(permit) in _compact_text(page_text))
    if permit_seen and tokens:
        status = "permit_page_phase_tokens_observed"
    elif permit_seen:
        status = "permit_page_no_phase_tokens_observed"
    elif tokens:
        status = "page_phase_tokens_observed_permit_not_located"
    else:
        status = "page_no_phase_tokens_observed"
    return {
        "bd_pdf_context_status": status,
        "bd_pdf_phase_tokens": "; ".join(tokens) or None,
        "bd_pdf_phase_snippets": " | ".join(snippets) or None,
        "bd_pdf_permit_number": permit,
        "bd_pdf_digest_month": _text(history_row.get("digest_month")),
        "bd_pdf_permit_stage": _text(history_row.get("permit_stage")),
        "bd_pdf_site_address": _text(history_row.get("site_address")),
        "bd_pdf_source_url": _text(history_row.get("source_url")),
        "bd_pdf_source_page": _page_key(history_row.get("source_pdf_page")),
        "bd_pdf_raw_snapshot": _text(history_row.get("raw_snapshot")),
    }


def build_shkp_bd_pdf_phase_context(
    bd_history: pd.DataFrame | None,
    crosswalk: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Extract phase-token context from existing BD detail-PDF snapshots.

    This is deliberately a source-page evidence layer.  It only records text
    such as ``phase 1A and 1B`` found on the official BD PDF page associated
    with an address/permit candidate.  It never interprets the token as a
    permit date, legal identity, ownership or phase assignment.
    """
    history = bd_history.copy() if bd_history is not None else pd.DataFrame()
    candidate = crosswalk.copy() if crosswalk is not None else pd.DataFrame()
    columns = [
        "bd_pdf_context_status",
        "bd_pdf_phase_tokens",
        "bd_pdf_phase_snippets",
        "bd_pdf_permit_number",
        "bd_pdf_digest_month",
        "bd_pdf_permit_stage",
        "bd_pdf_site_address",
        "bd_pdf_source_url",
        "bd_pdf_source_page",
        "bd_pdf_raw_snapshot",
    ]
    lineage = {
        "lineage_type": "research_shkp_bd_primary_pdf_phase_token_context",
        "source_datasets": ["bd_project_lifecycle_history", DATASET_NAME],
        "external_fetch": False,
        "phase_assignment": "blocked_pdf_token_context_only",
    }
    raw_snapshots = list(dict.fromkeys(
        [str(value) for frame in (history, candidate) if frame is not None
         for value in frame.attrs.get("raw_snapshots", []) if value]
    ))
    source_urls = list(dict.fromkeys(
        [str(value) for frame in (history, candidate) if frame is not None
         for value in frame.attrs.get("source_urls", []) if value]
    ))
    if history.empty or "raw_snapshot" not in history.columns:
        result = pd.DataFrame(columns=columns)
        result.attrs.update(raw_snapshots=raw_snapshots, source_urls=source_urls, lineage_metadata=lineage)
        return result

    # Limit the PDF work to address/permit candidates in the SHKP crosswalk.
    # This keeps the evidence layer bounded and avoids parsing unrelated BD
    # projects in the full 17k-row history.
    candidate_permits = set()
    candidate_refs = set()
    if not candidate.empty:
        for row in candidate.to_dict("records"):
            permit = _text(row.get("bd_permit_number"))
            if permit:
                candidate_permits.add(permit.casefold())
            ref = (_text(row.get("bd_source_url")), _page_key(row.get("bd_source_pdf_page")))
            if ref[0] and ref[1]:
                candidate_refs.add(ref)
    filtered_rows: list[dict[str, Any]] = []
    for row in history.to_dict("records"):
        raw_path = _text(row.get("raw_snapshot"))
        if not raw_path:
            continue
        permit = _text(row.get("permit_number"))
        ref = (_text(row.get("source_url")), _page_key(row.get("source_pdf_page")))
        if candidate_permits and (permit or "").casefold() not in candidate_permits and ref not in candidate_refs:
            continue
        filtered_rows.append(row)
    if not filtered_rows:
        result = pd.DataFrame(columns=columns)
        result.attrs.update(raw_snapshots=raw_snapshots, source_urls=source_urls, lineage_metadata=lineage)
        return result

    rows: list[dict[str, Any]] = []
    page_cache: dict[tuple[str, str], tuple[str, list[str], list[str]]] = {}
    for row in filtered_rows:
        raw_path = _text(row.get("raw_snapshot"))
        page = _page_key(row.get("source_pdf_page"))
        if not raw_path or not page:
            continue
        cache_key = (raw_path, page)
        if cache_key not in page_cache:
            try:
                pdf_path = Path(raw_path)
                with pdfplumber.open(pdf_path) as pdf:
                    page_index = int(page) - 1
                    if page_index < 0 or page_index >= len(pdf.pages):
                        raise IndexError(f"page {page} outside PDF page count {len(pdf.pages)}")
                    page_text = pdf.pages[page_index].extract_text(layout=True) or ""
                phase_tokens, phase_snippets = _pdf_phase_mentions(page_text)
                page_cache[cache_key] = (page_text, phase_tokens, phase_snippets)
            except Exception as exc:  # noqa: BLE001 -- retain page-level QA evidence
                page_cache[cache_key] = (f"__ERROR__:{exc!r}", [], [])
        page_text, phase_tokens, phase_snippets = page_cache[cache_key]
        if page_text.startswith("__ERROR__:"):
            context = {
                "bd_pdf_context_status": "page_read_error",
                "bd_pdf_phase_tokens": None,
                "bd_pdf_phase_snippets": None,
                "bd_pdf_permit_number": _text(row.get("permit_number")),
                "bd_pdf_digest_month": _text(row.get("digest_month")),
                "bd_pdf_permit_stage": _text(row.get("permit_stage")),
                "bd_pdf_site_address": _text(row.get("site_address")),
                "bd_pdf_source_url": _text(row.get("source_url")),
                "bd_pdf_source_page": page,
                "bd_pdf_raw_snapshot": raw_path,
            }
        else:
            context = _history_pdf_context_match(
                row,
                page_text=page_text,
                tokens=phase_tokens,
                snippets=phase_snippets,
            )
        rows.append(context)
    result = pd.DataFrame(rows, columns=columns).drop_duplicates(
        subset=["bd_pdf_permit_number", "bd_pdf_digest_month", "bd_pdf_permit_stage", "bd_pdf_source_url", "bd_pdf_source_page", "bd_pdf_site_address"],
        keep="first",
    ).reset_index(drop=True)
    result.attrs.update(
        raw_snapshots=list(dict.fromkeys(raw_snapshots + [row["bd_pdf_raw_snapshot"] for row in rows if row.get("bd_pdf_raw_snapshot")])),
        source_urls=list(dict.fromkeys(source_urls + [row["bd_pdf_source_url"] for row in rows if row.get("bd_pdf_source_url")])),
        lineage_metadata={
            **lineage,
            "input_history_rows": int(len(history)),
            "filtered_history_rows": int(len(filtered_rows)),
            "source_page_rows": int(len(result)),
            "source_page_count": int(len(page_cache)),
            "phase_token_rows": int(result["bd_pdf_phase_tokens"].notna().sum()) if not result.empty else 0,
        },
    )
    return result


def _phase_role_context(
    phase_ids: list[str],
    role_by_phase: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Flatten phase role rows into review-only, source-preserving fields."""
    roles = [
        row
        for phase_id in phase_ids
        for row in role_by_phase.get(phase_id, [])
    ]
    if not roles:
        return {
            "phase_role_evidence_status": "not_observed",
            "phase_role_evidence_ids": None,
            "phase_role_labels": None,
            "phase_role_vendors": None,
            "phase_role_holding_companies": None,
            "phase_role_source_urls": None,
        }
    return {
        "phase_role_evidence_status": "observed_context_only",
        "phase_role_evidence_ids": "; ".join(_unique_texts(pd.Series([row.get("evidence_id") for row in roles], dtype=object))) or None,
        "phase_role_labels": "; ".join(_unique_texts(pd.Series([row.get("phase_label") for row in roles], dtype=object))) or None,
        "phase_role_vendors": "; ".join(_unique_texts(pd.Series([row.get("vendor_or_owner") for row in roles], dtype=object))) or None,
        "phase_role_holding_companies": "; ".join(_unique_texts(pd.Series([row.get("holding_companies") for row in roles], dtype=object))) or None,
        "phase_role_source_urls": "; ".join(_unique_texts(pd.Series([row.get("source_url") for row in roles], dtype=object))) or None,
    }


def _ownership_roster_by_phase(
    ownership_roster: pd.DataFrame | None,
) -> dict[str, list[dict[str, Any]]]:
    """Group the non-legal indicative roster by SRPE phase ID.

    The roster is a snapshot/heuristic contract.  Keeping the rows as a
    separate lookup makes it possible to show numeric and JV context beside a
    BD review candidate without converting that context into a permit or legal
    ownership assertion.
    """
    if ownership_roster is None or ownership_roster.empty:
        return {}
    if "srpe_development_id" not in ownership_roster.columns:
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for row in ownership_roster.to_dict("records"):
        phase_id = _text(row.get("srpe_development_id"))
        if phase_id:
            result.setdefault(phase_id, []).append(row)
    return result


def _indicative_ownership_context(
    phase_ids: list[str],
    ownership_by_phase: dict[str, list[dict[str, Any]]],
    role_by_phase: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Attach roster/role alignment as explicit, non-promoting context.

    Direct percentage fields are populated only for a single candidate phase
    with one numeric indicative snapshot.  Multi-phase candidate contexts are
    preserved in JSON so a grouped 100%/JV mix cannot be mistaken for one
    phase-level stake.
    """
    records: list[dict[str, Any]] = []
    for phase_id in phase_ids:
        candidates = ownership_by_phase.get(phase_id, [])
        row = candidates[-1] if candidates else None
        owner_status = _text(row.get("indicative_owner_status")) if row else None
        pct = pd.to_numeric(pd.Series([row.get("indicative_ownership_pct") if row else None]), errors="coerce").iloc[0]
        pct_low = pd.to_numeric(pd.Series([row.get("indicative_ownership_pct_low") if row else None]), errors="coerce").iloc[0]
        pct_high = pd.to_numeric(pd.Series([row.get("indicative_ownership_pct_high") if row else None]), errors="coerce").iloc[0]
        pct_value = None if pd.isna(pct) else float(pct)
        pct_low_value = None if pd.isna(pct_low) else float(pct_low)
        pct_high_value = None if pd.isna(pct_high) else float(pct_high)
        role_count = len(role_by_phase.get(phase_id, []))
        source_count_value = pd.to_numeric(
            pd.Series([row.get("indicative_evidence_source_count") if row else None]),
            errors="coerce",
        ).iloc[0]
        records.append(
            {
                "srpe_development_id": phase_id,
                "indicative_owner_status": owner_status or "not_observed",
                "indicative_ownership_pct": pct_value,
                "indicative_ownership_pct_low": pct_low_value,
                "indicative_ownership_pct_high": pct_high_value,
                "indicative_numeric_consistency_status": _text(row.get("indicative_numeric_consistency_status")) if row else "not_observed",
                "indicative_evidence_basis": _text(row.get("indicative_evidence_basis")) if row else None,
                "indicative_evidence_level": _text(row.get("indicative_evidence_level")) if row else None,
                "indicative_evidence_source_count": int(source_count_value) if not pd.isna(source_count_value) else 0,
                "indicative_sales_use_status": _text(row.get("indicative_sales_use_status")) if row else "not_covered",
                "strict_ownership_attribution_ready": bool(row.get("strict_ownership_attribution_ready")) if row else False,
                "phase_role_evidence_count": int(role_count),
            }
        )

    numeric_records = [
        row for row in records
        if row.get("indicative_ownership_pct") is not None
        and "numeric" in (_text(row.get("indicative_owner_status")) or "")
    ]
    jv_records = [
        row for row in records
        if "jv" in ((_text(row.get("indicative_owner_status")) or "").casefold())
    ]
    observed_records = [row for row in records if row.get("indicative_owner_status") != "not_observed"]
    role_count = sum(int(row.get("phase_role_evidence_count") or 0) for row in records)
    if not records or not observed_records:
        context_status = "not_observed"
    elif len(numeric_records) == len(phase_ids) and len(records) == len(phase_ids):
        context_status = "all_candidate_phases_numeric_snapshot"
    elif len(jv_records) == len(phase_ids) and len(records) == len(phase_ids):
        context_status = "all_candidate_phases_jv_unquantified"
    elif numeric_records or jv_records:
        context_status = "mixed_or_incomplete_candidate_phase_context"
    else:
        context_status = "identity_only_without_numeric_or_jv_snapshot"

    if numeric_records and role_count:
        alignment_status = "numeric_snapshot_with_role_context"
    elif jv_records and role_count:
        alignment_status = "jv_snapshot_with_role_context"
    elif numeric_records:
        alignment_status = "numeric_snapshot_without_role_context"
    elif role_count:
        alignment_status = "role_context_without_numeric_snapshot"
    else:
        alignment_status = "no_numeric_or_role_context"

    single_numeric = len(phase_ids) == 1 and len(numeric_records) == 1 and len(records) == 1
    single = records[0] if single_numeric else {}
    basis = _unique_texts(pd.Series([row.get("indicative_evidence_basis") for row in records], dtype=object))
    levels = _unique_texts(pd.Series([row.get("indicative_evidence_level") for row in records], dtype=object))
    sales_statuses = _unique_texts(pd.Series([row.get("indicative_sales_use_status") for row in records], dtype=object))
    source_count = sum(int(row.get("indicative_evidence_source_count") or 0) for row in records) if records else 0
    return {
        "phase_role_evidence_count": int(role_count),
        "indicative_ownership_context_status": context_status,
        "indicative_phase_ownership_context_json": json.dumps(records, ensure_ascii=False, sort_keys=True),
        "indicative_ownership_pct": single.get("indicative_ownership_pct"),
        "indicative_ownership_pct_low": single.get("indicative_ownership_pct_low"),
        "indicative_ownership_pct_high": single.get("indicative_ownership_pct_high"),
        "indicative_numeric_consistency_status": single.get("indicative_numeric_consistency_status") if single else None,
        "indicative_evidence_basis": "; ".join(basis) or None,
        "indicative_evidence_level": "; ".join(levels) or None,
        "indicative_evidence_source_count": int(source_count),
        "indicative_sales_use_status": "; ".join(sales_statuses) or None,
        "indicative_ownership_role_alignment_status": alignment_status,
    }


def _pdf_context_for_cluster(
    cluster: pd.DataFrame,
    pdf_context: pd.DataFrame | None,
    *,
    phase_ids: list[str],
    phase_nos: dict[str, str | None],
    group_phase_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Attach source-page phase-token context to one BD cluster."""
    empty = {
        "bd_pdf_phase_context_status": "not_evaluated",
        "bd_pdf_phase_tokens": None,
        "bd_pdf_unmatched_phase_tokens": None,
        "bd_pdf_token_coverage_status": "not_evaluated",
        "bd_pdf_phase_candidate_ids": None,
        "bd_pdf_group_phase_candidate_ids": None,
        "bd_pdf_phase_snippets": None,
        "bd_pdf_context_source_urls": None,
        "bd_pdf_context_pages": None,
        "phase_context_concordance_status": "no_pdf_phase_context",
    }
    if pdf_context is None or pdf_context.empty or cluster.empty:
        return empty
    permit_values = {
        _text(value).casefold()
        for value in cluster.get("bd_permit_number", pd.Series(dtype=object))
        if _text(value)
    }
    refs = {
        (_text(row.get("bd_source_url")), _page_key(row.get("bd_source_pdf_page")))
        for row in cluster.to_dict("records")
        if _text(row.get("bd_source_url")) and _page_key(row.get("bd_source_pdf_page"))
    }
    site_keys = {_address_key(value) for value in cluster.get("bd_site_address", pd.Series(dtype=object)) if _address_key(value)}
    selected: list[dict[str, Any]] = []
    for record in pdf_context.to_dict("records"):
        permit = _text(record.get("bd_pdf_permit_number"))
        ref = (_text(record.get("bd_pdf_source_url")), _page_key(record.get("bd_pdf_source_page")))
        site = _address_key(record.get("bd_pdf_site_address"))
        permit_match = bool(permit and permit.casefold() in permit_values)
        ref_match = bool(ref[0] and ref[1] and ref in refs)
        site_match = bool(site and site in site_keys)
        stage_match = _text(record.get("bd_pdf_permit_stage")) in set(
            cluster.get("bd_permit_stage", pd.Series(dtype=object)).map(_text)
        )
        # A permit number can recur on several digest pages as later
        # observations.  When the candidate cluster has source URL/page
        # references, require that page reference rather than unioning every
        # page carrying the same permit number; otherwise unrelated phase
        # tokens on another issue would create a false conflict/narrowing.
        if refs:
            selected_match = ref_match
        else:
            selected_match = permit_match or (site_match and stage_match)
        if selected_match:
            selected.append(record)
    if not selected:
        return empty
    statuses = _unique_texts(pd.Series([row.get("bd_pdf_context_status") for row in selected], dtype=object))
    tokens: list[str] = []
    snippets: list[str] = []
    urls: list[str] = []
    pages: list[str] = []
    for record in selected:
        for token in (_text(record.get("bd_pdf_phase_tokens")) or "").split("; "):
            if token and token not in tokens:
                tokens.append(token)
        for snippet in (_text(record.get("bd_pdf_phase_snippets")) or "").split(" | "):
            if snippet and snippet not in snippets:
                snippets.append(snippet)
        for value in (_text(record.get("bd_pdf_source_url")),):
            if value and value not in urls:
                urls.append(value)
        page = _page_key(record.get("bd_pdf_source_page"))
        if page and page not in pages:
            pages.append(page)
    matched_ids: list[str] = []
    group_ids = group_phase_ids or phase_ids
    group_matched_ids: list[str] = []
    token_keys = {_phase_no_key(token) for token in tokens if _phase_no_key(token)}
    candidate_phase_no_keys = {
        _phase_no_key(phase_nos.get(phase_id))
        for phase_id in phase_ids
        if _phase_no_key(phase_nos.get(phase_id))
    }
    unmatched_tokens = [
        token for token in tokens
        if _phase_no_key(token) and _phase_no_key(token) not in candidate_phase_no_keys
    ]
    if not tokens:
        token_coverage_status = "no_pdf_phase_tokens"
    elif not candidate_phase_no_keys:
        token_coverage_status = "no_candidate_phase_numbers"
    elif unmatched_tokens:
        token_coverage_status = "some_pdf_phase_tokens_not_in_candidate_set"
    else:
        token_coverage_status = "all_pdf_phase_tokens_in_candidate_set"
    for phase_id in phase_ids:
        phase_no = _phase_no_key(phase_nos.get(phase_id))
        if phase_no and phase_no in token_keys:
            matched_ids.append(phase_id)
    for phase_id in group_ids:
        phase_no = _phase_no_key(phase_nos.get(phase_id))
        if phase_no and phase_no in token_keys:
            group_matched_ids.append(phase_id)
    candidate_families = {
        _phase_family_key(value)
        for value in phase_nos.values()
        if _phase_family_key(value)
    }
    token_families = {
        _phase_family_key(value)
        for value in tokens
        if _phase_family_key(value)
    }
    if group_matched_ids and not matched_ids:
        concordance = "pdf_context_points_to_other_group_phase"
    elif not candidate_phase_no_keys and tokens:
        concordance = "pdf_phase_tokens_not_comparable_no_candidate_phase_nos"
    elif tokens and not candidate_families.intersection(token_families):
        concordance = "pdf_phase_tokens_not_comparable_phase_label_format"
    elif matched_ids and len(matched_ids) < len(phase_ids):
        concordance = "pdf_context_narrows_candidate_set"
    elif matched_ids:
        concordance = "pdf_context_agrees_with_candidate_set"
    elif tokens and candidate_families.intersection(token_families):
        # A token such as ``1A(1)`` shares the broad ``1A`` family with a
        # candidate such as ``1A(2)`` but is not the same SRPE phase.  Keep it
        # separate from a true unrelated-number conflict; the BD page may be
        # documenting an earlier/non-residential subphase at the same lot.
        concordance = "pdf_context_same_family_different_phase_variant"
    elif tokens:
        concordance = "pdf_phase_tokens_do_not_match_candidate_set"
    else:
        concordance = "pdf_page_has_no_phase_tokens"
    if any(status == "permit_page_phase_tokens_observed" for status in statuses):
        context_status = "permit_page_phase_tokens_observed"
    elif any("phase_tokens_observed" in status for status in statuses):
        context_status = "page_phase_tokens_observed"
    elif any(status == "page_read_error" for status in statuses):
        context_status = "page_read_error"
    else:
        context_status = "permit_page_no_phase_tokens_observed"
    return {
        "bd_pdf_phase_context_status": context_status,
        "bd_pdf_phase_tokens": "; ".join(tokens) or None,
        "bd_pdf_unmatched_phase_tokens": "; ".join(unmatched_tokens) or None,
        "bd_pdf_token_coverage_status": token_coverage_status,
        "bd_pdf_phase_candidate_ids": "; ".join(matched_ids) or None,
        "bd_pdf_group_phase_candidate_ids": "; ".join(group_matched_ids) or None,
        "bd_pdf_phase_snippets": " | ".join(snippets) or None,
        "bd_pdf_context_source_urls": "; ".join(urls) or None,
        "bd_pdf_context_pages": "; ".join(pages) or None,
        "phase_context_concordance_status": concordance,
    }


def _schedule_candidate_contexts(
    group_row: Mapping[str, Any],
    phase_ids: list[str],
) -> list[dict[str, Any]]:
    """Return schedule contexts, or one explicit no-schedule fallback row."""
    group_id = _text(group_row.get("phase_group_id")) or "missing-group"
    contexts = _json_records(group_row.get("schedule_group_context_json"))
    result: list[dict[str, Any]] = []
    for index, context in enumerate(contexts):
        raw_ids = context.get("srpe_phase_ids")
        if isinstance(raw_ids, str):
            context_ids = [item.strip() for item in raw_ids.split(",") if item.strip()]
        elif isinstance(raw_ids, list):
            context_ids = [_text(item) for item in raw_ids]
            context_ids = [item for item in context_ids if item]
        else:
            context_ids = []
        # Keep only phase IDs that actually belong to this address group.  A
        # malformed schedule crosswalk must not inject a foreign phase into a
        # candidate set.
        context_ids = [phase_id for phase_id in context_ids if phase_id in phase_ids]
        if not context_ids:
            context_ids = list(phase_ids)
        result.append(
            {
                **context,
                "candidate_context_key": _schedule_context_key(group_id, index),
                "candidate_context_status": (
                    "official_schedule_phase_group_context"
                    if len(context_ids) < len(phase_ids)
                    else "official_schedule_group_context_not_phase_unique"
                ),
                "candidate_phase_ids": context_ids,
            }
        )
    if result:
        return result
    return [
        {
            "candidate_context_key": f"{group_id}::no-schedule-context",
            "candidate_context_status": "no_schedule_context",
            "candidate_phase_ids": list(phase_ids),
        }
    ]


def build_shkp_bd_phase_permit_candidate_evidence(
    crosswalk: pd.DataFrame,
    phase_group_evidence: pd.DataFrame | None = None,
    *,
    schedule_crosswalk: pd.DataFrame | None = None,
    phase_role_evidence: pd.DataFrame | None = None,
    ownership_roster: pd.DataFrame | None = None,
    bd_history: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a primary-document review queue without assigning permits.

    The output is intentionally a candidate evidence table rather than a
    resolved entity table.  One row combines a shared-address group, one
    official SHKP completion-schedule grouping (when present), and one BD
    permit/applicant/stage/site cluster.  Schedule labels and issuer-reported
    Group's Interest values narrow the review set, while SRPE/SHKP role URLs
    and BD PDF URLs make the next manual check reproducible.  A permit is
    never assigned to a phase and no ownership percentage is promoted.
    """
    source = crosswalk.copy() if crosswalk is not None else pd.DataFrame()
    groups = phase_group_evidence.copy() if phase_group_evidence is not None else build_shkp_bd_phase_group_evidence(source)
    role_by_phase = _role_context_by_phase(phase_role_evidence)
    ownership_by_phase = _ownership_roster_by_phase(ownership_roster)
    schedule_urls = _schedule_urls_by_phase(schedule_crosswalk)
    pdf_context = build_shkp_bd_pdf_phase_context(bd_history, source) if bd_history is not None else pd.DataFrame()
    lineage = {
        "lineage_type": "research_shkp_bd_phase_permit_candidate_evidence",
        "source_dataset": DATASET_NAME,
        "source_datasets": [
            DATASET_NAME,
            PHASE_GROUP_EVIDENCE_DATASET,
            *( ["shkp_completion_schedule_crosswalk"] if schedule_crosswalk is not None else [] ),
            *( ["shkp_phase_role_evidence"] if phase_role_evidence is not None else [] ),
            *( ["shkp_indicative_ownership_roster"] if ownership_roster is not None else [] ),
            *( ["bd_project_lifecycle_history"] if bd_history is not None else [] ),
        ],
        "ownership_promotion": "blocked_address_only",
        "permit_attribution": "blocked_address_only",
        "external_fetch": False,
        "row_policy": "one_phase_group_x_schedule_context_x_bd_cluster_no_phase_permit_assignment",
    }
    raw_snapshots = list(dict.fromkeys(
        [str(value) for frame in (source, groups, schedule_crosswalk, phase_role_evidence, ownership_roster, bd_history, pdf_context)
         if frame is not None for value in frame.attrs.get("raw_snapshots", []) if value]
    ))
    source_urls = list(dict.fromkeys(
        [str(value) for frame in (source, groups, schedule_crosswalk, phase_role_evidence, ownership_roster, bd_history, pdf_context)
         if frame is not None for value in frame.attrs.get("source_urls", []) if value]
    ))
    if groups.empty:
        result = pd.DataFrame(columns=PHASE_PERMIT_CANDIDATE_EVIDENCE_COLUMNS)
        result.attrs.update(raw_snapshots=raw_snapshots, source_urls=source_urls, lineage_metadata=lineage)
        return result

    if not source.empty:
        source["_group_key"] = [
            _phase_group_key(row.get("srpe_development_id"), row.get("srpe_address_en"), index)
            for index, row in source.iterrows()
        ]
    else:
        source["_group_key"] = pd.Series(dtype=object)

    rows: list[dict[str, Any]] = []
    for group_record in groups.to_dict("records"):
        group_id = _text(group_record.get("phase_group_id")) or "missing-group"
        phase_ids = [item.strip() for item in str(group_record.get("srpe_phase_ids") or "").split(";") if item.strip()]
        phase_context = _json_records(group_record.get("srpe_phase_order_context_json"))
        phase_by_id = {
            _text(item.get("srpe_development_id")): item
            for item in phase_context
            if _text(item.get("srpe_development_id"))
        }
        phase_names = {
            phase_id: _text(phase_by_id.get(phase_id, {}).get("phase_name"))
            for phase_id in phase_ids
        }
        phase_nos = {
            phase_id: _text(phase_by_id.get(phase_id, {}).get("phase_no"))
            for phase_id in phase_ids
        }
        group_source = source.loc[source["_group_key"].eq(group_id)].copy() if not source.empty else pd.DataFrame()
        matched = group_source.loc[
            group_source.get("bd_match_method", pd.Series(index=group_source.index, dtype=object)).isin(
                ["address_exact", "address_contains"]
            )
        ].copy() if not group_source.empty else pd.DataFrame()
        clusters: list[pd.DataFrame] = []
        if matched.empty:
            clusters = [matched]
        else:
            cluster_columns = [
                "bd_match_method",
                "bd_permit_stage",
                "bd_permit_number",
                "bd_site_address",
                "bd_applicant",
            ]
            cluster_source = matched.copy()
            grouping_columns: list[str] = []
            for column in cluster_columns:
                grouping_column = f"_candidate_{column}"
                cluster_source[grouping_column] = cluster_source.get(
                    column, pd.Series(index=cluster_source.index, dtype=object)
                ).map(_text).fillna("__missing__")
                grouping_columns.append(grouping_column)
            clusters = [frame for _, frame in cluster_source.groupby(grouping_columns, sort=True, dropna=False)]

        for context in _schedule_candidate_contexts(group_record, phase_ids):
            candidate_ids = [item for item in context.get("candidate_phase_ids", []) if item in phase_ids]
            if not candidate_ids:
                candidate_ids = list(phase_ids)
            context_names = [phase_names.get(item) for item in candidate_ids if phase_names.get(item)]
            context_nos = [phase_nos.get(item) for item in candidate_ids if phase_nos.get(item)]
            role_context = _phase_role_context(candidate_ids, role_by_phase)
            ownership_context = _indicative_ownership_context(
                candidate_ids,
                ownership_by_phase,
                role_by_phase,
            )
            schedule_urls_for_context = list(schedule_urls.get(candidate_ids[0], [])) if candidate_ids else []
            for phase_id in candidate_ids[1:]:
                for url in schedule_urls.get(phase_id, []):
                    if url not in schedule_urls_for_context:
                        schedule_urls_for_context.append(url)

            for cluster in clusters:
                method = _text(cluster.iloc[0].get("bd_match_method")) if not cluster.empty else None
                stage = _text(cluster.iloc[0].get("bd_permit_stage")) if not cluster.empty else None
                permit_number = _text(cluster.iloc[0].get("bd_permit_number")) if not cluster.empty else None
                site_address = _text(cluster.iloc[0].get("bd_site_address")) if not cluster.empty else None
                applicant_values = _unique_texts(cluster.get("bd_applicant", pd.Series(dtype=object))) if not cluster.empty else []
                digest_start, digest_end = _month_bounds(cluster.get("digest_month", pd.Series(dtype=object))) if not cluster.empty else (None, None)
                permit_year = _permit_year(permit_number)
                schedule_date = _text(context.get("schedule_date"))
                parsed_interest_pct = pd.to_numeric(
                    pd.Series([context.get("group_interest_pct")]), errors="coerce"
                ).iloc[0]
                schedule_interest_pct = None if pd.isna(parsed_interest_pct) else float(parsed_interest_pct)
                schedule_year = None
                if schedule_date:
                    parsed_schedule = pd.to_datetime(schedule_date, errors="coerce")
                    if not pd.isna(parsed_schedule):
                        schedule_year = int(parsed_schedule.year)
                if permit_year is None or schedule_year is None:
                    temporal_status = "no_comparable_year_context"
                    temporal_detail = "Schedule date or permit-number year is unavailable; no timing inference is made."
                elif schedule_year == permit_year:
                    temporal_status = "same_year_context_only"
                    temporal_detail = "Schedule date and permit-number year share a calendar year; this is not an event-date match."
                elif schedule_year < permit_year:
                    temporal_status = "schedule_precedes_permit_year_context"
                    temporal_detail = "Schedule date precedes the observed permit-number year; publication and permit dates remain distinct."
                else:
                    temporal_status = "schedule_follows_permit_year_context"
                    temporal_detail = "Schedule date follows the observed permit-number year; no phase assignment or permit date is inferred."

                pdf_phase_context = _pdf_context_for_cluster(
                    cluster,
                    pdf_context,
                    phase_ids=candidate_ids,
                    phase_nos=phase_nos,
                    group_phase_ids=phase_ids,
                )
                pdf_concordance = pdf_phase_context["phase_context_concordance_status"]
                if pdf_concordance in {
                    "pdf_context_agrees_with_candidate_set",
                    "pdf_context_narrows_candidate_set",
                }:
                    phase_context_review_status = "primary_pdf_phase_context_supported_not_assigned"
                    phase_context_review_basis = "primary_bd_pdf_phase_token_and_schedule_context"
                    reviewed_phase_ids = _split_phase_ids(pdf_phase_context.get("bd_pdf_phase_candidate_ids"))
                elif pdf_concordance == "pdf_context_points_to_other_group_phase":
                    phase_context_review_status = "primary_pdf_points_to_other_group_phase_not_assigned"
                    phase_context_review_basis = "primary_bd_pdf_group_phase_token_context"
                    reviewed_phase_ids = _split_phase_ids(pdf_phase_context.get("bd_pdf_group_phase_candidate_ids"))
                elif pdf_concordance == "pdf_context_same_family_different_phase_variant":
                    phase_context_review_status = "same_family_phase_variant_review"
                    phase_context_review_basis = "primary_bd_pdf_same_family_variant_token"
                    reviewed_phase_ids = []
                else:
                    phase_context_review_status = "unresolved_primary_document_context"
                    phase_context_review_basis = "no_phase_specific_primary_pdf_concordance"
                    reviewed_phase_ids = []
                group_status = _text(group_record.get("group_resolution_status")) or "unknown_group"
                if not method:
                    resolution_status = "no_bd_candidate_observed"
                    priority = "P2"
                    action = "retain_no_bd_candidate_and_check_historical_source_coverage"
                elif len(phase_ids) > 1 or group_status == "shared_address_group":
                    if pdf_phase_context["phase_context_concordance_status"] == "pdf_context_narrows_candidate_set":
                        resolution_status = "primary_pdf_phase_candidate_not_verified"
                    elif pdf_phase_context["phase_context_concordance_status"] == "pdf_context_same_family_different_phase_variant":
                        resolution_status = "primary_pdf_other_phase_variant_review"
                    elif pdf_phase_context["phase_context_concordance_status"] == "pdf_phase_tokens_do_not_match_candidate_set":
                        resolution_status = "primary_pdf_schedule_conflict_review"
                    elif (
                        pdf_phase_context["phase_context_concordance_status"] == "pdf_context_agrees_with_candidate_set"
                        and context.get("candidate_context_status") == "official_schedule_phase_group_context"
                    ):
                        resolution_status = "primary_pdf_schedule_concordant_candidate_not_verified"
                    else:
                        resolution_status = (
                            "schedule_subgroup_candidate_not_verified"
                            if context.get("candidate_context_status") == "official_schedule_phase_group_context"
                            else "shared_address_candidate_not_verified"
                        )
                    priority = "P0"
                    action = "open_srpe_phase_lot_and_primary_bd_pdf_review_before_any_permit_assignment"
                else:
                    resolution_status = (
                        "primary_pdf_phase_candidate_not_verified"
                        if pdf_phase_context["phase_context_concordance_status"] == "pdf_context_agrees_with_candidate_set"
                        else "single_phase_permit_candidate_not_verified"
                    )
                    priority = "P1"
                    action = "verify_bd_applicant_permit_cluster_against_srpe_phase_documents"

                bd_source_urls = _unique_texts(cluster.get("bd_source_url", pd.Series(dtype=object))) if not cluster.empty else []
                bd_pages = _unique_texts(cluster.get("bd_source_pdf_page", pd.Series(dtype=object))) if not cluster.empty else []
                srpe_source_urls = _unique_texts(group_source.get("srpe_source_url", pd.Series(dtype=object))) if not group_source.empty else []
                shkp_source_urls = _unique_texts(group_source.get("shkp_source_url", pd.Series(dtype=object))) if not group_source.empty else []
                all_urls = list(dict.fromkeys([
                    *schedule_urls_for_context,
                    *srpe_source_urls,
                    *shkp_source_urls,
                    *bd_source_urls,
                    *[url for url in (_text(group_record.get("source_urls", "")) or "").split("; ") if url],
                    *[url for url in (role_context.get("phase_role_source_urls") or "").split("; ") if url],
                ]))
                rows.append(
                    {
                        "phase_group_id": group_id,
                        "srpe_address_en": _text(group_record.get("srpe_address_en")),
                        "group_resolution_status": group_status,
                        "group_evidence_status": _text(group_record.get("group_evidence_status")),
                        "candidate_context_key": context.get("candidate_context_key"),
                        "candidate_context_status": context.get("candidate_context_status"),
                        "candidate_phase_ids": "; ".join(candidate_ids) or None,
                        "candidate_phase_names": "; ".join(context_names) or None,
                        "candidate_phase_nos": "; ".join(context_nos) or None,
                        "candidate_phase_count": int(len(candidate_ids)),
                        "schedule_date": schedule_date,
                        "schedule_project_row_no": _text(context.get("project_row_no")),
                        "schedule_lot_description": _text(context.get("lot_description")),
                        "schedule_project_label": _text(context.get("project_label")),
                        "schedule_completion_window": _text(context.get("completion_window")),
                        "schedule_group_interest_raw": _text(context.get("group_interest_raw")),
                        "schedule_group_interest_pct": schedule_interest_pct,
                        "schedule_match_status": (
                            "official_schedule_grouped" if schedule_date else "not_observed"
                        ),
                        "schedule_candidate_count": int(len(candidate_ids)) if schedule_date else 0,
                        "schedule_source_urls": "; ".join(schedule_urls_for_context) or None,
                        **pdf_phase_context,
                        "phase_context_review_status": phase_context_review_status,
                        "phase_context_review_basis": phase_context_review_basis,
                        "phase_context_reviewed_candidate_ids": "; ".join(reviewed_phase_ids) or None,
                        "phase_context_reviewed_candidate_count": int(len(reviewed_phase_ids)),
                        **role_context,
                        **ownership_context,
                        "bd_match_method": method or "none",
                        "bd_permit_stage": stage,
                        "bd_permit_number": permit_number,
                        "bd_permit_year": permit_year,
                        "bd_site_address": site_address,
                        "bd_applicants": "; ".join(applicant_values) or None,
                        "bd_applicant_quality_status": _applicant_quality_status("; ".join(applicant_values) or None),
                        "bd_history_row_count": int(len(cluster)),
                        "bd_digest_month_first_observed": digest_start,
                        "bd_digest_month_last_observed": digest_end,
                        "bd_parser_confidences": "; ".join(_unique_texts(cluster.get("bd_parser_confidence", pd.Series(dtype=object)))) or None,
                        "bd_parser_quality_flags": "; ".join(_unique_texts(cluster.get("bd_parser_quality_flag", pd.Series(dtype=object)))) or None,
                        "bd_source_urls": "; ".join(bd_source_urls) or None,
                        "bd_source_pdf_pages": "; ".join(bd_pages) or None,
                        "temporal_context_status": temporal_status,
                        "temporal_context_detail": temporal_detail,
                        "resolution_status": resolution_status,
                        "resolution_priority": priority,
                        "review_action": action,
                        "ownership_promotion_status": "blocked_address_only",
                        "permit_attribution_status": "blocked_address_only",
                        "research_only": True,
                        "source_urls": "; ".join(all_urls) or None,
                        "review_caveat": (
                            "Candidate evidence only. Official schedule labels/Group's Interest and project-site role fields "
                            "are corroborating context, not phase-level ownership. BD digest months are publication/observation "
                            "months; a permit-number year is not a permit date. Review the SRPE detail/lot and source BD PDF "
                            "before any permit attribution, unit use, or ownership promotion."
                        ),
                    }
                )

    result = pd.DataFrame(rows, columns=PHASE_PERMIT_CANDIDATE_EVIDENCE_COLUMNS)
    if not result.empty:
        result = result.sort_values(
            ["resolution_priority", "bd_history_row_count", "phase_group_id", "candidate_context_key"],
            ascending=[True, False, True, True],
            na_position="last",
        ).reset_index(drop=True)
    result.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=list(dict.fromkeys(source_urls)),
        lineage_metadata={
            **lineage,
            "candidate_rows": int(len(result)),
            "phase_group_count": int(result["phase_group_id"].nunique()) if not result.empty else 0,
            "blocked_row_count": int(result["ownership_promotion_status"].eq("blocked_address_only").sum()) if not result.empty else 0,
        },
    )
    return result


def _split_phase_ids(value: Any) -> list[str]:
    """Split a semicolon-delimited phase-id field without inventing IDs."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return [item.strip() for item in str(value).split(";") if item.strip()]


def build_shkp_bd_phase_permit_reconciliation(
    phase_permit_candidates: pd.DataFrame | None,
) -> pd.DataFrame:
    """Classify primary-document concordance without assigning a permit.

    The candidate evidence table intentionally stops before a phase-to-permit
    assertion.  This derived layer makes the remaining evidence legible:

    * ``single_phase_primary_document_concordant_needs_review`` means one
      phase remains in the candidate set and the BD page token agrees;
    * ``phase_set_primary_document_concordant_needs_review`` means the page
      agrees with a multi-phase set (for example 1A/1B), not one permit per
      phase;
    * ``phase_set_narrowed_by_primary_document_needs_review`` records a
      smaller subset when the page token narrows the group;
    * conflict, non-comparable label, and no-token states stay explicit.

    Every row is research-only and keeps both attribution gates blocked.  The
    ``resolved_phase_candidate_ids`` field is a review candidate set, never a
    legal permit assignment.
    """
    source = phase_permit_candidates.copy() if phase_permit_candidates is not None else pd.DataFrame()
    lineage = {
        "lineage_type": "research_shkp_bd_phase_permit_reconciliation",
        "source_dataset": PHASE_PERMIT_CANDIDATE_EVIDENCE_DATASET,
        "source_datasets": [PHASE_PERMIT_CANDIDATE_EVIDENCE_DATASET],
        "ownership_promotion": "blocked_address_only",
        "permit_attribution": "blocked_address_only",
        "external_fetch": False,
        "row_policy": "primary-document-and-schedule-concordance-without-permit-assignment",
    }
    if source.empty:
        result = pd.DataFrame(columns=PHASE_PERMIT_RECONCILIATION_COLUMNS)
        result.attrs.update(
            raw_snapshots=list(source.attrs.get("raw_snapshots", [])),
            source_urls=list(source.attrs.get("source_urls", [])),
            lineage_metadata=lineage,
        )
        return result

    rows: list[dict[str, Any]] = []
    for index, record in enumerate(source.to_dict("records")):
        candidate_ids = _split_phase_ids(record.get("candidate_phase_ids"))
        pdf_ids = _split_phase_ids(record.get("bd_pdf_phase_candidate_ids"))
        group_pdf_ids = _split_phase_ids(record.get("bd_pdf_group_phase_candidate_ids"))
        concordance = _text(record.get("phase_context_concordance_status")) or "no_pdf_phase_context"
        candidate_count = len(candidate_ids)
        resolved_ids: list[str] = []
        if concordance == "pdf_context_agrees_with_candidate_set":
            resolved_ids = pdf_ids or candidate_ids
            if candidate_count == 1:
                status = "single_phase_primary_document_concordant_needs_review"
                strength = "primary_pdf_and_single_phase_context"
            else:
                status = "phase_set_primary_document_concordant_needs_review"
                strength = "primary_pdf_phase_set_context"
        elif concordance == "pdf_context_narrows_candidate_set":
            resolved_ids = pdf_ids or group_pdf_ids
            status = "phase_set_narrowed_by_primary_document_needs_review"
            strength = "primary_pdf_narrowed_context"
        elif concordance == "pdf_phase_tokens_do_not_match_candidate_set":
            status = "primary_document_phase_conflict_review"
            strength = "primary_pdf_conflict_flag"
        elif concordance == "pdf_context_same_family_different_phase_variant":
            status = "primary_document_same_family_different_phase_review"
            strength = "primary_pdf_phase_variant_context"
        elif concordance in {
            "pdf_phase_tokens_not_comparable_phase_label_format",
            "pdf_phase_tokens_not_comparable_no_candidate_phase_nos",
        }:
            status = "primary_document_label_format_review"
            strength = "primary_pdf_non_comparable_context"
        elif concordance == "pdf_context_points_to_other_group_phase":
            resolved_ids = group_pdf_ids
            status = "primary_document_points_to_other_group_phase_review"
            strength = "primary_pdf_cross_group_context"
        elif concordance == "pdf_page_has_no_phase_tokens":
            if _text(record.get("candidate_context_status")) == "official_schedule_phase_group_context":
                status = "official_schedule_phase_set_needs_primary_pdf"
                strength = "official_schedule_phase_context_without_pdf_token"
            else:
                status = "primary_document_no_phase_token_review"
                strength = "primary_pdf_page_without_phase_token"
        elif concordance == "no_pdf_phase_context":
            if _text(record.get("candidate_context_status")) == "official_schedule_phase_group_context":
                status = "official_schedule_phase_set_needs_primary_pdf"
                strength = "official_schedule_phase_context_without_pdf_page"
            else:
                status = "schedule_or_address_only_review"
                strength = "schedule_or_address_context_only"
        else:
            status = "primary_document_unclassified_review"
            strength = "unclassified_primary_context"

        if not resolved_ids and status not in {
            "primary_document_phase_conflict_review",
            "primary_document_label_format_review",
            "primary_document_no_phase_token_review",
            "schedule_or_address_only_review",
            "primary_document_unclassified_review",
        }:
            resolved_ids = candidate_ids

        if status in {
            "single_phase_primary_document_concordant_needs_review",
            "phase_set_primary_document_concordant_needs_review",
            "phase_set_narrowed_by_primary_document_needs_review",
        }:
            phase_context_review_status = "phase_context_supported_not_assigned"
            phase_context_review_basis = (
                "primary_bd_pdf_phase_token_and_official_schedule_context"
            )
            reviewed_phase_ids = resolved_ids or candidate_ids
        elif status == "primary_document_points_to_other_group_phase_review":
            phase_context_review_status = "phase_context_points_to_other_group_phase_not_assigned"
            phase_context_review_basis = "primary_bd_pdf_group_phase_token_context"
            reviewed_phase_ids = group_pdf_ids
        elif status == "primary_document_same_family_different_phase_review":
            phase_context_review_status = "same_family_phase_variant_review"
            phase_context_review_basis = "primary_bd_pdf_same_family_variant_token"
            reviewed_phase_ids = []
        elif status == "official_schedule_phase_set_needs_primary_pdf":
            phase_context_review_status = "schedule_phase_set_without_primary_pdf"
            phase_context_review_basis = "official_schedule_phase_set_only"
            reviewed_phase_ids = []
        else:
            phase_context_review_status = "unresolved_primary_document_context"
            phase_context_review_basis = "no_phase_specific_primary_pdf_concordance"
            reviewed_phase_ids = []

        if status == "single_phase_primary_document_concordant_needs_review":
            action = "verify_single_phase_permit_against_srpe_lot_and_source_pdf_before_attribution"
        elif status == "phase_set_primary_document_concordant_needs_review":
            action = "retain_phase_set_and_review_phase_specific_lot_schedule_before_assignment"
        elif status == "phase_set_narrowed_by_primary_document_needs_review":
            action = "review_narrowed_phase_subset_against_srpe_lot_and_source_pdf"
        elif status == "primary_document_phase_conflict_review":
            action = "inspect_conflicting_primary_pdf_page_and_schedule_version"
        elif status == "primary_document_same_family_different_phase_review":
            action = "exclude_or_route_same_family_subphase_before_residential_phase_assignment"
        elif status == "official_schedule_phase_set_needs_primary_pdf":
            action = "use_official_schedule_phase_set_to_prioritize_primary_bd_pdf_or_lot_review"
        elif status == "primary_document_points_to_other_group_phase_review":
            action = "route_to_other_phase_in_same_address_group_without_reassignment"
        else:
            action = "retain_context_only_and_request_phase_specific_primary_document"

        source_urls = _unique_texts(pd.Series([
            record.get("source_urls"),
            record.get("bd_pdf_context_source_urls"),
            record.get("schedule_source_urls"),
            record.get("bd_source_urls"),
        ]))
        rows.append(
            {
                "reconciliation_id": f"{_text(record.get('phase_group_id')) or 'missing-group'}::{_text(record.get('candidate_context_key')) or index}",
                "phase_group_id": _text(record.get("phase_group_id")),
                "candidate_context_key": _text(record.get("candidate_context_key")),
                "srpe_address_en": _text(record.get("srpe_address_en")),
                "candidate_phase_ids": "; ".join(candidate_ids) or None,
                "candidate_phase_names": _text(record.get("candidate_phase_names")),
                "candidate_phase_nos": _text(record.get("candidate_phase_nos")),
                "candidate_phase_count": candidate_count,
                "resolved_phase_candidate_ids": "; ".join(resolved_ids) or None,
                "resolved_phase_candidate_count": len(resolved_ids),
                "bd_permit_stage": _text(record.get("bd_permit_stage")),
                "bd_permit_number": _text(record.get("bd_permit_number")),
                "bd_permit_year": record.get("bd_permit_year"),
                "bd_applicants": _text(record.get("bd_applicants")),
                "schedule_project_label": _text(record.get("schedule_project_label")),
                "schedule_lot_description": _text(record.get("schedule_lot_description")),
                "schedule_group_interest_raw": _text(record.get("schedule_group_interest_raw")),
                "schedule_group_interest_pct": record.get("schedule_group_interest_pct"),
                "candidate_context_status": _text(record.get("candidate_context_status")),
                "bd_pdf_phase_tokens": _text(record.get("bd_pdf_phase_tokens")),
                "bd_pdf_unmatched_phase_tokens": _text(record.get("bd_pdf_unmatched_phase_tokens")),
                "bd_pdf_token_coverage_status": _text(record.get("bd_pdf_token_coverage_status")),
                "bd_pdf_phase_candidate_ids": _text(record.get("bd_pdf_phase_candidate_ids")),
                "bd_pdf_group_phase_candidate_ids": _text(record.get("bd_pdf_group_phase_candidate_ids")),
                "phase_context_concordance_status": concordance,
                "phase_context_review_status": phase_context_review_status,
                "phase_context_review_basis": phase_context_review_basis,
                "phase_context_reviewed_candidate_ids": "; ".join(reviewed_phase_ids) or None,
                "phase_context_reviewed_candidate_count": len(reviewed_phase_ids),
                "phase_role_evidence_count": record.get("phase_role_evidence_count"),
                "indicative_ownership_context_status": _text(record.get("indicative_ownership_context_status")) or "not_observed",
                "indicative_phase_ownership_context_json": _text(record.get("indicative_phase_ownership_context_json")),
                "indicative_ownership_pct": record.get("indicative_ownership_pct"),
                "indicative_ownership_pct_low": record.get("indicative_ownership_pct_low"),
                "indicative_ownership_pct_high": record.get("indicative_ownership_pct_high"),
                "indicative_numeric_consistency_status": _text(record.get("indicative_numeric_consistency_status")),
                "indicative_evidence_basis": _text(record.get("indicative_evidence_basis")),
                "indicative_evidence_level": _text(record.get("indicative_evidence_level")),
                "indicative_evidence_source_count": record.get("indicative_evidence_source_count"),
                "indicative_sales_use_status": _text(record.get("indicative_sales_use_status")),
                "indicative_ownership_role_alignment_status": _text(record.get("indicative_ownership_role_alignment_status")) or "no_numeric_or_role_context",
                "reconciliation_status": status,
                "evidence_strength": strength,
                "permit_assignment_status": "blocked_address_only",
                "review_action": action,
                "source_urls": "; ".join(source_urls) or None,
                "ownership_promotion_status": "blocked_address_only",
                "permit_attribution_status": "blocked_address_only",
                "research_only": True,
                "review_caveat": (
                    "Research-only primary-document reconciliation. Resolved phase IDs are candidate sets only; "
                    "even a single-phase concordant page does not establish a legal permit-to-phase assignment, "
                    "ownership percentage, effective interval or attributable units."
                ),
            }
        )

    result = pd.DataFrame(rows, columns=PHASE_PERMIT_RECONCILIATION_COLUMNS)
    result.attrs.update(
        raw_snapshots=list(source.attrs.get("raw_snapshots", [])),
        source_urls=list(source.attrs.get("source_urls", [])),
        lineage_metadata={
            **lineage,
            "reconciliation_rows": int(len(result)),
            "status_counts": result["reconciliation_status"].value_counts().to_dict(),
        },
    )
    return result


def build_shkp_bd_phase_ownership_review(
    review_queue: pd.DataFrame | None,
    phase_permit_candidates: pd.DataFrame | None,
    phase_permit_reconciliation: pd.DataFrame | None,
    *,
    ownership_roster: pd.DataFrame | None = None,
    phase_role_evidence: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build one compact, non-promoting review row per SHKP/SRPE phase.

    The detailed candidate and reconciliation tables are intentionally at
    phase-group/document grain.  This roll-up makes the phase-level evidence
    usable for review and rough modelling while keeping grouped phases
    separate in the JSON ownership context and never summing shared-address
    activity into an attributable total.
    """
    queue = review_queue.copy() if review_queue is not None else pd.DataFrame()
    candidates = phase_permit_candidates.copy() if phase_permit_candidates is not None else pd.DataFrame()
    reconciliation = phase_permit_reconciliation.copy() if phase_permit_reconciliation is not None else pd.DataFrame()
    ownership_by_phase = _ownership_roster_by_phase(ownership_roster)
    role_by_phase = _role_context_by_phase(phase_role_evidence)
    lineage = {
        "lineage_type": "research_shkp_bd_phase_ownership_review",
        "source_datasets": [
            ENTITY_RESOLUTION_REVIEW_QUEUE_DATASET,
            PHASE_PERMIT_CANDIDATE_EVIDENCE_DATASET,
            PHASE_PERMIT_RECONCILIATION_DATASET,
            *( ["shkp_indicative_ownership_roster"] if ownership_roster is not None else [] ),
            *( ["shkp_phase_role_evidence"] if phase_role_evidence is not None else [] ),
        ],
        "ownership_promotion": "blocked_address_only",
        "permit_attribution": "blocked_address_only",
        "external_fetch": False,
        "row_policy": "one_phase_rollup_without_shared_address_activity_attribution",
    }
    raw_snapshots = list(dict.fromkeys(
        [str(value) for frame in (queue, candidates, reconciliation, ownership_roster, phase_role_evidence)
         if frame is not None for value in frame.attrs.get("raw_snapshots", []) if value]
    ))
    source_urls = list(dict.fromkeys(
        [str(value) for frame in (queue, candidates, reconciliation, ownership_roster, phase_role_evidence)
         if frame is not None for value in frame.attrs.get("source_urls", []) if value]
    ))
    if queue.empty:
        result = pd.DataFrame(columns=PHASE_OWNERSHIP_REVIEW_COLUMNS)
        result.attrs.update(raw_snapshots=raw_snapshots, source_urls=source_urls, lineage_metadata=lineage)
        return result

    def _url_values(value: Any) -> list[str]:
        text = _text(value)
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        values = parsed if isinstance(parsed, list) else re.split(r";\s*", text)
        return [str(item).strip() for item in values if str(item).strip()]

    def _add_urls(target: list[str], *values: Any) -> None:
        for value in values:
            for url in _url_values(value):
                if url not in target:
                    target.append(url)

    phase_rows: dict[str, dict[str, Any]] = {}
    phase_urls: dict[str, list[str]] = {}
    for record in queue.to_dict("records"):
        phase_id = _text(record.get("srpe_development_id"))
        if not phase_id:
            continue
        history_count = pd.to_numeric(record.get("bd_history_row_count"), errors="coerce")
        permit_count = pd.to_numeric(record.get("bd_distinct_permit_number_count"), errors="coerce")
        phase_rows[phase_id] = {
            "srpe_development_id": phase_id,
            "marketing_name": _text(record.get("marketing_name")),
            "srpe_phase_name": _text(record.get("srpe_phase_name")),
            "srpe_address_en": _text(record.get("srpe_address_en")),
            "phase_group_id": _text(record.get("phase_group_id")),
            "phase_group_member_ids": _text(record.get("phase_group_member_ids")),
            "entity_resolution_status": _text(record.get("entity_resolution_status")) or "unmatched",
            "review_priority": _text(record.get("review_priority")) or "P2",
            "bd_history_row_count": int(history_count) if pd.notna(history_count) else 0,
            "bd_distinct_permit_number_count": int(permit_count) if pd.notna(permit_count) else 0,
        }
        phase_urls[phase_id] = []
        _add_urls(
            phase_urls[phase_id],
            record.get("bd_source_urls"),
            record.get("shkp_site_url"),
            record.get("shkp_site_url"),
        )

    # Keep review counts separate from the phase-level history count.  A
    # shared-address candidate may be visible under several phases; counts
    # below are evidence-row counts, never unit/activity attribution.
    stats: dict[str, dict[str, Any]] = {
        phase_id: {
            "bd_candidate_row_count": 0,
            "phase_context_supported_row_count": 0,
            "phase_context_other_group_row_count": 0,
            "phase_context_same_family_variant_row_count": 0,
            "phase_context_unresolved_row_count": 0,
            "reviewed_candidate_ids": [],
            "phase_role_source_urls": [],
            "source_urls": phase_urls.get(phase_id, []),
        }
        for phase_id in phase_rows
    }
    for record in candidates.to_dict("records"):
        phase_ids = _split_phase_ids(record.get("candidate_phase_ids"))
        if not phase_ids:
            phase_ids = _split_phase_ids(record.get("phase_context_reviewed_candidate_ids"))
        status = _text(record.get("phase_context_review_status")) or "unresolved_primary_document_context"
        reviewed_ids = _split_phase_ids(record.get("phase_context_reviewed_candidate_ids"))
        targeted_ids = set(reviewed_ids) if reviewed_ids and status in {
            "primary_pdf_phase_context_supported_not_assigned",
            "primary_pdf_points_to_other_group_phase_not_assigned",
        } else set(phase_ids)
        phase_iteration_ids = list(dict.fromkeys([*phase_ids, *reviewed_ids]))
        for phase_id in phase_iteration_ids:
            if phase_id not in stats:
                continue
            item = stats[phase_id]
            if phase_id in phase_ids:
                item["bd_candidate_row_count"] += 1
            if status == "primary_pdf_phase_context_supported_not_assigned" and phase_id in targeted_ids:
                item["phase_context_supported_row_count"] += 1
            elif status == "primary_pdf_points_to_other_group_phase_not_assigned" and phase_id in targeted_ids:
                item["phase_context_other_group_row_count"] += 1
            elif status == "same_family_phase_variant_review":
                item["phase_context_same_family_variant_row_count"] += 1
            else:
                item["phase_context_unresolved_row_count"] += 1
            for reviewed_id in reviewed_ids:
                if reviewed_id == phase_id and reviewed_id not in item["reviewed_candidate_ids"]:
                    item["reviewed_candidate_ids"].append(reviewed_id)
            _add_urls(item["source_urls"], record.get("source_urls"), record.get("bd_pdf_context_source_urls"))

    # Reconciliation has the authoritative derived review status.  Count it
    # separately from candidate rows and do not use it to infer permit dates.
    for record in reconciliation.to_dict("records"):
        phase_ids = _split_phase_ids(record.get("candidate_phase_ids"))
        if not phase_ids:
            phase_ids = _split_phase_ids(record.get("phase_context_reviewed_candidate_ids"))
        status = _text(record.get("phase_context_review_status")) or "unresolved_primary_document_context"
        reviewed_ids = _split_phase_ids(record.get("phase_context_reviewed_candidate_ids"))
        targeted_ids = set(reviewed_ids) if reviewed_ids and status in {
            "phase_context_supported_not_assigned",
            "phase_context_points_to_other_group_phase_not_assigned",
        } else set(phase_ids)
        phase_iteration_ids = list(dict.fromkeys([*phase_ids, *reviewed_ids]))
        for phase_id in phase_iteration_ids:
            if phase_id not in stats:
                continue
            item = stats[phase_id]
            if status == "phase_context_supported_not_assigned" and phase_id in targeted_ids:
                item.setdefault("reconciliation_supported_count", 0)
                item["reconciliation_supported_count"] += 1
            elif status == "phase_context_points_to_other_group_phase_not_assigned" and phase_id in targeted_ids:
                item.setdefault("reconciliation_other_group_count", 0)
                item["reconciliation_other_group_count"] += 1
            elif status == "same_family_phase_variant_review":
                item.setdefault("reconciliation_variant_count", 0)
                item["reconciliation_variant_count"] += 1
            else:
                item.setdefault("reconciliation_unresolved_count", 0)
                item["reconciliation_unresolved_count"] += 1
            _add_urls(item["source_urls"], record.get("source_urls"))

    rows: list[dict[str, Any]] = []
    for phase_id, base in phase_rows.items():
        item = stats[phase_id]
        supported = int(item["phase_context_supported_row_count"])
        other_group = int(item["phase_context_other_group_row_count"])
        variant = int(item["phase_context_same_family_variant_row_count"])
        unresolved = int(item["phase_context_unresolved_row_count"])
        if supported and (other_group or variant or unresolved):
            context_status = "supported_and_unresolved_mixed"
        elif supported:
            context_status = "phase_context_supported_not_assigned"
        elif other_group:
            context_status = "phase_context_points_to_other_group_phase_not_assigned"
        elif variant:
            context_status = "same_family_phase_variant_review"
        elif unresolved:
            context_status = "unresolved_primary_document_context"
        else:
            context_status = "not_observed"

        role_context = _phase_role_context([phase_id], role_by_phase)
        ownership_context = _indicative_ownership_context([phase_id], ownership_by_phase, role_by_phase)
        _add_urls(
            item["source_urls"],
            *[row.get("source_urls_json") for row in ownership_by_phase.get(phase_id, [])],
        )
        owner_status = ownership_context.get("indicative_ownership_context_status")
        if owner_status == "all_candidate_phases_numeric_snapshot":
            ownership_review_status = "numeric_snapshot_review_only"
            ownership_next = "Obtain phase-specific continuity/effective interval evidence; snapshot is not a legal interval."
        elif owner_status == "all_candidate_phases_jv_unquantified":
            ownership_review_status = "jv_unquantified_review_only"
            ownership_next = "Obtain dated JV/SPV/HKEX or land evidence with numeric stake and bounded effective interval."
        elif owner_status == "identity_only_without_numeric_or_jv_snapshot":
            ownership_review_status = "identity_only_review"
            ownership_next = "Obtain independent numeric economic-interest evidence and bounded effective interval."
        else:
            ownership_review_status = "ownership_context_incomplete"
            ownership_next = "Resolve missing phase-level numeric/JV evidence before any sales attribution."

        if context_status == "phase_context_supported_not_assigned":
            permit_next = "Review SRPE lot/phase and BD applicant/permit primary document; context support does not assign a permit."
        elif context_status == "supported_and_unresolved_mixed":
            permit_next = "Separate supported phase subsets from unresolved/shared-address rows using source PDF and lot evidence."
        elif context_status == "phase_context_points_to_other_group_phase_not_assigned":
            permit_next = "Route the primary PDF to the other phase in the same address group; do not reassign automatically."
        elif context_status == "same_family_phase_variant_review":
            permit_next = "Inspect same-family/non-residential variant before linking to the SRPE residential phase."
        elif context_status == "not_observed":
            permit_next = "Check historical source coverage and obtain a phase-specific primary BD document."
        else:
            permit_next = "Obtain or review phase-specific primary BD PDF plus SRPE lot/phase evidence."

        _add_urls(item["source_urls"], role_context.get("phase_role_source_urls"))
        rows.append(
            {
                **base,
                "bd_candidate_row_count": int(item["bd_candidate_row_count"]),
                "phase_context_supported_row_count": supported,
                "phase_context_other_group_row_count": other_group,
                "phase_context_same_family_variant_row_count": variant,
                "phase_context_unresolved_row_count": unresolved,
                "phase_context_review_status": context_status,
                "phase_context_reviewed_candidate_ids": "; ".join(item["reviewed_candidate_ids"]) or None,
                **role_context,
                "phase_role_evidence_count": int(ownership_context.get("phase_role_evidence_count") or 0),
                **ownership_context,
                "ownership_review_status": ownership_review_status,
                "ownership_review_next_evidence": ownership_next,
                "permit_review_next_evidence": permit_next,
                "ownership_promotion_status": "blocked_address_only",
                "permit_attribution_status": "blocked_address_only",
                "research_only": True,
                "source_urls_json": json.dumps(item["source_urls"], ensure_ascii=False),
                "review_caveat": (
                    "Phase-level evidence roll-up only. Shared-address candidate rows are not summed or assigned; "
                    "indicative stake/range is a snapshot/model input, not legal ownership or an effective interval."
                ),
            }
        )

    result = pd.DataFrame(rows, columns=PHASE_OWNERSHIP_REVIEW_COLUMNS)
    result.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=list(dict.fromkeys(source_urls)),
        lineage_metadata={
            **lineage,
            "phase_rows": int(len(result)),
            "blocked_row_count": int(result["ownership_promotion_status"].eq("blocked_address_only").sum()) if not result.empty else 0,
        },
    )
    return result


def _phase_group_context_by_phase(group_evidence: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    """Expand one group-evidence row into phase-level review context."""
    if group_evidence is None or group_evidence.empty:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in group_evidence.to_dict("records"):
        phase_ids = [value.strip() for value in str(row.get("srpe_phase_ids") or "").split(";") if value.strip()]
        for phase_id in phase_ids:
            result[phase_id] = {
                "phase_group_id": _text(row.get("phase_group_id")),
                "phase_group_member_count": row.get("srpe_phase_count"),
                "phase_group_member_ids": _text(row.get("srpe_phase_ids")),
                "phase_group_resolution_status": _text(row.get("group_resolution_status")),
                "phase_group_evidence_status": _text(row.get("group_evidence_status")),
                "phase_group_permit_years": _text(row.get("bd_permit_years")),
                "phase_group_phase_order_context_json": _text(row.get("srpe_phase_order_context_json")),
                "official_schedule_evidence_status": _text(row.get("official_schedule_evidence_status")),
                "schedule_phase_group_sets": _text(row.get("schedule_phase_group_sets")),
                "schedule_group_context_json": _text(row.get("schedule_group_context_json")),
            }
    return result


def build_shkp_bd_history_entity_resolution_review(
    crosswalk: pd.DataFrame,
    site_evidence: pd.DataFrame | None = None,
    phase_group_evidence: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build a bounded, phase-level review queue from the address-only crosswalk.

    This is deliberately a compression of existing crosswalk evidence, not a
    second matching algorithm.  Each SHKP/SRPE phase occupies one queue row;
    repeated BD months or lifecycle stages only describe the review context and
    cannot change an entity or ownership decision.  The function never fetches
    data and force-blocks ownership/permit attribution on every output row.
    Optional official-project-site evidence is attached as a separate developer
    identity context; it never overrides the address-based phase status.
    """
    source = crosswalk.copy() if crosswalk is not None else pd.DataFrame()
    site_by_phase = _site_evidence_by_phase(site_evidence)
    site_probe_by_phase = _site_probe_evidence_by_phase(site_evidence)
    corporate_by_phase = _corporate_role_evidence_by_phase(site_evidence)
    group_evidence = phase_group_evidence if phase_group_evidence is not None else build_shkp_bd_phase_group_evidence(source)
    group_context_by_phase = _phase_group_context_by_phase(group_evidence)
    if source.empty:
        queue = pd.DataFrame(columns=ENTITY_RESOLUTION_REVIEW_QUEUE_COLUMNS)
        summary = pd.DataFrame(
            [{
                "candidate_phase_count": 0,
                "phase_with_bd_address_hit_count": 0,
                "ambiguous_phase_count": 0,
                "matched_needs_review_phase_count": 0,
                "unmatched_phase_count": 0,
                "site_evidence_phase_count": 0,
                "corporate_role_evidence_phase_count": 0,
                "site_named_shkp_phase_count": 0,
                "page_named_shkp_phase_count": 0,
                "site_no_shkp_keyword_phase_count": 0,
                "site_not_evaluated_phase_count": 0,
                "matched_bd_history_row_count": 0,
                "distinct_bd_permit_number_count": 0,
                "blocked_address_only_phase_count": 0,
                "research_only": True,
                "ownership_promotion_status": "blocked_address_only",
                "permit_attribution_status": "blocked_address_only",
                "summary_caveat": "Empty crosswalk input: no address evidence was evaluated; no ownership or permit attribution is promoted.",
            }],
            columns=ENTITY_RESOLUTION_REVIEW_SUMMARY_COLUMNS,
        )
    else:
        # Preserve distinct malformed/missing IDs as separate review rows rather
        # than collapsing them into a synthetic entity.
        source["_phase_key"] = source.get("srpe_development_id", pd.Series(index=source.index, dtype=object)).map(_text)
        source["_phase_key"] = source["_phase_key"].where(
            source["_phase_key"].notna(),
            "__missing_phase_id__" + source.index.astype(str),
        )
        rows: list[dict[str, Any]] = []
        for phase_key, group in source.groupby("_phase_key", sort=False, dropna=False):
            status = _entity_resolution_status(group)
            priority, action = _review_policy(status)
            site_fields = _developer_identity_fields(
                site_by_phase.get(str(phase_key)),
                site_probe_status=_text(site_probe_by_phase.get(str(phase_key), {}).get("shkp_match_status")),
                corporate_role_present=str(phase_key) in corporate_by_phase,
            )
            group_fields = group_context_by_phase.get(str(phase_key), {})
            matched = group.get("bd_match_method", pd.Series(index=group.index, dtype=object)).isin(
                ["address_exact", "address_contains"]
            )
            matched_rows = group.loc[matched]
            digest_start, digest_end = _month_bounds(matched_rows.get("digest_month", pd.Series(dtype=object)))
            permit_numbers = _unique_texts(matched_rows.get("bd_permit_number", pd.Series(dtype=object)))
            candidate_counts = pd.to_numeric(group.get("bd_candidate_count", pd.Series(dtype=float)), errors="coerce")
            phase_candidate_counts = pd.to_numeric(group.get("bd_phase_candidate_count", pd.Series(dtype=float)), errors="coerce")
            rows.append(
                {
                    "srpe_development_id": None if phase_key.startswith("__missing_phase_id__") else phase_key,
                    "marketing_name": next(iter(_unique_texts(group.get("marketing_name", pd.Series(dtype=object)))), None),
                    "srpe_phase_name": next(iter(_unique_texts(group.get("srpe_phase_name", pd.Series(dtype=object)))), None),
                    "srpe_address_en": next(iter(_unique_texts(group.get("srpe_address_en", pd.Series(dtype=object)))), None),
                    "crosswalk_match_status": "; ".join(_unique_texts(group.get("crosswalk_match_status", pd.Series(dtype=object)))) or None,
                    **site_fields,
                    "entity_resolution_status": status,
                    "review_priority": priority,
                    "review_queue_rank": None,
                    "entity_resolution_action": action,
                    "project_identity_status": "address_candidate_only" if status != "unmatched" else "not_observed",
                    "ownership_promotion_status": "blocked_address_only",
                    "permit_attribution_status": "blocked_address_only",
                    "review_scope": "research_only_address_to_bd_entity_resolution",
                    "bd_match_methods": "; ".join(_unique_texts(matched_rows.get("bd_match_method", pd.Series(dtype=object)))) or "none",
                    "bd_history_row_count": int(len(matched_rows)),
                    "bd_candidate_count": int(candidate_counts.max()) if candidate_counts.notna().any() else int(len(matched_rows)),
                    "bd_phase_candidate_count": int(phase_candidate_counts.max()) if phase_candidate_counts.notna().any() else 0,
                    "bd_distinct_permit_number_count": len(permit_numbers),
                    "bd_permit_stages": "; ".join(_unique_texts(matched_rows.get("bd_permit_stage", pd.Series(dtype=object)))) or None,
                    "bd_permit_numbers": "; ".join(permit_numbers) or None,
                    "bd_site_addresses": "; ".join(_unique_texts(matched_rows.get("bd_site_address", pd.Series(dtype=object)))) or None,
                    "bd_digest_month_first_observed": digest_start,
                    "bd_digest_month_last_observed": digest_end,
                    "bd_parser_confidences": "; ".join(_unique_texts(matched_rows.get("bd_parser_confidence", pd.Series(dtype=object)))) or None,
                    "bd_parser_quality_flags": "; ".join(_unique_texts(matched_rows.get("bd_parser_quality_flag", pd.Series(dtype=object)))) or None,
                    "bd_source_urls": "; ".join(_unique_texts(matched_rows.get("bd_source_url", pd.Series(dtype=object)))) or None,
                    **group_fields,
                    "research_only": True,
                    "review_caveat": (
                        "Address-only candidate evidence. Digest months are publication/observation months, not permit dates; "
                        "no phase-specific permit or ownership attribution is inferred. Official project-site role evidence is "
                        "separate developer context and does not resolve a shared address to one BD phase."
                    ),
                }
            )
        queue = pd.DataFrame(rows, columns=ENTITY_RESOLUTION_REVIEW_QUEUE_COLUMNS)
        priority_rank = queue["review_priority"].map({"P0": 0, "P1": 1, "P2": 2}).fillna(9)
        queue = queue.assign(_priority_rank=priority_rank).sort_values(
            ["_priority_rank", "bd_history_row_count", "srpe_development_id"],
            ascending=[True, False, True],
            na_position="last",
        ).drop(columns="_priority_rank").reset_index(drop=True)
        queue["review_queue_rank"] = range(1, len(queue) + 1)
        matched_rows = source.get("bd_match_method", pd.Series(dtype=object)).isin(["address_exact", "address_contains"])
        all_permits = _unique_texts(source.loc[matched_rows, "bd_permit_number"] if "bd_permit_number" in source else pd.Series(dtype=object))
        summary = pd.DataFrame(
            [{
                "candidate_phase_count": int(len(queue)),
                "phase_with_bd_address_hit_count": int(queue["entity_resolution_status"].ne("unmatched").sum()),
                "ambiguous_phase_count": int(queue["entity_resolution_status"].eq("ambiguous").sum()),
                "matched_needs_review_phase_count": int(queue["entity_resolution_status"].eq("matched_needs_review").sum()),
                "unmatched_phase_count": int(queue["entity_resolution_status"].eq("unmatched").sum()),
                "site_evidence_phase_count": int(queue["shkp_site_probe_match_status"].ne("not_available").sum()),
                "corporate_role_evidence_phase_count": int(queue["shkp_corporate_role_evidence_status"].eq("observed").sum()),
                "site_named_shkp_phase_count": int(queue["shkp_site_probe_match_status"].eq("site_named_shkp").sum()),
                "page_named_shkp_phase_count": int(queue["shkp_site_probe_match_status"].eq("page_named_shkp").sum()),
                "site_no_shkp_keyword_phase_count": int(queue["shkp_site_probe_match_status"].eq("site_no_shkp_keyword").sum()),
                "site_not_evaluated_phase_count": int(queue["shkp_site_probe_match_status"].eq("not_evaluated").sum()),
                "matched_bd_history_row_count": int(matched_rows.sum()),
                "distinct_bd_permit_number_count": len(all_permits),
                "blocked_address_only_phase_count": int(queue["ownership_promotion_status"].eq("blocked_address_only").sum()),
                "research_only": True,
                "ownership_promotion_status": "blocked_address_only",
                "permit_attribution_status": "blocked_address_only",
                "summary_caveat": "Address-only review queue derived from the existing crosswalk. Official project-site role evidence is attached as developer context, but the queue is not a permit-date, phase-to-permit, legal ownership, or attributable-sales dataset.",
            }],
            columns=ENTITY_RESOLUTION_REVIEW_SUMMARY_COLUMNS,
        )

    lineage = {
        "lineage_type": "research_shkp_bd_history_entity_resolution_review",
        "source_dataset": DATASET_NAME,
        "ownership_promotion": "blocked_address_only",
        "permit_attribution": "blocked_address_only",
        "external_fetch": False,
        "site_evidence_rows": int(len(site_evidence)) if site_evidence is not None else 0,
        "site_evidence_attached": bool(site_by_phase),
        "phase_group_evidence_rows": int(len(group_evidence)),
        "phase_group_evidence_attached": not group_evidence.empty,
    }
    raw_snapshots = list(dict.fromkeys(
        [str(value) for value in (crosswalk.attrs.get("raw_snapshots", []) if crosswalk is not None else []) if value]
        + [str(value) for value in (site_evidence.attrs.get("raw_snapshots", []) if site_evidence is not None else []) if value]
    ))
    source_urls = list(dict.fromkeys(
        [str(value) for value in (crosswalk.attrs.get("source_urls", []) if crosswalk is not None else []) if value]
        + [str(value) for value in (site_evidence.attrs.get("source_urls", []) if site_evidence is not None else []) if value]
        + [str(value) for value in (group_evidence.attrs.get("source_urls", []) if group_evidence is not None else []) if value]
    ))
    for frame in (queue, summary):
        frame.attrs.update(
            raw_snapshots=raw_snapshots,
            source_urls=source_urls,
            lineage_metadata=lineage,
        )
    return queue, summary


def build_shkp_bd_history_entity_resolution_review_queue(
    crosswalk: pd.DataFrame,
    site_evidence: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return the phase-level review queue from an existing BD crosswalk."""
    return build_shkp_bd_history_entity_resolution_review(crosswalk, site_evidence=site_evidence)[0]


def build_shkp_bd_history_entity_resolution_summary(
    crosswalk: pd.DataFrame,
    site_evidence: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return the one-row bounded review summary from an existing BD crosswalk."""
    return build_shkp_bd_history_entity_resolution_review(crosswalk, site_evidence=site_evidence)[1]


def _review_evidence_by_phase(review_queue: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    """Return the first phase-level review row for developer-context reuse."""
    if review_queue is None or review_queue.empty or "srpe_development_id" not in review_queue.columns:
        return {}
    source = review_queue.copy()
    source["_phase_key"] = source["srpe_development_id"].map(_text)
    source = source.loc[source["_phase_key"].notna()].copy()
    if source.empty:
        return {}
    if "review_queue_rank" in source.columns:
        source["_rank"] = pd.to_numeric(source["review_queue_rank"], errors="coerce")
        source = source.sort_values(["_phase_key", "_rank"], na_position="last")
    return {
        str(key): group.iloc[0].to_dict()
        for key, group in source.groupby("_phase_key", sort=False)
    }


def _candidate_context_fields(
    phase_key: str,
    review_by_phase: dict[str, dict[str, Any]],
    site_by_phase: dict[str, dict[str, Any]],
    site_probe_by_phase: dict[str, dict[str, Any]] | None = None,
    corporate_by_phase: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach site-probe context without treating it as legal attribution."""
    review = review_by_phase.get(phase_key)
    if review:
        return {
            "developer_identity_status": _text(review.get("developer_identity_status")) or "site_evidence_not_available",
            "shkp_site_match_status": _text(review.get("shkp_site_match_status")) or "not_available",
            "shkp_site_probe_match_status": _text(review.get("shkp_site_probe_match_status")) or "not_available",
            "shkp_corporate_role_evidence_status": _text(review.get("shkp_corporate_role_evidence_status")) or "not_observed",
            "shkp_site_url": _text(review.get("shkp_site_url")),
            "shkp_site_vendor": _text(review.get("shkp_site_vendor")),
            "shkp_site_holding_companies": _text(review.get("shkp_site_holding_companies")),
            "shkp_site_sales_agent": _text(review.get("shkp_site_sales_agent")),
        }
    identity = _developer_identity_fields(
        site_by_phase.get(phase_key),
        site_probe_status=_text((site_probe_by_phase or {}).get(phase_key, {}).get("shkp_match_status")),
        corporate_role_present=phase_key in (corporate_by_phase or {}),
    )
    return {
        "developer_identity_status": identity["developer_identity_status"],
        "shkp_site_match_status": identity["shkp_site_match_status"],
        "shkp_site_probe_match_status": identity["shkp_site_probe_match_status"],
        "shkp_corporate_role_evidence_status": identity["shkp_corporate_role_evidence_status"],
        "shkp_site_url": identity["shkp_site_url"],
        "shkp_site_vendor": identity["shkp_site_vendor"],
        "shkp_site_holding_companies": identity["shkp_site_holding_companies"],
        "shkp_site_sales_agent": identity["shkp_site_sales_agent"],
    }


def build_shkp_bd_phase_resolution_candidates(
    crosswalk: pd.DataFrame,
    site_evidence: pd.DataFrame | None = None,
    review_queue: pd.DataFrame | None = None,
    phase_group_evidence: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Cluster address-only BD history into phase/permit review candidates.

    A row is one SRPE phase × BD match-method × stage × permit number × site
    address × applicant cluster.  It is intentionally not a sales, units, or
    ownership table: repeated monthly/stage observations are counted as rows
    for audit context and no unit or floor-area values are summed.  Shared
    addresses remain P0 candidates until the SRPE lot/phase and BD permit
    applicant are reconciled with primary documents.
    """
    source = crosswalk.copy() if crosswalk is not None else pd.DataFrame()
    site_by_phase = _site_evidence_by_phase(site_evidence)
    site_probe_by_phase = _site_probe_evidence_by_phase(site_evidence)
    corporate_by_phase = _corporate_role_evidence_by_phase(site_evidence)
    review_by_phase = _review_evidence_by_phase(review_queue)
    group_evidence = phase_group_evidence if phase_group_evidence is not None else build_shkp_bd_phase_group_evidence(source)
    group_context_by_phase = _phase_group_context_by_phase(group_evidence)

    lineage = {
        "lineage_type": "research_shkp_bd_phase_resolution_candidates",
        "source_dataset": DATASET_NAME,
        "source_datasets": [DATASET_NAME],
        "ownership_promotion": "blocked_address_only",
        "permit_attribution": "blocked_address_only",
        "external_fetch": False,
        "row_policy": "one_phase_x_bd_permit_applicant_stage_address_cluster_no_unit_aggregation",
    }
    raw_snapshots = list(dict.fromkeys(
        [str(value) for value in (source.attrs.get("raw_snapshots", []) if crosswalk is not None else []) if value]
        + [str(value) for value in (site_evidence.attrs.get("raw_snapshots", []) if site_evidence is not None else []) if value]
        + [str(value) for value in (review_queue.attrs.get("raw_snapshots", []) if review_queue is not None else []) if value]
    ))
    source_urls = list(dict.fromkeys(
        [str(value) for value in (source.attrs.get("source_urls", []) if crosswalk is not None else []) if value]
        + [str(value) for value in (site_evidence.attrs.get("source_urls", []) if site_evidence is not None else []) if value]
        + [str(value) for value in (review_queue.attrs.get("source_urls", []) if review_queue is not None else []) if value]
        + [str(value) for value in (group_evidence.attrs.get("source_urls", []) if group_evidence is not None else []) if value]
    ))

    if source.empty:
        result = pd.DataFrame(columns=PHASE_RESOLUTION_CANDIDATE_COLUMNS)
        result.attrs.update(raw_snapshots=raw_snapshots, source_urls=source_urls, lineage_metadata=lineage)
        return result

    source["_phase_key"] = source.get(
        "srpe_development_id", pd.Series(index=source.index, dtype=object)
    ).map(_text)
    source["_phase_key"] = source["_phase_key"].where(
        source["_phase_key"].notna(), "__missing_phase_id__" + source.index.astype(str)
    )
    # Missing fields get an explicit grouping sentinel.  This keeps a missing
    # permit number from accidentally merging with another stage/applicant and
    # makes the resulting review candidate's uncertainty visible.
    group_columns = [
        "_phase_key",
        "bd_match_method",
        "bd_permit_stage",
        "bd_permit_number",
        "bd_site_address",
        "bd_applicant",
    ]
    for column in group_columns[1:]:
        values = source.get(column, pd.Series(index=source.index, dtype=object)).map(_text)
        source[f"_group_{column}"] = values.fillna("__missing__")
    grouped_columns = ["_phase_key"] + [f"_group_{column}" for column in group_columns[1:]]

    rows: list[dict[str, Any]] = []
    for keys, group in source.groupby(grouped_columns, sort=False, dropna=False):
        phase_key = str(keys[0])
        def _decode_group_value(value: Any) -> str | None:
            return None if value == "__missing__" else _text(value)

        method = _decode_group_value(keys[1])
        stage = _decode_group_value(keys[2])
        permit_number = _decode_group_value(keys[3])
        site_address = _decode_group_value(keys[4])
        applicant = _decode_group_value(keys[5])
        matched = method in {"address_exact", "address_contains"}
        phase_counts = pd.to_numeric(
            group.get("bd_phase_candidate_count", pd.Series(index=group.index, dtype=float)),
            errors="coerce",
        ).dropna()
        phase_candidate_count = int(phase_counts.max()) if not phase_counts.empty else (1 if matched else 0)
        status_values = set(_unique_texts(group.get("bd_match_status", pd.Series(dtype=object))))
        if not matched:
            resolution_status = "unmatched_no_bd_address"
            priority = "P2"
            action = "retain_unmatched_and_check_historical_source_coverage"
        elif phase_candidate_count > 1 or "ambiguous" in status_values:
            resolution_status = "shared_address_phase_candidate"
            priority = "P0"
            action = "join_srpe_phase_lot_and_role_evidence_then_review_bd_permit_cluster"
        else:
            resolution_status = "single_phase_address_candidate"
            priority = "P1"
            action = "verify_bd_applicant_permit_cluster_against_phase_documents"

        digest_start, digest_end = _month_bounds(group.get("digest_month", pd.Series(dtype=object)))
        parser_confidences = _unique_texts(group.get("bd_parser_confidence", pd.Series(dtype=object)))
        parser_quality_flags = _unique_texts(group.get("bd_parser_quality_flag", pd.Series(dtype=object)))
        bd_source_values = _unique_texts(group.get("bd_source_url", pd.Series(dtype=object)))
        if not bd_source_values:
            bd_source_values = _unique_texts(group.get("bd_source_pdf_page", pd.Series(dtype=object)))
        context = _candidate_context_fields(
            phase_key,
            review_by_phase,
            site_by_phase,
            site_probe_by_phase=site_probe_by_phase,
            corporate_by_phase=corporate_by_phase,
        )
        group_context = group_context_by_phase.get(phase_key, {})
        rows.append(
            {
                "srpe_development_id": None if phase_key.startswith("__missing_phase_id__") else phase_key,
                "marketing_name": next(iter(_unique_texts(group.get("marketing_name", pd.Series(dtype=object)))), None),
                "srpe_phase_name": next(iter(_unique_texts(group.get("srpe_phase_name", pd.Series(dtype=object)))), None),
                "srpe_address_en": next(iter(_unique_texts(group.get("srpe_address_en", pd.Series(dtype=object)))), None),
                "crosswalk_match_status": "; ".join(_unique_texts(group.get("crosswalk_match_status", pd.Series(dtype=object)))) or None,
                **context,
                "phase_resolution_status": resolution_status,
                "phase_resolution_priority": priority,
                "phase_resolution_action": action,
                "permit_identity_status": "permit_number_observed" if permit_number else "permit_number_not_published_or_missing",
                "bd_match_method": method or "none",
                "bd_permit_stage": stage,
                "bd_permit_number": permit_number,
                "bd_site_address": site_address,
                "bd_applicants": "; ".join(_unique_texts(group.get("bd_applicant", pd.Series(dtype=object)))) or applicant,
                "bd_applicant_quality_status": _applicant_quality_status(
                    "; ".join(_unique_texts(group.get("bd_applicant", pd.Series(dtype=object)))) or applicant
                ),
                "bd_history_row_count": int(len(group)),
                "bd_phase_candidate_count": phase_candidate_count,
                "bd_digest_month_first_observed": digest_start,
                "bd_digest_month_last_observed": digest_end,
                "bd_parser_confidences": "; ".join(parser_confidences) or None,
                "bd_parser_quality_flags": "; ".join(parser_quality_flags) or None,
                "bd_source_urls": "; ".join(bd_source_values) or None,
                **group_context,
                "ownership_promotion_status": "blocked_address_only",
                "permit_attribution_status": "blocked_address_only",
                "research_only": True,
                "review_caveat": (
                    "Research-only address/permit/applicant cluster. Repeated digest rows are observations and are not summed; "
                    "digest months are publication/observation months, not permit dates. Resolve the SRPE phase/lot and BD "
                    "permit/applicant against primary documents before any phase attribution or ownership use."
                ),
            }
        )

    result = pd.DataFrame(rows, columns=PHASE_RESOLUTION_CANDIDATE_COLUMNS)
    if not result.empty:
        result = result.sort_values(
            ["phase_resolution_priority", "bd_history_row_count", "srpe_development_id"],
            ascending=[True, False, True],
            na_position="last",
        ).reset_index(drop=True)
    result.attrs.update(raw_snapshots=raw_snapshots, source_urls=source_urls, lineage_metadata=lineage)
    return result


def run_shkp_bd_history_entity_resolution_review() -> dict[str, Any]:
    """Persist queue and summary from local crosswalk/site-evidence snapshots."""
    run_id = f"shkp-bd-history-entity-review-{uuid.uuid4()}"
    crosswalk = load_latest_normalized(DATASET_NAME)
    if crosswalk.empty:
        raise RuntimeError(f"{DATASET_NAME} is required and must contain rows")
    bd_history = load_latest_normalized("bd_project_lifecycle_history")
    site_frames = [
        load_latest_normalized("shkp_srpe_phase_site_evidence"),
        load_latest_normalized("shkp_srpe_phase_site_rendered_evidence"),
    ]
    site_frames = [frame for frame in site_frames if not frame.empty]
    role_evidence = load_latest_normalized("shkp_phase_role_evidence")
    ownership_roster = load_latest_normalized("shkp_indicative_ownership_roster")
    role_context = _official_role_evidence_as_site_evidence(role_evidence)
    all_site_frames = [*site_frames, role_context] if not role_context.empty else site_frames
    site_evidence = pd.concat(all_site_frames, ignore_index=True) if all_site_frames else pd.DataFrame()
    if all_site_frames:
        site_evidence.attrs["raw_snapshots"] = list(dict.fromkeys(
            [str(value) for frame in all_site_frames for value in frame.attrs.get("raw_snapshots", []) if value]
        ))
        site_evidence.attrs["source_urls"] = list(dict.fromkeys(
            [str(value) for frame in all_site_frames for value in frame.attrs.get("source_urls", []) if value]
        ))
    srpe_index = load_latest_normalized("srpe_development_index")
    schedule_crosswalk = load_latest_normalized("shkp_completion_schedule_crosswalk")
    phase_group_evidence = build_shkp_bd_phase_group_evidence(
        crosswalk,
        srpe_index=srpe_index,
        schedule_crosswalk=schedule_crosswalk,
    )
    queue, summary = build_shkp_bd_history_entity_resolution_review(
        crosswalk,
        site_evidence=site_evidence,
        phase_group_evidence=phase_group_evidence,
    )
    phase_candidates = build_shkp_bd_phase_resolution_candidates(
        crosswalk,
        site_evidence=site_evidence,
        review_queue=queue,
        phase_group_evidence=phase_group_evidence,
    )
    phase_permit_candidates = build_shkp_bd_phase_permit_candidate_evidence(
        crosswalk,
        phase_group_evidence=phase_group_evidence,
        schedule_crosswalk=schedule_crosswalk,
        phase_role_evidence=role_evidence,
        ownership_roster=ownership_roster,
        bd_history=bd_history,
    )
    phase_permit_reconciliation = build_shkp_bd_phase_permit_reconciliation(
        phase_permit_candidates,
    )
    phase_ownership_review = build_shkp_bd_phase_ownership_review(
        queue,
        phase_permit_candidates,
        phase_permit_reconciliation,
        ownership_roster=ownership_roster,
        phase_role_evidence=role_evidence,
    )
    lineage = queue.attrs.get("lineage_metadata", {})
    phase_candidate_lineage = phase_candidates.attrs.get("lineage_metadata", {})
    phase_permit_candidate_lineage = phase_permit_candidates.attrs.get("lineage_metadata", {})
    phase_permit_reconciliation_lineage = phase_permit_reconciliation.attrs.get("lineage_metadata", {})
    phase_ownership_review_lineage = phase_ownership_review.attrs.get("lineage_metadata", {})
    stored = {
        ENTITY_RESOLUTION_REVIEW_QUEUE_DATASET: save_normalized_dataset(
            ENTITY_RESOLUTION_REVIEW_QUEUE_DATASET,
            queue,
            run_id=run_id,
            raw_snapshots=queue.attrs.get("raw_snapshots"),
            source_urls=queue.attrs.get("source_urls"),
            lineage_metadata=lineage,
        ),
        ENTITY_RESOLUTION_REVIEW_SUMMARY_DATASET: save_normalized_dataset(
            ENTITY_RESOLUTION_REVIEW_SUMMARY_DATASET,
            summary,
            run_id=run_id,
            raw_snapshots=summary.attrs.get("raw_snapshots"),
            source_urls=summary.attrs.get("source_urls"),
            lineage_metadata=lineage,
        ),
        PHASE_RESOLUTION_CANDIDATE_DATASET: save_normalized_dataset(
            PHASE_RESOLUTION_CANDIDATE_DATASET,
            phase_candidates,
            run_id=run_id,
            raw_snapshots=phase_candidates.attrs.get("raw_snapshots"),
            source_urls=phase_candidates.attrs.get("source_urls"),
            lineage_metadata=phase_candidate_lineage,
        ),
        PHASE_GROUP_EVIDENCE_DATASET: save_normalized_dataset(
            PHASE_GROUP_EVIDENCE_DATASET,
            phase_group_evidence,
            run_id=run_id,
            raw_snapshots=phase_group_evidence.attrs.get("raw_snapshots"),
            source_urls=phase_group_evidence.attrs.get("source_urls"),
            lineage_metadata=phase_group_evidence.attrs.get("lineage_metadata"),
        ),
        PHASE_PERMIT_CANDIDATE_EVIDENCE_DATASET: save_normalized_dataset(
            PHASE_PERMIT_CANDIDATE_EVIDENCE_DATASET,
            phase_permit_candidates,
            run_id=run_id,
            raw_snapshots=phase_permit_candidates.attrs.get("raw_snapshots"),
            source_urls=phase_permit_candidates.attrs.get("source_urls"),
            lineage_metadata=phase_permit_candidate_lineage,
        ),
        PHASE_PERMIT_RECONCILIATION_DATASET: save_normalized_dataset(
            PHASE_PERMIT_RECONCILIATION_DATASET,
            phase_permit_reconciliation,
            run_id=run_id,
            raw_snapshots=phase_permit_reconciliation.attrs.get("raw_snapshots"),
            source_urls=phase_permit_reconciliation.attrs.get("source_urls"),
            lineage_metadata=phase_permit_reconciliation_lineage,
        ),
        PHASE_OWNERSHIP_REVIEW_DATASET: save_normalized_dataset(
            PHASE_OWNERSHIP_REVIEW_DATASET,
            phase_ownership_review,
            run_id=run_id,
            raw_snapshots=phase_ownership_review.attrs.get("raw_snapshots"),
            source_urls=phase_ownership_review.attrs.get("source_urls"),
            lineage_metadata=phase_ownership_review_lineage,
        ),
    }
    return {
        "run_id": run_id,
        "queue_rows": int(len(queue)),
        "phase_resolution_candidate_rows": int(len(phase_candidates)),
        "phase_group_evidence_rows": int(len(phase_group_evidence)),
        "phase_permit_candidate_evidence_rows": int(len(phase_permit_candidates)),
        "phase_permit_reconciliation_rows": int(len(phase_permit_reconciliation)),
        "phase_ownership_review_rows": int(len(phase_ownership_review)),
        "phase_permit_reconciliation_status_counts": phase_permit_reconciliation[
            "reconciliation_status"
        ].value_counts().to_dict(),
        "summary": summary.iloc[0].to_dict(),
        "normalized": stored,
        "warning": "Research-only address review queue; ownership and phase-specific permit attribution remain blocked.",
    }


def run_shkp_bd_history_crosswalk() -> dict[str, Any]:
    """Persist the latest available historical BD↔SHKP address audit."""
    run_id = str(uuid.uuid4())
    shkp_crosswalk = load_latest_normalized("shkp_srpe_crosswalk")
    srpe_index = load_latest_normalized("srpe_development_index")
    bd_history = load_latest_normalized("bd_project_lifecycle_history")
    if shkp_crosswalk.empty or srpe_index.empty or bd_history.empty:
        raise RuntimeError("shkp_srpe_crosswalk, srpe_development_index and bd_project_lifecycle_history are required")
    result = build_shkp_bd_history_crosswalk(shkp_crosswalk, srpe_index, bd_history)
    stored = save_normalized_dataset(
        DATASET_NAME,
        result,
        run_id=run_id,
        raw_snapshots=result.attrs.get("raw_snapshots"),
        source_urls=result.attrs.get("source_urls"),
        lineage_metadata=result.attrs.get("lineage_metadata"),
    )
    return {
        "run_id": run_id,
        "records": int(len(result)),
        "candidate_phases": int(len(shkp_crosswalk)),
        "matched_phases": int(result.loc[result["bd_match_method"].ne("none"), "srpe_development_id"].nunique()),
        "matched_rows": int(result["bd_match_method"].ne("none").sum()),
        "status_counts": result["bd_match_status"].value_counts(dropna=False).to_dict(),
        "normalized": stored,
        "warning": "Address-only candidate crosswalk; no ownership or phase-specific permit attribution is promoted.",
    }
