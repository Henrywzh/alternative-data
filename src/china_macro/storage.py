"""A single validated generation, not independently selected latest datasets."""
import hashlib
import json
from pathlib import Path
import uuid

import pandas as pd

from .config import DATA_DIR
from .normalize import clean


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def load_current(root: Path = DATA_DIR):
    pointer = root / "CURRENT.json"
    if not pointer.exists():
        return clean([]), clean([]), {}
    manifest = json.loads(pointer.read_text())
    run_id = manifest["run_id"]
    if not isinstance(run_id, str) or not run_id.replace("-", "").replace("T", "").isalnum():
        raise ValueError("Invalid China macro run id")
    frames = []
    for name in ["observations", "signals"]:
        path = root / "runs" / run_id / (name + ".parquet")
        if digest(path) != manifest["sha256"][name]:
            raise ValueError(f"China macro {name} integrity mismatch")
        frames.append(pd.read_parquet(path))
    return *frames, manifest


def save_current(observations, signals, manifest, root: Path = DATA_DIR) -> None:
    if observations.empty:
        raise ValueError("Refusing to publish an empty China macro snapshot")
    directory = root / "runs" / manifest["run_id"]
    directory.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name, frame in [("observations", observations), ("signals", signals)]:
        path = directory / (name + ".parquet")
        frame.to_parquet(path, index=False)
        hashes[name] = digest(path)
    manifest = {**manifest, "sha256": hashes, "records": {"observations": len(observations), "signals": len(signals)}}
    atomic_json(directory / "manifest.json", manifest)
    atomic_json(root / "CURRENT.json", manifest)
