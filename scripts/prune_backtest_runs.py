#!/usr/bin/env python3
"""Prune old run directories under ``data/registries/runs/``.

The unified backtest engine (``src/common/backtest``) writes one immutable
run directory per invocation under ``data/registries/runs/<engine_version>-
<hash>/``. Every run is untracked by git (see ``.gitignore``) and, left
alone, accumulates without bound — dozens of development-iteration snapshots
each holding a full parquet/JSON artifact set.

This script deletes the oldest run directories while keeping:

  * the N most recent runs (by the ``created_at`` timestamp in each run's
    ``manifest.json``, written by ``src/common/backtest/storage.py``), and
  * the run currently pointed at by ``data/registries/asia_backtest_latest.json``,
    no matter how old it is or whether it falls inside the keep window.

Dry-run is the default. Nothing is deleted unless ``--apply`` is passed.

Usage:
    python3 scripts/prune_backtest_runs.py                # dry run, keep=1
    python3 scripts/prune_backtest_runs.py --keep 3        # dry run, keep=3
    python3 scripts/prune_backtest_runs.py --keep 1 --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_ROOT = REPO_ROOT / "data" / "registries" / "runs"
DEFAULT_LATEST_POINTER = REPO_ROOT / "data" / "registries" / "asia_backtest_latest.json"

# The runs root must always resolve to a path ending in this relative
# suffix. This is the guard against accidentally pointing the script at an
# unrelated directory (e.g. via a typo'd --runs-root) and deleting it.
_EXPECTED_SUFFIX = Path("data") / "registries" / "runs"


class PruneError(RuntimeError):
    """Raised for any condition that should abort without deleting anything."""


@dataclass(frozen=True)
class RunInfo:
    path: Path
    run_id: str
    created_at: str | None  # ISO timestamp string, or None if unavailable
    size_bytes: int
    file_count: int


def _validate_runs_root(runs_root: Path) -> Path:
    """Refuse to operate on anything that isn't a data/registries/runs path."""
    resolved = runs_root.resolve()
    parts = resolved.parts
    suffix_parts = _EXPECTED_SUFFIX.parts
    if len(parts) < len(suffix_parts) or tuple(parts[-len(suffix_parts):]) != suffix_parts:
        raise PruneError(
            f"refusing to operate on {resolved}: path does not end in "
            f"'{_EXPECTED_SUFFIX}' — this script only prunes backtest run directories"
        )
    return resolved


