from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import socket
from dataclasses import replace
import importlib.util
import sys
import urllib.request

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import re


APP_ROOT = Path(__file__).resolve().parents[1] / "apps" / "research-control-tower"
APP_PATH = APP_ROOT / "app.py"


def _columns() -> dict[str, list[str]]:
    return {
        "entities.parquet": [
            "entity_id", "legal_name", "display_name", "country", "sector", "industry",
            "active_status", "active_from", "active_to", "registry_version", "source_or_research_note", "entity_type",
        ],
        "listings.parquet": [
            "listing_id", "entity_id", "exchange", "native_ticker", "canonical_ticker",
            "financial_data_security_id", "financial_data_issuer_group_id", "mapping_status",
            "mapping_verified_at", "mapping_source_url", "collection_eligible", "listing_role",
            "vendor_tickers", "currency", "primary_listing", "active_from", "active_to",
            "listing_status", "registry_version", "source_url", "source_or_research_note",
        ],
        "baskets.parquet": [
            "basket_id", "display_name", "purpose", "active_from", "active_to",
            "registry_version", "source_or_research_note",
        ],
        "basket_memberships.parquet": [
            "entity_id", "basket_id", "membership_tier", "primary_layer", "secondary_layers",
            "active_from", "active_to", "membership_reason", "source_or_research_note", "registry_version",
        ],
        "indices.parquet": [
            "index_id", "region", "display_name", "official_code", "official_code_namespace",
            "official_code_provider", "provider_symbol", "provider_symbol_namespace",
            "provider_symbol_provider", "provider", "currency", "active_from", "active_to",
            "registry_version", "source_url", "source_or_research_note",
        ],
        "events.parquet": [
            "event_id", "event_key", "observation_version", "scope", "event_type", "title",
            "description", "status", "certainty_class", "importance", "confidence", "date_precision",
            "starts_at", "ends_at", "source_timezone", "source_id", "source_url", "source_published_at",
            "first_observed_at", "last_verified_at", "review_by", "supersedes_event_id",
            "evidence_class", "evidence_ref", "reference_period", "previous_value", "previous_vintage",
            "market_consensus", "consensus_source", "own_nowcast", "actual_value", "actual_unit",
            "revised_value", "surprise_value", "surprise_unit", "scenario_notes", "expected_metrics",
            "thesis_implications", "registry_version",
        ],
        "event_entity_links.parquet": [
            "event_id", "target_type", "target_id", "link_role", "automated", "active_from", "active_to",
            "link_note", "registry_version",
        ],
        "event_basket_links.parquet": [
            "event_id", "target_type", "target_id", "link_role", "automated", "active_from", "active_to",
            "link_note", "registry_version",
        ],
        "event_watch_questions.parquet": [
            "event_id", "question_id", "question", "question_type", "priority", "registry_version",
        ],
        "macro_observations.parquet": [
            "observation_id", "event_id", "source_id", "series_id", "scope", "event_type", "metric_name",
            "reference_period", "observation_date", "release_at", "actual_value", "unit", "frequency",
            "first_observed_at", "source_published_at", "retrieved_at_utc", "source_url", "pit_class",
            "source_license_class", "is_provisional", "realtime_start", "realtime_end", "registry_version",
        ],
        "consensus_snapshots.parquet": [
            "snapshot_id", "provider", "entity_id", "listing_id", "financial_data_security_id",
            "canonical_ticker", "metric", "fiscal_period", "fiscal_year", "estimate_period_end", "horizon",
            "snapshot_at", "value", "statistic", "low_value", "high_value", "analyst_count",
            "provider_contributor_count", "currency", "unit", "accounting_basis", "provider_asof",
            "retrieved_at_utc", "source_url", "raw_hash", "pit_class", "source_run_id", "calculation_origin", "coverage_reason",
        ],
        "consensus_revisions.parquet": [
            "revision_id", "snapshot_id", "provider", "prior_provider", "entity_id", "listing_id",
            "financial_data_security_id", "canonical_ticker", "metric", "fiscal_period", "fiscal_year",
            "estimate_period_end", "horizon", "statistic", "current_snapshot_at", "current_value",
            "current_analyst_count", "current_dispersion", "lookback_days", "cutoff_at", "prior_snapshot_id",
            "prior_snapshot_at", "prior_value", "prior_provider_asof", "provider_asof", "retrieved_at_utc", "source_url", "pit_class", "source_run_id", "prior_analyst_count", "revision_value", "revision_pct",
            "analyst_count_change", "dispersion", "alignment_status",
        ],
        "quote_snapshots.parquet": [
            "quote_id", "listing_id", "canonical_ticker", "provider_symbol",
            "quote_timestamp", "retrieved_at_utc", "last_price", "bid", "ask",
            "day_change_pct", "volume", "currency", "market_status", "latency_class",
            "source_id", "source_url", "pit_class", "source_license_class",
            "registry_version",
        ],
        "price_bars.parquet": [
            "bar_id", "listing_id", "entity_id", "canonical_ticker", "provider_symbol",
            "interval", "bar_date", "open", "high", "low", "close", "adj_close",
            "volume", "currency", "source_id", "source_url", "retrieved_at_utc",
            "pit_class", "source_license_class", "registry_version",
        ],
        "news_filings.parquet": [
            "document_id", "document_type", "source_id", "headline", "publisher", "published_at",
            "first_observed_at", "source_url", "language", "related_entity_ids", "related_listing_ids",
            "related_basket_ids", "event_class", "importance", "source_quality", "pit_class",
            "source_license_class", "content_hash_if_permitted", "derived_summary_if_permitted",
        ],
        "official_filings.parquet": [
            "document_id", "document_type", "event_class", "source_id", "headline",
            "publisher", "published_at", "accepted_at", "scheduled_date",
            "retrieved_at_utc", "source_url", "language", "entity_id", "listing_id",
            "canonical_ticker", "reporting_period_label", "reporting_period_start",
            "reporting_period_end", "date_precision", "source_timezone",
            "event_status", "source_quality", "pit_class", "source_license_class",
            "content_hash_if_permitted", "source_note", "registry_version",
        ],
        "earnings_calendar.parquet": [
            "calendar_id", "entity_id", "listing_id", "canonical_ticker",
            "period_label", "period_start", "period_end", "event_type", "event_date",
            "date_precision", "date_basis", "source_timezone", "status", "source_id",
            "source_url", "headline", "published_at", "retrieved_at_utc",
            "source_quality", "pit_class", "source_license_class", "source_note",
            "registry_version",
        ],
        "earnings_actuals.parquet": [
            "actual_id", "version", "supersedes_actual_id", "entity_id", "listing_id",
            "canonical_ticker", "metric", "period_label", "period_start", "period_end",
            "reported_value", "normalized_value", "normalization_note", "currency",
            "unit", "accounting_basis", "filing_at", "published_at",
            "retrieved_at_utc", "source_url", "accession_no", "form", "xbrl_frame",
            "revision_reason", "is_restatement", "source_id", "source_quality",
            "pit_class", "source_license_class", "source_note", "registry_version",
        ],
        "source_health.parquet": [
            "source_id", "input_path", "source_kind", "status", "required", "row_count",
            "first_observation_at", "latest_observation_at", "source_latest_at", "retrieved_at_utc",
            "cadence", "source_url", "pit_class", "source_license_class", "entitlement_status",
            "entitlement_evidence", "entitlement_ref", "input_sha256", "schema_version",
            "missing_geographies", "detail",
        ],
    }


def _blank(name: str) -> dict[str, object]:
    return {column: None for column in _columns()[name]}


def _frame(name: str, rows: list[dict[str, object]]) -> pd.DataFrame:
    columns = _columns()[name]
    return pd.DataFrame([{**_blank(name), **row} for row in rows], columns=columns)


_DATE_COLUMNS = {
    "active_from", "active_to", "mapping_verified_at", "review_by", "observation_date",
    "estimate_period_end", "scheduled_date", "reporting_period_start",
    "reporting_period_end", "period_start", "period_end", "event_date",
 "bar_date",}
_TIMESTAMP_COLUMNS = {
    "starts_at", "ends_at", "source_published_at", "first_observed_at", "last_verified_at", "release_at",
    "retrieved_at_utc", "snapshot_at", "provider_asof", "current_snapshot_at",
    "cutoff_at", "prior_snapshot_at", "prior_provider_asof", "provider_asof", "published_at", "first_observation_at", "latest_observation_at",
    "source_latest_at", "quote_timestamp", "accepted_at", "filing_at",
}
_BOOLEAN_COLUMNS = {
    "collection_eligible", "primary_listing", "automated", "is_provisional",
    "required", "is_restatement",
}
_INTEGER_COLUMNS = {
    "observation_version", "fiscal_year", "analyst_count", "provider_contributor_count", "lookback_days",
    "current_analyst_count", "prior_analyst_count", "analyst_count_change", "row_count", "version",
}
_FLOAT_COLUMNS = {
    "confidence", "value", "low_value", "high_value", "current_value", "current_dispersion", "prior_value",
    "revision_value", "revision_pct", "dispersion", "last_price", "bid", "ask",
    "day_change_pct", "volume", "reported_value", "normalized_value",
 "open", "high", "low", "close", "adj_close",}


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for column in _DATE_COLUMNS & set(frame.columns):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.date
    for column in _TIMESTAMP_COLUMNS & set(frame.columns):
        frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)
    for column in _BOOLEAN_COLUMNS & set(frame.columns):
        frame[column] = frame[column].astype("boolean")
    for column in _INTEGER_COLUMNS & set(frame.columns):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    for column in _FLOAT_COLUMNS & set(frame.columns):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Float64")
    for column in frame.columns:
        if column not in _DATE_COLUMNS | _TIMESTAMP_COLUMNS | _BOOLEAN_COLUMNS | _INTEGER_COLUMNS | _FLOAT_COLUMNS:
            frame[column] = frame[column].astype("string")
    return frame


def _schema(name: str) -> pa.Schema:
    columns = _columns()[name]
    fields: list[pa.Field] = []
    for column in columns:
        if column in _DATE_COLUMNS:
            dtype = pa.date32()
        elif column in _TIMESTAMP_COLUMNS:
            dtype = pa.timestamp("us", tz="UTC")
        elif column in _BOOLEAN_COLUMNS:
            dtype = pa.bool_()
        elif column in _INTEGER_COLUMNS:
            dtype = pa.int64()
        elif column in _FLOAT_COLUMNS:
            dtype = pa.float64()
        else:
            dtype = pa.string()
        fields.append(pa.field(column, dtype, nullable=True))
    return pa.schema(fields)


def _event(
    event_id: str,
    *,
    title: str,
    starts_at: str | None,
    ends_at: str | None = None,
    certainty_class: str = "hard",
    status: str = "scheduled",
    importance: str | None = "medium",
    confidence: float | None = .8,
    first_observed_at: str = "2026-08-13T11:00:00Z",
    event_type: str = "earnings",
    evidence_class: str = "official_external",
    source_id: str = "source:official",
    source_url: str = "https://example.test/event",
) -> dict[str, object]:
    return {
        "event_id": event_id, "event_key": event_id, "observation_version": 1, "scope": "company",
        "event_type": event_type, "title": title, "description": f"Evidence for {title}.", "status": status,
        "certainty_class": certainty_class, "importance": importance, "confidence": confidence,
        "date_precision": "day", "starts_at": starts_at, "ends_at": ends_at, "source_timezone": "UTC",
        "source_id": source_id, "source_url": source_url, "source_published_at": first_observed_at,
        "first_observed_at": first_observed_at, "last_verified_at": "2026-08-13T11:30:00Z",
        "evidence_class": evidence_class, "evidence_ref": source_id, "registry_version": "v1",
    }


def _manifest(root: Path, *, previous_build_at: str | None, degraded: bool = False) -> dict[str, object]:
    artifacts: dict[str, dict[str, object]] = {}
    for name in (*_columns().keys(), "build_manifest.json"):
        path = root / name
        is_manifest = name == "build_manifest.json"
        artifacts[name] = {
            "name": name,
            "relative_path": name,
            "sha256": None if is_manifest else hashlib.sha256(path.read_bytes()).hexdigest(),
            "row_count": 1 if is_manifest else len(pd.read_parquet(path)),
            "byte_size": 0 if is_manifest else path.stat().st_size,
            "schema_version": "control_tower_marts_v1",
            "source_ids": [],
            "status": "available",
        }
    return {
        "schema_version": "control_tower_marts_v1", "build_id": "task6-fixture-001",
        "status": "degraded" if degraded else "success", "built_at_utc": "2026-08-13T12:00:00Z",
        "as_of_utc": "2026-08-13T12:00:00Z", "previous_build_at": previous_build_at,
        "network_policy": "forbidden", "input_fingerprints": {}, "artifacts": artifacts,
        "degraded_inputs": [], "validation_errors": [], "source_health_summary": {"available": 2, "unavailable": 0},
    }


def _write_manifest(root: Path, manifest: dict[str, object]) -> None:
    path = root / "build_manifest.json"
    for _ in range(8):
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        size = path.stat().st_size
        if manifest["artifacts"]["build_manifest.json"]["byte_size"] == size:
            return
        manifest["artifacts"]["build_manifest.json"]["byte_size"] = size
    raise AssertionError("manifest size did not converge")


