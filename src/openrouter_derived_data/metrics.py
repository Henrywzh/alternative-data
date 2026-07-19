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


def _prepare_activity(activity: pd.DataFrame, *, today: date) -> pd.DataFrame:
    """Normalize activity rows and retain only complete observation dates."""
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
    return normalized.loc[complete_day_rows].copy()


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
    """Return daily and seven-calendar-day rolling token-per-request ratios."""
    complete_activity = _prepare_activity(activity, today=today or _utc_today())
    if complete_activity.empty:
        return _empty_daily()

    calendar_days = pd.date_range(
        complete_activity["usage_date"].min(),
        complete_activity["usage_date"].max(),
        freq="D",
    )
    invalid_request_rows = (
        complete_activity["request_count"].isna()
        | complete_activity["request_count"].le(0)
    )
    excluded_by_day = (
        complete_activity.loc[invalid_request_rows]
        .groupby("usage_date")
        .size()
        .reindex(calendar_days, fill_value=0)
    )
    provenance = _activity_provenance(activity)
    rows: list[dict[str, object]] = []
    for metric_id, source_column in TOKEN_METRICS.items():
        metric_eligible = complete_activity.loc[
            complete_activity["request_count"].gt(0)
            & complete_activity[source_column].notna()
        ].copy()
        tokens_by_day = (
            metric_eligible.groupby("usage_date")[source_column]
            .sum()
            .reindex(calendar_days)
        )
        requests_by_day = (
            metric_eligible.groupby("usage_date")["request_count"]
            .sum()
            .reindex(calendar_days)
        )
        for window in (1, 7):
            rolling_tokens = tokens_by_day.rolling(window, min_periods=1).sum()
            rolling_requests = requests_by_day.rolling(window, min_periods=1).sum()
            values = rolling_tokens / rolling_requests
            excluded_in_window = excluded_by_day.rolling(window, min_periods=1).sum()
            for index, day in enumerate(calendar_days):
                window_start = day - pd.Timedelta(days=window - 1)
                contributing_models = metric_eligible.loc[
                    metric_eligible["usage_date"].between(window_start, day),
                    "model_permaslug",
                ]
                rows.append(
                    {
                        "dataset_id": DAILY_DATASET_ID,
                        **provenance,
                        "usage_date": day.strftime("%Y-%m-%d"),
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
                        "observed_model_count": contributing_models.nunique(),
                        "included_tokens": rolling_tokens.iloc[index],
                        "excluded_free_tokens": pd.NA,
                        "excluded_unpriced_tokens": pd.NA,
                        "excluded_zero_request_rows": excluded_in_window.iloc[index],
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

    eligible = _prepare_activity(activity, today=today or _utc_today())
    eligible = eligible.loc[
        eligible["request_count"].gt(0) & eligible["total_tokens"].notna()
    ].copy()
    if eligible.empty:
        return _empty_models()

    window_end_date = eligible["usage_date"].max()
    window_start_date = window_end_date - pd.Timedelta(days=window_days - 1)
    window = eligible.loc[eligible["usage_date"].ge(window_start_date)].copy()
    grouped = (
        window.groupby(["model_permaslug", "entity_id"], dropna=False, as_index=False)
        .agg(
            total_tokens=("total_tokens", lambda values: values.sum(min_count=1)),
            prompt_tokens=("prompt_tokens", lambda values: values.sum(min_count=1)),
            completion_tokens=("completion_tokens", lambda values: values.sum(min_count=1)),
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
