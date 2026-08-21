"""Focused regression tests for the final Tencent Control Tower review."""

from __future__ import annotations

from datetime import date, datetime, timezone
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
import types

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT, REPO_ROOT / "scripts", REPO_ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from src.research_control_tower.eligibility import (  # noqa: E402
    eligible_listing_ids,
    filter_eligible_listings,
)
from src.research_control_tower.registries import load_registry_bundle  # noqa: E402


CONFIG_ROOT = REPO_ROOT / "config" / "research_control_tower"
AS_OF = pd.Timestamp("2026-08-22T00:00:00Z")


def _snap(**overrides: object) -> dict[str, object]:
    """Return a captured consensus snapshot without importing another test."""
    row: dict[str, object] = {
        "snapshot_id": "run-scoped-id",
        "provider": "yfinance",
        "entity_id": "ALIBABA",
        "listing_id": "9988_HK",
        "financial_data_security_id": "sec-9988",
        "canonical_ticker": "9988.HK",
        "metric": "eps",
        "fiscal_period": "quarterly",
        "fiscal_year": 2027,
        "estimate_period_end": pd.Timestamp("2027-03-31").date(),
        "horizon": "0q",
        "snapshot_at": pd.Timestamp("2026-08-01T10:00:00Z"),
        "value": 3.00,
        "statistic": "mean",
        "low_value": 2.80,
        "high_value": 3.20,
        "analyst_count": 30,
        "provider_contributor_count": 30,
        "currency": "HKD",
        "unit": "currency_per_share",
        "accounting_basis": "provider_reported_non_gaap_unverified",
        "provider_asof": pd.Timestamp("2026-08-01T10:00:00Z"),
        "retrieved_at_utc": pd.Timestamp("2026-08-01T10:00:00Z"),
        "source_url": "https://finance.yahoo.com/quote/9988.HK/analysis",
        "raw_hash": "raw-hash",
        "pit_class": "snapshot_from_live_source",
        "source_run_id": "consensus-run-1",
        "calculation_origin": "provider_published_consensus",
        "coverage_reason": "",
    }
    row.update(overrides)
    return row


def _empty_store() -> pd.DataFrame:
    """Return an empty consensus store using the collector's own columns."""
    import research_control_tower_consensus_collector as collector

    return pd.DataFrame({column: pd.Series(dtype="object") for column in collector.STORE_COLUMNS})


def _audit_source_row(schema_id: str, timestamp: str) -> dict[str, object]:
    """Return the small valid optional-row fixtures used by these tests."""
    from src.research_control_tower.build import (
        CORP_ACTIONS_COLUMNS,
        INTERNAL_ESTIMATES_COLUMNS,
        VALUATION_SNAPSHOTS_COLUMNS,
        CORP_ACTIONS_SCHEMA_ID,
        INTERNAL_ESTIMATES_SCHEMA_ID,
        VALUATION_SNAPSHOTS_SCHEMA_ID,
    )

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
                "metric_basis": "NON_IFRS_MANAGEMENT",
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


def _listing(
    listing_id: str,
    *,
    entity_id: str = "TENCENT",
    ticker: str | None = None,
    mapping_status: str = "verified",
    collection_eligible: bool = True,
    listing_status: str = "active",
) -> dict[str, object]:
    return {
        "listing_id": listing_id,
        "entity_id": entity_id,
        "canonical_ticker": ticker or ("0700.HK" if listing_id == "0700_HK" else "TCEHY.US"),
        "financial_data_security_id": "sec-0700" if listing_id == "0700_HK" else "",
        "currency": "HKD" if listing_id == "0700_HK" else "USD",
        "mapping_status": mapping_status,
        "collection_eligible": collection_eligible,
        "listing_status": listing_status,
        "active_from": "2004-06-16",
        "active_to": "",
    }


def test_real_tcehy_listing_is_not_eligible_but_0700_remains_eligible() -> None:
    listings = load_registry_bundle(CONFIG_ROOT).listings

    eligible = eligible_listing_ids(listings, AS_OF)

    assert "0700_HK" in eligible
    assert "TCEHY_US" not in eligible


def test_listing_filter_reports_rejection_reasons_and_preserves_entity_only_rows() -> None:
    listings = pd.DataFrame(
        [
            _listing("0700_HK"),
            _listing(
                "TCEHY_US",
                mapping_status="unresolved",
                collection_eligible=False,
            ),
        ]
    )

    kept, rejected = filter_eligible_listings(listings, AS_OF)

    assert set(kept["listing_id"]) == {"0700_HK"}
    assert len(rejected) == 1
    assert rejected[0]["listing_id"] == "TCEHY_US"
    assert "mapping_status" in rejected[0]["reason"]


