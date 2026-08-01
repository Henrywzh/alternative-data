#!/usr/bin/env python3
"""Materialise the latest TD private-car make/model detail snapshot."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.hk_transport.sources.td_first_registered_vehicle_details import (
    fetch_td_first_registered_vehicle_details,
)


OUTPUT_PATH = ROOT / "data" / "processed" / "transport" / "hk_private_car_first_reg_model_latest.parquet"


def main() -> int:
    raw = fetch_td_first_registered_vehicle_details()
    result = (
        raw.groupby(
            ["observation_date", "vehicle_make", "vehicle_model", "fuel_type"],
            as_index=False,
        )
        .agg(first_reg_count=("vehicle_model", "size"))
        .sort_values(["observation_date", "first_reg_count"], ascending=[True, False])
        .reset_index(drop=True)
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(OUTPUT_PATH, index=False)
    print(
        f"Saved {len(result):,} latest make/model rows for "
        f"{result['observation_date'].iloc[0].strftime('%Y-%m')} to {OUTPUT_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
