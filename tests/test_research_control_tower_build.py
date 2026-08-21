from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import date
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from unittest.mock import patch

import pandas as pd
import pytest

from src.research_control_tower.build import (
    ARTIFACT_NAMES,
    CORP_ACTIONS_COLUMNS,
    CORP_ACTIONS_SCHEMA_ID,
    EARNINGS_ACTUALS_COLUMNS,
    EARNINGS_ACTUALS_SCHEMA_ID,
    EARNINGS_CALENDAR_COLUMNS,
    EVENT_LINK_COLUMNS,
    EVENT_OUTPUT_COLUMNS,
    EVENT_WATCH_QUESTION_COLUMNS,
    FILING_SCHEMA_ID,
    ECB_FX_SCHEMA_ID,
    FRED_META_SCHEMA_ID,
    FRED_OBSERVATIONS_SCHEMA_ID,
    INTERNAL_ESTIMATES_COLUMNS,
    INTERNAL_ESTIMATES_SCHEMA_ID,
    MACRO_COLLECTOR_SCHEMA_ID,
    MACRO_EVENTS_SCHEMA_ID,
    MACRO_OBSERVATIONS_SCHEMA_ID,
    MACRO_SOURCE_HEALTH_SCHEMA_ID,
    NEWS_SCHEMA_ID,
    OFFICIAL_FILINGS_COLUMNS,
    OFFICIAL_FILINGS_SCHEMA_ID,
    OFR_META_SCHEMA_ID,
    OFR_OBSERVATIONS_SCHEMA_ID,
    REGISTRY_OUTPUT_COLUMNS,
    QUOTE_SNAPSHOT_COLUMNS,
    QUOTE_SNAPSHOT_SCHEMA_ID,
    SOURCE_STATE_COLUMNS,
    SOURCE_STATE_SCHEMA_ID,
    SOURCE_TIME_COLUMNS,
    TAIWAN_REVENUE_SCHEMA_ID,
    TASK3_REVISION_COLUMNS,
    TASK3_SNAPSHOT_COLUMNS,
    VALUATION_SNAPSHOTS_COLUMNS,
    VALUATION_SNAPSHOTS_SCHEMA_ID,
    BuildConfig,
    BuildError,
    LocalInput,
    build_control_tower_marts,
    catalyst_eligibility,
    current_generation,
)
from src.research_control_tower.macro import (
    MACRO_OBSERVATION_COLUMNS,
    materialize_macro_calendar,
    materialize_macro_observations,
)
from src.research_control_tower.events import is_catalyst_eligible
import pyarrow as pa
import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).parents[1]
REGISTRY_SOURCE = REPO_ROOT / "config" / "research_control_tower"
TASK5_APP_ROOT = REPO_ROOT / "apps" / "research-control-tower"
TASK3_UTC_TIMESTAMP = pa.timestamp("us", tz="UTC")
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
        ("snapshot_at", TASK3_UTC_TIMESTAMP),
        ("value", pa.float64()),
        ("statistic", pa.string()),
        ("low_value", pa.float64()),
        ("high_value", pa.float64()),
        ("analyst_count", pa.int64()),
        ("provider_contributor_count", pa.int64()),
        ("currency", pa.string()),
        ("unit", pa.string()),
        ("accounting_basis", pa.string()),
        ("provider_asof", TASK3_UTC_TIMESTAMP),
        ("retrieved_at_utc", TASK3_UTC_TIMESTAMP),
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
        ("current_snapshot_at", TASK3_UTC_TIMESTAMP),
        ("current_value", pa.float64()),
        ("current_analyst_count", pa.int64()),
        ("current_dispersion", pa.float64()),
        ("lookback_days", pa.int64()),
        ("cutoff_at", TASK3_UTC_TIMESTAMP),
        ("prior_snapshot_id", pa.string()),
        ("prior_snapshot_at", TASK3_UTC_TIMESTAMP),
        ("prior_value", pa.float64()),
        ("prior_provider_asof", TASK3_UTC_TIMESTAMP),
        ("provider_asof", TASK3_UTC_TIMESTAMP),
        ("retrieved_at_utc", TASK3_UTC_TIMESTAMP),
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
        ("latest_snapshot_at", TASK3_UTC_TIMESTAMP),
        ("as_of", TASK3_UTC_TIMESTAMP),
        ("network_calls", pa.int64()),
        ("source_license_class", pa.string()),
        ("entitlement_status", pa.string()),
        ("entitlement_evidence", pa.string()),
        ("entitlement_ref", pa.string()),
    ]
)


def _copy_control_tower_inputs(target: Path) -> Path:
    target.mkdir(parents=True)
    for path in REGISTRY_SOURCE.glob("*.csv"):
        shutil.copy2(path, target / path.name)
    return target


@pytest.fixture()
def minimal_inputs(tmp_path: Path) -> BuildConfig:
    input_root = _copy_control_tower_inputs(tmp_path / "input" / "config")
    return BuildConfig(
        registry_root=input_root,
        event_root=input_root,
        output_dir=tmp_path / "output",
        as_of_utc=pd.Timestamp("2026-08-13T12:00:00Z"),
        build_id="fixture-build-v1",
    )


def _input(
    source_id: str,
    path: Path,
    schema: str,
    *,
    kind: str = "parquet",
    license_class: str = "public_metadata",
) -> LocalInput:
    return LocalInput(
        source_id=source_id,
        path=path,
        format=kind,
        expected_schema=schema,
        license_class=license_class,
    )


def _audit_source_row(schema_id: str, timestamp: str) -> dict[str, object]:
    if schema_id == CORP_ACTIONS_SCHEMA_ID:
        row = {column: None for column in CORP_ACTIONS_COLUMNS}
        row.update(
            {
                "action_id": "audit-corporate-action-1",
                "version": 1,
                "entity_id": "TENCENT",
                "listing_id": "0700_HK",
                "canonical_ticker": "0700.HK",
                "action_type": "buyback_execution",
                "filing_date": "2026-08-12",
                "execution_date": "2026-08-12",
                "published_at": timestamp,
                "retrieved_at_utc": timestamp,
                "source_document_id": "audit-doc-1",
                "source_url": "https://example.test/audit-doc-1",
                "document_format": "pdf",
                "source_quality": "official_body",
                "pit_class": "snapshot_from_live_source",
                "source_license_class": "official_public_metadata",
                "registry_version": "v1",
            }
        )
        return row
    if schema_id == VALUATION_SNAPSHOTS_SCHEMA_ID:
        row = {column: None for column in VALUATION_SNAPSHOTS_COLUMNS}
        row.update(
            {
                "valuation_id": "audit-valuation-1",
                "listing_id": "0700_HK",
                "valuation_date": "2026-08-12",
                "valuation_at": timestamp,
                "metric_name": "forward_pe",
                "accounting_basis": "NON_IFRS_MANAGEMENT",
                "metric_basis": "PROVIDER_UNVERIFIED",
                "ratio_value": 16.2,
                "numerator_value": 441.2,
                "numerator_currency": "HKD",
                "numerator_ref": "quote:audit-1",
                "numerator_source_id": "audit-quote",
                "numerator_source_url": "https://example.test/audit-quote",
                "numerator_pit_class": "snapshot_from_delayed_source",
                "numerator_at_utc": timestamp,
                "numerator_retrieved_at_utc": timestamp,
                "denominator_value": 27.2,
                "denominator_currency": "HKD",
                "denominator_ref": "consensus:audit-1",
                "denominator_source_id": "audit-consensus",
                "denominator_source_url": "https://example.test/audit-consensus",
                "denominator_pit_class": "snapshot_from_delayed_source",
                "denominator_at_utc": timestamp,
                "denominator_provider_asof_utc": timestamp,
                "denominator_retrieved_at_utc": timestamp,
                "source_id": "audit-valuation",
                "source_url": "https://example.test/audit-valuation",
                "retrieved_at_utc": timestamp,
                "pit_class": "snapshot_from_live_source",
                "coverage_reason": "audit fixture",
                "percentile_history_status": "unavailable",
            }
        )
        from src.research_control_tower.valuation import (
            ValuationInput,
            build_valuation_snapshot_row,
        )

        canonical = build_valuation_snapshot_row(
            ValuationInput(
                **{
                    field: row[field]
                    for field in ValuationInput.__dataclass_fields__
                    if field in row
                }
            )
        )
        row.update(canonical)
        return row
    if schema_id == INTERNAL_ESTIMATES_SCHEMA_ID:
        row = {column: None for column in INTERNAL_ESTIMATES_COLUMNS}
        row.update(
            {
                "estimate_id": "audit-estimate-1",
                "version": 1,
                "supersedes_estimate_id": "",
                "entity_id": "TENCENT",
                "listing_id": "0700_HK",
                "observation_type": "internal_estimate",
                "author": "audit-fixture",
                "metric": "revenue_total",
                "accounting_basis": "NON_IFRS_MANAGEMENT",
                "metric_basis": "NON_IFRS_MANAGEMENT",
                "fiscal_period": "FY2026",
                "fiscal_year": 2026,
                "value_mid": 1.0,
                "currency": "HKD",
                "unit": "million",
                "effective_asof": timestamp[:10],
                "recorded_at_utc": timestamp,
                "source_ref": "internal:audit-estimate-1",
                "pit_class": "not_pit",
            }
        )
        return row
    raise AssertionError(f"unsupported audit fixture schema: {schema_id}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _published(config: BuildConfig, name: str) -> Path:
    return current_generation(config.output_dir) / name


def _manifest(config: BuildConfig) -> dict:
    return json.loads(_published(config, "build_manifest.json").read_text())


def _write_task3_exports(
    root: Path,
    *,
    populated: bool = True,
    snapshot_overrides: dict | None = None,
    revision_overrides: dict | None = None,
    health_overrides: dict | None = None,
    additional_health_providers: tuple[str, ...] = (),
) -> Path:
    root.mkdir(parents=True)
    snapshot_row = {
            "snapshot_id": "snap-ak-1",
            "provider": "akshare",
            "entity_id": "TENCENT",
            "listing_id": "0700_HK",
            "financial_data_security_id": "sec-0700",
            "canonical_ticker": "0700.HK",
            "metric": "eps",
            "fiscal_period": "FY2026",
            "fiscal_year": 2026,
            "estimate_period_end": date(2026, 12, 31),
            "horizon": "FY1",
            "snapshot_at": pd.Timestamp("2026-08-12T00:00:00Z"),
            "value": 2.0,
            "statistic": "mean",
            "low_value": 1.8,
            "high_value": 2.2,
            "analyst_count": 5,
            "provider_contributor_count": 5,
            "currency": "USD",
            "unit": "USD/share",
            "accounting_basis": None,
            "provider_asof": pd.Timestamp("2026-08-12T00:00:00Z"),
            "retrieved_at_utc": pd.Timestamp("2026-08-12T01:00:00Z"),
            "source_url": "https://example.test/consensus",
            "raw_hash": hashlib.sha256(
                b"task3-synthetic-consensus-row"
            ).hexdigest(),
            "pit_class": "snapshot_from_live_source",
            "source_run_id": "task3-fixture-run",
            "calculation_origin": "canonical_fixture",
            "coverage_reason": None,
    }
    snapshot_row.update(snapshot_overrides or {})
    snapshot_rows = [snapshot_row]
    revision_row = {
        "revision_id": "rev-ak-1",
        "snapshot_id": "snap-ak-1",
        "provider": "akshare",
        "prior_provider": "akshare",
        "entity_id": "TENCENT",
        "listing_id": "0700_HK",
        "financial_data_security_id": "sec-0700",
        "canonical_ticker": "0700.HK",
        "metric": "eps",
        "fiscal_period": "FY2026",
        "fiscal_year": 2026,
        "estimate_period_end": date(2026, 12, 31),
        "horizon": "FY1",
        "statistic": "mean",
        "current_snapshot_at": pd.Timestamp("2026-08-12T00:00:00Z"),
        "current_value": 2.0,
        "current_analyst_count": 5,
        "current_dispersion": 0.2,
        "lookback_days": 7,
        "cutoff_at": pd.Timestamp("2026-08-05T00:00:00Z"),
        "prior_snapshot_id": "snap-ak-0",
        "prior_snapshot_at": pd.Timestamp("2026-08-04T00:00:00Z"),
        "prior_value": 1.9,
        "prior_provider_asof": pd.Timestamp("2026-08-04T00:00:00Z"),
        "provider_asof": pd.Timestamp("2026-08-12T00:00:00Z"),
        "retrieved_at_utc": pd.Timestamp("2026-08-12T01:00:00Z"),
        "source_url": "https://example.test/consensus",
        "pit_class": "snapshot_from_live_source",
        "source_run_id": "task3-fixture-run",
        "prior_analyst_count": 4,
        "revision_value": 0.1,
        "revision_pct": 0.0526315789,
        "analyst_count_change": 1,
        "dispersion": 0.2,
        "alignment_status": "aligned",
    }
    revision_row.update(revision_overrides or {})
    health_row = {
        "provider": "akshare",
        "status": "available",
        "reason": "fixture",
        "row_count": 1,
        "mapped_row_count": 1,
        "latest_snapshot_at": pd.Timestamp("2026-08-12T00:00:00Z"),
        "as_of": pd.Timestamp("2026-08-13T12:00:00Z"),
        "network_calls": 0,
        "source_license_class": "local_private_research",
        "entitlement_status": "terms_unverified",
        "entitlement_evidence": "fixture permits local/private research only",
        "entitlement_ref": "fixture-policy:local-private-research-v1",
    }
    health_row.update(health_overrides or {})
    health_rows = [health_row]
    health_rows.extend(
        {
            **health_row,
            "provider": provider,
            "reason": "synthetic valid-looking provider sidecar",
        }
        for provider in additional_health_providers
    )
    tables = {
        "control_tower_consensus_snapshots.parquet": pa.Table.from_pylist(
            snapshot_rows if populated else [],
            schema=TASK3_SNAPSHOT_ARROW_SCHEMA,
        ),
        "control_tower_consensus_revisions.parquet": pa.Table.from_pylist(
            [revision_row] if populated else [],
            schema=TASK3_REVISION_ARROW_SCHEMA,
        ),
        "control_tower_consensus_source_health.parquet": pa.Table.from_pylist(
            health_rows if populated else [],
            schema=TASK3_HEALTH_ARROW_SCHEMA,
        ),
    }
    for name, table in tables.items():
        pq.write_table(table, root / name)
    return root


def _write_optional_sources(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    macro_root = tmp_path / "input" / "macro"
    macro_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "date": "2026-08-07",
                "series_id": "NFCI",
                "value": 0.1,
                "fetched_at": "2026-08-08T04:34:37Z",
            }
        ]
    ).to_parquet(macro_root / "fred_observations.parquet", index=False)
    pd.DataFrame(
        [
            {
                "series_id": "NFCI",
                "title": "Chicago Fed National Financial Conditions Index",
                "frequency": "W",
                "units": "Index",
                "seasonal_adjustment": "NSA",
                "observation_start": "1971-01-08",
                "last_updated": "2026-08-05 07:37:42-05",
                "fetched_at": "2026-08-08T04:34:37Z",
            }
        ]
    ).to_parquet(macro_root / "fred_series_meta.parquet", index=False)

    news_root = tmp_path / "input" / "news"
    news_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "dataset_id": "ai_news_blog_posts",
                "source_url": "https://deepmind.google/blog/rss.xml",
                "source_run_id": "fixture-run",
                "scraped_at": "2026-08-10T00:00:00Z",
                "first_seen_at": "2026-08-10T00:00:00Z",
                "last_seen_at": "2026-08-10T00:00:00Z",
                "source_name": "GoogleDeepMind",
                "title": "NVIDIA announces a new AI platform",
                "link": "https://deepmind.google/blog/fixture",
                "pub_date": "Mon, 10 Aug 2026 09:00:00 +0000",
                "description": "This description must not be exported.",
                "body_text": "This body must not be exported.",
            }
        ]
    ).to_parquet(news_root / "official_blog.parquet", index=False)

    filing_root = tmp_path / "input" / "filings"
    filing_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "query": "artificial intelligence demand",
                "accession_no": "0001045810-26-000001",
                "cik": "0001045810",
                "company_name": "NVIDIA CORPORATION (NVDA)",
                "form": "8-K",
                "file_date": "2026-08-10",
                "filing_url": "https://www.sec.gov/Archives/edgar/data/1045810/fixture.htm",
                "fetched_at": "2026-08-11T00:00:00Z",
                "filing_content": "This filing body must not be exported.",
            }
        ]
    ).to_parquet(filing_root / "sec_filings.parquet", index=False)
    return (
        macro_root / "fred_observations.parquet",
        macro_root / "fred_series_meta.parquet",
        news_root / "official_blog.parquet",
        filing_root / "sec_filings.parquet",
    )


