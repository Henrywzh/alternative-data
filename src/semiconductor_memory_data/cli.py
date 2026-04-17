from __future__ import annotations

import argparse
from pathlib import Path

from semiconductor_memory_data.models import PipelineResult
from semiconductor_memory_data.pipeline import SemiconductorMemoryPipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Semiconductor memory alternative-data pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes (default: .)")
    parser.add_argument("--debug", action="store_true", help="Print extra diagnostic info")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # adata-update
    adata_update = subparsers.add_parser(
        "adata-update",
        help="Fetch one ADATA monthly report and upsert tables 1-3",
    )
    adata_update.add_argument(
        "--month",
        metavar="YYYY-MM",
        default=None,
        help="Month to fetch (default: most recent from list page)",
    )

    # adata-backfill
    backfill = subparsers.add_parser(
        "adata-backfill",
        help="Fetch ADATA historical reports and upsert tables 1-3",
    )
    backfill.add_argument("--start-month", metavar="YYYY-MM", default=None, help="Earliest month to include")
    backfill.add_argument("--end-month", metavar="YYYY-MM", default=None, help="Latest month to include")

    # fred-update
    subparsers.add_parser(
        "fred-update",
        help="Fetch latest FRED PPI observations and upsert fred_semiconductor_ppi",
    )

    # derive
    subparsers.add_parser(
        "derive",
        help="Rebuild semiconductor_memory_regime_monthly joined table from tables 3+4",
    )

    # validate
    subparsers.add_parser(
        "validate",
        help="Run spot-check validation across all 5 tables and print a summary",
    )

    args = parser.parse_args()
    base_dir = Path(args.base_dir).resolve()
    pipeline = SemiconductorMemoryPipeline(base_dir)

    if args.command == "adata-update":
        result = pipeline.run_adata_update(month=args.month)
        _print_result(result)

    elif args.command == "adata-backfill":
        result = pipeline.run_adata_backfill(
            start_month=args.start_month,
            end_month=args.end_month,
        )
        _print_result(result)

    elif args.command == "fred-update":
        result = pipeline.run_fred_update()
        _print_result(result)

    elif args.command == "derive":
        result = pipeline.run_derive()
        _print_result(result)

    elif args.command == "validate":
        counts = pipeline.run_validate()
        for key, value in counts.items():
            print(f"  {key}: {value}")


def _print_result(result: PipelineResult) -> None:
    print(f"run_id={result.run_id}")
    for dataset_id, total_rows in result.datasets_written.items():
        new_rows = result.dataset_row_deltas.get(dataset_id)
        suffix = f"  (+{new_rows} new)" if new_rows else ""
        print(f"  {dataset_id}: {total_rows} rows{suffix}")
    print(f"raw_run_dir={result.raw_run_dir}")


if __name__ == "__main__":
    main()
