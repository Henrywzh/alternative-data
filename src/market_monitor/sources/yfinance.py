"""US index / symbol daily data via yfinance (used for S&P 500 index)."""

from __future__ import annotations

from datetime import date
from datetime import timedelta

import pandas as pd


def fetch_daily(symbol: str, start_date: str | date | None = None, end_date: str | date | None = None) -> pd.DataFrame:
    """Daily OHLCV (adjusted close) for one yfinance symbol."""
    import yfinance as yf

    default_start = date.today() - timedelta(days=365 * 2)
    default_end = date.today()
    start = start_date.isoformat() if isinstance(start_date, date) else (str(start_date) if start_date else default_start.isoformat())
    end = end_date.isoformat() if isinstance(end_date, date) else (str(end_date) if end_date else default_end.isoformat())
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start, end=end, auto_adjust=True)
    if df is None or df.empty:
        return pd.DataFrame()
    if "Date" in df.columns:
        date_series = df["Date"]
    else:
        date_series = pd.Series(df.index)
    out = pd.DataFrame(
        {
            # Resolve every column to a positional numpy array so the DataFrame
            # constructor aligns by position, not by pandas index. yfinance
            # frames carry a Date index; new Series use RangeIndex, and index
            # alignment otherwise turns every value into NaN.
            "date": pd.to_datetime(date_series, errors="coerce").to_numpy(),
            "open": pd.to_numeric(df.get("Open"), errors="coerce").to_numpy(),
            "high": pd.to_numeric(df.get("High"), errors="coerce").to_numpy(),
            "low": pd.to_numeric(df.get("Low"), errors="coerce").to_numpy(),
            "close": pd.to_numeric(df.get("Close"), errors="coerce").to_numpy(),
            "volume": pd.to_numeric(df.get("Volume"), errors="coerce").to_numpy(),
            "amount": float("nan"),
        }
    )
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["date", "close"]).reset_index(drop=True)
