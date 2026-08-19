"""Immutable observation storage for market_monitor.

Mirrors the PIT philosophy of the sibling financial-data repo (immutable
run-scoped snapshots + lineage) without pulling in DuckDB. Every write lands in
``data/(raw|normalized)/market_monitor/<dataset>/<run_id>/`` with a sidecar
``lineage.json``. Derived signals live under ``data/derived/market_monitor``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .config import DERIVED_DIR, NORMALIZED_DIR, RAW_DIR


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_run_dataset(root: Path, dataset_name: str, frame: pd.DataFrame, *, metadata: Mapping[str, Any] | None = None, run_id: str | None = None) -> dict[str, str]:
    run_id = run_id or f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    target = root / dataset_name / run_id
    target.mkdir(parents=True, exist_ok=True)
    parquet_path = target / f"{dataset_name}.parquet"
    frame.to_parquet(parquet_path, index=False)
    lineage = {
        "dataset_name": dataset_name,
        "run_id": run_id,
        "created_at": _utc_now(),
        "run_scope": str(metadata.get("run_scope", "full")) if metadata and "run_scope" in metadata else "full",
        "records": int(len(frame)),
        "columns": list(frame.columns),
        "sha256": hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
    }
    if metadata:
        lineage.update({str(k): v for k, v in metadata.items()})
    lineage_path = target / "lineage.json"
    lineage_path.write_text(json.dumps(lineage, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"parquet": str(parquet_path), "run_id": run_id, "lineage": str(lineage_path)}


def save_raw(dataset_name: str, frame: pd.DataFrame, *, metadata: Mapping[str, Any] | None = None, run_id: str | None = None) -> dict[str, str]:
    """Immutable raw observation snapshot (source grain, no derived math)."""
    return _write_run_dataset(RAW_DIR, dataset_name, frame, metadata=metadata, run_id=run_id)


def save_normalized(dataset_name: str, frame: pd.DataFrame, *, metadata: Mapping[str, Any] | None = None, run_id: str | None = None) -> dict[str, str]:
    """Normalized time series (clean rows, stable IDs, source-cadenced)."""
    return _write_run_dataset(NORMALIZED_DIR, dataset_name, frame, metadata=metadata, run_id=run_id)


def save_derived(dataset_name: str, frame: pd.DataFrame, *, metadata: Mapping[str, Any] | None = None, run_id: str | None = None) -> dict[str, str]:
    """Derived research signal (technicals / relative strength / ranking)."""
    return _write_run_dataset(DERIVED_DIR, dataset_name, frame, metadata=metadata, run_id=run_id)


def new_run_id() -> str:
    """Generate a stable run id shared by every snapshot of one pipeline run."""
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


def load_latest(root: Path, dataset_name: str, scope: str | None = "full") -> pd.DataFrame:
    """Load the newest non-empty run snapshot matching scope (default 'full')."""
    dataset_dir = Path(root) / dataset_name
    if not dataset_dir.is_dir():
        return pd.DataFrame()
    # run_id directories already embed an ISO-ish timestamp (20260819T073000-…)
    # and are immutable; lexicographic descending order is therefore the
    # deterministic "newest first". mtime is not reliable on a fresh git clone
    # because every checked-out file shares the checkout mtime.
    for run in sorted(dataset_dir.iterdir(), key=lambda p: p.name, reverse=True):
        if not run.is_dir():
            continue
        parquet = run / f"{dataset_name}.parquet"
        if not parquet.exists():
            continue
        if scope is not None:
            lineage_path = run / "lineage.json"
            if lineage_path.exists():
                try:
                    meta = json.loads(lineage_path.read_text(encoding="utf-8"))
                    run_scope = meta.get("run_scope", "full")
                    if run_scope != scope:
                        continue
                except Exception:
                    continue
        frame = pd.read_parquet(parquet)
        if not frame.empty:
            return frame
    return pd.DataFrame()


def load_latest_normalized(dataset_name: str, scope: str | None = "full") -> pd.DataFrame:
    return load_latest(NORMALIZED_DIR, dataset_name, scope=scope)


def load_latest_derived(dataset_name: str, scope: str | None = "full") -> pd.DataFrame:
    return load_latest(DERIVED_DIR, dataset_name, scope=scope)
