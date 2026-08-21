from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'apps' / 'research-control-tower'))
"""Integration tests for Control Tower Tencent T0-T3 backend integration."""


import json
import pytest
import pandas as pd
import pyarrow.parquet as pq

from src.research_control_tower.build import (
    ARTIFACT_NAMES,
    OPTIONAL_ARTIFACT_NAMES,
    EARNINGS_ACTUALS_COLUMNS,
    CORP_ACTIONS_COLUMNS,
    VALUATION_SNAPSHOTS_COLUMNS,
    INTERNAL_ESTIMATES_COLUMNS,
    THESIS_CLAIMS_COLUMNS,
    THESIS_WATCH_QUESTIONS_COLUMNS,
    EVIDENCE_ITEMS_COLUMNS,
    CLAIM_EVIDENCE_LINKS_COLUMNS,
    BuildConfig,
    BuildError,
    LocalInput,
    build_control_tower_marts,
    current_generation,
)
from control_tower.config import (
    ARTIFACT_COLUMNS as APP_ARTIFACT_COLUMNS,
    ARTIFACT_NAMES as APP_ARTIFACT_NAMES,
    OPTIONAL_ARTIFACT_NAMES as APP_OPTIONAL_ARTIFACT_NAMES,
    resolve_artifact_root,
)
from control_tower.models import ControlTowerSnapshot
from control_tower.repository import ControlTowerRepository

REGISTRY_SOURCE = Path("config/research_control_tower")


def _copy_inputs(target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    for path in REGISTRY_SOURCE.glob("*.csv"):
        (target / path.name).write_bytes(path.read_bytes())
    return target


def test_t0_t3_backend_integration_builds_all_27_artifacts(tmp_path: Path) -> None:
    input_root = _copy_inputs(tmp_path / "config")
    output_dir = tmp_path / "output"
    as_of = pd.Timestamp("2026-08-21T12:00:00Z")

    config = BuildConfig(
        registry_root=input_root,
        event_root=input_root,
        output_dir=output_dir,
        as_of_utc=as_of,
        build_id="tencent-integration-test-001",
    )

    manifest = build_control_tower_marts(config)
    assert len(manifest.artifacts) == 27
    assert set(manifest.artifacts.keys()) == set(ARTIFACT_NAMES)

    gen = current_generation(output_dir)
    assert set(p.name for p in gen.iterdir()) == set(ARTIFACT_NAMES)

    # Check all optional marts exist with exact columns
    actions_df = pd.read_parquet(gen / "corporate_actions.parquet")
    assert list(actions_df.columns) == CORP_ACTIONS_COLUMNS

    val_df = pd.read_parquet(gen / "valuation_snapshots.parquet")
    assert list(val_df.columns) == VALUATION_SNAPSHOTS_COLUMNS

    est_df = pd.read_parquet(gen / "internal_estimates.parquet")
    assert list(est_df.columns) == INTERNAL_ESTIMATES_COLUMNS

    claims_df = pd.read_parquet(gen / "thesis_claims.parquet")
    assert list(claims_df.columns) == THESIS_CLAIMS_COLUMNS
    assert len(claims_df) == 3

    twq_df = pd.read_parquet(gen / "thesis_watch_questions.parquet")
    assert list(twq_df.columns) == THESIS_WATCH_QUESTIONS_COLUMNS
    assert len(twq_df) == 6

    evid_df = pd.read_parquet(gen / "evidence_items.parquet")
    assert list(evid_df.columns) == EVIDENCE_ITEMS_COLUMNS
    assert len(evid_df) == 4

    links_df = pd.read_parquet(gen / "claim_evidence_links.parquet")
    assert list(links_df.columns) == CLAIM_EVIDENCE_LINKS_COLUMNS
    assert len(links_df) == 4

    # Load via ControlTowerRepository
    repo = ControlTowerRepository(output_dir)
    snapshot = repo.load_snapshot()
    assert isinstance(snapshot, ControlTowerSnapshot)
    assert len(snapshot.thesis_claims) == 3
    assert len(snapshot.thesis_watch_questions) == 6
    assert len(snapshot.evidence_items) == 4
    assert len(snapshot.claim_evidence_links) == 4


def test_t0_t3_earnings_actuals_multiple_source_merge(tmp_path: Path) -> None:
    input_root = _copy_inputs(tmp_path / "config")
    output_dir = tmp_path / "output"
    as_of = pd.Timestamp("2026-08-21T12:00:00Z")

    # Parse 224 Tencent actuals from fixture
    from scripts.research_control_tower_tencent_financials import (
        parse_and_collect_tencent_actuals,
    )
    fixture_path = Path("tests/fixtures/tencent_ir/tencent_disclosures_2021_2026.json")
    tencent_actuals, _ = parse_and_collect_tencent_actuals(
        fixture_path=fixture_path,
        as_of_utc=as_of,
        retrieved_at_utc=as_of,
    )
    assert len(tencent_actuals) == 224
    tencent_actuals_file = tmp_path / "tencent_actuals.parquet"
    tencent_actuals.to_parquet(tencent_actuals_file)

    config = BuildConfig(
        registry_root=input_root,
        event_root=input_root,
        output_dir=output_dir,
        as_of_utc=as_of,
        build_id="tencent-actuals-merge-test",
        earnings_inputs=(
            LocalInput(
                source_id="earnings:tencent_disclosures",
                path=tencent_actuals_file,
                format="parquet",
                expected_schema="earnings_actuals_v1",
            ),
        ),
    )

    manifest = build_control_tower_marts(config)
    gen = current_generation(output_dir)
    actuals_df = pd.read_parquet(gen / "earnings_actuals.parquet")
    assert len(actuals_df) == 224
    assert list(actuals_df.columns) == EARNINGS_ACTUALS_COLUMNS
    assert "metric_basis" in actuals_df.columns
    assert set(actuals_df["metric_basis"].dropna()) == {"GAAP_REPORTED", "NON_IFRS_MANAGEMENT"}
