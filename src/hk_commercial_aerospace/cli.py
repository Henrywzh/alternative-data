"""CLI for HK Commercial Aerospace Sector Pipeline."""

from __future__ import annotations

import argparse

from .pipeline import run_stage_1_pipeline
from .sources.launch_library import fetch_upcoming_launches, fetch_chinese_commercial_launches
from .sources.sse_ipo_status import fetch_all_ipo_statuses
from .sources.celestrak_satellites import fetch_all_constellations
from .sources.google_patents import fetch_all_patent_counts


def main():
    parser = argparse.ArgumentParser(description="HK Commercial Aerospace Sector Alternative Data Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("run", help="Run Stage 1 ready-to-build ingestion")
    subparsers.add_parser("run-launches", help="Run Launch Library 2 fetches")
    subparsers.add_parser("run-ipo-status", help="Run SSE IPO Status ingestion")
    subparsers.add_parser("run-satellites", help="Run Celestrak satellite count ingestion")
    subparsers.add_parser("run-patents", help="Run Google Patents ingestion")

    args = parser.parse_args()

    try:
        if args.command == "run":
            results = run_stage_1_pipeline()
            print("\nStage 1 Ingestion completed across sources.")
        elif args.command == "run-launches":
            df_up = fetch_upcoming_launches()
            print(f"Fetched upcoming launches: {len(df_up)} records\n", df_up.head())
            df_dict = fetch_chinese_commercial_launches()
            print(f"Fetched Chinese commercial launches across {len(df_dict)} agencies")
        elif args.command == "run-ipo-status":
            df = fetch_all_ipo_statuses()
            print(f"Fetched IPO statuses: {len(df)} records\n", df.head())
        elif args.command == "run-satellites":
            df = fetch_all_constellations()
            print(f"Fetched Satellite counts: {len(df)} records\n", df.head())
        elif args.command == "run-patents":
            df = fetch_all_patent_counts()
            print(f"Fetched Patent counts: {len(df)} records\n", df.head())
        else:
            parser.print_help()
    except Exception as e:
        print(f"Error executing command: {e}")


if __name__ == "__main__":
    main()