def _write_bundle(root: Path, *, previous_build_at: str | None = "2026-08-13T10:00:00Z") -> None:
    root.mkdir()
    frames: dict[str, pd.DataFrame] = {
        "entities.parquet": _frame("entities.parquet", [
            {"entity_id": "E1", "legal_name": "Entity One", "display_name": "Entity One", "country": "US", "active_status": "active", "registry_version": "v1"},
            {"entity_id": "E2", "legal_name": "Entity Two", "display_name": "Entity Two", "country": "KR", "active_status": "active", "registry_version": "v1"},
        ]),
        "listings.parquet": _frame("listings.parquet", [
            {"listing_id": "L1", "entity_id": "E1", "exchange": "NASDAQ", "native_ticker": "EONE", "canonical_ticker": "EONE", "mapping_status": "verified", "collection_eligible": True, "listing_role": "primary", "currency": "USD", "primary_listing": True, "listing_status": "active", "registry_version": "v1"},
            {"listing_id": "L2", "entity_id": "E2", "exchange": "KRX", "native_ticker": "ETWO", "canonical_ticker": "ETWO", "mapping_status": "verified", "collection_eligible": True, "listing_role": "primary", "currency": "KRW", "primary_listing": True, "listing_status": "active", "registry_version": "v1"},
        ]),
        "baskets.parquet": _frame("baskets.parquet", [{"basket_id": "AI_BOTTLENECKS_GLOBAL", "display_name": "AI Bottlenecks Global", "purpose": "Fixture basket", "registry_version": "v1"}]),
        "basket_memberships.parquet": _frame("basket_memberships.parquet", [
            {"entity_id": "E1", "basket_id": "AI_BOTTLENECKS_GLOBAL", "membership_tier": "core", "primary_layer": "accelerators", "registry_version": "v1"},
            {"entity_id": "E2", "basket_id": "AI_BOTTLENECKS_GLOBAL", "membership_tier": "read_through", "primary_layer": "memory", "registry_version": "v1"},
        ]),
        "indices.parquet": _frame("indices.parquet", [{"index_id": "CSI500", "region": "CN", "display_name": "CSI 500", "official_code": "000905", "provider": "official", "registry_version": "v1"}]),
        "events.parquet": _frame("events.parquet", [
            _event("EV_HARD", title="Confirmed high-priority print", starts_at="2026-08-20T00:00:00Z", importance="high"),
            _event("EV_THESIS", title="Thesis qualification window", starts_at="2026-08-14T00:00:00Z", ends_at="2026-08-25T00:00:00Z", certainty_class="thesis_checkpoint", importance="low", evidence_class="internal_research", source_id="source:research", source_url=""),
            _event("EV_PROVISIONAL", title="Provisional date", starts_at="2026-08-28T00:00:00Z", certainty_class="provisional", importance="medium"),
            _event("EV_FAR", title="Far catalyst", starts_at="2026-12-15T00:00:00Z", importance="medium"),
            _event("EV_ACTIVE", title="Active range", starts_at="2026-08-01T00:00:00Z", ends_at="2026-08-20T00:00:00Z", status="active", importance="medium"),
            _event("EV_PAST", title="Observed prior event", starts_at="2026-08-01T00:00:00Z", ends_at="2026-08-02T00:00:00Z", status="observed", certainty_class="observed", importance="low", first_observed_at="2026-08-13T09:00:00Z"),
            _event("EV_PREBUILD", title="Pre-build event", starts_at="2026-08-22T00:00:00Z", importance="low", first_observed_at="2026-08-13T09:00:00Z"),
            _event("EV_GAP", title="Coverage gap", starts_at=None, status="unavailable", event_type="coverage_gap", importance=None, confidence=None, source_id="source:missing", source_url=""),
        ]),
        "event_entity_links.parquet": _frame("event_entity_links.parquet", [
            {"event_id": "EV_HARD", "target_type": "entity", "target_id": "E1", "link_role": "primary", "automated": True, "registry_version": "v1"},
            {"event_id": "EV_HARD", "target_type": "listing", "target_id": "L1", "link_role": "primary", "automated": True, "registry_version": "v1"},
            {"event_id": "EV_HARD", "target_type": "index", "target_id": "CSI500", "link_role": "context", "automated": False, "registry_version": "v1"},
            {"event_id": "EV_THESIS", "target_type": "entity", "target_id": "E2", "link_role": "read_through", "automated": True, "registry_version": "v1"},
        ]),
        "event_basket_links.parquet": _frame("event_basket_links.parquet", [{"event_id": "EV_HARD", "target_type": "basket", "target_id": "AI_BOTTLENECKS_GLOBAL", "link_role": "primary", "automated": True, "registry_version": "v1"}]),
        "event_watch_questions.parquet": _frame("event_watch_questions.parquet", [
            {"event_id": "EV_HARD", "question_id": "Q1", "question": "Does production approval confirm the demand signal?", "question_type": "support", "priority": 1, "registry_version": "v1"},
            {"event_id": "EV_HARD", "question_id": "Q2", "question": "What would falsify the capacity thesis?", "question_type": "falsification", "priority": 2, "registry_version": "v1"},
        ]),
        "macro_observations.parquet": _frame("macro_observations.parquet", [{"observation_id": "M1", "event_id": "EV_HARD", "source_id": "source:official", "series_id": "fixture", "scope": "macro", "event_type": "observation", "metric_name": "fixture metric", "observation_date": "2026-08-12", "release_at": "2026-08-13T11:00:00Z", "actual_value": "1", "unit": "index", "frequency": "monthly", "first_observed_at": "2026-08-13T11:00:00Z", "retrieved_at_utc": "2026-08-13T11:00:00Z", "source_url": "https://example.test/macro", "pit_class": "true_pit", "source_license_class": "public", "is_provisional": False, "registry_version": "v1"}]),
        "consensus_snapshots.parquet": _frame("consensus_snapshots.parquet", [{"snapshot_id": "S1", "provider": "fixture", "entity_id": "E1", "listing_id": "L1", "canonical_ticker": "EONE", "metric": "eps", "fiscal_period": "FY2026", "fiscal_year": 2026, "horizon": "FY", "snapshot_at": "2026-08-13T11:00:00Z", "value": 1.2, "statistic": "mean", "analyst_count": 4, "provider_contributor_count": 6, "currency": "USD", "unit": "per_share", "pit_class": "snapshot_from_live_source", "source_run_id": "run-1", "source_url": "https://example.test/consensus"}]),
        "consensus_revisions.parquet": _frame("consensus_revisions.parquet", [{"revision_id": "R1", "snapshot_id": "S1", "provider": "fixture", "entity_id": "E1", "listing_id": "L1", "canonical_ticker": "EONE", "metric": "eps", "fiscal_period": "FY2026", "fiscal_year": 2026, "horizon": "FY", "statistic": "mean", "current_snapshot_at": "2026-08-13T11:00:00Z", "current_value": 1.2, "current_analyst_count": 4, "prior_snapshot_at": "2026-08-01T11:00:00Z", "prior_value": 1.0, "prior_analyst_count": 3, "revision_value": .2, "revision_pct": .2, "currency": "USD", "unit": "per_share", "pit_class": "true_pit", "source_run_id": "run-1", "retrieved_at_utc": "2026-08-13T11:30:00Z", "alignment_status": "comparable"}]),
        "quote_snapshots.parquet": _frame("quote_snapshots.parquet", []),
        "price_bars.parquet": _frame("price_bars.parquet", []),
        "news_filings.parquet": _frame("news_filings.parquet", [{"document_id": "D1", "document_type": "official_filing", "source_id": "source:official", "headline": "Fixture official filing", "publisher": "Fixture IR", "published_at": "2026-08-13T11:00:00Z", "first_observed_at": "2026-08-13T11:00:00Z", "source_url": "https://example.test/filing", "language": "en", "related_entity_ids": "E1", "event_class": "filing", "importance": "high", "source_quality": "official", "pit_class": "true_pit", "source_license_class": "public"}]),
        "official_filings.parquet": _frame("official_filings.parquet", [{"document_id": "SEC-1", "document_type": "filing", "event_class": "general", "source_id": "sec_edgar_submissions", "headline": "Fixture SEC filing", "publisher": "SEC EDGAR", "published_at": "2026-08-13T11:00:00Z", "accepted_at": "2026-08-13T11:00:00Z", "retrieved_at_utc": "2026-08-13T11:30:00Z", "source_url": "https://example.test/sec", "language": "en", "entity_id": "E1", "listing_id": "L1", "canonical_ticker": "EONE", "date_precision": "minute", "source_timezone": "UTC", "event_status": "observed", "source_quality": "official_metadata", "pit_class": "snapshot_from_live_source", "source_license_class": "official_public_metadata", "source_note": "fixture", "registry_version": "v1"}]),
        "earnings_calendar.parquet": _frame("earnings_calendar.parquet", [{"calendar_id": "CAL-1", "entity_id": "E1", "listing_id": "L1", "canonical_ticker": "EONE", "period_label": "FY2026", "event_type": "annual_results", "event_date": "2026-08-13", "date_precision": "day", "date_basis": "filing_date", "source_timezone": "UTC", "status": "observed", "source_id": "sec_edgar_submissions", "source_url": "https://example.test/sec", "headline": "Fixture annual results", "published_at": "2026-08-13T11:00:00Z", "retrieved_at_utc": "2026-08-13T11:30:00Z", "source_quality": "official_metadata", "pit_class": "snapshot_from_live_source", "source_license_class": "official_public_metadata", "source_note": "fixture", "registry_version": "v1"}]),
        "earnings_actuals.parquet": _frame("earnings_actuals.parquet", [{"actual_id": "ACT-1", "version": 1, "entity_id": "E1", "listing_id": "L1", "canonical_ticker": "EONE", "metric": "revenue", "period_label": "FY2026", "period_end": "2026-03-31", "reported_value": 1.5, "normalized_value": 1.5, "normalization_note": "as_reported", "currency": "USD", "unit": "USD", "accounting_basis": "us-gaap as reported", "filing_at": "2026-08-13T11:00:00Z", "published_at": "2026-08-13T11:00:00Z", "retrieved_at_utc": "2026-08-13T11:30:00Z", "source_url": "https://example.test/actuals", "accession_no": "A1", "form": "20-F", "revision_reason": "initial_filing", "is_restatement": False, "source_id": "sec_companyfacts", "source_quality": "official_metadata", "pit_class": "snapshot_from_live_source", "source_license_class": "official_public_metadata", "source_note": "fixture", "registry_version": "v1"}]),
        "source_health.parquet": _frame("source_health.parquet", [
            {"source_id": "source:official", "input_path": "fixture", "source_kind": "official", "status": "available", "required": True, "row_count": 5, "latest_observation_at": "2026-08-13T11:00:00Z", "source_latest_at": "2026-08-13T11:00:00Z", "retrieved_at_utc": "2026-08-13T11:30:00Z", "pit_class": "true_pit", "source_license_class": "public", "schema_version": "v1", "detail": "fixture source"},
            {"source_id": "source:stale", "input_path": "fixture", "source_kind": "official", "status": "stale", "required": True, "row_count": 0, "latest_observation_at": "2026-08-01T00:00:00Z", "source_latest_at": "2026-08-01T00:00:00Z", "retrieved_at_utc": "2026-08-13T11:30:00Z", "pit_class": "not_pit", "source_license_class": "public", "schema_version": "v1", "detail": "fixture stale source"},
            {"source_id": "source:research", "input_path": "fixture", "source_kind": "research", "status": "available", "required": False, "row_count": 1, "retrieved_at_utc": "2026-08-13T11:00:00Z", "pit_class": "not_pit", "source_license_class": "private", "schema_version": "v1", "detail": "internal research"},
        ]),
    }
    for name, frame in frames.items():
        table = pa.Table.from_pandas(_typed(frame), schema=_schema(name), preserve_index=False, safe=False)
        pq.write_table(table, root / name)
    _write_manifest(root, _manifest(root, previous_build_at=previous_build_at))


