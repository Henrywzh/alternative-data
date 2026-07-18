from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from ai_hiring_data.pipeline import AIHiringPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect public AI hiring-demand data")
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    parser.add_argument("command", choices=("daily-update",), nargs="?", default="daily-update")
    parser.add_argument("--target-date", type=date.fromisoformat, help="Optional aggregate date (YYYY-MM-DD)")
    args = parser.parse_args()
    written = AIHiringPipeline(Path(args.base_dir).resolve()).run_daily_update(target_date=args.target_date)
    for dataset_id, row_count in written.items():
        print(f"{dataset_id}: {row_count} rows")


if __name__ == "__main__":
    main()
