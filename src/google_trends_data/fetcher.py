"""
Fetchers for Google Trends (via trendspyg) and stock prices (via yfinance).
"""
import logging
from datetime import datetime, timezone
from typing import List

import pandas as pd
import yfinance as yf
from trendspyg import download_google_trends_interest_over_time

from .models import TrendsDataPoint, StockDataPoint

logger = logging.getLogger(__name__)


class TrendsFetcher:
    """Fetches Google Trends interest-over-time data using trendspyg."""

    def fetch(
        self,
        keyword: str,
        geo: str = "",
        timeframe: str = "today 5-y",
    ) -> List[TrendsDataPoint]:
        """
        Fetch weekly interest-over-time for a single keyword.

        Args:
            keyword:   Search term (e.g. "Pop Mart").
            geo:       Country code ("HK", "US") or "" for worldwide.
            timeframe: Google Trends timeframe string (e.g. "today 5-y").

        Returns:
            List of TrendsDataPoint ordered oldest-first.
        """
        fetched_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"Fetching Google Trends for '{keyword}' geo='{geo}' timeframe='{timeframe}'")

        df: pd.DataFrame = download_google_trends_interest_over_time(
            keyword=keyword,
            geo=geo,
            timeframe=timeframe,
            output_format="dataframe",
        )

        records: List[TrendsDataPoint] = []
        for _, row in df.iterrows():
            records.append(
                TrendsDataPoint(
                    date=str(row["date"]),
                    keyword=keyword,
                    geo=geo,
                    trend_value=int(row["value"]),
                    is_partial=bool(row["is_partial"]),
                    fetched_at=fetched_at,
                )
            )

        logger.info(f"Fetched {len(records)} trend data points for '{keyword}'")
        return records


class StockFetcher:
    """Fetches historical OHLCV price data using yfinance."""

    def fetch(
        self,
        ticker: str,
        period: str = "5y",
        interval: str = "1d",
    ) -> List[StockDataPoint]:
        """
        Fetch daily OHLCV data for a stock ticker.

        Args:
            ticker:   Yahoo Finance ticker (e.g. "9992.HK" for Pop Mart).
            period:   yfinance period string (e.g. "5y", "2y", "1y").
            interval: yfinance interval (e.g. "1d", "1wk").

        Returns:
            List of StockDataPoint ordered oldest-first.
        """
        fetched_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"Fetching stock data for '{ticker}' period='{period}' interval='{interval}'")

        raw = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
        )

        if raw.empty:
            logger.warning(f"No stock data returned for ticker '{ticker}'")
            return []

        # Flatten multi-level columns if present (yfinance ≥ 0.2.x)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        records: List[StockDataPoint] = []
        for date_idx, row in raw.iterrows():
            records.append(
                StockDataPoint(
                    date=str(date_idx.date()),
                    ticker=ticker,
                    open=float(row.get("Open")) if pd.notna(row.get("Open")) else None,
                    high=float(row.get("High")) if pd.notna(row.get("High")) else None,
                    low=float(row.get("Low")) if pd.notna(row.get("Low")) else None,
                    close=float(row["Close"]),
                    adj_close=float(row.get("Adj Close", row["Close"])),
                    volume=int(row["Volume"]) if pd.notna(row.get("Volume")) else None,
                    fetched_at=fetched_at,
                )
            )

        logger.info(f"Fetched {len(records)} price data points for '{ticker}'")
        return records