def _write_synthetic_populated_task7_bundle(root: Path) -> None:
    """Write a synthetic populated Task 7 fixture using stable registry IDs.

    This is acceptance-test data only. It is deliberately not production
    coverage and does not modify the real generated publication.
    """

    _write_bundle(root)
    frames = {name: pd.read_parquet(root / name) for name in _columns()}

    entities = frames["entities.parquet"]
    entities.loc[entities["entity_id"].eq("E1"), ["entity_id", "legal_name", "display_name", "country", "sector", "industry"]] = [
        "SK_HYNIX", "SK hynix Inc.", "SK Hynix", "KR", "Semiconductors", "Memory chips",
    ]
    entities.loc[entities["entity_id"].eq("E2"), ["entity_id", "legal_name", "display_name", "country", "sector", "industry"]] = [
        "SYNTH_HBM_READ", "Synthetic HBM read-through Co.", "Synthetic HBM read-through", "US", "Semiconductors", "Packaging",
    ]
    entities = pd.concat(
        [
            entities,
            _frame("entities.parquet", [{
                "entity_id": "SYNTH_HBM_WATCH", "legal_name": "Synthetic HBM watch Co.",
                "display_name": "Synthetic HBM watch", "country": "TW", "sector": "Semiconductors",
                "industry": "Packaging", "active_status": "active", "registry_version": "v1",
            }]),
        ],
        ignore_index=True,
    )
    frames["entities.parquet"] = entities

    listings = frames["listings.parquet"]
    listings.loc[listings["listing_id"].eq("L1"), ["listing_id", "entity_id", "exchange", "native_ticker", "canonical_ticker", "mapping_status", "collection_eligible", "listing_role", "currency", "primary_listing"]] = [
        "000660_KR", "SK_HYNIX", "KRX", "000660", "000660.KS", "verified", True, "primary", "KRW", True,
    ]
    listings.loc[listings["listing_id"].eq("L2"), ["listing_id", "entity_id", "exchange", "native_ticker", "canonical_ticker", "mapping_status", "collection_eligible", "listing_role", "currency", "primary_listing"]] = [
        "SYNTH_READ_US", "SYNTH_HBM_READ", "NASDAQ", "SHBM", "SHBM", "verified", True, "primary", "USD", True,
    ]
    listings = pd.concat(
        [
            listings,
            _frame("listings.parquet", [{
                "listing_id": "000660_US", "entity_id": "SK_HYNIX", "exchange": "OTC",
                "native_ticker": "SKHNY", "canonical_ticker": "000660.US", "mapping_status": "verified",
                "collection_eligible": True, "listing_role": "secondary", "currency": "USD",
                "primary_listing": False, "listing_status": "active", "registry_version": "v1",
            }]),
        ],
        ignore_index=True,
    )
    frames["listings.parquet"] = listings

    memberships = frames["basket_memberships.parquet"]
    memberships.loc[memberships["entity_id"].eq("E1"), ["entity_id", "membership_tier", "primary_layer", "secondary_layers"]] = [
        "SK_HYNIX", "core", "hbm_memory", "advanced_packaging_test",
    ]
    memberships.loc[memberships["entity_id"].eq("E2"), ["entity_id", "membership_tier", "primary_layer", "secondary_layers"]] = [
        "SYNTH_HBM_READ", "read_through", "advanced_packaging_test", "hbm_memory",
    ]
    memberships = pd.concat(
        [
            memberships,
            _frame("basket_memberships.parquet", [{
                "entity_id": "SYNTH_HBM_WATCH", "basket_id": "AI_BOTTLENECKS_GLOBAL",
                "membership_tier": "watch_only", "primary_layer": "advanced_packaging_test",
                "secondary_layers": "hbm_memory", "active_from": "2026-01-01", "registry_version": "v1",
            }]),
        ],
        ignore_index=True,
    )
    frames["basket_memberships.parquet"] = memberships

    events = frames["events.parquet"]
    old_event_id = "AI_HBM4_QUALIFICATION_WINDOW"
    new_event_id = "AI_HBM4_QUALIFICATION_WINDOW_V2"
    events.loc[events["event_id"].eq("EV_HARD"), ["event_id", "event_key", "title", "description", "starts_at", "ends_at", "certainty_class", "source_id", "source_url", "evidence_class"]] = [
        old_event_id, old_event_id, "HBM4 customer qualification window", "Synthetic HBM4 qualification evidence.",
        "2026-08-20T00:00:00Z", "2026-08-25T00:00:00Z", "thesis_checkpoint", "research_control_tower_v1_thesis", "", "internal_research",
    ]
    events.loc[events["event_id"].eq("EV_THESIS"), ["event_id", "event_key", "title", "description", "starts_at", "ends_at", "certainty_class", "source_id", "source_url", "evidence_class", "supersedes_event_id"]] = [
        new_event_id, new_event_id, "HBM4 customer qualification window revised observation", "Synthetic revised HBM4 qualification evidence.",
        "2026-08-20T00:00:00Z", "2026-08-25T00:00:00Z", "thesis_checkpoint", "research_control_tower_v1_thesis", "", "internal_research", old_event_id,
    ]
    frames["events.parquet"] = events

    entity_links = frames["event_entity_links.parquet"]
    entity_links.loc[entity_links["event_id"].eq("EV_HARD"), "event_id"] = old_event_id
    entity_links.loc[entity_links["event_id"].eq(old_event_id), "target_id"] = entity_links.loc[entity_links["event_id"].eq(old_event_id), "target_id"].replace({"E1": "SK_HYNIX", "L1": "000660_KR"})
    entity_links.loc[entity_links["event_id"].eq("EV_THESIS"), ["event_id", "target_id"]] = [new_event_id, "SK_HYNIX"]
    frames["event_entity_links.parquet"] = entity_links

    basket_links = frames["event_basket_links.parquet"]
    basket_links.loc[basket_links["event_id"].eq("EV_HARD"), "event_id"] = old_event_id
    basket_links = pd.concat(
        [basket_links, _frame("event_basket_links.parquet", [{
            "event_id": new_event_id, "target_type": "basket", "target_id": "AI_BOTTLENECKS_GLOBAL",
            "link_role": "primary", "automated": True, "registry_version": "v1",
        }])],
        ignore_index=True,
    )
    frames["event_basket_links.parquet"] = basket_links

    questions = frames["event_watch_questions.parquet"]
    questions.loc[questions["event_id"].eq("EV_HARD"), "event_id"] = new_event_id
    questions = pd.concat(
        [
            questions,
            _frame("event_watch_questions.parquet", [{
                "event_id": old_event_id, "question_id": "HBM_OLD_Q", "question": "Was the earlier qualification observation superseded?",
                "question_type": "support", "priority": 2, "registry_version": "v1",
            }, {
                "event_id": new_event_id, "question_id": "HBM_NEW_Q", "question": "Does customer qualification support the HBM4 thesis?",
                "question_type": "support", "priority": 1, "registry_version": "v1",
            }]),
        ],
        ignore_index=True,
    )
    frames["event_watch_questions.parquet"] = questions

    documents = frames["news_filings.parquet"]
    documents.loc[documents["document_id"].eq("D1"), ["source_id", "headline", "publisher", "source_url", "related_entity_ids", "pit_class", "source_license_class", "derived_summary_if_permitted"]] = [
        "official:sk_hynix", "SK Hynix synthetic official metadata fixture", "SK Hynix IR metadata fixture",
        "https://example.test/synthetic/sk-hynix", "SK_HYNIX", "true_pit", "official_public", "Metadata-only synthetic acceptance row.",
    ]
    frames["news_filings.parquet"] = documents

    consensus = frames["consensus_snapshots.parquet"]
    consensus.loc[consensus["snapshot_id"].eq("S1"), ["provider", "entity_id", "listing_id", "financial_data_security_id", "canonical_ticker", "source_url", "pit_class", "source_run_id", "calculation_origin", "coverage_reason"]] = [
        "yfinance", "SK_HYNIX", "000660_KR", "000660_KR", "000660.KS", "https://example.test/synthetic/yfinance", "snapshot_from_live_source", "synthetic-yf-run-1", "synthetic_fixture", "synthetic provider row",
    ]
    secondary_consensus = consensus.iloc[0].copy()
    secondary_consensus[["snapshot_id", "listing_id", "canonical_ticker", "value"]] = ["S2", "000660_US", "000660.US", 1.3]
    consensus = pd.concat([consensus, pd.DataFrame([secondary_consensus])], ignore_index=True)
    frames["consensus_snapshots.parquet"] = consensus

    revisions = frames["consensus_revisions.parquet"]
    revisions.loc[revisions["revision_id"].eq("R1"), ["snapshot_id", "provider", "prior_provider", "entity_id", "listing_id", "financial_data_security_id", "canonical_ticker", "prior_provider_asof", "provider_asof", "retrieved_at_utc", "source_url", "pit_class", "source_run_id", "alignment_status"]] = [
        "S1", "yfinance", "yfinance", "SK_HYNIX", "000660_KR", "000660_KR", "000660.KS",
        "2026-08-01T00:00:00Z", "2026-08-13T11:00:00Z", "2026-08-13T11:30:00Z", "https://example.test/synthetic/yfinance", "snapshot_from_live_source", "synthetic-yf-run-1", "comparable",
    ]
    frames["consensus_revisions.parquet"] = revisions

    health = frames["source_health.parquet"]
    health.loc[health["source_id"].eq("source:research"), ["source_id", "source_kind", "status", "retrieved_at_utc", "source_license_class", "detail"]] = [
        "research_control_tower_v1_thesis", "research", "available", "2026-08-13T11:00:00Z", "internal_research", "synthetic internal research; source link unavailable",
    ]
    health = pd.concat(
        [
            health,
            _frame("source_health.parquet", [
                {"source_id": "provider:yfinance", "source_kind": "consensus_provider", "status": "available", "row_count": 2, "latest_observation_at": "2026-08-13T11:00:00Z", "source_latest_at": "2026-08-13T11:00:00Z", "retrieved_at_utc": "2026-08-13T11:30:00Z", "cadence": "daily", "source_url": "https://example.test/synthetic/yfinance", "pit_class": "snapshot_from_live_source", "source_license_class": "public_metadata", "schema_version": "v1", "detail": "synthetic yfinance provider"},
                {"source_id": "provider:akshare", "source_kind": "consensus_provider", "status": "unavailable", "cadence": "irregular", "schema_version": "v1", "detail": "synthetic fixture: akshare export unavailable"},
                {"source_id": "provider:fnguide", "source_kind": "consensus_provider", "status": "unavailable", "cadence": "irregular", "schema_version": "v1", "detail": "synthetic fixture: FnGuide export unavailable"},
                {"source_id": "provider:futu", "source_kind": "consensus_provider", "status": "unavailable", "cadence": "irregular", "schema_version": "v1", "detail": "synthetic fixture: Futu export unavailable"},
            ]),
        ],
        ignore_index=True,
    )
    frames["source_health.parquet"] = health

    for name, frame in frames.items():
        table = pa.Table.from_pandas(_typed(frame), schema=_schema(name), preserve_index=False, safe=False)
        pq.write_table(table, root / name)
    _write_manifest(root, _manifest(root, previous_build_at="2026-08-13T10:00:00Z"))


def _rewrite_manifest(root: Path, mutate) -> None:
    path = root / "build_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    mutate(manifest)
    _write_manifest(root, manifest)


def _write_typed_artifact(root: Path, name: str, frame: pd.DataFrame) -> None:
    table = pa.Table.from_pandas(
        _typed(frame),
        schema=_schema(name),
        preserve_index=False,
        safe=False,
    )
    pq.write_table(table, root / name)


@pytest.fixture(autouse=True)
def _imports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(APP_ROOT))


@pytest.fixture()
def generated_root(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    _write_bundle(root)
    return root


def _snapshot(root: Path):
    from control_tower.repository import ControlTowerRepository

    return ControlTowerRepository(root).load_snapshot()


def _app_text(app) -> str:
    pieces: list[str] = []
    for attr in ("title", "header", "subheader", "caption", "markdown", "info", "warning", "error", "text"):
        for item in getattr(app, attr, []):
            value = getattr(item, "value", "")
            if isinstance(value, str):
                pieces.append(value)
    return "\n".join(pieces)


def test_today_is_change_driven_and_initial_snapshot_is_typed(generated_root: Path) -> None:
    from control_tower.pages.today import select_today_changes

    snapshot = _snapshot(generated_root)
    changes = select_today_changes(snapshot)
    assert not changes.empty
    assert set(changes["event_id"]) >= {"EV_HARD", "EV_THESIS", "EV_PROVISIONAL"}
    assert "EV_PREBUILD" not in set(changes["event_id"])
    assert changes["changed_at"].dt.tz is not None

    _rewrite_manifest(generated_root, lambda manifest: manifest.update({"previous_build_at": None}))
    initial = _snapshot(generated_root)
    initial_changes = select_today_changes(initial)
    assert initial_changes.empty
    assert list(initial_changes.columns) == list(changes.columns)


def test_next_catalyst_prefers_explicit_high_importance() -> None:
    from control_tower.components.timeline import select_next_catalyst

    events = pd.DataFrame([
        {"event_id": "low", "event_type": "earnings", "status": "scheduled", "certainty_class": "thesis_checkpoint", "importance": "low", "starts_at": "2026-08-14T00:00:00Z", "ends_at": "2026-08-15T00:00:00Z"},
        {"event_id": "high", "event_type": "earnings", "status": "scheduled", "certainty_class": "hard", "importance": "high", "starts_at": "2026-08-20T00:00:00Z", "ends_at": "2026-08-20T00:00:00Z"},
    ])
    row = select_next_catalyst(events, pd.Timestamp("2026-08-13T00:00:00Z"))
    assert row is not None
    assert row["event_id"] == "high"


def test_timeline_groups_horizon_excludes_gap_and_preserves_metadata(generated_root: Path) -> None:
    from control_tower.components.timeline import group_timeline_events
    from control_tower.models import EventFilters
    from control_tower.pages.unified_timeline import build_timeline_view
    from control_tower.filters import apply_event_filters

    snapshot = _snapshot(generated_root)
    filtered = apply_event_filters(snapshot.events, EventFilters(horizon="30d", now_utc=snapshot.now_utc))
    assert "EV_GAP" not in set(filtered["event_id"])
    groups = group_timeline_events(filtered, now_utc=snapshot.now_utc, viewer_timezone="Europe/London")
    assert groups and all(group.month_key == "2026-08" for group in groups)
    view = build_timeline_view(snapshot, filters=EventFilters(horizon="30d", now_utc=snapshot.now_utc), viewer_timezone="Europe/London")
    hard = next(event for group in view.month_groups for event in group.events if event.event_id == "EV_HARD")
    assert hard.t_minus == "T-7d"
    assert hard.source_badges[0].pit_class == "true_pit"
    assert hard.watch_questions[0].startswith("Support:")
    assert hard.ticker_chips
    assert any("EONE" in chip.label and "NASDAQ" in chip.label for chip in hard.ticker_chips)
    assert "L1" not in {chip.label for chip in hard.ticker_chips}


def test_visible_metadata_and_importance_are_not_raw_ids(generated_root: Path) -> None:
    from control_tower.components.timeline import catalyst_html, catalyst_view_for_event

    snapshot = _snapshot(generated_root)
    row = snapshot.events.loc[snapshot.events["event_id"].eq("EV_HARD")].iloc[0]
    view = catalyst_view_for_event(snapshot, row, now_utc=snapshot.now_utc, viewer_timezone="Europe/London")
    assert view is not None
    html = catalyst_html(view, viewer_timezone="Europe/London")
    assert "EONE" in html and "NASDAQ" in html and "core" in html
    assert "Importance · high" in html
    assert "Source published" in html and "Retrieved" in html and "Last verified" in html


def test_consensus_schema_is_task4_29_and_35_and_priority_is_string(generated_root: Path) -> None:
    from control_tower.config import ARTIFACT_COLUMNS
    from control_tower.repository import ControlTowerRepository

    snapshot = _snapshot(generated_root)
    assert len(ARTIFACT_COLUMNS["consensus_snapshots.parquet"]) == 29
    assert len(ARTIFACT_COLUMNS["consensus_revisions.parquet"]) == 35
    assert len(snapshot.consensus_snapshots.columns) == 29
    assert len(snapshot.consensus_revisions.columns) == 35
    assert snapshot.event_watch_questions["priority"].dtype.name in {"string", "object"}
    assert not ControlTowerRepository(generated_root).load_snapshot().consensus_revisions.empty


def test_supersession_and_selected_universe_never_fall_back_to_all(generated_root: Path) -> None:
    from control_tower.models import EventFilters
    from control_tower.pages.today import build_today_view

    snapshot = _snapshot(generated_root)
    events = snapshot.events.copy()
    older = events.loc[events["event_id"].eq("EV_HARD")].iloc[0].copy()
    older["event_id"] = "EV_OLD"
    older["first_observed_at"] = "2026-08-13T10:30:00Z"
    newer = older.copy()
    newer["event_id"] = "EV_NEW"
    newer["supersedes_event_id"] = "EV_OLD"
    newer["first_observed_at"] = "2026-08-13T11:30:00Z"
    snapshot = replace(snapshot, events=pd.concat([events, pd.DataFrame([older, newer])], ignore_index=True))
    delta = __import__("control_tower.pages.today", fromlist=["select_today_changes"]).select_today_changes(snapshot)
    assert "EV_OLD" not in set(delta["event_id"])
    assert "EV_NEW" in set(delta["event_id"])

    filtered = build_today_view(snapshot, filters=EventFilters(basket_id=("DOES_NOT_EXIST",), now_utc=snapshot.now_utc), viewer_timezone="Europe/London")
    assert filtered.consensus_revisions.empty
    assert filtered.official_filings.empty
    assert filtered.guidance_changes.empty
    assert filtered.changes.empty


def test_scope_applicability_hides_company_data_without_fabricating_event_semantics(
    generated_root: Path,
) -> None:
    from control_tower.models import EventFilters
    from control_tower.pages.today import build_today_view

    snapshot = _snapshot(generated_root)
    macro_only = build_today_view(
        snapshot,
        filters=EventFilters(scope=("macro",), now_utc=snapshot.now_utc),
        viewer_timezone="Europe/London",
    )
    assert macro_only.consensus_revisions.empty
    assert macro_only.official_filings.empty
    assert macro_only.guidance_changes.empty
    assert not macro_only.source_alerts.empty
    assert not set(macro_only.changes["change_kind"]) & {
        "consensus_revision",
        "official_filing",
        "guidance_change",
    }

    # Event-ledger semantics do not get invented for provider revisions or
    # filings: these families remain present when company scope is selected.
    event_semantics = build_today_view(
        snapshot,
        filters=EventFilters(
            scope=("company",),
            status=("observed",),
            certainty_class=("observed",),
            importance=("low",),
            confidence_min=0.95,
            now_utc=snapshot.now_utc,
        ),
        viewer_timezone="Europe/London",
    )
    assert not event_semantics.consensus_revisions.empty
    assert not event_semantics.official_filings.empty

    empty_universe = build_today_view(
        snapshot,
        filters=EventFilters(
            basket_id=("DOES_NOT_EXIST",),
            scope=("company",),
            now_utc=snapshot.now_utc,
        ),
        viewer_timezone="Europe/London",
    )
    assert empty_universe.consensus_revisions.empty
    assert empty_universe.official_filings.empty
    assert empty_universe.guidance_changes.empty
    assert empty_universe.changes.empty


def test_revision_display_joins_snapshot_metadata_by_provider_and_fails_closed(
    generated_root: Path,
) -> None:
    from control_tower.pages.today import (
        _table_cell_text,
        enrich_consensus_revisions,
    )

    snapshot = _snapshot(generated_root)
    snapshots = snapshot.consensus_snapshots.copy()
    wrong_provider = snapshots.iloc[0].copy()
    wrong_provider["provider"] = "other-provider"
    wrong_provider["currency"] = "EUR"
    wrong_provider["unit"] = "wrong-unit"
    snapshots = pd.concat(
        [snapshots, pd.DataFrame([wrong_provider])],
        ignore_index=True,
    )

    revisions = snapshot.consensus_revisions.copy()
    revisions["current_analyst_count"] = pd.NA
    enriched = enrich_consensus_revisions(revisions, snapshots)
    row = enriched.iloc[0]
    assert row["provider"] == "fixture"
    assert row["currency"] == "USD"
    assert row["unit"] == "per_share"
    assert row["current_analyst_count"] == 4
    assert row["provider_contributor_count"] == 6

    missing = revisions.copy()
    missing["snapshot_id"] = "S-MISSING"
    unavailable = enrich_consensus_revisions(missing, snapshots).iloc[0]
    assert pd.isna(unavailable["currency"])
    assert pd.isna(unavailable["unit"])
    assert pd.isna(unavailable["provider_contributor_count"])
    assert _table_cell_text(
        "currency", unavailable["currency"], "Europe/London"
    ) == "Unavailable"
    assert _table_cell_text(
        "unit", unavailable["unit"], "Europe/London"
    ) == "Unavailable"


def test_current_is_resolved_once_before_cache_fingerprint_and_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from control_tower.config import artifact_fingerprint
    import streamlit as st

    publication = tmp_path / "publication"
    generations = publication / "generations"
    generations.mkdir(parents=True)
    first = generations / "gen-001"
    second = generations / "gen-002"
    _write_bundle(first)
    _write_bundle(second)
    _rewrite_manifest(
        second,
        lambda manifest: manifest.update({"build_id": "task6-fixture-002"}),
    )
    current = publication / "CURRENT"
    current.write_text("generations/gen-001\n", encoding="utf-8")
    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(publication))

    spec = importlib.util.spec_from_file_location(
        "task6_app_current_switch",
        APP_PATH,
    )
    assert spec is not None and spec.loader is not None
    task6_app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(task6_app)

    pinned_root = task6_app.configured_artifact_root()
    assert pinned_root == first.resolve()
    current.write_text("generations/gen-002\n", encoding="utf-8")

    st.cache_data.clear()
    fingerprint = artifact_fingerprint(pinned_root)
    loaded = task6_app.load_snapshot_cached(str(pinned_root), fingerprint)
    assert loaded.build_id == "task6-fixture-001"
    assert task6_app.configured_artifact_root() == second.resolve()