def _load_latest_run_id(latest_pointer: Path) -> str:
    if not latest_pointer.exists():
        raise PruneError(f"latest-run pointer not found: {latest_pointer}")
    try:
        payload = json.loads(latest_pointer.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PruneError(f"latest-run pointer is not valid JSON: {latest_pointer} ({exc})") from exc
    run_id = payload.get("run_id")
    if not run_id or not isinstance(run_id, str):
        raise PruneError(f"latest-run pointer is missing a valid 'run_id' field: {latest_pointer}")
    return run_id


def _dir_size(path: Path) -> tuple[int, int]:
    total_bytes = 0
    file_count = 0
    for item in path.rglob("*"):
        if item.is_file():
            total_bytes += item.stat().st_size
            file_count += 1
    return total_bytes, file_count


def _discover_runs(runs_root: Path) -> list[RunInfo]:
    runs: list[RunInfo] = []
    if not runs_root.exists():
        return runs
    for entry in sorted(runs_root.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "manifest.json"
        created_at: str | None = None
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                created_at = manifest.get("created_at")
            except json.JSONDecodeError:
                created_at = None
        size_bytes, file_count = _dir_size(entry)
        runs.append(
            RunInfo(
                path=entry,
                run_id=entry.name,
                created_at=created_at,
                size_bytes=size_bytes,
                file_count=file_count,
            )
        )
    return runs


def select_runs_to_delete(
    runs: Iterable[RunInfo],
    *,
    keep: int,
    protected_run_id: str,
) -> tuple[list[RunInfo], list[RunInfo]]:
    """Return (keep_list, delete_list).

    Runs with no readable ``created_at`` are always protected (kept) —
    we refuse to guess their recency rather than risk deleting something
    we can't order correctly.
    """
    runs = list(runs)
    undated = [r for r in runs if r.created_at is None and r.run_id != protected_run_id]
    dated = [r for r in runs if r.created_at is not None]

    dated_sorted = sorted(dated, key=lambda r: r.created_at, reverse=True)

    keep_set: dict[str, RunInfo] = {}
    for run in dated_sorted[:keep]:
        keep_set[run.run_id] = run

    protected = next((r for r in runs if r.run_id == protected_run_id), None)
    if protected is not None:
        keep_set[protected.run_id] = protected

    for run in undated:
        keep_set[run.run_id] = run

    keep_list = [r for r in runs if r.run_id in keep_set]
    delete_list = [r for r in runs if r.run_id not in keep_set]
    return keep_list, delete_list


def _human_mb(num_bytes: int) -> str:
    return f"{num_bytes / 1_048_576:.2f} MB"


def run_prune(
    *,
    runs_root: Path,
    latest_pointer: Path,
    keep: int,
    apply: bool,
) -> int:
    validated_root = _validate_runs_root(runs_root)
    protected_run_id = _load_latest_run_id(latest_pointer)

    runs = _discover_runs(validated_root)
    if not runs:
        print(f"No run directories found under {validated_root}. Nothing to do.")
        return 0

    keep_list, delete_list = select_runs_to_delete(runs, keep=keep, protected_run_id=protected_run_id)

    total_before_bytes = sum(r.size_bytes for r in runs)
    total_before_files = sum(r.file_count for r in runs)
    reclaim_bytes = sum(r.size_bytes for r in delete_list)
    reclaim_files = sum(r.file_count for r in delete_list)

    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] runs root: {validated_root}")
    print(f"[{mode}] latest.json run_id (protected): {protected_run_id}")
    print(f"[{mode}] keep = {keep} most recent run(s) by manifest created_at")
    print()
    print(f"Found {len(runs)} run directories, {total_before_files} files, {_human_mb(total_before_bytes)} total.")
    print()

    if delete_list:
        print(f"Would remove {len(delete_list)} run directories:" if not apply else f"Removing {len(delete_list)} run directories:")
        for run in sorted(delete_list, key=lambda r: r.created_at or ""):
            print(f"  - {run.run_id}  created_at={run.created_at}  {run.file_count} files  {_human_mb(run.size_bytes)}")
        print()
        print(f"Reclaimable: {reclaim_files} files, {_human_mb(reclaim_bytes)}")
    else:
        print("Nothing to remove — all runs are within the keep window or protected.")

    print()
    print(f"Retaining {len(keep_list)} run directories:")
    for run in sorted(keep_list, key=lambda r: r.created_at or "", reverse=True):
        tag = " (latest.json)" if run.run_id == protected_run_id else ""
        print(f"  - {run.run_id}  created_at={run.created_at}{tag}")

    if not apply:
        print()
        print("Dry run only — no files were deleted. Pass --apply to actually delete.")
        return 0

    for run in delete_list:
        shutil.rmtree(run.path)

    print()
    print(f"Deleted {len(delete_list)} run directories, reclaimed {_human_mb(reclaim_bytes)}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=DEFAULT_RUNS_ROOT,
        help="Path to data/registries/runs (default: repo's data/registries/runs)",
    )
    parser.add_argument(
        "--latest-pointer",
        type=Path,
        default=DEFAULT_LATEST_POINTER,
        help="Path to asia_backtest_latest.json (default: repo's data/registries/asia_backtest_latest.json)",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=1,
        help="Number of most recent runs to keep, by manifest created_at (default: 1)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without this flag the script only prints what it would do.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.keep < 0:
        print("error: --keep must be >= 0", file=sys.stderr)
        return 2
    try:
        return run_prune(
            runs_root=args.runs_root,
            latest_pointer=args.latest_pointer,
            keep=args.keep,
            apply=args.apply,
        )
    except PruneError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
