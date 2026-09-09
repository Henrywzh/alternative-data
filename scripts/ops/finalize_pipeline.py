#!/usr/bin/env python3
"""Emit a non-blocking Phase 0 shadow run report for one registered job."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipeline-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--execution", required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--registry",
        type=Path,
        default=REPO_ROOT / "config" / "ops" / "pipelines.yaml",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=REPO_ROOT / "schemas" / "ops" / "run-report.schema.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument(
        "--producer-outcome",
        action="append",
        default=[],
        metavar="NAME=OUTCOME",
    )
    args = parser.parse_args(argv)

    try:
        from ops_control.finalize import finalize_run, write_fallback_report
    except Exception as exc:
        payload = _write_stdlib_fallback(
            pipeline_id=args.pipeline_id,
            job_id=args.job_id,
            execution=args.execution,
            output_path=args.output,
            evidence_output_path=args.evidence_output,
            error_type=type(exc).__name__,
        )
        print(
            "::warning::Phase 0 shadow finalizer dependencies unavailable: "
            f"{type(exc).__name__}"
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    try:
        report = finalize_run(
            pipeline_id=args.pipeline_id,
            job_id=args.job_id,
            execution=args.execution,
            repo_root=args.repo_root.resolve(),
            registry_path=args.registry.resolve(),
            schema_path=args.schema.resolve(),
            output_path=args.output,
            evidence_output_path=args.evidence_output,
            baseline_path=args.baseline_report,
            producer_outcomes=_parse_producer_outcomes(args.producer_outcome),
        )
    except Exception as exc:
        report = write_fallback_report(
            pipeline_id=args.pipeline_id,
            job_id=args.job_id,
            execution=args.execution,
            output_path=args.output,
            evidence_output_path=args.evidence_output,
            error=exc,
        )
        print(f"::warning::{report.checks[0].message}")

    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    if report.derived_state != "HEALTHY":
        print(
            "::warning::Phase 0 shadow telemetry classified "
            f"{report.pipeline_id}/{report.job_id} as {report.derived_state}"
        )
    return 0


def _write_stdlib_fallback(
    *,
    pipeline_id: str,
    job_id: str,
    execution: str,
    output_path: Path,
    evidence_output_path: Path,
    error_type: str,
) -> dict[str, Any]:
    """Write minimal telemetry even when installed dependencies are unavailable."""

    observed_at = (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    message = f"Shadow finalizer dependencies unavailable: {error_type}"
    run_id = os.environ.get("GITHUB_RUN_ID", f"local-{observed_at}")
    commit_sha = os.environ.get("GITHUB_SHA", "local")
    server = os.environ.get("GITHUB_SERVER_URL", "").rstrip("/")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_url = (
        f"{server}/{repository}/actions/runs/{run_id}"
        if server and repository and not run_id.startswith("local-")
        else None
    )
    normalised_execution = execution.strip().lower()
    if normalised_execution not in {"success", "failure", "cancelled"}:
        normalised_execution = "unknown"
    try:
        run_attempt = max(int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")), 1)
    except ValueError:
        run_attempt = 1
    payload = {
        "schema_version": 1,
        "pipeline_id": pipeline_id,
        "job_id": job_id,
        "workflow": os.environ.get("GITHUB_WORKFLOW", "unknown"),
        "run_id": run_id,
        "run_attempt": run_attempt,
        "commit_sha": commit_sha,
        "started_at": os.environ.get("OPS_RUN_STARTED_AT"),
        "finished_at": observed_at,
        "execution": normalised_execution,
        "collection": "unknown",
        "data_health": "unknown",
        "publication": "failed",
        "evidence_quality": "incomplete",
        "derived_state": "UNKNOWN_EVIDENCE",
        "checks": [
            {
                "check_id": "ops-shadow-finalizer",
                "status": "unknown",
                "required": True,
                "message": message,
                "expected": None,
                "observed": None,
                "details": {},
            }
        ],
        "outputs": [],
        "evidence": [
            {
                "kind": "finalizer-error",
                "path": None,
                "observed_at": observed_at,
                "description": message,
                "run_url": run_url,
                "commit_sha": commit_sha,
                "check_id": "ops-shadow-finalizer",
                "references": [run_url] if run_url is not None else [],
            }
        ],
        "shadow": True,
    }
    _write_json(output_path, payload)
    _write_json(
        evidence_output_path,
        {
            "version": 1,
            "pipeline_id": pipeline_id,
            "job_id": job_id,
            "run_id": payload["run_id"],
            "run_url": run_url,
            "commit_sha": commit_sha,
            "observed_at": observed_at,
            "evidence": payload["evidence"],
        },
    )
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_producer_outcomes(values: list[str]) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for value in values:
        name, separator, outcome = value.partition("=")
        if not separator or not name.strip():
            raise ValueError(f"Invalid producer outcome {value!r}; expected NAME=OUTCOME")
        outcomes[name.strip()] = outcome.strip()
    return outcomes


if __name__ == "__main__":
    raise SystemExit(main())