def test_task4_consensus_columns_and_repository_typed_empty_contract(generated_root: Path) -> None:
    from control_tower.config import ARTIFACT_COLUMNS
    from control_tower.repository import ControlTowerRepository

    producer_path = Path(__file__).resolve().parents[2] / "financial-data" / "src" / "hk_financials" / "control_tower_export.py"
    if producer_path.exists():
        spec = importlib.util.spec_from_file_location("task4_control_tower_export", producer_path)
        assert spec is not None and spec.loader is not None
        producer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(producer)
        assert tuple(producer.SNAPSHOT_COLUMNS) == ARTIFACT_COLUMNS["consensus_snapshots.parquet"]
        assert tuple(producer.REVISION_COLUMNS) == ARTIFACT_COLUMNS["consensus_revisions.parquet"]
    _rewrite_manifest(generated_root, lambda manifest: (
        manifest["artifacts"]["consensus_snapshots.parquet"].update({"status": "unavailable", "sha256": None, "row_count": 0, "byte_size": 0}),
        manifest["artifacts"]["consensus_revisions.parquet"].update({"status": "unavailable", "sha256": None, "row_count": 0, "byte_size": 0}),
        manifest.update({"status": "degraded", "degraded_inputs": ["consensus_snapshots", "consensus_revisions"]}),
    ))
    snapshot = ControlTowerRepository(generated_root).load_snapshot()
    assert snapshot.consensus_snapshots.empty and len(snapshot.consensus_snapshots.columns) == 29
    assert snapshot.consensus_revisions.empty and len(snapshot.consensus_revisions.columns) == 35


def test_app_navigation_buttons_filters_persist_and_network_write_guards(generated_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(generated_root))
    calls: list[str] = []

    def block_network(kind: str):
        def blocked(*args, **kwargs):
            calls.append(kind)
            raise AssertionError(f"network called through {kind}")

        return blocked

    monkeypatch.setattr(socket.socket, "connect", block_network("socket.connect"))
    monkeypatch.setattr(
        socket,
        "create_connection",
        block_network("socket.create_connection"),
    )
    monkeypatch.setattr(socket, "getaddrinfo", block_network("dns.getaddrinfo"))
    monkeypatch.setattr(socket, "gethostbyname", block_network("dns.gethostbyname"))
    monkeypatch.setattr(socket, "gethostbyaddr", block_network("dns.gethostbyaddr"))
    monkeypatch.setattr(socket, "getnameinfo", block_network("dns.getnameinfo"))
    monkeypatch.setattr(urllib.request, "urlopen", block_network("urllib.urlopen"))
    monkeypatch.setattr(
        urllib.request.OpenerDirector,
        "open",
        block_network("urllib.opener.open"),
    )
    try:
        import requests
    except ImportError:
        requests = None
    if requests is not None:
        monkeypatch.setattr(
            requests.sessions.Session,
            "request",
            block_network("requests"),
        )

    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in generated_root.iterdir()}
    st.cache_data.clear()
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    assert app.expander
    assert any("Filters" in str(item.label) for item in app.expander)
    assert "Filter applicability" in _app_text(app)

    horizon = next(item for item in app.selectbox if item.label == "Horizon")
    app = horizon.select("7d").run()
    assert not app.exception
    assert app.session_state["ct_horizon"] == "7d"
    assert "Confirmed high-priority print" in _app_text(app)
    assert "Provisional date" not in _app_text(app)

    horizon = next(item for item in app.selectbox if item.label == "Horizon")
    app = horizon.select("90d").run()
    assert not app.exception
    assert app.session_state["ct_horizon"] == "90d"
    assert "Confirmed high-priority print" in _app_text(app)
    assert "Far catalyst" not in _app_text(app)

    horizon = next(item for item in app.selectbox if item.label == "Horizon")
    app = horizon.select("long_range").run()
    assert not app.exception
    assert app.session_state["ct_horizon"] == "long_range"
    assert "Far catalyst" in _app_text(app)

    scope = next(item for item in app.multiselect if item.label == "Scope")
    app = scope.select("macro").run()
    assert not app.exception
    assert "macro" in app.session_state["ct_scopes"]

    # The button is exercised through AppTest's actual widget event API.
    timeline_button = next(button for button in app.sidebar.button if button.label == "Unified Timeline")
    timeline_button.click().run()
    assert not app.exception
    assert app.session_state["ct_page"] == "Unified Timeline"
    assert app.session_state["ct_horizon"] == "long_range"
    assert "macro" in app.session_state["ct_scopes"]
    assert not calls
    after = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in generated_root.iterdir()}
    assert before == after


def test_app_shell_today_timeline_and_filters_are_reachable(generated_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(generated_root))
    import streamlit as st

    st.cache_data.clear()
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in generated_root.iterdir()}
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    assert set(app.session_state["page_labels"]) == {"Today", "Unified Timeline", "AI Bottlenecks", "Company", "Source Health"}
    assert app.session_state["ct_page"] == "Today"
    assert "Research Control Tower" in _app_text(app)
    assert "Initial snapshot" not in _app_text(app)

    app.session_state["ct_page"] = "Unified Timeline"
    app = app.run()
    assert not app.exception
    assert app.session_state["ct_page"] == "Unified Timeline"
    assert "Unified timeline" in _app_text(app)

    app.session_state["ct_page"] = "Company"
    app = app.run()
    assert not app.exception
    company_text = _app_text(app)
    assert "Selected listing · EONE · NASDAQ · USD · primary listing default" in company_text
    assert "Selected listing · L1" not in company_text


def test_control_tower_theme_css_is_explicit_and_native_controls_are_covered() -> None:
    from control_tower.components import get_control_tower_css

    light_css = get_control_tower_css("Light")
    dark_css = get_control_tower_css("Dark")

    assert "prefers-color-scheme" not in light_css
    assert "prefers-color-scheme" not in dark_css
    assert "background-color: #ffffff" in light_css
    assert "background-color: #0e1117" in dark_css
    assert '[data-baseweb="popover"]' in dark_css
    assert '[data-testid="stExpander"] summary' in dark_css
    assert "#f6c453" in dark_css


def test_app_defaults_to_stage1_focus_for_the_published_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(PRODUCTION_TASK7_PUBLICATION))
    import streamlit as st

    st.cache_data.clear()
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    assert app.session_state["ct_basket_ids"] == ("RESEARCH_STAGE_1_CHINA_INTERNET",)
    assert "Stage 1 · China Internet" in _app_text(app)


def test_task10_data_coverage_reports_presence_without_fabricating_linkage(
    generated_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from control_tower.coverage import (
        _is_non_empty_relation,
        build_data_coverage_summary,
    )
    from streamlit.testing.v1 import AppTest

    assert not _is_non_empty_relation("[]")
    assert not _is_non_empty_relation(" [ ] ")
    assert not _is_non_empty_relation([])
    assert _is_non_empty_relation('["E1"]')
    assert _is_non_empty_relation(("E1",))

    snapshot = _snapshot(generated_root)
    summary = build_data_coverage_summary(snapshot)
    rows = {row.category: row for row in summary.rows}
    assert rows["Price / Market Bars"].status_code == "unavailable"
    assert rows["Earnings Actuals"].status_code == "partial"
    assert rows["Earnings Actuals"].record_count == 1
    assert rows["Earnings Actuals"].linked_count == 1
    assert "mart does not exist" not in rows["Earnings Actuals"].details.lower()
    assert rows["Consensus Data"].record_count == 2
    assert rows["Consensus Data"].linked_count == 2
    assert rows["News & Filings"].linked_count == 2
    assert rows["Alternative Evidence / Events"].linked_count == 2

    unlinked_news = snapshot.news_filings.copy()
    for column in (
        "related_entity_ids",
        "related_listing_ids",
        "related_basket_ids",
    ):
        unlinked_news[column] = "[]"
    unlinked_official = snapshot.official_filings.copy()
    for column in ("entity_id", "listing_id"):
        if column in unlinked_official.columns:
            unlinked_official[column] = ""
    unlinked_summary = build_data_coverage_summary(
        replace(snapshot, news_filings=unlinked_news, official_filings=unlinked_official)
    )
    news_row = next(
        row for row in unlinked_summary.rows if row.category == "News & Filings"
    )
    assert news_row.status_code == "partial"
    assert news_row.linked_count == 0
    assert "0 carry" in news_row.details

    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in generated_root.iterdir()
    }
    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(generated_root))
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    rendered = _app_text(app)
    assert "Data coverage" in rendered
    assert "Price / Market Bars" in rendered
    assert "No price or market-bars artifact" in rendered
    assert "This is evidence coverage, not a trading signal" in rendered
    after = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in generated_root.iterdir()}
    assert before == after


def test_initial_app_mode_and_optional_degraded_mode(generated_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    _rewrite_manifest(generated_root, lambda manifest: manifest.update({"previous_build_at": None}))
    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(generated_root))
    st.cache_data.clear()
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    assert "Initial snapshot" in _app_text(app)
    assert "changed since" not in _app_text(app).lower()

    degraded_root = generated_root.parent / "degraded"
    shutil.copytree(generated_root, degraded_root)
    _rewrite_manifest(degraded_root, lambda manifest: (
        manifest["artifacts"]["news_filings.parquet"].update({"status": "unavailable", "sha256": None, "row_count": 0, "byte_size": 0}),
        manifest.update({"status": "degraded", "degraded_inputs": ["news_filings"]}),
    ))
    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(degraded_root))
    st.cache_data.clear()
    degraded = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not degraded.exception
    assert "Degraded data coverage" in _app_text(degraded)
    assert "No eligible catalyst" not in _app_text(degraded) or "Unified timeline" in _app_text(degraded)


def test_task7_theme_summary_is_registry_only_and_keeps_explicit_layers(generated_root: Path) -> None:
    from control_tower.pages.ai_bottlenecks import build_theme_summary

    snapshot = _snapshot(generated_root)
    summary = build_theme_summary(snapshot, "HBM_MEMORY")
    assert list(summary.members.columns) == [
        "entity_id", "display_name", "country", "basket_id", "membership_tier",
        "primary_layer", "secondary_layers", "member_role", "listing_ids",
        "verified_listing_ids", "collection_eligible", "latest_evidence_at",
        "evidence_count", "evidence_status", "consensus_status",
    ]
    assert summary.unavailable_reasons == ("no_matching_members",)
    assert summary.relationships.empty


def test_task7_company_view_fails_closed_for_unknown_company(generated_root: Path) -> None:
    from control_tower.pages.company import build_company_view

    snapshot = _snapshot(generated_root)
    view = build_company_view(snapshot, entity_id="E1")
    assert view.selected_listing_id == "L1"
    assert view.selection_mode == "primary_default"
    assert set(view.listings["listing_id"]) == {"L1"}
    assert view.consensus_status == "available"
    assert not view.events.empty
    assert view.invalidation_evidence.empty
    with pytest.raises(ValueError, match="unknown entity_id"):
        build_company_view(snapshot, entity_id="MISSING")


