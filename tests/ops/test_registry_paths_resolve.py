"""Every output the control tower watches must exist in the repository.

A registry entry is a path written down once and then left alone, so it goes
stale silently. When ``daily_provider_economics`` migrated to one parquet per
usage month, its registry entry still named the single file; the finalizer saw
a required output that did not exist and reported FAILED_ACTIONABLE -- the
loudest state it has -- on a pipeline that had in fact run perfectly. Nothing
asserted the registry against the repository, so the only signal was two
finalizer tests failing for a reason that read like a finalizer bug.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from common.partitioned_parquet import resolve_dataset_path
from ops_control.registry import load_registry


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config" / "ops" / "pipelines.yaml"


def _required_outputs() -> list[tuple[str, str, str]]:
    registry = load_registry(REGISTRY, repo_root=ROOT)
    return [
        (pipeline_id, output.output_id, output.path)
        for pipeline_id, pipeline in registry.pipelines.items()
        for job in pipeline.jobs.values()
        for output in job.outputs
        if output.required
    ]


@pytest.mark.parametrize(
    ("pipeline_id", "output_id", "relative_path"),
    _required_outputs(),
    ids=lambda value: str(value),
)
def test_every_required_registry_output_exists(
    pipeline_id: str, output_id: str, relative_path: str
) -> None:
    path = ROOT / relative_path
    # Resolved, not `is_file()`: a partitioned dataset is a directory, and the
    # point of this guard is that the registry and the layout agree.
    resolved = resolve_dataset_path(path) if path.suffix != ".json" else None
    assert resolved is not None or path.is_file(), (
        f"{pipeline_id}.{output_id} points at {relative_path}, which does not "
        "exist as a file or as a directory of parquet partitions. Either the "
        "dataset moved and the registry was not updated, or the producer has "
        "stopped writing it."
    )
