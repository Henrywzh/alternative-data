from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class QualityResult:
    quality_state: str
    quality_issues: str


def canonicalize_latest(
    frame: pd.DataFrame,
    *,
    grain: list[str],
    prefer_non_null: Iterable[str] = (),
    run_id_column: str = "source_run_id",
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    working = frame.copy()
    working["_row_order"] = range(len(working))
    for column in prefer_non_null:
        working[f"_has_{column}"] = working[column].notna().astype(int) if column in working.columns else 0
    if run_id_column in working.columns:
        working["_run_order"] = working[run_id_column].astype("string").fillna("")
    else:
        working["_run_order"] = ""

    sort_columns = [f"_has_{column}" for column in prefer_non_null] + ["_run_order", "_row_order"]
    working = working.sort_values(sort_columns)
    result = working.drop_duplicates(subset=grain, keep="last")
    helper_columns = [column for column in result.columns if column.startswith("_has_")] + ["_run_order", "_row_order"]
    return result.drop(columns=helper_columns).reset_index(drop=True)


def duplicate_count(frame: pd.DataFrame, grain: list[str]) -> int:
    if frame.empty:
        return 0
    return int(frame.duplicated(grain).sum())


def evaluate_metric_quality(
    *,
    baseline_observation_count: int,
    min_baseline_observations: int,
    latest_date: pd.Timestamp | None,
    run_date: pd.Timestamp,
    max_freshness_lag_days: int | None,
    invalid_value_count: int,
    duplicate_count: int,
    coverage_ratio: float | None,
    min_coverage_ratio: float | None,
    partial_period: bool,
    source_validated: bool,
) -> QualityResult:
    issues: list[str] = []

    if duplicate_count > 0:
        issues.append(f"duplicate_count={duplicate_count}")
        return QualityResult("duplicate_grain", "; ".join(issues))

    if invalid_value_count > 0:
        issues.append(f"invalid_value_count={invalid_value_count}")
        return QualityResult("invalid_values", "; ".join(issues))

    if not source_validated:
        issues.append("source_validated=false")
        return QualityResult("unvalidated_source", "; ".join(issues))

    if partial_period:
        issues.append("partial_period=true")
        return QualityResult("partial_period", "; ".join(issues))

    if latest_date is not None and max_freshness_lag_days is not None:
        lag_days = int((run_date.normalize() - latest_date.normalize()).days)
        if lag_days > max_freshness_lag_days:
            issues.append(f"freshness_lag_days={lag_days} above max_freshness_lag_days={max_freshness_lag_days}")
            return QualityResult("stale", "; ".join(issues))

    if baseline_observation_count < min_baseline_observations:
        issues.append(
            f"baseline_observation_count={baseline_observation_count} "
            f"below min_baseline_observations={min_baseline_observations}"
        )
        return QualityResult("insufficient_history", "; ".join(issues))

    if coverage_ratio is not None and min_coverage_ratio is not None and coverage_ratio < min_coverage_ratio:
        issues.append(f"coverage_ratio={coverage_ratio:.3f} below min_coverage_ratio={min_coverage_ratio:.3f}")
        return QualityResult("low_coverage", "; ".join(issues))

    return QualityResult("valid", "")
