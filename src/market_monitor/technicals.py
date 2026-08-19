"""Lightweight technical indicators on a daily close series."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_technicals(
    close: pd.Series,
    *,
    rsi_window: int = 14,
    ma_windows: tuple[int, ...] = (20, 60),
    vol_window: int = 20,
    drawdown_window: int = 60,
) -> dict[str, float | None]:
    """Return the latest-day technical snapshot for one series.

    All values are the most recent observation on the (sorted) series.
    """
    series = close.dropna().astype(float)
    if series.empty:
        return {"rsi": None, "ma20": None, "ma60": None, "ma20_pct": None, "ma60_pct": None, "realized_vol_20d": None, "drawdown_60d": None}

    last = float(series.iloc[-1])
    result: dict[str, float | None] = {}

    # RSI (Wilder smoothing, alpha=1/window, matching standard charting)
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / rsi_window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / rsi_window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    latest_rsi = rsi.iloc[-1] if len(rsi) else np.nan
    # If the *latest* window is all gains (avg_loss == 0 -> RSI NaN), that is a
    # genuine overbought condition (RSI 100), not a data gap. Run this check
    # on the latest window explicitly so a short pure-run tail never falls back
    # to a stale RSI from a window that still had losses.
    if pd.isna(latest_rsi) and len(series) >= 2:
        latest_region = series.tail(rsi_window)
        recent_diff = latest_region.diff().dropna()
        if len(recent_diff) and (recent_diff > 0).all():
            result["rsi"] = 100.0
        else:
            result["rsi"] = None
    else:
        rsi_valid = rsi.dropna()
        result["rsi"] = float(rsi_valid.iloc[-1]) if not rsi_valid.empty else None

    for window in ma_windows:
        ma = series.rolling(window).mean()
        ma_last = ma.dropna()
        result[f"ma{window}"] = float(ma_last.iloc[-1]) if not ma_last.empty else None
        ma_val = result[f"ma{window}"]
        result[f"ma{window}_pct"] = round((last / ma_val - 1.0) * 100.0, 4) if ma_val else None

    ret = series.pct_change()
    rv = ret.rolling(vol_window).std()
    rv_last = rv.dropna()
    result["realized_vol_20d"] = float(rv_last.iloc[-1]) if not rv_last.empty else None

    peak = series.rolling(drawdown_window, min_periods=1).max()
    dd = (series / peak - 1.0) * 100.0
    result["drawdown_60d"] = float(dd.dropna().iloc[-1]) if dd.notna().any() else None

    return result
