#!/usr/bin/env python3
"""Backfill openrouter_catalog_size from the two sources that hold real totals.

The catalog-size series cannot be recovered from raw_openrouter_models: that
table is change-only, so a live snapshot's row count is "models that changed
that day". Two places do hold complete catalogs:

1. Wayback-backfilled rows in raw_openrouter_models. Each of those snapshots
   IS a full single-shot archive dump, so its distinct model_id count is the
   catalog size as the archive saw it. The archive captured the bare URL,
   whose default response only includes text-output models, so these land in
   model_count_text_output with no all-modality figure.

2. Git revisions of raw_openrouter_models_current.parquet. That sidecar is a
   complete catalog written on every healthy live run and committed daily, so
   its history reconstructs the live era exactly -- both counts.

Live snapshots with no committed current-catalog revision (the sparse runs
before 2026-07-17) are left out rather than guessed: their true size is not
recoverable from anything on disk.

Revisions whose model count falls below MINIMUM_PRODUCTION_CATALOG_MODELS are
skipped -- the degraded-response bug that ran until 2026-08-08 wrote genuinely
collapsed catalogs to that file before the floor existed to reject them.
"""

from __future__ import annotations

import argparse
import io
import logging
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compute_availability_data.storage import (  # noqa: E402
    CAPTURE_SOURCE_LIVE,
    CAPTURE_SOURCE_WAYBACK,
    CATALOG_SIZE_COLUMNS,
    MINIMUM_PRODUCTION_CATALOG_MODELS,
    StorageManager,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_openrouter_catalog_size")

CURRENT_CATALOG_PATH = "data/normalized/compute_availability/raw_openrouter_models_current.parquet"


def wayback_rows(storage: StorageManager) -> pd.DataFrame:
    history = storage.load_dataset("raw_openrouter_models")
    if history.empty:
        return pd.DataFrame(columns=CATALOG_SIZE_COLUMNS)
    archived = history[history["source_run_id"].astype(str).str.startswith("wayback-")]
    if archived.empty:
        return pd.DataFrame(columns=CATALOG_SIZE_COLUMNS)
    return storage._catalog_size_rows(archived, capture_source=CAPTURE_SOURCE_WAYBACK)


def live_rows(storage: StorageManager, repo_root: Path) -> pd.DataFrame:
    log = subprocess.run(
        ["git", "-C", str(repo_root), "log", "--format=%H", "--", CURRENT_CATALOG_PATH],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    frames: list[pd.DataFrame] = []
    skipped = 0
    for commit in log:
        blob = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"{commit}:{CURRENT_CATALOG_PATH}"],
            capture_output=True,
            check=True,
        ).stdout
        if not blob:
            continue
        frame = pd.read_parquet(io.BytesIO(blob))
        if frame.empty or "model_id" not in frame.columns:
            continue
        if int(frame["model_id"].nunique()) < MINIMUM_PRODUCTION_CATALOG_MODELS:
            logger.warning(
                "Skipping %s: current catalog held only %d models (degraded response)",
                commit[:8],
                frame["model_id"].nunique(),
            )
            skipped += 1
            continue
        frames.append(storage._catalog_size_rows(frame, capture_source=CAPTURE_SOURCE_LIVE))

    logger.info("Read %d current-catalog revisions (%d skipped as degraded)", len(frames), skipped)
    if not frames:
        return pd.DataFrame(columns=CATALOG_SIZE_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report what would be written and stop.")
    args = parser.parse_args()

    storage = StorageManager(ROOT)
    archived = wayback_rows(storage)
    live = live_rows(storage, ROOT)
    rows = pd.concat([archived, live], ignore_index=True) if not archived.empty else live
    if rows.empty:
        logger.error("No catalog-size rows recovered from either source.")
        return 1

    rows = rows.drop_duplicates(subset=["snapshot_ts", "capture_source"], keep="last").sort_values("snapshot_ts")
    logger.info(
        "Recovered %d rows: %d wayback (text-output basis), %d live (both bases)",
        len(rows),
        len(archived),
        len(live),
    )
    if args.dry_run:
        logger.info("Dry run, not writing. Head/tail:\n%s\n...\n%s", rows.head(5), rows.tail(5))
        return 0

    merged = storage.append_catalog_size(rows)
    logger.info("Wrote openrouter_catalog_size: %d rows total", len(merged))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
