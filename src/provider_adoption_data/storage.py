from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from provider_adoption_data.models import DatasetRecord, Snapshot


NATURAL_KEYS: dict[str, list[str]] = {
    "pypi_downloads_daily": ["provider", "package_name", "with_mirrors", "download_date"],
    "github_repo_candidates_daily": ["provider", "repo_full_name", "repo_created_date"],
    "github_provider_signals_daily": ["provider", "repo_full_name", "signal_date", "signal_type"],
    "github_repo_rollup_daily": ["provider", "repo_full_name", "signal_date"],
    "provider_momentum_daily": ["provider", "signal_date"],
}

DATASET_COLUMNS = [
    "dataset_id",
    "source_url",
    "source_run_id",
    "scraped_at",
    "provider",
    "provider_display_name",
    "package_name",
    "package_type",
    "with_mirrors",
    "download_date",
    "downloads",
    "repo_full_name",
    "repo_owner",
    "repo_name",
    "repo_html_url",
    "repo_created_date",
    "repo_created_at",
    "repo_pushed_at",
    "repo_default_branch",
    "language_bucket",
    "signal_date",
    "signal_type",
    "matched_file_path",
    "matched_pattern",
    "is_fork",
    "is_archived",
    "stargazers_count",
    "has_manifest_dependency",
    "has_code_import",
    "has_env_var",
    "has_model_name",
    "matched_signal_count",
    "pypi_7d_avg",
    "pypi_28d_avg",
    "pypi_share_28d",
    "pypi_growth_28d",
    "github_new_repo_count",
    "github_repo_share",
    "github_import_repo_count",
    "github_env_repo_count",
    "github_model_repo_count",
    "momentum_score",
]

NUMERIC_COLUMNS = [
    "downloads",
    "stargazers_count",
    "matched_signal_count",
    "pypi_7d_avg",
    "pypi_28d_avg",
    "pypi_share_28d",
    "pypi_growth_28d",
    "github_new_repo_count",
    "github_repo_share",
    "github_import_repo_count",
    "github_env_repo_count",
    "github_model_repo_count",
    "momentum_score",
]

BOOL_COLUMNS = [
    "with_mirrors",
    "is_fork",
    "is_archived",
    "has_manifest_dependency",
    "has_code_import",
    "has_env_var",
    "has_model_name",
]

TEXT_COLUMNS = [
    column for column in DATASET_COLUMNS if column not in NUMERIC_COLUMNS and column not in BOOL_COLUMNS
]

SORT_KEYS: dict[str, list[str]] = {
    "pypi_downloads_daily": ["download_date", "provider", "package_name", "with_mirrors"],
    "github_repo_candidates_daily": ["repo_created_date", "provider", "repo_full_name"],
    "github_provider_signals_daily": ["signal_date", "provider", "repo_full_name", "signal_type"],
    "github_repo_rollup_daily": ["signal_date", "provider", "repo_full_name"],
    "provider_momentum_daily": ["signal_date", "provider"],
}


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "provider_adoption"
        self.normalized_root = base_dir / "data" / "normalized" / "provider_adoption"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_run(self, run_id: str, snapshots: Iterable[Snapshot], manifest: dict[str, Any]) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            suffix = ".json" if snapshot.body.strip().startswith(("{", "[")) else ".txt"
            (run_dir / f"{snapshot.name}{suffix}").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir

    def load_dataset(self, dataset_id: str) -> pd.DataFrame:
        csv_path = self.normalized_root / f"{dataset_id}.csv"
        if not csv_path.exists():
            return pd.DataFrame(columns=DATASET_COLUMNS)
        dataframe = pd.read_csv(csv_path)
        for column in DATASET_COLUMNS:
            if column not in dataframe.columns:
                dataframe[column] = pd.NA
        return dataframe[DATASET_COLUMNS]

    def upsert_dataset(self, dataset_id: str, records: Iterable[DatasetRecord]) -> pd.DataFrame:
        incoming = pd.DataFrame([record.to_dict() for record in records], columns=DATASET_COLUMNS)
        if incoming.empty:
            return self.load_dataset(dataset_id)

        existing = self.load_dataset(dataset_id)
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        merged = self._coerce_types(merged)
        merged = merged.drop_duplicates(subset=NATURAL_KEYS[dataset_id], keep="last")
        merged = merged.sort_values(by=SORT_KEYS[dataset_id], na_position="last").reset_index(drop=True)

        csv_path = self.normalized_root / f"{dataset_id}.csv"
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        merged.to_csv(csv_path, index=False)
        merged.to_parquet(parquet_path, index=False)
        return merged

    @staticmethod
    def _coerce_types(dataframe: pd.DataFrame) -> pd.DataFrame:
        for column in NUMERIC_COLUMNS:
            dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")
        for column in BOOL_COLUMNS:
            dataframe[column] = dataframe[column].map(
                lambda value: value
                if pd.isna(value) or isinstance(value, bool)
                else str(value).strip().lower() == "true"
            )
        for column in TEXT_COLUMNS:
            dataframe[column] = dataframe[column].astype("string")
        return dataframe
