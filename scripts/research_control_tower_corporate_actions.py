#!/usr/bin/env python3
"""Collect HKEX Next Day Disclosure / corporate actions for the Research Control Tower.

External collector for T1: writes only the standardized local inputs
(corporate_actions_v1.parquet + corporate_actions_state.parquet); the
separate Control Tower builder publishes the immutable artifact generation
with networking disabled.  Sources are HKEXnews official announcement metadata
and Next Day Disclosure Return bodies (Forms FF304/FF305).

The identity crosswalk is the same official-source CSV used by the filings
collector; only hkex_code rows are eligible.  TCEHY (US OTC DR) has no HKEX
disclosure identity and is intentionally not collected until official
depositary verification exists.
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

from research_control_tower.corporate_actions import (  # noqa: E402
    collect_corporate_actions,
    load_source_identity,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--as-of-utc", default=None)
    parser.add_argument("--retrieved-at-utc", default=None)
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument(
        "--max-rows-per-query",
        type=int,
        default=None,
        help=(
            "optional aggregate safety cap per issuer/title stream; default completes "
            "all date windows and reports any explicit truncation"
        ),
    )
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    identity = load_source_identity(args.identity)
    as_of = pd.Timestamp(args.as_of_utc) if args.as_of_utc else None
    retrieved_at = pd.Timestamp(args.retrieved_at_utc) if args.retrieved_at_utc else None
    frame, state = collect_corporate_actions(
        identity,
        as_of_utc=as_of,
        retrieved_at_utc=retrieved_at,
        lookback_days=args.lookback_days,
        max_rows_per_query=args.max_rows_per_query,
        output_dir=args.output_dir,
        timeout=args.timeout,
    )
    print(
        f"wrote {len(frame)} corporate-action rows ({len(state)} source-state rows) "
        f"to {args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
