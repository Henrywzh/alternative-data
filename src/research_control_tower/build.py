"""Build the Research Control Tower V1 local marts.

This module deliberately contains no collectors and no network-capable code.
Every input other than the two required CSV bundles is an explicit
``LocalInput`` descriptor.  The builder validates all required inputs before
creating a same-filesystem staging directory and commits only the named
artifacts, with ``build_manifest.json`` written last.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Iterable, Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .events import (
    EVENT_REQUIRED_COLUMNS,
    EventBundle,
    is_catalyst_eligible as task2_is_catalyst_eligible,
    load_event_bundle,
    validate_event_bundle,
)
from .macro import MACRO_EVENT_COLUMNS, MACRO_OBSERVATION_COLUMNS
from .registries import REGISTRY_FILES, load_registry_bundle, validate_registry_bundle


SCHEMA_VERSION = "control_tower_marts_v1"
NETWORK_POLICY = "forbidden"
CURRENT_POINTER_NAME = "CURRENT"
GENERATIONS_DIR_NAME = "generations"

REGISTRY_OUTPUT_COLUMNS: dict[str, list[str]] = {
    "entities": [
        "entity_id",
        "legal_name",
        "display_name",
        "country",
        "sector",
        "industry",
        "active_status",
        "active_from",
        "active_to",
        "registry_version",
        "source_or_research_note",
        "entity_type",
    ],
    "listings": [
        "listing_id",
        "entity_id",
        "exchange",
        "native_ticker",
        "canonical_ticker",
        "financial_data_security_id",
        "financial_data_issuer_group_id",
        "mapping_status",
        "mapping_verified_at",
        "mapping_source_url",
        "collection_eligible",
        "listing_role",
        "vendor_tickers",
        "currency",
        "primary_listing",
        "active_from",
        "active_to",
        "listing_status",
        "registry_version",
        "source_url",
        "source_or_research_note",
    ],
    "baskets": [
        "basket_id",
        "display_name",
        "purpose",
        "active_from",
        "active_to",
        "registry_version",
        "source_or_research_note",
    ],
    "basket_memberships": [
        "entity_id",
        "basket_id",
        "membership_tier",
        "primary_layer",
        "secondary_layers",
        "active_from",
        "active_to",
        "membership_reason",
        "source_or_research_note",
        "registry_version",
    ],
    "indices": [
        "index_id",
        "region",
        "display_name",
        "official_code",
        "official_code_namespace",
        "official_code_provider",
        "provider_symbol",
        "provider_symbol_namespace",
        "provider_symbol_provider",
        "provider",
        "currency",
        "active_from",
        "active_to",
        "registry_version",
        "source_url",
        "source_or_research_note",
    ],
}

EVENT_OUTPUT_COLUMNS = [
    "event_id",
    "event_key",
    "observation_version",
    "scope",
    "event_type",
    "title",
    "description",
    "status",
    "certainty_class",
    "confidence",
    "date_precision",
    "starts_at",
    "ends_at",
    "source_timezone",
    "source_id",
    "source_url",
    "source_published_at",
    "first_observed_at",
    "last_verified_at",
    "review_by",
    "supersedes_event_id",
    "evidence_class",
    "evidence_ref",
    "reference_period",
    "previous_value",
    "previous_vintage",
    "market_consensus",
    "consensus_source",
    "own_nowcast",
    "actual_value",
    "actual_unit",
    "revised_value",
    "surprise_value",
    "surprise_unit",
    "scenario_notes",
    "expected_metrics",
    "thesis_implications",
    "registry_version",
]
EVENT_LINK_COLUMNS = [
    "event_id",
    "target_type",
    "target_id",
    "link_role",
    "automated",
    "active_from",
    "active_to",
    "link_note",
    "registry_version",
]
EVENT_WATCH_QUESTION_COLUMNS = [
    "event_id",
    "question_id",
    "question",
    "question_type",
    "priority",
    "registry_version",
]

MACRO_OUTPUT_COLUMNS = list(MACRO_OBSERVATION_COLUMNS)

TASK3_SNAPSHOT_COLUMNS = [
    "snapshot_id",
    "provider",
    "entity_id",
    "listing_id",
    "financial_data_security_id",
    "canonical_ticker",
    "metric",
    "fiscal_period",
    "fiscal_year",
    "estimate_period_end",
    "horizon",
    "snapshot_at",
    "value",
    "statistic",
    "low_value",
    "high_value",
    "analyst_count",
    "provider_contributor_count",
    "currency",
    "unit",
    "accounting_basis",
    "provider_asof",
    "retrieved_at_utc",
    "source_url",
    "raw_hash",
    "pit_class",
    "source_run_id",
    "calculation_origin",
    "coverage_reason",
]
TASK3_REVISION_COLUMNS = [
    "revision_id",
    "snapshot_id",
    "provider",
    "prior_provider",
    "entity_id",
    "listing_id",
    "financial_data_security_id",
    "canonical_ticker",
    "metric",
    "fiscal_period",
    "fiscal_year",
    "estimate_period_end",
    "horizon",
    "statistic",
    "current_snapshot_at",
    "current_value",
    "current_analyst_count",
    "current_dispersion",
    "lookback_days",
    "cutoff_at",
    "prior_snapshot_id",
    "prior_snapshot_at",
    "prior_value",
    "prior_provider_asof",
    "provider_asof",
    "retrieved_at_utc",
    "source_url",
    "pit_class",
    "source_run_id",
    "prior_analyst_count",
    "revision_value",
    "revision_pct",
    "analyst_count_change",
    "dispersion",
    "alignment_status",
]
TASK3_HEALTH_COLUMNS = [
    "provider",
    "status",
    "reason",
    "row_count",
    "mapped_row_count",
    "latest_snapshot_at",
    "as_of",
    "network_calls",
    "source_license_class",
    "entitlement_status",
    "entitlement_evidence",
    "entitlement_ref",
]

_TASK3_UTC_TIMESTAMP = pa.timestamp("us", tz="UTC")
TASK3_SNAPSHOT_ARROW_SCHEMA = pa.schema(
    [
        ("snapshot_id", pa.string()),
        ("provider", pa.string()),
        ("entity_id", pa.string()),
        ("listing_id", pa.string()),
        ("financial_data_security_id", pa.string()),
        ("canonical_ticker", pa.string()),
        ("metric", pa.string()),
        ("fiscal_period", pa.string()),
        ("fiscal_year", pa.int64()),
        ("estimate_period_end", pa.date32()),
        ("horizon", pa.string()),
        ("snapshot_at", _TASK3_UTC_TIMESTAMP),
        ("value", pa.float64()),
        ("statistic", pa.string()),
        ("low_value", pa.float64()),
        ("high_value", pa.float64()),
        ("analyst_count", pa.int64()),
        ("provider_contributor_count", pa.int64()),
        ("currency", pa.string()),
        ("unit", pa.string()),
        ("accounting_basis", pa.string()),
        ("provider_asof", _TASK3_UTC_TIMESTAMP),
        ("retrieved_at_utc", _TASK3_UTC_TIMESTAMP),
        ("source_url", pa.string()),
        ("raw_hash", pa.string()),
        ("pit_class", pa.string()),
        ("source_run_id", pa.string()),
        ("calculation_origin", pa.string()),
        ("coverage_reason", pa.string()),
    ]
)
TASK3_REVISION_ARROW_SCHEMA = pa.schema(
    [
        ("revision_id", pa.string()),
        ("snapshot_id", pa.string()),
        ("provider", pa.string()),
        ("prior_provider", pa.string()),
        ("entity_id", pa.string()),
        ("listing_id", pa.string()),
        ("financial_data_security_id", pa.string()),
        ("canonical_ticker", pa.string()),
        ("metric", pa.string()),
        ("fiscal_period", pa.string()),
        ("fiscal_year", pa.int64()),
        ("estimate_period_end", pa.date32()),
        ("horizon", pa.string()),
        ("statistic", pa.string()),
        ("current_snapshot_at", _TASK3_UTC_TIMESTAMP),
        ("current_value", pa.float64()),
        ("current_analyst_count", pa.int64()),
        ("current_dispersion", pa.float64()),
        ("lookback_days", pa.int64()),
        ("cutoff_at", _TASK3_UTC_TIMESTAMP),
        ("prior_snapshot_id", pa.string()),
        ("prior_snapshot_at", _TASK3_UTC_TIMESTAMP),
        ("prior_value", pa.float64()),
        ("prior_provider_asof", _TASK3_UTC_TIMESTAMP),
        ("provider_asof", _TASK3_UTC_TIMESTAMP),
        ("retrieved_at_utc", _TASK3_UTC_TIMESTAMP),
        ("source_url", pa.string()),
        ("pit_class", pa.string()),
        ("source_run_id", pa.string()),
        ("prior_analyst_count", pa.int64()),
        ("revision_value", pa.float64()),
        ("revision_pct", pa.float64()),
        ("analyst_count_change", pa.int64()),
        ("dispersion", pa.float64()),
        ("alignment_status", pa.string()),
    ]
)
TASK3_HEALTH_ARROW_SCHEMA = pa.schema(
    [
        ("provider", pa.string()),
        ("status", pa.string()),
        ("reason", pa.string()),
        ("row_count", pa.int64()),
        ("mapped_row_count", pa.int64()),
        ("latest_snapshot_at", _TASK3_UTC_TIMESTAMP),
        ("as_of", _TASK3_UTC_TIMESTAMP),
        ("network_calls", pa.int64()),
        ("source_license_class", pa.string()),
        ("entitlement_status", pa.string()),
        ("entitlement_evidence", pa.string()),
        ("entitlement_ref", pa.string()),
    ]
)

QUOTE_SNAPSHOT_COLUMNS = [
    "quote_id",
    "listing_id",
    "canonical_ticker",
    "provider_symbol",
    "quote_timestamp",
    "retrieved_at_utc",
    "last_price",
    "bid",
    "ask",
    "day_change_pct",
    "volume",
    "currency",
    "market_status",
    "latency_class",
    "source_id",
    "source_url",
    "pit_class",
    "source_license_class",
    "registry_version",
]
QUOTE_SNAPSHOT_ARROW_SCHEMA = pa.schema(
    [
        ("quote_id", pa.string()),
        ("listing_id", pa.string()),
        ("canonical_ticker", pa.string()),
        ("provider_symbol", pa.string()),
        ("quote_timestamp", _TASK3_UTC_TIMESTAMP),
        ("retrieved_at_utc", _TASK3_UTC_TIMESTAMP),
        ("last_price", pa.float64()),
        ("bid", pa.float64()),
        ("ask", pa.float64()),
        ("day_change_pct", pa.float64()),
        ("volume", pa.float64()),
        ("currency", pa.string()),
        ("market_status", pa.string()),
        ("latency_class", pa.string()),
        ("source_id", pa.string()),
        ("source_url", pa.string()),
        ("pit_class", pa.string()),
        ("source_license_class", pa.string()),
        ("registry_version", pa.string()),
    ]
)

NEWS_FILINGS_COLUMNS = [
    "document_id",
    "document_type",
    "source_id",
    "headline",
    "publisher",
    "published_at",
    "first_observed_at",
    "source_url",
    "language",
    "related_entity_ids",
    "related_listing_ids",
    "related_basket_ids",
    "event_class",
    "importance",
    "source_quality",
    "pit_class",
    "source_license_class",
    "content_hash_if_permitted",
    "derived_summary_if_permitted",
]

# Batch 2/3 official-source marts.  These carry filing/announcement metadata
# and versioned earnings actuals only; document bodies are never admitted.
# Collector modules (official_filings.py, earnings_actuals.py) write the same
# standardized columns into local inputs that this offline builder consumes.
OFFICIAL_FILINGS_COLUMNS = [
    "document_id",
    "document_type",
    "event_class",
    "source_id",
    "headline",
    "publisher",
    "published_at",
    "accepted_at",
    "scheduled_date",
    "retrieved_at_utc",
    "source_url",
    "language",
    "entity_id",
    "listing_id",
    "canonical_ticker",
    "reporting_period_label",
    "reporting_period_start",
    "reporting_period_end",
    "date_precision",
    "source_timezone",
    "event_status",
    "source_quality",
    "pit_class",
    "source_license_class",
    "content_hash_if_permitted",
    "source_note",
    "registry_version",
]

EARNINGS_CALENDAR_COLUMNS = [
    "calendar_id",
    "entity_id",
    "listing_id",
    "canonical_ticker",
    "period_label",
    "period_start",
    "period_end",
    "event_type",
    "event_date",
    "date_precision",
    "date_basis",
    "source_timezone",
    "status",
    "source_id",
    "source_url",
    "headline",
    "published_at",
    "retrieved_at_utc",
    "source_quality",
    "pit_class",
    "source_license_class",
    "source_note",
    "registry_version",
]

EARNINGS_ACTUALS_COLUMNS = [
    "actual_id",
    "version",
    "supersedes_actual_id",
    "entity_id",
    "listing_id",
    "canonical_ticker",
    "metric",
    "period_label",
    "period_start",
    "period_end",
    "reported_value",
    "normalized_value",
    "normalization_note",
    "currency",
    "unit",
    "accounting_basis",
    "filing_at",
    "published_at",
    "retrieved_at_utc",
    "source_url",
    "accession_no",
    "form",
    "xbrl_frame",
    "revision_reason",
    "is_restatement",
    "source_id",
    "source_quality",
    "pit_class",
    "source_license_class",
    "source_note",
    "registry_version",
]

# Per-source collection-state sidecar written by the Batch 2/3 collectors.
# It keeps the plan's coverage semantics (available/partial/no_records/
# not_applicable/unavailable) explicit instead of collapsing an empty query
# response into a failed provider.
SOURCE_STATE_COLUMNS = [
    "source_id",
    "source_kind",
    "status",
    "detail",
    "row_count",
    "first_observation_at",
    "latest_observation_at",
    "source_latest_at",
    "retrieved_at_utc",
    "source_url",
    "pit_class",
    "source_license_class",
    "cadence",
]

SOURCE_HEALTH_COLUMNS = [
    "source_id",
    "input_path",
    "source_kind",
    "status",
    "required",
    "row_count",
    "first_observation_at",
    "latest_observation_at",
    "source_latest_at",
    "retrieved_at_utc",
    "cadence",
    "source_url",
    "pit_class",
    "source_license_class",
    "entitlement_status",
    "entitlement_evidence",
    "entitlement_ref",
    "input_sha256",
    "schema_version",
    "missing_geographies",
    "detail",
]

ARTIFACT_NAMES = (
    "entities.parquet",
    "listings.parquet",
    "baskets.parquet",
    "basket_memberships.parquet",
    "indices.parquet",
    "events.parquet",
    "event_entity_links.parquet",
    "event_basket_links.parquet",
    "event_watch_questions.parquet",
    "macro_observations.parquet",
    "consensus_snapshots.parquet",
    "consensus_revisions.parquet",
    "quote_snapshots.parquet",
    "news_filings.parquet",
    "official_filings.parquet",
    "earnings_calendar.parquet",
    "earnings_actuals.parquet",
    "source_health.parquet",
    "build_manifest.json",
)

OPTIONAL_ARTIFACT_NAMES = frozenset({
    "consensus_snapshots.parquet",
    "consensus_revisions.parquet",
    "quote_snapshots.parquet",
    "news_filings.parquet",
    "official_filings.parquet",
    "earnings_calendar.parquet",
    "earnings_actuals.parquet",
})

FRED_OBSERVATIONS_SCHEMA_ID = "fred_observations_v1"
FRED_META_SCHEMA_ID = "fred_series_meta_v1"
OFR_OBSERVATIONS_SCHEMA_ID = "ofr_timeseries_v1"
OFR_META_SCHEMA_ID = "ofr_mnemonics_v1"
TAIWAN_REVENUE_SCHEMA_ID = "tw_monthly_revenue_v1"
ECB_FX_SCHEMA_ID = "ecb_fx_rates_v1"
MACRO_OBSERVATIONS_SCHEMA_ID = "macro_observations_v1"
MACRO_COLLECTOR_SCHEMA_ID = "macro_collector_v1"
MACRO_EVENTS_SCHEMA_ID = "macro_events_v1"
MACRO_SOURCE_HEALTH_SCHEMA_ID = "macro_source_health_v1"
NEWS_SCHEMA_ID = "ai_news_blog_posts_v1"
FILING_SCHEMA_ID = "sec_edgar_filings_v1"
QUOTE_SNAPSHOT_SCHEMA_ID = "quote_snapshots_v1"
OFFICIAL_FILINGS_SCHEMA_ID = "official_filings_v1"
EARNINGS_ACTUALS_SCHEMA_ID = "earnings_actuals_v1"
SOURCE_STATE_SCHEMA_ID = "source_state_v1"

_SCHEMA_ALIASES = {
    FRED_OBSERVATIONS_SCHEMA_ID: FRED_OBSERVATIONS_SCHEMA_ID,
    "fred_observations": FRED_OBSERVATIONS_SCHEMA_ID,
    FRED_META_SCHEMA_ID: FRED_META_SCHEMA_ID,
    "fred_series_meta": FRED_META_SCHEMA_ID,
    OFR_OBSERVATIONS_SCHEMA_ID: OFR_OBSERVATIONS_SCHEMA_ID,
    "ofr_observations": OFR_OBSERVATIONS_SCHEMA_ID,
    OFR_META_SCHEMA_ID: OFR_META_SCHEMA_ID,
    "ofr_mnemonics": OFR_META_SCHEMA_ID,
    TAIWAN_REVENUE_SCHEMA_ID: TAIWAN_REVENUE_SCHEMA_ID,
    "tw_monthly_revenue": TAIWAN_REVENUE_SCHEMA_ID,
    ECB_FX_SCHEMA_ID: ECB_FX_SCHEMA_ID,
    "airline_fx_rates": ECB_FX_SCHEMA_ID,
    NEWS_SCHEMA_ID: NEWS_SCHEMA_ID,
    "official_ai_rss_v1": NEWS_SCHEMA_ID,
    "ai_news_blog_posts": NEWS_SCHEMA_ID,
    FILING_SCHEMA_ID: FILING_SCHEMA_ID,
    "sec_filings_v1": FILING_SCHEMA_ID,
    "edgar_filings": FILING_SCHEMA_ID,
    QUOTE_SNAPSHOT_SCHEMA_ID: QUOTE_SNAPSHOT_SCHEMA_ID,
    "quote_snapshots": QUOTE_SNAPSHOT_SCHEMA_ID,
    OFFICIAL_FILINGS_SCHEMA_ID: OFFICIAL_FILINGS_SCHEMA_ID,
    "official_filings": OFFICIAL_FILINGS_SCHEMA_ID,
    EARNINGS_ACTUALS_SCHEMA_ID: EARNINGS_ACTUALS_SCHEMA_ID,
    "earnings_actuals": EARNINGS_ACTUALS_SCHEMA_ID,
    SOURCE_STATE_SCHEMA_ID: SOURCE_STATE_SCHEMA_ID,
    "source_state": SOURCE_STATE_SCHEMA_ID,
    MACRO_OBSERVATIONS_SCHEMA_ID: MACRO_OBSERVATIONS_SCHEMA_ID,
    MACRO_COLLECTOR_SCHEMA_ID: MACRO_COLLECTOR_SCHEMA_ID,
    "macro_observations": MACRO_OBSERVATIONS_SCHEMA_ID,
    MACRO_EVENTS_SCHEMA_ID: MACRO_EVENTS_SCHEMA_ID,
    "macro_events": MACRO_EVENTS_SCHEMA_ID,
    MACRO_SOURCE_HEALTH_SCHEMA_ID: MACRO_SOURCE_HEALTH_SCHEMA_ID,
    "macro_source_health": MACRO_SOURCE_HEALTH_SCHEMA_ID,
}

_EXPECTED_OPTIONAL_SOURCES = (
    ("fred_observations", "macro", FRED_OBSERVATIONS_SCHEMA_ID, "US"),
    ("fred_series_meta", "macro", FRED_META_SCHEMA_ID, "US"),
    ("ofr_timeseries", "macro", OFR_OBSERVATIONS_SCHEMA_ID, "US"),
    ("ofr_mnemonics", "macro", OFR_META_SCHEMA_ID, "US"),
    ("tw_monthly_revenue", "macro", TAIWAN_REVENUE_SCHEMA_ID, "TW"),
    ("ecb_fx_rates", "macro", ECB_FX_SCHEMA_ID, "Europe"),
    ("consensus_export", "consensus", "task3_consensus_export_v1", ""),
    ("quote_snapshots", "market", QUOTE_SNAPSHOT_SCHEMA_ID, ""),
    ("news_official_ai_rss", "news", NEWS_SCHEMA_ID, ""),
    ("filings_sec_edgar", "filing", FILING_SCHEMA_ID, "US"),
    ("official_filings", "official_filing", OFFICIAL_FILINGS_SCHEMA_ID, "CN,HK,US"),
    ("official_filings_state", "official_filing", SOURCE_STATE_SCHEMA_ID, ""),
    ("earnings_actuals", "earnings", EARNINGS_ACTUALS_SCHEMA_ID, "CN,HK,US"),
    ("earnings_actuals_state", "earnings", SOURCE_STATE_SCHEMA_ID, ""),
)

# These are explicit source-specific freshness windows for current-vintage
# snapshots.  They are health policy, not release-calendar claims.  A source
# row beyond as_of_utc fails closed; an older source is retained only as a
# degraded health record and contributes a typed empty adapter output.
SOURCE_FRESHNESS_THRESHOLDS = {
    FRED_OBSERVATIONS_SCHEMA_ID: pd.Timedelta(days=14),
    FRED_META_SCHEMA_ID: pd.Timedelta(days=90),
    OFR_OBSERVATIONS_SCHEMA_ID: pd.Timedelta(days=30),
    OFR_META_SCHEMA_ID: pd.Timedelta(days=90),
    TAIWAN_REVENUE_SCHEMA_ID: pd.Timedelta(days=62),
    ECB_FX_SCHEMA_ID: pd.Timedelta(days=7),
    NEWS_SCHEMA_ID: pd.Timedelta(days=45),
    FILING_SCHEMA_ID: pd.Timedelta(days=14),
    MACRO_OBSERVATIONS_SCHEMA_ID: pd.Timedelta(days=30),
    MACRO_COLLECTOR_SCHEMA_ID: pd.Timedelta(days=30),
    MACRO_EVENTS_SCHEMA_ID: pd.Timedelta(days=30),
    "task3_consensus_export_v1": pd.Timedelta(days=14),
    "task3_consensus_source_health_v1": pd.Timedelta(days=14),
    QUOTE_SNAPSHOT_SCHEMA_ID: pd.Timedelta(minutes=5),
    # The Batch 2/3 collectors are designed for weekly-to-monthly runs; the
    # windows below are health policy for the collected snapshot, not
    # publication claims.  A stale snapshot fails closed into a typed empty
    # artifact and a degraded health row.
    OFFICIAL_FILINGS_SCHEMA_ID: pd.Timedelta(days=45),
    EARNINGS_ACTUALS_SCHEMA_ID: pd.Timedelta(days=120),
    SOURCE_STATE_SCHEMA_ID: pd.Timedelta(days=45),
}

SOURCE_TIME_COLUMNS = {
    FRED_OBSERVATIONS_SCHEMA_ID: {
        "observed": ("date",),
        "freshness": ("date",),
        "retrieved": ("fetched_at",),
        "future": ("date", "fetched_at"),
    },
    FRED_META_SCHEMA_ID: {
        "observed": ("observation_start",),
        "freshness": ("last_updated",),
        "retrieved": ("fetched_at",),
        "future": ("observation_start", "last_updated", "fetched_at"),
    },
    OFR_OBSERVATIONS_SCHEMA_ID: {
        "observed": ("date",),
        "freshness": ("date",),
        "retrieved": ("fetched_at",),
        "future": ("date", "fetched_at"),
    },
    OFR_META_SCHEMA_ID: {
        "observed": ("start_date",),
        "freshness": ("last_update",),
        "retrieved": ("fetched_at",),
        "future": ("start_date", "last_update", "fetched_at"),
    },
    TAIWAN_REVENUE_SCHEMA_ID: {
        "observed": ("revenue_month",),
        "freshness": ("revenue_month",),
        "retrieved": ("scraped_at",),
        "future": ("revenue_month", "filing_date", "scraped_at"),
    },
    ECB_FX_SCHEMA_ID: {
        "observed": ("observation_date",),
        "freshness": ("observation_date",),
        "retrieved": ("retrieved_at",),
        "future": ("observation_date", "source_release_date", "retrieved_at"),
    },
    NEWS_SCHEMA_ID: {
        "observed": ("pub_date",),
        "freshness": ("pub_date",),
        "retrieved": ("first_seen_at", "scraped_at"),
        "future": ("pub_date", "first_seen_at", "last_seen_at", "scraped_at"),
    },
    FILING_SCHEMA_ID: {
        "observed": ("file_date",),
        "freshness": ("file_date",),
        "retrieved": ("fetched_at",),
        "future": ("file_date", "fetched_at"),
    },
    OFFICIAL_FILINGS_SCHEMA_ID: {
        "observed": ("published_at",),
        "freshness": ("published_at", "accepted_at"),
        "retrieved": ("retrieved_at_utc",),
        "future": ("published_at", "accepted_at", "retrieved_at_utc"),
    },
    EARNINGS_ACTUALS_SCHEMA_ID: {
        "observed": ("period_end",),
        "freshness": ("filing_at", "published_at"),
        "retrieved": ("retrieved_at_utc",),
        "future": ("filing_at", "published_at", "retrieved_at_utc"),
    },
    SOURCE_STATE_SCHEMA_ID: {
        "observed": ("first_observation_at",),
        "freshness": ("latest_observation_at", "source_latest_at"),
        "retrieved": ("retrieved_at_utc",),
        "future": ("latest_observation_at", "source_latest_at", "retrieved_at_utc"),
    },
    "task3_consensus_export_v1": {
        "observed": ("snapshot_at", "current_snapshot_at"),
        "freshness": ("snapshot_at", "current_snapshot_at", "provider_asof", "retrieved_at_utc"),
        "retrieved": ("retrieved_at_utc",),
        "future": (
            "snapshot_at",
            "current_snapshot_at",
            "cutoff_at",
            "prior_snapshot_at",
            "prior_provider_asof",
            "provider_asof",
            "retrieved_at_utc",
        ),
    },
    "task3_consensus_source_health_v1": {
        "observed": ("latest_snapshot_at",),
        "freshness": ("as_of",),
        "retrieved": ("as_of",),
        "future": ("latest_snapshot_at", "as_of"),
    },
    # Macro collector artifacts are current-vintage snapshots; freshness is the
    # collector run time (retrieved_at_utc / first_observed_at), so a stale
    # artifact file fails closed instead of silently feeding an old snapshot.
    MACRO_OBSERVATIONS_SCHEMA_ID: {
        "observed": ("observation_date",),
        "freshness": ("retrieved_at_utc",),
        "retrieved": ("retrieved_at_utc",),
        "future": ("observation_date", "retrieved_at_utc"),
    },
    MACRO_COLLECTOR_SCHEMA_ID: {
        "observed": ("observation_date",),
        "freshness": ("retrieved_at_utc",),
        "retrieved": ("retrieved_at_utc",),
        "future": ("observation_date", "retrieved_at_utc"),
    },
    MACRO_EVENTS_SCHEMA_ID: {
        "observed": ("starts_at",),
        "freshness": ("first_observed_at",),
        "retrieved": ("first_observed_at",),
        # starts_at is intentionally excluded from ``future``: scheduled
        # (upcoming) macro releases legitimately have future start times.
        "future": ("first_observed_at",),
    },
    QUOTE_SNAPSHOT_SCHEMA_ID: {
        "observed": ("quote_timestamp",),
        "freshness": ("quote_timestamp",),
        "retrieved": ("retrieved_at_utc",),
        "future": ("quote_timestamp", "retrieved_at_utc"),
    },
}

QUALITY_CLASSES = frozenset({"official", "official_metadata", "discovery", "entitled", "unknown"})

# Health statuses that mean "the source was queried and its result is usable"
# for artifact availability.  ``no_records`` is an honest empty query result
# (the plan's coverage semantics), ``partial`` covers only some listings, and
# ``not_applicable`` describes a private entity with no public disclosure.
# None of these mark a build degraded; ``unavailable``/``degraded`` do.
CONTRIBUTING_STATUSES = frozenset({"available", "partial", "no_records"})

# Artifact-level availability policy.  Strict by default (Batch 0-1): only an
# all-``available`` contributing set publishes an ``available`` artifact, so a
# quote source with no usable rows stays degraded.  The Batch 2/3 official-
# source marts relax this: an honest ``partial``/``no_records``/
# ``not_applicable`` source state from the collector sidecar is a successful
# query result per the plan's coverage semantics, not a degraded build.
STRICT_USABLE_STATUSES = frozenset({"available"})
B23_USABLE_STATUSES = CONTRIBUTING_STATUSES | {"not_applicable"}
_ARTIFACT_USABLE_STATUSES = {
    "official_filings.parquet": B23_USABLE_STATUSES,
    "earnings_calendar.parquet": B23_USABLE_STATUSES,
    "earnings_actuals.parquet": B23_USABLE_STATUSES,
}


class BuildError(ValueError):
    """Raised when a required build contract cannot be satisfied."""


@dataclass(frozen=True)
class LocalInput:
    """An explicit local file descriptor consumed by an optional adapter."""

    source_id: str
    path: Path
    format: Literal["parquet", "csv", "json", "jsonl"]
    required: bool = False
    source_url: str | None = None
    cadence: str | None = None
    pit_class: str = "snapshot_from_live_source"
    license_class: str = "public_metadata"
    expected_schema: str = ""
    status_path: Path | None = None
    source_priority: int = 100

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("LocalInput.source_id must not be blank")
        if self.format not in {"parquet", "csv", "json", "jsonl"}:
            raise ValueError(f"unsupported LocalInput format: {self.format!r}")
        if not self.expected_schema.strip():
            raise ValueError("LocalInput.expected_schema must not be blank")
        object.__setattr__(self, "path", Path(self.path))
        if self.status_path is not None:
            object.__setattr__(self, "status_path", Path(self.status_path))
        if not isinstance(self.source_priority, int) or isinstance(self.source_priority, bool) or self.source_priority < 0:
            raise ValueError("LocalInput.source_priority must be a non-negative integer")
        if self.expected_schema.strip().lower() in {QUOTE_SNAPSHOT_SCHEMA_ID, "quote_snapshots"}:
            if self.pit_class.strip().lower() in {"", "snapshot_from_live_source"}:
                object.__setattr__(self, "pit_class", "snapshot_from_delayed_source")
            if self.license_class.strip().lower() in {"", "public_metadata"}:
                object.__setattr__(self, "license_class", "personal_use_terms_unverified")


@dataclass(frozen=True)
class BuildConfig:
    """Path-explicit, deterministic configuration for one local build."""

    registry_root: Path
    event_root: Path
    output_dir: Path
    as_of_utc: pd.Timestamp
    build_id: str
    macro_inputs: tuple[LocalInput, ...] = ()
    news_inputs: tuple[LocalInput, ...] = ()
    filing_inputs: tuple[LocalInput, ...] = ()
    official_filing_inputs: tuple[LocalInput, ...] = ()
    earnings_inputs: tuple[LocalInput, ...] = ()
    quote_inputs: tuple[LocalInput, ...] = ()
    consensus_export_dir: Path | None = None
    schema_version: str = SCHEMA_VERSION
    allow_degraded_optional: bool = True
    overwrite_existing: bool = True
    network_policy: Literal["forbidden"] = NETWORK_POLICY

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_root", Path(self.registry_root))
        object.__setattr__(self, "event_root", Path(self.event_root))
        object.__setattr__(self, "output_dir", Path(self.output_dir))
        if self.consensus_export_dir is not None:
            object.__setattr__(self, "consensus_export_dir", Path(self.consensus_export_dir))
        as_of = pd.Timestamp(self.as_of_utc)
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of_utc must be timezone-aware")
        object.__setattr__(self, "as_of_utc", as_of.tz_convert("UTC"))
        if not self.build_id.strip():
            raise ValueError("build_id must not be blank")
        if self.network_policy != NETWORK_POLICY:
            raise ValueError("network_policy must be 'forbidden'")
        descriptors = (
            *self.macro_inputs,
            *self.news_inputs,
            *self.filing_inputs,
            *self.official_filing_inputs,
            *self.earnings_inputs,
            *self.quote_inputs,
        )
        source_ids = [descriptor.source_id for descriptor in descriptors]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("optional LocalInput source_id values must be unique")


@dataclass(frozen=True)
class BuildManifest:
    """In-memory representation of the committed build manifest."""

    schema_version: str
    build_id: str
    status: Literal["success", "degraded"]
    built_at_utc: str
    as_of_utc: str
    previous_build_at: str | None
    network_policy: str
    input_fingerprints: dict[str, str]
    artifacts: dict[str, dict[str, Any]]
    degraded_inputs: list[str] = field(default_factory=list)
    validation_errors: list[dict[str, Any]] = field(default_factory=list)
    source_health_summary: dict[str, int] = field(default_factory=dict)
    generation_id: str = ""
    current_pointer: str = CURRENT_POINTER_NAME

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "build_id": self.build_id,
            "status": self.status,
            "built_at_utc": self.built_at_utc,
            "as_of_utc": self.as_of_utc,
            "previous_build_at": self.previous_build_at,
            "network_policy": self.network_policy,
            "input_fingerprints": dict(sorted(self.input_fingerprints.items())),
            "artifacts": {key: self.artifacts[key] for key in sorted(self.artifacts)},
            "degraded_inputs": sorted(self.degraded_inputs),
            "validation_errors": list(self.validation_errors),
            "source_health_summary": dict(sorted(self.source_health_summary.items())),
            "generation_id": self.generation_id,
            "current_pointer": self.current_pointer,
        }


@dataclass
class _SourceState:
    source_id: str
    source_kind: str
    path: Path | None
    schema_version: str
    required: bool
    pit_class: str
    license_class: str
    entitlement_status: str = ""
    entitlement_evidence: str = ""
    entitlement_ref: str = ""
    cadence: str | None = None
    source_url: str | None = None
    status: str = "unavailable"
    row_count: int = 0
    first_observation_at: Any = pd.NaT
    latest_observation_at: Any = pd.NaT
    source_latest_at: Any = pd.NaT
    retrieved_at_utc: Any = pd.NaT
    input_sha256: str | None = None
    missing_geographies: str = ""
    detail: str = ""
    errors: list[dict[str, Any]] = field(default_factory=list)

    def health_row(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "input_path": str(self.path) if self.path is not None else "",
            "source_kind": self.source_kind,
            "status": self.status,
            "required": self.required,
            "row_count": self.row_count,
            "first_observation_at": self.first_observation_at,
            "latest_observation_at": self.latest_observation_at,
            "source_latest_at": self.source_latest_at,
            "retrieved_at_utc": self.retrieved_at_utc,
            "cadence": self.cadence or "",
            "source_url": self.source_url or "",
            "pit_class": self.pit_class,
            "source_license_class": self.license_class,
            "entitlement_status": self.entitlement_status,
            "entitlement_evidence": self.entitlement_evidence,
            "entitlement_ref": self.entitlement_ref,
            "input_sha256": self.input_sha256 or "",
            "schema_version": self.schema_version,
            "missing_geographies": self.missing_geographies,
            "detail": self.detail,
        }


_REGISTRY_INPUT_COLUMNS = {key: list(columns) for key, columns in REGISTRY_OUTPUT_COLUMNS.items()}
_EVENT_INPUT_COLUMNS = {
    name: [
        "event_id",
        "event_key",
        "observation_version",
        "scope",
        "event_type",
        "title",
        "description",
        "status",
        "certainty_class",
        "confidence",
        "date_precision",
        "starts_at",
        "ends_at",
        "source_timezone",
        "source_id",
        "source_url",
        "source_published_at",
        "first_observed_at",
        "last_verified_at",
        "review_by",
        "supersedes_event_id",
        "evidence_class",
        "evidence_ref",
        "reference_period",
        "previous_value",
        "previous_vintage",
        "market_consensus",
        "consensus_source",
        "own_nowcast",
        "actual_value",
        "actual_unit",
        "revised_value",
        "surprise_value",
        "surprise_unit",
        "scenario_notes",
        "expected_metrics",
        "thesis_implications",
        "registry_version",
    ]
    if name == "events"
    else EVENT_LINK_COLUMNS
    if name == "event_links"
    else EVENT_WATCH_QUESTION_COLUMNS
    for name in EVENT_REQUIRED_COLUMNS
}

_OPTIONAL_COLUMNS = {
    NEWS_SCHEMA_ID: {
        "dataset_id",
        "source_url",
        "source_run_id",
        "scraped_at",
        "first_seen_at",
        "last_seen_at",
        "source_name",
        "title",
        "link",
        "pub_date",
        "description",
        "body_text",
    },
    FILING_SCHEMA_ID: {
        "query",
        "accession_no",
        "cik",
        "company_name",
        "form",
        "file_date",
        "filing_url",
        "fetched_at",
        "filing_content",
        "body_text",
    },
    OFFICIAL_FILINGS_SCHEMA_ID: set(OFFICIAL_FILINGS_COLUMNS),
    EARNINGS_ACTUALS_SCHEMA_ID: set(EARNINGS_ACTUALS_COLUMNS),
    SOURCE_STATE_SCHEMA_ID: set(SOURCE_STATE_COLUMNS),
    QUOTE_SNAPSHOT_SCHEMA_ID: set(QUOTE_SNAPSHOT_COLUMNS),
    # realtime_start/realtime_end are optional trailing vintage columns: a
    # legacy non-vintaged FRED export must keep building, while vintaged
    # exports (FredMacroStorage) validate cleanly.
    FRED_OBSERVATIONS_SCHEMA_ID: {
        "date",
        "series_id",
        "value",
        "fetched_at",
        "realtime_start",
        "realtime_end",
    },
    FRED_META_SCHEMA_ID: {
        "series_id",
        "title",
        "frequency",
        "units",
        "seasonal_adjustment",
        "observation_start",
        "last_updated",
        "fetched_at",
    },
    OFR_OBSERVATIONS_SCHEMA_ID: {"date", "mnemonic", "value", "fetched_at"},
    OFR_META_SCHEMA_ID: {
        "mnemonic",
        "name",
        "notes",
        "frequency",
        "start_date",
        "last_update",
        "fetched_at",
    },
    TAIWAN_REVENUE_SCHEMA_ID: {
        "dataset_id",
        "company_code",
        "company_name",
        "market",
        "industry",
        "filing_date",
        "revenue_month",
        "monthly_revenue_ntd",
        "mom_pct",
        "mom_pct_is_derived",
        "yoy_pct",
        "ytd_revenue_ntd",
        "ytd_yoy_pct",
        "source_url",
        "source_run_id",
        "scraped_at",
        "parser_version",
        "raw_company_name_text",
        "raw_monthly_revenue_text",
        "raw_mom_pct_text",
        "raw_yoy_pct_text",
        "raw_ytd_revenue_text",
        "raw_ytd_yoy_pct_text",
    },
    ECB_FX_SCHEMA_ID: {
        "dataset_id",
        "frequency",
        "observation_date",
        "pair",
        "base_currency",
        "quote_currency",
        "value",
        "unit",
        "source_release_date",
        "retrieved_at",
        "source_name",
        "source_url",
        "source_reference_currency",
    },
    MACRO_OBSERVATIONS_SCHEMA_ID: set(MACRO_OBSERVATION_COLUMNS),
    MACRO_COLLECTOR_SCHEMA_ID: set(MACRO_OBSERVATION_COLUMNS),
    MACRO_EVENTS_SCHEMA_ID: set(MACRO_EVENT_COLUMNS),
}

_REQUIRED_OPTIONAL_COLUMNS = {
    key: set(value) for key, value in _OPTIONAL_COLUMNS.items()
}
_REQUIRED_OPTIONAL_COLUMNS[NEWS_SCHEMA_ID] -= {"description", "body_text"}
_REQUIRED_OPTIONAL_COLUMNS[FILING_SCHEMA_ID] -= {"filing_content", "body_text"}
_REQUIRED_OPTIONAL_COLUMNS[FRED_OBSERVATIONS_SCHEMA_ID] -= {"realtime_start", "realtime_end"}


def _iso(value: Any) -> str:
    if value is None or value is pd.NaT or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return ""
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def _timestamp(value: Any, *, date_only: bool = False) -> pd.Timestamp | pd.NaT:
    if value is None or value is pd.NaT or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return pd.NaT
    if isinstance(value, str) and "," in value:
        try:
            parsed_rfc_date = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            parsed_rfc_date = None
        if parsed_rfc_date is not None:
            parsed = pd.Timestamp(parsed_rfc_date)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                parsed = parsed.tz_localize("UTC")
            else:
                parsed = parsed.tz_convert("UTC")
            return parsed.normalize() if date_only else parsed
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return pd.NaT
    if date_only:
        return pd.Timestamp(parsed).normalize()
    return pd.Timestamp(parsed)


def _source_local_date(value: Any, timezone_name: Any) -> pd.Timestamp | pd.NaT:
    """Return a date at local midnight without changing the source day."""

    parsed = pd.Timestamp(value) if not _is_blank(value) else pd.NaT
    if pd.isna(parsed):
        return pd.NaT
    timezone_text = "UTC" if _is_blank(timezone_name) else str(timezone_name)
    try:
        timezone = ZoneInfo(timezone_text)
    except (KeyError, ValueError):
        timezone = ZoneInfo("UTC")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.tz_localize(timezone)
    else:
        parsed = parsed.tz_convert(timezone)
    return pd.Timestamp(parsed.date())


def _stable_hash(*parts: Any) -> str:
    encoded = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_blank(value: Any) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    try:
        missing = pd.isna(value)
        if not hasattr(missing, "__len__") and bool(missing):
            return True
    except (TypeError, ValueError):
        pass
    return not str(value).strip()


def _text(value: Any) -> str:
    return "" if _is_blank(value) else str(value).strip()


def _json_list(values: Iterable[Any]) -> str:
    clean = sorted({str(value).strip() for value in values if not _is_blank(value)})
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))


def _split_ids(value: Any) -> list[str]:
    if _is_blank(value):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if not _is_blank(item)]
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if not _is_blank(item)]
        except json.JSONDecodeError:
            pass
    return [item.strip() for item in re.split(r"[;,|]", text) if item.strip()]


def _normalise_schema_id(value: str) -> str:
    try:
        return _SCHEMA_ALIASES[value]
    except KeyError as exc:
        raise BuildError(f"unsupported optional schema ID: {value!r}") from exc


def _append_state_error(
    state: _SourceState,
    *,
    code: str,
    message: str,
    severity: str = "warning",
) -> None:
    error = {
        "source_id": state.source_id,
        "code": code,
        "message": message,
        "severity": severity,
    }
    state.errors.append(error)
    state.detail = f"{state.detail}; {code}:{message}" if state.detail else f"{code}:{message}"


def _timestamp_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    return pd.Series(
        [_timestamp(value) for value in frame[column]],
        index=frame.index,
        dtype="datetime64[ns, UTC]",
    )


def _apply_source_policy(
    state: _SourceState,
    frame: pd.DataFrame,
    *,
    schema_id: str,
    as_of_utc: pd.Timestamp,
    observed_column: str | None = None,
    retrieved_column: str | None = None,
    latest_column: str | None = None,
    execution_evidence: bool = False,
) -> None:
    """Populate health and fail closed on future or stale source snapshots."""

    policy = SOURCE_TIME_COLUMNS.get(schema_id, {})
    observed_column = observed_column or next(iter(policy.get("observed", ())), None)
    retrieved_column = retrieved_column or next(iter(policy.get("retrieved", ())), None)
    latest_column = latest_column or next(iter(policy.get("freshness", ())), None)
    _set_state_from_frame(
        state,
        frame,
        observed_column=observed_column,
        retrieved_column=retrieved_column,
        latest_column=latest_column,
        execution_evidence=execution_evidence,
    )
    freshness_columns = tuple(policy.get("freshness", ()))
    future_columns = tuple(policy.get("future", ()))
    freshness_values = [
        _timestamp_series(frame, column)
        for column in freshness_columns
        if column in frame.columns
    ]
    freshness = pd.concat(freshness_values, ignore_index=True).dropna() if freshness_values else pd.Series(dtype="datetime64[ns, UTC]")
    if not freshness.empty:
        state.source_latest_at = freshness.max()
    future_values = [
        _timestamp_series(frame, column)
        for column in future_columns
        if column in frame.columns
    ]
    future = pd.concat(future_values, ignore_index=True).dropna() if future_values else pd.Series(dtype="datetime64[ns, UTC]")
    future_rows = future[future > as_of_utc]
    if not future_rows.empty:
        state.status = "degraded"
        _append_state_error(
            state,
            code="future_row_beyond_as_of",
            message=f"latest={_iso(future_rows.max())};as_of={_iso(as_of_utc)}",
        )
        return
    threshold = SOURCE_FRESHNESS_THRESHOLDS.get(schema_id)
    if threshold is not None and not freshness.empty:
        cutoff = as_of_utc - threshold
        if freshness.max() < cutoff:
            state.status = "degraded"
            _append_state_error(
                state,
                code="stale_source",
                message=(
                    f"latest={_iso(freshness.max())};cutoff={_iso(cutoff)};"
                    f"threshold={threshold}"
                ),
            )


def _read_local_input(descriptor: LocalInput) -> pd.DataFrame:
    path = Path(descriptor.path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if descriptor.format == "parquet":
        return pd.read_parquet(path)
    if descriptor.format == "csv":
        return pd.read_csv(path, keep_default_na=False)
    if descriptor.format == "json":
        raw = json.loads(path.read_text())
        if isinstance(raw, dict) and isinstance(raw.get("data"), list):
            raw = raw["data"]
        if not isinstance(raw, list):
            raise ValueError("JSON input must contain a list or a data list")
        return pd.DataFrame(raw)
    return pd.read_json(path, lines=True)


def _validate_exact_columns(frame: pd.DataFrame, expected: Sequence[str], label: str) -> None:
    actual = list(frame.columns)
    if actual != list(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        order = actual != list(expected) and not missing and not extra
        detail = []
        if missing:
            detail.append(f"missing={missing}")
        if extra:
            detail.append(f"extra={extra}")
        if order:
            detail.append("column_order_changed")
        raise BuildError(f"{label} schema drift: {'; '.join(detail)}")


def _validate_optional_columns(frame: pd.DataFrame, schema_id: str, label: str) -> None:
    allowed = _OPTIONAL_COLUMNS[schema_id]
    required = _REQUIRED_OPTIONAL_COLUMNS[schema_id]
    actual = set(frame.columns)
    missing = sorted(required - actual)
    extra = sorted(actual - allowed)
    if missing or extra:
        detail = []
        if missing:
            detail.append(f"missing={missing}")
        if extra:
            detail.append(f"extra={extra}")
        raise BuildError(f"{label} schema drift: {'; '.join(detail)}")


def _sort_frame(frame: pd.DataFrame, keys: Sequence[str]) -> pd.DataFrame:
    if frame.empty:
        return frame.reset_index(drop=True)
    usable = [key for key in keys if key in frame.columns]
    if not usable:
        return frame.reset_index(drop=True)
    return frame.sort_values(usable, kind="mergesort", na_position="last").reset_index(drop=True)


def _with_columns(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    output = frame.copy()
    for column in columns:
        if column not in output.columns:
            output[column] = pd.NA
    return output[list(columns)]


def _task1_frames(registries: Any) -> dict[str, pd.DataFrame]:
    keys = {
        "entities": ["entity_id"],
        "listings": ["listing_id"],
        "baskets": ["basket_id"],
        "basket_memberships": ["basket_id", "entity_id"],
        "indices": ["index_id"],
    }
    return {
        name: _sort_frame(
            _with_columns(getattr(registries, name), REGISTRY_OUTPUT_COLUMNS[name]),
            keys[name],
        )
        for name in REGISTRY_OUTPUT_COLUMNS
    }


def _validate_required_bundles(config: BuildConfig) -> tuple[Any, EventBundle]:
    for root, label in ((config.registry_root, "registry_root"), (config.event_root, "event_root")):
        if not root.is_dir():
            raise BuildError(f"missing {label}: {root}")
    try:
        registries = load_registry_bundle(config.registry_root)
        for name, columns in _REGISTRY_INPUT_COLUMNS.items():
            _validate_exact_columns(getattr(registries, name), columns, f"{name} registry")
        registry_issues = validate_registry_bundle(registries)
    except (FileNotFoundError, ValueError, TypeError) as exc:
        raise BuildError(f"required registry input invalid: {exc}") from exc
    if any(issue.severity == "error" for issue in registry_issues):
        detail = "; ".join(f"{issue.registry}:{issue.code}" for issue in registry_issues)
        raise BuildError(f"required registry validation failed: {detail}")

    try:
        events = load_event_bundle(config.event_root)
        for name, columns in _EVENT_INPUT_COLUMNS.items():
            _validate_exact_columns(getattr(events, name), columns, f"{name} event input")
        event_issues = validate_event_bundle(events, registries, config.as_of_utc)
    except (FileNotFoundError, ValueError, TypeError) as exc:
        raise BuildError(f"required event input invalid: {exc}") from exc
    if any(issue.severity == "error" for issue in event_issues):
        detail = "; ".join(f"{issue.registry}:{issue.code}" for issue in event_issues)
        raise BuildError(f"required event validation failed: {detail}")
    return registries, events


def _validate_required_optional_inputs(config: BuildConfig) -> None:
    """Validate required optional descriptors before any staging or writes."""

    for source_kind, descriptors in (
        ("macro", config.macro_inputs),
        ("news", config.news_inputs),
        ("filing", config.filing_inputs),
        ("official_filing", config.official_filing_inputs),
        ("earnings", config.earnings_inputs),
        ("market", config.quote_inputs),
    ):
        for descriptor in descriptors:
            if not descriptor.required:
                continue
            try:
                schema_id = _normalise_schema_id(descriptor.expected_schema)
            except BuildError as exc:
                raise BuildError(
                    f"required optional input uses unsupported schema: {descriptor.expected_schema}"
                ) from exc
            path = Path(descriptor.path)
            if not path.is_file():
                raise BuildError(f"required optional input missing: {path}")
            if schema_id == MACRO_SOURCE_HEALTH_SCHEMA_ID:
                payload, health_error = _read_macro_source_health(path)
                if health_error:
                    raise BuildError(f"required optional input invalid: {path}: {health_error}")
                if not payload:
                    raise BuildError(f"required optional input invalid: {path}: health sidecar has no source entries")
                continue
            try:
                frame = _read_local_input(descriptor)
                _validate_optional_columns(frame, schema_id, descriptor.source_id)
                state = _optional_state(descriptor, source_kind, schema_id)
                _apply_source_policy(
                    state,
                    frame,
                    schema_id=schema_id,
                    as_of_utc=config.as_of_utc,
                )
                if state.status != "available":
                    raise BuildError(
                        f"required optional input freshness policy failed: {state.detail}"
                    )
            except (OSError, ValueError, TypeError, KeyError, BuildError, pa.ArrowException) as exc:
                raise BuildError(f"required optional input invalid: {path}: {exc}") from exc


def _macro_event_rows(events_frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in events_frame[events_frame["scope"].eq("macro")].iterrows():
        start = _timestamp(row.get("starts_at"))
        evidence = str(row.get("evidence_class", ""))
        pit_class = "not_pit" if evidence == "internal_research" else "snapshot_from_live_source"
        license_class = "internal_research" if evidence == "internal_research" else "official_public"
        rows.append(
            {
                "observation_id": _stable_hash("event_macro", row["event_id"]),
                "event_id": row["event_id"],
                "source_id": row["source_id"],
                "series_id": "",
                "scope": row["scope"],
                "event_type": row["event_type"],
                "metric_name": row["event_type"],
                "reference_period": row["reference_period"],
                "observation_date": _source_local_date(start, row.get("source_timezone"))
                if not pd.isna(start)
                else pd.NaT,
                "release_at": pd.NaT,
                "actual_value": row["actual_value"],
                "unit": row["actual_unit"],
                "frequency": row["date_precision"],
                "first_observed_at": row["first_observed_at"],
                "source_published_at": row["source_published_at"],
                "retrieved_at_utc": pd.NaT,
                "source_url": row["source_url"],
                "pit_class": pit_class,
                "source_license_class": license_class,
                "is_provisional": row["certainty_class"] == "provisional",
                "registry_version": row["registry_version"],
            }
        )
    return rows


def _base_macro_frame(events: EventBundle) -> pd.DataFrame:
    return _with_columns(pd.DataFrame(_macro_event_rows(events.events)), MACRO_OUTPUT_COLUMNS)


def _macro_row(
    *,
    source_id: str,
    series_id: str,
    event_type: str,
    metric_name: str,
    reference_period: Any,
    observation_date: Any,
    actual_value: Any,
    unit: Any,
    frequency: Any,
    retrieved_at: Any,
    source_url: str,
    pit_class: str,
    license_class: str,
    is_provisional: bool = False,
    event_id: str = "",
    source_published_at: Any = pd.NaT,
    release_at: Any = pd.NaT,
    observation_timezone: str | None = None,
    registry_version: str = "v1",
    realtime_start: Any = None,
    realtime_end: Any = None,
) -> dict[str, Any]:
    return {
        "observation_id": _stable_hash("macro", source_id, series_id, reference_period, observation_date),
        "event_id": event_id,
        "source_id": source_id,
        "series_id": series_id,
        "scope": "macro",
        "event_type": event_type,
        "metric_name": metric_name,
        "reference_period": "" if _is_blank(reference_period) else str(reference_period),
        "observation_date": (
            _source_local_date(observation_date, observation_timezone)
            if observation_timezone
            else _timestamp(observation_date, date_only=True)
        ),
        "release_at": _timestamp(release_at),
        "actual_value": "" if _is_blank(actual_value) else str(actual_value),
        "unit": "" if _is_blank(unit) else str(unit),
        "frequency": "" if _is_blank(frequency) else str(frequency),
        "first_observed_at": _timestamp(pd.NaT),
        "source_published_at": _timestamp(source_published_at),
        "retrieved_at_utc": _timestamp(retrieved_at),
        "source_url": source_url,
        "pit_class": pit_class,
        "source_license_class": license_class,
        "is_provisional": is_provisional,
        "registry_version": registry_version,
        "realtime_start": (
            str(realtime_start)
            if realtime_start is not None and not pd.isna(realtime_start)
            else None
        ),
        "realtime_end": (
            str(realtime_end)
            if realtime_end is not None and not pd.isna(realtime_end)
            else None
        ),
    }


def _latest_timestamp(frame: pd.DataFrame, column: str) -> Any:
    if column not in frame.columns or frame.empty:
        return pd.NaT
    values = pd.to_datetime(frame[column], errors="coerce", utc=True)
    return values.max() if not values.dropna().empty else pd.NaT


def _first_timestamp(frame: pd.DataFrame, column: str) -> Any:
    if column not in frame.columns or frame.empty:
        return pd.NaT
    values = pd.to_datetime(frame[column], errors="coerce", utc=True)
    return values.min() if not values.dropna().empty else pd.NaT


def _optional_state(descriptor: LocalInput, source_kind: str, schema_id: str) -> _SourceState:
    return _SourceState(
        source_id=descriptor.source_id,
        source_kind=source_kind,
        path=Path(descriptor.path),
        schema_version=schema_id,
        required=descriptor.required,
        pit_class=descriptor.pit_class,
        license_class=descriptor.license_class,
        cadence=descriptor.cadence,
        source_url=descriptor.source_url,
    )


def _set_state_from_frame(
    state: _SourceState,
    frame: pd.DataFrame,
    *,
    observed_column: str | None = None,
    retrieved_column: str | None = None,
    latest_column: str | None = None,
    execution_evidence: bool = False,
) -> None:
    if state.status != "degraded":
        if len(frame) > 0:
            state.status = "available"
        elif execution_evidence:
            # An honest zero-row query result with collector/execution
            # evidence (e.g. a status sidecar) is ``no_records``; without
            # evidence an empty file is ``unavailable``, never ``available``.
            state.status = "no_records"
        else:
            state.status = "unavailable"
    state.row_count = len(frame)
    if observed_column and observed_column in frame.columns:
        parsed = pd.to_datetime(frame[observed_column], errors="coerce", utc=True)
        non_null = parsed.dropna()
        if not non_null.empty:
            state.first_observation_at = non_null.min()
            state.latest_observation_at = non_null.max()
    if latest_column and latest_column in frame.columns:
        parsed = pd.to_datetime(frame[latest_column], errors="coerce", utc=True)
        non_null = parsed.dropna()
        if not non_null.empty:
            state.source_latest_at = non_null.max()
    if retrieved_column and retrieved_column in frame.columns:
        parsed = pd.to_datetime(frame[retrieved_column], errors="coerce", utc=True)
        non_null = parsed.dropna()
        if not non_null.empty:
            state.retrieved_at_utc = non_null.max()


def _load_optional(
    descriptor: LocalInput,
    source_kind: str,
    *,
    as_of_utc: pd.Timestamp,
    execution_evidence: bool = False,
) -> tuple[_SourceState, pd.DataFrame | None, str | None]:
    try:
        schema_id = _normalise_schema_id(descriptor.expected_schema)
    except BuildError as exc:
        state = _optional_state(descriptor, source_kind, descriptor.expected_schema)
        state.status = "degraded"
        state.detail = f"unsupported_optional_schema:{descriptor.expected_schema}"
        _append_state_error(
            state,
            code="unsupported_schema",
            message=descriptor.expected_schema,
        )
        if Path(descriptor.path).is_file():
            state.input_sha256 = _file_hash(Path(descriptor.path))
        if descriptor.required:
            raise BuildError(
                f"required optional input uses unsupported schema: {descriptor.expected_schema}"
            ) from exc
        return state, None, None
    state = _optional_state(descriptor, source_kind, schema_id)
    if not Path(descriptor.path).is_file():
        state.status = "unavailable"
        state.detail = "configured_optional_input_missing"
        _append_state_error(state, code="missing_input", message=str(descriptor.path))
        if descriptor.required:
            raise BuildError(f"required optional input missing: {descriptor.path}")
        return state, None, None
    state.input_sha256 = _file_hash(Path(descriptor.path))
    try:
        frame = _read_local_input(descriptor)
        _validate_optional_columns(frame, schema_id, descriptor.source_id)
    except (OSError, ValueError, TypeError, KeyError, BuildError, pa.ArrowException) as exc:
        state.status = "degraded"
        state.detail = f"optional_input_invalid:{exc}"
        _append_state_error(state, code="input_validation_failed", message=str(exc))
        if descriptor.required:
            raise BuildError(f"required optional input invalid: {descriptor.path}: {exc}") from exc
        return state, None, schema_id
    _apply_source_policy(
        state,
        frame,
        schema_id=schema_id,
        as_of_utc=as_of_utc,
        execution_evidence=execution_evidence,
    )
    if state.status != "available":
        if descriptor.required:
            raise BuildError(
                f"required optional input freshness policy failed: {descriptor.path}: {state.detail}"
            )
        return state, None, schema_id
    return state, frame, schema_id


def _find_descriptor(inputs: Sequence[LocalInput], schema_id: str) -> LocalInput | None:
    canonical = _normalise_schema_id(schema_id)
    for descriptor in inputs:
        try:
            descriptor_schema = _normalise_schema_id(descriptor.expected_schema)
        except BuildError:
            continue
        if descriptor_schema == canonical:
            return descriptor
    return None


def _fred_macro(
    inputs: Sequence[LocalInput],
    *,
    as_of_utc: pd.Timestamp,
) -> tuple[list[dict[str, Any]], list[_SourceState], list[str]]:
    rows: list[dict[str, Any]] = []
    states: list[_SourceState] = []
    degraded: list[str] = []
    obs_descriptor = _find_descriptor(inputs, FRED_OBSERVATIONS_SCHEMA_ID)
    meta_descriptor = _find_descriptor(inputs, FRED_META_SCHEMA_ID)
    if obs_descriptor is None and meta_descriptor is None:
        return rows, states, degraded
    if obs_descriptor is None or meta_descriptor is None:
        if any(
            descriptor is not None and descriptor.required
            for descriptor in (obs_descriptor, meta_descriptor)
        ):
            raise BuildError("required FRED observations and metadata must be configured together")
        for descriptor in (obs_descriptor, meta_descriptor):
            if descriptor is not None:
                state = _optional_state(descriptor, "macro", _normalise_schema_id(descriptor.expected_schema))
                state.status = "degraded"
                state.detail = "fred_observations_and_meta_must_be_configured_together"
                if Path(descriptor.path).is_file():
                    state.input_sha256 = _file_hash(Path(descriptor.path))
                states.append(state)
        degraded.append("fred")
        return rows, states, degraded
    obs_state, observations, _ = _load_optional(obs_descriptor, "macro", as_of_utc=as_of_utc)
    meta_state, meta, _ = _load_optional(meta_descriptor, "macro", as_of_utc=as_of_utc)
    states.extend((obs_state, meta_state))
    if observations is None or meta is None:
        degraded.append("fred")
        return rows, states, degraded
    meta_by_series = meta.set_index("series_id", drop=False)
    for _, item in observations.iterrows():
        series_id = str(item["series_id"])
        metadata = meta_by_series.loc[series_id] if series_id in meta_by_series.index else None
        rows.append(
            _macro_row(
                source_id=obs_descriptor.source_id,
                series_id=series_id,
                event_type="fred_observation",
                metric_name=str(metadata["title"]) if metadata is not None else series_id,
                reference_period=item["date"],
                observation_date=item["date"],
                actual_value=item["value"],
                unit=metadata["units"] if metadata is not None else "",
                frequency=metadata["frequency"] if metadata is not None else "",
                retrieved_at=item["fetched_at"],
                source_url=f"https://fred.stlouisfed.org/series/{series_id}",
                pit_class=obs_descriptor.pit_class or "current_vintage",
                license_class=obs_descriptor.license_class,
                realtime_start=item.get("realtime_start"),
                realtime_end=item.get("realtime_end"),
            )
        )
    _set_state_from_frame(obs_state, observations, observed_column="date", retrieved_column="fetched_at")
    _set_state_from_frame(
        meta_state,
        meta,
        observed_column="observation_start",
        retrieved_column="fetched_at",
        latest_column="last_updated",
    )
    obs_state.source_url = obs_descriptor.source_url or "https://fred.stlouisfed.org/"
    meta_state.source_url = meta_descriptor.source_url or "https://fred.stlouisfed.org/"
    return rows, states, degraded


def _ofr_macro(
    inputs: Sequence[LocalInput],
    *,
    as_of_utc: pd.Timestamp,
) -> tuple[list[dict[str, Any]], list[_SourceState], list[str]]:
    rows: list[dict[str, Any]] = []
    states: list[_SourceState] = []
    degraded: list[str] = []
    obs_descriptor = _find_descriptor(inputs, OFR_OBSERVATIONS_SCHEMA_ID)
    meta_descriptor = _find_descriptor(inputs, OFR_META_SCHEMA_ID)
    if obs_descriptor is None and meta_descriptor is None:
        return rows, states, degraded
    if obs_descriptor is None or meta_descriptor is None:
        if any(
            descriptor is not None and descriptor.required
            for descriptor in (obs_descriptor, meta_descriptor)
        ):
            raise BuildError("required OFR observations and metadata must be configured together")
        degraded.append("ofr")
        for descriptor in (obs_descriptor, meta_descriptor):
            if descriptor is not None:
                state = _optional_state(descriptor, "macro", _normalise_schema_id(descriptor.expected_schema))
                state.status = "degraded"
                state.detail = "ofr_timeseries_and_meta_must_be_configured_together"
                if Path(descriptor.path).is_file():
                    state.input_sha256 = _file_hash(Path(descriptor.path))
                states.append(state)
        return rows, states, degraded
    obs_state, observations, _ = _load_optional(obs_descriptor, "macro", as_of_utc=as_of_utc)
    meta_state, meta, _ = _load_optional(meta_descriptor, "macro", as_of_utc=as_of_utc)
    states.extend((obs_state, meta_state))
    if observations is None or meta is None:
        degraded.append("ofr")
        return rows, states, degraded
    meta_by_series = meta.set_index("mnemonic", drop=False)
    for _, item in observations.iterrows():
        series_id = str(item["mnemonic"])
        metadata = meta_by_series.loc[series_id] if series_id in meta_by_series.index else None
        rows.append(
            _macro_row(
                source_id=obs_descriptor.source_id,
                series_id=series_id,
                event_type="ofr_observation",
                metric_name=str(metadata["name"]) if metadata is not None else series_id,
                reference_period=item["date"],
                observation_date=item["date"],
                actual_value=item["value"],
                unit="",
                frequency=metadata["frequency"] if metadata is not None else "",
                retrieved_at=item["fetched_at"],
                source_url="https://data.financialresearch.gov/hf/v1",
                pit_class=obs_descriptor.pit_class,
                license_class=obs_descriptor.license_class,
            )
        )
    _set_state_from_frame(obs_state, observations, observed_column="date", retrieved_column="fetched_at")
    _set_state_from_frame(meta_state, meta, observed_column="start_date", retrieved_column="fetched_at", latest_column="last_update")
    obs_state.source_url = obs_descriptor.source_url or "https://data.financialresearch.gov/hf/v1"
    meta_state.source_url = meta_descriptor.source_url or "https://data.financialresearch.gov/hf/v1"
    return rows, states, degraded


def _taiwan_macro(
    inputs: Sequence[LocalInput], registries: Any, *, as_of_utc: pd.Timestamp,
) -> tuple[list[dict[str, Any]], list[_SourceState], list[str]]:
    descriptor = _find_descriptor(inputs, TAIWAN_REVENUE_SCHEMA_ID)
    if descriptor is None:
        return [], [], []
    state, frame, _ = _load_optional(descriptor, "macro", as_of_utc=as_of_utc)
    if frame is None:
        state.missing_geographies = "TW"
        return [], [state], ["taiwan_semiconductor_revenue"]
    native = set(
        registries.listings.loc[
            (registries.listings["exchange"] == "TWSE")
            & registries.listings["mapping_status"].eq("verified")
            & registries.listings["collection_eligible"].fillna(False).astype(bool),
            "native_ticker",
        ].astype("string")
    )
    filtered = frame[frame["company_code"].astype("string").isin(native)].copy()
    if filtered.empty:
        state.status = "degraded"
        state.missing_geographies = "TW"
        state.detail = "no_verified_collection_eligible_tw_listing_match"
        return [], [state], ["taiwan_semiconductor_revenue"]
    rows: list[dict[str, Any]] = []
    for _, item in filtered.iterrows():
        row = _macro_row(
            source_id=descriptor.source_id,
            series_id=str(item["company_code"]),
            event_type="taiwan_monthly_revenue",
            metric_name="monthly_revenue_ntd",
            reference_period=item["revenue_month"],
            observation_date=f"{item['revenue_month']}-01",
            actual_value=item["monthly_revenue_ntd"],
            unit="NTD",
            frequency="monthly",
            retrieved_at=item["scraped_at"],
            source_url=str(item["source_url"]),
            pit_class=descriptor.pit_class,
            license_class=descriptor.license_class,
        )
        rows.append(row)
    _set_state_from_frame(state, filtered, observed_column="revenue_month", retrieved_column="scraped_at")
    if state.source_url is None and filtered["source_url"].notna().any():
        state.source_url = str(filtered["source_url"].dropna().iloc[0])
    return rows, [state], []


def _ecb_macro(
    inputs: Sequence[LocalInput],
    *,
    as_of_utc: pd.Timestamp,
) -> tuple[list[dict[str, Any]], list[_SourceState], list[str]]:
    descriptor = _find_descriptor(inputs, ECB_FX_SCHEMA_ID)
    if descriptor is None:
        return [], [], []
    state, frame, _ = _load_optional(descriptor, "macro", as_of_utc=as_of_utc)
    if frame is None:
        return [], [state], ["ecb_fx"]
    rows = [
        _macro_row(
            source_id=descriptor.source_id,
            series_id=str(item["pair"]),
            event_type="ecb_fx_observation",
            metric_name=str(item["pair"]),
            reference_period=item["observation_date"],
            observation_date=item["observation_date"],
            actual_value=item["value"],
            unit=item["unit"],
            frequency=item["frequency"],
            retrieved_at=item["retrieved_at"],
            source_url=str(item["source_url"]),
            pit_class=descriptor.pit_class,
            license_class=descriptor.license_class,
            release_at=item["source_release_date"],
        )
        for _, item in frame.iterrows()
    ]
    _set_state_from_frame(state, frame, observed_column="observation_date", retrieved_column="retrieved_at")
    state.source_url = str(frame["source_url"].dropna().iloc[0]) if frame["source_url"].notna().any() else state.source_url
    return rows, [state], []


_MACRO_HEALTH_STATUSES = frozenset({
    "available",
    "partial",
    "no_records",
    "stale",
    "not_applicable",
    "unavailable",
})


def _health_count(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _health_timestamp(value: Any) -> Any:
    try:
        return _timestamp(value)
    except (TypeError, ValueError):
        return pd.NaT


def _read_macro_source_health(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read the collector's macro_source_health.json sidecar.

    The sidecar is a JSON object keyed by collector source id (e.g.
    "official:fred_alfred") with SourceHealth.to_dict() payloads.  Returns
    (payload, None) on success and (None, reason) when invalid.
    """
    if not path.is_file():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"macro source health sidecar is invalid: {exc}"
    if not isinstance(payload, dict):
        return None, "macro source health sidecar must be a JSON object keyed by source_id"
    return payload, None


