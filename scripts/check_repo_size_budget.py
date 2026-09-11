#!/usr/bin/env python3
"""Guard the repository against the data-churn bloat that already cost ~1 GB.

Measured 2026-09-11 on ``main``: the pack was 991 MiB while all tracked
content was only 268 MB and all Python source was 8 MB. Parquet accounted
for 656 MB -- 66% of history -- across 9,103 blobs. Parquet is already
compressed, so git cannot delta two versions of the same table: every daily
refresh of a tracked ``.parquet`` stores a complete second copy forever.

``github_repo_rollup_daily.parquet`` alone burned 131 MB of history before
commit ccc7228d split it into date partitions. That fix is the pattern this
script pushes everyone toward: a partitioned dataset only ever *adds* a
small file, so history grows linearly with time instead of quadratically
with (file size x commit count).

Two modes:

* ``--staged`` (pre-commit): inspect only what is about to be committed.
  Fast enough for a hook; this is what stops a bad file at the door.
* ``--all`` (CI / on demand): inspect every tracked file and print the
  budget report against the ceilings in THRESHOLDS below.

Exit status is 1 when a hard limit is breached, 0 otherwise. Warnings never
fail the run -- they are advisory, because a legitimately large one-off file
should not block a commit at 2am.

Usage:
    python3 scripts/check_repo_size_budget.py --staged     # pre-commit hook
    python3 scripts/check_repo_size_budget.py --all        # full report
    python3 scripts/check_repo_size_budget.py --all --max-file-mb 10
    python3 scripts/check_repo_size_budget.py --install-hook
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Hard block at 100 MiB is GitHub's own push rejection. We fail well before
# it: a tracked file over FAIL_FILE_MB is nearly always a dataset that wants
# partitioning, not a file that genuinely belongs in git at that size.
FAIL_FILE_MB = 20.0
GITHUB_REJECT_MB = 100.0
GITHUB_WARN_MB = 50.0

# A monolithic table in data/normalized/ above this size is the shape that
# produced the 656 MB of parquet history. Partition it by date instead.
WARN_MONOLITH_MB = 1.0

# Repo-level ceilings. GitHub recommends staying under 1 GB and starts
# contacting you past ~5 GB.
WARN_PACK_GB = 2.0
FAIL_PACK_GB = 5.0

# Streamlit Community Cloud gives each app 1 GB of RAM. Measured expansion
# from JSON on disk to live Python objects is ~10x, on top of a 132 MB
# import baseline for pandas+pyarrow+plotly+streamlit.
ARTIFACT_ROOT = Path("apps/asia-markets-dashboard/.generated")
JSON_TO_RAM_FACTOR = 10.0
STREAMLIT_BASELINE_MB = 132.5
STREAMLIT_LIMIT_MB = 1024.0
WARN_ARTIFACT_TOTAL_MB = 80.0

MB = 1024 * 1024
DATA_TABLE_SUFFIXES = {".parquet", ".csv"}

# This repo partitions immutable data two ways, and both are append-only:
#   1. date-named files      data/normalized/<ds>/2026-09-08.parquet
#   2. run-id directories    data/normalized/<ds>/20260909T135011-1954c6c1/<file>
# Either shape means a refresh adds a new object instead of rewriting an
# existing one, so git stores each version exactly once.
PARTITION_FILE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?\.(parquet|csv|json)$")
PARTITION_DIR_RE = re.compile(r"^\d{8}T\d{6}-[0-9a-f]+$|^\d{4}-\d{2}(-\d{2})?$")


class CheckError(RuntimeError):
    """Raised when the repository cannot be inspected at all."""


@dataclass(frozen=True)
class Finding:
    level: str  # "fail" | "warn"
    path: str
    size_mb: float
    message: str


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise CheckError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _staged_paths() -> list[str]:
    # Added/copied/modified only: a deletion cannot grow the repository.
    out = _git("diff", "--cached", "--name-only", "--diff-filter=ACM", "-z")
    return [p for p in out.split("\0") if p]


def _tracked_paths() -> list[str]:
    out = _git("ls-files", "-z")
    return [p for p in out.split("\0") if p]


def _is_partitioned(path: Path) -> bool:
    """True when the file is one immutable partition rather than a live table."""
    if PARTITION_FILE_RE.match(path.name):
        return True
    return any(PARTITION_DIR_RE.match(parent.name) for parent in path.parents)


def inspect_paths(paths: list[str], *, max_file_mb: float) -> list[Finding]:
    findings: list[Finding] = []
    for rel in paths:
        absolute = REPO_ROOT / rel
        if not absolute.is_file():
            continue  # deleted, or a submodule entry
        size_mb = absolute.stat().st_size / MB
        path = Path(rel)

        if size_mb >= GITHUB_REJECT_MB:
            findings.append(Finding(
                "fail", rel, size_mb,
                f"exceeds GitHub's {GITHUB_REJECT_MB:.0f} MiB hard limit -- the push will be rejected",
            ))
        elif size_mb >= max_file_mb:
            findings.append(Finding(
                "fail", rel, size_mb,
                f"over the {max_file_mb:.0f} MB budget"
                + (f" (GitHub warns at {GITHUB_WARN_MB:.0f} MiB)" if size_mb >= GITHUB_WARN_MB else ""),
            ))
        elif (
            path.suffix in DATA_TABLE_SUFFIXES
            and size_mb >= WARN_MONOLITH_MB
            and rel.startswith("data/")
            and not _is_partitioned(path)
        ):
            findings.append(Finding(
                "warn", rel, size_mb,
                f"monolithic table rewritten in place -- each commit stores another {size_mb:.1f} MB; "
                "partition it by date (see commit ccc7228d)",
            ))
    return findings


def pack_size_gb() -> float | None:
    try:
        out = _git("count-objects", "-v")
    except CheckError:
        return None
    for line in out.splitlines():
        if line.startswith("size-pack:"):
            return int(line.split(":", 1)[1].strip()) / (1024 * 1024)  # KiB -> GiB
    return None


def streamlit_report() -> tuple[float, float] | None:
    """Return (artifacts_mb_on_disk, projected_peak_ram_mb)."""
    root = REPO_ROOT / ARTIFACT_ROOT
    if not root.is_dir():
        return None
    total_mb = sum(f.stat().st_size for f in root.glob("*.json") if f.is_file()) / MB
    projected = STREAMLIT_BASELINE_MB + total_mb * JSON_TO_RAM_FACTOR
    return total_mb, projected


def _print_findings(findings: list[Finding]) -> int:
    fails = [f for f in findings if f.level == "fail"]
    warns = [f for f in findings if f.level == "warn"]

    for finding in sorted(fails, key=lambda f: -f.size_mb):
        print(f"  FAIL  {finding.size_mb:8.1f} MB  {finding.path}\n        {finding.message}")
    for finding in sorted(warns, key=lambda f: -f.size_mb)[:15]:
        print(f"  warn  {finding.size_mb:8.1f} MB  {finding.path}\n        {finding.message}")
    if len(warns) > 15:
        print(f"  warn  ... and {len(warns) - 15} more monolithic tables")
    return len(fails)


def run_staged(max_file_mb: float) -> int:
    findings = inspect_paths(_staged_paths(), max_file_mb=max_file_mb)
    if not findings:
        return 0
    print("repo size budget:")
    fail_count = _print_findings(findings)
    if fail_count:
        print(
            "\nCommit blocked. Either partition the dataset by date, add it to .gitignore,\n"
            "or re-run with: git commit --no-verify"
        )
    return 1 if fail_count else 0


def run_all(max_file_mb: float) -> int:
    tracked = _tracked_paths()
    total_mb = sum(
        (REPO_ROOT / p).stat().st_size
        for p in tracked
        if (REPO_ROOT / p).is_file()
    ) / MB

    print("=== repo size budget ===")
    print(f"  tracked content    {total_mb:8.1f} MB   ({len(tracked):,} files)")

    pack_gb = pack_size_gb()
    status = 0
    if pack_gb is not None:
        flag = ""
        if pack_gb >= FAIL_PACK_GB:
            flag, status = "  <-- OVER LIMIT", 1
        elif pack_gb >= WARN_PACK_GB:
            flag = "  <-- rewrite history soon"
        print(f"  .git pack          {pack_gb:8.2f} GB   (warn {WARN_PACK_GB:.0f} GB / fail {FAIL_PACK_GB:.0f} GB){flag}")

    streamlit = streamlit_report()
    if streamlit:
        artifacts_mb, projected_mb = streamlit
        pct = projected_mb / STREAMLIT_LIMIT_MB * 100
        flag = "  <-- over 1 GB Streamlit limit" if projected_mb >= STREAMLIT_LIMIT_MB else ""
        if artifacts_mb >= WARN_ARTIFACT_TOTAL_MB and not flag:
            flag = "  <-- approaching the limit"
        print(f"  streamlit artifacts{artifacts_mb:8.1f} MB   -> ~{projected_mb:.0f} MB RAM ({pct:.0f}% of 1 GB){flag}")

    findings = inspect_paths(tracked, max_file_mb=max_file_mb)
    if findings:
        print("\n=== findings ===")
        if _print_findings(findings):
            status = 1
    else:
        print("\n  no files over budget")
    return status


HOOK_BODY = """#!/bin/sh
# Installed by scripts/check_repo_size_budget.py --install-hook
exec python3 "$(git rev-parse --show-toplevel)/scripts/check_repo_size_budget.py" --staged
"""


def install_hook() -> int:
    hook_path = REPO_ROOT / ".git" / "hooks" / "pre-commit"
    if hook_path.exists():
        print(f"refusing to overwrite existing hook: {hook_path}")
        return 1
    hook_path.write_text(HOOK_BODY, encoding="utf-8")
    hook_path.chmod(0o755)
    print(f"installed pre-commit hook at {hook_path}")
    print("bypass a single commit with: git commit --no-verify")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="check staged files only (pre-commit)")
    mode.add_argument("--all", action="store_true", help="check every tracked file and print the budget report")
    mode.add_argument("--install-hook", action="store_true", help="install this script as a pre-commit hook")
    parser.add_argument("--max-file-mb", type=float, default=FAIL_FILE_MB, help=f"per-file budget (default {FAIL_FILE_MB:.0f})")
    args = parser.parse_args()

    try:
        if args.install_hook:
            return install_hook()
        if args.staged:
            return run_staged(args.max_file_mb)
        return run_all(args.max_file_mb)
    except CheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
