from __future__ import annotations

import pandas as pd


def calculate_yoy_growth(series: pd.Series) -> pd.Series:
    ordered = _numeric_time_series(series)
    prior_index = ordered.index - pd.DateOffset(years=1)
    prior = pd.Series(ordered.reindex(prior_index).to_numpy(), index=ordered.index)
    return ((ordered / prior) - 1.0) * 100.0


def calculate_rolling_growth(series: pd.Series, *, window: int) -> pd.Series:
    ordered = _numeric_time_series(series)
    prior_average = ordered.shift(window).rolling(window=window, min_periods=window).mean()
    return ((ordered / prior_average) - 1.0) * 100.0


def robust_z_score(value: float, baseline: pd.Series) -> float:
    clean = pd.to_numeric(baseline, errors="coerce").dropna()
    if clean.empty or pd.isna(value):
        return float("nan")
    median = float(clean.median())
    mad = float((clean - median).abs().median())
    if mad == 0:
        std = float(clean.std(ddof=0))
        return float("nan") if std == 0 else (float(value) - median) / std
    return 0.6745 * (float(value) - median) / mad


def standard_z_score(value: float, baseline: pd.Series) -> float:
    clean = pd.to_numeric(baseline, errors="coerce").dropna()
    if clean.empty or pd.isna(value):
        return float("nan")
    std = float(clean.std(ddof=0))
    if std == 0:
        return float("nan")
    return (float(value) - float(clean.mean())) / std


def empirical_percentile(value: float, baseline: pd.Series) -> float:
    clean = pd.to_numeric(baseline, errors="coerce").dropna()
    if clean.empty or pd.isna(value):
        return float("nan")
    return float((clean <= float(value)).mean() * 100.0)


def empirical_tail_probability(value: float, baseline: pd.Series) -> float:
    clean = pd.to_numeric(baseline, errors="coerce").dropna()
    if clean.empty or pd.isna(value):
        return float("nan")
    numeric_value = float(value)
    left_tail = int((clean <= numeric_value).sum()) / len(clean)
    right_tail = int((clean >= numeric_value).sum()) / len(clean)
    return float(min(1.0, 2.0 * min(left_tail, right_tail)))


def summarize_latest_signal(
    *,
    latest_value: float,
    transformed_value: float,
    baseline_values: pd.Series,
    baseline_method: str,
    baseline_window: str,
    metric_direction: str,
    quality_state: str,
) -> dict[str, object]:
    clean = pd.to_numeric(baseline_values, errors="coerce").dropna()
    baseline_value = float(clean.median()) if not clean.empty else float("nan")
    robust = robust_z_score(transformed_value, clean)
    standard = standard_z_score(transformed_value, clean)
    stat = robust if baseline_method == "robust_z" else standard
    signed_stat = -stat if metric_direction == "negative" else stat
    tail = empirical_tail_probability(transformed_value, clean)
    percentile = empirical_percentile(transformed_value, clean)

    if quality_state != "valid":
        signal_state = "watch" if not pd.isna(signed_stat) and abs(float(signed_stat)) >= 1.0 else "neutral"
    elif not pd.isna(tail) and tail <= 0.05 and signed_stat > 0:
        signal_state = "bullish"
    elif not pd.isna(tail) and tail <= 0.05 and signed_stat < 0:
        signal_state = "bearish"
    elif not pd.isna(tail) and tail <= 0.10:
        signal_state = "watch"
    else:
        signal_state = "neutral"

    return {
        "latest_value": latest_value,
        "comparison_value": baseline_value,
        "baseline_value": baseline_value,
        "baseline_method": baseline_method,
        "baseline_window": baseline_window,
        "baseline_observation_count": int(len(clean)),
        "empirical_percentile": percentile,
        "tail_probability": tail,
        "effect_size": stat,
        "z_score": standard,
        "robust_z_score": robust,
        "percentile": percentile,
        "signed_stat": signed_stat,
        "signal_state": signal_state,
    }


def _numeric_time_series(series: pd.Series) -> pd.Series:
    ordered = pd.to_numeric(series, errors="coerce").copy()
    ordered.index = pd.to_datetime(ordered.index)
    return ordered.sort_index()
