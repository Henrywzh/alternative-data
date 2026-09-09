"""Immutable run-scoped storage for the global market-regime radar."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .config import DERIVED_DIR, NORMALIZED_DIR, RAW_DIR, RUN_RETENTION


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


def atomic_write_text(path: Path, payload: str, *, encoding: str = "utf-8") -> None:
    """Replace a text file only after its sibling temp file is fully written."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(payload, encoding=encoding)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_texts(
    payloads: Mapping[Path, str],
    *,
    encoding: str = "utf-8",
) -> None:
    """Stage a related set of files completely before publishing any of them."""
    temporary_paths: dict[Path, Path] = {}
    try:
        for raw_target, payload in payloads.items():
            target = Path(raw_target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(
                f".{target.name}.{uuid.uuid4().hex}.tmp"
            )
            temporary_paths[target] = temporary
            temporary.write_text(payload, encoding=encoding)
        for target, temporary in temporary_paths.items():
            temporary.replace(target)
    finally:
        for temporary in temporary_paths.values():
            temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_run_dataset(
    root: Path,
    dataset_name: str,
    frame: pd.DataFrame,
    *,
    metadata: Mapping[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, str]:
    run_id = run_id or new_run_id()
    target = root / dataset_name / run_id
    target.mkdir(parents=True, exist_ok=True)
    parquet_path = target / f"{dataset_name}.parquet"
    temporary_parquet = target / f".{dataset_name}.{uuid.uuid4().hex}.parquet.tmp"
    try:
        frame.to_parquet(temporary_parquet, index=False)
        temporary_parquet.replace(parquet_path)
    finally:
        temporary_parquet.unlink(missing_ok=True)
    lineage: dict[str, Any] = {}
    if metadata:
        lineage.update({str(k): v for k, v in metadata.items()})
    lineage.update(
        {
            "dataset_name": dataset_name,
            "run_id": run_id,
            "created_at": utc_now(),
            "run_scope": str(metadata.get("run_scope", "full")) if metadata and "run_scope" in metadata else "full",
            "records": int(len(frame)),
            "columns": list(frame.columns),
            "sha256": _sha256_file(parquet_path),
        }
    )
    lineage_path = target / "lineage.json"
    atomic_write_text(
        lineage_path,
        json.dumps(lineage, ensure_ascii=False, indent=2) + "\n",
    )
    return {"parquet": str(parquet_path), "run_id": run_id, "lineage": str(lineage_path)}


def save_raw(dataset_name: str, frame: pd.DataFrame, *, metadata: Mapping[str, Any] | None = None, run_id: str | None = None) -> dict[str, str]:
    return _write_run_dataset(RAW_DIR, dataset_name, frame, metadata=metadata, run_id=run_id)


def save_normalized(dataset_name: str, frame: pd.DataFrame, *, metadata: Mapping[str, Any] | None = None, run_id: str | None = None) -> dict[str, str]:
    return _write_run_dataset(NORMALIZED_DIR, dataset_name, frame, metadata=metadata, run_id=run_id)


def save_derived(dataset_name: str, frame: pd.DataFrame, *, metadata: Mapping[str, Any] | None = None, run_id: str | None = None) -> dict[str, str]:
    return _write_run_dataset(DERIVED_DIR, dataset_name, frame, metadata=metadata, run_id=run_id)


def load_latest_with_lineage(root: Path, dataset_name: str, scope: str | None = "full") -> tuple[pd.DataFrame, dict[str, Any] | None]:
    dataset_dir = Path(root) / dataset_name
    if not dataset_dir.is_dir():
        return pd.DataFrame(), None
    for run in sorted(dataset_dir.iterdir(), key=lambda p: p.name, reverse=True):
        parquet = run / f"{dataset_name}.parquet"
        lineage_path = run / "lineage.json"
        if not run.is_dir() or not parquet.exists() or not lineage_path.exists():
            continue
        try:
            lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
            if scope is not None and lineage.get("run_scope") != scope:
                continue
            if lineage.get("dataset_name") != dataset_name:
                continue
            if lineage.get("run_id") != run.name:
                continue
            expected_sha = str(lineage.get("sha256") or "")
            if len(expected_sha) != 64 or _sha256_file(parquet) != expected_sha:
                continue
            frame = pd.read_parquet(parquet)
            if not frame.empty:
                return frame, lineage
        except Exception:
            continue
    return pd.DataFrame(), None


def load_latest(root: Path, dataset_name: str, scope: str | None = "full") -> pd.DataFrame:
    frame, _ = load_latest_with_lineage(root, dataset_name, scope=scope)
    return frame


def load_latest_normalized(dataset_name: str, scope: str | None = "full") -> pd.DataFrame:
    return load_latest(NORMALIZED_DIR, dataset_name, scope=scope)


def load_latest_derived(dataset_name: str, scope: str | None = "full") -> pd.DataFrame:
    return load_latest(DERIVED_DIR, dataset_name, scope=scope)


def prune_runs(root: Path, dataset_name: str, *, keep: int = RUN_RETENTION) -> list[str]:
    dataset_dir = Path(root) / dataset_name
    if not dataset_dir.is_dir():
        return []
    runs = sorted((d for d in dataset_dir.iterdir() if d.is_dir()), key=lambda p: p.name, reverse=True)
    removed: list[str] = []
    for stale in runs[keep:]:
        shutil.rmtree(stale, ignore_errors=True)
        removed.append(stale.name)
    return removed
