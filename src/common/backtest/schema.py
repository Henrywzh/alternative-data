"""Schema and validation helpers for the additive long-form contract."""

from __future__ import annotations

from typing import Final

import pandas as pd

from .vocabulary import (
    EVALUATION_STATUSES,
    INTERVAL_STATUSES,
    METRIC_GRAINS,
    METRIC_STATUSES,
    PERIOD_TYPES,
    PIT_GRADES,
    TRACK_IDS,
)


LONG_FORM_COLUMNS: Final[tuple[str, ...]] = (
    "engine_version",
    "registry_id",
    "row_key",
    "logical_observation_id",
    "dedup_group_id",
    "dedup_rank",
    "is_primary_source",
    "source_dataset",
    "source_run_id",
    "input_bundle_id",
    "source_row_index",
    "source_row_fingerprint",
    "natural_observation_key",
    "entity_id",
    "target_id",
    "target_period_start",
    "target_period_end",
    "target_period_type",
    "track_id",
    "model_id",
    "model_family",
    "is_baseline",
    "model_applied",
    "forecast_origin",
    "information_cutoff",
    "source_observation_date",
    "actual_available_at",
    "actual_source_url",
    "predicted_value",
    "actual_value",
    "unit",
    "source_value_columns",
    "source_row_status",
    "input_pit_status",
    "target_pit_status",
    "pit_grade",
    "evaluation_status",
    "has_prediction",
    "has_actual",
    "imputation_used",
    "dependency_status",
    "scenario",
    "lookback_months",
    "model_use",
    "research_only",
    "source_caveat",
    "notes",
)

METRIC_COLUMNS: Final[tuple[str, ...]] = (
    "metric_policy_version",
    "registry_id",
    "input_bundle_id",
    "source_dataset",
    "entity_id",
    "target_id",
    "target_period_type",
    "track_id",
    "model_id",
    "is_baseline",
    "unit",
    "unit_canonical",
    "metric_grain",
    "pit_grade",
    "metric_scope",
    "metric_status",
    "headline_eligible",
    "n_valid",
    "n_headline_valid",
    "n_total",
    "n_evaluable",
    "n_diagnostic",
    "n_structural_excluded",
    "n_directional",
    "n_distinct_periods",
    "n_distinct_entities",
    "min_headline_rows",
    "directional_hit_rate_min_rows",
    "directional_hit_rate_status",
    "directional_degeneracy",
    "wape",
    "wape_status",
    "denominator_status",
    "mae",
    "rmse",
    "bias",
    "directional_hit_rate",
    "baseline_model_id",
    "baseline_n_overlap",
    "baseline_coverage_ratio",
    "baseline_coverage_status",
    "baseline_rmse",
    "scaler_id",
    "rmse_on_overlap",
    "n_scaled",
    "scaled_rmse",
    "skill_vs_baseline",
    "notes",
)


def empty_long_form() -> pd.DataFrame:
    return pd.DataFrame(columns=list(LONG_FORM_COLUMNS))


