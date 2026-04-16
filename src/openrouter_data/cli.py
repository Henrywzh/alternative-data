from __future__ import annotations

import argparse
from pathlib import Path

from openrouter_data.pipeline import ActivityPipeline, AppsPipeline, RankingsPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenRouter alternative-data ingestion pipeline")
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("initial-backfill", help="Fetch full rankings history and write normalized outputs")
    subparsers.add_parser("weekly-update", help="Fetch current rankings snapshots and append unseen completed weeks")
    subparsers.add_parser("backfill-missing", help="Fill unseen completed rankings weeks from the live source")

    validate = subparsers.add_parser("validate", help="Validate live rankings extraction or parse fixture HTML")
    validate.add_argument("--fixture", help="Optional rankings fixture HTML path")
    validate.add_argument(
        "--programming-fixture",
        help="Optional programming rankings fixture HTML path. Defaults to --fixture when omitted.",
    )

    subparsers.add_parser("apps-initial-backfill", help="Fetch current app detail and public apps snapshots")
    subparsers.add_parser("apps-daily-update", help="Fetch current app detail and public apps snapshots")
    
    activity = subparsers.add_parser("activity-daily-update", help="Discover top models and fetch granular usage activity")
    activity.add_argument("--limit", type=int, default=50, help="Number of models to discover and scrape")

    apps_validate = subparsers.add_parser("apps-validate", help="Validate live app extraction or parse fixture HTML")
    apps_validate.add_argument("--directory-fixture", help="Optional /apps fixture HTML path")
    apps_validate.add_argument("--app-fixture", help="Optional monitored app fixture HTML path")
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

    if args.command in {"initial-backfill", "weekly-update", "backfill-missing", "validate"}:
        pipeline = RankingsPipeline(base_dir)

        if args.command == "initial-backfill":
            _print_result(pipeline.run_initial_backfill())
            return

        if args.command == "weekly-update":
            _print_result(pipeline.run_weekly_update())
            return

        if args.command == "backfill-missing":
            _print_result(pipeline.run_backfill_missing())
            return

        fixture_html = None
        programming_fixture_html = None
        if args.fixture:
            fixture_html = Path(args.fixture).read_text(encoding="utf-8")
            if args.programming_fixture:
                programming_fixture_html = Path(args.programming_fixture).read_text(encoding="utf-8")
        counts = pipeline.validate(fixture_html=fixture_html, fixture_programming_html=programming_fixture_html)
        for dataset_id, count in counts.items():
            print(f"{dataset_id}: {count} records")
        return

    if args.command in {"apps-initial-backfill", "apps-daily-update", "apps-validate"}:
        pipeline = AppsPipeline(base_dir)

        if args.command == "apps-initial-backfill":
            _print_result(pipeline.run_initial_backfill())
            return

        if args.command == "apps-daily-update":
            _print_result(pipeline.run_daily_update())
            return

        directory_fixture_html = Path(args.directory_fixture).read_text(encoding="utf-8") if args.directory_fixture else None
        app_fixture_html = Path(args.app_fixture).read_text(encoding="utf-8") if args.app_fixture else None
        counts = pipeline.validate(directory_fixture_html=directory_fixture_html, app_fixture_html=app_fixture_html)
        for dataset_id, count in counts.items():
            print(f"{dataset_id}: {count} records")
        return

    if args.command == "activity-daily-update":
        pipeline = ActivityPipeline(base_dir)
        _print_result(pipeline.run_daily_update(limit=args.limit))
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
