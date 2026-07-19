"""Derived workload-intensity metrics from canonical OpenRouter activity."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Final

import pandas as pd


METHODOLOGY_VERSION: Final = "openrouter-derived-v1"
DAILY_DATASET_ID: Final = "openrouter_usage_economics_daily"
TOKEN_METRICS: Final = {
    "total_tokens_per_request": "total_tokens",
    "prompt_tokens_per_request": "prompt_tokens",
    "completion_tokens_per_request": "completion_tokens",
}
_DAILY_COLUMNS: Final = [
    "dataset_id",
    "source_url",
    "source_run_id",
    "scraped_at",
    "usage_date",
    "metric_id",
    "cohort_id",
    "value",
    "numerator",
    "denominator",
    "rolling_window_days",
    "benchmark_snapshot_date",
    "pricing_snapshot_date",
    "expected_family_count",
    "priced_family_count",
    "observed_family_count",
    "observed_model_count",
    "included_tokens",
    "excluded_free_tokens",
    "excluded_unpriced_tokens",
    "excluded_zero_request_rows",
    "methodology_version",
]
_MODEL_COLUMNS: Final = [
    "window_start_date",
    "window_end_date",
    "model_id",
    "company_id",
    "total_tokens",
    "prompt_tokens",
    "completion_tokens",
    "request_count",
    "token_share",
    "request_share",
    "tokens_per_request",
    "intensity_ratio",
    "model_match_status",
    "methodology_version",
]


def _empty_daily() -> pd.DataFrame:
    return pd.DataFrame(columns=_DAILY_COLUMNS)


def _empty_models() -> pd.DataFrame:
    return pd.DataFrame(columns=_MODEL_COLUMNS)


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _prepare_activity(activity: pd.DataFrame, *, today: date) -> tuple[pd.DataFrame, int]:
    """Normalize activity rows and retain only complete, ratio-eligible records."""
    required_columns = {
        "usage_date",
        "model_permaslug",
        "entity_id",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "request_count",
    }
    normalized = activity.copy()
    for column in required_columns:
        if column not in normalized:
            normalized[column] = pd.NA

    normalized["usage_date"] = pd.to_datetime(normalized["usage_date"], errors="coerce").dt.normalize()
    for column in ("total_tokens", "prompt_tokens", "completion_tokens", "request_count"):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    complete_day_rows = normalized["usage_date"].lt(pd.Timestamp(today))
    non_positive_requests = normalized["request_count"].isna() | normalized["request_count"].le(0)
    excluded_zero_request_rows = int((complete_day_rows & non_positive_requests).sum())
    eligible = normalized.loc[complete_day_rows & ~non_positive_requests].copy()
    return eligible, excluded_zero_request_rows


def _activity_provenance(activity: pd.DataFrame) -> dict[str, object]:
    """Carry available source metadata without inventing raw-source values."""
    provenance: dict[str, object] = {}
    for column in ("source_url", "source_run_id", "scraped_at"):
        values = activity[column].dropna() if column in activity else pd.Series(dtype="object")
        provenance[column] = values.iloc[-1] if not values.empty else pd.NA
    return provenance


def compute_workload_intensity_daily(
    activity: pd.DataFrame, *, today: date | None = None
) -> pd.DataFrame:
    """Return daily and seven-observation rolling token-per-request ratios."""
    eligible, excluded_zero_request_rows = _prepare_activity(activity, today=today or _utc_today())
    if eligible.empty:
        return _empty_daily()

    daily = (
        eligible.groupby("usage_date", as_index=False)
        .agg(
            total_tokens=("total_tokens", "sum"),
            prompt_tokens=("prompt_tokens", "sum"),
            completion_tokens=("completion_tokens", "sum"),
            request_count=("request_count", "sum"),
            observed_model_count=("model_permaslug", "nunique"),
        )
        .sort_values("usage_date", kind="stable")
        .reset_index(drop=True)
    )
    provenance = _activity_provenance(activity)
    rows: list[dict[str, object]] = []
    for window in (1, 7):
        rolling_requests = daily["request_count"].rolling(window, min_periods=1).sum()
        rolling_model_counts = daily["observed_model_count"].rolling(window, min_periods=1).max()
        for metric_id, source_column in TOKEN_METRICS.items():
            rolling_tokens = daily[source_column].rolling(window, min_periods=1).sum()
            values = rolling_tokens / rolling_requests.replace(0, pd.NA)
            for index, day in daily.iterrows():
                rows.append(
                    {
                        "dataset_id": DAILY_DATASET_ID,
                        **provenance,
                        "usage_date": day["usage_date"].strftime("%Y-%m-%d"),
                        "metric_id": metric_id,
                        "cohort_id": "all_models",
                        "value": values.iloc[index],
                        "numerator": rolling_tokens.iloc[index],
                        "denominator": rolling_requests.iloc[index],
                        "rolling_window_days": window,
                        "benchmark_snapshot_date": pd.NA,
                        "pricing_snapshot_date": pd.NA,
                        "expected_family_count": pd.NA,
                        "priced_family_count": pd.NA,
                        "observed_family_count": pd.NA,
                        "observed_model_count": rolling_model_counts.iloc[index],
                        "included_tokens": rolling_tokens.iloc[index],
                        "excluded_free_tokens": pd.NA,
                        "excluded_unpriced_tokens": pd.NA,
                        "excluded_zero_request_rows": excluded_zero_request_rows,
                        "methodology_version": METHODOLOGY_VERSION,
                    }
                )
    return pd.DataFrame(rows, columns=_DAILY_COLUMNS)


def compute_workload_intensity_models(
    activity: pd.DataFrame, *, today: date | None = None, window_days: int = 30
) -> pd.DataFrame:
    """Compare canonical models over the latest complete observation window."""
    if window_days < 1:
        raise ValueError("window_days must be positive")

    eligible, _ = _prepare_activity(activity, today=today or _utc_today())
    if eligible.empty:
        return _empty_models()

    window_end_date = eligible["usage_date"].max()
    window_start_date = window_end_date - pd.Timedelta(days=window_days - 1)
    window = eligible.loc[eligible["usage_date"].ge(window_start_date)].copy()
    grouped = (
        window.groupby(["model_permaslug", "entity_id"], dropna=False, as_index=False)
        .agg(
            total_tokens=("total_tokens", "sum"),
            prompt_tokens=("prompt_tokens", "sum"),
            completion_tokens=("completion_tokens", "sum"),
            request_count=("request_count", "sum"),
        )
        .rename(columns={"model_permaslug": "model_id", "entity_id": "company_id"})
    )
    total_tokens = grouped["total_tokens"].sum(min_count=1)
    total_requests = grouped["request_count"].sum(min_count=1)
    grouped["token_share"] = grouped["total_tokens"] / total_tokens
    grouped["request_share"] = grouped["request_count"] / total_requests
    grouped["tokens_per_request"] = grouped["total_tokens"] / grouped["request_count"].replace(0, pd.NA)
    grouped["intensity_ratio"] = grouped["token_share"] / grouped["request_share"].replace(0, pd.NA)
    grouped["window_start_date"] = window_start_date.strftime("%Y-%m-%d")
    grouped["window_end_date"] = window_end_date.strftime("%Y-%m-%d")
    grouped["model_match_status"] = "canonical"
    grouped["methodology_version"] = METHODOLOGY_VERSION
    return grouped.loc[:, _MODEL_COLUMNS].sort_values("model_id", kind="stable").reset_index(drop=True)
