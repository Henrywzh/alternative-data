from __future__ import annotations

from copy import deepcopy
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import time
import urllib.request

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest


APP_ROOT = Path(__file__).resolve().parents[1] / "apps" / "research-control-tower"


def _columns() -> dict[str, list[str]]:
    return {
        "entities.parquet": [
            "entity_id", "legal_name", "display_name", "country", "sector",
            "industry", "active_status", "active_from", "active_to",
            "registry_version", "source_or_research_note",
        ],
        "listings.parquet": [
            "listing_id", "entity_id", "exchange", "native_ticker",
            "canonical_ticker", "financial_data_security_id",
            "financial_data_issuer_group_id", "mapping_status",
            "mapping_verified_at", "mapping_source_url", "collection_eligible",
            "listing_role", "vendor_tickers", "currency", "primary_listing",
            "active_from", "active_to", "listing_status", "registry_version",
            "source_url", "source_or_research_note",
        ],
        "baskets.parquet": [
            "basket_id", "display_name", "purpose", "active_from", "active_to",
            "registry_version", "source_or_research_note",
        ],
        "basket_memberships.parquet": [
            "entity_id", "basket_id", "membership_tier", "primary_layer",
            "secondary_layers", "active_from", "active_to", "membership_reason",
            "source_or_research_note", "registry_version",
        ],
        "indices.parquet": [
            "index_id", "region", "display_name", "official_code",
            "official_code_namespace", "official_code_provider", "provider_symbol",
            "provider_symbol_namespace", "provider_symbol_provider", "provider",
            "currency", "active_from", "active_to", "registry_version",
            "source_url", "source_or_research_note",
        ],
        "events.parquet": [
            "event_id", "event_key", "observation_version", "scope", "event_type",
            "title", "description", "status", "certainty_class", "importance", "confidence",
            "date_precision", "starts_at", "ends_at", "source_timezone", "source_id",
            "source_url", "source_published_at", "first_observed_at",
            "last_verified_at", "review_by", "supersedes_event_id", "evidence_class",
            "evidence_ref", "reference_period", "previous_value", "previous_vintage",
            "market_consensus", "consensus_source", "own_nowcast", "actual_value",
            "actual_unit", "revised_value", "surprise_value", "surprise_unit",
            "scenario_notes", "expected_metrics", "thesis_implications",
            "registry_version",
        ],
        "event_entity_links.parquet": [
            "event_id", "target_type", "target_id", "link_role", "automated",
            "active_from", "active_to", "link_note", "registry_version",
        ],
        "event_basket_links.parquet": [
            "event_id", "target_type", "target_id", "link_role", "automated",
            "active_from", "active_to", "link_note", "registry_version",
        ],
        "event_watch_questions.parquet": [
            "event_id", "question_id", "question", "question_type", "priority",
            "registry_version",
        ],
        "macro_observations.parquet": [
            "observation_id", "event_id", "source_id", "series_id", "scope",
            "event_type", "metric_name", "reference_period", "observation_date",
            "release_at", "actual_value", "unit", "frequency", "first_observed_at",
            "source_published_at", "retrieved_at_utc", "source_url", "pit_class",
            "source_license_class", "is_provisional", "registry_version",
        ],
        "consensus_snapshots.parquet": [
            "snapshot_id", "provider", "entity_id", "listing_id",
            "financial_data_security_id", "canonical_ticker", "metric",
            "fiscal_period", "fiscal_year", "estimate_period_end", "horizon",
            "snapshot_at", "value", "statistic", "low_value", "high_value",
            "analyst_count", "provider_contributor_count", "currency", "unit",
            "accounting_basis", "provider_asof", "retrieved_at_utc", "source_url",
            "raw_hash", "pit_class", "source_run_id", "calculation_origin",
            "coverage_reason",
        ],
        "consensus_revisions.parquet": [
            "revision_id", "snapshot_id", "provider", "prior_provider", "entity_id",
            "listing_id", "financial_data_security_id", "canonical_ticker", "metric",
            "fiscal_period", "fiscal_year", "estimate_period_end", "horizon",
            "statistic", "current_snapshot_at", "current_value",
            "current_analyst_count", "current_dispersion", "lookback_days",
            "cutoff_at", "prior_snapshot_id", "prior_snapshot_at", "prior_value",
            "prior_provider_asof", "provider_asof", "retrieved_at_utc", "source_url",
            "pit_class", "source_run_id", "prior_analyst_count", "revision_value",
            "revision_pct", "analyst_count_change", "dispersion", "alignment_status",
        ],
        "quote_snapshots.parquet": [
            "quote_id", "listing_id", "canonical_ticker", "provider_symbol",
            "quote_timestamp", "retrieved_at_utc", "last_price", "bid", "ask",
            "day_change_pct", "volume", "currency", "market_status", "latency_class",
            "source_id", "source_url", "pit_class", "source_license_class",
            "registry_version",
        ],
        "news_filings.parquet": [
            "document_id", "document_type", "source_id", "headline", "publisher",
            "published_at", "first_observed_at", "source_url", "language",
            "related_entity_ids", "related_listing_ids", "related_basket_ids",
            "event_class", "importance", "source_quality", "pit_class",
            "source_license_class", "content_hash_if_permitted",
            "derived_summary_if_permitted",
        ],
        "source_health.parquet": [
            "source_id", "input_path", "source_kind", "status", "required",
            "row_count", "first_observation_at", "latest_observation_at",
            "source_latest_at", "retrieved_at_utc", "cadence", "source_url",
            "pit_class", "source_license_class", "entitlement_status",
            "entitlement_evidence", "entitlement_ref", "input_sha256", "schema_version",
            "missing_geographies", "detail",
        ],
    }


def _blank_row(columns: list[str]) -> dict[str, object]:
    return {column: None for column in columns}


def _frame(name: str, rows: list[dict[str, object]]) -> pd.DataFrame:
    columns = _columns()[name]
    return pd.DataFrame([{**_blank_row(columns), **row} for row in rows], columns=columns)


