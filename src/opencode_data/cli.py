from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opencode_data.pipeline import run_opencode_scrape


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenCode Data Collector CLI")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path("."),
        help="Base directory of the repository (default: current directory)",
    )
    parser.add_argument(
        "--top-models",
        type=int,
        default=15,
        help="Number of top models to fetch deepdives for (default: 15)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape_parser = subparsers.add_parser("scrape", help="Run full OpenCode scrape pipeline")
    scrape_parser.add_argument(
        "--top-models",
        type=int,
        default=15,
        help="Number of top models to fetch deepdives for",
    )

    args = parser.parse_args(argv)

    if args.command == "scrape":
        top_models = getattr(args, "top_models", 15)
        summary = run_opencode_scrape(base_dir=args.base_dir.resolve(), top_models_count=top_models)
        print("\n=== OpenCode Scrape Summary ===")
        for k, v in summary.items():
            print(f"  {k}: {v}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
