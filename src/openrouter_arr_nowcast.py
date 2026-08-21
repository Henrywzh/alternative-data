"""Calendar-safe ARR history and latest-month nowcasts.

The dashboard and the command-line report both consume the same normalized
provider/day revenue grain.  This module deliberately contains no Streamlit
or plotting code so the calendar and completeness rules can be tested in
isolation.
"""

from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

import numpy as np
import pandas as pd


Z_95 = 1.959963984540054
DEFAULT_PACING_LOOKBACK_MONTHS = 6


@dataclass(frozen=True)
class ArrNowcast:
    """One provider's four latest-month ARR estimates."""

    provider: str
    display_name: str
    mtd_revenue: float
    observed_days: int
    m1_arr: float
    m2_arr: float
    m2_low: float
    m2_high: float
    m3_arr: float
    m3_low: float
    m3_high: float
    m4_arr: float
    latest_7_daily_avg: float
    projected_latest_revenue_m3: float
    weekday_avg: float
    weekend_avg: float
    p_mean: float
    prior_period: pd.Period | None
    prior_arr: float


@dataclass(frozen=True)
class ArrNowcastSummary:
    """Complete pure result used by both dashboard and script consumers."""

    daily: pd.DataFrame
    history: pd.DataFrame
    pacing: pd.DataFrame
    nowcasts: tuple[ArrNowcast, ...]
    source_latest_date: pd.Timestamp
    latest_period: pd.Period
    observed_dates: pd.DatetimeIndex
    remaining_dates: pd.DatetimeIndex
    prior_period: pd.Period | None

    def nowcast_frame(self) -> pd.DataFrame:
        """Return nowcasts as a display-friendly dataframe."""

        frame = pd.DataFrame([asdict(item) for item in self.nowcasts])
        if frame.empty:
            return frame
        frame["prior_period"] = frame["prior_period"].map(
            lambda period: str(period) if period is not None else None
        )
        return frame


def _normalize_dates(values: object) -> pd.Series:
    """Parse dates as naive, normalized calendar days."""

    parsed = pd.to_datetime(values, errors="coerce", utc=True)
    # ``utc=True`` gives a consistent comparison basis for mixed input.  The
    # report is day-grain, so convert back to naive midnight after parsing.
    return parsed.dt.tz_localize(None).dt.normalize()


def _normalized_targets(targets: Mapping[str, str]) -> dict[str, str]:
    return {str(provider).strip().casefold(): str(label) for provider, label in targets.items()}


