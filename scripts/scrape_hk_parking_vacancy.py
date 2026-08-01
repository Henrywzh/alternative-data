#!/usr/bin/env python3
"""Append one official TD parking-vacancy snapshot to local history."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.hk_transport.sources.td_parking_vacancy import fetch_td_parking_vacancy


OUTPUT_PATH = ROOT / "data" / "processed" / "transport" / "hk_parking_vacancy_snapshots.parquet"


def main() -> int:
    current = fetch_td_parking_vacancy()
    if OUTPUT_PATH.exists():
        previous = pd.read_parquet(OUTPUT_PATH)
        combined = pd.concat([previous, current], ignore_index=True)
    else:
        combined = current
    combined["snapshot_at"] = pd.to_datetime(combined["snapshot_at"], errors="coerce")
    combined = (
        combined.dropna(subset=["snapshot_at", "park_id"])
        .drop_duplicates(["snapshot_at", "park_id", "vehicle_type", "service_category"])
        .sort_values(["snapshot_at", "park_id", "vehicle_type", "service_category"])
        .reset_index(drop=True)
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(OUTPUT_PATH, index=False)
    print(
        f"Appended {len(current):,} rows; history now has {len(combined):,} rows across "
        f"{combined['snapshot_at'].nunique():,} snapshots ({combined['snapshot_at'].min()} -> "
        f"{combined['snapshot_at'].max()}) at {OUTPUT_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
