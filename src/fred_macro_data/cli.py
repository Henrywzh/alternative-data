import argparse
import logging
from pathlib import Path
import sys

from .pipeline import FredMacroPipeline

def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

def main():
    parser = argparse.ArgumentParser(
        description="Fetch FRED macro/financial-conditions series metadata and observations."
    )
    parser.add_argument(
        "--data-dir",
        default=".",
        help="Base directory for data storage (default: current directory)",
    )
    parser.add_argument(
        "--series",
        nargs="*",
        default=None,
        help="Specific list of FRED series IDs to fetch. If omitted, uses the default whitelist.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    setup_logging(level=logging.DEBUG if args.debug else logging.INFO)

    base_path = Path(args.data_dir).resolve()
    pipeline = FredMacroPipeline(base_dir=base_path)
    res = pipeline.run(series_ids=args.series)

    requested = len(args.series) if args.series else len(pipeline.DEFAULT_SERIES)
    if res["errors"] and len(res["errors"]) >= requested:
        print(f"FRED Macro Update Failed: every requested series errored: {res}")
        sys.exit(1)

    print(f"FRED Macro Update Successful: {res}")

if __name__ == "__main__":
    main()