def _typed_frame(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    date_columns = {
        "active_from", "active_to", "mapping_verified_at", "review_by",
        "observation_date", "estimate_period_end",
    }
    timestamp_columns = {
        "starts_at", "ends_at", "source_published_at", "first_observed_at",
        "last_verified_at", "release_at", "retrieved_at_utc", "snapshot_at",
        "provider_asof", "current_snapshot_at",
        "prior_provider_asof", "cutoff_at", "prior_snapshot_at", "published_at",
        "first_observation_at",
        "latest_observation_at", "source_latest_at", "quote_timestamp",
    }
    boolean_columns = {"collection_eligible", "primary_listing", "automated", "is_provisional", "required"}
    integer_columns = {
        "observation_version", "fiscal_year", "analyst_count", "provider_contributor_count",
        "lookback_days", "current_analyst_count", "prior_analyst_count",
        "analyst_count_change", "row_count",
    }
    float_columns = {
        "confidence", "value", "low_value", "high_value", "current_value",
        "current_dispersion", "prior_value", "revision_value", "revision_pct",
        "dispersion", "last_price", "bid", "ask", "day_change_pct", "volume",
    }
    for column in date_columns & set(frame.columns):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.date
    for column in timestamp_columns & set(frame.columns):
        frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)
    for column in boolean_columns & set(frame.columns):
        frame[column] = frame[column].astype("boolean")
    for column in integer_columns & set(frame.columns):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    for column in float_columns & set(frame.columns):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Float64")
    return frame


def _fixture_schema(name: str) -> pa.Schema:
    columns = list(_columns()[name])
    if name == "events.parquet" and "importance" in columns:
        columns.remove("importance")
        columns.insert(9, "importance")
    date_columns = {
        "active_from", "active_to", "mapping_verified_at", "review_by",
        "observation_date", "estimate_period_end",
    }
    timestamp_columns = {
        "starts_at", "ends_at", "source_published_at", "first_observed_at",
        "last_verified_at", "release_at", "retrieved_at_utc", "snapshot_at",
        "provider_asof", "current_snapshot_at",
        "prior_provider_asof", "cutoff_at", "prior_snapshot_at", "published_at",
        "first_observation_at",
        "latest_observation_at", "source_latest_at", "quote_timestamp",
    }
    boolean_columns = {"collection_eligible", "primary_listing", "automated", "is_provisional", "required"}
    integer_columns = {
        "observation_version", "fiscal_year", "analyst_count", "provider_contributor_count",
        "lookback_days", "current_analyst_count", "prior_analyst_count",
        "analyst_count_change", "row_count",
    }
    float_columns = {
        "confidence", "value", "low_value", "high_value", "current_value",
        "current_dispersion", "prior_value", "revision_value", "revision_pct",
        "dispersion", "last_price", "bid", "ask", "day_change_pct", "volume",
    }
    fields = []
    for column in columns:
        if column in date_columns:
            dtype = pa.date32()
        elif column in timestamp_columns:
            dtype = pa.timestamp("us", tz="UTC")
        elif column in boolean_columns:
            dtype = pa.bool_()
        elif column in integer_columns:
            dtype = pa.int64()
        elif column in float_columns:
            dtype = pa.float64()
        else:
            dtype = pa.string()
        fields.append(pa.field(column, dtype, nullable=True))
    return pa.schema(fields)


def _write_manifest(root: Path, manifest: dict[str, object]) -> None:
    manifest_path = root / "build_manifest.json"
    for _ in range(8):
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        size = manifest_path.stat().st_size
        if manifest["artifacts"]["build_manifest.json"]["byte_size"] == size:
            return
        manifest["artifacts"]["build_manifest.json"]["byte_size"] = size
    raise AssertionError("manifest size did not converge")


def _write_named_manifest(root: Path, filename: str, manifest: dict[str, object]) -> None:
    manifest_path = root / filename
    record = manifest["artifacts"][filename]
    for _ in range(8):
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        size = manifest_path.stat().st_size
        if record["byte_size"] == size:
            return
        record["byte_size"] = size
    raise AssertionError("named manifest size did not converge")


def _manifest_for(root: Path, *, status: str = "success") -> dict[str, object]:
    artifacts: dict[str, dict[str, object]] = {}
    for name in (*_columns().keys(), "build_manifest.json"):
        path = root / name
        artifacts[name] = {
            "name": name,
            "relative_path": name,
            "sha256": None if name == "build_manifest.json" else hashlib.sha256(path.read_bytes()).hexdigest(),
            "row_count": 1 if name == "build_manifest.json" else len(pd.read_parquet(path)),
            "byte_size": 0 if name == "build_manifest.json" else path.stat().st_size,
            "schema_version": "control_tower_marts_v1",
            "source_ids": [],
            "status": "available",
        }
    return {
        "schema_version": "control_tower_marts_v1",
        "build_id": "fixture-build-001",
        "status": status,
        "built_at_utc": "2026-08-13T12:00:00Z",
        "as_of_utc": "2026-08-13T12:00:00Z",
        "previous_build_at": None,
        "network_policy": "forbidden",
        "input_fingerprints": {},
        "artifacts": artifacts,
        "degraded_inputs": [],
        "validation_errors": [],
        "source_health_summary": {"available": 1, "unavailable": 0},
    }


