"""One parquet file per observation date, for append-only datasets.

Parquet is compressed binary, so git cannot delta two versions of the same
table: rewriting a monolithic dataset stores a complete new blob every run.
Measured on this repo, that is how ``.git`` reached ~1 GB while all tracked
content was 268 MB and all Python source was 8 MB -- parquet alone accounted
for 66% of history. Commit ccc7228d fixed the two worst datasets by writing
one file per observation date, dropping their combined daily delta from
72 MB to 226 KB. This module is that logic, extracted so other packages
adopt the same layout instead of re-deriving its sharp edges.

WHEN THIS HELPS -- and when it does not
---------------------------------------
Partitioning only pays off for an **append-only** dataset, where a run adds
new dates and leaves earlier ones untouched. Measure before adopting it: take
two consecutive committed versions, group both by the candidate column, and
count how many groups differ. Under ~15% rewritten, partitioning is a large
win. A mutable table -- one whose old rows keep changing, e.g. a job record
that later gains a ``closed_at`` -- rewrites most partitions anyway, so it
gets all the file-count overhead and none of the benefit.

THE SHARP EDGES (each one cost a debugging session)
---------------------------------------------------
* A byte-identical parquet is still a brand new git blob. An unchanged
  partition must be skipped, not rewritten, or the whole problem comes back.
* Pandas dtypes are not stable across a parquet round trip: a bool column
  read back from object dtype, or an all-present int column that was float64
  in the concatenated frame, serialize to different bytes for identical
  values. The Arrow schema is pinned so bytes depend on values alone.
* ``pa.Table.from_pandas`` records the source frame's dtypes as JSON in the
  schema metadata, and that metadata travels into the file -- enough on its
  own to make an unchanged partition produce new bytes. It is dropped.
* A partition whose rows all disappeared must be deleted, not left behind as
  a ghost that ``load`` would concatenate back in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# A null observation date is real data, not a reason to drop the row, so it
# gets an explicit bucket rather than being discarded or merged into an
# arbitrary date.
UNPARTITIONED = "__unpartitioned__"

__all__ = ["PartitionSpec", "PartitionedParquetStore", "UNPARTITIONED"]


@dataclass(frozen=True)
class PartitionSpec:
    """How one dataset maps onto partition files.

    ``column`` is the dataset's own observation date, so a run's rows land in
    one partition. ``columns`` pins both the order and the membership of the
    written schema; ``bool_columns`` and ``numeric_columns`` pin the types.
    Anything not named in those two sets is written as a string.
    """

    column: str
    columns: Sequence[str]
    bool_columns: frozenset[str] = field(default_factory=frozenset)
    numeric_columns: frozenset[str] = field(default_factory=frozenset)
    # "day" truncates an ISO value to YYYY-MM-DD, "month" to YYYY-MM. A column
    # that already holds plain dates is unaffected by "day"; an hourly column
    # needs it, or it would get one file per hour. Neither is universally
    # better --
    # measure both. A dataset with many rows per day isolates a change well at
    # day granularity, while one with few rows per day pays so much per-file
    # parquet overhead that the directory balloons for no gain:
    #
    #   openrouter_task_spend (1,750 rows/day)   day: 5.52 MB,  80 KB delta
    #                                          month: 4.04 MB, 530 KB delta
    #   daily_provider_economics (110 rows/day)  day: 5.73 MB, 136 KB delta
    #                                          month: 1.14 MB, 125 KB delta
    granularity: str = "day"

    def __post_init__(self) -> None:
        if self.column not in self.columns:
            raise ValueError(f"partition column {self.column!r} is not in the dataset columns")
        if self.granularity not in ("day", "month"):
            raise ValueError(f"granularity must be 'day' or 'month', got {self.granularity!r}")

    def arrow_schema(self) -> pa.Schema:
        fields: list[tuple[str, pa.DataType]] = []
        for name in self.columns:
            if name in self.bool_columns:
                arrow_type: pa.DataType = pa.bool_()
            elif name in self.numeric_columns:
                arrow_type = pa.float64()
            else:
                arrow_type = pa.string()
            fields.append((name, arrow_type))
        return pa.schema(fields)


class PartitionedParquetStore:
    """Read and write one dataset as a directory of date partitions."""

    def __init__(self, directory: Path, spec: PartitionSpec) -> None:
        self.directory = directory
        self.spec = spec
        self._schema = spec.arrow_schema()

    def paths(self) -> list[Path]:
        """Every partition file, oldest name first. Empty when not migrated."""
        if not self.directory.is_dir():
            return []
        return sorted(self.directory.glob("*.parquet"))

    def exists(self) -> bool:
        return bool(self.paths())

    def load(self) -> pd.DataFrame | None:
        """Concatenated frame, or None when this dataset is not partitioned yet.

        Callers treat None as "fall back to the single-file layout", which is
        what a pre-migration checkout still has.
        """
        paths = self.paths()
        if not paths:
            return None
        return pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)

    @staticmethod
    def partition_name(value: Any) -> str:
        """Filesystem-safe stem for one partition value, at day granularity."""
        if value is None or pd.isna(value) or not str(value).strip():
            return UNPARTITIONED
        # Keep the stem safe without inventing a new date format.
        return str(value).strip().replace("/", "-")

    def _name(self, value: Any) -> str:
        """Partition stem for one value under this store's granularity.

        Truncation is what makes an hourly column partition by day: EIA stores
        ``2019-01-01T00``, and one file per hour would be 67k files. A value
        that is already a plain date truncates to itself, so a date column is
        unaffected by either setting.
        """
        name = self.partition_name(value)
        if name == UNPARTITIONED:
            return name
        # Only ISO-shaped values are sliced; anything else would be cut into a
        # misleading stem that silently merges unrelated partitions.
        if len(name) < 7 or name[4] != "-":
            return name
        return name[:7] if self.spec.granularity == "month" else name[:10]

    def serialize(self, frame: pd.DataFrame) -> bytes:
        """One partition as parquet bytes under the pinned schema."""
        table = pa.Table.from_pandas(
            frame[list(self.spec.columns)], schema=self._schema, preserve_index=False
        )
        table = table.replace_schema_metadata(None)
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink)
        return sink.getvalue().to_pybytes()

    def write(self, merged: pd.DataFrame) -> list[Path]:
        """Write one file per partition value, rewriting only what changed.

        Returns the partitions that actually changed on disk -- an empty list
        means the run produced no new git blobs at all.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        names = merged[self.spec.column].map(self._name)

        written: list[Path] = []
        for name, group in merged.groupby(names, sort=True):
            path = self.directory / f"{name}.parquet"
            payload = self.serialize(group[list(self.spec.columns)].reset_index(drop=True))
            # Compare the bytes about to be written, not the frames: a frame
            # comparison answers "are these equal in pandas", while the only
            # question that matters is "would this create a new blob".
            if path.exists() and path.read_bytes() == payload:
                continue
            path.write_bytes(payload)
            written.append(path)

        keep = {f"{name}.parquet" for name in names.unique()}
        for stale in self.directory.glob("*.parquet"):
            if stale.name not in keep:
                stale.unlink()
        return written
