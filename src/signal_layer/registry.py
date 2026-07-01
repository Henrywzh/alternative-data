from __future__ import annotations

from pathlib import Path

import pandas as pd

from signal_layer.models import (
    ALLOWED_CONFIDENCE,
    ALLOWED_DIRECTIONS,
    ALLOWED_EXPECTED_DIRECTIONS,
    ASSET_MAPPING_COLUMNS,
    METRIC_REGISTRY_COLUMNS,
)


class RegistryValidationError(ValueError):
    """Raised when signal-layer reference registries are invalid."""


def reference_dir(base_dir: str | Path) -> Path:
    return Path(base_dir) / "data" / "reference" / "signal_layer"


def load_registries(base_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    root = reference_dir(base_dir)
    metrics_path = root / "signal_metric_registry.csv"
    mappings_path = root / "signal_asset_mapping.csv"
    metrics = pd.read_csv(metrics_path)
    mappings = pd.read_csv(mappings_path)
    validate_registries(metrics, mappings)
    return _coerce_metrics(metrics), _coerce_mappings(mappings)


def validate_registries(metrics: pd.DataFrame, mappings: pd.DataFrame) -> None:
    _require_columns(metrics, METRIC_REGISTRY_COLUMNS, "signal_metric_registry")
    _require_columns(mappings, ASSET_MAPPING_COLUMNS, "signal_asset_mapping")

    duplicated_metrics = metrics.loc[
        metrics["metric_id"].duplicated(), "metric_id"
    ].dropna().unique().tolist()
    if duplicated_metrics:
        raise RegistryValidationError(f"duplicate metric_id values: {duplicated_metrics}")

    unknown_metrics = sorted(set(mappings["metric_id"].dropna()) - set(metrics["metric_id"].dropna()))
    if unknown_metrics:
        raise RegistryValidationError(f"mapping references unknown metric_id values: {unknown_metrics}")

    bad_directions = sorted(set(metrics["default_metric_direction"].dropna().str.lower()) - ALLOWED_DIRECTIONS)
    if bad_directions:
        raise RegistryValidationError(f"invalid default_metric_direction values: {bad_directions}")

    bad_expected = sorted(set(mappings["expected_direction"].dropna().str.lower()) - ALLOWED_EXPECTED_DIRECTIONS)
    if bad_expected:
        raise RegistryValidationError(f"invalid expected_direction values: {bad_expected}")

    bad_confidence = sorted(set(mappings["confidence"].dropna().str.lower()) - ALLOWED_CONFIDENCE)
    if bad_confidence:
        raise RegistryValidationError(f"invalid confidence values: {bad_confidence}")

    weights = pd.to_numeric(mappings["exposure_weight"], errors="coerce")
    if weights.isna().any() or (weights <= 0).any():
        raise RegistryValidationError("exposure_weight must be positive numeric values")


def _require_columns(frame: pd.DataFrame, required: list[str], name: str) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RegistryValidationError(f"{name} missing required columns: {missing}")


def _coerce_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    frame = metrics.copy()
    frame["higher_is_better"] = frame["higher_is_better"].map(
        lambda value: str(value).strip().lower() in {"true", "1", "yes"}
    )
    frame["min_baseline_observations"] = pd.to_numeric(
        frame["min_baseline_observations"], errors="coerce"
    ).astype("Int64")
    frame["max_freshness_lag_days"] = pd.to_numeric(
        frame["max_freshness_lag_days"], errors="coerce"
    ).astype("Int64")
    frame["min_coverage_ratio"] = pd.to_numeric(frame["min_coverage_ratio"], errors="coerce")
    return frame


def _coerce_mappings(mappings: pd.DataFrame) -> pd.DataFrame:
    frame = mappings.copy()
    frame["exposure_weight"] = pd.to_numeric(frame["exposure_weight"], errors="coerce")
    frame["lag_days"] = pd.to_numeric(frame["lag_days"], errors="coerce").fillna(0).astype(int)
    return frame
