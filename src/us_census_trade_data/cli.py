from __future__ import annotations

import argparse
from pathlib import Path

from us_census_trade_data.config import (
    DEFAULT_HS_CODE,
    DEFAULT_SOUTH_KOREA_CODE,
    resolve_optional_credential,
)
from us_census_trade_data.models import PipelineResult
from us_census_trade_data.pipeline import CensusTradePipeline
from us_census_trade_data.sources.census import CensusInternationalTradeSource


def main() -> None:
    parser = argparse.ArgumentParser(
        description="U.S. Census Bureau HS import data for Korean memory semiconductors",
    )
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    parser.add_argument("--partner-country-code", default=DEFAULT_SOUTH_KOREA_CODE, help="Four-digit Census code")
    parser.add_argument(
        "--partner-country-codes",
        default=None,
        help="Optional comma-separated codes for comparison, e.g. 5800,5830,5880,5700",
    )
    parser.add_argument("--hs-code", default=DEFAULT_HS_CODE, help="Import HS code")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backfill = subparsers.add_parser("backfill", help="Fetch historical monthly imports")
    backfill.add_argument("--start-month", metavar="YYYY-MM", default=None)
    backfill.add_argument("--end-month", metavar="YYYY-MM", default=None)

    update = subparsers.add_parser("update-latest", help="Fetch the latest closed month")
    update.add_argument("--revenue-month", metavar="YYYY-MM", default=None)

    port_backfill = subparsers.add_parser("port-backfill", help="Fetch historical imports by U.S. port")
    port_backfill.add_argument("--start-month", metavar="YYYY-MM", default=None)
    port_backfill.add_argument("--end-month", metavar="YYYY-MM", default=None)

    port_update = subparsers.add_parser("port-update-latest", help="Fetch the latest closed month by U.S. port")
    port_update.add_argument("--revenue-month", metavar="YYYY-MM", default=None)

    validate = subparsers.add_parser("validate", help="Report stored data quality checks")
    validate.add_argument("--fail-on-issues", action="store_true")

    args = parser.parse_args()
    base_dir = Path(args.base_dir).resolve()
    api_key = resolve_optional_credential(
        base_dir,
        ("CENSUS_DATA_API_KEY", "CENSUS_API_KEY", "US_CENSUS_API_KEY"),
    )
    pipeline = CensusTradePipeline(
        base_dir,
        source=CensusInternationalTradeSource(api_key=api_key),
    )
    partner_country_codes = _parse_codes(args.partner_country_codes)

    if args.command == "backfill":
        result = pipeline.run_backfill(
            start_month=args.start_month,
            end_month=args.end_month,
            partner_country_code=args.partner_country_code,
            partner_country_codes=partner_country_codes,
            hs_code=args.hs_code,
        )
        _print_result(result)
    elif args.command == "update-latest":
        result = pipeline.run_update_latest(
            revenue_month=args.revenue_month,
            partner_country_code=args.partner_country_code,
            partner_country_codes=partner_country_codes,
            hs_code=args.hs_code,
        )
        _print_result(result)
    elif args.command == "port-backfill":
        result = pipeline.run_port_backfill(
            start_month=args.start_month,
            end_month=args.end_month,
            partner_country_code=args.partner_country_code,
            partner_country_codes=partner_country_codes,
            hs_code=args.hs_code,
        )
        _print_result(result)
    elif args.command == "port-update-latest":
        result = pipeline.run_port_update_latest(
            revenue_month=args.revenue_month,
            partner_country_code=args.partner_country_code,
            partner_country_codes=partner_country_codes,
            hs_code=args.hs_code,
        )
        _print_result(result)
    elif args.command == "validate":
        counts = pipeline.validate()
        for key, value in counts.items():
            print(f"  {key}: {value}")
        port_counts = pipeline.validate_port()
        for key, value in port_counts.items():
            print(f"  port_{key}: {value}")
        if args.fail_on_issues:
            _raise_on_validation_issues({**counts, **{f"port_{key}": value for key, value in port_counts.items()}})


def _print_result(result: PipelineResult) -> None:
    print(f"run_id={result.run_id}")
    for dataset_id, total_rows in result.datasets_written.items():
        new_rows = result.dataset_row_deltas.get(dataset_id)
        suffix = f"  (+{new_rows} new)" if new_rows else ""
        print(f"  {dataset_id}: {total_rows} rows{suffix}")
    print(f"raw_run_dir={result.raw_run_dir}")


def _raise_on_validation_issues(counts: dict[str, int | str | None]) -> None:
    problems: list[str] = []
    if int(counts.get("rows") or 0) == 0:
        problems.append("rows=0")
    if int(counts.get("duplicate_keys") or 0) > 0:
        problems.append(f"duplicate_keys={counts['duplicate_keys']}")
    if int(counts.get("missing_general_value") or 0) > 0:
        problems.append(f"missing_general_value={counts['missing_general_value']}")
    if int(counts.get("port_rows") or 0) == 0:
        problems.append("port_rows=0")
    if int(counts.get("port_duplicate_keys") or 0) > 0:
        problems.append(f"port_duplicate_keys={counts['port_duplicate_keys']}")
    if int(counts.get("port_missing_general_value") or 0) > 0:
        problems.append(f"port_missing_general_value={counts['port_missing_general_value']}")
    if problems:
        raise SystemExit(f"Census trade validation failed: {', '.join(problems)}")


def _parse_codes(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    main()
