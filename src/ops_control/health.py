from __future__ import annotations

import importlib.util
import sys
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd

from common.partitioned_parquet import dataset_parts, read_dataset

from .models import (
    CheckResult,
    Evidence,
    HealthDimensions,
    OutputObservation,
    RunReport,
)
from .redaction import redact_text
from .registry import JobSpec, OutputSpec


_DATA_HEALTH_PRIORITY = ("regressed", "invalid", "missing", "stale", "unknown")


def derive_dimensions(
    *,
    execution: str,
    checks: list[CheckResult],
    producer_failures: bool = False,
) -> HealthDimensions:
    required = [check for check in checks if check.required]
    statuses = {check.status for check in required}
    has_healthy = "healthy" in statuses

    if not required:
        collection = "unknown"
        data_health = "unknown"
    else:
        data_health = next(
            (status for status in _DATA_HEALTH_PRIORITY if status in statuses),
            "fresh",
        )
        collection_failures = statuses.intersection({"missing", "invalid", "unknown"})
        if execution != "success" or producer_failures:
            collection = "partial" if has_healthy else "failed"
        elif collection_failures:
            collection = "partial" if has_healthy else "failed"
        else:
            collection = "complete"

    if producer_failures and has_healthy:
        publication = "retained_previous"
    elif execution == "success" and data_health == "fresh":
        publication = "published"
    elif execution != "success" and has_healthy:
        publication = "retained_previous"
    elif data_health == "stale":
        publication = "retained_previous"
    else:
        publication = "failed"

    if (
        execution != "success" or producer_failures
    ) and publication == "retained_previous":
        derived_state = "DEGRADED_RETAINED"
    elif data_health == "regressed":
        derived_state = "REGRESSED"
    elif data_health == "stale":
        derived_state = "STALE"
    elif data_health in {"missing", "invalid"}:
        derived_state = "FAILED_ACTIONABLE"
    elif data_health == "unknown":
        derived_state = "UNKNOWN_EVIDENCE"
    elif execution != "success":
        derived_state = "FAILED_ACTIONABLE"
    else:
        derived_state = "HEALTHY"

    return HealthDimensions(
        collection=collection,
        data_health=data_health,
        publication=publication,
        derived_state=derived_state,
    )


def classify_regression(
    latest_observation: str | None,
    previous_latest_observation: str | None,
) -> bool:
    if latest_observation is None or previous_latest_observation is None:
        return False
    return latest_observation < previous_latest_observation


def evaluate_job(
    *,
    job: JobSpec,
    repo_root: Path,
    observed_at: str,
    as_of: date,
    baseline: RunReport | None = None,
) -> tuple[list[CheckResult], list[OutputObservation], list[Evidence]]:
    baseline_outputs = {
        output.output_id: output for output in (baseline.outputs if baseline else [])
    }
    checks: list[CheckResult] = []
    outputs: list[OutputObservation] = []
    evidence: list[Evidence] = []

    for spec in job.outputs:
        output_checks, observation = evaluate_output(
            spec=spec,
            repo_root=repo_root,
            as_of=as_of,
        )
        previous = baseline_outputs.get(spec.output_id)
        if previous and classify_regression(
            observation.latest_observation,
            previous.latest_observation,
        ):
            output_checks.append(
                CheckResult(
                    check_id=f"{spec.output_id}.non-regression",
                    status="regressed",
                    required=spec.required,
                    message=(
                        "Latest observation moved backwards from "
                        f"{previous.latest_observation} to "
                        f"{observation.latest_observation}."
                    ),
                    expected=previous.latest_observation,
                    observed=observation.latest_observation,
                )
            )
        checks.extend(output_checks)
        outputs.append(observation)
        evidence.append(
            Evidence(
                kind="output",
                path=observation.path,
                observed_at=observed_at,
                description=(
                    f"Observed output {observation.output_id}: "
                    f"exists={observation.exists}, rows={observation.row_count}, "
                    f"latest={observation.latest_observation}."
                ),
                check_id=(
                    output_checks[0].check_id if output_checks else None
                ),
                references=[observation.path],
            )
        )

    return checks, outputs, evidence


def evaluate_output(
    *,
    spec: OutputSpec,
    repo_root: Path,
    as_of: date,
) -> tuple[list[CheckResult], OutputObservation]:
    path = repo_root / spec.path
    observation = _observe_output(spec, path)
    if not observation.exists:
        return [
            CheckResult(
                check_id=f"{spec.output_id}.exists",
                status="missing",
                required=spec.required,
                message=f"Required output {spec.path} does not exist.",
            )
        ], observation

    try:
        if spec.validator == "dataset_contract":
            checks = _evaluate_dataset_contract(
                spec=spec,
                path=path,
                repo_root=repo_root,
                as_of=as_of,
                observation=observation,
            )
        elif spec.validator == "asia_markets_freshness":
            checks = _evaluate_asia_markets(
                spec=spec,
                repo_root=repo_root,
                as_of=as_of,
            )
        else:
            checks = [
                CheckResult(
                    check_id=f"{spec.output_id}.file",
                    status="healthy",
                    required=spec.required,
                    message=f"Output {spec.path} exists.",
                )
            ]
    except Exception as exc:
        checks = [
            CheckResult(
                check_id=f"{spec.output_id}.validator",
                status="invalid",
                required=spec.required,
                message=redact_text(f"Validator raised {type(exc).__name__}: {exc}"),
            )
        ]
    return checks, observation