def prepare_target_daily(
    frame: pd.DataFrame,
    *,
    provider_column: str,
    targets: Mapping[str, str],
) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Aggregate target providers to one row per provider/calendar day.

    ``source_latest_date`` is taken before filtering to target providers.  The
    source's newest day is intentionally retained in the returned daily frame
    so callers can make the exclusion explicit and consistent.
    """

    required = {"usage_date", "estimated_revenue", provider_column}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Source is missing required columns: {sorted(missing)}")

    prepared = frame[["usage_date", "estimated_revenue", provider_column]].copy()
    prepared["usage_date"] = _normalize_dates(prepared["usage_date"])
    prepared["estimated_revenue"] = pd.to_numeric(
        prepared["estimated_revenue"], errors="coerce"
    ).fillna(0.0)
    prepared[provider_column] = prepared[provider_column].astype("string").str.strip().str.casefold()
    prepared = prepared.dropna(subset=["usage_date"])
    source_latest_date = prepared["usage_date"].max()
    if pd.isna(source_latest_date):
        raise ValueError("usage_date contains no valid dates")

    target_labels = _normalized_targets(targets)
    target = prepared[prepared[provider_column].isin(target_labels)].copy()
    target = target.rename(columns={provider_column: "provider"})
    if target.empty:
        raise ValueError("No target-provider observations found in source")

    daily = (
        target.groupby(["provider", "usage_date"], as_index=False)["estimated_revenue"]
        .sum()
        .sort_values(["provider", "usage_date"])
        .reset_index(drop=True)
    )
    return daily, pd.Timestamp(source_latest_date)


def month_is_complete(dates: Iterable[pd.Timestamp], period: pd.Period) -> bool:
    """Return whether *dates* contains every calendar day in *period*."""

    expected = pd.date_range(
        period.start_time.normalize(), period.end_time.normalize(), freq="D"
    )
    actual = _normalize_dates(pd.Series(list(dates))).dropna().drop_duplicates()
    return pd.DatetimeIndex(actual).sort_values().equals(expected.sort_values())


def build_monthly_history(
    daily: pd.DataFrame,
    source_latest_date: pd.Timestamp,
    targets: Mapping[str, str],
) -> tuple[pd.DataFrame, pd.Period]:
    """Build provider-month history and mark each row's true completeness."""

    labels = _normalized_targets(targets)
    latest_date = pd.Timestamp(source_latest_date).normalize()
    latest_period = latest_date.to_period("M")
    retained = daily.copy()
    retained["usage_date"] = _normalize_dates(retained["usage_date"])
    retained = retained[retained["usage_date"] < latest_date].copy()
    retained["month"] = retained["usage_date"].dt.to_period("M")

    rows: list[dict[str, object]] = []
    for (provider, period), group in retained.groupby(["provider", "month"], sort=True):
        days_in_month = calendar.monthrange(period.year, period.month)[1]
        complete = month_is_complete(group["usage_date"], period)
        revenue = float(pd.to_numeric(group["estimated_revenue"], errors="coerce").fillna(0.0).sum())
        rows.append(
            {
                "provider": provider,
                "display_name": labels.get(str(provider), str(provider)),
                "month": period,
                "month_label": str(period),
                "date": period.start_time.normalize(),
                "revenue": revenue,
                "observed_days": int(group["usage_date"].nunique()),
                "days_in_month": days_in_month,
                "complete": bool(complete),
                "arr": revenue / days_in_month * 365.0 if complete else np.nan,
            }
        )

    columns = [
        "provider", "display_name", "month", "month_label", "date", "revenue",
        "observed_days", "days_in_month", "complete", "arr",
    ]
    return pd.DataFrame(rows, columns=columns), latest_period


def pacing_periods(
    latest_period: pd.Period,
    *,
    lookback_months: int = DEFAULT_PACING_LOOKBACK_MONTHS,
) -> list[pd.Period]:
    """Return the immediately preceding calendar months for pacing history."""

    if lookback_months < 1:
        raise ValueError("lookback_months must be positive")
    return [latest_period - offset for offset in range(lookback_months, 0, -1)]


def calculate_pacing(
    daily: pd.DataFrame,
    history: pd.DataFrame,
    latest_period: pd.Period,
    source_latest_date: pd.Timestamp,
    targets: Mapping[str, str],
    *,
    lookback_months: int = DEFAULT_PACING_LOOKBACK_MONTHS,
    observed_days: int | None = None,
) -> pd.DataFrame:
    """Calculate first-observed-days pacing using complete provider-months only."""

    labels = _normalized_targets(targets)
    periods = pacing_periods(latest_period, lookback_months=lookback_months)
    latest_date = pd.Timestamp(source_latest_date).normalize()
    retained = daily.copy()
    retained["usage_date"] = _normalize_dates(retained["usage_date"])
    retained = retained[retained["usage_date"] < latest_date].copy()
    retained["month"] = retained["usage_date"].dt.to_period("M")
    pace_days = observed_days
    if pace_days is None:
        pace_days = max((latest_date - latest_period.start_time.normalize()).days, 1)

    records: list[dict[str, object]] = []
    for provider in labels:
        provider_history = history[
            history["provider"].eq(provider)
            & history["complete"].astype(bool)
            & history["month"].isin(periods)
        ]
        ratios: list[float] = []
        detail: list[str] = []
        for period in periods:
            month_data = retained[
                retained["provider"].eq(provider) & retained["month"].eq(period)
            ]
            if not provider_history["month"].eq(period).any():
                detail.append(f"{period}: incomplete")
                continue
            first_days = min(int(pace_days), int(period.days_in_month))
            first_n = float(
                month_data.loc[
                    month_data["usage_date"].dt.day <= first_days,
                    "estimated_revenue",
                ].sum()
            )
            total = float(month_data["estimated_revenue"].sum())
            if total <= 0:
                detail.append(f"{period}: zero revenue")
                continue
            ratio = first_n / total
            ratios.append(ratio)
            detail.append(f"{period}: {ratio:.3f}")

        values = np.asarray(ratios, dtype=float)
        n = len(values)
        if n == 0 or np.all(values == 0):
            mean, std, se, ci_low, ci_high = 0.55, 0.10, 0.05, 0.35, 0.75
            detail.append("fallback estimate used (insufficient history)")
        else:
            mean = float(values.mean())
            std = float(values.std(ddof=1)) if n > 1 else 0.10
            se = std / np.sqrt(n) if n > 1 else 0.05
            ci_low = max(mean - Z_95 * se if n > 1 else mean * 0.7, 0.15)
            ci_high = min(mean + Z_95 * se if n > 1 else mean * 1.3, 0.95)
        records.append(
            {
                "provider": provider,
                "display_name": labels[provider],
                "n": n,
                "mean": mean,
                "std": std,
                "se": se,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "detail": "; ".join(detail),
            }
        )

    return pd.DataFrame(records).set_index("provider")


