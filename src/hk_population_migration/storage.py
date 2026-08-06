import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import RAW_DIR, NORMALIZED_DIR


def save_raw_snapshot(dataset_name: str, content: bytes | str, file_ext: str = "json", source_url: str | None = None) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{dataset_name}_{timestamp}.{file_ext}"
    target_path = RAW_DIR / filename

    if isinstance(content, str):
        target_path.write_text(content, encoding="utf-8")
    else:
        target_path.write_bytes(content)

    meta_path = RAW_DIR / f"{filename}.meta.json"
    meta = {
        "dataset_name": dataset_name,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "source_url": source_url,
        "file_bytes": len(content.encode("utf-8") if isinstance(content, str) else content),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return target_path


def save_normalized_dataset(
    dataset_name: str,
    frame: pd.DataFrame,
    *,
    run_id: str,
    source_url: str | None = None,
) -> Path:
    """Persist a run-scoped normalized dataset with minimal provenance."""
    target_dir = NORMALIZED_DIR / dataset_name / run_id
    target_dir.mkdir(parents=True, exist_ok=False)
    dataset_path = target_dir / f"{dataset_name}.parquet"
    frame.to_parquet(dataset_path, index=False)
    (target_dir / "lineage.json").write_text(
        json.dumps(
            {
                "dataset_name": dataset_name,
                "run_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_url": source_url,
                "records": len(frame),
                "columns": list(frame.columns),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return dataset_path


def load_latest_normalized(dataset_name: str) -> pd.DataFrame:
    """Load the most recent normalized run for a dataset that actually has rows.

    A run whose live fetch legitimately returned zero rows (upstream outage,
    schema change) still gets a fresh timestamped directory. Picking by mtime
    alone would let that empty run permanently shadow the last good snapshot,
    so skip empty runs and fall back to the newest non-empty one instead.
    """
    dataset_dir = NORMALIZED_DIR / dataset_name
    if not dataset_dir.is_dir():
        return pd.DataFrame()
    run_dirs = [path for path in dataset_dir.iterdir() if path.is_dir()]
    if not run_dirs:
        return pd.DataFrame()
    for candidate in sorted(run_dirs, key=lambda path: path.stat().st_mtime, reverse=True):
        dataset_path = candidate / f"{dataset_name}.parquet"
        if not dataset_path.exists():
            continue
        frame = pd.read_parquet(dataset_path)
        if not frame.empty:
            return frame
    return pd.DataFrame()
