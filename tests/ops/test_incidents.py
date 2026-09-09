from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ops_control.incidents import classify_error, fingerprint_for, incident_from_report, merge_incident, retry_eligible, validate_incident
from ops_control.models import CheckResult, Evidence, RunReport
from ops_control.registry import load_registry
from ops_control.retry import maybe_retry_incident


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "ops" / "incident.schema.json"
NOW = datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc)


def _report(**overrides) -> RunReport:
    payload = dict(
        pipeline_id="openrouter-provider-activity",
        job_id="scrape-provider-activity",
        workflow="OpenRouter Provider Activity Daily",
        run_id="12345",
        run_attempt=1,
        commit_sha="abc123",
        started_at="2026-09-09T07:30:00Z",
        finished_at="2026-09-09T07:40:00Z",
        execution="failure",
        collection="failed",
        data_health="unknown",
        publication="failed",
        evidence_quality="incomplete",
        derived_state="FAILED_ACTIONABLE",
        checks=[
            CheckResult(
                check_id="producer.serving-activity",
                status="unknown",
                required=False,
                message="Producer step ended with failure: 504 gateway timeout",
                observed="failure",
            )
        ],
        outputs=[],
        evidence=[
            Evidence(
                kind="log",
                path=None,
                observed_at="2026-09-09T07:40:00Z",
                description="GitHub Actions reported a 504 gateway timeout.",
                check_id="producer.serving-activity",
            )
        ],
        shadow=True,
    )
    payload.update(overrides)
    return RunReport(**payload)


def test_transient_timeout_is_retry_eligible() -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    pipeline = registry.pipelines["openrouter-provider-activity"]
    report = _report()
    incident = incident_from_report(report, pipeline=pipeline, now=NOW)
    assert incident is not None
    assert incident.error_class == "transient_timeout"
    assert incident.retry_eligible is True
    assert incident.status == "RETRYING"
    validate_incident(incident.to_dict(), SCHEMA)


def test_stale_data_is_not_auto_retried_and_needs_human() -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    pipeline = registry.pipelines["openrouter-provider-activity"]
    report = _report(
        execution="success",
        collection="complete",
        data_health="stale",
        publication="retained_previous",
        derived_state="STALE",
        evidence_quality="verified",
        checks=[
            CheckResult(
                check_id="provider-daily-activity.freshness",
                status="stale",
                required=True,
                message="Latest observation is outside the freshness allowance.",
            )
        ],
    )
    incident = incident_from_report(report, pipeline=pipeline, now=NOW)
    assert incident is not None
    assert incident.error_class == "stale_data"
    assert incident.retry_eligible is False
    assert incident.needs_human is True
    assert incident.status == "NEEDS_HUMAN"


def test_same_fingerprint_is_stable_across_runs() -> None:
    left = fingerprint_for(pipeline_id="p", failed_check="c", error_class="e")
    right = fingerprint_for(pipeline_id="p", failed_check="c", error_class="e")
    assert left == right
    assert "p:c:e:" in left


def test_retry_helper_invokes_github_once(monkeypatch) -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    incident = incident_from_report(_report(), pipeline=registry.pipelines["openrouter-provider-activity"], now=NOW)
    calls = []
    monkeypatch.setattr(
        "ops_control.retry.retry_workflow_run",
        lambda **kwargs: calls.append(kwargs) or {},
    )
    updated, retried = maybe_retry_incident(
        incident=incident,
        repository="Henrywzh/alternative-data",
        token="ghs_test",
        now=NOW,
    )
    assert retried is True
    assert updated.retry_attempted is True
    assert updated.retry_eligible is False
    assert calls == [{"repository": "Henrywzh/alternative-data", "token": "ghs_test", "run_id": "12345"}]


def test_healthy_report_marks_existing_incident_recovered() -> None:
    from ops_control.incidents import mark_recovered
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    incident = incident_from_report(_report(), pipeline=registry.pipelines["openrouter-provider-activity"], now=NOW)
    recovered = mark_recovered(incident, now=NOW, run_id="999")
    assert recovered.status == "RECOVERED"
    assert recovered.derived_state == "HEALTHY"
    assert recovered.needs_human is False
    assert "999" in recovered.run_ids
