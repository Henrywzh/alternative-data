from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .pipeline import SpPmiPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="S&P Global PMI Sub-index Ingestion")
    parser.add_argument("--base-dir", type=Path, default=Path("."))
    args = parser.parse_args()
    print(json.dumps(SpPmiPipeline(base_dir=args.base_dir.resolve()).run(), indent=2))


if __name__ == "__main__":
    main()
