from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

import pandas as pd

from openrouter_data.models import DatasetRecord, RunContext, Snapshot
from openrouter_data.sources.apps import AppsSource
from openrouter_data.sources.activity import ACTIVITY_PROVIDER_SLUGS, ActivitySource
from openrouter_data.sources.base import SourceExtractor
from openrouter_data.sources.provider_activity import ProviderActivitySource, PROVIDER_SLUGS, PROVIDER_ACTIVITY_DATASET_ID
from openrouter_data.sources.rankings import CONTEXT_LENGTH_DATASET_ID, MODALITY_RANKINGS_DATASET_ID, RankingsSource
from openrouter_data.sources.task_spend import TASK_SPEND_DATASET_ID, TaskSpendSource
from openrouter_data.storage import StorageManager


RANKINGS_DATASET_IDS = (
    "top_models",
    "market_share",
    "provider_weekly_requests",
    "categories_programming",
    "context_length_requests",
    "modality_rankings",
)
APPS_DATASET_IDS = (
    "app_metadata_snapshots",
    "app_usage_daily",
    "app_top_models_daily_snapshot",
    "apps_global_ranking_snapshots",
    "apps_trending_snapshots",
)
ACTIVITY_DATASET_IDS = ("openrouter_model_activity",)
TASK_SPEND_DATASET_IDS = (TASK_SPEND_DATASET_ID,)


@dataclass
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: Path


class BasePipeline:
    dataset_ids: tuple[str, ...]
    optional_dataset_ids: set[str] = set()

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
                    datasets_written[dataset_id] = len(self._upsert_dataset(dataset_id, records))
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

    def _upsert_dataset(self, dataset_id: str, records: list[DatasetRecord]) -> pd.DataFrame:
        return self.storage.upsert_dataset(dataset_id, records)

    def _build_manifest(
        self,
        *,
        mode: str,
        context: RunContext,
        extracted: dict[str, list[DatasetRecord]],
    ) -> dict[str, Any]:
        manifest_dataset_ids = [
            dataset_id
            for dataset_id in self.dataset_ids
            if dataset_id not in self.optional_dataset_ids
            or extracted.get(dataset_id)
            or not self.storage.load_dataset(dataset_id).empty
        ]
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
                for dataset_id in manifest_dataset_ids
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
    optional_dataset_ids = {"context_length_requests", "modality_rankings"}

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
            if dataset_id == CONTEXT_LENGTH_DATASET_ID:
                existing_keys = {
                    (str(row.week_start_date), str(row.context_length_bucket), str(row.entity_id))
                    for row in existing[["week_start_date", "context_length_bucket", "entity_id"]].itertuples(index=False)
                } if not existing.empty else set()
                filtered[dataset_id] = [
                    record
                    for record in records
                    if (str(record.week_start_date), str(record.context_length_bucket), str(record.entity_id))
                    not in existing_keys
                ]
                continue
            if dataset_id == MODALITY_RANKINGS_DATASET_ID:
                existing_keys = {
                    (str(row.week_start_date), str(row.modality), str(row.entity_id))
                    for row in existing[["week_start_date", "modality", "entity_id"]].itertuples(index=False)
                } if not existing.empty else set()
                filtered[dataset_id] = [
                    record
                    for record in records
                    if (str(record.week_start_date), str(record.modality), str(record.entity_id))
                    not in existing_keys
                ]
                continue
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

    def _upsert_dataset(self, dataset_id: str, records: list[DatasetRecord]) -> pd.DataFrame:
        if dataset_id == "app_usage_daily":
            # The app chart includes the current, still-changing UTC day and a rolling
            # history. Replace complete app/date partitions so the next run finalizes
            # earlier partial observations and removes models that left the chart.
            return self.storage.upsert_dataset(
                dataset_id,
                records,
                replace_partitions=["app_id", "usage_date"],
            )
        return super()._upsert_dataset(dataset_id, records)

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

        usage_records = list(extracted.get("app_usage_daily", []))
        existing_usage = self.storage.load_dataset("app_usage_daily")
        if existing_usage.empty:
            filtered["app_usage_daily"] = usage_records
            return filtered

        existing_partitions = {
            (str(row.app_id), str(row.usage_date))
            for row in existing_usage[["app_id", "usage_date"]].drop_duplicates().itertuples(index=False)
        }
        dates_by_app: dict[str, set[str]] = {}
        for record in usage_records:
            dates_by_app.setdefault(str(record.app_id), set()).add(str(record.usage_date))
        refresh_partitions = {
            (app_id, usage_date)
            for app_id, dates in dates_by_app.items()
            for usage_date in sorted(dates)[-3:]
        }
        incoming_partitions = {
            (str(record.app_id), str(record.usage_date)) for record in usage_records
        }
        refresh_partitions.update(incoming_partitions - existing_partitions)
        filtered["app_usage_daily"] = [
            record
            for record in usage_records
            if (str(record.app_id), str(record.usage_date)) in refresh_partitions
        ]
        return filtered


