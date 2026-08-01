#!/usr/bin/env python3
"""Materialise TD Table 4.1(e) monthly private-car make/fuel history."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.hk_transport.sources.td_private_car_first_reg import fetch_td_private_car_first_reg


OUTPUT_PATH = ROOT / "data" / "processed" / "transport" / "hk_private_car_first_reg_monthly.parquet"


def main() -> int:
    raw = fetch_td_private_car_first_reg()
    result = (
        raw.groupby(["date", "month", "make", "fuel_type"], as_index=False)
        .agg(first_reg=("first_reg", "sum"))
        .sort_values(["date", "make", "fuel_type"])
        .reset_index(drop=True)
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(OUTPUT_PATH, index=False)
    print(
        f"Saved {len(result):,} monthly make/fuel rows ({result['month'].min()} -> {result['month'].max()}) "
        f"to {OUTPUT_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
