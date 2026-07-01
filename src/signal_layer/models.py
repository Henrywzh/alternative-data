from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


METRIC_REGISTRY_COLUMNS = [
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
    "higher_is_better",
    "default_metric_direction",
    "min_baseline_observations",
    "max_freshness_lag_days",
    "min_coverage_ratio",
    "description",
    "caveats",
]

ASSET_MAPPING_COLUMNS = [
    "metric_id",
    "ticker",
    "company_name",
    "asset_type",
    "theme",
    "exposure_type",
    "expected_direction",
    "exposure_weight",
    "lag_days",
    "confidence",
    "notes",
]

METRIC_SIGNAL_COLUMNS = [
    "metric_id",
    "source",
    "as_of_date",
    "entity_key",
    "entity_name",
    "latest_value",
    "comparison_value",
    "raw_change",
    "pct_change",
    "yoy_change",
    "rolling_change",
    "z_score",
    "robust_z_score",
    "percentile",
    "rank",
    "rank_change",
    "baseline_value",
    "baseline_method",
    "baseline_window",
    "baseline_observation_count",
    "empirical_percentile",
    "tail_probability",
    "effect_size",
    "signed_stat",
    "metric_direction",
    "signal_state",
    "confidence",
    "source_updated_at",
    "quality_state",
    "quality_issues",
    "caveats",
]

ASSET_SIGNAL_COLUMNS = [
    "ticker",
    "company_name",
    "asset_type",
    "as_of_date",
    "theme",
    "combined_signed_stat",
    "combined_tail_probability",
    "median_signed_stat",
    "positive_evidence_count",
    "negative_evidence_count",
    "bullish_metric_count",
    "bearish_metric_count",
    "neutral_metric_count",
    "top_metric_id",
    "top_metric_description",
    "driver_count",
    "valid_driver_count",
    "non_valid_driver_count",
    "quality_issues",
    "signal_state",
    "confidence",
    "summary",
]

THEME_SIGNAL_COLUMNS = [
    "theme",
    "as_of_date",
    "combined_signed_stat",
    "combined_tail_probability",
    "median_signed_stat",
    "positive_evidence_count",
    "negative_evidence_count",
    "active_metric_count",
    "active_asset_count",
    "top_metric_id",
    "top_ticker",
    "signal_state",
    "confidence",
    "summary",
]

ALLOWED_DIRECTIONS = {"positive", "negative", "ambiguous"}
ALLOWED_EXPECTED_DIRECTIONS = {"positive", "negative"}
ALLOWED_SIGNAL_STATES = {"bullish", "bearish", "neutral", "watch"}
ALLOWED_QUALITY_STATES = {
    "valid",
    "insufficient_history",
    "stale",
    "duplicate_grain",
    "low_coverage",
    "invalid_values",
    "partial_period",
    "unvalidated_source",
}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    output_dir: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