def _write_bundle(root: Path) -> None:
    root.mkdir()
    frames: dict[str, pd.DataFrame] = {}

    frames["entities.parquet"] = _frame("entities.parquet", [
        {"entity_id": "E1", "legal_name": "Entity One", "display_name": "One", "country": "US", "sector": "Technology", "industry": "Hardware", "active_status": "active", "active_from": "2020-01-01", "registry_version": "v1"},
        {"entity_id": "E2", "legal_name": "Entity Two", "display_name": "Two", "country": "JP", "sector": "Technology", "industry": "Software", "active_status": "active", "active_from": "2020-01-01", "registry_version": "v1"},
    ])
    frames["listings.parquet"] = _frame("listings.parquet", [
        {"listing_id": "L1", "entity_id": "E1", "exchange": "NYSE", "native_ticker": "ONE", "canonical_ticker": "ONE", "mapping_status": "verified", "collection_eligible": True, "listing_role": "primary", "currency": "USD", "primary_listing": True, "active_from": "2020-01-01", "listing_status": "active", "registry_version": "v1"},
        {"listing_id": "L2", "entity_id": "E1", "exchange": "NASDAQ", "native_ticker": "ONE.A", "canonical_ticker": "ONE", "mapping_status": "verified", "collection_eligible": True, "listing_role": "secondary", "currency": "USD", "primary_listing": False, "active_from": "2020-01-01", "listing_status": "active", "registry_version": "v1"},
        {"listing_id": "L3", "entity_id": "E2", "exchange": "TSE", "native_ticker": "TWO", "canonical_ticker": "TWO", "mapping_status": "verified", "collection_eligible": True, "listing_role": "primary", "currency": "JPY", "primary_listing": True, "active_from": "2020-01-01", "listing_status": "active", "registry_version": "v1"},
    ])
    frames["baskets.parquet"] = _frame("baskets.parquet", [
        {"basket_id": "BASKET_A", "display_name": "Basket A", "purpose": "core", "active_from": "2020-01-01", "registry_version": "v1"},
        {"basket_id": "BASKET_B", "display_name": "Basket B", "purpose": "read-through", "active_from": "2020-01-01", "registry_version": "v1"},
    ])
    frames["basket_memberships.parquet"] = _frame("basket_memberships.parquet", [
        {"entity_id": "E1", "basket_id": "BASKET_A", "membership_tier": "core", "primary_layer": "core", "active_from": "2020-01-01", "membership_reason": "fixture", "registry_version": "v1"},
        {"entity_id": "E2", "basket_id": "BASKET_B", "membership_tier": "read_through", "primary_layer": "read_through", "active_from": "2020-01-01", "membership_reason": "fixture", "registry_version": "v1"},
    ])
    frames["indices.parquet"] = _frame("indices.parquet", [
        {"index_id": "IDX1", "region": "US", "display_name": "Index One", "official_code": "IDX1", "official_code_namespace": "fixture", "official_code_provider": "fixture", "provider_symbol": "IDX1", "provider_symbol_namespace": "fixture", "provider_symbol_provider": "fixture", "provider": "fixture", "currency": "USD", "active_from": "2020-01-01", "registry_version": "v1"},
    ])

    event_rows = [
        {"event_id": "EV_HARD", "event_key": "EV_HARD", "observation_version": 1, "scope": "company", "event_type": "earnings", "title": "Hard event", "description": "fixture", "status": "confirmed", "certainty_class": "hard", "confidence": 0.95, "date_precision": "day", "starts_at": "2026-08-15T00:00:00Z", "ends_at": "2026-08-15T00:00:00Z", "source_timezone": "UTC", "source_id": "fixture", "source_url": "https://example.test/hard", "first_observed_at": "2026-08-01T00:00:00Z", "evidence_class": "official_external", "evidence_ref": "https://example.test/hard", "registry_version": "v1"},
        {"event_id": "EV_ACTIVE", "event_key": "EV_ACTIVE", "observation_version": 1, "scope": "basket", "event_type": "thesis_checkpoint", "title": "Active range", "description": "fixture", "status": "active", "certainty_class": "thesis_checkpoint", "confidence": 0.75, "date_precision": "month", "starts_at": "2026-08-10T00:00:00Z", "ends_at": "2026-12-01T00:00:00Z", "source_timezone": "UTC", "source_id": "fixture", "first_observed_at": "2026-08-01T00:00:00Z", "evidence_class": "internal_research", "evidence_ref": "docs/superpowers/specs/2026-08-13-research-control-tower-design.md#5.2-event-classes", "registry_version": "v1"},
        {"event_id": "EV_PAST", "event_key": "EV_PAST", "observation_version": 1, "scope": "macro", "event_type": "observation", "title": "Past event", "description": "fixture", "status": "observed", "certainty_class": "observed", "confidence": 0.5, "date_precision": "day", "starts_at": "2026-07-01T00:00:00Z", "ends_at": "2026-07-01T00:00:00Z", "source_timezone": "UTC", "source_id": "fixture", "first_observed_at": "2026-07-01T00:00:00Z", "evidence_class": "source_observation", "evidence_ref": "source:fixture", "registry_version": "v1"},
        {"event_id": "EV_FAR", "event_key": "EV_FAR", "observation_version": 1, "scope": "policy", "event_type": "policy", "title": "Far event", "description": "fixture", "status": "scheduled", "certainty_class": "provisional", "confidence": 0.6, "date_precision": "day", "starts_at": "2027-01-01T00:00:00Z", "ends_at": "2027-01-01T00:00:00Z", "source_timezone": "UTC", "source_id": "fixture", "source_url": "https://example.test/far", "first_observed_at": "2026-08-01T00:00:00Z", "evidence_class": "official_external", "evidence_ref": "https://example.test/far", "registry_version": "v1"},
        {"event_id": "EV_GAP", "event_key": "EV_GAP", "observation_version": 1, "scope": "index", "event_type": "coverage_gap", "title": "Gap", "description": "fixture", "status": "unavailable", "certainty_class": "observed", "date_precision": "day", "source_timezone": "UTC", "source_id": "fixture", "evidence_class": "source_observation", "evidence_ref": "source:fixture", "registry_version": "v1"},
        {"event_id": "EV_TIE_B", "event_key": "EV_TIE_B", "observation_version": 1, "scope": "company", "event_type": "earnings", "title": "Tie B", "description": "fixture", "status": "scheduled", "certainty_class": "observed", "confidence": 0.65, "date_precision": "day", "starts_at": "2026-08-20T00:00:00Z", "ends_at": "2026-08-20T00:00:00Z", "source_timezone": "UTC", "source_id": "fixture", "first_observed_at": "2026-08-01T00:00:00Z", "evidence_class": "source_observation", "evidence_ref": "source:fixture", "registry_version": "v1"},
        {"event_id": "EV_TIE_A", "event_key": "EV_TIE_A", "observation_version": 1, "scope": "company", "event_type": "earnings", "title": "Tie A", "description": "fixture", "status": "scheduled", "certainty_class": "observed", "confidence": 0.65, "date_precision": "day", "starts_at": "2026-08-20T00:00:00Z", "ends_at": "2026-08-20T00:00:00Z", "source_timezone": "UTC", "source_id": "fixture", "first_observed_at": "2026-08-01T00:00:00Z", "evidence_class": "source_observation", "evidence_ref": "source:fixture", "registry_version": "v1"},
    ]
    event_frame = _frame("events.parquet", event_rows)
    event_frame["importance"] = ["high", "medium", "low", None, "high", "low", "medium"]
    frames["events.parquet"] = event_frame
    frames["event_entity_links.parquet"] = _frame("event_entity_links.parquet", [
        {"event_id": "EV_HARD", "target_type": "entity", "target_id": "E1", "link_role": "primary", "automated": False, "active_from": "2020-01-01", "link_note": "fixture", "registry_version": "v1"},
        {"event_id": "EV_HARD", "target_type": "listing", "target_id": "L2", "link_role": "affected", "automated": False, "active_from": "2020-01-01", "link_note": "fixture", "registry_version": "v1"},
        {"event_id": "EV_HARD", "target_type": "index", "target_id": "IDX1", "link_role": "context", "automated": False, "active_from": "2020-01-01", "link_note": "fixture", "registry_version": "v1"},
        {"event_id": "EV_HARD", "target_type": "entity", "target_id": "E1", "link_role": "watch_only", "automated": False, "active_from": "2020-01-01", "link_note": "duplicate", "registry_version": "v1"},
        {"event_id": "EV_ACTIVE", "target_type": "entity", "target_id": "E2", "link_role": "primary", "automated": False, "active_from": "2020-01-01", "link_note": "fixture", "registry_version": "v1"},
    ])
    frames["event_basket_links.parquet"] = _frame("event_basket_links.parquet", [
        {"event_id": "EV_HARD", "target_type": "basket", "target_id": "BASKET_A", "link_role": "primary", "automated": False, "active_from": "2020-01-01", "link_note": "fixture", "registry_version": "v1"},
        {"event_id": "EV_HARD", "target_type": "basket", "target_id": "BASKET_B", "link_role": "affected", "automated": False, "active_from": "2020-01-01", "link_note": "fixture", "registry_version": "v1"},
        {"event_id": "EV_HARD", "target_type": "basket", "target_id": "BASKET_A", "link_role": "context", "automated": False, "active_from": "2020-01-01", "link_note": "duplicate", "registry_version": "v1"},
        {"event_id": "EV_ACTIVE", "target_type": "basket", "target_id": "BASKET_B", "link_role": "primary", "automated": False, "active_from": "2020-01-01", "link_note": "fixture", "registry_version": "v1"},
    ])
    frames["event_watch_questions.parquet"] = _frame("event_watch_questions.parquet", [
        {"event_id": "EV_ACTIVE", "question_id": "Q1", "question": "What changes?", "question_type": "invalidation", "priority": "high", "registry_version": "v1"},
    ])
    frames["macro_observations.parquet"] = _frame("macro_observations.parquet", [
        {"observation_id": "M1", "event_id": "EV_PAST", "source_id": "fixture", "series_id": "SERIES", "scope": "macro", "event_type": "observation", "metric_name": "metric", "reference_period": "2026-06", "observation_date": "2026-07-01", "actual_value": "1", "unit": "index", "frequency": "monthly", "first_observed_at": "2026-07-01T00:00:00Z", "retrieved_at_utc": "2026-07-02T00:00:00Z", "source_url": "https://example.test/macro", "pit_class": "snapshot", "source_license_class": "public", "is_provisional": False, "registry_version": "v1"},
    ])
    frames["consensus_snapshots.parquet"] = _frame("consensus_snapshots.parquet", [
        {"snapshot_id": "S1", "provider": "fixture", "entity_id": "E1", "listing_id": "L1", "financial_data_security_id": "SEC1", "canonical_ticker": "ONE", "metric": "eps", "fiscal_period": "FY2026", "fiscal_year": 2026, "estimate_period_end": "2026-12-31", "horizon": "FY", "snapshot_at": "2026-08-13T00:00:00Z", "value": 1.0, "statistic": "mean", "analyst_count": 4, "provider_contributor_count": 3, "currency": "USD", "unit": "per_share", "accounting_basis": "GAAP", "provider_asof": "2026-08-12T00:00:00Z", "retrieved_at_utc": "2026-08-13T00:00:00Z", "source_url": "https://example.test/consensus", "raw_hash": "raw-s1", "pit_class": "snapshot", "source_run_id": "run-001", "calculation_origin": "fixture", "coverage_reason": None},
    ])
    frames["consensus_revisions.parquet"] = _frame("consensus_revisions.parquet", [
        {"revision_id": "R1", "snapshot_id": "S1", "provider": "fixture", "prior_provider": "fixture", "entity_id": "E1", "listing_id": "L1", "financial_data_security_id": "SEC1", "canonical_ticker": "ONE", "metric": "eps", "fiscal_period": "FY2026", "fiscal_year": 2026, "estimate_period_end": "2026-12-31", "horizon": "FY", "statistic": "mean", "current_snapshot_at": "2026-08-13T00:00:00Z", "current_value": 1.0, "current_analyst_count": 4, "current_dispersion": 0.1, "lookback_days": 7, "cutoff_at": "2026-08-06T00:00:00Z", "prior_snapshot_id": "S0", "prior_snapshot_at": "2026-08-06T00:00:00Z", "prior_value": 0.9, "prior_provider_asof": "2026-08-05T00:00:00Z", "provider_asof": "2026-08-12T00:00:00Z", "retrieved_at_utc": "2026-08-13T00:00:00Z", "source_url": "https://example.test/consensus", "pit_class": "snapshot", "source_run_id": "run-001", "prior_analyst_count": 3, "revision_value": 0.1, "revision_pct": 0.111111, "analyst_count_change": 1, "dispersion": 0.1, "alignment_status": "aligned"},
    ])
    frames["quote_snapshots.parquet"] = _frame("quote_snapshots.parquet", [])
    frames["news_filings.parquet"] = _frame("news_filings.parquet", [])
    frames["source_health.parquet"] = _frame("source_health.parquet", [
        {"source_id": "fixture", "input_path": "fixture", "source_kind": "fixture", "status": "available", "required": True, "row_count": 1, "schema_version": "fixture_v1", "detail": "fixture"},
        {"source_id": "consensus", "input_path": "", "source_kind": "consensus", "status": "unavailable", "required": False, "row_count": 0, "schema_version": "fixture_v1", "detail": "optional fixture"},
    ])

    for name, frame in frames.items():
        frame = _typed_frame(name, frame)
        table = pa.Table.from_pandas(frame, schema=_fixture_schema(name), preserve_index=False, safe=False)
        pq.write_table(table, root / name)
    _write_manifest(root, _manifest_for(root))


