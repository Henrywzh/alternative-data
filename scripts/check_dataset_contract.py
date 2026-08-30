#!/usr/bin/env python3
"""Assert a normalized dataset still satisfies the contract its readers expect.

A producer step that is allowed to fail (``continue-on-error``) protects the
data already fetched by earlier steps, but it also makes a persistent breakage
invisible: the job stays green while every reader of the dataset silently
degrades.  This closes that gap by checking the artifact rather than the step
outcome, so a transient bad sweep stays quiet while a dataset that no longer
matches its contract is loud and stays loud until it is fixed.

``dashboard.data.DATASET_REGISTRY`` is the single source of truth for the
required columns, the natural key and the date column; nothing is duplicated
here.

Shape alone is not enough. A dataset can satisfy every structural rule and
still be dead: daily_cloud_infra_economics kept its columns, its key and its
38,816 rows while its rebuild step crashed every morning for nine days behind
a continue-on-error that GitHub reports as a success. Pass
``--fresh-within-days`` for any dataset produced by a step that is allowed to
fail, so a producer that stops producing is caught by the artifact it left
behind.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.data import DATASET_REGISTRY  # noqa: E402


def check_dataset(
    dataset_id: str,
    path: Path,
    fresh_within_days: float | None = None,
    now: pd.Timestamp | None = None,
) -> list[str]:
    """Return one message per contract violation; empty means healthy."""

    spec = DATASET_REGISTRY.get(dataset_id)
    if spec is None:
        return [f"{dataset_id} is not registered in dashboard.data.DATASET_REGISTRY"]
    if not path.is_file():
        return [f"{dataset_id}: {path} does not exist"]

    frame = pd.read_parquet(path)
    failures: list[str] = []

    required = [str(column) for column in spec.get("required_columns", [])]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        failures.append(
            f"{dataset_id}: missing required columns {missing}; "
            f"present columns are {sorted(frame.columns)}"
        )

    natural_keys = [str(column) for column in spec.get("natural_keys", [])]
    absent_keys = [column for column in natural_keys if column not in frame.columns]
    if absent_keys:
        failures.append(
            f"{dataset_id}: natural key columns {absent_keys} are absent, so "
            "uniqueness cannot be established"
        )
    elif natural_keys:
        duplicates = int(frame.duplicated(subset=natural_keys, keep="first").sum())
        if duplicates:
            failures.append(
                f"{dataset_id}: {duplicates} duplicate rows on the natural key "
                f"{natural_keys} out of {len(frame)} rows"
            )

    if frame.empty:
        failures.append(f"{dataset_id}: dataset is empty")
        return failures

    if fresh_within_days is not None:
        date_column = str(spec.get("primary_date_column") or "")
        if not date_column or date_column not in frame.columns:
            failures.append(
                f"{dataset_id}: freshness was requested but the registry's date "
                f"column {date_column!r} is not in the data"
            )
        else:
            dates = pd.to_datetime(frame[date_column], errors="coerce", utc=True).dropna()
            if dates.empty:
                failures.append(
                    f"{dataset_id}: no parseable dates in {date_column}, so "
                    "freshness cannot be established"
                )
            else:
                latest = dates.max().normalize()
                reference = (now or pd.Timestamp.now(tz="UTC")).normalize()
                lag_days = (reference - latest).total_seconds() / 86400.0
                if lag_days > fresh_within_days:
                    failures.append(
                        f"{dataset_id}: newest {date_column} is "
                        f"{latest.date()}, {lag_days:.0f} days behind "
                        f"{reference.date()} (limit {fresh_within_days:g})"
                    )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_id")
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--fresh-within-days",
        type=float,
        default=None,
        help=(
            "Fail when the newest date in the registry's primary date column is "
            "more than this many days old. Use it for datasets whose producing "
            "step is allowed to fail."
        ),
    )
    args = parser.parse_args(argv)

    failures = check_dataset(args.dataset_id, args.path, args.fresh_within_days)
    if not failures:
        print(f"{args.dataset_id}: contract satisfied")
        return 0
    print(f"{args.dataset_id}: CONTRACT VIOLATED", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
