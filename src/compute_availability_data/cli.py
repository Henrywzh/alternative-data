from __future__ import annotations

import argparse
from pathlib import Path

from compute_availability_data.pipeline import ComputeAvailabilityPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute Availability Data Acquisition Pipeline")
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("daily-update", help="Run all compute availability collectors (OpenRouter, Lambda, AWS)")
    return parser


import os

def load_config(base_dir: Path) -> None:
    config_path = base_dir / ".config"
    if config_path.exists():
        for line in config_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    base_dir = Path(args.base_dir).resolve()
    load_config(base_dir)

    pipeline = ComputeAvailabilityPipeline(base_dir)

    if args.command == "daily-update":
        result = pipeline.run_daily_update()
        print(f"run_id={result.run_id}")
        for dataset_id, rows in result.datasets_written.items():
            print(f"{dataset_id}: {rows} total rows")
        print(f"raw_run_dir={result.raw_run_dir}")
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
