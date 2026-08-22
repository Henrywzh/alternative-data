"""Storage utilities for HK Transport Sector Data."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .config import NORMALIZED_DIR, RAW_DIR


def atomic_replace(target_path: Path, write: Callable[[Path], Any]) -> Path:
    """Run ``write`` against a temporary sibling, then swap it into place.

    Normalized outputs here are tracked files that other processes read while
    a build is running — a Streamlit page, the next pipeline stage, or another
    pytest-xdist worker.  ``DataFrame.to_csv`` truncates the destination first
    and fills it afterwards, so a reader arriving inside that window sees an
    empty or half-written file.  Writing to a sibling temporary file and
    ``os.replace``-ing it makes the swap atomic: readers see either the whole
    previous version or the whole new one.
    """

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


def write_csv_atomic(frame: pd.DataFrame, target_path: Path, **kwargs: Any) -> Path:
    """Write a frame to CSV atomically; ``index=False`` unless overridden."""

    kwargs.setdefault("index", False)
    return atomic_replace(target_path, lambda path: frame.to_csv(path, **kwargs))


def save_raw_snapshot(
    dataset_name: str,
    payload: Any,
    *,
    file_ext: str = "json",
    source_url: str | None = None,
) -> Path:
    """Save raw data snapshot with metadata timestamp."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    file_path = RAW_DIR / f"{dataset_name}_{timestamp}.{file_ext}"

    if file_ext == "json":
        meta_payload = {
            "dataset": dataset_name,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source_url": source_url,
            "data": payload,
        }
        file_path.write_text(json.dumps(meta_payload, indent=2, default=str), encoding="utf-8")
    else:
        file_path.write_bytes(payload)

    return file_path
