#!/usr/bin/env python3
"""Fetch official macro calendar events and observations for Research Control Tower.

This script is an external collector running outside Streamlit. It queries
official primary macro data sources (FRED/ALFRED, BLS, BEA, Fed, ECB, NBS China, HK C&SD)
and writes standardized local files atomically.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd

# Make direct ``python scripts/...`` execution resolve the repository package
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research_control_tower.macro_sources import (
    MacroDataCollector,
    filter_observations_pit,
)

def write_atomic_artifact(data: pd.DataFrame | dict[str, Any], output_path: Path) -> Path:
    """Write dataframe or dict atomically via a temporary file."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(f".{output.name}.tmp")

    if isinstance(data, pd.DataFrame):
        if output.suffix == ".parquet":
            data.to_parquet(temp, index=False)
        elif output.suffix in (".csv", ".txt"):
            data.to_csv(temp, index=False)
        elif output.suffix == ".json":
            data.to_json(temp, orient="records", indent=2)
        else:
            data.to_parquet(temp, index=False)
    elif isinstance(data, dict):
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    temp.replace(output)
    return output

def main() -> int:
    parser = argparse.ArgumentParser(description="Collect official macro events and observations.")
    parser.add_argument("--output-dir", type=Path, default=Path("data/normalized/macro_collector"))
    parser.add_argument("--output-events", type=Path, default=None)
    parser.add_argument("--output-observations", type=Path, default=None)
    parser.add_argument("--output-health", type=Path, default=None)
    parser.add_argument("--as-of-utc", default=None, help="Optional snapshot timestamp for PIT filtering")
    parser.add_argument("--indicators", nargs="*", default=None, help="Optional list of specific indicators to collect")

    args = parser.parse_args()

    out_dir = args.output_dir
    out_events = args.output_events or (out_dir / "macro_events.parquet")
    out_obs = args.output_observations or (out_dir / "macro_observations.parquet")
    out_health = args.output_health or (out_dir / "macro_source_health.json")

    collector = MacroDataCollector(base_dir=REPO_ROOT)
    events_df, obs_df, health_map = collector.collect_all(
        indicators=args.indicators,
        as_of_utc=args.as_of_utc,
    )

    write_atomic_artifact(events_df, out_events)
    write_atomic_artifact(obs_df, out_obs)
    write_atomic_artifact(health_map, out_health)

    print("Macro Collection Complete:")
    print(f"  - Events written: {len(events_df)} -> {out_events}")
    print(f"  - Observations written: {len(obs_df)} -> {out_obs}")
    print(f"  - Health report written: {len(health_map)} sources -> {out_health}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