def test_build_writes_stable_artifact_set(tmp_path, minimal_inputs):
    manifest = build_control_tower_marts(minimal_inputs)

    assert set(ARTIFACT_NAMES) == {
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
        "price_bars.parquet",
        "news_filings.parquet",
        "official_filings.parquet",
        "earnings_calendar.parquet",
        "earnings_actuals.parquet",
        "corporate_actions.parquet",
        "valuation_snapshots.parquet",
        "internal_estimates.parquet",
        "thesis_claims.parquet",
        "thesis_watch_questions.parquet",
        "evidence_items.parquet",
        "claim_evidence_links.parquet",
        "source_health.parquet",
        "build_manifest.json",
    }
    generation = current_generation(minimal_inputs.output_dir)
    assert set(p.name for p in generation.iterdir()) == set(ARTIFACT_NAMES)
    assert set(p.name for p in minimal_inputs.output_dir.iterdir()) == {"CURRENT", "generations"}
    assert minimal_inputs.output_dir.joinpath("CURRENT").read_text() == f"generations/{generation.name}\n"
    assert manifest.status == "degraded"

    assert list(pd.read_parquet(_published(minimal_inputs, "events.parquet")).columns) == EVENT_OUTPUT_COLUMNS
    assert list(pd.read_parquet(_published(minimal_inputs, "event_entity_links.parquet")).columns) == EVENT_LINK_COLUMNS
    assert list(pd.read_parquet(_published(minimal_inputs, "event_basket_links.parquet")).columns) == EVENT_LINK_COLUMNS
    assert list(pd.read_parquet(_published(minimal_inputs, "event_watch_questions.parquet")).columns) == EVENT_WATCH_QUESTION_COLUMNS
    health = pd.read_parquet(_published(minimal_inputs, "source_health.parquet"))
    required_health = health[health["required"]]
    assert dict(zip(required_health["source_id"], required_health["row_count"])) == {
        "events:event_links": 52,
        "events:event_watch_questions": 20,
        "events:events": 21,
        "registry:basket_memberships": 97,
        "registry:baskets": 7,
        "registry:entities": 71,
        "registry:indices": 12,
        "registry:listings": 81,
    }
    manifest_json = json.loads(_published(minimal_inputs, "build_manifest.json").read_text())
    assert manifest_json["network_policy"] == "forbidden"
    assert manifest_json["artifacts"]["build_manifest.json"]["sha256"] is None
    assert manifest_json["artifacts"]["build_manifest.json"]["row_count"] == 1
    assert manifest_json["generation_id"] == current_generation(minimal_inputs.output_dir).name
    assert manifest_json["current_pointer"] == minimal_inputs.output_dir.joinpath("CURRENT").read_text().strip()
    assert manifest_json["previous_build_at"] is None


def test_invalid_thesis_seed_fails_closed_before_publication(tmp_path, minimal_inputs):
    claims_path = minimal_inputs.registry_root / "thesis_claims.csv"
    claims = pd.read_csv(claims_path, dtype="string", keep_default_na=False)
    claims.loc[0, "entity_id"] = "ORPHAN_ENTITY"
    claims.to_csv(claims_path, index=False)

    with pytest.raises(BuildError, match="thesis seed validation"):
        build_control_tower_marts(minimal_inputs)

    assert not minimal_inputs.output_dir.joinpath("CURRENT").exists()


def test_malformed_thesis_timestamp_is_validated_before_as_of_filter(
    tmp_path, minimal_inputs
):
    evidence_path = minimal_inputs.registry_root / "evidence_items.csv"
    evidence = pd.read_csv(evidence_path, dtype="string", keep_default_na=False)
    evidence.loc[0, "observed_at_utc"] = "not-a-timestamp"
    evidence.to_csv(evidence_path, index=False)

    with pytest.raises(BuildError, match="invalid_observed_at_utc_timestamp"):
        build_control_tower_marts(minimal_inputs)

    assert not minimal_inputs.output_dir.joinpath("CURRENT").exists()


def test_incomplete_thesis_seed_bundle_is_a_controlled_build_error(
    tmp_path, minimal_inputs
):
    (minimal_inputs.registry_root / "claim_evidence_links.csv").unlink()

    with pytest.raises(BuildError, match="thesis seed bundle incomplete"):
        build_control_tower_marts(minimal_inputs)

    assert not minimal_inputs.output_dir.joinpath("CURRENT").exists()


@pytest.mark.parametrize(
    ("schema_id", "config_field", "artifact_name"),
    [
        (CORP_ACTIONS_SCHEMA_ID, "corporate_actions_inputs", "corporate_actions.parquet"),
        (VALUATION_SNAPSHOTS_SCHEMA_ID, "valuation_inputs", "valuation_snapshots.parquet"),
        (INTERNAL_ESTIMATES_SCHEMA_ID, "valuation_inputs", "internal_estimates.parquet"),
    ],
)
def test_audit_source_time_policies_quarantine_future_and_flag_stale_rows(
    tmp_path,
    minimal_inputs,
    schema_id,
    config_field,
    artifact_name,
):
    assert schema_id in SOURCE_TIME_COLUMNS
    source_dir = tmp_path / schema_id
    source_dir.mkdir()

    def run(timestamp: str, suffix: str):
        path = source_dir / f"{suffix}.parquet"
        pd.DataFrame(
            [_audit_source_row(schema_id, timestamp)],
            columns=(
                CORP_ACTIONS_COLUMNS
                if schema_id == CORP_ACTIONS_SCHEMA_ID
                else VALUATION_SNAPSHOTS_COLUMNS
                if schema_id == VALUATION_SNAPSHOTS_SCHEMA_ID
                else INTERNAL_ESTIMATES_COLUMNS
            ),
        ).to_parquet(path, index=False)
        descriptor = _input(f"{schema_id}:{suffix}", path, schema_id)
        config = replace(
            minimal_inputs,
            output_dir=tmp_path / f"output-{suffix}",
            **{config_field: (descriptor,)},
        )
        build_control_tower_marts(config)
        health = pd.read_parquet(_published(config, "source_health.parquet"))
        source_health = health.loc[health["source_id"].eq(descriptor.source_id)].iloc[0]
        output = pd.read_parquet(_published(config, artifact_name))
        return source_health, output

    future_health, future_output = run("2026-08-14T00:00:00Z", "future")
    assert future_health["status"] == "degraded"
    assert "future_row_beyond_as_of" in future_health["detail"]
    assert future_output.empty

    stale_health, stale_output = run("2025-01-01T00:00:00Z", "stale")
    assert stale_health["status"] == "degraded"
    assert "stale_source" in stale_health["detail"]
    assert len(stale_output) == 1


def test_builder_merges_all_valuation_and_internal_descriptors(tmp_path, minimal_inputs):
    valuation_paths = []
    for suffix, valuation_id in (("one", "valuation-one"), ("two", "valuation-two")):
        path = tmp_path / f"valuation-{suffix}.parquet"
        row = _audit_source_row(VALUATION_SNAPSHOTS_SCHEMA_ID, "2026-08-12T00:00:00Z")
        row["numerator_ref"] = f"quote:{suffix}"
        from src.research_control_tower.valuation import ValuationInput, build_valuation_snapshot_row
        row.update(
            build_valuation_snapshot_row(
                ValuationInput(
                    **{
                        field: row[field]
                        for field in ValuationInput.__dataclass_fields__
                        if field in row
                    }
                )
            )
        )
        assert row["valuation_id"]
        pd.DataFrame([row], columns=VALUATION_SNAPSHOTS_COLUMNS).to_parquet(
            path, index=False
        )
        valuation_paths.append(path)

    estimate_paths = []
    for suffix, estimate_id in (("one", "estimate-one"), ("two", "estimate-two")):
        path = tmp_path / f"estimate-{suffix}.parquet"
        row = _audit_source_row(INTERNAL_ESTIMATES_SCHEMA_ID, "2026-08-12T00:00:00Z")
        row["estimate_id"] = estimate_id
        pd.DataFrame([row], columns=INTERNAL_ESTIMATES_COLUMNS).to_parquet(
            path, index=False
        )
        estimate_paths.append(path)

    config = replace(
        minimal_inputs,
        valuation_inputs=tuple(
            [
                _input(f"valuation-{idx}", path, VALUATION_SNAPSHOTS_SCHEMA_ID)
                for idx, path in enumerate(valuation_paths)
            ]
            + [
                _input(f"estimate-{idx}", path, INTERNAL_ESTIMATES_SCHEMA_ID)
                for idx, path in enumerate(estimate_paths)
            ]
        ),
    )
    build_control_tower_marts(config)

    valuations = pd.read_parquet(_published(config, "valuation_snapshots.parquet"))
    estimates = pd.read_parquet(_published(config, "internal_estimates.parquet"))
    assert len(valuations) == 2
    assert valuations["valuation_id"].notna().all()
    assert set(estimates["estimate_id"]) == {"estimate-one", "estimate-two"}


@pytest.mark.parametrize(
    ("schema_id", "id_column", "changed_column"),
    [
        (VALUATION_SNAPSHOTS_SCHEMA_ID, "valuation_id", "coverage_reason"),
        (INTERNAL_ESTIMATES_SCHEMA_ID, "estimate_id", "rationale_notes"),
    ],
)
def test_builder_rejects_divergent_valuation_descriptor_collisions(
    tmp_path, minimal_inputs, schema_id, id_column, changed_column
):
    columns = (
        VALUATION_SNAPSHOTS_COLUMNS
        if schema_id == VALUATION_SNAPSHOTS_SCHEMA_ID
        else INTERNAL_ESTIMATES_COLUMNS
    )
    first = _audit_source_row(schema_id, "2026-08-12T00:00:00Z")
    second = dict(first)
    second[changed_column] = "divergent descriptor payload"
    first_path = tmp_path / f"{schema_id}-first.parquet"
    second_path = tmp_path / f"{schema_id}-second.parquet"
    pd.DataFrame([first], columns=columns).to_parquet(first_path, index=False)
    pd.DataFrame([second], columns=columns).to_parquet(second_path, index=False)

    config = replace(
        minimal_inputs,
        valuation_inputs=(
            _input(f"{schema_id}-first", first_path, schema_id),
            _input(f"{schema_id}-second", second_path, schema_id),
        ),
    )
    with pytest.raises(BuildError, match="duplicate divergent"):
        build_control_tower_marts(config)


