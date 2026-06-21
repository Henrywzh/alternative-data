from __future__ import annotations

import argparse
from pathlib import Path

from taiwan_semiconductor_revenue_data.models import PipelineResult
from taiwan_semiconductor_revenue_data.pipeline import TaiwanSemiconductorRevenuePipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Taiwan semiconductor monthly revenue pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes (default: .)")
    parser.add_argument(
        "--companies",
        default=None,
        help="Optional comma-separated company code override (default: 2330,2303,5347)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backfill = subparsers.add_parser("backfill", help="Fetch MOPS historical monthly revenue pages")
    backfill.add_argument("--start-month", metavar="YYYY-MM", default=None, help="Earliest month to include")
    backfill.add_argument("--end-month", metavar="YYYY-MM", default=None, help="Latest month to include")

    update = subparsers.add_parser("update-latest", help="Fetch the latest closed-month revenue pages")
    update.add_argument(
        "--revenue-month",
        metavar="YYYY-MM",
        default=None,
        help="Override the latest closed month (useful for tests and manual reruns)",
    )

    subparsers.add_parser("validate", help="Report stored dataset counts and missing-field checks")

    args = parser.parse_args()
    base_dir = Path(args.base_dir).resolve()
    pipeline = TaiwanSemiconductorRevenuePipeline(base_dir)
    company_codes = _parse_company_codes(args.companies)

    if args.command == "backfill":
        result = pipeline.run_backfill(
            start_month=args.start_month,
            end_month=args.end_month,
            company_codes=company_codes,
        )
        _print_result(result)
    elif args.command == "update-latest":
        result = pipeline.run_update_latest(
            company_codes=company_codes,
            revenue_month=args.revenue_month,
        )
        _print_result(result)
    elif args.command == "validate":
        counts = pipeline.validate()
        for key, value in counts.items():
            print(f"  {key}: {value}")


def _parse_company_codes(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _print_result(result: PipelineResult) -> None:
    print(f"run_id={result.run_id}")
    for dataset_id, total_rows in result.datasets_written.items():
        new_rows = result.dataset_row_deltas.get(dataset_id)
        suffix = f"  (+{new_rows} new)" if new_rows else ""
        print(f"  {dataset_id}: {total_rows} rows{suffix}")
    print(f"raw_run_dir={result.raw_run_dir}")


if __name__ == "__main__":
    main()
