from __future__ import annotations

import argparse
from pathlib import Path

from ramp_data.pipeline import RampPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ramp vendor-intelligence alternative-data ingestion pipeline")
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("update", help="Crawl Ramp vendors/categories, gate, and upsert normalized datasets")
    subparsers.add_parser("ai-index", help="Fetch the Ramp AI Index (server-rendered) and upsert its datasets")
    subparsers.add_parser("filter-mode", help="Fetch the AI Index Filter-mode cohort timeseries endpoints and upsert")
    subparsers.add_parser("jobs-impact", help="Render the AI jobs-impact table via Playwright and upsert it")
    subparsers.add_parser("all", help="Run vendors + ai-index + filter-mode (server-rendered; excludes jobs-impact)")
    subparsers.add_parser("validate", help="Crawl vendors live and print quality summary without writing")
    return parser


def _print_result(run_result) -> None:
    print(f"run_id={run_result.run_id}")
    for dataset_id, total_rows in run_result.datasets_written.items():
        print(f"{dataset_id}: {total_rows} rows written")
    print(f"raw_run_dir={run_result.raw_run_dir}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    base_dir = Path(args.base_dir).resolve()

    pipeline = RampPipeline(base_dir)

    if args.command == "update":
        _print_result(pipeline.run_update())
        return

    if args.command == "ai-index":
        _print_result(pipeline.run_ai_index())
        return

    if args.command == "filter-mode":
        _print_result(pipeline.run_filter_mode())
        return

    if args.command == "jobs-impact":
        _print_result(pipeline.run_jobs_impact())
        return

    if args.command == "all":
        print("== vendors ==")
        _print_result(pipeline.run_update())
        print("== ai-index ==")
        _print_result(pipeline.run_ai_index())
        print("== filter-mode ==")
        _print_result(pipeline.run_filter_mode())
        return

    if args.command == "validate":
        report = pipeline.validate()
        for dataset_id, stats in report.items():
            detail = ", ".join(f"{key}={value}" for key, value in stats.items())
            print(f"{dataset_id}: {detail}")
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
