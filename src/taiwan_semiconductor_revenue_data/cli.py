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
        help=(
            "Optional comma-separated company code or preset override "
            "(default: all 11 tracked companies; presets: memory, ai_server_odms, all)"
        ),
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

    validate = subparsers.add_parser("validate", help="Report stored dataset counts and missing-field checks")
    validate.add_argument(
        "--fail-on-issues",
        action="store_true",
        help="Exit non-zero when duplicates, empty outputs, or missing monthly revenue are detected",
    )

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
        if args.fail_on_issues:
            _raise_on_validation_issues(counts)


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


def _raise_on_validation_issues(counts: dict[str, int]) -> None:
    problems: list[str] = []
    rows = int(counts.get("rows") or 0)
    companies = int(counts.get("companies") or 0)
    duplicate_keys = int(counts.get("duplicate_keys") or 0)
    missing_monthly_revenue = int(counts.get("missing_monthly_revenue") or 0)

    if rows == 0:
        problems.append("rows=0")
    if companies == 0:
        problems.append("companies=0")
    if duplicate_keys > 0:
        problems.append(f"duplicate_keys={duplicate_keys}")
    if missing_monthly_revenue > 0:
        problems.append(f"missing_monthly_revenue={missing_monthly_revenue}")
    month_gaps = int(counts.get("month_gaps") or 0)
    if month_gaps > 0:
        problems.append(f"month_gaps={month_gaps}")

    if problems:
        raise SystemExit(f"Taiwan semiconductor revenue validation failed: {', '.join(problems)}")


if __name__ == "__main__":
    main()
