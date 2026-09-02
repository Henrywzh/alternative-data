"""Sun Hung Kai Properties official property-directory feeds.

The SHKP corporate site renders its category pages from small JSON endpoints
under the same path as the page itself.  These feeds are useful for the
current marketing/investment-property catalogue, but they are not an
ownership or historical project universe.  Keep that distinction explicit in
the normalized contract and use SRPE/LandsD/company disclosures for legal
identity and history.
"""

from __future__ import annotations

import json
import hashlib
import math
import re
import time
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlencode, urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot
from .land_planning import is_tpb_application_detail_url


SHKP_SITE_BASE = "https://www.shkp.com"
SHKP_HK_PROPERTIES_BASE = f"{SHKP_SITE_BASE}/en-US/our-business/hong-kong-properties"


class SHKPSourceUnavailable(RuntimeError):
    """Raised when an official SHKP page returns no usable body/content."""

# Each entry describes one independently maintained listing.  The page's
# data-totalpage attribute is discovered at runtime; it is not hard-coded.
SHKP_LISTING_CONFIGS: tuple[dict[str, Any], ...] = (
    {
        "asset_type": "residential_for_sale",
        "subtype": "for_sale",
        "path": "residential-for-sale",
        "container_id": "major_forsales",
        "endpoint_suffix": "",
        "query": {},
    },
    {
        "asset_type": "residential_for_lease",
        "subtype": "signature_homes",
        "path": "residential-for-lease",
        "container_id": "major_signs",
        "endpoint_suffix": "",
        "query": {},
    },
    {
        "asset_type": "shopping_mall",
        "subtype": "shopping_malls",
        "path": "shopping-malls",
        "container_id": "major_malls",
        "endpoint_suffix": "",
        "query": {},
    },
    {
        "asset_type": "office",
        "subtype": "offices",
        "path": "offices",
        "container_id": "major_offices",
        "endpoint_suffix": "",
        "query": {},
    },
    {
        "asset_type": "hotel",
        "subtype": "hotel_type_a",
        "path": "hotels-and-serviced-suites",
        "container_id": "major_hotels",
        "endpoint_suffix": "",
        "query": {"hoteltype": "typea"},
    },
    {
        "asset_type": "hotel",
        "subtype": "hotel_type_b",
        "path": "hotels-and-serviced-suites",
        "container_id": "major_hotels",
        "endpoint_suffix": "",
        "query": {"hoteltype": "typeb"},
    },
    {
        "asset_type": "serviced_suite",
        "subtype": "serviced_suites",
        "path": "hotels-and-serviced-suites",
        "container_id": "major_suites",
        "endpoint_suffix": "/ss",
        "query": {},
    },
)


CATALOG_COLUMNS = [
    "asset_type",
    "subtype",
    "marketing_name",
    "district",
    "thumbnail_url",
    "external_project_url",
    "external_project_urls",
    "raw_langcode",
    "source_record_id",
    "source_page_url",
    "source_url",
    "page_number",
    "display_order",
    "listed_status",
    "fetched_at",
]

CORPORATE_DOCUMENT_COLUMNS = [
    "document_type",
    "title",
    "document_url",
    "source_page_url",
    "source_url",
    "published_date",
    "document_semantics",
    "reporting_period_end",
    "hkex_release_at",
    "issuer_release_date",
    "release_source_url",
    "release_evidence_type",
    "fetched_at",
]

# The issuer's History and Milestones page is a dated corporate project
# evidence layer.  It is useful for extending the current-property directory
# backwards, but it is not a complete phase/ownership register: one milestone
# may mention several projects and the page does not expose SRPE ids or legal
# holding percentages.  Keep the source text and image metadata intact so a
# later alias/phase review can return to the exact issuer evidence.
HISTORY_MILESTONE_COLUMNS = [
    "milestone_id",
    "milestone_year",
    "project_label",
    "milestone_summary",
    "image_url",
    "source_page_url",
    "source_url",
    "fetched_at",
    "evidence_status",
    "parse_version",
]

HISTORY_MILESTONE_CROSSWALK_COLUMNS = [
    "milestone_id",
    "milestone_year",
    "milestone_summary",
    "project_label",
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "match_status",
    "match_method",
    "match_score",
    "candidate_count",
    "candidate_ids_json",
    "evidence_status",
    "ownership_promotion_status",
    "source_url",
    "last_verified_at",
]

# One row per official annual-report PDF.  This is deliberately a document
# evidence layer, not a project table: older report vintages must be visible
# in the historical universe before their layout-specific project pages are
# parsed and reconciled to SRPE IDs.
HISTORICAL_ANNUAL_REPORT_INDEX_COLUMNS = [
    "report_document_id",
    "report_id",
    "report_label",
    "document_variant",
    "report_period_end",
    "document_url",
    "source_page_url",
    "issuer_release_date",
    "hkex_release_at",
    "release_source_url",
    "document_status",
    "project_table_parse_status",
    "evidence_type",
    "fetched_at",
]

PIPELINE_DISCLOSURE_COLUMNS = [
    "disclosure_id",
    "disclosure_type",
    "project_label",
    "status",
    "geography",
    "publication_date",
    "evidence_status",
    "evidence_context",
    "http_status",
    "response_content_bytes",
    "fetch_status",
    "fetch_attempts",
    "source_url",
    "fetched_at",
]

ANNUAL_REPORT_PROJECT_COLUMNS = [
    "report_id",
    "report_period_end",
    "evidence_type",
    "project_label",
    "location",
    "usage",
    "group_interest_raw",
    "group_interest_pct",
    "attributable_gfa_sqft",
    # Major-project narrative pages expose a richer fact set than the
    # handover table.  Keep those fields separate instead of overloading the
    # handover table's attributable-GFA value with a total or a component.
    "site_area_sqft",
    "gross_floor_area_sqft",
    "residential_gfa_sqft",
    "retail_gfa_sqft",
    "approximate_units",
    "completion_window",
    "ownership_basis",
    "source_section",
    "project_state",
    "geography",
    "page_number",
    "evidence_status",
    "evidence_context",
    "document_url",
    "source_url",
    "fetched_at",
]

# The annual report's ``Major Completed Properties in Hong Kong`` table is a
# separate exposure snapshot.  Its project/name page and its aligned GFA
# page are parsed together, but it deliberately does not share the handover
# table schema: these are completed investment assets rather than delivery
# events.  Keep raw labels and the reported ``Group's Interest`` beside the
# parsed values so an asset-level reviewer can return to the PDF without any
# ownership or rental-income inference.
SHKP_COMPLETED_PROPERTY_COLUMNS = [
    "completed_property_id",
    "report_id",
    "report_period_end",
    "project_label_raw",
    "location_raw",
    "geography",
    "lease_expiry_raw",
    "group_interest_raw",
    "group_interest_pct",
    "residential_gfa_sqft",
    "shopping_centre_gfa_sqft",
    "office_gfa_sqft",
    "hotel_gfa_sqft",
    "industrial_gfa_sqft",
    "total_gfa_sqft",
    "gfa_components_sum_sqft",
    "gfa_reconciliation_status",
    "project_page_number",
    "metrics_page_number",
    "evidence_status",
    "ownership_semantics",
    "caveat",
    "evidence_context",
    "document_url",
    "source_url",
    "fetched_at",
]

# The annual-report ``Principal Subsidiaries`` appendix is a dated legal-entity
# snapshot.  It is intentionally kept separate from the phase registry: the
# table lists subsidiaries that materially affect the Group, not a complete
# project/SPV inventory, and it does not provide an effective-from/effective-to
# interval.  ``pdf_page`` is the physical PDF page; ``printed_page`` is the
# page number visible in the report footer when it can be recovered.
SHKP_ANNUAL_PRINCIPAL_SUBSIDIARY_COLUMNS = [
    "report_id",
    "report_period_end",
    "as_of_date",
    "spv_name",
    "attributable_equity_pct",
    "business_description",
    "note",
    "share_capital_raw",
    "pdf_page",
    "printed_page",
    "evidence_status",
    "ownership_semantics",
    "annual_document_url",
    "source_url",
    "fetched_at",
]

# Candidate phase bridge for the annual subsidiary snapshot.  This is a
# review-only layer: a subsidiary name is only connected to a phase when an
# existing legal-observation or official project-site/vendor record supplies
# the bridge.  Unmatched subsidiaries are retained with a null SRPE ID so the
# table can discover future SPVs without turning a company-wide appendix into
# a project ownership assertion.
SHKP_ANNUAL_PRINCIPAL_SUBSIDIARY_CROSSWALK_COLUMNS = [
    "crosswalk_id",
    "report_id",
    "report_period_end",
    "as_of_date",
    "spv_name",
    "attributable_equity_pct",
    "business_description",
    "annual_pdf_page",
    "printed_page",
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "candidate_count",
    "match_status",
    "match_method",
    "ownership_status",
    "effective_from",
    "effective_to",
    "annual_document_url",
    "source_url",
    "source_page_or_detail",
    "bridge_record_id",
    "bridge_source_url",
    "bridge_source_page_or_detail",
    "source_urls_json",
    "annual_observation_consistency_status",
    "evidence_context",
    "last_verified_at",
]

# SHKP's dated completion schedule is a separate evidence layer from the
# annual-report handover table.  It is a project/lot-level snapshot of the
# Group's reported interest and expected handover window; it is not a legal
# SPV ownership register.  Keep the raw interest token (including ``JV``) and
# the parsed numeric value side by side.
SHKP_COMPLETION_SCHEDULE_COLUMNS = [
    "schedule_id",
    "schedule_date",
    "project_row_no",
    "lot_description",
    "project_label",
    "group_interest_raw",
    "group_interest_pct",
    "completion_window",
    "project_state",
    "residential_gfa_sqft",
    "shops_gfa_sqft",
    "office_gfa_sqft",
    "hotel_gfa_sqft",
    "industrial_gfa_sqft",
    "total_gfa_sqft",
    "page_number",
    "footnote_context",
    "document_url",
    "source_url",
    "fetched_at",
]

SHKP_COMPLETION_SCHEDULE_CROSSWALK_COLUMNS = [
    "schedule_id",
    "schedule_date",
    "project_row_no",
    "lot_description",
    "project_label",
    "group_interest_raw",
    "group_interest_pct",
    "completion_window",
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "srpe_phase_no",
    "srpe_address_en",
    "lot_match_status",
    "match_method",
    "match_confidence",
    "match_status",
    "candidate_count",
    "planning_consent_date",
    "ownership_status",
    "evidence_level",
    "document_url",
    "source_url",
    "matched_at",
]

SHKP_COMPLETION_SCHEDULE_AUDIT_COLUMNS = [
    "schedule_id",
    "schedule_date",
    "project_row_no",
    "lot_description",
    "project_label",
    "group_interest_raw",
    "group_interest_pct",
    "srpe_development_id",
    "srpe_phase_name",
    "match_status",
    "candidate_count",
    "registry_ownership_pct",
    "audit_status",
    "evidence_level",
    "document_url",
    "last_verified_at",
]

# Dated ownership-evidence records deliberately sit beside (rather than
# inside) the curated ownership registry.  ``Group's Interest`` is a reported
# accounting attribution; it is not automatically legal-SPV ownership.  The
# explicit promotion fields make that distinction machine-readable.
SHKP_COMPLETION_SCHEDULE_EVIDENCE_COLUMNS = [
    "evidence_id",
    "evidence_date",
    "schedule_id",
    "project_row_no",
    "lot_description",
    "project_label",
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "srpe_phase_no",
    "group_interest_raw",
    "group_interest_pct",
    "evidence_status",
    "legal_lot_bridge_status",
    "ownership_promotion_status",
    "evidence_level",
    "evidence_context",
    "evidence_urls_json",
    "source_url",
    "last_verified_at",
]

# A second, deliberately non-promoting view joins the dated completion
# schedule to annual-report and official project-site evidence.  It exists so
# reviewers can see what corroborates a Group-interest number and what is
# still missing before legal/SPV attribution.  No field in this contract may
# set ``ownership_attribution_ready``.
SHKP_COMPLETION_SCHEDULE_RECONCILIATION_COLUMNS = [
    "reconciliation_id",
    "schedule_id",
    "schedule_date",
    "project_row_no",
    "lot_description",
    "project_label",
    "completion_window",
    "group_interest_raw",
    "group_interest_pct",
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "srpe_phase_no",
    "schedule_match_status",
    "schedule_candidate_count",
    "annual_match_status",
    "annual_candidate_count",
    "annual_project_label",
    "annual_report_id",
    "annual_report_period_end",
    "annual_group_interest_raw",
    "annual_group_interest_pct",
    "annual_document_url",
    "site_match_status",
    "site_candidate_count",
    "site_marketing_name",
    "site_evidence_status",
    "vendor_name",
    "holding_companies",
    "site_source_url",
    "reconciliation_status",
    "ownership_promotion_status",
    "required_next_evidence",
    "evidence_urls_json",
    "evidence_context",
    "last_verified_at",
]

CROSSWALK_COLUMNS = [
    "marketing_name",
    "external_project_url",
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "srpe_phase_no",
    "match_method",
    "match_confidence",
    "match_status",
    "candidate_count",
    "shkp_source_record_id",
    "shkp_source_url",
    "srpe_source_url",
    "matched_at",
    # Ownership fields are part of the contract even before evidence is
    # attached.  Explicit status prevents a null percentage being mistaken
    # for a verified zero or an implicit 100% parent-company holding.
    "listed_parent",
    "ticker",
    "ownership_pct",
    "ownership_effective_from",
    "ownership_effective_to",
    "ownership_evidence_url",
    "ownership_evidence_level",
    "ownership_status",
]

ANNUAL_SRPE_CROSSWALK_COLUMNS = [
    "report_id",
    "report_period_end",
    "evidence_type",
    "project_label",
    "project_state",
    "geography",
    "annual_location",
    "annual_group_interest_raw",
    "annual_group_interest_pct",
    "annual_page_number",
    "annual_document_url",
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "srpe_phase_no",
    "srpe_address_en",
    "match_method",
    "match_confidence",
    "match_status",
    "candidate_count",
    "ownership_status",
    "matched_at",
]

PIPELINE_SRPE_CROSSWALK_COLUMNS = [
    "pipeline_evidence_key",
    "disclosure_id",
    "disclosure_type",
    "project_label",
    "pipeline_status",
    "geography",
    "publication_date",
    "evidence_status",
    "evidence_context",
    "source_url",
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "srpe_phase_no",
    "srpe_address_en",
    "match_method",
    "match_confidence",
    "match_status",
    "candidate_count",
    "ownership_status",
    "matched_at",
]

SHKP_SRPE_MANIFEST_COLUMNS = [
    "srpe_development_id",
    "development_name",
    "phase_name",
    "phase_no",
    "development_address",
    "document_category",
    "document_id",
    "serial_no",
    "date_of_printing",
    "submission_time",
    "file_name",
    "file_size_bytes",
    "download_endpoint",
    "detail_endpoint",
    "evidence_status",
    "fetched_at",
]

PLANNING_EVIDENCE_CROSSWALK_COLUMNS = [
    "evidence_source",
    "evidence_record_id",
    "evidence_date",
    "evidence_status",
    "development_name_raw",
    "location_raw",
    "lot_no_raw",
    "parent_or_developer_raw",
    "source_url",
    "page_or_detail",
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "srpe_address_en",
    "match_method",
    "match_confidence",
    "match_status",
    "candidate_count",
    "planning_consent_date",
    "ownership_status",
    "matched_at",
]

BD_CROSSWALK_COLUMNS = [
    "marketing_name",
    "srpe_development_id",
    "srpe_phase_name",
    "srpe_address_en",
    "crosswalk_match_status",
    "bd_permit_stage",
    "bd_permit_number",
    "bd_site_address",
    "bd_domestic_units_count",
    "bd_usable_floor_area_sqm",
    "bd_parser_confidence",
    "bd_match_method",
    "bd_match_status",
    "bd_candidate_count",
    "bd_phase_candidate_count",
    "shkp_source_url",
    "srpe_source_url",
    "bd_source_url",
    "matched_at",
]

SUPPORTING_SOURCE_COLUMNS = [
    "source_id",
    "agency",
    "evidence_type",
    "source_url",
    "source_grain",
    "join_keys",
    "status",
    "caveat",
]

LAND_PLANNING_DOCUMENT_COLUMNS = [
    "source_id",
    "agency",
    "evidence_type",
    "title",
    "document_url",
    "source_url",
    "record_id",
    "status",
    "fetched_at",
]

OWNERSHIP_AUDIT_COLUMNS = [
    "stock_code",
    "listed_company_en",
    "registry_project_name",
    "registry_alias",
    "registry_ownership_pct",
    "annual_project_label",
    "annual_group_interest_raw",
    "annual_group_interest_pct",
    "annual_page_number",
    "audit_status",
    "evidence_level",
    "annual_document_url",
    "last_verified_date",
]

PHASE_EVIDENCE_AUDIT_COLUMNS = [
    "evidence_case_id",
    "report_id",
    "project_label",
    "project_state",
    "annual_location",
    "annual_group_interest_raw",
    "annual_group_interest_pct",
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "srpe_phase_no",
    "planning_lot_no",
    "planning_entity_raw",
    "planning_consent_date",
    "candidate_status",
    "phase_status",
    "ownership_status",
    "evidence_summary",
    "evidence_urls_json",
    "evidence_pages_json",
    "source_count",
    "last_verified_at",
]

# Numeric subsidiary observations are kept as dated snapshots rather than
# converted into an ownership interval.  The annual reports identify the
# legal subsidiary and its attributable equity interest as at a reporting
# date, while the public sources do not establish an uninterrupted
# ``effective_from`` date.  Keeping this as a separate contract lets the
# registry expose useful evidence without silently opening the sales gate.
SHKP_LEGAL_OWNERSHIP_OBSERVATION_COLUMNS = [
    "observation_id",
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "listed_parent",
    "stock_code",
    "subsidiary_spv_name",
    "ownership_pct",
    "ownership_observed_as_of",
    "effective_from",
    "effective_to",
    "legally_continuous",
    "interval_blocker",
    "observation_type",
    "evidence_status",
    "ownership_source_url",
    "ownership_source_page",
    "phase_identity_source_url",
    "srpe_source_url",
    "promotion_status",
    "caveat",
    "source_urls_json",
    "last_verified_at",
]

# Manual/IRIS evidence is kept at land-register/memorial grain.  A registered
# title owner is not automatically the listed parent's attributable economic
# interest, so this contract is deliberately evidence-only and cannot open the
# sales gate on its own.
SHKP_LAND_REGISTRY_EVIDENCE_COLUMNS = [
    "evidence_id",
    "srpe_development_id",
    "lot_no",
    "memorial_no",
    "instrument_type",
    "instrument_date",
    "registered_owner",
    "owner_capacity",
    "registered_share",
    "consideration_hkd",
    "source_url",
    "source_document",
    "source_order_reference",
    "date_semantics",
    "phase_match_status",
    "legal_interest_type",
    "ownership_pct",
    "effective_from",
    "effective_to",
    "legally_continuous",
    "promotion_status",
    "caveat",
    "last_verified_at",
]

# The only layer allowed to carry a promotable phase-level interval.  This is
# a separately reviewed decision record, not an automatic transformation of a
# Land Registry title event, annual-report snapshot or project website row.
SHKP_PHASE_ATTRIBUTION_DECISION_COLUMNS = [
    "decision_id",
    "srpe_development_id",
    "phase_label",
    "listed_parent",
    "stock_code",
    "ownership_pct",
    "effective_from",
    "effective_to",
    "phase_identity_status",
    "phase_identity_evidence_ids",
    "economic_evidence_ids",
    "title_chain_evidence_ids",
    "continuity_basis",
    "reviewer",
    "reviewed_at",
    "decision_status",
    "evidence_type",
    "promotion_status",
    "ownership_attribution_ready",
    "source_urls_json",
    "caveat",
    "last_verified_at",
]

# A normalized, non-promoting event stream for ownership/phase review.  The
# same project can have an annual-report snapshot, a LandsD consent date and a
# project-site notice; those dates answer different questions and must remain
# distinguishable.  ``effective_from``/``effective_to`` are intentionally
# nullable until a legal SPV/JV source establishes an actual interval.
SHKP_OWNERSHIP_EVIDENCE_TIMELINE_COLUMNS = [
    "timeline_id",
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "event_date",
    "date_semantics",
    "event_type",
    "source_layer",
    "subsidiary_spv_name",
    "vendor_name",
    "holding_companies",
    "ownership_pct_observed",
    "ownership_raw",
    "evidence_level",
    "effective_from",
    "effective_to",
    "promotion_status",
    "source_url",
    "source_page_or_detail",
    "evidence_context",
    "last_verified_at",
]

# Entity-level evidence is deliberately separate from the phase registry.  A
# vendor, holding-company label, legal SPV and listed parent can all appear in
# the same project's evidence, but none of those labels alone establishes a
# continuous ownership interval.  This contract gives each observed entity a
# stable key and an explicit relation/evidence status without promoting it.
SHKP_ENTITY_OWNERSHIP_CROSSWALK_COLUMNS = [
    "entity_observation_id",
    "entity_key",
    "entity_name",
    "entity_type",
    "entity_role",
    "listed_parent",
    "stock_code",
    "srpe_development_id",
    "srpe_phase_name",
    "relation_status",
    "ownership_pct_observed",
    "ownership_observed_as_of",
    "effective_from",
    "effective_to",
    "evidence_status",
    "dedup_status",
    "source_url",
    "source_page_or_detail",
    "evidence_context",
    "source_urls_json",
    "last_verified_at",
]

SHKP_PROJECT_REGISTRY_COLUMNS = [
    "registry_key",
    "srpe_development_id",
    "development_name_en",
    "phase_name_en",
    "phase_no",
    "address_en",
    "planning_area_en",
    "active",
    "official_website",
    "srpe_earliest_publication",
    "srpe_date_suspend_sales",
    "srpe_date_complete_sales",
    "srpe_is_deleted",
    "srpe_eng_remark",
    "srpe_chn_remark",
    "srpe_eng_addr_idx_remark",
    "srpe_chn_addr_idx_remark",
    "srpe_index_snapshot_at",
    # Discovery scope only; these fields never open the ownership/sales gate.
    "universe_status",
    "universe_evidence_types",
    "curated_non_shkp_reason",
    "history_milestone_evidence_rows",
    "history_milestone_years",
    "history_milestone_summaries",
    "history_milestone_match_status",
    "shkp_marketing_names",
    "shkp_listing_count",
    "shkp_match_status",
    "shkp_match_confidence",
    "annual_project_labels",
    "annual_project_states",
    "annual_group_interest_raw",
    "annual_group_interest_pct",
    "annual_match_status",
    "completion_schedule_latest_date",
    "completion_schedule_windows",
    "completion_schedule_lot_descriptions",
    "completion_schedule_project_labels",
    "completion_schedule_group_interest_raw",
    "completion_schedule_group_interest_pct",
    "completion_schedule_match_status",
    "completion_schedule_ownership_status",
    "completion_schedule_evidence_rows",
    "planning_lot_nos",
    "planning_consent_dates",
    "planning_entity_labels",
    "planning_match_status",
    "planning_evidence_rows",
    "legal_spv_names",
    "ownership_observed_pct",
    "ownership_observed_as_of",
    "legal_ownership_observation_status",
    "legal_ownership_evidence_rows",
    "bd_match_status",
    "bd_phase_candidate_counts",
    "bd_permit_stages",
    "bd_permit_numbers",
    "bd_site_addresses",
    "bd_domestic_units_count",
    "bd_usable_floor_area_sqm",
    "bd_parser_confidences",
    "bd_evidence_rows",
    "pipeline_status",
    "pipeline_disclosure_labels",
    "pipeline_disclosure_states",
    "pipeline_disclosure_match_status",
    "pipeline_disclosure_rows",
    "pipeline_disclosure_keys",
    "pipeline_disclosure_last_publication_date",
    "curated_project_ids",
    "curated_stock_codes",
    "curated_registry_ownership_pct",
    "ownership_status",
    "ownership_evidence_level",
    "ownership_evidence_source_count",
    "ownership_evidence_promotion_status",
    "ownership_next_evidence",
    "ownership_effective_from",
    "ownership_effective_to",
    "ownership_interval_status",
    "ownership_interval_evidence_type",
    "ownership_attribution_decision_id",
    "ownership_interval_promotion_status",
    "ownership_attribution_ready",
    "pilot_status",
    "manifest_status",
    "source_urls_json",
    "evidence_count",
    "last_verified_at",
]

SHKP_SALES_INGESTION_ELIGIBILITY_COLUMNS = [
    "registry_key",
    "srpe_development_id",
    "development_name_en",
    "phase_name_en",
    "ownership_status",
    "ownership_effective_from",
    "ownership_effective_to",
    "ownership_interval_status",
    "ownership_interval_evidence_type",
    "ownership_attribution_decision_id",
    "ownership_interval_promotion_status",
    "ownership_attribution_ready",
    "pilot_status",
    "manifest_status",
    "manifest_document_count",
    "register_document_count",
    "price_list_document_count",
    "sales_arrangement_document_count",
    "sales_brochure_document_count",
    "manifest_composite_duplicate_count",
    "eligibility_status",
    "eligibility_reason",
    "source_urls_json",
    "last_verified_at",
]

SHKP_SALES_INGESTION_PLAN_COLUMNS = [
    "plan_key",
    "registry_key",
    "srpe_development_id",
    "development_name_en",
    "phase_name_en",
    "curated_project_ids",
    "curated_stock_codes",
    "pilot_status",
    "eligibility_status",
    "eligibility_reason",
    "ownership_status",
    "ownership_attribution_ready",
    "manifest_status",
    "manifest_document_count",
    "register_document_count",
    "price_list_document_count",
    "sales_arrangement_document_count",
    "sales_brochure_document_count",
    "ingestion_action",
    "allowed_document_categories",
    "parser_gate_status",
    "coverage_status",
    "next_step",
    "blocked_reason",
    "source_urls_json",
    "last_verified_at",
]


_CANONICAL_OWNERSHIP_PCT_FIELDS = (
    "ownership_pct",
    "ownership_observed_pct",
    "curated_registry_ownership_pct",
    "annual_group_interest_pct",
)


def _record_ownership_pct(record: Mapping[str, Any]) -> float | None:
    """Read the first populated numeric ownership field in canonical order."""
    for field in _CANONICAL_OWNERSHIP_PCT_FIELDS:
        value = record.get(field)
        numeric = pd.to_numeric(value, errors="coerce")
        if pd.notna(numeric):
            numeric_value = float(numeric)
            if math.isfinite(numeric_value) and 0.0 <= numeric_value <= 100.0:
                return numeric_value
            return None
    return None


def _record_has_phase_specific_effective_interval(record: Mapping[str, Any]) -> bool:
    """Return whether one record contains a usable bounded ownership interval.

    A boolean ``ownership_attribution_ready`` flag is not evidence by itself:
    callers can pass a hand-built frame (or an old normalized snapshot) that
    predates the interval gate.  The sales gate therefore requires an explicit
    start *and* end date, a numeric ownership percentage, and a separately
    reviewed ``approved_phase_attribution_decision`` with a decision id.
    Supporting both ``ownership_effective_*`` (registry rows) and
    ``effective_*`` (legal observations) keeps the invariant shared across the
    pipeline.
    """
    start = record.get("ownership_effective_from")
    if start is None or not str(start).strip():
        start = record.get("effective_from")
    end = record.get("ownership_effective_to")
    if end is None or not str(end).strip():
        end = record.get("effective_to")
    if start is None or end is None or not str(start).strip() or not str(end).strip():
        return False
    start_ts = pd.to_datetime(start, errors="coerce")
    end_ts = pd.to_datetime(end, errors="coerce")
    if pd.isna(start_ts) or pd.isna(end_ts) or start_ts > end_ts:
        return False
    if _record_ownership_pct(record) is None:
        return False
    promotion_status = str(
        record.get("ownership_interval_promotion_status")
        or record.get("promotion_status")
        or ""
    ).strip().lower()
    evidence_type = str(
        record.get("ownership_interval_evidence_type")
        or record.get("evidence_type")
        or ""
    ).strip().lower()
    decision_id = str(
        record.get("ownership_attribution_decision_id")
        or record.get("attribution_decision_id")
        or record.get("decision_id")
        or ""
    ).strip()
    decision_status = str(record.get("decision_status") or "").strip().lower()
    if decision_status and decision_status != "approved":
        return False
    # Only a separately reviewed phase-attribution decision can open the
    # interval gate.  A generic ``approved`` flag, a land-register row, or a
    # hand-built legacy frame is not sufficient evidence.
    approved_decision = (
        evidence_type == "approved_phase_attribution_decision"
        and bool(decision_id)
        and promotion_status in {"approved_phase_attribution", "approved"}
    )
    if not approved_decision:
        return False
    return promotion_status not in {
        "blocked",
        "blocked_effective_interval",
        "blocked_vendor_only",
        "blocked_grouped_role",
        "blocked_role_only",
    }


def resolve_strict_ownership_attribution(
    record: Mapping[str, Any],
) -> tuple[bool, float | None]:
    """Return the canonical strict-gate decision and numeric ownership.

    This is the shared source-of-truth adapter for downstream signal builders.
    A legacy ready flag, numeric snapshot or bounded dates cannot promote
    attribution without the approved phase-specific decision enforced by
    :func:`_record_has_phase_specific_effective_interval`.
    """
    ownership_pct = _record_ownership_pct(record)
    ready_value = record.get("ownership_attribution_ready")
    if isinstance(ready_value, str):
        ready_flag = ready_value.strip().lower() in {"1", "true", "yes", "y"}
    else:
        try:
            ready_flag = bool(ready_value) if not pd.isna(ready_value) else False
        except (TypeError, ValueError):
            ready_flag = False
    ready = (
        str(record.get("ownership_status") or "").strip() == "consistent_numeric"
        and ready_flag
        and ownership_pct is not None
        and _record_has_phase_specific_effective_interval(record)
    )
    return ready, ownership_pct


def _interval_values(
    records: Iterable[Mapping[str, Any]],
    field: str,
    *,
    registry_prefix: str = "ownership_",
) -> list[str]:
    """Collect unique valid interval endpoints from evidence records."""
    values: list[str] = []
    source_field = f"{registry_prefix}{field}"
    for record in records:
        value = record.get(source_field)
        if value is None or not str(value).strip():
            value = record.get(field)
        if value is None or not str(value).strip():
            continue
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            continue
        text = parsed.date().isoformat()
        if text not in values:
            values.append(text)
    return values

# Future/under-development disclosures often have no SRPE development ID yet,
# or point to several phases.  Keep their identity-resolution work at the
# disclosure grain instead of fabricating a phase row in the sales plan.
SHKP_FUTURE_PROJECT_RESOLUTION_PLAN_COLUMNS = [
    "pipeline_registry_key",
    "disclosure_id",
    "annual_report_id",
    "project_label",
    "project_state",
    "asset_scope",
    "geography",
    "publication_date",
    "source_url",
    "annual_document_url",
    "srpe_match_status",
    "srpe_candidate_ids",
    "srpe_candidate_count",
    "identity_evidence_ids",
    "identity_bridge_status",
    "identity_bridge_match_method",
    "identity_bridge_lot_nos",
    "identity_bridge_phase_labels",
    "identity_bridge_ownership_promotion_status",
    "identity_resolution_action",
    "required_evidence_type",
    "primary_source_url",
    "secondary_source_url",
    "bd_lookup_status",
    "website_lookup_status",
    "resolution_status",
    "linked_srpe_development_id",
    "linked_registry_key",
    "sales_plan_coverage_status",
    "resolution_priority",
    "last_verified_at",
]

# Bounded, official identity bridges for the future-project labels that were
# reviewed in the current step.  This is a separate evidence layer: a lot or
# vendor match is useful for follow-up, but it is not a legal ownership
# interval and does not promote a phase into the sales-ingestion gate.
SHKP_FUTURE_PROJECT_IDENTITY_EVIDENCE_COLUMNS = [
    "identity_evidence_id",
    "project_label",
    "asset_scope",
    "canonical_identity_status",
    "srpe_development_id",
    "srpe_match_status",
    "lot_no_raw",
    "phase_label",
    "address_raw",
    "vendor_raw",
    "holding_company_raw",
    "evidence_date",
    "primary_source_url",
    "secondary_source_url",
    "evidence_summary",
    "ownership_promotion_status",
    "next_step",
    "last_verified_at",
]

# Future-project evidence is intentionally event-sourced.  A new refresh adds
# observations and never rewrites an older disclosure/identity/SRPE event.
# Lifecycle states are separate from identity/ownership evidence so a failed
# lookup or a missing SRPE row cannot be interpreted as a cancellation or zero
# sales.
SHKP_FUTURE_PROJECT_EVENT_COLUMNS = [
    "event_id",
    "event_key",
    "canonical_project_id",
    "project_label",
    "aliases_json",
    "asset_scope",
    "event_type",
    "event_date",
    "event_date_semantics",
    "state_before",
    "state_after",
    "lot_no",
    "address",
    "srpe_development_id",
    "srpe_phase_name",
    "units",
    "gfa_sqft",
    "expected_launch_window",
    "expected_completion_window",
    "ownership_low_pct",
    "ownership_base_pct",
    "ownership_high_pct",
    "ownership_scenario_status",
    "source_url",
    "source_urls_json",
    "source_dataset",
    "evidence_status",
    "evidence_key",
    "sales_queue_status",
    "observed_at",
    "missing_data_policy",
]

SHKP_FUTURE_PROJECT_SNAPSHOT_COLUMNS = [
    "canonical_project_id",
    "project_label",
    "aliases_json",
    "asset_scope",
    "current_state",
    "state_event_date",
    "state_event_type",
    "lot_no",
    "address",
    "srpe_development_id",
    "srpe_phase_name",
    "units",
    "gfa_sqft",
    "expected_launch_window",
    "expected_completion_window",
    "ownership_low_pct",
    "ownership_base_pct",
    "ownership_high_pct",
    "ownership_scenario_status",
    "sales_queue_status",
    "coverage_status",
    "last_event_id",
    "last_observed_at",
    "source_urls_json",
    "missing_data_policy",
]

# A disclosure-level pipeline label is sometimes deliberately descriptive
# (for example ``(descriptive label)``) or carries a lot/address qualifier.
# These aliases are explicit identity bridges only; they do not collapse
# phases, infer ownership, or change the SRPE sales gate.  Keeping the mapping
# here makes the join auditable instead of relying on fuzzy substring matches.
SHKP_FUTURE_PROJECT_IDENTITY_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "Tsuen Wan West project (descriptive label)": ("Tsuen Wan West project",),
    "Kwu Tung adjacent project Phase 1 (descriptive label)": (
        "Kwu Tung adjacent project Phase 1",
    ),
    "Lot No. 1696 in DD 115, Tung Shing Lei, Yuen Long": (
        "Tung Shing Lei Phase 1",
    ),
    "Fanling Sheung Shui Town Lot No. 279, Kwu Tung": (
        "Kwu Tung adjacent project Phase 1",
    ),
    "Fanling Sheung Shui Town Lot No. 279": (
        "Kwu Tung adjacent project Phase 1",
    ),
    "Lot No. 4354 in DD 124, Kiu Tau Wai, Yuen Long": (
        "Lot No. 4354 in DD 124, Kiu Tau Wai",
    ),
}

SHKP_FUTURE_PROJECT_IDENTITY_EVIDENCE: tuple[dict[str, Any], ...] = (
    {
        "identity_evidence_id": "future:artist-square-towers",
        "project_label": "Artist Square Towers",
        "asset_scope": "commercial_investment_bot",
        "canonical_identity_status": "resolved_non_srpe_commercial_bot",
        "srpe_development_id": None,
        "srpe_match_status": "not_applicable_non_srpe",
        "lot_no_raw": None,
        "phase_label": None,
        "address_raw": "West Kowloon Cultural District",
        "vendor_raw": "Sun Hung Kai Properties / WKCD Authority partnership",
        "holding_company_raw": None,
        "evidence_date": "2026-03-13",
        "primary_source_url": "https://www.shkp.com/en-US/media/press-releases/20260313",
        "secondary_source_url": "https://www.shkp.com/en-US/media/press-releases/shkp-wins-tender-for-the-artist-square-towers-project-in-west-kowloon-creating",
        "evidence_summary": "Three harbourfront commercial towers; approximately 672,000 sq ft office and 27,000 sq ft retail; BOT/development partnership, not an SRPE first-hand residential phase.",
        "ownership_promotion_status": "not_applicable_non_residential",
        "next_step": "route_to_commercial_registry",
    },
    {
        "identity_evidence_id": "future:sha-po-south",
        "project_label": "Sha Po South project",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "matched_needs_review",
        "srpe_development_id": "11554",
        "srpe_match_status": "matched_needs_review",
        "lot_no_raw": "Lot 1071 in DD103",
        "phase_label": None,
        "address_raw": "1A Ying Ho Road, Kam Tin North",
        "vendor_raw": "Ease Gold Development Limited",
        "holding_company_raw": "Sun Hung Kai Properties Holding Investment Limited; Vast Earn; Peak Harbour",
        "evidence_date": "2026-06",
        "primary_source_url": "https://www.landsd.gov.hk/doc/en/consent/monthly/t1_2606.pdf",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "Official LandsD lot/address/vendor row intersects SRPE 11554 Garden Regency; identity is phase-linked but ownership remains a separate review.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "obtain dated Ease Gold legal ownership interval",
    },
    {
        "identity_evidence_id": "future:tsuen-wan-west",
        "project_label": "Tsuen Wan West project",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "matched_needs_review",
        "srpe_development_id": "11505",
        "srpe_match_status": "matched_needs_review",
        "lot_no_raw": "TWTL 160",
        "phase_label": None,
        "address_raw": "21 Wang Wo Tsai Street",
        "vendor_raw": "Tippon Investment Enterprises Limited",
        "holding_company_raw": "Sun Hung Kai Properties Limited; Win Profit Properties Limited",
        "evidence_date": "2026-02-16",
        "primary_source_url": "https://www.landsd.gov.hk/doc/en/consent/district/since1994/accessible/Tsuen%20Wan%5Bfrom%201994%5Dwac_e.pdf",
        "secondary_source_url": "https://www.tpb.gov.hk/tc/plan_application/Attachment/20200707/s16fi_A_TW_515_3_gist.pdf",
        "evidence_summary": "TWTL 160 and Wang Wo Tsai address/vendor evidence bridges the descriptive label to SRPE 11505 Lime Spark; regulatory vendor evidence is not an ownership interval.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "obtain dated Tippon/Win Profit legal ownership and SHKP attributable percentage",
    },
    {
        "identity_evidence_id": "future:city-one-sha-tin",
        "project_label": "City One Sha Tin project",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "lot_resolved_srpe_pending",
        "srpe_development_id": None,
        "srpe_match_status": "unmatched",
        "lot_no_raw": "Sha Tin Town Lot No. 623",
        "phase_label": None,
        "address_raw": "Yuen Shun Circuit, Siu Lek Yuen",
        "vendor_raw": "Fair Opal Limited",
        "holding_company_raw": "Sun Hung Kai Properties Limited",
        "evidence_date": "2024-07-17",
        "primary_source_url": "https://www.info.gov.hk/gia/general/202407/17/P2024071700583.htm",
        "secondary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/FY26%20Interim%20Results_For%20Website.pdf",
        "evidence_summary": "Tender and official presentation identify STTL623/Siu Lek Yuen, but the current SRPE snapshot has no phase ID or marketing site.",
        "ownership_promotion_status": "blocked_srpe_identity",
        "next_step": "poll SRPE and LandsD presale-consent records for phase/website identity",
    },
    {
        "identity_evidence_id": "future:kwu-tung-adjacent-phase-1",
        "project_label": "Kwu Tung adjacent project Phase 1",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "lot_resolved_srpe_pending",
        "srpe_development_id": None,
        "srpe_match_status": "unmatched",
        "lot_no_raw": "Fanling Sheung Shui Town Lot No. 279",
        "phase_label": "Phase 1",
        "address_raw": "Area 25, Kwu Tung",
        "vendor_raw": "Asset Capital Limited",
        "holding_company_raw": "Sun Hung Kai Properties",
        "evidence_date": "2021-04-27",
        "primary_source_url": "https://www.info.gov.hk/gia/general/202104/27/P2021042700641.htm",
        "secondary_source_url": "https://www.tpb.gov.hk/uploads/page/meetings/20250606/A_KTN_105_MainPaper.pdf",
        "evidence_summary": "Tender and planning evidence identify FSSTL279 and Phase 1 near Kwu Tung Station; no SRPE phase ID is present yet.",
        "ownership_promotion_status": "blocked_srpe_identity",
        "next_step": "poll SRPE for the first sales document and phase-specific vendor",
    },
    {
        "identity_evidence_id": "future:kwu-tung-south",
        "project_label": "Kwu Tung South residential development",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "lot_resolved_srpe_pending",
        "srpe_development_id": None,
        "srpe_match_status": "unmatched",
        "lot_no_raw": "Lot 2579 in DD92",
        "phase_label": None,
        "address_raw": "Kwu Tung South, Sheung Shui",
        "vendor_raw": None,
        "holding_company_raw": "Sun Hung Kai Properties (100% stake in disclosure)",
        "evidence_date": "2025-06-30",
        "primary_source_url": "https://www.tpb.gov.hk/en/papers/RNTPC/FSYLE/Y_NE-KTS_12/Y_NE-KTS_12_Main%20Paper.pdf",
        "secondary_source_url": "https://www.shkp.com/Content/Uploads/FinReports/SHKPAR_EN_2024_25.pdf",
        "evidence_summary": "Official planning and annual-report evidence identify DD92 Lot 2579 and a 100% SHKP project disclosure; no phase/vendor/SRPE ID is public in the current snapshot.",
        "ownership_promotion_status": "blocked_srpe_identity",
        "next_step": "keep separate from FSSTL279 and poll for phase-specific presale evidence",
    },
    {
        "identity_evidence_id": "future:tung-shing-lei-phase-1a",
        "project_label": "Tung Shing Lei Phase 1",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "lot_phase_resolved_srpe_pending",
        "srpe_development_id": None,
        "srpe_match_status": "unmatched",
        "lot_no_raw": "Lot 1696 in DD115",
        "phase_label": "Phase 1A",
        "address_raw": "28 Ho Chau Road",
        "vendor_raw": "Richduty Development Limited",
        "holding_company_raw": "Sun Hung Kai Properties Holding Investment",
        "evidence_date": "2026-06",
        "primary_source_url": "https://www.landsd.gov.hk/doc/en/consent/monthly/t2_2606.pdf",
        "secondary_source_url": "https://www.shkp.com/Content/Uploads/FinReports/SHKPAR_EN_2023_24.pdf",
        "evidence_summary": "LandsD pending-consent data distinguishes Lot 1696 Phase 1A (665 units) from Phase 1B; do not bind the broader label to both phases until SRPE identity is published.",
        "ownership_promotion_status": "blocked_srpe_identity",
        "next_step": "poll SRPE and preserve separate 1A/1B phase keys",
    },
    {
        "identity_evidence_id": "future:silicon-hill-phase-1",
        "project_label": "Silicon Hill / University Hill",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "phase_resolved_srpe",
        "srpe_development_id": "8405",
        "srpe_match_status": "matched",
        "lot_no_raw": "Tai Po Town Lot No. 244",
        "phase_label": "Phase 1 / Silicon Hill",
        "address_raw": "63 Yau King Lane, Tai Po",
        "vendor_raw": None,
        "holding_company_raw": "Sun Hung Kai Properties Limited (project-level snapshot only)",
        "evidence_date": "2024-06-30",
        "primary_source_url": "https://www.shkp.com/Content/Uploads/FinReports/SHKPAR_EN_2023_24.pdf",
        "secondary_source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/silicon-hill",
        "evidence_summary": "SHKP's 2023/24 annual report identifies Silicon Hill/University Hill at 63 Yau King Lane with 100% Group's Interest as at 2024-06-30; the official SRPE index resolves Phase 1 as development 8405 with the Silicon Hill website. The project-interest figure is not an effective ownership interval.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "retain phase identity; obtain dated vendor/SPV interval if historical sales are attributed",
    },
    {
        "identity_evidence_id": "future:university-hill-phase-2a",
        "project_label": "Silicon Hill / University Hill",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "phase_resolved_srpe",
        "srpe_development_id": "8445",
        "srpe_match_status": "matched",
        "lot_no_raw": "Tai Po Town Lot No. 244",
        "phase_label": "Phase 2A / University Hill",
        "address_raw": "63 Yau King Lane, Tai Po",
        "vendor_raw": "Channel First Limited (official phase notice)",
        "holding_company_raw": "Sun Hung Kai Properties Limited (project-level snapshot only)",
        "evidence_date": "2023-04-20",
        "primary_source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2023q2/sc/PDF/SHKPQTY_2023q2_ENSC_10-11.pdf",
        "secondary_source_url": "https://www.universityhill.com.hk/",
        "evidence_summary": "The official phase notice names Phase 2A of Tai Po Town Lot No. 244 as University Hill at 63 Yau King Lane; SRPE resolves it as development 8445. Annual-report 100% Group's Interest remains a dated project snapshot, not a phase ownership interval.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "retain phase identity; obtain dated Channel First/SPV interval if historical sales are attributed",
    },
    {
        "identity_evidence_id": "future:university-hill-phase-2b",
        "project_label": "Silicon Hill / University Hill",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "phase_resolved_srpe",
        "srpe_development_id": "9245",
        "srpe_match_status": "matched",
        "lot_no_raw": "Tai Po Town Lot No. 244",
        "phase_label": "Phase 2B / University Hill",
        "address_raw": "63 Yau King Lane, Tai Po",
        "vendor_raw": None,
        "holding_company_raw": "Sun Hung Kai Properties Limited (project-level snapshot only)",
        "evidence_date": "2023-04-20",
        "primary_source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2023q2/sc/PDF/SHKPQTY_2023q2_ENSC_10-11.pdf",
        "secondary_source_url": "https://www.universityhill.com.hk/p2b",
        "evidence_summary": "The official phase notice names Phase 2B of Tai Po Town Lot No. 244 as University Hill at 63 Yau King Lane; SRPE resolves it as development 9245 with the /p2b website. Identity is phase-resolved, but no dated SHKP economic-interest interval is inferred.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "retain phase identity; obtain dated vendor/SPV interval if historical sales are attributed",
    },
    {
        "identity_evidence_id": "future:yoho-west-parkside-phase-2",
        "project_label": "YOHO WEST PARKSIDE / Tin Wing Stop Development",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "matched_needs_review",
        "srpe_development_id": "10585",
        "srpe_match_status": "matched_needs_review",
        "lot_no_raw": "Tin Shui Wai Town Lot No. 23",
        "phase_label": "Phase 2 / YOHO WEST PARKSIDE",
        "address_raw": "Tin Shui Wai",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "The SHKP completion schedule identifies the Tin Wing Stop/Tin Shui Wai Town Lot 23 development and SRPE resolves YOHO WEST PARKSIDE Phase 2 as development 10585. Identity is phase-linked only; the schedule's JV label does not establish SHKP's share or effective interval.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "retain phase identity; obtain dated JV/SPV economics before sales attribution",
    },
    {
        "identity_evidence_id": "future:cullinan-sky-phase-2",
        "project_label": "Cullinan Sky Phase 2",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "matched_needs_review",
        "srpe_development_id": "11005",
        "srpe_match_status": "matched_needs_review",
        "lot_no_raw": "NKIL 6568",
        "phase_label": "Phase 2",
        "address_raw": "Kai Tak",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2025-06-30",
        "primary_source_url": "https://www.shkp.com/Content/Uploads/FinReports/SHKPAR_EN_2024_25.pdf",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "SHKP's annual report and completion disclosures separately name Cullinan Sky Phase 2, while SRPE resolves the phase as development 11005. The grouped Cullinan Sky/Sky Mall interest is not a phase-specific effective interval.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "obtain Phase-2 vendor/SPV evidence with effective dates",
    },
    {
        "identity_evidence_id": "future:tuen-mun-a16-station-package-one",
        "project_label": "Tuen Mun A16 Station Package One Property Development",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "lot_resolved_srpe_pending",
        "srpe_development_id": None,
        "srpe_match_status": "unmatched",
        "lot_no_raw": "Tuen Mun A16 Station Package One",
        "phase_label": None,
        "address_raw": "Tuen Mun",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/FY26%20Interim%20Results_For%20Website.pdf",
        "secondary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "evidence_summary": "The FY2026 interim presentation and completion schedule identify a residential Tuen Mun A16 station-package project with completion FY2028/29 or beyond; no SRPE development or phase ID is present in the current index.",
        "ownership_promotion_status": "blocked_srpe_identity",
        "next_step": "poll SRPE and first-hand sales notices for development/phase identity",
    },
    {
        "identity_evidence_id": "future:tung-chung-town-lot-55",
        "project_label": "Tung Chung Town Lot No. 55",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "lot_resolved_srpe_pending",
        "srpe_development_id": None,
        "srpe_match_status": "unmatched",
        "lot_no_raw": "Tung Chung Town Lot No. 55",
        "phase_label": None,
        "address_raw": "Tung Chung",
        "vendor_raw": "Land Castle Limited (tender award; parent-company evidence only)",
        "holding_company_raw": "Sun Hung Kai Properties Limited (parent-company observation only)",
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.info.gov.hk/gia/general/202502/19/P2025021900449p.htm",
        "secondary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "evidence_summary": "LandsD tender evidence links Land Castle to SHKP's stated parent and the completion schedule lists Tung Chung Town Lot 55 as a future residential project; no SRPE phase ID or continuous ownership interval is available.",
        "ownership_promotion_status": "blocked_srpe_identity",
        "next_step": "poll SRPE and statutory sales documents; keep tender-parent evidence separate from ownership",
    },
    {
        "identity_evidence_id": "future:sha-tin-town-lot-651",
        "project_label": "Sha Tin Town Lot No. 651",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "lot_resolved_srpe_pending",
        "srpe_development_id": None,
        "srpe_match_status": "unmatched",
        "lot_no_raw": "Sha Tin Town Lot No. 651, Tai Wai",
        "phase_label": None,
        "address_raw": "Tai Wai, Sha Tin",
        "vendor_raw": "Land Castle Limited (tender award; parent-company evidence only)",
        "holding_company_raw": "Sun Hung Kai Properties Limited (parent-company observation only)",
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.info.gov.hk/gia/general/202501/27/P2025012700497.htm",
        "secondary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "evidence_summary": "The LandsD tender award and SHKP completion schedule identify a future residential Tai Wai project on STTL 651; the current SRPE index has no matching development or phase ID.",
        "ownership_promotion_status": "blocked_srpe_identity",
        "next_step": "poll SRPE and first-hand sales notices for development/phase identity",
    },
    {
        "identity_evidence_id": "future:fanling-sheung-shui-town-lot-307",
        "project_label": "Fanling Sheung Shui Town Lot No. 307",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "lot_resolved_srpe_pending",
        "srpe_development_id": None,
        "srpe_match_status": "unmatched",
        "lot_no_raw": "Fanling Sheung Shui Town Lot No. 307",
        "phase_label": None,
        "address_raw": "Fanling North",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "The completion schedule identifies a future residential/shops project on Fanling Sheung Shui Town Lot 307; no SRPE development or phase ID is present in the current index.",
        "ownership_promotion_status": "blocked_srpe_identity",
        "next_step": "poll SRPE and first-hand sales notices for development/phase identity",
    },
    {
        "identity_evidence_id": "future:hung-shui-kiu-town-lot-5",
        "project_label": "Hung Shui Kiu Town Lot No. 5",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "lot_resolved_srpe_pending",
        "srpe_development_id": None,
        "srpe_match_status": "unmatched",
        "lot_no_raw": "Hung Shui Kiu Town Lot No. 5",
        "phase_label": None,
        "address_raw": "Hung Shui Kiu",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "The completion schedule identifies a future residential/shops project on Hung Shui Kiu Town Lot 5 with no current SRPE development or phase ID.",
        "ownership_promotion_status": "blocked_srpe_identity",
        "next_step": "poll SRPE and first-hand sales notices for development/phase identity",
    },
    {
        "identity_evidence_id": "future:dd105-lot-2091",
        "project_label": "Lot No. 2091 in DD 105, Shek Wu Wai",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "lot_resolved_srpe_pending",
        "srpe_development_id": None,
        "srpe_match_status": "unmatched",
        "lot_no_raw": "Lot No. 2091 in DD 105",
        "phase_label": None,
        "address_raw": "Shek Wu Wai, Yuen Long",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "The completion schedule carries a 54.5% project-interest snapshot for this future residential project; no SRPE phase identity is currently published and the percentage is not an effective interval.",
        "ownership_promotion_status": "blocked_srpe_identity",
        "next_step": "poll SRPE and retain the 54.5% schedule snapshot separately from attributable sales",
    },
    {
        "identity_evidence_id": "future:dd104-lot-4805",
        "project_label": "Lot No. 4805 in DD 104",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "lot_resolved_srpe_pending",
        "srpe_development_id": None,
        "srpe_match_status": "unmatched",
        "lot_no_raw": "Lot No. 4805 in DD 104",
        "phase_label": None,
        "address_raw": "Yuen Long",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "The completion schedule identifies a future residential project on DD104 Lot 4805; current SRPE has no phase ID and the schedule's 100% is a dated project snapshot only.",
        "ownership_promotion_status": "blocked_srpe_identity",
        "next_step": "poll SRPE and first-hand sales notices for development/phase identity",
    },
    {
        "identity_evidence_id": "future:three-fat-tseung-street",
        "project_label": "3 Fat Tseung Street",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "lot_resolved_srpe_pending",
        "srpe_development_id": None,
        "srpe_match_status": "unmatched",
        "lot_no_raw": "3 Fat Tseung Street",
        "phase_label": None,
        "address_raw": "Cheung Sha Wan",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/FY26%20Interim%20Results_For%20Website.pdf",
        "secondary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "evidence_summary": "The FY2026 interim presentation and completion schedule identify a future residential/shops project at 3 Fat Tseung Street with a 50% project-interest snapshot; no SRPE identity or effective interval is available.",
        "ownership_promotion_status": "blocked_srpe_identity",
        "next_step": "poll SRPE and preserve the 50% project snapshot without company-level sales attribution",
    },
    {
        "identity_evidence_id": "future:dd124-lot-4354-commercial",
        "project_label": "Lot No. 4354 in DD 124, Kiu Tau Wai",
        "asset_scope": "commercial_investment",
        "canonical_identity_status": "resolved_non_srpe_commercial",
        "srpe_development_id": None,
        "srpe_match_status": "not_applicable_non_residential",
        "lot_no_raw": "Lot No. 4354 in DD 124",
        "phase_label": None,
        "address_raw": "Kiu Tau Wai, Yuen Long",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "The completion schedule classifies this future project as shops/office rather than first-hand residential; route it to commercial property tracking instead of SRPE residential sales.",
        "ownership_promotion_status": "not_applicable_non_residential",
        "next_step": "route to commercial registry",
    },
    {
        "identity_evidence_id": "future:kil11273-commercial",
        "project_label": "Kowloon Inland Lot No. 11273, Mong Kok",
        "asset_scope": "commercial_investment",
        "canonical_identity_status": "resolved_non_srpe_commercial",
        "srpe_development_id": None,
        "srpe_match_status": "not_applicable_non_residential",
        "lot_no_raw": "Kowloon Inland Lot No. 11273",
        "phase_label": None,
        "address_raw": "Mong Kok",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "The schedule records office/shops for KIL11273, not a first-hand residential phase; exclude it from SRPE residential ingestion.",
        "ownership_promotion_status": "not_applicable_non_residential",
        "next_step": "route to commercial registry",
    },
    {
        "identity_evidence_id": "future:mega-idc-data-centre",
        "project_label": "MEGA IDC",
        "asset_scope": "data_centre",
        "canonical_identity_status": "resolved_non_srpe_non_residential",
        "srpe_development_id": None,
        "srpe_match_status": "not_applicable_non_residential",
        "lot_no_raw": "Tseung Kwan O Town Lot No. 131",
        "phase_label": None,
        "address_raw": "Tseung Kwan O",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "MEGA IDC is a data-centre project in SHKP's completion schedule, not a first-hand residential phase; exclude it from SRPE residential sales tracking.",
        "ownership_promotion_status": "not_applicable_non_residential",
        "next_step": "route to data-centre/commercial registry",
    },
    {
        "identity_evidence_id": "future:lot-1077-anderson-road-nonresidential",
        "project_label": "Lot No. 1077 in Survey District No. 3, off Anderson Road",
        "asset_scope": "commercial_investment",
        "canonical_identity_status": "resolved_non_srpe_non_residential",
        "srpe_development_id": None,
        "srpe_match_status": "not_applicable_non_residential",
        "lot_no_raw": "Lot No. 1077 in Survey District No. 3",
        "phase_label": None,
        "address_raw": "off Anderson Road, Kwun Tong",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.info.gov.hk/gia/general/202211/23/P2022112300669p.htm",
        "secondary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "evidence_summary": "LandsD tender/use evidence and the completion schedule classify this as non-residential commercial/industrial development; it is excluded from SRPE residential sales ingestion.",
        "ownership_promotion_status": "not_applicable_non_residential",
        "next_step": "route to commercial/industrial registry",
    },
    {
        "identity_evidence_id": "future:high-speed-rail-west-kowloon-commercial",
        "project_label": "High Speed Rail West Kowloon Terminus Development",
        "asset_scope": "commercial_investment",
        "canonical_identity_status": "resolved_non_srpe_commercial",
        "srpe_development_id": None,
        "srpe_match_status": "not_applicable_non_residential",
        "lot_no_raw": None,
        "phase_label": None,
        "address_raw": "West Kowloon",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "The annual-report/schedule project is a railway-terminus commercial development and not an SRPE first-hand residential phase.",
        "ownership_promotion_status": "not_applicable_non_residential",
        "next_step": "route to commercial/JV registry",
    },
    {
        "identity_evidence_id": "future:international-gateway-centre-commercial",
        "project_label": "International Gateway Centre (IGC)",
        "asset_scope": "commercial_investment",
        "canonical_identity_status": "resolved_non_srpe_commercial",
        "srpe_development_id": None,
        "srpe_match_status": "not_applicable_non_residential",
        "lot_no_raw": None,
        "phase_label": "Office portion",
        "address_raw": "Hong Kong / West Kowloon",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "IGC is an office/data-centre-related project in SHKP disclosures, not a first-hand residential phase; exclude from SRPE residential sales ingestion.",
        "ownership_promotion_status": "not_applicable_non_residential",
        "next_step": "route to commercial/data-centre registry",
    },
    {
        "identity_evidence_id": "future:scramble-hill-commercial",
        "project_label": "Scramble Hill",
        "asset_scope": "commercial_investment",
        "canonical_identity_status": "resolved_non_srpe_commercial",
        "srpe_development_id": None,
        "srpe_match_status": "not_applicable_non_residential",
        "lot_no_raw": None,
        "phase_label": None,
        "address_raw": "Kwun Tong",
        "vendor_raw": None,
        "holding_company_raw": None,
        "evidence_date": "2026-02-28",
        "primary_source_url": "https://www.shkp.com/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "Scramble Hill is an investment-property/commercial label in SHKP annual disclosures, not an SRPE residential development.",
        "ownership_promotion_status": "not_applicable_non_residential",
        "next_step": "route to commercial registry",
    },
    {
        "identity_evidence_id": "priority:cullinan-sky-phase-1",
        "project_label": "Cullinan Sky Phase 1",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "phase_resolved_srpe",
        "srpe_development_id": "9366",
        "srpe_match_status": "matched",
        "lot_no_raw": "NKIL 6568",
        "phase_label": "Phase 1",
        "address_raw": "Kai Tak, 10 Concorde Road",
        "vendor_raw": "Super Great Limited",
        "holding_company_raw": "Master Summit Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "evidence_date": "2026-08-03",
        "primary_source_url": "https://www.cullinansky.com.hk/",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "Official phase website and SRPE identity bridge Cullinan Sky Phase 1 to SRPE 9366 and NKIL 6568; vendor/holding labels are role evidence only and do not establish ownership percentage or effective dates.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "obtain phase-specific Super Great/SPV economic-interest interval",
    },
    {
        "identity_evidence_id": "priority:cullinan-harbour-phase-1",
        "project_label": "Cullinan Harbour Phase 1",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "phase_resolved_srpe",
        "srpe_development_id": "9785",
        "srpe_match_status": "matched",
        "lot_no_raw": "NKIL 6551",
        "phase_label": "Phase 1",
        "address_raw": "Kai Tak",
        "vendor_raw": "Well Capital (H.K.) Limited",
        "holding_company_raw": "Sun Hung Kai Properties Limited; Time Effort Limited; Trade Up Ventures Limited",
        "evidence_date": "2026-08-03",
        "primary_source_url": "https://www.cullinanharbour.com.hk/phasei/en/",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "Official phase page and SRPE identity bridge Cullinan Harbour Phase 1 to SRPE 9785 and NKIL 6551; the role chain does not state phase economics or effective dates.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "obtain phase-specific Well Capital/SPV economic-interest interval",
    },
    {
        "identity_evidence_id": "priority:cullinan-harbour-phase-2a",
        "project_label": "Cullinan Harbour Phase 2A",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "phase_resolved_srpe",
        "srpe_development_id": "10405",
        "srpe_match_status": "matched",
        "lot_no_raw": "NKIL 6551",
        "phase_label": "Phase 2A",
        "address_raw": "Kai Tak",
        "vendor_raw": "Well Capital (H.K.) Limited",
        "holding_company_raw": "Sun Hung Kai Properties Limited; Time Effort Limited; Trade Up Ventures Limited",
        "evidence_date": "2026-08-03",
        "primary_source_url": "https://www.cullinanharbour.com.hk/phaseii/en/",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "Official phase page and SRPE identity bridge Cullinan Harbour Phase 2A to SRPE 10405 and NKIL 6551; grouped role evidence does not establish phase economics or effective dates.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "obtain phase-specific Well Capital/SPV economic-interest interval",
    },
    {
        "identity_evidence_id": "priority:cullinan-harbour-phase-2b",
        "project_label": "Cullinan Harbour Phase 2B",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "phase_resolved_srpe",
        "srpe_development_id": "11516",
        "srpe_match_status": "matched",
        "lot_no_raw": "NKIL 6551",
        "phase_label": "Phase 2B",
        "address_raw": "Kai Tak",
        "vendor_raw": "Well Capital (H.K.) Limited",
        "holding_company_raw": "Sun Hung Kai Properties Limited; Time Effort Limited; Trade Up Ventures Limited",
        "evidence_date": "2026-08-03",
        "primary_source_url": "https://www.cullinanharbour.com.hk/phaseiib/en/",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "Official phase page and SRPE identity bridge Cullinan Harbour Phase 2B to SRPE 11516 and NKIL 6551; the current 100% snapshot remains non-interval evidence.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "obtain phase-specific Well Capital/SPV economic-interest interval",
    },
    {
        "identity_evidence_id": "priority:sierra-sea-phase-2a",
        "project_label": "Sierra Sea Phase 2A",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "phase_resolved_srpe",
        "srpe_development_id": "11305",
        "srpe_match_status": "matched",
        "lot_no_raw": "Tai Po Town Lot No. 253 Sai Sha",
        "phase_label": "Phase 2A",
        "address_raw": "8 Hoi Ying Road, Sai Sha",
        "vendor_raw": "Light Time Investments Limited",
        "holding_company_raw": "Sun Hung Kai Properties Limited; Vast Earn Limited; Williston Limited",
        "evidence_date": "2026-08-03",
        "primary_source_url": "https://www.sierrasea2a.com.hk/en/",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "Official Sierra Sea Phase 2A page and SRPE identity bridge resolve SRPE 11305 on Tai Po Town Lot 253; the grouped 100% project snapshot cannot be allocated to a phase interval.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "obtain Light Time/SPV phase-specific economics and continuity evidence",
    },
    {
        "identity_evidence_id": "priority:sierra-sea-phase-2b",
        "project_label": "Sierra Sea Phase 2B",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "phase_resolved_srpe",
        "srpe_development_id": "11345",
        "srpe_match_status": "matched",
        "lot_no_raw": "Tai Po Town Lot No. 253 Sai Sha",
        "phase_label": "Phase 2B",
        "address_raw": "8 Hoi Ying Road, Sai Sha",
        "vendor_raw": "Light Time Investments Limited",
        "holding_company_raw": "Sun Hung Kai Properties Limited; Vast Earn Limited; Williston Limited",
        "evidence_date": "2026-08-03",
        "primary_source_url": "https://www.sierrasea2b.com.hk/en/",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "Official Sierra Sea Phase 2B page and SRPE identity bridge resolve SRPE 11345 on Tai Po Town Lot 253; role evidence and grouped snapshots do not establish a phase interval.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "obtain Light Time/SPV phase-specific economics and continuity evidence",
    },
    {
        "identity_evidence_id": "priority:yoho-west-phase-1",
        "project_label": "YOHO WEST Phase 1",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "phase_resolved_srpe",
        "srpe_development_id": "9565",
        "srpe_match_status": "matched",
        "lot_no_raw": "Tin Shui Wai Town Lot No. 23",
        "phase_label": "Phase 1",
        "address_raw": "1 Tin Yan Road, Tin Shui Wai",
        "vendor_raw": "MTR Corporation Limited (Owner); Best Vision Development Limited (Person so engaged)",
        "holding_company_raw": "Better Sun Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "evidence_date": "2026-08-03",
        "primary_source_url": "https://www.yohowest.com.hk/",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "Official statutory project page and SRPE identity bridge resolve YOHO WEST Phase 1 to SRPE 9565; MTR/Best Vision role labels and JV status do not disclose SHKP economic share or interval.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "obtain dated MTR/Best Vision JV economics and SHKP share interval",
    },
    {
        "identity_evidence_id": "priority:yoho-hub-phase-b",
        "project_label": "The YOHO Hub Phase B",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "phase_resolved_srpe",
        "srpe_development_id": "7845",
        "srpe_match_status": "matched",
        "lot_no_raw": "Yuen Long Town Lot No. 510",
        "phase_label": "Phase B",
        "address_raw": "Yuen Long Station",
        "vendor_raw": "Yuen Long Property Development Limited (Owner); Success Keep Limited (Person so engaged)",
        "holding_company_raw": "Sun Hung Kai Properties Limited; Time Effort Limited; Able Mariner Limited",
        "evidence_date": "2026-08-03",
        "primary_source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/the-yoho-hub",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "Official SHKP/project role page and SRPE identity bridge resolve The YOHO Hub Phase B to SRPE 7845; the JV label has no numeric SHKP economics or effective interval.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "obtain dated Yuen Long Property Development/Success Keep JV economics and interval",
    },
    {
        "identity_evidence_id": "priority:yoho-hub-phase-c",
        "project_label": "The YOHO Hub II Phase C",
        "asset_scope": "residential_first_hand",
        "canonical_identity_status": "phase_resolved_srpe",
        "srpe_development_id": "8525",
        "srpe_match_status": "matched",
        "lot_no_raw": "Yuen Long Town Lot No. 510",
        "phase_label": "Phase C",
        "address_raw": "Yuen Long Station",
        "vendor_raw": "Yuen Long Property Development Limited (Owner); Success Keep Limited (Person so engaged)",
        "holding_company_raw": "Sun Hung Kai Properties Limited; Time Effort Limited; Able Mariner Limited",
        "evidence_date": "2026-08-03",
        "primary_source_url": "https://www.theyohohub2.com.hk/home?lang=en",
        "secondary_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "evidence_summary": "Official project role page and SRPE identity bridge resolve The YOHO Hub II Phase C to SRPE 8525; the JV role evidence has no numeric SHKP economics or effective interval.",
        "ownership_promotion_status": "blocked_effective_interval",
        "next_step": "obtain dated Yuen Long Property Development/Success Keep JV economics and interval",
    },
)

SHKP_OWNERSHIP_REVIEW_QUEUE_COLUMNS = [
    "registry_key",
    "srpe_development_id",
    "development_name_en",
    "phase_name_en",
    "address_en",
    "ownership_status",
    "ownership_attribution_ready",
    "eligibility_status",
    "review_scope",
    "review_priority",
    "evidence_layers_present",
    "evidence_count",
    "annual_group_interest_raw",
    "annual_group_interest_pct",
    "planning_lot_nos",
    "planning_entity_labels",
    "review_reason",
    "suggested_next_source",
    "source_urls_json",
    "last_verified_at",
]

SHKP_HISTORICAL_PHASE_REVIEW_QUEUE_COLUMNS = [
    "review_key",
    "report_id",
    "report_period_end",
    "evidence_type",
    "project_label",
    "annual_location",
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "active",
    "srpe_date_suspend_sales",
    "srpe_date_complete_sales",
    "match_status",
    "match_confidence",
    "match_method",
    "candidate_count",
    "transaction_manifest_rows",
    "transaction_manifest_status",
    "review_priority",
    "review_action",
    "review_reason",
    "annual_document_url",
    "last_verified_at",
]

SHKP_HISTORICAL_MANIFEST_COVERAGE_COLUMNS = [
    "srpe_development_id",
    "development_name_en",
    "phase_name_en",
    "active",
    "universe_status",
    "evidence_count",
    "manifest_rows",
    "register_rows",
    "price_list_rows",
    "sales_arrangement_rows",
    "sales_brochure_rows",
    "manifest_status",
    "transaction_backfill_status",
    "selection_scope",
    "source_urls_json",
    "last_verified_at",
]

# The historical manifest audit is persisted as a separate dataset, but the
# parent roster is the object most callers inspect.  Keep the generic
# ``manifest_status`` field (which refers to the current/live manifest layer)
# untouched and expose the historical backfill state under an explicit prefix.
SHKP_HISTORICAL_ROSTER_COVERAGE_COLUMNS = [
    "historical_manifest_status",
    "historical_manifest_rows",
    "historical_register_rows",
    "historical_price_list_rows",
    "historical_sales_arrangement_rows",
    "historical_sales_brochure_rows",
    "historical_transaction_backfill_status",
    "historical_manifest_selection_scope",
    "historical_manifest_source_urls_json",
    "historical_manifest_last_verified_at",
]

SHKP_HISTORICAL_PHASE_EVIDENCE_COVERAGE_COLUMNS = [
    "registry_key",
    "srpe_development_id",
    "development_name_en",
    "phase_name_en",
    "active",
    "universe_status",
    "universe_evidence_types",
    "evidence_count",
    "ownership_status",
    "ownership_evidence_level",
    "ownership_evidence_source_count",
    "ownership_evidence_promotion_status",
    "ownership_next_evidence",
    "ownership_interval_status",
    "ownership_attribution_ready",
    "manifest_status",
    "historical_manifest_status",
    "historical_manifest_rows",
    "historical_register_rows",
    "historical_price_list_rows",
    "historical_sales_arrangement_rows",
    "historical_sales_brochure_rows",
    "historical_transaction_backfill_status",
    "historical_manifest_selection_scope",
    "source_urls_json",
    "last_verified_at",
]

SHKP_INDICATIVE_OWNERSHIP_COLUMNS = [
    "registry_key",
    "srpe_development_id",
    "development_name_en",
    "phase_name_en",
    "active",
    "universe_status",
    "indicative_owner_status",
    "indicative_ownership_pct",
    "indicative_ownership_pct_low",
    "indicative_ownership_pct_high",
    "indicative_numeric_consistency_status",
    "indicative_confidence",
    "indicative_evidence_basis",
    "indicative_evidence_level",
    "indicative_evidence_source_count",
    "indicative_next_review",
    "indicative_sales_use_status",
    "strict_ownership_status",
    "strict_ownership_attribution_ready",
    "strict_ownership_interval_status",
    "source_urls_json",
    "last_verified_at",
]


def build_shkp_historical_manifest_coverage_audit(
    roster: pd.DataFrame,
    manifest: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Audit SRPE document retention across the full historical parent roster."""
    if roster is None or roster.empty:
        return pd.DataFrame(columns=SHKP_HISTORICAL_MANIFEST_COVERAGE_COLUMNS)
    manifest = manifest if manifest is not None else pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for record in roster.to_dict("records"):
        phase_id = str(record.get("srpe_development_id") or "").strip()
        if not phase_id:
            continue
        phase_manifest = manifest.loc[
            manifest.get("srpe_development_id", pd.Series(dtype="string")).astype("string").eq(phase_id)
        ] if not manifest.empty else pd.DataFrame()
        counts = phase_manifest.get("document_category", pd.Series(dtype="string")).value_counts().to_dict()
        register_rows = int(counts.get("register_of_transactions", 0))
        manifest_rows = int(len(phase_manifest))
        if register_rows:
            manifest_status = "observed_register"
            transaction_status = "transaction_register_available"
        elif manifest_rows:
            manifest_status = "observed_no_register"
            transaction_status = "no_transaction_register_observed"
        else:
            manifest_status = "not_observed"
            transaction_status = "not_probed"
        evidence_count = int(pd.to_numeric(pd.Series([record.get("evidence_count")]), errors="coerce").fillna(0).iloc[0])
        rows.append(
            {
                "srpe_development_id": phase_id,
                "development_name_en": record.get("development_name_en"),
                "phase_name_en": record.get("phase_name_en"),
                "active": record.get("active"),
                "universe_status": record.get("universe_status"),
                "evidence_count": evidence_count,
                "manifest_rows": manifest_rows,
                "register_rows": register_rows,
                "price_list_rows": int(counts.get("price_list", 0)),
                "sales_arrangement_rows": int(counts.get("sales_arrangement", 0)),
                "sales_brochure_rows": int(counts.get("sales_brochure", 0)),
                "manifest_status": manifest_status,
                "transaction_backfill_status": transaction_status,
                "selection_scope": "inactive_historical_evidence" if str(record.get("active") or "").upper() == "N" and evidence_count > 0 else "inactive_unobserved" if str(record.get("active") or "").upper() == "N" else "active_parent_roster",
                "source_urls_json": json.dumps(sorted(set(phase_manifest.get("source_url", pd.Series(dtype="string")).dropna().astype(str))), ensure_ascii=False),
                "last_verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    frame = pd.DataFrame(rows, columns=SHKP_HISTORICAL_MANIFEST_COVERAGE_COLUMNS)
    frame.attrs.update(
        lineage_metadata={
            "lineage_type": "derived_shkp_historical_srpe_manifest_coverage_audit",
            "parent_datasets": ["shkp_historical_phase_roster", "shkp_historical_srpe_document_manifest"],
            "ownership_promotion": False,
            "sales_promotion": False,
        }
    )
    return frame


def enrich_shkp_historical_phase_roster_manifest_coverage(
    roster: pd.DataFrame,
    coverage_audit: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Attach explicit historical-manifest fields to the parent roster.

    ``build_shkp_project_registry`` already has a generic ``manifest_status``
    field for the live/current catalog.  Reusing it for the historical
    backfill would silently overwrite one source layer with another, while
    omitting the audit from the roster leaves callers seeing ``not_loaded``
    even after all inactive phases have been probed.  This helper keeps the
    layers separate and makes the 521-row roster self-auditing.
    """
    if roster is None:
        return pd.DataFrame(columns=list(SHKP_HISTORICAL_ROSTER_COVERAGE_COLUMNS))
    out = roster.copy()
    defaults: dict[str, Any] = {
        "historical_manifest_status": "not_audited",
        "historical_manifest_rows": 0,
        "historical_register_rows": 0,
        "historical_price_list_rows": 0,
        "historical_sales_arrangement_rows": 0,
        "historical_sales_brochure_rows": 0,
        "historical_transaction_backfill_status": "not_audited",
        "historical_manifest_selection_scope": "not_audited",
        "historical_manifest_source_urls_json": "[]",
        "historical_manifest_last_verified_at": None,
    }
    for column, default in defaults.items():
        out[column] = default
    if coverage_audit is None or coverage_audit.empty:
        return out
    if "srpe_development_id" not in out.columns or "srpe_development_id" not in coverage_audit.columns:
        raise ValueError("historical roster and coverage audit require srpe_development_id")

    audit = coverage_audit.copy()
    audit["srpe_development_id"] = audit["srpe_development_id"].astype("string").str.strip()
    audit = audit.loc[audit["srpe_development_id"].ne("")].drop_duplicates(
        subset=["srpe_development_id"], keep="last"
    )
    out["_historical_manifest_join_id"] = out["srpe_development_id"].astype("string").str.strip()
    audit["_historical_manifest_join_id"] = audit["srpe_development_id"]
    rename = {
        "manifest_status": "historical_manifest_status",
        "manifest_rows": "historical_manifest_rows",
        "register_rows": "historical_register_rows",
        "price_list_rows": "historical_price_list_rows",
        "sales_arrangement_rows": "historical_sales_arrangement_rows",
        "sales_brochure_rows": "historical_sales_brochure_rows",
        "transaction_backfill_status": "historical_transaction_backfill_status",
        "selection_scope": "historical_manifest_selection_scope",
        "source_urls_json": "historical_manifest_source_urls_json",
        "last_verified_at": "historical_manifest_last_verified_at",
    }
    available = [
        "_historical_manifest_join_id",
        *[column for column in rename if column in audit.columns],
    ]
    audit = audit[available].rename(columns=rename)
    out = out.merge(audit, on="_historical_manifest_join_id", how="left", suffixes=("", "_audit"))
    out = out.drop(columns=["_historical_manifest_join_id"])
    for column, default in defaults.items():
        audit_column = f"{column}_audit"
        if audit_column in out.columns:
            out[column] = out[audit_column].where(out[audit_column].notna(), out[column])
            out = out.drop(columns=[audit_column])
    return out


def build_shkp_historical_phase_evidence_coverage(
    roster: pd.DataFrame,
) -> pd.DataFrame:
    """Materialise a one-row-per-phase evidence and promotion audit.

    This is a projection of the parent roster, not a second attribution
    engine.  It deliberately retains blocked/empty states so consumers can
    distinguish an SRPE-only phase from a numeric snapshot, a role-only match,
    and an approved phase attribution without joining several source layers.
    """
    if roster is None or roster.empty:
        return pd.DataFrame(columns=SHKP_HISTORICAL_PHASE_EVIDENCE_COVERAGE_COLUMNS)
    rows: list[dict[str, Any]] = []
    for record in roster.to_dict("records"):
        rows.append({column: record.get(column) for column in SHKP_HISTORICAL_PHASE_EVIDENCE_COVERAGE_COLUMNS})
    frame = pd.DataFrame(rows, columns=SHKP_HISTORICAL_PHASE_EVIDENCE_COVERAGE_COLUMNS)
    frame.attrs.update(
        lineage_metadata={
            "lineage_type": "derived_shkp_historical_phase_evidence_coverage",
            "parent_dataset": "shkp_historical_phase_roster",
            "ownership_promotion": False,
            "sales_promotion": False,
        }
    )
    return frame


def build_shkp_indicative_ownership_roster(
    roster: pd.DataFrame,
) -> pd.DataFrame:
    """Create an explicitly non-legal, research-use SHKP ownership view.

    This layer answers the user's practical question ("does this look like an
    SHKP project?") using directory matches, annual/schedule Group-interest
    snapshots, legal-role evidence and JV wording.  It intentionally does not
    populate the strict ownership fields or sales gate.  Numeric percentages
    are labelled indicative because they may be grouped, point-in-time or
    phase-unreconciled.
    """
    if roster is None or roster.empty:
        return pd.DataFrame(columns=SHKP_INDICATIVE_OWNERSHIP_COLUMNS)

    def _json_numeric(value: Any) -> list[float]:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return []
        text = str(value).strip()
        if not text:
            return []
        candidates: list[Any] = [value]
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                candidates = parsed if isinstance(parsed, list) else [parsed]
            except (TypeError, ValueError, json.JSONDecodeError):
                candidates = []
        values = pd.to_numeric(pd.Series(candidates), errors="coerce").dropna()
        return list(dict.fromkeys(float(item) for item in values.tolist() if 0 <= float(item) <= 100))

    # Annual reports often round Group's Interest to a whole percentage while
    # the completion schedule prints one decimal place (for example 53.0 vs
    # 53.3 for KENNEDY 38).  Treat a sub-half-point spread as rounding
    # variation, retain the observed range, and use the median only as an
    # explicitly indicative point estimate.  Larger spreads remain null so a
    # rough model cannot silently pick one conflicting snapshot.
    numeric_rounding_tolerance_pct = 0.5

    rows: list[dict[str, Any]] = []
    for record in roster.to_dict("records"):
        annual_raw = str(record.get("annual_group_interest_raw") or "").upper()
        schedule_raw = str(record.get("completion_schedule_group_interest_raw") or "").upper()
        jv_text = "JV" in annual_raw or "JV" in schedule_raw or str(record.get("ownership_status") or "").lower() == "annual_jv_unresolved"
        numeric_sources = [
            ("annual_report_group_interest_snapshot", record.get("annual_group_interest_pct")),
            ("completion_schedule_group_interest_snapshot", record.get("completion_schedule_group_interest_pct")),
            ("legal_observation_snapshot", record.get("ownership_observed_pct")),
            ("curated_registry_snapshot", record.get("curated_registry_ownership_pct")),
        ]
        numeric_values: list[float] = []
        numeric_basis: list[str] = []
        for basis, value in numeric_sources:
            values = _json_numeric(value)
            if values:
                numeric_basis.append(basis)
                numeric_values.extend(values)
        unique_numeric = list(dict.fromkeys(numeric_values))
        numeric_low = min(unique_numeric) if unique_numeric else None
        numeric_high = max(unique_numeric) if unique_numeric else None
        if not unique_numeric:
            numeric_consistency_status = "not_observed"
        elif len(unique_numeric) == 1:
            numeric_consistency_status = "single_snapshot_value"
        elif numeric_high - numeric_low <= numeric_rounding_tolerance_pct:
            numeric_consistency_status = "rounded_consistent_snapshots"
        else:
            numeric_consistency_status = "conflicting_snapshots"
        current_match = str(record.get("universe_status") or "") == "current_candidate" and str(record.get("shkp_match_status") or "") == "matched"
        current_review = str(record.get("shkp_match_status") or "") == "matched_needs_review"
        any_shkp_evidence = bool(record.get("universe_evidence_types")) or int(record.get("evidence_count") or 0) > 0
        evidence_level = str(record.get("ownership_evidence_level") or "srpe_parent_only")

        curated_promotion = SHKP_CURATED_PROMOTIONS.get(record.get("srpe_development_id"))
        if curated_promotion is not None:
            # Curated promotion from verified annual-report evidence (e.g.
            # The Cullinan / 天璽).  Research-layer numeric stake only; the
            # strict ownership gate remains blocked.
            indicative_pct = curated_promotion
            indicative_owner_status = "likely_shkp_numeric_snapshot"
            indicative_confidence = "medium"
            indicative_evidence_basis = "curated_shkp_promotion|" + (evidence_level or "srpe_parent_only")
            indicative_next_review = "confirm dated SPV/economic-interest continuity"
            indicative_sales_use_status = "indicative_numeric_only"
        elif unique_numeric:
            indicative_pct = (
                unique_numeric[0]
                if len(unique_numeric) == 1 or numeric_consistency_status == "rounded_consistent_snapshots"
                else None
            )
            if numeric_consistency_status == "rounded_consistent_snapshots":
                indicative_pct = float(pd.Series(unique_numeric, dtype="float64").median())
            indicative_owner_status = "likely_shkp_jv_or_grouped" if jv_text else "likely_shkp_numeric_snapshot"
            indicative_confidence = "high" if current_match and not jv_text else "medium"
            indicative_evidence_basis = "|".join(numeric_basis + (["jv_wording"] if jv_text else []))
            indicative_next_review = (
                "confirm phase split and effective dates"
                if (jv_text or len(unique_numeric) > 1)
                else "confirm dated SPV/economic-interest continuity"
            )
            indicative_sales_use_status = (
                "indicative_numeric_conflict"
                if numeric_consistency_status == "conflicting_snapshots"
                else "indicative_numeric_only"
            )
        elif jv_text and (current_match or current_review or any_shkp_evidence):
            curated_stake = SHKP_CURATED_JV_STAKE_OVERRIDES.get(record.get("srpe_development_id"))
            if curated_stake is not None:
                # Verified economic-interest evidence (e.g. Cullinan West is
                # effectively 100% SHKP with MTR as land owner/platform
                # provider, despite the annual report's "JV" label).
                indicative_pct = curated_stake
                indicative_owner_status = "likely_shkp_numeric_snapshot"
                indicative_confidence = "medium"
                indicative_evidence_basis = "curated_jv_stake_override|jv_wording|project_or_phase_evidence"
                indicative_next_review = "confirm dated SPV/economic-interest continuity"
                indicative_sales_use_status = "indicative_numeric_only"
            else:
                indicative_pct = None
                indicative_owner_status = "likely_shkp_jv_unquantified"
                indicative_confidence = "medium" if current_match or current_review else "low"
                indicative_evidence_basis = "jv_wording|project_or_phase_evidence"
                indicative_next_review = "obtain approximate SHKP/JV share; otherwise keep as JV activity"
                indicative_sales_use_status = "indicative_unquantified_jv"
        elif current_match:
            indicative_pct = None
            indicative_owner_status = "likely_shkp_unquantified"
            indicative_confidence = "high"
            indicative_evidence_basis = "exact_current_directory_phase_match"
            indicative_next_review = "find numeric stake if attributable sales are needed"
            indicative_sales_use_status = "indicative_unquantified"
        elif current_review or any_shkp_evidence:
            indicative_pct = None
            indicative_owner_status = "possible_shkp_review"
            indicative_confidence = "low"
            indicative_evidence_basis = evidence_level
            indicative_next_review = "resolve phase identity before using sales activity"
            indicative_sales_use_status = "review_only"
        else:
            indicative_pct = None
            indicative_owner_status = "not_observed"
            indicative_confidence = "none"
            indicative_evidence_basis = "srpe_parent_only"
            indicative_next_review = "find SHKP directory/annual-report/project-site evidence"
            indicative_sales_use_status = "not_covered"

        rows.append({
            "registry_key": record.get("registry_key"),
            "srpe_development_id": record.get("srpe_development_id"),
            "development_name_en": record.get("development_name_en"),
            "phase_name_en": record.get("phase_name_en"),
            "active": record.get("active"),
            "universe_status": record.get("universe_status"),
            "indicative_owner_status": indicative_owner_status,
            "indicative_ownership_pct": indicative_pct,
            "indicative_ownership_pct_low": numeric_low,
            "indicative_ownership_pct_high": numeric_high,
            "indicative_numeric_consistency_status": numeric_consistency_status,
            "indicative_confidence": indicative_confidence,
            "indicative_evidence_basis": indicative_evidence_basis,
            "indicative_evidence_level": evidence_level,
            "indicative_evidence_source_count": record.get("ownership_evidence_source_count", 0),
            "indicative_next_review": indicative_next_review,
            "indicative_sales_use_status": indicative_sales_use_status,
            "strict_ownership_status": record.get("ownership_status"),
            "strict_ownership_attribution_ready": bool(record.get("ownership_attribution_ready")),
            "strict_ownership_interval_status": record.get("ownership_interval_status"),
            "source_urls_json": record.get("source_urls_json"),
            "last_verified_at": record.get("last_verified_at"),
        })
    frame = pd.DataFrame(rows, columns=SHKP_INDICATIVE_OWNERSHIP_COLUMNS)
    frame.attrs.update(
        lineage_metadata={
            "lineage_type": "derived_shkp_indicative_ownership_roster",
            "parent_dataset": "shkp_historical_phase_roster",
            "strict_ownership_promotion": False,
            "indicative_use_only": True,
            "numeric_semantics": "point_in_time_or_grouped_snapshot; not legal effective interval",
        }
    )
    return frame


def build_shkp_historical_phase_review_queue(
    annual_crosswalk: pd.DataFrame,
    roster: pd.DataFrame,
    manifest: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Materialise alias/address/lot review work from annual-to-SRPE joins.

    The queue keeps unmatched annual labels even when no SRPE ID exists. A
    matched candidate is still review-only, and manifest coverage is reported
    as a separate operational field rather than treated as ownership evidence.
    """
    if annual_crosswalk is None or annual_crosswalk.empty:
        return pd.DataFrame(columns=SHKP_HISTORICAL_PHASE_REVIEW_QUEUE_COLUMNS)
    roster_by_id = {
        str(row.get("srpe_development_id")): row
        for row in (roster.to_dict("records") if roster is not None and not roster.empty else [])
        if str(row.get("srpe_development_id") or "").strip()
    }
    manifest_counts: dict[str, int] = {}
    if manifest is not None and not manifest.empty and "srpe_development_id" in manifest.columns:
        counts = manifest.loc[
            manifest.get("document_category", pd.Series(dtype="string")).astype("string").eq("register_of_transactions")
        ].groupby(manifest["srpe_development_id"].astype(str)).size()
        manifest_counts = {str(key): int(value) for key, value in counts.items()}
    rows: list[dict[str, Any]] = []
    for record in annual_crosswalk.to_dict("records"):
        status = str(record.get("match_status") or "unmatched")
        if status not in {"ambiguous", "matched_needs_review", "unmatched"}:
            continue
        # `or ""` is not enough to normalise a missing id: a null read out of a
        # DataFrame arrives as NaN, which is truthy, so str() would yield the
        # literal "nan" and an unmatched row would look matched.
        raw_phase_id = record.get("srpe_development_id")
        if raw_phase_id is None or (isinstance(raw_phase_id, float) and pd.isna(raw_phase_id)):
            raw_phase_id = ""
        phase_id = str(raw_phase_id).strip() or None
        phase = roster_by_id.get(phase_id or "", {})
        manifest_rows = manifest_counts.get(phase_id or "", 0)
        active = str(phase.get("active") or "").strip() or None
        if status == "matched_needs_review" and phase_id and active == "N":
            priority = "P0"
        elif status == "ambiguous" and phase_id:
            priority = "P1"
        else:
            priority = "P2"
        if not phase_id:
            action = "manual_alias_address_lot_reconciliation"
            reason = "annual project label has no conservative SRPE phase match"
        elif status == "ambiguous":
            action = "manual_phase_lot_or_address_disambiguation"
            reason = "annual label maps to multiple SRPE phases"
        else:
            action = "verify_phase_identity_and_dated_ownership"
            reason = "single candidate remains review-only; ownership interval is not inferred"
        rows.append(
            {
                "review_key": f"{record.get('report_id')}:{record.get('evidence_type')}:{record.get('project_label')}:{phase_id or 'unmatched'}",
                "report_id": record.get("report_id"),
                "report_period_end": record.get("report_period_end"),
                "evidence_type": record.get("evidence_type"),
                "project_label": record.get("project_label"),
                "annual_location": record.get("annual_location"),
                "srpe_development_id": phase_id,
                "srpe_development_name": record.get("srpe_development_name"),
                "srpe_phase_name": record.get("srpe_phase_name"),
                "active": active,
                "srpe_date_suspend_sales": phase.get("srpe_date_suspend_sales"),
                "srpe_date_complete_sales": phase.get("srpe_date_complete_sales"),
                "match_status": status,
                "match_confidence": record.get("match_confidence"),
                "match_method": record.get("match_method"),
                "candidate_count": record.get("candidate_count"),
                "transaction_manifest_rows": manifest_rows,
                "transaction_manifest_status": "register_manifest_available" if manifest_rows else "register_manifest_not_observed",
                "review_priority": priority,
                "review_action": action,
                "review_reason": reason,
                "annual_document_url": record.get("annual_document_url"),
                "last_verified_at": record.get("matched_at") or datetime.now(timezone.utc).isoformat(),
            }
        )
    frame = pd.DataFrame(rows, columns=SHKP_HISTORICAL_PHASE_REVIEW_QUEUE_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(
            ["review_priority", "transaction_manifest_rows", "report_period_end", "review_key"],
            ascending=[True, False, True, True],
            na_position="last",
            kind="stable",
        ).reset_index(drop=True)
    return frame

SHKP_PROJECT_SITE_VENDOR_FACT_COLUMNS = [
    "marketing_name",
    "source_record_id",
    "external_project_url",
    "source_url",
    "site_evidence_status",
    "development_name",
    "development_address",
    "district",
    "vendor_name",
    "holding_companies",
    "estimated_material_date",
    "evidence_context",
    "fetched_at",
]

SHKP_PROJECT_SITE_VENDOR_CROSSWALK_COLUMNS = [
    "marketing_name",
    "source_record_id",
    "vendor_name",
    "holding_companies",
    "estimated_material_date",
    "site_evidence_status",
    "site_source_url",
    "srpe_development_id",
    "srpe_phase_name",
    "srpe_address_en",
    "match_method",
    "match_status",
    "candidate_count",
    "ownership_status",
    "matched_at",
]

# A static, phase-scoped role-evidence contract for pages that are current,
# grouped, or JS-rendered and therefore cannot always be parsed by the live
# site collector.  These rows document vendor/owner/person-so-engaged roles;
# ``ownership_pct`` and effective dates stay null by design.
SHKP_PHASE_ROLE_EVIDENCE_COLUMNS = [
    "evidence_id",
    "srpe_development_id",
    "phase_label",
    "role_scope",
    "vendor_or_owner",
    "holding_companies",
    "source_url",
    "observed_as_of",
    "date_semantics",
    "ownership_pct",
    "effective_from",
    "effective_to",
    "evidence_status",
    "promotion_status",
    "caveat",
    "last_verified_at",
]

# One row per audited priority phase.  This is a coverage/control layer, not
# another ownership assertion: it records whether the phase has identity,
# role, numeric snapshot and decision evidence, and why the sales gate is
# still closed.
SHKP_OWNERSHIP_COVERAGE_AUDIT_COLUMNS = [
    "srpe_development_id",
    "srpe_development_name",
    "srpe_phase_name",
    "phase_identity_status",
    "identity_evidence_rows",
    "phase_role_evidence_rows",
    "vendor_or_owner",
    "holding_companies",
    "legal_ownership_observation_rows",
    "numeric_snapshot_rows",
    "attribution_decision_rows",
    "approved_interval_rows",
    "ownership_attribution_ready",
    "coverage_status",
    "coverage_gap",
    "required_next_evidence",
    "source_urls_json",
    "last_verified_at",
]

SHKP_PHASE_ROLE_EVIDENCE: tuple[dict[str, Any], ...] = (
    {
        "evidence_id": "site-role:9366:cullinan-sky-p1",
        "srpe_development_id": "9366",
        "phase_label": "Cullinan Sky Phase 1",
        "role_scope": "vendor_notice",
        "vendor_or_owner": "Super Great Limited",
        "holding_companies": "Master Summit Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.cullinansky.com.hk/",
        "observed_as_of": None,
        "date_semantics": "current_page",
        "evidence_status": "phase_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "Current statutory page identifies vendor/holding companies but does not state a numeric percentage or effective interval.",
    },
    {
        "evidence_id": "site-role:11005:cullinan-sky-p2",
        "srpe_development_id": "11005",
        "phase_label": "Cullinan Sky Phase 2",
        "role_scope": "vendor_notice",
        "vendor_or_owner": "Super Great Limited",
        "holding_companies": "Master Summit Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.cullinansky.com.hk/p2",
        "observed_as_of": None,
        "date_semantics": "current_page_grouped_footer",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The /p2 page currently renders a shared/legal footer; it is not independent Phase-2 effective ownership evidence.",
    },
    {
        "evidence_id": "site-role:9785:cullinan-harbour-p1",
        "srpe_development_id": "9785",
        "phase_label": "Cullinan Harbour Phase 1",
        "role_scope": "vendor_notice",
        "vendor_or_owner": "Well Capital (H.K.) Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Time Effort Limited; Trade Up Ventures Limited",
        "source_url": "https://www.cullinanharbour.com.hk/phasei/en/",
        "observed_as_of": None,
        "date_semantics": "current_page",
        "evidence_status": "phase_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "Role evidence only; no phase-level percentage or effective interval.",
    },
    {
        "evidence_id": "site-role:10405:cullinan-harbour-p2a",
        "srpe_development_id": "10405",
        "phase_label": "Cullinan Harbour Phase 2A",
        "role_scope": "vendor_notice",
        "vendor_or_owner": "Well Capital (H.K.) Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Time Effort Limited; Trade Up Ventures Limited",
        "source_url": "https://www.cullinanharbour.com.hk/phaseii/en/",
        "observed_as_of": None,
        "date_semantics": "current_page_grouped_footer",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "Page carries grouped Phase 1/2A role text; no single-phase percentage or effective interval.",
    },
    {
        "evidence_id": "site-role:11516:cullinan-harbour-p2b",
        "srpe_development_id": "11516",
        "phase_label": "Cullinan Harbour Phase 2B",
        "role_scope": "vendor_notice",
        "vendor_or_owner": "Well Capital (H.K.) Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Time Effort Limited; Trade Up Ventures Limited",
        "source_url": "https://www.cullinanharbour.com.hk/phaseiib/en/",
        "observed_as_of": None,
        "date_semantics": "current_page_grouped_footer",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "Page carries grouped phase role text; no single-phase percentage or effective interval.",
    },
    {
        "evidence_id": "site-role:11554:garden-regency",
        "srpe_development_id": "11554",
        "phase_label": "Garden Regency",
        "role_scope": "vendor_notice",
        "vendor_or_owner": "Ease Gold Development Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Vast Earn Limited; Peak Harbour Development Limited",
        "source_url": "https://www.gardenregency.com/en/",
        "observed_as_of": None,
        "date_semantics": "current_page",
        "evidence_status": "phase_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "One-to-one lot identity is strong, but current page is not an ownership-effective interval.",
    },
    {
        "evidence_id": "site-role:11505:lime-spark",
        "srpe_development_id": "11505",
        "phase_label": "Lime Spark",
        "role_scope": "vendor_notice",
        "vendor_or_owner": "Tippon Investment Enterprises Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Win Profit Properties Limited",
        "source_url": "https://www.limespark.hk/en-US",
        "observed_as_of": None,
        "date_semantics": "current_page",
        "evidence_status": "phase_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "Vendor/holding chain is current-page evidence; attributable SHKP percentage and effective dates are absent.",
    },
    {
        "evidence_id": "site-role:11305:sierra-sea-p2a",
        "srpe_development_id": "11305",
        "phase_label": "Sierra Sea Phase 2A",
        "role_scope": "vendor_notice",
        "vendor_or_owner": "Light Time Investments Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Vast Earn Limited; Williston Limited",
        "source_url": "https://www.sierrasea2a.com.hk/en/",
        "observed_as_of": None,
        "date_semantics": "current_page",
        "evidence_status": "phase_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "Phase-specific role page; SHKP percentage/effective interval not stated.",
    },
    {
        "evidence_id": "site-role:11345:sierra-sea-p2b",
        "srpe_development_id": "11345",
        "phase_label": "Sierra Sea Phase 2B",
        "role_scope": "vendor_notice",
        "vendor_or_owner": "Light Time Investments Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Vast Earn Limited; Williston Limited",
        "source_url": "https://www.sierrasea2b.com.hk/en/",
        "observed_as_of": None,
        "date_semantics": "current_page_or_brochure",
        "evidence_status": "phase_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "Phase-specific role/brochure evidence; grouped 100% schedule cannot be allocated to P2B.",
    },
    {
        "evidence_id": "site-role:9565:yoho-west-p1",
        "srpe_development_id": "9565",
        "phase_label": "YOHO WEST Phase 1",
        "role_scope": "owner_and_person_so_engaged",
        "vendor_or_owner": "MTR Corporation Limited (Owner); Best Vision Development Limited (Person so engaged)",
        "holding_companies": "Better Sun Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.yohowest.com.hk/",
        "observed_as_of": None,
        "date_semantics": "current_page_statutory_notice",
        "evidence_status": "phase_role_notice",
        "promotion_status": "blocked_role_only",
        "caveat": "MTR owner / SHKP-linked person-so-engaged roles do not publish SHKP equity or profit share.",
    },
    {
        "evidence_id": "site-role:10585:yoho-west-parkside",
        "srpe_development_id": "10585",
        "phase_label": "YOHO WEST PARKSIDE Phase 2",
        "role_scope": "owner_and_person_so_engaged",
        "vendor_or_owner": "MTR Corporation Limited (Owner); Best Vision Development Limited (Person so engaged)",
        "holding_companies": "Better Sun Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.yohowest.com.hk/p2/",
        "observed_as_of": None,
        "date_semantics": "current_page_statutory_notice",
        "evidence_status": "phase_role_notice",
        "promotion_status": "blocked_role_only",
        "caveat": "Current notice includes an estimated material date, not an ownership-effective date.",
    },
    {
        "evidence_id": "site-role:7845:yoho-hub-b",
        "srpe_development_id": "7845",
        "phase_label": "The YOHO Hub Phase B",
        "role_scope": "owner_and_person_so_engaged",
        "vendor_or_owner": "Yuen Long Property Development Limited (Owner); Success Keep Limited (Person so engaged)",
        "holding_companies": "Sun Hung Kai Properties Limited; Time Effort Limited; Able Mariner Limited",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/the-yoho-hub",
        "observed_as_of": "2022-03-31",
        "date_semantics": "printed_notice",
        "evidence_status": "phase_role_notice",
        "promotion_status": "blocked_role_only",
        "caveat": "Printed statutory role notice supports phase identity; annual/schedule JV remains non-numeric.",
    },
    {
        "evidence_id": "site-role:8525:yoho-hub-c",
        "srpe_development_id": "8525",
        "phase_label": "The YOHO Hub II Phase C",
        "role_scope": "owner_and_person_so_engaged",
        "vendor_or_owner": "Yuen Long Property Development Limited (Owner); Success Keep Limited (Person so engaged)",
        "holding_companies": "Sun Hung Kai Properties Limited; Time Effort Limited; Able Mariner Limited",
        "source_url": "https://www.theyohohub2.com.hk/home?lang=en",
        "observed_as_of": "2024-04-23",
        "date_semantics": "printed_notice",
        "evidence_status": "phase_role_notice",
        "promotion_status": "blocked_role_only",
        "caveat": "Printed statutory role notice supports phase identity; annual/schedule JV remains non-numeric.",
    },
    {
        "evidence_id": "official-role:4745:wings-at-sea-iva",
        "srpe_development_id": "4745",
        "phase_label": "Wings at Sea (LOHAS Park Phase IVA)",
        "role_scope": "owner_and_person_so_engaged",
        "vendor_or_owner": "MTR Corporation Limited (Owner); Globaluck Limited (Person so engaged)",
        "holding_companies": "Mount East Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/sites/assets/files/enshkpqsub64.pdf",
        "observed_as_of": "2018-12-31",
        "date_semantics": "official_quarterly_statutory_notice",
        "evidence_status": "phase_role_notice",
        "promotion_status": "blocked_role_only",
        "caveat": "Official SHKP Quarterly identifies Phase IVA and the person-so-engaged holding chain; it does not state SHKP's economic percentage or a continuous effective interval.",
    },
    {
        "evidence_id": "official-role:4865:wings-at-sea-ivb",
        "srpe_development_id": "4865",
        "phase_label": "Wings at Sea II (LOHAS Park Phase IVB)",
        "role_scope": "person_so_engaged",
        "vendor_or_owner": "Owner not applicable on the published notice; Person so engaged role",
        "holding_companies": "Mount East Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/wings-at-sea-ii",
        "observed_as_of": "2021-04-30",
        "date_semantics": "official_phase_notice",
        "evidence_status": "phase_role_notice",
        "promotion_status": "blocked_role_only",
        "caveat": "The official page states a Person-so-engaged holding chain but does not provide a numeric SHKP stake or effective interval; owner is shown as not applicable on the page.",
    },
    {
        "evidence_id": "official-role:3945:cullinan-west-p2a",
        "srpe_development_id": "3945",
        "phase_label": "Cullinan West Phase 2A",
        "role_scope": "owner_and_person_so_engaged",
        "vendor_or_owner": "Nam Cheong Property Development Limited (Owner); Joinyield Limited (Person so engaged)",
        "holding_companies": "West Rail Property Development Limited (Owner holding company); Leola Holdings Limited; Wisdom Mount Limited; Data Giant Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/cullinan-west",
        "observed_as_of": "2019-05-01",
        "date_semantics": "official_phase_notice",
        "evidence_status": "phase_role_notice",
        "promotion_status": "blocked_role_only",
        "caveat": "The page distinguishes the MTR/West Rail owner from the SHKP-linked person-so-engaged chain; it does not publish a numeric SHKP economic or profit share.",
    },
    {
        "evidence_id": "official-role:4945:cullinan-west-p3",
        "srpe_development_id": "4945",
        "phase_label": "Cullinan West II (Cullinan West Development Phase 3)",
        "role_scope": "phase_identity_only",
        "vendor_or_owner": None,
        "holding_companies": None,
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2019q3/tc/PDF/qty2019q3tc.pdf",
        "observed_as_of": "2019-09-30",
        "date_semantics": "official_quarterly_phase_reference",
        "evidence_status": "phase_identity_only",
        "promotion_status": "blocked_identity_only",
        "caveat": "The issuer Quarterly source identifies Cullinan West II as Phase 3; vendor/holding-company fields were not normalized from this source, so this row is identity evidence only.",
    },
    {
        "evidence_id": "official-role:5886:cullinan-west-p5",
        "srpe_development_id": "5886",
        "phase_label": "Cullinan West III (Cullinan West Development Phase 5)",
        "role_scope": "owner_and_person_so_engaged",
        "vendor_or_owner": "Nam Cheong Property Development Limited (Owner); Joinyield Limited (Person so engaged)",
        "holding_companies": "West Rail Property Development Limited (Owner holding company); Leola Holdings Limited; Wisdom Mount Limited; Data Giant Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/cullinan-west-iii-0",
        "observed_as_of": "2021-04-29",
        "date_semantics": "official_phase_notice_last_updated",
        "evidence_status": "phase_role_notice",
        "promotion_status": "blocked_role_only",
        "caveat": "The official phase notice explicitly identifies Phase 5, No. 28 Sham Mong Road and the MTR/West Rail owner plus SHKP-linked person-so-engaged chain; it does not publish a numeric SHKP economic share or effective interval.",
    },
    {
        "evidence_id": "official-role:7867:wetland-seasons-bay-p1",
        "srpe_development_id": "7867",
        "phase_label": "Wetland Seasons Bay Phase 1",
        "role_scope": "vendor_notice",
        "vendor_or_owner": "Vendor stated in the official Phase 1 notice; grouped Wetland Lot No.33 development role",
        "holding_companies": "Silver Wind Developments Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/wetland-seasons-bay-phase-1",
        "observed_as_of": "2022-01-01",
        "date_semantics": "official_phase_notice",
        "evidence_status": "phase_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "The official SHKP phase page identifies SHKP in the vendor holding-company chain; no numeric percentage or continuous effective interval is stated.",
    },
    {
        "evidence_id": "official-role:8045:wetland-seasons-bay-p2",
        "srpe_development_id": "8045",
        "phase_label": "Wetland Seasons Bay Phase 2",
        "role_scope": "vendor_notice",
        "vendor_or_owner": "Jet Group Limited",
        "holding_companies": "Silver Wind Developments Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/wetland-seasons-bay-phase-2",
        "observed_as_of": "2022-10-13",
        "date_semantics": "official_phase_notice",
        "evidence_status": "phase_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "Role evidence establishes a SHKP-linked vendor holding chain, not a numeric economic stake or effective interval.",
    },
    {
        "evidence_id": "official-role:8665:wetland-seasons-bay-p3",
        "srpe_development_id": "8665",
        "phase_label": "Wetland Seasons Bay Phase 3",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Jet Group Limited (grouped Wetland Lot No.33 notice)",
        "holding_companies": "Silver Wind Developments Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/sites/assets/files/2023-03/WSB_press%20release_EN.pdf",
        "observed_as_of": "2023-01-19",
        "date_semantics": "grouped_official_phase_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official grouped notice covers Phases 1–3 together; it cannot be used to allocate a numeric stake independently to Phase 3.",
    },
    {
        "evidence_id": "official-role:4625:victoria-harbour-p1b",
        "srpe_development_id": "4625",
        "phase_label": "Victoria Harbour Phase 1B",
        "role_scope": "vendor_notice",
        "vendor_or_owner": "Choice Win (H.K.) Limited",
        "holding_companies": "Topraise Group Limited; Total Corporate Holdings Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/victoria-harbour",
        "observed_as_of": "2019-05-01",
        "date_semantics": "official_phase_notice",
        "evidence_status": "phase_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "Official phase notice identifies the SHKP-linked holding chain but does not state an economic percentage or continuous interval.",
    },
    {
        "evidence_id": "official-role:8605:novo-land-p1a",
        "srpe_development_id": "8605",
        "phase_label": "NOVO LAND Phase 1A",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Pacific Good Investment Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Vast Earn Limited; Peak Harbour Development Ltd",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/novo-land",
        "observed_as_of": "2023-04-26",
        "date_semantics": "grouped_phase_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice groups NOVO LAND Phases 1A, 1B, 2A and 2B; it does not provide a phase-specific numeric stake or effective interval.",
    },
    {
        "evidence_id": "official-role:8705:novo-land-p1b",
        "srpe_development_id": "8705",
        "phase_label": "NOVO LAND Phase 1B",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Pacific Good Investment Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Vast Earn Limited; Peak Harbour Development Ltd",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/novo-land",
        "observed_as_of": "2023-04-26",
        "date_semantics": "grouped_phase_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice groups NOVO LAND Phases 1A, 1B, 2A and 2B; it does not provide a phase-specific numeric stake or effective interval.",
    },
    {
        "evidence_id": "official-role:9146:novo-land-p2a",
        "srpe_development_id": "9146",
        "phase_label": "NOVO LAND Phase 2A",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Pacific Good Investment Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Vast Earn Limited; Peak Harbour Development Ltd",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/novo-land",
        "observed_as_of": "2023-04-26",
        "date_semantics": "grouped_phase_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice groups NOVO LAND Phases 1A, 1B, 2A and 2B; it does not provide a phase-specific numeric stake or effective interval.",
    },
    {
        "evidence_id": "official-role:9085:novo-land-p2b",
        "srpe_development_id": "9085",
        "phase_label": "NOVO LAND Phase 2B",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Pacific Good Investment Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Vast Earn Limited; Peak Harbour Development Ltd",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/novo-land",
        "observed_as_of": "2023-04-26",
        "date_semantics": "grouped_phase_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice groups NOVO LAND Phases 1A, 1B, 2A and 2B; it does not provide a phase-specific numeric stake or effective interval.",
    },
    {
        "evidence_id": "official-role:10765:novo-land-p3a",
        "srpe_development_id": "10765",
        "phase_label": "NOVO LAND Phase 3A",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Pacific Good Investment Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Vast Earn Limited; Peak Harbour Development Ltd",
        "source_url": "https://promotions.shkp.com/shkpclub/bin/promo/pics/2024001575/sc.pdf",
        "observed_as_of": "2024-06-12",
        "date_semantics": "official_grouped_phase_promotion_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official SHKP Club notice groups NOVO LAND Phases 3A and 3B; it is useful identity/role evidence but not a phase-specific ownership interval.",
    },
    {
        "evidence_id": "official-role:10045:novo-land-p3b",
        "srpe_development_id": "10045",
        "phase_label": "NOVO LAND Phase 3B",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Pacific Good Investment Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Vast Earn Limited; Peak Harbour Development Ltd",
        "source_url": "https://promotions.shkp.com/shkpclub/bin/promo/pics/2024001575/sc.pdf",
        "observed_as_of": "2024-06-12",
        "date_semantics": "official_grouped_phase_promotion_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official SHKP Club notice groups NOVO LAND Phases 3A and 3B; it is useful identity/role evidence but not a phase-specific ownership interval.",
    },
    {
        "evidence_id": "official-role:10685:sierra-sea-p1a2",
        "srpe_development_id": "10685",
        "phase_label": "Sierra Sea Phase 1A(2)",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Light Time Investments Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Vast Earn Limited; Williston Investment S.A.",
        "source_url": "https://promotions.shkp.com/shkpclub/bin/promo/2025001637/2025001637_webcontent_en_GR.php",
        "observed_as_of": "2025-05-14",
        "date_semantics": "official_grouped_phase_promotion_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official promotion notice covers Sierra Sea Phases 1A(2) and 1B together; it does not disclose a phase-specific SHKP percentage or effective interval.",
    },
    {
        "evidence_id": "official-role:10725:sierra-sea-p1b",
        "srpe_development_id": "10725",
        "phase_label": "Sierra Sea Phase 1B",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Light Time Investments Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Vast Earn Limited; Williston Investment S.A.",
        "source_url": "https://promotions.shkp.com/shkpclub/bin/promo/2025001637/2025001637_webcontent_en_GR.php",
        "observed_as_of": "2025-05-14",
        "date_semantics": "official_grouped_phase_promotion_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official promotion notice covers Sierra Sea Phases 1A(2) and 1B together; it does not disclose a phase-specific SHKP percentage or effective interval.",
    },
    {
        "evidence_id": "official-role:10685:sierra-sea-q2-statutory",
        "srpe_development_id": "10685",
        "phase_label": "Sierra Sea Phase 1A(2)",
        "role_scope": "phase_statutory_notice",
        "vendor_or_owner": "Light Time Investments Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Vast Earn Limited; Williston Investment S.A.",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2025q2/sc/PDF/qty2025q2sc.pdf",
        "observed_as_of": "2025-06-30",
        "date_semantics": "official_quarterly_statutory_notice",
        "evidence_status": "phase_role_notice",
        "promotion_status": "blocked_role_only",
        "caveat": "The SHKP Quarterly statutory advertisement explicitly names Phase 1A(2), No. 8 Hoi Ying Road, and the vendor/holding-company chain; its grouped notice does not disclose a numeric phase stake or effective interval.",
    },
    {
        "evidence_id": "official-role:10725:sierra-sea-q2-statutory",
        "srpe_development_id": "10725",
        "phase_label": "Sierra Sea Phase 1B",
        "role_scope": "phase_statutory_notice",
        "vendor_or_owner": "Light Time Investments Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Vast Earn Limited; Williston Investment S.A.",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2025q2/sc/PDF/qty2025q2sc.pdf",
        "observed_as_of": "2025-06-30",
        "date_semantics": "official_quarterly_statutory_notice",
        "evidence_status": "phase_role_notice",
        "promotion_status": "blocked_role_only",
        "caveat": "The SHKP Quarterly statutory advertisement explicitly names Phase 1B, No. 8 Hoi Ying Road, and the vendor/holding-company chain; its grouped notice does not disclose a numeric phase stake or effective interval.",
    },
)

# Additional bounded primary notices discovered during the historical
# address/permit review.  These are grouped notices for older SHKP phases (or
# one exact phase notice for Silicon Hill), so they strengthen phase identity
# and JV routing without creating numeric ownership intervals.
SHKP_PHASE_ROLE_EVIDENCE_ADDITIONS: tuple[dict[str, Any], ...] = (
    {
        "evidence_id": "primary-role:5505:park-yoho-napoli",
        "srpe_development_id": "5505",
        "phase_label": "PARK YOHO Napoli (Phase 2B)",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Bright Strong Limited",
        "holding_companies": "Fourseas Investments Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2022q4/tc/ebook/15/",
        "observed_as_of": "2022-12-30",
        "date_semantics": "official_quarterly_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice maps PARK YOHO Napoli to Phase 2B at 18 Castle Peak Road and gives the vendor/holding chain, but the grouped notice cannot establish a phase-specific numeric stake or interval.",
    },
    {
        "evidence_id": "primary-role:8845:park-yoho-bologna",
        "srpe_development_id": "8845",
        "phase_label": "PARK YOHO Bologna (Phase 3)",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Bright Strong Limited",
        "holding_companies": "Fourseas Investments Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2022q4/tc/ebook/15/",
        "observed_as_of": "2022-12-30",
        "date_semantics": "official_quarterly_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice maps PARK YOHO Bologna to Phase 3 at 18 Castle Peak Road and gives the vendor/holding chain, but the grouped notice cannot establish a phase-specific numeric stake or interval.",
    },
    {
        "evidence_id": "primary-role:4447:park-yoho-genova",
        "srpe_development_id": "4447",
        "phase_label": "PARK YOHO Genova (Phase 2A)",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Bright Strong Limited",
        "holding_companies": "Fourseas Investments Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2022q4/tc/ebook/15/",
        "observed_as_of": "2022-12-30",
        "date_semantics": "official_quarterly_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice maps PARK YOHO Genova to Phase 2A at 18 Castle Peak Road and gives the vendor/holding chain, but the grouped notice cannot establish a phase-specific numeric stake or interval.",
    },
    {
        "evidence_id": "primary-role:5325:park-yoho-milano",
        "srpe_development_id": "5325",
        "phase_label": "PARK YOHO Milano (Phase 2C)",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Bright Strong Limited",
        "holding_companies": "Fourseas Investments Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2022q4/tc/ebook/15/",
        "observed_as_of": "2022-12-30",
        "date_semantics": "official_quarterly_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice maps PARK YOHO Milano to Phase 2C at 18 Castle Peak Road and gives the vendor/holding chain, but the grouped notice cannot establish a phase-specific numeric stake or interval.",
    },
    {
        "evidence_id": "primary-role:2906:park-yoho-sicilia",
        "srpe_development_id": "2906",
        "phase_label": "PARK YOHO Sicilia (Phase 1C)",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Bright Strong Limited",
        "holding_companies": "Fourseas Investments Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2022q4/tc/ebook/15/",
        "observed_as_of": "2022-12-30",
        "date_semantics": "official_quarterly_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice maps PARK YOHO Sicilia to Phase 1C at 18 Castle Peak Road and gives the vendor/holding chain, but the grouped notice cannot establish a phase-specific numeric stake or interval.",
    },
    {
        "evidence_id": "primary-role:2905:park-yoho-venezia",
        "srpe_development_id": "2905",
        "phase_label": "PARK YOHO Venezia (Phase 1B)",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Bright Strong Limited",
        "holding_companies": "Fourseas Investments Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2022q4/tc/ebook/15/",
        "observed_as_of": "2022-12-30",
        "date_semantics": "official_quarterly_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice maps PARK YOHO Venezia to Phase 1B at 18 Castle Peak Road and gives the vendor/holding chain, but the grouped notice cannot establish a phase-specific numeric stake or interval.",
    },
    {
        "evidence_id": "primary-role:6585:wetland-seasons-park-p1",
        "srpe_development_id": "6585",
        "phase_label": "Wetland Seasons Park Phase 1",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Pacific Gold Limited",
        "holding_companies": "Newray Ventures Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2021q2/sc/ebook/15/",
        "observed_as_of": "2021-06-30",
        "date_semantics": "official_quarterly_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice maps Wetland Seasons Park Phase 1 to 9 Wetland Park Road and groups Phases 1–3 under one vendor/holding chain; no phase-specific numeric stake or interval is disclosed.",
    },
    {
        "evidence_id": "primary-role:6765:wetland-seasons-park-p2",
        "srpe_development_id": "6765",
        "phase_label": "Wetland Seasons Park Phase 2",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Pacific Gold Limited",
        "holding_companies": "Newray Ventures Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2021q2/sc/ebook/15/",
        "observed_as_of": "2021-06-30",
        "date_semantics": "official_quarterly_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice maps Wetland Seasons Park Phase 2 to 9 Wetland Park Road and groups Phases 1–3 under one vendor/holding chain; no phase-specific numeric stake or interval is disclosed.",
    },
    {
        "evidence_id": "primary-role:6967:wetland-seasons-park-p3",
        "srpe_development_id": "6967",
        "phase_label": "Wetland Seasons Park Phase 3",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Pacific Gold Limited",
        "holding_companies": "Newray Ventures Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2021q2/sc/ebook/15/",
        "observed_as_of": "2021-06-30",
        "date_semantics": "official_quarterly_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice maps Wetland Seasons Park Phase 3 to 9 Wetland Park Road and groups Phases 1–3 under one vendor/holding chain; no phase-specific numeric stake or interval is disclosed.",
    },
    {
        "evidence_id": "primary-role:5265:st-martin-p1",
        "srpe_development_id": "5265",
        "phase_label": "St Martin Phase 1",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Superwick Limited",
        "holding_companies": "Value Day Holdings Limited; Total Corporate Holdings Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2018q3/tc/ebook/14/",
        "observed_as_of": "2018-10-04",
        "date_semantics": "official_quarterly_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice maps Phase 1 to 12 Fo Chun Road and groups St Martin Phases 1–2 under one vendor/holding chain; no phase-specific numeric stake or interval is disclosed.",
    },
    {
        "evidence_id": "primary-role:5266:st-martin-p2",
        "srpe_development_id": "5266",
        "phase_label": "St Martin Phase 2",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Superwick Limited",
        "holding_companies": "Value Day Holdings Limited; Total Corporate Holdings Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2018q3/tc/ebook/14/",
        "observed_as_of": "2018-10-04",
        "date_semantics": "official_quarterly_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice maps Phase 2 to 12 Fo Chun Road and groups St Martin Phases 1–2 under one vendor/holding chain; no phase-specific numeric stake or interval is disclosed.",
    },
    {
        "evidence_id": "primary-role:8445:university-hill-p2a",
        "srpe_development_id": "8445",
        "phase_label": "University Hill Phase 2A",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Channel First Limited",
        "holding_companies": "Elisford Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2023q2/sc/PDF/SHKPQTY_2023q2_ENSC_10-11.pdf",
        "observed_as_of": "2023-06-29",
        "date_semantics": "official_quarterly_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice maps University Hill Phase 2A to 63 Yau King Lane and groups Phases 2A–2B under one vendor/holding chain; no phase-specific numeric stake or interval is disclosed.",
    },
    {
        "evidence_id": "primary-role:9245:university-hill-p2b",
        "srpe_development_id": "9245",
        "phase_label": "University Hill Phase 2B",
        "role_scope": "grouped_vendor_notice",
        "vendor_or_owner": "Channel First Limited",
        "holding_companies": "Elisford Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2023q2/sc/PDF/SHKPQTY_2023q2_ENSC_10-11.pdf",
        "observed_as_of": "2023-06-29",
        "date_semantics": "official_quarterly_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official notice maps University Hill Phase 2B to 63 Yau King Lane and groups Phases 2A–2B under one vendor/holding chain; no phase-specific numeric stake or interval is disclosed.",
    },
    {
        "evidence_id": "primary-role:8405:silicon-hill-p1",
        "srpe_development_id": "8405",
        "phase_label": "Silicon Hill Phase 1",
        "role_scope": "phase_vendor_notice",
        "vendor_or_owner": "Channel First Limited",
        "holding_companies": "Elisford Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2022q2/tc/PDF/qty2022q2tc.pdf",
        "observed_as_of": "2022-06-30",
        "date_semantics": "official_quarterly_statutory_notice",
        "evidence_status": "phase_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "The official notice identifies Silicon Hill Phase 1 at 63 Yau King Lane and the vendor/holding chain; the development has later phases and the notice does not state a numeric SHKP stake or interval.",
    },
    {
        "evidence_id": "primary-role:7965:kennedy-38",
        "srpe_development_id": "7965",
        "phase_label": "Kennedy 38",
        "role_scope": "development_vendor_notice",
        "vendor_or_owner": "Harvest Treasure Limited; Victory Land Management Limited; City Precise Limited; Well Metro Development Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Assets Garden Holdings Limited; Triplex Fortune Group Limited; Ample Talent International Limited; Wentel Investment Limited; Silver Radiance Limited; Wheelock Properties Limited; Myers Investments Limited; Wheelock Investments Limited; Wheelock and Company Limited",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/kennedy-38",
        "observed_as_of": "2023-12-19",
        "date_semantics": "official_project_page_last_update",
        "evidence_status": "development_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "The official Kennedy 38 project page names the address, vendor chain and holding companies, including Sun Hung Kai Properties, but does not disclose a numeric SHKP phase stake or effective interval.",
    },
    {
        "evidence_id": "primary-role:7525:prince-central",
        "srpe_development_id": "7525",
        "phase_label": "Prince Central",
        "role_scope": "development_vendor_notice",
        "vendor_or_owner": "Junie Limited",
        "holding_companies": "Hyndman Limited; Pool Meadow Investment Limited; Victory Zone Holdings Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/prince-central",
        "observed_as_of": "2022-06-30",
        "date_semantics": "official_project_page_last_update",
        "evidence_status": "development_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "The official Prince Central project page names 195 Prince Edward Road West and the vendor/holding-company chain, but does not disclose a numeric SHKP phase stake or effective interval.",
    },
    {
        "evidence_id": "primary-role:7325:st-michel-p1",
        "srpe_development_id": "7325",
        "phase_label": "St Michel Phase 1",
        "role_scope": "grouped_phase_vendor_notice",
        "vendor_or_owner": "Mainco Limited",
        "holding_companies": "Champion Sino Holdings Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/sites/assets/files/2023-05/St%20Michel_press%20release_EN_20230515_v4_1530.pdf",
        "observed_as_of": "2023-05-12",
        "date_semantics": "official_press_release_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official St Michel notice explicitly names Phase 1 at 33 To Shek Street and the Mainco holding-company chain; it groups Phases 1 and 2 and does not disclose a numeric SHKP phase stake or effective interval.",
    },
    {
        "evidence_id": "primary-role:8245:st-michel-p2",
        "srpe_development_id": "8245",
        "phase_label": "St Michel Phase 2",
        "role_scope": "grouped_phase_vendor_notice",
        "vendor_or_owner": "Mainco Limited",
        "holding_companies": "Champion Sino Holdings Limited; Time Effort Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/sites/assets/files/2023-05/St%20Michel_press%20release_EN_20230515_v4_1530.pdf",
        "observed_as_of": "2023-05-12",
        "date_semantics": "official_press_release_grouped_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official St Michel notice explicitly names Phase 2 at 33 To Shek Street and the Mainco holding-company chain; it groups Phases 1 and 2 and does not disclose a numeric SHKP phase stake or effective interval.",
    },
    {
        "evidence_id": "primary-role:6445:central-peak",
        "srpe_development_id": "6445",
        "phase_label": "Central Peak Phase 1",
        "role_scope": "phase_vendor_notice",
        "vendor_or_owner": "Wisecity Development Limited",
        "holding_companies": "Neo Gains Limited; Wisdom Mount Limited; Data Giant Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/central-peak",
        "observed_as_of": "2020-11-30",
        "date_semantics": "official_project_page_last_update",
        "evidence_status": "phase_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "The official Central Peak project page names Phase 1 at 18 Stubbs Road and the vendor/holding-company chain, but does not disclose a numeric SHKP phase stake or effective interval.",
    },
    {
        "evidence_id": "primary-role:3625:lime-gala",
        "srpe_development_id": "3625",
        "phase_label": "Lime Gala",
        "role_scope": "development_vendor_notice",
        "vendor_or_owner": "Wealth Power International Enterprise Limited",
        "holding_companies": "Federica Investments Limited; Assets Garden Holdings Limited; Sun Hung Kai Properties Limited",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/lime-gala",
        "observed_as_of": "2019-05-01",
        "date_semantics": "official_project_page_last_update",
        "evidence_status": "development_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "The official Lime Gala project page names 393 Shau Kei Wan Road and the vendor/holding-company chain, but does not disclose a numeric SHKP phase stake or effective interval.",
    },
    {
        "evidence_id": "primary-role:4267:st-barths-p2",
        "srpe_development_id": "4267",
        "phase_label": "Crown of St. Barths (Phase 2)",
        "role_scope": "grouped_phase_vendor_notice",
        "vendor_or_owner": "Good Assets Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Time Effort Limited; China Benefit Holdings Limited",
        "source_url": "https://www.shkp.com/sites/assets/files/2019-07/20190716_PressRelease_E.pdf",
        "observed_as_of": "2019-07-16",
        "date_semantics": "official_press_release_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official St. Barths announcement explicitly maps Phase 2/Crown of St. Barths to 9 Yiu Sha Road and the Good Assets holding-company chain; it does not disclose a numeric SHKP phase stake or effective interval.",
    },
    {
        "evidence_id": "primary-role:4285:st-barths-p1",
        "srpe_development_id": "4285",
        "phase_label": "St. Barths (Phase 1)",
        "role_scope": "grouped_phase_vendor_notice",
        "vendor_or_owner": "Good Assets Limited",
        "holding_companies": "Sun Hung Kai Properties Limited; Time Effort Limited; China Benefit Holdings Limited",
        "source_url": "https://www.shkp.com/sites/assets/files/2019-07/20190716_PressRelease_E.pdf",
        "observed_as_of": "2019-07-16",
        "date_semantics": "official_press_release_statutory_notice",
        "evidence_status": "grouped_phase_vendor_notice",
        "promotion_status": "blocked_grouped_role",
        "caveat": "The official St. Barths announcement explicitly maps Phase 1/St. Barths to 9 Yiu Sha Road and the Good Assets holding-company chain; it does not disclose a numeric SHKP phase stake or effective interval.",
    },
    {
        "evidence_id": "primary-role:3826:babington-hill",
        "srpe_development_id": "3826",
        "phase_label": "Babington Hill",
        "role_scope": "development_vendor_notice",
        "vendor_or_owner": "Well Success Capital Investment Limited; Art Faith Corporation Limited; Come City Limited",
        "holding_companies": "Sharberg Holdings Limited; Phoenix Power Holdings Limited; Assets Garden Holdings Limited; Sun Hung Kai Properties Limited; New World Development Company Limited",
        "source_url": "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale/babington-hill",
        "observed_as_of": "2019-05-01",
        "date_semantics": "official_project_page_last_update",
        "evidence_status": "development_vendor_notice",
        "promotion_status": "blocked_vendor_only",
        "caveat": "The official Babington Hill project page names 23 Babington Path and the vendor/holding-company chain, but does not disclose a numeric SHKP phase stake or effective interval.",
    },
)

# Evidence-only registry for projects mentioned by SHKP disclosures but not
# yet promoted to an SRPE phase row.  This is deliberately separate from
# ``SHKP_PROJECT_REGISTRY_COLUMNS``: a descriptive future-project label may
# have no public development ID, legal vendor, or numeric ownership yet.
SHKP_PIPELINE_PROJECT_REGISTRY_COLUMNS = [
    "pipeline_registry_key",
    "project_label",
    "project_state",
    "geography",
    "disclosure_id",
    "disclosure_type",
    "publication_date",
    "evidence_status",
    "evidence_context",
    "source_url",
    "annual_report_id",
    "annual_report_period_end",
    "annual_evidence_type",
    "annual_document_url",
    "annual_page_number",
    "annual_group_interest_raw",
    "annual_group_interest_pct",
    "srpe_candidate_ids",
    "srpe_candidate_names",
    "srpe_candidate_phase_names",
    "srpe_match_status",
    "srpe_candidate_count",
    "ownership_status",
    "sales_ingestion_status",
    "last_verified_at",
]


SHKP_CORPORATE_PAGES: tuple[tuple[str, str], ...] = (
    (
        "financial_results_reports",
        f"{SHKP_SITE_BASE}/en-US/investor-relations/financial-results-reports",
    ),
    (
        "quarterly_article",
        f"{SHKP_SITE_BASE}/en-US/investor-relations/shkp-quarterly",
    ),
    (
        "announcement",
        f"{SHKP_SITE_BASE}/en-US/investor-relations/announcements",
    ),
)

SHKP_HISTORY_MILESTONES_URL = f"{SHKP_SITE_BASE}/en-US/about-us/history-and-milestones"

# Curated release evidence for the four long-form report/result pairs used by
# the first-stage SHKP financial model.  HKEX publication time is the PIT
# availability anchor; issuer-page dates and PDF filesystem metadata are only
# corroborating lineage.  URL matching is intentionally token-based because
# SHKP has changed the public asset filename/path across refreshes.
SHKP_CORPORATE_RELEASE_EVIDENCE: tuple[dict[str, Any], ...] = (
    {
        "match_tokens": ("SHKPAR_EN_2022_23.pdf",),
        "document_semantics": "annual_report",
        "reporting_period_end": "2023-06-30",
        "hkex_release_at": "2023-10-04T16:36:00+08:00",
        "issuer_release_date": "2023-10-04",
        "release_source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2023/1004/2023100400815.pdf",
        "release_evidence_type": "hkex_long_form_report_release",
    },
    {
        "match_tokens": ("SHKPAR_EN_2023_24.pdf",),
        "document_semantics": "annual_report",
        "reporting_period_end": "2024-06-30",
        "hkex_release_at": "2024-10-07T16:34:00+08:00",
        "issuer_release_date": "2024-10-07",
        "release_source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2024/1007/2024100700635.pdf",
        "release_evidence_type": "hkex_long_form_report_release",
    },
    {
        "match_tokens": ("SHKPAR_EN_2024_25.pdf",),
        "document_semantics": "annual_report",
        "reporting_period_end": "2025-06-30",
        "hkex_release_at": "2025-10-08T16:32:00+08:00",
        "issuer_release_date": "2025-10-08",
        "release_source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2025/1008/2025100800798.pdf",
        "release_evidence_type": "hkex_long_form_report_release",
    },
    {
        "match_tokens": ("E_IR_2025_26.pdf",),
        "document_semantics": "interim_report",
        "reporting_period_end": "2025-12-31",
        "hkex_release_at": "2026-03-19T16:30:00+08:00",
        "issuer_release_date": "2026-03-19",
        "release_source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0319/2026031900314.pdf",
        "release_evidence_type": "hkex_long_form_report_release",
    },
    {
        "match_tokens": ("e_0016_2023", "2023%20Annual%20Results"),
        "document_semantics": "results_announcement",
        "reporting_period_end": "2023-06-30",
        "hkex_release_at": "2023-09-07T16:33:00+08:00",
        "issuer_release_date": "2023-09-07",
        "release_source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2023/0907/2023090700366.pdf",
        "release_evidence_type": "hkex_results_announcement_release",
    },
    {
        "match_tokens": ("e_0016_2024", "2024%20Annual%20Results"),
        "document_semantics": "results_announcement",
        "reporting_period_end": "2024-06-30",
        "hkex_release_at": "2024-09-05T16:35:00+08:00",
        "issuer_release_date": "2024-09-05",
        "release_source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2024/0905/2024090500979.pdf",
        "release_evidence_type": "hkex_results_announcement_release",
    },
    {
        "match_tokens": ("SHKP_FY25", "2025%20Annual%20Results"),
        "document_semantics": "results_announcement",
        "reporting_period_end": "2025-06-30",
        "hkex_release_at": "2025-09-04T16:30:00+08:00",
        "issuer_release_date": "2025-09-04",
        "release_source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2025/0904/2025090400537.pdf",
        "release_evidence_type": "hkex_results_announcement_release",
    },
    {
        "match_tokens": ("ew_00016_2026", "2026%20Interim%20Results"),
        "document_semantics": "interim_results_announcement",
        "reporting_period_end": "2025-12-31",
        "hkex_release_at": "2026-02-26T16:30:00+08:00",
        "issuer_release_date": "2026-02-26",
        "release_source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0226/2026022600355.pdf",
        "release_evidence_type": "hkex_results_announcement_release",
    },
)


def _corporate_release_metadata(document_url: Any, title: Any = None) -> dict[str, Any]:
    """Return curated HKEX release metadata for a known SHKP document."""
    haystack = " ".join(
        unquote(str(value or "")).strip().casefold()
        for value in (document_url, title)
    )
    for evidence in SHKP_CORPORATE_RELEASE_EVIDENCE:
        tokens = tuple(str(token).casefold() for token in evidence["match_tokens"])
        if any(token in haystack for token in tokens):
            return {
                key: evidence.get(key)
                for key in (
                    "document_semantics",
                    "reporting_period_end",
                    "hkex_release_at",
                    "issuer_release_date",
                    "release_source_url",
                    "release_evidence_type",
                )
            }
    return {
        key: None
        for key in (
            "document_semantics",
            "reporting_period_end",
            "hkex_release_at",
            "issuer_release_date",
            "release_source_url",
            "release_evidence_type",
        )
    }


def enrich_shkp_corporate_document_release_dates(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach known HKEX release dates without guessing unknown documents.

    This also upgrades older normalized catalogues that predate the release
    metadata columns.  Unknown rows remain null and therefore stay discovery-
    only in the vintage contract.
    """
    result = frame.copy() if frame is not None else pd.DataFrame()
    for column in CORPORATE_DOCUMENT_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    if result.empty:
        return result.reindex(columns=CORPORATE_DOCUMENT_COLUMNS)
    metadata = result.apply(
        lambda row: _corporate_release_metadata(row.get("document_url"), row.get("title")),
        axis=1,
        result_type="expand",
    )
    for column in metadata.columns:
        # Curated evidence is authoritative for a matching known document;
        # preserve existing non-null values for unrelated/custom rows.
        result[column] = metadata[column].where(metadata[column].notna(), result[column])
    return result.reindex(columns=CORPORATE_DOCUMENT_COLUMNS)

# These are deliberately evidence labels, not an inferred project registry.
# The wording is taken from the official 2025/26 interim-results announcement;
# each fetch stores the surrounding text so a reviewer can promote a label only
# after matching it to SRPE/LandsD/BD and an ownership document.
SHKP_PIPELINE_DISCLOSURES: tuple[dict[str, Any], ...] = (
    {
        "disclosure_id": "shkp_202526_interim",
        "disclosure_type": "interim_results",
        "url": f"{SHKP_SITE_BASE}/en-US/media/press-releases/sun-hung-kai-properties-202526-interim-results-announcement",
        "publication_date": "2026-02-26",
        "items": (
            ("Cullinan Harbour Phase 2", "planned_launch_10m", "Kai Tak", "second phase of Cullinan Harbour"),
            ("Tsuen Wan West project", "planned_launch_10m", "Tsuen Wan", "project near MTR Tsuen Wan West Station"),
            ("Sha Po South project", "planned_launch_10m", "Yuen Long", "project at Sha Po South in Yuen Long"),
            ("Kwu Tung adjacent project Phase 1", "planned_launch_10m", "Kwu Tung", "first phase of a large-scale development adjacent to MTR Kwu Tung Station"),
            ("City One Sha Tin project", "planned_launch_10m", "Sha Tin", "project near MTR City One Station in Sha Tin"),
            ("Tung Shing Lei Phase 1", "planned_launch_10m", "Yuen Long", "first phase of Tung Shing Lei project in Yuen Long"),
            ("Kwu Tung South residential development", "under_development", "Kwu Tung South, Sheung Shui", "residential development in Kwu Tung South"),
            ("Artist Square Towers", "under_development", "West Kowloon", "Artist Square Towers Project"),
        ),
    },
)

SHKP_ANNUAL_REPORTS: tuple[dict[str, Any], ...] = (
    {
        "report_id": "shkp_ar_2023_24",
        "report_period_end": "2024-06-30",
        "url": f"{SHKP_SITE_BASE}/Content/Uploads/FinReports/SHKPAR_EN_2023_24.pdf",
        # Physical pages containing the Principal Subsidiaries appendix in
        # this report vintage (the printed page numbers are 220-224).
        "principal_pdf_page_range": (215, 231),
    },
    {
        "report_id": "shkp_ar_2024_25",
        "report_period_end": "2025-06-30",
        "url": f"{SHKP_SITE_BASE}/Content/Uploads/FinReports/SHKPAR_EN_2024_25.pdf",
        # The official annual report has 227 physical pages; the Principal
        # Subsidiaries appendix is near the end (printed pages 204-220).
        "principal_pdf_page_range": (195, 227),
    },
    {
        "report_id": "shkp_ar_2022_23",
        "report_period_end": "2023-06-30",
        "url": f"{SHKP_SITE_BASE}/Content/Uploads/FinReports/SHKPAR_EN_2022_23.pdf",
        "principal_pdf_page_range": (230, 247),
    },
)

# Official SHKP investor-relations snapshot.  The schedule says its
# information is current to late February 2026 and defines completion as the
# stage at which a project is ready for handover.  Keep older schedule URLs
# out of the routine run until their layout/version lineage is separately
# audited; callers can still pass a custom schedule to the parser in tests.
SHKP_COMPLETION_SCHEDULES: tuple[dict[str, Any], ...] = (
    {
        "schedule_id": "shkp_completion_hk_sep_2021",
        "schedule_date": "2021-09-30",
        "url": f"{SHKP_SITE_BASE}/sites/assets/files/2021-09/Completion%20Schedule_HongKong_Sep%202021_E.pdf",
    },
    {
        "schedule_id": "shkp_completion_hk_sep_2023",
        "schedule_date": "2023-09-30",
        "url": f"{SHKP_SITE_BASE}/sites/assets/files/2023-09/CompletionSchedule_HongKong_Sep2023_E.pdf",
    },
    {
        "schedule_id": "shkp_completion_hk_feb_2026",
        "schedule_date": "2026-02-28",
        "url": f"{SHKP_SITE_BASE}/sites/assets/files/2026-02/Completion%20Schedule_HK_E_Feb%202026.pdf",
    },
)

# These are bounded lot/phase bridges, not name/geography guesses.  The
# source schedule often reports one row for several phases, so one-to-many
# mappings remain ``ambiguous`` in the crosswalk and never become an ownership
# promotion by themselves.  The phase IDs are current SRPE IDs observed in the
# full all-development index.
SHKP_COMPLETION_SCHEDULE_SRPE_HINTS: dict[str, tuple[str, ...]] = {
    "new kowloon inland lot no. 6568": ("9366", "11005"),
    "new kowloon inland lot no. 6551": ("9785", "10405", "11516"),
    "tai po town lot no. 253 sai sha phases 1a 2 1b": ("10685", "10725"),
    "tai po town lot no. 253 sai sha phase 2a 2b": ("11305", "11345"),
    # Exact legal-lot bridge established from Garden Regency's official
    # brochure and SHKP's dated schedule.  It still remains reviewable in the
    # crosswalk before sales attribution is enabled.
    "lot no. 1071 in dd 103": ("11554",),
    "tin wing stop development phase 2": ("10585",),
}

# LandsD consent tables sometimes publish a project name as ``Unknown`` (or
# only expose the lot column).  These are explicit legal-lot bridges already
# audited against the SRPE index; they are allowed to create review
# candidates, but never a single-phase ownership promotion.  Keep the keys
# compact because the source table mixes English and Chinese lot labels, e.g.
# ``NKIL 6551 新九龍內地段第6551號``.
SHKP_PLANNING_SRPE_LOT_HINTS: dict[str, tuple[str, ...]] = {
    "nkil6551": ("9785", "10405", "11516"),
    "nkil6568": ("9366", "11005"),
    "tswtl23": ("9565", "10585"),
    "twtl160": ("11505",),
    "lot1071indd103": ("11554",),
    "yltl510": ("7845", "8525"),
}

# Phase-qualified LandsD names can narrow a shared-lot candidate without
# becoming an ownership assertion.  Rows that say only ``Development`` (or
# combine phases) deliberately remain grouped/ambiguous; only an explicit
# phase token is allowed to apply this refinement.
SHKP_PLANNING_SRPE_PHASE_HINTS: dict[str, dict[str, tuple[str, ...]]] = {
    "nkil6568": {"phase1": ("9366",), "phase2": ("11005",)},
    "nkil6551": {
        "phase1": ("9785",),
        "phase2a": ("10405",),
        "phase2b": ("11516",),
    },
    "tswtl23": {"phase1": ("9565",), "phase2": ("10585",)},
    "yltl510": {"phaseb": ("7845",), "phasec": ("8525",)},
}

_SUPER_GREAT_OWNERSHIP_OBSERVATIONS: tuple[dict[str, Any], ...] = (
    {
        "as_of": "2018-05-15",
        "url": "https://www.hkexnews.hk/listedco/listconews/sehk/2018/0515/ltn20180515731.pdf",
        "page": "1-2",
        "type": "tender_wholly_owned_subsidiary",
        "supplemental_source_urls": (
            "https://www.info.gov.hk/gia/general/201805/15/P2018051500781.htm",
        ),
    },
    {
        "as_of": "2024-06-30",
        "url": "https://www.hkexnews.hk/listedco/listconews/sehk/2024/1007/2024100700635.pdf",
        "page": "224",
        "type": "annual_principal_subsidiary",
    },
    {
        "as_of": "2025-06-30",
        "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/1008/2025100800798.pdf",
        "page": "220",
        "type": "annual_principal_subsidiary",
    },
    {
        "as_of": "2025-12-31",
        "url": "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0319/2026031900314.pdf",
        "page": "7",
        "type": "interim_property_table_group_interest",
        "evidence_status": "numeric_grouped_project_snapshot",
        "caveat": (
            "The 2025/26 interim property table reports 100% Group's Interest for the grouped "
            "Cullinan Sky / Cullinan Sky Mall project as at 31 December 2025; it does not split "
            "Cullinan Sky Phase 1 from Phase 2 or establish a continuous effective interval."
        ),
    },
)

# The FY2026 interim-results presentation gives a current, phase-labelled
# stake snapshot for Cullinan Sky Phase 2. It is stronger than the grouped
# annual-report row for identity, but it is still a presentation-date
# observation rather than an effective ownership interval.
_CULLINAN_SKY_PHASE_2_INTERIM_OBSERVATIONS: tuple[dict[str, Any], ...] = (
    {
        "as_of": "2026-02-26",
        "url": "https://www.shkp.com/sites/assets/files/2026-02/FY26%20Interim%20Results_For%20Website.pdf",
        "page": "16 (presentation)",
        "type": "interim_phase_stake_snapshot",
        "ownership_pct": 100.0,
        "evidence_status": "numeric_phase_stake_snapshot",
        "caveat": (
            "The FY2026 interim-results presentation lists Cullinan Sky Phase 2 at 100% stake; "
            "this is a current presentation-date snapshot and does not establish the date the stake became effective, "
            "a continuous SPV chain, or an effective-to date."
        ),
    },
)

_WELL_CAPITAL_OWNERSHIP_OBSERVATIONS: tuple[dict[str, Any], ...] = (
    {
        "as_of": "2019-01-23",
        "url": "https://www.info.gov.hk/gia/general/201901/23/P2019012300718.htm",
        "page": "web",
        "type": "landsd_tender_award_parent_company",
        "ownership_pct": None,
        "evidence_status": "parent_company_observation",
        "caveat": (
            "Lands Department tender notice identifies Well Capital (H.K.) Limited as the successful tenderer "
            "for NKIL 6551 and Sun Hung Kai Properties Limited as parent company; it does not state an effective "
            "shareholding date or phase-level percentage."
        ),
    },
    {
        "as_of": "2024-06-30",
        "url": "https://www.hkexnews.hk/listedco/listconews/sehk/2024/1007/2024100700635.pdf",
        "page": "225",
        "type": "annual_principal_subsidiary",
    },
    {
        "as_of": "2025-06-30",
        "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/1008/2025100800798.pdf",
        "page": "221",
        "type": "annual_principal_subsidiary",
    },
)

# Keep this separate from the shared NKIL 6551 observations so Phase 1 and
# Phase 2A do not inherit a Phase 2B-only fact.
_CULLINAN_HARBOUR_PHASE_2B_INTERIM_OBSERVATIONS: tuple[dict[str, Any], ...] = (
    {
        "as_of": "2026-02-26",
        "url": "https://www.shkp.com/sites/assets/files/2026-02/FY26%20Interim%20Results_For%20Website.pdf",
        "page": "17 (presentation)",
        "type": "interim_phase_stake_snapshot",
        "ownership_pct": 100.0,
        "evidence_status": "numeric_phase_stake_snapshot",
        "caveat": (
            "The FY2026 interim-results pipeline table lists Cullinan Harbour Phase 2B at 100% stake; "
            "the row is a presentation-date snapshot and does not establish a continuous Well Capital ownership interval."
        ),
    },
)

_SIERRA_SEA_GROUPED_OWNERSHIP_OBSERVATIONS: tuple[dict[str, Any], ...] = (
    {
        "as_of": "2025-06-30",
        "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/1008/2025100800798.pdf",
        "page": "40",
        "type": "annual_project_table_group_interest",
        "ownership_pct": 100.0,
        "evidence_status": "numeric_grouped_project_snapshot",
        "caveat": (
            "The annual-report property table reports Tai Po Town Lot No. 253, Sai Sha Phases 2A & 2B "
            "(Sai Sha Residences) at 100% Group's Interest; the evidence is grouped across both phases and does not establish "
            "a phase-specific effective interval."
        ),
    },
)

SHKP_LEGAL_OWNERSHIP_OBSERVATION_SPECS: tuple[dict[str, Any], ...] = (
    {
        "srpe_development_ids": ("9366",),
        "spv": "Super Great Limited",
        "phase_identity_source_url": "https://www.cullinansky.com.hk/",
        "observations": _SUPER_GREAT_OWNERSHIP_OBSERVATIONS,
    },
    {
        "srpe_development_ids": ("11005",),
        "spv": "Super Great Limited",
        "phase_identity_source_url": "https://www.cullinansky.com.hk/p2",
        "observations": _SUPER_GREAT_OWNERSHIP_OBSERVATIONS,
    },
    {
        "srpe_development_ids": ("11005",),
        "spv": "Super Great Limited",
        "phase_identity_source_url": "https://www.cullinansky.com.hk/p2",
        "observations": _CULLINAN_SKY_PHASE_2_INTERIM_OBSERVATIONS,
    },
    {
        "srpe_development_ids": ("9785",),
        "spv": "Well Capital (H.K.) Limited",
        "phase_identity_source_url": "https://www.cullinanharbour.com.hk/phasei/en/",
        "observations": _WELL_CAPITAL_OWNERSHIP_OBSERVATIONS,
    },
    {
        "srpe_development_ids": ("10405",),
        "spv": "Well Capital (H.K.) Limited",
        "phase_identity_source_url": "https://www.cullinanharbour.com.hk/phaseii/en/",
        "observations": _WELL_CAPITAL_OWNERSHIP_OBSERVATIONS,
    },
    {
        "srpe_development_ids": ("11516",),
        "spv": "Well Capital (H.K.) Limited",
        "phase_identity_source_url": "https://www.cullinanharbour.com.hk/phaseiib/en/",
        "observations": _WELL_CAPITAL_OWNERSHIP_OBSERVATIONS,
    },
    {
        "srpe_development_ids": ("11516",),
        "spv": "Well Capital (H.K.) Limited",
        "phase_identity_source_url": "https://www.cullinanharbour.com.hk/phaseiib/en/",
        "observations": _CULLINAN_HARBOUR_PHASE_2B_INTERIM_OBSERVATIONS,
    },
    {
        "srpe_development_ids": ("11554",),
        "spv": "Ease Gold Development Limited",
        "phase_identity_source_url": "https://www.gardenregency.com/en/",
        "observations": (
            {
                "as_of": "2024-06-30",
                "url": "https://www.shkp.com/Content/Uploads/FinReports/SHKPAR_EN_2023_24.pdf",
                "page": "221",
                "type": "annual_principal_subsidiary",
            },
            {
                "as_of": "2026-02-26",
                "url": "https://www.shkp.com/sites/assets/files/2026-02/FY26%20Interim%20Results_For%20Website.pdf",
                "page": "17 (presentation)",
                "type": "interim_lot_stake_snapshot",
                "ownership_pct": 100.0,
                "evidence_status": "numeric_lot_bridged_project_snapshot",
                "caveat": (
                    "The FY2026 interim-results pipeline table lists Lot No. 1071 in DD103 at 100% stake; "
                    "the lot bridge identifies Garden Regency, but this presentation-date fact is not a legal effective interval."
                ),
            },
        ),
    },
    {
        "srpe_development_ids": ("11505",),
        "spv": "Tippon Investment Enterprises Limited",
        "phase_identity_source_url": "https://www.limespark.hk/en-US",
        "observations": (
            {
                "as_of": "2025-06-30",
                "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/1008/2025100800798.pdf",
                "page": "40, 42",
                "type": "annual_project_table_group_interest",
                "evidence_status": "numeric_address_bridged_project_snapshot",
                "caveat": (
                    "The annual report records 13–23 Wang Wo Tsai Street, Tsuen Wan at 100% Group's Interest; "
                    "the address/lot bridge resolves this project row to SRPE 11505 Lime Spark, but it is not a "
                    "phase-specific SPV effective interval."
                ),
            },
            {
                "as_of": "2026-02-26",
                "url": "https://www.shkp.com/sites/assets/files/2026-02/FY26%20Interim%20Results_For%20Website.pdf",
                "page": "17 (presentation)",
                "type": "interim_address_stake_snapshot",
                "ownership_pct": 100.0,
                "evidence_status": "numeric_address_bridged_project_snapshot",
                "caveat": (
                    "The FY2026 interim-results pipeline table lists 13–23 Wang Wo Tsai Street at 100% stake; "
                    "the address bridge identifies Lime Spark, but this presentation-date fact is not a phase/SPV effective interval."
                ),
            },
        ),
    },
    {
        "srpe_development_ids": ("11305", "11345"),
        "spv": "Unresolved Sai Sha Residences project entity",
        "phase_identity_source_url": "https://www.srpe.gov.hk/opip/all_development",
        "observations": _SIERRA_SEA_GROUPED_OWNERSHIP_OBSERVATIONS,
    },
)

# Some SHKP directory rows point several Cullinan Harbour phases at the same
# root domain.  The statutory vendor notice is phase-specific, so use the
# official phase pages when the marketing label is explicit.  This is a URL
# identity/evidence correction only; it does not infer a legal ownership
# percentage or an effective date.
SHKP_PROJECT_SITE_URL_OVERRIDES: dict[str, str] = {
    "cullinanharbourphase1": "https://www.cullinanharbour.com.hk/phasei/en/",
    "cullinanharbourphase2a": "https://www.cullinanharbour.com.hk/phaseii/en/",
    "cullinanharbourphase2b": "https://www.cullinanharbour.com.hk/phaseiib/en/",
    "cullinansky": "https://www.cullinansky.com.hk/",
    "cullinanskyphase2": "https://www.cullinansky.com.hk/p2",
}

# Supplemental first-party bridge for the only current one-to-one numeric
# schedule match.  The brochure is retained as evidence that the project is
# built on the exact lot named by SHKP; it still does not establish the legal
# SPV's current shareholding or an effective-date history.
SHKP_COMPLETION_SCHEDULE_SUPPLEMENTAL_EVIDENCE: dict[str, dict[str, str]] = {
    "11554": {
        "evidence_level": "official_project_brochure_legal_lot_bridge",
        "source_url": "https://www.gardenregency.com/en/component/phocadownload/category/3-sales-brochure.html?download=415:please-click-here-to-download&Itemid=152",
        "evidence_context": "Garden Regency official sales brochure identifies Lot 1071 in DD 103; this matches the SHKP completion-schedule lot row.",
    },
}

# Explicit annual-report phase qualifiers that are stronger than the shared
# project name/address.  A grouped report row still remains ``ambiguous``
# when it names two phases, but the candidate IDs are bounded to the phases
# actually named instead of every phase on the same lot.
SHKP_ANNUAL_SRPE_PHASE_HINTS: dict[str, tuple[str, ...]] = {
    "novo land phases 2a 2b": ("9146", "9085"),
    "novo land phases 3a 3b": ("10765", "10045"),
    "grand jeté phase 1": ("8505",),
    "grand jeté phase 2": ("9145",),
    # The annual reports call the development "Sai Sha Residences", while
    # SRPE currently exposes the same lot as Sierra Sea.  The exact phase
    # qualifier is therefore the useful bridge; keep both phases as a
    # grouped candidate rather than silently assigning either one.
    "sai sha residences phase 2a and 2b": ("11305", "11345"),
}

# A small number of official disclosures use a marketing/site label that is
# materially different from SRPE's development name (for example, ``Sai Sha
# Residences`` versus ``Sierra Sea``).  These bridges are deliberately
# explicit and phase-bounded; they may create candidates only when the
# configured SRPE IDs are actually present in the live index.
SHKP_ANNUAL_SRPE_ALIAS_HINTS: dict[str, tuple[str, ...]] = {
    "sai sha residences phase 2a and 2b": ("11305", "11345"),
}

# First-party interim-result labels that can be bridged to an SRPE phase only
# through a dated lot/address/vendor record.  These are intentionally review
# matches: the bridge resolves identity, but never promotes legal ownership or
# opens the sales-ingestion gate.
SHKP_PIPELINE_SRPE_ALIAS_HINTS: dict[str, tuple[str, ...]] = {
    "shaposouthproject": ("11554",),
    "tsuenwanwestproject": ("11505",),
}

# Explicitly non-residential labels are kept in the SHKP pipeline but routed
# out of the SRPE residential identity queue.  A commercial/BOT project must
# not be treated as an unmatched first-hand residential phase merely because
# it has no row in the SRPE index.
SHKP_NON_SRPE_COMMERCIAL_LABELS: dict[str, str] = {
    "artistsquaretowers": "commercial_investment_bot",
    "igcofficetowers": "commercial_investment",
    "internationalgatewaycentreigcofficeportion": "commercial_investment",
    "cullinanskymall": "commercial_investment",
    "scramblehill": "commercial_investment",
}

# Curated phase-level exclusions verified against official developer
# disclosures / public records (2026-08-09).  The annual-report label match
# is phase-inclusive for shared lot addresses (e.g. every Lohas Park phase
# shares ``1 Lohas Park Road``), so ``address_contains`` can fan a single
# SHKP annual label (e.g. "Wings at Sea & Wings at Sea II") out to phases
# that are actually owned by other developers.  These rows must never be
# treated as SHKP residential phases, even though their SRPE row carries an
# ambiguous annual-report match.  The mapping value is the verified actual
# developer and the review basis.
SHKP_CURATED_NON_SHKP_SRPE_PHASES: dict[str, str] = {
    # Lohas Park (康城) phases that are NOT Sun Hung Kai:
    # Phase 1 首都 THE CAPITOL / Phase 2 領都 LE PRIME / Phase 3 緻藍天 THE
    # WINGS are CK Asset + Nan Fung + MTR.  Phase 5 MALIBU, Phase 6 LP6,
    # Phase 7A MONTARA, 7B GRAND MONTARA, Phase 9 MARINI / GRAND MARINI /
    # OCEAN MARINI are Wheelock; Phase 10 LP10 is Nan Fung; Phase 11 凱柏峰
    # VILLA GARDA I-III is Sino Land + K. Wah + China Merchants; Phase 12
    # SEASONS PLACE / PARK SEASONS / GRAND SEASONS and Phase 13 LA MIRABELLE
    # I/II are Wheelock-led.  Only Phase 4 (晉海 WINGS AT SEA / WINGS AT SEA
    # II) belongs to SHKP and is intentionally NOT excluded here.
    "5065": "malibu_wheelock_mtr_not_shkp",
    "7425": "lp10_nanfung_mtr_not_shkp",
    "6045": "montara_wheelock_mtr_not_shkp",
    "6145": "grand_montara_wheelock_mtr_not_shkp",
    "6265": "marini_wheelock_mtr_not_shkp",
    "6285": "grand_marini_wheelock_mtr_not_shkp",
    "6525": "ocean_marini_wheelock_mtr_not_shkp",
    "8545": "villa_garda_i_sino_kwah_cmst_not_shkp",
    "8625": "villa_garda_ii_sino_kwah_cmst_not_shkp",
    "8645": "villa_garda_iii_sino_kwah_cmst_not_shkp",
    "9829": "seasons_place_wheelock_mtr_not_shkp",
    "9830": "park_seasons_wheelock_mtr_not_shkp",
    "10486": "grand_seasons_wheelock_mtr_not_shkp",
    "11385": "la_mirabelle_ii_wheelock_led_not_shkp",
    "11386": "la_mirabelle_i_wheelock_led_not_shkp",
    # One Innovale (粉嶺北) is Henderson Land, not SHKP.  Its SRPE row sits
    # at 8 Ma Sik Road; the annual "Noble Hill" label (38 Ma Sik Road,
    # Sheung Shui) matched it only through a partial address substring.
    "8667": "one_innovale_phase1_henderson_not_shkp",
    "8786": "one_innovale_phase2_henderson_not_shkp",
    "8825": "one_innovale_phase3_henderson_not_shkp",
    # 2026-08-09 quick verification: Mount Nicholson (聶歌信山) is a 50:50
    # Wharf Holdings + Nan Fung JV (Wheelock is sales agent only), and
    # Mount Pavilia (傲瀧) is New World Development + Pukik Holdings.
    # Neither is SHKP; their SRPE transaction registers were downloaded in
    # the historical-coverage backfill and must not enter the model.
    "2526": "mount_nicholson_wharf_nanfung_not_shkp",
    "2545": "mount_nicholson_wharf_nanfung_not_shkp",
    "2605": "mount_pavilia_newworld_pukik_not_shkp",
}

# Curated JV stake evidence for the remaining SHKP joint-venture phases
# (verified 2026-08-09).  MTR station-over-platform developments are the
# dominant case: MTR contributes the land/platform and receives a
# consideration, while SHKP leads development with a much larger economic
# interest than a mechanical 50/50 split would imply.
#
# * Cullinan West (匯璽, Nam Cheong Station): SHKP subsidiary develops and
#   holds the development rights; MTR acts as land owner/platform provider.
#   SHKP's economic interest is effectively 100%; the "JV" label in the
#   annual report reflects the MTR land arrangement, not a 50% equity share.
# * The YOHO Hub I/II and YOHO WEST: disclosed as 50% SHKP / 50% MTR joint
#   ventures; the mechanical 50% base is correct.
# * Wings at Sea (晉海, Lohas Park Phase 4): SHKP-led with MTR as owner;
#   no public percentage, 50% remains a conservative working assumption.
SHKP_CURATED_JV_STAKE_OVERRIDES: dict[str, float] = {
    # Values are PERCENT (consistent with indicative_ownership_pct where
    # 100.0 = 100%); 1.0 here would be misread as 1%.
    "3945": 100.0,  # Cullinan West
    "4945": 100.0,  # Cullinan West II
    "5886": 100.0,  # Cullinan West III
}

# Curated SHKP phase promotions verified 2026-08-09 from annual-report
# evidence.  These phases carry official SHKP evidence but were left
# outside the automatic roster promotion (e.g. historical projects whose
# annual labels are generic).  Promotion assigns a numeric stake for the
# research layer only; the strict ownership gate stays blocked.
SHKP_CURATED_PROMOTIONS: dict[str, float] = {
    # Kowloon Station Development - The Cullinan (天璽): SHKP flagship,
    # opened 2013-09; annual report lists ICC Phase 3 / Ritz-Carlton and
    # history milestones confirm SHKP development.  Its 250 transaction
    # events (HKD 11.4bn, FY2014+ concentrated) were missing from the
    # historical layer, which caused the early-year under-coverage.
    "645": 100.0,
    # Shouson Peak (壽臣山, opened 2013-09) and Twelve Peaks (山頂,
    # opened 2014-06): SHKP luxury houses with direct annual-report label
    # evidence ("Shouson Peak", "Twelve Peaks").  Their early transaction
    # registers were missing from the model, contributing to the
    # FY2017-2022 under-coverage.
    "285": 100.0,
    "966": 100.0,
    # The Wings (唐賢街9號, Tseung Kwan O) - SHKP's own development; the
    # annual report lists "The Wings IIIA / IIIB" at 100% owned in the
    # FY2015-17 handover tables.  This is NOT the CK Asset "The Wings"
    # (Lo Wu / LOHAS Park 緻藍天) that the earlier address-based exclusion
    # targeted; the two are different projects and the exclusion wrongly
    # suppressed this phase's annual evidence.  Opened 2016-12.
    "3005": 100.0,
}

# A major-project fact box often names the legal lot but not the SRPE
# marketing/phase name.  Reuse only the bounded lot bridges already audited
# for the dated completion schedule; these create review candidates and never
# create a single-phase or ownership promotion.
SHKP_ANNUAL_SRPE_LOT_HINTS: dict[str, tuple[str, ...]] = {
    "new kowloon inland lot no. 6568": ("9366", "11005"),
    "new kowloon inland lot no. 6551": ("9785", "10405", "11516"),
    "tai po town lot no. 253 sai sha": ("10685", "10725", "11305", "11345"),
}

# The annual report's future-pipeline paragraphs use descriptive labels for
# several projects that do not yet have a public marketing name.  Keep those
# labels as evidence anchors instead of inventing a project ID.
SHKP_ANNUAL_PIPELINE_ITEMS: tuple[dict[str, str], ...] = (
    {
        "project_label": "Cullinan Sky Phase 2 / Cullinan Harbour Phase 2",
        "project_state": "planned_sale_10m",
        "geography": "Kai Tak",
        "search_phrase": "second phases of Cullinan Sky and Cullinan Harbour",
    },
    {
        "project_label": "Sai Sha Residences Phase 2A and 2B",
        "project_state": "planned_sale_10m",
        "geography": "Sai Sha",
        "search_phrase": "Sai Sha Residences Phase 2A and 2B",
    },
    {
        "project_label": "Tsuen Wan West project (descriptive label)",
        "project_state": "planned_sale_10m",
        "geography": "Tsuen Wan West",
        "search_phrase": "a project near MTR Tsuen Wan West Station",
    },
    {
        "project_label": "Kwu Tung adjacent project Phase 1 (descriptive label)",
        "project_state": "planned_sale_10m",
        "geography": "Kwu Tung",
        "search_phrase": "the first phase of a large-scale development adjacent to MTR Kwu Tung Station",
    },
    {
        "project_label": "Scramble Hill",
        "project_state": "investment_property_completion",
        "geography": "Kwun Tong",
        "search_phrase": "Scramble Hill, a brand-new shopping mall in Kwun Tong",
    },
    {
        "project_label": "Cullinan Sky Mall",
        "project_state": "investment_property_completion",
        "geography": "Kai Tak",
        "search_phrase": "Cullinan Sky Mall in Kai Tak",
    },
    {
        "project_label": "IGC office towers",
        "project_state": "handover_window",
        "geography": "West Kowloon",
        "search_phrase": "IGC office towers atop the High Speed Rail West Kowloon Terminus",
    },
)

SHKP_SUPPORTING_SOURCES: tuple[dict[str, str], ...] = (
    {
        "source_id": "srpe_all_development",
        "agency": "SRPE / SRPA",
        "evidence_type": "first_hand_development_phase",
        "source_url": "https://www.srpe.gov.hk/opip/all_development",
        "source_grain": "development/phase",
        "join_keys": "development_id;official_website;address",
        "status": "available",
        "caveat": "First-hand residential development index; not a legal ownership table.",
    },
    {
        "source_id": "buildings_department_md53_md56",
        "agency": "Hong Kong Buildings Department",
        "evidence_type": "construction_lifecycle",
        "source_url": "https://www.bd.gov.hk/en/whats-new/monthly-digests/index.html",
        "source_grain": "monthly project/stage XLS",
        "join_keys": "site_address;permit_number;stage",
        "status": "available",
        "caveat": "Md53-Md56 are current monthly snapshots; address matching is a candidate link, not ownership proof.",
    },
    {
        "source_id": "landsd_land_sale_records",
        "agency": "Lands Department",
        "evidence_type": "land_sale_and_tender",
        "source_url": "https://www.landsd.gov.hk/en/resources/land-info-stat/land-sale/land-sale-records.html",
        "source_grain": "land lot / tender record",
        "join_keys": "lot_number;site_address;disposal_date",
        "status": "catalog_only",
        "caveat": "Land disposal evidence does not by itself prove current SPV ownership or residential phase mapping.",
    },
    {
        "source_id": "landsd_development_control_consent",
        "agency": "Lands Department",
        "evidence_type": "consent_and_deed",
        "source_url": "https://www.landsd.gov.hk/en/resources/land-info-stat/dev-control-compliance/consent/consents-sell-assign-approvals-deeds-mutual-covenant.html",
        "source_grain": "lot / consent / deed document",
        "join_keys": "lot_number;vendor;project_alias",
        "status": "catalog_only",
        "caveat": "Historical PDFs require document-level extraction and version/date preservation.",
    },
    {
        "source_id": "land_registry_iris_search",
        "agency": "Hong Kong Land Registry",
        "evidence_type": "registered_title_and_memorial",
        "source_url": "https://www.landreg.gov.hk/en/services/services_b_2.htm",
        "source_grain": "current/full land register and memorial document",
        "join_keys": "lot_number;property_reference_number;memorial_number",
        "status": "paid_manual",
        "caveat": "IRIS ad-hoc searches are paid and there is no public batch endpoint for ordinary users; title events do not automatically establish SHKP economic ownership or a phase interval.",
    },
    {
        "source_id": "land_registry_street_index_crt",
        "agency": "Hong Kong Land Registry",
        "evidence_type": "lot_address_reference",
        "source_url": "https://www.landreg.gov.hk/en/public/pu-si_agree.htm",
        "source_grain": "street index / New Territories lot-address cross-reference",
        "join_keys": "street_name;address;lot_number",
        "status": "reference_only_manual_browse",
        "caveat": "The free online SI/CRT service is browsing-only and its terms prohibit downloading, saving, copying or reproducing the data; it may guide manual IRIS searches but must not be scraped into normalized data.",
    },
    {
        "source_id": "tpb_applications_under_processing",
        "agency": "Town Planning Board",
        "evidence_type": "planning_application",
        "source_url": "https://www.tpb.gov.hk/en/plan_application/application_comment_list.html",
        "source_grain": "planning application",
        "join_keys": "application_number;lot_number;site_address",
        "status": "catalog_only",
        "caveat": "Planning application status is an early project signal, not a construction or sales milestone.",
    },
    {
        "source_id": "tpb_statutory_planning_portal",
        "agency": "Town Planning Board",
        "evidence_type": "ozp_and_permission",
        "source_url": "https://www.ozp.tpb.gov.hk/",
        "source_grain": "OZP / planning permission",
        "join_keys": "ozp_reference;lot_number;site_address",
        "status": "catalog_only",
        "caveat": "Portal records need a separate parser and should remain point-in-time evidence.",
    },
)


def _page_tag(html: str, container_id: str) -> str | None:
    match = re.search(
        rf'<(?:div|section)[^>]+id=["\']{re.escape(container_id)}["\'][^>]*>',
        html,
        flags=re.IGNORECASE,
    )
    return match.group(0) if match else None


def _page_total(html: str, container_id: str) -> int:
    tag = _page_tag(html, container_id)
    if not tag:
        return 1
    match = re.search(r'data-totalpage=["\'](\d+)', tag, flags=re.IGNORECASE)
    return max(1, int(match.group(1))) if match else 1


def _page_href(html: str, container_id: str, fallback: str) -> str:
    tag = _page_tag(html, container_id)
    if not tag:
        return fallback
    match = re.search(r'data-href=["\']([^"\']+)', tag, flags=re.IGNORECASE)
    return match.group(1) if match else fallback


def _external_urls(raw_langcode: Any) -> list[str]:
    """Extract every external project link from SHKP's HTML fragment.

    The site JavaScript currently keeps only one ``http://`` anchor.  That
    loses HTTPS links and multi-phase links (e.g. NOVO LAND), so the ingestion
    deliberately preserves all anchors instead.
    """
    if raw_langcode is None or (isinstance(raw_langcode, float) and pd.isna(raw_langcode)):
        return []
    fragment = str(raw_langcode)
    soup = BeautifulSoup(fragment, "html.parser")
    urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if href.lower().startswith(("http://", "https://")):
            if href not in urls:
                urls.append(href)
    return urls


def _normalize_rows(
    rows: Iterable[dict[str, Any]],
    *,
    config: dict[str, Any],
    source_page_url: str,
    source_url: str,
    page_number: int,
    fetched_at: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for display_order, row in enumerate(rows, start=1):
        name = str(row.get("name") or "").strip()
        if not name:
            # A nameless JSON row is not useful as a catalogue record.  Keep
            # the raw response in lineage so it can be inspected later.
            continue
        urls = _external_urls(row.get("langcode"))
        records.append(
            {
                "asset_type": config["asset_type"],
                "subtype": config["subtype"],
                "marketing_name": name,
                "district": str(row.get("districtLabel") or "").strip(),
                "thumbnail_url": urljoin(SHKP_SITE_BASE, str(row.get("src") or "")),
                "external_project_url": urls[0] if urls else None,
                "external_project_urls": json.dumps(urls, ensure_ascii=False),
                "raw_langcode": str(row.get("langcode") or ""),
                "source_record_id": f"{config['asset_type']}:{config['subtype']}:{page_number}:{display_order}",
                "source_page_url": source_page_url,
                "source_url": source_url,
                "page_number": page_number,
                "display_order": display_order,
                "listed_status": "current_website_listing",
                "fetched_at": fetched_at,
            }
        )
    return records


def fetch_shkp_property_catalog(
    *,
    session: requests.Session | None = None,
    timeout: float = 60,
    max_pages: int | None = None,
    tolerate_category_errors: bool = True,
) -> pd.DataFrame:
    """Fetch SHKP's current Hong Kong property-directory listings.

    This intentionally covers the site JSON catalogues (residential sale and
    lease, malls, offices, hotels and serviced suites).  The industrial page
    currently exposes a static photo album rather than a project JSON list;
    it is therefore not silently represented as a zero-row project feed.
    """
    client = session or requests.Session()
    client.headers.update(
        {
            **DEFAULT_HEADERS,
            "Accept": "application/json, text/html, */*",
            "Referer": f"{SHKP_SITE_BASE}/en-US/our-business/hong-kong-properties",
        }
    )
    fetched_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    fetch_summary: list[dict[str, Any]] = []

    for config in SHKP_LISTING_CONFIGS:
        landing_url = f"{SHKP_HK_PROPERTIES_BASE}/{config['path']}"
        category_rows = 0
        total_pages = 0
        category_summary: dict[str, Any] = {
            "asset_type": config["asset_type"],
            "subtype": config["subtype"],
            "pages_fetched": 0,
            "rows_emitted": 0,
            "source_page_url": landing_url,
            "status": "failed",
            "error_type": None,
            "error": None,
        }
        try:
            landing = client.get(landing_url, timeout=timeout)
            # Save the body before status validation: a 999/403 HTML response
            # is useful evidence of WAF/source drift and must not disappear.
            landing_raw = save_raw_snapshot(
                f"shkp_{config['asset_type']}_{config['subtype']}_landing",
                getattr(landing, "content", getattr(landing, "text", "")),
                file_ext="html",
                source_url=landing_url,
            )
            raw_snapshots.append(str(landing_raw))
            source_urls.append(landing_url)
            landing.raise_for_status()
            html = landing.text
            page_href = _page_href(html, config["container_id"], landing_url)
            total_pages = _page_total(html, config["container_id"])
            if max_pages is not None:
                total_pages = min(total_pages, max(1, int(max_pages)))

            for page_number in range(total_pages):
                query = dict(config.get("query") or {})
                query["page"] = page_number
                query_text = urlencode(query)
                endpoint_suffix = str(config.get("endpoint_suffix") or "").rstrip("/")
                api_url = f"{page_href.rstrip('/')}{endpoint_suffix}/getList?{query_text}"
                response = client.get(api_url, timeout=timeout)
                raw_json = save_raw_snapshot(
                    f"shkp_{config['asset_type']}_{config['subtype']}_listing",
                    getattr(response, "content", getattr(response, "text", "")),
                    file_ext="json",
                    source_url=api_url,
                )
                raw_snapshots.append(str(raw_json))
                source_urls.append(api_url)
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError as first_error:
                    # The SHKP endpoint occasionally returns an HTML/empty
                    # 200 response under transient WAF pressure.  Retry a
                    # bounded number of times while keeping each bad body.
                    payload = None
                    last_error: Exception = first_error
                    for retry in range(2):
                        time.sleep(0.5 * (retry + 1))
                        retry_response = client.get(api_url, timeout=timeout)
                        retry_raw = save_raw_snapshot(
                            f"shkp_{config['asset_type']}_{config['subtype']}_listing_retry",
                            getattr(retry_response, "content", getattr(retry_response, "text", "")),
                            file_ext="json",
                            source_url=api_url,
                        )
                        raw_snapshots.append(str(retry_raw))
                        try:
                            retry_response.raise_for_status()
                            payload = retry_response.json()
                            break
                        except (ValueError, requests.RequestException) as retry_error:
                            last_error = retry_error
                    if payload is None:
                        preview = str(getattr(response, "text", ""))[:120].replace("\n", " ")
                        raise ValueError(
                            f"SHKP listing endpoint returned non-JSON after 3 attempts: "
                            f"{api_url} (status={getattr(response, 'status_code', None)}, preview={preview!r})"
                        ) from last_error
                if not isinstance(payload, list):
                    raise ValueError(f"SHKP listing endpoint returned non-list JSON: {api_url}")
                normalized = _normalize_rows(
                    payload,
                    config=config,
                    source_page_url=landing_url,
                    source_url=api_url,
                    page_number=page_number,
                    fetched_at=fetched_at,
                )
                records.extend(normalized)
                category_rows += len(normalized)
            category_summary.update(
                {
                    "pages_fetched": total_pages,
                    "rows_emitted": category_rows,
                    "status": "success",
                }
            )
        except Exception as exc:
            category_summary.update(
                {
                    "pages_fetched": total_pages,
                    "rows_emitted": category_rows,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            fetch_summary.append(category_summary)
            if not tolerate_category_errors:
                raise
            # A single WAF/HTML/schema failure must not erase successful
            # residential/office/mall categories from the same refresh.
            continue
        fetch_summary.append(category_summary)

    frame = pd.DataFrame(records, columns=CATALOG_COLUMNS)
    if not frame.empty:
        frame = frame.drop_duplicates(
            subset=["asset_type", "subtype", "marketing_name", "district", "external_project_url"]
        ).reset_index(drop=True)
    frame.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        lineage_metadata={
            "lineage_type": "official_website_json_catalog",
            "fetch_summary": fetch_summary,
            "partial_source_refresh": any(item.get("status") == "failed" for item in fetch_summary),
            "failed_category_count": sum(item.get("status") == "failed" for item in fetch_summary),
            "tolerate_category_errors": bool(tolerate_category_errors),
            "industrial_page_note": "static photo album; no project JSON endpoint emitted",
        },
    )
    return frame


def _host(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text if "://" in text else f"https://{text}")
    return parsed.netloc.lower().removeprefix("www.")


def _normalized_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _phase_tokens(value: Any) -> set[str]:
    """Return phase qualifiers only when the text explicitly says phase(s).

    This keeps street/lot numbers out of the comparison while allowing a
    website label such as ``Cullinan Harbour Phase 2A`` to disambiguate a
    shared official project URL.
    """
    text = str(value or "").upper()
    marker = re.search(r"\bPHASES?\b", text)
    if not marker:
        return set()
    suffix = text[marker.end() : marker.end() + 96]
    tokens = {
        re.sub(r"[^A-Z0-9]", "", token)
        for token in re.findall(r"\b\d+[A-Z]?(?:\(\d+\))?\b", suffix)
    }
    # A disclosure may say "Phase 2" while SRPE exposes Phase 2A/2B.
    # Keep the numeric base as a compatibility token, but retain the full
    # qualifier for exact phase checks.
    for token in list(tokens):
        match = re.match(r"(\d+)[A-Z]", token)
        if match:
            tokens.add(match.group(1))
    return tokens


def _phase_qualified_candidate_match(query: Any, candidate: Mapping[str, Any]) -> bool:
    """Whether a phase-qualified marketing label agrees with an SRPE row."""
    requested = _phase_tokens(query)
    if not requested:
        return False
    candidate_phase_text = " ".join(
        str(candidate.get(field) or "")
        for field in ("phase_name_en", "phase_name_zh", "phase_no")
    )
    available = _phase_tokens(candidate_phase_text)
    specific_requested = {token for token in requested if re.fullmatch(r"\d+[A-Z]", token)}
    phase_match = bool(specific_requested & available) if specific_requested else bool(requested & available)
    if not phase_match:
        return False
    query_base = _normalized_name(re.split(r"\bPHASES?\b", str(query or ""), maxsplit=1, flags=re.IGNORECASE)[0])
    candidate_base = _normalized_name(
        candidate.get("development_name_en")
        or candidate.get("display_name")
        or candidate.get("development_name_zh")
    )
    return bool(query_base and candidate_base and (query_base in candidate_base or candidate_base in query_base))


def build_shkp_srpe_crosswalk(
    shkp_catalog: pd.DataFrame,
    srpe_index: pd.DataFrame,
) -> pd.DataFrame:
    """Create an auditable SHKP marketing-name -> SRPE phase crosswalk.

    Website domains are strong discovery evidence, but a shared domain can
    serve several phases.  In that case every candidate is retained and the
    row is marked ambiguous instead of assigning sales to the wrong phase.
    """
    rows: list[dict[str, Any]] = []
    srpe_records = srpe_index.to_dict("records") if not srpe_index.empty else []
    domain_map: dict[str, list[dict[str, Any]]] = {}
    for candidate in srpe_records:
        domain = _host(candidate.get("official_website"))
        if domain:
            domain_map.setdefault(domain, []).append(candidate)

    for source_row in shkp_catalog.to_dict("records"):
        if source_row.get("asset_type") != "residential_for_sale":
            continue
        try:
            urls = json.loads(source_row.get("external_project_urls") or "[]")
        except (TypeError, json.JSONDecodeError):
            urls = []
        if not urls and source_row.get("external_project_url"):
            urls = [source_row["external_project_url"]]
        domains = {_host(url) for url in urls if _host(url)}
        candidates: dict[str, dict[str, Any]] = {}
        methods: dict[str, set[str]] = {}
        for domain in domains:
            for candidate in domain_map.get(domain, []):
                identifier = str(candidate.get("development_id"))
                candidates[identifier] = candidate
                methods.setdefault(identifier, set()).add("website_domain_exact")

        query_name = _normalized_name(source_row.get("marketing_name"))
        if query_name:
            for candidate in srpe_records:
                names = {
                    _normalized_name(candidate.get("development_name_en")),
                    _normalized_name(candidate.get("phase_name_en")),
                }
                names.discard("")
                if query_name in names:
                    identifier = str(candidate.get("development_id"))
                    candidates[identifier] = candidate
                    methods.setdefault(identifier, set()).add("name_exact")
                elif _phase_qualified_candidate_match(source_row.get("marketing_name"), candidate):
                    identifier = str(candidate.get("development_id"))
                    candidates[identifier] = candidate
                    methods.setdefault(identifier, set()).add("phase_name_exact")

        # A shared official SHKP URL is useful discovery evidence but can
        # point every phase at the first SRPE row returned by the site.  If
        # the marketing label is phase-qualified, discard domain-only rows
        # whose phase qualifier disagrees.  This prevents the previous
        # Cullinan Harbour 2A/2B -> SRPE Phase 1 false join while retaining
        # rows matched by an exact phase name.
        requested_phases = _phase_tokens(source_row.get("marketing_name"))
        if requested_phases:
            compatible: dict[str, dict[str, Any]] = {}
            compatible_methods: dict[str, set[str]] = {}
            for identifier, candidate in candidates.items():
                method_set = methods.get(identifier, set())
                candidate_phase_text = " ".join(
                    str(candidate.get(field) or "")
                    for field in ("phase_name_en", "phase_name_zh", "phase_no")
                )
                # Some official SRPE projects use a marketing alias that is
                # absent from the legal development name (for example,
                # ``Sierra Sea`` vs ``Sai Sha Residences``).  A phase-specific
                # official website domain is still a valid identity bridge,
                # but only when the explicit phase token agrees.  This is
                # deliberately narrower than geography and cannot admit a
                # whole shared domain's unrelated phase.
                website_phase_anchor = (
                    "website_domain_exact" in method_set
                    and bool(requested_phases & _phase_tokens(candidate_phase_text))
                )
                if "name_exact" in method_set or _phase_qualified_candidate_match(
                    source_row.get("marketing_name"), candidate
                ) or website_phase_anchor:
                    compatible[identifier] = candidate
                    compatible_methods[identifier] = set(method_set)
                    if website_phase_anchor:
                        compatible_methods[identifier].add("website_domain_phase_exact")
            candidates = compatible
            methods = compatible_methods

        fetched_at = source_row.get("fetched_at") or datetime.now(timezone.utc).isoformat()
        if not candidates:
            rows.append(
                {
                    "marketing_name": source_row.get("marketing_name"),
                    "external_project_url": source_row.get("external_project_url"),
                    "srpe_development_id": None,
                    "srpe_development_name": None,
                    "srpe_phase_name": None,
                    "srpe_phase_no": None,
                    "match_method": "none",
                    "match_confidence": "unmatched",
                    "match_status": "unmatched",
                    "candidate_count": 0,
                    "shkp_source_record_id": source_row.get("source_record_id"),
                    "shkp_source_url": source_row.get("source_url"),
                    "srpe_source_url": None,
                    "matched_at": fetched_at,
                    "listed_parent": None,
                    "ticker": None,
                    "ownership_pct": None,
                    "ownership_effective_from": None,
                    "ownership_effective_to": None,
                    "ownership_evidence_url": None,
                    "ownership_evidence_level": "none",
                    "ownership_status": "not_verified",
                }
            )
            continue

        candidate_count = len(candidates)
        for identifier, candidate in candidates.items():
            method_set = methods.get(identifier, set())
            method = "+".join(sorted(method_set))
            if candidate_count == 1 and "website_domain_exact" in method_set and "name_exact" in method_set:
                confidence, status = "high", "matched"
            elif candidate_count == 1:
                confidence, status = "medium", "matched_needs_review"
            else:
                confidence, status = "low", "ambiguous"
            rows.append(
                {
                    "marketing_name": source_row.get("marketing_name"),
                    "external_project_url": source_row.get("external_project_url"),
                    "srpe_development_id": identifier,
                    "srpe_development_name": candidate.get("development_name_en") or candidate.get("development_name_zh"),
                    "srpe_phase_name": candidate.get("phase_name_en") or candidate.get("phase_name_zh"),
                    "srpe_phase_no": candidate.get("phase_no"),
                    "match_method": method,
                    "match_confidence": confidence,
                    "match_status": status,
                    "candidate_count": candidate_count,
                    "shkp_source_record_id": source_row.get("source_record_id"),
                    "shkp_source_url": source_row.get("source_url"),
                    "srpe_source_url": candidate.get("source_url"),
                    "matched_at": fetched_at,
                    "listed_parent": None,
                    "ticker": None,
                    "ownership_pct": None,
                    "ownership_effective_from": None,
                    "ownership_effective_to": None,
                    "ownership_evidence_url": None,
                    "ownership_evidence_level": "none",
                    "ownership_status": "not_verified",
                }
            )
    return pd.DataFrame(rows, columns=CROSSWALK_COLUMNS)


def build_shkp_annual_srpe_crosswalk(
    annual_projects: pd.DataFrame,
    srpe_index: pd.DataFrame,
) -> pd.DataFrame:
    """Create a conservative annual-report-project -> SRPE candidate join.

    Annual reports use handover labels and addresses while SRPE uses legal
    development/phase names.  Exact phase/name and address-substring matches
    are retained as candidates; one-to-many matches remain ``ambiguous`` and
    no ownership percentage is inferred from either source.
    """
    rows: list[dict[str, Any]] = []
    srpe_records = srpe_index.to_dict("records") if not srpe_index.empty else []
    for annual in annual_projects.to_dict("records"):
        label = str(annual.get("project_label") or "").strip()
        label_norm = _normalized_name(label)
        # A label such as "NOVO LAND Phases 3A & 3B" has a useful base name,
        # but the base is intentionally only a candidate key, never a phase
        # assignment.  Keep phase-qualified exact matches alongside it.
        base_label = re.split(r"\bphases?\b", label, maxsplit=1, flags=re.IGNORECASE)[0]
        base_norm = _normalized_name(base_label)
        location_norm = _normalized_address(annual.get("location"))
        candidates: dict[str, tuple[dict[str, Any], set[str]]] = {}
        for candidate in srpe_records:
            identifier = str(candidate.get("development_id") or "")
            if not identifier:
                continue
            methods: set[str] = set()
            name_values = [
                candidate.get("display_name"),
                candidate.get("development_name_en"),
                candidate.get("phase_name_en"),
            ]
            name_norms = {_normalized_name(value) for value in name_values if _normalized_name(value)}
            if label_norm and label_norm in name_norms:
                methods.add("name_exact")
            if base_norm and base_norm in {
                _normalized_name(candidate.get("development_name_en")),
                _normalized_name(candidate.get("display_name")),
            }:
                methods.add("base_name_exact")
            candidate_address = _normalized_address(candidate.get("address_en"))
            if location_norm and candidate_address:
                if location_norm == candidate_address:
                    methods.add("address_exact")
                elif len(candidate_address) >= 8 and (
                    _safe_address_substring(candidate_address, location_norm)
                    or _safe_address_substring(location_norm, candidate_address)
                ):
                    methods.add("address_contains")
            if methods:
                candidates[identifier] = (candidate, methods)

        # Major-project fact boxes may provide only the legal lot.  Apply an
        # explicit, audited lot bridge for those rows; do not let a lot hint
        # widen handover or descriptive pipeline evidence into guessed phases.
        if annual.get("evidence_type") == "major_project_under_development":
            lot_hint_ids: set[str] = set()
            for lot_hint, identifiers in SHKP_ANNUAL_SRPE_LOT_HINTS.items():
                hint_norm = _normalized_name(lot_hint)
                if hint_norm and (hint_norm == location_norm or hint_norm in location_norm):
                    lot_hint_ids.update(identifiers)
            if lot_hint_ids:
                hinted_candidates: dict[str, tuple[dict[str, Any], set[str]]] = {}
                for candidate in srpe_records:
                    identifier = str(candidate.get("development_id") or "")
                    if identifier in lot_hint_ids:
                        prior_methods = candidates.get(identifier, ({}, set()))[1]
                        hinted_candidates[identifier] = (
                            candidate,
                            {*prior_methods, "lot_hint_exact"},
                        )
                if hinted_candidates:
                    candidates = hinted_candidates

        # Apply only explicit phase-qualified annual labels.  If a configured
        # hint is present, intersect it with the name/address candidates; do
        # not create an SRPE row that the report could not first identify by
        # its project/base name.
        phase_hint_ids: set[str] = set()
        for hint, identifiers in SHKP_ANNUAL_SRPE_PHASE_HINTS.items():
            if _normalized_name(hint) in label_norm:
                phase_hint_ids.update(identifiers)
        if phase_hint_ids:
            hinted_candidates = {
                identifier: (value[0], {*value[1], "phase_hint_exact"})
                for identifier, value in candidates.items()
                if identifier in phase_hint_ids
            }
            if hinted_candidates:
                candidates = hinted_candidates
            else:
                # Some disclosures use a stable marketing/site alias rather
                # than SRPE's development name.  Only the explicit alias map
                # may bridge that gap; do not widen this to fuzzy matching.
                alias_ids: set[str] = set()
                for alias, identifiers in SHKP_ANNUAL_SRPE_ALIAS_HINTS.items():
                    if _normalized_name(alias) in label_norm:
                        alias_ids.update(identifiers)
                if alias_ids:
                    aliased_candidates = {
                        str(candidate.get("development_id")): (
                            candidate,
                            {"annual_alias_exact", "phase_hint_exact"},
                        )
                        for candidate in srpe_records
                        if str(candidate.get("development_id") or "") in alias_ids
                    }
                    if aliased_candidates:
                        candidates = aliased_candidates

        candidate_count = len(candidates)
        if not candidates:
            candidates = {"": ({}, {"none"})}
        for identifier, (candidate, methods) in candidates.items():
            if identifier == "":
                status, confidence = "unmatched", "unmatched"
                method = "none"
            elif candidate_count > 1:
                status, confidence = "ambiguous", "low"
                method = "+".join(sorted(methods))
            elif methods.issuperset({"name_exact", "address_exact"}) or methods.issuperset({"name_exact", "address_contains"}):
                status, confidence = "matched_needs_review", "high"
                method = "+".join(sorted(methods))
            else:
                status, confidence = "matched_needs_review", "medium"
                method = "+".join(sorted(methods))
            rows.append(
                {
                    "report_id": annual.get("report_id"),
                    "report_period_end": annual.get("report_period_end"),
                    "evidence_type": annual.get("evidence_type"),
                    "project_label": label or None,
                    "project_state": annual.get("project_state"),
                    "geography": annual.get("geography"),
                    "annual_location": annual.get("location"),
                    "annual_group_interest_raw": annual.get("group_interest_raw"),
                    "annual_group_interest_pct": annual.get("group_interest_pct"),
                    "annual_page_number": annual.get("page_number"),
                    "annual_document_url": annual.get("document_url"),
                    "srpe_development_id": identifier or None,
                    "srpe_development_name": candidate.get("development_name_en") or candidate.get("display_name"),
                    "srpe_phase_name": candidate.get("phase_name_en") or candidate.get("phase_name_zh"),
                    "srpe_phase_no": candidate.get("phase_no"),
                    "srpe_address_en": candidate.get("address_en"),
                    "match_method": method,
                    "match_confidence": confidence,
                    "match_status": status,
                    "candidate_count": candidate_count,
                    "ownership_status": "not_verified",
                    "matched_at": annual.get("fetched_at") or datetime.now(timezone.utc).isoformat(),
                }
            )
    return pd.DataFrame(rows, columns=ANNUAL_SRPE_CROSSWALK_COLUMNS)


def build_shkp_pipeline_srpe_crosswalk(
    pipeline_disclosures: pd.DataFrame,
    srpe_index: pd.DataFrame,
) -> pd.DataFrame:
    """Build a conservative crosswalk for future/under-development labels.

    SHKP interim-result disclosures use descriptive labels such as
    ``Cullinan Harbour Phase 2`` or ``Tsuen Wan West project``.  They are
    useful pipeline evidence, but are not stable legal project IDs.  This
    function therefore retains every name/phase/geography candidate and
    always leaves ownership as ``not_verified``.  A single candidate is still
    ``matched_needs_review``; multiple candidates are ``ambiguous`` and an
    unmatched disclosure is retained as a review row with a null SRPE ID.
    """
    rows: list[dict[str, Any]] = []
    srpe_records = srpe_index.to_dict("records") if not srpe_index.empty else []

    def _pipeline_candidates(label: str, geography: str) -> dict[str, tuple[dict[str, Any], set[str]]]:
        label_norm = _normalized_name(label)
        base_label = re.split(r"\bphases?\b", label, maxsplit=1, flags=re.IGNORECASE)[0]
        base_norm = _normalized_name(base_label)
        geography_norm = _normalized_name(geography)
        candidates: dict[str, tuple[dict[str, Any], set[str]]] = {}
        for candidate in srpe_records:
            identifier = str(candidate.get("development_id") or "").strip()
            if not identifier:
                continue
            methods: set[str] = set()
            name_values = [
                candidate.get("display_name"),
                candidate.get("development_name_en"),
                candidate.get("phase_name_en"),
                candidate.get("phase_name_zh"),
            ]
            name_norms = {
                _normalized_name(value)
                for value in name_values
                if _normalized_name(value)
            }
            if label_norm and label_norm in name_norms:
                methods.add("name_exact")
            if base_norm and any(
                base_norm == value or (len(base_norm) >= 8 and base_norm in value)
                for value in name_norms
            ):
                methods.add("base_name_candidate")
            if _phase_qualified_candidate_match(label, candidate):
                methods.add("phase_name_candidate")
            name_anchor = bool(
                {"name_exact", "base_name_candidate", "phase_name_candidate"} & methods
            )
            planning_area = _normalized_name(candidate.get("planning_area_en"))
            candidate_address = _normalized_address(candidate.get("address_en"))
            if name_anchor and geography_norm and (
                geography_norm == planning_area
                or (len(geography_norm) >= 6 and geography_norm in planning_area)
                or (candidate_address and geography_norm in candidate_address)
            ):
                methods.add("geography_candidate")
            # Geography alone is deliberately not an identity key.  Broad
            # areas such as Sha Tin, Tsuen Wan and Yuen Long contain many
            # unrelated SRPE phases; retaining them as candidates would turn
            # a descriptive disclosure into a false many-to-many join.
            if name_anchor:
                candidates[identifier] = (candidate, methods)

        # A phase-qualified disclosure must not inherit a same-name Phase 1
        # row just because the development name/domain is shared.
        requested_phases = _phase_tokens(label)
        if requested_phases:
            compatible: dict[str, tuple[dict[str, Any], set[str]]] = {}
            for identifier, (candidate, methods) in candidates.items():
                if "phase_name_candidate" in methods:
                    compatible[identifier] = (candidate, methods)
            candidates = compatible
        return candidates

    for disclosure in pipeline_disclosures.to_dict("records"):
        label = str(disclosure.get("project_label") or "").strip()
        geography = str(disclosure.get("geography") or "").strip()
        evidence_status = str(disclosure.get("evidence_status") or "").strip().lower()
        label_norm = _normalized_name(label)
        evidence_key = hashlib.sha256(
            "|".join(
                str(disclosure.get(field) or "").strip()
                for field in ("disclosure_id", "publication_date", "project_label", "status", "source_url")
            ).encode("utf-8")
        ).hexdigest()
        # A missing phrase is an observation about source drift, not evidence
        # that the project was cancelled.  Keep it in the audit queue without
        # attempting a stale name-to-phase match.
        candidates = _pipeline_candidates(label, geography) if evidence_status == "found" else {}
        # A commercial/BOT label is deliberately not matched to SRPE.  Keep a
        # visible registry row, but make the non-applicability explicit so the
        # downstream future-resolution plan can route it to a commercial asset
        # registry rather than treating it as a residential identity gap.
        commercial_scope = SHKP_NON_SRPE_COMMERCIAL_LABELS.get(label_norm)
        if commercial_scope:
            candidates = {}
        # Lot/address evidence resolved two descriptive interim labels to a
        # single SRPE phase.  Keep the result as a conservative review match;
        # ownership remains explicitly unverified until a legal effective
        # interval is available.
        if evidence_status == "found" and not candidates and not commercial_scope:
            alias_ids = SHKP_PIPELINE_SRPE_ALIAS_HINTS.get(label_norm, ())
            if alias_ids:
                candidates = {
                    str(candidate.get("development_id")): (
                        candidate,
                        {"official_lot_address_alias"},
                    )
                    for candidate in srpe_records
                    if str(candidate.get("development_id") or "") in set(alias_ids)
                }
        candidate_count = len(candidates)
        if evidence_status != "found":
            candidates = {"": ({}, {"not_evaluated"})}
        elif not candidates:
            candidates = {"": ({}, {"none"})}
        for identifier, (candidate, methods) in candidates.items():
            if evidence_status != "found":
                status, confidence, method = "not_evaluated", "not_evaluated", "not_evaluated"
            elif commercial_scope and not identifier:
                status, confidence, method = "not_applicable_non_srpe", "not_applicable", "explicit_commercial_label"
            elif not identifier:
                status, confidence, method = "unmatched", "unmatched", "none"
            elif candidate_count > 1:
                status, confidence = "ambiguous", "low"
                method = "+".join(sorted(methods))
            else:
                status = "matched_needs_review"
                confidence = "high" if {"name_exact", "phase_name_candidate"} <= methods else "medium"
                method = "+".join(sorted(methods))
            rows.append(
                {
                    "pipeline_evidence_key": evidence_key,
                    "disclosure_id": disclosure.get("disclosure_id"),
                    "disclosure_type": disclosure.get("disclosure_type"),
                    "project_label": label or None,
                    "pipeline_status": disclosure.get("status"),
                    "geography": geography or None,
                    "publication_date": disclosure.get("publication_date"),
                    "evidence_status": disclosure.get("evidence_status"),
                    "evidence_context": disclosure.get("evidence_context"),
                    "source_url": disclosure.get("source_url"),
                    "srpe_development_id": identifier or None,
                    "srpe_development_name": candidate.get("development_name_en") or candidate.get("display_name"),
                    "srpe_phase_name": candidate.get("phase_name_en") or candidate.get("phase_name_zh"),
                    "srpe_phase_no": candidate.get("phase_no"),
                    "srpe_address_en": candidate.get("address_en"),
                    "match_method": method,
                    "match_confidence": confidence,
                    "match_status": status,
                    "candidate_count": candidate_count,
                    "ownership_status": "not_verified",
                    "matched_at": disclosure.get("fetched_at") or datetime.now(timezone.utc).isoformat(),
                }
            )
    return pd.DataFrame(rows, columns=PIPELINE_SRPE_CROSSWALK_COLUMNS)


def build_shkp_pipeline_project_registry(
    pipeline_crosswalk: pd.DataFrame | None = None,
    annual_srpe_crosswalk: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Materialise an evidence-only registry for future/under-development labels.

    The SRPE phase registry is intentionally keyed by a public development ID.
    SHKP disclosures also contain useful labels which do not yet have such an
    ID (for example a project near a future MTR station).  Dropping those rows
    would make the project universe look smaller than the official evidence;
    promoting them into the SRPE registry would be equally misleading.  This
    layer keeps one row per dated pipeline/annual evidence item, aggregates all
    SRPE candidates, and leaves ownership and sales ingestion explicitly
    blocked.
    """
    pipeline = pipeline_crosswalk if pipeline_crosswalk is not None else pd.DataFrame()
    annual = annual_srpe_crosswalk if annual_srpe_crosswalk is not None else pd.DataFrame()
    if pipeline.empty and annual.empty:
        return pd.DataFrame(columns=SHKP_PIPELINE_PROJECT_REGISTRY_COLUMNS)

    def _text(value: Any) -> str:
        return str(value or "").strip()

    def _unique(values: Iterable[Any]) -> list[str]:
        return list(dict.fromkeys(_text(value) for value in values if _text(value)))

    def _status(values: Iterable[Any]) -> str:
        statuses = set(_unique(values))
        for candidate in ("ambiguous", "matched_needs_review", "matched", "not_applicable_non_srpe", "unmatched", "not_evaluated"):
            if candidate in statuses:
                return candidate
        return "not_observed"

    rows: list[dict[str, Any]] = []

    if not pipeline.empty:
        for evidence_key, group in pipeline.groupby("pipeline_evidence_key", dropna=False, sort=False):
            records = group.to_dict("records")
            first = records[0]
            candidate_ids = _unique(record.get("srpe_development_id") for record in records)
            candidate_names = _unique(record.get("srpe_development_name") for record in records)
            candidate_phases = _unique(record.get("srpe_phase_name") for record in records)
            candidate_counts = pd.to_numeric(
                pd.Series([record.get("candidate_count") for record in records]),
                errors="coerce",
            ).dropna()
            rows.append(
                {
                    "pipeline_registry_key": f"pipeline:{_text(evidence_key)}",
                    "project_label": _text(first.get("project_label")) or None,
                    "project_state": _text(first.get("pipeline_status")) or None,
                    "geography": _text(first.get("geography")) or None,
                    "disclosure_id": _text(first.get("disclosure_id")) or None,
                    "disclosure_type": _text(first.get("disclosure_type")) or None,
                    "publication_date": _text(first.get("publication_date")) or None,
                    "evidence_status": _text(first.get("evidence_status")) or None,
                    "evidence_context": _text(first.get("evidence_context")) or None,
                    "source_url": _text(first.get("source_url")) or None,
                    "annual_report_id": None,
                    "annual_report_period_end": None,
                    "annual_evidence_type": None,
                    "annual_document_url": None,
                    "annual_page_number": None,
                    "annual_group_interest_raw": None,
                    "annual_group_interest_pct": None,
                    "srpe_candidate_ids": " | ".join(candidate_ids) or None,
                    "srpe_candidate_names": " | ".join(candidate_names) or None,
                    "srpe_candidate_phase_names": " | ".join(candidate_phases) or None,
                    "srpe_match_status": _status(record.get("match_status") for record in records),
                    "srpe_candidate_count": int(max(candidate_counts)) if not candidate_counts.empty else len(candidate_ids),
                    "ownership_status": "not_verified",
                    "sales_ingestion_status": "not_ready",
                    "last_verified_at": max(
                        _unique(record.get("matched_at") for record in records),
                        default=datetime.now(timezone.utc).isoformat(),
                    ),
                }
            )

    if not annual.empty:
        group_columns = [
            column for column in ("report_id", "report_period_end", "evidence_type", "project_label")
            if column in annual.columns
        ]
        for group_key, group in annual.groupby(group_columns, dropna=False, sort=False):
            records = group.to_dict("records")
            first = records[0]
            if not isinstance(group_key, tuple):
                group_key = (group_key,)
            key_payload = "|".join(_text(value) for value in group_key)
            evidence_key = hashlib.sha256(f"annual|{key_payload}".encode("utf-8")).hexdigest()
            candidate_ids = _unique(record.get("srpe_development_id") for record in records)
            candidate_names = _unique(record.get("srpe_development_name") for record in records)
            candidate_phases = _unique(record.get("srpe_phase_name") for record in records)
            annual_interest = _unique(record.get("annual_group_interest_raw") for record in records)
            annual_pct = pd.to_numeric(
                pd.Series([record.get("annual_group_interest_pct") for record in records]),
                errors="coerce",
            ).dropna()
            rows.append(
                {
                    "pipeline_registry_key": f"annual:{evidence_key}",
                    "project_label": _text(first.get("project_label")) or None,
                    "project_state": _text(first.get("project_state")) or None,
                    "geography": _text(first.get("geography")) or _text(first.get("annual_location")) or None,
                    "disclosure_id": None,
                    "disclosure_type": None,
                    # The annual crosswalk exposes the report period end, not
                    # the PDF publication timestamp.  Do not relabel an
                    # accounting period as a publication date.
                    "publication_date": None,
                    "evidence_status": "found",
                    "evidence_context": None,
                    "source_url": _text(first.get("annual_document_url")) or None,
                    "annual_report_id": _text(first.get("report_id")) or None,
                    "annual_report_period_end": _text(first.get("report_period_end")) or None,
                    "annual_evidence_type": _text(first.get("evidence_type")) or None,
                    "annual_document_url": _text(first.get("annual_document_url")) or None,
                    "annual_page_number": _text(first.get("annual_page_number")) or None,
                    "annual_group_interest_raw": " | ".join(annual_interest) or None,
                    # Keep this evidence field string-typed: a report can
                    # contain one numeric percentage in one row and several
                    # candidate percentages in another.  Mixing floats and
                    # JSON strings makes Arrow inference fail at persistence.
                    "annual_group_interest_pct": (
                        str(float(annual_pct.iloc[0])) if len(annual_pct) == 1 else (
                            json.dumps([float(value) for value in annual_pct.tolist()], ensure_ascii=False)
                            if not annual_pct.empty else None
                        )
                    ),
                    "srpe_candidate_ids": " | ".join(candidate_ids) or None,
                    "srpe_candidate_names": " | ".join(candidate_names) or None,
                    "srpe_candidate_phase_names": " | ".join(candidate_phases) or None,
                    "srpe_match_status": _status(record.get("match_status") for record in records),
                    "srpe_candidate_count": len(candidate_ids),
                    "ownership_status": "not_verified",
                    "sales_ingestion_status": "not_ready",
                    "last_verified_at": max(
                        _unique(record.get("matched_at") for record in records),
                        default=datetime.now(timezone.utc).isoformat(),
                    ),
                }
            )

    result = pd.DataFrame(rows, columns=SHKP_PIPELINE_PROJECT_REGISTRY_COLUMNS)
    if not result.empty:
        # Keep interest evidence string-typed for parquet persistence: a
        # report can print a single numeric pct in one row and several
        # candidate pcts in another, and mixing plain numeric strings with
        # JSON-array strings makes pyarrow's pandas conversion attempt a
        # double cast and fail (e.g. "Could not convert '[2.0, 58.0]'").
        # A dedicated dtype pins the column as string regardless of values.
        result["annual_group_interest_pct"] = result["annual_group_interest_pct"].astype("string")
        result = result.sort_values("pipeline_registry_key", kind="stable").reset_index(drop=True)
    return result


def fetch_shkp_srpe_document_manifest(
    srpe_development_ids: Iterable[str | int],
    *,
    session: requests.Session | None = None,
    max_developments: int = 10,
    timeout: float = 30,
) -> pd.DataFrame:
    """Fetch bounded SRPE filing manifests for SHKP candidate development IDs.

    This is deliberately a metadata-only step: it calls the official SRPE
    ``getSelectedDevResult`` detail endpoint, archives each JSON response and
    emits real transaction-register/price-list/sales-arrangement/brochure
    filing rows with the download endpoint.  It does not download or parse
    PDFs, and it does not imply that a candidate is owned by SHKP.
    """
    if max_developments < 0:
        raise ValueError("max_developments must be non-negative")
    from .srpe import SRPE_API_BASE, SRPE_DOWNLOAD_ACTIONS

    client = session or requests.Session()
    client.headers.update({
        **DEFAULT_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://www.srpe.gov.hk",
        "Referer": "https://www.srpe.gov.hk/opip/",
    })
    detail_endpoint = f"{SRPE_API_BASE}/DevBldgSearch/getSelectedDevResult"
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = [detail_endpoint]
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    requested = 0
    for raw_id in srpe_development_ids:
        development_id = str(raw_id).strip()
        if not development_id or development_id in seen:
            continue
        if requested >= max_developments:
            break
        seen.add(development_id)
        requested += 1
        try:
            response = client.post(
                detail_endpoint,
                json={"timeStamp": int(time.time() * 1000), "devId": development_id},
                timeout=timeout,
            )
            response.raise_for_status()
            content = getattr(response, "content", b"")
            if isinstance(content, str):
                content = content.encode("utf-8")
            raw_path = save_raw_snapshot(
                "shkp_srpe_manifest",
                bytes(content),
                file_ext="json",
                source_url=detail_endpoint,
            )
            raw_snapshots.append(str(raw_path))
            body = response.json()
            detail = (body.get("resultData") or {}).get("devInfoResp") or {}
        except Exception as exc:
            skipped.append({"srpe_development_id": development_id, "reason": f"detail_fetch_error: {exc}"})
            continue

        dev = detail.get("dev") or {}
        addresses = dev.get("addresses") or []
        address = addresses[0].get("engAddress") if addresses else None
        metadata = {
            "srpe_development_id": development_id,
            "development_name": dev.get("engName"),
            "phase_name": dev.get("engPhaseName"),
            "phase_no": dev.get("engPhaseNo"),
            "development_address": address,
        }

        documents: list[tuple[str, dict[str, Any]]] = []
        documents.extend(("register_of_transactions", doc) for doc in detail.get("transactions") or [])
        documents.extend(("price_list", doc) for doc in detail.get("prices") or [])
        documents.extend(("sales_arrangement", doc) for doc in detail.get("salesArrangements") or [])
        brochures = detail.get("brochureList") or ([detail["brochure"]] if detail.get("brochure") else [])
        for brochure in brochures:
            for part in brochure.get("partFiles") or []:
                documents.append(("sales_brochure", {
                    "id": brochure.get("id"),
                    "serialNo": part.get("partNo"),
                    "dateOfPrinting": brochure.get("dateOfPrint"),
                    "file": part,
                }))

        for category, document in documents:
            file_info = document.get("file") or {}
            document_id = document.get("id") or file_info.get("id")
            if document_id is None:
                skipped.append({
                    "srpe_development_id": development_id,
                    "reason": f"missing_document_id:{category}",
                })
                continue
            download_endpoint = f"{SRPE_API_BASE}/download/{SRPE_DOWNLOAD_ACTIONS[category]}"
            if download_endpoint not in source_urls:
                source_urls.append(download_endpoint)
            rows.append({
                **metadata,
                "document_category": category,
                "document_id": str(document_id),
                "serial_no": document.get("serialNo"),
                "date_of_printing": document.get("dateOfPrinting"),
                "submission_time": file_info.get("submissionTime"),
                "file_name": file_info.get("fileName"),
                "file_size_bytes": file_info.get("fileSize"),
                "download_endpoint": download_endpoint,
                "detail_endpoint": detail_endpoint,
                "evidence_status": "manifest_document",
                "fetched_at": fetched_at,
            })

    frame = pd.DataFrame(rows, columns=SHKP_SRPE_MANIFEST_COLUMNS)
    if not frame.empty:
        frame = frame.drop_duplicates(
            subset=["srpe_development_id", "document_category", "document_id", "file_name"]
        ).reset_index(drop=True)
    frame.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        skipped_documents=skipped,
        lineage_metadata={
            "lineage_type": "official_srpe_candidate_manifest_fetch",
            "requested_developments": requested,
            "fetched_manifest_snapshots": len(raw_snapshots),
            "parsed_document_rows": int(len(frame)),
            "skipped_items": len(skipped),
            "pdf_downloaded": False,
            "ownership_inference": False,
        },
    )
    return frame


def build_shkp_planning_evidence_crosswalk(
    tpb_facts: pd.DataFrame,
    landsd_facts: pd.DataFrame,
    srpe_index: pd.DataFrame,
) -> pd.DataFrame:
    """Join parsed TPB/LandsD facts to SRPE candidates without attribution.

    The two planning sources do not publish a common developer ticker or SRPE
    ID.  This function only retains text/name/address candidates.  A single
    candidate is still ``matched_needs_review`` because lot/SPV and dated
    ownership evidence must be reviewed before it can enter the registry.
    """
    rows: list[dict[str, Any]] = []
    srpe_records = srpe_index.to_dict("records") if not srpe_index.empty else []

    def _candidate_rows(
        evidence_source: str,
        evidence: dict[str, Any],
    ) -> None:
        if evidence_source == "tpb":
            evidence_id = evidence.get("application_no")
            evidence_date = evidence.get("application_received_date")
            development_name = None
            location = evidence.get("location_raw")
            lot_no = None
            parent_or_developer = None
            source_url = evidence.get("detail_url")
            page_or_detail = source_url
            text_value = " ".join(str(evidence.get(key) or "") for key in ("location_raw", "proposal_raw"))
            evidence_status = evidence.get("evidence_status")
        else:
            evidence_id = f"{evidence.get('document_url')}#page={evidence.get('page_number')}"
            evidence_date = evidence.get("consent_or_approval_date")
            development_name = evidence.get("development_name_raw")
            location = None
            lot_no = evidence.get("lot_no_raw")
            parent_or_developer = evidence.get("parent_or_holding_company_or_developer_raw")
            source_url = evidence.get("document_url")
            # Keep this cross-source lineage field homogeneous for Parquet:
            # TPB carries a detail URL while LandsD carries a numeric page.
            page_or_detail = f"page={evidence.get('page_number')}"
            text_value = " ".join(str(evidence.get(key) or "") for key in (
                "development_name_raw",
                "lot_no_raw",
                "parent_or_holding_company_or_developer_raw",
            ))
            evidence_status = "parsed_pdf_row"

        text_norm = _normalized_name(text_value)
        location_norm = _normalized_address(location)
        candidates: dict[str, tuple[dict[str, Any], set[str]]] = {}
        for candidate in srpe_records:
            identifier = str(candidate.get("development_id") or "")
            if not identifier:
                continue
            methods: set[str] = set()
            for value in (
                candidate.get("display_name"),
                candidate.get("development_name_en"),
                candidate.get("phase_name_en"),
            ):
                normalized = _normalized_name(value)
                if normalized and len(normalized) >= 8 and normalized in text_norm:
                    methods.add("name_contains")
            candidate_address = _normalized_address(candidate.get("address_en"))
            if candidate_address and len(candidate_address) >= 8 and (
                candidate_address in text_norm or (location_norm and candidate_address in location_norm)
            ):
                methods.add("address_contains")
            if methods:
                candidates[identifier] = (candidate, methods)

        # A bounded legal-lot hint is stronger than a missing/unstable
        # project-name parse (notably Garden Regency, which is emitted as
        # ``Unknown`` in the current Yuen Long PDF).  Restrict the candidate
        # set to the audited phase IDs so this cannot widen a row into a
        # geography-only or fuzzy name match.
        lot_norm = _normalized_name(lot_no)
        lot_hint_ids: set[str] = set()
        for lot_hint, identifiers in SHKP_PLANNING_SRPE_LOT_HINTS.items():
            if lot_hint and lot_hint in lot_norm:
                lot_hint_ids.update(identifiers)
        if lot_hint_ids:
            # When the official development name includes an explicit phase,
            # narrow a shared-lot bridge to that phase.  Check longer tokens
            # first so ``phase2a`` is not consumed as generic ``phase2``.
            phase_hint_ids: set[str] = set()
            for lot_hint, phase_hints in SHKP_PLANNING_SRPE_PHASE_HINTS.items():
                if lot_hint not in lot_norm:
                    continue
                for phase_token, identifiers in sorted(
                    phase_hints.items(), key=lambda item: len(item[0]), reverse=True
                ):
                    if phase_token in text_norm:
                        phase_hint_ids.update(identifiers)
            if phase_hint_ids:
                lot_hint_ids &= phase_hint_ids
            hinted_candidates: dict[str, tuple[dict[str, Any], set[str]]] = {}
            for candidate in srpe_records:
                identifier = str(candidate.get("development_id") or "")
                if identifier not in lot_hint_ids:
                    continue
                prior_methods = candidates.get(identifier, ({}, set()))[1]
                hinted_candidates[identifier] = (
                    candidate,
                    {*prior_methods, "lot_hint_exact"},
                )
            if hinted_candidates:
                candidates = hinted_candidates

        candidate_count = len(candidates)
        if not candidates:
            candidates = {"": ({}, {"none"})}
        for identifier, (candidate, methods) in candidates.items():
            if not identifier:
                match_status, confidence, method = "unmatched", "unmatched", "none"
            elif candidate_count > 1:
                match_status, confidence = "ambiguous", "low"
                method = "+".join(sorted(methods))
            else:
                match_status, confidence = "matched_needs_review", "medium"
                method = "+".join(sorted(methods))
            rows.append({
                "evidence_source": evidence_source,
                "evidence_record_id": evidence_id,
                "evidence_date": evidence_date,
                "evidence_status": evidence_status,
                "development_name_raw": development_name,
                "location_raw": location,
                "lot_no_raw": lot_no,
                "parent_or_developer_raw": parent_or_developer,
                "source_url": source_url,
                "page_or_detail": page_or_detail,
                "srpe_development_id": identifier or None,
                "srpe_development_name": candidate.get("development_name_en") or candidate.get("display_name"),
                "srpe_phase_name": candidate.get("phase_name_en") or candidate.get("phase_name_zh"),
                "srpe_address_en": candidate.get("address_en"),
                "match_method": method,
                "match_confidence": confidence,
                "match_status": match_status,
                "candidate_count": candidate_count,
                "planning_consent_date": evidence_date,
                "ownership_status": "not_verified",
                "matched_at": datetime.now(timezone.utc).isoformat(),
            })

    for evidence in tpb_facts.to_dict("records") if not tpb_facts.empty else []:
        _candidate_rows("tpb", evidence)
    for evidence in landsd_facts.to_dict("records") if not landsd_facts.empty else []:
        _candidate_rows("landsd", evidence)
    return pd.DataFrame(rows, columns=PLANNING_EVIDENCE_CROSSWALK_COLUMNS)


def build_shkp_legal_ownership_observations(
    srpe_index: pd.DataFrame,
) -> pd.DataFrame:
    """Materialise dated legal-SPV ownership observations for audited phases.

    These rows are deliberately observations, not intervals.  The official
    annual-report subsidiary tables prove the SPV's numeric attributable
    equity interest *as at* a reporting date; they do not prove when that
    interest became effective or that it was uninterrupted.  Consequently
    every row remains ``blocked_effective_interval`` and cannot set
    ``ownership_attribution_ready``.
    """
    if srpe_index.empty:
        return pd.DataFrame(columns=SHKP_LEGAL_OWNERSHIP_OBSERVATION_COLUMNS)
    srpe_by_id = {
        str(record.get("development_id") or ""): record
        for record in srpe_index.to_dict("records")
        if str(record.get("development_id") or "").strip()
    }
    srpe_source_url = (
        str(srpe_index.attrs.get("source_urls", ["https://www.srpe.gov.hk/opip/all_development"])[0])
        if srpe_index.attrs.get("source_urls")
        else "https://www.srpe.gov.hk/opip/all_development"
    )
    rows: list[dict[str, Any]] = []
    for spec in SHKP_LEGAL_OWNERSHIP_OBSERVATION_SPECS:
        for development_id in spec["srpe_development_ids"]:
            srpe = srpe_by_id.get(str(development_id))
            if not srpe:
                continue
            for observation in spec["observations"]:
                    ownership_url = str(observation["url"])
                    supplemental_urls = [
                        str(url)
                        for url in observation.get("supplemental_source_urls", ())
                        if str(url).strip()
                    ]
                    source_urls = [
                        ownership_url,
                        str(spec["phase_identity_source_url"]),
                        srpe_source_url,
                        *supplemental_urls,
                    ]
                    ownership_pct = observation.get("ownership_pct", 100.0)
                    evidence_status = observation.get("evidence_status", "numeric_spv_snapshot")
                    caveat = observation.get("caveat") or (
                        "Official source proves 100% subsidiary equity interest as at the stated date; "
                        "no continuous effective-from/effective-to interval is established."
                    )
                    rows.append(
                    {
                        "observation_id": f"{development_id}:{observation['as_of']}:{observation['type']}",
                        "srpe_development_id": str(development_id),
                        "srpe_development_name": srpe.get("development_name_en") or srpe.get("display_name"),
                        "srpe_phase_name": srpe.get("phase_name_en"),
                        "listed_parent": "Sun Hung Kai Properties Limited",
                        "stock_code": "0016",
                        "subsidiary_spv_name": spec["spv"],
                        "ownership_pct": ownership_pct,
                        "ownership_observed_as_of": observation["as_of"],
                        "effective_from": None,
                        "effective_to": None,
                        "legally_continuous": False,
                        "interval_blocker": (
                            "grouped_phase_or_project_snapshot"
                            if evidence_status in {
                                "numeric_grouped_project_snapshot",
                                "numeric_lot_bridged_project_snapshot",
                                "numeric_address_bridged_project_snapshot",
                            }
                            else "presentation_snapshot_no_effective_dates"
                            if evidence_status == "numeric_phase_stake_snapshot"
                            else "parent_company_observation_no_numeric_pct"
                            if evidence_status == "parent_company_observation"
                            else "reporting_date_snapshot_no_effective_dates"
                        ),
                        "observation_type": observation["type"],
                        "evidence_status": evidence_status,
                        "ownership_source_url": ownership_url,
                        "ownership_source_page": observation["page"],
                        "phase_identity_source_url": spec["phase_identity_source_url"],
                        "srpe_source_url": srpe_source_url,
                        "promotion_status": "blocked_effective_interval",
                        "caveat": caveat,
                        "source_urls_json": json.dumps(source_urls, ensure_ascii=False),
                        "last_verified_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
    frame = pd.DataFrame(rows, columns=SHKP_LEGAL_OWNERSHIP_OBSERVATION_COLUMNS)
    raw_path = save_raw_snapshot(
        "shkp_legal_ownership_observations",
        frame.to_json(orient="records", force_ascii=False),
        file_ext="json",
        source_url="static://shkp-legal-ownership-observations",
    )
    frame.attrs.update(
        raw_snapshot=str(raw_path),
        raw_snapshots=[str(raw_path)],
        source_urls=sorted({url for row in rows for url in json.loads(row["source_urls_json"])}),
        lineage_metadata={
            "lineage_type": "static_official_legal_spv_ownership_observations",
            "observation_rows": int(len(frame)),
            "phase_count": int(frame["srpe_development_id"].nunique()) if not frame.empty else 0,
            "ownership_inference": False,
            "promotion_policy": "numeric snapshots require effective interval before sales attribution",
        },
    )
    return frame


def build_shkp_land_registry_evidence(
    records: pd.DataFrame | Iterable[Mapping[str, Any]] | None,
    *,
    last_verified_at: str | None = None,
) -> pd.DataFrame:
    """Normalize manual IRIS/Land Registry records without promoting them.

    Land Registry records describe registered title, memorial instruments and
    lot shares.  They do not, by themselves, establish a listed parent's
    attributable economic percentage or a continuous phase-level interval.
    This function therefore preserves explicitly supplied dates/percentages
    for review but forces ``legally_continuous=False`` and a blocked promotion
    status.  The output is intentionally separate from
    ``shkp_legal_ownership_observations``; an operator must reconcile SPV/JV
    evidence before any interval can enter the sales gate.
    """
    if records is None:
        return pd.DataFrame(columns=SHKP_LAND_REGISTRY_EVIDENCE_COLUMNS)
    frame = records.copy() if isinstance(records, pd.DataFrame) else pd.DataFrame(records)
    if frame.empty:
        return pd.DataFrame(columns=SHKP_LAND_REGISTRY_EVIDENCE_COLUMNS)

    def _text(value: Any) -> str | None:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        value = str(value).strip()
        return value or None

    def _date(value: Any, field: str) -> str | None:
        text = _text(value)
        if not text:
            return None
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            raise ValueError(f"{field} contains an invalid date: {text!r}")
        return parsed.date().isoformat()

    verified_at = last_verified_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for raw in frame.to_dict("records"):
        lot_no = _text(raw.get("lot_no"))
        memorial_no = _text(raw.get("memorial_no"))
        instrument_type = _text(raw.get("instrument_type"))
        instrument_date = _date(raw.get("instrument_date"), "instrument_date")
        if not lot_no:
            raise ValueError("Land Registry evidence requires lot_no")
        if not memorial_no and not instrument_date:
            raise ValueError("Land Registry evidence requires memorial_no or instrument_date")
        source_url = _text(raw.get("source_url"))
        source_document = _text(raw.get("source_document"))
        source_order_reference = _text(raw.get("source_order_reference"))
        if not any((source_url, source_document, source_order_reference)):
            raise ValueError("Land Registry evidence requires a source URL, document, or order reference")

        pct_value = raw.get("ownership_pct")
        pct = None if pct_value is None or _text(pct_value) is None else pd.to_numeric(pct_value, errors="coerce")
        if pct is not None and (pd.isna(pct) or not 0 <= float(pct) <= 100):
            raise ValueError("ownership_pct must be numeric and between 0 and 100")

        identity = "|".join(
            value or ""
            for value in (
                lot_no,
                memorial_no,
                instrument_type,
                instrument_date,
                _text(raw.get("registered_owner")),
            )
        )
        evidence_id = _text(raw.get("evidence_id")) or f"landreg:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"
        rows.append(
            {
                "evidence_id": evidence_id,
                "srpe_development_id": _text(raw.get("srpe_development_id")),
                "lot_no": lot_no,
                "memorial_no": memorial_no,
                "instrument_type": instrument_type,
                "instrument_date": instrument_date,
                "registered_owner": _text(raw.get("registered_owner")),
                "owner_capacity": _text(raw.get("owner_capacity")),
                "registered_share": _text(raw.get("registered_share")),
                "consideration_hkd": pd.to_numeric(raw.get("consideration_hkd"), errors="coerce"),
                "source_url": source_url,
                "source_document": source_document,
                "source_order_reference": source_order_reference,
                "date_semantics": _text(raw.get("date_semantics")) or "land_registry_instrument_date",
                "phase_match_status": _text(raw.get("phase_match_status")) or "not_evaluated",
                "legal_interest_type": _text(raw.get("legal_interest_type")) or "registered_title",
                "ownership_pct": float(pct) if pct is not None and pd.notna(pct) else None,
                # Never infer effective dates from an instrument date.
                "effective_from": _date(raw.get("effective_from"), "effective_from"),
                "effective_to": _date(raw.get("effective_to"), "effective_to"),
                "legally_continuous": False,
                "promotion_status": "blocked_land_registry_owner_only",
                "caveat": _text(raw.get("caveat")) or (
                    "Registered-title evidence is not SHKP attributable economic ownership; "
                    "reconcile SPV/JV, phase identity and effective interval separately."
                ),
                "last_verified_at": verified_at,
            }
        )
    result = pd.DataFrame(rows, columns=SHKP_LAND_REGISTRY_EVIDENCE_COLUMNS)
    result.attrs.update(
        lineage_metadata={
            "lineage_type": "manual_iris_land_registry_evidence",
            "evidence_rows": len(result),
            "ownership_inference": False,
            "sales_promotion": False,
            "promotion_policy": "registered title never promotes SHKP attribution without separate approved SPV/JV evidence",
        }
    )
    result.attrs["source_urls"] = [
        value for value in result["source_url"].dropna().astype(str).unique().tolist() if value
    ]
    return result


def build_shkp_phase_attribution_decisions(
    records: pd.DataFrame | Iterable[Mapping[str, Any]] | None,
    *,
    last_verified_at: str | None = None,
) -> pd.DataFrame:
    """Validate the separately reviewed layer that may open attribution.

    This function is intentionally manual and narrow.  An approved decision
    must cite phase-identity, economic-interest and title-chain evidence,
    provide a bounded numeric interval, a continuity basis, and reviewer
    sign-off.  It is the only output that carries the evidence type consumed
    by the registry interval gate.
    """
    if records is None:
        return pd.DataFrame(columns=SHKP_PHASE_ATTRIBUTION_DECISION_COLUMNS)
    frame = records.copy() if isinstance(records, pd.DataFrame) else pd.DataFrame(records)
    if frame.empty:
        return pd.DataFrame(columns=SHKP_PHASE_ATTRIBUTION_DECISION_COLUMNS)

    def _text(value: Any) -> str | None:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        text = str(value).strip()
        return text or None

    def _date(value: Any, field: str) -> str | None:
        text = _text(value)
        if not text:
            return None
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            raise ValueError(f"{field} contains an invalid date: {text!r}")
        return parsed.date().isoformat()

    def _evidence_ids(value: Any, field: str, *, required: bool) -> str | None:
        text = _text(value)
        ids = [item.strip() for item in (text or "").split("|") if item.strip()]
        if required and not ids:
            raise ValueError(f"approved phase attribution requires {field}")
        return " | ".join(dict.fromkeys(ids)) or None

    verified_at = last_verified_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for raw in frame.to_dict("records"):
        decision_id = _text(raw.get("decision_id"))
        srpe_id = _text(raw.get("srpe_development_id"))
        if not decision_id or not srpe_id:
            raise ValueError("phase attribution decision requires decision_id and srpe_development_id")
        status = (_text(raw.get("decision_status")) or "blocked_review").lower()
        if status not in {"approved", "blocked_review", "rejected"}:
            raise ValueError("decision_status must be approved, blocked_review, or rejected")
        pct = pd.to_numeric(raw.get("ownership_pct"), errors="coerce")
        if status == "approved":
            if pd.isna(pct) or not 0 <= float(pct) <= 100:
                raise ValueError("approved phase attribution requires ownership_pct between 0 and 100")
        elif pd.notna(pct) and not 0 <= float(pct) <= 100:
            raise ValueError("ownership_pct must be between 0 and 100 when supplied")
        start = _date(raw.get("effective_from"), "effective_from")
        end = _date(raw.get("effective_to"), "effective_to")
        if status == "approved":
            if not start or not end or start > end:
                raise ValueError("approved phase attribution requires a bounded effective interval")
            if (_text(raw.get("phase_identity_status")) or "").lower() != "matched":
                raise ValueError("approved phase attribution requires phase_identity_status=matched")
            for field in ("phase_identity_evidence_ids", "economic_evidence_ids", "title_chain_evidence_ids", "continuity_basis", "reviewer", "reviewed_at"):
                if not _text(raw.get(field)):
                    raise ValueError(f"approved phase attribution requires {field}")
        source_urls = _text(raw.get("source_urls_json")) or "[]"
        # Verify that a supplied source field is valid JSON rather than
        # persisting an un-auditable free-form string.
        try:
            parsed_urls = json.loads(source_urls)
            if not isinstance(parsed_urls, list):
                raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("source_urls_json must be a JSON list") from exc
        if status == "approved":
            valid_urls = [
                str(url).strip()
                for url in parsed_urls
                if isinstance(url, str) and str(url).strip()
            ]
            if not valid_urls:
                raise ValueError("approved phase attribution requires at least one source URL")
        rows.append(
            {
                "decision_id": decision_id,
                "srpe_development_id": srpe_id,
                "phase_label": _text(raw.get("phase_label")),
                "listed_parent": _text(raw.get("listed_parent")),
                "stock_code": _text(raw.get("stock_code")),
                "ownership_pct": float(pct) if pd.notna(pct) else None,
                "effective_from": start,
                "effective_to": end,
                "phase_identity_status": _text(raw.get("phase_identity_status")) or "not_evaluated",
                "phase_identity_evidence_ids": _evidence_ids(raw.get("phase_identity_evidence_ids"), "phase_identity_evidence_ids", required=status == "approved"),
                "economic_evidence_ids": _evidence_ids(raw.get("economic_evidence_ids"), "economic_evidence_ids", required=status == "approved"),
                "title_chain_evidence_ids": _evidence_ids(raw.get("title_chain_evidence_ids"), "title_chain_evidence_ids", required=status == "approved"),
                "continuity_basis": _text(raw.get("continuity_basis")),
                "reviewer": _text(raw.get("reviewer")),
                "reviewed_at": _date(raw.get("reviewed_at"), "reviewed_at"),
                "decision_status": status,
                "evidence_type": "approved_phase_attribution_decision" if status == "approved" else "phase_attribution_review_decision",
                "promotion_status": "approved_phase_attribution" if status == "approved" else "blocked_phase_attribution_review",
                "ownership_attribution_ready": status == "approved",
                "source_urls_json": source_urls,
                "caveat": _text(raw.get("caveat")) or "Manual review decision; do not overwrite the underlying source evidence.",
                "last_verified_at": verified_at,
            }
        )
    result = pd.DataFrame(rows, columns=SHKP_PHASE_ATTRIBUTION_DECISION_COLUMNS)
    result.attrs.update(
        lineage_metadata={
            "lineage_type": "manual_phase_attribution_decision",
            "decision_rows": len(result),
            "approved_rows": int(result["ownership_attribution_ready"].sum()),
            "promotion_policy": "only approved phase attribution decisions may feed the interval gate",
        }
    )
    result.attrs["source_urls"] = sorted({
        url
        for value in result["source_urls_json"].tolist()
        for url in json.loads(value)
        if url
    })
    return result


def build_shkp_ownership_evidence_timeline(
    *,
    legal_ownership_observations: pd.DataFrame | None = None,
    annual_principal_subsidiary_crosswalk: pd.DataFrame | None = None,
    annual_srpe_crosswalk: pd.DataFrame | None = None,
    completion_schedule_crosswalk: pd.DataFrame | None = None,
    planning_evidence_crosswalk: pd.DataFrame | None = None,
    pipeline_crosswalk: pd.DataFrame | None = None,
    site_vendor_crosswalk: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Materialize date-semantics-aware project ownership evidence.

    This is a review timeline, not an ownership interval table.  It brings
    together the dated facts already parsed by the source-specific layers but
    keeps ``ownership_observed_as_of``, ``annual_report_period_end``,
    ``completion_schedule_as_of``, regulatory consent dates, disclosure dates
    and project-site material dates distinct.  No row can set an effective
    ownership interval or open the attributable-sales gate.
    """
    frames = {
        "legal_spv": legal_ownership_observations if legal_ownership_observations is not None else pd.DataFrame(),
        "annual_principal_subsidiary": annual_principal_subsidiary_crosswalk if annual_principal_subsidiary_crosswalk is not None else pd.DataFrame(),
        "annual_report": annual_srpe_crosswalk if annual_srpe_crosswalk is not None else pd.DataFrame(),
        "completion_schedule": completion_schedule_crosswalk if completion_schedule_crosswalk is not None else pd.DataFrame(),
        "planning": planning_evidence_crosswalk if planning_evidence_crosswalk is not None else pd.DataFrame(),
        "pipeline_disclosure": pipeline_crosswalk if pipeline_crosswalk is not None else pd.DataFrame(),
        "project_site": site_vendor_crosswalk if site_vendor_crosswalk is not None else pd.DataFrame(),
    }
    rows: list[dict[str, Any]] = []

    def _text(value: Any) -> str | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        value = str(value).strip()
        return value or None

    def _date(value: Any) -> str | None:
        text = _text(value)
        if not text:
            return None
        parsed = pd.to_datetime(text, errors="coerce")
        return parsed.date().isoformat() if pd.notna(parsed) else None

    def _number(value: Any) -> float | None:
        parsed = pd.to_numeric(value, errors="coerce")
        return float(parsed) if pd.notna(parsed) else None

    def _append(
        record: dict[str, Any],
        *,
        source_layer: str,
        event_date: Any,
        date_semantics: str,
        event_type: str,
        evidence_level: str,
        promotion_status: str,
        source_url: Any,
        source_page_or_detail: Any = None,
        subsidiary_spv_name: Any = None,
        vendor_name: Any = None,
        holding_companies: Any = None,
        ownership_pct_observed: Any = None,
        ownership_raw: Any = None,
        evidence_context: Any = None,
        source_key: Any = None,
    ) -> None:
        phase_id = _text(record.get("srpe_development_id"))
        observed_date = _date(event_date)
        if not phase_id or not observed_date:
            return
        key = "|".join(
            str(value or "")
            for value in (source_layer, phase_id, observed_date, event_type, source_key, source_url)
        )
        rows.append(
            {
                "timeline_id": hashlib.sha1(key.encode("utf-8")).hexdigest(),
                "srpe_development_id": phase_id,
                "srpe_development_name": _text(record.get("srpe_development_name")),
                "srpe_phase_name": _text(record.get("srpe_phase_name")),
                "event_date": observed_date,
                "date_semantics": date_semantics,
                "event_type": event_type,
                "source_layer": source_layer,
                "subsidiary_spv_name": _text(subsidiary_spv_name),
                "vendor_name": _text(vendor_name),
                "holding_companies": _text(holding_companies),
                "ownership_pct_observed": _number(ownership_pct_observed),
                "ownership_raw": _text(ownership_raw),
                "evidence_level": evidence_level,
                "effective_from": None,
                "effective_to": None,
                "promotion_status": promotion_status,
                "source_url": _text(source_url),
                "source_page_or_detail": _text(source_page_or_detail),
                "evidence_context": _text(evidence_context),
                "last_verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    for record in frames["legal_spv"].to_dict("records"):
        evidence_status = _text(record.get("evidence_status")) or "numeric_spv_snapshot"
        numeric_snapshot = evidence_status == "numeric_spv_snapshot"
        ownership_pct = record.get("ownership_pct")
        _append(
            record,
            source_layer="legal_spv",
            event_date=record.get("ownership_observed_as_of"),
            date_semantics="ownership_observed_as_of",
            event_type=_text(record.get("observation_type")) or "legal_spv_observation",
            evidence_level=("numeric_spv_snapshot" if numeric_snapshot else "official_parent_company_observation"),
            promotion_status=_text(record.get("promotion_status")) or "blocked_effective_interval",
            source_url=record.get("ownership_source_url"),
            source_page_or_detail=record.get("ownership_source_page"),
            subsidiary_spv_name=record.get("subsidiary_spv_name"),
            ownership_pct_observed=ownership_pct,
            ownership_raw=(
                f"{ownership_pct}% as at {record.get('ownership_observed_as_of')}"
                if ownership_pct is not None
                else f"parent company observed as at {record.get('ownership_observed_as_of')}"
            ),
            evidence_context=record.get("caveat"),
            source_key=record.get("observation_id"),
        )

    for record in frames["annual_principal_subsidiary"].to_dict("records"):
        pct = _number(record.get("attributable_equity_pct"))
        pct_text = f"{pct:g}%" if pct is not None else "not reported"
        match_status = _text(record.get("match_status")) or "unmatched_entity_only"
        promotion = (
            "blocked_phase_group_ambiguous"
            if "ambiguous" in match_status
            else "blocked_spv_reconciliation"
        )
        _append(
            record,
            source_layer="annual_principal_subsidiary",
            event_date=record.get("as_of_date") or record.get("report_period_end"),
            date_semantics="annual_principal_subsidiary_as_of",
            event_type="annual_principal_subsidiary_snapshot",
            evidence_level="official_annual_principal_subsidiary_snapshot",
            promotion_status=promotion,
            source_url=record.get("annual_document_url") or record.get("source_url"),
            source_page_or_detail=record.get("printed_page") or record.get("annual_pdf_page"),
            subsidiary_spv_name=record.get("spv_name"),
            ownership_pct_observed=pct,
            ownership_raw=f"{pct_text} attributable equity interest as at {record.get('as_of_date') or record.get('report_period_end')}",
            evidence_context=(
                f"match_status={match_status}; "
                f"consistency={_text(record.get('annual_observation_consistency_status')) or 'not_comparable'}; "
                "Principal Subsidiaries is a material-subsidiary appendix, not a complete project/SPV inventory."
            ),
            source_key=record.get("crosswalk_id"),
        )

    for record in frames["annual_report"].to_dict("records"):
        raw = _text(record.get("annual_group_interest_raw"))
        promotion = "blocked_jv_unresolved" if (raw or "").upper() == "JV" else (
            "blocked_phase_group_ambiguous"
            if _text(record.get("match_status")) == "ambiguous"
            else "blocked_spv_reconciliation"
        )
        _append(
            record,
            source_layer="annual_report",
            event_date=record.get("report_period_end"),
            date_semantics="annual_report_period_end",
            event_type=_text(record.get("evidence_type")) or "annual_project_evidence",
            evidence_level="official_annual_report_group_interest",
            promotion_status=promotion,
            source_url=record.get("annual_document_url"),
            source_page_or_detail=record.get("annual_page_number"),
            ownership_pct_observed=record.get("annual_group_interest_pct"),
            ownership_raw=raw,
            evidence_context=record.get("srpe_phase_name") or record.get("srpe_development_name"),
            source_key=record.get("report_id"),
        )

    for record in frames["completion_schedule"].to_dict("records"):
        raw = _text(record.get("group_interest_raw"))
        match_status = _text(record.get("match_status"))
        promotion = "blocked_jv_unresolved" if (raw or "").upper() == "JV" else (
            "blocked_phase_group_ambiguous"
            if match_status == "ambiguous"
            else "blocked_spv_reconciliation"
        )
        _append(
            record,
            source_layer="completion_schedule",
            event_date=record.get("schedule_date"),
            date_semantics="completion_schedule_as_of",
            event_type="completion_schedule_group_interest",
            evidence_level="official_completion_schedule_group_interest",
            promotion_status=promotion,
            source_url=record.get("document_url") or record.get("source_url"),
            source_page_or_detail=record.get("project_row_no"),
            ownership_pct_observed=record.get("group_interest_pct"),
            ownership_raw=raw,
            evidence_context=record.get("lot_description") or record.get("project_label"),
            source_key=f"{record.get('schedule_id')}:{record.get('project_row_no')}",
        )

    for record in frames["planning"].to_dict("records"):
        evidence_source = _text(record.get("evidence_source")) or "planning"
        _append(
            record,
            source_layer="planning",
            event_date=record.get("planning_consent_date") or record.get("evidence_date"),
            date_semantics="regulatory_consent_or_approval_date",
            event_type=f"{evidence_source}_regulatory_evidence",
            evidence_level="official_regulatory_evidence_not_ownership",
            promotion_status="blocked_regulatory_date_not_ownership",
            source_url=record.get("source_url"),
            source_page_or_detail=record.get("page_or_detail"),
            ownership_raw=record.get("parent_or_developer_raw"),
            evidence_context=" | ".join(
                value for value in (
                    _text(record.get("development_name_raw")),
                    _text(record.get("lot_no_raw")),
                    _text(record.get("parent_or_developer_raw")),
                ) if value
            ),
            source_key=record.get("evidence_record_id"),
        )

    for record in frames["pipeline_disclosure"].to_dict("records"):
        _append(
            record,
            source_layer="pipeline_disclosure",
            event_date=record.get("publication_date"),
            date_semantics="disclosure_publication_date",
            event_type=_text(record.get("pipeline_status")) or "pipeline_disclosure",
            evidence_level="official_shkp_disclosure",
            promotion_status="blocked_disclosure_only",
            source_url=record.get("source_url"),
            evidence_context=record.get("project_label"),
            source_key=record.get("pipeline_evidence_key"),
        )

    for record in frames["project_site"].to_dict("records"):
        _append(
            record,
            source_layer="project_site",
            event_date=record.get("estimated_material_date") or record.get("matched_at"),
            date_semantics="estimated_material_date" if record.get("estimated_material_date") else "site_observed_at",
            event_type="project_site_vendor_notice",
            evidence_level="official_project_site_vendor_notice",
            promotion_status="blocked_vendor_only",
            source_url=record.get("site_source_url"),
            vendor_name=record.get("vendor_name"),
            holding_companies=record.get("holding_companies"),
            evidence_context=record.get("holding_companies") or record.get("vendor_name"),
            source_key=record.get("marketing_name"),
        )

    frame = pd.DataFrame(rows, columns=SHKP_OWNERSHIP_EVIDENCE_TIMELINE_COLUMNS)
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["timeline_id"]).sort_values(
            ["srpe_development_id", "event_date", "source_layer", "timeline_id"],
            kind="stable",
        ).reset_index(drop=True)
    raw_snapshots = [
        str(path)
        for source_frame in frames.values()
        for path in source_frame.attrs.get("raw_snapshots", [])
        if path
    ]
    source_urls = [
        str(url)
        for source_frame in frames.values()
        for url in source_frame.attrs.get("source_urls", [])
        if url
    ]
    frame.attrs.update(
        raw_snapshots=list(dict.fromkeys(raw_snapshots)),
        source_urls=list(dict.fromkeys(source_urls)),
        lineage_metadata={
            "lineage_type": "derived_shkp_ownership_evidence_timeline",
            "timeline_rows": int(len(frame)),
            "phase_count": int(frame["srpe_development_id"].nunique()) if not frame.empty else 0,
            "date_semantics": sorted(frame["date_semantics"].dropna().unique().tolist()) if not frame.empty else [],
            "ownership_inference": False,
            "sales_promotion": False,
        },
    )
    return frame


def build_shkp_entity_ownership_crosswalk(
    *,
    legal_ownership_observations: pd.DataFrame | None = None,
    planning_evidence_crosswalk: pd.DataFrame | None = None,
    site_vendor_crosswalk: pd.DataFrame | None = None,
    allowed_srpe_development_ids: set[str] | None = None,
) -> pd.DataFrame:
    """Build a stable, non-promoting entity/phase evidence crosswalk.

    The source layers use different entity vocabularies: annual reports name
    legal subsidiaries, project sites publish vendor/holding notices, and
    LandsD/TPB records expose raw developer labels.  This function normalizes
    those observations to deterministic ``entity_key`` values while keeping
    the relationship and date semantics explicit.  It intentionally does not
    convert a vendor or holding-company label into a numeric SHKP percentage
    and never populates an effective ownership interval.
    """
    frames = {
        "legal": legal_ownership_observations if legal_ownership_observations is not None else pd.DataFrame(),
        "planning": planning_evidence_crosswalk if planning_evidence_crosswalk is not None else pd.DataFrame(),
        "site": site_vendor_crosswalk if site_vendor_crosswalk is not None else pd.DataFrame(),
    }
    allowed_ids = {str(value) for value in (allowed_srpe_development_ids or set()) if str(value).strip()}
    if allowed_ids and not frames["planning"].empty and "srpe_development_id" in frames["planning"].columns:
        frames["planning"] = frames["planning"].loc[
            frames["planning"]["srpe_development_id"].astype("string").isin(allowed_ids)
        ].copy()
    if allowed_ids and not frames["site"].empty and "srpe_development_id" in frames["site"].columns:
        frames["site"] = frames["site"].loc[
            frames["site"]["srpe_development_id"].astype("string").isin(allowed_ids)
        ].copy()
    rows: list[dict[str, Any]] = []

    def _text(value: Any) -> str | None:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        text = str(value).strip()
        return text or None

    def _date(value: Any) -> str | None:
        text = _text(value)
        if not text:
            return None
        parsed = pd.to_datetime(text, errors="coerce")
        return parsed.date().isoformat() if pd.notna(parsed) else None

    def _number(value: Any) -> float | None:
        parsed = pd.to_numeric(value, errors="coerce")
        return float(parsed) if pd.notna(parsed) else None

    def _entity_key(entity_name: str, entity_type: str) -> str:
        normalized = _normalized_name(entity_name)
        # Do not collapse an SPV and an identically named non-SPV label into
        # one namespace.  The normalized name itself remains visible in the
        # row and can be reconciled manually later.
        return f"{entity_type}:{normalized}" if normalized else f"{entity_type}:unresolved"

    def _listed_parent_for(name: str | None, fallback: str | None = None) -> tuple[str | None, str | None]:
        normalized = _normalized_name(name)
        if normalized == "sunhungkaipropertieslimited":
            return "Sun Hung Kai Properties Limited", "0016"
        return fallback, None

    def _source_urls(value: Any) -> list[str]:
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value if str(item).strip()]
        text = _text(value)
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return [text]
        return [str(item) for item in parsed] if isinstance(parsed, list) else [text]

    def _append(
        *,
        entity_name: Any,
        entity_type: str,
        entity_role: str,
        srpe_development_id: Any,
        srpe_phase_name: Any,
        relation_status: str,
        ownership_pct_observed: Any = None,
        ownership_observed_as_of: Any = None,
        evidence_status: str,
        dedup_status: str,
        source_url: Any = None,
        source_page_or_detail: Any = None,
        evidence_context: Any = None,
        source_urls: list[str] | None = None,
        listed_parent: Any = None,
        stock_code: Any = None,
    ) -> None:
        name = _text(entity_name)
        phase_id = _text(srpe_development_id)
        if not name or not phase_id:
            return
        urls = list(dict.fromkeys(_source_urls(source_urls) + _source_urls(source_url)))
        primary_url = _text(source_url) or (urls[0] if urls else None)
        observed_date = _date(ownership_observed_as_of)
        key = "|".join(
            str(value or "")
            for value in (
                _entity_key(name, entity_type),
                phase_id,
                relation_status,
                observed_date,
                primary_url,
                _text(source_page_or_detail),
            )
        )
        parent = _text(listed_parent)
        code = _text(stock_code)
        if not parent or not code:
            inferred_parent, inferred_code = _listed_parent_for(name)
            parent = parent or inferred_parent
            code = code or inferred_code
        rows.append(
            {
                "entity_observation_id": hashlib.sha1(key.encode("utf-8")).hexdigest(),
                "entity_key": _entity_key(name, entity_type),
                "entity_name": name,
                "entity_type": entity_type,
                "entity_role": entity_role,
                "listed_parent": parent,
                "stock_code": code,
                "srpe_development_id": phase_id,
                "srpe_phase_name": _text(srpe_phase_name),
                "relation_status": relation_status,
                "ownership_pct_observed": _number(ownership_pct_observed),
                "ownership_observed_as_of": observed_date,
                "effective_from": None,
                "effective_to": None,
                "evidence_status": evidence_status,
                "dedup_status": dedup_status,
                "source_url": primary_url,
                "source_page_or_detail": _text(source_page_or_detail),
                "evidence_context": _text(evidence_context),
                "source_urls_json": json.dumps(urls, ensure_ascii=False),
                "last_verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    for record in frames["legal"].to_dict("records"):
        phase_id = record.get("srpe_development_id")
        spv = record.get("subsidiary_spv_name")
        evidence_status = _text(record.get("evidence_status")) or "numeric_spv_snapshot"
        numeric = evidence_status == "numeric_spv_snapshot"
        source_urls = _source_urls(record.get("source_urls_json"))
        _append(
            entity_name=spv,
            entity_type="subsidiary_spv",
            entity_role="subsidiary_of_listed_parent",
            srpe_development_id=phase_id,
            srpe_phase_name=record.get("srpe_phase_name"),
            relation_status="numeric_snapshot" if numeric else "parent_company_observation",
            ownership_pct_observed=record.get("ownership_pct"),
            ownership_observed_as_of=record.get("ownership_observed_as_of"),
            evidence_status=evidence_status,
            dedup_status="snapshot_not_effective_interval",
            source_url=record.get("ownership_source_url"),
            source_page_or_detail=record.get("ownership_source_page"),
            evidence_context=record.get("caveat"),
            source_urls=source_urls,
            listed_parent=record.get("listed_parent"),
            stock_code=record.get("stock_code"),
        )
        _append(
            entity_name=record.get("listed_parent"),
            entity_type="listed_parent",
            entity_role="parent_of_observed_subsidiary",
            srpe_development_id=phase_id,
            srpe_phase_name=record.get("srpe_phase_name"),
            relation_status="parent_observed",
            evidence_status=evidence_status,
            dedup_status="parent_identity_only",
            source_url=record.get("ownership_source_url"),
            source_page_or_detail=record.get("ownership_source_page"),
            evidence_context=f"Observed parent of {spv or 'unresolved subsidiary'}",
            source_urls=source_urls,
            listed_parent=record.get("listed_parent"),
            stock_code=record.get("stock_code"),
        )

    for record in frames["site"].to_dict("records"):
        phase_id = record.get("srpe_development_id")
        common = {
            "srpe_development_id": phase_id,
            "srpe_phase_name": record.get("srpe_phase_name"),
            "evidence_status": _text(record.get("site_evidence_status")) or "site_observation",
            "dedup_status": "site_notice_review_only",
            "source_url": record.get("site_source_url"),
            "source_page_or_detail": record.get("marketing_name"),
            "evidence_context": record.get("holding_companies") or record.get("vendor_name"),
        }
        _append(
            entity_name=record.get("vendor_name"),
            entity_type="vendor_or_developer",
            entity_role="project_vendor_notice",
            relation_status="vendor_observed",
            **common,
        )
        holding_text = _text(record.get("holding_companies"))
        if holding_text:
            # Project sites use comma-separated English company labels in the
            # bounded P0 facts.  Keep an unsplittable raw label intact rather
            # than guessing at names containing punctuation.
            holding_names = [part.strip() for part in re.split(r"\s*,\s*", holding_text) if part.strip()]
            for holding_name in holding_names or [holding_text]:
                parent, code = _listed_parent_for(holding_name)
                _append(
                    entity_name=holding_name,
                    entity_type="holding_company_observation",
                    entity_role="holding_company_notice",
                    relation_status="holding_company_observed",
                    listed_parent=parent,
                    stock_code=code,
                    **common,
                )

    for record in frames["planning"].to_dict("records"):
        raw = _text(record.get("parent_or_developer_raw"))
        if not raw:
            continue
        labels = [part.strip() for part in re.split(r"\s*/\s*|\s*;\s*|\s*\|\s*", raw) if part.strip()]
        for label in labels or [raw]:
            parent, code = _listed_parent_for(label)
            _append(
                entity_name=label,
                entity_type="planning_entity_observation",
                entity_role="planning_party_label",
                srpe_development_id=record.get("srpe_development_id"),
                srpe_phase_name=record.get("srpe_phase_name"),
                relation_status="planning_entity_observed",
                evidence_status=_text(record.get("evidence_status")) or "planning_observation",
                dedup_status="planning_label_review_only",
                source_url=record.get("source_url"),
                source_page_or_detail=record.get("page_or_detail"),
                evidence_context=raw,
                listed_parent=parent,
                stock_code=code,
            )

    frame = pd.DataFrame(rows, columns=SHKP_ENTITY_OWNERSHIP_CROSSWALK_COLUMNS)
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["entity_observation_id"]).sort_values(
            ["srpe_development_id", "entity_type", "entity_key", "ownership_observed_as_of", "entity_observation_id"],
            kind="stable",
        ).reset_index(drop=True)
    raw_snapshots = [
        str(path)
        for source_frame in frames.values()
        for path in source_frame.attrs.get("raw_snapshots", [])
        if path
    ]
    source_urls = [
        str(url)
        for source_frame in frames.values()
        for url in source_frame.attrs.get("source_urls", [])
        if url
    ]
    frame.attrs.update(
        raw_snapshots=list(dict.fromkeys(raw_snapshots)),
        source_urls=list(dict.fromkeys(source_urls)),
        lineage_metadata={
            "lineage_type": "derived_shkp_entity_ownership_crosswalk",
            "entity_observation_rows": int(len(frame)),
            "entity_count": int(frame["entity_key"].nunique()) if not frame.empty else 0,
            "phase_count": int(frame["srpe_development_id"].nunique()) if not frame.empty else 0,
            "allowed_phase_scope": sorted(allowed_ids),
            "ownership_inference": False,
            "effective_interval_promotion": False,
            "dedup_policy": "stable entity key plus phase/relation/date/source identity; raw labels retained",
        },
    )
    return frame


def _document_type_from_link(page_kind: str, title: str, href: str) -> str:
    lower = f"{title} {href}".lower()
    if page_kind == "financial_results_reports":
        if "annual report" in lower or "ar20" in lower:
            return "annual_report"
        if "interim" in lower or "ir20" in lower:
            return "interim_report"
        if "presentation" in lower or "ppt" in lower:
            return "results_presentation"
        return "financial_report"
    return page_kind


def _published_date_from_text(value: str) -> str | None:
    match = re.search(r"\b(20\d{2})[-/]([01]?\d)[-/]([0-3]?\d)\b", value)
    if not match:
        return None
    try:
        return pd.Timestamp(
            year=int(match.group(1)), month=int(match.group(2)), day=int(match.group(3))
        ).date().isoformat()
    except ValueError:
        return None


def _group_pdf_words_by_top(words: list[dict[str, Any]], tolerance: float = 2.5) -> list[list[dict[str, Any]]]:
    """Group pdfplumber words into visual lines while retaining x positions."""
    lines: list[list[dict[str, Any]]] = []
    line_tops: list[float] = []
    for word in sorted(words, key=lambda item: (float(item.get("top", 0)), float(item.get("x0", 0)))):
        top = float(word.get("top", 0))
        target = None
        for index, line_top in enumerate(line_tops):
            if abs(top - line_top) <= tolerance:
                target = index
                break
        if target is None:
            line_tops.append(top)
            lines.append([word])
        else:
            lines[target].append(word)
    for line in lines:
        line.sort(key=lambda item: float(item.get("x0", 0)))
    return lines


def _shkp_annual_table_ranges(words: list[dict[str, Any]]) -> tuple[float, float, float, float, float]:
    """Return project/location/usage/interest/area x-boundaries per PDF template."""
    # The 2023/24 annual report moved the table to a compact layout where the
    # Location column begins at ~184pt and the use/area columns begin much
    # later.  Newer reports use the wider ~195/300/390/463pt layout.  Detect
    # the compact header rather than applying a report-year special case.
    lines = _group_pdf_words_by_top(words, tolerance=4.5)
    for line in lines:
        positions = {str(word.get("text") or "").lower(): float(word.get("x0", 0)) for word in line}
        # Require the actual table header.  Older pages can contain a
        # narrative line with the words ``Location`` and ``Usage`` before the
        # table; using it shifts every body column and silently drops rows.
        if "project" not in positions or "location" not in positions:
            continue
        if "usage" not in positions:
            interest_x = positions.get("interest")
            area_x = next(
                (float(word.get("x0", 0)) for word in line
                if str(word.get("text") or "").lower().lstrip("(").startswith(("square", "gross"))),
                None,
            )
            if interest_x is not None and area_x is not None:
                # Leave a narrow gap around the legacy body glyphs: the
                # first ``Joint`` token can sit ~2.5pt left of the header's
                # Interest anchor.
                return 0.0, positions["location"] - 2.0, interest_x - 3.0, area_x - 2.0, area_x - 2.0
            continue
        location_x = positions["location"]
        usage_x = positions["usage"]
        interest_x = positions.get("interest")
        area_x = next(
            (float(word.get("x0", 0)) for word in line
             if str(word.get("text") or "").lower().lstrip("(").startswith(("square", "gross"))),
            None,
        )
        if interest_x is not None and area_x is not None:
            # Use the actual header anchors.  The interest body cell in some
            # legacy reports begins noticeably left of the wrapped
            # ``Interest`` header, so split the usage/interest gap at its
            # midpoint instead of dropping the first ``Joint`` token.
            interest_start = usage_x + (interest_x - usage_x) * 0.5
            return 0.0, location_x - 2.0, usage_x - 2.0, interest_start, area_x - 2.0
        if location_x < 195 and usage_x > 300:
            interest_candidates = [
                float(word.get("x0", 0))
                for candidate_line in lines
                for word in candidate_line
                if str(word.get("text") or "").lower() == "interest"
                and abs(float(word.get("top", 0)) - float(line[0].get("top", 0))) < 40
            ]
            area_candidates = [
                float(word.get("x0", 0))
                for candidate_line in lines
                for word in candidate_line
                if str(word.get("text") or "").lower() == "square"
                and abs(float(word.get("top", 0)) - float(line[0].get("top", 0))) < 40
            ]
            interest_x = min(interest_candidates, default=419.0)
            area_x = min(area_candidates, default=487.0)
            # Header and body glyphs can differ by a fraction of a point;
            # leave a small gap at each boundary so the first body glyph in a
            # cell is not assigned to the preceding column.
            return 0.0, location_x - 2.0, usage_x - 2.0, interest_x - 2.0, area_x - 2.0
    return 0.0, 195.0, 300.0, 390.0, 463.0


def _parse_shkp_handover_table_words(
    words: list[dict[str, Any]],
    *,
    page_number: int,
    geography: str,
) -> list[dict[str, Any]]:
    """Parse the visually aligned project table in an SHKP annual report.

    The parser uses column x-ranges and a row's final GFA value rather than
    relying on PDF text order, which is interleaved when project/location/usage
    cells wrap onto multiple lines.  Rows not ending in a numeric GFA are not
    promoted to project facts.
    """
    lines = _group_pdf_words_by_top(words)
    legacy_no_usage = any(
        "project" in {str(word.get("text") or "").lower() for word in line}
        and "location" in {str(word.get("text") or "").lower() for word in line}
        and "interest" in {str(word.get("text") or "").lower() for word in line}
        and "usage" not in {str(word.get("text") or "").lower() for word in line}
        for line in lines
    )
    project_x, location_x, usage_x, interest_x, area_x = _shkp_annual_table_ranges(words)
    start_indexes: list[int] = []
    for index, line in enumerate(lines):
        project = [str(word.get("text") or "") for word in line if project_x <= float(word.get("x0", 0)) < location_x]
        area = [str(word.get("text") or "") for word in line if float(word.get("x0", 0)) >= area_x]
        if project and project[0].lower() not in {"project", "total"} and any(
            re.fullmatch(r"[\d,]+", value) for value in area
        ):
            start_indexes.append(index)
    rows: list[dict[str, Any]] = []
    for position, start in enumerate(start_indexes):
        end = start_indexes[position + 1] if position + 1 < len(start_indexes) else len(lines)
        row_lines: list[list[dict[str, Any]]] = []
        for line in lines[start:end]:
            if any(str(word.get("text") or "").lower() == "total" for word in line):
                break
            row_lines.append(line)

        def collect(x0_min: float, x0_max: float | None = None) -> list[str]:
            values: list[str] = []
            for line in row_lines:
                for word in line:
                    x0 = float(word.get("x0", 0))
                    if x0 >= x0_min and (x0_max is None or x0 < x0_max):
                        values.append(str(word.get("text") or ""))
            return values

        project_label = " ".join(
            value for value in collect(project_x, location_x)
            if not re.fullmatch(r"\d+\)", value)
        ).strip()
        location = " ".join(collect(location_x, usage_x)).strip()
        if legacy_no_usage:
            usage = None
            interest = " ".join(collect(usage_x, interest_x)).strip()
        else:
            usage = " ".join(collect(usage_x, interest_x)).strip()
            interest = " ".join(collect(interest_x, area_x)).strip()
        area_values = [value for value in collect(area_x) if re.fullmatch(r"[\d,]+", value)]
        if not project_label or not area_values:
            continue
        area = int(area_values[-1].replace(",", ""))
        interest_pct = None
        if re.fullmatch(r"\d+(?:\.\d+)?", interest):
            interest_pct = float(interest)
        context = " ".join(" ".join(str(word.get("text") or "") for word in line) for line in row_lines)
        rows.append(
            {
                "project_label": project_label,
                "location": location,
                "usage": usage,
                "group_interest_raw": interest,
                "group_interest_pct": interest_pct,
                "attributable_gfa_sqft": area,
                "geography": geography,
                "page_number": page_number,
                "evidence_context": context,
            }
        )
    return rows


def _shkp_major_project_area(value: str) -> int | None:
    """Parse a square-foot value from a major-project narrative cell."""
    text = str(value or "").lower().replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(million\s+)?square\s+feet", text)
    if not match:
        return None
    amount = float(match.group(1)) * (1_000_000 if match.group(2) else 1)
    return int(round(amount))


def _shkp_major_project_column_lines(text: str) -> list[str]:
    """Normalize one visual PDF column into line-level text."""
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in str(text or "").splitlines()
        if re.sub(r"\s+", " ", line).strip()
    ]


def _parse_shkp_major_project_column_text(
    text: str,
    *,
    page_number: int,
    geography: str,
) -> list[dict[str, Any]]:
    """Parse the fact boxes in SHKP's ``Major Projects under Development``.

    Annual reports render these pages as two visual columns and interleave the
    columns when text is extracted naively.  Callers therefore pass one
    column at a time.  The parser only emits a row when a lot descriptor and
    an explicit ownership line are present; descriptive narrative without
    those anchors remains unstructured evidence instead of becoming a false
    project record.
    """
    lines = _shkp_major_project_column_lines(text)
    ownership_indexes = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(
            r"\(?\s*(?:\d+(?:\.\d+)?\s*%\s*owned|joint\s+venture)\s*\)?",
            line,
            flags=re.IGNORECASE,
        )
    ]
    if not ownership_indexes:
        return []

    def _is_lot_line(line: str) -> bool:
        return bool(
            re.search(
                r"\b(?:inland\s+lot|town\s+lot|lot\s+no\.?|lot\s+\d|DD\s*\d+)",
                line,
                flags=re.IGNORECASE,
            )
        )

    def _area_values(segment: str) -> list[tuple[int, str | None]]:
        values: list[tuple[int, str | None]] = []
        for match in re.finditer(
            r"([\d,]+(?:\.\d+)?)\s*(million\s+)?square\s+feet\s*(?:\(([^)]+)\))?",
            segment,
            flags=re.IGNORECASE,
        ):
            amount = float(match.group(1).replace(",", "")) * (1_000_000 if match.group(2) else 1)
            values.append((int(round(amount)), match.group(3)))
        return values

    rows: list[dict[str, Any]] = []
    generic_labels = {
        "kowloon",
        "new territories east",
        "new territories west",
        "hong kong island",
        "property development",
        "review of operations",
    }
    for owner_index in ownership_indexes:
        lot_index = next(
            (
                index
                for index in range(owner_index - 1, max(-1, owner_index - 9), -1)
                if _is_lot_line(lines[index])
            ),
            None,
        )
        if lot_index is None:
            continue

        project_label = None
        for index in range(lot_index - 1, max(-1, lot_index - 4), -1):
            candidate = lines[index].strip(" ,")
            if candidate.lower() in generic_labels:
                continue
            # A two-column extraction can put the tail of the previous
            # project's narrative immediately above the next lot.  Sentence
            # fragments ending in punctuation are not project titles; fall
            # back to the legal lot label in that case.
            if (
                candidate.endswith((".", ":", ";", "!", "?"))
                or "." in candidate
                or candidate[:1].islower()
                or not candidate.isascii()
                or re.search(
                    r"\b(?:enhancing|are poised|the project will|the development will|providing|enjoy|will be|currently in)\b",
                    candidate,
                    flags=re.IGNORECASE,
                )
            ):
                continue
            if candidate and not re.search(
                r"^(?:site area|gross floor|attributable gross|approximate|expected date|certificate of)",
                candidate,
                flags=re.IGNORECASE,
            ):
                project_label = candidate
                break
        project_label = project_label or lines[lot_index]

        # Fact boxes place all metadata immediately after the ownership line;
        # keep a bounded window so narrative from the next project cannot
        # leak into this row when a page uses a single column.
        block_lines = lines[lot_index : min(len(lines), owner_index + 14)]
        block = " ".join(block_lines)
        ownership_basis = lines[owner_index].strip("() ")
        interest_match = re.search(r"(\d+(?:\.\d+)?)\s*%", ownership_basis)
        group_interest_pct = float(interest_match.group(1)) if interest_match else None

        site_area_match = re.search(
            r"site area\s*:\s*(.*?)(?=\s+gross floor|\s+attributable gross|$)",
            block,
            flags=re.IGNORECASE,
        )
        site_area_sqft = _shkp_major_project_area(site_area_match.group(1)) if site_area_match else None

        gfa_match = re.search(
            r"(?:attributable\s+)?gross(?:\s+floor)?(?:\s+area)?\s*:?[\s]*(.*?)(?=\s+approximate(?: attributable)?\s*:|\s+expected date of\s*:|\s+certificate of|$)",
            block,
            flags=re.IGNORECASE,
        )
        gfa_segment = gfa_match.group(1) if gfa_match else ""
        area_values = _area_values(gfa_segment)
        gross_floor_area_sqft = sum(value for value, _ in area_values) or None
        residential_gfa_sqft = sum(
            value for value, usage in area_values if usage and "residential" in usage.lower()
        ) or None
        retail_gfa_sqft = sum(
            value for value, usage in area_values if usage and "retail" in usage.lower()
        ) or None

        units_match = re.search(
            r"approximate(?: attributable)?\s*:\s*([\d,]+)",
            block,
            flags=re.IGNORECASE,
        )
        approximate_units = int(units_match.group(1).replace(",", "")) if units_match else None

        expected_index = next(
            (index for index, line in enumerate(block_lines) if re.search(r"expected date of\s*:", line, flags=re.IGNORECASE)),
            None,
        )
        completion_window = None
        if expected_index is not None:
            expected_line = block_lines[expected_index]
            expected_value = re.split(r"expected date of\s*:\s*", expected_line, maxsplit=1, flags=re.IGNORECASE)[-1]
            completion_parts = [expected_value]
            for following in block_lines[expected_index + 1 :]:
                if re.match(
                    r"^(?:certificate of|strategically|comprising|located|atop|adjacent|through|set to|sitting|the |with about|with just|foundation|superstructure)",
                    following,
                    flags=re.IGNORECASE,
                ):
                    break
                completion_parts.append(following)
            completion_window = re.sub(r"\s+", " ", " ".join(completion_parts)).strip() or None
            completion_window = re.sub(r"\s+completion$", "", completion_window, flags=re.IGNORECASE)
        lower_block = block.lower()
        project_state = (
            "future_planning_stage"
            if "planning stage" in lower_block or "design and planning" in lower_block
            else "under_development_major_project"
        )
        rows.append(
            {
                "evidence_type": "major_project_under_development",
                "project_label": project_label,
                "location": lines[lot_index],
                "usage": None,
                "group_interest_raw": ownership_basis,
                "group_interest_pct": group_interest_pct,
                "attributable_gfa_sqft": None,
                "site_area_sqft": site_area_sqft,
                "gross_floor_area_sqft": gross_floor_area_sqft,
                "residential_gfa_sqft": residential_gfa_sqft,
                "retail_gfa_sqft": retail_gfa_sqft,
                "approximate_units": approximate_units,
                "completion_window": completion_window,
                "ownership_basis": ownership_basis,
                "source_section": "major_projects_under_development",
                "project_state": project_state,
                "geography": geography,
                "page_number": page_number,
                "evidence_status": "found",
                "evidence_context": block[:1800],
            }
        )
    return rows


def _parse_shkp_major_project_page_words(
    words: list[dict[str, Any]],
    *,
    page_width: float,
    page_number: int,
    geography: str,
) -> list[dict[str, Any]]:
    """Split a two-column annual-report page before parsing fact boxes."""
    midpoint = float(page_width) / 2.0
    rows: list[dict[str, Any]] = []
    for column_words in (
        [word for word in words if float(word.get("x0", 0)) < midpoint],
        [word for word in words if float(word.get("x0", 0)) >= midpoint],
    ):
        lines = _group_pdf_words_by_top(column_words, tolerance=3.0)
        column_text = "\n".join(
            " ".join(str(word.get("text") or "") for word in line)
            for line in lines
        )
        rows.extend(
            _parse_shkp_major_project_column_text(
                column_text,
                page_number=page_number,
                geography=geography,
            )
        )
    return rows


def _completion_schedule_number(words: list[dict[str, Any]]) -> int | None:
    """Parse a visually aligned GFA cell, including split PDF number glyphs."""
    tokens = [str(word.get("text") or "").strip() for word in words]
    tokens = [token for token in tokens if token and not re.fullmatch(r"\(\d+\)", token)]
    if any(token == "-" for token in tokens) and not any(re.search(r"\d", token) for token in tokens):
        return None
    joined = "".join(tokens)
    match = re.search(r"\d[\d,]*", joined)
    if not match:
        return None
    digits = re.sub(r"[^0-9]", "", match.group(0))
    return int(digits) if digits else None


def _completion_schedule_interest(words: list[dict[str, Any]]) -> tuple[str | None, float | None]:
    tokens = [str(word.get("text") or "").strip() for word in words]
    # Footnote markers can sit in the same visual cell as a percentage.
    tokens = [token for token in tokens if token and not re.fullmatch(r"\(\d+\)", token)]
    raw = " ".join(tokens).strip() or None
    if raw and raw.upper() == "JV":
        return raw, None
    match = re.search(r"\d+(?:\.\d+)?", raw or "")
    return raw, float(match.group(0)) if match else None


def _parse_shkp_completion_schedule_words(
    words: list[dict[str, Any]],
    *,
    page_number: int,
    schedule_date: str,
) -> list[dict[str, Any]]:
    """Parse the aligned project rows in SHKP's completion-schedule PDF.

    The PDF is a two-page text-native table.  Parsing by x-ranges is
    intentional: ``extract_text`` interleaves wrapped lot names, labels and
    split thousands separators, while the visual columns are stable across
    the current schedule.  Rows without a leading ordinal or without an
    interest token are ignored rather than guessed into the registry.
    """
    # A few long lot descriptions have footnote glyphs that shift one wrapped
    # cell by ~3pt; use a slightly wider tolerance than the annual-report
    # parser while the table's row spacing remains ~15pt.
    lines = _group_pdf_words_by_top(words, tolerance=4.5)
    row_starts: list[int] = []
    for index, line in enumerate(lines):
        if not line:
            continue
        first = str(line[0].get("text") or "").strip()
        # The page template moved the table left margin from ~12pt (2026 and
        # 2021) to ~26pt (2023); use a bounded margin rather than a single
        # vintage-specific coordinate.
        if float(line[0].get("x0", 0)) < 45 and re.fullmatch(r"\d+\)", first):
            row_starts.append(index)

    rows: list[dict[str, Any]] = []
    completion_window: str | None = None
    for index, line in enumerate(lines):
        text = " ".join(str(word.get("text") or "") for word in line).strip()
        match = re.search(r"(?:Completed|Completion) in\s+(.+)$", text, flags=re.IGNORECASE)
        if match and not re.match(r"^\d+\)", text):
            completion_window = re.sub(r"\s+", " ", match.group(1)).strip()

        if index not in row_starts:
            continue
        row_position = row_starts.index(index)
        end = row_starts[row_position + 1] if row_position + 1 < len(row_starts) else len(lines)
        row_lines: list[list[dict[str, Any]]] = []
        for line_index, row_line in enumerate(lines[index:end]):
            # A project row can wrap to a second visual line, but the table
            # inserts subtotals, the next completion-window heading and
            # footnotes before the next ordinal.  Do not let those lines
            # leak into the previous row's aligned columns.
            line_text = " ".join(str(word.get("text") or "") for word in row_line).strip()
            if line_index > 0 and (
                re.match(r"^(?:Others|Subtotal|Year Total|Total for|Scheduled for|Completion in)", line_text, flags=re.IGNORECASE)
                or re.match(r"^\(\d+\)", line_text)
            ):
                break
            row_lines.append(row_line)

        def collect(x_min: float, x_max: float | None = None) -> list[dict[str, Any]]:
            return [
                word
                for row_line in row_lines
                for word in row_line
                if float(word.get("x0", 0)) >= x_min
                and (x_max is None or float(word.get("x0", 0)) < x_max)
            ]

        ordinal = str(row_lines[0][0].get("text") or "").strip()
        row_no = int(ordinal[:-1])
        lot_words = collect(20, 240)
        project_words = collect(240, 390)
        interest_words = collect(390, 455)
        lot_description = " ".join(
            str(word.get("text") or "") for word in lot_words
            if str(word.get("text") or "").strip() != ordinal
        ).strip()
        project_label = " ".join(str(word.get("text") or "") for word in project_words).strip()
        interest_raw, interest_pct = _completion_schedule_interest(interest_words)
        if not lot_description or not interest_raw:
            continue
        row_text = " ".join(str(word.get("text") or "") for row_line in row_lines for word in row_line)
        rows.append(
            {
                "schedule_date": schedule_date,
                "project_row_no": row_no,
                "lot_description": lot_description,
                "project_label": project_label or None,
                "group_interest_raw": interest_raw,
                "group_interest_pct": interest_pct,
                "completion_window": completion_window,
                "project_state": "under_development_completion_schedule",
                "residential_gfa_sqft": _completion_schedule_number(collect(450, 510)),
                "shops_gfa_sqft": _completion_schedule_number(collect(510, 575)),
                "office_gfa_sqft": _completion_schedule_number(collect(575, 630)),
                "hotel_gfa_sqft": _completion_schedule_number(collect(630, 680)),
                "industrial_gfa_sqft": _completion_schedule_number(collect(680, 735)),
                "total_gfa_sqft": _completion_schedule_number(collect(735)),
                "page_number": page_number,
                "footnote_context": row_text,
            }
        )
    return rows


def fetch_shkp_completion_schedule_projects(
    *,
    schedules: Iterable[Mapping[str, Any]] | None = None,
    session: requests.Session | None = None,
    timeout: float = 90,
) -> pd.DataFrame:
    """Fetch and parse official SHKP project-completion schedule snapshots."""
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "application/pdf,*/*"})
    fetched_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    parse_summary: list[dict[str, Any]] = []
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pdfplumber is required for SHKP completion schedules") from exc

    for config in tuple(schedules or SHKP_COMPLETION_SCHEDULES):
        schedule_id = str(config["schedule_id"])
        schedule_date = str(config["schedule_date"])
        document_url = str(config["url"])
        response = None
        for attempt in range(3):
            candidate = client.get(document_url, timeout=timeout)
            candidate.raise_for_status()
            if candidate.content.lstrip().startswith(b"%PDF"):
                response = candidate
                break
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
        if response is None:
            raise ValueError(f"SHKP completion schedule URL returned non-PDF content: {document_url}")
        raw_path = save_raw_snapshot(
            f"{schedule_id}_pdf", response.content, file_ext="pdf", source_url=document_url
        )
        raw_snapshots.append(str(raw_path))
        source_urls.append(document_url)
        schedule_rows = 0
        with pdfplumber.open(BytesIO(response.content)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                page_rows = _parse_shkp_completion_schedule_words(
                    page.extract_words(x_tolerance=1, y_tolerance=3),
                    page_number=page_number,
                    schedule_date=schedule_date,
                )
                schedule_rows += len(page_rows)
                for row in page_rows:
                    records.append(
                        {
                            "schedule_id": schedule_id,
                            **row,
                            "document_url": document_url,
                            "source_url": document_url,
                            "fetched_at": fetched_at,
                        }
                    )
        parse_summary.append({"schedule_id": schedule_id, "project_rows": schedule_rows})

    frame = pd.DataFrame(records, columns=SHKP_COMPLETION_SCHEDULE_COLUMNS)
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["schedule_id", "project_row_no"]).reset_index(drop=True)
    frame.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        lineage_metadata={
            "lineage_type": "official_shkp_completion_schedule_pdf",
            "parse_summary": parse_summary,
            "ownership_registry_ready": False,
            "interest_semantics": "Group's Interest reported by SHKP; not legal-SPV ownership",
        },
    )
    return frame


def _shkp_printed_page_number(text: str) -> str | None:
    """Recover the printed annual-report page number from a page footer."""
    match = re.search(
        r"(?m)^\s*(\d{3})\s+SUN\s+HUNG\s+KAI\s+PROPERTIES\s+LIMITED\s*$",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def _parse_shkp_principal_subsidiary_page_words(
    words: list[dict[str, Any]],
    *,
    pdf_page: int,
    report_period_end: str,
    allow_continuation: bool = False,
) -> list[dict[str, Any]]:
    """Parse one visually aligned ``Principal Subsidiaries`` page.

    The appendix repeats a compact five-column layout over several pages.  A
    row starts only when a name-column token and a numeric Company (%) token
    share the same visual line; continuation lines are then collected by
    column boundaries.  This avoids treating wrapped names, note numbers and
    registered-capital footnotes as separate subsidiaries.
    """
    lines = _group_pdf_words_by_top(words, tolerance=2.8)
    if not lines:
        return []

    def line_text(line: list[dict[str, Any]]) -> str:
        return " ".join(str(word.get("text") or "") for word in line).strip()

    header_index = None
    for index, line in enumerate(lines):
        text = line_text(line).lower()
        if "name" in text and "activities" in text and "company" in text:
            header_index = index
            break
    if header_index is None and not allow_continuation:
        return []
    # Continuation pages repeat the column layout but may omit the title and
    # occasionally omit the Name/Activities header entirely.  Their first
    # valid row is still identifiable by the same x-coordinate/percentage
    # rule, so start scanning from the top of the page.
    if header_index is None:
        header_index = -1

    row_starts: list[int] = []
    for index in range(header_index + 1, len(lines)):
        line = lines[index]
        # Footnotes can share the table's x-columns and contain percentages
        # (for example ``Interest rate ... 2.85%``).  They are not entity
        # rows and must not become a false subsidiary or contaminate the last
        # valid row.
        candidate_text = line_text(line)
        if re.match(
            r"^(?:notes?\b|interest\s+rate\b|\d+\.\s*)",
            candidate_text,
            flags=re.IGNORECASE,
        ):
            continue
        # Name begins around x=65 and the equity percentage is centered near
        # x=294 in the audited 2022/23 and 2023/24 templates.  Keep generous
        # boundaries so small template shifts do not drop a row.
        name_words = [
            str(word.get("text") or "")
            for word in line
            if 52 <= float(word.get("x0", 0)) < 230
        ]
        pct_words = [
            str(word.get("text") or "")
            for word in line
            if 280 <= float(word.get("x0", 0)) < 314
            and re.fullmatch(r"\d{1,3}(?:\.\d+)?", str(word.get("text") or ""))
        ]
        if name_words and pct_words:
            row_starts.append(index)
    if not row_starts:
        return []

    rows: list[dict[str, Any]] = []
    for position, start in enumerate(row_starts):
        end = row_starts[position + 1] if position + 1 < len(row_starts) else len(lines)
        row_lines: list[list[dict[str, Any]]] = []
        for line in lines[start:end]:
            text = line_text(line)
            # The footer and the next appendix are not part of a subsidiary
            # row.  A page break normally ends the row before these tokens,
            # but the guard keeps synthetic/test pages deterministic.
            if re.match(
                r"^(?:notes?\b|interest\s+rate\b|\d+\.\s*)",
                text,
                flags=re.IGNORECASE,
            ):
                break
            if re.search(r"Principal\s+(?:Joint\s+Ventures|Associates)", text, flags=re.IGNORECASE):
                break
            if re.search(r"SUN\s+HUNG\s+KAI\s+PROPERTIES\s+LIMITED", text, flags=re.IGNORECASE):
                break
            row_lines.append(line)

        def collect(x_min: float, x_max: float | None = None) -> list[str]:
            values: list[str] = []
            for row_line in row_lines:
                for word in row_line:
                    x0 = float(word.get("x0", 0))
                    if x0 < x_min or (x_max is not None and x0 >= x_max):
                        continue
                    value = str(word.get("text") or "").strip()
                    if value:
                        values.append(value)
            return values

        name = re.sub(r"\s+", " ", " ".join(collect(52, 230))).strip()
        if not name:
            continue
        # Wrapped rows at a physical page break can leave a generic suffix
        # such as ``Limited 75`` on the next page.  It is not a new
        # subsidiary; the preceding row owns the continuation text.
        if name.casefold() in {"limited", "agency limited", "co., ltd.", "co. ltd."}:
            continue
        pct_values = collect(280, 314)
        pct_match = next(
            (value for value in pct_values if re.fullmatch(r"\d{1,3}(?:\.\d+)?", value)),
            None,
        )
        if pct_match is None:
            continue
        activities = re.sub(r"\s+", " ", " ".join(collect(312, 460))).strip()
        notes = re.sub(r"\s+", " ", " ".join(collect(228, 255))).strip()
        share_capital = re.sub(r"\s+", " ", " ".join(collect(460, 545))).strip()
        rows.append(
            {
                "as_of_date": report_period_end,
                "spv_name": name,
                "attributable_equity_pct": float(pct_match),
                "business_description": activities or None,
                "note": notes or None,
                "share_capital_raw": share_capital or None,
                "pdf_page": pdf_page,
            }
        )
    return rows


def parse_shkp_annual_principal_subsidiaries(
    pdf_paths: Iterable[str | Path],
    *,
    reports: Iterable[Mapping[str, Any]] | None = None,
    fetched_at: str | None = None,
) -> pd.DataFrame:
    """Parse Principal Subsidiaries tables from already archived annual PDFs.

    ``fetch_shkp_annual_report_pipeline`` already downloads the annual PDFs;
    this parser consumes those raw snapshots to avoid a second network fetch.
    A report can legitimately have no parseable appendix (for example a short
    financial-results PDF), in which case the lineage records zero rows rather
    than manufacturing an empty ownership assertion.
    """
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pdfplumber is required for SHKP principal-subsidiary extraction") from exc

    report_configs = tuple(reports or SHKP_ANNUAL_REPORTS)
    by_token: dict[str, Mapping[str, Any]] = {
        str(config["report_id"]): config for config in report_configs
    }
    fetched_value = fetched_at or datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    parse_summary: list[dict[str, Any]] = []

    for raw_path_value in pdf_paths:
        raw_path = Path(str(raw_path_value))
        if not raw_path.exists() or raw_path.suffix.lower() != ".pdf":
            continue
        report = next(
            (
                config
                for report_id, config in by_token.items()
                if report_id in raw_path.as_posix()
            ),
            None,
        )
        if report is None:
            continue
        report_id = str(report["report_id"])
        report_period_end = str(report["report_period_end"])
        document_url = str(report["url"])
        raw_snapshots.append(str(raw_path))
        source_urls.append(document_url)
        report_rows = 0
        principal_pages = 0
        in_principal_section = False
        with pdfplumber.open(raw_path) as pdf:
            page_range = report.get("principal_pdf_page_range")
            if page_range:
                first_page = max(1, int(page_range[0]))
                last_page = min(len(pdf.pages), int(page_range[1]))
            else:
                # Keep an unconfigured report bounded to the final 60 pages;
                # the appendix is part of the financial-statement notes and
                # appears near the end in audited annual-report vintages.
                first_page = max(1, len(pdf.pages) - 59)
                last_page = len(pdf.pages)
            for pdf_page in range(first_page, last_page + 1):
                page = pdf.pages[pdf_page - 1]
                text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
                normalized = re.sub(r"\s+", " ", text).strip()
                # The appendix title appears only on the first page of some
                # report vintages; subsequent pages repeat the table header or
                # continue the rows without the title.  Keep a small section
                # state so continuation pages (where Ease Gold/Well Capital
                # often live) are not silently dropped.  Stop before the
                # separate Joint Ventures/Associates appendices.
                if re.search(
                    r"Principal\s+(?:Joint\s+Ventures|Associates)",
                    normalized,
                    flags=re.IGNORECASE,
                ):
                    in_principal_section = False
                    continue
                has_title = "Principal Subsidiaries" in normalized
                has_table_header = all(
                    token in normalized for token in ("Name", "Company", "Activities", "Equity")
                )
                if has_title and has_table_header:
                    in_principal_section = True
                if not in_principal_section:
                    continue
                rows = _parse_shkp_principal_subsidiary_page_words(
                    page.extract_words(x_tolerance=1, y_tolerance=3),
                    pdf_page=pdf_page,
                    report_period_end=report_period_end,
                    allow_continuation=True,
                )
                if not rows:
                    continue
                principal_pages += 1
                printed_page = _shkp_printed_page_number(text)
                for row in rows:
                    report_rows += 1
                    records.append(
                        {
                            "report_id": report_id,
                            "report_period_end": report_period_end,
                            **row,
                            "printed_page": printed_page,
                            "evidence_status": "found",
                            "ownership_semantics": "attributable equity interest held by the Company as at report period end; no effective interval",
                            "annual_document_url": document_url,
                            "source_url": document_url,
                            "fetched_at": fetched_value,
                        }
                    )
        parse_summary.append(
            {
                "report_id": report_id,
                "report_period_end": report_period_end,
                "principal_subsidiary_pages": principal_pages,
                "rows": report_rows,
                "pdf_pages": len(pdf.pages),
                "scanned_pdf_page_range": [first_page, last_page],
            }
        )

    frame = pd.DataFrame(records, columns=SHKP_ANNUAL_PRINCIPAL_SUBSIDIARY_COLUMNS)
    if not frame.empty:
        frame = frame.drop_duplicates(
            subset=["report_id", "spv_name", "as_of_date", "pdf_page"]
        ).reset_index(drop=True)
    frame.attrs.update(
        raw_snapshots=list(dict.fromkeys(raw_snapshots)),
        source_urls=list(dict.fromkeys(source_urls)),
        lineage_metadata={
            "lineage_type": "official_shkp_annual_report_principal_subsidiary_pdf",
            "parse_summary": parse_summary,
            "ownership_registry_ready": False,
            "effective_interval_promotion": False,
            "table_semantics": "principal subsidiaries only; not a complete project/SPV inventory",
        },
    )
    return frame


def build_shkp_annual_principal_subsidiary_crosswalk(
    principal_subsidiaries: pd.DataFrame,
    *,
    legal_ownership_observations: pd.DataFrame | None = None,
    site_vendor_crosswalk: pd.DataFrame | None = None,
    srpe_index: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a conservative annual-subsidiary → SRPE phase candidate bridge.

    The annual appendix is a company-level material-subsidiary disclosure. It
    does not identify a project, phase or JV economic split. This function
    therefore only creates phase candidates when an independent existing layer
    supplies the bridge: an exact legal-SPV observation or an official
    project-site/vendor crosswalk. All other subsidiary rows remain visible as
    ``unmatched_entity_only`` with a null SRPE ID. No row receives an effective
    ownership interval or sales-attribution permission.
    """
    annual = principal_subsidiaries.copy() if principal_subsidiaries is not None else pd.DataFrame()
    legal = legal_ownership_observations.copy() if legal_ownership_observations is not None else pd.DataFrame()
    site = site_vendor_crosswalk.copy() if site_vendor_crosswalk is not None else pd.DataFrame()
    srpe = srpe_index.copy() if srpe_index is not None else pd.DataFrame()
    if annual.empty:
        return pd.DataFrame(columns=SHKP_ANNUAL_PRINCIPAL_SUBSIDIARY_CROSSWALK_COLUMNS)

    def _text(value: Any) -> str | None:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        text = str(value).strip()
        return text or None

    def _number(value: Any) -> float | None:
        parsed = pd.to_numeric(value, errors="coerce")
        return float(parsed) if pd.notna(parsed) else None

    def _normalized_entity(value: Any) -> str:
        return _normalized_name(_text(value))

    legal_by_name: dict[str, list[dict[str, Any]]] = {}
    if not legal.empty and "subsidiary_spv_name" in legal.columns:
        for record in legal.to_dict("records"):
            key = _normalized_entity(record.get("subsidiary_spv_name"))
            if key:
                legal_by_name.setdefault(key, []).append(record)

    site_by_name: dict[str, list[dict[str, Any]]] = {}
    if not site.empty and "vendor_name" in site.columns:
        for record in site.to_dict("records"):
            key = _normalized_entity(record.get("vendor_name"))
            phase_id = _text(record.get("srpe_development_id"))
            if key and phase_id:
                site_by_name.setdefault(key, []).append(record)

    srpe_by_id = {
        _text(record.get("development_id")): record
        for record in srpe.to_dict("records")
        if _text(record.get("development_id"))
    }

    rows: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    for record in annual.to_dict("records"):
        spv_name = _text(record.get("spv_name"))
        if not spv_name:
            continue
        entity_key = _normalized_entity(spv_name)
        legal_candidates = legal_by_name.get(entity_key, [])
        site_candidates = site_by_name.get(entity_key, []) if not legal_candidates else []
        candidates: list[dict[str, Any]] = []
        match_status = "unmatched_entity_only"
        match_method = "no_independent_phase_bridge"
        if legal_candidates:
            candidates = legal_candidates
            match_status = "matched_legal_spv_phase_review_only"
            match_method = "exact_spv_name_to_legal_observation"
        elif site_candidates:
            candidates = site_candidates
            match_status = "matched_vendor_phase_review_only"
            match_method = "exact_vendor_name_to_project_site_crosswalk"

        # De-duplicate phase candidates while retaining the first source row;
        # one annual snapshot can legitimately cover several phases.
        candidate_by_phase: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            phase_id = _text(candidate.get("srpe_development_id"))
            if phase_id and phase_id not in candidate_by_phase:
                candidate_by_phase[phase_id] = candidate
        candidate_rows = list(candidate_by_phase.values())
        candidate_count = len(candidate_rows)
        if candidate_count > 1:
            # A name-level bridge can still point to several SRPE phases.
            # Make that ambiguity explicit; all such rows remain review-only
            # and never promote ownership or sales attribution.
            if match_method == "exact_spv_name_to_legal_observation":
                match_status = "matched_legal_spv_phase_group_ambiguous"
            elif match_method == "exact_vendor_name_to_project_site_crosswalk":
                match_status = "matched_vendor_phase_group_ambiguous"
        if not candidate_rows:
            candidate_rows = [{}]

        for candidate in candidate_rows:
            phase_id = _text(candidate.get("srpe_development_id"))
            srpe_record = srpe_by_id.get(phase_id, {})
            phase_name = _text(candidate.get("srpe_phase_name")) or _text(
                srpe_record.get("phase_name_en") or srpe_record.get("phase_name")
            )
            development_name = _text(
                candidate.get("srpe_development_name")
                or candidate.get("development_name_en")
            ) or _text(srpe_record.get("development_name_en") or srpe_record.get("development_name"))
            source_url = _text(
                candidate.get("ownership_source_url")
                or candidate.get("site_source_url")
                or record.get("source_url")
            )
            source_page = _text(
                candidate.get("ownership_source_page")
                or candidate.get("marketing_name")
                or record.get("printed_page")
                or record.get("pdf_page")
            )
            bridge_record_id = _text(
                candidate.get("observation_id")
                or candidate.get("source_record_id")
            )
            if not bridge_record_id and phase_id:
                bridge_record_id = f"{match_method}:{entity_key}:{phase_id}"
            bridge_source_url = _text(
                candidate.get("ownership_source_url")
                or candidate.get("site_source_url")
                or candidate.get("source_url")
            )
            bridge_source_page = _text(
                candidate.get("ownership_source_page")
                or candidate.get("site_source_page_or_detail")
                or candidate.get("marketing_name")
            )
            annual_pct = _number(record.get("attributable_equity_pct"))
            bridge_pct = _number(candidate.get("ownership_pct"))
            annual_date = _text(record.get("as_of_date") or record.get("report_period_end"))
            bridge_date = _text(candidate.get("ownership_observed_as_of"))
            if match_method == "exact_spv_name_to_legal_observation":
                if not bridge_date or bridge_pct is None or annual_pct is None:
                    consistency_status = "not_comparable_legal_observation"
                elif bridge_date == annual_date and bridge_pct == annual_pct:
                    consistency_status = "date_and_pct_consistent"
                elif bridge_date == annual_date:
                    consistency_status = "date_consistent_pct_conflict"
                elif bridge_pct == annual_pct:
                    consistency_status = "pct_consistent_date_differs"
                else:
                    consistency_status = "date_and_pct_differ"
            elif match_method == "exact_vendor_name_to_project_site_crosswalk":
                consistency_status = "not_comparable_site_vendor_bridge"
            else:
                consistency_status = "no_independent_bridge"
            source_list = [
                _text(record.get("annual_document_url")),
                _text(record.get("source_url")),
                bridge_source_url,
                _text(candidate.get("phase_identity_source_url")),
                _text(candidate.get("srpe_source_url")),
            ]
            source_urls_json = json.dumps(
                list(dict.fromkeys(value for value in source_list if value)),
                ensure_ascii=False,
            )
            evidence_context = _text(
                candidate.get("caveat")
                or candidate.get("holding_companies")
                or candidate.get("vendor_name")
                or "Annual Principal Subsidiaries snapshot; phase bridge remains review-only"
            )
            key = "|".join(
                str(value or "")
                for value in (
                    record.get("report_id"),
                    record.get("as_of_date") or record.get("report_period_end"),
                    spv_name,
                    phase_id,
                    match_status,
                    record.get("pdf_page"),
                )
            )
            rows.append(
                {
                    "crosswalk_id": hashlib.sha1(key.encode("utf-8")).hexdigest(),
                    "report_id": _text(record.get("report_id")),
                    "report_period_end": _text(record.get("report_period_end")),
                    "as_of_date": _text(record.get("as_of_date")) or _text(record.get("report_period_end")),
                    "spv_name": spv_name,
                    "attributable_equity_pct": _number(record.get("attributable_equity_pct")),
                    "business_description": _text(record.get("business_description")),
                    "annual_pdf_page": _text(record.get("pdf_page")),
                    "printed_page": _text(record.get("printed_page")),
                    "srpe_development_id": phase_id,
                    "srpe_development_name": development_name,
                    "srpe_phase_name": phase_name,
                    "candidate_count": candidate_count,
                    "match_status": match_status,
                    "match_method": match_method,
                    "ownership_status": "snapshot_only_non_promoting",
                    "effective_from": None,
                    "effective_to": None,
                    "annual_document_url": _text(record.get("annual_document_url")),
                    "source_url": source_url,
                    "source_page_or_detail": source_page,
                    "bridge_record_id": bridge_record_id,
                    "bridge_source_url": bridge_source_url,
                    "bridge_source_page_or_detail": bridge_source_page,
                    "source_urls_json": source_urls_json,
                    "annual_observation_consistency_status": consistency_status,
                    "evidence_context": evidence_context,
                    "last_verified_at": now,
                }
            )

    frame = pd.DataFrame(rows, columns=SHKP_ANNUAL_PRINCIPAL_SUBSIDIARY_CROSSWALK_COLUMNS)
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["crosswalk_id"]).sort_values(
            ["spv_name", "as_of_date", "srpe_development_id", "crosswalk_id"],
            kind="stable",
        ).reset_index(drop=True)
    raw_snapshots = [
        str(path)
        for source_frame in (annual, legal, site)
        for path in source_frame.attrs.get("raw_snapshots", [])
        if path
    ]
    source_urls = [
        str(url)
        for source_frame in (annual, legal, site)
        for url in source_frame.attrs.get("source_urls", [])
        if url
    ]
    frame.attrs.update(
        raw_snapshots=list(dict.fromkeys(raw_snapshots)),
        source_urls=list(dict.fromkeys(source_urls)),
        lineage_metadata={
            "lineage_type": "derived_shkp_annual_principal_subsidiary_phase_candidate_crosswalk",
            "rows": int(len(frame)),
            "entity_count": int(frame["spv_name"].nunique()) if not frame.empty else 0,
            "phase_count": int(frame["srpe_development_id"].dropna().nunique()) if not frame.empty else 0,
            "ownership_inference": False,
            "effective_interval_promotion": False,
            "sales_promotion": False,
            "unmatched_entities_retained": True,
        },
    )
    return frame


def build_shkp_completion_schedule_crosswalk(
    schedule_projects: pd.DataFrame,
    srpe_index: pd.DataFrame,
) -> pd.DataFrame:
    """Map dated schedule rows to SRPE candidates using bounded lot bridges."""
    if schedule_projects.empty:
        return pd.DataFrame(columns=SHKP_COMPLETION_SCHEDULE_CROSSWALK_COLUMNS)
    srpe_by_id = {
        str(row.get("development_id")): row
        for row in srpe_index.to_dict("records")
        if row.get("development_id") is not None
    }
    srpe_records = list(srpe_by_id.values())
    rows: list[dict[str, Any]] = []
    for schedule in schedule_projects.to_dict("records"):
        lot_text = _normalized_name(schedule.get("lot_description"))
        label_text = _normalized_name(schedule.get("project_label"))
        candidate_ids: tuple[str, ...] = ()
        method = "none"
        bounded_lot = False
        # The schedule has several rows for Tai Po Town Lot 253.  Restrict
        # phase mapping explicitly; an unexposed/future phase must not fall
        # back to every SRPE row named ``Sai Sha Residences``.
        if "taipotownlotno253" in lot_text:
            bounded_lot = True
            if "phase2a2b" in lot_text or "phases2a2b" in lot_text:
                candidate_ids = ("11305", "11345")
                method = "official_lot_phase_bridge"
            elif "phases1a21b" in lot_text or "phase1a21b" in lot_text:
                candidate_ids = ("10685", "10725")
                method = "official_lot_phase_bridge"
            else:
                method = "official_lot_phase_not_exposed"
        # Prefer exact configured lot/phase bridges.  Do not use geography as
        # a matcher: the completion schedule is itself not a legal-name table.
        if not bounded_lot:
            for hint, ids in SHKP_COMPLETION_SCHEDULE_SRPE_HINTS.items():
                hint_norm = _normalized_name(hint)
                if hint_norm and hint_norm in lot_text:
                    candidate_ids = ids
                    method = "official_lot_phase_bridge"
                    break
        if not candidate_ids and method == "none":
            for hint, ids in SHKP_COMPLETION_SCHEDULE_SRPE_HINTS.items():
                hint_norm = _normalized_name(hint)
                if hint_norm and hint_norm in label_text:
                    candidate_ids = ids
                    method = "official_project_label_bridge"
                    break
        if not candidate_ids and method == "none" and label_text:
            # Exact normalized SRPE project/phase name matches are useful for
            # rows such as an explicitly named phase, but stay reviewable.
            exact = []
            for srpe in srpe_records:
                names = {
                    _normalized_name(srpe.get("display_name")),
                    _normalized_name(srpe.get("development_name_en")),
                    _normalized_name(srpe.get("phase_name_en")),
                }
                if label_text in names or any(name and name in label_text for name in names):
                    exact.append(str(srpe.get("development_id")))
            candidate_ids = tuple(dict.fromkeys(exact))
            if candidate_ids:
                method = "srpe_project_label_exact"

        candidate_count = len(candidate_ids)
        if not candidate_ids:
            candidate_ids = (None,)
        for candidate_id in candidate_ids:
            srpe = srpe_by_id.get(str(candidate_id), {}) if candidate_id else {}
            if not candidate_id:
                match_status, confidence, lot_status = "unmatched", "unmatched", "unmatched"
            elif candidate_count > 1:
                match_status, confidence = "ambiguous", "medium"
                lot_status = "lot_phase_grouped"
            else:
                match_status, confidence = "matched_needs_review", "high"
                lot_status = "lot_exact" if "lot" in method else "label_exact"
            raw_interest = str(schedule.get("group_interest_raw") or "").strip()
            ownership_status = "schedule_jv_unresolved" if raw_interest.upper() == "JV" else (
                "schedule_numeric_reported" if pd.notna(schedule.get("group_interest_pct")) else "not_reported"
            )
            rows.append(
                {
                    "schedule_id": schedule.get("schedule_id"),
                    "schedule_date": schedule.get("schedule_date"),
                    "project_row_no": schedule.get("project_row_no"),
                    "lot_description": schedule.get("lot_description"),
                    "project_label": schedule.get("project_label"),
                    "group_interest_raw": raw_interest or None,
                    "group_interest_pct": schedule.get("group_interest_pct"),
                    "completion_window": schedule.get("completion_window"),
                    "srpe_development_id": candidate_id,
                    "srpe_development_name": srpe.get("development_name_en") or srpe.get("display_name"),
                    "srpe_phase_name": srpe.get("phase_name_en"),
                    "srpe_phase_no": srpe.get("phase_no"),
                    "srpe_address_en": srpe.get("address_en"),
                    "lot_match_status": lot_status,
                    "match_method": method,
                    "match_confidence": confidence,
                    "match_status": match_status,
                    "candidate_count": candidate_count,
                    "ownership_status": ownership_status,
                    "evidence_level": "official_completion_schedule_group_interest",
                    "document_url": schedule.get("document_url"),
                    "source_url": schedule.get("source_url"),
                    "matched_at": datetime.now(timezone.utc).isoformat(),
                }
            )
    return pd.DataFrame(rows, columns=SHKP_COMPLETION_SCHEDULE_CROSSWALK_COLUMNS)


def build_shkp_completion_schedule_ownership_audit(
    registry: pd.DataFrame,
    completion_crosswalk: pd.DataFrame,
) -> pd.DataFrame:
    """Compare schedule evidence with the curated ownership registry.

    This audit is intentionally non-promoting.  It identifies numeric
    support, JV conflicts and phase ambiguity without changing the sales gate.
    """
    rows: list[dict[str, Any]] = []
    registry_by_id = {
        str(record.get("srpe_development_id")): record
        for record in registry.to_dict("records")
        if record.get("srpe_development_id") is not None
    }
    for record in completion_crosswalk.to_dict("records"):
        candidate_id = str(record.get("srpe_development_id") or "")
        registry_row = registry_by_id.get(candidate_id, {})
        reg_pct = pd.to_numeric(registry_row.get("curated_registry_ownership_pct"), errors="coerce")
        schedule_pct = pd.to_numeric(record.get("group_interest_pct"), errors="coerce")
        raw = str(record.get("group_interest_raw") or "").upper()
        if record.get("match_status") == "unmatched":
            status = "no_schedule_match"
        elif raw == "JV":
            status = "schedule_jv_conflict" if pd.notna(reg_pct) else "schedule_jv_unresolved"
        elif record.get("match_status") == "ambiguous":
            status = "schedule_numeric_phase_ambiguous"
        elif pd.notna(reg_pct) and pd.notna(schedule_pct) and float(reg_pct) == float(schedule_pct):
            status = "schedule_numeric_supports_registry"
        else:
            status = "schedule_numeric_needs_reconciliation"
        rows.append(
            {
                "schedule_id": record.get("schedule_id"),
                "schedule_date": record.get("schedule_date"),
                "project_row_no": record.get("project_row_no"),
                "lot_description": record.get("lot_description"),
                "project_label": record.get("project_label"),
                "group_interest_raw": record.get("group_interest_raw"),
                "group_interest_pct": schedule_pct,
                "srpe_development_id": candidate_id or None,
                "srpe_phase_name": record.get("srpe_phase_name"),
                "match_status": record.get("match_status"),
                "candidate_count": record.get("candidate_count"),
                "registry_ownership_pct": reg_pct,
                "audit_status": status,
                "evidence_level": record.get("evidence_level"),
                "document_url": record.get("document_url"),
                "last_verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=SHKP_COMPLETION_SCHEDULE_AUDIT_COLUMNS)


def build_shkp_completion_schedule_ownership_evidence(
    completion_crosswalk: pd.DataFrame,
) -> pd.DataFrame:
    """Materialise dated, non-promoting Group-interest evidence records.

    Every row comes from a numeric completion-schedule observation that has a
    bounded SRPE candidate.  Grouped lot rows remain explicitly blocked for
    phase attribution; a one-to-one lot bridge still remains blocked until the
    legal SPV/JV document and effective-date history are reconciled.  ``JV``
    rows are retained as unresolved evidence rather than converted to a
    percentage.
    """
    if completion_crosswalk.empty:
        return pd.DataFrame(columns=SHKP_COMPLETION_SCHEDULE_EVIDENCE_COLUMNS)
    rows: list[dict[str, Any]] = []
    for record in completion_crosswalk.to_dict("records"):
        candidate_id = str(record.get("srpe_development_id") or "").strip()
        if not candidate_id:
            continue
        raw_interest = str(record.get("group_interest_raw") or "").strip()
        numeric_interest = pd.to_numeric(record.get("group_interest_pct"), errors="coerce")
        if not raw_interest and pd.isna(numeric_interest):
            continue
        supplemental = SHKP_COMPLETION_SCHEDULE_SUPPLEMENTAL_EVIDENCE.get(candidate_id, {})
        urls = [str(record.get("document_url") or "").strip()]
        if supplemental.get("source_url"):
            urls.append(str(supplemental["source_url"]).strip())
        urls = list(dict.fromkeys(value for value in urls if value))
        match_status = str(record.get("match_status") or "").strip()
        if raw_interest.upper() == "JV":
            evidence_status = "reported_jv"
            promotion_status = "blocked_jv_unresolved"
        elif match_status == "ambiguous":
            evidence_status = "reported_numeric_grouped_lot"
            promotion_status = "blocked_phase_group_ambiguous"
        elif match_status == "matched_needs_review":
            evidence_status = "reported_numeric_one_to_one_lot"
            promotion_status = "blocked_spv_reconciliation"
        else:
            evidence_status = "reported_numeric_unresolved_match"
            promotion_status = "blocked_phase_match"
        lot_bridge = (
            "exact_legal_lot_bridge_with_supplemental_brochure"
            if supplemental
            else "exact_schedule_lot_grouped_phase"
            if match_status == "ambiguous"
            else "schedule_lot_candidate"
        )
        context = (
            supplemental.get("evidence_context")
            if supplemental
            else f"SHKP completion schedule row {record.get('project_row_no')} reports Group's Interest={raw_interest} for {record.get('lot_description')}; SRPE phase mapping status={match_status}."
        )
        rows.append(
            {
                "evidence_id": f"{record.get('schedule_id')}:{record.get('project_row_no')}:{candidate_id}",
                "evidence_date": record.get("schedule_date"),
                "schedule_id": record.get("schedule_id"),
                "project_row_no": record.get("project_row_no"),
                "lot_description": record.get("lot_description"),
                "project_label": record.get("project_label"),
                "srpe_development_id": candidate_id,
                "srpe_development_name": record.get("srpe_development_name"),
                "srpe_phase_name": record.get("srpe_phase_name"),
                "srpe_phase_no": record.get("srpe_phase_no"),
                "group_interest_raw": raw_interest or None,
                "group_interest_pct": numeric_interest,
                "evidence_status": evidence_status,
                "legal_lot_bridge_status": lot_bridge,
                "ownership_promotion_status": promotion_status,
                "evidence_level": supplemental.get(
                    "evidence_level", "official_completion_schedule_group_interest"
                ),
                "evidence_context": context,
                "evidence_urls_json": json.dumps(urls, ensure_ascii=False),
                "source_url": record.get("source_url") or record.get("document_url"),
                "last_verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=SHKP_COMPLETION_SCHEDULE_EVIDENCE_COLUMNS)


def build_shkp_completion_schedule_reconciliation(
    completion_crosswalk: pd.DataFrame,
    annual_srpe_crosswalk: pd.DataFrame | None = None,
    site_vendor_crosswalk: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Join schedule, annual and vendor evidence without promoting ownership.

    A completion schedule publishes the Group's Interest for a lot/project
    row, while annual reports and first-hand project notices may expose a
    different label, vendor or JV description.  This function keeps those
    observations at their source grain and classifies the reconciliation
    state.  It intentionally never writes a ticker, ownership percentage or
    ``ownership_attribution_ready`` value.
    """
    if completion_crosswalk.empty:
        return pd.DataFrame(columns=SHKP_COMPLETION_SCHEDULE_RECONCILIATION_COLUMNS)

    annual_frame = annual_srpe_crosswalk if annual_srpe_crosswalk is not None else pd.DataFrame()
    site_frame = site_vendor_crosswalk if site_vendor_crosswalk is not None else pd.DataFrame()

    def _candidate_rows(frame: pd.DataFrame, candidate_id: str) -> list[dict[str, Any]]:
        if frame.empty or "srpe_development_id" not in frame.columns or not candidate_id:
            return []
        return [
            row
            for row in frame.to_dict("records")
            if str(row.get("srpe_development_id") or "").strip() == candidate_id
        ]

    def _annual_row(candidate_id: str) -> tuple[dict[str, Any], int]:
        records = _candidate_rows(annual_frame, candidate_id)
        if not records:
            return {}, 0
        # Prefer the latest report, then a row with a concrete match status.
        records.sort(
            key=lambda row: (
                str(row.get("report_period_end") or ""),
                1 if str(row.get("match_status") or "") == "matched_needs_review" else 0,
            ),
            reverse=True,
        )
        return records[0], len(records)

    def _site_row(candidate_id: str) -> tuple[dict[str, Any], int]:
        records = _candidate_rows(site_frame, candidate_id)
        if not records:
            return {}, 0
        # A parsed vendor fact is stronger than a dynamic page that only
        # exposes a notice.  Keep the full count as a coverage field.
        records.sort(
            key=lambda row: (
                1 if str(row.get("site_evidence_status") or "") == "found" else 0,
                1 if str(row.get("match_status") or "") == "matched" else 0,
                1 if str(row.get("match_status") or "") == "matched_needs_review" else 0,
            ),
            reverse=True,
        )
        return records[0], len(records)

    def _interest_equal(left: Any, right: Any) -> bool:
        left_num = pd.to_numeric(left, errors="coerce")
        right_num = pd.to_numeric(right, errors="coerce")
        return pd.notna(left_num) and pd.notna(right_num) and float(left_num) == float(right_num)

    rows: list[dict[str, Any]] = []
    for record in completion_crosswalk.to_dict("records"):
        candidate_id = str(record.get("srpe_development_id") or "").strip()
        annual, annual_count = _annual_row(candidate_id)
        site, site_count = _site_row(candidate_id)
        schedule_match = str(record.get("match_status") or "").strip()
        schedule_raw = str(record.get("group_interest_raw") or "").strip()
        annual_raw = str(annual.get("annual_group_interest_raw") or "").strip()
        site_status = str(site.get("site_evidence_status") or "").strip() or None
        holding = str(site.get("holding_companies") or "").strip()
        annual_pct = pd.to_numeric(annual.get("annual_group_interest_pct"), errors="coerce")
        schedule_pct = pd.to_numeric(record.get("group_interest_pct"), errors="coerce")

        if not candidate_id:
            reconciliation_status = "unmatched_schedule_row"
            promotion_status = "blocked_phase_match"
            required_next = "lot/phase bridge from SRPE, land-grant or project document"
        elif schedule_raw.upper() == "JV" or annual_raw.upper() == "JV":
            reconciliation_status = "jv_unresolved"
            promotion_status = "blocked_jv_unresolved"
            required_next = "dated JV agreement or numeric annual/HKEX disclosure plus phase effective date"
        elif schedule_match == "ambiguous":
            reconciliation_status = "grouped_phase_ambiguous"
            promotion_status = "blocked_phase_group_ambiguous"
            required_next = "phase-specific SPV/vendor or legal-lot evidence plus effective date"
        elif pd.notna(schedule_pct) and pd.notna(annual_pct):
            if _interest_equal(schedule_pct, annual_pct):
                reconciliation_status = (
                    "numeric_interest_corroborated_vendor_found"
                    if site_status == "found" and holding
                    else "numeric_interest_corroborated"
                )
                required_next = "legal SPV/shareholding and effective-date confirmation"
            else:
                reconciliation_status = "annual_schedule_interest_conflict"
                required_next = "reconcile annual versus schedule interest by phase and report date"
            promotion_status = "blocked_spv_reconciliation"
        elif site_status == "found" or holding:
            reconciliation_status = "vendor_evidence_without_numeric_pct"
            promotion_status = "blocked_spv_reconciliation"
            required_next = "numeric SPV/JV shareholding and effective-date evidence"
        else:
            reconciliation_status = "spv_effective_date_required"
            promotion_status = "blocked_spv_reconciliation"
            required_next = "legal SPV/shareholding and effective-date evidence"

        urls = [
            str(record.get("document_url") or "").strip(),
            str(annual.get("annual_document_url") or "").strip(),
            str(site.get("site_source_url") or "").strip(),
        ]
        urls = list(dict.fromkeys(value for value in urls if value))
        contexts = [
            f"Schedule Group's Interest={schedule_raw or 'not reported'}; match_status={schedule_match or 'unknown'}.",
        ]
        if annual:
            contexts.append(
                f"Latest annual evidence={annual.get('annual_project_label') or 'unnamed'} "
                f"({annual.get('report_period_end') or 'undated'}), "
                f"interest={annual_raw or 'not reported'}, status={annual.get('match_status') or 'unknown'}."
            )
        if site:
            contexts.append(
                f"Project-site vendor evidence={site.get('vendor_name') or 'not stated'}; "
                f"holding={holding or 'not stated'}; site_status={site_status or 'unknown'}."
            )
        contexts.append("No legal ownership promotion is made by this reconciliation layer.")

        rows.append(
            {
                "reconciliation_id": f"{record.get('schedule_id')}:{record.get('project_row_no')}:{candidate_id or 'unmatched'}",
                "schedule_id": record.get("schedule_id"),
                "schedule_date": record.get("schedule_date"),
                "project_row_no": record.get("project_row_no"),
                "lot_description": record.get("lot_description"),
                "project_label": record.get("project_label"),
                "completion_window": record.get("completion_window"),
                "group_interest_raw": schedule_raw or None,
                "group_interest_pct": schedule_pct,
                "srpe_development_id": candidate_id or None,
                "srpe_development_name": record.get("srpe_development_name"),
                "srpe_phase_name": record.get("srpe_phase_name"),
                "srpe_phase_no": record.get("srpe_phase_no"),
                "schedule_match_status": schedule_match or None,
                "schedule_candidate_count": record.get("candidate_count"),
                "annual_match_status": annual.get("match_status"),
                "annual_candidate_count": annual_count,
                "annual_project_label": annual.get("project_label"),
                "annual_report_id": annual.get("report_id"),
                "annual_report_period_end": annual.get("report_period_end"),
                "annual_group_interest_raw": annual_raw or None,
                "annual_group_interest_pct": annual_pct,
                "annual_document_url": annual.get("annual_document_url"),
                "site_match_status": site.get("match_status"),
                "site_candidate_count": site_count,
                "site_marketing_name": site.get("marketing_name"),
                "site_evidence_status": site_status,
                "vendor_name": site.get("vendor_name"),
                "holding_companies": holding or None,
                "site_source_url": site.get("site_source_url"),
                "reconciliation_status": reconciliation_status,
                "ownership_promotion_status": promotion_status,
                "required_next_evidence": required_next,
                "evidence_urls_json": json.dumps(urls, ensure_ascii=False),
                "evidence_context": " ".join(contexts),
                "last_verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=SHKP_COMPLETION_SCHEDULE_RECONCILIATION_COLUMNS)


def _phrase_context(text: str, phrase: str, window: int = 240) -> tuple[str, str]:
    """Return found/not-found plus a bounded context around a disclosure phrase."""
    position = text.lower().find(phrase.lower())
    if position < 0:
        return "not_found", ""
    start = max(0, text.rfind(".", 0, position) + 1)
    end = text.find(".", position)
    if end < 0:
        end = min(len(text), position + window)
    return "found", text[start : end + 1].strip()


def _classify_shkp_annual_row_geography(location: Any, page_geography: str) -> str:
    """Correct annual-table geography when a page mixes layout/section text.

    Older annual reports do not always print the same ``Property Business —
    Mainland`` header used by the newer parser.  The row's location cell is a
    stronger bounded signal for well-known mainland cities; otherwise retain
    the page-level classification and make no inference from a project name.
    """
    location_text = str(location or "")
    if re.search(
        r"\b(?:Shanghai|Guangzhou|Foshan|Suzhou|Zhongshan|Wuxi|Hangzhou|Chengdu|Beijing|Nanjing|Huadu|Panyu|Minhang|Lujiazui|Chancheng)\b",
        location_text,
        flags=re.IGNORECASE,
    ):
        return "Mainland"
    return page_geography


def _normalized_address(value: Any) -> str:
    """Normalize an address conservatively for candidate matching only."""
    text = str(value or "").lower()
    text = re.sub(r"\b(flat|unit|floor|room|tower|block)\s*[a-z0-9-]*\b", " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _safe_address_substring(needle: str, haystack: str) -> bool:
    """Return True when ``needle`` is a substring of ``haystack`` with a safe
    leading boundary.

    Normalized addresses collapse punctuation, so "38 Ma Sik Road" becomes
    ``38masikroad`` and "8 Ma Sik Road" becomes ``8masikroad``.  A plain
    substring check would wrongly match the latter against the former
    (house-number prefix swallowing), which is exactly how the One Innovale
    rows picked up the Noble Hill annual label.  A leading digit is only a
    safe boundary when the character before it in the haystack is not a
    digit, so whole street numbers cannot partially match.
    """
    if not needle:
        return False
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            return False
        leading = haystack[index - 1] if index > 0 else ""
        if needle[0].isdigit() and leading.isdigit():
            start = index + 1
            continue
        return True


def build_shkp_bd_crosswalk(
    shkp_crosswalk: pd.DataFrame,
    srpe_index: pd.DataFrame,
    bd_events: pd.DataFrame,
) -> pd.DataFrame:
    """Match SHKP/SRPE candidates to current BD project-stage rows.

    This is intentionally an address candidate join.  Exact address matches
    are marked ``matched_needs_review`` and one-to-many matches remain
    ``ambiguous``; no BD event is promoted to a listed-company ownership fact.
    """
    srpe_by_id = {
        str(row.get("development_id")): row
        for row in srpe_index.to_dict("records")
        if row.get("development_id") is not None
    }
    srpe_address_groups: dict[str, set[str]] = {}
    for srpe_id, srpe in srpe_by_id.items():
        address_key = _normalized_address(srpe.get("address_en"))
        if address_key:
            srpe_address_groups.setdefault(address_key, set()).add(srpe_id)
    bd_records = bd_events.to_dict("records") if not bd_events.empty else []
    bd_source_url = str(bd_events.attrs.get("source_url") or "https://www.bd.gov.hk/en/whats-new/monthly-digests/index.html")
    rows: list[dict[str, Any]] = []
    for candidate in shkp_crosswalk.to_dict("records"):
        development_id = str(candidate.get("srpe_development_id") or "")
        srpe = srpe_by_id.get(development_id, {})
        srpe_address = str(srpe.get("address_en") or "").strip()
        srpe_key = _normalized_address(srpe_address)
        matches: list[tuple[dict[str, Any], str]] = []
        if srpe_key:
            for event in bd_records:
                bd_address = str(event.get("site_address") or "").strip()
                bd_key = _normalized_address(bd_address)
                if not bd_key:
                    continue
                if bd_key == srpe_key:
                    matches.append((event, "address_exact"))
                elif len(srpe_key) >= 10 and (srpe_key in bd_key or bd_key in srpe_key):
                    matches.append((event, "address_contains"))

        candidate_count = len(matches)
        if not matches:
            matches = [({}, "none")]
        phase_candidate_count = len(srpe_address_groups.get(srpe_key, set())) if srpe_key else 0
        for event, method in matches:
            phase_group_ambiguous = method != "none" and phase_candidate_count > 1
            status = "unmatched" if method == "none" else (
                "ambiguous" if candidate_count > 1 or phase_group_ambiguous else "matched_needs_review"
            )
            if phase_group_ambiguous:
                method = f"{method}+phase_group_ambiguous"
            rows.append(
                {
                    "marketing_name": candidate.get("marketing_name"),
                    "srpe_development_id": development_id or None,
                    "srpe_phase_name": candidate.get("srpe_phase_name"),
                    "srpe_address_en": srpe_address or None,
                    "crosswalk_match_status": candidate.get("match_status"),
                    "bd_permit_stage": event.get("permit_stage"),
                    "bd_permit_number": event.get("permit_number"),
                    "bd_site_address": event.get("site_address"),
                    "bd_domestic_units_count": event.get("domestic_units_count", event.get("estimated_units")),
                    "bd_usable_floor_area_sqm": event.get("usable_floor_area_sqm"),
                    "bd_parser_confidence": event.get("parser_confidence"),
                    "bd_match_method": method,
                    "bd_match_status": status,
                    "bd_candidate_count": candidate_count,
                    "bd_phase_candidate_count": phase_candidate_count,
                    "shkp_source_url": candidate.get("shkp_source_url"),
                    "srpe_source_url": candidate.get("srpe_source_url"),
                    "bd_source_url": bd_source_url,
                    "matched_at": candidate.get("matched_at") or datetime.now(timezone.utc).isoformat(),
                }
            )
    return pd.DataFrame(rows, columns=BD_CROSSWALK_COLUMNS)


def fetch_shkp_supporting_source_catalog() -> pd.DataFrame:
    """Return the official LandsD/TPB/BD/SRPE evidence contracts for SHKP."""
    frame = pd.DataFrame(SHKP_SUPPORTING_SOURCES, columns=SUPPORTING_SOURCE_COLUMNS)
    payload = frame.to_json(orient="records", force_ascii=False)
    raw_path = save_raw_snapshot(
        "shkp_supporting_source_catalog",
        payload,
        file_ext="json",
        source_url="static://shkp-supporting-source-catalog",
    )
    frame.attrs.update(
        raw_snapshot=str(raw_path),
        source_url="static://shkp-supporting-source-catalog",
        raw_snapshots=[str(raw_path)],
        source_urls=frame["source_url"].drop_duplicates().tolist(),
        lineage_metadata={"lineage_type": "static_official_source_contract_catalog"},
    )
    return frame


def build_shkp_ownership_evidence_audit(
    registry: pd.DataFrame,
    annual_report_projects: pd.DataFrame,
) -> pd.DataFrame:
    """Compare curated registry ownership against annual-report table evidence.

    The comparison is deliberately one-way: an annual report can flag a
    registry conflict or corroborate a numeric percentage, but a name match
    never creates a new ownership record.  Unmatched registry rows remain
    visible with ``no_annual_match``.
    """
    annual = annual_report_projects[
        annual_report_projects.get("evidence_type", pd.Series(dtype=str)).eq("handover_table")
    ].copy() if not annual_report_projects.empty else pd.DataFrame()
    annual = annual[annual.get("geography", pd.Series(dtype=str)).eq("Hong Kong")] if not annual.empty else annual
    rows: list[dict[str, Any]] = []

    def _split_values(value: Any) -> list[str]:
        return [part.strip() for part in str(value or "").split("|") if part.strip()]

    for record in registry.to_dict("records"):
        # The original audit consumed a small project registry with
        # ``stock_code``/``project_name_en`` fields.  The live phase registry
        # uses ``curated_stock_codes`` and descriptive SRPE name fields; adapt
        # both schemas instead of silently returning a zero-row core layer.
        stock_candidates = _split_values(record.get("stock_code")) or _split_values(
            record.get("curated_stock_codes")
        )
        stock_code = next(
            (value.zfill(4) for value in stock_candidates if value.isdigit()),
            "",
        )
        if not stock_code:
            # The live SRPE registry is scoped to SHKP evidence but does not
            # repeat a ticker on every phase.  Presence of an explicit SHKP
            # listing/annual/completion label is enough to audit the row; it
            # is not treated as a numeric ownership assertion.
            has_shkp_evidence = any(
                _split_values(record.get(field))
                for field in (
                    "shkp_marketing_names",
                    "annual_project_labels",
                    "completion_schedule_project_labels",
                )
            )
            if has_shkp_evidence:
                stock_code = "0016"
        if stock_code != "0016":
            continue
        project_name = str(record.get("project_name_en") or "").strip()
        if not project_name:
            project_name = " ".join(
                value
                for value in (
                    str(record.get("development_name_en") or "").strip(),
                    str(record.get("phase_name_en") or "").strip(),
                )
                if value
            )
        aliases = _split_values(record.get("project_aliases"))
        aliases.extend(_split_values(record.get("shkp_marketing_names")))
        aliases.extend(_split_values(record.get("annual_project_labels")))
        aliases.extend(_split_values(record.get("completion_schedule_project_labels")))
        aliases = list(dict.fromkeys(value for value in aliases if value != project_name))
        registry_ownership = record.get("ownership_pct")
        if registry_ownership is None:
            registry_ownership = record.get("curated_registry_ownership_pct")
        last_verified_date = record.get("last_verified_date") or record.get("last_verified_at")
        candidates: list[tuple[dict[str, Any], str]] = []
        for alias in [project_name, *aliases]:
            alias_key = _normalized_name(alias)
            if len(alias_key) < 5:
                continue
            for project in annual.to_dict("records"):
                project_key = _normalized_name(project.get("project_label"))
                if alias_key and (alias_key in project_key or project_key in alias_key):
                    candidates.append((project, alias))
        # Keep the longest alias/most specific project evidence when a broad
        # alias (e.g. PARK YOHO) and a phase-specific alias both match.
        if candidates:
            project, alias = sorted(candidates, key=lambda item: len(_normalized_name(item[1])), reverse=True)[0]
            registry_pct = pd.to_numeric(registry_ownership, errors="coerce")
            annual_pct = pd.to_numeric(project.get("group_interest_pct"), errors="coerce")
            raw_interest = str(project.get("group_interest_raw") or "").strip()
            if raw_interest.upper() == "JV":
                status = "unresolved_jv"
            elif pd.notna(registry_pct) and pd.notna(annual_pct) and float(registry_pct) == float(annual_pct):
                status = "consistent_numeric"
            elif pd.notna(registry_pct) and pd.notna(annual_pct):
                status = "conflict_numeric"
            else:
                status = "annual_interest_unresolved"
            rows.append(
                {
                    "stock_code": stock_code,
                    "listed_company_en": record.get("listed_company_en") or "Sun Hung Kai Properties Limited",
                    "registry_project_name": project_name,
                    "registry_alias": alias,
                    "registry_ownership_pct": registry_pct,
                    "annual_project_label": project.get("project_label"),
                    "annual_group_interest_raw": raw_interest,
                    "annual_group_interest_pct": annual_pct,
                    "annual_page_number": project.get("page_number"),
                    "audit_status": status,
                    "evidence_level": "annual_report_handover_table",
                    "annual_document_url": project.get("document_url"),
                    "last_verified_date": last_verified_date,
                }
            )
        else:
            rows.append(
                {
                    "stock_code": stock_code,
                    "listed_company_en": record.get("listed_company_en") or "Sun Hung Kai Properties Limited",
                    "registry_project_name": project_name,
                    "registry_alias": None,
                    "registry_ownership_pct": pd.to_numeric(registry_ownership, errors="coerce"),
                    "annual_project_label": None,
                    "annual_group_interest_raw": None,
                    "annual_group_interest_pct": None,
                    "annual_page_number": None,
                    "audit_status": "no_annual_match",
                    "evidence_level": "registry_only",
                    "annual_document_url": None,
                    "last_verified_date": last_verified_date,
                }
            )
    return pd.DataFrame(rows, columns=OWNERSHIP_AUDIT_COLUMNS)


def build_shkp_phase_evidence_quality_audit(
    annual_report_projects: pd.DataFrame,
    srpe_index: pd.DataFrame,
    planning_facts: pd.DataFrame,
) -> pd.DataFrame:
    """Build a phase-level evidence queue without inferring legal ownership.

    Annual-report labels, SRPE phase IDs, and LandsD consent rows answer
    different questions.  This audit keeps their intersection visible and
    explicitly flags phase conflicts, same-lot ambiguity, and unresolved JV
    language.  A planning row's ``Parent Co. or Holding Co./Developer`` text
    is retained as source evidence only; it never becomes an ownership
    percentage or a legal owner field.
    """
    if annual_report_projects.empty:
        return pd.DataFrame(columns=PHASE_EVIDENCE_AUDIT_COLUMNS)
    srpe_records = srpe_index.to_dict("records") if not srpe_index.empty else []
    planning_records = planning_facts.to_dict("records") if not planning_facts.empty else []
    annual = annual_report_projects.copy()
    if "geography" in annual.columns:
        annual = annual[annual["geography"].astype(str).str.casefold().isin({"hong kong", "kai tak", "sai sha", "kwu tung", "yuen long", "tuen mun west"})]

    rows: list[dict[str, Any]] = []
    for report_row in annual.to_dict("records"):
        label = str(report_row.get("project_label") or "").strip()
        label_norm = _normalized_name(label)
        # Split future disclosure labels such as "Cullinan Sky Phase 2 /
        # Cullinan Harbour Phase 2" into independently searchable name parts.
        name_parts = [part.strip() for part in re.split(r"/|;|\band\b", label, flags=re.IGNORECASE) if part.strip()]
        name_parts_norm = [_normalized_name(part) for part in name_parts]
        requested_phases = _phase_tokens(label)
        annual_base = re.split(r"\bPHASES?\b", label, maxsplit=1, flags=re.IGNORECASE)[0]
        annual_base_norm = _normalized_name(annual_base)

        candidates: list[dict[str, Any]] = []
        for candidate in srpe_records:
            candidate_id = str(candidate.get("development_id") or "")
            if not candidate_id:
                continue
            candidate_text = " ".join(
                str(candidate.get(field) or "")
                for field in ("display_name", "development_name_en", "phase_name_en", "phase_name_zh")
            )
            candidate_norm = _normalized_name(candidate_text)
            candidate_phase_tokens = _phase_tokens(
                " ".join(str(candidate.get(field) or "") for field in ("phase_name_en", "phase_no"))
            )
            exact_name = bool(label_norm and label_norm in {_normalized_name(candidate.get(field)) for field in ("display_name", "development_name_en", "phase_name_en")})
            base_name = bool(annual_base_norm and annual_base_norm in candidate_norm)
            part_base_norms = [
                _normalized_name(re.split(r"\bPHASES?\b", part, maxsplit=1, flags=re.IGNORECASE)[0])
                for part in name_parts
            ]
            part_base_name = any(
                len(part_norm) >= 6 and part_norm in candidate_norm
                for part_norm in part_base_norms
            )
            part_name = any(
                len(part_norm) >= 6 and part_norm in candidate_norm
                for part_norm in name_parts_norm
            )
            address_match = False
            annual_location = _normalized_address(report_row.get("location"))
            candidate_address = _normalized_address(candidate.get("address_en"))
            if annual_location and candidate_address:
                address_match = annual_location == candidate_address or (
                    len(candidate_address) >= 8 and (candidate_address in annual_location or annual_location in candidate_address)
                )
            phase_match = bool(requested_phases & candidate_phase_tokens) if requested_phases else True
            if exact_name or ((base_name or part_name or part_base_name or address_match) and (phase_match or not requested_phases or address_match)):
                candidates.append(candidate)

        # Search source planning rows by the annual/base/project labels.  A
        # hit is evidence that the lot/developer text is relevant, not proof
        # that every SRPE phase on that lot is owned by SHKP.
        planning_hits: list[dict[str, Any]] = []
        for planning in planning_records:
            planning_text = " ".join(
                str(planning.get(field) or "")
                for field in ("development_name_raw", "lot_no_raw", "parent_or_holding_company_or_developer_raw")
            )
            planning_norm = _normalized_name(planning_text)
            if any(
                token and token in planning_norm
                for token in [annual_base_norm, *name_parts_norm, *part_base_norms]
                if len(token) >= 6
            ):
                planning_hits.append(planning)

        raw_interest = str(report_row.get("group_interest_raw") or "").strip()
        annual_pct = pd.to_numeric(report_row.get("group_interest_pct"), errors="coerce")
        if raw_interest.upper() == "JV":
            ownership_status = "annual_jv_unresolved"
        elif pd.notna(annual_pct):
            ownership_status = "annual_numeric_reported"
        else:
            ownership_status = "not_reported"

        if not candidates:
            candidates = [{}]
        for candidate in candidates:
            candidate_id = str(candidate.get("development_id") or "") or None
            phase_name = candidate.get("phase_name_en") or candidate.get("phase_name_zh")
            phase_tokens = _phase_tokens(" ".join(str(candidate.get(field) or "") for field in ("phase_name_en", "phase_no")))
            if candidate_id and requested_phases and phase_tokens and not (requested_phases & phase_tokens):
                phase_status = "phase_conflict"
            elif requested_phases and not phase_tokens:
                phase_status = "phase_not_exposed"
            elif candidate_id and requested_phases:
                phase_status = "phase_supported"
            else:
                phase_status = "phase_not_requested"

            # Match planning rows to the candidate's phase/name when
            # possible; otherwise keep all relevant lot rows and expose the
            # ambiguity instead of silently assigning one.
            candidate_name_tokens = [
                _normalized_name(candidate.get(field))
                for field in ("display_name", "development_name_en", "phase_name_en")
                if _normalized_name(candidate.get(field))
            ]
            candidate_hits = [
                planning for planning in planning_hits
                if any(token in _normalized_name(planning.get("development_name_raw")) for token in candidate_name_tokens if len(token) >= 6)
            ] if candidate_id else []
            relevant_hits = candidate_hits or planning_hits
            if relevant_hits and len(candidates) > 1:
                candidate_status = "candidate_supported_ambiguous"
            elif relevant_hits:
                candidate_status = "candidate_supported"
            elif candidate_id:
                candidate_status = "srpe_candidate_not_confirmed_by_planning"
            else:
                candidate_status = "unmatched"

            evidence_urls: list[str] = []
            if report_row.get("document_url"):
                evidence_urls.append(str(report_row["document_url"]))
            evidence_urls.extend(
                str(hit.get("document_url")) for hit in relevant_hits if hit.get("document_url")
            )
            evidence_urls = list(dict.fromkeys(evidence_urls))
            pages = [hit.get("page_number") for hit in relevant_hits if hit.get("page_number") is not None]
            entity_values = list(dict.fromkeys(
                str(hit.get("parent_or_holding_company_or_developer_raw"))
                for hit in relevant_hits
                if hit.get("parent_or_holding_company_or_developer_raw")
            ))
            lot_values = list(dict.fromkeys(
                str(hit.get("lot_no_raw")) for hit in relevant_hits if hit.get("lot_no_raw")
            ))
            dates = [str(hit.get("consent_or_approval_date")) for hit in relevant_hits if hit.get("consent_or_approval_date")]
            if phase_status == "phase_conflict":
                summary = "Annual phase qualifier conflicts with the SRPE candidate phase; keep manual review status."
            elif candidate_status == "candidate_supported_ambiguous":
                summary = "Official planning rows support the project/lot, but multiple SRPE phases share the candidate evidence."
            elif candidate_status == "candidate_supported":
                summary = "Official planning row name/lot and SRPE candidate are consistent; ownership percentage remains separate."
            elif candidate_id:
                summary = "SRPE candidate retained, but no bounded planning row confirmed this phase."
            else:
                summary = "No conservative SRPE candidate found; retain annual disclosure as an unlinked project label."
            rows.append(
                {
                    "evidence_case_id": f"{report_row.get('report_id')}:{label}:{candidate_id or 'unmatched'}",
                    "report_id": report_row.get("report_id"),
                    "project_label": label or None,
                    "project_state": report_row.get("project_state"),
                    "annual_location": report_row.get("location"),
                    "annual_group_interest_raw": raw_interest or None,
                    "annual_group_interest_pct": annual_pct,
                    "srpe_development_id": candidate_id,
                    "srpe_development_name": candidate.get("development_name_en") or candidate.get("display_name"),
                    "srpe_phase_name": phase_name,
                    "srpe_phase_no": candidate.get("phase_no"),
                    "planning_lot_no": " | ".join(lot_values) or None,
                    "planning_entity_raw": " | ".join(entity_values) or None,
                    "planning_consent_date": ", ".join(dict.fromkeys(dates)) or None,
                    "candidate_status": candidate_status,
                    "phase_status": phase_status,
                    "ownership_status": ownership_status,
                    "evidence_summary": summary,
                    "evidence_urls_json": json.dumps(evidence_urls, ensure_ascii=False),
                    "evidence_pages_json": json.dumps(pages, ensure_ascii=False),
                    "source_count": len(evidence_urls),
                    "last_verified_at": datetime.now(timezone.utc).isoformat(),
                }
            )
    return pd.DataFrame(rows, columns=PHASE_EVIDENCE_AUDIT_COLUMNS)


def build_shkp_project_registry(
    srpe_index: pd.DataFrame,
    shkp_crosswalk: pd.DataFrame | None = None,
    annual_srpe_crosswalk: pd.DataFrame | None = None,
    planning_crosswalk: pd.DataFrame | None = None,
    *,
    pilot_registry: pd.DataFrame | None = None,
    srpe_manifest: pd.DataFrame | None = None,
    pipeline_crosswalk: pd.DataFrame | None = None,
    bd_crosswalk: pd.DataFrame | None = None,
    completion_schedule_crosswalk: pd.DataFrame | None = None,
    legal_ownership_observations: pd.DataFrame | None = None,
    phase_attribution_decisions: pd.DataFrame | None = None,
    history_milestone_crosswalk: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build one auditable row per SRPE development/phase.

    This is an evidence registry, not a legal ownership table.  It makes the
    current SHKP directory, annual-report labels, bounded LandsD/TPB facts,
    and the explicit SRPE pilot boundary queryable from one stable key while
    retaining source-specific statuses.  A null or unresolved field is
    intentional: absence of a candidate is never promoted to zero ownership,
    zero pipeline, or zero sales.
    """
    empty = pd.DataFrame(columns=SHKP_PROJECT_REGISTRY_COLUMNS)
    if srpe_index.empty:
        return empty

    shkp = shkp_crosswalk if shkp_crosswalk is not None else pd.DataFrame()
    annual = annual_srpe_crosswalk if annual_srpe_crosswalk is not None else pd.DataFrame()
    planning = planning_crosswalk if planning_crosswalk is not None else pd.DataFrame()
    pilot = pilot_registry if pilot_registry is not None else pd.DataFrame()
    manifest = srpe_manifest if srpe_manifest is not None else pd.DataFrame()
    pipeline = pipeline_crosswalk if pipeline_crosswalk is not None else pd.DataFrame()
    bd = bd_crosswalk if bd_crosswalk is not None else pd.DataFrame()
    completion = completion_schedule_crosswalk if completion_schedule_crosswalk is not None else pd.DataFrame()
    legal_ownership = legal_ownership_observations if legal_ownership_observations is not None else pd.DataFrame()
    attribution_decisions = phase_attribution_decisions if phase_attribution_decisions is not None else pd.DataFrame()
    history_crosswalk = history_milestone_crosswalk if history_milestone_crosswalk is not None else pd.DataFrame()

    def _records_for(frame: pd.DataFrame, key: str, value: str) -> list[dict[str, Any]]:
        if frame.empty or key not in frame.columns:
            return []
        return frame[frame[key].astype("string").eq(value)].to_dict("records")

    def _unique_text(records: list[dict[str, Any]], field: str) -> list[str]:
        return list(dict.fromkeys(
            str(record.get(field)).strip()
            for record in records
            if record.get(field) is not None and str(record.get(field)).strip()
        ))

    def _status(records: list[dict[str, Any]], field: str = "match_status") -> str:
        values = {str(record.get(field) or "").strip() for record in records}
        values.discard("")
        for candidate in ("ambiguous", "matched_needs_review", "matched", "unmatched", "not_evaluated"):
            if candidate in values:
                return candidate
        return "not_observed"

    def _numeric_values(records: list[dict[str, Any]], field: str) -> list[float]:
        values = pd.to_numeric(pd.Series([record.get(field) for record in records]), errors="coerce").dropna()
        return list(dict.fromkeys(float(value) for value in values.tolist()))

    def _scalar_or_json(values: list[Any]) -> Any:
        if not values:
            return None
        if len(values) == 1:
            return values[0]
        return json.dumps(values, ensure_ascii=False)

    def _phase_pipeline_status(
        shkp_records: list[dict[str, Any]],
        annual_records: list[dict[str, Any]],
        planning_records: list[dict[str, Any]],
        pipeline_records: list[dict[str, Any]],
    ) -> str:
        statuses: list[str] = []
        if shkp_records:
            statuses.append("current_website_listing")
        for value in _unique_text(annual_records, "project_state"):
            if value:
                statuses.append(value)
        if planning_records and not statuses:
            statuses.append("planning_evidence_only")
        for value in _unique_text(pipeline_records, "pipeline_status"):
            if value:
                statuses.append(value)
        if not statuses:
            statuses.append("srpe_index_only")
        return "|".join(dict.fromkeys(statuses))

    def _universe_status(
        shkp_records: list[dict[str, Any]],
        annual_records: list[dict[str, Any]],
        pipeline_records: list[dict[str, Any]],
        completion_records: list[dict[str, Any]],
        legal_records: list[dict[str, Any]],
        history_records: list[dict[str, Any]],
    ) -> tuple[str, list[str]]:
        """Classify discovery evidence without inferring ownership.

        ``current_candidate`` means the phase is on the current SHKP
        residential directory with an exact crosswalk.  Historical annual or
        schedule ambiguity is retained in its own match-status columns and
        must not erase the fact that the phase is currently listed.  An
        unresolved current-directory match remains ``review_required``.
        ``historical_candidate`` is reserved for non-current evidence that is
        currently unambiguous; ``not_observed`` means only the SRPE parent row
        is known.  This is a universe-discovery status, not an attribution
        decision.
        """
        evidence_types: list[str] = []
        if shkp_records:
            evidence_types.append("current_shkp_directory")
        if annual_records:
            evidence_types.append("shkp_annual_report")
        if pipeline_records:
            evidence_types.append("shkp_pipeline_disclosure")
        if completion_records:
            evidence_types.append("shkp_completion_schedule")
        if legal_records:
            evidence_types.append("legal_ownership_snapshot")
        if history_records:
            evidence_types.append("shkp_history_milestones")
        statuses = {
            str(record.get("match_status") or "").strip()
            for record in [*shkp_records, *annual_records, *pipeline_records, *completion_records, *history_records]
        }
        statuses.discard("")
        unresolved = bool(statuses & {"ambiguous", "matched_needs_review", "unmatched"})
        current_statuses = {
            str(record.get("match_status") or "").strip()
            for record in shkp_records
        }
        current_statuses.discard("")
        current_unresolved = bool(current_statuses & {"ambiguous", "matched_needs_review", "unmatched"})
        if shkp_records and "matched" in current_statuses and not current_unresolved:
            status = "current_candidate"
        elif evidence_types and not unresolved:
            status = "historical_candidate"
        elif evidence_types:
            status = "review_required"
        else:
            status = "not_observed"
        return status, evidence_types

    rows: list[dict[str, Any]] = []
    for srpe_record in srpe_index.to_dict("records"):
        srpe_id = str(srpe_record.get("development_id") or "").strip()
        if not srpe_id:
            continue
        curated_non_shkp = SHKP_CURATED_NON_SHKP_SRPE_PHASES.get(srpe_id)
        shkp_records = _records_for(shkp, "srpe_development_id", srpe_id)
        # Curated exclusions verified against official developer records
        # (2026-08-09).  The ambiguous annual label match fanned out over
        # shared-lot addresses (Lohas Park) or a partial address substring
        # (One Innovale / Noble Hill).  Suppress the SHKP annual evidence so
        # the phase cannot be promoted or pollute the sales model; the
        # exclusion reason is retained as explicit review context.
        annual_records = (
            []
            if curated_non_shkp
            else _records_for(annual, "srpe_development_id", srpe_id)
        )
        planning_records = _records_for(planning, "srpe_development_id", srpe_id)
        pipeline_records = _records_for(pipeline, "srpe_development_id", srpe_id)
        bd_records = _records_for(bd, "srpe_development_id", srpe_id)
        completion_records = _records_for(completion, "srpe_development_id", srpe_id)
        legal_records = _records_for(legal_ownership, "srpe_development_id", srpe_id)
        decision_records = _records_for(attribution_decisions, "srpe_development_id", srpe_id)
        history_records = _records_for(history_crosswalk, "srpe_development_id", srpe_id)
        observed_pipeline_records = [
            record for record in pipeline_records
            if str(record.get("evidence_status") or "").strip().lower() == "found"
        ]
        pilot_records = []
        if not pilot.empty:
            for key in ("srpe_dev_id", "srpe_development_id"):
                if key in pilot.columns:
                    pilot_records.extend(
                        pilot[pilot[key].astype("string").eq(srpe_id)].to_dict("records")
                    )
        # Preserve one curated phase row even if both legacy ID columns match.
        pilot_records = list({str(record.get("project_id")): record for record in pilot_records}.values())
        manifest_records = _records_for(manifest, "srpe_development_id", srpe_id)

        shkp_names = _unique_text(shkp_records, "marketing_name")
        annual_labels = _unique_text(annual_records, "project_label")
        annual_states = _unique_text(annual_records, "project_state")
        annual_raw_interest = _unique_text(annual_records, "annual_group_interest_raw")
        annual_pct = _numeric_values(annual_records, "annual_group_interest_pct")
        completion_dates = _unique_text(completion_records, "schedule_date")
        completion_windows = _unique_text(completion_records, "completion_window")
        completion_lots = _unique_text(completion_records, "lot_description")
        completion_labels = _unique_text(completion_records, "project_label")
        completion_raw_interest = _unique_text(completion_records, "group_interest_raw")
        completion_pct = _numeric_values(completion_records, "group_interest_pct")
        history_years = _unique_text(history_records, "milestone_year")
        history_summaries = _unique_text(history_records, "milestone_summary")
        planning_lots = _unique_text(planning_records, "lot_no_raw")
        planning_dates = _unique_text(planning_records, "planning_consent_date")
        planning_entities = _unique_text(planning_records, "parent_or_developer_raw")
        legal_spvs = _unique_text(legal_records, "subsidiary_spv_name")
        legal_observed_pct = _numeric_values(legal_records, "ownership_pct")
        legal_observed_dates = _unique_text(legal_records, "ownership_observed_as_of")
        legal_observation_status = (
            "numeric_spv_snapshot_needs_effective_interval"
            if legal_records and legal_observed_pct
            else "not_observed"
        )

        curated_pct = _numeric_values(pilot_records, "ownership_pct")
        if any(value.upper() == "JV" for value in annual_raw_interest):
            ownership_status = "annual_jv_unresolved"
        elif curated_pct and annual_pct and set(curated_pct) == set(annual_pct):
            ownership_status = "consistent_numeric"
        elif annual_pct:
            ownership_status = "annual_numeric_unreconciled"
        elif curated_pct:
            ownership_status = "curated_registry_only"
        else:
            ownership_status = "not_verified"

        # Do not infer a continuous ownership window from annual-report or
        # completion-schedule snapshots.  An interval is only eligible when a
        # phase-scoped evidence row explicitly carries numeric ownership,
        # both endpoints, and a non-blocked promotion status.
        # Only the separately reviewed decision layer may open the interval
        # gate.  Legal snapshots, title events and curated pilot rows remain
        # evidence inputs but are never treated as approved decisions.
        interval_records = decision_records
        interval_ready_records = [
            record for record in interval_records
            if _record_has_phase_specific_effective_interval(record)
        ]
        interval_pct = _numeric_values(interval_ready_records, "ownership_pct")
        interval_pct_consistent = bool(interval_pct) and (
            (not annual_pct or set(interval_pct) == set(annual_pct))
            and (not curated_pct or set(interval_pct) == set(curated_pct))
        )
        effective_from_values = _interval_values(interval_ready_records, "effective_from")
        effective_to_values = _interval_values(interval_ready_records, "effective_to")
        interval_evidence_types = list(dict.fromkeys(
            str(record.get("ownership_interval_evidence_type") or record.get("evidence_type"))
            for record in interval_ready_records
            if record.get("ownership_interval_evidence_type") or record.get("evidence_type")
        ))
        attribution_decision_ids = list(dict.fromkeys(
            str(record.get("ownership_attribution_decision_id") or record.get("attribution_decision_id") or record.get("decision_id"))
            for record in interval_ready_records
            if record.get("ownership_attribution_decision_id") or record.get("attribution_decision_id") or record.get("decision_id")
        ))
        interval_promotion_statuses = list(dict.fromkeys(
            str(record.get("ownership_interval_promotion_status") or record.get("promotion_status"))
            for record in interval_ready_records
            if record.get("ownership_interval_promotion_status") or record.get("promotion_status")
        ))
        interval_ready = bool(interval_ready_records)
        if interval_ready and interval_pct_consistent:
            ownership_interval_status = "phase_specific_bounded_interval"
        elif interval_ready:
            ownership_interval_status = "blocked_interval_pct_mismatch"
        elif legal_observed_pct or curated_pct:
            ownership_interval_status = "blocked_effective_interval"
        else:
            ownership_interval_status = "not_observed"

        completion_raw_upper = {value.upper() for value in completion_raw_interest}
        if "JV" in completion_raw_upper:
            completion_ownership_status = "schedule_jv_unresolved"
        elif completion_pct:
            completion_ownership_status = "schedule_numeric_reported"
        else:
            completion_ownership_status = "not_observed"

        source_urls: list[str] = []
        for record in [srpe_record, *shkp_records, *annual_records, *planning_records, *pipeline_records, *bd_records, *completion_records, *legal_records, *decision_records, *history_records]:
            for field in ("source_url", "shkp_source_url", "srpe_source_url", "annual_document_url", "document_url", "bd_source_url", "ownership_source_url", "phase_identity_source_url"):
                value = record.get(field)
                if value and str(value).strip() and str(value).strip() not in source_urls:
                    source_urls.append(str(value).strip())

        shkp_status = _status(shkp_records)
        annual_status = _status(annual_records)
        planning_status = _status(planning_records)
        match_confidence = _unique_text(shkp_records, "match_confidence")
        pilot_groups = _unique_text(pilot_records, "pilot_group")
        universe_status, universe_evidence_types = _universe_status(
            shkp_records,
            annual_records,
            pipeline_records,
            completion_records,
            legal_records,
            history_records,
        )
        numeric_evidence = bool(annual_pct or completion_pct or legal_observed_pct or curated_pct)
        role_or_identity_evidence = bool(
            shkp_records or annual_records or completion_records or legal_records or history_records
        )
        if interval_ready and interval_pct_consistent:
            ownership_evidence_level = "approved_phase_attribution"
            ownership_evidence_promotion_status = "approved_phase_attribution"
            ownership_next_evidence = None
        elif numeric_evidence:
            ownership_evidence_level = "numeric_snapshot_or_grouped_interest"
            if ownership_status == "annual_jv_unresolved" or "JV" in completion_raw_upper:
                ownership_evidence_promotion_status = "blocked_jv_economics_interval"
                ownership_next_evidence = "phase-specific JV economic percentage, dated effective interval and continuity basis"
            else:
                ownership_evidence_promotion_status = "blocked_numeric_snapshot_only"
                ownership_next_evidence = "phase-specific SPV/economic-interest evidence with dated effective_from/effective_to and continuity"
        elif role_or_identity_evidence:
            ownership_evidence_level = "phase_or_project_identity_only"
            ownership_evidence_promotion_status = "blocked_role_or_identity_only"
            ownership_next_evidence = "numeric SHKP economic interest plus dated phase-specific SPV/JV interval"
        else:
            ownership_evidence_level = "srpe_parent_only"
            ownership_evidence_promotion_status = "blocked_no_shkp_evidence"
            ownership_next_evidence = "official SHKP directory, annual-report, project-site or legal-role evidence"
        ownership_evidence_urls: list[str] = []
        for record in [*shkp_records, *annual_records, *completion_records, *legal_records, *decision_records, *history_records]:
            for field in (
                "source_url",
                "shkp_source_url",
                "annual_document_url",
                "document_url",
                "ownership_source_url",
                "phase_identity_source_url",
                "evidence_url",
            ):
                value = record.get(field)
                if value and str(value).strip() and str(value).strip() not in ownership_evidence_urls:
                    ownership_evidence_urls.append(str(value).strip())
        rows.append(
            {
                "registry_key": f"srpe:{srpe_id}",
                "srpe_development_id": srpe_id,
                "development_name_en": srpe_record.get("development_name_en") or srpe_record.get("display_name"),
                "phase_name_en": srpe_record.get("phase_name_en"),
                "phase_no": srpe_record.get("phase_no"),
                "address_en": srpe_record.get("address_en"),
                "planning_area_en": srpe_record.get("planning_area_en"),
                "active": srpe_record.get("active"),
                "official_website": srpe_record.get("official_website"),
                "srpe_earliest_publication": srpe_record.get("srpe_earliest_publication"),
                "srpe_date_suspend_sales": srpe_record.get("srpe_date_suspend_sales"),
                "srpe_date_complete_sales": srpe_record.get("srpe_date_complete_sales"),
                "srpe_is_deleted": srpe_record.get("srpe_is_deleted"),
                "srpe_eng_remark": srpe_record.get("srpe_eng_remark"),
                "srpe_chn_remark": srpe_record.get("srpe_chn_remark"),
                "srpe_eng_addr_idx_remark": srpe_record.get("srpe_eng_addr_idx_remark"),
                "srpe_chn_addr_idx_remark": srpe_record.get("srpe_chn_addr_idx_remark"),
                "srpe_index_snapshot_at": srpe_record.get("fetched_at"),
                "universe_status": universe_status,
                "universe_evidence_types": "|".join(universe_evidence_types) or None,
                "curated_non_shkp_reason": curated_non_shkp,
                "history_milestone_evidence_rows": len(history_records),
                "history_milestone_years": " | ".join(history_years) or None,
                "history_milestone_summaries": " | ".join(history_summaries) or None,
                "history_milestone_match_status": _status(history_records),
                "shkp_marketing_names": " | ".join(shkp_names) or None,
                "shkp_listing_count": len(shkp_names),
                "shkp_match_status": shkp_status,
                "shkp_match_confidence": "|".join(match_confidence) or None,
                "annual_project_labels": " | ".join(annual_labels) or None,
                "annual_project_states": " | ".join(annual_states) or None,
                "annual_group_interest_raw": " | ".join(annual_raw_interest) or None,
                "annual_group_interest_pct": _scalar_or_json(annual_pct),
                "annual_match_status": annual_status,
                "completion_schedule_latest_date": max(completion_dates, default=None),
                "completion_schedule_windows": " | ".join(completion_windows) or None,
                "completion_schedule_lot_descriptions": " | ".join(completion_lots) or None,
                "completion_schedule_project_labels": " | ".join(completion_labels) or None,
                "completion_schedule_group_interest_raw": " | ".join(completion_raw_interest) or None,
                "completion_schedule_group_interest_pct": _scalar_or_json(completion_pct),
                "completion_schedule_match_status": _status(completion_records),
                "completion_schedule_ownership_status": completion_ownership_status,
                "completion_schedule_evidence_rows": len(completion_records),
                "planning_lot_nos": " | ".join(planning_lots) or None,
                "planning_consent_dates": " | ".join(planning_dates) or None,
                "planning_entity_labels": " | ".join(planning_entities) or None,
                "planning_match_status": planning_status,
                "planning_evidence_rows": len(planning_records),
                "legal_spv_names": " | ".join(legal_spvs) or None,
                "ownership_observed_pct": _scalar_or_json(legal_observed_pct),
                "ownership_observed_as_of": " | ".join(legal_observed_dates) or None,
                "legal_ownership_observation_status": legal_observation_status,
                "legal_ownership_evidence_rows": len(legal_records),
                "bd_match_status": _status(bd_records, "bd_match_status"),
                "bd_phase_candidate_counts": " | ".join(
                    _unique_text(bd_records, "bd_phase_candidate_count")
                ) or None,
                "bd_permit_stages": " | ".join(_unique_text(bd_records, "bd_permit_stage")) or None,
                "bd_permit_numbers": " | ".join(_unique_text(bd_records, "bd_permit_number")) or None,
                "bd_site_addresses": " | ".join(_unique_text(bd_records, "bd_site_address")) or None,
                "bd_domestic_units_count": " | ".join(_unique_text(bd_records, "bd_domestic_units_count")) or None,
                "bd_usable_floor_area_sqm": " | ".join(_unique_text(bd_records, "bd_usable_floor_area_sqm")) or None,
                "bd_parser_confidences": " | ".join(_unique_text(bd_records, "bd_parser_confidence")) or None,
                "bd_evidence_rows": len(bd_records),
                "pipeline_status": _phase_pipeline_status(
                    shkp_records, annual_records, planning_records, observed_pipeline_records
                ),
                "pipeline_disclosure_labels": " | ".join(
                    _unique_text(observed_pipeline_records, "project_label")
                ) or None,
                "pipeline_disclosure_states": " | ".join(
                    _unique_text(observed_pipeline_records, "pipeline_status")
                ) or None,
                "pipeline_disclosure_match_status": _status(pipeline_records),
                "pipeline_disclosure_rows": len(pipeline_records),
                "pipeline_disclosure_keys": " | ".join(
                    _unique_text(observed_pipeline_records, "pipeline_evidence_key")
                ) or None,
                "pipeline_disclosure_last_publication_date": max(
                    _unique_text(observed_pipeline_records, "publication_date"),
                    default=None,
                ),
                "curated_project_ids": " | ".join(_unique_text(pilot_records, "project_id")) or None,
                "curated_stock_codes": " | ".join(_unique_text(pilot_records, "stock_code")) or None,
                "curated_registry_ownership_pct": _scalar_or_json(curated_pct),
                "ownership_status": ownership_status,
                "ownership_evidence_level": ownership_evidence_level,
                "ownership_evidence_source_count": len(ownership_evidence_urls),
                "ownership_evidence_promotion_status": ownership_evidence_promotion_status,
                "ownership_next_evidence": ownership_next_evidence,
                "ownership_effective_from": _scalar_or_json(effective_from_values),
                "ownership_effective_to": _scalar_or_json(effective_to_values),
                "ownership_interval_status": ownership_interval_status,
                "ownership_interval_evidence_type": " | ".join(interval_evidence_types) or None,
                "ownership_attribution_decision_id": " | ".join(attribution_decision_ids) or None,
                "ownership_interval_promotion_status": " | ".join(interval_promotion_statuses) or None,
                "ownership_attribution_ready": (
                    ownership_status == "consistent_numeric"
                    and interval_ready
                    and interval_pct_consistent
                ),
                "pilot_status": "|".join(pilot_groups) or "not_in_pilot",
                "manifest_status": "filings_available" if manifest_records else "not_loaded",
                "source_urls_json": json.dumps(source_urls, ensure_ascii=False),
                "evidence_count": len(shkp_records) + len(annual_records) + len(planning_records) + len(pipeline_records) + len(completion_records) + len(legal_records) + len(decision_records),
                "last_verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=SHKP_PROJECT_REGISTRY_COLUMNS)


def build_shkp_sales_ingestion_eligibility(
    project_registry: pd.DataFrame,
    srpe_manifest: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Create a phase-level gate for the next SRPE sales ingestion step.

    This contract deliberately separates *filing availability* from *sales
    eligibility*.  A phase with a transaction register but unresolved SHKP
    ownership remains ``ownership_review_required``; a phase with reconciled
    ownership but no manifest remains ``manifest_required``.  Manifest
    variants are keyed by ``document_id + serial_no + file_name`` because a
    single SRPE document ID can legitimately expose multiple filing files.
    """
    if project_registry.empty:
        return pd.DataFrame(columns=SHKP_SALES_INGESTION_ELIGIBILITY_COLUMNS)
    manifest = srpe_manifest if srpe_manifest is not None else pd.DataFrame()
    rows: list[dict[str, Any]] = []
    categories = {
        "register_of_transactions": "register_document_count",
        "price_list": "price_list_document_count",
        "sales_arrangement": "sales_arrangement_document_count",
        "sales_brochure": "sales_brochure_document_count",
    }
    manifest_ids = (
        manifest["srpe_development_id"].astype("string")
        if not manifest.empty and "srpe_development_id" in manifest.columns
        else pd.Series(dtype="string")
    )
    for registry_row in project_registry.to_dict("records"):
        development_id = str(registry_row.get("srpe_development_id") or "").strip()
        phase_manifest = (
            manifest.loc[manifest_ids.eq(development_id)].copy()
            if not manifest.empty and development_id
            else pd.DataFrame()
        )
        counts = {column: 0 for column in categories.values()}
        for category, column in categories.items():
            if not phase_manifest.empty and "document_category" in phase_manifest.columns:
                counts[column] = int(phase_manifest["document_category"].eq(category).sum())
        duplicate_count = 0
        if not phase_manifest.empty:
            composite = [
                column for column in ("srpe_development_id", "document_category", "document_id", "serial_no", "file_name")
                if column in phase_manifest.columns
            ]
            if composite:
                duplicate_count = int(phase_manifest.duplicated(composite).sum())
        interval_ready = _record_has_phase_specific_effective_interval(registry_row)
        # The explicit interval is the source-of-truth gate.  This protects
        # against stale/manual registry rows that still carry the legacy
        # boolean flag without phase-specific effective dates.
        ownership_ready = (
            str(registry_row.get("ownership_status") or "") == "consistent_numeric"
            and bool(registry_row.get("ownership_attribution_ready"))
            and interval_ready
        )
        has_manifest = not phase_manifest.empty
        if ownership_ready and counts["register_document_count"] > 0:
            eligibility_status = "eligible_register_price_review"
            eligibility_reason = "numeric ownership with a bounded phase-specific effective interval is reconciled and transaction register is available; price-list history remains a separate review"
        elif ownership_ready:
            eligibility_status = "manifest_required"
            eligibility_reason = "numeric ownership with a bounded phase-specific effective interval is reconciled but no SRPE filing manifest is loaded for this phase"
        elif has_manifest:
            eligibility_status = "ownership_review_required"
            if str(registry_row.get("ownership_status") or "") == "consistent_numeric" and not interval_ready:
                eligibility_reason = "SRPE filings are available and a numeric snapshot is present, but no phase-specific bounded effective interval is reconciled"
            else:
                eligibility_reason = "SRPE filings are available but SHKP ownership/JV attribution is not reconciled"
        else:
            eligibility_status = "not_ready"
            if str(registry_row.get("ownership_status") or "") == "consistent_numeric" and not interval_ready:
                eligibility_reason = "numeric ownership snapshot exists, but no phase-specific bounded effective interval is reconciled"
            else:
                eligibility_reason = "neither reconciled ownership nor SRPE filing metadata is available"
        source_urls = registry_row.get("source_urls_json")
        rows.append(
            {
                "registry_key": registry_row.get("registry_key"),
                "srpe_development_id": development_id,
                "development_name_en": registry_row.get("development_name_en"),
                "phase_name_en": registry_row.get("phase_name_en"),
                "ownership_status": registry_row.get("ownership_status"),
                "ownership_effective_from": registry_row.get("ownership_effective_from"),
                "ownership_effective_to": registry_row.get("ownership_effective_to"),
                "ownership_interval_status": registry_row.get("ownership_interval_status") or (
                    "phase_specific_bounded_interval" if interval_ready else "blocked_effective_interval"
                ),
                "ownership_interval_evidence_type": registry_row.get("ownership_interval_evidence_type"),
                "ownership_attribution_decision_id": registry_row.get("ownership_attribution_decision_id"),
                "ownership_interval_promotion_status": registry_row.get("ownership_interval_promotion_status"),
                "ownership_attribution_ready": ownership_ready,
                "pilot_status": registry_row.get("pilot_status"),
                "manifest_status": "filings_available" if has_manifest else "not_loaded",
                "manifest_document_count": int(len(phase_manifest)),
                **counts,
                "manifest_composite_duplicate_count": duplicate_count,
                "eligibility_status": eligibility_status,
                "eligibility_reason": eligibility_reason,
                "source_urls_json": source_urls,
                "last_verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=SHKP_SALES_INGESTION_ELIGIBILITY_COLUMNS)


def build_shkp_sales_ingestion_plan(
    project_registry: pd.DataFrame,
    sales_eligibility: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Turn the ownership/manifest gate into an executable SRPE work plan.

    This is an operational plan, not a sales dataset.  Only phases with
    reconciled numeric ownership and a transaction register are allowed to
    enter the bounded PDF runner.  Every other phase receives an explicit next
    step and remains blocked, so an operator cannot accidentally treat a
    website listing or a filing-only phase as attributable sales.
    """
    if project_registry.empty:
        return pd.DataFrame(columns=SHKP_SALES_INGESTION_PLAN_COLUMNS)
    eligibility = sales_eligibility if sales_eligibility is not None else pd.DataFrame()
    eligibility_by_id = {
        str(row.get("srpe_development_id") or ""): row
        for row in eligibility.to_dict("records")
        if str(row.get("srpe_development_id") or "")
    }
    rows: list[dict[str, Any]] = []
    for registry_row in project_registry.to_dict("records"):
        development_id = str(registry_row.get("srpe_development_id") or "").strip()
        gate = eligibility_by_id.get(development_id, {})
        status = str(gate.get("eligibility_status") or "not_ready")
        reason = str(gate.get("eligibility_reason") or "").strip() or None
        registry_interval_ready = _record_has_phase_specific_effective_interval(registry_row)
        gate_interval_ready = _record_has_phase_specific_effective_interval(gate)
        ownership_ready = (
            str(registry_row.get("ownership_status") or "") == "consistent_numeric"
            and str(gate.get("ownership_status") or "") == "consistent_numeric"
            and bool(registry_row.get("ownership_attribution_ready"))
            and registry_interval_ready
            and bool(gate.get("ownership_attribution_ready"))
            and gate_interval_ready
        )
        if status == "eligible_register_price_review" and not ownership_ready:
            status = "ownership_review_required"
            reason = "sales plan blocked: phase-specific bounded ownership interval is missing from registry or eligibility evidence"
        pilot_status = str(registry_row.get("pilot_status") or "").strip() or None
        if status == "eligible_register_price_review":
            action = "download_register_and_price_lists"
            allowed = "register_of_transactions|price_list|sales_arrangement"
            parser_gate = "pending_document_completeness"
            coverage = "pilot_boundary_available" if "core_pilot" in str(pilot_status or "") else "manifest_ready"
            next_step = "Run bounded SRPE PDF ingestion; audit register completeness before aggregating sales"
            blocked_reason = None
        elif status == "ownership_review_required":
            action = "review_ownership_before_sales"
            allowed = None
            parser_gate = "blocked_ownership"
            coverage = "manifest_only"
            next_step = "Resolve dated SPV/JV ownership evidence before PDF ingestion"
            blocked_reason = reason or "ownership/JV attribution is unresolved"
        elif status == "manifest_required":
            action = "refresh_srpe_manifest"
            allowed = None
            parser_gate = "blocked_manifest"
            coverage = "ownership_ready_no_manifest"
            next_step = "Refresh the official SRPE filing manifest for this phase"
            blocked_reason = reason or "numeric ownership is ready but no filing manifest is loaded"
        else:
            action = "discover_ownership_and_manifest"
            allowed = None
            parser_gate = "blocked_inputs"
            coverage = "not_started"
            next_step = "Obtain official SHKP/SRPE crosswalk and filing metadata before PDF ingestion"
            blocked_reason = reason or "ownership and filing inputs are not ready"

        rows.append(
            {
                "plan_key": f"sales:{registry_row.get('registry_key') or development_id}",
                "registry_key": registry_row.get("registry_key"),
                "srpe_development_id": development_id,
                "development_name_en": registry_row.get("development_name_en"),
                "phase_name_en": registry_row.get("phase_name_en"),
                "curated_project_ids": registry_row.get("curated_project_ids"),
                "curated_stock_codes": registry_row.get("curated_stock_codes"),
                "pilot_status": pilot_status,
                "eligibility_status": status,
                "eligibility_reason": reason,
                "ownership_status": registry_row.get("ownership_status"),
                "ownership_attribution_ready": ownership_ready,
                "manifest_status": gate.get("manifest_status") or registry_row.get("manifest_status"),
                "manifest_document_count": gate.get("manifest_document_count", 0),
                "register_document_count": gate.get("register_document_count", 0),
                "price_list_document_count": gate.get("price_list_document_count", 0),
                "sales_arrangement_document_count": gate.get("sales_arrangement_document_count", 0),
                "sales_brochure_document_count": gate.get("sales_brochure_document_count", 0),
                "ingestion_action": action,
                "allowed_document_categories": allowed,
                "parser_gate_status": parser_gate,
                "coverage_status": coverage,
                "next_step": next_step,
                "blocked_reason": blocked_reason,
                "source_urls_json": gate.get("source_urls_json") or registry_row.get("source_urls_json"),
                "last_verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=SHKP_SALES_INGESTION_PLAN_COLUMNS)


def build_shkp_future_project_resolution_plan(
    pipeline_registry: pd.DataFrame,
    sales_plan: pd.DataFrame | None = None,
    identity_evidence: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Create an identity-first plan for future/under-development disclosures.

    ``shkp_pipeline_project_registry`` is intentionally a disclosure-level
    evidence layer.  Its rows may have no SRPE development ID, or several
    candidate phases, so they must not be silently dropped from operations and
    must not be sent to the PDF sales runner.  This plan preserves those rows,
    specifies the evidence needed to resolve identity, and anti-joins any
    single candidate against the phase-level sales plan when one is available.
    """
    pipeline = pipeline_registry.copy() if pipeline_registry is not None else pd.DataFrame()
    if pipeline.empty:
        return pd.DataFrame(columns=SHKP_FUTURE_PROJECT_RESOLUTION_PLAN_COLUMNS)
    sales = sales_plan.copy() if sales_plan is not None else pd.DataFrame()
    identity = identity_evidence.copy() if identity_evidence is not None else pd.DataFrame()

    def _text(value: Any) -> str | None:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        text = str(value).strip()
        return text or None

    def _candidate_ids(value: Any) -> list[str]:
        text = _text(value)
        if not text:
            return []
        return list(dict.fromkeys(item.strip() for item in text.split("|") if item.strip()))

    sales_ids = {
        _text(value)
        for value in sales.get("srpe_development_id", pd.Series(dtype=object)).tolist()
        if _text(value)
    }
    identity_by_label: dict[str, list[dict[str, Any]]] = {}
    if not identity.empty:
        for identity_record in identity.to_dict("records"):
            label_key = _normalized_name(identity_record.get("project_label"))
            if label_key:
                identity_by_label.setdefault(label_key, []).append(identity_record)
    identity_aliases = {
        _normalized_name(source): tuple(
            _normalized_name(target)
            for target in targets
            if _normalized_name(target)
        )
        for source, targets in SHKP_FUTURE_PROJECT_IDENTITY_LABEL_ALIASES.items()
    }
    sales_plan_built = sales_plan is not None
    rows: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for record in pipeline.to_dict("records"):
        registry_key = _text(record.get("pipeline_registry_key"))
        if not registry_key:
            continue
        label_norm = _normalized_name(record.get("project_label"))
        candidate_ids = _candidate_ids(record.get("srpe_candidate_ids"))
        identity_keys = [label_norm]
        identity_match_method = "exact_label"
        if label_norm in identity_aliases:
            identity_keys.extend(identity_aliases[label_norm])
            identity_match_method = "curated_label_alias"
        identity_records: list[dict[str, Any]] = []
        seen_identity_ids: set[str] = set()
        for identity_key in identity_keys:
            for identity_record in identity_by_label.get(identity_key, []):
                evidence_id = _text(identity_record.get("identity_evidence_id")) or repr(identity_record)
                if evidence_id in seen_identity_ids:
                    continue
                seen_identity_ids.add(evidence_id)
                identity_records.append(identity_record)
        if not identity_records:
            identity_match_method = "none"
        identity_ids = _candidate_ids(
            " | ".join(
                str(identity_record.get("srpe_development_id"))
                for identity_record in identity_records
                if _text(identity_record.get("srpe_development_id"))
            )
        )
        candidate_ids = list(dict.fromkeys([*candidate_ids, *identity_ids]))
        candidate_count_value = pd.to_numeric(record.get("srpe_candidate_count"), errors="coerce")
        candidate_count = max(
            int(candidate_count_value) if pd.notna(candidate_count_value) else 0,
            len(candidate_ids),
        )
        match_status = _text(record.get("srpe_match_status")) or "not_observed"
        state = (_text(record.get("project_state")) or "").casefold()
        commercial_scope = SHKP_NON_SRPE_COMMERCIAL_LABELS.get(label_norm)
        identity_statuses = {
            _text(identity_record.get("canonical_identity_status")) or "not_evaluated"
            for identity_record in identity_records
        }
        identity_non_srpe_scope = next(
            (
                _text(identity_record.get("asset_scope"))
                for identity_record in identity_records
                if str(identity_record.get("srpe_match_status") or "").startswith("not_applicable")
                or str(identity_record.get("asset_scope") or "").startswith("commercial")
            ),
            None,
        )
        if not commercial_scope and identity_non_srpe_scope:
            commercial_scope = identity_non_srpe_scope
        identity_bridge_status = "not_observed"
        if identity_records:
            if any(
                str(identity_record.get("srpe_match_status") or "").startswith("not_applicable")
                or str(identity_record.get("asset_scope") or "").startswith("commercial")
                for identity_record in identity_records
            ):
                identity_bridge_status = "non_srpe_asset"
            elif len(identity_ids) > 1:
                identity_bridge_status = "multiple_phase_candidates"
            elif identity_ids and any(status == "phase_resolved_srpe" for status in identity_statuses):
                identity_bridge_status = "phase_resolved"
            elif identity_ids:
                identity_bridge_status = "phase_candidate_needs_review"
            else:
                identity_bridge_status = "lot_resolved_srpe_pending"

        if commercial_scope:
            asset_scope = commercial_scope
            action = "route_to_commercial_registry"
            required_evidence = "SHKP commercial asset/land concession/BOT and development-partner evidence"
            resolution_status = "resolved_non_srpe_commercial_bot" if commercial_scope.endswith("_bot") else "not_applicable_to_srpe_residential"
            linked_id = None
            priority = "P2"
        elif match_status == "ambiguous" or candidate_count > 1:
            asset_scope = "residential_first_hand_or_unknown"
            action = "resolve_phase_before_ownership"
            required_evidence = "phase-specific SRPE filing/project site plus lot/SPV/JV bridge"
            resolution_status = "unresolved_multiple_srpe_candidates"
            linked_id = None
            priority = "P0"
        elif candidate_ids and (match_status in {"matched", "matched_needs_review"} or identity_ids):
            asset_scope = "residential_first_hand_or_unknown"
            action = "link_to_sales_plan_then_review_ownership"
            required_evidence = "dated legal SPV/JV ownership evidence after phase identity review"
            resolution_status = (
                "identity_phase_linked_review_required"
                if identity_ids
                else "candidate_linked_review_required"
            )
            linked_id = candidate_ids[0]
            priority = "P1"
        else:
            asset_scope = "residential_first_hand_or_unknown"
            action = "resolve_identity_before_manifest"
            required_evidence = "SRPE development/phase identity, official project site, and lot/address bridge"
            resolution_status = (
                "identity_lot_resolved_srpe_pending"
                if identity_records
                else "unresolved_no_srpe_candidate"
            )
            linked_id = None
            priority = "P0" if any(token in state for token in ("planned_sale", "planned_launch", "under_development")) else "P1"

        if commercial_scope:
            linked_registry_key = None
            coverage_status = "not_applicable_non_residential"
        elif linked_id:
            linked_registry_key = f"srpe:{linked_id}"
            if sales_plan_built:
                coverage_status = (
                    "covered_by_phase_sales_plan"
                    if linked_id in sales_ids
                    else "candidate_not_in_sales_plan"
                )
            else:
                coverage_status = "phase_known_sales_plan_not_built"
        elif candidate_ids:
            linked_registry_key = None
            coverage_status = "candidate_unlinked"
        else:
            linked_registry_key = None
            coverage_status = "no_srpe_identity"

        source_url = _text(record.get("source_url"))
        annual_url = _text(record.get("annual_document_url"))
        identity_urls = [
            _text(identity_record.get(field))
            for identity_record in identity_records
            for field in ("primary_source_url", "secondary_source_url")
            if _text(identity_record.get(field))
        ]
        source_urls = list(dict.fromkeys([value for value in (source_url, annual_url, *identity_urls) if value]))
        rows.append(
            {
                "pipeline_registry_key": registry_key,
                "disclosure_id": _text(record.get("disclosure_id")),
                "annual_report_id": _text(record.get("annual_report_id")),
                "project_label": _text(record.get("project_label")),
                "project_state": _text(record.get("project_state")),
                "asset_scope": asset_scope,
                "geography": _text(record.get("geography")),
                "publication_date": _text(record.get("publication_date")),
                "source_url": source_url,
                "annual_document_url": annual_url,
                "srpe_match_status": match_status,
                "srpe_candidate_ids": " | ".join(candidate_ids) or None,
                "srpe_candidate_count": candidate_count,
                "identity_evidence_ids": " | ".join(
                    _text(identity_record.get("identity_evidence_id"))
                    for identity_record in identity_records
                    if _text(identity_record.get("identity_evidence_id"))
                ) or None,
                "identity_bridge_status": identity_bridge_status,
                "identity_bridge_match_method": identity_match_method,
                "identity_bridge_lot_nos": " | ".join(
                    list(dict.fromkeys(
                        _text(identity_record.get("lot_no_raw"))
                        for identity_record in identity_records
                        if _text(identity_record.get("lot_no_raw"))
                    ))
                ) or None,
                "identity_bridge_phase_labels": " | ".join(
                    list(dict.fromkeys(
                        _text(identity_record.get("phase_label"))
                        for identity_record in identity_records
                        if _text(identity_record.get("phase_label"))
                    ))
                ) or None,
                "identity_bridge_ownership_promotion_status": " | ".join(
                    list(dict.fromkeys(
                        _text(identity_record.get("ownership_promotion_status"))
                        for identity_record in identity_records
                        if _text(identity_record.get("ownership_promotion_status"))
                    ))
                ) or None,
                "identity_resolution_action": action,
                "required_evidence_type": required_evidence,
                "primary_source_url": (
                    source_url or annual_url
                    if commercial_scope
                    else "https://www.srpe.gov.hk/opip/all_development"
                ),
                "secondary_source_url": (
                    "https://www.srpe.gov.hk/opip/all_development"
                    if commercial_scope
                    else source_url or annual_url
                ),
                "bd_lookup_status": "not_started",
                "website_lookup_status": "not_started",
                "resolution_status": resolution_status,
                "linked_srpe_development_id": linked_id,
                "linked_registry_key": linked_registry_key,
                "sales_plan_coverage_status": coverage_status,
                "resolution_priority": priority,
                "last_verified_at": _text(record.get("last_verified_at")) or now,
            }
        )

    frame = pd.DataFrame(rows, columns=SHKP_FUTURE_PROJECT_RESOLUTION_PLAN_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(["resolution_priority", "pipeline_registry_key"], kind="stable").reset_index(drop=True)
    return frame


def _future_clean_text(value: Any) -> str | None:
    """Scalar text helper shared by the future-project event/snapshot builders."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    value_text = str(value).strip()
    return value_text or None


def build_shkp_future_project_events(
    pipeline_disclosures: pd.DataFrame | None,
    pipeline_registry: pd.DataFrame | None,
    resolution_plan: pd.DataFrame | None = None,
    identity_evidence: pd.DataFrame | None = None,
    srpe_index: pd.DataFrame | None = None,
    *,
    prior_events: pd.DataFrame | None = None,
    ownership_observations: pd.DataFrame | None = None,
    observed_at: str | None = None,
) -> pd.DataFrame:
    """Build an append-only event log for SHKP future projects.

    The source layers deliberately have different grains: an issuer
    disclosure is a project-level dated observation, an identity bridge may
    only resolve a lot, and SRPE is a phase-level lifecycle snapshot.  This
    function keeps those observations as separate events and only emits a
    lifecycle state when the source explicitly supports one.  Missing SRPE,
    units, GFA, ownership or sales documents remain ``not_observed``/null;
    they are never converted into cancellation or zero sales.
    """
    pipeline = pipeline_registry.copy() if pipeline_registry is not None else pd.DataFrame()
    disclosures = pipeline_disclosures.copy() if pipeline_disclosures is not None else pd.DataFrame()
    resolution = resolution_plan.copy() if resolution_plan is not None else pd.DataFrame()
    identity = identity_evidence.copy() if identity_evidence is not None else pd.DataFrame()
    srpe = srpe_index.copy() if srpe_index is not None else pd.DataFrame()
    prior = prior_events.copy() if prior_events is not None else pd.DataFrame()
    now = observed_at or datetime.now(timezone.utc).isoformat()

    def text(value: Any) -> str | None:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        value_text = str(value).strip()
        return value_text or None

    def split_ids(value: Any) -> list[str]:
        raw = text(value)
        if not raw:
            return []
        return list(dict.fromkeys(item.strip() for item in raw.split("|") if item.strip()))

    def normalize_date(value: Any) -> str | None:
        raw = text(value)
        if not raw:
            return None
        parsed = pd.to_datetime(raw, errors="coerce", utc=True)
        if pd.isna(parsed):
            return raw[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", raw) else None
        return parsed.date().isoformat()

    def lifecycle_state(value: Any) -> str | None:
        status = (text(value) or "").casefold()
        return {
            "planned_launch_10m": "planned_launch",
            "planned_sale_10m": "planned_launch",
            "planned_launch": "planned_launch",
            "under_development": "under_development",
            "planned": "planned_launch",
        }.get(status)

    def srpe_lifecycle(row: Mapping[str, Any]) -> str:
        if text(row.get("srpe_is_deleted") or row.get("isDeleted")) in {"Y", "y", "1", "true", "True"}:
            return "deleted"
        if text(row.get("srpe_date_complete_sales") or row.get("dateCompleteSales")):
            return "completed"
        if (text(row.get("active")) or "").upper() == "Y":
            return "active"
        if text(row.get("srpe_date_suspend_sales") or row.get("dateSuspendSales")):
            return "suspended"
        if (text(row.get("active")) or "").upper() == "N":
            return "inactive"
        return "unknown"

    srpe_by_id = {
        str(row.get("development_id") or "").strip(): row
        for row in srpe.to_dict("records")
        if text(row.get("development_id"))
    }
    resolution_by_key = {
        text(row.get("pipeline_registry_key")): row
        for row in resolution.to_dict("records")
        if text(row.get("pipeline_registry_key"))
    }
    identity_by_label: dict[str, list[dict[str, Any]]] = {}
    for row in identity.to_dict("records"):
        key = _normalized_name(row.get("project_label"))
        if key:
            identity_by_label.setdefault(key, []).append(row)

    # Numeric observations are deliberately labelled snapshots, not legal
    # effective intervals.  They can populate a scenario band for review but
    # never make the sales gate ready.
    numeric_ownership: dict[str, tuple[float | None, float | None, float | None, str]] = {}
    if ownership_observations is not None and not ownership_observations.empty:
        for phase_id, group in ownership_observations.groupby(
            ownership_observations.get("srpe_development_id", pd.Series(dtype="string")).astype(str),
            dropna=False,
        ):
            values = pd.to_numeric(group.get("ownership_pct"), errors="coerce").dropna().tolist()
            if not values or not text(phase_id):
                continue
            numeric_ownership[str(phase_id)] = (
                float(min(values)),
                float(pd.Series(values).median()),
                float(max(values)),
                "observed_snapshot_not_interval" if len(set(values)) == 1 else "observed_range_not_interval",
            )

    def ownership_fields(phase_id: str | None) -> tuple[float | None, float | None, float | None, str]:
        return numeric_ownership.get(str(phase_id), (None, None, None, "not_observed"))

    def project_id(label: Any, linked_id: Any = None) -> str:
        phase_id = text(linked_id)
        if phase_id:
            return f"srpe:{phase_id}"
        normalized = _normalized_name(label)
        return f"pipeline:{normalized or 'unidentified'}"

    def source_urls(*values: Any) -> list[str]:
        urls: list[str] = []
        for value in values:
            if isinstance(value, (list, tuple, set)):
                items = value
            else:
                items = [value]
            for item in items:
                candidate = text(item)
                if candidate and candidate not in urls:
                    urls.append(candidate)
        return urls

    rows: list[dict[str, Any]] = []

    def append_event(
        *,
        canonical_id: str,
        label: Any,
        aliases: Iterable[Any] = (),
        asset_scope: Any,
        event_type: str,
        event_date: Any,
        event_date_semantics: str,
        state_after: Any = None,
        srpe_id: Any = None,
        phase_name: Any = None,
        lot_no: Any = None,
        address: Any = None,
        units: Any = None,
        gfa_sqft: Any = None,
        expected_launch_window: Any = None,
        expected_completion_window: Any = None,
        source_url: Any = None,
        source_url_list: Iterable[Any] = (),
        source_dataset: str,
        evidence_status: Any,
        evidence_key: Any,
        sales_queue_status: Any,
        ownership: tuple[float | None, float | None, float | None, str],
        state_before: Any = None,
    ) -> None:
        urls = source_urls(source_url, source_url_list)
        date_value = normalize_date(event_date)
        event_payload = "|".join(
            text(value) or ""
            for value in (
                canonical_id,
                event_type,
                date_value,
                text(evidence_key),
                text(source_url),
                text(srpe_id),
                text(state_after),
            )
        )
        event_key = hashlib.sha256(event_payload.encode("utf-8")).hexdigest()
        rows.append(
            {
                "event_id": f"shkp-future-event-{event_key[:20]}",
                "event_key": event_key,
                "canonical_project_id": canonical_id,
                "project_label": text(label),
                "aliases_json": json.dumps(
                    list(dict.fromkeys(text(value) for value in aliases if text(value))),
                    ensure_ascii=False,
                ),
                "asset_scope": text(asset_scope) or "residential_first_hand_or_unknown",
                "event_type": event_type,
                "event_date": date_value,
                "event_date_semantics": event_date_semantics,
                "state_before": text(state_before),
                "state_after": text(state_after),
                "lot_no": text(lot_no),
                "address": text(address),
                "srpe_development_id": text(srpe_id),
                "srpe_phase_name": text(phase_name),
                "units": units,
                "gfa_sqft": gfa_sqft,
                "expected_launch_window": text(expected_launch_window),
                "expected_completion_window": text(expected_completion_window),
                "ownership_low_pct": ownership[0],
                "ownership_base_pct": ownership[1],
                "ownership_high_pct": ownership[2],
                "ownership_scenario_status": ownership[3],
                "source_url": urls[0] if urls else None,
                "source_urls_json": json.dumps(urls, ensure_ascii=False),
                "source_dataset": source_dataset,
                "evidence_status": text(evidence_status) or "not_observed",
                "evidence_key": text(evidence_key),
                "sales_queue_status": text(sales_queue_status) or "not_evaluated",
                "observed_at": now,
                "missing_data_policy": "unknown_is_not_zero; no_srpe_is_not_no_sales",
            }
        )

    for record in pipeline.to_dict("records"):
        registry_key = text(record.get("pipeline_registry_key"))
        if not registry_key:
            continue
        plan = resolution_by_key.get(registry_key, {})
        label = text(record.get("project_label"))
        linked_id = text(plan.get("linked_srpe_development_id"))
        candidate_ids = split_ids(record.get("srpe_candidate_ids"))
        commercial = (text(plan.get("asset_scope")) or "").startswith("commercial")
        asset_scope = text(plan.get("asset_scope")) or (
            "commercial_investment_or_bot" if commercial else "residential_first_hand_or_unknown"
        )
        identity_rows = identity_by_label.get(_normalized_name(label), [])
        aliases = [row.get("phase_label") for row in identity_rows]
        aliases.extend(candidate_ids)
        pipeline_state = lifecycle_state(record.get("project_state"))
        evidence_status = text(record.get("evidence_status")) or "not_observed"
        # ``not_found`` means the current HTML fetch did not expose the
        # configured phrase; it is not evidence that the issuer withdrew the
        # project.  Keep the disclosure's dated planned/development state in
        # the event log, but keep the source gap visible and do not open the
        # sales queue.  Only a genuinely unevaluated source suppresses the
        # configured state.
        if evidence_status in {"not_observed", "not_evaluated", ""}:
            pipeline_state = None
        pipeline_event_state = None if linked_id else ("commercial_under_development" if commercial else pipeline_state)
        queue_status = (
            "not_applicable_non_residential" if commercial else
            "eligible_for_recent_srpe_queue" if linked_id else
            "not_ready_srpe_pending" if evidence_status == "found" else
            "not_evaluated_source_gap"
        )
        ownership = ownership_fields(linked_id)
        append_event(
            canonical_id=project_id(label, linked_id),
            label=label,
            aliases=aliases,
            asset_scope=asset_scope,
            event_type="pipeline_disclosure",
            event_date=record.get("publication_date"),
            event_date_semantics="issuer_publication_date",
            state_after=pipeline_event_state,
            srpe_id=linked_id,
            phase_name=(srpe_by_id.get(linked_id) or {}).get("phase_name_en"),
            lot_no=plan.get("identity_bridge_lot_nos"),
            address=record.get("geography"),
            expected_launch_window=(
                "within_10_months_of_publication"
                if text(record.get("project_state")) in {"planned_launch_10m", "planned_sale_10m"}
                else None
            ),
            source_url=record.get("source_url"),
            source_dataset="shkp_pipeline_project_registry",
            evidence_status=evidence_status,
            evidence_key=registry_key,
            sales_queue_status=queue_status,
            ownership=ownership,
        )

    # Identity events are retained even when they have no SRPE ID.  They are
    # the bridge that lets a future refresh promote a project automatically.
    for record in identity.to_dict("records"):
        label = text(record.get("project_label"))
        linked_id = text(record.get("srpe_development_id"))
        commercial = (text(record.get("asset_scope")) or "").startswith("commercial")
        append_event(
            canonical_id=project_id(label, linked_id),
            label=label,
            aliases=[record.get("phase_label")],
            asset_scope=record.get("asset_scope"),
            event_type="identity_bridge",
            event_date=record.get("evidence_date"),
            event_date_semantics="identity_evidence_date",
            state_after=None,
            srpe_id=linked_id,
            phase_name=record.get("phase_label"),
            lot_no=record.get("lot_no_raw"),
            address=record.get("address_raw"),
            source_url=record.get("primary_source_url"),
            source_url_list=[record.get("secondary_source_url")],
            source_dataset="shkp_future_project_identity_evidence",
            evidence_status="found",
            evidence_key=record.get("identity_evidence_id"),
            sales_queue_status=("not_applicable_non_residential" if commercial else "not_ready_srpe_pending"),
            ownership=ownership_fields(linked_id),
        )

    # Every explicitly identified SRPE phase gets one lifecycle event.  This
    # is the promotion hook: an active phase is queue-eligible even if the
    # marketing directory has not yet listed it.
    linked_ids = set()
    for record in resolution.to_dict("records"):
        linked = text(record.get("linked_srpe_development_id"))
        if linked:
            linked_ids.add(linked)
    # Identity evidence can resolve a phase before the issuer disclosure
    # resolver has a one-to-one link (for example a shared development with a
    # phase-specific official site).  Once an SRPE id is known there too, use
    # the same lifecycle/queue promotion hook.
    for record in identity.to_dict("records"):
        linked = text(record.get("srpe_development_id"))
        if linked and not (text(record.get("asset_scope")) or "").startswith("commercial"):
            linked_ids.add(linked)
    for phase_id in sorted(linked_ids):
        phase = srpe_by_id.get(phase_id)
        if not phase:
            continue
        lifecycle = srpe_lifecycle(phase)
        state = {
            "active": "srpe_active_prelaunch",
            "suspended": "sales_suspended",
            "completed": "sales_completed",
            "deleted": "deleted",
            "inactive": "srpe_inactive",
            "unknown": "srpe_lifecycle_unknown",
        }.get(lifecycle, "srpe_lifecycle_unknown")
        event_date = (
            phase.get("srpe_date_complete_sales")
            or phase.get("srpe_date_suspend_sales")
            or phase.get("srpe_earliest_publication")
        )
        event_semantics = (
            "srpe_completion_date" if phase.get("srpe_date_complete_sales") else
            "srpe_suspension_date" if phase.get("srpe_date_suspend_sales") else
            "srpe_earliest_publication"
        )
        labels = [phase.get("development_name_en"), phase.get("phase_name_en")]
        linked_labels = resolution.loc[
            resolution.get("linked_srpe_development_id", pd.Series(dtype="string")).astype("string").eq(phase_id)
        ] if not resolution.empty and "linked_srpe_development_id" in resolution.columns else pd.DataFrame()
        labels.extend(linked_labels.get("project_label", pd.Series(dtype="string")).tolist())
        queue = "eligible_for_recent_srpe_queue" if lifecycle == "active" else "not_eligible_terminal_or_suspended"
        append_event(
            canonical_id=f"srpe:{phase_id}",
            label=next((text(value) for value in labels if text(value)), phase_id),
            aliases=labels,
            asset_scope="residential_first_hand_or_unknown",
            event_type="srpe_lifecycle_observation",
            event_date=event_date,
            event_date_semantics=event_semantics,
            state_after=state,
            srpe_id=phase_id,
            phase_name=phase.get("phase_name_en"),
            address=phase.get("address_en"),
            source_url=phase.get("source_url") or "https://www.srpe.gov.hk/opip/all_development",
            source_dataset="srpe_development_index",
            evidence_status="found",
            evidence_key=f"srpe:{phase_id}:{lifecycle}",
            sales_queue_status=queue,
            ownership=ownership_fields(phase_id),
        )

    current = pd.DataFrame(rows, columns=SHKP_FUTURE_PROJECT_EVENT_COLUMNS)
    frames = [frame.reindex(columns=SHKP_FUTURE_PROJECT_EVENT_COLUMNS) for frame in (prior, current) if frame is not None and not frame.empty]
    merged = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SHKP_FUTURE_PROJECT_EVENT_COLUMNS)
    if not merged.empty:
        merged = merged.drop_duplicates(subset=["event_key"], keep="last").reset_index(drop=True)
        merged = merged.sort_values(["event_date", "canonical_project_id", "event_id"], kind="stable", na_position="last").reset_index(drop=True)
    merged.attrs.update(
        lineage_metadata={
            "lineage_type": "shkp_future_project_append_only_events",
            "append_only": True,
            "dedupe_key": "event_key",
            "current_observation_rows": int(len(current)),
            "prior_event_rows": int(len(prior)),
            "merged_event_rows": int(len(merged)),
            "missing_data_policy": "unknown_is_not_zero; no_srpe_is_not_no_sales",
            "ownership_inference": False,
            "sales_promotion": "active linked SRPE phases are marked queue-eligible; legal ownership remains gated",
        },
        source_urls=list(dict.fromkeys(
            str(value)
            for frame in (pipeline, disclosures, identity, srpe)
            for value in frame.attrs.get("source_urls", [])
            if value
        )),
    )
    return merged


def build_shkp_future_project_snapshot(events: pd.DataFrame | None) -> pd.DataFrame:
    """Derive the latest future-project state without imputing missing sales."""
    frame = events.copy() if events is not None else pd.DataFrame()
    if frame.empty:
        return pd.DataFrame(columns=SHKP_FUTURE_PROJECT_SNAPSHOT_COLUMNS)
    for column in SHKP_FUTURE_PROJECT_EVENT_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    state_events = frame.loc[frame["state_after"].notna()].copy()
    rows: list[dict[str, Any]] = []
    for canonical_id, group in frame.groupby("canonical_project_id", dropna=False, sort=True):
        group = group.copy()
        lifecycle = state_events.loc[state_events["canonical_project_id"].eq(canonical_id)].copy()
        if lifecycle.empty:
            latest_state = None
            latest_state_event = None
            identity_only = group.loc[group["event_type"].eq("identity_bridge")]
            if not identity_only.empty and not (
                group["asset_scope"].fillna("").astype(str).str.startswith("commercial").all()
            ):
                # A lot/alias bridge without an SRPE id is an explicit
                # ``srpe_pending`` state, not an empty/zero-sales state.
                latest_state_event = identity_only.sort_values(
                    "observed_at", kind="stable", na_position="last"
                ).iloc[-1].to_dict()
                latest_state = "srpe_pending"
        else:
            lifecycle["_event_date"] = pd.to_datetime(lifecycle["event_date"], errors="coerce", utc=True)
            lifecycle["_observed_at"] = pd.to_datetime(lifecycle["observed_at"], errors="coerce", utc=True)
            lifecycle = lifecycle.sort_values(["_event_date", "_observed_at", "event_id"], kind="stable", na_position="last")
            latest_state_event = lifecycle.iloc[-1].to_dict()
            latest_state = _future_clean_text(latest_state_event.get("state_after"))
        latest = group.sort_values("observed_at", kind="stable", na_position="last").iloc[-1].to_dict()
        state_record = latest_state_event or latest
        urls: list[str] = []
        for value in group.get("source_urls_json", pd.Series(dtype="string")).tolist():
            try:
                parsed = json.loads(value) if value else []
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = []
            if isinstance(parsed, list):
                urls.extend(str(item) for item in parsed if _future_clean_text(item))
        urls.extend(str(value) for value in group.get("source_url", pd.Series(dtype="string")).tolist() if _future_clean_text(value))
        urls = list(dict.fromkeys(urls))
        commercial = (_future_clean_text(latest.get("asset_scope")) or "").startswith("commercial") or (_future_clean_text(latest_state) or "").startswith("commercial")
        if commercial:
            coverage = "commercial_separate_registry"
        elif latest_state in {"srpe_active_prelaunch"}:
            coverage = "srpe_identity_known_sales_queue_candidate"
        elif latest_state in {"planned_launch", "under_development", "srpe_pending", "srpe_lifecycle_unknown"}:
            coverage = "future_project_srpe_pending_or_unresolved"
        elif latest_state in {"sales_suspended", "sales_completed", "deleted", "srpe_inactive"}:
            coverage = "terminal_or_suspended_not_queue"
        else:
            coverage = "identity_observed_state_unknown"
        queue_values = [_future_clean_text(value) for value in group.get("sales_queue_status", pd.Series(dtype="string")).tolist() if _future_clean_text(value)]
        queue = next((value for value in reversed(queue_values) if value == "eligible_for_recent_srpe_queue"), queue_values[-1] if queue_values else "not_evaluated")
        rows.append(
            {
                "canonical_project_id": _future_clean_text(canonical_id),
                "project_label": _future_clean_text(latest.get("project_label")) or _future_clean_text(state_record.get("project_label")),
                "aliases_json": latest.get("aliases_json"),
                "asset_scope": _future_clean_text(latest.get("asset_scope")) or "residential_first_hand_or_unknown",
                "current_state": latest_state,
                "state_event_date": state_record.get("event_date"),
                "state_event_type": state_record.get("event_type"),
                "lot_no": latest.get("lot_no"),
                "address": latest.get("address"),
                "srpe_development_id": latest.get("srpe_development_id") or state_record.get("srpe_development_id"),
                "srpe_phase_name": latest.get("srpe_phase_name") or state_record.get("srpe_phase_name"),
                "units": latest.get("units"),
                "gfa_sqft": latest.get("gfa_sqft"),
                "expected_launch_window": latest.get("expected_launch_window"),
                "expected_completion_window": latest.get("expected_completion_window"),
                "ownership_low_pct": latest.get("ownership_low_pct"),
                "ownership_base_pct": latest.get("ownership_base_pct"),
                "ownership_high_pct": latest.get("ownership_high_pct"),
                "ownership_scenario_status": latest.get("ownership_scenario_status") or "not_observed",
                "sales_queue_status": queue,
                "coverage_status": coverage,
                "last_event_id": state_record.get("event_id") or latest.get("event_id"),
                "last_observed_at": latest.get("observed_at"),
                "source_urls_json": json.dumps(urls, ensure_ascii=False),
                "missing_data_policy": "unknown_is_not_zero; no_srpe_is_not_no_sales",
            }
        )
    result = pd.DataFrame(rows, columns=SHKP_FUTURE_PROJECT_SNAPSHOT_COLUMNS)
    result.attrs["lineage_metadata"] = {
        "lineage_type": "derived_shkp_future_project_current_snapshot",
        "source_dataset": "shkp_future_project_events",
        "append_only_source": True,
        "missing_data_policy": "unknown_is_not_zero; no_srpe_is_not_no_sales",
    }
    return result


def build_shkp_future_project_identity_evidence(
    *,
    last_verified_at: str | None = None,
) -> pd.DataFrame:
    """Return the bounded official lot/phase bridges for future labels.

    The rows are deliberately hand-curated evidence anchors, not inferred
    ownership records.  Keeping them normalized makes the identity work
    queryable and auditable while the SRPE index catches up with planned
    projects and phase-specific sales documents.
    """
    verified_at = last_verified_at or datetime.now(timezone.utc).isoformat()
    rows = []
    for evidence in SHKP_FUTURE_PROJECT_IDENTITY_EVIDENCE:
        row = dict(evidence)
        row["last_verified_at"] = verified_at
        rows.append(row)
    frame = pd.DataFrame(rows, columns=SHKP_FUTURE_PROJECT_IDENTITY_EVIDENCE_COLUMNS)
    frame.attrs.update(
        source_urls=list(dict.fromkeys(
            url
            for row in rows
            for url in (row.get("primary_source_url"), row.get("secondary_source_url"))
            if url
        )),
        lineage_metadata={
            "lineage_type": "curated_official_future_project_identity_evidence",
            "evidence_rows": len(frame),
            "ownership_inference": False,
            "sales_promotion": False,
        },
    )
    return frame


def build_shkp_phase_role_evidence(
    *,
    last_verified_at: str | None = None,
) -> pd.DataFrame:
    """Return static phase-scoped statutory role evidence without promotion.

    This fills the gap between a dynamic project-site parser and the legal
    ownership registry: role labels are useful for phase identity and JV
    review, but they never become a numeric ownership interval.
    """
    verified_at = last_verified_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for evidence in (*SHKP_PHASE_ROLE_EVIDENCE, *SHKP_PHASE_ROLE_EVIDENCE_ADDITIONS):
        row = dict(evidence)
        row.setdefault("ownership_pct", None)
        row.setdefault("effective_from", None)
        row.setdefault("effective_to", None)
        row["last_verified_at"] = verified_at
        rows.append(row)
    frame = pd.DataFrame(rows, columns=SHKP_PHASE_ROLE_EVIDENCE_COLUMNS)
    frame.attrs.update(
        source_urls=list(dict.fromkeys(str(row["source_url"]) for row in rows if row.get("source_url"))),
        lineage_metadata={
            "lineage_type": "curated_official_phase_role_evidence",
            "evidence_rows": len(frame),
            "ownership_inference": False,
            "promotion_policy": "role evidence never sets numeric ownership or effective interval",
        },
    )
    return frame


def build_shkp_ownership_coverage_audit(
    srpe_index: pd.DataFrame,
    *,
    phase_role_evidence: pd.DataFrame | None = None,
    legal_ownership_observations: pd.DataFrame | None = None,
    phase_attribution_decisions: pd.DataFrame | None = None,
    identity_evidence: pd.DataFrame | None = None,
    priority_phase_ids: Iterable[str] | None = None,
    last_verified_at: str | None = None,
) -> pd.DataFrame:
    """Audit evidence coverage without opening the attributable-sales gate.

    The legal-observation table intentionally covers only numeric subsidiary
    or project snapshots.  JV phases may instead have role evidence (owner,
    vendor or person-so-engaged) with no numeric percentage.  This audit keeps
    those cases visible and distinguishes ``role_only`` from a genuinely
    unobserved phase, while every row still requires an approved bounded
    attribution decision before sales can be promoted.
    """
    if srpe_index is None or srpe_index.empty:
        return pd.DataFrame(columns=SHKP_OWNERSHIP_COVERAGE_AUDIT_COLUMNS)

    priority = {
        str(value).strip()
        for value in (priority_phase_ids or ())
        if str(value).strip()
    }
    srpe = srpe_index.copy()
    if priority:
        srpe = srpe.loc[
            srpe.get("development_id", pd.Series(dtype="string"))
            .astype("string")
            .isin(priority)
        ]
    role = phase_role_evidence.copy() if phase_role_evidence is not None else pd.DataFrame()
    legal = legal_ownership_observations.copy() if legal_ownership_observations is not None else pd.DataFrame()
    decisions = phase_attribution_decisions.copy() if phase_attribution_decisions is not None else pd.DataFrame()
    identity = identity_evidence.copy() if identity_evidence is not None else pd.DataFrame()

    def _rows(frame: pd.DataFrame, development_id: str) -> list[dict[str, Any]]:
        if frame.empty or "srpe_development_id" not in frame.columns:
            return []
        return frame.loc[
            frame["srpe_development_id"].astype("string").eq(development_id)
        ].to_dict("records")

    def _urls(records: Iterable[Mapping[str, Any]]) -> list[str]:
        urls: list[str] = []
        for record in records:
            for field in (
                "source_url",
                "source_urls_json",
                "ownership_source_url",
                "phase_identity_source_url",
                "primary_source_url",
                "secondary_source_url",
            ):
                value = record.get(field)
                if field == "source_urls_json" and value:
                    try:
                        parsed = json.loads(str(value))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        parsed = []
                    values = parsed if isinstance(parsed, list) else []
                else:
                    values = [value]
                for url in values:
                    text = str(url or "").strip()
                    if text and text not in urls:
                        urls.append(text)
        return urls

    verified_at = last_verified_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for srpe_record in srpe.to_dict("records"):
        development_id = str(srpe_record.get("development_id") or "").strip()
        if not development_id:
            continue
        role_records = _rows(role, development_id)
        legal_records = _rows(legal, development_id)
        decision_records = _rows(decisions, development_id)
        identity_records = _rows(identity, development_id)
        numeric_records = [
            record
            for record in legal_records
            if pd.notna(pd.to_numeric(record.get("ownership_pct"), errors="coerce"))
        ]
        approved_records = [
            record
            for record in decision_records
            if _record_has_phase_specific_effective_interval(record)
        ]
        ready = bool(approved_records)
        has_identity = bool(identity_records)
        has_role = bool(role_records)
        has_legal = bool(legal_records)
        if ready:
            coverage_status = "approved_interval"
            coverage_gap = None
            next_evidence = "none"
        elif not has_identity and not has_role and not has_legal:
            coverage_status = "no_ownership_evidence"
            coverage_gap = "missing_identity_role_and_ownership_evidence"
            next_evidence = "phase-specific SRPE/project identity plus vendor/SPV/JV evidence"
        elif not has_identity and has_role and not has_legal:
            coverage_status = "role_only"
            coverage_gap = "identity_bridge_and_numeric_ownership_snapshot_missing"
            next_evidence = "phase-specific lot/SPV identity plus numeric SHKP/JV economics"
        elif has_legal and not ready:
            coverage_status = "numeric_snapshot_blocked"
            coverage_gap = "bounded_effective_interval_or_approved_decision_missing"
            next_evidence = "phase-specific SPV/JV/title-chain evidence with bounded effective_from/effective_to and review decision"
        else:
            coverage_status = "identity_role_blocked"
            coverage_gap = "numeric_ownership_and_approved_interval_missing"
            next_evidence = "phase-specific numeric SHKP/JV economics and bounded effective interval"
        records_for_urls = [*identity_records, *role_records, *legal_records, *decision_records]
        vendor_or_owner = " | ".join(
            dict.fromkeys(
                str(record.get("vendor_or_owner")).strip()
                for record in role_records
                if str(record.get("vendor_or_owner") or "").strip()
            )
        ) or None
        holding_companies = " | ".join(
            dict.fromkeys(
                str(record.get("holding_companies")).strip()
                for record in role_records
                if str(record.get("holding_companies") or "").strip()
            )
        ) or None
        rows.append(
            {
                "srpe_development_id": development_id,
                "srpe_development_name": srpe_record.get("development_name_en") or srpe_record.get("display_name"),
                "srpe_phase_name": srpe_record.get("phase_name_en"),
                "phase_identity_status": (
                    "identity_evidence_present"
                    if has_identity
                    else "role_or_registry_only"
                    if has_role or has_legal
                    else "not_observed"
                ),
                "identity_evidence_rows": len(identity_records),
                "phase_role_evidence_rows": len(role_records),
                "vendor_or_owner": vendor_or_owner,
                "holding_companies": holding_companies,
                "legal_ownership_observation_rows": len(legal_records),
                "numeric_snapshot_rows": len(numeric_records),
                "attribution_decision_rows": len(decision_records),
                "approved_interval_rows": len(approved_records),
                "ownership_attribution_ready": ready,
                "coverage_status": coverage_status,
                "coverage_gap": coverage_gap,
                "required_next_evidence": next_evidence,
                "source_urls_json": json.dumps(_urls(records_for_urls), ensure_ascii=False),
                "last_verified_at": verified_at,
            }
        )
    frame = pd.DataFrame(rows, columns=SHKP_OWNERSHIP_COVERAGE_AUDIT_COLUMNS)
    frame.attrs.update(
        lineage_metadata={
            "lineage_type": "shkp_ownership_evidence_coverage_audit",
            "audited_phase_rows": len(frame),
            "approved_interval_rows": int(frame["approved_interval_rows"].sum()) if not frame.empty else 0,
            "sales_promotion": False,
        },
    )
    return frame


def build_shkp_ownership_review_queue(
    project_registry: pd.DataFrame,
    sales_eligibility: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Materialise the unresolved ownership/JV review queue.

    The queue is intentionally narrower than the 522-row SRPE universe: it
    contains phases with retained SHKP/annual/planning/pipeline/manifest
    evidence but without a reconciled numeric ownership attribution.  It is a
    work queue, not a promoted ownership table.  Priority is driven by the
    sales gate and explicit JV/annual mismatch states, never by website names
    alone.
    """
    if project_registry.empty:
        return pd.DataFrame(columns=SHKP_OWNERSHIP_REVIEW_QUEUE_COLUMNS)
    eligibility = sales_eligibility if sales_eligibility is not None else pd.DataFrame()
    eligibility_by_id = {
        str(row.get("srpe_development_id") or ""): row
        for row in eligibility.to_dict("records")
        if str(row.get("srpe_development_id") or "")
    }
    rows: list[dict[str, Any]] = []
    for record in project_registry.to_dict("records"):
        if (
            str(record.get("ownership_status") or "") == "consistent_numeric"
            and bool(record.get("ownership_attribution_ready"))
            and _record_has_phase_specific_effective_interval(record)
        ):
            continue
        evidence_count_value = pd.to_numeric(record.get("evidence_count"), errors="coerce")
        evidence_count = int(evidence_count_value) if pd.notna(evidence_count_value) else 0
        manifest_present = str(record.get("manifest_status") or "") == "filings_available"
        if evidence_count <= 0 and not manifest_present:
            continue
        development_id = str(record.get("srpe_development_id") or "").strip()
        eligibility_row = eligibility_by_id.get(development_id, {})
        eligibility_status = eligibility_row.get("eligibility_status")
        reasons: list[str] = []
        layers: list[str] = []
        for layer, field in (
            ("shkp", "shkp_match_status"),
            ("annual", "annual_match_status"),
            ("planning", "planning_match_status"),
            ("pipeline", "pipeline_disclosure_match_status"),
            ("manifest", "manifest_status"),
        ):
            value = str(record.get(field) or "").strip()
            if value and value not in {"not_observed", "not_loaded"}:
                layers.append(layer)
        ownership_status = str(record.get("ownership_status") or "not_verified")
        if ownership_status == "annual_jv_unresolved":
            reasons.append("annual report says JV without a numeric group interest")
        elif ownership_status == "annual_numeric_unreconciled":
            reasons.append("annual numeric interest does not reconcile to the curated registry")
        elif ownership_status in {"curated_registry_only", "not_verified"}:
            reasons.append("no dated numeric legal-ownership evidence has been reconciled")
        if ownership_status == "consistent_numeric" and not _record_has_phase_specific_effective_interval(record):
            reasons.append("numeric ownership snapshot is present but no phase-specific bounded effective interval is reconciled")
        if str(record.get("planning_match_status") or "") in {"ambiguous", "matched_needs_review"}:
            reasons.append("LandsD/TPB evidence maps to multiple or review-only phase candidates")
        if str(record.get("pipeline_disclosure_match_status") or "") in {"ambiguous", "matched_needs_review"}:
            reasons.append("future/under-development disclosure remains a phase candidate, not ownership")
        if manifest_present:
            reasons.append("SRPE filing exists but sales promotion is blocked until ownership is reconciled")

        if eligibility_status == "ownership_review_required" or ownership_status == "annual_jv_unresolved":
            priority = "P0"
        elif ownership_status == "annual_numeric_unreconciled" or "planning" in layers:
            priority = "P1"
        else:
            priority = "P2"
        review_scope = "sales_promotion_blocker" if manifest_present else "ownership_mapping_review"
        if ownership_status == "annual_jv_unresolved":
            next_source = "dated JV agreement, land-grant/SPV filing, or HKEX disclosure with numeric interest"
        elif "planning" in layers:
            next_source = "LandsD land-grant/consent plus SPV/vendor and dated HKEX or annual-report evidence"
        else:
            next_source = "SHKP annual report, HKEX announcement, or official land-grant/vendor document"
        rows.append(
            {
                "registry_key": record.get("registry_key"),
                "srpe_development_id": development_id,
                "development_name_en": record.get("development_name_en"),
                "phase_name_en": record.get("phase_name_en"),
                "address_en": record.get("address_en"),
                "ownership_status": ownership_status,
                "ownership_attribution_ready": False,
                "eligibility_status": eligibility_status,
                "review_scope": review_scope,
                "review_priority": priority,
                "evidence_layers_present": "|".join(layers),
                "evidence_count": evidence_count,
                "annual_group_interest_raw": record.get("annual_group_interest_raw"),
                "annual_group_interest_pct": record.get("annual_group_interest_pct"),
                "planning_lot_nos": record.get("planning_lot_nos"),
                "planning_entity_labels": record.get("planning_entity_labels"),
                "review_reason": " | ".join(dict.fromkeys(reasons)),
                "suggested_next_source": next_source,
                "source_urls_json": record.get("source_urls_json"),
                "last_verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=SHKP_OWNERSHIP_REVIEW_QUEUE_COLUMNS)


def fetch_shkp_land_planning_documents(
    *,
    session: requests.Session | None = None,
    timeout: float = 60,
) -> pd.DataFrame:
    """Catalog LandsD/TPB/BD source links for later project-level matching.

    The output intentionally stops at the source-document/application grain:
    it does not infer that a land lot or planning application belongs to an
    SHKP phase.  The OZP portal is currently a client-rendered shell, so its
    page-only status is preserved rather than represented as zero applications.
    """
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "text/html, */*"})
    fetched_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []

    for source in SHKP_SUPPORTING_SOURCES:
        source_id = source["source_id"]
        source_url = source["source_url"]
        if source_id == "srpe_all_development":
            records.append(
                {
                    "source_id": source_id,
                    "agency": source["agency"],
                    "evidence_type": source["evidence_type"],
                    "title": "SRPE index is ingested by the dedicated API contract",
                    "document_url": source_url,
                    "source_url": source_url,
                    "record_id": source_id,
                    "status": "api_contract",
                    "fetched_at": fetched_at,
                }
            )
            continue
        response = client.get(source_url, timeout=timeout)
        response.raise_for_status()
        raw_path = save_raw_snapshot(
            f"shkp_{source_id}_landing",
            response.content,
            file_ext="html",
            source_url=source_url,
        )
        raw_snapshots.append(str(raw_path))
        source_urls.append(source_url)
        soup = BeautifulSoup(response.text, "html.parser")
        candidate_links: list[tuple[str, str]] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            href_compact = re.sub(r"\s+", "", href)
            href_lower = href_compact.lower()
            if source_id.startswith("landsd_") and not href_lower.split("?")[0].endswith((".pdf", ".xls", ".xlsx")):
                continue
            if source_id == "tpb_applications_under_processing" and not is_tpb_application_detail_url(urljoin(source_url, href_compact)):
                continue
            if source_id == "tpb_statutory_planning_portal":
                continue
            if source_id == "buildings_department_md53_md56" and not href_lower.endswith((".xls", ".xlsx")):
                continue
            document_url = urljoin(source_url, href_compact)
            title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
            if not title:
                title = document_url.rsplit("/", 1)[-1] or source_id
            candidate_links.append((title, document_url))

        seen: set[str] = set()
        for ordinal, (title, document_url) in enumerate(candidate_links, start=1):
            if document_url in seen:
                continue
            seen.add(document_url)
            records.append(
                {
                    "source_id": source_id,
                    "agency": source["agency"],
                    "evidence_type": source["evidence_type"],
                    "title": title,
                    "document_url": document_url,
                    "source_url": source_url,
                    "record_id": f"{source_id}:{ordinal}",
                    "status": "document_link",
                    "fetched_at": fetched_at,
                }
            )
        if not seen:
            records.append(
                {
                    "source_id": source_id,
                    "agency": source["agency"],
                    "evidence_type": source["evidence_type"],
                    "title": "Source page returned no structured links",
                    "document_url": source_url,
                    "source_url": source_url,
                    "record_id": f"{source_id}:page",
                    "status": "page_only",
                    "fetched_at": fetched_at,
                }
            )

    frame = pd.DataFrame(records, columns=LAND_PLANNING_DOCUMENT_COLUMNS)
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["source_id", "document_url"]).reset_index(drop=True)
    frame.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        lineage_metadata={
            "lineage_type": "official_land_planning_document_catalog",
            # Parquet pandas metadata requires JSON-safe scalar keys; the
            # natural groupby tuple keys must be flattened before storage.
            "source_counts": {
                f"{source_id}|{status}": int(count)
                for (source_id, status), count in frame.groupby(["source_id", "status"]).size().items()
            } if not frame.empty else {},
            "project_matching_completed": False,
        },
    )
    return frame


def _completed_property_number(words: list[dict[str, Any]]) -> int | None:
    """Parse a numeric GFA cell, treating the report dash as missing."""
    tokens = [str(word.get("text") or "").strip() for word in words]
    tokens = [token for token in tokens if token]
    if not tokens or all(token in {"–", "-", "—"} for token in tokens):
        return None
    match = re.search(r"\d[\d,]*", "".join(tokens))
    if not match:
        return None
    return int(match.group(0).replace(",", ""))


def _completed_property_metric_rows(
    words: list[dict[str, Any]],
    *,
    page_number: int,
) -> list[dict[str, Any]]:
    """Parse the aligned GFA rows on the completed-property metrics page.

    This page is a visual table rather than a reliable text stream.  The
    column anchors are stable across the current annual-report template and
    are intentionally expressed as ranges, so a dash or a number shifting a
    few points does not move it into an adjacent usage bucket.
    """
    lines = _group_pdf_words_by_top(words, tolerance=4.5)
    rows: list[dict[str, Any]] = []
    # Lease expiries can extend past 2099 (the current table includes 2127
    # and 2842), so this is deliberately any four-digit year rather than
    # ``20xx`` only.
    lease_pattern = re.compile(r"\d{4}(?:/\d{4})*")
    for line in lines:
        lease_words = [
            word for word in line
            if float(word.get("x0", 0)) < 145
        ]
        lease_raw = " ".join(str(word.get("text") or "") for word in lease_words).strip()
        if not lease_pattern.fullmatch(lease_raw):
            continue
        # Boundaries follow the printed column starts (~169, 239, 280/302,
        # 336, 393/415, 449/472, 501).  The generous gaps absorb template
        # kerning without allowing the total column into industrial.
        def collect(x_min: float, x_max: float | None = None) -> list[dict[str, Any]]:
            return [
                word for word in line
                if float(word.get("x0", 0)) >= x_min
                and (x_max is None or float(word.get("x0", 0)) < x_max)
            ]

        interest_words = collect(145, 200)
        interest_raw = " ".join(str(word.get("text") or "") for word in interest_words).strip() or None
        interest_match = re.search(r"\d+(?:\.\d+)?", interest_raw or "")
        rows.append(
            {
                "lease_expiry_raw": lease_raw,
                "group_interest_raw": interest_raw,
                "group_interest_pct": float(interest_match.group(0)) if interest_match else None,
                "residential_gfa_sqft": _completed_property_number(collect(200, 252)),
                "shopping_centre_gfa_sqft": _completed_property_number(collect(252, 325)),
                "office_gfa_sqft": _completed_property_number(collect(325, 385)),
                "hotel_gfa_sqft": _completed_property_number(collect(385, 445)),
                "industrial_gfa_sqft": _completed_property_number(collect(445, 500)),
                "total_gfa_sqft": _completed_property_number(collect(500)),
                "metrics_page_number": page_number,
            }
        )
    return rows


def _completed_property_project_rows(
    words: list[dict[str, Any]],
    *,
    page_number: int,
) -> list[dict[str, Any]]:
    """Parse project/location rows from the preceding completed-assets page."""
    lines = _group_pdf_words_by_top(words, tolerance=4.5)
    header_index = next(
        (
            index for index, line in enumerate(lines)
            if "project" in {str(word.get("text") or "").lower() for word in line}
            and "location" in {str(word.get("text") or "").lower() for word in line}
        ),
        None,
    )
    if header_index is None:
        return []
    district_names = {"hong kong island", "kowloon", "new territories"}
    row_starts: list[int] = []
    for index in range(header_index + 1, len(lines)):
        line = lines[index]
        text = " ".join(str(word.get("text") or "") for word in line).strip()
        if text.startswith("(") or "SUN HUNG KAI PROPERTIES" in text or "ANNUAL REPORT" in text:
            break
        project_x_positions = [float(word.get("x0", 0)) for word in line if float(word.get("x0", 0)) < 300]
        has_project = bool(project_x_positions)
        has_location = any(float(word.get("x0", 0)) >= 300 for word in line)
        # Wrapped continuation rows (e.g. ``The Silveri...`` beneath
        # Citygate) are indented by ~9pt; genuine project starts sit at the
        # 62pt margin.  Requiring the margin prevents a continuation with its
        # own wrapped address from becoming a duplicate asset.
        if has_project and has_location and min(project_x_positions) < 67 and text.lower() not in district_names:
            row_starts.append(index)
    rows: list[dict[str, Any]] = []
    current_district = None
    for position, start in enumerate(row_starts):
        # Keep the section heading immediately preceding this row.  A district
        # heading itself has no right-hand location cell and is not a row
        # start, so it is safe to scan the small prefix here.
        for line in lines[header_index + 1 : start + 1]:
            text = " ".join(str(word.get("text") or "") for word in line).strip().lower()
            if text in district_names:
                current_district = text.title()
        end = row_starts[position + 1] if position + 1 < len(row_starts) else len(lines)
        row_lines = lines[start:end]
        filtered_row_lines = [
            line for line in row_lines
            if " ".join(str(word.get("text") or "") for word in line).strip().lower() not in district_names
            and not " ".join(str(word.get("text") or "") for word in line).strip().startswith("(")
            and not "SUN HUNG KAI PROPERTIES" in " ".join(str(word.get("text") or "") for word in line)
            and not "ANNUAL REPORT" in " ".join(str(word.get("text") or "") for word in line)
            and not "Including" == str(line[0].get("text") or "").strip()
        ]
        project_words = [
            word for line in filtered_row_lines for word in line
            if float(word.get("x0", 0)) < 300
            and str(word.get("text") or "").strip() not in {"(1)", "(2)"}
        ]
        location_words = [
            word for line in filtered_row_lines for word in line
            if float(word.get("x0", 0)) >= 300
        ]
        project_label = " ".join(str(word.get("text") or "") for word in project_words).strip()
        location = " ".join(str(word.get("text") or "") for word in location_words).strip()
        if not project_label or not location:
            continue
        rows.append(
            {
                "project_label_raw": project_label,
                "location_raw": location,
                "geography": current_district or "Hong Kong",
                "project_page_number": page_number,
            }
        )
    return rows


def _build_shkp_completed_property_rows(
    project_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
    *,
    report_id: str,
    report_period_end: str,
    document_url: str,
    fetched_at: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pair the two printed pages without guessing when row counts differ."""
    summary = {
        "project_rows": len(project_rows),
        "metric_rows": len(metric_rows),
        "aligned_rows": 0,
        "status": "aligned" if len(project_rows) == len(metric_rows) else "row_count_mismatch",
    }
    if not project_rows or len(project_rows) != len(metric_rows):
        return [], summary
    records: list[dict[str, Any]] = []
    for ordinal, (project, metric) in enumerate(zip(project_rows, metric_rows), start=1):
        label_key = re.sub(r"[^a-z0-9]+", "-", project["project_label_raw"].lower()).strip("-")
        property_id = f"{report_id}:completed:{ordinal}:{label_key}"
        component_sum = sum(
            int(metric.get(column) or 0)
            for column in (
                "residential_gfa_sqft",
                "shopping_centre_gfa_sqft",
                "office_gfa_sqft",
                "hotel_gfa_sqft",
                "industrial_gfa_sqft",
            )
        )
        total_gfa = metric.get("total_gfa_sqft")
        reconciliation_status = (
            "missing_total"
            if total_gfa is None
            else "reconciled"
            if int(total_gfa) == component_sum
            else "component_total_mismatch"
        )
        records.append(
            {
                "completed_property_id": property_id,
                "report_id": report_id,
                "report_period_end": report_period_end,
                **project,
                **metric,
                "gfa_components_sum_sqft": component_sum,
                "gfa_reconciliation_status": reconciliation_status,
                "evidence_status": "found",
                "ownership_semantics": "Group's Interest (%) reported at report period end; not a dated legal-SPV interval",
                "caveat": "Attributable GFA exposure metadata only; not rental income, NOI, valuation or recognized revenue. Do not sum with the development pipeline.",
                "evidence_context": f"{project['project_label_raw']} | {project['location_raw']} | lease {metric['lease_expiry_raw']} | interest {metric['group_interest_raw']}",
                "document_url": document_url,
                "source_url": document_url,
                "fetched_at": fetched_at,
            }
        )
    summary["aligned_rows"] = len(records)
    return records, summary


def fetch_shkp_annual_report_pipeline(
    *,
    session: requests.Session | None = None,
    timeout: float = 90,
    reports: Iterable[Mapping[str, Any]] | None = None,
) -> pd.DataFrame:
    """Extract SHKP annual-report project-table and pipeline evidence.

    This deliberately returns evidence rows, not a completed ownership
    registry.  The handover table's ``JV`` value remains raw when the report
    does not publish a percentage; descriptive future-project labels remain
    descriptive until SRPE/LandsD/TPB/BD evidence supplies a stable ID.
    """
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "application/pdf,*/*"})
    fetched_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    parse_summary: list[dict[str, Any]] = []
    completed_property_records: list[dict[str, Any]] = []

    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - project dependency is declared
        raise RuntimeError("pdfplumber is required for SHKP annual-report extraction") from exc

    report_configs = tuple(reports or SHKP_ANNUAL_REPORTS)
    for report in report_configs:
        document_url = str(report["url"])
        # SHKP's asset host occasionally serves a short HTML edge/error page
        # for an otherwise valid PDF URL.  Do not persist that body as a
        # document or fail immediately: retry the same official URL a few
        # times, while keeping the final error explicit if the outage lasts.
        response = None
        for attempt in range(3):
            candidate = client.get(document_url, timeout=timeout)
            candidate.raise_for_status()
            if candidate.content.lstrip().startswith(b"%PDF"):
                response = candidate
                break
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
        if response is None:
            content_type = candidate.headers.get("content-type", "") if candidate is not None else ""
            prefix = (candidate.content[:80] if candidate is not None else b"").decode("utf-8", errors="replace")
            raise ValueError(
                f"SHKP annual-report URL returned non-PDF content after 3 attempts: "
                f"{document_url} (content_type={content_type!r}, prefix={prefix!r})"
            )
        raw_path = save_raw_snapshot(
            f"{report['report_id']}_pdf",
            response.content,
            file_ext="pdf",
            source_url=document_url,
        )
        raw_snapshots.append(str(raw_path))
        source_urls.append(document_url)
        handover_rows = 0
        future_rows = 0
        major_project_rows = 0
        completed_project_rows: list[dict[str, Any]] = []
        completed_property_summary: dict[str, Any] = {
            "project_rows": 0,
            "metric_rows": 0,
            "aligned_rows": 0,
            "status": "not_found",
        }
        pipeline_evidence: dict[str, tuple[int, str]] = {}
        in_major_projects_section = False
        with pdfplumber.open(BytesIO(response.content)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
                normalized_text = re.sub(r"\s+", " ", text).strip()
                if (
                    "Major Completed Properties in Hong Kong" in normalized_text
                    and completed_property_summary.get("status") != "aligned"
                ):
                    candidate_project_rows = _completed_property_project_rows(
                        page.extract_words(x_tolerance=1, y_tolerance=3),
                        page_number=page_number,
                    )
                    if candidate_project_rows:
                        completed_project_rows = candidate_project_rows
                        completed_property_summary["project_page_number"] = page_number
                if (
                    completed_project_rows
                    and "Attributable Gross Floor Area (square feet)" in normalized_text
                ):
                    metric_rows = _completed_property_metric_rows(
                        page.extract_words(x_tolerance=1, y_tolerance=3),
                        page_number=page_number,
                    )
                    completed_records, completed_property_summary = _build_shkp_completed_property_rows(
                        completed_project_rows,
                        metric_rows,
                        report_id=str(report["report_id"]),
                        report_period_end=str(report["report_period_end"]),
                        document_url=document_url,
                        fetched_at=fetched_at,
                    )
                    completed_property_records.extend(completed_records)
                    completed_property_summary["metrics_page_number"] = page_number
                    completed_project_rows = []
                # The handover table changed its area header between report
                # vintages (``Attributable ...`` versus ``Gross Floor Area``).
                # Use the stable column labels rather than a single template
                # phrase so older annual reports are not silently skipped.
                has_handover_header = all(
                    token in normalized_text
                    for token in ("Project", "Location", "Interest")
                ) and ("Attributable" in normalized_text or "Gross Floor Area" in normalized_text)
                if has_handover_header:
                    geography = "Mainland" if "Property Business – Mainland" in normalized_text or "Property Business - Mainland" in normalized_text else "Hong Kong"
                    table_rows = _parse_shkp_handover_table_words(
                        page.extract_words(x_tolerance=1, y_tolerance=3),
                        page_number=page_number,
                        geography=geography,
                    )
                    for row in table_rows:
                        handover_rows += 1
                        row_geography = _classify_shkp_annual_row_geography(
                            row.get("location"),
                            geography,
                        )
                        records.append(
                            {
                                "report_id": report["report_id"],
                                "report_period_end": report["report_period_end"],
                                "evidence_type": "handover_table",
                                **row,
                                "project_state": "handover_completed",
                                "geography": row_geography,
                                "evidence_status": "found",
                                "document_url": document_url,
                                "source_url": document_url,
                                "fetched_at": fetched_at,
                            }
                        )
                if "Major Projects under Development" in normalized_text:
                    in_major_projects_section = True
                if in_major_projects_section and re.search(
                    r"\(?\s*(?:\d+(?:\.\d+)?\s*%\s*owned|joint\s+venture)\s*\)?",
                    normalized_text,
                    flags=re.IGNORECASE,
                ):
                    major_rows = _parse_shkp_major_project_page_words(
                        page.extract_words(x_tolerance=1, y_tolerance=3),
                        page_width=page.width,
                        page_number=page_number,
                        geography="Hong Kong",
                    )
                    for row in major_rows:
                        major_project_rows += 1
                        records.append(
                            {
                                "report_id": report["report_id"],
                                "report_period_end": report["report_period_end"],
                                **row,
                                "document_url": document_url,
                                "source_url": document_url,
                                "fetched_at": fetched_at,
                            }
                        )
                # The section is a finite narrative block.  Once a page no
                # longer carries either an expected-completion field or a
                # project ownership anchor, do not scan the remainder of the
                # report for unrelated percentage disclosures.
                if in_major_projects_section and page_number > 1 and not (
                    "Expected date of" in normalized_text
                    or re.search(r"\b(?:%\s*owned|Joint Venture)\b", normalized_text, flags=re.IGNORECASE)
                ):
                    in_major_projects_section = False

                if not report.get("include_pipeline_anchors", True):
                    continue
                for item in SHKP_ANNUAL_PIPELINE_ITEMS:
                    evidence_status, context = _phrase_context(normalized_text, item["search_phrase"])
                    if evidence_status == "found" and item["project_label"] not in pipeline_evidence:
                        pipeline_evidence[item["project_label"]] = (page_number, context)

            # Emit exactly one row per configured evidence anchor after all
            # pages have been scanned.  This avoids marking an item as
            # not-found on the final page after it was already found earlier.
            if report.get("include_pipeline_anchors", True):
                for item in SHKP_ANNUAL_PIPELINE_ITEMS:
                    if item["project_label"] in pipeline_evidence:
                        evidence_status = "found"
                        page_number, context = pipeline_evidence[item["project_label"]]
                    else:
                        evidence_status = "not_found"
                        page_number, context = len(pdf.pages), ""
                    future_rows += 1
                    records.append(
                        {
                            "report_id": report["report_id"],
                            "report_period_end": report["report_period_end"],
                            "evidence_type": "future_pipeline_text",
                            "project_label": item["project_label"],
                            "location": None,
                            "usage": None,
                            "group_interest_raw": None,
                            "group_interest_pct": None,
                            "attributable_gfa_sqft": None,
                            "site_area_sqft": None,
                            "gross_floor_area_sqft": None,
                            "residential_gfa_sqft": None,
                            "retail_gfa_sqft": None,
                            "approximate_units": None,
                            "completion_window": None,
                            "ownership_basis": None,
                            "source_section": "future_pipeline_text",
                            "project_state": item["project_state"],
                            "geography": item["geography"],
                            "page_number": page_number,
                            "evidence_status": evidence_status,
                            "evidence_context": context,
                            "document_url": document_url,
                            "source_url": document_url,
                            "fetched_at": fetched_at,
                        }
                    )
        parse_summary.append(
            {
                "report_id": report["report_id"],
                "handover_rows": handover_rows,
                "future_pipeline_rows": future_rows,
                "major_project_rows": major_project_rows,
                "completed_property_rows": int(completed_property_summary.get("aligned_rows", 0)),
                "completed_property_parse": completed_property_summary,
            }
        )

    frame = pd.DataFrame(records, columns=ANNUAL_REPORT_PROJECT_COLUMNS)
    if not frame.empty:
        frame = frame.drop_duplicates(
            subset=["report_id", "evidence_type", "project_label", "page_number"]
        ).reset_index(drop=True)
    frame.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        # Keep attrs JSON-safe: ``save_normalized_dataset`` writes this frame
        # to Parquet, and pandas/pyarrow attempts to serialize attrs as file
        # metadata.  The catalog runner reconstructs the dedicated asset
        # frame from this record list before persistence.
        completed_properties_records=completed_property_records,
        lineage_metadata={
            "lineage_type": "official_annual_report_pdf_evidence",
            "parse_summary": parse_summary,
            "completed_property_rows": len(completed_property_records),
            "ownership_registry_ready": False,
        },
    )
    return frame


def fetch_shkp_history_milestones(
    *,
    session: requests.Session | None = None,
    timeout: float = 60,
) -> pd.DataFrame:
    """Fetch the official SHKP History and Milestones project evidence page.

    The page is rendered as one ``.year-projects`` block per calendar year,
    with one ``.project-block`` per milestone.  This parser deliberately
    preserves the issuer's milestone wording instead of pretending that a
    sentence such as ``Hands over A, B and C`` is an individual phase-level
    observation.  A later reconciliation layer can split/alias those labels
    against SRPE, annual reports and project-site evidence.
    """
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "text/html, */*"})
    response = client.get(SHKP_HISTORY_MILESTONES_URL, timeout=timeout)
    response.raise_for_status()
    raw_path = save_raw_snapshot(
        "shkp_history_and_milestones_page",
        response.content,
        file_ext="html",
        source_url=SHKP_HISTORY_MILESTONES_URL,
    )
    soup = BeautifulSoup(response.text, "html.parser")
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    year_blocks = soup.select(".year-projects[data-year]")
    for year_block in year_blocks:
        raw_year = str(year_block.get("data-year") or "").strip()
        try:
            milestone_year = int(raw_year)
        except (TypeError, ValueError):
            milestone_year = None
        for ordinal, block in enumerate(year_block.select(".project-block"), start=1):
            summary = " ".join(
                str(block.select_one(".project-summary").get_text(" ", strip=True)).split()
            ) if block.select_one(".project-summary") else ""
            image = block.select_one(".project-image img")
            image_alt = " ".join(str(image.get("alt") or "").split()) if image else ""
            project_label = summary or image_alt
            image_url = urljoin(SHKP_HISTORY_MILESTONES_URL, str(image.get("src") or "")) if image else ""
            if not project_label and not image_url:
                continue
            key = f"{raw_year}|{ordinal}|{project_label}|{image_url}"
            milestone_id = f"shkp_milestone:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}"
            rows.append(
                {
                    "milestone_id": milestone_id,
                    "milestone_year": milestone_year,
                    "project_label": project_label or None,
                    "milestone_summary": summary or image_alt or None,
                    "image_url": image_url or None,
                    "source_page_url": SHKP_HISTORY_MILESTONES_URL,
                    "source_url": SHKP_HISTORY_MILESTONES_URL,
                    "fetched_at": fetched_at,
                    "evidence_status": "parsed_official_milestone",
                    "parse_version": "history_milestones_v1",
                }
            )
    if not year_blocks:
        raise SHKPSourceUnavailable(
            "SHKP History and Milestones page returned no year-projects blocks"
        )
    frame = pd.DataFrame(rows, columns=HISTORY_MILESTONE_COLUMNS)
    if frame.empty:
        raise SHKPSourceUnavailable(
            "SHKP History and Milestones page returned no project milestone rows"
        )
    frame = frame.drop_duplicates(subset=["milestone_id"]).sort_values(
        ["milestone_year", "milestone_id"], ascending=[False, True], na_position="last"
    ).reset_index(drop=True)
    frame.attrs.update(
        raw_snapshot=str(raw_path),
        raw_snapshots=[str(raw_path)],
        source_url=SHKP_HISTORY_MILESTONES_URL,
        source_urls=[SHKP_HISTORY_MILESTONES_URL],
        lineage_metadata={
            "lineage_type": "official_shkp_history_and_milestones_evidence",
            "year_block_count": len(year_blocks),
            "milestone_rows": int(len(frame)),
            "phase_level_ownership_ready": False,
            "parse_version": "history_milestones_v1",
        },
    )
    return frame


def build_shkp_history_milestone_crosswalk(
    milestones: pd.DataFrame,
    srpe_index: pd.DataFrame,
) -> pd.DataFrame:
    """Map milestone wording to conservative SRPE phase candidates.

    Only exact normalized phrase containment is used.  Phase-name matches are
    ranked above development-name matches; ties remain ``ambiguous`` and all
    candidate IDs are retained.  This is an identity-review layer, never an
    ownership or sales-attribution decision.
    """
    if milestones is None or milestones.empty or srpe_index is None or srpe_index.empty:
        return pd.DataFrame(columns=HISTORY_MILESTONE_CROSSWALK_COLUMNS)

    def _norm(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    srpe_records = srpe_index.to_dict("records")
    rows: list[dict[str, Any]] = []
    for milestone in milestones.to_dict("records"):
        text = _norm(milestone.get("milestone_summary") or milestone.get("project_label"))
        candidates: list[tuple[int, dict[str, Any], str]] = []
        for candidate in srpe_records:
            phase = _norm(candidate.get("phase_name_en"))
            development = _norm(candidate.get("development_name_en"))
            score = 0
            method = ""
            if phase and len(phase) >= 5 and phase in text:
                score, method = 3, "phase_name_exact_in_milestone"
            elif development and len(development) >= 5 and development in text:
                score, method = 2, "development_name_exact_in_milestone"
            elif development.endswith("development"):
                base = development[: -len("development")]
                if len(base) >= 5 and base in text:
                    score, method = 1, "development_name_suffix_exact_in_milestone"
            if score:
                candidates.append((score, candidate, method))
        best_score = max((value[0] for value in candidates), default=0)
        best = [value for value in candidates if value[0] == best_score]
        candidate_ids = list(dict.fromkeys(str(value[1].get("development_id")) for value in best))
        if not best:
            best = [(0, {}, "none")]
        status = "matched_needs_review" if len(candidate_ids) == 1 else "ambiguous" if candidate_ids else "unmatched"
        for score, candidate, method in best:
            rows.append(
                {
                    "milestone_id": milestone.get("milestone_id"),
                    "milestone_year": milestone.get("milestone_year"),
                    "milestone_summary": milestone.get("milestone_summary"),
                    "project_label": milestone.get("project_label"),
                    "srpe_development_id": candidate.get("development_id") or None,
                    "srpe_development_name": candidate.get("development_name_en") or None,
                    "srpe_phase_name": candidate.get("phase_name_en") or None,
                    "match_status": status,
                    "match_method": method,
                    "match_score": score or None,
                    "candidate_count": len(candidate_ids),
                    "candidate_ids_json": json.dumps(candidate_ids, ensure_ascii=False),
                    "evidence_status": "identity_review_only",
                    "ownership_promotion_status": "blocked_no_phase_specific_ownership_interval",
                    "source_url": milestone.get("source_url"),
                    "last_verified_at": milestone.get("fetched_at") or datetime.now(timezone.utc).isoformat(),
                }
            )
    frame = pd.DataFrame(rows, columns=HISTORY_MILESTONE_CROSSWALK_COLUMNS)
    frame.attrs.update(
        source_urls=list(frame["source_url"].dropna().astype(str).drop_duplicates()) if not frame.empty else [],
        lineage_metadata={
            "lineage_type": "derived_shkp_history_milestone_srpe_identity_crosswalk",
            "match_policy": "exact_normalized_phrase_containment_only; phase_name_ranked_above_development_name",
            "ownership_promotion": False,
            "sales_attribution": False,
        },
    )
    return frame


def fetch_shkp_corporate_documents(
    *,
    session: requests.Session | None = None,
    timeout: float = 60,
) -> pd.DataFrame:
    """Catalog SHKP annual/interim reports, quarterly articles and filings.

    This is intentionally a document catalogue.  PDF table extraction and
    point-in-time corporate metrics are separate stages so that a changed
    website link cannot silently become a fabricated sales series.
    """
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "text/html, */*"})
    fetched_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    page_pdf_counts: list[dict[str, Any]] = []
    for page_kind, page_url in SHKP_CORPORATE_PAGES:
        response = None
        anchors: list[Any] = []
        for attempt in range(3):
            response = client.get(page_url, timeout=timeout)
            response.raise_for_status()
            raw_path = save_raw_snapshot(
                f"shkp_{page_kind}_page" if attempt == 0 else f"shkp_{page_kind}_page_retry",
                response.content,
                file_ext="html",
                source_url=page_url,
            )
            raw_snapshots.append(str(raw_path))
            soup = BeautifulSoup(response.text, "html.parser")
            anchors = [
                anchor
                for anchor in soup.find_all("a", href=True)
                if str(anchor.get("href") or "").strip().lower().endswith(".pdf")
            ]
            if anchors or page_kind == "announcement":
                break
            time.sleep(0.5 * (attempt + 1))
        if response is None:  # pragma: no cover - defensive; requests always returns a response
            raise RuntimeError(f"SHKP corporate page was not fetched: {page_url}")
        if not anchors and page_kind in {"financial_results_reports", "quarterly_article"}:
            raise SHKPSourceUnavailable(
                f"SHKP corporate page returned no PDF links after 3 attempts: {page_url}"
            )
        source_urls.append(page_url)
        page_pdf_counts.append({"page_kind": page_kind, "pdf_links": len(anchors)})
        seen: set[str] = set()
        for anchor in anchors:
            href = str(anchor.get("href") or "").strip()
            document_url = urljoin(page_url, href)
            if document_url in seen:
                continue
            seen.add(document_url)
            title = anchor.get_text(" ", strip=True) or document_url.rsplit("/", 1)[-1]
            records.append(
                {
                    "document_type": _document_type_from_link(page_kind, title, document_url),
                    "title": re.sub(r"\s+", " ", title).strip(),
                    "document_url": document_url,
                    "source_page_url": page_url,
                    "source_url": page_url,
                    "published_date": _published_date_from_text(title),
                    "fetched_at": fetched_at,
                }
            )
    frame = enrich_shkp_corporate_document_release_dates(
        pd.DataFrame(records, columns=CORPORATE_DOCUMENT_COLUMNS)
    )
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["document_type", "document_url"]).reset_index(drop=True)
    frame.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        lineage_metadata={
            "lineage_type": "official_website_document_catalog",
            "page_count": len(SHKP_CORPORATE_PAGES),
            "page_pdf_counts": page_pdf_counts,
        },
    )
    return frame


def build_shkp_historical_annual_report_index(
    corporate_documents: pd.DataFrame,
) -> pd.DataFrame:
    """Build an auditable index of issuer annual-report vintages.

    The corporate-document catalogue already exposes official annual-report
    PDFs back to 2001/02.  Keep that availability history separate from the
    layout-specific project parser: a report can be a valid historical source
    even while its project pages remain ``pending`` for manual/template audit.
    No project or ownership fact is inferred here.
    """
    if corporate_documents is None or corporate_documents.empty:
        return pd.DataFrame(columns=HISTORICAL_ANNUAL_REPORT_INDEX_COLUMNS)
    documents = corporate_documents.copy()
    documents = documents.loc[
        documents.get("document_type", pd.Series(dtype="string")).astype("string").eq("annual_report")
    ].copy()
    if documents.empty:
        return pd.DataFrame(columns=HISTORICAL_ANNUAL_REPORT_INDEX_COLUMNS)

    rows: list[dict[str, Any]] = []
    pattern = re.compile(r"(?:annual\s+report|ar)[^0-9]*(20\d{2})[\s/_-]*(\d{2})", re.IGNORECASE)
    for record in documents.to_dict("records"):
        title = str(record.get("title") or "")
        url = str(record.get("document_url") or "")
        match = pattern.search(f"{title} {unquote(url)}")
        if not match:
            # Keep an unparsed official PDF visible instead of dropping it.
            start_year = end_year = None
            report_label = title or url.rsplit("/", 1)[-1]
        else:
            start_year = int(match.group(1))
            end_suffix = int(match.group(2))
            end_year = (start_year // 100) * 100 + end_suffix
            if end_year <= start_year:
                end_year += 100
            report_label = f"Annual Report {start_year}/{end_suffix:02d}"
        report_id = (
            f"shkp_ar_{start_year}_{end_year % 100:02d}"
            if start_year is not None and end_year is not None
            else f"shkp_ar_unparsed:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]}"
        )
        document_variant = "text_only" if "text only" in f"{title} {url}".casefold() else "full_pdf"
        report_document_id = f"{report_id}:{document_variant}:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:8]}"
        rows.append(
            {
                "report_document_id": report_document_id,
                "report_id": report_id,
                "report_label": report_label,
                "document_variant": document_variant,
                "report_period_end": f"{end_year}-06-30" if end_year is not None else None,
                "document_url": url,
                "source_page_url": record.get("source_page_url"),
                "issuer_release_date": record.get("issuer_release_date"),
                "hkex_release_at": record.get("hkex_release_at"),
                "release_source_url": record.get("release_source_url"),
                "document_status": "available_official_pdf" if url else "missing_url",
                "project_table_parse_status": "pending_template_audit",
                "evidence_type": "official_issuer_annual_report",
                "fetched_at": record.get("fetched_at"),
            }
        )
    frame = pd.DataFrame(rows, columns=HISTORICAL_ANNUAL_REPORT_INDEX_COLUMNS)
    frame = frame.drop_duplicates(subset=["report_document_id"]).sort_values(
        ["report_period_end", "report_id"], na_position="last"
    ).reset_index(drop=True)
    frame.attrs.update(
        source_urls=list(dict.fromkeys(str(value) for value in documents.get("source_page_url", pd.Series(dtype="string")).dropna())),
        lineage_metadata={
            "lineage_type": "derived_shkp_historical_annual_report_index",
            "document_rows": int(len(frame)),
            "project_table_parse_policy": "availability_is_separate_from_layout_specific_project_extraction",
        },
    )
    return frame


def fetch_shkp_pipeline_disclosures(
    *,
    session: requests.Session | None = None,
    timeout: float = 60,
    empty_body_retries: int = 2,
    empty_body_retry_delay: float = 0.25,
) -> pd.DataFrame:
    """Capture project-level evidence phrases from official SHKP disclosures.

    The output is an evidence catalogue, not a legal project/ownership table:
    project labels are curated search anchors and the surrounding source text
    is retained for review.  A missing phrase is emitted as ``not_found`` so a
    changed disclosure cannot silently become a zero or a deletion.  Empty
    bodies are tracked separately as ``source_empty``: an upstream WAF,
    transient response, or JavaScript-only page must not be represented as
    evidence that a project is absent.  A small bounded retry is used only for
    empty bodies, and every attempt is retained as a raw snapshot.
    """
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "text/html, */*"})
    fetched_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    for disclosure in SHKP_PIPELINE_DISCLOSURES:
        url = str(disclosure["url"])
        max_attempts = max(1, int(empty_body_retries) + 1)
        response = None
        raw_content: bytes = b""
        response_text = ""
        attempt = 0
        attempt_paths: list[str] = []
        while attempt < max_attempts:
            attempt += 1
            response = client.get(url, timeout=timeout)
            response.raise_for_status()
            candidate_content = getattr(response, "content", b"")
            candidate_text = getattr(response, "text", "") or ""
            if isinstance(candidate_content, str):
                candidate_content = candidate_content.encode("utf-8")
            elif candidate_content is None:
                candidate_content = b""
            raw_content = bytes(candidate_content)
            response_text = str(candidate_text)
            raw_path = save_raw_snapshot(
                f"{disclosure['disclosure_id']}_pipeline_page_attempt_{attempt}",
                raw_content,
                file_ext="html",
                source_url=url,
            )
            attempt_paths.append(str(raw_path))
            has_body = bool(raw_content.strip()) or bool(response_text.strip())
            if has_body or attempt >= max_attempts:
                break
            if empty_body_retry_delay > 0:
                time.sleep(float(empty_body_retry_delay))
        if response is None:  # pragma: no cover - defensive; the loop always runs
            raise SHKPSourceUnavailable(f"No response received for {url}")
        raw_snapshots.extend(attempt_paths)
        source_urls.append(url)
        response_status = getattr(response, "status_code", None)
        response_content_bytes = len(raw_content)
        body_is_empty = not raw_content.strip() and not response_text.strip()
        fetch_status = "empty_body_after_retries" if body_is_empty else "ok"
        soup = BeautifulSoup(response_text, "html.parser")
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
        for project_label, status, geography, search_phrase in disclosure["items"]:
            position = text.lower().find(search_phrase.lower()) if text else -1
            if body_is_empty:
                context = (
                    "Official disclosure endpoint returned an empty body after "
                    f"{attempt} fetch attempt(s); this is a source/fetch gap, "
                    "not evidence that the project is absent."
                )
                evidence_status = "source_empty"
            elif position >= 0:
                sentence_end = text.find(".", position)
                if sentence_end < 0:
                    sentence_end = min(len(text), position + len(search_phrase) + 500)
                context = text[max(0, position - 180) : sentence_end + 1]
                evidence_status = "found"
            else:
                context = ""
                evidence_status = "not_found"
            records.append(
                {
                    "disclosure_id": disclosure["disclosure_id"],
                    "disclosure_type": disclosure["disclosure_type"],
                    "project_label": project_label,
                    "status": status,
                    "geography": geography,
                    "publication_date": disclosure.get("publication_date"),
                    "evidence_status": evidence_status,
                    "evidence_context": context,
                    "http_status": response_status,
                    "response_content_bytes": response_content_bytes,
                    "fetch_status": fetch_status,
                    "fetch_attempts": attempt,
                    "source_url": url,
                    "fetched_at": fetched_at,
                }
            )
    frame = pd.DataFrame(records, columns=PIPELINE_DISCLOSURE_COLUMNS)
    frame.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        lineage_metadata={
            "lineage_type": "official_disclosure_evidence_catalog",
            "disclosure_count": len(SHKP_PIPELINE_DISCLOSURES),
            "not_a_legal_ownership_registry": True,
        },
    )
    return frame


def fetch_shkp_project_site_vendor_facts(
    property_catalog: pd.DataFrame,
    *,
    project_names: Iterable[str] | None = None,
    session: requests.Session | None = None,
    timeout: float = 45,
    run_id: str | None = None,
) -> pd.DataFrame:
    """Fetch vendor/holding/material-date facts from official project sites.

    SHKP's directory links to first-party project sites whose statutory
    purchaser notices often expose the vendor and holding companies.  This
    function keeps those facts at site-evidence grain; it does not convert a
    holding-company name into a numeric listed-parent ownership percentage.
    Next.js sites may embed the notice in escaped server-component data, so the
    parser checks both rendered text and escaped ``label/value`` pairs.
    """
    if property_catalog.empty:
        return pd.DataFrame(columns=SHKP_PROJECT_SITE_VENDOR_FACT_COLUMNS)
    requested = {
        _normalized_name(value)
        for value in (project_names or [])
        if _normalized_name(value)
    }
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "text/html, */*"})
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    seen: set[str] = set()

    def _value_from_next_data(raw_html: str, label: str) -> str | None:
        pattern = re.compile(
            rf'\\"label\\":\\"{re.escape(label)}\\",\\"value\\":\\"(.*?)\\"',
            re.DOTALL,
        )
        match = pattern.search(raw_html)
        if not match:
            return None
        encoded = match.group(1).replace('\\u003c', '<').replace('\\u003e', '>').replace('\\u0026', '&')
        encoded = encoded.replace('\\"', '"')
        return BeautifulSoup(encoded, "html.parser").get_text(" ", strip=True)

    for property_row in property_catalog.to_dict("records"):
        if property_row.get("asset_type") != "residential_for_sale":
            continue
        marketing_name = str(property_row.get("marketing_name") or "").strip()
        if requested and _normalized_name(marketing_name) not in requested:
            continue
        url = SHKP_PROJECT_SITE_URL_OVERRIDES.get(
            _normalized_name(marketing_name),
            str(property_row.get("external_project_url") or "").strip(),
        )
        if not url or url in seen:
            continue
        seen.add(url)
        base_record = {
            "marketing_name": marketing_name or None,
            "source_record_id": property_row.get("source_record_id"),
            "external_project_url": url,
            "source_url": url,
            "site_evidence_status": "error",
            "development_name": None,
            "development_address": None,
            "district": property_row.get("district"),
            "vendor_name": None,
            "holding_companies": None,
            "estimated_material_date": None,
            "evidence_context": None,
            "fetched_at": fetched_at,
        }
        try:
            response = client.get(url, timeout=timeout)
            response.raise_for_status()
            raw_path = save_raw_snapshot(
                "shkp_project_site_vendor_page",
                response.content,
                file_ext="html",
                source_url=url,
                run_id=run_id,
            )
            raw_snapshots.append(str(raw_path))
            source_urls.append(url)
            text = re.sub(r"\s+", " ", BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)).strip()
            # First-hand-sales sites are not consistent about the separator
            # used between statutory notice fields. Several current SHKP
            # phase sites (including Cullinan Harbour Phase 2B) publish a
            # full-width vertical bar. Normalize it before extracting the
            # Vendor/Holding Companies pair; otherwise a present legal notice
            # is incorrectly recorded as ``no_vendor_fact``.
            notice_text = text.replace("｜", "|").replace("¦", "|")
            # Some pages render a vertical separator as the capital letter
            # ``I`` after HTML text extraction (e.g. ``Not applicable I
            # Holding companies ...``). Normalize it only before another
            # statutory field label, so ordinary prose containing ``I`` is
            # not rewritten.
            notice_text = re.sub(
                r"\s+I\s+(?=(?:Holding|One of the holding|Authorized|The firm|Building|"
                r"Any other|This advertisement|The estimated material date))",
                " | ",
                notice_text,
            )
            # Most notices use ``Vendor: ... | Holding Companies: ...``. A
            # few (notably YOHO WEST) use multiple statutory fields such as
            # ``Holding company of the Vendor (Owner): Not applicable`` and
            # ``Holding companies of the Vendor (Person so engaged): ...``.
            # Parse the pipe-delimited fields first so the latter is not
            # mistaken for a missing vendor fact; retain the old regex/Next.js
            # fallbacks for pages whose HTML omits separators.
            notice_fields = [part.strip() for part in notice_text.split("|") if part.strip()]
            vendor_values = []
            holding_values = []
            for field in notice_fields:
                vendor_field = None
                # ``Holding company of the Vendor`` contains the word
                # ``Vendor`` but is not itself the vendor field.
                if not re.match(r"(?:Holding|One of the holding)\b", field, flags=re.IGNORECASE):
                    vendor_field = re.search(
                        r"\bVendor(?:\s*\([^|:]*\))?\s*:\s*(?P<value>.*)$",
                        field,
                        flags=re.IGNORECASE,
                    )
                if vendor_field:
                    vendor_values.append(vendor_field.group("value").strip())
                    continue
                holding_field = re.search(
                    r"(?:Holding\s+compan(?:y|ies)|One of the holding companies)[^:]*:\s*(?P<value>.*)$",
                    field,
                    flags=re.IGNORECASE,
                )
                if holding_field:
                    value = holding_field.group("value").strip()
                    if value and value.casefold() not in {"not applicable", "n/a", "na"}:
                        holding_values.append(value)
            direct_vendor_match = re.search(
                r"\bVendor(?:\s*\([^|:]*\))?\s*:\s*(?P<value>.*?)(?=\s*(?:\||"
                r"Holding\s+compan(?:y|ies)|One of the holding companies|Authorized Person|$))",
                notice_text,
                flags=re.IGNORECASE,
            )
            vendor = (
                direct_vendor_match.group("value").strip()
                if direct_vendor_match
                else (vendor_values[0] if vendor_values else _value_from_next_data(response.text, "Vendor"))
            )
            if vendor:
                vendor = re.sub(r"\s*\(Note:.*$", "", str(vendor), flags=re.IGNORECASE).strip()
            holding = " | ".join(dict.fromkeys(holding_values)) if holding_values else (
                _value_from_next_data(response.text, "Holding companies of the Vendor")
                or _value_from_next_data(response.text, "Holding Companies of the vendor")
            )
            vendor_match = re.search(
                r"\bVendor(?:\s*\([^|:]*\))?\s*:\s*(?P<vendor>.*?)\s*\|\s*"
                r"(?:Holding Companies(?: of the vendor)?|One of the holding companies[^:]*?)\s*:\s*"
                r"(?P<holding>.*?)(?=\s+(?:Authorized Person|The firm or corporation|"
                r"Building contractor|The firms of solicitors|Authorized institution|"
                r"Any other person|This advertisement|Phase\s+\d+\s+Name|Name of the Phase|"
                r"District|The website|Last Update)|\s*\||$)",
                notice_text,
                flags=re.IGNORECASE,
            )
            if not vendor and vendor_match:
                vendor = vendor_match.group("vendor").strip()
            if not holding and vendor_match:
                holding = vendor_match.group("holding").strip()
            material_match = re.search(
                r"estimated material date[^:]*:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})",
                text,
                flags=re.IGNORECASE,
            )
            if not material_match:
                material_match = re.search(
                    r"material date[^0-9]{0,120}(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})",
                    response.text,
                    flags=re.IGNORECASE,
                )
            if not material_match:
                decoded_html = (
                    response.text.replace('\\u003c', '<')
                    .replace('\\u003e', '>')
                    .replace('\\u0026', '&')
                    .replace('\\"', '"')
                )
                material_text = re.sub(
                    r"\s+",
                    " ",
                    BeautifulSoup(decoded_html, "html.parser").get_text(" ", strip=True),
                )
                material_match = re.search(
                    r"(?:material date|completion)[^:]*:\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})",
                    material_text,
                    flags=re.IGNORECASE,
                )
            base_record.update(
                {
                    "site_evidence_status": "found" if vendor or holding else "no_vendor_fact",
                    "development_name": marketing_name or None,
                    "vendor_name": vendor,
                    "holding_companies": holding,
                    "estimated_material_date": material_match.group(1) if material_match else None,
                    "evidence_context": (
                        " | ".join(value for value in (vendor, holding) if value)
                        or (vendor_match.group(0) if vendor_match else text[-3000:])
                    )[:3000],
                }
            )
        except (requests.RequestException, ValueError) as exc:
            base_record["site_evidence_status"] = "error"
            base_record["evidence_context"] = str(exc)
        rows.append(base_record)

    frame = pd.DataFrame(rows, columns=SHKP_PROJECT_SITE_VENDOR_FACT_COLUMNS)
    frame.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        lineage_metadata={
            "lineage_type": "official_shkp_project_site_vendor_evidence",
            "project_count": int(len(frame)),
            "found_count": int(frame["site_evidence_status"].eq("found").sum()) if not frame.empty else 0,
            "ownership_inference": False,
        },
    )
    return frame


def build_shkp_project_site_vendor_crosswalk(
    site_vendor_facts: pd.DataFrame,
    shkp_srpe_crosswalk: pd.DataFrame,
) -> pd.DataFrame:
    """Attach first-party vendor facts to the existing SHKP↔SRPE candidates.

    A project website can state a vendor and holding companies without stating
    the listed parent's percentage.  The crosswalk therefore carries those
    facts to every existing phase candidate but keeps ``ownership_status`` at
    ``not_verified`` and preserves a null-ID row when no SRPE candidate exists.
    """
    if site_vendor_facts.empty:
        return pd.DataFrame(columns=SHKP_PROJECT_SITE_VENDOR_CROSSWALK_COLUMNS)
    candidate_map: dict[str, list[dict[str, Any]]] = {}
    if not shkp_srpe_crosswalk.empty and "marketing_name" in shkp_srpe_crosswalk.columns:
        for record in shkp_srpe_crosswalk.to_dict("records"):
            candidate_map.setdefault(str(record.get("marketing_name") or ""), []).append(record)
    rows: list[dict[str, Any]] = []
    for fact in site_vendor_facts.to_dict("records"):
        marketing_name = str(fact.get("marketing_name") or "")
        candidates = candidate_map.get(marketing_name, [])
        candidate_count = len(candidates)
        if not candidates:
            candidates = [{}]
        for candidate in candidates:
            identifier = candidate.get("srpe_development_id")
            rows.append(
                {
                    "marketing_name": marketing_name or None,
                    "source_record_id": fact.get("source_record_id"),
                    "vendor_name": fact.get("vendor_name"),
                    "holding_companies": fact.get("holding_companies"),
                    "estimated_material_date": fact.get("estimated_material_date"),
                    "site_evidence_status": fact.get("site_evidence_status"),
                    "site_source_url": fact.get("source_url"),
                    "srpe_development_id": identifier,
                    "srpe_phase_name": candidate.get("srpe_phase_name"),
                    "srpe_address_en": candidate.get("srpe_address_en"),
                    "match_method": candidate.get("match_method") or "site_name_only",
                    "match_status": candidate.get("match_status") or "unmatched",
                    "candidate_count": candidate_count,
                    "ownership_status": "not_verified",
                    "matched_at": fact.get("fetched_at") or datetime.now(timezone.utc).isoformat(),
                }
            )
    return pd.DataFrame(rows, columns=SHKP_PROJECT_SITE_VENDOR_CROSSWALK_COLUMNS)
