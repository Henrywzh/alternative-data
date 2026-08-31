"""Lightweight technical indicators on a daily close series."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_technical_history(
    close: pd.Series,
    *,
    rsi_window: int = 14,
    ma_windows: tuple[int, ...] = (20, 60),
    vol_window: int = 20,
    drawdown_window: int = 60,
) -> pd.DataFrame:
    """Return the daily technical series used by the latest snapshot.

    The dashboard needs only the latest row, while the event-driven alert
    policy needs to know when a condition was entered and then confirmed. This
    function keeps both consumers on the same RSI/MA/drawdown definitions.
    """
    series = close.dropna().astype(float)
    columns = ["rsi"]
    columns.extend(name for window in ma_windows for name in (f"ma{window}", f"ma{window}_pct"))
    columns.extend((f"realized_vol_{vol_window}d", f"drawdown_{drawdown_window}d"))
    if series.empty:
        return pd.DataFrame(index=series.index, columns=columns, dtype=float)

    result = pd.DataFrame(index=series.index)

    # RSI (Wilder smoothing, alpha=1/window, matching standard charting).
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / rsi_window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / rsi_window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)

    # A pure winning run has no average loss, which makes the formula NaN but
    # is a genuine overbought reading. Apply the same short-tail rule used by
    # the former latest-only implementation to every eligible date.
    pure_gain_run = pd.Series(False, index=series.index)
    for position, index in enumerate(series.index):
        if position < 1:
            continue
        recent = series.iloc[max(0, position - rsi_window + 1): position + 1]
        recent_diff = recent.diff().dropna()
        pure_gain_run.loc[index] = bool(len(recent_diff) and (recent_diff > 0).all())
    result["rsi"] = rsi.mask(rsi.isna() & pure_gain_run, 100.0)

    for window in ma_windows:
        ma = series.rolling(window).mean()
        result[f"ma{window}"] = ma
        result[f"ma{window}_pct"] = (series / ma - 1.0) * 100.0

    ret = series.pct_change()
    result[f"realized_vol_{vol_window}d"] = ret.rolling(vol_window).std()

    peak = series.rolling(drawdown_window, min_periods=1).max()
    result[f"drawdown_{drawdown_window}d"] = (series / peak - 1.0) * 100.0
    return result


def compute_technicals(
    close: pd.Series,
    *,
    rsi_window: int = 14,
    ma_windows: tuple[int, ...] = (20, 60),
    vol_window: int = 20,
    drawdown_window: int = 60,
) -> dict[str, float | None]:
    """Return the latest-day technical snapshot for one series."""
    history = compute_technical_history(
        close,
        rsi_window=rsi_window,
        ma_windows=ma_windows,
        vol_window=vol_window,
        drawdown_window=drawdown_window,
    )
    if history.empty:
        return {column: None for column in history.columns}

    latest = history.iloc[-1]
    result: dict[str, float | None] = {}
    for column, value in latest.items():
        result[column] = None if pd.isna(value) else float(value)
        if column.endswith("_pct"):
            result[column] = None if result[column] is None else round(result[column], 4)
    return result
