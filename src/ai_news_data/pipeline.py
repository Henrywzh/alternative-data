from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_news_data.models import GenericRecord, RunContext
from ai_news_data.sources.blogs import BlogsSource
from ai_news_data.sources.hackernews import HackerNewsSource
from ai_news_data.sources.huggingface import HuggingFaceSource
from ai_news_data.sources.reddit import RedditSource
from ai_news_data.storage import StorageManager


class ValidationError(RuntimeError):
    """Raised when a source's live fetch looks blocked/broken rather than genuinely empty."""


@dataclass
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: Path


# A source coming back fully empty usually means it's blocked/rate-limited or
# its layout changed, not that there's genuinely zero AI news today. Gate
# before upsert so a bad run can never silently erase yesterday's history.
MIN_EXPECTED_ROWS: dict[str, int] = {
    "ai_news_hf_papers": 1,
    "ai_news_hf_trending_models": 1,
    "ai_news_hn_stories": 1,
    "ai_news_reddit_posts": 1,
    "ai_news_blog_posts": 1,
}


class AiNewsPipeline:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.sources = {
            "huggingface": HuggingFaceSource(),
            "hackernews": HackerNewsSource(),
            "reddit": RedditSource(),
            "blogs": BlogsSource(),
        }

    def _context(self) -> RunContext:
        return RunContext(
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            scraped_at=datetime.now(timezone.utc),
        )

    def run_source(self, name: str) -> PipelineResult:
        source = self.sources[name]
        context = self._context()
        snapshots = source.fetch_snapshots()

        manifest: dict[str, Any] = {
            "run_id": context.run_id,
            "source": name,
            "scraped_at": context.scraped_at_iso,
            "status": "pending",
        }
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)

        try:
            extracted: dict[str, list[GenericRecord]] = source.extract(snapshots, context)
            self._assert_quality(extracted)

            datasets_written: dict[str, int] = {}
            for dataset_id, records in extracted.items():
                if records:
                    datasets_written[dataset_id] = len(self.storage.upsert_dataset(dataset_id, records))
                else:
                    datasets_written[dataset_id] = len(self.storage.load_dataset(dataset_id))

            manifest["status"] = "success"
            self.storage.write_raw_run(context.run_id, snapshots, manifest)
            return PipelineResult(context.run_id, datasets_written, raw_run_dir)
        except Exception as exc:
            manifest["status"] = "failed"
            manifest["error"] = str(exc)
            self.storage.write_raw_run(context.run_id, snapshots, manifest)
            raise

    def run_all(self) -> dict[str, PipelineResult]:
        results: dict[str, PipelineResult] = {}
        errors: dict[str, str] = {}
        for name in self.sources:
            try:
                results[name] = self.run_source(name)
            except Exception as exc:
                # One broken source (e.g. Reddit 429s) shouldn't block the
                # others' writes, which have already landed by this point.
                errors[name] = str(exc)
        if errors:
            print(f"WARNING: sources failed: {errors}")
        return results

    @staticmethod
    def _assert_quality(extracted: dict[str, list[GenericRecord]]) -> None:
        failures = []
        for dataset_id, records in extracted.items():
            min_rows = MIN_EXPECTED_ROWS.get(dataset_id, 0)
            if len(records) < min_rows:
                failures.append(f"{dataset_id}: only {len(records)} rows (expected >= {min_rows})")
        if failures:
            raise ValidationError("; ".join(failures))
