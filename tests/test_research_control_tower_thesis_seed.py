from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.research_control_tower.events import load_event_bundle
from src.research_control_tower.events import validate_event_bundle
from src.research_control_tower.registries import load_registry_bundle
from src.research_control_tower.thesis_seed import (
    ThesisSeedBundle,
    count_active_conflicts,
    get_claim_evidence,
    get_claim_watch_questions,
    get_entity_thesis_claims,
    load_tencent_event_seed_bundle,
    load_thesis_seed_bundle,
    merge_event_bundles,
    validate_thesis_seed_bundle,
)


@pytest.fixture()
def config_root() -> Path:
    return Path(__file__).parents[1] / "config" / "research_control_tower"


@pytest.fixture()
def registries(config_root: Path):
    return load_registry_bundle(config_root)


@pytest.fixture()
def events(config_root: Path):
    return load_event_bundle(config_root)


@pytest.fixture()
def thesis_bundle(config_root: Path) -> ThesisSeedBundle:
    return load_thesis_seed_bundle(config_root)


def test_live_thesis_seed_bundle_loads_cleanly(thesis_bundle: ThesisSeedBundle):
    assert not thesis_bundle.thesis_claims.empty
    assert not thesis_bundle.thesis_watch_questions.empty
    assert not thesis_bundle.evidence_items.empty
    assert not thesis_bundle.claim_evidence_links.empty

    # Check Tencent claims exist
    tencent_claims = thesis_bundle.thesis_claims[
        thesis_bundle.thesis_claims["entity_id"] == "TENCENT"
    ]
    assert len(tencent_claims) >= 3
    assert set(tencent_claims["claim_id"]) >= {
        "TENCENT_THESIS_BULL_AI_ADS",
        "TENCENT_THESIS_BASE_COMPOUNDER",
        "TENCENT_THESIS_BEAR_CAPEX_TRAP",
    }

    # Check boolean columns parsed
    assert thesis_bundle.claim_evidence_links["conflict_hint"].dtype.name == "boolean"


def test_live_thesis_seed_bundle_validation_passes(
    thesis_bundle: ThesisSeedBundle,
    registries,
    events,
):
    now_utc = pd.Timestamp("2026-08-21T00:00:00Z")
    issues = validate_thesis_seed_bundle(thesis_bundle, registries, events, now_utc)
    assert issues == [], f"Validation failed with issues: {issues}"


def test_validation_rejects_naive_now_timestamp(
    thesis_bundle: ThesisSeedBundle,
    registries,
    events,
):
    naive_now = pd.Timestamp("2026-08-21 00:00:00")
    issues = validate_thesis_seed_bundle(thesis_bundle, registries, events, naive_now)
    assert any(issue.code == "now_not_timezone_aware" for issue in issues)


def test_validation_rejects_orphan_claim_entity(
    thesis_bundle: ThesisSeedBundle,
    registries,
    events,
):
    now_utc = pd.Timestamp("2026-08-21T00:00:00Z")
    broken_claims = thesis_bundle.thesis_claims.copy()
    broken_claims.loc[0, "entity_id"] = "UNKNOWN_CORP"
    broken_bundle = replace(thesis_bundle, thesis_claims=broken_claims)
    issues = validate_thesis_seed_bundle(broken_bundle, registries, events, now_utc)
    assert any(issue.code == "orphan_claim_entity_id" for issue in issues)


def test_validation_rejects_orphan_watch_question_claim(
    thesis_bundle: ThesisSeedBundle,
    registries,
    events,
):
    now_utc = pd.Timestamp("2026-08-21T00:00:00Z")
    broken_questions = thesis_bundle.thesis_watch_questions.copy()
    broken_questions.loc[0, "claim_id"] = "UNKNOWN_CLAIM_ID"
    broken_bundle = replace(thesis_bundle, thesis_watch_questions=broken_questions)
    issues = validate_thesis_seed_bundle(broken_bundle, registries, events, now_utc)
    assert any(issue.code == "orphan_watch_question_claim_id" for issue in issues)


def test_validation_rejects_entity_mismatch_between_claim_and_question(
    thesis_bundle: ThesisSeedBundle,
    registries,
    events,
):
    now_utc = pd.Timestamp("2026-08-21T00:00:00Z")
    broken_questions = thesis_bundle.thesis_watch_questions.copy()
    broken_questions.loc[0, "entity_id"] = "ALIBABA"
    broken_bundle = replace(thesis_bundle, thesis_watch_questions=broken_questions)
    issues = validate_thesis_seed_bundle(broken_bundle, registries, events, now_utc)
    assert any(issue.code == "watch_question_entity_mismatch" for issue in issues)


