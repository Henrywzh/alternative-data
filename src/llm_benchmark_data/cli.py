from __future__ import annotations

import argparse
from pathlib import Path

from llm_benchmark_data.pipeline import BenchmarkPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM Benchmark and HBM Demand Ingestion Pipeline")
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("update", help="Fetch ZeroEval benchmarks and update normalized Parquet")
    subparsers.add_parser("view", help="View the current benchmarks dataset")

    args = parser.parse_args()
    base_dir = Path(args.base_dir).resolve()
    pipeline = BenchmarkPipeline(base_dir)

    if args.command == "update":
        print("🚀 Fetching latest LLM benchmarks from ZeroEval...")
        result = pipeline.run()
        print(f"✅ Update successful!")
        print(f"   Run ID: {result.run_id}")
        print(f"   Total Models: {result.rows_written}")
        print(f"   Raw output: {result.raw_run_dir}")
    elif args.command == "view":
        df = pipeline.storage.load_dataset()
        if df.empty:
            print("❌ No data found.")
        else:
            print(df.sort_values("release_date", ascending=False).head(20))


if __name__ == "__main__":
    main()
