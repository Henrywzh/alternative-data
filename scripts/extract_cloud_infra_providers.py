#!/usr/bin/env python3
"""Compatibility entrypoint for the incremental serving-provider pipeline.

The original one-off extractor overwrote history and fabricated prices for
unmatched routes.  Keep this filename for existing local workflows, but route
all work through the validated ingestion and economics mart builders.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openrouter_data.pipeline import ServingProviderActivityPipeline  # noqa: E402
from research_data.marts import build_daily_cloud_infra_economics  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", default=str(ROOT))
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Fetch and validate without writing normalized data or marts.",
    )
    args = parser.parse_args()
    base_dir = Path(args.base_dir).expanduser().resolve()
    pipeline = ServingProviderActivityPipeline(base_dir)

    if args.validate_only:
        print(pipeline.validate())
        return 0

    result = pipeline.run_daily_update()
    economics = build_daily_cloud_infra_economics(
        base_dir=base_dir,
        refresh=True,
    )
    print(f"run_id={result.run_id}")
    print(
        "cloud_infra_daily_activity="
        f"{result.datasets_written.get('cloud_infra_daily_activity', 0)} rows"
    )
    print(f"daily_cloud_infra_economics={len(economics)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
