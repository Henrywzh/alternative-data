#!/usr/bin/env python3
"""Materialise TD Table 4.1(a) private-car fleet stock."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.hk_transport.sources.td_vehicle_fleet_stock import (  # noqa: E402
    COLUMNS,
    TOLERANCE,
    _check_identity,
    _find_private_car_sheet,
    _header_text,
    _validate_headers,
    fetch_td_vehicle_fleet_stock,
    parse_private_car_fleet_sheet,
)

OUTPUT_PARQUET = ROOT / "data" / "processed" / "transport" / "hk_vehicle_stock_monthly.parquet"
TABLE_URL = "https://www.td.gov.hk/filemanager/en/content_4883/table41a.xls"


# Backwards-compatible name for the old scraper test and any local scripts.
parse_sheet = parse_private_car_fleet_sheet


def main() -> int:
    result = fetch_td_vehicle_fleet_stock()
    OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(OUTPUT_PARQUET, index=False)
    print(
        f"Saved {len(result):,} monthly private-car fleet rows "
        f"({result['date'].min()} -> {result['date'].max()}) to {OUTPUT_PARQUET}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
