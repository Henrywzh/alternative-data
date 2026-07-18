import argparse
import logging
from pathlib import Path
import sys

from .pipeline import NewsPipeline

def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

def main():
    parser = argparse.ArgumentParser(
        description="Fetch global financial news from Guardian, Marketaux, Currents, and GDELT."
    )
    parser.add_argument(
        "--data-dir",
        default=".",
        help="Base directory for data storage (default: current directory)",
    )
    parser.add_argument(
        "--query",
        default="finance",
        help=(
            "Free-text query term, applied to Guardian and GDELT (default: 'finance'). "
            "Marketaux uses a fixed stock symbol list and Currents uses a fixed "
            "'business' category on the free tier, so this flag has no effect on them."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Max number of articles to fetch per source (default: 5)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    setup_logging(level=logging.DEBUG if args.debug else logging.INFO)

    base_path = Path(args.data_dir).resolve()
    pipeline = NewsPipeline(base_dir=base_path)
    configured_sources = sum(
        client is not None
        for client in (
            pipeline.guardian_client,
            pipeline.marketaux_client,
            pipeline.currents_client,
            pipeline.gdelt_client,
        )
    )
    res = pipeline.run(query=args.query, limit=args.limit)

    if configured_sources and len(res["errors"]) >= configured_sources:
        print(f"Global News Update Failed: every configured source errored: {res}")
        sys.exit(1)

    print(f"Global News Update Successful: {res}")

if __name__ == "__main__":
    main()