def test_builder_relation_gate_rejects_tcehy_but_keeps_0700_and_entity_only_rows() -> None:
    from src.research_control_tower.build import _resolve_official_relations

    registries = load_registry_bundle(CONFIG_ROOT)
    rows = pd.DataFrame(
        [
            {"entity_id": "TENCENT", "listing_id": "0700_HK", "canonical_ticker": "wrong"},
            {"entity_id": "TENCENT", "listing_id": "TCEHY_US", "canonical_ticker": "TCEHY.US"},
            {"entity_id": "TENCENT", "listing_id": "", "canonical_ticker": "entity-only"},
        ]
    )

    kept, rejected = _resolve_official_relations(
        rows,
        registries,
        as_of_utc=AS_OF,
    )

    assert set(kept["listing_id"]) == {"0700_HK", ""}
    assert kept.loc[kept["listing_id"].eq("0700_HK"), "canonical_ticker"].item() == "0700.HK"
    assert [item["listing_id"] for item in rejected] == ["TCEHY_US"]
    assert "mapping_status" in str(rejected[0]["reason"])


def test_consensus_collector_never_queries_unresolved_tcehy(monkeypatch: pytest.MonkeyPatch) -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import research_control_tower_consensus_collector as collector

    queried: list[str] = []

    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            queried.append(symbol)

        earnings_estimate = pd.DataFrame(
            {"avg": [28.0], "low": [27.0], "high": [29.0], "numberOfAnalysts": [5]},
            index=["0q"],
        )
        revenue_estimate = pd.DataFrame()
        eps_trend = pd.DataFrame()

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))
    listings = pd.DataFrame(
        [
            _listing("0700_HK", ticker="0700.HK"),
            _listing(
                "TCEHY_US",
                ticker="TCEHY.US",
                mapping_status="unresolved",
                collection_eligible=False,
            ),
        ]
    ).assign(provider_symbol=lambda frame: frame["canonical_ticker"].str.replace(r"\.US$", "", regex=True))

    snapshots, _revisions, calls, notes = collector.collect_yfinance(
        listings,
        pd.DataFrame(),
        run_id="final-findings",
        now=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
    )

    assert queried == ["0700.HK"]
    assert calls == 3
    assert {row["listing_id"] for row in snapshots} == {"0700_HK"}
    assert any("TCEHY_US" in note and "mapping_status" in note for note in notes)


def test_consensus_tie_break_includes_source_run_id_and_is_reverse_order_stable() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import research_control_tower_consensus_collector as collector

    base = {
        "provider_asof": pd.Timestamp("2026-08-01T10:00:00Z"),
        "retrieved_at_utc": pd.Timestamp("2026-08-01T10:00:00Z"),
        "snapshot_at": pd.Timestamp("2026-08-01T10:00:00Z"),
    }
    first = {
        **base,
        "snapshot_id": "first",
        "value": 3.0,
        "source_run_id": "run-alpha",
    }
    second = {
        **base,
        "snapshot_id": "second",
        "value": 3.0,
        "source_run_id": "run-omega",
    }
    first = _snap(**first)
    second = _snap(**second)
    forward = collector.accumulate_snapshots(_empty_store(), [first, second], date(2026, 8, 1))
    reverse = collector.accumulate_snapshots(_empty_store(), [second, first], date(2026, 8, 1))

    assert len(forward) == len(reverse) == 1
    assert forward.iloc[0]["source_run_id"] == reverse.iloc[0]["source_run_id"]
    assert forward.iloc[0]["source_run_id"] == "run-omega"


def test_corporate_action_version_is_integer_and_registry_version_is_text() -> None:
    from src.research_control_tower.corporate_actions import REGISTRY_VERSION, VERSION

    assert VERSION == 1
    assert isinstance(VERSION, int)
    assert REGISTRY_VERSION == "v1"
    assert isinstance(REGISTRY_VERSION, str)


def test_legacy_corporate_action_version_is_migrated_before_arrow_coercion(tmp_path: Path) -> None:
    from src.research_control_tower.build import CORP_ACTIONS_SCHEMA_ID, LocalInput, _load_optional
    row = _audit_source_row(CORP_ACTIONS_SCHEMA_ID, "2026-08-12T00:00:00Z")
    row["version"] = "v1"
    path = tmp_path / "legacy-corporate-actions.csv"
    pd.DataFrame([row]).to_csv(path, index=False)
    descriptor = LocalInput(
        source_id="legacy-corporate-actions",
        path=path,
        format="csv",
        expected_schema=CORP_ACTIONS_SCHEMA_ID,
    )

    state, loaded, normalized_schema = _load_optional(
        descriptor,
        "corporate_actions",
        as_of_utc=AS_OF,
    )

    assert normalized_schema == CORP_ACTIONS_SCHEMA_ID
    assert loaded is not None
    assert int(loaded.iloc[0]["version"]) == 1
    assert loaded.iloc[0]["registry_version"] == "v1"
    assert "legacy_corporate_action_version_migrated=1" in state.detail


