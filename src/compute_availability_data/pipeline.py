from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from compute_availability_data.models import PipelineResult, RunContext
from compute_availability_data.sources.aws_spot import AwsSpotSource
from compute_availability_data.sources.lambda_cloud import LambdaCloudSource
from compute_availability_data.sources.openrouter import OpenRouterSource
from compute_availability_data.storage import StorageManager


class ComputeAvailabilityPipeline:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.openrouter_source = OpenRouterSource()
        self.lambda_source = LambdaCloudSource()
        self.aws_source = AwsSpotSource()

    def run_daily_update(self) -> PipelineResult:
        context = self._create_context()
        scraped_at = context.scraped_at_iso
        
        # 1. Fetch
        or_snapshot = self.openrouter_source.fetch_snapshot()
        lc_snapshot = self.lambda_source.fetch_snapshot()
        aws_snapshots = self.aws_source.fetch_snapshots()
        
        all_snapshots = [or_snapshot, lc_snapshot] + aws_snapshots
        
        # 2. Store Raw
        manifest = {
            "run_id": context.run_id,
            "scraped_at": scraped_at,
            "sources": ["openrouter", "lambda_cloud", "aws_spot"],
        }
        self.storage.write_raw_run(context.run_id, all_snapshots, manifest)
        
        # 3. Extract & Normalize
        or_records = self.openrouter_source.extract(or_snapshot, context.run_id, scraped_at)
        lc_records = self.lambda_source.extract(lc_snapshot, context.run_id, scraped_at)
        aws_records = self.aws_source.extract(aws_snapshots, context.run_id, scraped_at)
        
        # 4. Upsert
        or_df = self.storage.upsert_dataset("raw_openrouter_models", or_records)
        lc_df = self.storage.upsert_dataset("raw_lambda_instance_types", lc_records)
        aws_df = self.storage.upsert_dataset("raw_aws_spot_price_history", aws_records)
        
        written = {
            "raw_openrouter_models": len(or_df),
            "raw_lambda_instance_types": len(lc_df),
            "raw_aws_spot_price_history": len(aws_df),
        }
        
        return PipelineResult(
            run_id=context.run_id,
            datasets_written=written,
            raw_run_dir=str(self.storage.raw_root / context.run_id),
        )

    def _create_context(self) -> RunContext:
        return RunContext(
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            scraped_at=datetime.now(timezone.utc),
        )
