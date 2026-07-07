from __future__ import annotations

import argparse
from pathlib import Path

from vercel_ai_data.pipeline import VercelPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vercel AI Gateway alternative-data ingestion pipeline")
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("daily-update", help="Fetch and update model/lab leaderboards and catalog datasets")
    subparsers.add_parser("validate", help="Fetch datasets live and print summary counts of extracted records")
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

    pipeline = VercelPipeline(base_dir)

    if args.command == "daily-update":
        _print_result(pipeline.run_daily_update())
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