def _observe_output(spec: OutputSpec, path: Path) -> OutputObservation:
    # A parquet output is one file or a directory of date partitions, and the
    # registry may name either spelling, so ask the shared resolver rather
    # than `is_file()`. Judging a migrated dataset missing is not a cosmetic
    # error: a required output that does not exist makes the whole run
    # FAILED_ACTIONABLE, which is the loudest state the control tower has.
    parts = dataset_parts(path)
    if parts:
        frame = read_dataset(path)
        latest: str | None = None
        date_column = _primary_date_column(spec.dataset_id)
        if date_column and date_column in frame.columns:
            values = frame[date_column].dropna().astype(str)
            if not values.empty:
                latest = str(values.max())[:10]
        return OutputObservation(
            output_id=spec.output_id,
            path=spec.path,
            required=spec.required,
            exists=True,
            # Summed, so the reported size stays comparable across a
            # migration instead of collapsing to one partition.
            size_bytes=sum(part.stat().st_size for part in parts),
            row_count=len(frame),
            latest_observation=latest,
        )

    if not path.is_file():
        return OutputObservation(
            output_id=spec.output_id,
            path=spec.path,
            required=spec.required,
            exists=False,
            size_bytes=None,
            row_count=None,
            latest_observation=None,
        )

    latest = None
    if path.suffix == ".json":
        try:
            import json

            payload = json.loads(path.read_text(encoding="utf-8"))
            latest = str(payload.get("asOf") or payload.get("auditedAt") or "") or None
        except (OSError, ValueError, TypeError):
            latest = None

    return OutputObservation(
        output_id=spec.output_id,
        path=spec.path,
        required=spec.required,
        exists=True,
        size_bytes=path.stat().st_size,
        row_count=None,
        latest_observation=latest,
    )


def _evaluate_dataset_contract(
    *,
    spec: OutputSpec,
    path: Path,
    repo_root: Path,
    as_of: date,
    observation: OutputObservation,
) -> list[CheckResult]:
    module = _load_script(
        repo_root / "scripts" / "check_dataset_contract.py",
        "ops_control_dataset_contract",
    )
    mode = str(spec.freshness.get("mode", ""))
    max_age = (
        float(spec.freshness["max_age_days"])
        if mode == "max_age_days"
        else None
    )
    failures = module.check_dataset(
        spec.dataset_id,
        path,
        fresh_within_days=max_age,
        now=pd.Timestamp(as_of, tz="UTC"),
    )
    if failures:
        status = _contract_failure_status(failures)
        return [
            CheckResult(
                check_id=f"{spec.output_id}.contract",
                status=status,
                required=spec.required,
                message=redact_text("; ".join(str(item) for item in failures)),
                observed=observation.latest_observation,
            )
        ]

    checks = [
        CheckResult(
            check_id=f"{spec.output_id}.contract",
            status="healthy",
            required=spec.required,
            message="Dataset contract satisfied.",
            observed=observation.latest_observation,
        )
    ]
    if mode == "monthly_release_lag":
        expected = expected_month_by_release_lag(
            as_of,
            release_lag_days=int(spec.freshness["release_lag_days"]),
        )
        status = (
            "healthy"
            if observation.latest_observation
            and observation.latest_observation[:7] >= expected
            else "stale"
        )
        checks.append(
            CheckResult(
                check_id=f"{spec.output_id}.freshness",
                status=status,
                required=spec.required,
                message=(
                    "Latest monthly observation meets the release-lag contract."
                    if status == "healthy"
                    else "Latest monthly observation is behind the release-lag contract."
                ),
                expected=expected,
                observed=(
                    observation.latest_observation[:7]
                    if observation.latest_observation
                    else None
                ),
            )
        )
    return checks


def _evaluate_asia_markets(
    *,
    spec: OutputSpec,
    repo_root: Path,
    as_of: date,
) -> list[CheckResult]:
    if spec.artifact_root is None:
        raise ValueError("asia_markets_freshness validator requires artifact_root")
    module = _load_script(
        repo_root / "scripts" / "audit_asia_markets_freshness.py",
        "ops_control_asia_freshness",
    )
    report = module.audit_artifacts(repo_root / spec.artifact_root, as_of=as_of)
    checks: list[CheckResult] = []
    for item in report.get("checks", []):
        status = "healthy" if item.get("status") == "healthy" else "stale"
        checks.append(
            CheckResult(
                check_id=str(item.get("check_id", "asia-markets.unknown")),
                status=status,
                required=bool(item.get("required", True)),
                message=redact_text(str(item.get("notes", ""))),
                expected=_optional_string(item.get("expected_latest_period")),
                observed=_optional_string(item.get("latest_observation")),
                details={
                    "sector": item.get("sector"),
                    "dataset": item.get("dataset"),
                },
            )
        )
    if not checks:
        checks.append(
            CheckResult(
                check_id=f"{spec.output_id}.audit",
                status="unknown",
                required=spec.required,
                message="Asia Markets freshness audit returned no checks.",
            )
        )
    return checks


def expected_month_by_release_lag(as_of: date, *, release_lag_days: int) -> str:
    candidates: list[date] = []
    for offset in range(-24, 1):
        month_index = as_of.year * 12 + as_of.month - 1 + offset
        year, month_index_zero = divmod(month_index, 12)
        month = month_index_zero + 1
        end = date(year, month, monthrange(year, month)[1])
        if (as_of - end).days >= release_lag_days:
            candidates.append(end)
    if not candidates:
        raise ValueError(f"No eligible month for {as_of}")
    return max(candidates).strftime("%Y-%m")


def _contract_failure_status(failures: list[str]) -> str:
    text = " ".join(failures).lower()
    if "does not exist" in text:
        return "missing"
    if "days behind" in text:
        return "stale"
    return "invalid"


def _primary_date_column(dataset_id: str | None) -> str | None:
    if dataset_id is None:
        return None
    from dashboard.data import DATASET_REGISTRY

    value = DATASET_REGISTRY.get(dataset_id, {}).get("primary_date_column")
    return str(value) if value else None


def _load_script(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)
