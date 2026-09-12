from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver


class RegistryError(ValueError):
    """Raised when the pipeline registry is internally inconsistent."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True)
class OutputSpec:
    output_id: str
    path: str
    required: bool
    validator: str
    dataset_id: str | None = None
    artifact_root: str | None = None
    freshness: dict[str, Any] = field(default_factory=dict)
    # Which column carries the observation date. dataset_contract takes this
    # from dashboard.data.DATASET_REGISTRY, but a lane that feeds no dashboard
    # is not registered there and still needs to be watched for going stale,
    # so observation_freshness lets the registry name the column directly.
    date_column: str | None = None


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    outputs: tuple[OutputSpec, ...]


@dataclass(frozen=True)
class PipelineSpec:
    pipeline_id: str
    workflow: str
    cadence: dict[str, Any]
    criticality: str
    jobs: dict[str, JobSpec]


@dataclass(frozen=True)
class PipelineRegistry:
    version: int
    phase: int
    pipelines: dict[str, PipelineSpec]

    def job(self, pipeline_id: str, job_id: str) -> tuple[PipelineSpec, JobSpec]:
        try:
            pipeline = self.pipelines[pipeline_id]
        except KeyError as exc:
            raise RegistryError(f"Unknown pipeline_id {pipeline_id!r}") from exc
        try:
            return pipeline, pipeline.jobs[job_id]
        except KeyError as exc:
            raise RegistryError(
                f"Pipeline {pipeline_id!r} has no job {job_id!r}"
            ) from exc


def load_registry(path: Path, *, repo_root: Path) -> PipelineRegistry:
    try:
        payload = yaml.load(
            path.read_text(encoding="utf-8"),
            Loader=_UniqueKeyLoader,
        )
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"Cannot load pipeline registry {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RegistryError("Pipeline registry root must be a mapping")
    if payload.get("version") != 1:
        raise RegistryError(f"Unsupported registry version {payload.get('version')!r}")
    phase = payload.get("phase")
    if isinstance(phase, bool) or not isinstance(phase, int) or phase < 0:
        raise RegistryError(f"Registry phase must be a non-negative integer: {phase!r}")
    raw_pipelines = payload.get("pipelines")
    if not isinstance(raw_pipelines, dict) or not raw_pipelines:
        raise RegistryError("Pipeline registry must contain a non-empty pipelines map")

    dataset_registry: dict[str, Any] | None = None
    pipelines: dict[str, PipelineSpec] = {}
    for pipeline_id, raw_pipeline in raw_pipelines.items():
        if not isinstance(raw_pipeline, dict):
            raise RegistryError(f"Pipeline {pipeline_id!r} must be a mapping")
        workflow = str(raw_pipeline.get("workflow", "")).strip()
        workflow_path = repo_root / ".github" / "workflows" / workflow
        if not workflow or not workflow_path.is_file():
            raise RegistryError(
                f"Pipeline {pipeline_id!r} references missing workflow {workflow!r}"
            )
        cadence = _validate_cadence(
            raw_pipeline.get("cadence"),
            pipeline_id=str(pipeline_id),
        )
        criticality = str(raw_pipeline.get("criticality", "")).strip()
        if criticality not in {"low", "medium", "high"}:
            raise RegistryError(
                f"Pipeline {pipeline_id!r} has invalid criticality {criticality!r}"
            )

        raw_jobs = raw_pipeline.get("jobs")
        if not isinstance(raw_jobs, dict) or not raw_jobs:
            raise RegistryError(f"Pipeline {pipeline_id!r} has no jobs")
        jobs: dict[str, JobSpec] = {}
        for job_id, raw_job in raw_jobs.items():
            if not isinstance(raw_job, dict):
                raise RegistryError(
                    f"Pipeline {pipeline_id!r} job {job_id!r} must be a mapping"
                )
            raw_outputs = raw_job.get("outputs")
            if not isinstance(raw_outputs, list) or not raw_outputs:
                raise RegistryError(
                    f"Pipeline {pipeline_id!r} job {job_id!r} has no outputs"
                )
            if any(
                isinstance(item, dict)
                and str(item.get("validator", "")).strip() == "dataset_contract"
                for item in raw_outputs
            ) and dataset_registry is None:
                dataset_registry = _dataset_registry(repo_root)
            outputs = tuple(
                _parse_output(
                    item,
                    pipeline_id=str(pipeline_id),
                    job_id=str(job_id),
                    dataset_registry=dataset_registry or {},
                )
                for item in raw_outputs
            )
            output_ids = [output.output_id for output in outputs]
            if len(output_ids) != len(set(output_ids)):
                raise RegistryError(
                    f"Pipeline {pipeline_id!r} job {job_id!r} has duplicate output IDs"
                )
            jobs[str(job_id)] = JobSpec(job_id=str(job_id), outputs=outputs)

        pipelines[str(pipeline_id)] = PipelineSpec(
            pipeline_id=str(pipeline_id),
            workflow=workflow,
            cadence=cadence,
            criticality=criticality,
            jobs=jobs,
        )

    return PipelineRegistry(
        version=1,
        phase=phase,
        pipelines=pipelines,
    )


def _parse_output(
    payload: Any,
    *,
    pipeline_id: str,
    job_id: str,
    dataset_registry: dict[str, Any],
) -> OutputSpec:
    if not isinstance(payload, dict):
        raise RegistryError(
            f"Pipeline {pipeline_id!r} job {job_id!r} output must be a mapping"
        )
    output_id = str(payload.get("id", "")).strip()
    path = str(payload.get("path", "")).strip()
    if not output_id:
        raise RegistryError(f"Pipeline {pipeline_id!r} job {job_id!r} output has no id")
    _validate_relative_path(path, label=f"Output {output_id!r}")

    validator = str(payload.get("validator", "")).strip()
    allowed = {"file", "dataset_contract", "asia_markets_freshness", "observation_freshness"}
    if validator not in allowed:
        raise RegistryError(
            f"Output {output_id!r} uses unsupported validator {validator!r}"
        )
    dataset_id = _optional_string(payload.get("dataset_id"))
    if validator == "dataset_contract":
        if not dataset_id or dataset_id not in dataset_registry:
            raise RegistryError(
                f"Output {output_id!r} references unknown dataset contract {dataset_id!r}"
            )

    date_column = _optional_string(payload.get("date_column"))
    if validator == "observation_freshness" and not date_column:
        raise RegistryError(
            f"Output {output_id!r} requires date_column for observation freshness"
        )

    artifact_root = _optional_string(payload.get("artifact_root"))
    if artifact_root is not None:
        _validate_relative_path(artifact_root, label=f"Output {output_id!r} artifact_root")

    freshness = payload.get("freshness", {})
    if not isinstance(freshness, dict):
        raise RegistryError(f"Output {output_id!r} freshness must be a mapping")
    _validate_freshness(
        freshness,
        output_id=output_id,
        required=validator in ("dataset_contract", "observation_freshness"),
    )
    if validator == "asia_markets_freshness" and artifact_root is None:
        raise RegistryError(
            f"Output {output_id!r} requires artifact_root for Asia Markets freshness"
        )

    return OutputSpec(
        output_id=output_id,
        path=path,
        required=bool(payload.get("required", True)),
        validator=validator,
        dataset_id=dataset_id,
        artifact_root=artifact_root,
        freshness=dict(freshness),
        date_column=date_column,
    )


def _validate_relative_path(value: str, *, label: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise RegistryError(f"{label} path must be repository-relative: {value!r}")


def _validate_cadence(payload: Any, *, pipeline_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RegistryError(f"Pipeline {pipeline_id!r} cadence must be a mapping")
    kind = str(payload.get("kind", "")).strip()
    # "weekly" shares daily's shape -- a fixed expected gap between runs -- and
    # differs only in size, so it validates the same field rather than earning
    # a branch of its own.
    if kind in ("daily", "weekly"):
        interval = payload.get("expected_interval_hours")
        if (
            isinstance(interval, bool)
            or not isinstance(interval, (int, float))
            or interval <= 0
        ):
            raise RegistryError(
                f"Pipeline {pipeline_id!r} expected_interval_hours must be positive"
            )
    elif kind == "monthly_windows":
        windows = payload.get("schedule_windows")
        if not isinstance(windows, list) or not windows:
            raise RegistryError(
                f"Pipeline {pipeline_id!r} monthly cadence needs schedule_windows"
            )
        purposes: set[str] = set()
        for window in windows:
            if not isinstance(window, dict):
                raise RegistryError(
                    f"Pipeline {pipeline_id!r} schedule window must be a mapping"
                )
            days = str(window.get("days", "")).strip()
            match = re.fullmatch(r"(\d{1,2})(?:-(\d{1,2}))?", days)
            start = int(match.group(1)) if match else 0
            end = int(match.group(2) or start) if match else 0
            if not match or not 1 <= start <= end <= 31:
                raise RegistryError(
                    f"Pipeline {pipeline_id!r} has impossible schedule days {days!r}"
                )
            purpose = str(window.get("purpose", "")).strip()
            if not purpose or purpose in purposes:
                raise RegistryError(
                    f"Pipeline {pipeline_id!r} has missing or duplicate window purpose"
                )
            purposes.add(purpose)
    else:
        raise RegistryError(
            f"Pipeline {pipeline_id!r} has unsupported cadence kind {kind!r}"
        )
    return dict(payload)


def _validate_freshness(
    payload: dict[str, Any],
    *,
    output_id: str,
    required: bool,
) -> None:
    mode = str(payload.get("mode", "")).strip()
    if not mode:
        if required:
            raise RegistryError(
                f"Output {output_id!r} requires an explicit freshness mode"
            )
        return
    if mode == "max_age_days":
        value = payload.get("max_age_days")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value <= 0
        ):
            raise RegistryError(
                f"Output {output_id!r} max_age_days must be positive"
            )
    elif mode == "monthly_release_lag":
        value = payload.get("release_lag_days")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RegistryError(
                f"Output {output_id!r} release_lag_days must be non-negative"
            )
    else:
        raise RegistryError(
            f"Output {output_id!r} uses unsupported freshness mode {mode!r}"
        )


def _dataset_registry(repo_root: Path) -> dict[str, Any]:
    root = str(repo_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from dashboard.data import DATASET_REGISTRY
    except Exception as exc:
        raise RegistryError(f"Cannot load dashboard dataset contracts: {exc}") from exc
    return DATASET_REGISTRY


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
