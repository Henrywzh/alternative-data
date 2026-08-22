"""The partitioned layout for the two append-only provider-adoption datasets.

These two datasets grow by ~7200 rows a day on top of ~917k already stored.  A
single-file layout therefore rewrote a 36 MB parquet blob nightly for a 0.8%
change, and parquet is compressed binary that git cannot delta -- roughly 26 GB
of history a year across the pair.  What these tests protect is not the layout
itself but the property that makes it worth having: a day's update must touch
only the partitions whose rows actually changed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from provider_adoption_data.models import DatasetRecord
from provider_adoption_data.storage import (
    DATASET_COLUMNS,
    PARTITION_COLUMNS,
    StorageManager,
)


DATASET_ID = "github_repo_rollup_daily"
PARTITION_COLUMN = PARTITION_COLUMNS[DATASET_ID]


def _record(signal_date: str, repo: str, *, stars: int = 1) -> DatasetRecord:
    return DatasetRecord(
        dataset_id=DATASET_ID,
        source_url="https://api.github.com/search/repositories",
        source_run_id="run-1",
        scraped_at="2026-08-22T02:00:00Z",
        provider="anthropic",
        repo_full_name=repo,
        signal_date=signal_date,
        stargazers_count=stars,
    )


def _digests(storage: StorageManager) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in storage.partition_paths(DATASET_ID)
    }


@pytest.fixture()
def storage(tmp_path: Path) -> StorageManager:
    manager = StorageManager(tmp_path)
    manager.upsert_dataset(
        DATASET_ID,
        [
            _record("2026-08-18", "a/one"),
            _record("2026-08-19", "a/two"),
            _record("2026-08-20", "a/three"),
        ],
    )
    return manager


def test_rows_land_in_one_file_per_observation_date(storage: StorageManager) -> None:
    names = sorted(path.name for path in storage.partition_paths(DATASET_ID))
    assert names == [
        "2026-08-18.parquet",
        "2026-08-19.parquet",
        "2026-08-20.parquet",
    ]
    assert not (storage.normalized_root / f"{DATASET_ID}.parquet").exists()


def test_a_new_day_rewrites_only_that_days_partition(storage: StorageManager) -> None:
    """The whole point: yesterday's bytes must not churn when today arrives."""

    before = _digests(storage)
    storage.upsert_dataset(DATASET_ID, [_record("2026-08-21", "a/four")])
    after = _digests(storage)

    assert set(after) - set(before) == {"2026-08-21.parquet"}
    unchanged = {name: digest for name, digest in before.items()}
    assert {name: after[name] for name in unchanged} == unchanged


def test_reupserting_identical_rows_rewrites_nothing(storage: StorageManager) -> None:
    """A byte-identical parquet is still a new git blob, so skip the write."""

    before = _digests(storage)
    storage.upsert_dataset(DATASET_ID, [_record("2026-08-20", "a/three")])
    assert _digests(storage) == before


def test_amending_one_day_leaves_the_other_days_untouched(
    storage: StorageManager,
) -> None:
    before = _digests(storage)
    storage.upsert_dataset(DATASET_ID, [_record("2026-08-19", "a/two", stars=99)])
    after = _digests(storage)

    assert after["2026-08-19.parquet"] != before["2026-08-19.parquet"]
    assert after["2026-08-18.parquet"] == before["2026-08-18.parquet"]
    assert after["2026-08-20.parquet"] == before["2026-08-20.parquet"]


def test_the_round_trip_preserves_every_row_and_the_canonical_schema(
    storage: StorageManager,
) -> None:
    loaded = storage.load_dataset(DATASET_ID)
    assert list(loaded.columns) == DATASET_COLUMNS
    assert len(loaded) == 3
    assert sorted(loaded["repo_full_name"]) == ["a/one", "a/three", "a/two"]


