#!/usr/bin/env python3
"""Fetch delayed public quote snapshots for the Research Control Tower.

This script is an external collector.  It writes only the standardized local
input; the separate Control Tower builder publishes the immutable artifact
generation with networking disabled.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

# Make direct python scripts/... execution resolve the repository package
# without requiring an editable install.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.research_control_tower.quote_collector import (
    collect_yfinance_quotes,
    write_quote_snapshot,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--entities", type=Path, default=None)
    parser.add_argument("--as-of-utc", default=None)
    parser.add_argument("--stage1-only", action="store_true", default=True)
    args = parser.parse_args()

    listings = pd.read_csv(args.listings)
    entities = pd.read_csv(args.entities) if args.entities and args.entities.exists() else None
    as_of = pd.Timestamp(args.as_of_utc) if args.as_of_utc else None
    frame = collect_yfinance_quotes(
        listings,
        as_of_utc=as_of,
        entities=entities,
        stage1_only=args.stage1_only,
    )
    output = write_quote_snapshot(frame, args.output)
    print(f"wrote {len(frame)} delayed quote rows to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
