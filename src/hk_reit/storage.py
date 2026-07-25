"""Raw snapshot + normalized dataset storage for the HK REIT pipeline.

Deliberately no mock/fallback-sample data path anywhere in this module or
its callers: a failed fetch must surface as an empty/failed result, never
as fabricated placeholder rows silently marked "success" (see the
hk_local_consumer pipeline review for why that matters).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union
import uuid

import pandas as pd

from .config import NORMALIZED_DIR, RAW_DIR


def _latest_snapshot_hash(source_name: str, date_str: str) -> Optional[str]:
    """Return the content hash of the most recent snapshot for this source/date, if any."""
    target_dir = RAW_DIR / source_name / date_str
    if not target_dir.exists():
        return None
    meta_files = sorted(target_dir.glob("*.meta.json"))
    if not meta_files:
        return None
    try:
        latest = json.loads(meta_files[-1].read_text(encoding="utf-8"))
        return latest.get("sha256")
    except (json.JSONDecodeError, OSError):
        return None


def save_raw_snapshot(
    source_name: str,
    content: Union[str, bytes, Dict[str, Any]],
    file_ext: str = "json",
    *,
    source_url: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Path:
    """Save an immutable raw snapshot and its provenance metadata.

    Real content-hash dedup: if the most recent snapshot for this source
    on this UTC date has an identical hash, no new file is written and the
    existing snapshot path is returned instead.
    """
    now = datetime.now(timezone.utc)
    if isinstance(content, (dict, list)):
        raw_bytes = json.dumps(content, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    elif isinstance(content, str):
        raw_bytes = content.encode("utf-8")
    elif isinstance(content, bytes):
        raw_bytes = content
    else:
        raw_bytes = json.dumps(content, ensure_ascii=False, indent=2, default=str).encode("utf-8")

    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    date_str = now.strftime("%Y-%m-%d")

    if _latest_snapshot_hash(source_name, date_str) == content_hash:
        target_dir = RAW_DIR / source_name / date_str
        existing = sorted(target_dir.glob(f"*_{content_hash[:12]}.{file_ext.lstrip('.').lower()}"))
        if existing:
            return existing[-1]

    timestamp_str = now.strftime("%Y%m%dT%H%M%S_%fZ")
    file_ext_clean = file_ext.lstrip(".").lower()
    snapshot_id = f"{timestamp_str}_{content_hash[:12]}"
    target_dir = RAW_DIR / source_name / date_str
    target_dir.mkdir(parents=True, exist_ok=True)
    raw_path = target_dir / f"{snapshot_id}.{file_ext_clean}"
    meta_path = target_dir / f"{snapshot_id}.meta.json"

    with open(raw_path, "wb") as f:
        f.write(raw_bytes)

    metadata = {
        "source_name": source_name,
        "fetched_at": now.isoformat(),
        "run_id": run_id,
        "source_url": source_url,
        "file_extension": file_ext_clean,
        "content_size_bytes": len(raw_bytes),
        "sha256": content_hash,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return raw_path


def save_normalized_dataset(
    dataset_name: str,
    df: pd.DataFrame,
    *,
    run_id: Optional[str] = None,
    raw_snapshot: Optional[str] = None,
    source_url: Optional[str] = None,
) -> Dict[str, str]:
    """Save normalized output as an immutable run-scoped dataset with lineage."""
    run_id = run_id or str(uuid.uuid4())
    target_dir = NORMALIZED_DIR / dataset_name / run_id
    target_dir.mkdir(parents=True, exist_ok=False)
    parquet_path = target_dir / f"{dataset_name}.parquet"

    df.to_parquet(parquet_path, index=False)

    lineage_path = target_dir / "lineage.json"
    with open(lineage_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "dataset_name": dataset_name,
                "run_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "raw_snapshot": raw_snapshot,
                "source_url": source_url,
                "records": len(df),
                "columns": list(df.columns),
            },
            f,
            indent=2,
        )

    return {
        "parquet": str(parquet_path),
        "lineage": str(lineage_path),
        "run_id": run_id,
        "raw_snapshot": raw_snapshot,
    }


def latest_run_dir(dataset_name: str) -> Optional[Path]:
    """Resolve the most recently-created run directory for a normalized dataset."""
    root = NORMALIZED_DIR / dataset_name
    if not root.exists():
        return None
    candidates = [p for p in root.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)