def test_company_view_consumes_quote_snapshot_and_classifies_freshness(generated_root: Path) -> None:
    from control_tower.models import EventFilters
    from control_tower.pages.company import COMPANY_QUOTE_COLUMNS, build_company_view

    snapshot = _snapshot(generated_root)
    quote = _typed(_frame("quote_snapshots.parquet", [{
        "quote_id": "Q1",
        "listing_id": "L1",
        "canonical_ticker": "EONE",
        "provider_symbol": "EONE",
        "quote_timestamp": "2026-08-13T11:59:30Z",
        "retrieved_at_utc": "2026-08-13T12:00:00Z",
        "last_price": 123.45,
        "bid": 123.40,
        "ask": 123.50,
        "day_change_pct": 1.2,
        "volume": 1000.0,
        "currency": "USD",
        "market_status": "open",
        "latency_class": "realtime",
        "source_id": "fixture_quotes",
        "source_url": "https://example.test/quotes",
        "pit_class": "snapshot_from_live_source",
        "source_license_class": "public_metadata",
        "registry_version": "v1",
    }]))
    listings = snapshot.listings.copy()
    listings.loc[listings["listing_id"].eq("L1"), "vendor_tickers"] = "yfinance:EONE"
    snapshot = replace(snapshot, listings=listings, quote_snapshots=quote)

    view = build_company_view(snapshot, entity_id="E1")
    assert tuple(view.quote_snapshots.columns) == COMPANY_QUOTE_COLUMNS
    assert view.quote_status == "available"
    assert view.quote_snapshots.iloc[0]["last_price"] == 123.45
    assert view.quote_snapshots.iloc[0]["freshness"] == "delayed"
    assert view.quote_snapshots.iloc[0]["latency_class"] == "delayed"
    assert view.quote_snapshots.iloc[0]["pit_class"] == "snapshot_from_delayed_source"
    assert view.quote_snapshots.iloc[0]["source_license_class"] == "personal_use_terms_unverified"

    missing_registry_fields = quote.copy()
    missing_registry_fields.loc[:, ["canonical_ticker", "provider_symbol", "currency"]] = ""
    derived_view = build_company_view(
        replace(snapshot, quote_snapshots=missing_registry_fields), entity_id="E1"
    )
    derived_row = derived_view.quote_snapshots.iloc[0]
    assert derived_row["canonical_ticker"] == "EONE"
    assert derived_row["provider_symbol"] == "EONE"
    assert derived_row["currency"] == "USD"

    macro_only = build_company_view(
        snapshot,
        entity_id="E1",
        filters=EventFilters(
            scope=("macro",),
            now_utc=snapshot.now_utc,
        ),
    )
    assert macro_only.quote_snapshots.empty

def test_task9_company_view_respects_global_scope_and_country_filters(generated_root: Path) -> None:
    from control_tower.models import EventFilters
    from control_tower.pages.company import _filtered_entity_ids, build_company_view

    snapshot = _snapshot(generated_root)
    country_filter = EventFilters(country=("US",), now_utc=snapshot.now_utc)
    assert _filtered_entity_ids(snapshot, country_filter) == {"E1"}

    macro_only = build_company_view(
        snapshot,
        entity_id="E1",
        filters=EventFilters(scope=("macro",), now_utc=snapshot.now_utc),
    )
    assert macro_only.events.empty
    assert macro_only.consensus.empty
    assert macro_only.consensus_revisions.empty
    assert macro_only.official_documents.empty


def test_task7_source_health_marks_stale_and_retrieval_only_not_healthy() -> None:
    from control_tower.pages.source_health import classify_source_health

    frame = pd.DataFrame([
        {
            "source_id": "fresh",
            "status": "available",
            "cadence": "daily",
            "source_latest_at": "2026-08-12T00:00:00Z",
            "pit_class": "true_pit",
            "source_license_class": "official_public",
        },
        {
            "source_id": "stale",
            "status": "available",
            "cadence": "daily",
            "source_latest_at": "2026-08-01T00:00:00Z",
            "pit_class": "not_pit",
            "source_license_class": "discovery",
        },
        {
            "source_id": "retrieval",
            "status": "available",
            "cadence": "daily",
            "retrieved_at_utc": "2026-08-13T00:00:00Z",
            "source_license_class": "restricted_body",
        },
    ])
    result = classify_source_health(frame, now_utc=pd.Timestamp("2026-08-13T00:00:00Z"))
    assert set(result["source_id"]) == {"fresh", "stale", "retrieval"}
    assert result.loc[result["source_id"].eq("stale"), "display_status"].item() == "stale"
    assert result.loc[result["source_id"].eq("retrieval"), "display_status"].item() != "healthy"
    assert result.loc[result["source_id"].eq("retrieval"), "age_basis"].item() == "retrieval_only"
    assert result.loc[result["source_id"].eq("stale"), "pit_display"].item() == "not_pit"
    assert result.loc[result["source_id"].eq("retrieval"), "license_display"].item() == "Restricted body · metadata only"

def test_task7_app_reaches_research_and_data_pages_without_writes(generated_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(generated_root))
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in generated_root.iterdir()}
    for page in ("AI Bottlenecks", "Company", "Source Health"):
        st.cache_data.clear()
        app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
        assert not app.exception
        app.session_state["ct_page"] = page
        app = app.run()
        assert not app.exception
        assert page in _app_text(app)
    after = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in generated_root.iterdir()}
    assert before == after


PRODUCTION_TASK7_PUBLICATION = APP_ROOT / ".generated"


def _production_task7_generation_or_skip() -> Path:
    from control_tower.config import (
        ARTIFACT_COLUMNS,
        DATA_ARTIFACT_NAMES,
        LEGACY_EARNINGS_ACTUALS_COLUMNS,
        LEGACY_DATA_ARTIFACT_NAMES,
        LEGACY_GENERATION_DATA_ARTIFACT_NAMES,
        resolve_artifact_root,
    )

    current = PRODUCTION_TASK7_PUBLICATION / "CURRENT"
    if not current.exists() and not current.is_symlink():
        pytest.skip(
            "Task 7 production acceptance requires "
            f"{current}; developer unit runs may omit the published CURRENT pointer"
        )

    resolution = resolve_artifact_root(PRODUCTION_TASK7_PUBLICATION)
    assert resolution.current_path == current.resolve(strict=True)
    assert resolution.current_target is not None
    assert resolution.artifact_root == (
        PRODUCTION_TASK7_PUBLICATION / resolution.current_target
    ).resolve(strict=True)
    assert resolution.artifact_root.parent == (
        PRODUCTION_TASK7_PUBLICATION / "generations"
    ).resolve(strict=True)

    actual_data_artifact_names = {
        name
        for name in DATA_ARTIFACT_NAMES
        if (resolution.artifact_root / name).exists()
    }
    accepted_artifact_sets = (
        set(DATA_ARTIFACT_NAMES),
        set(LEGACY_DATA_ARTIFACT_NAMES),
        set(LEGACY_GENERATION_DATA_ARTIFACT_NAMES),
    )
    assert actual_data_artifact_names in accepted_artifact_sets, (
        f"CURRENT publication {resolution.current_target} has an unsupported "
        f"artifact set: {sorted(actual_data_artifact_names)!r}"
    )

    for name in sorted(actual_data_artifact_names):
        actual_columns = tuple(pq.read_schema(resolution.artifact_root / name).names)
        accepted_columns = {
            ARTIFACT_COLUMNS[name],
            ARTIFACT_COLUMNS[name][:20] + (ARTIFACT_COLUMNS[name][-1],),
        }
        if name == "earnings_actuals.parquet":
            accepted_columns.add(LEGACY_EARNINGS_ACTUALS_COLUMNS)
        assert actual_columns in accepted_columns, (
            f"CURRENT publication {resolution.current_target} has non-final "
            f"{name} schema: {actual_columns!r}"
        )

    entities = pd.read_parquet(resolution.artifact_root / "entities.parquet")
    listings = pd.read_parquet(resolution.artifact_root / "listings.parquet")
    memberships = pd.read_parquet(
        resolution.artifact_root / "basket_memberships.parquet"
    )
    assert entities["entity_id"].astype("string").eq("SK_HYNIX").any(), (
        f"CURRENT publication {resolution.current_target} has no SK_HYNIX entity"
    )
    sk_hynix_listing = listings.loc[
        listings["listing_id"].astype("string").eq("000660_KR")
    ]
    assert len(sk_hynix_listing) == 1, (
        f"CURRENT publication {resolution.current_target} must have exactly one "
        "000660_KR listing"
    )
    assert sk_hynix_listing["entity_id"].astype("string").item() == "SK_HYNIX"
    stage1_members = memberships.loc[
        memberships["basket_id"].astype("string").eq("RESEARCH_STAGE_1_CHINA_INTERNET")
    ]
    assert set(stage1_members["entity_id"].astype("string")) == {
        "ALIBABA", "TENCENT", "BAIDU", "KUAISHOU", "BILIBILI", "BYTEDANCE",
    }
    assert entities.set_index("entity_id").loc["BYTEDANCE", "entity_type"] == "private"
    actual_hbm = memberships.loc[
        memberships["basket_id"].astype("string").eq("AI_BOTTLENECKS_GLOBAL")
        & memberships["primary_layer"].astype("string").eq("hbm_memory")
    ]
    assert not actual_hbm.empty, (
        f"CURRENT publication {resolution.current_target} has no final HBM memberships"
    )
    assert actual_hbm["entity_id"].astype("string").eq("SK_HYNIX").any()
    return resolution.artifact_root


def test_task7_real_generation_acceptance_covers_registry_company_and_source_matrix() -> None:
    from control_tower.pages.ai_bottlenecks import build_theme_summary
    from control_tower.pages.company import (
        COMPANY_CONSENSUS_COLUMNS,
        COMPANY_REVISION_COLUMNS,
        build_company_view,
    )

    root = _production_task7_generation_or_skip()
    snapshot = _snapshot(root)
    hbm = build_theme_summary(snapshot, "HBM_MEMORY")
    assert {"core", "read_through"} <= set(hbm.members["membership_tier"])
    assert hbm.members.loc[
        hbm.members["entity_id"].eq("SK_HYNIX"), "primary_layer"
    ].item() == "hbm_memory"
    assert "AI_HBM4_QUALIFICATION_WINDOW_V2" in set(hbm.catalysts["event_id"])
    assert "AI_HBM4_QUALIFICATION_WINDOW" not in set(hbm.catalysts["event_id"])
    assert "AI_HBM4_QUALIFICATION_WINDOW" in set(hbm.evidence_changes["event_id"])
    old_lineage = hbm.evidence_changes.loc[
        hbm.evidence_changes["event_id"].eq("AI_HBM4_QUALIFICATION_WINDOW")
    ]
    assert old_lineage["detail"].astype("string").str.contains("superseded", case=False).any()

    packaging = build_theme_summary(snapshot, "advanced_packaging_test")
    assert {"core", "read_through", "watch_only"} <= set(packaging.members["membership_tier"])
    watch_ids = set(packaging.members.loc[packaging.members["membership_tier"].eq("watch_only"), "entity_id"])
    assert watch_ids
    assert not watch_ids.intersection(set(packaging.evidence_changes["entity_id"].dropna().astype("string")))
    assert not packaging.members.loc[packaging.members["membership_tier"].eq("watch_only"), "consensus_status"].isin(["available"]).any()

    company = build_company_view(snapshot, entity_id="SK_HYNIX")
    # The production fixture is an archived focus predecessor; Company must
    # reject it from the active public listing surface.
    assert company.listings.empty
    assert company.selected_listing_id is None
    assert company.memberships.loc[
        company.memberships["primary_layer"].eq("hbm_memory"), "membership_tier"
    ].eq("core").any()
    assert "AI_HBM4_QUALIFICATION_WINDOW_V2" in set(company.events["event_id"])
    assert "AI_HBM4_QUALIFICATION_WINDOW" not in set(company.events["event_id"])
    assert any("AI_HBM4_QUALIFICATION_WINDOW" in caveat for caveat in company.caveats)
    assert not company.watch_questions.empty
    assert tuple(company.consensus.columns) == COMPANY_CONSENSUS_COLUMNS
    assert tuple(company.consensus_revisions.columns) == COMPANY_REVISION_COLUMNS
    provider_ids = {value.casefold() for value in company.source_health["source_id"].astype("string")}
    # Every Task 3 provider must be represented, but not always under the same
    # id: the page synthesises "provider:<name>" only when the build supplied
    # no health row of its own. Once real consensus rows exist for a provider
    # the build emits "consensus:<name>", which is the better record -- the
    # synthetic placeholder is deliberately skipped. Assert the coverage, not
    # which of the two spellings a provider currently has.
    for provider in ("yfinance", "akshare", "fnguide", "futu"):
        assert {f"provider:{provider}", f"consensus:{provider}"} & provider_ids, (
            f"{provider} has no source-health row under either id form"
        )
    provider_statuses = company.source_health.loc[
        company.source_health["source_id"].astype("string").str.startswith("provider:")
    ]
    assert not provider_statuses.empty
    assert set(provider_statuses["status"]) <= {"available", "degraded", "unavailable", "stale", "failed", "conflicted", "review_required"}
    if company.official_documents.empty:
        assert "official_documents" in set(company.source_health["source_id"].astype("string"))

def test_task7_synthetic_populated_acceptance_uses_stable_sk_hynix_ids(tmp_path: Path) -> None:
    """Synthetic populated contract fixture; not a claim of production coverage."""

    from control_tower.pages.ai_bottlenecks import build_theme_summary
    from control_tower.pages.company import (
        COMPANY_CONSENSUS_COLUMNS,
        COMPANY_DOCUMENT_COLUMNS,
        COMPANY_EVENT_COLUMNS,
        COMPANY_INVALIDATION_COLUMNS,
        COMPANY_LISTING_COLUMNS,
        COMPANY_MEMBERSHIP_COLUMNS,
        COMPANY_QUESTION_COLUMNS,
        COMPANY_REVISION_COLUMNS,
        build_company_view,
    )

    root = tmp_path / "synthetic-populated-task7"
    _write_synthetic_populated_task7_bundle(root)
    snapshot = _snapshot(root)

    theme = build_theme_summary(snapshot, "HBM_MEMORY")
    assert {"core", "read_through"} <= set(theme.members["membership_tier"])
    assert theme.members.loc[theme.members["entity_id"].eq("SK_HYNIX"), "primary_layer"].item() == "hbm_memory"
    assert theme.members.loc[theme.members["entity_id"].eq("SYNTH_HBM_READ"), "member_role"].item() == "read_through_member"
    assert "advanced_packaging_test" in set(theme.relationships["secondary_layer"])

    default_view = build_company_view(snapshot, entity_id="SK_HYNIX")
    assert default_view.selected_listing_id == "000660_KR"
    assert default_view.selection_mode == "primary_default"
    assert set(default_view.listings["listing_id"]) == {"000660_KR", "000660_US"}
    assert not default_view.official_documents.empty
    assert set(default_view.consensus["provider"]) == {"yfinance"}
    assert set(default_view.consensus["listing_id"]) == {"000660_KR"}
    assert not default_view.consensus_revisions.empty
    assert not default_view.watch_questions.empty
    assert default_view.invalidation_evidence.empty
    assert tuple(default_view.listings.columns) == COMPANY_LISTING_COLUMNS
    assert tuple(default_view.memberships.columns) == COMPANY_MEMBERSHIP_COLUMNS
    assert tuple(default_view.events.columns) == COMPANY_EVENT_COLUMNS
    assert tuple(default_view.official_documents.columns) == COMPANY_DOCUMENT_COLUMNS
    assert tuple(default_view.consensus.columns) == COMPANY_CONSENSUS_COLUMNS
    assert tuple(default_view.consensus_revisions.columns) == COMPANY_REVISION_COLUMNS
    assert tuple(default_view.watch_questions.columns) == COMPANY_QUESTION_COLUMNS
    assert tuple(default_view.invalidation_evidence.columns) == COMPANY_INVALIDATION_COLUMNS
    assert {"provider:yfinance", "provider:akshare", "provider:fnguide", "provider:futu"} <= set(default_view.source_health["source_id"])
    assert default_view.source_health.loc[default_view.source_health["source_id"].eq("provider:fnguide"), "display_status"].item() == "unavailable"
    assert default_view.source_health.loc[default_view.source_health["source_id"].eq("provider:futu"), "display_status"].item() == "unavailable"
    assert "AI_HBM4_QUALIFICATION_WINDOW_V2" in set(default_view.events["event_id"])
    assert "AI_HBM4_QUALIFICATION_WINDOW" not in set(default_view.events["event_id"])

    secondary_view = build_company_view(snapshot, entity_id="SK_HYNIX", listing_id="000660_US")
    assert secondary_view.selected_listing_id == "000660_US"
    assert set(secondary_view.consensus["listing_id"]) == {"000660_US"}
    assert set(secondary_view.events["event_id"]) == set(default_view.events["event_id"])
    assert set(secondary_view.memberships["basket_id"]) == set(default_view.memberships["basket_id"])


