from __future__ import annotations

import statistics
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from artificial_analysis_data.models import (
    ArtificialAnalysisModelPoint,
    CapexQuarterPoint,
    ContextWindowQuarterPoint,
    LeadingModelByLabPoint,
    PipelineResult,
    RunContext,
    Snapshot,
    parse_quarter_sort_key,
)
from artificial_analysis_data.sources.api import ArtificialAnalysisApiSource
from artificial_analysis_data.sources.capex import ArtificialAnalysisCapexSource
from artificial_analysis_data.sources.config import resolve_api_key
from artificial_analysis_data.storage import StorageManager


PARSER_VERSION = "aa-v1"


class ArtificialAnalysisPipeline:
    def __init__(
        self,
        base_dir: Path,
        *,
        api_source: ArtificialAnalysisApiSource | None = None,
        capex_source: ArtificialAnalysisCapexSource | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.api_source = api_source or ArtificialAnalysisApiSource()
        self.capex_source = capex_source or ArtificialAnalysisCapexSource()

    def run_daily_update(self) -> PipelineResult:
        context = self._create_context()
        api_key = resolve_api_key(self.base_dir)
        api_snapshot = self.api_source.fetch_snapshot(api_key)
        capex_snapshots = self.capex_source.fetch_snapshots()
        model_points = self.api_source.extract(
            api_snapshot,
            run_id=context.run_id,
            scraped_at=context.scraped_at_iso,
            as_of_date=context.as_of_date,
        )
        capex_points = self.capex_source.extract(capex_snapshots, run_id=context.run_id, scraped_at=context.scraped_at_iso)
        leader_points = self._derive_leading_models_by_lab(model_points, run_id=context.run_id, scraped_at=context.scraped_at_iso)
        context_points = self._derive_context_window_quarter(model_points, run_id=context.run_id, scraped_at=context.scraped_at_iso)
        snapshots = [api_snapshot, *capex_snapshots]
        manifest = self._build_manifest(
            context,
            command="daily-update",
            snapshots=snapshots,
            counts={
                "artificial_analysis_models_daily": len(model_points),
                "artificial_analysis_leading_models_by_lab_daily": len(leader_points),
                "artificial_analysis_context_window_quarter_daily": len(context_points),
                "artificial_analysis_capex_quarterly": len(capex_points),
            },
        )
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)

        return self._write_datasets(
            context,
            raw_run_dir,
            {
                "artificial_analysis_models_daily": model_points,
                "artificial_analysis_leading_models_by_lab_daily": leader_points,
                "artificial_analysis_context_window_quarter_daily": context_points,
                "artificial_analysis_capex_quarterly": capex_points,
            },
        )

    def run_capex_update(self) -> PipelineResult:
        context = self._create_context()
        snapshots = self.capex_source.fetch_snapshots()
        capex_points = self.capex_source.extract(snapshots, run_id=context.run_id, scraped_at=context.scraped_at_iso)
        manifest = self._build_manifest(
            context,
            command="capex-update",
            snapshots=snapshots,
            counts={"artificial_analysis_capex_quarterly": len(capex_points)},
        )
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)
        return self._write_datasets(
            context,
            raw_run_dir,
            {"artificial_analysis_capex_quarterly": capex_points},
        )

    def validate(self) -> dict[str, int]:
        api_key = resolve_api_key(self.base_dir)
        context = self._create_context()
        api_snapshot = self.api_source.fetch_snapshot(api_key)
        capex_snapshots = self.capex_source.fetch_snapshots()
        model_points = self.api_source.extract(
            api_snapshot,
            run_id=context.run_id,
            scraped_at=context.scraped_at_iso,
            as_of_date=context.as_of_date,
        )
        capex_points = self.capex_source.extract(capex_snapshots, run_id=context.run_id, scraped_at=context.scraped_at_iso)
        return {
            "api_models": len(model_points),
            "capex_quarters": len(capex_points),
            "context_window_fields_missing": int(not any(point.context_window_tokens is not None for point in model_points)),
        }

    def _write_datasets(
        self,
        context: RunContext,
        raw_run_dir: Path,
        dataset_records: dict[str, list[object]],
    ) -> PipelineResult:
        datasets_written: dict[str, int] = {}
        deltas: dict[str, int] = {}
        for dataset_id, records in dataset_records.items():
            # The API currently omits context-window coverage in some responses, so we
            # intentionally skip persisting an empty derived dataset until the source
            # exposes real values again.
            if not records:
                continue
            existing = self.storage.load_dataset(dataset_id)
            written = self.storage.upsert_dataset(dataset_id, records)
            datasets_written[dataset_id] = len(written)
            deltas[dataset_id] = max(len(written) - len(existing), 0)
        return PipelineResult(
            run_id=context.run_id,
            datasets_written=datasets_written,
            raw_run_dir=str(raw_run_dir),
            dataset_row_deltas=deltas,
        )

    def _create_context(self) -> RunContext:
        return RunContext(
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            scraped_at=datetime.now(timezone.utc),
        )

    def _build_manifest(
        self,
        context: RunContext,
        *,
        command: str,
        snapshots: list[Snapshot],
        counts: dict[str, int],
    ) -> dict[str, object]:
        return {
            "run_id": context.run_id,
            "scraped_at": context.scraped_at_iso,
            "as_of_date": context.as_of_date,
            "source": "artificial_analysis",
            "command": command,
            "parser_version": PARSER_VERSION,
            "counts": counts,
            "snapshots": [{"name": snapshot.name, "source_url": snapshot.source_url} for snapshot in snapshots],
        }

    def _derive_leading_models_by_lab(
        self,
        points: list[ArtificialAnalysisModelPoint],
        *,
        run_id: str,
        scraped_at: str,
    ) -> list[LeadingModelByLabPoint]:
        by_creator: dict[str, ArtificialAnalysisModelPoint] = {}
        for point in points:
            creator_key = point.creator_id or point.creator_slug or point.creator_name or "unknown"
            current = by_creator.get(creator_key)
            if current is None or (point.intelligence_index or float("-inf")) > (current.intelligence_index or float("-inf")):
                by_creator[creator_key] = point
        return [
            LeadingModelByLabPoint(
                as_of_date=point.as_of_date,
                creator_id=point.creator_id,
                creator_name=point.creator_name,
                creator_slug=point.creator_slug,
                creator_country=point.creator_country,
                model_id=point.model_id,
                model_slug=point.model_slug,
                model_name=point.model_name,
                release_date=point.release_date,
                intelligence_index=point.intelligence_index,
                source_url=point.source_url,
                source_run_id=run_id,
                scraped_at=scraped_at,
            )
            for point in sorted(by_creator.values(), key=lambda row: (row.creator_slug or "", row.model_name))
        ]

    def _derive_context_window_quarter(
        self,
        points: list[ArtificialAnalysisModelPoint],
        *,
        run_id: str,
        scraped_at: str,
    ) -> list[ContextWindowQuarterPoint]:
        grouped: dict[str, dict[str, list[int]]] = {}
        for point in points:
            if point.release_quarter is None or point.context_window_tokens is None:
                continue
            grouped.setdefault(point.release_quarter, {"proprietary": [], "open": []})
            bucket = "open" if _is_open_model(point) else "proprietary"
            grouped[point.release_quarter][bucket].append(point.context_window_tokens)

        rows: list[ContextWindowQuarterPoint] = []
        for quarter in sorted(grouped, key=parse_quarter_sort_key):
            quarter_values = grouped[quarter]
            rows.append(
                ContextWindowQuarterPoint(
                    as_of_date=points[0].as_of_date if points else datetime.now(timezone.utc).date().isoformat(),
                    release_quarter=quarter,
                    context_window_median_proprietary=_median_or_none(quarter_values["proprietary"]),
                    context_window_median_open_source_total=_median_or_none(quarter_values["open"]),
                    proprietary_model_count=len(quarter_values["proprietary"]),
                    open_source_model_count=len(quarter_values["open"]),
                    source_url=points[0].source_url if points else "derived://artificial_analysis/context_window_quarter_daily",
                    source_run_id=run_id,
                    scraped_at=scraped_at,
                )
            )
        return rows


def _is_open_model(point: ArtificialAnalysisModelPoint) -> bool:
    if point.is_open_weights is not None:
        return bool(point.is_open_weights)
    category = (point.open_source_categorization or "").lower()
    return "open" in category


def _median_or_none(values: list[int]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))
