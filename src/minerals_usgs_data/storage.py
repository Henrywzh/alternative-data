from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pandas as pd

from minerals_usgs_data.models import (
    MineralApplicationRecord,
    MineralMasterRecord,
    MineralMetricRecord,
)

MASTER_COLUMNS = [field.name for field in fields(MineralMasterRecord)]
APPLICATION_COLUMNS = [field.name for field in fields(MineralApplicationRecord)]
METRIC_COLUMNS = [field.name for field in fields(MineralMetricRecord)]


class MineralsStorage:
    def __init__(self, base_dir: Path, *, report_year: int) -> None:
        self.base_dir = Path(base_dir)
        self.report_year = str(report_year)
        self.raw_root = self.base_dir / "data" / "raw" / "minerals_usgs" / self.report_year
        self.processed_root = self.base_dir / "data" / "processed" / "minerals_usgs" / self.report_year
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.processed_root.mkdir(parents=True, exist_ok=True)

    def write_raw_text(self, *, file_name: str, text: str) -> Path:
        path = self.raw_root / file_name
        path.write_text(text, encoding="utf-8")
        return path

    def write_all(
        self,
        *,
        master_records: list[MineralMasterRecord],
        application_records: list[MineralApplicationRecord],
        metric_records: list[MineralMetricRecord],
    ) -> dict[str, Path]:
        return {
            "minerals_master_csv": self._write_frame("minerals_master", master_records, MASTER_COLUMNS),
            "mineral_applications_csv": self._write_frame(
                "mineral_applications",
                application_records,
                APPLICATION_COLUMNS,
            ),
            "mineral_metrics_csv": self._write_frame("mineral_metrics", metric_records, METRIC_COLUMNS),
        }

    def _write_frame(self, dataset_name: str, records: list[object], columns: list[str]) -> Path:
        rows = [record.to_dict() for record in records]
        frame = pd.DataFrame(rows, columns=columns)
        if dataset_name == "mineral_metrics" and not frame.empty and "metric_value" in frame.columns:
            non_null_values = frame["metric_value"].dropna()
            has_string_value = any(isinstance(value, str) for value in non_null_values)
            has_non_string_value = any(not isinstance(value, str) for value in non_null_values)
            if has_string_value and has_non_string_value:
                frame["metric_value"] = frame["metric_value"].map(
                    lambda value: None if pd.isna(value) else str(value)
                )
        csv_path = self.processed_root / f"{dataset_name}.csv"
        parquet_path = self.processed_root / f"{dataset_name}.parquet"
        frame.to_csv(csv_path, index=False)
        frame.to_parquet(parquet_path, index=False)
        return csv_path
