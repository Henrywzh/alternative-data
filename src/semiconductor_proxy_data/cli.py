from __future__ import annotations

import argparse
from pathlib import Path

from semiconductor_proxy_data.models import PipelineResult
from semiconductor_proxy_data.pipeline import SemiconductorProxyPipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Semiconductor macro proxy monthly data pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes (default: .)")
    parser.add_argument(
        "--regions",
        default=None,
        help="Optional comma-separated region override (e.g. korea,china,hongkong,japan)",
    )
    parser.add_argument(
        "--categories",
        default=None,
        help="Optional comma-separated category override (e.g. ic_only,broad_semiconductor)",
    )
    parser.add_argument(
        "--sources",
        default="all",
        choices=["official", "backup", "all"],
        help="Source tier to run (default: all)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backfill = subparsers.add_parser("backfill", help="Fetch historical monthly statistics")
    backfill.add_argument("--start-month", metavar="YYYY-MM", default=None, help="Earliest month to include")
    backfill.add_argument("--end-month", metavar="YYYY-MM", default=None, help="Latest month to include")

    update = subparsers.add_parser("update-latest", help="Fetch the latest closed-month statistics")
    update.add_argument(
        "--period-month",
        metavar="YYYY-MM",
        default=None,
        help="Override the latest closed month (useful for tests and manual reruns)",
    )

    validate = subparsers.add_parser("validate", help="Report stored dataset counts and duplicate checks")
    validate.add_argument(
        "--fail-on-issues",
        action="store_true",
        help="Exit non-zero when duplicates, stale rows, or empty official outputs are detected",
    )
    subparsers.add_parser("compare-backup", help="Recompute official vs backup comparison gaps")

    import_csv = subparsers.add_parser("import-csv", help="Import a custom local CSV dataset (e.g. from KCS or KITA)")
    import_csv.add_argument("--filepath", required=True, help="Path to the custom CSV file")
    import_csv.add_argument("--region", required=True, help="Target region (e.g. korea, china, japan, hongkong)")
    import_csv.add_argument("--category-id", default="ic_only", help="Category id for the imported official series")
    import_csv.add_argument("--metric-type", default="exports", help="Metric type for the imported official series")
    import_csv.add_argument("--flow-code", default="X", help="Flow code for the imported official series")
    import_csv.add_argument("--scale-thousand", action="store_true", help="Multiply value column by 1000")

    args = parser.parse_args()
    base_dir = Path(args.base_dir).resolve()
    pipeline = SemiconductorProxyPipeline(base_dir)
    regions = _parse_regions(args.regions)
    categories = _parse_regions(args.categories)

    if args.command == "backfill":
        result = pipeline.run_backfill(
            start_month=args.start_month,
            end_month=args.end_month,
            regions=regions,
            categories=categories,
            sources=args.sources,
        )
        _print_result(result)
    elif args.command == "update-latest":
        result = pipeline.run_update_latest(
            regions=regions,
            categories=categories,
            period_month=args.period_month,
            sources=args.sources,
        )
        _print_result(result)
    elif args.command == "validate":
        counts = pipeline.validate()
        for key, value in counts.items():
            print(f"  {key}: {value}")
        if args.fail_on_issues:
            _raise_on_validation_issues(counts)
    elif args.command == "compare-backup":
        result = pipeline.compare_backup()
        _print_result(result)
    elif args.command == "import-csv":
        filepath = Path(args.filepath).resolve()
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        result = pipeline.import_custom_csv(
            filepath=filepath,
            region=args.region,
            category_id=args.category_id,
            metric_type=args.metric_type,
            flow_code=args.flow_code,
            scale_thousand=args.scale_thousand,
        )
        _print_result(result)


def _parse_regions(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _print_result(result: PipelineResult) -> None:
    print(f"run_id={result.run_id}")
    for dataset_id, total_rows in result.datasets_written.items():
        new_rows = result.dataset_row_deltas.get(dataset_id)
        suffix = f"  (+{new_rows} new)" if new_rows else ""
        print(f"  {dataset_id}: {total_rows} rows{suffix}")
    print(f"raw_run_dir={result.raw_run_dir}")


def _raise_on_validation_issues(counts: dict[str, int | str | None]) -> None:
    problems: list[str] = []
    official_rows = int(counts.get("official_rows") or 0)
    official_duplicates = int(counts.get("official_duplicates") or 0)
    backup_duplicates = int(counts.get("backup_duplicates") or 0)
    official_stale_rows = int(counts.get("official_stale_rows") or 0)
    backup_stale_rows = int(counts.get("backup_stale_rows") or 0)

    if official_rows == 0:
        problems.append("official_rows=0")
    if official_duplicates > 0:
        problems.append(f"official_duplicates={official_duplicates}")
    if backup_duplicates > 0:
        problems.append(f"backup_duplicates={backup_duplicates}")
    if official_stale_rows > 0:
        problems.append(f"official_stale_rows={official_stale_rows}")
    if backup_stale_rows > 0:
        problems.append(f"backup_stale_rows={backup_stale_rows}")

    if problems:
        raise SystemExit(f"Semiconductor proxy validation failed: {', '.join(problems)}")


if __name__ == "__main__":
    main()
