"""CLI for HK Telecom Sector Pipeline."""

from __future__ import annotations

import argparse

from .pipeline import run_stage_1_pipeline
from .sources.hkt_operating_drivers import fetch_hkt_operating_drivers
from .sources.hutchison_telecom_operating_drivers import fetch_hutchison_telecom_operating_drivers
from .sources.numbering_plan import fetch_numbering_plan
from .sources.smartone_operating_drivers import fetch_smartone_operating_drivers


def main():
    parser = argparse.ArgumentParser(description="HK Telecom Sector Alternative Data Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("run-stage-1", help="Run Stage 1 ready-to-build ingestion")
    subparsers.add_parser("run-all", help="Run full pipeline across all sources")
    subparsers.add_parser("run-hkt", help="Run HKT operating drivers ingestion")
    subparsers.add_parser("run-smartone", help="Run SmarTone operating drivers ingestion")
    subparsers.add_parser("run-hutchison", help="Run Hutchison Telecom (3 HK) KPI ingestion")
    subparsers.add_parser("run-numbering-plan", help="Run OFCA numbering plan snapshot ingestion")

    args = parser.parse_args()

    try:
        if args.command in ("run-stage-1", "run-all"):
            results = run_stage_1_pipeline()
            print("\nStage 1 Ingestion completed across sources.")
        elif args.command == "run-hkt":
            df = fetch_hkt_operating_drivers()
            print(f"Fetched HKT operating drivers: {len(df)} records\n", df.head())
        elif args.command == "run-smartone":
            df = fetch_smartone_operating_drivers()
            print(f"Fetched SmarTone operating drivers: {len(df)} records\n", df.head())
        elif args.command == "run-hutchison":
            df = fetch_hutchison_telecom_operating_drivers()
            print(f"Fetched Hutchison Telecom operating drivers: {len(df)} records\n", df.head())
        elif args.command == "run-numbering-plan":
            df = fetch_numbering_plan()
            print(f"Fetched numbering plan snapshot: {len(df)} records\n", df.head())
        else:
            parser.print_help()
    except Exception as e:
        print(f"Error executing command: {e}")


if __name__ == "__main__":
    main()
