"""Relative-strength spreads and rolling z-scores across exposures.

The core decision signal is *relative* (spread between two exposures), not a
single absolute RSI. V1 computes size / style / region spreads:

    Small/Large   = R(csi1000) - R(csi300)
    Mid/Large     = R(csi500)  - R(csi300)
    Growth/Div    = R(growth)  - R(dividend)
    China/SP500   = R(csi300)  - R(SPX)

Each spread is evaluated over 5D / 20D / 60D / 120D and a full-history rolling
z-score of the 20D spread. ``trend`` compares the 5D vs 20D spread.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


WINDOWS = (5, 20, 60, 120)


def _rolling_days_ago(cumulative: pd.Series, days: int) -> float | None:
    """Windowed return from an already-cumulative series, by position.

    ``cumulative`` is a cumulative-sum series of daily spread returns. The last
    ``days`` observations are summed (position-based so it works across
    trading-day calendars; the caller is responsible for aligning both legs to
    the same dates first).
    """
    if len(cumulative) < days + 1:
        return None
    val = float(cumulative.iloc[-1] - cumulative.iloc[-1 - days])
    return round(val, 4)


def compute_spread_metrics(
    left_close: pd.Series,
    right_close: pd.Series,
    *,
    label: str,
) -> dict[str, float | None]:
    """Compute windowed relative returns + z-score for one spread.

    Both input series are expected to share the same monotonic date index
    (the caller aligns them with ``join="inner"``); positions therefore map to
    the same trading calendar.
    """
    out: dict[str, float | None] = {"label": label}
    joined = pd.concat([left_close.rename("l"), right_close.rename("r")], axis=1, join="inner").dropna()
    for window in WINDOWS:
        left_ret = joined["l"] / joined["l"].shift(window) - 1.0
        right_ret = joined["r"] / joined["r"].shift(window) - 1.0
        spread = ((left_ret - right_ret) * 100.0).dropna()
        out[f"spread_{window}d_pct"] = round(float(spread.iloc[-1]), 4) if not spread.empty else None

    z_window = 20
    # Use a fixed lookback (1 trading year) for the z-score mean/std so the
    # signal is stable to how much history the ingestion happened to load —
    # otherwise switching start_date from 2y to 1y silently rescales every
    # historical z-score.
    lookback = 252
    if len(joined) >= z_window + 1:
        left_ret_z = joined["l"] / joined["l"].shift(z_window) - 1.0
        right_ret_z = joined["r"] / joined["r"].shift(z_window) - 1.0
        roll = ((left_ret_z - right_ret_z) * 100.0).dropna()
        hist = roll.dropna()
        if len(hist) >= z_window:
            baseline = hist.tail(lookback)
            mean = float(baseline.mean())
            std = float(baseline.std(ddof=0))
            out["spread_20d_zscore"] = round(float((hist.iloc[-1] - mean) / std) if std else 0.0, 4)
            out["spread_20d_pct"] = round(float(hist.iloc[-1]), 4)
    return out


def build_relative_regime(close_by_exposure: dict[str, pd.Series]) -> list[dict]:
    """Build the relative-regime block for the dashboard."""
    rows = []
    pairs = (
        ("csi1000", "csi300", "Small / Large"),
        ("csi500", "csi300", "Mid / Large"),
        ("growth", "dividend", "Growth / Dividend"),
        ("csi300", "sp500", "China / S&P 500"),
    )
    for left_id, right_id, label in pairs:
        left_series = close_by_exposure.get(left_id)
        right_series = close_by_exposure.get(right_id)
        if left_series is None or right_series is None or left_series.empty or right_series.empty:
            rows.append({"label": label, "left": left_id, "right": right_id, "spread_20d_zscore": None, "trend": None})
            continue
        metrics = compute_spread_metrics(left_series, right_series, label=label)
        z = metrics.get("spread_20d_zscore")
        s5 = metrics.get("spread_5d_pct")
        s20 = metrics.get("spread_20d_pct")
        # Trend compares the most recent 5D momentum against the 20D window:
        # only if 5D is meaningfully stronger (positive) than the 20D run-rate
        # is it "up", otherwise if it is catching down it is "down".
        if s5 is None or s20 is None:
            trend = None
        else:
            run_rate_20 = s20 / 4.0  # levelise 20D to a 5D-equivalent scale
            trend = "UP" if s5 > run_rate_20 + 0.05 else ("DOWN" if s5 < run_rate_20 - 0.05 else "FLAT")
        rows.append(
            {
                "label": label,
                "left": left_id,
                "right": right_id,
                "spread_20d_zscore": z,
                "spread_5d_pct": s5,
                "spread_20d_pct": s20,
                "trend": trend,
            }
        )
    return rows