@pytest.mark.parametrize("kind", ["earnings", "corporate_actions"])
def test_duplicate_ids_use_full_payload_collision_checks(tmp_path, minimal_inputs, kind):
    if kind == "earnings":
        source_dir = tmp_path / "earnings"
        source_dir.mkdir(parents=True, exist_ok=True)
        source_path, _state_path = _write_earnings_inputs(source_dir)
        frame = pd.read_parquet(source_path)
        schema_id = EARNINGS_ACTUALS_SCHEMA_ID
        config_field = "earnings_inputs"
        frame.loc[0, "source_note"] = "divergent payload"
    else:
        source_dir = tmp_path / "corporate"
        source_dir.mkdir(parents=True, exist_ok=True)
        row = _audit_source_row(CORP_ACTIONS_SCHEMA_ID, "2026-08-12T00:00:00Z")
        frame = pd.DataFrame([row], columns=CORP_ACTIONS_COLUMNS)
        schema_id = CORP_ACTIONS_SCHEMA_ID
        config_field = "corporate_actions_inputs"
        frame.loc[0, "source_note"] = "divergent payload"

    exact_path = source_dir / "exact.parquet"
    divergent_path = source_dir / "divergent.parquet"
    original = pd.read_parquet(source_path) if kind == "earnings" else pd.DataFrame(
        [_audit_source_row(CORP_ACTIONS_SCHEMA_ID, "2026-08-12T00:00:00Z")],
        columns=CORP_ACTIONS_COLUMNS,
    )
    original.to_parquet(exact_path, index=False)
    frame.to_parquet(divergent_path, index=False)

    exact_config = replace(
        minimal_inputs,
        output_dir=tmp_path / f"{kind}-exact-output",
        **{
            config_field: (
                _input(f"{kind}-exact-a", exact_path, schema_id),
                _input(f"{kind}-exact-b", exact_path, schema_id),
            )
        },
    )
    build_control_tower_marts(exact_config)
    exact_output = pd.read_parquet(
        _published(
            exact_config,
            "earnings_actuals.parquet"
            if kind == "earnings"
            else "corporate_actions.parquet",
        )
    )
    assert len(exact_output) == len(original)
    if kind == "corporate_actions":
        assert exact_output["version"].notna().all()
        assert set(exact_output["version"].astype(int)) == {1}
        assert pd.api.types.is_integer_dtype(exact_output["version"])

    divergent_config = replace(
        minimal_inputs,
        output_dir=tmp_path / f"{kind}-divergent-output",
        **{
            config_field: (
                _input(f"{kind}-divergent-a", exact_path, schema_id),
                _input(f"{kind}-divergent-b", divergent_path, schema_id),
            )
        },
    )
    with pytest.raises(BuildError, match="duplicate divergent"):
        build_control_tower_marts(divergent_config)
def test_two_builds_persist_selected_current_lineage_and_today_delta(
    tmp_path, minimal_inputs, monkeypatch
):
    monkeypatch.syspath_prepend(str(TASK5_APP_ROOT))
    from control_tower.pages.today import select_today_changes
    from control_tower.repository import ControlTowerRepository

    first_config = replace(
        minimal_inputs,
        as_of_utc=pd.Timestamp("2026-08-12T00:00:00Z"),
        build_id="fixture-build-v1",
    )
    first = build_control_tower_marts(first_config)
    first_generation = current_generation(first_config.output_dir)
    first_manifest = json.loads((first_generation / "build_manifest.json").read_text())
    first_built_at = first_manifest["built_at_utc"]

    second_config = replace(
        minimal_inputs,
        as_of_utc=pd.Timestamp("2026-08-13T12:00:00Z"),
        build_id="fixture-build-v2",
    )
    second = build_control_tower_marts(second_config)
    second_generation = current_generation(second_config.output_dir)
    second_manifest = json.loads((second_generation / "build_manifest.json").read_text())

    assert first.status == "degraded"
    assert second.status == "degraded"
    assert second_manifest["previous_build_at"] == first_built_at
    assert second_manifest["generation_id"] != first_manifest["generation_id"]
    assert second_manifest["current_pointer"] == (minimal_inputs.output_dir / "CURRENT").read_text().strip()
    first_snapshot = ControlTowerRepository(first_generation).load_snapshot()
    second_snapshot = ControlTowerRepository(second_generation).load_snapshot()
    assert first_snapshot.previous_build_at is None
    assert second_snapshot.previous_build_at == pd.Timestamp(first_built_at)
    assert select_today_changes(first_snapshot).empty
    assert not select_today_changes(second_snapshot).empty


def test_invalid_current_fails_before_publication_and_preserves_pointer(minimal_inputs):
    build_control_tower_marts(minimal_inputs)
    output = minimal_inputs.output_dir
    old_pointer = (output / "CURRENT").read_bytes()
    generation = current_generation(output)
    manifest_path = generation / "build_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["built_at_utc"] = "not-a-timestamp"
    manifest_path.write_text(json.dumps(manifest) + "\n")

    with pytest.raises(BuildError, match="CURRENT selected manifest has an invalid built_at_utc"):
        build_control_tower_marts(replace(minimal_inputs, build_id="fixture-build-invalid-current"))
    assert (output / "CURRENT").read_bytes() == old_pointer
    assert not list((output / "generations").glob("fixture-build-invalid-current-*"))


def test_invalid_current_pointer_fails_before_publication(minimal_inputs):
    build_control_tower_marts(minimal_inputs)
    output = minimal_inputs.output_dir
    old_pointer = (output / "CURRENT").read_bytes()
    (output / "CURRENT").write_text("generations/missing-generation\n")
    with pytest.raises(BuildError, match="CURRENT generation does not exist"):
        build_control_tower_marts(replace(minimal_inputs, build_id="fixture-build-invalid-pointer"))
    assert (output / "CURRENT").read_text() == "generations/missing-generation\n"
    assert old_pointer != (output / "CURRENT").read_bytes()


def test_current_lineage_cannot_be_future_of_requested_as_of(minimal_inputs):
    build_control_tower_marts(
        replace(minimal_inputs, as_of_utc=pd.Timestamp("2026-08-13T12:00:00Z"))
    )
    with pytest.raises(BuildError, match="built_at_utc must be strictly earlier"):
        build_control_tower_marts(
            replace(
                minimal_inputs,
                as_of_utc=pd.Timestamp("2026-08-12T00:00:00Z"),
                build_id="fixture-build-before-current",
            )
        )


def test_two_builds_with_equal_effective_timestamp_fail_before_staging(
    minimal_inputs,
):
    effective_at = pd.Timestamp("2026-08-13T12:00:00Z")
    first_config = replace(
        minimal_inputs,
        as_of_utc=effective_at,
        build_id="fixture-equal-lineage-v1",
    )
    build_control_tower_marts(first_config)
    pointer = minimal_inputs.output_dir / "CURRENT"
    pointer_before = pointer.read_bytes()
    generation_before = current_generation(minimal_inputs.output_dir)

    with pytest.raises(BuildError, match="built_at_utc must be strictly earlier"):
        build_control_tower_marts(
            replace(
                minimal_inputs,
                as_of_utc=effective_at,
                build_id="fixture-equal-lineage-v2",
            )
        )

    assert pointer.read_bytes() == pointer_before
    assert current_generation(minimal_inputs.output_dir) == generation_before
    assert not list(
        (minimal_inputs.output_dir / "generations").glob(
            "fixture-equal-lineage-v2-*"
        )
    )
    assert not list(minimal_inputs.output_dir.glob(".research-control-tower-*"))


def test_selected_manifest_rejects_equal_previous_build_at_before_staging(
    minimal_inputs,
):
    build_control_tower_marts(
        replace(
            minimal_inputs,
            as_of_utc=pd.Timestamp("2026-08-12T00:00:00Z"),
            build_id="fixture-invalid-equal-previous-v1",
        )
    )
    output = minimal_inputs.output_dir
    pointer_before = (output / "CURRENT").read_bytes()
    generation = current_generation(output)
    manifest_path = generation / "build_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["previous_build_at"] = manifest["built_at_utc"]
    for _ in range(8):
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        size = manifest_path.stat().st_size
        if manifest["artifacts"]["build_manifest.json"]["byte_size"] == size:
            break
        manifest["artifacts"]["build_manifest.json"]["byte_size"] = size
    else:
        raise AssertionError("manifest size did not converge")

    with pytest.raises(
        BuildError,
        match="previous_build_at must be strictly earlier",
    ):
        build_control_tower_marts(
            replace(
                minimal_inputs,
                as_of_utc=pd.Timestamp("2026-08-13T00:00:00Z"),
                build_id="fixture-invalid-equal-previous-v2",
            )
        )

    assert (output / "CURRENT").read_bytes() == pointer_before
    assert not list(
        (output / "generations").glob("fixture-invalid-equal-previous-v2-*")
    )
    assert not list(output.glob(".research-control-tower-*"))


def test_degraded_build_source_health_artifact_is_available_to_task5_reader(
    minimal_inputs,
    monkeypatch,
):
    monkeypatch.syspath_prepend(str(TASK5_APP_ROOT))
    from control_tower.repository import ControlTowerRepository

    manifest = build_control_tower_marts(minimal_inputs)
    manifest_json = _manifest(minimal_inputs)
    source_health = pd.read_parquet(_published(minimal_inputs, "source_health.parquet"))

    assert manifest.status == "degraded"
    assert manifest_json["artifacts"]["source_health.parquet"]["status"] == "available"
    assert {"unavailable", "degraded"} & set(source_health["status"])

    snapshot = ControlTowerRepository(minimal_inputs.output_dir).load_snapshot()
    assert snapshot.manifest["status"] == "degraded"
    assert {"unavailable", "degraded"} & set(snapshot.source_health["status"])