def _publication_from_bundle(tmp_path: Path, bundle: Path, target: str = "generations/gen-001") -> Path:
    publication = tmp_path / "publication"
    generation = publication / target
    generation.parent.mkdir(parents=True)
    shutil.copytree(bundle, generation)
    manifest = json.loads((generation / "build_manifest.json").read_text(encoding="utf-8"))
    manifest["generation_id"] = Path(target).name
    manifest["current_pointer"] = target
    _write_manifest(generation, manifest)
    (publication / "CURRENT").write_text(target + "\n", encoding="utf-8")
    return publication


@pytest.fixture(autouse=True)
def _control_tower_import_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(APP_ROOT))


@pytest.fixture()
def generated_root(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    _write_bundle(root)
    return root


def _rewrite_manifest(root: Path, mutate) -> None:
    manifest_path = root / "build_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    mutate(manifest)
    _write_manifest(root, manifest)


def test_repository_is_read_only(generated_root: Path) -> None:
    from control_tower.repository import ControlTowerRepository

    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in generated_root.iterdir()}
    repo = ControlTowerRepository(generated_root)
    snapshot = repo.load_snapshot()
    after = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in generated_root.iterdir()}
    assert len(snapshot.entities) > 0
    assert set(snapshot.__dataclass_fields__) >= {"entities", "events", "source_health"}
    assert not hasattr(repo, "save")
    assert before == after


