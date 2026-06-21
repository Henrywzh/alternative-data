"""
Orchestrates the full Google Trends → Stock Price → Combined Signal pipeline.
"""
import logging
from pathlib import Path

from .fetcher import TrendsFetcher, StockFetcher
from .storage import GoogleTrendsStorage
from .signal import combine, correlation_summary

logger = logging.getLogger(__name__)


class GoogleTrendsPipeline:
    """
    Full pipeline:
      1. Fetch Google Trends interest-over-time for a keyword.
      2. Fetch daily stock prices for a ticker.
      3. Align them into a weekly combined signal DataFrame.
      4. Persist raw + processed data to Parquet.
      5. Print a quick correlation summary.
    """

    def __init__(self, data_dir: str = "data"):
        cwd = Path.cwd()
        base_dir = cwd / data_dir
        self.storage = GoogleTrendsStorage(base_dir)
        self.trends_fetcher = TrendsFetcher()
        self.stock_fetcher = StockFetcher()

    def run(
        self,
        keyword: str,
        ticker: str,
        geo: str = "",
        timeframe: str = "today 5-y",
        stock_period: str = "5y",
    ):
        """
        Args:
            keyword:      Google Trends search term (e.g. "Pop Mart").
            ticker:       Yahoo Finance ticker (e.g. "9992.HK").
            geo:          Country code or "" for worldwide.
            timeframe:    trendspyg timeframe string.
            stock_period: yfinance period string.
        """
        logger.info(f"=== Pipeline START: keyword='{keyword}' ticker='{ticker}' geo='{geo}' ===")

        # 1. Fetch Google Trends
        trends = self.trends_fetcher.fetch(keyword=keyword, geo=geo, timeframe=timeframe)
        self.storage.save_trends(keyword=keyword, geo=geo, records=trends)

        # 2. Fetch stock prices
        stocks = self.stock_fetcher.fetch(ticker=ticker, period=stock_period)
        self.storage.save_stock(ticker=ticker, records=stocks)

        # 3. Combine into weekly signal
        combined_df = combine(trends, stocks)
        self.storage.save_combined(keyword=keyword, geo=geo, ticker=ticker, df=combined_df)

        # 4. Correlation summary
        corr = correlation_summary(combined_df)
        if not corr.empty:
            logger.info("\n=== Correlation Summary ===\n" + corr.to_string(index=False))
            print("\n=== Correlation: Google Trends vs Stock Returns ===")
            print(corr.to_string(index=False))
        else:
            logger.warning("Not enough overlapping data to compute correlation.")

        logger.info(f"=== Pipeline DONE ===")
        return combined_df
