"""Historical market-price contract for Sun Hung Kai Properties.

The sibling ``financial-data`` database intentionally stores fundamentals and
market snapshots, not a daily price series.  This module keeps the missing
series separate and explicit: raw OHLCV values are preserved alongside the
vendor adjusted close, distributions, split markers, fetch time and requested
window.  It is therefore suitable as a reviewed input to a later backtest,
but it does not claim that Yahoo historical bars are point-in-time revisions
that were knowable on each original trading day.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import pandas as pd

from .storage import save_normalized_dataset


SHKP_TICKER = "0016.HK"
YAHOO_HISTORY_URL = "https://finance.yahoo.com/quote/0016.HK/history"
DEFAULT_PRICE_HISTORY_START = "2010-01-01"
PRICE_HISTORY_DATASET = "shkp_financial_model_price_history"

SHKP_PRICE_HISTORY_COLUMNS = [
    "ticker",
    "trading_date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "dividend_per_share",
    "stock_split_ratio",
    "total_return_index",
    "price_currency",
    "source",
    "source_url",
    "requested_start",
    "requested_end",
    "fetched_at",
    "price_adjustment_policy",
    "price_quality",
    "caveat",
]


def _flatten_yahoo_columns(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Return a single-ticker frame from either Yahoo column layout."""
    if not isinstance(frame.columns, pd.MultiIndex):
        return frame.copy()
    # yfinance has emitted both ``(field, ticker)`` and ``(ticker, field)``
    # layouts across versions.  Select the level containing the requested
    # ticker and drop only that level; never silently use another ticker.
    levels = [list(frame.columns.get_level_values(level)) for level in range(frame.columns.nlevels)]
    ticker_level = next(
        (level for level, values in enumerate(levels) if ticker in values),
        None,
    )
    if ticker_level is None:
        # A one-ticker response can sometimes use an empty/normalised symbol.
        # In that case only accept a single ticker value rather than guessing.
        unique_values = [set(values) for values in levels]
        candidate = next((level for level, values in enumerate(unique_values) if len(values) == 1), None)
        if candidate is None:
            raise ValueError(f"Yahoo response has no unambiguous {ticker} column level")
        ticker_level = candidate
    selected = frame.xs(ticker, axis=1, level=ticker_level, drop_level=True) if ticker in levels[ticker_level] else frame.xs(levels[ticker_level][0], axis=1, level=ticker_level, drop_level=True)
    if isinstance(selected.columns, pd.MultiIndex):
        selected.columns = [column[-1] for column in selected.columns]
    return selected


def _field_column(columns: pd.Index, *names: str) -> str | None:
    normalised = {str(column).strip().casefold(): column for column in columns}
    for name in names:
        if name.casefold() in normalised:
            return str(normalised[name.casefold()])
    return None


