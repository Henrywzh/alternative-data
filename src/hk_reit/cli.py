"""CLI entry points for the HK REIT data pipeline."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .pipeline import run_all_reit_pipelines, run_reit_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hk-reit-data")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="Fetch all REIT datasets (spot quotes + price history).")
    sub.add_parser("run-strict", help="Same as run, but exit non-zero if every dataset failed/empty.")
    args = parser.parse_args(argv)

    if args.command == "run":
        results = run_reit_pipeline()
    elif args.command == "run-strict":
        try:
            results = run_all_reit_pipelines()
        except Exception as exc:
            print(f"REIT pipeline run failed: {exc}", file=sys.stderr)
            return 1
    else:
        parser.print_help()
        return 1

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