def _load_macro_source_health(
    descriptor: LocalInput,
) -> tuple[list[_SourceState], list[str]]:
    """Turn a collector health sidecar into per-source health states.

    Each collector source (official:fred_alfred, official:bls, official:bea,
    official:ecb, ...) becomes its own source_health row so the build surfaces
    the collector's six-state contract instead of hiding it.
    """
    path = Path(descriptor.path)
    states: list[_SourceState] = []
    degraded: list[str] = []
    if not path.is_file():
        state = _optional_state(descriptor, "macro", MACRO_SOURCE_HEALTH_SCHEMA_ID)
        state.status = "unavailable"
        state.detail = "configured_optional_input_missing"
        _append_state_error(state, code="missing_input", message=str(path))
        if descriptor.required:
            raise BuildError(f"required optional input missing: {path}")
        return [state], [descriptor.source_id]
    payload, health_error = _read_macro_source_health(path)
    if health_error is not None:
        state = _optional_state(descriptor, "macro", MACRO_SOURCE_HEALTH_SCHEMA_ID)
        state.input_sha256 = _file_hash(path)
        state.status = "degraded"
        state.detail = f"optional_input_invalid:{health_error}"
        _append_state_error(state, code="input_validation_failed", message=health_error)
        if descriptor.required:
            raise BuildError(f"required optional input invalid: {path}: {health_error}")
        return [state], [descriptor.source_id]
    if not payload:
        state = _optional_state(descriptor, "macro", MACRO_SOURCE_HEALTH_SCHEMA_ID)
        state.input_sha256 = _file_hash(path)
        state.status = "degraded"
        state.detail = "optional_input_invalid:health sidecar has no source entries"
        _append_state_error(state, code="input_validation_failed", message="health sidecar has no source entries")
        if descriptor.required:
            raise BuildError(f"required optional input invalid: {path}: health sidecar has no source entries")
        return [state], [descriptor.source_id]
    for source_id, info in payload.items():
        if not isinstance(info, dict):
            continue
        raw_status = str(info.get("status") or "").strip()
        if raw_status not in _MACRO_HEALTH_STATUSES:
            status = "degraded"
        else:
            # The collector vocabulary uses ``stale``; the build contract uses
            # ``degraded`` for the same fail-closed condition.
            status = "degraded" if raw_status == "stale" else raw_status
        observation_count = _health_count(info.get("observation_count"))
        event_count = _health_count(info.get("event_count"))
        series_covered = info.get("series_covered") or []
        if not isinstance(series_covered, list):
            series_covered = []
        health_state = _SourceState(
            source_id=str(info.get("source_id") or source_id),
            source_kind="macro",
            path=path,
            schema_version=MACRO_SOURCE_HEALTH_SCHEMA_ID,
            required=descriptor.required,
            pit_class=descriptor.pit_class,
            license_class=descriptor.license_class,
            status=status,
            row_count=observation_count + event_count,
            retrieved_at_utc=_health_timestamp(info.get("retrieved_at_utc")),
            detail=(
                f"collector_event_count={event_count};"
                f"collector_observation_count={observation_count}"
                + (f";collector_error={info['error_detail']}" if info.get("error_detail") else "")
                + (f";series_covered={','.join(str(item) for item in series_covered)}" if series_covered else "")
            ),
        )
        if status not in CONTRIBUTING_STATUSES | {"not_applicable"} and info.get("error_detail"):
            _append_state_error(
                health_state,
                code="collector_source_unavailable",
                message=str(info["error_detail"]),
            )
        states.append(health_state)
    if states:
        # The sidecar itself is a successful collector run: surface an
        # aggregate descriptor state so _expected_health_states does not
        # fabricate a degraded row for the sidecar descriptor.
        aggregate = _optional_state(descriptor, "macro", MACRO_SOURCE_HEALTH_SCHEMA_ID)
        aggregate.input_sha256 = _file_hash(path)
        aggregate.status = "available"
        aggregate.row_count = sum(state.row_count for state in states)
        aggregate.detail = f"collector_sources={len(states)}"
        states.insert(0, aggregate)
    return states, degraded