def test_consensus_contract_is_populated_and_typed_empty(generated_root: Path) -> None:
    from control_tower.config import ARTIFACT_COLUMNS
    from control_tower.repository import ControlTowerRepository

    populated = ControlTowerRepository(generated_root).load_snapshot()
    assert not populated.consensus_snapshots.empty
    assert not populated.consensus_revisions.empty
    assert list(populated.consensus_snapshots.columns) == list(ARTIFACT_COLUMNS["consensus_snapshots.parquet"])
    assert list(populated.consensus_revisions.columns) == list(ARTIFACT_COLUMNS["consensus_revisions.parquet"])
    assert len(populated.consensus_snapshots.columns) == 29
    assert len(populated.consensus_revisions.columns) == 35
    assert "source_run_id" in populated.consensus_snapshots.columns
    assert {
        "prior_provider_asof", "provider_asof", "retrieved_at_utc",
        "source_url", "pit_class", "source_run_id",
    } <= set(populated.consensus_revisions.columns)

    for name in ("consensus_snapshots.parquet", "consensus_revisions.parquet"):
        (generated_root / name).unlink()
    _rewrite_manifest(
        generated_root,
        lambda manifest: (
            [
                manifest["artifacts"][name].update(
                    {"status": "unavailable", "sha256": None, "byte_size": 0, "row_count": 0}
                )
                for name in ("consensus_snapshots.parquet", "consensus_revisions.parquet")
            ],
            manifest.update({
                "status": "degraded",
                "degraded_inputs": ["consensus_snapshots", "consensus_revisions"],
            }),
        )[-1],
    )
    empty = ControlTowerRepository(generated_root).load_snapshot()
    assert empty.status == "degraded"
    assert empty.consensus_snapshots.empty
    assert empty.consensus_revisions.empty
    assert list(empty.consensus_snapshots.columns) == list(ARTIFACT_COLUMNS["consensus_snapshots.parquet"])
    assert list(empty.consensus_revisions.columns) == list(ARTIFACT_COLUMNS["consensus_revisions.parquet"])
    assert str(empty.consensus_snapshots["source_run_id"].dtype) == "string"
    assert str(empty.consensus_revisions["prior_provider_asof"].dtype) == "datetime64[ns, UTC]"


def test_watch_question_priority_matches_task4_arrow_contract(generated_root: Path) -> None:
    from control_tower.repository import ControlTowerRepository

    table = pq.read_table(generated_root / "event_watch_questions.parquet")
    assert table.schema.field("priority").type == pa.string()

    snapshot = ControlTowerRepository(generated_root).load_snapshot()
    assert pd.api.types.is_string_dtype(snapshot.event_watch_questions["priority"])
    assert snapshot.event_watch_questions.loc[0, "priority"] == "high"


def test_direct_manifest_json_is_supported(generated_root: Path) -> None:
    from control_tower.repository import ControlTowerRepository

    manifest = _manifest_for(generated_root)
    record = manifest["artifacts"].pop("build_manifest.json")
    record["name"] = "manifest.json"
    record["relative_path"] = "manifest.json"
    manifest["artifacts"]["manifest.json"] = record
    (generated_root / "build_manifest.json").unlink()
    _write_named_manifest(generated_root, "manifest.json", manifest)

    snapshot = ControlTowerRepository(generated_root).load_snapshot()
    assert snapshot.build_id == "fixture-build-001"
    assert len(snapshot.entities) == 2


def test_legacy_direct_root_ignores_unrelated_entries(generated_root: Path) -> None:
    from control_tower.config import ARTIFACT_NAMES, artifact_fingerprint
    from control_tower.repository import ControlTowerRepository

    (generated_root / "unrelated.txt").write_text("not an artifact", encoding="utf-8")
    unrelated_directory = generated_root / "other-run"
    unrelated_directory.mkdir()
    (unrelated_directory / "events.parquet").write_bytes(b"not selected")

    snapshot = ControlTowerRepository(generated_root).load_snapshot()
    fingerprint_names = {item[0] for item in artifact_fingerprint(generated_root)}

    assert len(snapshot.entities) == 2
    assert fingerprint_names == set(ARTIFACT_NAMES)
    assert "unrelated.txt" not in fingerprint_names
    assert "other-run/events.parquet" not in fingerprint_names


def test_publication_current_resolves_exact_generation_and_invalidates_fingerprint(
    generated_root: Path, tmp_path: Path
) -> None:
    from control_tower.config import ARTIFACT_NAMES, artifact_fingerprint
    from control_tower.repository import ControlTowerRepository

    publication = _publication_from_bundle(tmp_path, generated_root)
    generation_two = publication / "generations" / "gen-002"
    shutil.copytree(publication / "generations" / "gen-001", generation_two)
    (publication / "CURRENT").write_text("generations/gen-001\n", encoding="utf-8")
    first = artifact_fingerprint(publication)
    snapshot = ControlTowerRepository(publication).load_snapshot()
    assert len(snapshot.entities) == 2
    assert [item[0] for item in first][0:2] == ["CURRENT", "CURRENT_TARGET"]
    assert len([item for item in first if item[0].startswith("generations/gen-001/")]) == len(ARTIFACT_NAMES)

    (publication / "CURRENT").write_text("generations/gen-002\n", encoding="utf-8")
    second = artifact_fingerprint(publication)
    assert first != second
    assert any(item[0].startswith("generations/gen-002/") for item in second)


