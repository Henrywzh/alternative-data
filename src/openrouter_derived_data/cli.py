"""Command-line entry point for OpenRouter-derived marts."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
import sys

from .guard import report_exit_code, run_guard
from .pipeline import OpenRouterDerivedPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build validated OpenRouter derived-data marts"
    )
    parser.add_argument("--base-dir", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--today", type=date.fromisoformat, metavar="YYYY-MM-DD")

    guard = commands.add_parser(
        "guard", help="report capability-resolution drift from committed inputs"
    )
    guard.add_argument("--top-n", type=int, default=10, metavar="N")
    guard.add_argument(
        "--fail-on",
        choices=("error", "fuzzy"),
        default="error",
        help="'fuzzy' also fails when a top-N family runs on an automatic match",
    )
    guard.add_argument("--json", action="store_true", help="emit a machine-readable summary")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    base_dir = Path(args.base_dir).resolve()

    if args.command == "guard":
        report = run_guard(base_dir, top_n=args.top_n, fail_on=args.fail_on)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        for finding in report.findings:
            stream = sys.stderr if finding.severity == "error" else sys.stdout
            print(f"[{finding.severity}] {finding.check}: {finding.message}", file=stream)
        if not report.findings:
            print(f"capability guard: clean (top {report.top_n})")
        raise SystemExit(report_exit_code(report, fail_on=args.fail_on))

    result = OpenRouterDerivedPipeline(base_dir).build(today=args.today)
    for dataset_id, rows in sorted(result.items()):
        print(f"{dataset_id}: {rows} rows")


if __name__ == "__main__":
    main()
