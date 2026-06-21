"""CLI entry point for Google Trends + Stock pipeline."""
import argparse
import logging
import sys

from .pipeline import GoogleTrendsPipeline


def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Google Trends + stock price data and compute correlation signal."
    )
    parser.add_argument(
        "--keyword",
        default="Pop Mart",
        help="Google Trends search keyword (default: 'Pop Mart')",
    )
    parser.add_argument(
        "--ticker",
        default="9992.HK",
        help="Yahoo Finance stock ticker (default: '9992.HK' = Pop Mart HKEX)",
    )
    parser.add_argument(
        "--geo",
        default="",
        help="Country/region code, e.g. 'HK', 'US'. Empty string = worldwide (default: '')",
    )
    parser.add_argument(
        "--timeframe",
        default="today 5-y",
        help="trendspyg timeframe string (default: 'today 5-y')",
    )
    parser.add_argument(
        "--stock-period",
        default="5y",
        help="yfinance period string (default: '5y')",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Base directory for data storage (default: ./data)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    setup_logging(level=logging.DEBUG if args.debug else logging.INFO)

    pipeline = GoogleTrendsPipeline(data_dir=args.data_dir)
    pipeline.run(
        keyword=args.keyword,
        ticker=args.ticker,
        geo=args.geo,
        timeframe=args.timeframe,
        stock_period=args.stock_period,
    )


if __name__ == "__main__":
    main()
