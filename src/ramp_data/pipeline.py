from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ramp_data.models import DatasetRecord, GenericRecord, RunContext, Snapshot
from ramp_data.schemas import (
    AI_INDEX_DATASETS,
    FILTER_MODE_DATASETS,
    JOBS_IMPACT,
    JOBS_IMPACT_DATASET,
    CATEGORY_CHARTS_DATASETS,
)
from ramp_data.sources.ai_index import RampAiIndexSource
from ramp_data.sources.filter_mode import RampFilterModeSource
from ramp_data.sources.jobs_impact import RampJobsImpactSource
from ramp_data.sources.vendors import RampVendorsSource
from ramp_data.sources.category_charts import RampCategoryChartsSource
from ramp_data.storage import StorageManager


# Data-quality gates. These guard against a silent upstream layout change (a
# renamed RSC key, a Cloudflare interstitial) nulling the payload and then
# overwriting committed history via the upsert. A row-count floor alone is not
# enough — we also assert the key metric is actually populated and in range.
MIN_EXPECTED_ROWS: dict[str, int] = {
    "ramp_vendor_adoption_monthly": 500,
    "ramp_category_vendors": 100,
}
MIN_CATEGORIES = 10
MIN_ADOPTION_NON_NULL_RATIO = 0.9


class ValidationError(RuntimeError):
    """Raised when a live crawl fails the data-quality gates."""


@dataclass
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: Path


