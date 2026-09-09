from __future__ import annotations

from datetime import datetime, timezone
import json
import subprocess
import sys
from pathlib import Path

from ops_control.finalize import finalize_run, write_fallback_report
from ops_control.schema import validate_run_report


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
