from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from compute_availability_data.models import DatasetRecord, Snapshot


# NOTE: "compute_availability" is a legacy name. After removing AWS Spot + Lambda
# Cloud sources, this module only handles the OpenRouter model catalog.
NATURAL_KEYS: dict[str, list[str]] = {
    "raw_openrouter_models": ["model_id", "snapshot_ts"],
}

DATASET_COLUMNS = [
    "dataset_id",
    "source_url",
    "source_run_id",
    "scraped_at",
    "snapshot_ts",
    "model_id",
    "canonical_slug",
    "model_name",
    "created_at",
    "context_length",
    "architecture",
    "description",
    "hugging_face_id",
    "architecture_modality",
    "input_modalities_json",
    "output_modalities_json",
    "tokenizer",
    "instruct_type",
    "supported_parameters_json",
    "default_parameters_json",
    "per_request_limits_json",
    "pricing_prompt",
    "pricing_completion",
    "pricing_request",
    "pricing_image",
    "pricing_web_search",
    "pricing_internal_reasoning",
    "pricing_input_cache_read",
    "pricing_input_cache_write",
    "top_provider_id",
    "top_provider_context_length",
    "top_provider_max_completion_tokens",
    "top_provider_is_moderated",
    "provider_prefix",
    "expiration_date",
    "knowledge_cutoff",
    "benchmarks_json",
    "links_json",
    "reasoning_json",
    "supported_voices_json",
]

NUMERIC_COLUMNS = [
    "created_at",
    "context_length",
    "pricing_prompt",
    "pricing_completion",
    "pricing_request",
    "pricing_image",
    "pricing_web_search",
    "pricing_internal_reasoning",
    "pricing_input_cache_read",
    "pricing_input_cache_write",
    "top_provider_context_length",
    "top_provider_max_completion_tokens",
]

BOOL_COLUMNS = ["top_provider_is_moderated"]

TEXT_COLUMNS = [
    column for column in DATASET_COLUMNS if column not in NUMERIC_COLUMNS and column not in BOOL_COLUMNS
]

SORT_KEYS: dict[str, list[str]] = {
    "raw_openrouter_models": ["snapshot_ts", "model_id"],
}

OPENROUTER_CHANGE_COLUMNS = [
    column
    for column in DATASET_COLUMNS
    if column
    not in {
        "dataset_id",
        "source_url",
        "source_run_id",
        "scraped_at",
        "snapshot_ts",
        "model_id",
    }
]

