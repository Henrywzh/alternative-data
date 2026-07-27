from __future__ import annotations

import argparse
import os
from pathlib import Path

from .automation import GoogleTrendsWatchlistRunner
from .exporter import FallbackGoogleTrendsExporter
from .exporter import GoogleTrendsCsvExporter
from .exporter import SerpApiCsvExporter


def _resolve_api_key(base_dir: Path, name: str) -> str:
    import os

    value = os.environ.get(name, "")
    if value:
        return value
    config_path = base_dir / ".config"
    if not config_path.exists():
        return ""
    prefix = f"{name}="
    for line in config_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Google Trends watchlist CSV automation")
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--base-dir", default=".", help="Repository root (default: .)")
    shared.add_argument(
        "--watchlist",
        default="src/google_trends_data/watchlist.json",
        help="Path to the Google Trends watchlist JSON",
    )
    shared.add_argument(
        "--search-delay",
        type=float,
        default=2.0,
        help="Minimum seconds between CSV/SerpApi search attempts (default: 2)",
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
    shared.add_argument(
        "--frequency",
        choices=("all", "weekly", "monthly"),
        default="all",
        help="Enabled watchlist refresh frequency (default: all)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("refresh-enabled", parents=[shared], help="Refresh all enabled watchlist entries")
    subparsers.add_parser(
        "refresh-enabled-library",
        parents=[shared],
        help="Refresh all enabled watchlist entries using the Python Trends fetcher",
    )

    refresh_ticker = subparsers.add_parser("refresh-ticker", parents=[shared], help="Refresh a single watchlist ticker")
    refresh_ticker.add_argument("--ticker", required=True, help="Ticker symbol to refresh")

    subparsers.add_parser("validate", parents=[shared], help="Export and parse the first enabled watchlist item")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    base_dir = Path(args.base_dir).resolve()
    exporter = FallbackGoogleTrendsExporter(
        primary=GoogleTrendsCsvExporter(profile_dir=Path(args.profile_dir).expanduser(), max_attempts=1),
        fallback=SerpApiCsvExporter(api_key=_resolve_api_key(base_dir, "SERP_API_KEY")),
        delay_seconds=args.search_delay,
    )
    runner = GoogleTrendsWatchlistRunner(
        base_dir=base_dir,
        watchlist_path=Path(args.watchlist),
        exporter=exporter,
    )

    common = {
        "timeframe": args.timeframe,
        "hl": args.hl,
        "headless": not args.headful,
        "download_dir": Path(args.download_dir) if args.download_dir else None,
    }
    frequency = {"frequency": args.frequency} if args.frequency != "all" else {}

    if args.command == "refresh-enabled":
        result = runner.refresh_enabled(stock_period=args.stock_period, **common, **frequency)
    elif args.command == "refresh-enabled-library":
        result = runner.refresh_enabled_with_fetcher(
            timeframe=args.timeframe,
            stock_period=args.stock_period,
            **frequency,
        )
    elif args.command == "refresh-ticker":
        result = runner.refresh_ticker(args.ticker, stock_period=args.stock_period, **common)
    else:
        result = runner.validate(**common, **frequency)

    for key, value in result.items():
        print(f"{key}={value}")
    if exporter.source_summary():
        print(f"export_sources={exporter.source_summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