class TaskSpendPipeline(BasePipeline):
    dataset_ids = TASK_SPEND_DATASET_IDS

    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir, TaskSpendSource())

    def run_daily_update(self) -> PipelineResult:
        return self._execute(mode="task-spend-daily-update")

    def validate(self) -> dict[str, int]:
        context = self._create_context(run_id="validate-task-spend")
        snapshots = self.source.fetch_snapshots()
        extracted = self.source.extract(snapshots, context)
        return {dataset_id: len(records) for dataset_id, records in extracted.items()}

    def _filter_for_mode(
        self,
        mode: str,
        extracted: dict[str, list[DatasetRecord]],
    ) -> dict[str, list[DatasetRecord]]:
        if mode != "task-spend-daily-update":
            raise ValueError(f"Unsupported mode: {mode}")
        return extracted


class ActivityPipeline(BasePipeline):
    dataset_ids = ACTIVITY_DATASET_IDS

    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir, ActivitySource())

    def run_daily_update(self, limit: int = 0) -> PipelineResult:
        """Discover model slugs for the configured major providers, then ingest activity."""
        slugs = self._discover_activity_slugs(limit=limit)
        if not slugs:
            slugs = self.source.fetch_popular_slugs(limit=limit or 200)

        snapshots = self.source.fetch_snapshots(slugs)
        return self._execute(mode="activity-daily-update", snapshots=snapshots)

    def _discover_activity_slugs(self, limit: int = 0) -> list[str]:
        slugs: list[str] = []
        seen: set[str] = set()
        allowed_prefixes = set(ACTIVITY_PROVIDER_SLUGS.keys())

        def add_many(values: list[str]) -> None:
            for value in values:
                if "/" not in value or value.split("/")[0] not in allowed_prefixes:
                    continue
                if value not in seen:
                    seen.add(value)
                    slugs.append(value)

        live_catalog_slugs: list[str] = []
        try:
            live_catalog_slugs = self.source.fetch_catalog_slugs(limit=0)
        except Exception as exc:
            print(f"Warning: Failed to fetch live OpenRouter model catalog for activity discovery: {exc}")
        # Keep newly released models in the capped scrape even before they
        # appear in provider activity history.
        if limit and limit > 0:
            recent_catalog_slugs = [slug for slug in live_catalog_slugs if re.search(r"-(20\d{6})$", slug)]
            add_many(recent_catalog_slugs)
        # Spend remaining requests on models with the most recent traffic.
        add_many(self._discover_active_provider_slugs(limit=0))
        add_many(live_catalog_slugs)
        add_many(self._discover_catalog_slugs(limit=0))

        if limit and limit > 0:
            return slugs[:limit]
        return slugs

    def _discover_active_provider_slugs(self, limit: int = 0) -> list[str]:
        path = self.base_dir / "data" / "normalized" / "openrouter" / "provider_daily_activity.parquet"
        if not path.exists():
            return []
        activity = pd.read_parquet(path, columns=["usage_date", "model_permaslug", "total_tokens"])
        if activity.empty:
            return []
        activity["usage_date_dt"] = pd.to_datetime(activity["usage_date"], errors="coerce")
        activity["total_tokens"] = pd.to_numeric(activity["total_tokens"], errors="coerce").fillna(0)
        latest_date = activity["usage_date_dt"].max()
        if pd.isna(latest_date):
            return []
        recent = activity[activity["usage_date_dt"] >= latest_date - pd.Timedelta(days=29)].copy()
        ranked = recent.groupby("model_permaslug")["total_tokens"].sum().sort_values(ascending=False)
        allowed_prefixes = set(ACTIVITY_PROVIDER_SLUGS.keys())
        slugs = [
            str(slug) for slug in ranked.index
            if isinstance(slug, str) and "/" in slug and slug.split("/", 1)[0] in allowed_prefixes
        ]
        return slugs[:limit] if limit and limit > 0 else slugs

    def _discover_catalog_slugs(self, limit: int = 0) -> list[str]:
        catalog_root = self.base_dir / "data" / "normalized" / "compute_availability"
        parquet_path = catalog_root / "raw_openrouter_models.parquet"
        csv_path = catalog_root / "raw_openrouter_models.csv"
        if parquet_path.exists():
            catalog = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            catalog = pd.read_csv(csv_path)
        else:
            return []

        if catalog.empty or "provider_prefix" not in catalog.columns:
            return []

        if "snapshot_ts" in catalog.columns and catalog["snapshot_ts"].notna().any():
            latest_snapshots = sorted(catalog["snapshot_ts"].dropna().astype(str).unique())[-14:]
            catalog = catalog[catalog["snapshot_ts"].astype(str).isin(latest_snapshots)].copy()

        allowed_prefixes = set(ACTIVITY_PROVIDER_SLUGS.keys())
        catalog["provider_prefix"] = catalog["provider_prefix"].astype("string")
        catalog = catalog[catalog["provider_prefix"].isin(allowed_prefixes)].copy()
        if catalog.empty:
            return []

        slug_series = catalog.get("canonical_slug")
        if slug_series is None or slug_series.isna().all():
            slug_series = catalog.get("model_id")
        else:
            slug_series = slug_series.fillna(catalog.get("model_id"))
        if slug_series is None:
            return []

        slugs: list[str] = []
        seen: set[str] = set()
        for slug in slug_series.astype("string").dropna().tolist():
            slug_str = str(slug).strip()
            if not slug_str or "/" not in slug_str or slug_str in seen:
                continue
            if slug_str.split("/")[0] not in allowed_prefixes:
                continue
            seen.add(slug_str)
            slugs.append(slug_str)

        if limit and limit > 0:
            return slugs[:limit]
        return slugs

    def _filter_for_mode(
        self,
        mode: str,
        extracted: dict[str, list[DatasetRecord]],
    ) -> dict[str, list[DatasetRecord]]:
        # For activity daily update, we typically keep all extracted rows for the day 
        # (duplicates are handled by StorageManager natural keys)
        return extracted


