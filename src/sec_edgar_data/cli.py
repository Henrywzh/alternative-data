import argparse
import logging
from pathlib import Path
import sys

from .pipeline import EdgarPipeline

def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

def main():
    parser = argparse.ArgumentParser(
        description="Search SEC EDGAR full-text filings for a keyword watchlist."
    )
    parser.add_argument(
        "--data-dir",
        default=".",
        help="Base directory for data storage (default: current directory)",
    )
    parser.add_argument(
        "--queries",
        nargs="*",
        default=None,
        help="Specific list of full-text search query terms. If omitted, uses the default watchlist.",
    )
    parser.add_argument(
        "--forms",
        nargs="*",
        default=None,
        help="Filing form types to restrict the search to (default: 8-K, 10-Q, 10-K).",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        help="How many days back to search for new filings (default: 7).",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    setup_logging(level=logging.DEBUG if args.debug else logging.INFO)

    base_path = Path(args.data_dir).resolve()
    pipeline = EdgarPipeline(base_dir=base_path)
    res = pipeline.run(queries=args.queries, forms=args.forms, lookback_days=args.lookback_days)

    requested = len(args.queries) if args.queries else len(pipeline.DEFAULT_QUERIES)
    if res["errors"] and len(res["errors"]) >= requested:
        print(f"SEC EDGAR Update Failed: every requested query errored: {res}")
        sys.exit(1)

    print(f"SEC EDGAR Update Successful: {res}")

if __name__ == "__main__":
    main()