def latest_month_window(
    daily: pd.DataFrame,
    source_latest_date: pd.Timestamp,
    targets: Mapping[str, str],
) -> tuple[pd.Period, pd.DatetimeIndex, pd.DatetimeIndex]:
    """Return latest period, complete observed dates, and remaining dates.

    The source's newest date is the first remaining date because it is treated
    as incomplete.  Provider coverage is checked for every observed calendar
    date so an apparently valid MTD cannot silently omit a provider-day.
    """

    latest_date = pd.Timestamp(source_latest_date).normalize()
    latest_period = latest_date.to_period("M")
    observed_dates = pd.date_range(
        latest_period.start_time.normalize(), latest_date - pd.Timedelta(days=1), freq="D"
    )
    remaining_dates = pd.date_range(
        latest_date, latest_period.end_time.normalize(), freq="D"
    )
    if observed_dates.empty:
        raise ValueError("Latest source date leaves no complete days for a nowcast")

    normalized_daily = daily.copy()
    normalized_daily["usage_date"] = _normalize_dates(normalized_daily["usage_date"])
    for provider in _normalized_targets(targets):
        provider_dates = pd.DatetimeIndex(
            normalized_daily.loc[
                normalized_daily["provider"].eq(provider)
                & (normalized_daily["usage_date"] < latest_date),
                "usage_date",
            ].dropna().unique()
        )
        missing = observed_dates.difference(provider_dates)
        if not missing.empty:
            dates = [date.date().isoformat() for date in missing]
            raise ValueError(f"{provider} is missing latest-month complete days: {dates}")
    return latest_period, observed_dates, remaining_dates


