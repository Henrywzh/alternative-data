#!/usr/bin/env python3
"""Collect official filing/announcement metadata for the Research Control Tower.

External collector for Batch 2: writes only the standardized local inputs
(``official_filings_v1.parquet`` + ``official_filings_state.parquet``); the
separate Control Tower builder publishes the immutable artifact generation
with networking disabled.  Sources are SEC EDGAR submissions metadata and
HKEXnews announcement titles; issuer-IR pages are only consumed through an
explicit standardized snapshot, never scraped.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# src/ too, as scripts/build_research_control_tower.py already does: pyproject
# maps these packages to the top level (package-dir = {"" = "src"}) and they
# import each other by those names, so the repo root alone is not enough.
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from research_control_tower.official_filings import (  # noqa: E402
    collect_official_filings,
    load_source_identity,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--as-of-utc", default=None)
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--ir-snapshot", type=Path, default=None)
    args = parser.parse_args()

    identity = load_source_identity(args.identity)
    as_of = pd.Timestamp(args.as_of_utc) if args.as_of_utc else None
    frame, state = collect_official_filings(
        identity,
        as_of_utc=as_of,
        lookback_days=args.lookback_days,
        output_dir=args.output_dir,
        ir_snapshot_path=args.ir_snapshot,
        raw_root=REPO_ROOT,
    )
    print(
        f"wrote {len(frame)} official filing/announcement metadata rows "
        f"({len(state)} source-state rows) to {args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