def test_a_null_observation_date_gets_its_own_partition_not_a_silent_drop(
    storage: StorageManager,
) -> None:
    storage.upsert_dataset(DATASET_ID, [_record(None, "a/undated")])

    names = {path.name for path in storage.partition_paths(DATASET_ID)}
    assert "__unpartitioned__.parquet" in names
    loaded = storage.load_dataset(DATASET_ID)
    assert "a/undated" in set(loaded["repo_full_name"])


def test_a_legacy_single_file_checkout_is_still_readable(tmp_path: Path) -> None:
    """Restoring a pre-migration checkout must not read as an empty dataset."""

    manager = StorageManager(tmp_path)
    legacy = pd.DataFrame(
        [{column: pd.NA for column in DATASET_COLUMNS}],
    )
    legacy.loc[0, "dataset_id"] = DATASET_ID
    legacy.loc[0, "provider"] = "anthropic"
    legacy.loc[0, "repo_full_name"] = "a/legacy"
    legacy.loc[0, PARTITION_COLUMN] = "2026-08-01"
    legacy.to_parquet(manager.normalized_root / f"{DATASET_ID}.parquet", index=False)

    assert manager.partition_paths(DATASET_ID) == []
    assert set(manager.load_dataset(DATASET_ID)["repo_full_name"]) == {"a/legacy"}


def test_partitions_win_over_a_leftover_single_file(storage: StorageManager) -> None:
    """A stale monolith beside the partitions must not double every row."""

    stale = storage.load_dataset(DATASET_ID)
    stale.to_parquet(storage.normalized_root / f"{DATASET_ID}.parquet", index=False)

    assert len(storage.load_dataset(DATASET_ID)) == 3

def test_bytes_are_stable_across_a_parquet_round_trip(tmp_path: Path) -> None:
    """The property the layout depends on, tested the way it actually fails.

    ``test_reupserting_identical_rows_rewrites_nothing`` compares a frame that
    never left memory, and that passed while the real dataset rewrote all 138
    partitions every night.  Two things drift across a parquet round trip: a
    bool column written from ``_coerce_types``' object dtype reads back as
    bool, and ``from_pandas`` records the source dtypes in the file's pandas
    metadata.  Either one changes the bytes while every value stays the same,
    which is indistinguishable from real churn to git.  So reload from disk
    first, then re-upsert, and require the bytes to be untouched.
    """

    manager = StorageManager(tmp_path)
    manager.upsert_dataset(
        DATASET_ID,
        [
            _record("2026-08-18", "a/one", stars=3),
            _record("2026-08-19", "a/two", stars=0),
        ],
    )
    first = _digests(manager)

    # Round trip through disk exactly as the next night's run does.
    reloaded = manager.load_dataset(DATASET_ID)
    assert not reloaded.empty
    manager.upsert_dataset(
        DATASET_ID,
        [
            _record("2026-08-18", "a/one", stars=3),
            _record("2026-08-19", "a/two", stars=0),
        ],
    )

    assert _digests(manager) == first


def test_serialization_ignores_the_in_memory_dtype(tmp_path: Path) -> None:
    """Same values, different pandas dtypes, identical bytes."""

    manager = StorageManager(tmp_path)
    frame = pd.DataFrame(
        [{column: pd.NA for column in DATASET_COLUMNS} for _ in range(2)]
    )
    frame["provider"] = ["anthropic", "openai"]
    frame["is_fork"] = [True, False]
    frame["stargazers_count"] = [1, 2]

    as_bool_and_int = frame.copy()
    as_bool_and_int["is_fork"] = as_bool_and_int["is_fork"].astype(bool)
    as_bool_and_int["stargazers_count"] = as_bool_and_int["stargazers_count"].astype("int64")

    as_object_and_float = frame.copy()
    as_object_and_float["is_fork"] = as_object_and_float["is_fork"].astype(object)
    as_object_and_float["stargazers_count"] = as_object_and_float["stargazers_count"].astype("float64")

    assert manager._serialize_partition(as_bool_and_int) == manager._serialize_partition(
        as_object_and_float
    )