def _build_macro(
    events: EventBundle,
    registries: Any,
    inputs: Sequence[LocalInput],
    *,
    as_of_utc: pd.Timestamp,
) -> tuple[pd.DataFrame, list[_SourceState], list[str]]:
    rows = _base_macro_frame(events).to_dict("records")
    states: list[_SourceState] = []
    degraded: list[str] = []
    collector_descriptor = (
        _find_descriptor(inputs, MACRO_OBSERVATIONS_SCHEMA_ID)
        or _find_descriptor(inputs, MACRO_COLLECTOR_SCHEMA_ID)
        or _find_descriptor(inputs, "macro_observations")
    )
    if collector_descriptor is not None:
        c_state, c_frame, _ = _load_optional(collector_descriptor, "macro", as_of_utc=as_of_utc)
        states.append(c_state)
        if c_frame is not None and not c_frame.empty:
            rows.extend(c_frame.to_dict("records"))
            _set_state_from_frame(c_state, c_frame, observed_column="observation_date", retrieved_column="retrieved_at_utc")
        else:
            degraded.append("macro_collector")
    events_descriptor = _find_descriptor(inputs, MACRO_EVENTS_SCHEMA_ID)
    if events_descriptor is not None:
        ev_state, ev_frame, _ = _load_optional(events_descriptor, "macro", as_of_utc=as_of_utc)
        states.append(ev_state)
        if ev_frame is not None and not ev_frame.empty:
            rows.extend(_macro_event_rows(ev_frame))
            _set_state_from_frame(
                ev_state,
                ev_frame,
                observed_column="starts_at",
                retrieved_column="first_observed_at",
            )
        else:
            degraded.append("macro_collector_events")
    health_descriptor = _find_descriptor(inputs, MACRO_SOURCE_HEALTH_SCHEMA_ID)
    if health_descriptor is not None:
        health_states, health_degraded = _load_macro_source_health(health_descriptor)
        states.extend(health_states)
        degraded.extend(health_degraded)
    for adapter in (_fred_macro, _ofr_macro):
        adapter_rows, adapter_states, adapter_degraded = adapter(inputs, as_of_utc=as_of_utc)
        rows.extend(adapter_rows)
        states.extend(adapter_states)
        degraded.extend(adapter_degraded)
    tw_rows, tw_states, tw_degraded = _taiwan_macro(inputs, registries, as_of_utc=as_of_utc)
    rows.extend(tw_rows)
    states.extend(tw_states)
    degraded.extend(tw_degraded)
    ecb_rows, ecb_states, ecb_degraded = _ecb_macro(inputs, as_of_utc=as_of_utc)
    rows.extend(ecb_rows)
    states.extend(ecb_states)
    degraded.extend(ecb_degraded)
    frame = _with_columns(pd.DataFrame(rows), MACRO_OUTPUT_COLUMNS)
    return _sort_frame(frame, ["observation_id"]), states, sorted(set(degraded))


