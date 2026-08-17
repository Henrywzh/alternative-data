from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from semiconductor_high_frequency_data.config import resolve_credential
from semiconductor_high_frequency_data.models import PipelineResult, RunContext, Snapshot
from semiconductor_high_frequency_data.sources.kcs import KoreaCustomsHighFrequencySource
from semiconductor_high_frequency_data.sources.kosis import KosisSemiconductorSource
from semiconductor_high_frequency_data.sources.krx import KrxPositioningSource
from semiconductor_high_frequency_data.storage import StorageManager


class HighFrequencyPipeline:
    def __init__(
        self,
        base_dir: Path,
        *,
        kcs_source: KoreaCustomsHighFrequencySource | None = None,
        krx_source: KrxPositioningSource | None = None,
        kosis_source: KosisSemiconductorSource | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.kcs_source = kcs_source or KoreaCustomsHighFrequencySource()
        self.krx_source = krx_source or KrxPositioningSource()
        self.kosis_source = kosis_source or KosisSemiconductorSource()

    def run_kcs_update(
        self,
        *,
        start_month: str,
        end_month: str,
        include_ten_day: bool = True,
        include_monthly_memory: bool = True,
        country_scopes: dict[str, str] | None = None,
    ) -> PipelineResult:
        months = _month_range(start_month, end_month)
        if getattr(self.kcs_source, "service_key", None) is None:
            self.kcs_source.service_key = resolve_credential(
                self.base_dir,
                ("KCS_SERVICE_KEY", "KOREA_CUSTOMS_SERVICE_KEY"),
            )

        context = self._create_context()
        snapshots: list[Snapshot] = []
        ten_day_points = []
        monthly_points = []
        if include_ten_day:
            ten_day_snapshots = self.kcs_source.fetch_ten_day_snapshots(months)
            snapshots.extend(ten_day_snapshots)
            ten_day_points = self.kcs_source.extract_ten_day(
                ten_day_snapshots,
                run_id=context.run_id,
                scraped_at=context.scraped_at_iso,
            )
        if include_monthly_memory:
            monthly_snapshots = self.kcs_source.fetch_monthly_memory_snapshots(
                months,
                country_scopes=country_scopes,
            )
            snapshots.extend(monthly_snapshots)
            monthly_points = self.kcs_source.extract_monthly_memory(
                monthly_snapshots,
                run_id=context.run_id,
                scraped_at=context.scraped_at_iso,
            )

        return self._write_result(
            context,
            snapshots=snapshots,
            command="kcs-update",
            datasets={
                "kcs_10day_exports": ten_day_points,
                "kcs_memory_monthly_country": monthly_points,
            },
        )

    def run_krx_update(
        self,
        *,
        start_date: str,
        end_date: str,
        instrument_codes: list[str],
        include_investor_flow: bool = True,
        include_short_position: bool = True,
        instrument_isins: dict[str, str] | None = None,
    ) -> PipelineResult:
        context = self._create_context()
        snapshots = self.krx_source.fetch_snapshots(
            start_date=start_date,
            end_date=end_date,
            instrument_codes=instrument_codes,
            instrument_isins=instrument_isins,
            include_investor_flow=include_investor_flow,
            include_short_position=include_short_position,
        )
        points = self.krx_source.extract(
            snapshots,
            run_id=context.run_id,
            scraped_at=context.scraped_at_iso,
        )
        return self._write_result(
            context,
            snapshots=snapshots,
            command="krx-update",
            datasets={"krx_positioning_daily": points},
        )

    def run_kosis_update(self, *, start_month: str, end_month: str) -> PipelineResult:
        if getattr(self.kosis_source, "api_key", None) is None:
            self.kosis_source.api_key = resolve_credential(
                self.base_dir,
                ("KOSIS_API_KEY", "KOSIS_KEY"),
            )
        context = self._create_context()
        snapshots = self.kosis_source.fetch_snapshots(start_month=start_month, end_month=end_month)
        points = self.kosis_source.extract(
            snapshots,
            run_id=context.run_id,
            scraped_at=context.scraped_at_iso,
        )
        return self._write_result(
            context,
            snapshots=snapshots,
            command="kosis-update",
            datasets={"kosis_semiconductor_cycle_monthly": points},
        )

    def validate(self) -> dict[str, int | str | None]:
        result: dict[str, int | str | None] = {}
        for dataset_id in (
            "kcs_10day_exports",
            "kcs_memory_monthly_country",
            "krx_positioning_daily",
            "kosis_semiconductor_cycle_monthly",
        ):
            dataframe = self.storage.load_dataset(dataset_id)
            natural_key = self.storage_specs(dataset_id)["natural_key"]
            result[f"{dataset_id}_rows"] = int(len(dataframe))
            result[f"{dataset_id}_duplicates"] = int(dataframe.duplicated(subset=natural_key).sum()) if not dataframe.empty else 0
            result[f"{dataset_id}_latest_period"] = _latest_period(dataframe, dataset_id)
        return result

    def storage_specs(self, dataset_id: str) -> dict[str, list[str]]:
        from semiconductor_high_frequency_data.storage import DATASET_SPECS

        return DATASET_SPECS[dataset_id]

    def _write_result(
        self,
        context: RunContext,
        *,
        snapshots: list[Snapshot],
        command: str,
        datasets: dict[str, list[object]],
    ) -> PipelineResult:
        existing = {dataset_id: self.storage.load_dataset(dataset_id) for dataset_id in datasets}
        manifest = {
            "run_id": context.run_id,
            "scraped_at": context.scraped_at_iso,
            "command": command,
            "parser_versions": sorted({
                str(record.to_dict().get("parser_version"))
                for records in datasets.values()
                for record in records
                if record.to_dict().get("parser_version")
            }),
            "snapshots": [
                {"name": snapshot.name, "source_url": snapshot.source_url, "metadata": snapshot.metadata}
                for snapshot in snapshots
            ],
            "dataset_row_counts": {dataset_id: len(records) for dataset_id, records in datasets.items()},
        }
        raw_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)
        written: dict[str, int] = {}
        deltas: dict[str, int] = {}
        for dataset_id, records in datasets.items():
            dataframe = self.storage.upsert_dataset(dataset_id, records)
            written[dataset_id] = len(dataframe)
            deltas[dataset_id] = max(len(dataframe) - len(existing[dataset_id]), 0)
        return PipelineResult(
            run_id=context.run_id,
            datasets_written=written,
            raw_run_dir=str(raw_dir),
            dataset_row_deltas=deltas,
        )

    @staticmethod
    def _create_context() -> RunContext:
        now = datetime.now(timezone.utc)
        return RunContext(
            run_id=now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            scraped_at=now,
        )


def _month_range(start_month: str, end_month: str) -> list[str]:
    start = pd.Period(start_month, freq="M")
    end = pd.Period(end_month, freq="M")
    if end < start:
        raise ValueError("end_month must be greater than or equal to start_month")
    return [period.strftime("%Y-%m") for period in pd.period_range(start=start, end=end, freq="M")]


def _latest_period(dataframe: pd.DataFrame, dataset_id: str) -> str | None:
    if dataframe.empty:
        return None
    column = "trade_date" if dataset_id == "krx_positioning_daily" else "period"
    return str(dataframe[column].max())
