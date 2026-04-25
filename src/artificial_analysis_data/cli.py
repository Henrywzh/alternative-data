from __future__ import annotations

import argparse
from pathlib import Path

from artificial_analysis_data.pipeline import ArtificialAnalysisPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Artificial Analysis ingestion pipeline")
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("daily-update", help="Fetch Artificial Analysis API data and refresh capex history")
    subparsers.add_parser("capex-update", help="Refresh only the capital expenditure history")
    subparsers.add_parser("validate", help="Validate API access and capex parsing")
    return parser


def _print_result(run_result) -> None:
    print(f"run_id={run_result.run_id}")
    for dataset_id, total_rows in run_result.datasets_written.items():
        new_rows = getattr(run_result, "dataset_row_deltas", {}).get(dataset_id)
        if new_rows is None:
            print(f"{dataset_id}: {total_rows} rows written")
        else:
            print(f"{dataset_id}: total_rows={total_rows} new_rows={new_rows}")
    print(f"raw_run_dir={run_result.raw_run_dir}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    base_dir = Path(args.base_dir).resolve()
    pipeline = ArtificialAnalysisPipeline(base_dir)

    if args.command == "daily-update":
        _print_result(pipeline.run_daily_update())
        return
    if args.command == "capex-update":
        _print_result(pipeline.run_capex_update())
        return
    if args.command == "validate":
        for key, value in pipeline.validate().items():
            print(f"{key}: {value}")
        return
    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
