#!/usr/bin/env python3
"""Materialise MTTD Table 2.3 passenger journeys."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.hk_transport.sources.mttd_passenger_journeys import (  # noqa: E402
    fetch_mttd_passenger_journeys,
)

OUTPUT_PARQUET = ROOT / "data" / "processed" / "transport" / "mttd_passenger_journeys_monthly.parquet"


def main() -> int:
    result = fetch_mttd_passenger_journeys()
    OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(OUTPUT_PARQUET, index=False)
    print(
        f"Saved {len(result):,} MTTD Table 2.3 rows "
        f"({result['month'].min()} -> {result['month'].max()}) to {OUTPUT_PARQUET}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
