from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .health import derive_dimensions, evaluate_job
from .models import CheckResult, Evidence, OutputObservation, RunReport
from .redaction import redact_text, redact_value
from .registry import load_registry
from .schema import validate_run_report


def finalize_run(
    *,
    pipeline_id: str,
    job_id: str,
    execution: str,
    repo_root: Path,
    registry_path: Path,
    schema_path: Path,
    output_path: Path,
    evidence_output_path: Path,
    baseline_path: Path | None = None,
    producer_outcomes: dict[str, str] | None = None,
    now: datetime | None = None,
) -> RunReport:
    observed_at = _isoformat(now or datetime.now(timezone.utc))
    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{observed_at}")
    commit_sha = os.environ.get("GITHUB_SHA", "local")
    run_url = _run_url(run_id)
    registry = load_registry(registry_path, repo_root=repo_root)
    pipeline, job = registry.job(pipeline_id, job_id)
    baseline = _load_baseline(baseline_path)
    checks, outputs, evidence = evaluate_job(
        job=job,
        repo_root=repo_root,
        observed_at=observed_at,
        as_of=(now or datetime.now(timezone.utc)).date(),
        baseline=baseline,
    )
    failed_producers = sorted(
        name
        for name, outcome in (producer_outcomes or {}).items()
        if outcome.strip().lower() in {"failure", "cancelled"}
    )
    checks.extend(
        CheckResult(
            check_id=f"producer.{name}",
            status="unknown",
            required=False,
            message=f"Producer step ended with {producer_outcomes[name]}.",
            observed=producer_outcomes[name],
        )
        for name in failed_producers
    )
    dimensions = derive_dimensions(
        execution=execution,
        checks=checks,
        producer_failures=bool(failed_producers),
    )
    evidence_quality = (
        "incomplete" if any(check.status == "unknown" for check in checks) else "verified"
    )
    report = RunReport(
        pipeline_id=pipeline_id,
        job_id=job_id,
        workflow=os.environ.get("GITHUB_WORKFLOW", pipeline.workflow),
        run_id=run_id,
        run_attempt=_positive_int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")),
        commit_sha=commit_sha,
        started_at=os.environ.get("OPS_RUN_STARTED_AT"),
        finished_at=observed_at,
        execution=_normalise_execution(execution),
        collection=dimensions.collection,
        data_health=dimensions.data_health,
        publication=dimensions.publication,
        evidence_quality=evidence_quality,
        derived_state=dimensions.derived_state,
        checks=[_redact_check(check) for check in checks],
        outputs=[_redact_output(output) for output in outputs],
        evidence=[
            _redact_evidence(
                item,
                run_url=run_url,
                commit_sha=commit_sha,
            )
            for item in evidence
        ],
        shadow=True,
    )
    validate_run_report(report.to_dict(), schema_path)
    _write_json(output_path, report.to_dict())
    _write_evidence_manifest(evidence_output_path, report)
    return report


def write_fallback_report(
    *,
    pipeline_id: str,
    job_id: str,
    execution: str,
    output_path: Path,
    evidence_output_path: Path,
    error: Exception,
    now: datetime | None = None,
) -> RunReport:
    observed_at = _isoformat(now or datetime.now(timezone.utc))
    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{observed_at}")
    commit_sha = os.environ.get("GITHUB_SHA", "local")
    run_url = _run_url(run_id)
    message = redact_text(f"Shadow finalizer failed: {type(error).__name__}: {error}")
    report = RunReport(
        pipeline_id=pipeline_id,
        job_id=job_id,
        workflow=os.environ.get("GITHUB_WORKFLOW", "unknown"),
        run_id=run_id,
        run_attempt=_positive_int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")),
        commit_sha=commit_sha,
        started_at=os.environ.get("OPS_RUN_STARTED_AT"),
        finished_at=observed_at,
        execution=_normalise_execution(execution),
        collection="unknown",
        data_health="unknown",
        publication="failed",
        evidence_quality="incomplete",
        derived_state="UNKNOWN_EVIDENCE",
        checks=[
            CheckResult(
                check_id="ops-shadow-finalizer",
                status="unknown",
                required=True,
                message=message,
            )
        ],
        outputs=[],
        evidence=[
            Evidence(
                kind="finalizer-error",
                path=None,
                observed_at=observed_at,
                description=message,
                run_url=run_url,
                commit_sha=commit_sha,
                check_id="ops-shadow-finalizer",
                references=[run_url] if run_url is not None else [],
            )
        ],
        shadow=True,
    )
    _write_json(output_path, report.to_dict())
    _write_evidence_manifest(evidence_output_path, report)
    return report


def _write_evidence_manifest(path: Path, report: RunReport) -> None:
    _write_json(
        path,
        {
            "version": 1,
            "pipeline_id": report.pipeline_id,
            "job_id": report.job_id,
            "run_id": report.run_id,
            "run_url": _run_url(report.run_id),
            "commit_sha": report.commit_sha,
            "observed_at": report.finished_at,
            "evidence": [item.to_dict() for item in report.evidence],
        },
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_baseline(path: Path | None) -> RunReport | None:
    if path is None or not path.is_file():
        return None
    return RunReport.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _redact_check(check: CheckResult) -> CheckResult:
    return CheckResult(
        check_id=redact_text(check.check_id),
        status=check.status,
        required=check.required,
        message=redact_text(check.message),
        expected=redact_text(check.expected) if check.expected is not None else None,
        observed=redact_text(check.observed) if check.observed is not None else None,
        details=redact_value(check.details),
    )


def _redact_evidence(
    evidence: Evidence,
    *,
    run_url: str | None,
    commit_sha: str,
) -> Evidence:
    return Evidence(
        kind=redact_text(evidence.kind),
        path=redact_text(evidence.path) if evidence.path is not None else None,
        observed_at=evidence.observed_at,
        description=redact_text(evidence.description),
        run_url=redact_text(evidence.run_url or run_url) if evidence.run_url or run_url else None,
        commit_sha=redact_text(evidence.commit_sha or commit_sha),
        check_id=redact_text(evidence.check_id) if evidence.check_id is not None else None,
        references=[
            redact_text(reference)
            for reference in (
                evidence.references
                + ([run_url] if run_url is not None and run_url not in evidence.references else [])
            )
        ],
    )


def _redact_output(output: OutputObservation) -> OutputObservation:
    return OutputObservation(
        output_id=redact_text(output.output_id),
        path=redact_text(output.path),
        required=output.required,
        exists=output.exists,
        size_bytes=output.size_bytes,
        row_count=output.row_count,
        latest_observation=(
            redact_text(output.latest_observation)
            if output.latest_observation is not None
            else None
        ),
    )


def _normalise_execution(value: str) -> str:
    normalised = value.strip().lower()
    return normalised if normalised in {"success", "failure", "cancelled"} else "unknown"


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        return 1
    return max(parsed, 1)


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_url(run_id: str) -> str | None:
    server = os.environ.get("GITHUB_SERVER_URL")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not server or not repository or run_id.startswith("local-"):
        return None
    return f"{server.rstrip('/')}/{repository}/actions/runs/{run_id}"
