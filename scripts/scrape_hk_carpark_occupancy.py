#!/usr/bin/env python3
"""Append one TD metered-space occupancy snapshot."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.hk_transport.sources.td_carpark_occupancy import (  # noqa: E402
    fetch_td_carpark_occupancy,
)

OUTPUT_PARQUET = ROOT / "data" / "processed" / "transport" / "hk_carpark_occupancy_snapshots.parquet"


def main() -> int:
    current = fetch_td_carpark_occupancy()
    if OUTPUT_PARQUET.exists():
        previous = pd.read_parquet(OUTPUT_PARQUET)
        # The occupancy denominator changed from an abandoned DPO subset to
        # the official metered-space inventory. Keep only the current schema
        # so an older empty/partial parquet cannot pollute the append.
        previous = previous.reindex(columns=current.columns)
        combined = pd.concat([previous, current], ignore_index=True)
    else:
        combined = current
    combined["snapshot_at"] = pd.to_datetime(combined["snapshot_at"], errors="coerce")
    combined = (
        combined.dropna(subset=["snapshot_at", "district", "occupancy_rate", "sample_size"])
        .drop_duplicates(["snapshot_at", "district"])
        .sort_values(["snapshot_at", "district"])
        .reset_index(drop=True)
    )
    OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(OUTPUT_PARQUET, index=False)
    print(
        f"Appended {len(current):,} occupancy rows; history now has "
        f"{len(combined):,} rows across {combined['snapshot_at'].nunique():,} snapshots "
        f"at {OUTPUT_PARQUET}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
