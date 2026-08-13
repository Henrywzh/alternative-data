#!/usr/bin/env python3
"""Pipeline runner for the unified Asia Markets backtest engine.

Stages (each must exit zero before the next runs):

1. ``scripts/mtr_farebox_revenue_backtest.py`` — regenerate the MTR source
   tables from the normalized official-actuals dataset (Step 4 migration:
   the script no longer owns the actual values).
2. ``scripts/build_asia_backtest_registry.py`` — Step 1 metadata contract.
3. ``scripts/build_mtr_walk_forward_oos.py`` — build the independent MTR
   chronological FY/H1 practical-OOS track and monthly forecast-only companion.
4. ``scripts/build_asia_backtest_long_form.py`` — Step 3 additive long form
   with dedup value assertions (hard gate).
5. Metrics are emitted by the long-form stage into the same immutable run;
   ``scripts/build_asia_backtest_metrics.py`` remains available for an
   explicit standalone rebuild but is not a second runner stage.
6. ``scripts/prune_backtest_runs.py`` — retire old ``data/registries/runs/``
   snapshots, run only after every stage above has succeeded. A failed build
   leaves the previous snapshot in place on purpose, so pruning never runs
   on a failed pipeline. The run pointed at by
   ``data/registries/asia_backtest_latest.json`` is always protected by the
   prune script itself, regardless of the keep window.

The engine is deliberately additive: it never rewrites a wide table consumed
by a dashboard and never changes a model calculation.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(script: str, extra: list[str] | None = None, *, required: bool = True) -> bool:
    command = [sys.executable, str(ROOT / script)] + (extra or [])
    print(f"\n=== {script} ===")
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode != 0:
        print(f"[backtest-engine] stage failed: {script} (exit {completed.returncode})")
        if required:
            return False
    return True


DEFAULT_KEEP_RUNS = 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the unified Asia Markets backtest engine")
    parser.add_argument("--skip-mtr", action="store_true", help="skip the MTR source rebuild")
    parser.add_argument("--mtr-live", action="store_true", help="pass --live to the MTR script")
    parser.add_argument(
        "--skip-prune",
        action="store_true",
        help="skip pruning old data/registries/runs/ snapshots after a successful build",
    )
    parser.add_argument(
        "--keep-runs",
        type=int,
        default=DEFAULT_KEEP_RUNS,
        help=f"number of most recent run snapshots to keep when pruning (default: {DEFAULT_KEEP_RUNS})",
    )
    args = parser.parse_args()

    stages: list[tuple[str, list[str] | None, bool]] = []
    if not args.skip_mtr:
        stages.append(("scripts/mtr_farebox_revenue_backtest.py", ["--live"] if args.mtr_live else None, True))
    stages.append(("scripts/build_mtr_walk_forward_oos.py", None, True))
    stages.append(("scripts/build_asia_backtest_registry.py", None, True))
    stages.append(("scripts/build_asia_backtest_long_form.py", None, True))

    for script, extra, required in stages:
        if not _run(script, extra, required=required):
            return 1

    print("\n[backtest-engine] all stages passed")

    # Pruning only ever runs here, after every required stage above has
    # already returned success -- a failed run is exactly when the previous
    # immutable snapshot under data/registries/runs/ must be left alone, so
    # this call must never be reachable from a non-zero return above.
    if args.skip_prune:
        print("[backtest-engine] prune stage skipped (--skip-prune)")
    else:
        prune_ok = _run(
            "scripts/prune_backtest_runs.py",
            ["--keep", str(args.keep_runs), "--apply"],
            required=False,
        )
        if not prune_ok:
            print("[backtest-engine] prune stage failed; old run directories were left in place")

    return 0


if __name__ == "__main__":
    sys.exit(main())
