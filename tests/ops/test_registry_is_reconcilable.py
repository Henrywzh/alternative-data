"""Every registered pipeline must actually be reachable by the reconciler.

A registry entry can be valid and still be invisible to reconciliation, and
the failure is silent in both directions:

  * a job with no `artifact_prefix` is skipped by collect_latest_reports, so
    its last successful run reads as None and every reconciliation opens a
    missed-schedule incident for a pipeline that ran perfectly;
  * a cadence kind that expected_jobs_due does not know, or a monthly window
    without `job_id`, makes the job never due -- so it is never checked at
    all, while looking monitored in the registry.

The three free-institutional pipelines shipped with all three defects: the
daily one raised a false incident on the reconciler's first green run, and the
weekly and monthly ones were never examined.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from ops_control.reconcile import expected_jobs_due, schedule_deadline
from ops_control.registry import load_registry


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "config" / "ops" / "pipelines.yaml"
WORKFLOWS = ROOT / ".github" / "workflows"
REGISTRY = load_registry(REGISTRY_PATH, repo_root=ROOT)
NOW = datetime(2026, 9, 13, 13, 0, tzinfo=timezone.utc)

PIPELINES = sorted(REGISTRY.pipelines)
JOBS = [
    (pipeline_id, job_id)
    for pipeline_id, pipeline in sorted(REGISTRY.pipelines.items())
    for job_id in sorted(pipeline.jobs)
]


@pytest.mark.parametrize(("pipeline_id", "job_id"), JOBS)
def test_every_job_declares_where_its_telemetry_lands(pipeline_id: str, job_id: str) -> None:
    pipeline = REGISTRY.pipelines[pipeline_id]
    job = pipeline.jobs[job_id]
    prefix = job.artifact_prefix or pipeline.artifact_prefix

    assert prefix, (
        f"{pipeline_id}.{job_id} has no artifact_prefix, so the reconciler "
        "cannot find its last successful run and will report a healthy "
        "pipeline as a missed schedule on every pass."
    )


@pytest.mark.parametrize(("pipeline_id", "job_id"), JOBS)
def test_every_job_can_become_due(pipeline_id: str, job_id: str) -> None:
    # A deadline of None means this job is never evaluated -- an unknown
    # cadence kind, or a monthly window with no job_id.
    pipeline = REGISTRY.pipelines[pipeline_id]
    job = pipeline.jobs[job_id]

    deadline = schedule_deadline(pipeline, job, now=NOW)
    monthly = str(pipeline.cadence.get("kind", "")) == "monthly_windows"

    assert deadline is not None or monthly, (
        f"{pipeline_id}.{job_id} never gets a deadline, so reconciliation "
        "skips it while the registry makes it look watched."
    )


@pytest.mark.parametrize("pipeline_id", PIPELINES)
def test_a_monthly_window_names_the_job_it_covers(pipeline_id: str) -> None:
    pipeline = REGISTRY.pipelines[pipeline_id]
    if str(pipeline.cadence.get("kind", "")) != "monthly_windows":
        pytest.skip("not a windowed cadence")

    for window in pipeline.cadence.get("schedule_windows", []):
        job_id = str(window.get("job_id") or "")
        assert job_id in pipeline.jobs, (
            f"{pipeline_id} has a schedule window for {job_id!r}, which is not "
            "one of its jobs, so expected_jobs_due skips it silently."
        )


@pytest.mark.parametrize("pipeline_id", PIPELINES)
def test_the_prefix_matches_the_artifact_the_workflow_uploads(pipeline_id: str) -> None:
    # The prefix is only useful if it matches reality; these are two strings in
    # two files that nothing otherwise ties together.
    pipeline = REGISTRY.pipelines[pipeline_id]
    prefixes = [pipeline.artifact_prefix] + [j.artifact_prefix for j in pipeline.jobs.values()]
    prefixes = [p for p in prefixes if p]
    workflow = (WORKFLOWS / pipeline.workflow).read_text(encoding="utf-8")

    for prefix in prefixes:
        assert prefix in workflow, (
            f"{pipeline_id} expects artifacts named {prefix!r}, but "
            f"{pipeline.workflow} never uploads one."
        )
