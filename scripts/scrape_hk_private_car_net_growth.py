#!/usr/bin/env python3
"""Materialise TD Table 4.1(c) private-car net-registration history."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.hk_transport.sources.td_private_car_net_registration import (  # noqa: E402
    fetch_td_private_car_net_registration,
    parse_private_car_net_registration_sheet,
)

OUTPUT_PARQUET = ROOT / "data" / "processed" / "transport" / "hk_private_car_net_growth_monthly.parquet"


def main() -> int:
    result = fetch_td_private_car_net_registration()
    OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(OUTPUT_PARQUET, index=False)
    print(
        f"Saved {len(result):,} monthly private-car net-registration rows "
        f"({result['date'].min()} -> {result['date'].max()}) to {OUTPUT_PARQUET}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