@pytest.mark.parametrize("target", [
    "/tmp/outside",
    "../outside",
    "generations/../gen-001",
    "generations/./gen-001",
    "generations/missing",
])
def test_publication_current_rejects_unsafe_or_missing_targets(
    generated_root: Path, tmp_path: Path, target: str
) -> None:
    from control_tower.config import ArtifactResolutionError, resolve_artifact_root

    publication = _publication_from_bundle(tmp_path, generated_root)
    (publication / "CURRENT").write_text(target + "\n", encoding="utf-8")
    with pytest.raises(ArtifactResolutionError):
        resolve_artifact_root(publication)


def test_publication_current_rejects_symlink_escape_and_non_exact_generation(
    generated_root: Path, tmp_path: Path
) -> None:
    from control_tower.config import ArtifactResolutionError, resolve_artifact_root

    publication = _publication_from_bundle(tmp_path, generated_root)
    outside = tmp_path / "outside-generation"
    shutil.copytree(generated_root, outside)
    escape = publication / "generations" / "escape"
    escape.symlink_to(outside, target_is_directory=True)
    (publication / "CURRENT").write_text("generations/escape\n", encoding="utf-8")
    with pytest.raises(ArtifactResolutionError, match="symlinked directories|escapes publication root"):
        resolve_artifact_root(publication)

    (publication / "CURRENT").write_text("generations/gen-001\n", encoding="utf-8")
    (publication / "generations" / "gen-001" / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ArtifactResolutionError, match="unexpected"):
        resolve_artifact_root(publication)


def test_publication_generation_rejects_in_generation_symlink(
    generated_root: Path, tmp_path: Path
) -> None:
    from control_tower.config import ArtifactResolutionError, resolve_artifact_root

    publication = _publication_from_bundle(tmp_path, generated_root)
    generation = publication / "generations" / "gen-001"
    source = generation / "entities.parquet"
    source.unlink()
    source.symlink_to(generation / "listings.parquet")
    with pytest.raises(ArtifactResolutionError, match="must not be a symlink"):
        resolve_artifact_root(publication)


def test_publication_manifest_generation_id_must_match_current(
    generated_root: Path, tmp_path: Path
) -> None:
    from control_tower.repository import ControlTowerRepository, ControlTowerStartupError

    publication = _publication_from_bundle(tmp_path, generated_root)
    generation = publication / "generations" / "gen-001"
    manifest = json.loads((generation / "build_manifest.json").read_text(encoding="utf-8"))
    manifest["generation_id"] = "gen-other"
    _write_manifest(generation, manifest)
    with pytest.raises(ControlTowerStartupError, match="generation_id does not match CURRENT target"):
        ControlTowerRepository(publication).load_snapshot()


def test_publication_manifest_current_pointer_must_match_current(
    generated_root: Path, tmp_path: Path
) -> None:
    from control_tower.repository import ControlTowerRepository, ControlTowerStartupError

    publication = _publication_from_bundle(tmp_path, generated_root)
    generation = publication / "generations" / "gen-001"
    manifest = json.loads((generation / "build_manifest.json").read_text(encoding="utf-8"))
    manifest["current_pointer"] = "generations/gen-other"
    _write_manifest(generation, manifest)

    with pytest.raises(
        ControlTowerStartupError,
        match="current_pointer does not match CURRENT target",
    ):
        ControlTowerRepository(publication).load_snapshot()


def test_required_manifest_status_always_fails_closed(generated_root: Path) -> None:
    from control_tower.repository import ControlTowerRepository, ControlTowerStartupError

    _rewrite_manifest(
        generated_root,
        lambda manifest: (
            manifest["artifacts"]["source_health.parquet"].update({"status": "unavailable"}),
            manifest.update({"status": "degraded"}),
        )[-1],
    )
    with pytest.raises(ControlTowerStartupError, match="required artifact 'source_health.parquet'"):
        ControlTowerRepository(generated_root).load_snapshot()


def test_failure_fingerprint_includes_present_expected_files(generated_root: Path) -> None:
    from control_tower.config import artifact_fingerprint

    (generated_root / "events.parquet").unlink()
    (generated_root / "CURRENT").write_text("../unsafe\n", encoding="utf-8")
    fingerprint = artifact_fingerprint(generated_root)
    names = [item[0] for item in fingerprint]
    assert "entities.parquet" in names
    assert "build_manifest.json" in names
    assert "CURRENT" in names


def test_manifest_row_count_must_be_one(generated_root: Path) -> None:
    from control_tower.repository import ControlTowerRepository, ControlTowerStartupError

    _rewrite_manifest(
        generated_root,
        lambda manifest: manifest["artifacts"]["build_manifest.json"].update({"row_count": 2}),
    )
    with pytest.raises(ControlTowerStartupError, match="build_manifest.json row count mismatch"):
        ControlTowerRepository(generated_root).load_snapshot()


def test_publication_current_must_not_be_a_symlink(generated_root: Path, tmp_path: Path) -> None:
    from control_tower.config import ArtifactResolutionError, resolve_artifact_root

    publication = _publication_from_bundle(tmp_path, generated_root)
    current = publication / "CURRENT"
    current.unlink()
    current.symlink_to(publication / "generations" / "gen-001" / "build_manifest.json")
    with pytest.raises(ArtifactResolutionError, match="CURRENT must be a regular file"):
        resolve_artifact_root(publication)


def test_optional_artifact_missing_enters_degraded_mode(generated_root: Path) -> None:
    from control_tower.repository import ControlTowerRepository

    (generated_root / "consensus_revisions.parquet").unlink()
    _rewrite_manifest(
        generated_root,
        lambda manifest: manifest["artifacts"]["consensus_revisions.parquet"].update(
            {"status": "unavailable", "sha256": None, "byte_size": 0, "row_count": 0}
        ) or manifest.update({"status": "degraded", "degraded_inputs": ["consensus_revisions"]}),
    )
    snapshot = ControlTowerRepository(generated_root).load_snapshot()
    assert snapshot.status == "degraded"
    assert "consensus_revisions" in snapshot.missing_optional
    assert snapshot.consensus_revisions.empty
    assert snapshot.degraded_reasons["consensus_revisions"] == "missing"


