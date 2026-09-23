"""Storage utilities for HK Stablecoin & Crypto Sector Data."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import NORMALIZED_DIR, RAW_DIR


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


def save_normalized_frame(dataset_name: str, frame, *, source: str, extra: dict | None = None) -> Path:
    """Persist a compact parquet cache plus a small JSON manifest."""
    import pandas as pd

    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = NORMALIZED_DIR / f"{dataset_name}.parquet"
    manifest_path = NORMALIZED_DIR / f"{dataset_name}_manifest.json"
    fetched_at = datetime.now(timezone.utc).isoformat()
    payload = frame.copy() if frame is not None else pd.DataFrame()
    payload.to_parquet(parquet_path, index=False)
    latest = None
    if not payload.empty and "date" in payload.columns:
        latest = str(pd.to_datetime(payload["date"], errors="coerce").max().date())
    manifest = {
        "dataset": dataset_name,
        "source": source,
        "fetched_at": fetched_at,
        "rows": int(len(payload)),
        "latest_date": latest,
    }
    if extra:
        manifest.update(extra)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    return parquet_path


def load_latest_normalized_frame(dataset_name: str):
    """Load the committed parquet cache if it exists."""
    import pandas as pd

    parquet_path = NORMALIZED_DIR / f"{dataset_name}.parquet"
    if not parquet_path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_parquet(parquet_path)
    except Exception:
        return pd.DataFrame()
    return frame if frame is not None else pd.DataFrame()
