import argparse
import sys
from pathlib import Path
from replicate_data.pipeline import run_replicate_scrape

def main():
    parser = argparse.ArgumentParser(description="Replicate AI data scraper CLI")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path("."),
        help="Base directory of the repository (default: current directory)",
    )
    subparsers = parser.add_subparsers(dest="command")

    scrape_parser = subparsers.add_parser("scrape", help="Execute Replicate scrape pipeline")
    scrape_parser.add_argument("--top-models", type=int, default=10, help="Top models per collection to deep scrape")

    args = parser.parse_args()

    if args.command == "scrape":
        run_replicate_scrape(base_dir=args.base_dir.resolve(), top_models_per_col=args.top_models)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