def test_legacy_generation_without_quote_artifact_loads_as_degraded(tmp_path: Path) -> None:
    from control_tower.repository import ControlTowerRepository

    root = tmp_path / "legacy-bundle"
    _write_bundle(root)
    (root / "quote_snapshots.parquet").unlink()
    manifest_path = root / "build_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"].pop("quote_snapshots.parquet")
    manifest["status"] = "degraded"
    manifest["degraded_inputs"] = ["quote_snapshots"]
    _write_manifest(root, manifest)

    snapshot = ControlTowerRepository(root).load_snapshot()

    assert snapshot.status == "degraded"
    assert "quote_snapshots" in snapshot.missing_optional
    assert snapshot.quote_snapshots.empty
    assert snapshot.degraded_reasons["quote_snapshots"] == "missing"


@pytest.mark.parametrize(
    "name",
    [
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
        "source_health.parquet",
        "build_manifest.json",
    ],
)
def test_missing_required_artifact_fails(generated_root: Path, name: str) -> None:
    from control_tower.repository import ControlTowerRepository, ControlTowerStartupError

    if name != "build_manifest.json":
        (generated_root / name).unlink()
    else:
        (generated_root / name).unlink()
    with pytest.raises(ControlTowerStartupError, match=rf"'{name}'"):
        ControlTowerRepository(generated_root).load_snapshot()


def test_corrupt_required_parquet_fails(generated_root: Path) -> None:
    from control_tower.repository import ControlTowerRepository, ControlTowerStartupError

    path = generated_root / "events.parquet"
    path.write_bytes(b"not parquet")
    with pytest.raises(ControlTowerStartupError, match="events.parquet.*hash mismatch"):
        ControlTowerRepository(generated_root).load_snapshot()


def test_corrupt_optional_parquet_degrades_without_partial_rows(generated_root: Path) -> None:
    from control_tower.repository import ControlTowerRepository

    path = generated_root / "news_filings.parquet"
    path.write_bytes(b"not parquet")
    _rewrite_manifest(
        generated_root,
        lambda manifest: manifest["artifacts"]["news_filings.parquet"].update(
            {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "byte_size": path.stat().st_size, "status": "available"}
        ),
    )
    snapshot = ControlTowerRepository(generated_root).load_snapshot()
    assert snapshot.news_filings.empty
    assert snapshot.degraded_reasons["news_filings"] == "corrupt"


@pytest.mark.parametrize("field", ["sha256", "row_count", "schema_version"])
def test_required_manifest_mismatch_fails(generated_root: Path, field: str) -> None:
    from control_tower.repository import ControlTowerRepository, ControlTowerStartupError

    def mutate(manifest):
        record = manifest["artifacts"]["entities.parquet"]
        record[field] = "bad" if field != "row_count" else 999

    _rewrite_manifest(generated_root, mutate)
    with pytest.raises(ControlTowerStartupError, match="entities.parquet"):
        ControlTowerRepository(generated_root).load_snapshot()


def test_optional_manifest_mismatch_degrades_to_typed_empty(generated_root: Path) -> None:
    from control_tower.repository import ControlTowerRepository

    _rewrite_manifest(
        generated_root,
        lambda manifest: manifest["artifacts"]["consensus_snapshots.parquet"].update(
            {"row_count": 999}
        ),
    )
    snapshot = ControlTowerRepository(generated_root).load_snapshot()
    assert snapshot.consensus_snapshots.empty
    assert snapshot.degraded_reasons["consensus_snapshots"] == "manifest_mismatch"
    assert list(snapshot.consensus_snapshots.columns) == _columns()["consensus_snapshots.parquet"]


def test_invalid_manifest_and_path_traversal_fail(generated_root: Path) -> None:
    from control_tower.repository import ControlTowerRepository, ControlTowerStartupError

    manifest_path = generated_root / "build_manifest.json"
    manifest_path.write_text("{")
    with pytest.raises(ControlTowerStartupError, match="build_manifest.json is invalid"):
        ControlTowerRepository(generated_root).load_snapshot()

    _write_manifest(generated_root, _manifest_for(generated_root))
    _rewrite_manifest(
        generated_root,
        lambda manifest: manifest["artifacts"]["entities.parquet"].update({"relative_path": "../entities.parquet"}),
    )
    with pytest.raises(ControlTowerStartupError, match="entities.parquet"):
        ControlTowerRepository(generated_root).load_snapshot()


def test_manifest_status_and_schema_are_validated(generated_root: Path) -> None:
    from control_tower.repository import ControlTowerRepository, ControlTowerStartupError

    _rewrite_manifest(generated_root, lambda manifest: manifest.update({"schema_version": "future_v2"}))
    with pytest.raises(ControlTowerStartupError, match="unsupported manifest schema"):
        ControlTowerRepository(generated_root).load_snapshot()

    _write_manifest(generated_root, _manifest_for(generated_root))
    _rewrite_manifest(generated_root, lambda manifest: manifest.update({"status": "success", "degraded_inputs": ["news"]}))
    with pytest.raises(ControlTowerStartupError, match="inconsistent manifest status"):
        ControlTowerRepository(generated_root).load_snapshot()


@pytest.mark.parametrize(
    ("built_at_utc", "as_of_utc", "previous_build_at"),
    [
        (
            "2026-08-13T12:00:00Z",
            "2026-08-13T12:00:00Z",
            "2026-08-13T12:00:00Z",
        ),
        (
            "2026-08-13T13:00:00Z",
            "2026-08-13T12:00:00Z",
            "2026-08-13T12:00:00Z",
        ),
    ],
)
def test_manifest_previous_build_at_must_be_strictly_earlier(
    generated_root: Path,
    built_at_utc: str,
    as_of_utc: str,
    previous_build_at: str,
) -> None:
    from control_tower.repository import (
        ControlTowerRepository,
        ControlTowerStartupError,
    )

    _rewrite_manifest(
        generated_root,
        lambda manifest: manifest.update(
            {
                "built_at_utc": built_at_utc,
                "as_of_utc": as_of_utc,
                "previous_build_at": previous_build_at,
            }
        ),
    )

    with pytest.raises(
        ControlTowerStartupError,
        match="previous_build_at must be strictly earlier",
    ):
        ControlTowerRepository(generated_root).load_snapshot()


