"""Tests for the shared date-partitioned parquet store.

The load-bearing property is byte stability: an unchanged partition must not
be rewritten, because git stores a byte-identical parquet as a brand new
blob. Every other guarantee here exists to protect that one.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from common.partitioned_parquet import (
    UNPARTITIONED,
    PartitionSpec,
    PartitionedParquetStore,
)

COLUMNS = ["signal_date", "entity_id", "score", "is_active"]
SPEC = PartitionSpec(
    column="signal_date",
    columns=COLUMNS,
    bool_columns=frozenset({"is_active"}),
    numeric_columns=frozenset({"score"}),
)


def _frame(rows: list[tuple[str, str, float, bool]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=COLUMNS)


def _store(tmp_path: Path) -> PartitionedParquetStore:
    return PartitionedParquetStore(tmp_path / "dataset", SPEC)


def test_load_returns_none_before_migration(tmp_path: Path) -> None:
    # A pre-migration checkout has no partition directory; the caller needs to
    # be able to tell that apart from an empty dataset so it can fall back to
    # the single-file layout instead of silently serving zero rows.
    assert _store(tmp_path).load() is None
    assert _store(tmp_path).exists() is False


def test_round_trip_preserves_every_row(tmp_path: Path) -> None:
    store = _store(tmp_path)
    frame = _frame([
        ("2026-01-01", "a", 1.5, True),
        ("2026-01-01", "b", 2.5, False),
        ("2026-01-02", "c", 3.5, True),
    ])
    store.write(frame)

    loaded = store.load()
    assert loaded is not None
    assert len(loaded) == 3
    assert sorted(loaded["entity_id"]) == ["a", "b", "c"]
    assert {p.name for p in store.paths()} == {"2026-01-01.parquet", "2026-01-02.parquet"}


def test_unchanged_partition_is_not_rewritten(tmp_path: Path) -> None:
    """The whole point: an append-only day must not touch earlier days."""
    store = _store(tmp_path)
    day_one = _frame([("2026-01-01", "a", 1.0, True)])
    store.write(day_one)
    first = (tmp_path / "dataset" / "2026-01-01.parquet").read_bytes()

    # A later run carries the old day forward unchanged and appends a new one.
    both = pd.concat([day_one, _frame([("2026-01-02", "b", 2.0, False)])], ignore_index=True)
    written = store.write(both)

    assert [p.name for p in written] == ["2026-01-02.parquet"], "only the new day should be written"
    assert (tmp_path / "dataset" / "2026-01-01.parquet").read_bytes() == first


def test_rewrite_is_byte_stable_across_a_round_trip(tmp_path: Path) -> None:
    """Reloading and rewriting identical data must produce identical bytes.

    Pandas dtypes drift across a parquet round trip -- bool read back from
    object, int64 where the concatenated frame held float64 -- and unpinned
    that drift alone changes the serialized bytes. This is the regression
    that would quietly restore the original bloat.
    """
    store = _store(tmp_path)
    store.write(_frame([("2026-01-01", "a", 1.0, True), ("2026-01-02", "b", 2.0, False)]))
    before = {p.name: p.read_bytes() for p in store.paths()}

    reloaded = store.load()
    assert reloaded is not None
    written = store.write(reloaded)

    assert written == [], "a round trip changed the bytes; the schema pin is not holding"
    assert {p.name: p.read_bytes() for p in store.paths()} == before


def test_changed_partition_is_rewritten(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write(_frame([("2026-01-01", "a", 1.0, True)]))
    written = store.write(_frame([("2026-01-01", "a", 9.0, True)]))
    assert [p.name for p in written] == ["2026-01-01.parquet"]
    loaded = store.load()
    assert loaded is not None and loaded["score"].tolist() == [9.0]


def test_emptied_partition_is_deleted_not_left_as_a_ghost(tmp_path: Path) -> None:
    # A lingering file would be concatenated back in by load(), resurrecting
    # rows the pipeline deliberately dropped.
    store = _store(tmp_path)
    store.write(_frame([("2026-01-01", "a", 1.0, True), ("2026-01-02", "b", 2.0, False)]))
    store.write(_frame([("2026-01-02", "b", 2.0, False)]))

    assert {p.name for p in store.paths()} == {"2026-01-02.parquet"}
    loaded = store.load()
    assert loaded is not None and len(loaded) == 1


@pytest.mark.parametrize("blank", [None, "", "   ", pd.NA])
def test_blank_partition_values_get_an_explicit_bucket(tmp_path: Path, blank: object) -> None:
    # A null observation date is real data; dropping it or folding it into an
    # arbitrary date would lose rows silently.
    store = _store(tmp_path)
    store.write(pd.DataFrame([[blank, "a", 1.0, True]], columns=COLUMNS))

    assert {p.name for p in store.paths()} == {f"{UNPARTITIONED}.parquet"}
    loaded = store.load()
    assert loaded is not None and len(loaded) == 1


def test_partition_name_keeps_the_stem_filesystem_safe() -> None:
    assert PartitionedParquetStore.partition_name("2026/01/02") == "2026-01-02"
    assert PartitionedParquetStore.partition_name("  2026-01-02  ") == "2026-01-02"


def _month_spec() -> PartitionSpec:
    """SPEC, but grouping each month into one file."""
    return PartitionSpec(
        column=SPEC.column,
        columns=SPEC.columns,
        bool_columns=SPEC.bool_columns,
        numeric_columns=SPEC.numeric_columns,
        granularity="month",
    )


def test_month_granularity_groups_a_month_into_one_file(tmp_path: Path) -> None:
    store = PartitionedParquetStore(tmp_path / "dataset", _month_spec())
    store.write(_frame([
        ("2026-01-05", "a", 1.0, True),
        ("2026-01-20", "b", 2.0, False),
        ("2026-02-03", "c", 3.0, True),
    ]))

    assert {p.name for p in store.paths()} == {"2026-01.parquet", "2026-02.parquet"}
    loaded = store.load()
    assert loaded is not None and len(loaded) == 3


def test_month_granularity_still_isolates_an_untouched_month(tmp_path: Path) -> None:
    store = PartitionedParquetStore(tmp_path / "dataset", _month_spec())
    january = _frame([("2026-01-05", "a", 1.0, True)])
    store.write(january)

    both = pd.concat([january, _frame([("2026-02-03", "c", 3.0, True)])], ignore_index=True)
    written = store.write(both)

    assert [p.name for p in written] == ["2026-02.parquet"]


def test_month_granularity_leaves_non_date_keys_alone(tmp_path: Path) -> None:
    # Truncating a non-date key to 7 characters would silently merge unrelated
    # partitions, so only ISO-shaped values are truncated.
    store = PartitionedParquetStore(tmp_path / "dataset", _month_spec())
    store.write(_frame([("quarterly-2026-Q1", "a", 1.0, True)]))
    assert {p.name for p in store.paths()} == {"quarterly-2026-Q1.parquet"}


def test_spec_rejects_an_unknown_granularity() -> None:
    with pytest.raises(ValueError, match="granularity must be"):
        PartitionSpec(column="a", columns=["a"], granularity="week")


def test_spec_rejects_a_partition_column_outside_the_schema() -> None:
    # Caught at construction rather than as a KeyError mid-write.
    with pytest.raises(ValueError, match="not in the dataset columns"):
        PartitionSpec(column="missing", columns=["a", "b"])


def test_day_granularity_truncates_an_hourly_column(tmp_path: Path) -> None:
    """An hourly value must land in its day's file, not one file per hour.

    EIA stores 2,545,579 rows keyed by hour; partitioning on the raw value
    would write ~67,000 files instead of 2,810.
    """
    store = _store(tmp_path)
    store.write(_frame([
        ("2026-01-01T00", "a", 1.0, True),
        ("2026-01-01T13", "b", 2.0, False),
        ("2026-01-02T04", "c", 3.0, True),
    ]))

    assert {p.name for p in store.paths()} == {"2026-01-01.parquet", "2026-01-02.parquet"}
    loaded = store.load()
    assert loaded is not None and len(loaded) == 3


def test_day_granularity_leaves_a_plain_date_unchanged(tmp_path: Path) -> None:
    # The three datasets already on this layout key on plain dates; truncating
    # to 10 characters must be a no-op for them.
    store = _store(tmp_path)
    store.write(_frame([("2026-01-05", "a", 1.0, True)]))
    assert {p.name for p in store.paths()} == {"2026-01-05.parquet"}
