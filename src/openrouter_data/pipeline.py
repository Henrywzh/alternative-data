from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from openrouter_data.models import DatasetRecord, RunContext, Snapshot
from openrouter_data.sources.apps import AppsSource
from openrouter_data.sources.activity import ActivitySource
from openrouter_data.sources.base import SourceExtractor
from openrouter_data.sources.rankings import RankingsSource
from openrouter_data.storage import StorageManager


RANKINGS_DATASET_IDS = ("top_models", "market_share", "categories_programming")
APPS_DATASET_IDS = (
    "app_metadata_snapshots",
    "app_usage_daily",
    "app_top_models_daily_snapshot",
    "apps_global_ranking_snapshots",
    "apps_trending_snapshots",
)
ACTIVITY_DATASET_IDS = ("openrouter_model_activity",)


@dataclass
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: Path


class BasePipeline:
    dataset_ids: tuple[str, ...]

    def __init__(self, base_dir: Path, source: SourceExtractor) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.source = source

    def _create_context(self, *, run_id: str | None = None) -> RunContext:
        return RunContext(
            run_id=run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            scraped_at=datetime.now(timezone.utc),
        )

    def _execute(self, *, mode: str, snapshots: list[Snapshot] | None = None) -> PipelineResult:
        context = self._create_context()
        snapshots = self.source.fetch_snapshots() if snapshots is None else snapshots
        
        # Build a preliminary manifest so we have something on disk even if extraction fails
        manifest = self._build_manifest(mode=mode, context=context, extracted={})
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)

        try:
            extracted = self.source.extract(snapshots, context)
            filtered = self._filter_for_mode(mode, extracted)
            datasets_written = {}
            for dataset_id in self.dataset_ids:
                records = filtered.get(dataset_id, [])
                if records:
                    datasets_written[dataset_id] = len(self.storage.upsert_dataset(dataset_id, records))
                else:
                    datasets_written[dataset_id] = len(self.storage.load_dataset(dataset_id))
            
            # Update manifest with extraction results
            manifest = self._build_manifest(mode=mode, context=context, extracted=filtered)
            self.storage.write_raw_run(context.run_id, snapshots, manifest)
            
            return PipelineResult(run_id=context.run_id, datasets_written=datasets_written, raw_run_dir=raw_run_dir)
        except Exception as exc:
            # Update manifest with error status if possible
            manifest["status"] = "failed"
            manifest["error"] = str(exc)
            self.storage.write_raw_run(context.run_id, snapshots, manifest)
            raise

    def _build_manifest(
        self,
        *,
        mode: str,
        context: RunContext,
        extracted: dict[str, list[DatasetRecord]],
    ) -> dict[str, Any]:
        return {
            "run_id": context.run_id,
            "mode": mode,
            "scraped_at": context.scraped_at_iso,
            "parser_version": "0.2.0",
            "source_name": self.source.name,
            "datasets": [
                {
                    "dataset_id": dataset_id,
                    "status": "ok" if extracted.get(dataset_id) else "no_new_rows",
                    "rows": len(extracted.get(dataset_id, [])),
                    "source_urls": sorted({record.source_url for record in extracted.get(dataset_id, [])}),
                }
                for dataset_id in self.dataset_ids
            ],
        }

    def _filter_for_mode(
        self,
        mode: str,
        extracted: dict[str, list[DatasetRecord]],
    ) -> dict[str, list[DatasetRecord]]:
        raise NotImplementedError


