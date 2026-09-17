"""Every partitioned dataset's directory must be committable.

A dataset stored as one parquet per observation date lives in a directory.
.gitignore excludes `data/normalized/<domain>/*` and re-includes `*.parquet`,
which reaches files but not directories -- so without an explicit rule for the
directory, git ignores every partition.

That is silent and destructive rather than noisy: the daily job deletes the
tracked single file, commits the deletion, writes the partitions, and git
discards them. The dataset vanishes from the repository and the run reports
success. openrouter_task_spend was lost from main exactly this way on
2026-09-12, recovered from history the same day.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def _partitioned_dataset_dirs() -> list[tuple[str, Path]]:
    """(dataset_id, directory) for every dataset written as date partitions."""
    from ai_hiring_data.storage import PARTITION_COLUMNS as HIRING
    from openrouter_data.storage import PARTITION_COLUMNS as OPENROUTER
    from provider_adoption_data.storage import PARTITION_COLUMNS as ADOPTION
    from research_data.marts import PARTITIONED_MARTS

    normalized = REPO_ROOT / "data" / "normalized"
    entries: list[tuple[str, Path]] = []
    for dataset_id in ADOPTION:
        entries.append((dataset_id, normalized / "provider_adoption" / dataset_id))
    for dataset_id in OPENROUTER:
        entries.append((dataset_id, normalized / "openrouter" / dataset_id))
    for dataset_id in HIRING:
        entries.append((dataset_id, normalized / "ai_hiring" / dataset_id))
    for mart_name in PARTITIONED_MARTS:
        entries.append((mart_name, normalized / "marts" / mart_name))
    entries.append(("eia_grid_hourly", normalized / "eia_energy" / "eia_grid_hourly"))
    return entries


@pytest.mark.parametrize(
    ("dataset_id", "directory"),
    _partitioned_dataset_dirs(),
    ids=[dataset_id for dataset_id, _ in _partitioned_dataset_dirs()],
)
def test_partition_files_are_not_gitignored(dataset_id: str, directory: Path) -> None:
    candidate = directory / "2026-01-02.parquet"
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(candidate.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    # check-ignore exits 0 when the path IS ignored.
    assert result.returncode != 0, (
        f"{dataset_id} writes date partitions into {directory.relative_to(REPO_ROOT)}/, "
        "but .gitignore excludes them. The refresh job will delete the tracked single "
        "file and the partitions it writes will be silently discarded. Add "
        f"'!{directory.relative_to(REPO_ROOT)}/' and '!{directory.relative_to(REPO_ROOT)}/*.parquet'."
    )