def calculate_nowcasts(
    daily: pd.DataFrame,
    source_latest_date: pd.Timestamp,
    pacing: pd.DataFrame,
    history: pd.DataFrame,
    targets: Mapping[str, str],
) -> tuple[tuple[ArrNowcast, ...], pd.DatetimeIndex, pd.DatetimeIndex, pd.Period]:
    """Calculate all four latest-period nowcast models independently."""

    labels = _normalized_targets(targets)
    latest_period, observed_dates, remaining_dates = latest_month_window(
        daily, source_latest_date, labels
    )
    latest_date = pd.Timestamp(source_latest_date).normalize()
    latest_7_dates = observed_dates[-7:]
    remaining_weekday_count = int(sum(date.weekday() < 5 for date in remaining_dates))
    remaining_weekend_count = int(sum(date.weekday() >= 5 for date in remaining_dates))
    observed_days = len(observed_dates)
    normalized_daily = daily.copy()
    normalized_daily["usage_date"] = _normalize_dates(normalized_daily["usage_date"])

    results: list[ArrNowcast] = []
    for provider, display_name in labels.items():
        provider_daily = (
            normalized_daily[normalized_daily["provider"].eq(provider)]
            .set_index("usage_date")["estimated_revenue"]
            .reindex(observed_dates)
            .astype(float)
        )
        mtd_revenue = float(provider_daily.sum())
        latest_7 = provider_daily.reindex(latest_7_dates)
        weekday_values = latest_7[latest_7.index.weekday < 5].to_numpy(dtype=float)
        weekend_values = latest_7[latest_7.index.weekday >= 5].to_numpy(dtype=float)
        if len(weekday_values) < 2 or len(weekend_values) < 2:
            raise ValueError(
                f"Latest 7-day window for {provider} lacks both weekday and weekend replicates"
            )

        weekday_avg = float(weekday_values.mean())
        weekend_avg = float(weekend_values.mean())
        projected_revenue = mtd_revenue + (
            remaining_weekday_count * weekday_avg
            + remaining_weekend_count * weekend_avg
        )

        residuals = np.concatenate(
            [weekday_values - weekday_avg, weekend_values - weekend_avg]
        )
        residual_df = len(latest_7) - 2
        residual_se = float(np.sqrt(np.square(residuals).sum() / residual_df))
        weekday_mean_se = residual_se / np.sqrt(len(weekday_values))
        weekend_mean_se = residual_se / np.sqrt(len(weekend_values))
        projected_revenue_se = np.sqrt(
            (remaining_weekday_count * weekday_mean_se) ** 2
            + (remaining_weekend_count * weekend_mean_se) ** 2
        )
        projected_low = projected_revenue - Z_95 * projected_revenue_se
        projected_high = projected_revenue + Z_95 * projected_revenue_se

        pace = pacing.loc[provider]
        pace_mean = float(pace["mean"])
        pace_low = float(pace["ci_low"])
        pace_high = float(pace["ci_high"])
        m2 = mtd_revenue / pace_mean * 12.0
        m2_low = mtd_revenue / pace_high * 12.0
        m2_high = mtd_revenue / pace_low * 12.0

        provider_history = history[
            history["provider"].eq(provider)
            & history["complete"].astype(bool)
            & (history["month"] < latest_period)
        ]
        if provider_history.empty:
            prior_period = None
            prior_arr = np.nan
        else:
            prior_period = provider_history["month"].max()
            prior_arr = float(
                provider_history.loc[
                    provider_history["month"].eq(prior_period), "arr"
                ].iloc[0]
            )

        latest_7_avg = float(latest_7.mean())
        results.append(
            ArrNowcast(
                provider=provider,
                display_name=display_name,
                mtd_revenue=mtd_revenue,
                observed_days=observed_days,
                m1_arr=mtd_revenue / observed_days * 365.0,
                m2_arr=m2,
                m2_low=m2_low,
                m2_high=m2_high,
                m3_arr=projected_revenue * 12.0,
                m3_low=max(0.0, projected_low * 12.0),
                m3_high=projected_high * 12.0,
                m4_arr=latest_7_avg * 365.0,
                latest_7_daily_avg=latest_7_avg,
                projected_latest_revenue_m3=projected_revenue,
                weekday_avg=weekday_avg,
                weekend_avg=weekend_avg,
                p_mean=pace_mean,
                prior_period=prior_period,
                prior_arr=prior_arr,
            )
        )

    complete_history = history[
        history["complete"].astype(bool) & (history["month"] < latest_period)
    ]
    prior_period = complete_history["month"].max() if not complete_history.empty else None
    return tuple(results), observed_dates, remaining_dates, latest_period


def build_arr_nowcast_summary(
    frame: pd.DataFrame,
    *,
    provider_column: str,
    targets: Mapping[str, str],
    lookback_months: int = DEFAULT_PACING_LOOKBACK_MONTHS,
) -> ArrNowcastSummary:
    """Build a complete calendar-safe ARR summary from a source frame."""

    daily, source_latest_date = prepare_target_daily(
        frame, provider_column=provider_column, targets=targets
    )
    history, latest_period = build_monthly_history(
        daily, source_latest_date, targets
    )
    observed_days = max(
        (pd.Timestamp(source_latest_date).normalize() - latest_period.start_time.normalize()).days,
        1,
    )
    pacing = calculate_pacing(
        daily,
        history,
        latest_period,
        source_latest_date,
        targets,
        lookback_months=lookback_months,
        observed_days=observed_days,
    )
    nowcasts, observed_dates, remaining_dates, _ = calculate_nowcasts(
        daily, source_latest_date, pacing, history, targets
    )
    complete_history = history[
        history["complete"].astype(bool) & (history["month"] < latest_period)
    ]
    prior_period = complete_history["month"].max() if not complete_history.empty else None
    return ArrNowcastSummary(
        daily=daily,
        history=history,
        pacing=pacing,
        nowcasts=nowcasts,
        source_latest_date=source_latest_date,
        latest_period=latest_period,
        observed_dates=observed_dates,
        remaining_dates=remaining_dates,
        prior_period=prior_period,
    )
