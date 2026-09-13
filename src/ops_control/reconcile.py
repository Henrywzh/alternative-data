from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Any

from .baseline import extract_run_report, select_previous_artifact
from .incidents import Incident, incident_from_report, missed_schedule_incident
from .models import RunReport
from .registry import JobSpec, PipelineRegistry, PipelineSpec


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def expected_jobs_due(pipeline: PipelineSpec, *, now: datetime) -> list[JobSpec]:
    cadence = pipeline.cadence or {}
    kind = str(cadence.get("kind", ""))
    if kind == "daily":
        return list(pipeline.jobs.values())
    if kind != "monthly_windows":
        return []
    due: list[JobSpec] = []
    for window in cadence.get("schedule_windows", []):
        job_id = str(window.get("job_id") or "")
        if not job_id or job_id not in pipeline.jobs:
            continue
        job = pipeline.jobs[job_id]
        deadline = schedule_deadline(pipeline, job, now=now)
        if deadline is not None and now >= deadline:
            due.append(job)
    return due


def schedule_deadline(pipeline: PipelineSpec, job: JobSpec, *, now: datetime) -> datetime | None:
    cadence = pipeline.cadence or {}
    grace = timedelta(hours=float(cadence.get("grace_hours", 6)))
    kind = str(cadence.get("kind", ""))
    if kind == "daily":
        interval = timedelta(hours=float(cadence.get("expected_interval_hours", 24)))
        return now - interval - grace
    if kind != "monthly_windows":
        return None
    for window in cadence.get("schedule_windows", []):
        if str(window.get("job_id") or "") != job.job_id:
            continue
        days = str(window.get("days", "")).strip()
        end = int(days.split("-")[-1])
        end = min(end, monthrange(now.year, now.month)[1])
        if now.day < end:
            return None
        close = datetime(now.year, now.month, end, 23, 59, tzinfo=timezone.utc)
        return close + grace
    return None


def missed_schedule(*, pipeline: PipelineSpec, job: JobSpec, last_finished_at: str | None, now: datetime) -> bool:
    deadline = schedule_deadline(pipeline, job, now=now)
    if deadline is None:
        return False
    finished = parse_iso(last_finished_at)
    if finished is None:
        return now >= deadline
    return finished < deadline and now >= deadline


def collect_latest_reports(*, registry: PipelineRegistry, artifacts: list[dict[str, Any]], download_artifact) -> dict[tuple[str, str], RunReport]:
    reports: dict[tuple[str, str], RunReport] = {}
    for pipeline in registry.pipelines.values():
        for job in pipeline.jobs.values():
            prefix = job.artifact_prefix or pipeline.artifact_prefix
            if not prefix:
                continue
            artifact = select_previous_artifact(artifacts, artifact_prefix=prefix, current_run_id="")
            if artifact is None:
                continue
            payload = extract_run_report(download_artifact(artifact))
            reports[(pipeline.pipeline_id, job.job_id)] = RunReport.from_dict(payload)
    return reports


def reconcile_registry(*, registry: PipelineRegistry, reports: dict[tuple[str, str], RunReport], now: datetime) -> list[Incident]:
    incidents: list[Incident] = []
    for pipeline in registry.pipelines.values():
        for job in expected_jobs_due(pipeline, now=now):
            report = reports.get((pipeline.pipeline_id, job.job_id))
            last_finished = None if report is None else report.finished_at
            if missed_schedule(pipeline=pipeline, job=job, last_finished_at=last_finished, now=now):
                incidents.append(missed_schedule_incident(pipeline=pipeline, job_id=job.job_id, now=now, last_finished_at=last_finished))
                continue
            if report is None:
                continue
            incident = incident_from_report(report, pipeline=pipeline, now=now)
            if incident is not None:
                incidents.append(incident)
    return incidents
