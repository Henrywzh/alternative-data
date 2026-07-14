from __future__ import annotations

import argparse
from pathlib import Path

from minerals_signal_data.pipeline import MineralsSignalPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mineral-linked stock signals research pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--base-dir", default=".", help="Repository root for data writes")
    shared.add_argument("--workbook", help="Path to the mineral workbook (.xlsx) or critical-minerals CSV")
    shared.add_argument(
        "--stock-mapping",
        help="Path to the stock-mapping CSV (defaults to a sibling stock_mapping.csv for CSV workbooks; "
        "ignored for .xlsx, which reads the mapping sheet)",
    )
    shared.add_argument("--run-label", default="latest", help="Output partition label")

    subparsers.add_parser(
        "load-workbook",
        parents=[shared],
        help="Normalize workbook sheets into analytics-ready tables",
    )
    subparsers.add_parser(
        "build-price-universe",
        parents=[shared],
        help="Alias for workbook normalization focused on price sources",
    )

    fetch_prices = subparsers.add_parser(
        "fetch-price-history",
        parents=[shared],
        help="Fetch public mineral price history",
    )
    fetch_prices.add_argument("--start-date", help="Optional start date")
    fetch_prices.add_argument("--end-date", help="Optional end date")
    fetch_prices.add_argument("--manual-prices", help="Optional CSV for manual/proxy mineral series")

    derive = subparsers.add_parser(
        "derive-signals",
        parents=[shared],
        help="Derive weekly mineral and stock signals",
    )
    derive.add_argument("--mineral-prices", required=True, help="CSV of mineral daily prices")

    backtest = subparsers.add_parser("backtest", parents=[shared], help="Run weekly long-only backtest")
    backtest.add_argument("--stock-signals", required=True, help="CSV of stock weekly signals")
    backtest.add_argument("--stock-prices", required=True, help="CSV of stock daily adjusted prices")

    run_v1 = subparsers.add_parser("run-v1", parents=[shared], help="Run the live-supported V1 research pipeline")
    run_v1.add_argument("--start-date", default="2022-01-01", help="Backtest start date")
    run_v1.add_argument("--end-date", help="Optional backtest end date")

    run_v2 = subparsers.add_parser("run-v2", parents=[shared], help="Run the broader V2 price-coverage pipeline")
    run_v2.add_argument("--start-date", default="2022-01-01", help="Backtest start date")
    run_v2.add_argument("--end-date", help="Optional backtest end date")
    run_v2.add_argument(
        "--min-mineral-coverage",
        type=int,
        default=0,
        help="Fail (non-zero exit) if fewer than N minerals fetch price history; guards against "
        "silent bot-blocked scrapes (0 disables the check)",
    )

    run_live = subparsers.add_parser("run-live", parents=[shared], help="Run the live dashboard price-refresh pipeline")
    run_live.add_argument("--start-date", default="2022-01-01", help="Price history start date")
    run_live.add_argument("--end-date", help="Optional price history end date")

    subparsers.add_parser("validate", parents=[shared], help="Validate workbook coverage and mappings")

    tungsten = subparsers.add_parser("scrape-tungsten", help="Scrape daily tungsten prices from Chinatungsten/CTIA")
    tungsten.add_argument("--base-dir", default=".", help="Repository root for data writes")
    tungsten.add_argument("--max-pages", type=int, default=3, help="Max category pages to scrape")
    tungsten.add_argument("--since-date", help="Only write articles on/after this YYYY-MM-DD date")
    tungsten.add_argument("--since-days", type=int, help="Only write articles from the last N days")
    tungsten.add_argument(
        "--source",
        choices=["ctia", "chinatungsten"],
        default="chinatungsten",
        help="Data source to scrape (defaults to chinatungsten; CTIA is explicit)",
    )
    tungsten.add_argument(
        "--with-images",
        action="store_true",
        help="Also download price-table/trend images (local only; not committed)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    pipeline = MineralsSignalPipeline(Path(args.base_dir).resolve())

    if args.command in {"load-workbook", "build-price-universe"}:
        outputs = pipeline.load_workbook(
            args.workbook,
            stock_mapping_path=args.stock_mapping,
            run_label=args.run_label,
        )
    elif args.command == "fetch-price-history":
        outputs = pipeline.fetch_price_history(
            args.workbook,
            start_date=args.start_date,
            end_date=args.end_date,
            manual_prices_path=args.manual_prices,
            run_label=args.run_label,
        )
    elif args.command == "derive-signals":
        outputs = pipeline.derive_signals(
            args.workbook,
            args.mineral_prices,
            stock_mapping_path=args.stock_mapping,
            run_label=args.run_label,
        )
    elif args.command == "backtest":
        outputs = pipeline.backtest(args.stock_signals, args.stock_prices, run_label=args.run_label)
    elif args.command == "run-v1":
        outputs = pipeline.run_v1(
            args.workbook,
            stock_mapping_path=args.stock_mapping,
            start_date=args.start_date,
            end_date=args.end_date,
            run_label=args.run_label,
        )
    elif args.command == "run-v2":
        outputs = pipeline.run_v2(
            args.workbook,
            stock_mapping_path=args.stock_mapping,
            start_date=args.start_date,
            end_date=args.end_date,
            run_label=args.run_label,
            min_mineral_coverage=args.min_mineral_coverage,
        )
    elif args.command == "run-live":
        outputs = pipeline.run_live(
            args.workbook,
            stock_mapping_path=args.stock_mapping,
            start_date=args.start_date,
            end_date=args.end_date,
            run_label=args.run_label,
        )
    elif args.command == "scrape-tungsten":
        from minerals_signal_data.chinatungsten_scraper import scrape_range

        scrape_range(
            args.base_dir,
            max_pages=args.max_pages,
            with_images=args.with_images,
            since_date=args.since_date,
            since_days=args.since_days,
            source=args.source,
        )
        return 0
    elif args.command == "validate":
        counts = pipeline.validate(args.workbook, stock_mapping_path=args.stock_mapping)
        for key, value in counts.items():
            print(f"{key}={value}")
        return 0
    else:
        parser.error(f"Unknown command: {args.command}")
        return 1

    for key, value in outputs.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
