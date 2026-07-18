import argparse
import logging
from pathlib import Path
import sys

from .pipeline import OfrPipeline

def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

def main():
    parser = argparse.ArgumentParser(
        description="Fetch OFR Hedge Fund Monitor metadata and timeseries data."
    )
    parser.add_argument(
        "--data-dir",
        default=".",
        help="Base directory for data storage (default: current directory)",
    )
    parser.add_argument(
        "--mnemonics",
        nargs="*",
        default=None,
        help="Specific list of mnemonics to fetch. If omitted, uses default list.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    setup_logging(level=logging.DEBUG if args.debug else logging.INFO)

    base_path = Path(args.data_dir).resolve()
    pipeline = OfrPipeline(base_dir=base_path)
    res = pipeline.run(mnemonics=args.mnemonics)

    requested = len(args.mnemonics) if args.mnemonics else len(pipeline.DEFAULT_MNEMONICS)
    if res["errors"] and len(res["errors"]) >= requested:
        print(f"OFR Update Failed: every requested mnemonic errored: {res}")
        sys.exit(1)

    print(f"OFR Update Successful: {res}")

if __name__ == "__main__":
    main()
