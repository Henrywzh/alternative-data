from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from openrouter_data.models import DatasetRecord, RunContext
from openrouter_data.sources.rankings import RankingsSource
from openrouter_data.storage import StorageManager


DATASET_IDS = ("top_models", "market_share", "categories_programming")


@dataclass
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: Path


class RankingsPipeline:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.source = RankingsSource()

    def run_initial_backfill(self) -> PipelineResult:
        return self._run(mode="initial-backfill")

    def run_backfill_missing(self) -> PipelineResult:
        return self._run(mode="backfill-missing")

    def run_weekly_update(self) -> PipelineResult:
        return self._run(mode="weekly-update")

    def validate(self, *, fixture_html: str | None = None, fixture_programming_html: str | None = None) -> dict[str, int]:
        context = RunContext(run_id="validate", scraped_at=datetime.now(UTC))
        if fixture_html is None:
            snapshots = self.source.fetch_snapshots()
        else:
            from openrouter_data.models import Snapshot

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

    def _run(self, *, mode: str) -> PipelineResult:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        context = RunContext(run_id=run_id, scraped_at=datetime.now(UTC))
        snapshots = self.source.fetch_snapshots()
        extracted = self.source.extract(snapshots, context)
        filtered = self._filter_for_mode(mode, extracted)
        datasets_written = {}
        for dataset_id, records in filtered.items():
            if records:
                datasets_written[dataset_id] = len(self.storage.upsert_dataset(dataset_id, records))
            else:
                datasets_written[dataset_id] = len(self.storage.load_dataset(dataset_id))
        manifest = self._build_manifest(mode=mode, context=context, extracted=filtered)
        raw_run_dir = self.storage.write_raw_run(run_id, snapshots, manifest)
        return PipelineResult(run_id=run_id, datasets_written=datasets_written, raw_run_dir=raw_run_dir)

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
            existing_weeks = set(existing["week_start_date"].tolist()) if not existing.empty else set()
            if mode == "backfill-missing":
                filtered[dataset_id] = [record for record in records if record.week_start_date not in existing_weeks]
            elif mode == "weekly-update":
                filtered[dataset_id] = [record for record in records if record.week_start_date not in existing_weeks]
            else:
                raise ValueError(f"Unsupported mode: {mode}")
        return filtered

    @staticmethod
    def _build_manifest(
        *,
        mode: str,
        context: RunContext,
        extracted: dict[str, list[DatasetRecord]],
    ) -> dict[str, Any]:
        return {
            "run_id": context.run_id,
            "mode": mode,
            "scraped_at": context.scraped_at_iso,
            "parser_version": "0.1.0",
            "datasets": [
                {
                    "dataset_id": dataset_id,
                    "status": "ok" if records else "no_new_rows",
                    "rows": len(records),
                    "source_urls": sorted({record.source_url for record in records}),
                }
                for dataset_id, records in extracted.items()
            ],
        }
