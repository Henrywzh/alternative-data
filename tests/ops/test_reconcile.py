from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ops_control.incidents import missed_schedule_incident
from ops_control.models import RunReport, CheckResult
from ops_control.reconcile import missed_schedule, reconcile_registry
from ops_control.registry import load_registry
from ops_control.reporting import build_digest


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _healthy_report(pipeline_id: str, job_id: str, finished_at: str) -> RunReport:
    return RunReport(
        pipeline_id=pipeline_id,
        job_id=job_id,
        workflow=pipeline_id,
        run_id="99",
        run_attempt=1,
        commit_sha="abc",
        started_at=finished_at,
        finished_at=finished_at,
        execution="success",
        collection="complete",
        data_health="fresh",
        publication="published",
        evidence_quality="verified",
        derived_state="HEALTHY",
        checks=[CheckResult(check_id="ok", status="healthy", required=True, message="ok")],
        outputs=[],
        evidence=[],
        shadow=True,
    )


def test_daily_pipeline_is_missed_after_interval_plus_grace() -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    pipeline = registry.pipelines["openrouter-provider-activity"]
    job = pipeline.jobs["scrape-provider-activity"]
    assert missed_schedule(
        pipeline=pipeline,
        job=job,
        last_finished_at="2026-09-07T01:30:00Z",
        now=NOW,
    ) is True
    assert missed_schedule(
        pipeline=pipeline,
        job=job,
        last_finished_at="2026-09-09T01:30:00Z",
        now=NOW,
    ) is False


def test_reconcile_emits_missed_schedule_when_no_recent_report() -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    incidents = reconcile_registry(registry=registry, reports={}, now=NOW)
    fingerprints = {item.error_class for item in incidents}
    assert "missed_schedule" in fingerprints
    assert any(item.pipeline_id == "openrouter-provider-activity" for item in incidents)


def test_digest_mentions_healthy_count_and_open_incidents() -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    pipeline = registry.pipelines["openrouter-provider-activity"]
    incident = missed_schedule_incident(
        pipeline=pipeline,
        job_id="scrape-provider-activity",
        now=NOW,
        last_finished_at=None,
    )
    body = build_digest(registry=registry, incidents=[incident], now=NOW)
    assert "Open incidents: 1" in body
    assert "Needs human: 0" in body
    assert "openrouter-provider-activity/scrape-provider-activity" in body


def test_monday_digest_includes_weekly_section() -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    monday = datetime(2026, 9, 7, 1, 0, tzinfo=timezone.utc)  # 09:00 Taipei
    body = build_digest(registry=registry, incidents=[], now=monday)
    assert "All registered pilot jobs look healthy." in body
    assert "Weekly reliability:" in body
