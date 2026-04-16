from __future__ import annotations

import argparse
from pathlib import Path

from provider_adoption_data.pipeline import ProviderAdoptionPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provider adoption alternative-data ingestion pipeline")
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    parser.add_argument("--date", dest="target_date", help="Target date in YYYY-MM-DD format")
    parser.add_argument("--providers", help="Comma-separated provider slugs to include")
    parser.add_argument("--debug", action="store_true", help="Reserved for future logging expansion")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("pypi-daily-update", help="Fetch PyPI download history and write normalized outputs")
    subparsers.add_parser("npm-daily-update", help="Fetch npm download history and write normalized outputs")
    subparsers.add_parser("github-daily-update", help="Fetch GitHub provider signals for a target date")
    subparsers.add_parser("huggingface-daily-update", help="Fetch Hugging Face model download history and write normalized outputs")
    subparsers.add_parser("derived-daily-update", help="Compute provider momentum metrics for a target date")

    backfill = subparsers.add_parser("backfill", help="Run GitHub/PyPI/derived updates over a bounded date range")
    backfill.add_argument("--start-date", required=True, help="Start date in YYYY-MM-DD format")
    backfill.add_argument("--end-date", required=True, help="End date in YYYY-MM-DD format")

    subparsers.add_parser("validate", help="Validate provider registry and basic collector config")
    return parser


def _provider_slugs(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [slug.strip() for slug in value.split(",") if slug.strip()]


def _print_result(run_result) -> None:
    print(f"run_id={run_result.run_id}")
    for dataset_id, total_rows in run_result.datasets_written.items():
        new_rows = getattr(run_result, "dataset_row_deltas", {}).get(dataset_id)
        if new_rows is None:
            print(f"{dataset_id}: {total_rows} rows written")
        else:
            print(f"{dataset_id}: total_rows={total_rows} new_rows={new_rows}")
    raw_run_dirs = getattr(run_result, "raw_run_dirs", None)
    if raw_run_dirs:
        for raw_run_dir in dict.fromkeys(raw_run_dirs):
            print(f"raw_run_dir={raw_run_dir}")
        return
    print(f"raw_run_dir={run_result.raw_run_dir}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    base_dir = Path(args.base_dir).resolve()
    pipeline = ProviderAdoptionPipeline(base_dir)
    provider_slugs = _provider_slugs(args.providers)

    if args.command == "pypi-daily-update":
        _print_result(pipeline.run_pypi_daily_update(target_date=args.target_date, provider_slugs=provider_slugs))
        return
    if args.command == "npm-daily-update":
        _print_result(pipeline.run_npm_daily_update(target_date=args.target_date, provider_slugs=provider_slugs))
        return
    if args.command == "github-daily-update":
        _print_result(pipeline.run_github_daily_update(target_date=args.target_date, provider_slugs=provider_slugs))
        return
    if args.command == "huggingface-daily-update":
        _print_result(pipeline.run_huggingface_daily_update(target_date=args.target_date, provider_slugs=provider_slugs))
        return
    if args.command == "derived-daily-update":
        _print_result(pipeline.run_derived_daily_update(target_date=args.target_date, provider_slugs=provider_slugs))
        return
    if args.command == "backfill":
        _print_result(
            pipeline.run_backfill(
                start_date=args.start_date,
                end_date=args.end_date,
                provider_slugs=provider_slugs,
            )
        )
        return
    if args.command == "validate":
        counts = pipeline.validate(provider_slugs=provider_slugs)
        for key, value in counts.items():
            print(f"{key}: {value}")
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
