"""Small technical helpers shared by the ETF Monitor charts."""

from __future__ import annotations

import pandas as pd


RATIO_DEFAULTS = {
    "china": ("csi1000", "csi300"),
    "us": ("us_small", "us_broad"),
    "apac": ("hstech", "hsi"),
    "emea": ("dax", "ftse100"),
    "global": ("csi300", "sp500"),
}


def ratio_default_index(eids: list[str], preferred: str, fallback: int) -> int:
    if preferred in eids:
        return eids.index(preferred)
    return min(fallback, max(len(eids) - 1, 0))


def macd_frame(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Classic MACD (12/26/9) on a positive price or ratio series."""
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return pd.DataFrame(columns=["macd", "signal", "histogram"])
    ema_fast = values.ewm(span=fast, adjust=False).mean()
    ema_slow = values.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    histogram = macd - signal_line
    return pd.DataFrame(
        {"macd": macd, "signal": signal_line, "histogram": histogram},
        index=values.index,
    )