@pytest.mark.parametrize(
    ("schema_id", "source_kind", "field", "value"),
    [
        ("corporate_actions_v1", "corporate_actions", "version", "1.5"),
        ("corporate_actions_v1", "corporate_actions", "action_id", ""),
        ("valuation_snapshots_v2", "valuation", "numerator_value", "not-a-number"),
        ("valuation_snapshots_v2", "valuation", "numerator_source_url", ""),
        ("internal_estimates_v1", "valuation", "recorded_at_utc", "not-a-timestamp"),
        ("internal_estimates_v1", "valuation", "source_ref", ""),
    ],
)
def test_high_risk_optional_rows_fail_closed_before_policy_or_arrow_coercion(
    tmp_path: Path,
    schema_id: str,
    source_kind: str,
    field: str,
    value: object,
) -> None:
    from src.research_control_tower.build import LocalInput, _load_optional
    row = _audit_source_row(schema_id, "2026-08-12T00:00:00Z")
    row[field] = value
    path = tmp_path / f"{schema_id}-{field}.csv"
    pd.DataFrame([row]).to_csv(path, index=False)
    descriptor = LocalInput(
        source_id=f"invalid-{schema_id}-{field}",
        path=path,
        format="csv",
        expected_schema=schema_id,
    )

    state, loaded, normalized_schema = _load_optional(
        descriptor,
        source_kind,
        as_of_utc=AS_OF,
    )

    assert normalized_schema == schema_id
    assert loaded is None
    assert state.status == "degraded"
    assert "semantic_validation_failed" in state.detail


def test_valuation_cli_documentation_uses_safe_current_utc_placeholder() -> None:
    readme = (REPO_ROOT / "apps" / "research-control-tower" / "README.md").read_text()
    valuation_block = readme.split("python scripts/research_control_tower_valuation.py", 1)[1].split("```", 1)[0]
    assert "2026-08-22" not in valuation_block
    assert '$(date -u +%Y-%m-%dT%H:%M:%SZ)' in valuation_block
    command_catalog = (REPO_ROOT / "scripts" / "build_research_control_tower.py").read_text()
    assert '--as-of "$(date -u +%Y-%m-%dT%H:%M:%SZ)"' in command_catalog
    assert '"--as-of 2026-08-22T00:00:00Z "' not in command_catalog


def test_app_resolver_rejects_partial_generation_contract(tmp_path: Path) -> None:
    app_root = REPO_ROOT / "apps" / "research-control-tower"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    from control_tower.config import ArtifactResolutionError, resolve_artifact_root

    source = REPO_ROOT / "apps" / "research-control-tower" / ".generated" / "generations"
    generation = next(
        path
        for path in source.iterdir()
        if path.is_dir()
        and (path / "build_manifest.json").is_file()
        and len(list(path.iterdir())) == 27
    )
    publication = tmp_path / "publication"
    target = publication / "generations" / "partial"
    target.parent.mkdir(parents=True)
    shutil.copytree(generation, target)
    (target / "internal_estimates.parquet").unlink()
    (publication / "CURRENT").write_text("generations/partial\n", encoding="utf-8")

    with pytest.raises(ArtifactResolutionError, match="recognized contract|missing"):
        resolve_artifact_root(publication)


def test_valid_null_optionals_remain_valid_in_thesis_seed_validation() -> None:
    from src.research_control_tower.thesis_seed import load_thesis_seed_bundle, validate_thesis_seed_bundle
    from src.research_control_tower.events import load_event_bundle

    bundle = load_thesis_seed_bundle(CONFIG_ROOT)
    events = load_event_bundle(CONFIG_ROOT)
    issues = validate_thesis_seed_bundle(
        bundle,
        load_registry_bundle(CONFIG_ROOT),
        events,
        AS_OF,
    )

    assert not [issue for issue in issues if issue.severity == "error"]


def test_thesis_nonblank_timestamp_and_boolean_are_not_silently_coerced() -> None:
    from src.research_control_tower.thesis_seed import (
        load_thesis_seed_bundle,
        validate_thesis_seed_bundle,
    )
    from src.research_control_tower.events import load_event_bundle

    bundle = load_thesis_seed_bundle(CONFIG_ROOT)
    events = load_event_bundle(CONFIG_ROOT)
    evidence = bundle.evidence_items.copy()
    evidence["observed_at_utc"] = evidence["observed_at_utc"].astype("object")
    evidence.loc[0, "observed_at_utc"] = "not-a-timestamp"
    links = bundle.claim_evidence_links.copy()
    links["conflict_hint"] = links["conflict_hint"].astype("object")
    links.loc[0, "conflict_hint"] = "maybe"
    malformed = replace(bundle, evidence_items=evidence, claim_evidence_links=links)

    issues = validate_thesis_seed_bundle(
        malformed,
        load_registry_bundle(CONFIG_ROOT),
        events,
        AS_OF,
    )
    codes = {issue.code for issue in issues}
    assert "invalid_observed_at_utc_timestamp" in codes
    assert "invalid_conflict_hint_boolean" in codes
