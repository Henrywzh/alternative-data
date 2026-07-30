"""Shared history-window rules for the portable Asia Markets dashboards.

Historical chart builders should retain the source cadence and use a
date-based window rather than a hard-coded row count.  A row-count slice makes
the displayed history depend on cadence (for example, 60 rows is five years
monthly but only 60 days daily) and silently drifts as sources add or miss
observations.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


DEFAULT_HISTORY_YEARS = 10


def history_window(
    frame: pd.DataFrame,
    date_column: str,
    *,
    years: int = DEFAULT_HISTORY_YEARS,
) -> pd.DataFrame:
    """Return the latest ``years`` of observations without changing grain.

    The cutoff is anchored to the latest valid observation in ``frame`` rather
    than the build clock.  That means a delayed monthly source still exposes
    its most recent ten years, while a source with less than ten years of
    coverage returns all available rows.  Invalid dates are excluded because
    they cannot be placed honestly on a time axis.
    """
    if frame.empty or date_column not in frame.columns:
        return frame.iloc[0:0].copy()
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    valid = dates.notna()
    if not valid.any():
        return frame.iloc[0:0].copy()
    latest = dates.loc[valid].max()
    cutoff = latest - pd.DateOffset(years=years)
    return frame.loc[valid & dates.ge(cutoff)].copy()


def history_coverage(frame: pd.DataFrame, date_column: str) -> dict[str, Any]:
    """Describe the actual date coverage for status/manifest metadata."""
    if frame.empty or date_column not in frame.columns:
        return {"available_from": None, "available_to": None, "records": 0}
    dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
    if dates.empty:
        return {"available_from": None, "available_to": None, "records": 0}
    return {
        "available_from": dates.min().strftime("%Y-%m-%d"),
        "available_to": dates.max().strftime("%Y-%m-%d"),
        "records": int(len(dates)),
    }
