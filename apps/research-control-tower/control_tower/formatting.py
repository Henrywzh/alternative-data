"""Pure display formatting helpers."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


def _aware_timestamp(value: str | pd.Timestamp | datetime, label: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a valid timezone-aware timestamp") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return timestamp


def format_t_minus(
    starts_at: str | pd.Timestamp | datetime | None,
    viewer_tz: str,
    now_utc: str | pd.Timestamp | datetime,
) -> str:
    """Format calendar-day distance in the caller's IANA viewer timezone.

    A range is represented by its start. Missing starts are displayed as an
    em dash. No wall-clock default is used: callers supply ``now_utc``.
    """

    try:
        timezone = ZoneInfo(viewer_tz)
    except Exception as exc:
        raise ValueError(f"unknown viewer timezone: {viewer_tz!r}") from exc

    now = _aware_timestamp(now_utc, "now_utc").tz_convert(timezone)
    if starts_at is None or starts_at is pd.NaT:
        return "—"
    try:
        if pd.isna(starts_at):
            return "—"
    except (TypeError, ValueError):
        pass
    start = _aware_timestamp(starts_at, "starts_at").tz_convert(timezone)
    delta_days = (start.date() - now.date()).days
    if delta_days > 0:
        return f"T-{delta_days}d"
    if delta_days < 0:
        return f"T+{-delta_days}d"
    return "T0d"


__all__ = ["format_t_minus"]