class RankingsPipeline(BasePipeline):
    dataset_ids = RANKINGS_DATASET_IDS

    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir, RankingsSource())

    def run_initial_backfill(self) -> PipelineResult:
        return self._execute(mode="initial-backfill")

    def run_backfill_missing(self) -> PipelineResult:
        return self._execute(mode="backfill-missing")

    def run_weekly_update(self) -> PipelineResult:
        return self._execute(mode="weekly-update")

    def validate(self, *, fixture_html: str | None = None, fixture_programming_html: str | None = None) -> dict[str, int]:
        context = self._create_context(run_id="validate")
        if fixture_html is None:
            snapshots = self.source.fetch_snapshots()
        else:
            snapshots = [
                Snapshot(name="rankings", source_url="fixture://rankings", body=fixture_html),
                Snapshot(
                    name="rankings_programming",
                    source_url="fixture://rankings_programming",
                    body=fixture_programming_html or fixture_html,
                ),
            ]
        extracted = self.source.extract(snapshots, context)
        return {dataset_id: len(records) for dataset_id, records in extracted.items()}

    def _filter_for_mode(
        self,
        mode: str,
        extracted: dict[str, list[DatasetRecord]],
    ) -> dict[str, list[DatasetRecord]]:
        if mode == "initial-backfill":
            return extracted

        filtered: dict[str, list[DatasetRecord]] = {}
        for dataset_id, records in extracted.items():
            existing = self.storage.load_dataset(dataset_id)
            existing_weeks = set(existing["week_start_date"].dropna().tolist()) if not existing.empty else set()
            if mode in {"backfill-missing", "weekly-update"}:
                filtered[dataset_id] = [record for record in records if record.week_start_date not in existing_weeks]
            else:
                raise ValueError(f"Unsupported mode: {mode}")
        return filtered


class AppsPipeline(BasePipeline):
    dataset_ids = APPS_DATASET_IDS

    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir, AppsSource())

    def run_initial_backfill(self) -> PipelineResult:
        return self._execute(mode="apps-initial-backfill")

    def run_daily_update(self) -> PipelineResult:
        return self._execute(mode="apps-daily-update")

    def validate(
        self,
        *,
        directory_fixture_html: str | None = None,
        app_fixture_html: str | None = None,
    ) -> dict[str, int]:
        context = self._create_context(run_id="validate-apps")
        if directory_fixture_html is None and app_fixture_html is None:
            snapshots = self.source.fetch_snapshots()
        else:
            fixture_body = app_fixture_html or directory_fixture_html or ""
            snapshots = [
                Snapshot(name="apps_directory", source_url="fixture://apps", body=directory_fixture_html or fixture_body),
                Snapshot(
                    name="app_openclaw",
                    source_url="fixture://apps?url=openclaw",
                    body=fixture_body,
                ),
            ]
        extracted = self.source.extract(snapshots, context)
        return {dataset_id: len(records) for dataset_id, records in extracted.items()}

    def _filter_for_mode(
        self,
        mode: str,
        extracted: dict[str, list[DatasetRecord]],
    ) -> dict[str, list[DatasetRecord]]:
        if mode not in {"apps-initial-backfill", "apps-daily-update"}:
            raise ValueError(f"Unsupported mode: {mode}")

        filtered = dict(extracted)
        if mode == "apps-initial-backfill":
            return filtered

        existing_usage = self.storage.load_dataset("app_usage_daily")
        if existing_usage.empty:
            return filtered

        seen_keys = {
            (row.app_id, row.usage_date, row.model_permaslug)
            for row in existing_usage[["app_id", "usage_date", "model_permaslug"]].itertuples(index=False)
        }
        filtered["app_usage_daily"] = [
            record
            for record in extracted.get("app_usage_daily", [])
            if (record.app_id, record.usage_date, record.model_permaslug) not in seen_keys
        ] or extracted.get("app_usage_daily", [])
        return filtered


class ActivityPipeline(BasePipeline):
    dataset_ids = ACTIVITY_DATASET_IDS

    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir, ActivitySource())

    def run_daily_update(self, limit: int = 200) -> PipelineResult:
        """Discovery phase then execute common pipeline logic."""
        # 1. Discover top N slugs
        popular_slugs = self.source.fetch_popular_slugs(limit=limit)
        
        # 2. Fetch snapshots for those slugs
        snapshots = self.source.fetch_snapshots(popular_slugs)
        
        # 3. Standard execution
        return self._execute(mode="activity-daily-update", snapshots=snapshots)

    def _filter_for_mode(
        self,
        mode: str,
        extracted: dict[str, list[DatasetRecord]],
    ) -> dict[str, list[DatasetRecord]]:
        # For activity daily update, we typically keep all extracted rows for the day 
        # (duplicates are handled by StorageManager natural keys)
        return extracted
