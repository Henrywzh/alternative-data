from __future__ import annotations

import argparse
from pathlib import Path

from semiconductor_high_frequency_data.config import resolve_optional_credential
from semiconductor_high_frequency_data.models import PipelineResult
from semiconductor_high_frequency_data.pipeline import HighFrequencyPipeline
from semiconductor_high_frequency_data.sources.kosis import KosisSemiconductorSource
from semiconductor_high_frequency_data.sources.krx import KrxPositioningSource


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Semiconductor high-frequency alternative-data pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes (default: .)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    kcs = subparsers.add_parser("kcs-update", help="Fetch KCS 10-day and HS-854232 country trade")
    kcs.add_argument("--start-month", required=True, metavar="YYYY-MM")
    kcs.add_argument("--end-month", required=True, metavar="YYYY-MM")
    kcs.add_argument("--countries", default=None, help="Comma-separated scope=code pairs, e.g. world=00,taiwan=TW")
    kcs.add_argument("--no-ten-day", action="store_true")
    kcs.add_argument("--no-monthly-memory", action="store_true")

    krx = subparsers.add_parser("krx-update", help="Fetch KRX investor and issue short-position data")
    krx.add_argument("--start-date", required=True, metavar="YYYYMMDD")
    krx.add_argument("--end-date", required=True, metavar="YYYYMMDD")
    krx.add_argument("--codes", default="000660,005930", help="Comma-separated six-digit issue codes")
    krx.add_argument("--isins", default=None, help="Optional comma-separated code=ISIN pairs")
    krx.add_argument("--no-investor-flow", action="store_true")
    krx.add_argument("--no-short-position", action="store_true")
    krx.add_argument("--investor-bld", default=None)
    krx.add_argument("--short-position-bld", default=None)

    kosis = subparsers.add_parser("kosis-update", help="Fetch KOSIS semiconductor production/shipment/inventory")
    kosis.add_argument("--start-month", required=True, metavar="YYYY-MM")
    kosis.add_argument("--end-month", required=True, metavar="YYYY-MM")
    kosis.add_argument("--org-id", default="101")
    kosis.add_argument("--table-id", default="DT_1F01501")
    kosis.add_argument("--industry-code", default=None)

    subparsers.add_parser("validate", help="Report row counts and duplicate checks")

    args = parser.parse_args()
    base_dir = Path(args.base_dir).resolve()

    if args.command == "krx-update":
        pipeline = HighFrequencyPipeline(
            base_dir,
            krx_source=KrxPositioningSource(
                investor_bld=args.investor_bld,
                short_position_bld=args.short_position_bld,
                cookie_header=resolve_optional_credential(base_dir, ("KRX_COOKIE_HEADER",)),
            ),
        )
        result = pipeline.run_krx_update(
            start_date=args.start_date,
            end_date=args.end_date,
            instrument_codes=_parse_csv(args.codes),
            instrument_isins=_parse_pairs(args.isins),
            include_investor_flow=not args.no_investor_flow,
            include_short_position=not args.no_short_position,
        )
        _print_result(result)
    elif args.command == "kcs-update":
        pipeline = HighFrequencyPipeline(base_dir)
        result = pipeline.run_kcs_update(
            start_month=args.start_month,
            end_month=args.end_month,
            include_ten_day=not args.no_ten_day,
            include_monthly_memory=not args.no_monthly_memory,
            country_scopes=_parse_pairs(args.countries),
        )
        _print_result(result)
    elif args.command == "kosis-update":
        pipeline = HighFrequencyPipeline(
            base_dir,
            kosis_source=KosisSemiconductorSource(
                org_id=args.org_id,
                table_id=args.table_id,
                industry_code=args.industry_code,
            ),
        )
        result = pipeline.run_kosis_update(start_month=args.start_month, end_month=args.end_month)
        _print_result(result)
    elif args.command == "validate":
        pipeline = HighFrequencyPipeline(base_dir)
        for key, value in pipeline.validate().items():
            print(f"  {key}: {value}")


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_pairs(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    pairs: dict[str, str] = {}
    for item in value.split(","):
        if "=" not in item:
            raise ValueError(f"Expected key=value pair, got {item!r}")
        key, raw_value = item.split("=", 1)
        pairs[key.strip()] = raw_value.strip()
    return pairs


def _print_result(result: PipelineResult) -> None:
    print(f"run_id={result.run_id}")
    for dataset_id, total_rows in result.datasets_written.items():
        new_rows = result.dataset_row_deltas.get(dataset_id)
        suffix = f"  (+{new_rows} new)" if new_rows else ""
        print(f"  {dataset_id}: {total_rows} rows{suffix}")
    print(f"raw_run_dir={result.raw_run_dir}")


if __name__ == "__main__":
    main()
