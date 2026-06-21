from __future__ import annotations

import argparse
import os
from pathlib import Path

from .automation import GoogleTrendsWatchlistRunner
from .exporter import GoogleTrendsCsvExporter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Google Trends watchlist CSV automation")
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--base-dir", default=".", help="Repository root (default: .)")
    shared.add_argument(
        "--watchlist",
        default="src/google_trends_data/watchlist.json",
        help="Path to the Google Trends watchlist JSON",
    )
    shared.add_argument("--timeframe", default="today 5-y", help="Google Trends timeframe string")
    shared.add_argument("--stock-period", default="5y", help="yfinance period string")
    shared.add_argument("--hl", default="en-US", help="Google Trends locale")
    shared.add_argument(
        "--profile-dir",
        default=os.environ.get("GOOGLE_TRENDS_PROFILE_DIR", "~/.cache/google-trends-playwright"),
        help="Persistent Chromium profile directory",
    )
    shared.add_argument("--download-dir", default=None, help="Optional CSV download directory")
    shared.add_argument("--headful", action="store_true", help="Run Chromium with a visible window")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("refresh-enabled", parents=[shared], help="Refresh all enabled watchlist entries")

    refresh_ticker = subparsers.add_parser("refresh-ticker", parents=[shared], help="Refresh a single watchlist ticker")
    refresh_ticker.add_argument("--ticker", required=True, help="Ticker symbol to refresh")

    subparsers.add_parser("validate", parents=[shared], help="Export and parse the first enabled watchlist item")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    exporter = GoogleTrendsCsvExporter(profile_dir=Path(args.profile_dir).expanduser())
    runner = GoogleTrendsWatchlistRunner(
        base_dir=Path(args.base_dir).resolve(),
        watchlist_path=Path(args.watchlist),
        exporter=exporter,
    )

    common = {
        "timeframe": args.timeframe,
        "hl": args.hl,
        "headless": not args.headful,
        "download_dir": Path(args.download_dir) if args.download_dir else None,
    }

    if args.command == "refresh-enabled":
        result = runner.refresh_enabled(stock_period=args.stock_period, **common)
    elif args.command == "refresh-ticker":
        result = runner.refresh_ticker(args.ticker, stock_period=args.stock_period, **common)
    else:
        result = runner.validate(**common)

    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
