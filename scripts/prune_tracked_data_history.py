#!/usr/bin/env python3
"""Keep only a recent window of each partitioned dataset tracked in git.

The remote does not need every partition ever collected -- a fresh clone
mostly wants the working window, and research that needs the deep history
runs locally. This script narrows what git tracks while leaving every
partition byte-for-byte in place on disk:

    data/normalized/<ds>/2024-01-05.parquet   on disk, NOT tracked
    data/normalized/<ds>/2025-11-20.parquet   on disk, tracked
    data/normalized/<ds>/2026-09-08.parquet   on disk, tracked

It does this with ``git rm --cached`` plus a managed .gitignore block, so
readers that glob the partition directory keep working unchanged.

WHAT THIS DOES NOT DO
---------------------
It does not shrink ``.git``. Blobs already written to history stay in the
pack forever; retention only stops the pack from growing further and slims
a fresh checkout. Reclaiming the ~656 MB of parquet already in history needs
``git filter-repo`` and a force-push, which rewrites every commit SHA and
invalidates all other clones and worktrees. That is a separate, deliberate
decision -- not something this script does behind your back.

BEFORE YOU RUN THIS WITH --apply
--------------------------------
Partitions dropped from tracking exist on exactly ONE disk afterwards. Much
of that data was collected incrementally by scheduled CI and cannot be
re-fetched -- most upstream APIs do not serve deep history. Archive first
(external drive, object storage, or a bare mirror), then pass
``--i-have-a-backup`` to confirm. The flag exists so this is a decision you
make once, consciously, rather than a default that quietly deletes your
only copy of two years of collection.

Usage:
    python3 scripts/prune_tracked_data_history.py                       # dry run, 2y
    python3 scripts/prune_tracked_data_history.py --keep-years 3        # dry run
    python3 scripts/prune_tracked_data_history.py --dataset data/normalized/ai_hiring
    python3 scripts/prune_tracked_data_history.py --apply --i-have-a-backup
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GITIGNORE = REPO_ROOT / ".gitignore"

BEGIN_MARK = "# >>> BEGIN retention window -- managed by scripts/prune_tracked_data_history.py"
END_MARK = "# <<< END retention window"

# Only ever touch paths under data/. The guard against a typo'd --dataset
# pointing at src/ or apps/ and untracking source code.
ALLOWED_ROOT = Path("data")

PARTITION_RE = re.compile(r"^(?P<year>\d{4})-\d{2}(-\d{2})?\.(parquet|csv|json)$")
MB = 1024 * 1024


class PruneError(RuntimeError):
    """Raised when the request is unsafe or the repository cannot be read."""


@dataclass
class Dataset:
    directory: str                      # repo-relative
    tracked_by_year: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    @property
    def years(self) -> list[str]:
        return sorted(self.tracked_by_year)

    def paths_before(self, cutoff_year: int) -> list[str]:
        return [
            path
            for year, paths in self.tracked_by_year.items()
            if int(year) < cutoff_year
            for path in paths
        ]

    def years_kept(self, cutoff_year: int) -> list[str]:
        return [y for y in self.years if int(y) >= cutoff_year]


def _git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise PruneError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def discover(dataset_filter: str | None) -> list[Dataset]:
    """Group every tracked, date-named partition by its parent directory."""
    datasets: dict[str, Dataset] = {}
    for rel in _git("ls-files", "-z").split("\0"):
        if not rel:
            continue
        path = Path(rel)
        if ALLOWED_ROOT not in path.parents:
            continue
        match = PARTITION_RE.match(path.name)
        if not match:
            continue
        directory = str(path.parent)
        if dataset_filter and not directory.startswith(dataset_filter.rstrip("/")):
            continue
        dataset = datasets.setdefault(directory, Dataset(directory))
        dataset.tracked_by_year[match.group("year")].append(rel)
    return [datasets[key] for key in sorted(datasets)]


def _size_mb(paths: list[str]) -> float:
    total = 0
    for rel in paths:
        absolute = REPO_ROOT / rel
        if absolute.is_file():
            total += absolute.stat().st_size
    return total / MB


def render_ignore_block(datasets: list[Dataset], cutoff_year: int) -> str:
    lines = [
        BEGIN_MARK,
        "# Partitions older than the retention window stay on local disk but are",
        "# not tracked. Regenerate after a refresh with:",
        "#   python3 scripts/prune_tracked_data_history.py --apply --i-have-a-backup",
    ]
    for dataset in datasets:
        kept = dataset.years_kept(cutoff_year)
        if not kept:
            continue
        lines.append(f"{dataset.directory}/[0-9][0-9][0-9][0-9]-*")
        for year in kept:
            lines.append(f"!{dataset.directory}/{year}-*")
    lines.append(END_MARK)
    return "\n".join(lines) + "\n"


def write_ignore_block(block: str) -> None:
    text = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.exists() else ""
    if BEGIN_MARK in text and END_MARK in text:
        head, _, rest = text.partition(BEGIN_MARK)
        _, _, tail = rest.partition(END_MARK)
        text = head.rstrip("\n") + "\n" + tail.lstrip("\n")
    if text and not text.endswith("\n"):
        text += "\n"
    GITIGNORE.write_text(text + "\n" + block, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep-years", type=int, default=2,
                        help="calendar years to keep tracked, including the current one (default 2)")
    parser.add_argument("--dataset", help="limit to one directory prefix under data/")
    parser.add_argument("--apply", action="store_true", help="actually untrack (default is a dry run)")
    parser.add_argument("--i-have-a-backup", action="store_true",
                        help="confirm the out-of-window partitions are archived somewhere other than this disk")
    args = parser.parse_args()

    if args.keep_years < 1:
        print("error: --keep-years must be at least 1", file=sys.stderr)
        return 2
    if args.dataset and not args.dataset.startswith("data/"):
        print("error: --dataset must be under data/", file=sys.stderr)
        return 2

    cutoff_year = date.today().year - args.keep_years + 1

    try:
        datasets = discover(args.dataset)
    except PruneError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not datasets:
        print("no tracked date-partitioned datasets found"
              + (f" under {args.dataset}" if args.dataset else ""))
        return 0

    print(f"retention window: {cutoff_year} and newer  (--keep-years {args.keep_years})\n")

    to_remove: list[str] = []
    for dataset in datasets:
        stale = dataset.paths_before(cutoff_year)
        kept = dataset.years_kept(cutoff_year)
        tracked_total = sum(len(v) for v in dataset.tracked_by_year.values())
        if not stale:
            print(f"  ok      {dataset.directory}")
            print(f"          {tracked_total} partitions, all within window ({', '.join(kept) or 'none'})")
            continue
        to_remove.extend(stale)
        print(f"  PRUNE   {dataset.directory}")
        print(f"          untrack {len(stale)} of {tracked_total} partitions "
              f"({_size_mb(stale):.1f} MB) -- years {', '.join(y for y in dataset.years if int(y) < cutoff_year)}")
        print(f"          keep    {', '.join(kept) or 'none'}  (files stay on disk)")

    if not to_remove:
        print("\nnothing to prune.")
        return 0

    print(f"\ntotal: {len(to_remove)} partitions, {_size_mb(to_remove):.1f} MB would leave the tracked tree")
    print("note: this caps future growth and slims a fresh clone. It does NOT shrink")
    print("      .git -- existing blobs stay in the pack until a history rewrite.")

    if not args.apply:
        print("\ndry run. Re-run with --apply --i-have-a-backup to act.")
        return 0

    if not args.i_have_a_backup:
        print("\nrefusing to apply: pass --i-have-a-backup once the out-of-window partitions",
              "\nare archived off this disk. Most of this data cannot be re-fetched upstream.",
              file=sys.stderr)
        return 2

    # --cached keeps every file on disk; only the index entry goes away.
    for start in range(0, len(to_remove), 500):
        _git("rm", "--cached", "--quiet", "--", *to_remove[start:start + 500])
    write_ignore_block(render_ignore_block(datasets, cutoff_year))

    print(f"\nuntracked {len(to_remove)} partitions and refreshed the .gitignore block.")
    print("Files are untouched on disk. Review with: git status && git diff --cached --stat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
