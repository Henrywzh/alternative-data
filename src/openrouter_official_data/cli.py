from __future__ import annotations

import argparse
import os
from datetime import date, timedelta
from pathlib import Path

from openrouter_official_data.pipeline import OpenRouterOfficialPipeline


def _load_config(base_dir: Path) -> None:
    path = base_dir / ".config"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect documented OpenRouter public datasets")
    parser.add_argument("--base-dir", default=".")
    subparsers = parser.add_subparsers(dest="command", required=True)
    daily = subparsers.add_parser("daily-update")
    daily.add_argument("--date", help="Most recent completed UTC date (YYYY-MM-DD)")
    backfill = subparsers.add_parser("rankings-backfill")
    backfill.add_argument("--start-date", default="2025-01-01")
    backfill.add_argument("--end-date", default=(date.today() - timedelta(days=1)).isoformat())
    return parser


def main() -> None:
    args = build_parser().parse_args()
    base_dir = Path(args.base_dir).resolve()
    _load_config(base_dir)
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    pipeline = OpenRouterOfficialPipeline(base_dir, api_key)
    if args.command == "daily-update":
        result = pipeline.run_daily_update(target_date=date.fromisoformat(args.date) if args.date else None)
    else:
        result = pipeline.run_rankings_backfill(
            start_date=date.fromisoformat(args.start_date),
            end_date=date.fromisoformat(args.end_date),
        )
    for dataset_id, rows in sorted(result.items()):
        print(f"{dataset_id}: {rows} rows")


if __name__ == "__main__":
    main()
