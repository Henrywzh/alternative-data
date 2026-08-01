#!/usr/bin/env python3
"""Materialise C&SD Table E705 cross-boundary movement history."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.hk_transport.sources.censtatd_boundary_movements import (  # noqa: E402
    fetch_censtatd_boundary_movements,
)

OUTPUT_PARQUET = ROOT / "data" / "processed" / "transport" / "censtatd_boundary_movements_monthly.parquet"


def main() -> int:
    result = fetch_censtatd_boundary_movements()
    OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(OUTPUT_PARQUET, index=False)
    print(
        f"Saved {len(result):,} C&SD Table E705 rows "
        f"({result['month'].min()} -> {result['month'].max()}) to {OUTPUT_PARQUET}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