MINIMUM_PRODUCTION_CATALOG_MODELS = 100
MINIMUM_PRODUCTION_PROVIDER_PREFIXES = 10
MINIMUM_PRIOR_CATALOG_RATIO = 0.60


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "compute_availability"
        self.normalized_root = base_dir / "data" / "normalized" / "compute_availability"
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
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        if parquet_path.exists():
            dataframe = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            dataframe = pd.read_csv(csv_path)
        else:
            return pd.DataFrame(columns=DATASET_COLUMNS)
        for column in DATASET_COLUMNS:
            if column not in dataframe.columns:
                dataframe[column] = pd.NA
        return dataframe[DATASET_COLUMNS]

    def load_current_catalog(self) -> pd.DataFrame:
        path = self.normalized_root / "raw_openrouter_models_current.parquet"
        if not path.exists():
            return pd.DataFrame(columns=DATASET_COLUMNS)
        dataframe = pd.read_parquet(path)
        for column in DATASET_COLUMNS:
            if column not in dataframe.columns:
                dataframe[column] = pd.NA
        return self._coerce_types(dataframe[DATASET_COLUMNS])

    @staticmethod
    def validate_current_catalog(
        incoming: pd.DataFrame,
        previous: pd.DataFrame,
        *,
        minimum_models: int = 1,
        minimum_provider_prefixes: int = 1,
    ) -> None:
        if incoming.empty:
            raise ValueError("OpenRouter Models API returned an empty catalog")
        if "model_id" not in incoming.columns or incoming["model_id"].isna().any():
            raise ValueError("OpenRouter Models API returned rows without model IDs")
        if incoming["model_id"].astype(str).duplicated().any():
            raise ValueError("OpenRouter Models API returned duplicate model IDs")

        incoming_count = int(incoming["model_id"].nunique())
        if incoming_count < minimum_models:
            raise ValueError(
                f"OpenRouter Models API returned only {incoming_count} models; expected at least {minimum_models}"
            )
        incoming_providers = int(incoming["provider_prefix"].dropna().astype(str).nunique())
        if incoming_providers < minimum_provider_prefixes:
            raise ValueError(
                "OpenRouter Models API provider coverage collapsed: "
                f"{incoming_providers} prefixes; expected at least {minimum_provider_prefixes}"
            )

        if previous.empty:
            return
        previous_count = int(previous["model_id"].dropna().astype(str).nunique())
        if previous_count >= MINIMUM_PRODUCTION_CATALOG_MODELS:
            minimum_from_history = int(previous_count * MINIMUM_PRIOR_CATALOG_RATIO)
            if incoming_count < minimum_from_history:
                raise ValueError(
                    "OpenRouter Models API catalog collapsed from "
                    f"{previous_count} to {incoming_count} models; current catalog was preserved"
                )
        previous_providers = int(previous["provider_prefix"].dropna().astype(str).nunique())
        if previous_providers >= MINIMUM_PRODUCTION_PROVIDER_PREFIXES:
            minimum_providers = max(1, int(previous_providers * MINIMUM_PRIOR_CATALOG_RATIO))
            if incoming_providers < minimum_providers:
                raise ValueError(
                    "OpenRouter Models API provider coverage collapsed from "
                    f"{previous_providers} to {incoming_providers}; current catalog was preserved"
                )

    def upsert_dataset(self, dataset_id: str, records: Iterable[DatasetRecord]) -> pd.DataFrame:
        incoming = pd.DataFrame([record.to_dict() for record in records], columns=DATASET_COLUMNS)
        if incoming.empty:
            return self.load_dataset(dataset_id)

        existing = self.load_dataset(dataset_id)
        incoming = self._coerce_types(incoming)
        if dataset_id == "raw_openrouter_models":
            # Keep a tiny authoritative current catalog alongside the compact
            # change history. The historical table intentionally drops
            # unchanged rows, so it cannot represent model removals by itself.
            previous_current = self.load_current_catalog()
            self.validate_current_catalog(incoming, previous_current)
            current = incoming.sort_values("model_id").reset_index(drop=True)
            current_path = self.normalized_root / "raw_openrouter_models_current.parquet"
            temp_path = current_path.with_suffix(".tmp")
            current.to_parquet(temp_path, index=False)
            temp_path.replace(current_path)
        existing = self._coerce_types(existing) if not existing.empty else existing
        if dataset_id == "raw_openrouter_models":
            incoming = self._filter_unchanged_openrouter_rows(existing, incoming)
            if incoming.empty:
                return existing.reset_index(drop=True)

        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
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
            dataframe[column] = dataframe[column].astype("boolean")
        for column in TEXT_COLUMNS:
            dataframe[column] = dataframe[column].astype("string")
        return dataframe

    @staticmethod
    def _filter_unchanged_openrouter_rows(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
        if incoming.empty:
            return incoming
        if existing.empty:
            return incoming

        latest_existing = (
            existing.sort_values(["model_id", "snapshot_ts"], na_position="last")
            .groupby("model_id", as_index=False)
            .tail(1)
            .set_index("model_id")
        )

        keep_indexes: list[int] = []
        for index, row in incoming.iterrows():
            model_id = row["model_id"]
            if pd.isna(model_id) or model_id not in latest_existing.index:
                keep_indexes.append(index)
                continue

            previous = latest_existing.loc[model_id]
            changed = any(not StorageManager._values_equal(row[column], previous[column]) for column in OPENROUTER_CHANGE_COLUMNS)
            if changed:
                keep_indexes.append(index)

        return incoming.loc[keep_indexes].reset_index(drop=True)

    @staticmethod
    def _values_equal(left: object, right: object) -> bool:
        if pd.isna(left) and pd.isna(right):
            return True
        if pd.isna(left) or pd.isna(right):
            return False
        return left == right
