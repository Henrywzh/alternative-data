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

CATALOG_SIZE_DATASET = "openrouter_catalog_size"

# Catalog size cannot be derived from raw_openrouter_models: that table is
# change-only (see _filter_unchanged_openrouter_rows), so a live snapshot's
# row count is "models that changed today", not the catalog. This tiny
# sidecar records the true size at the one moment we hold the complete
# response -- the incoming frame, before change filtering.
#
# Two counts, because the two capture sources see different catalogs. The
# live pipeline requests ?output_modalities=all; Wayback archived the bare
# URL, whose default response only includes models that can output text. The
# text-output count is therefore the only level-comparable series across the
# whole history; model_count_all exists for live captures only.
CATALOG_SIZE_COLUMNS = [
    "snapshot_ts",
    "source_run_id",
    "capture_source",
    "model_count_all",
    "model_count_text_output",
    "provider_count",
]

CAPTURE_SOURCE_LIVE = "live_api"
CAPTURE_SOURCE_WAYBACK = "wayback_archive"

# The live catalog has run 336-524 models across every genuinely healthy
# fetch on record. 100 (the original floor) was low enough that a badly
# degraded-but-nonempty response -- observed in production between
# 2026-04-17 and 2026-08-08, ranging 1-223 models per day, likely a CDN/
# network issue specific to the CI runner's requests, not an auth problem
# (reproduced healthy 524-model responses locally both with and without the
# real API key) -- could still clear it and get written as if it were a
# real catalog. 250 sits safely below every healthy count observed and
# above every broken one, so it actually catches this failure mode instead
# of just documenting it.
MINIMUM_PRODUCTION_CATALOG_MODELS = 250
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

    def load_catalog_size(self) -> pd.DataFrame:
        path = self.normalized_root / f"{CATALOG_SIZE_DATASET}.parquet"
        if not path.exists():
            return pd.DataFrame(columns=CATALOG_SIZE_COLUMNS)
        frame = pd.read_parquet(path)
        for column in CATALOG_SIZE_COLUMNS:
            if column not in frame.columns:
                frame[column] = pd.NA
        return frame[CATALOG_SIZE_COLUMNS]

    def record_catalog_size(
        self,
        frame: pd.DataFrame,
        *,
        capture_source: str = CAPTURE_SOURCE_LIVE,
    ) -> pd.DataFrame:
        """Record the catalog size of one complete, unfiltered catalog response.

        `frame` must be a full catalog pull, not a change-filtered batch --
        this is the only point in the write path where the whole response is
        still in hand.
        """
        rows = self._catalog_size_rows(frame, capture_source=capture_source)
        return self.append_catalog_size(rows)

    def append_catalog_size(self, rows: pd.DataFrame) -> pd.DataFrame:
        existing = self.load_catalog_size()
        if rows.empty:
            return existing
        merged = pd.concat([existing, rows], ignore_index=True) if not existing.empty else rows.copy()
        merged = merged.drop_duplicates(subset=["snapshot_ts", "capture_source"], keep="last")
        merged = merged.sort_values("snapshot_ts").reset_index(drop=True)
        merged = merged[CATALOG_SIZE_COLUMNS]

        parquet_path = self.normalized_root / f"{CATALOG_SIZE_DATASET}.parquet"
        temp_path = parquet_path.with_suffix(".tmp")
        merged.to_parquet(temp_path, index=False)
        temp_path.replace(parquet_path)
        merged.to_csv(self.normalized_root / f"{CATALOG_SIZE_DATASET}.csv", index=False)
        return merged

    @staticmethod
    def _catalog_size_rows(frame: pd.DataFrame, *, capture_source: str) -> pd.DataFrame:
        if frame.empty or "model_id" not in frame.columns:
            return pd.DataFrame(columns=CATALOG_SIZE_COLUMNS)

        rows: list[dict[str, Any]] = []
        for snapshot_ts, group in frame.groupby("snapshot_ts", sort=True):
            models = group.drop_duplicates("model_id")
            all_count = int(models["model_id"].nunique())
            text_count = StorageManager._text_output_model_count(models)
            rows.append(
                {
                    "snapshot_ts": str(snapshot_ts),
                    "source_run_id": str(group["source_run_id"].iloc[0]) if "source_run_id" in group else None,
                    "capture_source": capture_source,
                    # A Wayback capture of the bare URL never contained the
                    # non-text-output models in the first place, so its total
                    # is a text-output count and there is no all-modality
                    # figure to report for it.
                    "model_count_all": all_count if capture_source == CAPTURE_SOURCE_LIVE else pd.NA,
                    "model_count_text_output": text_count if capture_source == CAPTURE_SOURCE_LIVE else all_count,
                    "provider_count": int(models["provider_prefix"].dropna().astype(str).nunique())
                    if "provider_prefix" in models
                    else pd.NA,
                }
            )
        return pd.DataFrame(rows, columns=CATALOG_SIZE_COLUMNS)

    @staticmethod
    def _text_output_model_count(frame: pd.DataFrame) -> int:
        """Count models the bare (no ?output_modalities=all) endpoint would return.

        That default response carries every model whose output modalities
        include text. A row with no parsable output_modalities predates the
        field and was text-only, so it counts.
        """
        if "output_modalities_json" not in frame.columns:
            return int(frame["model_id"].nunique())
        count = 0
        for value in frame["output_modalities_json"]:
            if value is None or pd.isna(value):
                count += 1
                continue
            try:
                modalities = json.loads(str(value))
            except (json.JSONDecodeError, TypeError):
                count += 1
                continue
            if not isinstance(modalities, list) or not modalities:
                count += 1
            elif any(str(item).lower() == "text" for item in modalities):
                count += 1
        return count

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
            self.record_catalog_size(incoming, capture_source=CAPTURE_SOURCE_LIVE)
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
