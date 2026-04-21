from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from compute_availability_data.models import PipelineResult, RunContext
from compute_availability_data.sources.openrouter import OpenRouterSource
from compute_availability_data.storage import StorageManager


class ComputeAvailabilityPipeline:
    # NOTE: Package name is legacy. AWS Spot and Lambda Cloud sources were removed;
    # this pipeline now only scrapes the OpenRouter model catalog.
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.openrouter_source = OpenRouterSource()

    def run_daily_update(self) -> PipelineResult:
        context = self._create_context()
        scraped_at = context.scraped_at_iso

        # 1. Fetch
        or_snapshot = self.openrouter_source.fetch_snapshot()

        # 2. Store Raw
        manifest = {
            "run_id": context.run_id,
            "scraped_at": scraped_at,
            "sources": ["openrouter"],
        }
        self.storage.write_raw_run(context.run_id, [or_snapshot], manifest)

        # 3. Extract & Normalize
        or_records = self.openrouter_source.extract(or_snapshot, context.run_id, scraped_at)

        # 4. Upsert
        or_df = self.storage.upsert_dataset("raw_openrouter_models", or_records)

        written = {
            "raw_openrouter_models": len(or_df),
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
