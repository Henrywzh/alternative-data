from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


class SignalLayerStorage:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.processed_root = self.base_dir / "data" / "processed" / "signals"
        self.processed_root.mkdir(parents=True, exist_ok=True)

    def write_dataset(self, dataset_name: str, frame: pd.DataFrame) -> Path:
        self.processed_root.mkdir(parents=True, exist_ok=True)
        csv_path = self.processed_root / f"{dataset_name}.csv"
        parquet_path = self.processed_root / f"{dataset_name}.parquet"
        frame.to_csv(csv_path, index=False)
        frame.to_parquet(parquet_path, index=False)
        return csv_path

    def write_run_manifest(self, manifest: dict[str, Any]) -> Path:
        path = self.processed_root / "latest_signal_run.json"
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        return path
