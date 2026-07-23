"""Storage utilities for HK Utilities Sector Data."""

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
