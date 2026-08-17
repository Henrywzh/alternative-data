"""Metric policy for the unified forecast-accuracy contract.

Every group emits two rows, distinguished by ``metric_grain``: ``pooled``
(the cross-entity aggregate, kept as a reference row but never headline
eligible) and ``per_entity`` (one row per entity in the group, the only
grain that may be headline eligible). See B3 in the backtest engine notes.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .schema import METRIC_COLUMNS, validate_interval_table, validate_long_form, validate_metric_table
from .storage import runtime_metadata
from .tracks import assert_single_track
from .vocabulary import (
    BASELINE_MODEL_ID,
    BASELINE_SCALER_ID,
    EVALUABLE_STATUSES,
    METRIC_GRAINS,
    METRIC_MANIFEST_VERSION,
    METRIC_POLICY_VERSION,
    MIN_BASELINE_COVERAGE,
    MIN_BASELINE_RMSE,
    MIN_DIRECTIONAL_HIT_RATE_ROWS,
    MIN_HEADLINE_ROWS,
    MIN_SCALER_OVERLAP,
    canonicalize_unit,
    is_headline_grade,
)


INTERVAL_COLUMNS = (
    "registry_id",
    "model_id",
    "target_period_type",
    "track_id",
    "unit",
    "unit_canonical",
    "metric_grain",
    "entity_id",
    "n_eval",
    "n_distinct_periods",
    "metric_status",
    "interval_status",
    "error_p10",
    "error_p25",
    "error_p50",
    "error_p75",
    "error_p90",
)


def _finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _metric_scope(group: pd.DataFrame) -> str:
    if group.empty:
        return "none"
    if (group["pit_grade"] == "D_diagnostic_only").any() or (
        group["evaluation_status"] == "diagnostic_only"
    ).any():
        return "diagnostic_only"
    return "headline_candidate" if (
        group["evaluation_status"].isin(EVALUABLE_STATUSES)
        & group["pit_grade"].map(is_headline_grade)
    ).all() else "diagnostic"


def _directional_details(
    group: pd.DataFrame,
    baseline_by_observation: dict[tuple[str, str, str], float],
) -> tuple[pd.Series, pd.Series]:
    hits: list[bool] = []
    actual_directions: list[float] = []
    for _, row in group.iterrows():
        baseline = baseline_by_observation.get(
            (
                str(row["registry_id"]),
                str(row["logical_observation_id"]),
                str(row["track_id"]),
            )
        )
        if not _finite(baseline) or not _finite(row["actual_value"]) or not _finite(row["predicted_value"]):
            continue
        actual_direction = np.sign(float(row["actual_value"]) - float(baseline))
        predicted_direction = np.sign(float(row["predicted_value"]) - float(baseline))
        if actual_direction == 0 or predicted_direction == 0:
            continue
        hits.append(bool(actual_direction == predicted_direction))
        actual_directions.append(float(actual_direction))
    return pd.Series(hits, dtype="boolean"), pd.Series(actual_directions, dtype="float64")


def _directional_degeneracy(n_directional: int, direction_hit: float, actual_directions: pd.Series) -> str:
    if n_directional == 0:
        return "insufficient"
    if direction_hit == 1.0:
        return "all_correct"
    if direction_hit == 0.0:
        return "all_incorrect"
    if actual_directions.nunique(dropna=True) == 1:
        return "single_direction_actual"
    return "none"


def compute_metric_table(long_form: pd.DataFrame) -> pd.DataFrame:
    """Compute row-count guarded metrics without mutating the long-form data."""
    if long_form.empty:
        return pd.DataFrame(columns=list(METRIC_COLUMNS))
    validate_long_form(long_form)
    frame = long_form.copy()
    frame["predicted_value"] = pd.to_numeric(frame["predicted_value"], errors="coerce")
    frame["actual_value"] = pd.to_numeric(frame["actual_value"], errors="coerce")
    observed = frame[
        frame["is_primary_source"]
        & frame["has_prediction"]
        & frame["predicted_value"].notna()
    ].copy()
    # Structural replays are provenance, not accuracy evidence. Diagnostic
    # rows are retained only when explicitly marked diagnostic-only.
    headline_rows = observed[
        observed["evaluation_status"].isin(EVALUABLE_STATUSES)
        & observed["pit_grade"].map(is_headline_grade)
        & observed["has_actual"]
        & observed["actual_value"].notna()
    ]
    diagnostic_rows = observed[
        observed["evaluation_status"].eq("diagnostic_only")
        & observed["pit_grade"].eq("D_diagnostic_only")
        & observed["has_actual"]
        & observed["actual_value"].notna()
    ]
    valid = pd.concat([headline_rows, diagnostic_rows], ignore_index=True).drop_duplicates("row_key")
    # Keep forecast-only baseline rows in the lookup. They are not metric rows
    # until the target actual is available, but are needed for future scoring.
    baseline_for_lookup = observed[observed["is_baseline"]].copy()
    baseline = valid[valid["is_baseline"]].copy()
    baseline_by_observation: dict[tuple[str, str, str], float] = {}
    if not baseline_for_lookup.empty:
        baseline_by_observation = {
            (
                str(row["registry_id"]),
                str(row["logical_observation_id"]),
                str(row["track_id"]),
            ): float(row["predicted_value"])
            for _, row in baseline_for_lookup.iterrows()
        }

    model_rows = valid[~valid["is_baseline"]].copy()
    group_columns = [
        "registry_id",
        "source_dataset",
        "target_id",
        "target_period_type",
        "track_id",
        "model_id",
        "is_baseline",
        "unit",
    ]
    results: list[dict[str, Any]] = []
    if model_rows.empty and baseline.empty:
        return pd.DataFrame(columns=list(METRIC_COLUMNS))

    all_groups = pd.concat([model_rows, baseline], ignore_index=True).groupby(group_columns, dropna=False, sort=True)
    all_source_groups = frame.groupby(group_columns, dropna=False, sort=True)
    for keys, group in all_groups:
        assert_single_track(group, context=f"compute_metric_table grouping for {keys}")
        source_group = all_source_groups.get_group(keys) if keys in all_source_groups.groups else group
        results.append(
            _build_metric_row(
                group,
                source_group,
                keys,
                "pooled",
                baseline_by_observation,
            )
        )
        for entity in sorted(set(group["entity_id"].astype(str))):
            entity_group = group[group["entity_id"].astype(str) == entity]
            entity_source_group = source_group[source_group["entity_id"].astype(str) == entity]
            results.append(
                _build_metric_row(
                    entity_group,
                    entity_source_group,
                    keys,
                    "per_entity",
                    baseline_by_observation,
                )
            )
    metric_table = pd.DataFrame(results, columns=list(METRIC_COLUMNS))
    validate_metric_table(metric_table)
    return metric_table


def _build_metric_row(
    group: pd.DataFrame,
    source_group: pd.DataFrame,
    keys: tuple[Any, ...],
    grain: str,
    baseline_by_observation: dict[tuple[str, str, str], float],
) -> dict[str, Any]:
    """Compute one metrics row for ``group`` at the given ``grain``.

    ``group`` is already scoped to exactly the rows the row should cover:
    the full pooled cross-entity group for ``grain == "pooled"``, or a
    single-entity subset of it for ``grain == "per_entity"``. ``source_group``
    is the corresponding slice of the raw (pre-filter) long form, used for
    the n_total/n_evaluable/n_diagnostic/n_structural_excluded counts.
    """
    if grain not in METRIC_GRAINS:
        raise ValueError(f"Unknown metric_grain {grain!r}; expected one of {METRIC_GRAINS}")
    registry_id, source_dataset, target_id, period_type, track_id, model_id, is_baseline, unit = keys
    entity_scope = ";".join(sorted(set(group["entity_id"].astype(str))))
    n_valid = len(group)
    n_distinct_periods = int(group["target_period_start"].nunique(dropna=True))
    n_distinct_entities = int(group["entity_id"].nunique(dropna=True))
    if grain == "per_entity" and n_distinct_entities != 1:
        raise ValueError(
            f"per_entity metric row for {registry_id}/{model_id} must resolve to exactly "
            f"one entity_id, found {n_distinct_entities}: {entity_scope}"
        )
    min_rows = MIN_HEADLINE_ROWS.get(str(period_type), 10)
    if not bool(is_baseline):
        direction, actual_directions = _directional_details(group, baseline_by_observation)
    else:
        direction, actual_directions = pd.Series(dtype="boolean"), pd.Series(dtype="float64")
    n_directional = int(direction.notna().sum())
    direction_hit = float(direction.mean()) if n_directional else np.nan
    directional_degeneracy = _directional_degeneracy(n_directional, direction_hit, actual_directions)
    residual = group["predicted_value"] - group["actual_value"]
    rmse = float(np.sqrt(np.mean(np.square(residual))))
    mae = float(np.mean(np.abs(residual)))
    bias = float(np.mean(residual))
    actual_abs_sum = float(group["actual_value"].abs().sum())
    wape = float(group["predicted_value"].sub(group["actual_value"]).abs().sum() / actual_abs_sum) if actual_abs_sum > 0 else np.nan
    wape_status = "valid" if actual_abs_sum > 0 else "no_denominator"
    denominator_status = "actual_abs_sum_positive" if actual_abs_sum > 0 else "zero_or_missing_actual"
    primary_source_group = source_group[source_group["is_primary_source"]]
    n_total = int(len(source_group))
    n_evaluable = int(
        (
            primary_source_group["evaluation_status"].isin(EVALUABLE_STATUSES)
            & primary_source_group["pit_grade"].map(is_headline_grade)
            & primary_source_group["has_actual"]
            & primary_source_group["actual_value"].notna()
        ).sum()
    )
    n_diagnostic = int(
        (
            primary_source_group["evaluation_status"].eq("diagnostic_only")
            & primary_source_group["pit_grade"].eq("D_diagnostic_only")
        ).sum()
    )
    n_structural_excluded = int((primary_source_group["pit_grade"] == "C_structural_replay").sum())
    eligible_mask = group["evaluation_status"].isin(EVALUABLE_STATUSES) & group["pit_grade"].map(is_headline_grade)
    n_headline = int(eligible_mask.sum())
    scope = _metric_scope(group)
    if scope == "diagnostic_only":
        status = "diagnostic_only"
    elif n_valid < min_rows or n_headline < min_rows or n_distinct_periods < min_rows:
        status = "insufficient_sample"
    elif scope == "headline_candidate":
        status = "valid_headline"
    else:
        status = "valid_diagnostic"
    overlap = pd.DataFrame()
    if not bool(is_baseline):
        overlap = group[
            group.apply(
                lambda row: (
                    str(row["registry_id"]),
                    str(row["logical_observation_id"]),
                    str(row["track_id"]),
                ) in baseline_by_observation,
                axis=1,
            )
        ]
    baseline_rmse = np.nan
    if len(overlap) >= MIN_SCALER_OVERLAP:
        base_residual = (
            overlap.apply(
                lambda row: baseline_by_observation[
                    (
                        str(row["registry_id"]),
                        str(row["logical_observation_id"]),
                        str(row["track_id"]),
                    )
                ],
                axis=1,
            ).astype(float)
            - overlap["actual_value"].astype(float)
        )
        baseline_rmse = float(np.sqrt(np.mean(np.square(base_residual))))
    n_scaled = int(len(overlap))
    baseline_coverage_ratio = (
        float(n_scaled / n_valid)
        if not bool(is_baseline) and n_valid > 0
        else np.nan
    )
    # baseline_by_observation already keys on logical_observation_id, which
    # embeds entity_id (<entity_id>:<target_id>:<period_type>:<period_start>),
    # so membership in that 3-tuple dict is equivalent to an entity-scoped
    # 4-tuple lookup: n_scaled (== len(overlap)) is zero exactly when no row
    # in this group's baseline lookup key is present at all.
    if bool(is_baseline):
        baseline_coverage_status = "not_applicable"
    elif n_scaled == 0:
        baseline_coverage_status = "not_available"
    elif not _finite(baseline_coverage_ratio):
        baseline_coverage_status = "not_available"
    elif baseline_coverage_ratio >= 1.0:
        baseline_coverage_status = "complete"
    elif baseline_coverage_ratio >= MIN_BASELINE_COVERAGE:
        baseline_coverage_status = "partial"
    else:
        baseline_coverage_status = "insufficient_coverage"
    rmse_on_overlap = (
        float(
            np.sqrt(
                np.mean(
                    np.square(
                        overlap["predicted_value"].astype(float) - overlap["actual_value"].astype(float)
                    )
                )
            )
        )
        if n_scaled > 0
        else np.nan
    )
    scaled = (
        float(rmse_on_overlap / baseline_rmse)
        if _finite(baseline_rmse) and baseline_rmse > MIN_BASELINE_RMSE and _finite(rmse_on_overlap)
        else np.nan
    )
    directional_min = MIN_DIRECTIONAL_HIT_RATE_ROWS.get(str(period_type), 12)
    directional_status = (
        "valid"
        if n_directional >= directional_min and n_distinct_periods >= directional_min
        else "insufficient_sample"
        if n_directional
        else "not_available"
    )
    if directional_degeneracy not in ("none", "insufficient"):
        directional_status = "degenerate"
    # Coverage is separate from the minimum overlap needed to calculate a
    # scaler. A scaler can be numerically valid on a small overlap while
    # still being too incomplete for a headline claim.
    if (
        grain == "per_entity"
        and not bool(is_baseline)
        and status == "valid_headline"
        and baseline_coverage_status == "insufficient_coverage"
    ):
        status = "insufficient_baseline_coverage"
    # Pooled rows are a retained reference aggregate only, never a headline
    # claim: their n_valid looks large (many correlated entities x periods)
    # even when the independent sample (n_distinct_periods) is small, so
    # headline eligibility is hard-forced off regardless of status.
    headline_eligible = (
        False if grain == "pooled" else bool(status == "valid_headline" and not bool(is_baseline))
    )
    return {
        "metric_policy_version": METRIC_POLICY_VERSION,
        "registry_id": registry_id,
        "input_bundle_id": ";".join(sorted(set(group["input_bundle_id"].astype(str)))),
        "source_dataset": source_dataset,
        "entity_id": entity_scope,
        "target_id": target_id,
        "target_period_type": period_type,
        "track_id": track_id,
        "model_id": model_id,
        "is_baseline": bool(is_baseline),
        "unit": unit,
        "unit_canonical": canonicalize_unit(unit),
        "metric_grain": grain,
        "pit_grade": ";".join(sorted(set(group["pit_grade"].astype(str)))),
        "metric_scope": scope,
        "metric_status": status,
        "headline_eligible": headline_eligible,
        "n_valid": n_valid,
        "n_headline_valid": n_headline,
        "n_total": n_total,
        "n_evaluable": n_evaluable,
        "n_diagnostic": n_diagnostic,
        "n_structural_excluded": n_structural_excluded,
        "n_directional": n_directional,
        "n_distinct_periods": n_distinct_periods,
        "n_distinct_entities": n_distinct_entities,
        "min_headline_rows": min_rows,
        "directional_hit_rate_min_rows": directional_min,
        "directional_hit_rate_status": directional_status,
        "directional_degeneracy": directional_degeneracy,
        "wape": wape,
        "wape_status": wape_status,
        "denominator_status": denominator_status,
        "mae": mae,
        "rmse": rmse,
        "bias": bias,
        "directional_hit_rate": direction_hit,
        "baseline_model_id": BASELINE_MODEL_ID,
        "baseline_n_overlap": int(len(overlap)),
        "baseline_coverage_ratio": baseline_coverage_ratio,
        "baseline_coverage_status": baseline_coverage_status,
        "baseline_rmse": baseline_rmse,
        "scaler_id": BASELINE_SCALER_ID,
        "rmse_on_overlap": rmse_on_overlap,
        "n_scaled": n_scaled,
        "scaled_rmse": scaled,
        "skill_vs_baseline": float(1.0 - scaled) if _finite(scaled) else np.nan,
        "notes": "Baseline RMSE and scaled_rmse are computed on the same overlapping logical observations (rmse_on_overlap/n_scaled); a zero baseline RMSE leaves scaled metrics null.",
    }


def _interval_metric_status_lookup(metrics: pd.DataFrame) -> dict[tuple[str, str, str, str, str, str, str], str]:
    """Map an interval group's join key to the metrics table's classification.

    Keyed on everything ``compute_error_intervals`` groups by (registry_id,
    model_id, target_period_type, track_id, unit, metric_grain, entity_id),
    skipping ``target_id``/``source_dataset``/``is_baseline`` since intervals
    never splits on them: baseline rows are excluded upstream, and every
    ``registry_id`` resolves to exactly one ``target_id``. Raises if that
    assumption is ever violated by a duplicate key mapping to two different
    statuses, rather than silently picking one.
    """
    if metrics.empty:
        return {}
    lookup: dict[tuple[str, str, str, str, str, str, str], str] = {}
    for row in metrics.loc[~metrics["is_baseline"]].itertuples(index=False):
        key = (
            str(row.registry_id),
            str(row.model_id),
            str(row.target_period_type),
            str(row.track_id),
            str(row.unit),
            str(row.metric_grain),
            str(row.entity_id),
        )
        status = str(row.metric_status)
        existing = lookup.get(key)
        if existing is not None and existing != status:
            raise ValueError(
                f"Ambiguous metric_status for interval join key {key}: {existing!r} vs {status!r}"
            )
        lookup[key] = status
    return lookup


def _interval_status(*, grain: str, metric_status: str, n_eval: int, error_p10: float, error_p90: float) -> str:
    """Classify the interval itself, never more permissive than ``metric_status``.

    A collapsed distribution (a single observation, or zero spread across
    more than one) is flagged regardless of grain or sample size -- plotting
    an "error band" made of one point is misleading even as a reference row.
    Otherwise the pooled row stays a reference distribution (matching
    ``compute_metric_table``'s hard-forced ``headline_eligible = False``),
    and a per-entity row is only ever "eligible" when the metrics table
    already calls it ``valid_headline``; every other metric_status is passed
    through unchanged so the two tables can never disagree.
    """
    if n_eval <= 1 or error_p10 == error_p90:
        return "degenerate"
    if grain == "pooled":
        return "reference_only"
    if metric_status == "valid_headline":
        return "eligible"
    return metric_status


def compute_error_intervals(long_form: pd.DataFrame, metrics: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return PIT-filtered absolute-error percentiles by explicit grain.

    The pooled row is retained as a reference distribution only. Per-entity
    rows are the primary consumer grain and prevent a large entity's error
    scale from silently defining every other entity's interval.

    ``metric_status``/``interval_status`` are guard columns for consumers
    (e.g. an error-band chart) so a degenerate or under-sampled distribution
    can never be read as a clean result. ``metric_status`` is carried
    through from ``compute_metric_table`` for the same contract/grain/entity
    rather than reclassified here, so the two tables never disagree; pass an
    already-computed ``metrics`` frame to avoid recomputing it.
    """
    if long_form.empty:
        return pd.DataFrame(columns=list(INTERVAL_COLUMNS))
    validate_long_form(long_form)
    if metrics is None:
        metrics = compute_metric_table(long_form)
    status_lookup = _interval_metric_status_lookup(metrics)
    rows = long_form[
        (long_form["is_primary_source"] == True)  # noqa: E712
        & (long_form["is_baseline"] == False)  # noqa: E712
        & (long_form["has_prediction"] == True)  # noqa: E712
        & (long_form["has_actual"] == True)  # noqa: E712
        & long_form["evaluation_status"].isin(EVALUABLE_STATUSES)
        & long_form["pit_grade"].map(is_headline_grade)
        & long_form["predicted_value"].notna()
        & long_form["actual_value"].notna()
    ].copy()
    if rows.empty:
        return pd.DataFrame(columns=list(INTERVAL_COLUMNS))
    rows["abs_error"] = (rows["predicted_value"] - rows["actual_value"]).abs()
    records: list[dict[str, Any]] = []
    group_columns = ["registry_id", "model_id", "target_period_type", "track_id", "unit"]
    for keys, contract_group in rows.groupby(group_columns, sort=False):
        registry_id, model_id, period_type, track_id, unit = keys
        grain_groups = [
            (
                "pooled",
                ";".join(sorted(contract_group["entity_id"].astype(str).unique())),
                contract_group,
            )
        ]
        grain_groups.extend(
            ("per_entity", str(entity_id), entity_group)
            for entity_id, entity_group in contract_group.groupby("entity_id", sort=True)
        )
        for grain, entity_scope, group in grain_groups:
            values = group["abs_error"].to_numpy(dtype=float)
            n_eval = int(len(values))
            n_distinct_periods = int(group["target_period_start"].nunique(dropna=True))
            error_p10 = float(np.percentile(values, 10))
            error_p90 = float(np.percentile(values, 90))
            status_key = (
                str(registry_id),
                str(model_id),
                str(period_type),
                str(track_id),
                str(unit),
                grain,
                entity_scope,
            )
            if status_key not in status_lookup:
                raise ValueError(
                    f"No matching metrics row for interval group {status_key}; "
                    "compute_metric_table and compute_error_intervals have diverged."
                )
            metric_status = status_lookup[status_key]
            records.append(
                {
                    "registry_id": str(registry_id),
                    "model_id": str(model_id),
                    "target_period_type": str(period_type),
                    "track_id": str(track_id),
                    "unit": str(unit),
                    "unit_canonical": canonicalize_unit(unit),
                    "metric_grain": grain,
                    "entity_id": entity_scope,
                    "n_eval": n_eval,
                    "n_distinct_periods": n_distinct_periods,
                    "metric_status": metric_status,
                    "interval_status": _interval_status(
                        grain=grain,
                        metric_status=metric_status,
                        n_eval=n_eval,
                        error_p10=error_p10,
                        error_p90=error_p90,
                    ),
                    "error_p10": error_p10,
                    "error_p25": float(np.percentile(values, 25)),
                    "error_p50": float(np.percentile(values, 50)),
                    "error_p75": float(np.percentile(values, 75)),
                    "error_p90": error_p90,
                }
            )
    interval_table = pd.DataFrame.from_records(records, columns=list(INTERVAL_COLUMNS))
    validate_interval_table(interval_table)
    return interval_table


def build_metrics_manifest(
    long_form: pd.DataFrame,
    metrics: pd.DataFrame,
    intervals: pd.DataFrame,
) -> dict[str, Any]:
    """Build the small, serializable summary that accompanies metric tables."""
    status_counts = metrics["metric_status"].value_counts().to_dict() if not metrics.empty else {}
    headline = metrics[metrics["headline_eligible"] == True] if not metrics.empty else metrics  # noqa: E712
    grain_counts = metrics["metric_grain"].value_counts().to_dict() if not metrics.empty else {}
    interval_grain_counts = intervals["metric_grain"].value_counts().to_dict() if not intervals.empty else {}
    interval_status_counts = intervals["interval_status"].value_counts().to_dict() if not intervals.empty else {}
    coverage_counts = (
        metrics.loc[
            (metrics["metric_grain"] == "per_entity") & (~metrics["is_baseline"]),
            "baseline_coverage_status",
        ].value_counts().to_dict()
        if not metrics.empty
        else {}
    )
    headline_metric_ids = [
        ":".join(
            (
                str(row["registry_id"]),
                str(row["target_id"]),
                str(row["target_period_type"]),
                str(row["track_id"]),
                str(row["model_id"]),
                str(row["entity_id"]),
                str(row["metric_grain"]),
            )
        )
        for _, row in headline.iterrows()
    ]
    return {
        "manifest_version": METRIC_MANIFEST_VERSION,
        "metric_policy_version": METRIC_POLICY_VERSION,
        "long_form_rows": int(len(long_form)),
        "long_form_schema_columns": int(len(long_form.columns)),
        "contract_rows": int(len(metrics)),
        "metrics_schema_columns": int(len(metrics.columns)),
        "metric_status_counts": {str(key): int(value) for key, value in status_counts.items()},
        "headline_contracts": int(len(headline)),
        "headline_contract_ids": sorted(set(headline["registry_id"].astype(str).tolist())),
        "headline_metric_ids": sorted(headline_metric_ids),
        "metric_grain_counts": {str(key): int(value) for key, value in grain_counts.items()},
        "headline_contracts_by_grain": {
            str(key): int(value)
            for key, value in headline["metric_grain"].value_counts().to_dict().items()
        },
        "pooled_rows_are_reference_only": True,
        "interval_rows": int(len(intervals)),
        "interval_grain_counts": {str(key): int(value) for key, value in interval_grain_counts.items()},
        "interval_status_counts": {str(key): int(value) for key, value in interval_status_counts.items()},
        "baseline_coverage_threshold": MIN_BASELINE_COVERAGE,
        "baseline_coverage_status_counts": {
            str(key): int(value) for key, value in coverage_counts.items()
        },
        "input_bundle_ids": sorted(long_form["input_bundle_id"].dropna().astype(str).unique().tolist()),
        "runtime": runtime_metadata(),
    }
