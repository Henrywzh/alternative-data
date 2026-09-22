from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ops_control.incidents import missed_schedule_incident
from ops_control.models import RunReport, CheckResult
from ops_control.reconcile import (
    missed_schedule,
    reconcile_registry,
    recover_resolved_incidents,
)
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
    assert "Jobs without open incidents:" in body
    assert "Needs human: 0" in body
    assert "openrouter-provider-activity/scrape-provider-activity" in body


def test_monday_digest_includes_weekly_section() -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    monday = datetime(2026, 9, 7, 1, 0, tzinfo=timezone.utc)  # 09:00 Taipei
    body = build_digest(registry=registry, incidents=[], now=monday)
    assert "No open incidents in registered jobs." in body
    assert "Weekly reliability:" in body


def test_digest_only_counts_recovery_in_last_24_hours() -> None:
    from ops_control.incidents import mark_recovered

    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    pipeline = registry.pipelines["openrouter-provider-activity"]
    old = missed_schedule_incident(
        pipeline=pipeline, job_id="scrape-provider-activity", now=NOW, last_finished_at=None
    )
    recent = mark_recovered(old, now=datetime(2026, 9, 9, 11, 0, tzinfo=timezone.utc))
    historic = mark_recovered(old, now=datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc))
    body = build_digest(registry=registry, incidents=[recent, historic], now=NOW)
    assert "Recovered in last 24h: 1" in body
    assert body.count("- openrouter-provider-activity/scrape-provider-activity:") == 1
    assert "previous issue:" in body


def test_monthly_window_is_checked_after_grace_not_during_the_window() -> None:
    from ops_control.reconcile import expected_jobs_due
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    pipeline = registry.pipelines["semiconductor-memory-monthly"]
    during = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    after = datetime(2026, 9, 6, 6, 0, tzinfo=timezone.utc)
    assert expected_jobs_due(pipeline, now=during) == []
    due = expected_jobs_due(pipeline, now=after)
    assert [job.job_id for job in due] == ["adata-update"]
    incidents = reconcile_registry(registry=registry, reports={}, now=after)
    assert any(
        item.pipeline_id == "semiconductor-memory-monthly"
        and item.job_id == "adata-update"
        and item.error_class == "missed_schedule"
        for item in incidents
    )


def test_monthly_run_inside_window_satisfies_deadline() -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    pipeline = registry.pipelines["semiconductor-memory-monthly"]
    job = pipeline.jobs["adata-update"]
    assert missed_schedule(
        pipeline=pipeline,
        job=job,
        last_finished_at="2026-09-05T12:00:00Z",
        now=datetime(2026, 9, 22, 16, 0, tzinfo=timezone.utc),
    ) is False
    assert missed_schedule(
        pipeline=pipeline,
        job=job,
        last_finished_at="2026-08-05T12:00:00Z",
        now=datetime(2026, 9, 22, 16, 0, tzinfo=timezone.utc),
    ) is True


def test_late_monthly_run_resolves_open_missed_schedule() -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    pipeline = registry.pipelines["semiconductor-memory-monthly"]
    job = pipeline.jobs["adata-update"]
    assert missed_schedule(
        pipeline=pipeline,
        job=job,
        last_finished_at="2026-09-08T12:00:00Z",
        now=datetime(2026, 9, 22, 16, 0, tzinfo=timezone.utc),
    ) is False


def test_healthy_report_recovers_old_incident_when_job_is_now_clear() -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    pipeline = registry.pipelines["openrouter-provider-activity"]
    existing = missed_schedule_incident(
        pipeline=pipeline,
        job_id="scrape-provider-activity",
        now=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
        last_finished_at=None,
    )
    report = _healthy_report(
        "openrouter-provider-activity",
        "scrape-provider-activity",
        "2026-09-09T11:30:00Z",
    )

    recovered = recover_resolved_incidents(
        open_incidents=[existing],
        reports={(report.pipeline_id, report.job_id): report},
        current_incidents=[],
        now=NOW,
    )

    assert len(recovered) == 1
    assert recovered[0].fingerprint == existing.fingerprint
    assert recovered[0].status == "RECOVERED"
    assert recovered[0].derived_state == "HEALTHY"
    assert report.run_id in recovered[0].run_ids


def test_stale_healthy_report_does_not_recover_job_with_current_incident() -> None:
    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    pipeline = registry.pipelines["openrouter-provider-activity"]
    existing = missed_schedule_incident(
        pipeline=pipeline,
        job_id="scrape-provider-activity",
        now=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
        last_finished_at=None,
    )
    current = missed_schedule_incident(
        pipeline=pipeline,
        job_id="scrape-provider-activity",
        now=NOW,
        last_finished_at="2026-09-07T01:30:00Z",
    )
    report = _healthy_report(
        "openrouter-provider-activity",
        "scrape-provider-activity",
        "2026-09-07T01:30:00Z",
    )

    recovered = recover_resolved_incidents(
        open_incidents=[existing],
        reports={(report.pipeline_id, report.job_id): report},
        current_incidents=[current],
        now=NOW,
    )

    assert recovered == []