def test_relation_enrichment_preserves_targets_and_deduplicates(generated_root: Path) -> None:
    from control_tower.repository import ControlTowerRepository

    snapshot = ControlTowerRepository(generated_root).load_snapshot()
    events = snapshot.events
    row = events.loc[events["event_id"].eq("EV_HARD")].iloc[0]
    assert row["related_entity_ids"] == ("E1",)
    assert row["related_listing_ids"] == ("L2",)
    assert row["related_basket_ids"] == ("BASKET_A", "BASKET_B")
    assert row["related_index_ids"] == ("IDX1",)
    assert row["related_countries"] == ("JP", "US")
    assert row["membership_tiers"] == ("core", "read_through")
    assert set(events["event_id"]) == {"EV_HARD", "EV_ACTIVE", "EV_PAST", "EV_FAR", "EV_GAP", "EV_TIE_A", "EV_TIE_B"}
    assert set(snapshot.event_entity_links["target_type"]) == {"entity", "listing", "index"}


def test_filters_have_or_within_and_across_semantics_and_exclude_gaps(generated_root: Path) -> None:
    from control_tower.filters import apply_event_filters
    from control_tower.models import EventFilters
    from control_tower.repository import ControlTowerRepository

    events = ControlTowerRepository(generated_root).load_snapshot().events
    result = apply_event_filters(
        events,
        EventFilters(
            basket_id=("BASKET_B", "BASKET_A"),
            country=("JP",),
            membership_tier=("read_through",),
            scope=("basket",),
            now_utc="2026-08-13T00:00:00Z",
        ),
    )
    assert list(result["event_id"]) == ["EV_ACTIVE"]
    assert "EV_GAP" not in set(apply_event_filters(events, EventFilters()).get("event_id", []))
    assert list(EventFilters(basket_id=(" basket_b ", "BASKET_A", "basket_b")).basket_id) == ["BASKET_A", "BASKET_B"]


def test_filters_support_status_confidence_importance_and_catalyst(generated_root: Path) -> None:
    from control_tower.filters import apply_event_filters
    from control_tower.models import EventFilters
    from control_tower.repository import ControlTowerRepository

    events = ControlTowerRepository(generated_root).load_snapshot().events
    assert list(apply_event_filters(events, EventFilters(importance=("HIGH",))) ["event_id"]) == ["EV_HARD"]
    assert list(apply_event_filters(events, EventFilters(status=("scheduled",), confidence_min=0.55))["event_id"]) == ["EV_TIE_A", "EV_TIE_B", "EV_FAR"]
    assert list(apply_event_filters(events, EventFilters(catalyst_eligible=True))["event_id"])
    with pytest.raises(ValueError, match="unsupported scope"):
        EventFilters(scope=("not-a-scope",))
    with pytest.raises(ValueError, match="timezone-aware"):
        EventFilters(horizon="7d", now_utc="2026-08-13T00:00:00")


def test_horizons_are_half_open_at_long_range_cutoff_and_keep_active_ranges(generated_root: Path) -> None:
    from control_tower.filters import apply_event_filters
    from control_tower.models import EventFilters
    from control_tower.repository import ControlTowerRepository

    events = ControlTowerRepository(generated_root).load_snapshot().events
    now = "2026-08-13T00:00:00Z"
    assert "EV_HARD" in set(apply_event_filters(events, EventFilters(horizon="7d", now_utc=now))["event_id"])
    assert "EV_ACTIVE" in set(apply_event_filters(events, EventFilters(horizon="90d", now_utc=now))["event_id"])
    assert "EV_FAR" in set(apply_event_filters(events, EventFilters(horizon="long_range", now_utc=now))["event_id"])
    assert "EV_GAP" not in set(apply_event_filters(events, EventFilters(horizon="long_range", now_utc=now))["event_id"])
    with pytest.raises(ValueError, match="now_utc"):
        apply_event_filters(events, EventFilters(horizon="7d"))


def test_stable_sort_uses_importance_then_event_id_then_input_position(generated_root: Path) -> None:
    from control_tower.filters import apply_event_filters
    from control_tower.models import EventFilters
    from control_tower.repository import ControlTowerRepository

    events = ControlTowerRepository(generated_root).load_snapshot().events
    events.loc[events["event_id"].eq("EV_TIE_A"), "importance"] = "high"
    events.loc[events["event_id"].eq("EV_TIE_B"), "importance"] = "medium"
    result = apply_event_filters(events, EventFilters(horizon="30d", now_utc="2026-08-13T00:00:00Z"))
    assert list(result.loc[result["starts_at"].eq(pd.Timestamp("2026-08-20T00:00:00Z")), "event_id"]) == ["EV_TIE_A", "EV_TIE_B"]


def test_format_t_minus_uses_viewer_calendar_and_validates_timezones() -> None:
    from control_tower.formatting import format_t_minus

    now = pd.Timestamp("2026-08-13T00:00:00Z")
    assert format_t_minus("2026-08-15T00:30:00+09:00", "Europe/London", now) == "T-1d"
    assert format_t_minus("2026-08-12T00:30:00Z", "Europe/London", now) == "T+1d"
    assert format_t_minus("2026-08-13T12:00:00Z", "Europe/London", now) == "T0d"
    assert format_t_minus(None, "UTC", now) == "—"
    with pytest.raises(ValueError, match="timezone-aware"):
        format_t_minus("2026-08-15T00:30:00", "UTC", now)
    with pytest.raises(ValueError, match="unknown viewer timezone"):
        format_t_minus("2026-08-15T00:30:00Z", "Mars/Phobos", now)


def test_fingerprint_contains_manifest_and_every_fixed_artifact(generated_root: Path) -> None:
    from control_tower.config import ARTIFACT_NAMES, artifact_fingerprint

    fingerprint = artifact_fingerprint(generated_root)
    assert [item[0] for item in fingerprint] == list(ARTIFACT_NAMES)
    assert all(len(item) == 4 for item in fingerprint)
    assert all(item[3] for item in fingerprint)


def test_repository_load_has_no_network_or_write_primitives(generated_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from control_tower.repository import ControlTowerRepository

    def fail(*args, **kwargs):
        raise AssertionError("unexpected external or write operation")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket.socket, "send", fail)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", fail)
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    monkeypatch.setattr(Path, "write_text", fail)
    monkeypatch.setattr(Path, "write_bytes", fail)
    monkeypatch.setattr(os, "replace", fail)
    monkeypatch.setattr(os, "rename", fail)
    monkeypatch.setattr(tempfile, "mkstemp", fail)
    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail)
    ControlTowerRepository(generated_root).load_snapshot()