def test_build_has_no_external_network_calls(tmp_path, minimal_inputs, monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("network")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(socket, "socket", fail_network)
    monkeypatch.setattr("urllib.request.urlopen", fail_network)
    manifest = build_control_tower_marts(minimal_inputs)
    assert manifest.status == "degraded"


def test_local_adapters_preserve_provenance_and_license_boundary(tmp_path, minimal_inputs):
    obs_path, meta_path, news_path, filing_path = _write_optional_sources(tmp_path)
    consensus_dir = _write_task3_exports(tmp_path / "input" / "consensus")
    config = replace(
        minimal_inputs,
        macro_inputs=(
            _input("fred_observations", obs_path, FRED_OBSERVATIONS_SCHEMA_ID),
            _input("fred_meta", meta_path, FRED_META_SCHEMA_ID),
        ),
        news_inputs=(_input("official_ai_rss", news_path, NEWS_SCHEMA_ID),),
        filing_inputs=(_input("sec_edgar", filing_path, FILING_SCHEMA_ID),),
        consensus_export_dir=consensus_dir,
    )

    manifest = build_control_tower_marts(config)
    macro = pd.read_parquet(_published(config, "macro_observations.parquet"))
    news_filings = pd.read_parquet(_published(config, "news_filings.parquet"))
    snapshots = pd.read_parquet(_published(config, "consensus_snapshots.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))

    fred = macro[macro["source_id"] == "fred_observations"]
    assert not fred.empty
    assert fred.iloc[0]["source_url"] == "https://fred.stlouisfed.org/series/NFCI"
    assert fred.iloc[0]["pit_class"] in {"current_vintage", "snapshot_from_live_source"}
    assert fred.iloc[0]["release_at"] is pd.NaT or pd.isna(fred.iloc[0]["release_at"])
    assert set(snapshots["provider"]) == {"akshare"}
    assert set(news_filings["document_type"]) == {"news", "filing"}
    assert not any(
        column in news_filings.columns
        for column in ("body_text", "summary", "description", "filing_content", "news_content")
    )
    assert news_filings["derived_summary_if_permitted"].isna().all()
    assert _sha256(obs_path) in set(health["input_sha256"].dropna())
    assert _sha256(news_path) in set(health["input_sha256"].dropna())
    assert _sha256(filing_path) in set(health["input_sha256"].dropna())
    assert "fred_observations" in set(health["source_id"])
    fred_health = health[health["source_id"] == "fred_observations"].iloc[0]
    assert fred_health["retrieved_at_utc"] == pd.Timestamp("2026-08-08T04:34:37Z")
    assert fred_health["source_license_class"] == "public_metadata"
    assert int(fred_health["row_count"]) == 1
    assert set(news_filings["source_quality"]) == {"official", "official_metadata"}
    assert manifest.status == "degraded"


def _collector_observation_row() -> dict:
    return {
        "observation_id": "macro_obs_CPIAUCSL_2026-01_20260101_20260213",
        "event_id": "MACRO_US_CPI_R10_20260213",
        "source_id": "official:fred_alfred",
        "series_id": "CPIAUCSL",
        "scope": "macro",
        "event_type": "us_cpi",
        "metric_name": "Consumer Price Index (CPI)",
        "reference_period": "2026-01",
        "observation_date": "2026-01-01",
        "release_at": None,
        "actual_value": 310.2,
        "unit": "Index 1982-1984=100",
        "frequency": "month",
        "first_observed_at": None,
        "source_published_at": None,
        "retrieved_at_utc": "2026-08-12T00:00:00Z",
        "source_url": "https://fred.stlouisfed.org/series/CPIAUCSL",
        "pit_class": "official_first_release",
        "source_license_class": "public_domain",
        "is_provisional": False,
        "realtime_start": "2026-02-13",
        "realtime_end": "9999-12-31",
        "registry_version": "v1",
    }


def test_macro_collector_observations_v1_descriptor_builds_and_contributes(
    tmp_path, minimal_inputs
):
    # P1-1: macro_observations_v1/macro_collector_v1 are registered with the
    # correct optional-column set, so a valid descriptor builds without a
    # KeyError and contributes rows + health.
    macro_root = tmp_path / "input" / "macro"
    macro_root.mkdir(parents=True)
    collector_path = macro_root / "macro_observations.parquet"
    materialize_macro_observations([_collector_observation_row()]).to_parquet(
        collector_path, index=False
    )
    config = replace(
        minimal_inputs,
        macro_inputs=(
            LocalInput(
                source_id="macro_collector",
                path=collector_path,
                format="parquet",
                expected_schema=MACRO_OBSERVATIONS_SCHEMA_ID,
            ),
        ),
    )

    manifest = build_control_tower_marts(config)
    macro = pd.read_parquet(_published(config, "macro_observations.parquet"))
    collector_rows = macro[macro["source_id"] == "official:fred_alfred"]

    assert not collector_rows.empty
    assert collector_rows.iloc[0]["series_id"] == "CPIAUCSL"
    assert collector_rows.iloc[0]["realtime_start"] == "2026-02-13"
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    health_row = health[health["source_id"] == "macro_collector"].iloc[0]
    assert health_row["status"] == "available"
    assert int(health_row["row_count"]) == 1
    assert manifest.artifacts["macro_observations.parquet"]["status"] == "available"

    # The legacy alias schema id resolves to the same optional-column set.
    alias_config = replace(
        config,
        as_of_utc=pd.Timestamp("2026-08-14T00:00:00Z"),
        build_id="fixture-build-alias-v1",
        macro_inputs=(
            LocalInput(
                source_id="macro_collector_alias",
                path=collector_path,
                format="parquet",
                expected_schema=MACRO_COLLECTOR_SCHEMA_ID,
            ),
        ),
    )
    build_control_tower_marts(alias_config)


def test_vintaged_fred_observations_parquet_builds_without_schema_drift(
    tmp_path, minimal_inputs
):
    # P1-2: realtime_start/realtime_end are allowed trailing columns for
    # fred_observations_v1; vintaged exports build and keep their vintages.
    macro_root = tmp_path / "input" / "macro"
    macro_root.mkdir(parents=True)
    obs_path = macro_root / "fred_observations.parquet"
    pd.DataFrame(
        [
            {
                "date": "2026-08-07",
                "series_id": "NFCI",
                "value": 0.1,
                "fetched_at": "2026-08-08T04:34:37Z",
                "realtime_start": "2026-08-01",
                "realtime_end": "2026-08-08",
            },
            {
                "date": "2026-08-07",
                "series_id": "NFCI",
                "value": 0.2,
                "fetched_at": "2026-08-08T04:34:37Z",
                "realtime_start": "2026-08-09",
                "realtime_end": "9999-12-31",
            },
        ]
    ).to_parquet(obs_path, index=False)
    meta_path = macro_root / "fred_series_meta.parquet"
    pd.DataFrame(
        [
            {
                "series_id": "NFCI",
                "title": "Chicago Fed National Financial Conditions Index",
                "frequency": "W",
                "units": "Index",
                "seasonal_adjustment": "NSA",
                "observation_start": "1971-01-08",
                "last_updated": "2026-08-05 07:37:42-05",
                "fetched_at": "2026-08-08T04:34:37Z",
            }
        ]
    ).to_parquet(meta_path, index=False)
    config = replace(
        minimal_inputs,
        macro_inputs=(
            _input("fred_observations", obs_path, FRED_OBSERVATIONS_SCHEMA_ID),
            _input("fred_meta", meta_path, FRED_META_SCHEMA_ID),
        ),
    )

    manifest = build_control_tower_marts(config)
    macro = pd.read_parquet(_published(config, "macro_observations.parquet"))
    fred = macro[macro["source_id"] == "fred_observations"]

    assert len(fred) == 2
    assert set(fred["realtime_start"].dropna()) == {"2026-08-01", "2026-08-09"}
    assert manifest.artifacts["macro_observations.parquet"]["status"] == "available"


def test_empty_macro_optional_inputs_are_unavailable_and_degrade_build(
    tmp_path, minimal_inputs
):
    # P2-7: zero-row sources must never report available; without execution
    # evidence an empty frame is unavailable and degrades the build.
    macro_root = tmp_path / "input" / "macro"
    macro_root.mkdir(parents=True)
    empty_obs = macro_root / "fred_observations.parquet"
    pd.DataFrame(columns=["date", "series_id", "value", "fetched_at"]).to_parquet(
        empty_obs, index=False
    )
    empty_meta = macro_root / "fred_series_meta.parquet"
    pd.DataFrame(
        columns=[
            "series_id",
            "title",
            "frequency",
            "units",
            "seasonal_adjustment",
            "observation_start",
            "last_updated",
            "fetched_at",
        ]
    ).to_parquet(empty_meta, index=False)
    config = replace(
        minimal_inputs,
        macro_inputs=(
            _input("fred_observations", empty_obs, FRED_OBSERVATIONS_SCHEMA_ID),
            _input("fred_meta", empty_meta, FRED_META_SCHEMA_ID),
        ),
    )

    manifest = build_control_tower_marts(config)
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    by_source = health.set_index("source_id")["status"].to_dict()

    assert by_source["fred_observations"] == "unavailable"
    assert by_source["fred_meta"] == "unavailable"
    assert manifest.artifacts["macro_observations.parquet"]["status"] == "degraded"
    assert "fred_observations" in manifest.degraded_inputs


def test_macro_collector_health_and_events_reach_build(tmp_path, minimal_inputs):
    # P2-8: macro_source_health.json and macro_events.parquet must reach the
    # build: per-source health rows and macro calendar event rows.
    macro_root = tmp_path / "input" / "macro"
    macro_root.mkdir(parents=True)
    obs_path = macro_root / "macro_observations.parquet"
    materialize_macro_observations([_collector_observation_row()]).to_parquet(
        obs_path, index=False
    )
    events_path = macro_root / "macro_events.parquet"
    events_df = materialize_macro_calendar(
        {
            "us_cpi": pd.DataFrame(
                [
                    {
                        "release_date": "2026-02-13",
                        "release_id": 10,
                        "source_timezone": "America/New_York",
                        "title": "US CPI Release",
                    }
                ]
            )
        }
    )
    events_df.to_parquet(events_path, index=False)
    health_path = macro_root / "macro_source_health.json"
    health_path.write_text(
        json.dumps(
            {
                "official:fred_alfred": {
                    "source_id": "official:fred_alfred",
                    "status": "available",
                    "retrieved_at_utc": "2026-08-12T00:00:00Z",
                    "event_count": 1,
                    "observation_count": 1,
                    "series_covered": ["CPIAUCSL"],
                    "error_detail": None,
                    "source_caveats": "fixture",
                },
                "official:bls": {
                    "source_id": "official:bls",
                    "status": "unavailable",
                    "retrieved_at_utc": "2026-08-12T00:00:00Z",
                    "event_count": 0,
                    "observation_count": 0,
                    "series_covered": [],
                    "error_detail": "no native BLS key",
                    "source_caveats": None,
                },
                "official:bea": {
                    "source_id": "official:bea",
                    "status": "partial",
                    "retrieved_at_utc": "2026-08-12T00:00:00Z",
                    "event_count": 1,
                    "observation_count": 0,
                    "series_covered": [],
                    "error_detail": None,
                    "source_caveats": None,
                },
                "official:ecb": {
                    "source_id": "official:ecb",
                    "status": "no_records",
                    "retrieved_at_utc": "2026-08-12T00:00:00Z",
                    "event_count": 0,
                    "observation_count": 0,
                    "series_covered": [],
                    "error_detail": None,
                    "source_caveats": None,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    config = replace(
        minimal_inputs,
        macro_inputs=(
            LocalInput(
                source_id="macro_collector",
                path=obs_path,
                format="parquet",
                expected_schema=MACRO_OBSERVATIONS_SCHEMA_ID,
            ),
            LocalInput(
                source_id="macro_collector_events",
                path=events_path,
                format="parquet",
                expected_schema=MACRO_EVENTS_SCHEMA_ID,
            ),
            LocalInput(
                source_id="macro_collector_health",
                path=health_path,
                format="json",
                expected_schema=MACRO_SOURCE_HEALTH_SCHEMA_ID,
            ),
        ),
    )

    manifest = build_control_tower_marts(config)
    macro = pd.read_parquet(_published(config, "macro_observations.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))

    # Macro calendar events from the collector reach the macro observations.
    assert (macro["event_id"] == "MACRO_US_CPI_R10_20260213").any()
    event_row = macro[macro["event_id"] == "MACRO_US_CPI_R10_20260213"].iloc[0]
    assert event_row["event_type"] == "us_cpi"
    assert event_row["source_id"] == "official:fred_alfred"

    # Health propagation: collector sources appear with their own statuses.
    by_source = health.set_index("source_id")["status"].to_dict()
    assert by_source["official:fred_alfred"] == "available"
    assert by_source["official:bls"] == "unavailable"
    assert by_source["official:bea"] == "partial"
    assert by_source["official:ecb"] == "no_records"
    bls_row = health[health["source_id"] == "official:bls"].iloc[0]
    assert "collector_error=no native BLS key" in bls_row["detail"]
    assert int(bls_row["row_count"]) == 0
    fred_health = health[health["source_id"] == "official:fred_alfred"].iloc[0]
    assert int(fred_health["row_count"]) == 2  # 1 event + 1 observation
    assert "series_covered=CPIAUCSL" in fred_health["detail"]
    assert "official:bls" in manifest.degraded_inputs
    # The collector's unavailable official:bls state degrades the artifact.
    assert manifest.artifacts["macro_observations.parquet"]["status"] == "degraded"


def test_stale_macro_collector_artifact_is_flagged(tmp_path, minimal_inputs):
    # P2-8: macro_observations_v1 has freshness thresholds so stale collector
    # artifacts are flagged and fail closed.
    macro_root = tmp_path / "input" / "macro"
    macro_root.mkdir(parents=True)
    stale_row = _collector_observation_row()
    stale_row["retrieved_at_utc"] = "2026-06-01T00:00:00Z"
    obs_path = macro_root / "macro_observations.parquet"
    materialize_macro_observations([stale_row]).to_parquet(obs_path, index=False)
    config = replace(
        minimal_inputs,
        macro_inputs=(
            LocalInput(
                source_id="macro_collector",
                path=obs_path,
                format="parquet",
                expected_schema=MACRO_OBSERVATIONS_SCHEMA_ID,
            ),
        ),
    )

    manifest = build_control_tower_marts(config)
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    health_row = health[health["source_id"] == "macro_collector"].iloc[0]

    assert health_row["status"] == "degraded"
    assert "stale_source" in health_row["detail"]
    assert any(
        error["code"] == "stale_source" for error in manifest.validation_errors
    )
    assert "macro_collector" in manifest.degraded_inputs
    assert manifest.artifacts["macro_observations.parquet"]["status"] == "degraded"


@pytest.mark.parametrize(
    "health_overrides",
    [
        {"source_license_class": None},
        {"entitlement_status": "entitlement_required"},
        {"entitlement_evidence": None},
        {"entitlement_ref": None},
        {"source_license_class": "public_metadata"},
    ],
)
def test_populated_consensus_without_accepted_provider_evidence_is_typed_empty(
    tmp_path, minimal_inputs, health_overrides
):
    consensus_dir = _write_task3_exports(
        tmp_path / "input" / "consensus",
        health_overrides=health_overrides,
    )
    config = replace(minimal_inputs, consensus_export_dir=consensus_dir)
    manifest = build_control_tower_marts(config)
    snapshots = pd.read_parquet(_published(config, "consensus_snapshots.parquet"))
    revisions = pd.read_parquet(_published(config, "consensus_revisions.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    provider = health.loc[health["source_id"].eq("consensus:akshare")].iloc[0]
    assert snapshots.empty
    assert revisions.empty
    assert provider["status"] == "degraded"
    assert "provider_entitlement_evidence_missing_or_unsupported" in provider["detail"]
    assert "consensus_export" in manifest.degraded_inputs


def test_provider_health_sidecar_keeps_accepted_provider_rows_separate(
    tmp_path, minimal_inputs
):
    consensus_dir = _write_task3_exports(tmp_path / "input" / "consensus")
    config = replace(minimal_inputs, consensus_export_dir=consensus_dir)
    build_control_tower_marts(config)
    snapshots = pd.read_parquet(_published(config, "consensus_snapshots.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    assert set(snapshots["provider"]) == {"akshare"}
    assert snapshots["raw_hash"].str.fullmatch(r"[0-9a-f]{64}").all()
    provider = health.loc[health["source_id"].eq("consensus:akshare")].iloc[0]
    assert provider["source_license_class"] == "local_private_research"
    assert provider["entitlement_status"] == "terms_unverified"
    assert provider["entitlement_evidence"]
    assert provider["entitlement_ref"] == "fixture-policy:local-private-research-v1"


def test_revision_prior_provider_without_sidecar_evidence_is_not_admitted(
    tmp_path, minimal_inputs
):
    consensus_dir = _write_task3_exports(
        tmp_path / "input" / "consensus",
        revision_overrides={"prior_provider": "yfinance"},
    )
    config = replace(minimal_inputs, consensus_export_dir=consensus_dir)
    build_control_tower_marts(config)
    revisions = pd.read_parquet(_published(config, "consensus_revisions.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    assert revisions.empty
    assert health.loc[health["source_id"].eq("consensus_export"), "status"].item() == "degraded"


def test_unknown_current_provider_with_valid_sidecar_is_typed_empty(
    tmp_path, minimal_inputs
):
    provider = "unsupported_provider"
    consensus_dir = _write_task3_exports(
        tmp_path / "input" / "consensus",
        snapshot_overrides={"provider": provider},
        revision_overrides={
            "provider": provider,
            "prior_provider": provider,
        },
        health_overrides={"provider": provider},
    )
    config = replace(minimal_inputs, consensus_export_dir=consensus_dir)
    manifest = build_control_tower_marts(config)
    snapshots = pd.read_parquet(_published(config, "consensus_snapshots.parquet"))
    revisions = pd.read_parquet(_published(config, "consensus_revisions.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    provider_health = health.loc[
        health["source_id"].eq(f"consensus:{provider}")
    ].iloc[0]

    assert snapshots.empty
    assert revisions.empty
    assert provider_health["status"] == "degraded"
    assert "provider_not_in_task3_allowlist" in provider_health["detail"]
    assert "consensus_export" in manifest.degraded_inputs


def test_unknown_prior_provider_with_valid_sidecar_removes_revision(
    tmp_path, minimal_inputs
):
    provider = "unsupported_provider"
    consensus_dir = _write_task3_exports(
        tmp_path / "input" / "consensus",
        revision_overrides={"prior_provider": provider},
        additional_health_providers=(provider,),
    )
    config = replace(minimal_inputs, consensus_export_dir=consensus_dir)
    manifest = build_control_tower_marts(config)
    snapshots = pd.read_parquet(_published(config, "consensus_snapshots.parquet"))
    revisions = pd.read_parquet(_published(config, "consensus_revisions.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    provider_health = health.loc[
        health["source_id"].eq(f"consensus:{provider}")
    ].iloc[0]

    assert set(snapshots["provider"]) == {"akshare"}
    assert revisions.empty
    assert provider_health["status"] == "degraded"
    assert "provider_not_in_task3_allowlist" in provider_health["detail"]
    assert "consensus_export" in manifest.degraded_inputs


def test_optional_macro_adapters_cover_ofr_taiwan_and_ecb(tmp_path, minimal_inputs):
    macro_root = tmp_path / "input" / "macro"
    macro_root.mkdir(parents=True)
    ofr_obs = macro_root / "ofr_timeseries.parquet"
    ofr_meta = macro_root / "ofr_mnemonics.parquet"
    tw_revenue = macro_root / "tw_monthly_revenue.parquet"
    ecb_fx = macro_root / "airline_fx_rates.parquet"
    pd.DataFrame(
        [{"date": "2026-07-17", "mnemonic": "FIXTURE_SERIES", "value": 1.5, "fetched_at": "2026-08-08T04:40:11Z"}]
    ).to_parquet(ofr_obs, index=False)
    pd.DataFrame(
        [{"mnemonic": "FIXTURE_SERIES", "name": "Fixture OFR series", "notes": "", "frequency": "Daily", "start_date": "2026-01-01", "last_update": "2026-07-20", "fetched_at": "2026-08-08T04:40:09Z"}]
    ).to_parquet(ofr_meta, index=False)
    pd.DataFrame(
        [{
            "dataset_id": "tw_monthly_revenue",
            "company_code": "2330",
            "company_name": "TSMC",
            "market": "TWSE",
            "industry": "Semiconductors",
            "filing_date": None,
            "revenue_month": "2026-06",
            "monthly_revenue_ntd": 100.0,
            "mom_pct": None,
            "mom_pct_is_derived": False,
            "yoy_pct": 20.0,
            "ytd_revenue_ntd": 600.0,
            "ytd_yoy_pct": 15.0,
            "source_url": "https://mops.twse.com.tw/mops/api/t05st10_ifrs",
            "source_run_id": "fixture-run",
            "scraped_at": "2026-08-07T14:23:57Z",
            "parser_version": "fixture",
            "raw_company_name_text": "TSMC",
            "raw_monthly_revenue_text": "100",
            "raw_mom_pct_text": None,
            "raw_yoy_pct_text": "20",
            "raw_ytd_revenue_text": "600",
            "raw_ytd_yoy_pct_text": "15",
        }]
    ).to_parquet(tw_revenue, index=False)
    pd.DataFrame(
        [{
            "dataset_id": "airline_fx_rates",
            "frequency": "daily",
            "observation_date": "2026-08-07",
            "pair": "USD_HKD",
            "base_currency": "USD",
            "quote_currency": "HKD",
            "value": 7.8,
            "unit": "quote currency per USD",
            "source_release_date": None,
            "retrieved_at": "2026-08-09T19:41:55Z",
            "source_name": "ECB",
            "source_url": "https://data-api.ecb.europa.eu/service/data/fixture",
            "source_reference_currency": "EUR",
        }]
    ).to_parquet(ecb_fx, index=False)
    config = replace(
        minimal_inputs,
        macro_inputs=(
            _input("ofr_observations", ofr_obs, OFR_OBSERVATIONS_SCHEMA_ID),
            _input("ofr_meta", ofr_meta, OFR_META_SCHEMA_ID),
            _input("tw_monthly_revenue", tw_revenue, TAIWAN_REVENUE_SCHEMA_ID),
            _input("ecb_fx_rates", ecb_fx, ECB_FX_SCHEMA_ID),
        ),
    )

    build_control_tower_marts(config)
    macro = pd.read_parquet(_published(config, "macro_observations.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    assert {"ofr_observations", "tw_monthly_revenue", "ecb_fx_rates"} <= set(macro["source_id"])
    assert macro.loc[macro["source_id"] == "ecb_fx_rates", "release_at"].isna().all()
    assert {"ofr_observations", "tw_monthly_revenue", "ecb_fx_rates"} <= set(health["source_id"])


def test_links_split_without_losing_index_targets(minimal_inputs):
    build_control_tower_marts(minimal_inputs)
    entity_links = pd.read_parquet(_published(minimal_inputs, "event_entity_links.parquet"))
    basket_links = pd.read_parquet(_published(minimal_inputs, "event_basket_links.parquet"))

    assert set(basket_links["target_type"]) == {"basket"}
    assert set(entity_links["target_type"]) == {"entity", "listing", "index"}


def test_unresolved_mapping_is_excluded_and_health_mentions_missing_geography(
    tmp_path, minimal_inputs
):
    news_path = tmp_path / "input" / "news" / "official_blog.parquet"
    news_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "dataset_id": "ai_news_blog_posts",
                "source_url": "https://example.test/rss.xml",
                "source_run_id": "fixture",
                "scraped_at": "2026-08-10T00:00:00Z",
                "first_seen_at": "2026-08-10T00:00:00Z",
                "last_seen_at": "2026-08-10T00:00:00Z",
                "source_name": "Official",
                "title": "Unrelated industry note on an unlisted vendor",
                "link": "https://example.test/zte",
                "pub_date": "Mon, 10 Aug 2026 09:00:00 +0000",
                "description": "ignored",
            }
        ]
    ).to_parquet(news_path, index=False)
    config = replace(
        minimal_inputs,
        news_inputs=(_input("official_ai_rss", news_path, NEWS_SCHEMA_ID),),
    )

    build_control_tower_marts(config)
    news = pd.read_parquet(_published(config, "news_filings.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    assert news.iloc[0]["related_entity_ids"] == "[]"
    assert news.iloc[0]["related_listing_ids"] == "[]"
    assert "CN" in " ".join(health["detail"].fillna(""))


def test_optional_missing_inputs_are_typed_and_unavailable(minimal_inputs):
    manifest = build_control_tower_marts(minimal_inputs)
    output = minimal_inputs.output_dir
    consensus = pd.read_parquet(_published(minimal_inputs, "consensus_snapshots.parquet"))
    revisions = pd.read_parquet(_published(minimal_inputs, "consensus_revisions.parquet"))
    quotes = pd.read_parquet(_published(minimal_inputs, "quote_snapshots.parquet"))
    news = pd.read_parquet(_published(minimal_inputs, "news_filings.parquet"))
    health = pd.read_parquet(_published(minimal_inputs, "source_health.parquet"))

    assert consensus.empty and list(consensus.columns) == TASK3_SNAPSHOT_COLUMNS
    assert revisions.empty and list(revisions.columns) == TASK3_REVISION_COLUMNS
    assert quotes.empty and list(quotes.columns) == QUOTE_SNAPSHOT_COLUMNS
    assert news.empty
    unavailable = health[health["status"] == "unavailable"]
    assert {"consensus_export", "quote_snapshots", "news_official_ai_rss", "filings_sec_edgar"} <= set(
        unavailable["source_id"]
    )
    assert manifest.degraded_inputs


def test_quote_snapshot_input_is_normalized_into_optional_artifact(tmp_path, minimal_inputs):
    listings = pd.read_csv(minimal_inputs.registry_root / "listings.csv")
    listing = listings.loc[listings["listing_status"].astype("string").str.lower().eq("active")].iloc[0]
    row = {column: None for column in QUOTE_SNAPSHOT_COLUMNS}
    row.update({
        "quote_id": "quote-fixture-1",
        "listing_id": listing["listing_id"],
        "canonical_ticker": listing["canonical_ticker"],
        "provider_symbol": listing["native_ticker"],
        "quote_timestamp": "2026-08-13T11:59:00Z",
        "retrieved_at_utc": "2026-08-13T12:00:00Z",
        "last_price": 123.45,
        "bid": 123.40,
        "ask": 123.50,
        "day_change_pct": 1.2,
        "volume": 1000.0,
        "currency": listing["currency"],
        "market_status": "open",
        "latency_class": "realtime",
        "source_id": "fixture_quotes",
        "source_url": "https://example.test/quotes",
        "pit_class": "snapshot_from_live_source",
        "source_license_class": "public_metadata",
        "registry_version": "v1",
    })
    quote_path = tmp_path / "quotes.parquet"
    pd.DataFrame([row], columns=QUOTE_SNAPSHOT_COLUMNS).to_parquet(quote_path, index=False)
    config = replace(
        minimal_inputs,
        quote_inputs=(
            _input(
                "fixture_quotes",
                quote_path,
                QUOTE_SNAPSHOT_SCHEMA_ID,
                license_class="public_metadata",
            ),
        ),
    )

    manifest = build_control_tower_marts(config)
    quotes = pd.read_parquet(_published(config, "quote_snapshots.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    assert manifest.artifacts["quote_snapshots.parquet"]["status"] == "available"
    assert list(quotes.columns) == QUOTE_SNAPSHOT_COLUMNS
    assert len(quotes) == 1
    assert quotes.iloc[0]["last_price"] == 123.45
    assert quotes.iloc[0]["latency_class"] == "delayed"
    assert quotes.iloc[0]["pit_class"] == "snapshot_from_delayed_source"
    assert quotes.iloc[0]["source_license_class"] == "personal_use_terms_unverified"
    assert health.loc[health["source_id"].eq("fixture_quotes"), "status"].item() == "available"


def test_quote_local_input_defaults_are_delayed_and_personal_use(tmp_path):
    descriptor = LocalInput(
        source_id="quote_defaults",
        path=tmp_path / "quotes.parquet",
        format="parquet",
        expected_schema=QUOTE_SNAPSHOT_SCHEMA_ID,
    )
    assert descriptor.pit_class == "snapshot_from_delayed_source"
    assert descriptor.license_class == "personal_use_terms_unverified"


@pytest.mark.parametrize(
    ("rejection", "listing_id"),
    [("archived", "NVDA_US"), ("future", "BABA_US"), ("private", "BABA_US")],
)
def test_builder_rejects_ineligible_quote_registry_rows(
    tmp_path, minimal_inputs, rejection, listing_id
):
    listings_path = minimal_inputs.registry_root / "listings.csv"
    listings = pd.read_csv(listings_path, keep_default_na=False)
    if rejection == "future":
        listings.loc[listings["listing_id"].eq(listing_id), "active_from"] = "2030-01-01"
        listings.to_csv(listings_path, index=False)
    listing = listings.loc[listings["listing_id"].eq(listing_id)].iloc[0]
    if rejection == "private":
        entities_path = minimal_inputs.registry_root / "entities.csv"
        entities = pd.read_csv(entities_path, keep_default_na=False)
        entities.loc[entities["entity_id"].eq(listing["entity_id"]), "entity_type"] = "private"
        entities.to_csv(entities_path, index=False)

    quote_path = tmp_path / f"{rejection}.parquet"
    pd.DataFrame([_active_quote_row(listing)], columns=QUOTE_SNAPSHOT_COLUMNS).to_parquet(
        quote_path, index=False
    )
    config = replace(
        minimal_inputs,
        quote_inputs=(_input(f"bad_{rejection}", quote_path, QUOTE_SNAPSHOT_SCHEMA_ID),),
    )
    build_control_tower_marts(config)
    quotes = pd.read_parquet(_published(config, "quote_snapshots.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    assert quotes.empty
    assert health.loc[health["source_id"].eq(f"bad_{rejection}"), "status"].item() == "degraded"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("canonical_ticker", "WRONG.TICKER"),
        ("currency", "EUR"),
        ("provider_symbol", "WRONG_SYMBOL"),
    ],
)
def test_builder_rejects_quote_identity_mismatches(tmp_path, minimal_inputs, field, value):
    listings = pd.read_csv(minimal_inputs.registry_root / "listings.csv")
    listing = listings.loc[listings["listing_status"].astype("string").str.lower().eq("active")].iloc[0]
    row = _active_quote_row(listing)
    row[field] = value
    quote_path = tmp_path / f"mismatch-{field}.parquet"
    pd.DataFrame([row], columns=QUOTE_SNAPSHOT_COLUMNS).to_parquet(quote_path, index=False)
    config = replace(
        minimal_inputs,
        quote_inputs=(_input(f"mismatch_{field}", quote_path, QUOTE_SNAPSHOT_SCHEMA_ID),),
    )

    build_control_tower_marts(config)
    quotes = pd.read_parquet(_published(config, "quote_snapshots.parquet"))
    assert quotes.empty


def _active_quote_row(listing: pd.Series, *, source_id: str = "market:yfinance", price: float = 123.45) -> dict:
    row = {column: None for column in QUOTE_SNAPSHOT_COLUMNS}
    row.update(
        {
            "quote_id": f"quote-{listing['listing_id']}-{price}",
            "listing_id": listing["listing_id"],
            "canonical_ticker": listing["canonical_ticker"],
            "provider_symbol": str(listing["vendor_tickers"]).split(";")[0].split(":", 1)[-1],
            "quote_timestamp": "2026-08-13T11:59:00Z",
            "retrieved_at_utc": "2026-08-13T12:00:00Z",
            "last_price": price,
            "currency": listing["currency"],
            "market_status": "unknown",
            "latency_class": "delayed",
            "source_id": source_id,
            "source_url": "https://example.test/quotes",
            "pit_class": "snapshot_from_delayed_source",
            "source_license_class": "personal_use_terms_unverified",
            "registry_version": "v1",
        }
    )
    return row


def test_quote_status_sidecar_propagates_partial_diagnostics_and_quote_age(
    tmp_path, minimal_inputs
):
    listings = pd.read_csv(minimal_inputs.registry_root / "listings.csv")
    listing = listings.loc[listings["listing_status"].astype("string").str.lower().eq("active")].iloc[0]
    quote_path = tmp_path / "quotes.parquet"
    pd.DataFrame([_active_quote_row(listing)], columns=QUOTE_SNAPSHOT_COLUMNS).to_parquet(
        quote_path, index=False
    )
    sidecar_path = tmp_path / "quotes.status.json"
    sidecar_path.write_text(
        json.dumps(
            {
                "schema": "quote_collection_status_v1",
                "aggregate_status": "partial",
                "row_count": 1,
                "expected_listing_count": 2,
                "diagnostic_count": 1,
                "diagnostics": [
                    {
                        "symbol": "MISSING",
                        "listing_id": "MISSING_LISTING",
                        "entity_id": "MISSING_ENTITY",
                        "status": "no_records",
                        "reason": "missing provider row",
                    }
                ],
                "issues": ["one listing returned no record"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    config = replace(
        minimal_inputs,
        quote_inputs=(
            LocalInput(
                source_id="market:yfinance",
                path=quote_path,
                format="parquet",
                expected_schema=QUOTE_SNAPSHOT_SCHEMA_ID,
                status_path=sidecar_path,
                source_priority=10,
            ),
        ),
    )

    manifest = build_control_tower_marts(config)
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    quote_health = health.loc[health["source_id"].eq("market:yfinance")].iloc[0]

    assert manifest.status == "degraded"
    assert manifest.artifacts["quote_snapshots.parquet"]["status"] == "degraded"
    assert "market:yfinance" in manifest.degraded_inputs
    assert str(sidecar_path) in manifest.input_fingerprints
    assert quote_health["status"] == "partial"
    assert quote_health["source_latest_at"] == pd.Timestamp("2026-08-13T11:59:00Z")
    assert quote_health["retrieved_at_utc"] == pd.Timestamp("2026-08-13T12:00:00Z")
    assert "collector_status=partial" in str(quote_health["detail"])
    assert "diagnostic_statuses=no_records:1" in str(quote_health["detail"])


def test_empty_quote_output_is_unavailable_without_execution_evidence(tmp_path, minimal_inputs):
    # P2-7: an empty frame is no_records only with execution evidence (status
    # sidecar); without evidence it is unavailable, never available.
    quote_path = tmp_path / "empty_quotes.parquet"
    pd.DataFrame(columns=QUOTE_SNAPSHOT_COLUMNS).to_parquet(quote_path, index=False)
    config = replace(
        minimal_inputs,
        quote_inputs=(
            LocalInput(
                source_id="empty_quotes",
                path=quote_path,
                format="parquet",
                expected_schema=QUOTE_SNAPSHOT_SCHEMA_ID,
            ),
        ),
    )

    manifest = build_control_tower_marts(config)
    health = pd.read_parquet(_published(config, "source_health.parquet"))

    assert manifest.artifacts["quote_snapshots.parquet"]["status"] == "unavailable"
    assert health.loc[health["source_id"].eq("empty_quotes"), "status"].item() == "unavailable"


def test_quote_source_priority_is_explicit_not_lexicographic(tmp_path, minimal_inputs):
    listings = pd.read_csv(minimal_inputs.registry_root / "listings.csv")
    listing = listings.loc[listings["listing_status"].astype("string").str.lower().eq("active")].iloc[0]
    preferred_path = tmp_path / "preferred.parquet"
    fallback_path = tmp_path / "fallback.parquet"
    pd.DataFrame([_active_quote_row(listing, source_id="z_preferred", price=200.0)], columns=QUOTE_SNAPSHOT_COLUMNS).to_parquet(preferred_path, index=False)
    pd.DataFrame([_active_quote_row(listing, source_id="a_fallback", price=100.0)], columns=QUOTE_SNAPSHOT_COLUMNS).to_parquet(fallback_path, index=False)
    config = replace(
        minimal_inputs,
        quote_inputs=(
            LocalInput(source_id="z_preferred", path=preferred_path, format="parquet", expected_schema=QUOTE_SNAPSHOT_SCHEMA_ID, source_priority=1),
            LocalInput(source_id="a_fallback", path=fallback_path, format="parquet", expected_schema=QUOTE_SNAPSHOT_SCHEMA_ID, source_priority=20),
        ),
    )

    build_control_tower_marts(config)
    quotes = pd.read_parquet(_published(config, "quote_snapshots.parquet"))

    assert len(quotes) == 1
    assert quotes.iloc[0]["source_id"] == "z_preferred"
    assert quotes.iloc[0]["last_price"] == 200.0


def test_task3_contract_is_current_29_35_and_physical_empty_schema_is_stable(
    tmp_path, minimal_inputs
):
    assert len(TASK3_SNAPSHOT_COLUMNS) == 29
    assert len(TASK3_REVISION_COLUMNS) == 35
    empty_config = replace(minimal_inputs, output_dir=tmp_path / "output-empty")
    populated_config = replace(
        minimal_inputs,
        output_dir=tmp_path / "output-populated",
        consensus_export_dir=_write_task3_exports(tmp_path / "input" / "consensus"),
    )
    build_control_tower_marts(empty_config)
    build_control_tower_marts(populated_config)
    empty_root = current_generation(empty_config.output_dir)
    populated_root = current_generation(populated_config.output_dir)
    expected = {
        "consensus_snapshots.parquet": TASK3_SNAPSHOT_ARROW_SCHEMA,
        "consensus_revisions.parquet": TASK3_REVISION_ARROW_SCHEMA,
    }
    for name, task3_schema in expected.items():
        empty_schema = pq.read_schema(empty_root / name)
        populated_schema = pq.read_schema(populated_root / name)
        assert empty_schema == populated_schema
        assert empty_schema == task3_schema

    sys.path.insert(0, str(TASK5_APP_ROOT))
    try:
        from control_tower.repository import ControlTowerRepository

        snapshot = ControlTowerRepository(populated_config.output_dir).load_snapshot()
    finally:
        sys.path.remove(str(TASK5_APP_ROOT))
    assert len(snapshot.consensus_snapshots) == 1
    assert len(snapshot.consensus_revisions) == 1


@pytest.mark.parametrize(
    ("export_kwargs", "expected_source_id"),
    [
        (
            {
                "revision_overrides": {
                    "provider_asof": pd.Timestamp("2026-08-14T00:00:00Z"),
                }
            },
            "consensus_export",
        ),
        (
            {
                "health_overrides": {
                    "as_of": pd.Timestamp("2026-08-14T00:00:00Z"),
                }
            },
            "consensus:akshare",
        ),
    ],
)
def test_task3_future_revision_and_health_timestamps_degrade_with_structured_errors(
    tmp_path,
    minimal_inputs,
    export_kwargs,
    expected_source_id,
):
    consensus_dir = _write_task3_exports(
        tmp_path / f"input/{expected_source_id.replace(':', '-')}",
        **export_kwargs,
    )
    config = replace(minimal_inputs, consensus_export_dir=consensus_dir)

    manifest = build_control_tower_marts(config)
    health = pd.read_parquet(_published(config, "source_health.parquet"))

    source_row = health.loc[health["source_id"].eq(expected_source_id)].iloc[0]
    assert source_row["status"] == "degraded"
    assert "future_row_beyond_as_of" in source_row["detail"]
    assert any(
        error["source_id"] == expected_source_id
        and error["code"] == "future_row_beyond_as_of"
        for error in manifest.validation_errors
    )
    assert pd.read_parquet(_published(config, "consensus_snapshots.parquet")).empty
    assert pd.read_parquet(_published(config, "consensus_revisions.parquet")).empty


@pytest.mark.parametrize(
    ("export_kwargs", "expected_source_id"),
    [
        (
            {
                "revision_overrides": {
                    "current_snapshot_at": pd.Timestamp("2026-07-01T00:00:00Z"),
                    "provider_asof": pd.Timestamp("2026-07-01T00:00:00Z"),
                    "retrieved_at_utc": pd.Timestamp("2026-07-01T01:00:00Z"),
                }
            },
            "consensus_export",
        ),
        (
            {
                "health_overrides": {
                    "as_of": pd.Timestamp("2026-07-01T00:00:00Z"),
                }
            },
            "consensus:akshare",
        ),
    ],
)
def test_task3_stale_revision_and_health_retrieval_degrade_by_consensus_threshold(
    tmp_path,
    minimal_inputs,
    export_kwargs,
    expected_source_id,
):
    consensus_dir = _write_task3_exports(
        tmp_path / f"input/stale-{expected_source_id.replace(':', '-')}",
        **export_kwargs,
    )
    config = replace(minimal_inputs, consensus_export_dir=consensus_dir)

    manifest = build_control_tower_marts(config)
    health = pd.read_parquet(_published(config, "source_health.parquet"))

    source_row = health.loc[health["source_id"].eq(expected_source_id)].iloc[0]
    assert source_row["status"] == "degraded"
    assert "stale_source" in source_row["detail"]
    assert any(
        error["source_id"] == expected_source_id
        and error["code"] == "stale_source"
        for error in manifest.validation_errors
    )
    assert pd.read_parquet(_published(config, "consensus_snapshots.parquet")).empty
    assert pd.read_parquet(_published(config, "consensus_revisions.parquet")).empty


def test_full_manifest_records_hash_size_rows_and_schema(minimal_inputs):
    build_control_tower_marts(minimal_inputs)
    generation = current_generation(minimal_inputs.output_dir)
    manifest = _manifest(minimal_inputs)
    for name in ARTIFACT_NAMES:
        record = manifest["artifacts"][name]
        path = generation / name
        assert record["relative_path"] == name
        assert record["byte_size"] == path.stat().st_size
        if name == "build_manifest.json":
            assert record["row_count"] == 1
        else:
            assert record["row_count"] == pq.read_metadata(path).num_rows
        if name != "build_manifest.json":
            assert record["sha256"] == _sha256(path)
            assert record["schema_version"] == "control_tower_marts_v1"


def test_catalyst_eligibility_matches_task2_and_excludes_coverage_gaps(minimal_inputs):
    build_control_tower_marts(minimal_inputs)
    events = pd.read_parquet(_published(minimal_inputs, "events.parquet"))
    assert catalyst_eligibility(events).equals(is_catalyst_eligible(events))
    gaps = events[events["event_type"].eq("coverage_gap")]
    assert not gaps.empty
    assert not catalyst_eligibility(gaps).any()


def test_failed_generation_write_preserves_current_and_cleans_staging(minimal_inputs, monkeypatch):
    build_control_tower_marts(minimal_inputs)
    successor = replace(
        minimal_inputs,
        as_of_utc=minimal_inputs.as_of_utc + pd.Timedelta(seconds=1),
        build_id="fixture-build-write-failure",
    )
    old_pointer = (minimal_inputs.output_dir / "CURRENT").read_bytes()
    import src.research_control_tower.build as build_module

    original_write = build_module._write_parquet
    calls = {"count": 0}

    def fail_after_first(path, frame, schema):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("forced generation write failure")
        return original_write(path, frame, schema)

    monkeypatch.setattr(build_module, "_write_parquet", fail_after_first)
    with pytest.raises(OSError, match="forced generation write failure"):
        build_control_tower_marts(successor)
    assert (minimal_inputs.output_dir / "CURRENT").read_bytes() == old_pointer
    assert current_generation(minimal_inputs.output_dir).name == old_pointer.decode().strip().split("/")[-1]
    assert not list(minimal_inputs.output_dir.glob(".research-control-tower-*"))


def test_failed_generation_publish_preserves_current_and_leaves_no_partial_generation(
    minimal_inputs, monkeypatch
):
    build_control_tower_marts(minimal_inputs)
    minimal_inputs = replace(
        minimal_inputs,
        as_of_utc=minimal_inputs.as_of_utc + pd.Timedelta(seconds=1),
        build_id="fixture-build-publish-failure",
    )
    old_pointer = (minimal_inputs.output_dir / "CURRENT").read_bytes()
    import src.research_control_tower.build as build_module

    original_replace = build_module.os.replace

    def fail_generation(source, destination):
        if Path(destination).parent.name == "generations":
            raise OSError("forced generation publish failure")
        return original_replace(source, destination)

    monkeypatch.setattr(build_module.os, "replace", fail_generation)
    with pytest.raises(OSError, match="forced generation publish failure"):
        build_control_tower_marts(minimal_inputs)
    assert (minimal_inputs.output_dir / "CURRENT").read_bytes() == old_pointer
    assert len(list((minimal_inputs.output_dir / "generations").iterdir())) == 1
    assert not list(minimal_inputs.output_dir.glob(".research-control-tower-*"))


def test_failed_current_switch_preserves_old_current_and_keeps_new_immutable_generation(
    minimal_inputs, monkeypatch
):
    build_control_tower_marts(minimal_inputs)
    minimal_inputs = replace(
        minimal_inputs,
        as_of_utc=minimal_inputs.as_of_utc + pd.Timedelta(seconds=1),
        build_id="fixture-build-pointer-failure",
    )
    old_pointer = (minimal_inputs.output_dir / "CURRENT").read_bytes()
    import src.research_control_tower.build as build_module

    original_replace = build_module.os.replace

    def fail_current(source, destination):
        if Path(destination).name == "CURRENT":
            raise OSError("forced CURRENT switch failure")
        return original_replace(source, destination)

    monkeypatch.setattr(build_module.os, "replace", fail_current)
    with pytest.raises(OSError, match="forced CURRENT switch failure"):
        build_control_tower_marts(minimal_inputs)
    assert (minimal_inputs.output_dir / "CURRENT").read_bytes() == old_pointer
    assert len(list((minimal_inputs.output_dir / "generations").iterdir())) == 2
    assert not list(minimal_inputs.output_dir.glob(".research-control-tower-*"))


def test_corrupt_optional_parquet_degrades_without_replacing_current(tmp_path, minimal_inputs):
    corrupt = tmp_path / "input" / "news" / "corrupt.parquet"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"not parquet")
    config = replace(minimal_inputs, news_inputs=(_input("corrupt_news", corrupt, NEWS_SCHEMA_ID),))
    manifest = build_control_tower_marts(config)
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    assert health.loc[health["source_id"].eq("corrupt_news"), "status"].iloc[0] == "degraded"
    assert any(error["source_id"] == "corrupt_news" for error in manifest.validation_errors)


def test_future_optional_rows_fail_closed_and_required_future_rows_fail_build(tmp_path, minimal_inputs):
    future = tmp_path / "input" / "macro" / "future.parquet"
    future.parent.mkdir(parents=True)
    pd.DataFrame(
        [{"date": "2026-08-14", "series_id": "NFCI", "value": 0.1, "fetched_at": "2026-08-14T01:00:00Z"}]
    ).to_parquet(future, index=False)
    meta = tmp_path / "input" / "macro" / "meta.parquet"
    pd.DataFrame(
        [{
            "series_id": "NFCI",
            "title": "NFCI",
            "frequency": "W",
            "units": "Index",
            "seasonal_adjustment": "NSA",
            "observation_start": "1971-01-08",
            "last_updated": "2026-08-13T00:00:00Z",
            "fetched_at": "2026-08-13T01:00:00Z",
        }]
    ).to_parquet(meta, index=False)
    config = replace(
        minimal_inputs,
        macro_inputs=(
            _input("future_fred", future, FRED_OBSERVATIONS_SCHEMA_ID),
            _input("future_fred_meta", meta, FRED_META_SCHEMA_ID),
        ),
    )
    manifest = build_control_tower_marts(config)
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    row = health.loc[health["source_id"].eq("future_fred")].iloc[0]
    assert row["status"] == "degraded"
    assert "future_row_beyond_as_of" in row["detail"]
    assert any(error["code"] == "future_row_beyond_as_of" for error in manifest.validation_errors)

    required_config = replace(
        config,
        macro_inputs=(
            replace(config.macro_inputs[0], required=True),
            config.macro_inputs[1],
        ),
    )
    with pytest.raises(BuildError, match="freshness policy"):
        build_control_tower_marts(required_config)


def test_stale_optional_rows_degrade_by_source_threshold(tmp_path, minimal_inputs):
    stale = tmp_path / "input" / "macro" / "stale.parquet"
    stale.parent.mkdir(parents=True)
    pd.DataFrame(
        [{"date": "2026-07-01", "series_id": "NFCI", "value": 0.1, "fetched_at": "2026-07-02T01:00:00Z"}]
    ).to_parquet(stale, index=False)
    meta = tmp_path / "input" / "macro" / "meta.parquet"
    pd.DataFrame(
        [{
            "series_id": "NFCI",
            "title": "NFCI",
            "frequency": "W",
            "units": "Index",
            "seasonal_adjustment": "NSA",
            "observation_start": "1971-01-08",
            "last_updated": "2026-07-02T00:00:00Z",
            "fetched_at": "2026-07-02T01:00:00Z",
        }]
    ).to_parquet(meta, index=False)
    config = replace(
        minimal_inputs,
        macro_inputs=(
            _input("stale_fred", stale, FRED_OBSERVATIONS_SCHEMA_ID),
            _input("stale_fred_meta", meta, FRED_META_SCHEMA_ID),
        ),
    )
    build_control_tower_marts(config)
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    assert health.loc[health["source_id"].eq("stale_fred"), "status"].iloc[0] == "degraded"
    assert "stale_source" in health.loc[health["source_id"].eq("stale_fred"), "detail"].iloc[0]

    # Staleness degrades the source; it does not delete the evidence. The rows
    # were validly collected and are simply older than the freshness window, so
    # they reach the mart and the reason travels in source_health beside them.
    # Dropping them emptied 13,598 real ECB FX observations off the dashboard
    # while reporting the source as merely "unavailable".
    observations = pd.read_parquet(_published(config, "macro_observations.parquet"))
    assert not observations.empty
    assert (observations["source_id"] == "stale_fred").any()


def test_stale_rows_are_retained_but_future_rows_still_fail_closed(tmp_path, minimal_inputs):
    """Staleness and lookahead are different failures and must stay different.

    A stale row is real evidence that is merely old. A row dated after as_of
    would leak lookahead into anything built on it, so it still fails closed --
    the relaxation that carries stale rows through must not widen to cover it.
    """
    def _write(path: Path, date_value: str, fetched_at: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [{"date": date_value, "series_id": "NFCI", "value": 0.1, "fetched_at": fetched_at}]
        ).to_parquet(path, index=False)
        return path

    def _meta(path: Path, last_updated: str, fetched_at: str) -> Path:
        pd.DataFrame(
            [{
                "series_id": "NFCI", "title": "NFCI", "frequency": "W", "units": "Index",
                "seasonal_adjustment": "NSA", "observation_start": "1971-01-08",
                "last_updated": last_updated, "fetched_at": fetched_at,
            }]
        ).to_parquet(path, index=False)
        return path

    stale = _write(tmp_path / "stale" / "obs.parquet", "2026-07-01", "2026-07-02T01:00:00Z")
    stale_meta = _meta(tmp_path / "stale" / "meta.parquet", "2026-07-02T00:00:00Z", "2026-07-02T01:00:00Z")
    stale_config = replace(
        minimal_inputs,
        macro_inputs=(
            _input("stale_fred", stale, FRED_OBSERVATIONS_SCHEMA_ID),
            _input("stale_fred_meta", stale_meta, FRED_META_SCHEMA_ID),
        ),
    )
    build_control_tower_marts(stale_config)
    stale_rows = pd.read_parquet(_published(stale_config, "macro_observations.parquet"))
    assert (stale_rows["source_id"] == "stale_fred").any(), "stale evidence must be retained"

    future_dir = tmp_path / "future"
    ahead = _write(future_dir / "obs.parquet", "2026-09-30", "2026-09-30T01:00:00Z")
    ahead_meta = _meta(future_dir / "meta.parquet", "2026-09-30T00:00:00Z", "2026-09-30T01:00:00Z")
    future_config = replace(
        minimal_inputs,
        output_dir=tmp_path / "future-out",
        macro_inputs=(
            _input("future_fred", ahead, FRED_OBSERVATIONS_SCHEMA_ID),
            _input("future_fred_meta", ahead_meta, FRED_META_SCHEMA_ID),
        ),
    )
    build_control_tower_marts(future_config)
    future_rows = pd.read_parquet(_published(future_config, "macro_observations.parquet"))
    future_health = pd.read_parquet(_published(future_config, "source_health.parquet"))
    assert not (future_rows["source_id"] == "future_fred").any(), "lookahead must fail closed"
    detail = future_health.loc[future_health["source_id"].eq("future_fred"), "detail"].iloc[0]
    assert "future_row_beyond_as_of" in detail


def test_current_pointer_and_generation_reject_symlinks(minimal_inputs):
    build_control_tower_marts(minimal_inputs)
    generation = current_generation(minimal_inputs.output_dir)
    link = minimal_inputs.output_dir / "generations" / "link"
    link.symlink_to(generation, target_is_directory=True)
    pointer = minimal_inputs.output_dir / "CURRENT"
    pointer.write_text("generations/link\n")
    with pytest.raises(BuildError, match="symlink"):
        current_generation(minimal_inputs.output_dir)


def test_optional_schema_failure_is_degraded_and_typed(tmp_path, minimal_inputs):
    bad_path = tmp_path / "input" / "news" / "bad.parquet"
    bad_path.parent.mkdir(parents=True)
    pd.DataFrame({"unexpected": [1]}).to_parquet(bad_path, index=False)
    config = replace(
        minimal_inputs,
        news_inputs=(_input("bad_news", bad_path, NEWS_SCHEMA_ID),),
    )

    manifest = build_control_tower_marts(config)
    news = pd.read_parquet(_published(config, "news_filings.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    bad_health = health[health["source_id"] == "bad_news"].iloc[0]

    assert news.empty and list(news.columns) == [
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
    assert bad_health["status"] == "degraded"
    assert "schema drift" in bad_health["detail"]
    assert "bad_news" in manifest.degraded_inputs


def test_optional_failure_commits_a_complete_degraded_set(tmp_path, minimal_inputs):
    bad_path = tmp_path / "input" / "news" / "bad.parquet"
    bad_path.parent.mkdir(parents=True)
    pd.DataFrame({"unexpected": [1]}).to_parquet(bad_path, index=False)
    config = replace(
        minimal_inputs,
        news_inputs=(_input("bad_news", bad_path, NEWS_SCHEMA_ID),),
    )

    manifest = build_control_tower_marts(config)
    assert manifest.status == "degraded"
    assert set(path.name for path in current_generation(config.output_dir).iterdir()) == set(ARTIFACT_NAMES)
    assert not list(config.output_dir.glob(".research-control-tower-*"))


def test_disallowing_optional_degradation_fails_before_output_replacement(
    minimal_inputs,
):
    config = replace(minimal_inputs, allow_degraded_optional=False)
    with pytest.raises(BuildError, match="allow_degraded_optional=False"):
        build_control_tower_marts(config)
    assert not config.output_dir.exists()


def test_required_failure_preserves_existing_final_artifact(tmp_path, minimal_inputs):
    output = minimal_inputs.output_dir
    output.mkdir(parents=True)
    sentinel = output / "entities.parquet"
    sentinel.write_bytes(b"old-final-artifact")
    old_manifest = output / "build_manifest.json"
    old_manifest.write_text('{"build_id":"old"}\n')

    events_path = minimal_inputs.event_root / "events.csv"
    original = events_path.read_text()
    events_path.write_text(original.replace(",actual_unit,", ",", 1))
    try:
        with pytest.raises((BuildError, ValueError)):
            build_control_tower_marts(minimal_inputs)
    finally:
        events_path.write_text(original)

    assert sentinel.read_bytes() == b"old-final-artifact"
    assert old_manifest.read_text() == '{"build_id":"old"}\n'


def test_manifest_is_replaced_last_and_only_exact_paths_are_replaced(
    minimal_inputs, monkeypatch
):
    import src.research_control_tower.build as build_module

    replacements: list[str] = []
    original_replace = os.replace

    def record_replace(source, destination):
        replacements.append(Path(destination).name)
        return original_replace(source, destination)

    monkeypatch.setattr(build_module.os, "replace", record_replace)
    build_control_tower_marts(minimal_inputs)

    assert replacements[-1] == "CURRENT"
    assert replacements[0] == current_generation(minimal_inputs.output_dir).name
    assert set(replacements) == {current_generation(minimal_inputs.output_dir).name, "CURRENT"}


def test_build_is_deterministic_for_same_inputs(tmp_path):
    input_root = _copy_control_tower_inputs(tmp_path / "input" / "config")
    left = BuildConfig(
        registry_root=input_root,
        event_root=input_root,
        output_dir=tmp_path / "left",
        as_of_utc=pd.Timestamp("2026-08-13T12:00:00Z"),
        build_id="deterministic-build-v1",
    )
    right = replace(left, output_dir=tmp_path / "right")
    build_control_tower_marts(left)
    build_control_tower_marts(right)

    left_generation = current_generation(left.output_dir)
    right_generation = current_generation(right.output_dir)
    assert left_generation.name == right_generation.name
    for name in ARTIFACT_NAMES:
        assert (left_generation / name).read_bytes() == (right_generation / name).read_bytes()


def test_cli_help_exposes_build_command():
    result = subprocess.run(
        [sys.executable, "-m", "src.research_control_tower.cli", "--help"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "build" in result.stdout


def _write_official_filings_inputs(tmp_path: Path) -> tuple[Path, Path]:
    filings = pd.DataFrame(
        [
            {
                "document_id": "hkexnews:2026081201234",
                "document_type": "announcement",
                "event_class": "earnings_results",
                "source_id": "hkexnews",
                "headline": "ANNOUNCEMENT OF THE RESULTS FOR THE THREE AND SIX MONTHS ENDED 30 JUNE 2026",
                "publisher": "HKEXnews",
                "published_at": "2026-08-12T08:31:00Z",
                "accepted_at": "2026-08-12T08:31:00Z",
                "scheduled_date": None,
                "retrieved_at_utc": "2026-08-13T12:00:00Z",
                "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0812/2026081201234.htm",
                "language": "en",
                "entity_id": "TENCENT",
                "listing_id": "0700_HK",
                "canonical_ticker": "0700.HK",
                "reporting_period_label": "1H2026",
                "reporting_period_start": "2025-12-30",
                "reporting_period_end": "2026-06-30",
                "date_precision": "minute",
                "source_timezone": "Asia/Hong_Kong",
                "event_status": "observed",
                "source_quality": "official_metadata",
                "pit_class": "snapshot_from_live_source",
                "source_license_class": "official_public_metadata",
                "content_hash_if_permitted": "",
                "source_note": "fixture HKEX announcement metadata",
                "registry_version": "v1",
            },
            {
                "document_id": "sec:0001104659-26-096226",
                "document_type": "filing",
                "event_class": "general",
                "source_id": "sec_edgar_submissions",
                "headline": "Alibaba Group Holding Ltd — Form 6-K — FORM 6-K",
                "publisher": "SEC EDGAR",
                "published_at": "2026-08-10T14:02:25Z",
                "accepted_at": "2026-08-10T14:02:25Z",
                "scheduled_date": None,
                "retrieved_at_utc": "2026-08-13T12:00:00Z",
                "source_url": "https://www.sec.gov/Archives/edgar/data/1577552/000110465926096226/tm2623260d1_6k.htm",
                "language": "en",
                "entity_id": "ALIBABA",
                "listing_id": "BABA_US",
                "canonical_ticker": "BABA.US",
                "reporting_period_label": "",
                "reporting_period_start": None,
                "reporting_period_end": None,
                "date_precision": "minute",
                "source_timezone": "UTC",
                "event_status": "observed",
                "source_quality": "official_metadata",
                "pit_class": "snapshot_from_live_source",
                "source_license_class": "official_public_metadata",
                "content_hash_if_permitted": "",
                "source_note": "fixture SEC submissions metadata",
                "registry_version": "v1",
            },
        ],
        columns=OFFICIAL_FILINGS_COLUMNS,
    )
    state = pd.DataFrame(
        [
            {
                "source_id": "filings:sec_edgar_submissions",
                "source_kind": "official_filing",
                "status": "available",
                "detail": "sec_submissions_metadata rows=1",
                "row_count": 1,
                "retrieved_at_utc": "2026-08-13T12:00:00Z",
                "source_url": "https://data.sec.gov/submissions/",
                "pit_class": "snapshot_from_live_source",
                "source_license_class": "official_public_metadata",
                "cadence": "daily",
            },
            {
                "source_id": "filings:hkexnews",
                "source_kind": "official_filing",
                "status": "available",
                "detail": "hkexnews_title_search rows=1",
                "row_count": 1,
                "retrieved_at_utc": "2026-08-13T12:00:00Z",
                "source_url": "https://www1.hkexnews.hk/",
                "pit_class": "snapshot_from_live_source",
                "source_license_class": "official_public_metadata",
                "cadence": "daily",
            },
            {
                "source_id": "filings:issuer_ir",
                "source_kind": "official_filing",
                "status": "no_records",
                "detail": "no machine-readable issuer IR snapshot configured",
                "row_count": 0,
                "retrieved_at_utc": "2026-08-13T12:00:00Z",
                "pit_class": "snapshot_from_live_source",
                "source_license_class": "official_public_metadata",
                "cadence": "monthly",
            },
            {
                "source_id": "filings:bytedance",
                "source_kind": "official_filing",
                "status": "not_applicable",
                "detail": "private company; no public filings",
                "row_count": 0,
                "retrieved_at_utc": "2026-08-13T12:00:00Z",
                "pit_class": "snapshot_from_live_source",
                "source_license_class": "official_public_metadata",
                "cadence": "",
            },
        ],
        columns=SOURCE_STATE_COLUMNS,
    )
    filings_path = tmp_path / "official_filings_v1.parquet"
    state_path = tmp_path / "official_filings_state.parquet"
    filings.to_parquet(filings_path, index=False)
    state.to_parquet(state_path, index=False)
    return filings_path, state_path


def _write_earnings_inputs(tmp_path: Path) -> tuple[Path, Path]:
    actuals = pd.DataFrame(
        [
            {
                "actual_id": "actual:revenue:2025-04-01:2026-03-31:A1:1",
                "version": 1,
                "supersedes_actual_id": "",
                "entity_id": "ALIBABA",
                "listing_id": "BABA_US",
                "canonical_ticker": "BABA.US",
                "metric": "revenue",
                "period_label": "FY2026",
                "period_start": "2025-04-01",
                "period_end": "2026-03-31",
                "reported_value": 52504000000.0,
                "normalized_value": 52504000000.0,
                "normalization_note": "as_reported; no normalization applied",
                "currency": "CNY",
                "unit": "CNY",
                "accounting_basis": "us-gaap as reported",
                "filing_at": "2026-06-25T00:00:00Z",
                "published_at": "2026-06-25T00:00:00Z",
                "retrieved_at_utc": "2026-08-13T12:00:00Z",
                "source_url": "https://www.sec.gov/Archives/edgar/data/1577552/",
                "accession_no": "A1",
                "form": "20-F",
                "xbrl_frame": "CY2025",
                "revision_reason": "initial_filing",
                "is_restatement": False,
                "source_id": "sec_companyfacts",
                "source_quality": "official_metadata",
                "pit_class": "snapshot_from_live_source",
                "source_license_class": "official_public_metadata",
                "source_note": "fixture companyfacts",
                "registry_version": "v1",
            },
            {
                "actual_id": "actual:revenue:2025-04-01:2026-03-31:A2:2",
                "version": 2,
                "supersedes_actual_id": "actual:revenue:2025-04-01:2026-03-31:A1:1",
                "entity_id": "ALIBABA",
                "listing_id": "BABA_US",
                "canonical_ticker": "BABA.US",
                "metric": "revenue",
                "period_label": "FY2026",
                "period_start": "2025-04-01",
                "period_end": "2026-03-31",
                "reported_value": 53120000000.0,
                "normalized_value": 53120000000.0,
                "normalization_note": "as_reported; no normalization applied",
                "currency": "CNY",
                "unit": "CNY",
                "accounting_basis": "us-gaap as reported",
                "filing_at": "2026-07-30T00:00:00Z",
                "published_at": "2026-07-30T00:00:00Z",
                "retrieved_at_utc": "2026-08-13T12:00:00Z",
                "source_url": "https://www.sec.gov/Archives/edgar/data/1577552/",
                "accession_no": "A2",
                "form": "20-F/A",
                "xbrl_frame": "CY2025",
                "revision_reason": "restatement_or_amended_filing",
                "is_restatement": True,
                "source_id": "sec_companyfacts",
                "source_quality": "official_metadata",
                "pit_class": "snapshot_from_live_source",
                "source_license_class": "official_public_metadata",
                "source_note": "fixture companyfacts",
                "registry_version": "v1",
            },
        ],
        columns=EARNINGS_ACTUALS_COLUMNS,
    )
    state = pd.DataFrame(
        [
            {
                "source_id": "earnings:sec_companyfacts",
                "source_kind": "earnings",
                "status": "available",
                "detail": "sec_companyfacts rows=2",
                "row_count": 2,
                "retrieved_at_utc": "2026-08-13T12:00:00Z",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/",
                "pit_class": "snapshot_from_live_source",
                "source_license_class": "official_public_metadata",
                "cadence": "weekly",
            },
            {
                "source_id": "earnings:hkex_issuer_ir",
                "source_kind": "earnings",
                "status": "no_records",
                "detail": "HKEX-only issuers without SEC XBRL actuals",
                "row_count": 0,
                "retrieved_at_utc": "2026-08-13T12:00:00Z",
                "pit_class": "snapshot_from_live_source",
                "source_license_class": "official_public_metadata",
                "cadence": "monthly",
            },
            {
                "source_id": "earnings:bytedance",
                "source_kind": "earnings",
                "status": "not_applicable",
                "detail": "private company with no public earnings disclosure",
                "row_count": 0,
                "retrieved_at_utc": "2026-08-13T12:00:00Z",
                "pit_class": "snapshot_from_live_source",
                "source_license_class": "official_public_metadata",
                "cadence": "",
            },
        ],
        columns=SOURCE_STATE_COLUMNS,
    )
    actuals_path = tmp_path / "earnings_actuals_v1.parquet"
    state_path = tmp_path / "earnings_actuals_state.parquet"
    actuals.to_parquet(actuals_path, index=False)
    state.to_parquet(state_path, index=False)
    return actuals_path, state_path


def test_official_filings_and_earnings_inputs_populate_optional_artifacts(tmp_path, minimal_inputs):
    filings_path, filings_state = _write_official_filings_inputs(tmp_path)
    actuals_path, actuals_state = _write_earnings_inputs(tmp_path)
    config = replace(
        minimal_inputs,
        official_filing_inputs=(
            _input("official_filings", filings_path, OFFICIAL_FILINGS_SCHEMA_ID),
            _input("official_filings_state", filings_state, SOURCE_STATE_SCHEMA_ID),
        ),
        earnings_inputs=(
            _input("earnings_actuals", actuals_path, EARNINGS_ACTUALS_SCHEMA_ID),
            _input("earnings_actuals_state", actuals_state, SOURCE_STATE_SCHEMA_ID),
        ),
    )

    manifest = build_control_tower_marts(config)
    filings = pd.read_parquet(_published(config, "official_filings.parquet"))
    calendar = pd.read_parquet(_published(config, "earnings_calendar.parquet"))
    actuals = pd.read_parquet(_published(config, "earnings_actuals.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))

    assert len(filings) == 2
    assert list(filings.columns) == OFFICIAL_FILINGS_COLUMNS
    assert set(filings["source_id"]) == {"hkexnews", "sec_edgar_submissions"}
    assert not any(column in filings.columns for column in ("body_text", "filing_content", "summary"))
    assert filings["content_hash_if_permitted"].isna().all()

    assert len(calendar) == 1
    row = calendar.iloc[0]
    assert row["entity_id"] == "TENCENT"
    assert row["listing_id"] == "0700_HK"
    assert row["event_type"] == "interim_results"
    assert row["date_basis"] == "announcement_date"
    assert row["date_precision"] == "day"
    assert row["status"] == "observed"
    assert row["event_date"] == pd.Timestamp("2026-08-12").date()
    assert row["source_timezone"] == "Asia/Hong_Kong"

    assert len(actuals) == 2
    revenue = actuals[actuals["metric"].eq("revenue")].sort_values("version")
    assert list(revenue["version"]) == [1, 2]
    assert list(revenue["reported_value"]) == [52504000000.0, 53120000000.0]
    assert revenue.iloc[1]["supersedes_actual_id"] == revenue.iloc[0]["actual_id"]
    assert revenue.iloc[1]["is_restatement"].item() is True
    assert revenue.iloc[0]["currency"] == "CNY"
    assert revenue.iloc[0]["normalized_value"] == revenue.iloc[0]["reported_value"]

    assert manifest.artifacts["official_filings.parquet"]["status"] == "available"
    assert manifest.artifacts["earnings_calendar.parquet"]["status"] == "available"
    assert manifest.artifacts["earnings_actuals.parquet"]["status"] == "available"
    assert "official_filings" not in manifest.degraded_inputs
    assert "earnings_actuals" not in manifest.degraded_inputs

    by_source = health.set_index("source_id")["status"].to_dict()
    assert by_source["filings:hkexnews"] == "available"
    assert by_source["filings:issuer_ir"] == "no_records"
    assert by_source["filings:bytedance"] == "not_applicable"
    assert by_source["earnings:sec_companyfacts"] == "available"
    assert by_source["earnings:hkex_issuer_ir"] == "no_records"
    assert by_source["earnings:bytedance"] == "not_applicable"


def test_official_filings_unresolved_relations_are_dropped_and_flagged(tmp_path, minimal_inputs):
    filings_path, filings_state = _write_official_filings_inputs(tmp_path)
    frame = pd.read_parquet(filings_path)
    frame.loc[0, "entity_id"] = "NOT_A_REGISTRY_ENTITY"
    frame.loc[0, "listing_id"] = "NOT_A_LISTING"
    frame.to_parquet(filings_path, index=False)
    config = replace(
        minimal_inputs,
        official_filing_inputs=(
            _input("official_filings", filings_path, OFFICIAL_FILINGS_SCHEMA_ID),
            _input("official_filings_state", filings_state, SOURCE_STATE_SCHEMA_ID),
        ),
    )

    manifest = build_control_tower_marts(config)
    filings = pd.read_parquet(_published(config, "official_filings.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    assert len(filings) == 1
    assert set(filings["entity_id"]) == {"ALIBABA"}
    state = health.loc[health["source_id"].eq("official_filings")].iloc[0]
    assert "dropped_unresolved_relations=1" in state["detail"]
    assert any(
        error["code"] == "unresolved_relations"
        for error in manifest.validation_errors
    )


def test_batch23_missing_inputs_are_typed_empty_and_degraded(minimal_inputs):
    manifest = build_control_tower_marts(minimal_inputs)
    filings = pd.read_parquet(_published(minimal_inputs, "official_filings.parquet"))
    calendar = pd.read_parquet(_published(minimal_inputs, "earnings_calendar.parquet"))
    actuals = pd.read_parquet(_published(minimal_inputs, "earnings_actuals.parquet"))
    assert filings.empty and list(filings.columns) == OFFICIAL_FILINGS_COLUMNS
    assert calendar.empty and list(calendar.columns) == EARNINGS_CALENDAR_COLUMNS
    assert actuals.empty and list(actuals.columns) == EARNINGS_ACTUALS_COLUMNS
    assert "official_filings" in manifest.degraded_inputs
    assert "earnings_actuals" in manifest.degraded_inputs


def test_batch23_future_rows_fail_closed(tmp_path, minimal_inputs):
    filings_path, filings_state = _write_official_filings_inputs(tmp_path)
    frame = pd.read_parquet(filings_path)
    frame.loc[0, "published_at"] = "2026-08-14T08:31:00Z"  # after as_of_utc
    frame.to_parquet(filings_path, index=False)
    config = replace(
        minimal_inputs,
        official_filing_inputs=(
            _input("official_filings", filings_path, OFFICIAL_FILINGS_SCHEMA_ID),
            _input("official_filings_state", filings_state, SOURCE_STATE_SCHEMA_ID),
        ),
    )

    manifest = build_control_tower_marts(config)
    filings = pd.read_parquet(_published(config, "official_filings.parquet"))
    health = pd.read_parquet(_published(config, "source_health.parquet"))
    assert filings.empty
    state = health.loc[health["source_id"].eq("official_filings")].iloc[0]
    assert state["status"] == "degraded"
    assert "future_row_beyond_as_of" in state["detail"]
    assert "official_filings" in manifest.degraded_inputs
