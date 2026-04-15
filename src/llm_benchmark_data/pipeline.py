from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from llm_benchmark_data.models import RunContext, Snapshot, BenchmarkPoint
from llm_benchmark_data.sources.zeroeval import ZeroEvalSource
from llm_benchmark_data.storage import StorageManager


@dataclass
class PipelineResult:
    run_id: str
    rows_written: int
    raw_run_dir: Path


class BenchmarkPipeline:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.source = ZeroEvalSource()

    def run(self) -> PipelineResult:
        context = RunContext(
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            scraped_at=datetime.now(timezone.utc),
        )
        
        # 1. Fetch
        snapshots = self.source.fetch_snapshots()
        
        # 2. Extract
        points = self.source.extract(snapshots, run_id=context.run_id)
        
        # 3. Store Raw
        manifest = {
            "run_id": context.run_id,
            "scraped_at": context.scraped_at_iso,
            "source": "zeroeval",
            "models_count": len(points),
        }
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)
        
        # 4. Upsert Normalized
        df = self.storage.upsert_dataset(points)
        
        return PipelineResult(
            run_id=context.run_id,
            rows_written=len(df),
            raw_run_dir=raw_run_dir
        )


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="LLM Benchmark Data Pipeline")
    parser.add_argument("command", choices=["update", "view"])
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.parent
    pipeline = BenchmarkPipeline(project_root)

    if args.command == "update":
        print("🚀 Running LLM Benchmark update (Source: ZeroEval)...")
        result = pipeline.run()
        print(f"✅ Update complete!")
        print(f"   Run ID: {result.run_id}")
        print(f"   Total Models in Database: {result.rows_written}")
        print(f"   Raw data saved to: {result.raw_run_dir}")
    elif args.command == "view":
        df = pipeline.storage.load_dataset()
        if df.empty:
            print("❌ No data found.")
        else:
            print(df.tail(10))