def test_validation_rejects_duplicate_claim_id(
    thesis_bundle: ThesisSeedBundle,
    registries,
    events,
):
    now_utc = pd.Timestamp("2026-08-21T00:00:00Z")
    duplicated_claims = pd.concat(
        [thesis_bundle.thesis_claims, thesis_bundle.thesis_claims.iloc[[0]]],
        ignore_index=True,
    )
    broken_bundle = replace(thesis_bundle, thesis_claims=duplicated_claims)
    issues = validate_thesis_seed_bundle(broken_bundle, registries, events, now_utc)
    assert any(issue.code == "duplicate_claim_id" for issue in issues)


def test_validation_rejects_invalid_status_and_question_type(
    thesis_bundle: ThesisSeedBundle,
    registries,
    events,
):
    now_utc = pd.Timestamp("2026-08-21T00:00:00Z")
    broken_claims = thesis_bundle.thesis_claims.copy()
    broken_claims.loc[0, "status"] = "undecided"

    broken_questions = thesis_bundle.thesis_watch_questions.copy()
    broken_questions.loc[0, "question_type"] = "speculation"

    broken_bundle = replace(
        thesis_bundle,
        thesis_claims=broken_claims,
        thesis_watch_questions=broken_questions,
    )
    issues = validate_thesis_seed_bundle(broken_bundle, registries, events, now_utc)
    assert any(issue.code == "invalid_thesis_status" for issue in issues)
    assert any(issue.code == "invalid_question_type" for issue in issues)


def test_validation_rejects_orphan_evidence_link(
    thesis_bundle: ThesisSeedBundle,
    registries,
    events,
):
    now_utc = pd.Timestamp("2026-08-21T00:00:00Z")
    broken_links = thesis_bundle.claim_evidence_links.copy()
    broken_links.loc[0, "evidence_id"] = "UNKNOWN_EVIDENCE"
    broken_bundle = replace(thesis_bundle, claim_evidence_links=broken_links)
    issues = validate_thesis_seed_bundle(broken_bundle, registries, events, now_utc)
    assert any(issue.code == "orphan_claim_evidence_link_evidence_id" for issue in issues)


def test_helper_queries(thesis_bundle: ThesisSeedBundle):
    claims = get_entity_thesis_claims(thesis_bundle, "TENCENT")
    assert len(claims) >= 3

    bull_questions = get_claim_watch_questions(thesis_bundle, "TENCENT_THESIS_BULL_AI_ADS")
    assert len(bull_questions) >= 2
    assert "TENCENT_TWQ_AIM_GROWTH" in set(bull_questions["question_id"])

    bull_evidence = get_claim_evidence(thesis_bundle, "TENCENT_THESIS_BULL_AI_ADS")
    assert len(bull_evidence) >= 2
    assert "EVID_TENCENT_2Q2026_RESULTS_FILING" in set(bull_evidence["evidence_id"])
    assert "summary_text" in bull_evidence.columns
    assert "conflict_hint" in bull_evidence.columns

    # Active conflicts
    all_conflicts = count_active_conflicts(thesis_bundle)
    tencent_conflicts = count_active_conflicts(thesis_bundle, entity_id="TENCENT")
    assert all_conflicts >= 1
    assert tencent_conflicts >= 1


def test_tencent_event_seed_bundle_loads_and_validates(config_root: Path, registries, events):
    tencent_events = load_tencent_event_seed_bundle(config_root)
    assert len(tencent_events.events) >= 5
    assert len(tencent_events.event_links) >= 15
    assert len(tencent_events.event_watch_questions) >= 8

    # Merge into base event bundle and validate
    merged = merge_event_bundles(events, tencent_events)
    now_utc = pd.Timestamp("2026-08-21T00:00:00Z")
    issues = validate_event_bundle(merged, registries, now_utc)
    assert issues == [], f"Merged event bundle has validation issues: {issues}"

    # Verify Tencent links
    tencent_links = merged.event_links[merged.event_links["target_id"] == "TENCENT"]
    assert len(tencent_links) >= 5

    # Verify all Tencent thesis checkpoints have watch questions
    checkpoint_ids = set(
        tencent_events.events.loc[
            tencent_events.events["certainty_class"] == "thesis_checkpoint", "event_id"
        ]
    )
    question_event_ids = set(tencent_events.event_watch_questions["event_id"])
    assert checkpoint_ids <= question_event_ids
