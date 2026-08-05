#!/usr/bin/env python3
"""Backfill raw_openrouter_models (pricing) history from the Wayback Machine.

openrouter.ai/api/v1/models is a public JSON API and archives cleanly -- no
JS hydration to worry about, unlike the rankings/activity pages. Wayback has
captures back to mid-2025 for the requested floor (earlier ones exist too,
but the pipeline is scoped to 2025-01-01 onward for now).

This deliberately does NOT call compute_availability_data.storage.
StorageManager.upsert_dataset(): that method overwrites
raw_openrouter_models_current.parquet with whatever batch it's given (would
clobber today's live catalog with stale backfilled data) and drops rows
whose price is unchanged from the *latest known* value (assumes forward-only
time; a backfilled 2025 row would get compared against today's 2026 price
and silently dropped if the price never moved). Both behaviors are wrong for
backfill, so this script appends directly to the historical parquet/csv
using the same natural key and leaves the live "current" file untouched.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compute_availability_data.models import Snapshot  # noqa: E402
from compute_availability_data.sources.openrouter import OpenRouterSource  # noqa: E402
from compute_availability_data.storage import (  # noqa: E402
    DATASET_COLUMNS,
    NATURAL_KEYS,
    SORT_KEYS,
    StorageManager,
)
from wayback_backfill import WaybackClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_openrouter_pricing")

DATASET_ID = "raw_openrouter_models"
SOURCE_URL = OpenRouterSource.URL


def backfill_append(storage: StorageManager, incoming: pd.DataFrame) -> int:
    """Append backfilled rows to the historical table only -- see module docstring."""
    existing = storage.load_dataset(DATASET_ID)
    before = len(existing)
    incoming = storage._coerce_types(incoming.copy())
    existing = storage._coerce_types(existing.copy()) if not existing.empty else existing
    merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming
    merged = merged.drop_duplicates(subset=NATURAL_KEYS[DATASET_ID], keep="last")
    merged = merged.sort_values(by=SORT_KEYS[DATASET_ID], na_position="last").reset_index(drop=True)

    csv_path = storage.normalized_root / f"{DATASET_ID}.csv"
    parquet_path = storage.normalized_root / f"{DATASET_ID}.parquet"
    merged.to_csv(csv_path, index=False)
    merged.to_parquet(parquet_path, index=False)
    return len(merged) - before


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date", default="20250101")
    parser.add_argument("--to-date", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    parser.add_argument("--request-delay", type=float, default=1.5)
    parser.add_argument("--dry-run", action="store_true", help="List captures and parse them, but do not write.")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N captures (for testing).")
    args = parser.parse_args()

    client = WaybackClient(request_delay_seconds=args.request_delay)
    storage = StorageManager(ROOT)
    source = OpenRouterSource()

    captures = client.list_snapshots(SOURCE_URL, from_date=args.from_date, to_date=args.to_date)
    logger.info("Found %d Wayback captures of %s between %s and %s", len(captures), SOURCE_URL, args.from_date, args.to_date)
    if args.limit:
        captures = captures[: args.limit]

    all_records = []
    failures = []
    for index, capture in enumerate(captures, start=1):
        logger.info("[%d/%d] fetching capture %s (%s)", index, len(captures), capture.timestamp, capture.capture_date)
        try:
            body = client.fetch_capture(capture)
            snapshot = Snapshot(name="openrouter_models_wayback", source_url=capture.original, body=body)
            scraped_at = f"{capture.capture_date}T00:00:00Z"
            run_id = f"wayback-{capture.timestamp}-{uuid4().hex[:8]}"
            records = source.extract(snapshot, run_id, scraped_at)
            if not records:
                logger.warning("Capture %s produced zero records; skipping", capture.timestamp)
                continue
            all_records.extend(records)
            logger.info("  -> %d model rows", len(records))
        except Exception as exc:  # noqa: BLE001
            logger.warning("  capture %s failed: %s", capture.timestamp, exc)
            failures.append((capture.timestamp, str(exc)))

    if not all_records:
        logger.error("No records extracted from any capture; nothing to write.")
        return 1

    incoming = pd.DataFrame([record.to_dict() for record in all_records], columns=DATASET_COLUMNS)
    logger.info(
        "Parsed %d total rows across %d captures (%d model-day observations before dedup)",
        len(incoming), len(captures) - len(failures), len(incoming),
    )

    if args.dry_run:
        logger.info("Dry run: not writing. Sample:\n%s", incoming[["model_id", "snapshot_ts", "pricing_prompt", "pricing_completion"]].head(10))
        if failures:
            logger.warning("%d captures failed: %s", len(failures), failures[:5])
        return 0

    added = backfill_append(storage, incoming)
    logger.info("Wrote %s: %d new rows added (dedup on model_id+snapshot_ts)", DATASET_ID, added)
    if failures:
        logger.warning("%d/%d captures failed and were skipped: %s", len(failures), len(captures), failures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
