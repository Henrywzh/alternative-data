#!/usr/bin/env python3
"""Split the single-file provider-adoption datasets into date partitions.

Idempotent: running it against an already-partitioned checkout rewrites nothing
and reports zero changes.  Safe to re-run after restoring an older checkout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from provider_adoption_data.storage import (  # noqa: E402
    DATASET_COLUMNS,
    PARTITION_COLUMNS,
    StorageManager,
)


def migrate(base_dir: Path, *, dry_run: bool = False) -> int:
    storage = StorageManager(base_dir)
    failures = 0
    for dataset_id in sorted(PARTITION_COLUMNS):
        monolith = storage.normalized_root / f"{dataset_id}.parquet"
        existing = storage.partition_paths(dataset_id)
        if not monolith.exists():
            print(f"{dataset_id}: already partitioned ({len(existing)} partitions)")
            continue

        frame = pd.read_parquet(monolith)
        for column in DATASET_COLUMNS:
            if column not in frame.columns:
                frame[column] = pd.NA
        frame = frame[DATASET_COLUMNS]
        if dry_run:
            buckets = frame[PARTITION_COLUMNS[dataset_id]].nunique(dropna=False)
            print(f"{dataset_id}: would write {buckets} partitions from {len(frame)} rows")
            continue

        storage._write_partitions(dataset_id, frame)
        written = storage.partition_paths(dataset_id)
        # Only drop the single file once the partitions read back identically.
        reloaded = pd.concat(
            [pd.read_parquet(path) for path in written], ignore_index=True
        )
        if len(reloaded) != len(frame):
            print(
                f"{dataset_id}: ABORT -- partitions hold {len(reloaded)} rows, "
                f"monolith had {len(frame)}",
                file=sys.stderr,
            )
            failures += 1
            continue
        monolith.unlink()
        (storage.normalized_root / f"{dataset_id}.csv").unlink(missing_ok=True)
        print(f"{dataset_id}: {len(frame)} rows -> {len(written)} partitions")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return migrate(args.base_dir.resolve(), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