class RampPipeline:
    dataset_ids = ("ramp_category_vendors", "ramp_vendor_adoption_monthly")

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.source = RampVendorsSource()
        self.ai_index_source = RampAiIndexSource()
        self.filter_mode_source = RampFilterModeSource()
        self.jobs_impact_source = RampJobsImpactSource()
        self.category_charts_source = RampCategoryChartsSource()


    def _create_context(self, *, run_id: str | None = None) -> RunContext:
        return RunContext(
            run_id=run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            scraped_at=datetime.now(timezone.utc),
        )

    def run_update(self) -> PipelineResult:
        context = self._create_context()

        snapshots = self.source.fetch_snapshots()

        manifest: dict[str, Any] = {
            "run_id": context.run_id,
            "mode": "update",
            "scraped_at": context.scraped_at_iso,
            "status": "pending",
            "datasets": [],
        }
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)

        try:
            extracted = self.source.extract(snapshots, context)

            # Gate BEFORE any write: a bad crawl must not overwrite history.
            self._assert_quality(snapshots, extracted)

            datasets_written: dict[str, int] = {}
            for dataset_id in self.dataset_ids:
                records = extracted.get(dataset_id, [])
                if records:
                    datasets_written[dataset_id] = len(self.storage.upsert_dataset(dataset_id, records))
                else:
                    datasets_written[dataset_id] = len(self.storage.load_dataset(dataset_id))

            manifest["status"] = "success"
            manifest["datasets"] = [
                {
                    "dataset_id": dataset_id,
                    "status": "ok" if extracted.get(dataset_id) else "no_new_rows",
                    "rows": len(extracted.get(dataset_id, [])),
                }
                for dataset_id in self.dataset_ids
            ]
            self.storage.write_raw_run(context.run_id, snapshots, manifest)

            return PipelineResult(
                run_id=context.run_id,
                datasets_written=datasets_written,
                raw_run_dir=raw_run_dir,
            )
        except Exception as exc:
            manifest["status"] = "failed"
            manifest["error"] = str(exc)
            self.storage.write_raw_run(context.run_id, snapshots, manifest)
            raise

    def _execute(
        self,
        source,
        dataset_ids: tuple[str, ...],
        gate,
        mode: str,
    ) -> PipelineResult:
        """Shared fetch → raw-capture → extract → gate → upsert flow.

        The gate runs before any upsert, so a blocked/malformed source can never
        overwrite committed history.
        """
        context = self._create_context()
        snapshots = source.fetch_snapshots()

        manifest: dict[str, Any] = {
            "run_id": context.run_id,
            "mode": mode,
            "scraped_at": context.scraped_at_iso,
            "status": "pending",
            "datasets": [],
        }
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)

        try:
            extracted = source.extract(snapshots, context)
            gate(snapshots, extracted)

            datasets_written: dict[str, int] = {}
            for dataset_id in dataset_ids:
                records = extracted.get(dataset_id, [])
                if records:
                    datasets_written[dataset_id] = len(self.storage.upsert_dataset(dataset_id, records))
                else:
                    datasets_written[dataset_id] = len(self.storage.load_dataset(dataset_id))

            manifest["status"] = "success"
            manifest["datasets"] = [
                {
                    "dataset_id": dataset_id,
                    "status": "ok" if extracted.get(dataset_id) else "no_new_rows",
                    "rows": len(extracted.get(dataset_id, [])),
                }
                for dataset_id in dataset_ids
            ]
            self.storage.write_raw_run(context.run_id, snapshots, manifest)

            return PipelineResult(
                run_id=context.run_id,
                datasets_written=datasets_written,
                raw_run_dir=raw_run_dir,
            )
        except Exception as exc:
            manifest["status"] = "failed"
            manifest["error"] = str(exc)
            self.storage.write_raw_run(context.run_id, snapshots, manifest)
            raise

    def run_ai_index(self) -> PipelineResult:
        return self._execute(
            self.ai_index_source,
            tuple(AI_INDEX_DATASETS.keys()),
            self._assert_ai_index_quality,
            mode="ai-index",
        )

    def run_filter_mode(self) -> PipelineResult:
        return self._execute(
            self.filter_mode_source,
            tuple(FILTER_MODE_DATASETS.keys()),
            self._assert_filter_mode_quality,
            mode="filter-mode",
        )

    def run_jobs_impact(self) -> PipelineResult:
        return self._execute(
            self.jobs_impact_source,
            (JOBS_IMPACT_DATASET,),
            self._assert_jobs_impact_quality,
            mode="jobs-impact",
        )

    def run_category_charts(self) -> PipelineResult:
        return self._execute(
            self.category_charts_source,
            tuple(CATEGORY_CHARTS_DATASETS.keys()),
            self._assert_category_charts_quality,
            mode="category-charts",
        )


    @staticmethod
    def _assert_category_charts_quality(
        snapshots: list[Snapshot],
        extracted: dict[str, list[GenericRecord]],
    ) -> dict[str, dict[str, Any]]:
        report: dict[str, dict[str, Any]] = {}
        failures: list[str] = []
        for dataset_id, cfg in CATEGORY_CHARTS_DATASETS.items():
            records = extracted.get(dataset_id, [])
            rows = len(records)
            report[dataset_id] = {"rows": rows}
            if rows < cfg["min_rows"]:
                failures.append(
                    f"{dataset_id}: only {rows} rows (expected >= {cfg['min_rows']}) "
                    f"— Datawrapper download empty or malformed"
                )
        if failures:
            raise ValidationError("; ".join(failures))
        return report

    @staticmethod
    def _assert_filter_mode_quality(
        snapshots: list[Snapshot],
        extracted: dict[str, list[GenericRecord]],
    ) -> dict[str, dict[str, Any]]:
        report: dict[str, dict[str, Any]] = {}
        failures: list[str] = []
        for dataset_id, cfg in FILTER_MODE_DATASETS.items():
            records = extracted.get(dataset_id, [])
            rows = len(records)
            report[dataset_id] = {"rows": rows}
            if rows < cfg["min_rows"]:
                failures.append(
                    f"{dataset_id}: only {rows} rows (expected >= {cfg['min_rows']}) "
                    f"— filter-mode endpoint empty or version token stale"
                )
                continue
            missing_month = sum(1 for r in records if not r.payload.get("date_month"))
            if missing_month:
                failures.append(f"{dataset_id}: {missing_month} rows missing date_month")
        if failures:
            raise ValidationError("; ".join(failures))
        return report

    @staticmethod
    def _assert_ai_index_quality(
        snapshots: list[Snapshot],
        extracted: dict[str, list[GenericRecord]],
    ) -> dict[str, dict[str, Any]]:
        report: dict[str, dict[str, Any]] = {}
        failures: list[str] = []
        for dataset_id, cfg in AI_INDEX_DATASETS.items():
            records = extracted.get(dataset_id, [])
            rows = len(records)
            report[dataset_id] = {"rows": rows}
            if rows < cfg["min_rows"]:
                failures.append(f"{dataset_id}: only {rows} rows (expected >= {cfg['min_rows']}) — possible layout change")
                continue
            missing_month = sum(1 for r in records if not r.payload.get("date_month"))
            if missing_month:
                failures.append(f"{dataset_id}: {missing_month} rows missing date_month")
            if "adoption_rate_pct" in cfg["fields"]:
                oor = [
                    r.payload.get("adoption_rate_pct") for r in records
                    if isinstance(r.payload.get("adoption_rate_pct"), (int, float))
                    and not (0.0 <= float(r.payload["adoption_rate_pct"]) <= 100.0)
                ]
                if oor:
                    failures.append(f"{dataset_id}: {len(oor)} adoption_rate_pct values outside [0, 100]")
        if failures:
            raise ValidationError("; ".join(failures))
        return report

    @staticmethod
    def _assert_jobs_impact_quality(
        snapshots: list[Snapshot],
        extracted: dict[str, list[GenericRecord]],
    ) -> dict[str, dict[str, Any]]:
        records = extracted.get(JOBS_IMPACT_DATASET, [])
        rows = len(records)
        report = {JOBS_IMPACT_DATASET: {"rows": rows}}
        failures: list[str] = []
        if rows < JOBS_IMPACT["min_rows"]:
            failures.append(
                f"{JOBS_IMPACT_DATASET}: only {rows} rows (expected >= {JOBS_IMPACT['min_rows']}) "
                f"— data table not found or Ramp layout changed"
            )
        populated = sum(1 for r in records if r.payload.get("high_intensity_effect") is not None)
        if rows and populated / rows < 0.9:
            failures.append(f"{JOBS_IMPACT_DATASET}: high_intensity_effect populated for only {populated}/{rows} rows")
        if failures:
            raise ValidationError("; ".join(failures))
        return report

    def validate(self, *, snapshots: list[Snapshot] | None = None) -> dict[str, dict[str, Any]]:
        """Crawl live (or use injected snapshots) and assert the quality gates.

        Raises ValidationError if any dataset looks malformed. Does not write.
        """
        context = self._create_context(run_id="validate")
        if snapshots is None:
            snapshots = self.source.fetch_snapshots()
        extracted = self.source.extract(snapshots, context)
        return self._assert_quality(snapshots, extracted)

    def _assert_quality(
        self,
        snapshots: list[Snapshot],
        extracted: dict[str, list[DatasetRecord]],
    ) -> dict[str, dict[str, Any]]:
        report: dict[str, dict[str, Any]] = {}
        failures: list[str] = []

        category_pages = sum(1 for s in snapshots if s.name.startswith("category__"))
        if category_pages < MIN_CATEGORIES:
            failures.append(
                f"discovered only {category_pages} category pages (expected >= {MIN_CATEGORIES}) "
                f"— possible layout change or blocked crawl"
            )

        for dataset_id in self.dataset_ids:
            records = extracted.get(dataset_id, [])
            stats, problems = self._quality_check(dataset_id, records)
            report[dataset_id] = stats
            failures.extend(problems)

        if failures:
            raise ValidationError("; ".join(failures))
        return report

    @staticmethod
    def _quality_check(
        dataset_id: str,
        records: list[DatasetRecord],
    ) -> tuple[dict[str, Any], list[str]]:
        rows = len(records)
        stats: dict[str, Any] = {"rows": rows}
        problems: list[str] = []

        min_rows = MIN_EXPECTED_ROWS.get(dataset_id, 1)
        if rows < min_rows:
            problems.append(f"{dataset_id}: only {rows} rows (expected >= {min_rows})")

        non_null = sum(1 for r in records if r.adoption_rate is not None)
        ratio = non_null / rows if rows else 0.0
        stats["adoption_rate_non_null_ratio"] = round(ratio, 4)
        if rows and ratio < MIN_ADOPTION_NON_NULL_RATIO:
            problems.append(
                f"{dataset_id}: adoption_rate populated for only {ratio:.0%} of rows "
                f"(expected >= {MIN_ADOPTION_NON_NULL_RATIO:.0%}) — possible upstream schema change"
            )
        out_of_range = [
            r.adoption_rate for r in records
            if r.adoption_rate is not None and not (0.0 <= r.adoption_rate <= 1.0)
        ]
        if out_of_range:
            problems.append(f"{dataset_id}: {len(out_of_range)} adoption_rate values outside [0, 1]")

        return stats, problems