def test_task7_theme_and_company_use_strict_half_open_link_overlap(tmp_path: Path) -> None:
    from control_tower.pages.ai_bottlenecks import build_theme_summary
    from control_tower.pages.company import build_company_view

    root = tmp_path / "synthetic-boundary-task7"
    _write_synthetic_populated_task7_bundle(root)
    snapshot = _snapshot(root)
    base_event = snapshot.events.loc[snapshot.events["event_id"].eq("AI_HBM4_QUALIFICATION_WINDOW_V2")].iloc[0].copy()
    base_link = snapshot.event_entity_links.loc[
        snapshot.event_entity_links["event_id"].eq("AI_HBM4_QUALIFICATION_WINDOW_V2")
        & snapshot.event_entity_links["target_id"].eq("SK_HYNIX")
    ].iloc[0].copy()

    cases = (
        ("event_end_equals_link_start", "2026-08-20T00:00:00Z", "2026-08-25T00:00:00Z", "2026-08-25", "2026-09-01"),
        ("event_start_equals_link_end", "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z", "2026-08-20", "2026-09-01"),
    )
    for suffix, starts_at, ends_at, active_from, active_to in cases:
        event_id = f"TASK7_BOUNDARY_{suffix}"
        event = base_event.copy()
        event["event_id"] = event_id
        event["event_key"] = event_id
        event["starts_at"] = starts_at
        event["ends_at"] = ends_at
        event["related_entity_ids"] = ()
        event["related_listing_ids"] = ()
        event["related_basket_ids"] = ()
        link = base_link.copy()
        link["event_id"] = event_id
        link["active_from"] = active_from
        link["active_to"] = active_to
        altered = replace(
            snapshot,
            events=pd.concat([snapshot.events, pd.DataFrame([event])], ignore_index=True),
            event_entity_links=pd.concat([snapshot.event_entity_links, pd.DataFrame([link])], ignore_index=True),
        )
        theme = build_theme_summary(altered, "HBM_MEMORY")
        company = build_company_view(altered, entity_id="SK_HYNIX")
        assert event_id not in set(theme.catalysts["event_id"])
        assert event_id not in set(theme.evidence_changes["event_id"])
        assert event_id not in set(company.events["event_id"])


def test_task7_date_event_without_end_uses_one_source_local_day(tmp_path: Path) -> None:
    from control_tower.pages.ai_bottlenecks import build_theme_summary
    from control_tower.pages.company import build_company_view

    root = tmp_path / "synthetic-date-boundary-task7"
    _write_synthetic_populated_task7_bundle(root)
    snapshot = _snapshot(root)
    base_event = snapshot.events.loc[
        snapshot.events["event_id"].eq("AI_HBM4_QUALIFICATION_WINDOW_V2")
    ].iloc[0].copy()
    base_link = snapshot.event_entity_links.loc[
        snapshot.event_entity_links["event_id"].eq("AI_HBM4_QUALIFICATION_WINDOW_V2")
        & snapshot.event_entity_links["target_id"].eq("SK_HYNIX")
    ].iloc[0].copy()

    events: list[pd.Series] = []
    links: list[pd.Series] = []
    for suffix, active_from, active_to in (
        ("overlap_aug20", "2026-08-20", "2026-08-21"),
        ("boundary_aug21", "2026-08-21", "2026-09-01"),
    ):
        event_id = f"TASK7_DATE_ONLY_{suffix}"
        event = base_event.copy()
        event["event_id"] = event_id
        event["event_key"] = event_id
        event["date_precision"] = "date"
        # This UTC instant is still Aug 20 in the declared source timezone.
        # The inferred end is Aug 21 00:00 America/New_York (04:00 UTC).
        event["starts_at"] = "2026-08-20T23:30:00Z"
        event["ends_at"] = pd.NaT
        event["source_timezone"] = "America/New_York"
        event["related_entity_ids"] = ()
        event["related_listing_ids"] = ()
        event["related_basket_ids"] = ()
        events.append(event)

        link = base_link.copy()
        link["event_id"] = event_id
        link["active_from"] = active_from
        link["active_to"] = active_to
        links.append(link)

    altered = replace(
        snapshot,
        events=pd.concat([snapshot.events, pd.DataFrame(events)], ignore_index=True),
        event_entity_links=pd.concat(
            [snapshot.event_entity_links, pd.DataFrame(links)], ignore_index=True
        ),
    )
    theme = build_theme_summary(altered, "HBM_MEMORY")
    company = build_company_view(altered, entity_id="SK_HYNIX")
    theme_ids = set(theme.catalysts["event_id"])
    company_ids = set(company.events["event_id"])

    assert "TASK7_DATE_ONLY_overlap_aug20" in theme_ids
    assert "TASK7_DATE_ONLY_overlap_aug20" in company_ids
    # The event end equals the Aug 21 link start after source-local
    # normalization, so strict half-open overlap excludes the association.
    assert "TASK7_DATE_ONLY_boundary_aug21" not in theme_ids
    assert "TASK7_DATE_ONLY_boundary_aug21" not in set(
        theme.evidence_changes["event_id"]
    )
    assert "TASK7_DATE_ONLY_boundary_aug21" not in company_ids


def test_task7_real_hbm_catalyst_retains_internal_source_metadata() -> None:
    from control_tower.pages.ai_bottlenecks import build_theme_summary

    root = _production_task7_generation_or_skip()
    summary = build_theme_summary(_snapshot(root), "HBM_MEMORY")
    catalyst = summary.catalysts.loc[summary.catalysts["event_id"].eq("AI_HBM4_QUALIFICATION_WINDOW_V2")].iloc[0]
    assert catalyst["pit_class"] == "not_pit"
    assert catalyst["source_license_class"] == "internal_research"
    assert catalyst["source_link_status"] == "unavailable"
    assert catalyst["source_url"] == ""
    assert catalyst["display_status"] == "not_pit"
    assert catalyst["source_health_status"] in {"unavailable", "not_pit"}


def test_task7_real_hbm_catalyst_render_discloses_not_pit_and_missing_link(monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    root = _production_task7_generation_or_skip()
    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(root))
    st.cache_data.clear()
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    app.session_state["ct_page"] = "AI Bottlenecks"
    app.session_state["ct_ai_layer"] = "hbm_memory"
    app = app.run()
    assert not app.exception
    rendered = _app_text(app)
    # The lineage line lists every pit_class present in the layer, so asserting
    # the literal "PIT not_pit" only passed while not_pit happened to sort
    # first. Wiring real FRED observations in made the line read
    # "PIT current_vintage, not_pit" -- the same disclosure, one position over.
    # Assert the disclosure, not its position.
    lineage = re.search(r"Lineage status[^\n]*", rendered)
    assert lineage is not None, "lineage status line is missing"
    assert "not_pit" in lineage.group(0)
    assert "Source link unavailable" in rendered


def test_task7_source_health_precedence_matrix() -> None:
    from control_tower.pages.source_health import classify_source_health

    now = pd.Timestamp("2026-08-13T00:00:00Z")
    rows = [
        {"source_id": "failed", "status": "failed", "source_latest_at": "2026-08-12T00:00:00Z"},
        {"source_id": "schema", "status": "schema_error", "source_latest_at": "2026-08-12T00:00:00Z"},
        {"source_id": "conflicted", "status": "conflicted", "source_latest_at": "2026-08-12T00:00:00Z"},
        {"source_id": "review", "status": "review_required", "source_latest_at": "2026-08-12T00:00:00Z"},
        {"source_id": "entitlement_required", "status": "entitlement_required", "entitlement_status": "missing", "source_latest_at": "2026-08-12T00:00:00Z"},
        {"source_id": "entitlement_denied", "status": "entitlement_denied", "entitlement_status": "denied", "source_latest_at": "2026-08-12T00:00:00Z"},
        {"source_id": "unavailable", "status": "unavailable", "source_latest_at": "2026-08-12T00:00:00Z"},
        {"source_id": "degraded", "status": "degraded", "source_latest_at": "2026-08-12T00:00:00Z"},
        {"source_id": "boundary", "status": "available", "cadence": "daily", "source_latest_at": "2026-08-10T00:00:00Z"},
        {"source_id": "stale", "status": "available", "cadence": "daily", "source_latest_at": "2026-08-09T23:59:59Z"},
        {"source_id": "future", "status": "available", "cadence": "daily", "source_latest_at": "2026-08-14T00:00:00Z"},
        {"source_id": "retrieval_only", "status": "available", "cadence": "daily", "retrieved_at_utc": "2026-08-13T00:00:00Z"},
        {"source_id": "missing_pit", "status": "available", "cadence": "daily", "source_latest_at": "2026-08-13T00:00:00Z", "pit_class": ""},
        {"source_id": "discovery", "status": "available", "cadence": "daily", "source_latest_at": "2026-08-13T00:00:00Z", "source_license_class": "discovery"},
        {"source_id": "restricted", "status": "available", "cadence": "daily", "source_latest_at": "2026-08-13T00:00:00Z", "source_license_class": "restricted_body"},
    ]
    result = classify_source_health(pd.DataFrame(rows), now_utc=now)
    statuses = result.set_index("source_id")["display_status"].to_dict()
    assert statuses == {
        "failed": "failed",
        "schema": "failed",
        "conflicted": "conflicted",
        "review": "review_required",
        "entitlement_required": "entitlement_error",
        "entitlement_denied": "entitlement_error",
        "unavailable": "unavailable",
        "degraded": "degraded",
        "boundary": "healthy",
        "stale": "stale",
        "future": "clock_skew",
        "retrieval_only": "unclassified",
        "missing_pit": "healthy",
        "discovery": "healthy",
        "restricted": "healthy",
    }
    labels = result.set_index("source_id")["display_label"].to_dict()
    assert labels["entitlement_required"] == "Entitlement required"
    assert labels["entitlement_denied"] == "Entitlement denied"
    assert labels["retrieval_only"].startswith("Available · Freshness not classified")
    assert result.loc[result["source_id"].eq("missing_pit"), "pit_display"].item() == "PIT unavailable"
    assert result.loc[result["source_id"].eq("discovery"), "license_display"].item() == "Discovery/context only"
    assert result.loc[result["source_id"].eq("restricted"), "license_display"].item() == "Restricted body · metadata only"
    empty = classify_source_health(pd.DataFrame(columns=["source_id", "status"]), now_utc=now)
    assert str(empty["age_at_utc"].dtype) == "datetime64[ns, UTC]"


def test_task7_theme_active_link_interval_excludes_watch_only_event() -> None:
    from control_tower.pages.ai_bottlenecks import build_theme_summary

    root = _production_task7_generation_or_skip()
    snapshot = _snapshot(root)
    baseline = build_theme_summary(snapshot, "advanced_packaging_test")
    watch_id = next(iter(set(baseline.members.loc[baseline.members["membership_tier"].eq("watch_only"), "entity_id"])))
    event = snapshot.events.iloc[0].copy()
    event["event_id"] = "TASK7_WATCH_ONLY_INTERVAL_EVENT"
    event["event_key"] = "TASK7_WATCH_ONLY_INTERVAL_EVENT"
    event["starts_at"] = snapshot.as_of_utc + pd.Timedelta(days=1)
    event["ends_at"] = snapshot.as_of_utc + pd.Timedelta(days=2)
    event["related_entity_ids"] = ()
    event["related_listing_ids"] = ()
    event["related_basket_ids"] = ()
    event["status"] = "scheduled"
    event["event_type"] = "thesis"
    events = pd.concat([snapshot.events, pd.DataFrame([event])], ignore_index=True)
    link = {column: pd.NA for column in snapshot.event_entity_links.columns}
    link.update({"event_id": "TASK7_WATCH_ONLY_INTERVAL_EVENT", "target_type": "entity", "target_id": watch_id, "active_from": "2030-01-01", "active_to": "2030-02-01", "link_role": "primary", "automated": True, "registry_version": "v1"})
    links = pd.concat([snapshot.event_entity_links, pd.DataFrame([link])], ignore_index=True)
    altered = replace(snapshot, events=events, event_entity_links=links)
    summary = build_theme_summary(altered, "advanced_packaging_test")
    assert "TASK7_WATCH_ONLY_INTERVAL_EVENT" not in set(summary.catalysts["event_id"])
    assert "TASK7_WATCH_ONLY_INTERVAL_EVENT" not in set(summary.evidence_changes["event_id"])


