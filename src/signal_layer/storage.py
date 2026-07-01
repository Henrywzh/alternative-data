from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd


class SignalLayerStorage:
    MANIFEST_NAME = "latest_signal_run.json"

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.processed_root = self.base_dir / "data" / "processed" / "signals"
        self.processed_root.mkdir(parents=True, exist_ok=True)

    def create_run_dir(self, run_id: str) -> Path:
        target_dir = self.processed_root / run_id
        target_dir.mkdir(parents=True, exist_ok=False)
        return target_dir

    def latest_dir(self) -> Path:
        return self.processed_root / "latest"

    def write_dataset(
        self,
        dataset_name: str,
        frame: pd.DataFrame,
        *,
        target_dir: str | Path | None = None,
    ) -> Path:
        destination = Path(target_dir) if target_dir is not None else self.processed_root
        destination.mkdir(parents=True, exist_ok=True)
        csv_path = destination / f"{dataset_name}.csv"
        parquet_path = destination / f"{dataset_name}.parquet"
        frame.to_csv(csv_path, index=False)
        frame.to_parquet(parquet_path, index=False)
        return csv_path

    def write_run_manifest(
        self,
        manifest: dict[str, Any],
        *,
        target_dir: str | Path | None = None,
    ) -> Path:
        destination = Path(target_dir) if target_dir is not None else self.processed_root
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / self.MANIFEST_NAME
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def update_latest(self, run_dir: str | Path) -> Path:
        source_dir = Path(run_dir)
        latest_dir = self.latest_dir()
        staging_dir = Path(
            tempfile.mkdtemp(prefix=f".latest-{source_dir.name}-", dir=self.processed_root)
        )
        try:
            shutil.copytree(source_dir, staging_dir, dirs_exist_ok=True)
            if latest_dir.exists():
                shutil.rmtree(latest_dir)
            staging_dir.replace(latest_dir)
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
        return latest_dir
