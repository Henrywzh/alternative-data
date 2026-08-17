"""Deterministic, additive storage for unified backtest runs.

This is a new contract for derived backtest artifacts.  It intentionally does
not change ``src.hk_real_estate.storage`` or any existing ingestion writer.
Existing sector run IDs remain untouched; the engine records their source
fingerprints and parent run IDs in its own manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .vocabulary import METRIC_POLICY_VERSION


def _json_default(value: Any) -> str:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataframe_fingerprint(frame: pd.DataFrame) -> str:
    """Return a row-order-independent fingerprint for schema and values."""
    ordered = frame.copy().reindex(sorted(frame.columns, key=str), axis=1)
    records = json.loads(ordered.to_json(orient="records", date_format="iso", date_unit="ns", double_precision=15))
    canonical_rows = sorted(canonical_json(record) for record in records)
    schema = [(str(column), str(ordered[column].dtype)) for column in ordered.columns]
    payload = {
        "columns": schema,
        "rows": canonical_rows,
    }
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


@dataclass(frozen=True)
class BacktestRunSpec:
    engine_version: str
    config: Mapping[str, Any]
    input_fingerprints: Mapping[str, str]
    parent_run_ids: tuple[str, ...] = ()

    @property
    def run_id(self) -> str:
        payload = {
            "engine_version": self.engine_version,
            "config": dict(self.config),
            "input_fingerprints": dict(sorted(self.input_fingerprints.items())),
            "parent_run_ids": sorted(self.parent_run_ids),
        }
        return f"{self.engine_version}-{sha256_bytes(canonical_json(payload).encode('utf-8'))[:16]}"


class RunArtifactStore:
    """Write one immutable-ish run directory plus a stable latest pointer."""

    def __init__(self, root: Path, spec: BacktestRunSpec) -> None:
        self.root = Path(root)
        self.spec = spec
        self.run_dir = self.root / spec.run_id

    def _atomic_write_bytes(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = path.read_bytes()
            if existing == content:
                return
            raise FileExistsError(
                f"immutable run artifact already exists with different content: {path}"
            )
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            handle.write(content)
            temp_name = handle.name
        os.replace(temp_name, path)

    def write_dataframe(self, name: str, frame: pd.DataFrame) -> Path:
        path = self.run_dir / f"{name}.csv"
        content = frame.to_csv(index=False).encode("utf-8")
        self._atomic_write_bytes(path, content)
        return path

    def write_parquet(self, name: str, frame: pd.DataFrame) -> Path:
        """Write a parquet companion using the same atomic-write discipline."""
        path = self.run_dir / f"{name}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = pd.read_parquet(path)
            if dataframe_fingerprint(existing) == dataframe_fingerprint(frame):
                return path
            raise FileExistsError(
                f"immutable run artifact already exists with different content: {path}"
            )
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".parquet", delete=False) as handle:
            temp_name = Path(handle.name)
        try:
            frame.to_parquet(temp_name, index=False)
            os.replace(temp_name, path)
        finally:
            temp_name.unlink(missing_ok=True)
        return path

    def write_json(self, name: str, payload: Mapping[str, Any]) -> Path:
        path = self.run_dir / f"{name}.json"
        content = (json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n").encode("utf-8")
        if path.exists():
            existing = path.read_bytes()
            if existing == content:
                return path
            raise FileExistsError(
                f"immutable run artifact already exists with different content: {path}"
            )
        self._atomic_write_bytes(path, content)
        return path

    def write_manifest(
        self,
        *,
        artifacts: Mapping[str, Path],
        counts: Mapping[str, int],
        caveats: list[str],
        status: str = "ready",
    ) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        existing = self.run_dir / "manifest.json"
        artifact_entries: dict[str, dict[str, Any]] = {}
        for name, path in sorted(artifacts.items()):
            if not path.exists():
                raise FileNotFoundError(f"manifest artifact does not exist: {path}")
            artifact_entries[name] = {
                "path": str(path.relative_to(self.run_dir)),
                "sha256": file_fingerprint(path),
                "bytes": int(path.stat().st_size),
            }
        created_at = datetime.now(timezone.utc).isoformat()
        manifest = {
            "engine_version": self.spec.engine_version,
            "run_id": self.spec.run_id,
            "created_at": created_at,
            "status": status,
            "config": dict(self.spec.config),
            "input_fingerprints": dict(sorted(self.spec.input_fingerprints.items())),
            "parent_run_ids": list(self.spec.parent_run_ids),
            "artifacts": artifact_entries,
            "schema": {
                "long_form": str(self.spec.config.get("schema", "asia_backtest_long_form_v1")),
                "metrics": METRIC_POLICY_VERSION,
            },
            "runtime": runtime_metadata(),
            "counts": dict(counts),
            "caveats": caveats,
            "model_calculation_changed": False,
            "dashboard_changed": False,
            "wide_tables_replaced": False,
        }
        if existing.exists():
            prior = json.loads(existing.read_text(encoding="utf-8"))
            comparable_prior = dict(prior)
            comparable_current = dict(manifest)
            comparable_current["created_at"] = comparable_prior.get("created_at")
            if comparable_prior != comparable_current:
                raise FileExistsError(
                    f"immutable run manifest already exists with different content: {existing}"
                )
            return existing
        return self.write_json("manifest", manifest)

    def write_latest_pointer(self, manifest_path: Path) -> Path:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "ready":
            raise ValueError(f"refusing to point latest at non-ready run: {manifest_path}")
        pointer = self.root.parent / "asia_backtest_latest.json"
        payload = {
            "run_id": self.spec.run_id,
            "manifest": str(manifest_path.relative_to(pointer.parent)),
            "engine_version": self.spec.engine_version,
        }
        content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        # This file is an index, not an immutable run artifact.  It must move
        # atomically when a newer validated run becomes current.
        pointer.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=pointer.parent, delete=False) as handle:
            handle.write(content)
            temp_name = handle.name
        os.replace(temp_name, pointer)
        return pointer


def _pyarrow_version() -> str:
    try:
        import pyarrow

        return str(pyarrow.__version__)
    except Exception:
        return "unavailable"


def runtime_metadata() -> dict[str, str]:
    """Return the runtime identity that can affect derived artifacts."""
    return {
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "pyarrow": _pyarrow_version(),
        "platform": platform.platform(),
    }
