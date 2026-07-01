from __future__ import annotations

import math

import pandas as pd

from signal_layer.transforms import (
    calculate_rolling_growth,
    calculate_yoy_growth,
    empirical_tail_probability,
    robust_z_score,
    summarize_latest_signal,
)


def test_calculate_yoy_growth_uses_same_month_prior_year() -> None:
    series = pd.Series(
        [100.0, 120.0, 150.0],
        index=pd.to_datetime(["2025-05-01", "2026-04-01", "2026-05-01"]),
    )

    result = calculate_yoy_growth(series)

    assert math.isclose(result.loc[pd.Timestamp("2026-05-01")], 50.0)


def test_calculate_rolling_growth_compares_latest_to_prior_window_average() -> None:
    series = pd.Series(
        [100.0, 100.0, 100.0, 120.0, 120.0, 120.0],
        index=pd.date_range("2026-01-01", periods=6, freq="D"),
    )

    result = calculate_rolling_growth(series, window=3)

    assert math.isclose(result.iloc[-1], 20.0)


def test_robust_z_score_uses_median_and_mad() -> None:
    baseline = pd.Series([10.0, 11.0, 12.0, 13.0, 100.0])

    result = robust_z_score(15.0, baseline)

    assert result > 0
    assert result < 3


def test_empirical_tail_probability_is_two_sided() -> None:
    baseline = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])

    assert empirical_tail_probability(5.0, baseline) == 0.4


def test_summarize_latest_signal_returns_watch_for_invalid_quality() -> None:
    result = summarize_latest_signal(
        latest_value=150.0,
        transformed_value=50.0,
        baseline_values=pd.Series([1.0, 2.0, 3.0]),
        baseline_method="robust_z",
        baseline_window="90D",
        metric_direction="positive",
        quality_state="insufficient_history",
    )

    assert result["signal_state"] == "watch"
    assert result["signed_stat"] > 0
    assert result["baseline_observation_count"] == 3


def test_summarize_latest_signal_never_directional_for_ambiguous_metric() -> None:
    result = summarize_latest_signal(
        latest_value=150.0,
        transformed_value=50.0,
        baseline_values=pd.Series([1.0, 2.0, 3.0]),
        baseline_method="robust_z",
        baseline_window="90D",
        metric_direction="ambiguous",
        quality_state="valid",
    )

    assert pd.isna(result["signed_stat"])
    assert result["signal_state"] == "watch"
