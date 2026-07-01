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


BOOL_TOKENS = {
    "true": True,
    "1": True,
    "yes": True,
    "false": False,
    "0": False,
    "no": False,
}
REQUIRED_METRIC_FIELDS = [
    "metric_id",
    "source",
    "dataset_id",
    "date_column",
    "value_column",
    "entity_columns",
    "cadence",
    "transform",
    "baseline_method",
    "baseline_window",
    "seasonality_mode",
    "default_metric_direction",
]
REQUIRED_MAPPING_FIELDS = [
    "metric_id",
    "ticker",
    "company_name",
    "asset_type",
    "theme",
    "exposure_type",
    "expected_direction",
    "confidence",
]


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
    _require_values(metrics, REQUIRED_METRIC_FIELDS, "required metric fields")
    _require_values(mappings, REQUIRED_MAPPING_FIELDS, "required mapping fields")

    duplicated_metrics = metrics.loc[
        metrics["metric_id"].duplicated(), "metric_id"
    ].dropna().unique().tolist()
    if duplicated_metrics:
        raise RegistryValidationError(f"duplicate metric_id values: {duplicated_metrics}")

    unknown_metrics = sorted(set(mappings["metric_id"].dropna()) - set(metrics["metric_id"].dropna()))
    if unknown_metrics:
        raise RegistryValidationError(f"mapping references unknown metric_id values: {unknown_metrics}")

    bad_directions = sorted(
        set(metrics["default_metric_direction"].dropna().str.lower()) - ALLOWED_DIRECTIONS
    )
    if bad_directions:
        raise RegistryValidationError(f"invalid default_metric_direction values: {bad_directions}")

    bad_expected = sorted(
        set(mappings["expected_direction"].dropna().str.lower()) - ALLOWED_EXPECTED_DIRECTIONS
    )
    if bad_expected:
        raise RegistryValidationError(f"invalid expected_direction values: {bad_expected}")

    bad_confidence = sorted(
        set(mappings["confidence"].dropna().str.lower()) - ALLOWED_CONFIDENCE
    )
    if bad_confidence:
        raise RegistryValidationError(f"invalid confidence values: {bad_confidence}")

    _validate_bool(metrics["higher_is_better"], "higher_is_better")
    min_baseline = _validate_numeric(
        metrics["min_baseline_observations"], "min_baseline_observations"
    )
    if (min_baseline <= 0).any():
        raise RegistryValidationError("min_baseline_observations must be greater than 0")

    max_freshness_lag = _validate_numeric(
        metrics["max_freshness_lag_days"], "max_freshness_lag_days"
    )
    if (max_freshness_lag < 0).any():
        raise RegistryValidationError("max_freshness_lag_days must be greater than or equal to 0")

    min_coverage = _validate_numeric(
        metrics["min_coverage_ratio"], "min_coverage_ratio", allow_blank=True
    )
    present_coverage = min_coverage.dropna()
    if ((present_coverage < 0) | (present_coverage > 1)).any():
        raise RegistryValidationError("min_coverage_ratio must be between 0 and 1")

    weights = _validate_numeric(mappings["exposure_weight"], "exposure_weight")
    if (weights <= 0).any():
        raise RegistryValidationError("exposure_weight must be positive numeric values")

    lag_days = _validate_numeric(mappings["lag_days"], "lag_days")
    if (lag_days < 0).any():
        raise RegistryValidationError("lag_days must be greater than or equal to 0")


def _require_columns(frame: pd.DataFrame, required: list[str], name: str) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RegistryValidationError(f"{name} missing required columns: {missing}")


def _require_values(frame: pd.DataFrame, required: list[str], name: str) -> None:
    missing_values = [
        column
        for column in required
        if frame[column].isna().any()
        or frame[column].map(lambda value: str(value).strip() == "").any()
    ]
    if missing_values:
        raise RegistryValidationError(f"{name} must be non-empty: {missing_values}")


def _is_blank(value: object) -> bool:
    return pd.isna(value) or str(value).strip() == ""


def _validate_bool(values: pd.Series, name: str) -> None:
    invalid = [
        value
        for value in values
        if not isinstance(value, bool) and str(value).strip().lower() not in BOOL_TOKENS
    ]
    if invalid:
        raise RegistryValidationError(f"{name} contains invalid boolean values: {invalid}")


def _validate_numeric(values: pd.Series, name: str, *, allow_blank: bool = False) -> pd.Series:
    blanks = values.map(_is_blank)
    candidates = values.mask(blanks) if allow_blank else values
    numeric = pd.to_numeric(candidates, errors="coerce")
    invalid = numeric.isna()
    if allow_blank:
        invalid &= ~blanks
    if invalid.any():
        raise RegistryValidationError(f"{name} must be numeric")
    return numeric


def _coerce_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    frame = metrics.copy()
    frame["higher_is_better"] = frame["higher_is_better"].map(
        lambda value: value
        if isinstance(value, bool)
        else BOOL_TOKENS[str(value).strip().lower()]
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
