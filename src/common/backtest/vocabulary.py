"""Shared vocabulary for Asia Markets forecast/backtest contracts.

The values are deliberately the vocabulary already present in the Airlines
backtests, extended only where the MTR and SHKP source contracts require a
distinct status.  Keep this module free of model logic so every sector can use
the same labels without importing another sector's implementation.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

PitGrade = Literal[
    "A_strict_pit",
    "B_practical_pit",
    "C_structural_replay",
    "D_diagnostic_only",
]

EvaluationStatus = Literal[
    "valid_oos",
    "valid_practical_oos",
    "valid_forward_oos",
    "forecast_only",
    "current_forecast",
    "insufficient_sample",
    "insufficient_input_coverage",
    "no_source_coverage",
    "structural_calibration",
    "historical_structural_check",
    "calibration_year",
    "diagnostic_only",
    "duplicate_source_alias",
    "not_headline_eligible",
]

PIT_GRADES: Final[tuple[str, ...]] = (
    "A_strict_pit",
    "B_practical_pit",
    "C_structural_replay",
    "D_diagnostic_only",
)

EVALUABLE_STATUSES: Final[tuple[str, ...]] = (
    "valid_oos",
    "valid_practical_oos",
    "valid_forward_oos",
)

# Every evaluation status the long-form contract accepts, including the
# narrower EVALUABLE_STATUSES above. Derived from the EvaluationStatus
# Literal via get_args() rather than retyped, so the runtime tuple used by
# validate_long_form's isin()/bad-value checks and the static Literal type
# checkers see can never drift apart.
EVALUATION_STATUSES: Final[tuple[str, ...]] = get_args(EvaluationStatus)

# Every metric_status compute_metric_table can emit (see _build_metric_row
# in metrics.py). Kept here, not derived from a Literal, because
# metric_status is assigned as plain string literals in metrics.py rather
# than typed against a Literal alias; validate_metric_table below cross-
# checks this list is exhaustive.
METRIC_STATUSES: Final[tuple[str, ...]] = (
    "valid_headline",
    "valid_diagnostic",
    "insufficient_sample",
    "insufficient_baseline_coverage",
    "diagnostic_only",
)

# Every interval_status compute_error_intervals can emit (see
# _interval_status in metrics.py): its own three classifications, plus every
# metric_status value passed through unchanged.
INTERVAL_STATUSES: Final[tuple[str, ...]] = (
    "degenerate",
    "reference_only",
    "eligible",
) + METRIC_STATUSES

TRACK_IDS: Final[tuple[str, ...]] = (
    "fiscal_year",
    "half_year_non_overlapping",
    "ytd_current",
    "monthly_sparse",
)

PERIOD_TYPES: Final[tuple[str, ...]] = ("month", "H1", "H2", "FY")

MIN_HEADLINE_ROWS: Final[dict[str, int]] = {
    "month": 24,
    "H1": 10,
    "H2": 10,
    "FY": 10,
}

MIN_DIRECTIONAL_HIT_RATE_ROWS: Final[dict[str, int]] = {
    "month": 36,
    "H1": 12,
    "H2": 12,
    "FY": 12,
}

BASELINE_MODEL_ID: Final[str] = "baseline_same_period_last_year"
BASELINE_SCALER_ID: Final[str] = "same_period_last_year_rmse"
METRIC_POLICY_VERSION: Final[str] = "asia_backtest_metrics_v2"
METRIC_MANIFEST_VERSION: Final[str] = "asia_backtest_metrics_manifest_v2"
MIN_SCALER_OVERLAP: Final[int] = 2
MIN_BASELINE_RMSE: Final[float] = 1e-12
MIN_DENOMINATOR: Final[float] = 1e-12
# A skill-vs-baseline claim must not be headline-eligible when the baseline
# exists for only a small fraction of the model's evaluated observations.
# The first observation in a series can legitimately lack a prior-year
# baseline; this threshold allows that normal edge while rejecting broad
# coverage loss.
MIN_BASELINE_COVERAGE: Final[float] = 0.80

METRIC_GRAINS: Final[tuple[str, ...]] = ("per_entity", "pooled")

# The long form spells the same unit two different ways ("HK$m" for MTR,
# "HKD m" for SHKP rental/profit); both are HKD millions. "HKD" (SHKP
# contract activity) is genuinely 1e6 different -- raw dollars, not
# millions -- and must not be folded into "HKD_mn". No registry_id mixes
# units today, so an unmapped spelling is passed through unchanged rather
# than raising, but any new spelling should be added here explicitly.
UNIT_CANONICAL_MAP: Final[dict[str, str]] = {
    "HK$m": "HKD_mn",
    "HKD m": "HKD_mn",
    "HKD": "HKD",
    "RMB mn": "RMB_mn",
}


def is_evaluable_status(value: object) -> bool:
    return str(value) in EVALUABLE_STATUSES


def is_headline_grade(value: object) -> bool:
    return str(value) in {"A_strict_pit", "B_practical_pit"}


def canonicalize_unit(value: object) -> str:
    """Map a long-form ``unit`` string to its canonical spelling.

    Preserves the original ``unit`` column unchanged; this is a metric-layer
    label only. Unrecognized spellings pass through as-is rather than
    raising, so a new unit surfaces as itself instead of breaking the build.
    """
    return UNIT_CANONICAL_MAP.get(str(value), str(value))
