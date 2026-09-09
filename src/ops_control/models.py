from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    status: str
    required: bool
    message: str
    expected: str | None = None
    observed: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CheckResult":
        return cls(
            check_id=str(payload["check_id"]),
            status=str(payload["status"]),
            required=bool(payload["required"]),
            message=str(payload.get("message", "")),
            expected=_optional_string(payload.get("expected")),
            observed=_optional_string(payload.get("observed")),
            details=dict(payload.get("details", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OutputObservation:
    output_id: str
    path: str
    required: bool
    exists: bool
    size_bytes: int | None
    row_count: int | None
    latest_observation: str | None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OutputObservation":
        return cls(
            output_id=str(payload["output_id"]),
            path=str(payload["path"]),
            required=bool(payload["required"]),
            exists=bool(payload["exists"]),
            size_bytes=_optional_int(payload.get("size_bytes")),
            row_count=_optional_int(payload.get("row_count")),
            latest_observation=_optional_string(payload.get("latest_observation")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Evidence:
    kind: str
    path: str | None
    observed_at: str
    description: str
    run_url: str | None = None
    commit_sha: str | None = None
    check_id: str | None = None
    references: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Evidence":
        return cls(
            kind=str(payload["kind"]),
            path=_optional_string(payload.get("path")),
            observed_at=str(payload["observed_at"]),
            description=str(payload.get("description", "")),
            run_url=_optional_string(payload.get("run_url")),
            commit_sha=_optional_string(payload.get("commit_sha")),
            check_id=_optional_string(payload.get("check_id")),
            references=[str(item) for item in payload.get("references", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HealthDimensions:
    collection: str
    data_health: str
    publication: str
    derived_state: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class RunReport:
    pipeline_id: str
    job_id: str
    workflow: str
    run_id: str
    run_attempt: int
    commit_sha: str
    started_at: str | None
    finished_at: str
    execution: str
    collection: str
    data_health: str
    publication: str
    evidence_quality: str
    derived_state: str
    checks: list[CheckResult]
    outputs: list[OutputObservation]
    evidence: list[Evidence]
    shadow: bool = True
    schema_version: int = field(default=1, init=False)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunReport":
        report = cls(
            pipeline_id=str(payload["pipeline_id"]),
            job_id=str(payload["job_id"]),
            workflow=str(payload["workflow"]),
            run_id=str(payload["run_id"]),
            run_attempt=int(payload["run_attempt"]),
            commit_sha=str(payload["commit_sha"]),
            started_at=_optional_string(payload.get("started_at")),
            finished_at=str(payload["finished_at"]),
            execution=str(payload["execution"]),
            collection=str(payload["collection"]),
            data_health=str(payload["data_health"]),
            publication=str(payload["publication"]),
            evidence_quality=str(payload["evidence_quality"]),
            derived_state=str(payload["derived_state"]),
            checks=[CheckResult.from_dict(item) for item in payload.get("checks", [])],
            outputs=[
                OutputObservation.from_dict(item) for item in payload.get("outputs", [])
            ],
            evidence=[Evidence.from_dict(item) for item in payload.get("evidence", [])],
            shadow=bool(payload["shadow"]),
        )
        if int(payload.get("schema_version", 0)) != report.schema_version:
            raise ValueError(
                f"Unsupported run-report schema version: {payload.get('schema_version')!r}"
            )
        return report

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)
