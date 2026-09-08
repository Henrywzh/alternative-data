from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

from ops_control.schema import validate_run_report


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
PILOT_JOBS = {
    "openrouter-provider-activity-daily.yml": (
        "openrouter-provider-activity",
        ["scrape-provider-activity"],
    ),
    "asia-markets-dashboard-refresh-daily.yml": (
        "asia-markets-dashboard-refresh",
        ["refresh-dashboard-data"],
    ),
    "semiconductor-memory-monthly.yml": (
        "semiconductor-memory-monthly",
        ["adata-update", "fred-update"],
    ),
}


@pytest.mark.parametrize(
    ("workflow_name", "pipeline_id", "job_id"),
    [
        (workflow_name, pipeline_id, job_id)
        for workflow_name, (pipeline_id, job_ids) in PILOT_JOBS.items()
        for job_id in job_ids
    ],
)
def test_every_pilot_job_emits_and_uploads_non_blocking_shadow_telemetry(
    workflow_name: str,
    pipeline_id: str,
    job_id: str,
    tmp_path: Path,
) -> None:
    workflow = yaml.load(
        (WORKFLOWS / workflow_name).read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert workflow["permissions"]["actions"] == "read"
    job = workflow["jobs"][job_id]
    steps = {step["name"]: step for step in job["steps"] if "name" in step}

    baseline = steps["Fetch previous Phase 0 baseline"]
    assert baseline["if"] == "always()"
    assert baseline["continue-on-error"] == "true"
    assert "scripts/ops/fetch_baseline.py" in baseline["run"]

    emit = steps["Emit Phase 0 shadow run report"]
    assert emit["if"] == "always()"
    assert emit["continue-on-error"] == "true"
    assert "scripts/ops/finalize_pipeline.py" in emit["run"]
    assert f"--pipeline-id {pipeline_id}" in emit["run"]
    assert f"--job-id {job_id}" in emit["run"]
    assert "--baseline-report " in emit["run"]

    fallback = steps["Ensure Phase 0 fallback telemetry exists"]
    assert fallback["if"] == "always()"
    assert fallback["continue-on-error"] == "true"
    assert fallback["uses"] == "actions/github-script@v7"

    report_path = tmp_path / workflow_name / job_id / "run-report.json"
    evidence_path = report_path.with_name("evidence-manifest.json")
    env = dict(os.environ)
    env.update(
        {
            "OPS_PIPELINE_ID": pipeline_id,
            "OPS_JOB_ID": job_id,
            "OPS_JOB_STATUS": "failure",
            "OPS_REPORT_PATH": str(report_path),
            "OPS_EVIDENCE_PATH": str(evidence_path),
            "GITHUB_WORKFLOW": workflow_name,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_SHA": "a" * 40,
        }
    )
    script = fallback["with"]["script"]
    result = subprocess.run(
        ["node", "-e", f"(async () => {{\n{script}\n}})()"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    validate_run_report(payload, ROOT / "schemas" / "ops" / "run-report.schema.json")
    assert payload["derived_state"] == "UNKNOWN_EVIDENCE"
    assert evidence_path.is_file()

    original_report = report_path.read_text(encoding="utf-8")
    evidence_path.unlink()
    repaired = subprocess.run(
        ["node", "-e", f"(async () => {{\n{script}\n}})()"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert repaired.returncode == 0, repaired.stderr
    assert report_path.read_text(encoding="utf-8") == original_report
    manifest = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == payload["run_id"]

    report_path.write_text("{}\n", encoding="utf-8")
    evidence_path.unlink()
    replaced = subprocess.run(
        ["node", "-e", f"(async () => {{\n{script}\n}})()"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert replaced.returncode == 0, replaced.stderr
    validate_run_report(
        json.loads(report_path.read_text(encoding="utf-8")),
        ROOT / "schemas" / "ops" / "run-report.schema.json",
    )
    assert evidence_path.is_file()

    upload = steps["Upload Phase 0 shadow telemetry"]
    assert upload["if"] == "always()"
    assert upload["continue-on-error"] == "true"
    assert upload["uses"] == "actions/upload-artifact@v7"
    assert upload["with"]["retention-days"] == "30"


def test_phase_zero_pilots_only_use_github_hosted_runners() -> None:
    for workflow_name, (_, job_ids) in PILOT_JOBS.items():
        workflow = yaml.load(
            (WORKFLOWS / workflow_name).read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        for job_id in job_ids:
            assert workflow["jobs"][job_id]["runs-on"] == "ubuntu-latest"
            assert "self-hosted" not in str(workflow["jobs"][job_id])


def test_tolerated_producer_outcomes_are_wired_into_shadow_finalizers() -> None:
    openrouter = (
        WORKFLOWS / "openrouter-provider-activity-daily.yml"
    ).read_text(encoding="utf-8")
    asia = (
        WORKFLOWS / "asia-markets-dashboard-refresh-daily.yml"
    ).read_text(encoding="utf-8")

    assert "--producer-outcome \"serving-activity=${{ steps.serving_activity.outcome }}\"" in openrouter
    assert "--producer-outcome \"serving-economics=${{ steps.serving_economics.outcome }}\"" in openrouter
    assert "--producer-outcome \"bd-history=${{ steps.bd_history.outputs.producer_outcome }}\"" in asia
    assert "--producer-outcome \"local-consumer-ingest=${{ steps.local_consumer_ingest.outputs.producer_outcome }}\"" in asia
    assert "--producer-outcome \"sector-builders=${{ steps.sector_builders.outputs.producer_outcome }}\"" in asia