def normalize_shkp_price_history(
    history: pd.DataFrame,
    *,
    ticker: str = SHKP_TICKER,
    requested_start: str | None = None,
    requested_end: str | None = None,
    fetched_at: str | datetime | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Normalize and validate a yfinance daily-bar response.

    A duplicate trading date, missing close, invalid OHLC, or observation
    dated after the fetch timestamp is an error rather than a row to repair.
    This makes upstream schema changes visible before a backtest consumes the
    series.
    """
    if history is None or history.empty:
        raise ValueError(f"No historical price rows returned for {ticker}")
    frame = _flatten_yahoo_columns(history, ticker)
    if isinstance(frame.index, pd.DatetimeIndex):
        frame = frame.reset_index()
    else:
        frame = frame.reset_index(drop=False)
    date_col = _field_column(frame.columns, "Date", "Datetime", "index")
    if date_col is None:
        raise ValueError("Yahoo response lacks a date column/index")
    frame["trading_date"] = pd.to_datetime(frame[date_col], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    if frame["trading_date"].isna().any():
        raise ValueError("Yahoo response contains invalid trading dates")
    if frame["trading_date"].duplicated().any():
        duplicates = frame.loc[frame["trading_date"].duplicated(keep=False), "trading_date"].dt.strftime("%Y-%m-%d").unique().tolist()
        raise ValueError("Yahoo response contains duplicate trading dates: " + ", ".join(duplicates))

    output: dict[str, Any] = {"trading_date": frame["trading_date"]}
    for output_name, candidates in {
        "open": ("Open",),
        "high": ("High",),
        "low": ("Low",),
        "close": ("Close",),
        "adj_close": ("Adj Close", "Adjusted Close"),
        "volume": ("Volume",),
        "dividend_per_share": ("Dividends", "Dividend"),
        "stock_split_ratio": ("Stock Splits", "Stock Split", "Splits"),
    }.items():
        column = _field_column(frame.columns, *candidates)
        output[output_name] = frame[column] if column else pd.NA
    result = pd.DataFrame(output)
    for column in ("open", "high", "low", "close", "adj_close", "volume", "dividend_per_share", "stock_split_ratio"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    fetch_timestamp = pd.Timestamp(fetched_at) if fetched_at is not None else pd.Timestamp.now(tz="UTC")
    if fetch_timestamp.tzinfo is None:
        fetch_timestamp = fetch_timestamp.tz_localize("UTC")
    fetch_timestamp = fetch_timestamp.tz_convert("UTC")
    missing_close = result["close"].isna()
    if missing_close.any():
        # Yahoo may return an in-progress current-session row with OHLC fields
        # partly populated but no close.  It is not a daily observation yet;
        # exclude only that fetch-date row and fail closed for older gaps.
        fetch_day = fetch_timestamp.tz_localize(None).normalize()
        historical_gap = missing_close & result["trading_date"].lt(fetch_day)
        if historical_gap.any():
            dates = result.loc[historical_gap, "trading_date"].dt.strftime("%Y-%m-%d").tolist()
            raise ValueError("Yahoo response contains historical rows without close prices: " + ", ".join(dates))
        result = result.loc[~missing_close].copy()
    if result.empty:
        raise ValueError(f"No completed daily price rows returned for {ticker}")
    if result[["open", "high", "low", "close"]].lt(0).any().any():
        raise ValueError("Yahoo response contains negative OHLC prices")
    if result["volume"].notna().any() and result["volume"].dropna().lt(0).any():
        raise ValueError("Yahoo response contains negative volume")
    if result["adj_close"].isna().all():
        # Keep the series usable but make the loss of vendor adjustment
        # explicit.  We never silently label raw close as a true total return.
        result["adj_close"] = result["close"]
        adjustment_policy = "raw_ohlc_no_vendor_adjustment_adj_close_fallback"
        adjustment_caveat = "Yahoo adjusted close was absent; adj_close equals close and total return excludes distributions."
    else:
        result["adj_close"] = result["adj_close"].fillna(result["close"])
        adjustment_policy = "raw_ohlc_with_yahoo_adjusted_close"
        adjustment_caveat = "Yahoo adjusted close incorporates the vendor's split/distribution adjustment methodology."
    result = result.sort_values("trading_date").reset_index(drop=True)
    base_adj = float(result.loc[0, "adj_close"])
    if base_adj <= 0:
        raise ValueError("Yahoo response starts with a non-positive adjusted close")
    result["total_return_index"] = result["adj_close"] / base_adj * 100.0

    if (result["trading_date"] > fetch_timestamp.tz_localize(None).normalize()).any():
        raise ValueError("Yahoo response contains a trading date after fetched_at")
    result["ticker"] = ticker
    result["price_currency"] = "HKD"
    result["source"] = "yfinance"
    result["source_url"] = YAHOO_HISTORY_URL
    result["requested_start"] = requested_start
    result["requested_end"] = requested_end
    result["fetched_at"] = fetch_timestamp.isoformat()
    result["price_adjustment_policy"] = adjustment_policy
    result["price_quality"] = "historical_daily_bar_vendor_replay"
    incomplete_note = (
        " In-progress fetch-date rows without a close were excluded."
        if missing_close.any()
        else ""
    )
    result["caveat"] = (
        "Historical Yahoo bars can be revised after the trading date and are not a point-in-time replay; "
        + adjustment_caveat
        + incomplete_note
    )
    return result.reindex(columns=SHKP_PRICE_HISTORY_COLUMNS)


def fetch_shkp_price_history(
    *,
    start_date: str | None = DEFAULT_PRICE_HISTORY_START,
    end_date: str | None = None,
    ticker: str = SHKP_TICKER,
    fetcher: Callable[..., pd.DataFrame] | None = None,
    fetched_at: str | datetime | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Fetch SHKP daily history with raw OHLCV and vendor adjustments."""
    if fetcher is None:
        try:
            import yfinance as yf  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("yfinance is required for SHKP price history") from exc
        fetcher = yf.download
    frame = fetcher(
        ticker,
        start=start_date,
        end=end_date,
        actions=True,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    return normalize_shkp_price_history(
        frame,
        ticker=ticker,
        requested_start=start_date,
        requested_end=end_date,
        fetched_at=fetched_at,
    )


def run_shkp_price_history(
    *,
    start_date: str | None = DEFAULT_PRICE_HISTORY_START,
    end_date: str | None = None,
    ticker: str = SHKP_TICKER,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Fetch and persist the reviewed SHKP price-history contract."""
    frame = fetch_shkp_price_history(start_date=start_date, end_date=end_date, ticker=ticker)
    adjustment_policies = sorted(frame["price_adjustment_policy"].dropna().astype(str).unique())
    persisted = save_normalized_dataset(
        PRICE_HISTORY_DATASET,
        frame,
        run_id=run_id,
        source_url=YAHOO_HISTORY_URL,
        source_urls=[YAHOO_HISTORY_URL],
        lineage_metadata={
            "lineage_type": "shkp_market_price_history",
            "ticker": ticker,
            "requested_start": start_date,
            "requested_end": end_date,
            "adjustment_policy": adjustment_policies,
            "point_in_time_warning": "Vendor history is not a point-in-time replay; fetched_at is preserved for audit.",
        },
    )
    return {
        "mode": "shkp_price_history",
        "ticker": ticker,
        "rows": int(len(frame)),
        "first_date": frame["trading_date"].min().strftime("%Y-%m-%d"),
        "last_date": frame["trading_date"].max().strftime("%Y-%m-%d"),
        "normalized": persisted,
    }
