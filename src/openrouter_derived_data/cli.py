"""Command-line entry point for OpenRouter-derived marts."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .pipeline import OpenRouterDerivedPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build validated OpenRouter derived-data marts"
    )
    parser.add_argument("--base-dir", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--today", type=date.fromisoformat, metavar="YYYY-MM-DD")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = OpenRouterDerivedPipeline(Path(args.base_dir).resolve()).build(
        today=args.today
    )
    for dataset_id, rows in sorted(result.items()):
        print(f"{dataset_id}: {rows} rows")


if __name__ == "__main__":
    main()