def _verified_crosswalk(registries: Any) -> tuple[dict[str, str], dict[str, str], dict[str, set[str]]]:
    listings = registries.listings.copy()
    eligible = listings[
        listings["mapping_status"].eq("verified")
        & listings["collection_eligible"].fillna(False).astype(bool)
    ]
    listing_by_ticker: dict[str, str] = {}
    entity_by_listing: dict[str, str] = {}
    for _, row in eligible.iterrows():
        listing_id = str(row["listing_id"])
        entity_by_listing[listing_id] = str(row["entity_id"])
        for key in (row["native_ticker"], row["canonical_ticker"]):
            if not _is_blank(key):
                listing_by_ticker[str(key).upper()] = listing_id
    baskets_by_entity: dict[str, set[str]] = {}
    for _, row in registries.basket_memberships.iterrows():
        entity = str(row["entity_id"])
        baskets_by_entity.setdefault(entity, set()).add(str(row["basket_id"]))
    return listing_by_ticker, entity_by_listing, baskets_by_entity


def _unresolved_geographies(registries: Any) -> str:
    unresolved_entities = set(
        registries.listings.loc[
            registries.listings["mapping_status"].ne("verified"), "entity_id"
        ].astype("string")
    )
    countries = registries.entities.loc[
        registries.entities["entity_id"].isin(unresolved_entities), "country"
    ]
    return ",".join(sorted({str(value) for value in countries if not _is_blank(value)}))


def _explicit_related_ids(row: Mapping[str, Any], registries: Any) -> tuple[list[str], list[str], list[str]]:
    listing_by_ticker, entity_by_listing, baskets_by_entity = _verified_crosswalk(registries)
    mapped_entities = set(entity_by_listing.values())
    listing_ids: set[str] = set()
    entity_ids: set[str] = set()
    basket_ids: set[str] = set()
    for column in ("related_listing_ids", "listing_id", "ticker", "symbol"):
        for value in _split_ids(row.get(column)):
            if value in entity_by_listing:
                listing_ids.add(value)
            elif value.upper() in listing_by_ticker:
                listing_ids.add(listing_by_ticker[value.upper()])
    for listing_id in listing_ids:
        entity = entity_by_listing.get(listing_id)
        if entity:
            entity_ids.add(entity)
    for column in ("related_entity_ids", "entity_id"):
        for value in _split_ids(row.get(column)):
            if value in mapped_entities:
                entity_ids.add(value)
    for value in _split_ids(row.get("related_basket_ids")):
        if value in set(registries.baskets["basket_id"]):
            basket_ids.add(value)
    for entity in entity_ids:
        basket_ids.update(baskets_by_entity.get(entity, set()))
    return sorted(entity_ids), sorted(listing_ids), sorted(basket_ids)


def _source_quality_class(descriptor: LocalInput, document_type: str) -> str:
    """Normalize quality separately from the publisher/display name."""

    if document_type == "filing":
        return "official_metadata"
    source_text = f"{descriptor.source_id} {descriptor.license_class}".lower()
    if "entitled" in source_text or "commercial" in source_text:
        return "entitled"
    if "discovery" in source_text:
        return "discovery"
    if "official" in source_text or "rss" in source_text or "public_metadata" in source_text:
        return "official"
    return "unknown"


