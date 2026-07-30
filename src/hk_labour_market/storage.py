"""Append-only raw and normalized storage for HK labour-market data."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import NORMALIZED_DIR, RAW_DIR


def save_raw_snapshot(dataset_id: str, payload: Any, *, source_url: str, run_id: str) -> Path:
    """Save an immutable JSON response plus provenance metadata."""
    now = datetime.now(timezone.utc)
    body = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    target_dir = RAW_DIR / dataset_id / now.strftime("%Y-%m-%d")
    target_dir.mkdir(parents=True, exist_ok=True)
    snapshot_id = f"{now.strftime('%Y%m%dT%H%M%S_%fZ')}_{digest[:12]}_{uuid.uuid4().hex[:8]}"
    raw_path = target_dir / f"{snapshot_id}.json"
    raw_path.write_bytes(body)
    raw_path.with_suffix(".meta.json").write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "run_id": run_id,
                "fetched_at": now.isoformat(),
                "source_url": source_url,
                "sha256": digest,
                "content_size_bytes": len(body),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return raw_path


def save_normalized_dataset(
    dataset_id: str,
    frame: pd.DataFrame,
    *,
    run_id: str,
    raw_snapshot: Path,
    source_url: str,
    data_source: str = "official_censtatd_api",
) -> dict[str, str]:
    """Store one immutable normalized Parquet vintage and its lineage."""
    target_dir = NORMALIZED_DIR / dataset_id / run_id
    target_dir.mkdir(parents=True, exist_ok=False)
    parquet_path = target_dir / f"{dataset_id}.parquet"
    frame.to_parquet(parquet_path, index=False)
    lineage_path = target_dir / "lineage.json"
    lineage_path.write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "run_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "raw_snapshot": str(raw_snapshot),
                "source_url": source_url,
                "records": len(frame),
                "columns": list(frame.columns),
                "data_source": data_source,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"parquet": str(parquet_path), "lineage": str(lineage_path)}


def write_run_manifest(run_id: str, results: dict[str, Any]) -> Path:
    """Write one run-level audit result after every source has been attempted."""
    target_dir = NORMALIZED_DIR / "runs" / run_id
    target_dir.mkdir(parents=True, exist_ok=True)
    status = "success" if results and all(item["status"] == "success" for item in results.values()) else "failed"
    manifest_path = target_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": status,
                "datasets": results,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return manifest_path


def write_latest_run_pointer(stage_name: str, run_id: str, manifest_path: Path) -> Path:
    """Point consumers at the latest successful run without using file mtimes."""
    pointer_path = NORMALIZED_DIR / "latest_runs.json"
    current: dict[str, Any] = {}
    if pointer_path.exists():
        try:
            current = json.loads(pointer_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    current[stage_name] = {
        "run_id": run_id,
        "manifest": str(manifest_path),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    temp_path = pointer_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    temp_path.replace(pointer_path)
    return pointer_path
