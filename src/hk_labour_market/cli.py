"""CLI for official Hong Kong labour-market data ingestion."""

from __future__ import annotations

import argparse
import json

from .marts import build_analysis_marts
from .audit import run_labour_market_audit
from .pipeline import (
    run_stage_1_pipeline,
    run_stage_2_pipeline,
    run_stage_3_pipeline,
    run_stage_4_pipeline,
    run_update_pipeline,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="HK Labour Market official-data pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run-stage-1", help="Backfill all core official C&SD full-history tables")
    subparsers.add_parser("run-stage-2", help="Backfill detailed official jobs and construction history")
    subparsers.add_parser("run-stage-3", help="Backfill annual official wage-distribution and working-hours history")
    subparsers.add_parser("run-stage-4", help="Backfill reliable official labour-supply policy history")
    subparsers.add_parser("build-marts", help="Build source-backed labour-market analytical marts")
    subparsers.add_parser("run-update", help="Refresh all official sources and rebuild analytical marts")
    subparsers.add_parser("audit", help="Run the final labour-market data quality audit")
    args = parser.parse_args()
    if args.command == "run-stage-1":
        print(json.dumps(run_stage_1_pipeline(), indent=2))
    elif args.command == "run-stage-2":
        print(json.dumps(run_stage_2_pipeline(), indent=2))
    elif args.command == "run-stage-3":
        print(json.dumps(run_stage_3_pipeline(), indent=2))
    elif args.command == "run-stage-4":
        print(json.dumps(run_stage_4_pipeline(), indent=2))
    elif args.command == "build-marts":
        print(json.dumps(build_analysis_marts(), indent=2))
    elif args.command == "run-update":
        print(json.dumps(run_update_pipeline(), indent=2))
    elif args.command == "audit":
        print(json.dumps(run_labour_market_audit(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
