"""Command-line entry point for the local Research Control Tower builder."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

from .build import (
    BuildConfig,
    LocalInput,
    build_control_tower_marts,
)


def _local_input(value: str) -> LocalInput:
    source_id, path, file_format, schema = value.split("|", 3)
    return LocalInput(
        source_id=source_id,
        path=Path(path),
        format=file_format,
        expected_schema=schema,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-control-tower")
    subparsers = parser.add_subparsers(dest="command")
    build = subparsers.add_parser("build", help="build the 15 local Control Tower marts")
    build.add_argument("--registry-root", type=Path, required=True)
    build.add_argument("--event-root", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--as-of-utc", required=True)
    build.add_argument("--build-id", required=True)
    build.add_argument("--consensus-export-dir", type=Path)
    build.add_argument(
        "--macro-input",
        action="append",
        default=[],
        metavar="SOURCE_ID|PATH|FORMAT|SCHEMA_ID",
        help="explicit optional macro input descriptor; may be repeated",
    )
    build.add_argument(
        "--news-input",
        action="append",
        default=[],
        metavar="SOURCE_ID|PATH|FORMAT|SCHEMA_ID",
        help="explicit optional news input descriptor; may be repeated",
    )
    build.add_argument(
        "--filing-input",
        action="append",
        default=[],
        metavar="SOURCE_ID|PATH|FORMAT|SCHEMA_ID",
        help="explicit optional filing input descriptor; may be repeated",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command != "build":
        parser.print_help()
        return 0
    config = BuildConfig(
        registry_root=args.registry_root,
        event_root=args.event_root,
        output_dir=args.output_dir,
        as_of_utc=pd.Timestamp(args.as_of_utc),
        build_id=args.build_id,
        consensus_export_dir=args.consensus_export_dir,
        macro_inputs=tuple(_local_input(item) for item in args.macro_input),
        news_inputs=tuple(_local_input(item) for item in args.news_input),
        filing_inputs=tuple(_local_input(item) for item in args.filing_input),
    )
    manifest = build_control_tower_marts(config)
    print(f"{manifest.status}: {config.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
