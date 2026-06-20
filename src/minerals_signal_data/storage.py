from __future__ import annotations

from pathlib import Path

import pandas as pd


class MineralsSignalStorage:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.processed_root = self.base_dir / "data" / "processed" / "minerals_signal_data"
        self.processed_root.mkdir(parents=True, exist_ok=True)

    def write_dataset(self, dataset_name: str, frame: pd.DataFrame, *, run_label: str = "latest") -> Path:
        target_dir = self.processed_root / dataset_name / run_label
        target_dir.mkdir(parents=True, exist_ok=True)
        csv_path = target_dir / f"{dataset_name}.csv"
        parquet_path = target_dir / f"{dataset_name}.parquet"
        frame.to_csv(csv_path, index=False)
        frame.to_parquet(parquet_path, index=False)
        return csv_path

    def output_path(self, dataset_name: str, *, run_label: str = "latest", file_name: str) -> Path:
        target_dir = self.processed_root / dataset_name / run_label
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / file_name
