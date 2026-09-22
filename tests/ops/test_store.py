from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from ops_control.incidents import legacy_fingerprint_for, mark_recovered, missed_schedule_incident
from ops_control.registry import load_registry
from ops_control.store import IncidentStore, _issue_body, parse_issue


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "ops" / "incident.schema.json"


def test_fingerprint_search_query_includes_is_issue(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_paginate(url: str, *, token: str, params=None):
        captured["url"] = url
        captured["params"] = params
        return []

    monkeypatch.setattr("ops_control.store.paginate", fake_paginate)
    store = IncidentStore(
        repository="Henrywzh/alternative-data-ops",
        token="ghs_test",
        schema_path=SCHEMA,
    )

    assert store.find_by_fingerprint("asia-markets-dashboard-refresh:x:y:abc") is None
    assert captured["url"] == "https://api.github.com/search/issues"
    query = str((captured["params"] or {}).get("q"))
    assert "is:issue" in query
    assert "repo:Henrywzh/alternative-data-ops" in query
    assert "label:ops-incident" in query
    assert '"fingerprint: asia-markets-dashboard-refresh:x:y:abc"' in query


def test_closed_github_issue_cannot_appear_as_open_incident() -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    incident = missed_schedule_incident(
        pipeline=registry.pipelines["openrouter-provider-activity"],
        job_id="scrape-provider-activity",
        now=datetime(2026, 9, 9, tzinfo=timezone.utc),
        last_finished_at=None,
    )
    parsed = parse_issue({
        "state": "closed",
        "body": _issue_body(incident),
        "html_url": "https://github.com/example/ops/issues/3",
    })
    assert parsed is not None
    assert parsed.status == "CLOSED"
    assert parsed.needs_human is False
    assert parsed.issue_url == "https://github.com/example/ops/issues/3"


def test_manually_reopened_recovered_issue_requires_human_review() -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    incident = missed_schedule_incident(
        pipeline=registry.pipelines["openrouter-provider-activity"],
        job_id="scrape-provider-activity",
        now=datetime(2026, 9, 8, tzinfo=timezone.utc),
        last_finished_at=None,
    )
    recovered = mark_recovered(incident, now=datetime(2026, 9, 9, tzinfo=timezone.utc))

    parsed = parse_issue({
        "state": "open",
        "body": _issue_body(recovered),
        "html_url": "https://github.com/example/ops/issues/3",
    })

    assert parsed is not None
    assert parsed.status == "NEEDS_HUMAN"
    assert parsed.needs_human is True
    assert parsed.retry_eligible is False
    assert parsed.recovered_at is None
    assert parsed.manually_reopened is True


def test_upsert_migrates_matching_legacy_issue_without_creating_duplicate(monkeypatch) -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    incoming = missed_schedule_incident(
        pipeline=registry.pipelines["semiconductor-memory-monthly"],
        job_id="adata-update",
        now=datetime(2026, 9, 22, tzinfo=timezone.utc),
        last_finished_at=None,
    )
    old_fingerprint = legacy_fingerprint_for(
        pipeline_id=incoming.pipeline_id,
        failed_check=incoming.failed_check,
        error_class=incoming.error_class,
    )
    existing = replace(
        incoming,
        fingerprint=old_fingerprint,
        incident_id=old_fingerprint,
        issue_url="https://github.com/example/ops/issues/4",
    )
    calls = []
    store = IncidentStore(repository="example/ops", token="ghs_test", schema_path=SCHEMA)
    monkeypatch.setattr(store, "find_by_fingerprint", lambda fingerprint: existing if fingerprint == old_fingerprint else None)
    monkeypatch.setattr(
        "ops_control.store.request_json",
        lambda url, **kwargs: calls.append((url, kwargs)) or {},
    )

    migrated = store.upsert(incoming)

    assert migrated.fingerprint == incoming.fingerprint
    assert migrated.issue_url == existing.issue_url
    assert len(calls) == 1
    assert calls[0][0].endswith("/issues/4")
    assert calls[0][1]["method"] == "PATCH"
    assert f"fingerprint: {incoming.fingerprint}" in calls[0][1]["payload"]["body"]


def test_legacy_collision_does_not_merge_different_job(monkeypatch) -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    pipeline = registry.pipelines["semiconductor-memory-monthly"]
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    adata = missed_schedule_incident(pipeline=pipeline, job_id="adata-update", now=now, last_finished_at=None)
    fred = missed_schedule_incident(pipeline=pipeline, job_id="fred-update", now=now, last_finished_at=None)
    old_fingerprint = legacy_fingerprint_for(
        pipeline_id=adata.pipeline_id,
        failed_check=adata.failed_check,
        error_class=adata.error_class,
    )
    existing = replace(adata, fingerprint=old_fingerprint, incident_id=old_fingerprint)
    store = IncidentStore(repository="example/ops", token="ghs_test", schema_path=SCHEMA)
    monkeypatch.setattr(store, "find_by_fingerprint", lambda fingerprint: existing if fingerprint == old_fingerprint else None)
    calls = []
    monkeypatch.setattr(
        "ops_control.store.request_json",
        lambda url, **kwargs: calls.append((url, kwargs)) or {"html_url": "https://github.com/example/ops/issues/10"},
    )

    created = store.upsert(fred)

    assert created.job_id == "fred-update"
    assert created.issue_url == "https://github.com/example/ops/issues/10"
    assert len(calls) == 1
    assert calls[0][1]["method"] == "POST"