def _news_rows(
    descriptor: LocalInput, frame: pd.DataFrame, registries: Any
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, item in frame.iterrows():
        headline = "" if _is_blank(item.get("title")) else str(item.get("title"))
        url = "" if _is_blank(item.get("link")) else str(item.get("link"))
        published = _timestamp(item.get("pub_date"))
        first_seen = _timestamp(item.get("first_seen_at"))
        entity_ids, listing_ids, basket_ids = _explicit_related_ids(item, registries)
        rows.append(
            {
                "document_id": _stable_hash("news", descriptor.source_id, url, headline, published),
                "document_type": "news",
                "source_id": descriptor.source_id,
                "headline": headline,
                "publisher": item.get("source_name", ""),
                "published_at": published,
                "first_observed_at": first_seen,
                "source_url": url or descriptor.source_url or item.get("source_url", ""),
                "language": item.get("language", "") if "language" in frame.columns else "",
                "related_entity_ids": _json_list(entity_ids),
                "related_listing_ids": _json_list(listing_ids),
                "related_basket_ids": _json_list(basket_ids),
                "event_class": "official_news_metadata",
                "importance": item.get("importance", "") if "importance" in frame.columns else "",
                "source_quality": _source_quality_class(descriptor, "news"),
                "pit_class": descriptor.pit_class,
                "source_license_class": descriptor.license_class,
                "content_hash_if_permitted": "",
                "derived_summary_if_permitted": "",
            }
        )
    return rows


def _filing_rows(
    descriptor: LocalInput, frame: pd.DataFrame, registries: Any
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, item in frame.iterrows():
        accession = str(item.get("accession_no", ""))
        company = str(item.get("company_name", ""))
        form = str(item.get("form", ""))
        entity_ids, listing_ids, basket_ids = _explicit_related_ids(item, registries)
        rows.append(
            {
                "document_id": accession or _stable_hash("filing", descriptor.source_id, company, form, item.get("file_date")),
                "document_type": "filing",
                "source_id": descriptor.source_id,
                "headline": " ".join(part for part in (company, form) if part and part != "nan"),
                "publisher": "SEC",
                "published_at": _timestamp(item.get("file_date"), date_only=True),
                "first_observed_at": _timestamp(item.get("fetched_at")),
                "source_url": item.get("filing_url", "") or descriptor.source_url or "",
                "language": "en",
                "related_entity_ids": _json_list(entity_ids),
                "related_listing_ids": _json_list(listing_ids),
                "related_basket_ids": _json_list(basket_ids),
                "event_class": "sec_filing_metadata",
                "importance": "",
                "source_quality": _source_quality_class(descriptor, "filing"),
                "pit_class": descriptor.pit_class,
                "source_license_class": descriptor.license_class,
                "content_hash_if_permitted": "",
                "derived_summary_if_permitted": "",
            }
        )
    return rows


def _build_news_filings(
    registries: Any,
    news_inputs: Sequence[LocalInput],
    filing_inputs: Sequence[LocalInput],
    *,
    as_of_utc: pd.Timestamp,
) -> tuple[pd.DataFrame, list[_SourceState], list[str]]:
    rows: list[dict[str, Any]] = []
    states: list[_SourceState] = []
    degraded: list[str] = []
    missing_geographies = _unresolved_geographies(registries)
    for descriptor, kind, row_builder in [
        *[(item, "news", _news_rows) for item in news_inputs],
        *[(item, "filing", _filing_rows) for item in filing_inputs],
    ]:
        state, frame, schema_id = _load_optional(descriptor, kind, as_of_utc=as_of_utc)
        state.missing_geographies = missing_geographies
        states.append(state)
        if frame is None:
            degraded.append(descriptor.source_id)
            continue
        if kind == "news":
            rows.extend(row_builder(descriptor, frame, registries))
            _set_state_from_frame(state, frame, observed_column="pub_date", retrieved_column="first_seen_at")
            if "source_url" in frame.columns and frame["source_url"].notna().any():
                state.source_url = str(frame["source_url"].dropna().iloc[0])
        else:
            rows.extend(row_builder(descriptor, frame, registries))
            _set_state_from_frame(state, frame, observed_column="file_date", retrieved_column="fetched_at")
            if "filing_url" in frame.columns and frame["filing_url"].notna().any():
                state.source_url = str(frame["filing_url"].dropna().iloc[0])
        if schema_id is None:
            degraded.append(descriptor.source_id)
    if not news_inputs:
        state = _SourceState(
            source_id="news_official_ai_rss",
            source_kind="news",
            path=None,
            schema_version=NEWS_SCHEMA_ID,
            required=False,
            pit_class="snapshot_from_live_source",
            license_class="official_public",
            missing_geographies=missing_geographies,
            detail="optional_official_ai_rss_not_configured",
        )
        states.append(state)
        degraded.append("news_official_ai_rss")
    if not filing_inputs:
        state = _SourceState(
            source_id="filings_sec_edgar",
            source_kind="filing",
            path=None,
            schema_version=FILING_SCHEMA_ID,
            required=False,
            pit_class="snapshot_from_live_source",
            license_class="official_public",
            missing_geographies="CN,DE,FR,GB,HK,IE,JP,KR,NL,TW",
            detail="optional_sec_metadata_not_configured; query_scoped_us_only",
        )
        states.append(state)
        degraded.append("filings_sec_edgar")
    frame = _with_columns(pd.DataFrame(rows), NEWS_FILINGS_COLUMNS)
    return _sort_frame(frame, ["document_id"]), states, sorted(set(degraded))


def _sidecar_int(value: Any) -> int:
    try:
        numeric = pd.to_numeric(value, errors="coerce")
        return int(numeric) if not pd.isna(numeric) else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def _sidecar_states(frame: pd.DataFrame) -> list[_SourceState]:
    """Convert collector state-sidecar rows into explicit source-health rows.

    The sidecar preserves the plan's coverage semantics (available/partial/
    no_records/not_applicable/unavailable) as the raw status so an honest
    empty query is never relabelled as a failed provider and a private entity
    is never treated as a broken public source.
    """

    states: list[_SourceState] = []
    for _, item in frame.iterrows():
        source_id = str(item.get("source_id") or "").strip()
        if not source_id:
            continue
        status = str(item.get("status") or "unavailable").strip() or "unavailable"
        detail = str(item.get("detail") or "").strip()
        states.append(
            _SourceState(
                source_id=source_id,
                source_kind=str(item.get("source_kind") or "optional").strip() or "optional",
                path=None,
                schema_version=SOURCE_STATE_SCHEMA_ID,
                required=False,
                pit_class=str(item.get("pit_class") or "snapshot_from_live_source"),
                license_class=str(item.get("source_license_class") or "public_metadata"),
                cadence=str(item.get("cadence") or "").strip() or None,
                source_url=str(item.get("source_url") or "").strip() or None,
                status=status,
                row_count=_sidecar_int(item.get("row_count")),
                first_observation_at=_timestamp(item.get("first_observation_at")),
                latest_observation_at=_timestamp(item.get("latest_observation_at")),
                source_latest_at=_timestamp(item.get("source_latest_at")),
                retrieved_at_utc=_timestamp(item.get("retrieved_at_utc")),
                detail=detail or f"{status}; collector state sidecar",
            )
        )
    return states


def _resolve_official_relations(
    frame: pd.DataFrame,
    registries: Any,
) -> tuple[pd.DataFrame, int]:
    """Keep only rows whose entity/listing relations resolve in the registry.

    Unknown or mismatched rows are dropped with a counted note rather than
    silently admitted; the caller records the drop on the source-health row.
    """

    known_entities = set(registries.entities["entity_id"].astype("string"))
    known_listings = set(registries.listings["listing_id"].astype("string"))
    listing_entities = dict(
        zip(
            registries.listings["listing_id"].astype("string"),
            registries.listings["entity_id"].astype("string"),
        )
    )
    canonical_by_listing = dict(
        zip(
            registries.listings["listing_id"].astype("string"),
            registries.listings["canonical_ticker"].astype("string"),
        )
    )
    kept: list[dict[str, Any]] = []
    dropped = 0
    for _, item in frame.iterrows():
        entity = str(item.get("entity_id") or "").strip()
        listing = str(item.get("listing_id") or "").strip()
        if (
            entity not in known_entities
            or listing not in known_listings
            or listing_entities.get(listing) != entity
        ):
            dropped += 1
            continue
        row = dict(item)
        row["canonical_ticker"] = canonical_by_listing.get(listing, row.get("canonical_ticker", ""))
        kept.append(row)
    return pd.DataFrame(kept), dropped


def _calendar_event_type(period_label: Any, period_start: Any, period_end: Any) -> str:
    label = str(period_label or "").upper()
    if any(token in label for token in ("ANNUAL", "YEAR ENDED", "FULL YEAR")) or label.startswith("FY"):
        return "annual_results"
    if any(token in label for token in ("INTERIM", "SIX MONTH", "HALF YEAR")) or label.startswith("1H"):
        return "interim_results"
    if any(token in label for token in ("QUARTER", "THREE MONTH")) or re.match(r"^Q[1-4]", label):
        return "quarterly_results"
    start = _timestamp(period_start, date_only=True)
    end = _timestamp(period_end, date_only=True)
    if not pd.isna(start) and not pd.isna(end):
        days = (end - start).days
        if 330 <= days <= 380:
            return "annual_results"
        if 150 <= days <= 200:
            return "interim_results"
    return "results"


def _calendar_rows_from_filings(filings: pd.DataFrame) -> pd.DataFrame:
    """Derive the official earnings calendar from filing/announcement rows.

    Only rows explicitly classified as earnings results by the source adapter
    become calendar rows.  The event date is either the source-native
    announcement date (HKEX publishes an exact local timestamp) or the filing
    date (SEC metadata exposes the accepted date, not the press-release time);
    ``date_basis`` keeps that distinction visible and ``date_precision`` is
    never inflated beyond what the source provides.
    """

    rows: list[dict[str, Any]] = []
    for _, item in filings.iterrows():
        if str(item.get("event_class") or "") != "earnings_results":
            continue
        status = str(item.get("event_status") or "observed")
        scheduled = _timestamp(item.get("scheduled_date"), date_only=True)
        published = _timestamp(item.get("published_at"))
        if status == "scheduled" and not pd.isna(scheduled):
            event_date = scheduled
            date_basis = "scheduled"
            published_at = pd.NaT
            headline = str(item.get("headline") or "")
        elif not pd.isna(published):
            event_date = published.tz_convert("UTC").normalize()
            date_basis = (
                "announcement_date"
                if str(item.get("date_precision") or "") == "minute"
                else "filing_date"
            )
            published_at = published
            headline = str(item.get("headline") or "")
        else:
            continue
        period_start = _timestamp(item.get("reporting_period_start"), date_only=True)
        period_end = _timestamp(item.get("reporting_period_end"), date_only=True)
        rows.append(
            {
                "calendar_id": _stable_hash(
                    "earnings_calendar", item.get("document_id"), item.get("listing_id")
                ),
                "entity_id": item.get("entity_id"),
                "listing_id": item.get("listing_id"),
                "canonical_ticker": item.get("canonical_ticker"),
                "period_label": item.get("reporting_period_label"),
                "period_start": period_start,
                "period_end": period_end,
                "event_type": _calendar_event_type(
                    item.get("reporting_period_label"), period_start, period_end
                ),
                "event_date": event_date,
                "date_precision": "day",
                "date_basis": date_basis,
                "source_timezone": item.get("source_timezone"),
                "status": status if status in {"scheduled", "confirmed", "observed"} else "observed",
                "source_id": item.get("source_id"),
                "source_url": item.get("source_url"),
                "headline": headline,
                "published_at": published_at,
                "retrieved_at_utc": _timestamp(item.get("retrieved_at_utc")),
                "source_quality": item.get("source_quality"),
                "pit_class": item.get("pit_class"),
                "source_license_class": item.get("source_license_class"),
                "source_note": item.get("source_note"),
                "registry_version": item.get("registry_version"),
            }
        )
    return _sort_frame(
        _with_columns(pd.DataFrame(rows), EARNINGS_CALENDAR_COLUMNS),
        ["calendar_id"],
    )


def _build_official_filings(
    registries: Any,
    inputs: Sequence[LocalInput],
    *,
    as_of_utc: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, list[_SourceState], list[str]]:
    """Materialize the official filings/announcements mart and the derived
    earnings calendar from the Batch 2 collector inputs."""

    filings_descriptor = _find_descriptor(inputs, OFFICIAL_FILINGS_SCHEMA_ID)
    state_descriptor = _find_descriptor(inputs, SOURCE_STATE_SCHEMA_ID)
    states: list[_SourceState] = []
    degraded: list[str] = []
    rows: list[dict[str, Any]] = []

    if filings_descriptor is not None:
        state, frame, _schema_id = _load_optional(
            filings_descriptor, "official_filing", as_of_utc=as_of_utc
        )
        states.append(state)
        if frame is None:
            degraded.append(filings_descriptor.source_id)
        else:
            frame = _with_columns(frame, OFFICIAL_FILINGS_COLUMNS)
            frame, dropped = _resolve_official_relations(frame, registries)
            if dropped:
                state.row_count = len(frame)
                state.detail = (
                    f"{state.detail}; " if state.detail else ""
                ) + f"dropped_unresolved_relations={dropped}"
                _append_state_error(
                    state,
                    code="unresolved_relations",
                    message=f"dropped {dropped} rows with unknown entity/listing ids",
                )
            rows = frame.to_dict("records")
    else:
        degraded.append("official_filings")

    if state_descriptor is not None:
        state, state_frame, _schema_id = _load_optional(
            state_descriptor, "official_filing", as_of_utc=as_of_utc
        )
        states.append(state)
        if state_frame is None:
            degraded.append(state_descriptor.source_id)
        else:
            states.extend(_sidecar_states(_with_columns(state_frame, SOURCE_STATE_COLUMNS)))
    else:
        degraded.append("official_filings_state")

    filings_out = _with_columns(pd.DataFrame(rows), OFFICIAL_FILINGS_COLUMNS)
    filings_out = _sort_frame(filings_out, ["document_id", "listing_id"])
    calendar_out = _calendar_rows_from_filings(filings_out)
    return filings_out, calendar_out, states, sorted(set(degraded))


def _build_earnings_actuals(
    registries: Any,
    inputs: Sequence[LocalInput],
    *,
    as_of_utc: pd.Timestamp,
) -> tuple[pd.DataFrame, list[_SourceState], list[str]]:
    """Materialize the versioned earnings-actuals mart from Batch 3 inputs."""

    actuals_descriptor = _find_descriptor(inputs, EARNINGS_ACTUALS_SCHEMA_ID)
    state_descriptor = _find_descriptor(inputs, SOURCE_STATE_SCHEMA_ID)
    states: list[_SourceState] = []
    degraded: list[str] = []
    rows: list[dict[str, Any]] = []

    if actuals_descriptor is not None:
        state, frame, _schema_id = _load_optional(
            actuals_descriptor, "earnings", as_of_utc=as_of_utc
        )
        states.append(state)
        if frame is None:
            degraded.append(actuals_descriptor.source_id)
        else:
            frame = _with_columns(frame, EARNINGS_ACTUALS_COLUMNS)
            frame, dropped = _resolve_official_relations(frame, registries)
            if dropped:
                state.row_count = len(frame)
                state.detail = (
                    f"{state.detail}; " if state.detail else ""
                ) + f"dropped_unresolved_relations={dropped}"
                _append_state_error(
                    state,
                    code="unresolved_relations",
                    message=f"dropped {dropped} rows with unknown entity/listing ids",
                )
            rows = frame.to_dict("records")
    else:
        degraded.append("earnings_actuals")

    if state_descriptor is not None:
        state, state_frame, _schema_id = _load_optional(
            state_descriptor, "earnings", as_of_utc=as_of_utc
        )
        states.append(state)
        if state_frame is None:
            degraded.append(state_descriptor.source_id)
        else:
            states.extend(_sidecar_states(_with_columns(state_frame, SOURCE_STATE_COLUMNS)))
    else:
        degraded.append("earnings_actuals_state")

    actuals_out = _with_columns(pd.DataFrame(rows), EARNINGS_ACTUALS_COLUMNS)
    actuals_out = _sort_frame(
        actuals_out, ["entity_id", "metric", "period_end", "version"]
    )
    return actuals_out, states, sorted(set(degraded))


def _task3_empty(columns: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})


def _task3_schema(frame: pd.DataFrame, columns: Sequence[str], label: str) -> None:
    if list(frame.columns) != list(columns):
        raise BuildError(f"{label} schema drift: expected exact Task 3 columns")


def _task3_physical_schema(path: Path, expected: pa.Schema, label: str) -> None:
    actual = pq.read_schema(path)
    if not actual.equals(expected):
        raise BuildError(
            f"{label} physical schema drift: expected exact Task 3 Arrow schema"
        )


def _composite_input_hash(named_hashes: Mapping[str, str]) -> str:
    """Hash the ordered ``filename\x1fsha256`` pairs for a multi-file source."""

    return hashlib.sha256(
        "\x1f".join(
            f"{name}\x1f{named_hashes[name]}" for name in sorted(named_hashes)
        ).encode("utf-8")
    ).hexdigest()


_CONSENSUS_ALLOWED_LOCAL_LICENSES = frozenset(
    {"local_private_research", "research_use_only", "private_research"}
)
_CONSENSUS_ALLOWED_ENTITLEMENT_STATUSES = frozenset(
    {"terms_unverified", "permitted_local_private"}
)
_TASK3_SUPPORTED_CONSENSUS_PROVIDERS = ("akshare", "yfinance")
_TASK3_OPTIONAL_CONSENSUS_PROVIDERS = (
    "futu",
    "fnguide",
    "alpha_vantage",
    "fmp",
)
_CONSENSUS_PROVIDER_ALLOWLIST = frozenset(
    (*_TASK3_SUPPORTED_CONSENSUS_PROVIDERS, *_TASK3_OPTIONAL_CONSENSUS_PROVIDERS)
)


def _consensus_entitlement_usable(item: Mapping[str, Any]) -> bool:
    """Return whether a provider-health row permits local/private rows."""

    license_class = "" if _is_blank(item.get("source_license_class")) else str(item.get("source_license_class")).strip().lower()
    entitlement_status = "" if _is_blank(item.get("entitlement_status")) else str(item.get("entitlement_status")).strip().lower()
    evidence = "" if _is_blank(item.get("entitlement_evidence")) else str(item.get("entitlement_evidence")).strip()
    reference = "" if _is_blank(item.get("entitlement_ref")) else str(item.get("entitlement_ref")).strip()
    return bool(
        license_class in _CONSENSUS_ALLOWED_LOCAL_LICENSES
        and entitlement_status in _CONSENSUS_ALLOWED_ENTITLEMENT_STATUSES
        and evidence
        and reference
    )


def _build_consensus(
    config: BuildConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, list[_SourceState], list[str], dict[str, str]]:
    snapshots = _task3_empty(TASK3_SNAPSHOT_COLUMNS)
    revisions = _task3_empty(TASK3_REVISION_COLUMNS)
    states: list[_SourceState] = []
    degraded: list[str] = []
    fingerprints: dict[str, str] = {}
    directory = config.consensus_export_dir
    if directory is None or not directory.is_dir():
        state = _SourceState(
            source_id="consensus_export",
            source_kind="consensus",
            path=directory,
            schema_version="task3_consensus_export_v1",
            required=False,
            pit_class="snapshot_from_live_source",
            license_class="local_private_research",
            entitlement_status="terms_unverified",
            entitlement_evidence="No populated rows are admitted without Task 3 provider-health evidence",
            entitlement_ref="task3-provider-policy:sidecar-required-v1",
            detail="optional_task3_export_directory_missing",
        )
        states.append(state)
        degraded.append("consensus_export")
        return snapshots, revisions, states, degraded, fingerprints
    names = {
        "snapshots": "control_tower_consensus_snapshots.parquet",
        "revisions": "control_tower_consensus_revisions.parquet",
        "health": "control_tower_consensus_source_health.parquet",
    }
    paths = {key: directory / name for key, name in names.items()}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    state = _SourceState(
        source_id="consensus_export",
        source_kind="consensus",
        path=directory,
        schema_version="task3_consensus_export_v1",
        required=False,
        pit_class="snapshot_from_live_source",
        license_class="local_private_research",
        entitlement_status="terms_unverified",
        entitlement_evidence=(
            "Task 3 provider-health sidecar is required for populated consensus "
            "rows; no redistribution rights are asserted"
        ),
        entitlement_ref="task3-provider-policy:sidecar-required-v1",
    )
    if missing:
        state.status = "unavailable"
        state.detail = f"task3_export_files_missing:{','.join(missing)}"
        states.append(state)
        degraded.append("consensus_export")
        return snapshots, revisions, states, degraded, fingerprints
    try:
        _task3_physical_schema(
            paths["snapshots"],
            TASK3_SNAPSHOT_ARROW_SCHEMA,
            "consensus snapshots",
        )
        _task3_physical_schema(
            paths["revisions"],
            TASK3_REVISION_ARROW_SCHEMA,
            "consensus revisions",
        )
        _task3_physical_schema(
            paths["health"],
            TASK3_HEALTH_ARROW_SCHEMA,
            "consensus source health",
        )
        snapshots = pd.read_parquet(paths["snapshots"])
        revisions = pd.read_parquet(paths["revisions"])
        health = pd.read_parquet(paths["health"])
        _task3_schema(snapshots, TASK3_SNAPSHOT_COLUMNS, "consensus snapshots")
        _task3_schema(revisions, TASK3_REVISION_COLUMNS, "consensus revisions")
        _task3_schema(health, TASK3_HEALTH_COLUMNS, "consensus source health")
    except (OSError, ValueError, TypeError, BuildError, pa.ArrowException) as exc:
        state.status = "degraded"
        state.detail = f"task3_export_invalid:{exc}"
        states.append(state)
        degraded.append("consensus_export")
        return _task3_empty(TASK3_SNAPSHOT_COLUMNS), _task3_empty(TASK3_REVISION_COLUMNS), states, degraded, fingerprints
    for path in paths.values():
        fingerprints[str(path)] = _file_hash(path)
    state.status = "available"
    state.row_count = len(snapshots) + len(revisions)
    state.first_observation_at = _first_timestamp(snapshots, "snapshot_at")
    state.latest_observation_at = _latest_timestamp(snapshots, "snapshot_at")
    state.source_latest_at = _latest_timestamp(snapshots, "provider_asof")
    state.retrieved_at_utc = _latest_timestamp(snapshots, "retrieved_at_utc")
    state.input_sha256 = _composite_input_hash(
        {path.name: fingerprints[str(path)] for path in paths.values()}
    )
    state.detail = (
        "composite_sha256=sha256(sorted(filename\\x1ffile_sha256_pairs));"
        "files=control_tower_consensus_snapshots.parquet,"
        "control_tower_consensus_revisions.parquet,"
        "control_tower_consensus_source_health.parquet"
    )
    for frame in (snapshots, revisions):
        if not frame.empty:
            _apply_source_policy(
                state,
                frame,
                schema_id="task3_consensus_export_v1",
                as_of_utc=config.as_of_utc,
            )
    state.row_count = len(snapshots) + len(revisions)
    state.first_observation_at = min(
        (
            value
            for value in (
                _first_timestamp(snapshots, "snapshot_at"),
                _first_timestamp(revisions, "current_snapshot_at"),
            )
            if not pd.isna(value)
        ),
        default=pd.NaT,
    )
    state.latest_observation_at = max(
        (
            value
            for value in (
                _latest_timestamp(snapshots, "snapshot_at"),
                _latest_timestamp(revisions, "current_snapshot_at"),
            )
            if not pd.isna(value)
        ),
        default=pd.NaT,
    )
    if state.status != "available":
        states.append(state)
        degraded.append("consensus_export")
        return (
            _task3_empty(TASK3_SNAPSHOT_COLUMNS),
            _task3_empty(TASK3_REVISION_COLUMNS),
            states,
            degraded,
            fingerprints,
        )
    states.append(state)
    provider_policy_failed = False
    usable_provider_count = 0
    health_providers = {
        str(value).strip()
        for value in health["provider"].tolist()
        if not _is_blank(value)
    }
    populated_providers = {
        str(value).strip()
        for frame in (snapshots, revisions)
        for value in frame.get("provider", pd.Series(dtype="object")).tolist()
        if not _is_blank(value)
    }
    populated_providers.update(
        str(value).strip()
        for value in revisions.get("prior_provider", pd.Series(dtype="object")).tolist()
        if not _is_blank(value)
    )
    unknown_providers = populated_providers - _CONSENSUS_PROVIDER_ALLOWLIST
    if unknown_providers:
        provider_policy_failed = True
        _append_state_error(
            state,
            code="provider_not_in_task3_allowlist",
            message=(
                "populated providers outside the Task 3 allowlist: "
                + ",".join(sorted(unknown_providers))
            ),
        )
    missing_health_providers = populated_providers - health_providers
    if missing_health_providers:
        provider_policy_failed = True
        _append_state_error(
            state,
            code="provider_health_sidecar_missing_for_populated_rows",
            message=(
                "providers without matching health rows: "
                + ",".join(sorted(missing_health_providers))
            ),
        )
    for _, item in health.sort_values(["provider", "status"], kind="mergesort").iterrows():
        provider = str(item["provider"])
        reported_status = str(item["status"])
        provider_rows = snapshots[snapshots["provider"].eq(provider)]
        provider_revisions = revisions[revisions["provider"].eq(provider)]
        prior_provider_revisions = revisions[revisions["prior_provider"].eq(provider)]
        populated = (
            not provider_rows.empty
            or not provider_revisions.empty
            or not prior_provider_revisions.empty
        )
        entitlement_usable = _consensus_entitlement_usable(item)
        sidecar_status = "" if _is_blank(item.get("entitlement_status")) else str(item.get("entitlement_status")).strip().lower()
        sidecar_evidence = "" if _is_blank(item.get("entitlement_evidence")) else str(item.get("entitlement_evidence")).strip()
        sidecar_ref = "" if _is_blank(item.get("entitlement_ref")) else str(item.get("entitlement_ref")).strip()
        sidecar_license = "" if _is_blank(item.get("source_license_class")) else str(item.get("source_license_class")).strip()
        provider_state = _SourceState(
            source_id=f"consensus:{provider}",
            source_kind="consensus",
            path=paths["health"],
            schema_version="task3_consensus_source_health_v1",
            required=False,
            pit_class="snapshot_from_live_source",
            license_class=sidecar_license,
            entitlement_status=sidecar_status,
            entitlement_evidence=sidecar_evidence,
            entitlement_ref=sidecar_ref,
            source_latest_at=_timestamp(item["latest_snapshot_at"]),
            detail=str(item["reason"]),
        )
        provider_state.status = "available"
        provider_state.input_sha256 = fingerprints[str(paths["health"])]
        _apply_source_policy(
            provider_state,
            item.to_frame().T,
            schema_id="task3_consensus_source_health_v1",
            as_of_utc=config.as_of_utc,
        )
        policy_failed = provider_state.status != "available"
        if populated and provider not in _CONSENSUS_PROVIDER_ALLOWLIST:
            policy_failed = True
            _append_state_error(
                provider_state,
                code="provider_not_in_task3_allowlist",
                message=(
                    f"provider={provider}; populated consensus rows require an "
                    "explicitly recognized Task 3 provider"
                ),
            )
        if populated and not entitlement_usable:
            policy_failed = True
            _append_state_error(
                provider_state,
                code="provider_entitlement_evidence_missing_or_unsupported",
                message=(
                    f"provider={provider}; populated consensus rows require "
                    "accepted local/private license and evidence reference"
                ),
            )
        if populated and reported_status != "available":
            policy_failed = True
            _append_state_error(
                provider_state,
                code="provider_health_not_available_for_populated_rows",
                message=f"provider={provider};status={reported_status}",
            )
        if not policy_failed:
            provider_state.status = reported_status
        else:
            provider_policy_failed = True
            provider_state.status = "degraded"
        if provider_state.status == "available" and populated:
            usable_provider_count += 1
        provider_state.row_count = (
            int(item["row_count"]) if not _is_blank(item["row_count"]) else 0
        )
        states.append(provider_state)
    if provider_policy_failed:
        state.status = "degraded"
        degraded.append("consensus_export")
        failed_providers = {
            str(item["provider"])
            for _, item in health.iterrows()
            if not _consensus_entitlement_usable(item)
            or str(item["status"]) != "available"
            or str(item["provider"]) not in _CONSENSUS_PROVIDER_ALLOWLIST
        }
        failed_providers.update(missing_health_providers)
        failed_providers.update(unknown_providers)
        snapshots = snapshots[~snapshots["provider"].isin(failed_providers)].copy()
        revisions = revisions[
            ~revisions["provider"].isin(failed_providers)
            & ~revisions["prior_provider"].isin(failed_providers)
        ].copy()
    if usable_provider_count == 0:
        state.status = "unavailable"
        _append_state_error(
            state,
            code="no_usable_provider",
            message="all Task 3 provider health rows are unavailable or degraded",
        )
        degraded.append("consensus_export")
        snapshots = _task3_empty(TASK3_SNAPSHOT_COLUMNS)
        revisions = _task3_empty(TASK3_REVISION_COLUMNS)
    return (
        _sort_frame(snapshots, ["provider", "listing_id", "metric", "fiscal_period", "snapshot_at", "snapshot_id"]),
        _sort_frame(revisions, ["provider", "listing_id", "metric", "fiscal_period", "lookback_days", "revision_id"]),
        states,
        degraded,
        fingerprints,
    )


def _empty_quote_snapshots() -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in QUOTE_SNAPSHOT_COLUMNS})


