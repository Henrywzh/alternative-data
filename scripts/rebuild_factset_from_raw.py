"""Rebuild FactSet normalized data from a retained raw snapshot.

This command is deliberately offline.  It is useful after parser/schema
changes because the source HTML and OCR remain available under
``data/raw/factset_earnings``.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from factset_earnings_data.replay import replay_raw_run
from factset_earnings_data.storage import FactsetEarningsStorage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, default=ROOT)
    parser.add_argument("--run-id", help="Raw FactSet run id; defaults to newest full article snapshot.")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow explicitly replaying a partial raw run for forensic work.",
    )
    args = parser.parse_args()

    result = replay_raw_run(args.base_dir, args.run_id, allow_partial=args.allow_partial)
    storage = FactsetEarningsStorage(args.base_dir)
    # A replay is a deterministic projection of one raw run.  Replacement is
    # intentional: additive upserts would retain observations that disappeared
    # or became unsupported in the selected run.
    observations = storage.replace_observations(result.observations)
    catalog = storage.replace_article_catalog(result.catalog)
    catalog_dates = sorted(
        record.report_date for record in result.catalog if record.report_date
    )
    receipt_path = storage.normalized_root / "factset_replay_receipt.json"
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "raw_run_id": result.raw_run_id,
                "raw_manifest": f"data/raw/factset_earnings/{result.raw_run_id}/manifest.json",
                "replayed_at_utc": datetime.now(timezone.utc).isoformat(),
                "replay": result.stats,
                "normalized_observations": len(observations),
                "article_catalog": len(catalog),
                "catalog_min_report_date": catalog_dates[0] if catalog_dates else None,
                "catalog_max_report_date": catalog_dates[-1] if catalog_dates else None,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "raw_run_id": result.raw_run_id,
                "replay": result.stats,
                "normalized_observations": len(observations),
                "article_catalog": len(catalog),
                "observation_path": str(storage.normalized_root / "factset_sp500_earnings_regime.parquet"),
                "catalog_path": str(storage.normalized_root / "factset_article_catalog.parquet"),
                "replay_receipt_path": str(receipt_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
