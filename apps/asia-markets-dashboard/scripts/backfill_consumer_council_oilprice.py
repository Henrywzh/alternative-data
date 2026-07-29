#!/usr/bin/env python3
"""Backfill Consumer Council daily oil-price history into the local cache."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.hk_local_consumer.sources.consumer_council_oilprice import (
    fetch_consumer_council_oilprice_history,
    merge_consumer_council_oilprice_history,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2009)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    args = parser.parse_args()
    for year in range(args.start_year, args.end_year + 1):
        frame = fetch_consumer_council_oilprice_history(f"{year}-01-01", f"{year}-12-31")
        if frame.empty:
            print(f"{year}: no rows")
            continue
        merged = merge_consumer_council_oilprice_history(frame)
        print(f"{year}: {len(frame):,} fetched; {len(merged):,} cached")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
