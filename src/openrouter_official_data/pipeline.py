from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from openrouter_official_data.extract import extract_snapshots
from openrouter_official_data.quality import (
    build_legacy_reconciliation,
    validate_dataset,
    validate_rankings_coverage,
)
from openrouter_official_data.source import OpenRouterOfficialSource
from openrouter_official_data.storage import OfficialStorage
from market_pulse_data import build_market_pulse, build_overview_signal_series


class OpenRouterOfficialPipeline:
    def __init__(self, base_dir: Path, api_key: str) -> None:
        self.base_dir = base_dir
        self.source = OpenRouterOfficialSource(api_key)
        self.storage = OfficialStorage(base_dir)

    @staticmethod
    def _context() -> tuple[str, str]:
        now = datetime.now(timezone.utc)
        run_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        scraped_at = now.isoformat().replace("+00:00", "Z")
        return run_id, scraped_at

    def run_daily_update(self, *, target_date: date | None = None) -> dict[str, int]:
        run_id, scraped_at = self._context()
        snapshots = self.source.fetch_daily_snapshots(target_date=target_date)
        return self._execute(run_id=run_id, scraped_at=scraped_at, snapshots=snapshots, mode="daily-update")

    def run_rankings_backfill(self, *, start_date: date, end_date: date) -> dict[str, int]:
        run_id, scraped_at = self._context()
        snapshots = self.source.fetch_rankings_backfill(start_date=start_date, end_date=end_date)
        return self._execute(run_id=run_id, scraped_at=scraped_at, snapshots=snapshots, mode="rankings-backfill")

    def _execute(self, *, run_id: str, scraped_at: str, snapshots, mode: str) -> dict[str, int]:
        core_snapshots = [snapshot for snapshot in snapshots if snapshot.name.startswith("rankings_daily")]
        if len(core_snapshots) != 1:
            raise ValueError("Official OpenRouter run requires exactly one core rankings snapshot")
        core_snapshot = core_snapshots[0]
        extracted = extract_snapshots(core_snapshots, run_id=run_id, scraped_at=scraped_at)
        optional_failures = list(self.source.last_failures)
        for snapshot in snapshots:
            if snapshot is core_snapshot:
                continue
            try:
                partial = extract_snapshots([snapshot], run_id=run_id, scraped_at=scraped_at)
            except (TypeError, ValueError) as exc:
                optional_failures.append(
                    {
                        "name": snapshot.name,
                        "path": snapshot.source_url,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            for dataset_id, rows in partial.items():
                extracted.setdefault(dataset_id, []).extend(rows)

        rankings_rows = extracted.get("official_model_rankings_daily", [])
        rankings = pd.DataFrame(rankings_rows)
        validate_dataset("official_model_rankings_daily", rankings)
        validate_rankings_coverage(
            rankings,
            expected_start_date=str(core_snapshot.query["start_date"]),
            expected_end_date=str(core_snapshot.query["end_date"]),
        )

        optional_dataset_names = {
            "official_task_classifications": "task_classifications",
            "official_task_models": "task_classifications",
            "official_task_macro_categories": "task_classifications",
            "official_providers": "providers",
            "official_benchmarks": "benchmarks",
            "official_app_rankings": "app_rankings",
        }
        failed_names = {str(failure["name"]) for failure in optional_failures}
        attempted_names = {snapshot.name for snapshot in snapshots} | failed_names
        for dataset_id, source_name in optional_dataset_names.items():
            source_attempted = source_name in attempted_names
            if source_name == "app_rankings":
                source_attempted = any(name.startswith("app_rankings_") for name in attempted_names)
            if not source_attempted:
                continue
            rows = extracted.get(dataset_id, [])
            source_failed = source_name in failed_names
            if source_name == "app_rankings":
                source_failed = source_failed or any(
                    name.startswith("app_rankings_") for name in failed_names
                )
            if not rows and not source_failed:
                optional_failures.append(
                    {
                        "name": source_name,
                        "path": f"https://openrouter.ai/api/v1/{source_name}",
                        "error": "EmptyPayload: no valid rows were extracted",
                    }
                )
                failed_names.add(source_name)

        health_by_dataset: dict[str, dict[str, object]] = {}
        written: dict[str, int] = {}
        for dataset_id, rows in extracted.items():
            if not rows:
                continue
            incoming = pd.DataFrame(rows)
            profile = validate_dataset(dataset_id, incoming)
            stored = self.storage.upsert(dataset_id, incoming)
            validate_dataset(dataset_id, stored)
            written[dataset_id] = len(stored)
            health_by_dataset[dataset_id] = {
                **profile,
                "source_url": incoming["source_url"].dropna().astype(str).iloc[-1]
                if "source_url" in incoming and incoming["source_url"].notna().any()
                else "https://openrouter.ai/api/v1",
                "source_run_id": run_id,
                "scraped_at": scraped_at,
            }

        failure_datasets = {
            "task_classifications": (
                "official_task_classifications",
                "official_task_models",
                "official_task_macro_categories",
            ),
            "providers": ("official_providers",),
            "benchmarks": ("official_benchmarks",),
            "app_rankings": ("official_app_rankings",),
        }
        for failure in optional_failures:
            name = failure["name"]
            affected = ("official_app_rankings",) if name.startswith("app_rankings_") else failure_datasets.get(name, ())
            for dataset_id in affected:
                failure_path = str(failure["path"])
                failure_url = (
                    failure_path
                    if failure_path.startswith(("http://", "https://"))
                    else f"https://openrouter.ai/api/v1{failure_path}"
                )
                row = health_by_dataset.setdefault(
                    dataset_id,
                    {
                        "dataset_id": dataset_id,
                        "row_count": 0,
                        "first_date": None,
                        "latest_date": None,
                        "duplicate_rows": 0,
                        "source_url": failure_url,
                        "source_run_id": run_id,
                        "scraped_at": scraped_at,
                    },
                )
                row["status"] = "warning"
                details = [value for value in str(row.get("detail") or "").split(" | ") if value]
                details.append(f"{name}: {failure['error']}")
                row["detail"] = " | ".join(details)

        health_rows = list(health_by_dataset.values())

        official = self.storage.load("official_model_rankings_daily")
        reconciliation = build_legacy_reconciliation(self.base_dir, official)
        if not reconciliation.empty:
            reconciliation["source_url"] = "derived://openrouter-official-legacy-reconciliation"
            reconciliation["source_run_id"] = run_id
            reconciliation["scraped_at"] = scraped_at
            stored = self.storage.upsert("official_legacy_reconciliation", reconciliation)
            written["official_legacy_reconciliation"] = len(stored)

        if health_rows:
            stored_health = self.storage.upsert("official_source_health", health_rows)
            written["official_source_health"] = len(stored_health)

        pulse = build_market_pulse(self.base_dir, run_id=run_id, scraped_at=scraped_at)
        if not pulse.empty:
            written["market_pulse_daily"] = len(pulse)
        overview_signals = build_overview_signal_series(
            self.base_dir,
            run_id=run_id,
            scraped_at=scraped_at,
        )
        if not overview_signals.empty:
            written["overview_signal_series"] = len(overview_signals)

        manifest = {
            "run_id": run_id,
            "scraped_at": scraped_at,
            "mode": mode,
            "source": "OpenRouter official API",
            "datasets": health_rows,
            "request_count": len(snapshots),
            "attempted_request_count": len(snapshots) + len(self.source.last_failures),
            "optional_failures": optional_failures,
        }
        self.storage.write_raw_run(run_id=run_id, snapshots=snapshots, manifest=manifest)
        return written
