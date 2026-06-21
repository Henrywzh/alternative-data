"""Data models for Google Trends + Stock data."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class TrendsDataPoint:
    """A single weekly Google Trends data point for a keyword."""
    date: str                  # ISO8601 date string (weekly)
    keyword: str
    geo: str                   # e.g. "" = worldwide, "HK", "US"
    trend_value: int           # Google's 0-100 relative interest index
    is_partial: bool           # True if the week is not yet complete
    fetched_at: str            # ISO8601 timestamp of when we fetched


@dataclass
class StockDataPoint:
    """Daily OHLCV data point for a stock ticker."""
    date: str                  # ISO8601 date string (daily)
    ticker: str
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: float
    adj_close: float
    volume: Optional[int]
    fetched_at: str


@dataclass
class CombinedSignal:
    """
    Merged weekly record aligning a Google Trends value
    with the stock's weekly closing price.
    """
    week_start: str            # ISO8601 Monday of the week
    keyword: str
    geo: str
    trend_value: int
    is_partial: bool
    ticker: str
    stock_close: Optional[float]       # Closing price at the end of that week
    stock_adj_close: Optional[float]
    stock_weekly_return: Optional[float]  # (close_t / close_{t-1}) - 1
