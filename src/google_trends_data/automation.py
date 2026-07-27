from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .csv_importer import parse_interest_over_time_csv
from .fetcher import StockFetcher
from .fetcher import TrendsFetcher
from .signal import combine
from .storage import GoogleTrendsStorage


def load_watchlist(
    path: str | Path,
    *,
    enabled_only: bool = True,
    frequency: str | None = None,
) -> list[dict[str, Any]]:
    watchlist = json.loads(Path(path).read_text(encoding="utf-8"))
    if enabled_only:
        watchlist = [item for item in watchlist if item.get("enabled")]
    if frequency is not None:
        if frequency not in {"weekly", "monthly"}:
            raise ValueError(f"Unsupported watchlist frequency: {frequency}")
        watchlist = [item for item in watchlist if item.get("refresh_frequency", "weekly") == frequency]
    return watchlist


class GoogleTrendsWatchlistRunner:
    def __init__(
        self,
        *,
        base_dir: str | Path,
        watchlist_path: str | Path,
        exporter: Any,
        trends_fetcher: TrendsFetcher | Any | None = None,
        stock_fetcher: StockFetcher | Any | None = None,
        data_dir: str = "data",
    ) -> None:
        self.base_dir = Path(base_dir)
        self.watchlist_path = Path(watchlist_path)
        self.exporter = exporter
        self.trends_fetcher = trends_fetcher or TrendsFetcher()
        self.stock_fetcher = stock_fetcher or StockFetcher()
        self.data_dir = data_dir

    def refresh_enabled(
        self,
        *,
        timeframe: str = "today 5-y",
        stock_period: str = "5y",
        hl: str = "en-US",
        headless: bool = True,
        download_dir: str | Path | None = None,
        frequency: str | None = None,
    ) -> dict[str, int]:
        entries = load_watchlist(self.watchlist_path, enabled_only=True, frequency=frequency)
        return self._refresh_entries(
            entries,
            timeframe=timeframe,
            stock_period=stock_period,
            hl=hl,
            headless=headless,
            download_dir=download_dir,
        )

    def refresh_enabled_with_fetcher(
        self,
        *,
        timeframe: str = "today 5-y",
        stock_period: str = "5y",
        frequency: str | None = None,
    ) -> dict[str, int]:
        entries = load_watchlist(self.watchlist_path, enabled_only=True, frequency=frequency)
        return self._refresh_entries_with_fetcher(
            entries,
            timeframe=timeframe,
            stock_period=stock_period,
        )

    def refresh_ticker(
        self,
        ticker: str,
        *,
        timeframe: str = "today 5-y",
        stock_period: str = "5y",
        hl: str = "en-US",
        headless: bool = True,
        download_dir: str | Path | None = None,
    ) -> dict[str, int]:
        entries = [item for item in load_watchlist(self.watchlist_path, enabled_only=False) if item["ticker"] == ticker]
        if not entries:
            raise ValueError(f"Ticker '{ticker}' not found in watchlist")
        return self._refresh_entries(
            entries,
            timeframe=timeframe,
            stock_period=stock_period,
            hl=hl,
            headless=headless,
            download_dir=download_dir,
        )

    def validate(
        self,
        *,
        timeframe: str = "today 5-y",
        hl: str = "en-US",
        headless: bool = True,
        download_dir: str | Path | None = None,
        frequency: str | None = None,
    ) -> dict[str, Any]:
        entries = load_watchlist(self.watchlist_path, enabled_only=True, frequency=frequency)
        if not entries:
            raise ValueError("Watchlist has no enabled entries to validate")

        entry = entries[0]
        keyword_spec = entry["keywords"][0]
        export_dir = Path(download_dir) if download_dir else self.base_dir / "output" / "google_trends_downloads"
        csv_path = self.exporter.export_interest_over_time(
            keyword=keyword_spec["term"],
            geo=keyword_spec.get("geo", ""),
            timeframe=timeframe,
            hl=hl,
            output_dir=export_dir,
            headless=headless,
        )
        records = parse_interest_over_time_csv(
            csv_path,
            keyword=keyword_spec["term"],
            geo=keyword_spec.get("geo", ""),
        )
        return {
            "ticker": entry["ticker"],
            "keyword": keyword_spec["term"],
            "geo": keyword_spec.get("geo", ""),
            "rows": len(records),
        }

    def _refresh_entries(
        self,
        entries: list[dict[str, Any]],
        *,
        timeframe: str,
        stock_period: str,
        hl: str,
        headless: bool,
        download_dir: str | Path | None,
    ) -> dict[str, int]:
        if not entries:
            return {"tickers": 0, "keyword_pairs": 0}

        staged_trends: list[tuple[dict[str, Any], dict[str, str], list[Any]]] = []
        staged_stocks: dict[str, list[Any]] = {}
        export_dir = Path(download_dir) if download_dir else self.base_dir / "output" / "google_trends_downloads"

        for entry in entries:
            ticker = entry["ticker"]
            for keyword_spec in entry["keywords"]:
                csv_path = self.exporter.export_interest_over_time(
                    keyword=keyword_spec["term"],
                    geo=keyword_spec.get("geo", ""),
                    timeframe=timeframe,
                    hl=hl,
                    output_dir=export_dir,
                    headless=headless,
                )
                records = parse_interest_over_time_csv(
                    csv_path,
                    keyword=keyword_spec["term"],
                    geo=keyword_spec.get("geo", ""),
                )
                staged_trends.append((entry, keyword_spec, records))

            staged_stocks[ticker] = self.stock_fetcher.fetch(ticker=ticker, period=stock_period)

        storage = GoogleTrendsStorage(self.base_dir / self.data_dir)
        for ticker, stocks in staged_stocks.items():
            storage.save_stock(ticker, stocks)

        for entry, keyword_spec, trends in staged_trends:
            ticker = entry["ticker"]
            geo = keyword_spec.get("geo", "")
            storage.save_trends(keyword=keyword_spec["term"], geo=geo, records=trends)
            combined = combine(trends, staged_stocks[ticker])
            storage.save_combined(keyword=keyword_spec["term"], geo=geo, ticker=ticker, df=combined)

        return {
            "tickers": len(entries),
            "keyword_pairs": len(staged_trends),
        }

    def _refresh_entries_with_fetcher(
        self,
        entries: list[dict[str, Any]],
        *,
        timeframe: str,
        stock_period: str,
    ) -> dict[str, int]:
        if not entries:
            return {"tickers": 0, "keyword_pairs": 0}

        staged_trends: list[tuple[dict[str, Any], dict[str, str], list[Any]]] = []
        staged_stocks: dict[str, list[Any]] = {}

        for entry in entries:
            ticker = entry["ticker"]
            for keyword_spec in entry["keywords"]:
                records = self.trends_fetcher.fetch(
                    keyword=keyword_spec["term"],
                    geo=keyword_spec.get("geo", ""),
                    timeframe=timeframe,
                )
                staged_trends.append((entry, keyword_spec, records))

            staged_stocks[ticker] = self.stock_fetcher.fetch(ticker=ticker, period=stock_period)

        storage = GoogleTrendsStorage(self.base_dir / self.data_dir)
        for ticker, stocks in staged_stocks.items():
            storage.save_stock(ticker, stocks)

        for entry, keyword_spec, trends in staged_trends:
            ticker = entry["ticker"]
            geo = keyword_spec.get("geo", "")
            storage.save_trends(keyword=keyword_spec["term"], geo=geo, records=trends)
            combined = combine(trends, staged_stocks[ticker])
            storage.save_combined(keyword=keyword_spec["term"], geo=geo, ticker=ticker, df=combined)

        return {
            "tickers": len(entries),
            "keyword_pairs": len(staged_trends),
        }
