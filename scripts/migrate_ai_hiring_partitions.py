#!/usr/bin/env python3
"""Split the single-file ai_hiring datasets in PARTITION_COLUMNS into date partitions.

Idempotent: running it against an already-partitioned checkout rewrites
nothing and reports zero changes. Safe to re-run after restoring an older
checkout.

The single file is only removed once the partitions have been read back and
compared against it column by column, so a failed migration leaves the
original in place rather than a half-written directory.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_hiring_data.storage import (  # noqa: E402
    DATASET_COLUMNS,
    PARTITION_COLUMNS,
    HiringStorage,
)


def _columns_match(left: pd.Series, right: pd.Series) -> bool:
    """True when two columns hold the same values, ignoring dtype representation.

    The partition schema is pinned -- that is what keeps an unchanged
    partition byte-identical -- so an integer column reads back as float64 and
    10 becomes 10.0. Stringifying both sides would report that as data loss
    when nothing was lost.
    """
    left_numeric = pd.to_numeric(left, errors="coerce")
    right_numeric = pd.to_numeric(right, errors="coerce")
    if left_numeric.notna().sum() == left.notna().sum() and right_numeric.notna().sum() == right.notna().sum():
        both_null = left_numeric.isna() & right_numeric.isna()
        return bool((both_null | (left_numeric == right_numeric)).all())
    left_text, right_text = left.astype("string"), right.astype("string")
    return bool(((left_text.isna() & right_text.isna()) | (left_text == right_text)).all())


def migrate(base_dir: Path, *, dry_run: bool = False) -> int:
    storage = HiringStorage(base_dir)
    failures = 0

    for dataset_id in sorted(PARTITION_COLUMNS):
        store = storage.partition_store(dataset_id)
        assert store is not None  # dataset_id came from PARTITION_COLUMNS
        monolith = storage.normalized_root / f"{dataset_id}.parquet"

        if not monolith.exists():
            print(f"{dataset_id}: already partitioned ({len(store.paths())} partitions)")
            continue

        columns = DATASET_COLUMNS[dataset_id]
        frame = pd.read_parquet(monolith)
        for column in columns:
            if column not in frame.columns:
                frame[column] = pd.NA
        frame = frame[columns]

        if dry_run:
            # Count the partition stems the store would actually write, not the
            # distinct column values: at month granularity an hourly or daily
            # column collapses many values into one file, and reporting the
            # raw nunique told the operator to expect 366 files where the run
            # produces 13.
            buckets = frame[PARTITION_COLUMNS[dataset_id]].map(store._name).nunique(dropna=False)
            size_mb = monolith.stat().st_size / (1024 * 1024)
            print(f"{dataset_id}: would write {buckets} partitions from {len(frame):,} rows "
                  f"(replacing a {size_mb:.1f} MB single file)")
            continue

        store.write(frame)
        reloaded = store.load()
        if reloaded is None or len(reloaded) != len(frame):
            got = 0 if reloaded is None else len(reloaded)
            print(f"{dataset_id}: FAILED -- partitions hold {got:,} rows, expected {len(frame):,}; "
                  "leaving the single file in place")
            failures += 1
            continue

        # Order is not preserved across a groupby-and-concat round trip, so
        # compare on a stable sort rather than positionally.
        sort_keys = [c for c in columns if c in reloaded.columns]
        left = frame.sort_values(sort_keys).reset_index(drop=True)
        right = reloaded[columns].sort_values(sort_keys).reset_index(drop=True)
        differing = [c for c in columns if not _columns_match(left[c], right[c])]
        if differing:
            print(f"{dataset_id}: FAILED -- partition contents differ from the single file "
                  f"in {differing}; leaving the single file in place")
            failures += 1
            continue

        monolith.unlink()
        total_mb = sum(p.stat().st_size for p in store.paths()) / (1024 * 1024)
        print(f"{dataset_id}: wrote {len(store.paths())} partitions ({total_mb:.1f} MB), "
              f"verified {len(frame):,} rows, removed the single file")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-dir", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true", help="report what would change and exit")
    args = parser.parse_args()
    return 1 if migrate(args.base_dir.resolve(), dry_run=args.dry_run) else 0


if __name__ == "__main__":
    raise SystemExit(main())
