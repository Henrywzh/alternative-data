"""Small, immutable-ish helpers for raw public-data snapshots.

The source packages intentionally own parsing and normalized schemas.  This
module only owns the boring but important audit layer shared by the one-shot
backfill runner: raw bytes, content hashes, source URLs, and a run manifest.
All paths are relative to a source-specific ``data/raw`` directory and are
validated so a malformed URL-derived filename cannot escape the run folder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"raw artifact path must remain inside the run directory: {name!r}")
    if not relative.name:
        raise ValueError("raw artifact path must contain a filename")
    return relative


@dataclass
class RawSnapshotRun:
    """Write source snapshots and collect a machine-readable coverage manifest."""

    root: Path
    run_id: str
    source: str
    entries: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.run_dir = self.root / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, name: str) -> Path:
        relative = _safe_relative_path(name)
        path = self.run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write_bytes(
        self,
        name: str,
        payload: bytes,
        *,
        source_url: str | None = None,
        status_code: int | None = None,
        rows: int | None = None,
        coverage: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        gzip_payload: bool = False,
    ) -> Path:
        relative = _safe_relative_path(name)
        stored_payload = gzip.compress(payload, mtime=0) if gzip_payload else payload
        if gzip_payload and relative.suffix != ".gz":
            relative = Path(f"{relative}.gz")
        path = self.run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(stored_payload)
        self.entries.append(
            {
                "path": str(path.relative_to(self.root)),
                "source_url": source_url,
                "status_code": status_code,
                "byte_size": len(stored_payload),
                "payload_sha256": sha256_bytes(payload),
                "stored_sha256": sha256_bytes(stored_payload),
                "gzip_payload": gzip_payload,
                "rows": rows,
                "coverage": dict(coverage or {}),
                "metadata": dict(metadata or {}),
                "captured_at_utc": utc_now(),
            }
        )
        return path

    def write_json(self, name: str, value: Any, **kwargs: Any) -> Path:
        payload = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")
        return self.write_bytes(name if name.endswith(".json") else f"{name}.json", payload, **kwargs)

    def record_existing_file(
        self,
        name: str,
        *,
        source_url: str | None = None,
        status_code: int | None = None,
        rows: int | None = None,
        coverage: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Path:
        """Record a file already streamed into this run directory.

        Large official bulk files should not be copied into a second in-memory
        bytes object merely to calculate an audit hash.  The caller writes to
        ``path_for(name)`` (or the returned run path) and then records it here.
        """
        relative = _safe_relative_path(name)
        path = self.run_dir / relative
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(path)
        self.entries.append(
            {
                "path": str(path.relative_to(self.root)),
                "source_url": source_url,
                "status_code": status_code,
                "byte_size": path.stat().st_size,
                "payload_sha256": sha256_file(path),
                "stored_sha256": sha256_file(path),
                "gzip_payload": False,
                "rows": rows,
                "coverage": dict(coverage or {}),
                "metadata": dict(metadata or {}),
                "captured_at_utc": utc_now(),
            }
        )
        return path

    def finalize(
        self,
        *,
        status: str,
        errors: Mapping[str, Any] | None = None,
        normalized_outputs: Mapping[str, Any] | None = None,
        coverage: Mapping[str, Any] | None = None,
    ) -> Path:
        manifest = {
            "manifest_version": "free_public_data_snapshot.v1",
            "source": self.source,
            "run_id": self.run_id,
            "started_at_utc": self.entries[0]["captured_at_utc"] if self.entries else utc_now(),
            "finished_at_utc": utc_now(),
            "status": status,
            "errors": dict(errors or {}),
            "coverage": dict(coverage or {}),
            "normalized_outputs": dict(normalized_outputs or {}),
            "entries": self.entries,
        }
        path = self.run_dir / "manifest.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        temporary.replace(path)
        return path
