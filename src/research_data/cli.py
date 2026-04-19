from __future__ import annotations

import argparse
from pathlib import Path

from .api import catalog
from .marts import MART_REGISTRY, build_all_marts, build_daily_provider_economics, build_frontier_model_registry, build_weekly_openrouter_usage


def _build_single_mart(name: str, base_dir: Path, refresh: bool) -> int:
    if name == "weekly_openrouter_usage":
        frame = build_weekly_openrouter_usage(base_dir=base_dir, refresh=refresh)
    elif name == "daily_provider_economics":
        frame = build_daily_provider_economics(base_dir=base_dir, refresh=refresh)
    elif name == "frontier_model_registry":
        frame = build_frontier_model_registry(base_dir=base_dir, refresh=refresh)
    else:
        raise ValueError(f"Unknown mart '{name}'")
    return len(frame)


def main() -> None:
    parser = argparse.ArgumentParser(prog="research-data", description="Build and inspect analysis-ready research marts.")
    parser.add_argument("--base-dir", default=".", help="Repository root to read and write data under.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog_parser = subparsers.add_parser("catalog", help="Show the source and mart dataset catalog.")
    catalog_parser.add_argument("--base-dir", default=".", help="Repository root to read and write data under.")
    catalog_parser.add_argument("--include-empty", action="store_true", help="Keep zero-row datasets in the output.")

    build_marts_parser = subparsers.add_parser("build-marts", help="Build every research mart.")
    build_marts_parser.add_argument("--base-dir", default=".", help="Repository root to read and write data under.")
    build_marts_parser.add_argument("--refresh", action="store_true", help="Force rebuild even if mart files exist.")

    build_mart_parser = subparsers.add_parser("build-mart", help="Build a single named mart.")
    build_mart_parser.add_argument("--base-dir", default=".", help="Repository root to read and write data under.")
    build_mart_parser.add_argument("mart_name", choices=sorted(MART_REGISTRY))
    build_mart_parser.add_argument("--refresh", action="store_true", help="Force rebuild even if mart files exist.")

    args = parser.parse_args()
    base_dir = Path(args.base_dir).resolve()

    if args.command == "catalog":
        frame = catalog(base_dir=base_dir)
        if not args.include_empty:
            frame = frame[frame["row_count"] > 0].copy()
        print(frame.to_string(index=False))
        return

    if args.command == "build-marts":
        built = build_all_marts(base_dir=base_dir, refresh=args.refresh)
        for mart_name, frame in built.items():
            print(f"{mart_name}: {len(frame)} rows")
        return

    if args.command == "build-mart":
        row_count = _build_single_mart(args.mart_name, base_dir=base_dir, refresh=args.refresh)
        print(f"{args.mart_name}: {row_count} rows")
        return


if __name__ == "__main__":
    main()
