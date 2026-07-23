"""CLI for HK Utilities Sector Pipeline."""

from __future__ import annotations

import argparse
import json

from .pipeline import run_stage_1_pipeline
from .sources.clp_electricity import fetch_clp_electricity
from .sources.hko_temperature import fetch_hko_temperature
from .sources.power_assets_segments import fetch_power_assets_segments
from .sources.towngas_proxy import fetch_towngas_proxy


def main():
    parser = argparse.ArgumentParser(description="HK Utilities Sector Alternative Data Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("run-stage-1", help="Run Stage 1 ready-to-build ingestion")
    subparsers.add_parser("run-all", help="Run full pipeline across all sources")
    subparsers.add_parser("run-clp", help="Run CLP electricity sales ingestion")
    subparsers.add_parser("run-towngas", help="Run Towngas proxy gas consumption ingestion")
    subparsers.add_parser("run-hko-temp", help="Run HKO mean temperature ingestion")
    subparsers.add_parser("run-power-assets", help="Run Power Assets geographic segment ingestion")

    args = parser.parse_args()

    try:
        if args.command in ("run-stage-1", "run-all"):
            results = run_stage_1_pipeline()
            print("\nStage 1 Ingestion completed across sources.")
        elif args.command == "run-clp":
            df = fetch_clp_electricity()
            print(f"Fetched CLP electricity: {len(df)} records\n", df.head())
        elif args.command == "run-towngas":
            df = fetch_towngas_proxy()
            print(f"Fetched Towngas proxy: {len(df)} records\n", df.head())
        elif args.command == "run-hko-temp":
            df = fetch_hko_temperature()
            print(f"Fetched HKO mean temperature: {len(df)} records\n", df.head())
        elif args.command == "run-power-assets":
            df = fetch_power_assets_segments()
            print(f"Fetched Power Assets segments: {len(df)} records\n", df.head())
        else:
            parser.print_help()
    except Exception as e:
        print(f"Error executing command: {e}")


if __name__ == "__main__":
    main()
