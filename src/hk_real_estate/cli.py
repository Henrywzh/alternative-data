import argparse
import json
import sys

from .pipeline import (
    run_group_a_pipeline,
    run_group_b_pipeline,
    run_group_c_pipeline,
    run_all_pipelines,
    run_stage_1_pipeline,
    run_stage_2_pipeline,
    run_all_incomplete_pipelines,
    run_centaline_indices_pipeline,
    run_midland_monthly_pipeline,
    run_rvd_commercial_pipeline,
    run_midland_snapshot_pipeline,
    run_policy_event_research_pipeline,
)

def main():
    parser = argparse.ArgumentParser(description="HK Real Estate Alternative Data Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("run-group-a", help="Run Group A data ingestion")
    subparsers.add_parser("run-group-b", help="Run Group B data ingestion")
    subparsers.add_parser("run-group-c", help="Run Group C data ingestion")
    subparsers.add_parser("run-all", help="Run full pipeline across all data sources")
    subparsers.add_parser("run-stage-1", help="Run Stage 1 source ingestion")
    subparsers.add_parser("run-stage-2", help="Run Stage 2 financing & stock attribution ingestion")
    subparsers.add_parser("run-incomplete-5", help="Run digestion pipeline for the 5 incomplete data sources")
    subparsers.add_parser("run-centaline-indices", help="Run Tranche 1 CCI/CRI/CSI ingestion only")
    subparsers.add_parser("run-midland-monthly", help="Run Tranche 2 Midland monthly ingestion only")
    subparsers.add_parser("run-rvd-commercial", help="Run Tranche 3 RVD office/retail ingestion only")
    subparsers.add_parser("run-midland-snapshots", help="Run Tranche 4 Midland snapshot ingestion only")
    subparsers.add_parser("run-policy-events", help="Run Tranche 5 policy-source and registry research contracts")

    args = parser.parse_args()

    try:
        if args.command == "run-group-a":
            results = run_group_a_pipeline()
            print("\nGroup A Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-group-b":
            results = run_group_b_pipeline()
            print("\nGroup B Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-group-c":
            results = run_group_c_pipeline()
            print("\nGroup C Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-all":
            results = run_all_pipelines()
            print("\nFull Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-stage-1":
            results = run_stage_1_pipeline()
            print("\nStage 1 Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-stage-2":
            results = run_stage_2_pipeline()
            print("\nStage 2 Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-incomplete-5":
            results = run_all_incomplete_pipelines()
            print("\nIncomplete 5 Ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-centaline-indices":
            results = run_centaline_indices_pipeline()
            print("\nCentaline Tranche 1 ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-midland-monthly":
            results = run_midland_monthly_pipeline()
            print("\nMidland Tranche 2 ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-rvd-commercial":
            results = run_rvd_commercial_pipeline()
            print("\nRVD Tranche 3 ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-midland-snapshots":
            results = run_midland_snapshot_pipeline()
            print("\nMidland Tranche 4 ingestion completed:\n" + json.dumps(results, indent=2))
        elif args.command == "run-policy-events":
            results = run_policy_event_research_pipeline()
            print("\nPolicy/event Tranche 5 ingestion completed:\n" + json.dumps(results, indent=2))
        else:
            parser.print_help()
    except Exception as e:
        print(f"\nFATAL: Ingestion failed with error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