def _write_task8_region_filter_bundle(root: Path) -> None:
    """Add an explicit non-KR HBM event to exercise filtered projections."""

    _write_synthetic_populated_task7_bundle(root)
    snapshot = _snapshot(root)
    event = snapshot.events.iloc[0].copy()
    event_id = "TASK8_US_HBM_EVENT"
    event["event_id"] = event_id
    event["event_key"] = event_id
    event["title"] = "US-targeted HBM evidence"
    event["event_type"] = "thesis"
    event["status"] = "scheduled"
    event["starts_at"] = "2026-09-15T00:00:00Z"
    event["ends_at"] = "2026-09-16T00:00:00Z"
    event["supersedes_event_id"] = pd.NA
    event["related_entity_ids"] = ()
    event["related_listing_ids"] = ()
    event["related_basket_ids"] = ()

    entity_link = {column: pd.NA for column in snapshot.event_entity_links.columns}
    entity_link.update(
        {
            "event_id": event_id,
            "target_type": "entity",
            "target_id": "SYNTH_HBM_READ",
            "link_role": "primary",
            "automated": True,
            "active_from": "2026-01-01",
            "registry_version": "v1",
        }
    )
    basket_link = {column: pd.NA for column in snapshot.event_basket_links.columns}
    basket_link.update(
        {
            "event_id": event_id,
            "target_type": "basket",
            "target_id": "AI_BOTTLENECKS_GLOBAL",
            "link_role": "primary",
            "automated": True,
            "active_from": "2026-01-01",
            "registry_version": "v1",
        }
    )

    altered = replace(
        snapshot,
        events=pd.concat([snapshot.events, pd.DataFrame([event])], ignore_index=True),
        event_entity_links=pd.concat(
            [snapshot.event_entity_links, pd.DataFrame([entity_link])],
            ignore_index=True,
        ),
        event_basket_links=pd.concat(
            [snapshot.event_basket_links, pd.DataFrame([basket_link])],
            ignore_index=True,
        ),
    )
    for name, frame in {
        "events.parquet": altered.events,
        "event_entity_links.parquet": altered.event_entity_links,
        "event_basket_links.parquet": altered.event_basket_links,
    }.items():
        table = pa.Table.from_pandas(
            _typed(frame), schema=_schema(name), preserve_index=False, safe=False
        )
        pq.write_table(table, root / name)
    _write_manifest(root, _manifest(root, previous_build_at="2026-08-13T10:00:00Z"))


def test_task8_theme_region_filters_members_evidence_and_catalysts_consistently(
    tmp_path: Path,
) -> None:
    from control_tower.pages.ai_bottlenecks import build_theme_summary

    root = tmp_path / "task8-region-filter"
    _write_task8_region_filter_bundle(root)
    snapshot = _snapshot(root)

    kr = build_theme_summary(snapshot, "HBM_MEMORY", countries=("KR",))
    assert kr.member_count == 1
    assert set(kr.members["country"]) == {"KR"}
    assert set(kr.evidence_changes["entity_id"].dropna().astype("string")) == {
        "SK_HYNIX"
    }
    assert "TASK8_US_HBM_EVENT" not in set(kr.catalysts["event_id"])

    us = build_theme_summary(snapshot, "HBM_MEMORY", countries=("US",))
    assert set(us.members["entity_id"]) == {"SYNTH_HBM_READ"}
    assert set(us.evidence_changes["entity_id"].dropna().astype("string")) == {
        "SYNTH_HBM_READ"
    }
    assert "TASK8_US_HBM_EVENT" in set(us.catalysts["event_id"])


def test_task8_app_region_filter_renders_only_selected_theme_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    root = tmp_path / "task8-app-region-filter"
    _write_task8_region_filter_bundle(root)
    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(root))
    st.cache_data.clear()

    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    app.session_state["ct_page"] = "AI Bottlenecks"
    app = app.run()
    layer = next(item for item in app.selectbox if item.label == "Primary bottleneck layer")
    app = layer.select("hbm_memory").run()
    region = next(item for item in app.multiselect if item.label == "Theme region")
    app = region.select("KR").run()
    assert not app.exception

    rendered_entity_ids: set[str] = set()
    for dataframe in app.dataframe:
        if "entity_id" in dataframe.value.columns:
            rendered_entity_ids.update(
                dataframe.value["entity_id"].dropna().astype("string")
            )
    assert rendered_entity_ids == {"SK_HYNIX"}
    rendered = _app_text(app)
    assert "1 registry member(s)" in rendered
    assert "Active theme filters" in rendered
    assert "region=KR" in rendered
    assert "US-targeted HBM evidence" not in rendered


def test_task8_source_health_metric_counts_reconcile_status_rows() -> None:
    from control_tower.pages.source_health import (
        classify_source_health,
        source_health_counts,
    )

    rows = [
        {"source_id": f"available-{index}", "status": "available"}
        for index in range(14)
    ]
    rows.extend(
        {"source_id": f"unavailable-{index}", "status": "unavailable"}
        for index in range(4)
    )
    rows.extend(
        {"source_id": f"degraded-{index}", "status": "degraded"}
        for index in range(3)
    )
    classified = classify_source_health(
        pd.DataFrame(rows), now_utc=pd.Timestamp("2026-08-13T00:00:00Z")
    )
    counts = source_health_counts(classified)
    assert counts == {
        "sources": 21,
        "available": 14,
        "healthy": 0,
        "freshness_unclassified": 14,
        "stale": 0,
        "no_records": 0,
        "not_applicable": 0,
        "unavailable_degraded": 7,
        "errors_gaps": 0,
    }

    explicit = pd.DataFrame(
        [
            {"source_id": "gap", "status": "gap", "display_status": "unclassified"},
            {
                "source_id": "unresolved",
                "status": "unresolved",
                "display_status": "unclassified",
            },
            {
                "source_id": "conflict",
                "status": "conflict",
                "display_status": "unclassified",
            },
        ]
    )
    assert source_health_counts(explicit)["errors_gaps"] == 3


def test_task8_source_health_app_uses_issue_metric_not_row_count(
    generated_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    rows = [
        {"source_id": f"available-{index}", "status": "available"}
        for index in range(14)
    ]
    rows.extend(
        {"source_id": f"unavailable-{index}", "status": "unavailable"}
        for index in range(4)
    )
    rows.extend(
        {"source_id": f"degraded-{index}", "status": "degraded"}
        for index in range(3)
    )
    health = _frame("source_health.parquet", rows)
    table = pa.Table.from_pandas(
        _typed(health),
        schema=_schema("source_health.parquet"),
        preserve_index=False,
        safe=False,
    )
    pq.write_table(table, generated_root / "source_health.parquet")
    _write_manifest(
        generated_root,
        _manifest(generated_root, previous_build_at="2026-08-13T10:00:00Z"),
    )

    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(generated_root))
    st.cache_data.clear()
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    app.session_state["ct_page"] = "Source Health"
    app = app.run()
    assert not app.exception
    metrics = {item.label: item.value for item in app.metric}
    assert metrics == {
        "Sources": "21",
        "Available": "14",
        "Healthy": "0",
        "Freshness unclassified": "14",
        "Stale": "0",
        "Unavailable / degraded": "7",
        "Explicit errors / gaps": "0",
    }


def test_task8_sidebar_uses_responsive_auto_initial_state() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    assert 'initial_sidebar_state="collapsed"' in source


def test_task9_superseded_events_are_filtered_from_timeline_and_next_catalyst(
    tmp_path: Path,
) -> None:
    from control_tower.components.timeline import select_next_catalyst
    from control_tower.filters import apply_event_filters, superseded_event_ids
    from control_tower.models import EventFilters
    from control_tower.pages.unified_timeline import build_timeline_view

    root = tmp_path / "task9-hbm-supersession"
    _write_task8_region_filter_bundle(root)
    snapshot = _snapshot(root)
    events = snapshot.events
    old_id = "AI_HBM4_QUALIFICATION_WINDOW"
    new_id = "AI_HBM4_QUALIFICATION_WINDOW_V2"
    assert old_id in set(events["event_id"])
    assert new_id in set(events["event_id"])
    assert superseded_event_ids(events) == {old_id}

    filtered = apply_event_filters(
        events, EventFilters(horizon="all", now_utc=snapshot.now_utc)
    )
    assert old_id not in set(filtered["event_id"])
    assert new_id in set(filtered["event_id"])

    # The old HBM4 window is high-importance and would win the catalyst rank
    # without supersession filtering; it must never be presented.
    next_row = select_next_catalyst(events, snapshot.now_utc)
    assert next_row is not None
    assert next_row["event_id"] != old_id

    view = build_timeline_view(
        snapshot,
        filters=EventFilters(horizon="all", now_utc=snapshot.now_utc),
        viewer_timezone="Europe/London",
    )
    visible = {event.event_id for group in view.month_groups for event in group.events}
    assert old_id not in visible
    assert new_id in visible


def test_task9_stale_bundle_today_shows_stale_state_and_recent_events(
    generated_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    from control_tower.models import EventFilters
    from control_tower.pages.today import (
        bundle_latest_data_at,
        build_today_view,
    )

    fresh = _snapshot(generated_root)
    fresh_model = build_today_view(
        fresh,
        filters=EventFilters(now_utc=fresh.now_utc),
        viewer_timezone="Europe/London",
    )
    assert fresh_model.bundle_stale is False

    # Latest source observation is 2026-08-13T11:00:00Z; move the previous
    # build after it so the delta window contains no new source data.
    _rewrite_manifest(
        generated_root,
        lambda manifest: manifest.update(
            {"previous_build_at": "2026-08-13T11:45:00Z"}
        ),
    )
    snapshot = _snapshot(generated_root)
    assert bundle_latest_data_at(snapshot) == pd.Timestamp("2026-08-13T11:00:00Z")
    model = build_today_view(
        snapshot,
        filters=EventFilters(now_utc=snapshot.now_utc),
        viewer_timezone="Europe/London",
    )
    assert model.bundle_stale is True
    assert model.changes.empty
    assert not model.recent_events.empty
    assert "EV_GAP" not in set(model.recent_events["event_id"])

    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(generated_root))
    st.cache_data.clear()
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    assert "bundle is stale" in _app_text(app).lower()
    assert "No changes in the selected snapshot window" not in _app_text(app)
    assert "Provisional date" in _app_text(app)


def test_task9_source_health_buckets_and_privacy_sanitisation() -> None:
    from control_tower.pages.source_health import (
        classify_source_health,
        display_input_path,
        sanitise_source_detail,
        source_health_counts,
    )

    rows = [
        {
            "source_id": "avail-fresh",
            "status": "available",
            "cadence": "daily",
            "source_latest_at": "2026-08-12T00:00:00Z",
        },
        {
            "source_id": "avail-no-cadence",
            "status": "available",
            "input_path": "/private/tmp/leaky/news.csv",
            "detail": "missing_input:/private/tmp/leaky/news.csv; missing_input:/private/tmp/leaky/news.csv",
        },
        {"source_id": "stale-src", "status": "stale"},
        {"source_id": "unavail", "status": "unavailable"},
        {"source_id": "degraded-src", "status": "degraded"},
    ]
    classified = classify_source_health(
        pd.DataFrame(rows), now_utc=pd.Timestamp("2026-08-13T00:00:00Z")
    )
    counts = source_health_counts(classified)
    assert counts == {
        "sources": 5,
        "available": 2,
        "healthy": 1,
        "freshness_unclassified": 1,
        "stale": 1,
        "no_records": 0,
        "not_applicable": 0,
        "unavailable_degraded": 2,
        "errors_gaps": 0,
    }

    leaky = classified.loc[classified["source_id"].eq("avail-no-cadence")].iloc[0]
    assert leaky["input_path"] == "news.csv"
    assert "/private/tmp" not in str(leaky["detail"])
    assert str(leaky["detail"]).count("missing_input:") == 1

    assert display_input_path("C:\\tmp\\win.csv") == "win.csv"
    assert display_input_path("input/news.csv") == "input/news.csv"
    assert display_input_path("") == ""
    assert (
        sanitise_source_detail(
            "missing_input:/a/b/c.csv; missing_input:/a/b/c.csv"
        )
        == "missing_input:c.csv"
    )
    assert sanitise_source_detail("missing_input:/Users/john doe/cache/file.csv") == "missing_input:file.csv"


def test_task9_sidebar_active_state_is_immediate(
    generated_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(generated_root))
    st.cache_data.clear()
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception

    def button(label: str):
        return next(item for item in app.sidebar.button if item.label == label)

    assert button("Today").proto.type == "primary"
    assert button("Unified Timeline").proto.type == "secondary"

    button("Unified Timeline").click().run()
    assert not app.exception
    assert app.session_state["ct_page"] == "Unified Timeline"
    # Active styling must be correct on the same interaction, not one beat later.
    assert button("Unified Timeline").proto.type == "primary"
    assert button("Today").proto.type == "secondary"


def test_task9_mobile_sidebar_is_compressed() -> None:
    css_source = (
        APP_ROOT / "control_tower" / "components" / "__init__.py"
    ).read_text(encoding="utf-8")
    assert "@media (max-width: 759px)" in css_source
    narrow = css_source.split("@media (max-width: 759px)")[1].split("@media")[0]
    assert 'data-testid="stSidebar"' in narrow
    assert "width" in narrow and "min-width" in narrow


def test_task9_next_catalyst_is_presented_only_by_flight_deck(
    generated_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(generated_root))
    st.cache_data.clear()
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    assert _app_text(app).count("Next catalyst") == 1

    app.session_state["ct_page"] = "Unified Timeline"
    app = app.run()
    assert not app.exception
    assert _app_text(app).count("Next catalyst") == 1

    app.session_state["ct_page"] = "AI Bottlenecks"
    app = app.run()
    assert not app.exception
    assert "Prices" not in _app_text(app)


def test_task9_workbench_dedup_keeps_distinct_same_source_events() -> None:
    from control_tower.pages.ai_bottlenecks import _compact_catalyst_frame

    frame = pd.DataFrame([
        {
            "event_id": "E1",
            "event_type": "observation",
            "title": "Revenue observation",
            "starts_at": "2026-08-01T00:00:00Z",
            "source_id": "official_source",
            "related_entity_ids": ("TSMC",),
            "related_basket_ids": ("AI_BOTTLENECKS_GLOBAL",),
        },
        {
            "event_id": "E2",
            "event_type": "observation",
            "title": "Capacity observation",
            "starts_at": "2026-08-01T00:00:00Z",
            "source_id": "official_source",
            "related_entity_ids": ("TSMC",),
            "related_basket_ids": ("AI_BOTTLENECKS_GLOBAL",),
        },
    ])
    assert len(_compact_catalyst_frame(frame)) == 2


def test_batch0_stage1_matrix_renders_on_today_and_empty_source_health(
    generated_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    empty_health = _frame("source_health.parquet", [])
    table = pa.Table.from_pandas(
        _typed(empty_health),
        schema=_schema("source_health.parquet"),
        preserve_index=False,
        safe=False,
    )
    pq.write_table(table, generated_root / "source_health.parquet")
    _write_manifest(
        generated_root,
        _manifest(generated_root, previous_build_at="2026-08-13T10:00:00Z"),
    )

    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(generated_root))
    st.cache_data.clear()
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    today_text = _app_text(app)
    assert "Stage 1 coverage matrix" in today_text
    assert any(
        "Price / market quotes" in dataframe.value.columns
        for dataframe in app.dataframe
    )

    app.session_state["ct_page"] = "Source Health"
    app = app.run()
    assert not app.exception
    source_text = _app_text(app)
    assert "No source-health rows are available" in source_text
    assert "Stage 1 coverage matrix" in source_text
    assert any(
        "Price / market quotes" in dataframe.value.columns
        for dataframe in app.dataframe
    )


