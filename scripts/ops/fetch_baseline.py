#!/usr/bin/env python3
"""Fetch the most recent prior Phase 0 run report from GitHub artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-prefix", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    from ops_control.baseline import write_previous_report

    found = write_previous_report(
        artifact_prefix=args.artifact_prefix,
        output_path=args.output,
    )
    if found:
        print(f"Downloaded previous run report to {args.output}")
    else:
        print("No prior Phase 0 run report is available yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
