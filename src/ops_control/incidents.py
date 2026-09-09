from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, RefResolver
from jsonschema.exceptions import SchemaError, ValidationError

from .models import CheckResult, Evidence, RunReport
from .redaction import redact_text, redact_value
from .registry import PipelineSpec
from .schema import _FORMAT_CHECKER


ACTIVE_STATUSES = {
    "DETECTED",
    "RETRYING",
    "TRIAGING_CLOUD",
    "NEEDS_LOCAL",
    "NEEDS_HUMAN",
    "VALIDATING",
}
TERMINAL_STATUSES = {"RECOVERED", "CLOSED"}
TRANSIENT_ERROR_CLASSES = {"transient_timeout", "rate_limited", "upstream_5xx"}
TRANSIENT_PATTERNS = (
    re.compile(r"\b(timeout|timed out|temporarily unavailable)\b", re.I),
    re.compile(r"\b(429|rate[- ]?limit)\b", re.I),
    re.compile(r"\b(50[0234]|bad gateway|service unavailable|gateway timeout)\b", re.I),
)


class IncidentSchemaError(ValueError):
    """Raised when an incident payload fails schema validation."""


@dataclass(frozen=True)
class Incident:
    incident_id: str
    fingerprint: str
    pipeline_id: str
    job_id: str
    status: str
    severity: str
    title: str
    summary: str
    failed_check: str
    error_class: str
    derived_state: str
    retry_eligible: bool
    retry_attempted: bool
    needs_human: bool
    needs_local: bool
    opened_at: str
    updated_at: str
    last_seen_at: str
    occurrence_count: int
    run_ids: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    observed: tuple[str, ...]
    inferred: tuple[str, ...]
    unknown: tuple[str, ...]
    recovered_at: str | None = None
    issue_url: str | None = None
    schema_version: int = field(default=1, init=False)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Incident":
        return cls(
            incident_id=str(payload["incident_id"]),
            fingerprint=str(payload["fingerprint"]),
            pipeline_id=str(payload["pipeline_id"]),
            job_id=str(payload["job_id"]),
            status=str(payload["status"]),
            severity=str(payload["severity"]),
            title=str(payload["title"]),
            summary=str(payload["summary"]),
            failed_check=str(payload["failed_check"]),
            error_class=str(payload["error_class"]),
            derived_state=str(payload["derived_state"]),
            retry_eligible=bool(payload["retry_eligible"]),
            retry_attempted=bool(payload["retry_attempted"]),
            needs_human=bool(payload["needs_human"]),
            needs_local=bool(payload["needs_local"]),
            opened_at=str(payload["opened_at"]),
            updated_at=str(payload["updated_at"]),
            last_seen_at=str(payload["last_seen_at"]),
            occurrence_count=int(payload["occurrence_count"]),
            run_ids=tuple(str(item) for item in payload.get("run_ids", [])),
            evidence=tuple(Evidence.from_dict(item) for item in payload.get("evidence", [])),
            observed=tuple(str(item) for item in payload.get("observed", [])),
            inferred=tuple(str(item) for item in payload.get("inferred", [])),
            unknown=tuple(str(item) for item in payload.get("unknown", [])),
            recovered_at=None if payload.get("recovered_at") is None else str(payload["recovered_at"]),
            issue_url=None if payload.get("issue_url") is None else str(payload["issue_url"]),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = self.schema_version
        payload["run_ids"] = list(self.run_ids)
        payload["observed"] = list(self.observed)
        payload["inferred"] = list(self.inferred)
        payload["unknown"] = list(self.unknown)
        payload["evidence"] = [item.to_dict() for item in self.evidence]
        return payload


def fingerprint_for(
    *,
    pipeline_id: str,
    failed_check: str,
    error_class: str,
) -> str:
    digest = hashlib.sha256(
        f"{pipeline_id}|{failed_check}|{error_class}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{pipeline_id}:{failed_check}:{error_class}:{digest}"


def classify_error(check: CheckResult | None, *, derived_state: str) -> str:
    if derived_state == "MISSED_SCHEDULE":
        return "missed_schedule"
    if derived_state == "REGRESSED":
        return "observation_regressed"
    if derived_state == "STALE":
        return "stale_data"
    if derived_state == "DEGRADED_RETAINED":
        return "retained_previous"
    if derived_state == "UNKNOWN_EVIDENCE":
        return "incomplete_evidence"
    message = "" if check is None else f"{check.check_id} {check.message} {check.observed or ''}"
    for pattern, label in (
        (TRANSIENT_PATTERNS[0], "transient_timeout"),
        (TRANSIENT_PATTERNS[1], "rate_limited"),
        (TRANSIENT_PATTERNS[2], "upstream_5xx"),
    ):
        if pattern.search(message):
            return label
    if check is not None and check.status == "missing":
        return "missing_output"
    if check is not None and check.status == "invalid":
        return "invalid_output"
    return "failed_check"


def retry_eligible(
    *,
    error_class: str,
    pipeline: PipelineSpec | None = None,
    retry_attempted: bool = False,
) -> bool:
    if retry_attempted:
        return False
    policy = (pipeline.retry if pipeline is not None else {}) or {}
    if not bool(policy.get("automatic")):
        return False
    return error_class in TRANSIENT_ERROR_CLASSES


def primary_failed_check(report: RunReport) -> CheckResult | None:
    required_failures = [
        check
        for check in report.checks
        if check.required and check.status not in {"healthy", "ok"}
    ]
    if required_failures:
        return required_failures[0]
    optional_failures = [
        check for check in report.checks if check.status not in {"healthy", "ok"}
    ]
    return optional_failures[0] if optional_failures else None


def incident_from_report(
    report: RunReport,
    *,
    pipeline: PipelineSpec | None = None,
    now: datetime | None = None,
) -> Incident | None:
    if report.derived_state == "HEALTHY":
        return None
    check = primary_failed_check(report)
    failed_check = check.check_id if check is not None else "derived-state"
    error_class = classify_error(check, derived_state=report.derived_state)
    fingerprint = fingerprint_for(
        pipeline_id=report.pipeline_id,
        failed_check=failed_check,
        error_class=error_class,
    )
    observed_at = _isoformat(now or datetime.now(timezone.utc))
    eligible = retry_eligible(
        error_class=error_class,
        pipeline=pipeline,
        retry_attempted=report.run_attempt > 1,
    )
    needs_human = error_class not in TRANSIENT_ERROR_CLASSES and error_class != "missed_schedule"
    needs_local = error_class == "incomplete_evidence"
    status = "RETRYING" if eligible else ("NEEDS_LOCAL" if needs_local else "NEEDS_HUMAN" if needs_human else "DETECTED")
    summary = check.message if check is not None else f"Pipeline entered {report.derived_state}."
    observed = [
        redact_text(
            f"{report.pipeline_id}/{report.job_id} derived_state={report.derived_state} "
            f"execution={report.execution} collection={report.collection} "
            f"data_health={report.data_health} publication={report.publication}"
        )
    ]
    if check is not None:
        observed.append(redact_text(f"{check.check_id}: {check.message}"))
    inferred: list[str] = []
    unknown: list[str] = []
    if error_class in TRANSIENT_ERROR_CLASSES:
        inferred.append("The failure matches a transient infrastructure pattern and may recover on retry.")
    elif report.derived_state == "STALE":
        inferred.append("The workflow completed, but the latest observation is outside the freshness allowance.")
        unknown.append("Whether the upstream source delayed publication or the extractor missed a live update.")
    elif report.derived_state == "UNKNOWN_EVIDENCE":
        unknown.append("Whether the source still exposes the expected data after a rendered-page inspection.")
        needs_local = True
    return Incident(
        incident_id=fingerprint,
        fingerprint=fingerprint,
        pipeline_id=report.pipeline_id,
        job_id=report.job_id,
        status=status,
        severity=_severity(pipeline),
        title=f"{report.pipeline_id}: {failed_check} ({error_class})",
        summary=redact_text(summary),
        failed_check=failed_check,
        error_class=error_class,
        derived_state=report.derived_state,
        retry_eligible=eligible,
        retry_attempted=report.run_attempt > 1,
        needs_human=needs_human and not eligible,
        needs_local=needs_local,
        opened_at=observed_at,
        updated_at=observed_at,
        last_seen_at=report.finished_at,
        occurrence_count=1,
        run_ids=(report.run_id,),
        evidence=tuple(report.evidence),
        observed=tuple(observed),
        inferred=tuple(inferred),
        unknown=tuple(unknown),
    )


def missed_schedule_incident(
    *,
    pipeline: PipelineSpec,
    job_id: str,
    now: datetime,
    last_finished_at: str | None,
) -> Incident:
    failed_check = "schedule.window"
    error_class = "missed_schedule"
    fingerprint = fingerprint_for(
        pipeline_id=pipeline.pipeline_id,
        failed_check=failed_check,
        error_class=error_class,
    )
    observed_at = _isoformat(now)
    summary = (
        f"No successful run was observed for {pipeline.pipeline_id}/{job_id} "
        f"inside the expected schedule window."
    )
    observed = [
        summary if last_finished_at is None else f"{summary} Last finished_at={last_finished_at}."
    ]
    return Incident(
        incident_id=fingerprint,
        fingerprint=fingerprint,
        pipeline_id=pipeline.pipeline_id,
        job_id=job_id,
        status="DETECTED",
        severity=_severity(pipeline),
        title=f"{pipeline.pipeline_id}: missed schedule",
        summary=summary,
        failed_check=failed_check,
        error_class=error_class,
        derived_state="MISSED_SCHEDULE",
        retry_eligible=False,
        retry_attempted=False,
        needs_human=False,
        needs_local=False,
        opened_at=observed_at,
        updated_at=observed_at,
        last_seen_at=observed_at,
        occurrence_count=1,
        run_ids=(f"missed-{pipeline.pipeline_id}-{job_id}-{observed_at}",),
        evidence=(
            Evidence(
                kind="schedule",
                path=None,
                observed_at=observed_at,
                description=observed[0],
                check_id=failed_check,
            ),
        ),
        observed=tuple(observed),
        inferred=("The workflow may have been skipped, queued too long, or failed before emitting telemetry.",),
        unknown=("Whether GitHub skipped the cron, or the finalizer never uploaded a report.",),
    )


def merge_incident(existing: Incident, incoming: Incident) -> Incident:
    if existing.fingerprint != incoming.fingerprint:
        raise ValueError("Cannot merge incidents with different fingerprints")
    run_ids = tuple(dict.fromkeys([*existing.run_ids, *incoming.run_ids]))
    if incoming.derived_state == "HEALTHY":
        status = "RECOVERED"
        recovered_at = incoming.updated_at
        needs_human = False
        needs_local = False
        retry_eligible = False
    elif existing.status == "RECOVERED":
        status = incoming.status
        recovered_at = None
        needs_human = incoming.needs_human
        needs_local = incoming.needs_local
        retry_eligible = incoming.retry_eligible and not existing.retry_attempted
    else:
        status = existing.status if existing.status in ACTIVE_STATUSES else incoming.status
        if incoming.retry_eligible and not existing.retry_attempted:
            status = "RETRYING"
        recovered_at = existing.recovered_at
        needs_human = existing.needs_human or incoming.needs_human
        needs_local = existing.needs_local or incoming.needs_local
        retry_eligible = incoming.retry_eligible and not existing.retry_attempted
    return replace(
        existing,
        status=status,
        severity=_higher_severity(existing.severity, incoming.severity),
        title=incoming.title,
        summary=incoming.summary,
        derived_state=incoming.derived_state,
        retry_eligible=retry_eligible,
        retry_attempted=existing.retry_attempted or incoming.retry_attempted,
        needs_human=needs_human,
        needs_local=needs_local,
        updated_at=incoming.updated_at,
        last_seen_at=incoming.last_seen_at,
        recovered_at=recovered_at,
        occurrence_count=existing.occurrence_count + 1,
        run_ids=run_ids,
        evidence=incoming.evidence or existing.evidence,
        observed=tuple(dict.fromkeys([*existing.observed, *incoming.observed])),
        inferred=tuple(dict.fromkeys([*existing.inferred, *incoming.inferred])),
        unknown=tuple(dict.fromkeys([*existing.unknown, *incoming.unknown])),
        issue_url=existing.issue_url or incoming.issue_url,
    )


def mark_retry_attempted(incident: Incident, *, now: datetime) -> Incident:
    return replace(
        incident,
        status="RETRYING",
        retry_eligible=False,
        retry_attempted=True,
        updated_at=_isoformat(now),
    )


def mark_recovered(incident: Incident, *, now: datetime, run_id: str | None = None) -> Incident:
    run_ids = incident.run_ids if not run_id or run_id in incident.run_ids else incident.run_ids + (run_id,)
    stamp = _isoformat(now)
    return replace(
        incident,
        status="RECOVERED",
        derived_state="HEALTHY",
        retry_eligible=False,
        needs_human=False,
        needs_local=False,
        updated_at=stamp,
        last_seen_at=stamp,
        recovered_at=stamp,
        run_ids=run_ids,
    )


def validate_incident(payload: dict[str, Any], schema_path: Path) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        store = {schema.get("$id", str(schema_path)): schema}
        sibling = schema_path.with_name("run-report.schema.json")
        if sibling.is_file():
            sibling_schema = json.loads(sibling.read_text(encoding="utf-8"))
            store[sibling_schema.get("$id", str(sibling))] = sibling_schema
        resolver = RefResolver.from_schema(schema, store=store)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(
            schema,
            resolver=resolver,
            format_checker=_FORMAT_CHECKER,
        ).validate(payload)
    except (OSError, json.JSONDecodeError, SchemaError) as exc:
        raise IncidentSchemaError(f"incident schema: {exc}") from exc
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise IncidentSchemaError(f"{location}: {exc.message}") from exc


def redact_incident(incident: Incident) -> Incident:
    payload = redact_value(incident.to_dict())
    return Incident.from_dict(payload)


def _severity(pipeline: PipelineSpec | None) -> str:
    if pipeline is None:
        return "medium"
    return {
        "low": "low",
        "medium": "medium",
        "high": "high",
    }.get(pipeline.criticality, "medium")


def _higher_severity(left: str, right: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return left if order.get(left, 0) >= order.get(right, 0) else right


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
