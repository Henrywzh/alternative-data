from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from vercel_ai_data.models import DatasetRecord, RunContext, Snapshot
from vercel_ai_data.sources.leaderboard import VercelLeaderboardSource
from vercel_ai_data.sources.models_catalog import VercelModelsCatalogSource
from vercel_ai_data.storage import StorageManager

# Data-quality gates. These guard against a silent upstream schema change (e.g.
# a renamed field) nulling the key metric and then overwriting committed history
# via the daily upsert. A row-count check alone is not enough — rows still exist,
# they are just empty — so we also assert the payload is actually populated.
LEADERBOARD_DATASETS = ("vercel_model_leaderboard", "vercel_lab_leaderboard")
MIN_EXPECTED_ROWS: dict[str, int] = {
    "vercel_model_leaderboard": 10,
    "vercel_lab_leaderboard": 10,
    "vercel_models": 5,
}
MIN_SHARE_NON_NULL_RATIO = 0.9


class ValidationError(RuntimeError):
    """Raised when a live fetch fails the data-quality gates."""


@dataclass
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: Path


class VercelPipeline:
    dataset_ids = ("vercel_model_leaderboard", "vercel_lab_leaderboard", "vercel_models")

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.leaderboard_source = VercelLeaderboardSource()
        self.catalog_source = VercelModelsCatalogSource()

    def _create_context(self, *, run_id: str | None = None) -> RunContext:
        return RunContext(
            run_id=run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            scraped_at=datetime.now(timezone.utc),
        )

    def run_daily_update(self) -> PipelineResult:
        context = self._create_context()

        # 1. Fetch snapshots from sources
        snapshots: list[Snapshot] = []
        snapshots.extend(self.leaderboard_source.fetch_snapshots())
        snapshots.extend(self.catalog_source.fetch_snapshots())

        # Build initial manifest
        manifest = {
            "run_id": context.run_id,
            "mode": "daily-update",
            "scraped_at": context.scraped_at_iso,
            "status": "pending",
            "datasets": [],
        }
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)

        try:
            # 2. Extract dataset records
            extracted: dict[str, list[DatasetRecord]] = {}

            leaderboard_extracted = self.leaderboard_source.extract(snapshots, context)
            extracted.update(leaderboard_extracted)

            catalog_extracted = self.catalog_source.extract(snapshots, context)
            extracted.update(catalog_extracted)

            # 3. Upsert to storage
            datasets_written = {}
            for dataset_id in self.dataset_ids:
                records = extracted.get(dataset_id, [])
                if records:
                    datasets_written[dataset_id] = len(self.storage.upsert_dataset(dataset_id, records))
                else:
                    datasets_written[dataset_id] = len(self.storage.load_dataset(dataset_id))

            # Update manifest
            manifest["status"] = "success"
            manifest["datasets"] = [
                {
                    "dataset_id": dataset_id,
                    "status": "ok" if extracted.get(dataset_id) else "no_new_rows",
                    "rows": len(extracted.get(dataset_id, [])),
                    "source_urls": sorted({record.source_url for record in extracted.get(dataset_id, [])}),
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

    def validate(
        self,
        *,
        model_leaderboard_json: str | None = None,
        lab_leaderboard_json: str | None = None,
        models_json: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Fetch live (or from injected fixtures) and assert data-quality gates.

        Raises ValidationError if any dataset looks malformed so that CI fails
        *before* the daily-update step can overwrite committed history.
        """
        context = self._create_context(run_id="validate")

        if model_leaderboard_json is None and lab_leaderboard_json is None and models_json is None:
            snapshots: list[Snapshot] = []
            snapshots.extend(self.leaderboard_source.fetch_snapshots())
            snapshots.extend(self.catalog_source.fetch_snapshots())
        else:
            snapshots = [
                Snapshot("vercel_model_leaderboard", "fixture://models", model_leaderboard_json or "{}"),
                Snapshot("vercel_lab_leaderboard", "fixture://labs", lab_leaderboard_json or "{}"),
                Snapshot("vercel_models", "fixture://catalog", models_json or "{}"),
            ]

        extracted: dict[str, list[DatasetRecord]] = {}
        extracted.update(self.leaderboard_source.extract(snapshots, context))
        extracted.update(self.catalog_source.extract(snapshots, context))

        report: dict[str, dict[str, Any]] = {}
        failures: list[str] = []
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

        if dataset_id in LEADERBOARD_DATASETS:
            non_null = sum(1 for r in records if r.share_percent is not None)
            ratio = non_null / rows if rows else 0.0
            stats["share_percent_non_null"] = non_null
            stats["share_percent_non_null_ratio"] = round(ratio, 4)
            if rows and ratio < MIN_SHARE_NON_NULL_RATIO:
                problems.append(
                    f"{dataset_id}: share_percent populated for only "
                    f"{ratio:.0%} of rows (expected >= {MIN_SHARE_NON_NULL_RATIO:.0%}) "
                    f"— possible upstream schema change"
                )
            out_of_range = [
                r.share_percent for r in records
                if r.share_percent is not None and not (0.0 <= r.share_percent <= 100.5)
            ]
            if out_of_range:
                problems.append(
                    f"{dataset_id}: {len(out_of_range)} share_percent values out of [0, 100]"
                )
        elif dataset_id == "vercel_models":
            priced = sum(
                1 for r in records
                if r.pricing_input is not None or r.pricing_output is not None
            )
            stats["priced_models"] = priced
            missing_id = sum(1 for r in records if not r.model_id)
            if missing_id:
                problems.append(f"{dataset_id}: {missing_id} rows missing model_id")

        return stats, problems
