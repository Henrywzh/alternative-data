"""One atomic-write primitive for every mart this package publishes.

Every writer here targets a path that other processes — a concurrent test
worker, a Streamlit reader, the next pipeline stage — may read at any moment.
A plain ``to_parquet``/``to_csv`` truncates the destination first and fills it
afterwards, so a reader that arrives inside that window sees a zero-length or
half-written file.  Writing to a sibling temporary file and ``os.replace``-ing
it into place makes the swap atomic on POSIX and Windows alike: a reader sees
either the whole previous version or the whole new one, never a partial file.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def atomic_replace(target_path: Path, write: Callable[[Path], Any]) -> Path:
    """Run ``write`` against a temporary sibling, then swap it into place."""

    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.", suffix=".tmp", dir=target_path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        write(temporary_path)
        os.replace(temporary_path, target_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return target_path


def write_parquet_atomic(
    frame: pd.DataFrame,
    output_path: Path,
    *,
    schema: pa.Schema | None = None,
) -> Path:
    """Write a frame to parquet atomically.

    When ``schema`` is supplied the frame's columns must match it exactly, so
    a contract-bearing mart cannot drift its schema between runs; without one
    the frame's own dtypes are used.
    """

    if schema is not None:
        expected = [field.name for field in schema]
        if list(frame.columns) != expected:
            raise ValueError(f"invalid output columns for {Path(output_path).name}")
        table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
        return atomic_replace(output_path, lambda path: pq.write_table(table, path))
    return atomic_replace(
        output_path, lambda path: frame.to_parquet(path, index=False)
    )


def write_csv_atomic(frame: pd.DataFrame, output_path: Path, **kwargs: Any) -> Path:
    """Write a frame to CSV atomically; ``index=False`` unless overridden."""

    kwargs.setdefault("index", False)
    return atomic_replace(output_path, lambda path: frame.to_csv(path, **kwargs))


__all__ = ["atomic_replace", "write_csv_atomic", "write_parquet_atomic"]