def test_today_page_renders_quote_snapshots_and_filters_by_universe(
    generated_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    root = tmp_path / "populated-quotes"
    shutil.copytree(generated_root, root)
    quote = _frame("quote_snapshots.parquet", [{
        "quote_id": "today-quote",
        "listing_id": "L1",
        "canonical_ticker": "EONE",
        "provider_symbol": "EONE",
        "quote_timestamp": "2026-08-13T11:59:30Z",
        "retrieved_at_utc": "2026-08-13T12:00:00Z",
        "last_price": 123.45,
        "currency": "USD",
        "market_status": "closed",
        "latency_class": "delayed",
        "source_id": "fixture_quotes",
        "source_url": "https://example.test/quotes",
        "pit_class": "snapshot_from_delayed_source",
        "source_license_class": "personal_use_terms_unverified",
        "registry_version": "v1",
    }])
    health = _frame("source_health.parquet", [{
        "source_id": "fixture_quotes",
        "input_path": "fixture_quotes.parquet",
        "source_kind": "market",
        "status": "available",
        "required": False,
        "row_count": 1,
        "latest_observation_at": "2026-08-13T11:59:30Z",
        "source_latest_at": "2026-08-13T11:59:30Z",
        "retrieved_at_utc": "2026-08-13T12:00:00Z",
        "cadence": "daily",
        "source_url": "https://example.test/quotes",
        "pit_class": "snapshot_from_delayed_source",
        "source_license_class": "personal_use_terms_unverified",
        "schema_version": "v1",
        "detail": "populated delayed quote fixture",
    }])
    empty_basket = _frame("baskets.parquet", [{
        "basket_id": "EMPTY_BASKET",
        "display_name": "Empty basket",
        "purpose": "empty-universe probe",
        "active_from": "2026-01-01",
        "registry_version": "v1",
    }])
    _write_typed_artifact(root, "quote_snapshots.parquet", quote)
    _write_typed_artifact(root, "source_health.parquet", health)
    _write_typed_artifact(
        root,
        "baskets.parquet",
        pd.concat([pd.read_parquet(root / "baskets.parquet"), empty_basket], ignore_index=True),
    )
    _write_manifest(root, _manifest(root, previous_build_at="2026-08-13T10:00:00Z"))

    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(root))
    st.cache_data.clear()
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    rendered = _app_text(app)
    assert "Stage 1 market quotes (delayed)" in rendered
    assert "USD 123.45" in rendered
    assert "Freshness: delayed" in rendered
    assert "Market status: closed" in rendered
    assert "Source health:" in rendered

    # A selected universe with no eligible listings must not fall back to the
    # unfiltered quote artifact.
    app.session_state["ct_basket_ids"] = ("EMPTY_BASKET",)
    app = app.run()
    assert not app.exception
    assert "USD 123.45" not in _app_text(app)
    assert "Latest market quotes unavailable" in _app_text(app)

    # Non-company scope suppresses the quote panel entirely.
    app.session_state["ct_scopes"] = ("macro",)
    app = app.run()
    assert not app.exception
    assert "Stage 1 market quotes (delayed)" not in _app_text(app)


def test_today_selected_universe_uses_shared_listing_eligibility(
    generated_root: Path,
) -> None:
    from control_tower.models import EventFilters
    from control_tower.pages.today import _selected_universe

    snapshot = _snapshot(generated_root)
    listings = pd.concat(
        [
            snapshot.listings,
            pd.DataFrame(
                [
                    {
                        "listing_id": "TCEHY_US",
                        "entity_id": "E1",
                        "canonical_ticker": "TCEHY.US",
                        "mapping_status": "unresolved",
                        "collection_eligible": False,
                        "listing_status": "active",
                        "active_from": "2026-01-01",
                        "active_to": None,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    snapshot = replace(snapshot, listings=listings)

    entities, listing_ids, baskets = _selected_universe(
        snapshot,
        EventFilters(),
    )

    assert entities == {"E1", "E2"}
    assert listing_ids == {"L1", "L2"}
    assert "TCEHY_US" not in listing_ids
    assert baskets == set()


def test_today_page_marks_bytedance_only_universe_not_applicable(
    generated_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    root = tmp_path / "private-only"
    shutil.copytree(generated_root, root)
    private_entity = _frame("entities.parquet", [{
        "entity_id": "BYTEDANCE",
        "legal_name": "ByteDance Ltd.",
        "display_name": "ByteDance",
        "country": "CN",
        "sector": "Internet",
        "industry": "Platforms",
        "active_status": "active",
        "active_from": "2026-01-01",
        "registry_version": "v1",
        "entity_type": "private",
    }])
    private_basket = _frame("baskets.parquet", [{
        "basket_id": "BYTEDANCE_ONLY",
        "display_name": "ByteDance only",
        "purpose": "private-company probe",
        "active_from": "2026-01-01",
        "registry_version": "v1",
    }])
    private_membership = _frame("basket_memberships.parquet", [{
        "entity_id": "BYTEDANCE",
        "basket_id": "BYTEDANCE_ONLY",
        "membership_tier": "watch_only",
        "primary_layer": "platforms",
        "active_from": "2026-01-01",
        "registry_version": "v1",
    }])
    _write_typed_artifact(
        root,
        "entities.parquet",
        pd.concat([pd.read_parquet(root / "entities.parquet"), private_entity], ignore_index=True),
    )
    _write_typed_artifact(
        root,
        "baskets.parquet",
        pd.concat([pd.read_parquet(root / "baskets.parquet"), private_basket], ignore_index=True),
    )
    _write_typed_artifact(
        root,
        "basket_memberships.parquet",
        pd.concat([pd.read_parquet(root / "basket_memberships.parquet"), private_membership], ignore_index=True),
    )
    _write_manifest(root, _manifest(root, previous_build_at="2026-08-13T10:00:00Z"))

    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(root))
    st.cache_data.clear()
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    app.session_state["ct_basket_ids"] = ("BYTEDANCE_ONLY",)
    app = app.run()
    assert not app.exception
    rendered = _app_text(app)
    assert "ByteDance" in rendered
    assert "Market quotes not applicable" in rendered
    assert "Not applicable" in rendered
    assert "USD 123.45" not in rendered

def test_flight_deck_active_window_presents_as_active_catalyst(generated_root: Path) -> None:
    from control_tower.components.flight_deck import build_flight_deck, flight_deck_html
    from control_tower.models import EventFilters

    snapshot = _snapshot(generated_root)
    now = pd.Timestamp("2026-08-22T00:06:00Z")
    active_events = pd.DataFrame([
        {
            "event_id": "AI_ADVANCED_PACKAGING_WINDOW",
            "event_type": "thesis_checkpoint",
            "title": "Advanced packaging adoption window",
            "status": "active",
            "certainty_class": "thesis_checkpoint",
            "importance": "high",
            "starts_at": "2026-06-30T16:00:00Z",
            "ends_at": "2027-06-30T15:59:59Z",
            "date_precision": "year",
        }
    ])
    active_snapshot = replace(snapshot, events=active_events, as_of_utc=now)
    deck = build_flight_deck(
        active_snapshot,
        filters=EventFilters(horizon="30d", now_utc=now),
        viewer_timezone="Europe/London",
    )
    assert deck.catalyst_timing_state == "active"
    html = flight_deck_html(deck)
    assert "Active catalyst" in html
    assert "Active window" in html
    assert "T+53d" not in html
    assert "Next catalyst" not in html


def test_flight_deck_future_event_retains_next_catalyst_and_t_minus(generated_root: Path) -> None:
    from control_tower.components.flight_deck import build_flight_deck, flight_deck_html
    from control_tower.models import EventFilters

    snapshot = _snapshot(generated_root)
    now = pd.Timestamp("2026-08-22T00:06:00Z")
    future_events = pd.DataFrame([
        {
            "event_id": "EV_FUTURE",
            "event_type": "earnings",
            "title": "Future earnings release",
            "status": "scheduled",
            "certainty_class": "hard",
            "importance": "high",
            "starts_at": "2026-08-29T00:00:00Z",
            "ends_at": "2026-08-29T00:00:00Z",
            "date_precision": "day",
        }
    ])
    future_snapshot = replace(snapshot, events=future_events, as_of_utc=now)
    deck = build_flight_deck(
        future_snapshot,
        filters=EventFilters(horizon="30d", now_utc=now),
        viewer_timezone="Europe/London",
    )
    assert deck.catalyst_timing_state == "future"
    html = flight_deck_html(deck)
    assert "Next catalyst" in html
    assert "T-7d" in html
    assert "Active catalyst" not in html
    assert "Active window" not in html


def test_flight_deck_boundary_exact_day_now_and_ended_window(generated_root: Path) -> None:
    from control_tower.components.flight_deck import build_flight_deck, flight_deck_html
    from control_tower.components.timeline import is_active_catalyst
    from control_tower.models import EventFilters

    snapshot = _snapshot(generated_root)
    now = pd.Timestamp("2026-08-22T00:00:00Z")

    # 1. Exact instant event happening right now (starts_at == ends_at == now) -> active
    events_t0 = pd.DataFrame([
        {
            "event_id": "EV_TODAY",
            "event_type": "earnings",
            "title": "Today exact earnings",
            "status": "scheduled",
            "certainty_class": "hard",
            "importance": "high",
            "starts_at": "2026-08-22T00:00:00Z",
            "ends_at": "2026-08-22T00:00:00Z",
            "date_precision": "day",
        }
    ])
    snapshot_t0 = replace(snapshot, events=events_t0, as_of_utc=now)
    deck_t0 = build_flight_deck(
        snapshot_t0,
        filters=EventFilters(horizon="30d", now_utc=now),
        viewer_timezone="Europe/London",
    )
    assert deck_t0.catalyst_timing_state == "active"
    html_t0 = flight_deck_html(deck_t0)
    assert "Active catalyst" in html_t0
    assert "Active window" in html_t0

    # 2. Window boundary: now exactly at ends_at -> active
    events_window = pd.DataFrame([
        {
            "event_id": "EV_WINDOW_END",
            "event_type": "thesis_checkpoint",
            "title": "Ending window",
            "status": "active",
            "certainty_class": "thesis_checkpoint",
            "importance": "high",
            "starts_at": "2026-08-01T00:00:00Z",
            "ends_at": "2026-08-22T10:00:00Z",
            "date_precision": "day",
        }
    ])
    now_window = pd.Timestamp("2026-08-22T10:00:00Z")
    snapshot_window = replace(snapshot, events=events_window, as_of_utc=now_window)
    deck_window = build_flight_deck(
        snapshot_window,
        filters=EventFilters(horizon="30d", now_utc=now_window),
        viewer_timezone="Europe/London",
    )
    assert deck_window.catalyst_timing_state == "active"
    html_window = flight_deck_html(deck_window)
    assert "Active catalyst" in html_window
    assert "Active window" in html_window

    # 3. Window beginning exactly now (starts_at == now < ends_at) -> active
    events_window_start = pd.DataFrame([
        {
            "event_id": "EV_WINDOW_START",
            "event_type": "thesis_checkpoint",
            "title": "Starting window",
            "status": "active",
            "certainty_class": "thesis_checkpoint",
            "importance": "high",
            "starts_at": "2026-08-22T10:00:00Z",
            "ends_at": "2026-08-23T10:00:00Z",
            "date_precision": "day",
        }
    ])
    snapshot_window_start = replace(snapshot, events=events_window_start, as_of_utc=now_window)
    deck_window_start = build_flight_deck(
        snapshot_window_start,
        filters=EventFilters(horizon="30d", now_utc=now_window),
        viewer_timezone="Europe/London",
    )
    assert deck_window_start.catalyst_timing_state == "active"
    html_window_start = flight_deck_html(deck_window_start)
    assert "Active catalyst" in html_window_start
    assert "Active window" in html_window_start

    # 4. Instant event immediately after ends_at -> past (not selected as active or future)
    now_past = pd.Timestamp("2026-08-22T00:00:01Z")
    snapshot_past = replace(snapshot, events=events_t0, as_of_utc=now_past)
    deck_past = build_flight_deck(
        snapshot_past,
        filters=EventFilters(horizon="30d", now_utc=now_past),
        viewer_timezone="Europe/London",
    )
    assert deck_past.catalyst_timing_state == "none"
    html_past = flight_deck_html(deck_past)
    assert "No eligible catalyst" in html_past

    # 5. Truly future event (now < starts_at) -> future
    now_before = pd.Timestamp("2026-08-21T12:00:00Z")
    snapshot_before = replace(snapshot, events=events_t0, as_of_utc=now_before)
    deck_before = build_flight_deck(
        snapshot_before,
        filters=EventFilters(horizon="30d", now_utc=now_before),
        viewer_timezone="Europe/London",
    )
    assert deck_before.catalyst_timing_state == "future"
    html_before = flight_deck_html(deck_before)
    assert "Next catalyst" in html_before
    assert "T-1d" in html_before

    # 6. Direct helper semantics verification
    t_start = pd.Timestamp("2026-08-22T10:00:00Z")
    t_end = pd.Timestamp("2026-08-23T10:00:00Z")
    assert is_active_catalyst(t_start, t_end, t_start) is True
    assert is_active_catalyst(t_start, t_end, t_end) is True
    assert is_active_catalyst(t_start, t_end, pd.Timestamp("2026-08-22T15:00:00Z")) is True
    assert is_active_catalyst(t_start, t_end, pd.Timestamp("2026-08-22T09:59:59Z")) is False
    assert is_active_catalyst(t_start, t_end, pd.Timestamp("2026-08-23T10:00:01Z")) is False
    assert is_active_catalyst(t_start, None, t_start) is True
    assert is_active_catalyst(t_start, None, pd.Timestamp("2026-08-22T10:00:01Z")) is False
    assert is_active_catalyst(None, t_end, t_start) is False


def test_app_and_company_page_import_from_app_dir_without_pythonpath() -> None:
    import os
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    app_dir = repo_root / "apps" / "research-control-tower"
    clean_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    # Test importing app from apps/research-control-tower directory
    proc_app = subprocess.run(
        [sys.executable, "-c", "import app; assert hasattr(app, 'main')"],
        cwd=str(app_dir),
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert proc_app.returncode == 0, f"Import from app_dir failed: {proc_app.stderr}"

    # Test importing company page standalone from app_dir
    proc_company = subprocess.run(
        [sys.executable, "-c", "from control_tower.pages.company import render_company_page"],
        cwd=str(app_dir),
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert proc_company.returncode == 0, f"Import company page from app_dir failed: {proc_company.stderr}"
