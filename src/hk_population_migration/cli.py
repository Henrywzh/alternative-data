"""CLI for the Hong Kong population and migration ingestion pipeline."""

from __future__ import annotations

import argparse
import json
from typing import Any

import pandas as pd

from .pipeline import run_stage_1_pipeline


def _summary(results: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for dataset_id, result in results.items():
        if isinstance(result, pd.DataFrame):
            summary[dataset_id] = {
                "status": "success",
                "records": len(result),
            }
        else:
            summary[dataset_id] = {
                "status": "error",
                "error": str(result.get("error", "unknown error"))
                if isinstance(result, dict)
                else str(result),
            }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HK population and migration official-data pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    update = subparsers.add_parser(
        "run-update",
        help="Refresh all active official sources into normalized storage",
    )
    update.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any active source refresh fails.",
    )
    args = parser.parse_args()

    if args.command == "run-update":
        results = run_stage_1_pipeline(raise_on_failure=args.strict)
        print(json.dumps(_summary(results), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
