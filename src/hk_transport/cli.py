"""CLI for HK Transport Sector Pipeline."""

from __future__ import annotations

import argparse

from .pipeline import run_stage_1_pipeline
from .sources.cathay_traffic import fetch_cathay_traffic
from .sources.mtr_patronage import fetch_mtr_patronage


def main():
    parser = argparse.ArgumentParser(description="HK Transport Sector Alternative Data Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("run-stage-1", help="Run Stage 1 ready-to-build ingestion")
    subparsers.add_parser("run-all", help="Run full pipeline across all sources")
    subparsers.add_parser("run-mtr", help="Run MTR patronage ingestion")
    subparsers.add_parser("run-cathay", help="Run Cathay & HKIA traffic ingestion")

    args = parser.parse_args()

    try:
        if args.command in ("run-stage-1", "run-all"):
            results = run_stage_1_pipeline()
            print("\nStage 1 Ingestion completed across sources.")
        elif args.command == "run-mtr":
            df = fetch_mtr_patronage()
            print(f"Fetched MTR patronage: {len(df)} records\n", df.head())
        elif args.command == "run-cathay":
            df = fetch_cathay_traffic()
            print(f"Fetched Cathay & HKIA traffic: {len(df)} records\n", df.head())
        else:
            parser.print_help()
    except Exception as e:
        print(f"Error executing command: {e}")


if __name__ == "__main__":
    main()
