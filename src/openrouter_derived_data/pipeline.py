"""Validated publication of OpenRouter-derived Parquet marts."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from .identity import load_capability_map, rank_capability_families
from .metrics import (
    DAILY_DATASET_ID,
    TOKEN_METRICS,
    _DAILY_COLUMNS,
    _MODEL_COLUMNS,
    compute_price_metrics,
    compute_workload_intensity_daily,
    compute_workload_intensity_models,
)


MODEL_DATASET_ID = "openrouter_workload_intensity_models"
_INPUTS = {
    "activity": "data/normalized/openrouter/openrouter_model_activity.parquet",
    "economics": "data/normalized/marts/daily_provider_economics.parquet",
    "pricing": "data/normalized/compute_availability/raw_openrouter_models.parquet",
    "models": "data/normalized/artificial_analysis/artificial_analysis_models_daily.parquet",
}
_DESTINATIONS = {
    DAILY_DATASET_ID: "data/normalized/marts/openrouter_usage_economics_daily.parquet",
    MODEL_DATASET_ID: "data/normalized/marts/openrouter_workload_intensity_models.parquet",
}
_INPUT_REQUIRED_COLUMNS = {
    "activity": {
        "usage_date",
        "model_permaslug",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "request_count",
    },
    "economics": {
        "usage_date",
        "model_permaslug",
        "total_tokens",
        "estimated_revenue",
        "pricing_snapshot_ts",
        "pricing_prompt",
        "pricing_completion",
        "pricing_join_status",
    },
    "pricing": {"model_id", "snapshot_ts", "pricing_prompt", "pricing_completion"},
    "models": {
        "as_of_date",
        "model_id",
        "model_name",
        "release_date",
        "intelligence_index",
    },
}
_INPUT_NATURAL_KEYS = {
    "activity": ("usage_date", "model_permaslug"),
    "economics": ("usage_date", "model_permaslug"),
    "pricing": ("model_id", "snapshot_ts"),
    "models": ("as_of_date", "model_id"),
}
_DATE_KEY_COLUMNS = {
    "usage_date",
    "as_of_date",
    "snapshot_ts",
    "window_start_date",
    "window_end_date",
}
_OUTPUT_NATURAL_KEYS = {
    DAILY_DATASET_ID: ("usage_date", "metric_id", "cohort_id", "rolling_window_days"),
    MODEL_DATASET_ID: ("window_start_date", "window_end_date", "model_id", "company_id"),
}


class OpenRouterDerivedPipeline:
    """Build the versioned OpenRouter economics and workload-intensity marts."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def build(self, *, today: date | None = None) -> dict[str, int]:
        """Validate inputs, build both marts, and publish them as a verified pair."""
        target_day = today or datetime.now(timezone.utc).date()
        derived_scraped_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        derived_run_id = f"openrouter-derived-{uuid4().hex}"
        inputs = self._load_inputs()
        self._validate_inputs(inputs, today=target_day)

        capability_map = load_capability_map(self.base_dir)
        rankings = rank_capability_families(
            inputs["models"], inputs["economics"]["usage_date"], capability_map
        )
        workload_daily = compute_workload_intensity_daily(
            inputs["activity"], today=target_day
        )
        price_metrics = compute_price_metrics(
            inputs["economics"],
            inputs["pricing"],
            rankings,
            capability_map,
            today=target_day,
            derived_provenance={
                "source_url": "derived://openrouter-derived-pipeline",
                "source_run_id": derived_run_id,
                "scraped_at": derived_scraped_at,
            },
        )
        outputs = {
            DAILY_DATASET_ID: pd.concat(
                [workload_daily, price_metrics], ignore_index=True
            ),
            MODEL_DATASET_ID: compute_workload_intensity_models(
                inputs["activity"], today=target_day
            ),
        }
        self._validate_outputs(outputs)
        self._write_verified_pair(outputs)
        return {dataset_id: len(frame) for dataset_id, frame in outputs.items()}

    def _load_inputs(self) -> dict[str, pd.DataFrame]:
        loaded: dict[str, pd.DataFrame] = {}
        for dataset_id, relative_path in _INPUTS.items():
            path = self.base_dir / relative_path
            if not path.exists():
                raise FileNotFoundError(path)
            loaded[dataset_id] = pd.read_parquet(path)
        return loaded

    def _validate_inputs(
        self, inputs: dict[str, pd.DataFrame], *, today: date
    ) -> None:
        for dataset_id, frame in inputs.items():
            self._validate_columns(
                dataset_id, frame, _INPUT_REQUIRED_COLUMNS[dataset_id]
            )
            self._validate_natural_key(
                dataset_id, frame, self._input_natural_key(dataset_id, frame)
            )

        activity_dates = pd.to_datetime(
            inputs["activity"]["usage_date"], errors="coerce", utc=True
        ).dt.tz_localize(None).dt.normalize()
        if not activity_dates.lt(pd.Timestamp(today)).any():
            raise ValueError("activity has no complete observation day")

        economics_dates = pd.to_datetime(
            inputs["economics"]["usage_date"], errors="coerce", utc=True
        ).dt.tz_localize(None).dt.normalize().dropna()
        if economics_dates.empty:
            raise ValueError("economics has no valid usage date")
        benchmark_dates = pd.to_datetime(
            inputs["models"]["as_of_date"], errors="coerce", utc=True
        ).dt.tz_localize(None).dt.normalize()
        if not benchmark_dates.le(economics_dates.max()).any():
            raise ValueError("no Artificial Analysis snapshot exists for input dates")

    @staticmethod
    def _input_natural_key(
        dataset_id: str, frame: pd.DataFrame
    ) -> tuple[str, ...]:
        if dataset_id != "activity":
            return _INPUT_NATURAL_KEYS[dataset_id]
        if "category_slug" in frame:
            return ("usage_date", "model_permaslug", "category_slug")
        if "entity_id" in frame and frame["entity_id"].notna().any():
            return ("usage_date", "model_permaslug", "entity_id")
        return _INPUT_NATURAL_KEYS[dataset_id]

    @staticmethod
    def _validate_columns(
        dataset_id: str, frame: pd.DataFrame, required_columns: set[str]
    ) -> None:
        missing = sorted(required_columns - set(frame.columns))
        if missing:
            raise ValueError(f"{dataset_id} is missing required columns: {missing}")

    @staticmethod
    def _validate_natural_key(
        dataset_id: str,
        frame: pd.DataFrame,
        key_columns: tuple[str, ...],
        *,
        optional_key_columns: frozenset[str] = frozenset(),
    ) -> None:
        key_values = frame.loc[:, list(key_columns)].copy()
        for column in _DATE_KEY_COLUMNS & set(key_columns):
            normalized = pd.to_datetime(
                key_values[column], errors="coerce", utc=True, format="mixed"
            )
            if column != "snapshot_ts":
                normalized = normalized.dt.tz_localize(None).dt.normalize()
            key_values[column] = normalized
        required_key_columns = [
            column for column in key_columns if column not in optional_key_columns
        ]
        if key_values.loc[:, required_key_columns].isna().any().any():
            raise ValueError(f"{dataset_id} has missing natural key values: {list(key_columns)}")
        if key_values.duplicated(list(key_columns)).any():
            raise ValueError(f"{dataset_id} has duplicate natural keys: {list(key_columns)}")

    def _validate_outputs(self, outputs: dict[str, pd.DataFrame]) -> None:
        self._validate_output(
            DAILY_DATASET_ID,
            outputs[DAILY_DATASET_ID],
            _DAILY_COLUMNS,
            "value",
        )
        self._validate_output(
            MODEL_DATASET_ID,
            outputs[MODEL_DATASET_ID],
            _MODEL_COLUMNS,
            "intensity_ratio",
        )
        daily = outputs[DAILY_DATASET_ID]
        workload = daily.loc[
            daily["metric_id"].isin(TOKEN_METRICS), "value"
        ]
        market = daily.loc[
            daily["metric_id"].eq("realized_market_average"), "value"
        ]
        if not workload.notna().any():
            raise ValueError("workload intensity output has no non-missing values")
        if not market.notna().any():
            raise ValueError("market-price output has no non-missing values")

    def _validate_output(
        self,
        dataset_id: str,
        frame: pd.DataFrame,
        expected_columns: list[str],
        value_column: str,
    ) -> None:
        if list(frame.columns) != expected_columns:
            raise ValueError(f"{dataset_id} has an unexpected output schema")
        if frame.empty:
            raise ValueError(f"{dataset_id} has no output rows")
        self._validate_natural_key(
            dataset_id,
            frame,
            _OUTPUT_NATURAL_KEYS[dataset_id],
            optional_key_columns=(
                frozenset({"company_id"})
                if dataset_id == MODEL_DATASET_ID
                else frozenset()
            ),
        )
        if not frame[value_column].notna().any():
            raise ValueError(f"{dataset_id} has no non-missing output values")

    def _write_verified_pair(self, outputs: dict[str, pd.DataFrame]) -> None:
        destinations = {
            dataset_id: self.base_dir / relative_path
            for dataset_id, relative_path in _DESTINATIONS.items()
        }
        temporary_files: dict[str, Path] = {}
        backups: dict[str, Path] = {}
        existing_final_files = {
            dataset_id: destination.exists()
            for dataset_id, destination in destinations.items()
        }
        token = uuid4().hex
        replaced = False
        try:
            for dataset_id, destination in destinations.items():
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(".parquet.tmp")
                temporary_files[dataset_id] = temporary
                outputs[dataset_id].to_parquet(temporary, index=False)
                verified = pd.read_parquet(temporary)
                if (
                    list(verified.columns) != list(outputs[dataset_id].columns)
                    or len(verified) != len(outputs[dataset_id])
                ):
                    raise ValueError(f"Failed to verify {destination.name}")

            for dataset_id, destination in destinations.items():
                if existing_final_files[dataset_id]:
                    backup = destination.with_name(f"{destination.name}.{token}.backup")
                    destination.replace(backup)
                    backups[dataset_id] = backup
            for dataset_id, destination in destinations.items():
                temporary_files[dataset_id].replace(destination)
            replaced = True
        finally:
            if not replaced:
                for dataset_id, destination in destinations.items():
                    backup = backups.get(dataset_id)
                    if backup is not None and backup.exists():
                        backup.replace(destination)
                    elif not existing_final_files[dataset_id] and destination.exists():
                        destination.unlink()
            for temporary in temporary_files.values():
                temporary.unlink(missing_ok=True)
            for backup in backups.values():
                backup.unlink(missing_ok=True)