def _quote_status_path(descriptor: LocalInput) -> Path:
    if descriptor.status_path is not None:
        return Path(descriptor.status_path)
    path = Path(descriptor.path)
    return path.with_name(f"{path.stem}.status.json")


def _quote_vendor_symbols(listing: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    raw = listing.get("vendor_tickers", "")
    if _is_blank(raw):
        return {}
    providers: dict[str, list[str]] = {}
    for token in str(raw).split(";"):
        name, separator, symbol = token.partition(":")
        if separator and name.strip() and symbol.strip():
            providers.setdefault(name.strip().casefold(), []).append(symbol.strip())
    return {key: tuple(dict.fromkeys(values)) for key, values in providers.items()}


def _quote_interval_active(row: Mapping[str, Any], as_of_utc: pd.Timestamp) -> bool:
    point = as_of_utc.tz_convert("UTC").tz_localize(None).normalize()
    start = _timestamp(row.get("active_from"), date_only=True)
    end = _timestamp(row.get("active_to"), date_only=True)
    start_date = pd.NaT if pd.isna(start) else start.tz_localize(None).normalize()
    end_date = pd.NaT if pd.isna(end) else end.tz_localize(None).normalize()
    return (pd.isna(start_date) or point >= start_date) and (pd.isna(end_date) or point < end_date)


def _quote_bool(value: Any) -> bool:
    if _is_blank(value):
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _quote_row_rejection(
    item: Mapping[str, Any],
    listing: Mapping[str, Any] | None,
    entity: Mapping[str, Any] | None,
    *,
    source_id: str,
    as_of_utc: pd.Timestamp,
) -> str | None:
    if listing is None:
        return "unknown listing_id; registry truth is required"
    if entity is None:
        return "listing references an unknown entity_id"
    entity_type = _text(entity.get("entity_type")).lower()
    if entity_type == "private":
        return "private entity has no public quote coverage"
    if _text(entity.get("active_status")).lower() not in {"", "active"}:
        return "entity is archived or inactive"
    if not _quote_interval_active(entity, as_of_utc):
        return "entity is outside its active interval"
    if _text(listing.get("listing_status")).lower() != "active":
        return "listing is archived or inactive"
    if not _quote_interval_active(listing, as_of_utc):
        return "listing is future or outside its active interval"
    if not _quote_bool(listing.get("collection_eligible")):
        return "listing is not collection eligible"
    if _text(listing.get("mapping_status")).lower() != "verified":
        return "listing mapping is not verified"

    supplied_ticker = _text(item.get("canonical_ticker"))
    registry_ticker = _text(listing.get("canonical_ticker"))
    if supplied_ticker and supplied_ticker != registry_ticker:
        return "canonical_ticker does not match listing registry"

    supplied_currency = _text(item.get("currency")).upper()
    registry_currency = _text(listing.get("currency")).upper()
    if supplied_currency and registry_currency and supplied_currency != registry_currency:
        return "currency does not match listing registry"

    vendor_symbols = _quote_vendor_symbols(listing)
    supplied_symbol = _text(item.get("provider_symbol"))
    provider_key = _text(source_id).rsplit(":", 1)[-1].casefold()
    accepted_symbols = vendor_symbols.get(provider_key, ())
    if not accepted_symbols:
        accepted_symbols = tuple(
            symbol
            for symbols in vendor_symbols.values()
            for symbol in symbols
        )
    if supplied_symbol and accepted_symbols and supplied_symbol not in accepted_symbols:
        return "provider_symbol does not match listing registry"
    if supplied_symbol and not accepted_symbols and vendor_symbols:
        return "provider_symbol cannot be derived from listing registry"
    return None


def _read_quote_status(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"quote collection status sidecar is invalid: {exc}"
    if not isinstance(payload, dict) or payload.get("schema") != "quote_collection_status_v1":
        return None, "quote collection status sidecar has an unsupported schema"
    if payload.get("aggregate_status") not in {"available", "partial", "no_records", "unavailable"}:
        return None, "quote collection status sidecar has an invalid aggregate_status"
    diagnostics = payload.get("diagnostics", [])
    if not isinstance(diagnostics, list):
        return None, "quote collection status sidecar diagnostics must be a list"
    for key in ("row_count", "expected_listing_count", "diagnostic_count"):
        if not isinstance(payload.get(key), int) or isinstance(payload.get(key), bool):
            return None, f"quote collection status sidecar has an invalid {key}"
    if int(payload["diagnostic_count"]) != len(diagnostics):
        return None, "quote collection status sidecar diagnostic_count does not match diagnostics"
    if payload["aggregate_status"] in {"unavailable", "no_records"} and payload["row_count"] != 0:
        return None, "quote collection status sidecar reports no rows but row_count is non-zero"
    return payload, None


def _build_quote_snapshots(
    registries: Any,
    inputs: Sequence[LocalInput],
    *,
    as_of_utc: pd.Timestamp,
) -> tuple[pd.DataFrame, list[_SourceState], list[str], dict[str, str]]:
    """Load already-normalized quote snapshots without contacting providers."""

    listing_rows = registries.listings.set_index("listing_id", drop=False).to_dict("index")
    entity_rows = registries.entities.set_index("entity_id", drop=False).to_dict("index")
    rows: list[dict[str, Any]] = []
    states: list[_SourceState] = []
    degraded: list[str] = []
    fingerprints: dict[str, str] = {}

    if not inputs:
        state = _SourceState(
            source_id="quote_snapshots",
            source_kind="market",
            path=None,
            schema_version=QUOTE_SNAPSHOT_SCHEMA_ID,
            required=False,
            pit_class="snapshot_from_delayed_source",
            license_class="personal_use_terms_unverified",
            status="unavailable",
            detail="optional_quote_snapshot_input_not_configured",
        )
        states.append(state)
        return _empty_quote_snapshots(), states, ["quote_snapshots"], fingerprints

    for descriptor_index, descriptor in enumerate(inputs):
        status_path = _quote_status_path(descriptor)
        state, frame, schema_id = _load_optional(
            descriptor,
            "market",
            as_of_utc=as_of_utc,
            execution_evidence=status_path.is_file(),
        )
        states.append(state)
        if frame is None:
            degraded.append(descriptor.source_id)
            continue

        status_payload, status_error = _read_quote_status(status_path)
        if status_path.is_file():
            fingerprints[str(status_path)] = _file_hash(status_path)
            if state.input_sha256:
                state.input_sha256 = _composite_input_hash(
                    {"data": state.input_sha256, "status": fingerprints[str(status_path)]}
                )
        if status_error:
            state.status = "degraded"
            _append_state_error(state, code="quote_status_sidecar_invalid", message=status_error)
            degraded.append(descriptor.source_id)

        parsed_quote = pd.to_datetime(frame["quote_timestamp"], errors="coerce", utc=True)
        parsed_retrieved = pd.to_datetime(frame["retrieved_at_utc"], errors="coerce", utc=True)
        parsed_price = pd.to_numeric(frame["last_price"], errors="coerce")
        invalid_reasons: list[str] = []
        for index, item in frame.iterrows():
            listing_id = str(item.get("listing_id") or "").strip()
            listing = listing_rows.get(listing_id)
            entity = entity_rows.get(str(listing.get("entity_id")) if listing is not None else "")
            quote_timestamp = parsed_quote.loc[index]
            retrieved_at = parsed_retrieved.loc[index]
            price = parsed_price.loc[index]
            rejection = _quote_row_rejection(
                item,
                listing,
                entity,
                source_id=str(item.get("source_id") or descriptor.source_id),
                as_of_utc=as_of_utc,
            )
            if rejection:
                invalid_reasons.append(f"row {index}: {rejection}")
                continue
            if pd.isna(quote_timestamp):
                invalid_reasons.append(f"row {index}: invalid quote_timestamp")
                continue
            if not pd.isna(retrieved_at) and retrieved_at > as_of_utc:
                invalid_reasons.append(f"row {index}: retrieved_at_utc beyond as_of_utc")
                continue
            if not pd.isna(quote_timestamp) and quote_timestamp > as_of_utc:
                invalid_reasons.append(f"row {index}: quote_timestamp beyond as_of_utc")
                continue
            if pd.isna(price) or not math.isfinite(float(price)):
                invalid_reasons.append(f"row {index}: invalid last_price")
                continue

            canonical_ticker = str(listing.get("canonical_ticker") or "").strip()
            vendor_symbols = _quote_vendor_symbols(listing)
            provider_key = _text(item.get("source_id") or descriptor.source_id).rsplit(":", 1)[-1].casefold()
            provider_candidates = vendor_symbols.get(provider_key, ()) or tuple(
                symbol for symbols in vendor_symbols.values() for symbol in symbols
            )
            provider_symbol = _text(item.get("provider_symbol")) or (
                provider_candidates[0] if len(provider_candidates) == 1 else ""
            )
            quote_id = str(item.get("quote_id") or "").strip() or (
                f"quote_{listing_id}_{quote_timestamp.strftime('%Y%m%dT%H%M%S')}_"
                f"{descriptor.source_id}"
            )
            raw_pit = str(item.get("pit_class") or descriptor.pit_class).strip()
            raw_license = str(item.get("source_license_class") or descriptor.license_class).strip()
            row = item.to_dict()
            row.update({
                "quote_id": quote_id,
                "listing_id": listing_id,
                "canonical_ticker": canonical_ticker,
                "provider_symbol": provider_symbol,
                "quote_timestamp": quote_timestamp,
                "retrieved_at_utc": retrieved_at,
                "last_price": float(price),
                "currency": str(listing.get("currency") or item.get("currency") or "").strip(),
                "market_status": str(item.get("market_status") or "unknown").strip(),
                "latency_class": "delayed",
                "source_id": str(item.get("source_id") or descriptor.source_id).strip(),
                "source_url": str(item.get("source_url") or descriptor.source_url or "").strip(),
                "pit_class": (
                    "snapshot_from_delayed_source"
                    if raw_pit.lower() in {"snapshot_from_live_source", "live"}
                    else raw_pit
                ),
                "source_license_class": (
                    "personal_use_terms_unverified"
                    if raw_license.lower() in {"public", "public_metadata"}
                    else raw_license
                ),
                "registry_version": str(item.get("registry_version") or listing.get("registry_version") or "v1").strip(),
                "__source_priority": descriptor.source_priority,
                "__source_order": descriptor_index,
            })
            rows.append(row)

        if invalid_reasons:
            state.status = "degraded"
            _append_state_error(
                state,
                code="quote_rows_rejected",
                message=";".join(invalid_reasons[:3]),
            )
            degraded.append(descriptor.source_id)

        if status_payload is not None:
            reported_rows = int(status_payload["row_count"])
            if reported_rows != len(frame):
                state.status = "degraded"
                _append_state_error(
                    state,
                    code="quote_status_row_count_mismatch",
                    message=f"sidecar={reported_rows};input={len(frame)}",
                )
                degraded.append(descriptor.source_id)
            reported_status = str(status_payload["aggregate_status"])
            if reported_status != "available":
                if state.status == "available":
                    state.status = reported_status
                degraded.append(descriptor.source_id)
            sidecar_issues = [str(value) for value in status_payload.get("issues", []) if str(value).strip()]
            sidecar_diag_count = int(status_payload.get("diagnostic_count", 0))
            diagnostic_statuses: dict[str, int] = {}
            for diagnostic in status_payload.get("diagnostics", []):
                if isinstance(diagnostic, dict):
                    status = str(diagnostic.get("status") or "unknown").strip() or "unknown"
                    diagnostic_statuses[status] = diagnostic_statuses.get(status, 0) + 1
            diagnostic_summary = ",".join(
                f"{status}:{count}" for status, count in sorted(diagnostic_statuses.items())
            )
            if sidecar_issues or sidecar_diag_count or diagnostic_summary:
                detail = (
                    f"collector_status={reported_status};diagnostics={sidecar_diag_count}"
                    + (f";diagnostic_statuses={diagnostic_summary}" if diagnostic_summary else "")
                    + (f";issues={' | '.join(sidecar_issues[:3])}" if sidecar_issues else "")
                )
                state.detail = f"{state.detail}; {detail}" if state.detail else detail

    if not rows:
        for state in states:
            if state.status == "available":
                state.status = "no_records"
                _append_state_error(
                    state,
                    code="empty_quote_output",
                    message="quote input contains no valid rows",
                )
        return _empty_quote_snapshots(), states, sorted(set(degraded)), fingerprints

    frame = pd.DataFrame(rows)
    before_dedupe = len(frame)
    frame = frame.sort_values(
        ["listing_id", "quote_timestamp", "retrieved_at_utc", "__source_priority", "__source_order", "quote_id"],
        ascending=[True, True, True, False, False, True],
        na_position="first",
        kind="mergesort",
    ).drop_duplicates(subset=["listing_id"], keep="last")
    if len(frame) < before_dedupe:
        for state in states:
            if state.status == "available":
                state.detail = (
                    f"{state.detail}; duplicate_latest_quote_rows_dropped="
                    f"{before_dedupe - len(frame)}"
                ).strip("; ")
    return _sort_frame(frame.loc[:, QUOTE_SNAPSHOT_COLUMNS], ["listing_id"]), states, sorted(set(degraded)), fingerprints


def _expected_health_states(config: BuildConfig, existing: Sequence[_SourceState]) -> list[_SourceState]:
    present = {state.source_id for state in existing}
    all_inputs: list[tuple[LocalInput, str]] = [
        *((descriptor, "macro") for descriptor in config.macro_inputs),
        *((descriptor, "news") for descriptor in config.news_inputs),
        *((descriptor, "filing") for descriptor in config.filing_inputs),
        *((descriptor, "official_filing") for descriptor in config.official_filing_inputs),
        *((descriptor, "earnings") for descriptor in config.earnings_inputs),
        *((descriptor, "market") for descriptor in config.quote_inputs),
    ]
    states = list(existing)
    existing_by_source = {state.source_id: state for state in existing}
    for descriptor, source_kind in all_inputs:
        if descriptor.source_id in existing_by_source:
            continue
        try:
            schema_id = _normalise_schema_id(descriptor.expected_schema)
        except BuildError:
            state = _optional_state(descriptor, source_kind, descriptor.expected_schema)
            state.status = "degraded"
            state.detail = f"unsupported_optional_schema:{descriptor.expected_schema}"
            if Path(descriptor.path).is_file():
                state.input_sha256 = _file_hash(Path(descriptor.path))
            states.append(state)
            continue
        state = _optional_state(descriptor, source_kind, schema_id)
        state.status = "degraded"
        state.detail = "configured_input_not_used_by_v1_adapter"
        matching = [item for item in existing if item.source_id == descriptor.source_id]
        if matching:
            source_state = matching[0]
            state.status = source_state.status
            state.row_count = source_state.row_count
            state.input_sha256 = source_state.input_sha256
            state.detail = source_state.detail
        states.append(state)

    for source_id, kind, schema_id, geography in _EXPECTED_OPTIONAL_SOURCES:
        if source_id in present:
            continue
        matching_descriptors: list[LocalInput] = []
        for descriptor, source_kind in all_inputs:
            try:
                descriptor_schema = _normalise_schema_id(descriptor.expected_schema)
            except BuildError:
                continue
            if descriptor_schema == schema_id:
                matching_descriptors.append(descriptor)
        if matching_descriptors:
            descriptor = matching_descriptors[0]
            state = _SourceState(
                source_id=source_id,
                source_kind=kind,
                path=descriptor.path,
                schema_version=schema_id,
                required=descriptor.required,
                pit_class=descriptor.pit_class,
                license_class=descriptor.license_class,
                cadence=descriptor.cadence,
                source_url=descriptor.source_url,
                detail=f"configured_as_{descriptor.source_id}",
            )
            state.status = "available" if any(item.source_id == descriptor.source_id and item.status == "available" for item in existing) else "degraded"
            state.row_count = next((item.row_count for item in existing if item.source_id == descriptor.source_id), 0)
            state.input_sha256 = next((item.input_sha256 for item in existing if item.source_id == descriptor.source_id), None)
            states.append(state)
        else:
            state = _SourceState(
                source_id=source_id,
                source_kind=kind,
                path=None,
                schema_version=schema_id,
                required=False,
                pit_class="snapshot_from_live_source",
                license_class="official_public",
                missing_geographies=geography,
                detail="optional_source_not_configured",
            )
            states.append(state)
    return states


def _unconfigured_optional_ids(config: BuildConfig) -> list[str]:
    configured_by_kind: dict[str, set[str]] = {
        "macro": set(), "news": set(), "filing": set(),
        "official_filing": set(), "earnings": set(), "market": set(),
    }
    for source_kind, descriptors in (
        ("macro", config.macro_inputs),
        ("news", config.news_inputs),
        ("filing", config.filing_inputs),
        ("official_filing", config.official_filing_inputs),
        ("earnings", config.earnings_inputs),
        ("market", config.quote_inputs),
    ):
        for descriptor in descriptors:
            try:
                configured_by_kind[source_kind].add(_normalise_schema_id(descriptor.expected_schema))
            except BuildError:
                continue
    missing: list[str] = []
    for source_id, source_kind, schema_id, _ in _EXPECTED_OPTIONAL_SOURCES:
        if source_id == "consensus_export":
            continue
        if schema_id not in configured_by_kind[source_kind]:
            missing.append(source_id)
    if config.consensus_export_dir is None or not config.consensus_export_dir.is_dir():
        missing.append("consensus_export")
    return missing


def _health_frame(states: Sequence[_SourceState], required_sources: Sequence[_SourceState]) -> pd.DataFrame:
    combined = list(required_sources) + list(states)
    # A source ID can be represented by a configured row and an expected alias;
    # retain the configured row and make the summary alias explicit only when it
    # carries different availability information.
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for state in combined:
        key = (state.source_id, state.source_kind)
        if key in seen:
            continue
        seen.add(key)
        if state.missing_geographies:
            suffix = f"missing_geographies={state.missing_geographies}"
            state.detail = f"{state.detail}; {suffix}" if state.detail else suffix
        rows.append(state.health_row())
    frame = _with_columns(pd.DataFrame(rows), SOURCE_HEALTH_COLUMNS)
    return _sort_frame(frame, ["source_kind", "source_id"])


def _required_health(config: BuildConfig) -> tuple[list[_SourceState], dict[str, str]]:
    states: list[_SourceState] = []
    fingerprints: dict[str, str] = {}
    for root, root_kind, files in [
        (config.registry_root, "registry", REGISTRY_FILES),
        (config.event_root, "events", {"events": "events.csv", "event_links": "event_links.csv", "event_watch_questions": "event_watch_questions.csv"}),
    ]:
        for logical_name, filename in files.items():
            path = root / filename
            if not path.is_file():
                raise BuildError(f"required input missing: {path}")
            digest = _file_hash(path)
            fingerprints[str(path)] = digest
            state = _SourceState(
                source_id=f"{root_kind}:{logical_name}",
                source_kind=root_kind,
                path=path,
                schema_version=f"{root_kind}_v1",
                required=True,
                pit_class="snapshot_from_live_source",
                license_class="internal_research",
                input_sha256=digest,
                status="available",
                detail="validated_required_bundle",
            )
            states.append(state)
    return states, fingerprints


def _arrow_schema() -> dict[str, pa.Schema]:
    string = pa.string()
    timestamp = pa.timestamp("us", tz="UTC")
    date_type = pa.date32()
    def fields(columns: Sequence[str], overrides: Mapping[str, pa.DataType] = {}) -> pa.Schema:
        return pa.schema([pa.field(column, overrides.get(column, string), nullable=True) for column in columns])

    registry_overrides = {
        "active_from": date_type,
        "active_to": date_type,
        "mapping_verified_at": date_type,
        "collection_eligible": pa.bool_(),
        "primary_listing": pa.bool_(),
    }
    registry_schemas = {
        name: fields(columns, registry_overrides) for name, columns in REGISTRY_OUTPUT_COLUMNS.items()
    }
    event_schemas = {
        "events": fields(
            EVENT_OUTPUT_COLUMNS,
            {
                "observation_version": pa.int64(),
                "confidence": pa.float64(),
                "starts_at": timestamp,
                "ends_at": timestamp,
                "source_published_at": timestamp,
                "first_observed_at": timestamp,
                "last_verified_at": timestamp,
                "review_by": date_type,
            },
        ),
        "event_links": fields(
            EVENT_LINK_COLUMNS,
            {"automated": pa.bool_(), "active_from": date_type, "active_to": date_type},
        ),
        "event_watch_questions": fields(EVENT_WATCH_QUESTION_COLUMNS),
    }
    macro_schema = fields(
        MACRO_OUTPUT_COLUMNS,
        {
            "observation_date": date_type,
            "release_at": timestamp,
            "first_observed_at": timestamp,
            "source_published_at": timestamp,
            "retrieved_at_utc": timestamp,
            "is_provisional": pa.bool_(),
        },
    )
    news_schema = fields(
        NEWS_FILINGS_COLUMNS,
        {"published_at": timestamp, "first_observed_at": timestamp},
    )
    official_filings_schema = fields(
        OFFICIAL_FILINGS_COLUMNS,
        {
            "published_at": timestamp,
            "accepted_at": timestamp,
            "scheduled_date": date_type,
            "retrieved_at_utc": timestamp,
            "reporting_period_start": date_type,
            "reporting_period_end": date_type,
        },
    )
    earnings_calendar_schema = fields(
        EARNINGS_CALENDAR_COLUMNS,
        {
            "period_start": date_type,
            "period_end": date_type,
            "event_date": date_type,
            "published_at": timestamp,
            "retrieved_at_utc": timestamp,
        },
    )
    earnings_actuals_schema = fields(
        EARNINGS_ACTUALS_COLUMNS,
        {
            "version": pa.int64(),
            "period_start": date_type,
            "period_end": date_type,
            "reported_value": pa.float64(),
            "normalized_value": pa.float64(),
            "filing_at": timestamp,
            "published_at": timestamp,
            "retrieved_at_utc": timestamp,
            "is_restatement": pa.bool_(),
        },
    )
    health_schema = fields(
        SOURCE_HEALTH_COLUMNS,
        {
            "required": pa.bool_(),
            "row_count": pa.int64(),
            "first_observation_at": timestamp,
            "latest_observation_at": timestamp,
            "source_latest_at": timestamp,
            "retrieved_at_utc": timestamp,
        },
    )
    return {
        **{f"{name}.parquet": schema for name, schema in registry_schemas.items()},
        "events.parquet": event_schemas["events"],
        "event_entity_links.parquet": event_schemas["event_links"],
        "event_basket_links.parquet": event_schemas["event_links"],
        "event_watch_questions.parquet": event_schemas["event_watch_questions"],
        "macro_observations.parquet": macro_schema,
        "consensus_snapshots.parquet": TASK3_SNAPSHOT_ARROW_SCHEMA,
        "consensus_revisions.parquet": TASK3_REVISION_ARROW_SCHEMA,
        "quote_snapshots.parquet": QUOTE_SNAPSHOT_ARROW_SCHEMA,
        "news_filings.parquet": news_schema,
        "official_filings.parquet": official_filings_schema,
        "earnings_calendar.parquet": earnings_calendar_schema,
        "earnings_actuals.parquet": earnings_actuals_schema,
        "source_health.parquet": health_schema,
    }


def _prepare_for_arrow(frame: pd.DataFrame, schema: pa.Schema) -> pd.DataFrame:
    output = _with_columns(frame, schema.names)
    for field in schema:
        column = field.name
        dtype = field.type
        if pa.types.is_string(dtype):
            output[column] = output[column].map(lambda value: None if _is_blank(value) else str(value))
        elif pa.types.is_timestamp(dtype):
            output[column] = pd.to_datetime(output[column], errors="coerce", utc=True)
        elif pa.types.is_date32(dtype):
            parsed = pd.to_datetime(output[column], errors="coerce", utc=True)
            output[column] = parsed.dt.tz_localize(None).dt.normalize()
        elif pa.types.is_boolean(dtype):
            output[column] = output[column].map(
                lambda value: pd.NA if _is_blank(value) else bool(value) if isinstance(value, (bool, int)) else str(value).lower() in {"true", "1", "yes"}
            ).astype("boolean")
        elif pa.types.is_integer(dtype):
            output[column] = pd.to_numeric(output[column], errors="coerce").astype("Int64")
        elif pa.types.is_floating(dtype):
            output[column] = pd.to_numeric(output[column], errors="coerce").astype("Float64")
    return output[list(schema.names)]


def _write_parquet(path: Path, frame: pd.DataFrame, schema: pa.Schema) -> None:
    prepared = _prepare_for_arrow(frame, schema)
    table = pa.Table.from_pandas(prepared, schema=schema, preserve_index=False, safe=False)
    pq.write_table(table, path, compression="snappy", coerce_timestamps="us", allow_truncated_timestamps=True)


def _artifact_record(
    path: Path,
    *,
    name: str,
    row_count: int,
    schema_version: str,
    source_ids: Sequence[str],
    status: str = "available",
    sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "relative_path": name,
        "sha256": sha256 if sha256 is not None else _file_hash(path),
        "row_count": row_count,
        "byte_size": path.stat().st_size,
        "schema_version": schema_version,
        "source_ids": sorted(set(source_ids)),
        "status": status,
    }


def _artifact_status(
    source_ids: Sequence[str],
    states_by_id: Mapping[str, _SourceState],
    *,
    usable_statuses: frozenset[str] = STRICT_USABLE_STATUSES,
) -> str:
    contributing = [states_by_id[source_id] for source_id in source_ids if source_id in states_by_id]
    if not contributing:
        return "unavailable"
    if all(state.status in usable_statuses for state in contributing):
        return "available"
    if all(state.status == "unavailable" for state in contributing):
        return "unavailable"
    return "degraded"


def _validate_output_frames(frames: Mapping[str, pd.DataFrame]) -> None:
    schemas = _arrow_schema()
    for name, frame in frames.items():
        if name not in schemas:
            continue
        if list(frame.columns) != list(schemas[name].names):
            raise BuildError(f"output schema drift for {name}")


def _validate_written_generation(
    generation: Path,
    manifest: BuildManifest,
    *,
    expected_generation_id: str | None = None,
) -> None:
    """Validate every generation artifact before it can become CURRENT."""

    if generation.is_symlink() or not generation.is_dir():
        raise BuildError("generation must be a regular directory")
    entries = list(generation.iterdir())
    if set(path.name for path in entries) != set(ARTIFACT_NAMES):
        raise BuildError(
            f"generation does not contain exactly the {len(ARTIFACT_NAMES)} Control Tower artifacts"
        )
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise BuildError("generation artifacts must be regular non-symlink files")
    if expected_generation_id is not None:
        if manifest.generation_id != expected_generation_id:
            raise BuildError("manifest generation_id does not match publication generation")
        if manifest.current_pointer != _generation_relative_path(expected_generation_id):
            raise BuildError("manifest current_pointer does not match publication namespace")
    schemas = _arrow_schema()
    for name in ARTIFACT_NAMES:
        path = generation / name
        record = manifest.artifacts.get(name)
        if record is None:
            raise BuildError(f"manifest missing artifact record: {name}")
        if not path.is_file():
            raise BuildError(f"generation artifact missing: {path}")
        if int(record["byte_size"]) != path.stat().st_size:
            raise BuildError(f"manifest byte_size mismatch: {name}")
        if name == "build_manifest.json":
            continue
        if record["sha256"] != _file_hash(path):
            raise BuildError(f"manifest sha256 mismatch: {name}")
        table_schema = pq.read_schema(path)
        if table_schema != schemas[name]:
            raise BuildError(f"physical Parquet schema mismatch: {name}")
        if int(record["row_count"]) != pq.read_metadata(path).num_rows:
            raise BuildError(f"manifest row_count mismatch: {name}")
    manifest_path = generation / "build_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if int(payload["artifacts"]["build_manifest.json"]["row_count"]) != 1:
        raise BuildError("manifest row_count must be 1")
    if payload["artifacts"]["build_manifest.json"]["byte_size"] != manifest_path.stat().st_size:
        raise BuildError("manifest byte_size mismatch: build_manifest.json")
    if payload["artifacts"]["build_manifest.json"]["sha256"] != manifest.artifacts["build_manifest.json"]["sha256"]:
        raise BuildError("manifest in-memory/file artifact record mismatch")


def _safe_generation_id(build_id: str, input_fingerprints: Mapping[str, str]) -> str:
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-", build_id).strip(".-") or "build"
    digest = _stable_hash(build_id, *[f"{key}={input_fingerprints[key]}" for key in sorted(input_fingerprints)])[:16]
    return f"{readable}-{digest}"


def _generation_relative_path(generation_id: str) -> str:
    if not generation_id or generation_id in {".", ".."} or "/" in generation_id or "\\" in generation_id:
        raise BuildError(f"unsafe generation id: {generation_id!r}")
    return f"{GENERATIONS_DIR_NAME}/{generation_id}"


def _validate_current_pointer(output_dir: Path, pointer_value: str) -> Path:
    value = pointer_value.strip()
    pointer = PurePosixPath(value)
    if not value or pointer.is_absolute() or "\\" in value or any(part in {"", ".", ".."} for part in pointer.parts):
        raise BuildError("CURRENT pointer must be a safe relative generation path")
    if len(pointer.parts) != 2 or pointer.parts[0] != GENERATIONS_DIR_NAME:
        raise BuildError("CURRENT pointer must target generations/<generation_id>")
    generation = output_dir / Path(*pointer.parts)
    if generation.is_symlink():
        raise BuildError("CURRENT target generation must not be a symlink")
    try:
        generation.resolve().relative_to(output_dir.resolve())
    except ValueError as exc:
        raise BuildError("CURRENT pointer escapes publication root") from exc
    if not generation.is_dir():
        raise BuildError(f"CURRENT generation does not exist: {value}")
    entries = list(generation.iterdir())
    if set(path.name for path in entries) != set(ARTIFACT_NAMES):
        raise BuildError("CURRENT target must contain exactly the 16 artifacts")
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise BuildError("CURRENT target artifacts must be regular non-symlink files")
    return generation


def _validated_current_lineage(
    output_dir: Path,
    *,
    as_of_utc: pd.Timestamp,
) -> tuple[str | None, str | None]:
    """Read the selected CURRENT manifest without discovering generations."""

    root = Path(output_dir)
    pointer = root / CURRENT_POINTER_NAME
    if not pointer.exists() and not pointer.is_symlink():
        return None, None
    if pointer.is_symlink() or not pointer.is_file():
        raise BuildError("existing CURRENT must be a regular file")
    pointer_value = pointer.read_text(encoding="utf-8").strip()
    generation = _validate_current_pointer(root, pointer_value)
    try:
        payload = json.loads(
            (generation / "build_manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildError("CURRENT selected generation has an invalid manifest") from exc
    generation_id = PurePosixPath(pointer_value).parts[-1]
    if not isinstance(payload, dict):
        raise BuildError("CURRENT selected manifest must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise BuildError("CURRENT selected manifest has an unsupported schema")
    if payload.get("generation_id") != generation_id:
        raise BuildError("CURRENT generation_id does not match manifest")
    if payload.get("current_pointer") != pointer_value:
        raise BuildError("CURRENT pointer does not match manifest namespace")
    if payload.get("status") not in {"success", "degraded"}:
        raise BuildError("CURRENT selected manifest has an invalid status")
    built_at = _timestamp(payload.get("built_at_utc"))
    if pd.isna(built_at):
        raise BuildError("CURRENT selected manifest has an invalid built_at_utc")
    selected_as_of = _timestamp(payload.get("as_of_utc"))
    if pd.isna(selected_as_of):
        raise BuildError("CURRENT selected manifest has an invalid as_of_utc")
    if built_at >= as_of_utc:
        raise BuildError(
            "CURRENT selected manifest built_at_utc must be strictly earlier "
            "than requested as_of_utc"
        )
    previous = payload.get("previous_build_at")
    if previous not in (None, ""):
        previous_timestamp = _timestamp(previous)
        if pd.isna(previous_timestamp):
            raise BuildError("CURRENT selected manifest has an invalid previous_build_at")
        if previous_timestamp >= built_at or previous_timestamp >= selected_as_of:
            raise BuildError(
                "CURRENT selected manifest previous_build_at must be strictly "
                "earlier than built_at_utc and as_of_utc"
            )
    if payload.get("network_policy") != NETWORK_POLICY:
        raise BuildError("CURRENT selected manifest network_policy is not forbidden")
    if not str(payload.get("build_id") or "").strip():
        raise BuildError("CURRENT selected manifest has an invalid build_id")
    if not isinstance(payload.get("degraded_inputs"), list) or not isinstance(
        payload.get("validation_errors"), list
    ):
        raise BuildError("CURRENT selected manifest degraded/validation fields are invalid")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(ARTIFACT_NAMES):
        raise BuildError("CURRENT selected manifest has an invalid artifact set")
    schemas = _arrow_schema()
    for name in ARTIFACT_NAMES:
        record = artifacts.get(name)
        if not isinstance(record, dict):
            raise BuildError(f"CURRENT selected manifest is missing artifact record: {name}")
        path = generation / name
        if path.is_symlink() or not path.is_file():
            raise BuildError(f"CURRENT selected generation artifact is not a regular file: {name}")
        if record.get("name") != name or record.get("relative_path") != name:
            raise BuildError(f"CURRENT selected manifest path record mismatch: {name}")
        if record.get("schema_version") != SCHEMA_VERSION:
            raise BuildError(f"CURRENT selected manifest schema version mismatch: {name}")
        if int(record.get("byte_size", -1)) != path.stat().st_size:
            raise BuildError(f"CURRENT selected manifest byte_size mismatch: {name}")
        if name == "build_manifest.json":
            if record.get("sha256") not in (None, "") or int(record.get("row_count", -1)) != 1:
                raise BuildError("CURRENT selected manifest self-record is invalid")
            continue
        if record.get("status") not in {"available", "degraded", "unavailable"}:
            raise BuildError(f"CURRENT selected manifest artifact status is invalid: {name}")
        if name not in OPTIONAL_ARTIFACT_NAMES and record.get("status") != "available":
            raise BuildError(f"CURRENT selected manifest required artifact is not available: {name}")
        if record.get("sha256") != _file_hash(path):
            raise BuildError(f"CURRENT selected manifest sha256 mismatch: {name}")
        if int(record.get("row_count", -1)) != pq.read_metadata(path).num_rows:
            raise BuildError(f"CURRENT selected manifest row_count mismatch: {name}")
        if pq.read_schema(path) != schemas[name]:
            raise BuildError(f"CURRENT selected manifest schema mismatch: {name}")
    return _iso(built_at), generation_id


def current_generation(output_dir: Path) -> Path:
    """Resolve the validated immutable generation selected by CURRENT."""

    root = Path(output_dir)
    pointer = root / CURRENT_POINTER_NAME
    if pointer.is_symlink() or not pointer.is_file():
        raise BuildError(f"CURRENT pointer missing: {pointer}")
    pointer_value = pointer.read_text(encoding="utf-8")
    generation = _validate_current_pointer(root, pointer_value)
    manifest = json.loads((generation / "build_manifest.json").read_text(encoding="utf-8"))
    relative = pointer_value.strip()
    if manifest.get("generation_id") != PurePosixPath(relative).parts[-1]:
        raise BuildError("CURRENT generation_id does not match manifest")
    if manifest.get("current_pointer") != relative:
        raise BuildError("CURRENT pointer does not match manifest namespace")
    return generation


def catalyst_eligibility(events: pd.DataFrame) -> pd.Series:
    """Expose Task 2's catalyst gate without adding a mart column."""

    return task2_is_catalyst_eligible(events)


def _make_manifest(
    config: BuildConfig,
    frames: Mapping[str, pd.DataFrame],
    staging: Path,
    input_fingerprints: Mapping[str, str],
    degraded_inputs: Sequence[str],
    health: pd.DataFrame,
    source_ids_by_artifact: Mapping[str, Sequence[str]],
    source_states: Sequence[_SourceState],
    validation_errors: Sequence[dict[str, Any]],
    generation_id: str,
    previous_build_at: str | None,
) -> BuildManifest:
    artifacts: dict[str, dict[str, Any]] = {}
    states_by_id = {state.source_id: state for state in source_states}
    for name, frame in frames.items():
        if name == "build_manifest.json":
            continue
        source_ids = source_ids_by_artifact.get(name, ())
        # This required mart reports source states; those row-level states do
        # not describe the availability of the successfully validated mart.
        status = (
            "available"
            if name == "source_health.parquet"
            else _artifact_status(
                source_ids,
                states_by_id,
                usable_statuses=_ARTIFACT_USABLE_STATUSES.get(name, STRICT_USABLE_STATUSES),
            )
        )
        artifacts[name] = _artifact_record(
            staging / name,
            name=name,
            row_count=len(frame),
            schema_version=config.schema_version,
            source_ids=source_ids,
            status=status,
        )
    artifacts["build_manifest.json"] = {
        "name": "build_manifest.json",
        "relative_path": "build_manifest.json",
        "sha256": None,
        "row_count": 1,
        "byte_size": 0,
        "schema_version": config.schema_version,
        "source_ids": [],
        "status": "available",
    }
    counts = health["status"].value_counts(dropna=False).to_dict() if not health.empty else {}
    return BuildManifest(
        schema_version=config.schema_version,
        build_id=config.build_id,
        status="degraded" if degraded_inputs else "success",
        built_at_utc=_iso(config.as_of_utc),
        as_of_utc=_iso(config.as_of_utc),
        previous_build_at=previous_build_at,
        network_policy=config.network_policy,
        input_fingerprints=dict(sorted(input_fingerprints.items())),
        artifacts=artifacts,
        degraded_inputs=sorted(set(degraded_inputs)),
        validation_errors=list(validation_errors),
        source_health_summary={str(key): int(value) for key, value in counts.items()},
        generation_id=generation_id,
        current_pointer=f"{GENERATIONS_DIR_NAME}/{generation_id}",
    )


def _write_manifest(path: Path, manifest: BuildManifest) -> None:
    # The manifest's own hash remains null by design: a self-hash is
    # self-referential. Its byte size is fixed-pointed and checked after write.
    for _ in range(4):
        payload = manifest.to_dict()
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        actual_size = path.stat().st_size
        if manifest.artifacts["build_manifest.json"]["byte_size"] == actual_size:
            return
        manifest.artifacts["build_manifest.json"]["byte_size"] = actual_size
    raise BuildError("manifest byte_size did not converge")


def _commit_generation(
    output_dir: Path,
    staging_generation: Path,
    generation_id: str,
) -> None:
    """Publish one complete immutable generation, then switch CURRENT."""

    generations_dir = output_dir / GENERATIONS_DIR_NAME
    if generations_dir.exists() and (generations_dir.is_symlink() or not generations_dir.is_dir()):
        raise BuildError("generations namespace must be a regular directory")
    generations_dir.mkdir(parents=True, exist_ok=True)
    final_generation = generations_dir / generation_id
    if final_generation.exists():
        raise BuildError(f"immutable generation already exists: {final_generation}")
    os.replace(staging_generation, final_generation)
    pointer_stage = output_dir / f".{CURRENT_POINTER_NAME}.{generation_id}.tmp"
    pointer_stage.write_text(_generation_relative_path(generation_id) + "\n", encoding="utf-8")
    try:
        pointer_value = pointer_stage.read_text(encoding="utf-8")
        pointer = PurePosixPath(pointer_value.strip())
        if pointer.parts[-1] != generation_id:
            raise BuildError("staged CURRENT pointer generation mismatch")
        _validate_current_pointer(output_dir, pointer_value)
        os.replace(pointer_stage, output_dir / CURRENT_POINTER_NAME)
    finally:
        if pointer_stage.exists():
            pointer_stage.unlink()


def build_control_tower_marts(config: BuildConfig) -> BuildManifest:
    """Build and atomically publish the 16 named Control Tower artifacts."""

    if config.network_policy != NETWORK_POLICY:
        raise BuildError("network access is forbidden for the Control Tower builder")
    registries, events = _validate_required_bundles(config)
    _validate_required_optional_inputs(config)
    required_states, input_fingerprints = _required_health(config)

    registry_frames = _task1_frames(registries)
    event_frame = _sort_frame(_with_columns(events.events, EVENT_OUTPUT_COLUMNS), ["event_id"])
    entity_links = events.event_links[events.event_links["target_type"].ne("basket")].copy()
    basket_links = events.event_links[events.event_links["target_type"].eq("basket")].copy()
    link_frames = {
        "event_entity_links.parquet": _sort_frame(_with_columns(entity_links, EVENT_LINK_COLUMNS), ["event_id", "target_type", "target_id", "link_role"]),
        "event_basket_links.parquet": _sort_frame(_with_columns(basket_links, EVENT_LINK_COLUMNS), ["event_id", "target_id", "link_role"]),
    }
    frames: dict[str, pd.DataFrame] = {
        "entities.parquet": registry_frames["entities"],
        "listings.parquet": registry_frames["listings"],
        "baskets.parquet": registry_frames["baskets"],
        "basket_memberships.parquet": registry_frames["basket_memberships"],
        "indices.parquet": registry_frames["indices"],
        "events.parquet": event_frame,
        **link_frames,
        "event_watch_questions.parquet": _sort_frame(_with_columns(events.event_watch_questions, EVENT_WATCH_QUESTION_COLUMNS), ["event_id", "question_id"]),
    }

    macro_frame, macro_states, macro_degraded = _build_macro(
        events, registries, config.macro_inputs, as_of_utc=config.as_of_utc
    )
    consensus_snapshots, consensus_revisions, consensus_states, consensus_degraded, consensus_fingerprints = _build_consensus(config)
    quote_frame, quote_states, quote_degraded, quote_fingerprints = _build_quote_snapshots(
        registries,
        config.quote_inputs,
        as_of_utc=config.as_of_utc,
    )
    news_frame, news_states, news_degraded = _build_news_filings(
        registries,
        config.news_inputs,
        config.filing_inputs,
        as_of_utc=config.as_of_utc,
    )
    official_filings_frame, calendar_frame, official_states, official_degraded = _build_official_filings(
        registries,
        config.official_filing_inputs,
        as_of_utc=config.as_of_utc,
    )
    actuals_frame, actuals_states, actuals_degraded = _build_earnings_actuals(
        registries,
        config.earnings_inputs,
        as_of_utc=config.as_of_utc,
    )
    input_fingerprints.update(consensus_fingerprints)
    input_fingerprints.update(quote_fingerprints)
    frames["macro_observations.parquet"] = macro_frame
    frames["consensus_snapshots.parquet"] = consensus_snapshots
    frames["consensus_revisions.parquet"] = consensus_revisions
    frames["quote_snapshots.parquet"] = quote_frame
    frames["news_filings.parquet"] = news_frame
    frames["official_filings.parquet"] = official_filings_frame
    frames["earnings_calendar.parquet"] = calendar_frame
    frames["earnings_actuals.parquet"] = actuals_frame

    required_row_counts = {
        "registry:entities": len(registry_frames["entities"]),
        "registry:listings": len(registry_frames["listings"]),
        "registry:baskets": len(registry_frames["baskets"]),
        "registry:basket_memberships": len(registry_frames["basket_memberships"]),
        "registry:indices": len(registry_frames["indices"]),
        "events:events": len(event_frame),
        "events:event_links": len(events.event_links),
        "events:event_watch_questions": len(events.event_watch_questions),
    }
    for state in required_states:
        state.row_count = required_row_counts[state.source_id]

    optional_states = _expected_health_states(
        config,
        [
            *macro_states,
            *consensus_states,
            *quote_states,
            *news_states,
            *official_states,
            *actuals_states,
        ],
    )
    for state in optional_states:
        if state.status != "available" and not state.errors:
            _append_state_error(
                state,
                code=("optional_source_unavailable" if state.status == "unavailable" else "optional_source_degraded"),
                message=state.detail or "optional source did not provide usable rows",
            )
    optional_degraded = [
        *macro_degraded,
        *consensus_degraded,
        *quote_degraded,
        *news_degraded,
        *official_degraded,
        *actuals_degraded,
        *_unconfigured_optional_ids(config),
    ]
    non_contributing = CONTRIBUTING_STATUSES | {"not_applicable"}
    state_degraded = [
        state.source_id for state in optional_states if state.status not in non_contributing
    ]
    optional_degraded = sorted(set([*optional_degraded, *state_degraded]))
    if optional_degraded and not config.allow_degraded_optional:
        raise BuildError(
            "optional inputs degraded while allow_degraded_optional=False: "
            + ",".join(sorted(set(optional_degraded)))
        )
    for state in optional_states:
        if state.path is not None and state.path.is_file() and state.input_sha256 is None:
            state.input_sha256 = _file_hash(state.path)
            input_fingerprints[str(state.path)] = state.input_sha256
    health_frame = _health_frame(optional_states, required_states)
    frames["source_health.parquet"] = health_frame

    source_ids_by_artifact = {
        "entities.parquet": ["registry:entities"],
        "listings.parquet": ["registry:listings"],
        "baskets.parquet": ["registry:baskets"],
        "basket_memberships.parquet": ["registry:basket_memberships"],
        "indices.parquet": ["registry:indices"],
        "events.parquet": ["events:events"],
        "event_entity_links.parquet": ["events:event_links"],
        "event_basket_links.parquet": ["events:event_links"],
        "event_watch_questions.parquet": ["events:event_watch_questions"],
        "macro_observations.parquet": ["events:events", *[state.source_id for state in macro_states]],
        "consensus_snapshots.parquet": [state.source_id for state in consensus_states],
        "consensus_revisions.parquet": [state.source_id for state in consensus_states],
        "quote_snapshots.parquet": [state.source_id for state in quote_states],
        "news_filings.parquet": [state.source_id for state in news_states],
        "official_filings.parquet": [state.source_id for state in official_states],
        "earnings_calendar.parquet": [state.source_id for state in official_states],
        "earnings_actuals.parquet": [state.source_id for state in actuals_states],
        "source_health.parquet": [state.source_id for state in [*required_states, *optional_states]],
    }
    _validate_output_frames(frames)

    output_dir = config.output_dir
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_build_at, _previous_generation_id = _validated_current_lineage(
        output_dir,
        as_of_utc=config.as_of_utc,
    )
    if not config.overwrite_existing and (output_dir / CURRENT_POINTER_NAME).exists():
        raise BuildError(
            f"publication already has CURRENT and overwrite_existing=False: {output_dir}"
        )

    generation_id = _safe_generation_id(config.build_id, input_fingerprints)
    existing_current = output_dir / CURRENT_POINTER_NAME
    if existing_current.exists() and (existing_current.is_symlink() or not existing_current.is_file()):
        raise BuildError("existing CURRENT must be a regular file")
    staging_root = Path(tempfile.mkdtemp(prefix=".research-control-tower-", dir=str(output_dir)))
    staging = staging_root / "generation"
    staging.mkdir()
    validation_errors = [
        error
        for state in [*required_states, *optional_states]
        for error in state.errors
    ]
    all_source_states = [*required_states, *optional_states]
    try:
        schemas = _arrow_schema()
        for name, frame in frames.items():
            _write_parquet(staging / name, frame, schemas[name])
        manifest = _make_manifest(
            config,
            frames,
            staging,
            input_fingerprints,
            optional_degraded,
            health_frame,
            source_ids_by_artifact,
            all_source_states,
            validation_errors,
            generation_id,
            previous_build_at,
        )
        _write_manifest(staging / "build_manifest.json", manifest)
        _validate_written_generation(staging, manifest, expected_generation_id=generation_id)
        _commit_generation(output_dir, staging, generation_id)
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)
    return manifest


__all__ = [
    "ARTIFACT_NAMES",
    "BuildConfig",
    "BuildError",
    "BuildManifest",
    "CONTRIBUTING_STATUSES",
    "CURRENT_POINTER_NAME",
    "EARNINGS_ACTUALS_COLUMNS",
    "EARNINGS_ACTUALS_SCHEMA_ID",
    "EARNINGS_CALENDAR_COLUMNS",
    "ECB_FX_SCHEMA_ID",
    "EVENT_LINK_COLUMNS",
    "EVENT_OUTPUT_COLUMNS",
    "EVENT_WATCH_QUESTION_COLUMNS",
    "FILING_SCHEMA_ID",
    "FRED_META_SCHEMA_ID",
    "FRED_OBSERVATIONS_SCHEMA_ID",
    "LocalInput",
    "MACRO_COLLECTOR_SCHEMA_ID",
    "MACRO_EVENTS_SCHEMA_ID",
    "MACRO_OBSERVATIONS_SCHEMA_ID",
    "MACRO_OUTPUT_COLUMNS",
    "MACRO_SOURCE_HEALTH_SCHEMA_ID",
    "NEWS_FILINGS_COLUMNS",
    "NEWS_SCHEMA_ID",
    "OFFICIAL_FILINGS_COLUMNS",
    "OFFICIAL_FILINGS_SCHEMA_ID",
    "OPTIONAL_ARTIFACT_NAMES",
    "QUOTE_SNAPSHOT_COLUMNS",
    "QUOTE_SNAPSHOT_SCHEMA_ID",
    "QUOTE_SNAPSHOT_ARROW_SCHEMA",
    "OFR_META_SCHEMA_ID",
    "OFR_OBSERVATIONS_SCHEMA_ID",
    "REGISTRY_OUTPUT_COLUMNS",
    "SOURCE_HEALTH_COLUMNS",
    "SOURCE_STATE_COLUMNS",
    "SOURCE_STATE_SCHEMA_ID",
    "TAIWAN_REVENUE_SCHEMA_ID",
    "TASK3_REVISION_COLUMNS",
    "TASK3_SNAPSHOT_COLUMNS",
    "TASK3_HEALTH_COLUMNS",
    "build_control_tower_marts",
    "catalyst_eligibility",
    "current_generation",
]
