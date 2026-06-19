from __future__ import annotations

import argparse
from pathlib import Path

from minerals_usgs_data.pipeline import MineralsUSGSPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="USGS minerals data ingestion pipeline")
    parser.add_argument("pdf_path", help="Path to the USGS Mineral Commodity Summaries PDF")
    parser.add_argument("--report-year", required=True, type=int, help="Report year for output partitioning")
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    pipeline = MineralsUSGSPipeline(base_dir=Path(args.base_dir).resolve())
    outputs = pipeline.run(pdf_path=Path(args.pdf_path), report_year=args.report_year)

    for key, path in outputs.items():
        print(f"{key}={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