def validate_long_form(frame: pd.DataFrame) -> None:
    missing = sorted(set(LONG_FORM_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"Long-form frame is missing columns: {missing}")
    required = [
        "registry_id",
        "row_key",
        "logical_observation_id",
        "source_dataset",
        "entity_id",
        "target_id",
        "target_period_start",
        "target_period_end",
        "target_period_type",
        "track_id",
        "model_id",
        "model_family",
        "input_bundle_id",
        "source_row_fingerprint",
        "natural_observation_key",
        "pit_grade",
        "evaluation_status",
        "unit",
    ]
    if frame[required].isna().any().any():
        raise ValueError("Long-form frame contains null required keys")
    if not frame["row_key"].is_unique:
        raise ValueError("Long-form row_key must be unique")
    if not frame["target_period_type"].isin(PERIOD_TYPES).all():
        bad = sorted(set(frame.loc[~frame["target_period_type"].isin(PERIOD_TYPES), "target_period_type"]))
        raise ValueError(f"Unsupported target period types: {bad}")
    if not frame["track_id"].isin(TRACK_IDS).all():
        bad = sorted(set(frame.loc[~frame["track_id"].isin(TRACK_IDS), "track_id"]))
        raise ValueError(f"Unsupported track IDs: {bad}")
    if not frame["pit_grade"].isin(PIT_GRADES).all():
        bad = sorted(set(frame.loc[~frame["pit_grade"].isin(PIT_GRADES), "pit_grade"]))
        raise ValueError(f"Unsupported PIT grades: {bad}")
    if not frame["evaluation_status"].isin(EVALUATION_STATUSES).all():
        bad = sorted(set(frame.loc[~frame["evaluation_status"].isin(EVALUATION_STATUSES), "evaluation_status"]))
        raise ValueError(f"Unsupported evaluation statuses: {bad}")
    start = pd.to_datetime(frame["target_period_start"], errors="coerce")
    end = pd.to_datetime(frame["target_period_end"], errors="coerce")
    if start.isna().any() or end.isna().any() or (end < start).any():
        raise ValueError("Long-form frame contains invalid target period bounds")
    for flag in ("is_primary_source", "is_baseline", "model_applied", "has_prediction", "has_actual", "imputation_used"):
        if flag not in frame:
            raise ValueError(f"Long-form frame is missing boolean flag: {flag}")
    for flag in ("is_primary_source", "is_baseline", "model_applied", "has_prediction", "has_actual", "imputation_used"):
        if frame[flag].isna().any():
            raise ValueError(f"Long-form boolean flag contains nulls: {flag}")
    prediction_without_value = frame["has_prediction"] & frame["predicted_value"].isna()
    actual_without_value = frame["has_actual"] & frame["actual_value"].isna()
    if prediction_without_value.any():
        raise ValueError("Long-form has_prediction=True rows must contain predicted_value")
    if actual_without_value.any():
        raise ValueError("Long-form has_actual=True rows must contain actual_value")
    contradictory_forecast = (
        frame["has_actual"]
        & frame["evaluation_status"].eq("forecast_only")
        & ~frame["is_baseline"]
    )
    if contradictory_forecast.any():
        raise ValueError("Long-form rows with an actual cannot remain forecast_only")


def validate_metric_table(frame: pd.DataFrame) -> None:
    """Validate the Step 6 metric table emitted by ``compute_metric_table``.

    Symmetric in spirit to ``validate_long_form``: checks required columns,
    enum membership for ``metric_grain``/``metric_status``/``pit_grade``, and
    the two structural invariants ``compute_metric_table`` already enforces
    by construction (pooled rows are never headline_eligible; per_entity
    rows resolve to exactly one entity) -- re-checked here so a future
    refactor of ``_build_metric_row`` cannot silently break them.
    """
    missing = sorted(set(METRIC_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"Metric table is missing columns: {missing}")
    if frame.empty:
        return
    if not frame["metric_grain"].isin(METRIC_GRAINS).all():
        bad = sorted(set(frame.loc[~frame["metric_grain"].isin(METRIC_GRAINS), "metric_grain"]))
        raise ValueError(f"Unsupported metric grains: {bad}")
    if not frame["metric_status"].isin(METRIC_STATUSES).all():
        bad = sorted(set(frame.loc[~frame["metric_status"].isin(METRIC_STATUSES), "metric_status"]))
        raise ValueError(f"Unsupported metric statuses: {bad}")
    # metric_table's pit_grade is a ";"-joined set of the grades observed in
    # the group (see _build_metric_row), not a single value per row like the
    # long form, so membership is checked per split component.
    observed_pit_grades: set[str] = set()
    for value in frame["pit_grade"].astype(str):
        observed_pit_grades.update(part for part in value.split(";") if part)
    bad_pit_grades = sorted(observed_pit_grades - set(PIT_GRADES))
    if bad_pit_grades:
        raise ValueError(f"Unsupported PIT grades in metric table: {bad_pit_grades}")
    pooled_headline = frame.loc[frame["metric_grain"] == "pooled", "headline_eligible"]
    if pooled_headline.any():
        raise ValueError("Pooled metric rows must never be headline_eligible")
    per_entity = frame.loc[frame["metric_grain"] == "per_entity"]
    non_singular_entity = per_entity.loc[per_entity["n_distinct_entities"] != 1]
    if not non_singular_entity.empty:
        raise ValueError(
            "per_entity metric rows must have n_distinct_entities == 1, found: "
            f"{sorted(non_singular_entity['n_distinct_entities'].unique().tolist())}"
        )


def validate_interval_table(frame: pd.DataFrame) -> None:
    """Validate the ``metric_grain``/``metric_status``/``interval_status`` guard
    columns emitted by ``compute_error_intervals``.

    Only the vocabulary of these three guard columns is checked here -- the
    row-level linkage back to the metrics table (every interval group must
    resolve to exactly one metrics row) is already enforced inside
    ``compute_error_intervals`` itself, which raises before this function
    would ever see a divergent frame.
    """
    required = ("metric_grain", "metric_status", "interval_status")
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"Interval table is missing columns: {missing}")
    if frame.empty:
        return
    if not frame["metric_grain"].isin(METRIC_GRAINS).all():
        bad = sorted(set(frame.loc[~frame["metric_grain"].isin(METRIC_GRAINS), "metric_grain"]))
        raise ValueError(f"Unsupported metric grains in interval table: {bad}")
    if not frame["metric_status"].isin(METRIC_STATUSES).all():
        bad = sorted(set(frame.loc[~frame["metric_status"].isin(METRIC_STATUSES), "metric_status"]))
        raise ValueError(f"Unsupported metric statuses in interval table: {bad}")
    if not frame["interval_status"].isin(INTERVAL_STATUSES).all():
        bad = sorted(set(frame.loc[~frame["interval_status"].isin(INTERVAL_STATUSES), "interval_status"]))
        raise ValueError(f"Unsupported interval statuses: {bad}")