PROVIDER_ACTIVITY_DATASET_IDS = (PROVIDER_ACTIVITY_DATASET_ID,)


class ProviderActivityPipeline(BasePipeline):
    """Scrapes openrouter.ai/{provider} for all priority providers daily.

    Self-healing: each run ingests the full 91-day trailing window and upserts
    on (usage_date, model_permaslug), so missed days are automatically backfilled
    on the next successful run.
    """

    dataset_ids = PROVIDER_ACTIVITY_DATASET_IDS

    def __init__(self, base_dir: Path, provider_slugs: dict[str, str] | None = None) -> None:
        self._provider_slugs = provider_slugs or PROVIDER_SLUGS
        super().__init__(base_dir, ProviderActivitySource())

    def run_daily_update(self) -> PipelineResult:
        snapshots = self.source.fetch_snapshots(self._provider_slugs)
        return self._execute(mode="provider-activity-daily-update", snapshots=snapshots)

    def validate(self) -> dict[str, dict[str, Any]]:
        context = self._create_context(run_id="validate-provider-activity")
        snapshots = self.source.fetch_snapshots(self._provider_slugs)
        extracted = self.source.extract(snapshots, context)
        return ProviderActivitySource.validate_records(
            extracted.get(PROVIDER_ACTIVITY_DATASET_ID, []),
            expected_providers=self._provider_slugs,
            scraped_at=context.scraped_at,
        )

    def _filter_for_mode(
        self,
        mode: str,
        extracted: dict[str, list[DatasetRecord]],
    ) -> dict[str, list[DatasetRecord]]:
        """Upsert semantics: keep all rows; StorageManager deduplicates on natural key."""
        if mode != "provider-activity-daily-update":
            raise ValueError(f"Unsupported mode: {mode}")
        records = extracted.get(PROVIDER_ACTIVITY_DATASET_ID, [])
        scraped_at = datetime.now(timezone.utc)
        for record in records:
            if record.scraped_at:
                try:
                    scraped_at = datetime.fromisoformat(record.scraped_at.replace("Z", "+00:00"))
                except ValueError:
                    pass
                break
        ProviderActivitySource.validate_records(
            records,
            expected_providers=self._provider_slugs,
            scraped_at=scraped_at,
        )
        return extracted
