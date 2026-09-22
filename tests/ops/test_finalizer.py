from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import subprocess
import sys
from pathlib import Path

from ops_control.finalize import _maybe_record_incident, finalize_run, write_fallback_report
from ops_control.incidents import mark_recovered, missed_schedule_incident
from ops_control.models import CheckResult, RunReport
from ops_control.registry import load_registry
from ops_control.schema import validate_run_report
from ops_control.store import _issue_body, parse_issue


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config" / "ops" / "pipelines.yaml"
SCHEMA = ROOT / "schemas" / "ops" / "run-report.schema.json"
NOW = datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc)


def test_finalizer_writes_schema_valid_report_and_evidence_manifest(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "run-report.json"
    evidence_path = tmp_path / "evidence-manifest.json"

    report = finalize_run(
        pipeline_id="openrouter-provider-activity",
        job_id="scrape-provider-activity",
        execution="success",
        repo_root=ROOT,
        registry_path=REGISTRY,
        schema_path=SCHEMA,
        output_path=report_path,
        evidence_output_path=evidence_path,
        now=NOW,
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    validate_run_report(payload, SCHEMA)
    assert report.derived_state == "HEALTHY"
    assert evidence_path.is_file()
    assert len(report.outputs) == 5
    assert all(output.exists for output in report.outputs)


def test_failed_job_with_valid_existing_outputs_is_degraded_not_healthy(
    tmp_path: Path,
) -> None:
    report = finalize_run(
        pipeline_id="openrouter-provider-activity",
        job_id="scrape-provider-activity",
        execution="failure",
        repo_root=ROOT,
        registry_path=REGISTRY,
        schema_path=SCHEMA,
        output_path=tmp_path / "run-report.json",
        evidence_output_path=tmp_path / "evidence-manifest.json",
        now=NOW,
    )

    assert report.execution == "failure"
    assert report.data_health == "fresh"
    assert report.publication == "retained_previous"
    assert report.derived_state == "DEGRADED_RETAINED"


def test_tolerated_producer_failure_is_preserved_in_report(tmp_path: Path) -> None:
    report = finalize_run(
        pipeline_id="openrouter-provider-activity",
        job_id="scrape-provider-activity",
        execution="success",
        producer_outcomes={"serving-provider": "failure"},
        repo_root=ROOT,
        registry_path=REGISTRY,
        schema_path=SCHEMA,
        output_path=tmp_path / "run-report.json",
        evidence_output_path=tmp_path / "evidence-manifest.json",
        now=NOW,
    )

    assert report.execution == "success"
    assert report.collection == "partial"
    assert report.evidence_quality == "incomplete"
    assert report.derived_state == "DEGRADED_RETAINED"
    assert any(check.check_id == "producer.serving-provider" for check in report.checks)


def test_previous_run_report_detects_observation_period_regression(
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline = finalize_run(
        pipeline_id="openrouter-provider-activity",
        job_id="scrape-provider-activity",
        execution="success",
        repo_root=ROOT,
        registry_path=REGISTRY,
        schema_path=SCHEMA,
        output_path=tmp_path / "baseline-source.json",
        evidence_output_path=tmp_path / "baseline-evidence.json",
        now=NOW,
    )
    payload = baseline.to_dict()
    for output in payload["outputs"]:
        output["latest_observation"] = "2099-01-01"
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")

    report = finalize_run(
        pipeline_id="openrouter-provider-activity",
        job_id="scrape-provider-activity",
        execution="success",
        repo_root=ROOT,
        registry_path=REGISTRY,
        schema_path=SCHEMA,
        output_path=tmp_path / "run-report.json",
        evidence_output_path=tmp_path / "evidence-manifest.json",
        baseline_path=baseline_path,
        now=NOW,
    )

    assert report.data_health == "regressed"
    assert report.derived_state == "REGRESSED"
    assert any(check.status == "regressed" for check in report.checks)


def test_finalizer_error_still_writes_a_schema_valid_fallback(tmp_path: Path) -> None:
    report_path = tmp_path / "run-report.json"
    evidence_path = tmp_path / "evidence-manifest.json"

    report = write_fallback_report(
        pipeline_id="unknown-pipeline",
        job_id="unknown-job",
        execution="failure",
        output_path=report_path,
        evidence_output_path=evidence_path,
        error=RuntimeError("api_key=top-secret-value"),
        now=NOW,
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    validate_run_report(payload, SCHEMA)
    assert report.derived_state == "UNKNOWN_EVIDENCE"
    assert "top-secret-value" not in report_path.read_text(encoding="utf-8")
    assert "top-secret-value" not in evidence_path.read_text(encoding="utf-8")


def test_healthy_finalizer_preserves_manual_reopen_but_recovers_ordinary_issue(monkeypatch) -> None:
    registry = load_registry(REGISTRY, repo_root=ROOT)
    pipeline = registry.pipelines["openrouter-provider-activity"]
    original = missed_schedule_incident(
        pipeline=pipeline,
        job_id="scrape-provider-activity",
        now=NOW,
        last_finished_at=None,
    )
    reopened = parse_issue({
        "state": "open",
        "body": _issue_body(mark_recovered(original, now=NOW)),
        "html_url": "https://github.com/example/ops/issues/3",
    })
    assert reopened is not None
    ordinary = replace(original, status="NEEDS_HUMAN", needs_human=True)
    written = []

    class FakeStore:
        def __init__(self, **kwargs):
            pass

        def find_open_for_job(self, pipeline_id, job_id):
            return [reopened, ordinary]

        def upsert(self, incident):
            written.append(incident)

    monkeypatch.setenv("OPS_INCIDENT_REPO", "example/ops")
    monkeypatch.setenv("OPS_INCIDENT_TOKEN", "test-token")
    monkeypatch.setattr("ops_control.finalize.IncidentStore", FakeStore)
    report = RunReport(
        pipeline_id=original.pipeline_id,
        job_id=original.job_id,
        workflow="test.yml",
        run_id="100",
        run_attempt=1,
        commit_sha="abc",
        started_at="2026-09-08T02:00:00Z",
        finished_at="2026-09-08T02:00:00Z",
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

    _maybe_record_incident(report, pipeline=pipeline, now=NOW)

    assert len(written) == 1
    assert written[0].status == "RECOVERED"
    assert written[0].manually_reopened is False


def test_script_writes_fallback_when_third_party_dependencies_are_unavailable(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "run-report.json"
    evidence_path = tmp_path / "evidence-manifest.json"
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(ROOT / "scripts" / "ops" / "finalize_pipeline.py"),
            "--pipeline-id",
            "openrouter-provider-activity",
            "--job-id",
            "scrape-provider-activity",
            "--execution",
            "failure",
            "--output",
            str(report_path),
            "--evidence-output",
            str(evidence_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    validate_run_report(payload, SCHEMA)
    assert payload["derived_state"] == "UNKNOWN_EVIDENCE"
    assert evidence_path.is_file()
