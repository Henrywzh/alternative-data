"""US index / symbol daily data via yfinance (used for S&P 500 index)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from ..freshness import isoformat_utc, last_completed_session_date, market_date


def fetch_daily(
    symbol: str,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    *,
    session_calendar: str = "XNYS",
    now_utc: datetime | None = None,
) -> pd.DataFrame:
    """Fetch completed-session daily OHLCV (adjusted close) for one symbol.

    Yahoo's ``end`` parameter is exclusive, but requesting the report date can
    still include a currently forming daily candle. Bound the request to the
    exchange's latest completed session, then filter the response too in case
    the provider returns an out-of-range row.
    """
    import yfinance as yf

    def _as_date(value: str | date) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])

    completed_session = last_completed_session_date(session_calendar, now_utc=now_utc)
    safe_end_exclusive = completed_session + timedelta(days=1)
    requested_end = _as_date(end_date) if end_date is not None else date.fromisoformat(market_date(now_utc))
    effective_end = min(requested_end, safe_end_exclusive)
    start = _as_date(start_date) if start_date is not None else effective_end - timedelta(days=365 * 2)
    if start >= effective_end:
        return pd.DataFrame()

    start_text = start.isoformat()
    end_text = effective_end.isoformat()
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start_text, end=end_text, auto_adjust=True)
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
    out = out.dropna(subset=["date", "close"])
    # Treat the local filter as authoritative; the API's exclusive end is a
    # request hint, not a guarantee that an incomplete/current bar is absent.
    out = out[
        out["date"].ge(start_text)
        & out["date"].lt(end_text)
        & out["date"].le(completed_session.isoformat())
    ]
    out = out.sort_values("date").reset_index(drop=True)
    out["retrieved_at_utc"] = isoformat_utc()
    out["observation_type"] = "daily_close"
    return out
