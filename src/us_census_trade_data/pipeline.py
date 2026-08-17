from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from us_census_trade_data.config import (
    DEFAULT_COMPARISON_COUNTRY_CODES,
    DEFAULT_HS_CODE,
    DEFAULT_SOUTH_KOREA_CODE,
    DEFAULT_START_MONTH,
    resolve_optional_credential,
    SourceResponseError,
)
from us_census_trade_data.models import PipelineResult, RunContext
from us_census_trade_data.sources.census import (
    CensusInternationalTradeSource,
    CensusPortInternationalTradeSource,
)
from us_census_trade_data.storage import DATASET_ID, PORT_DATASET_ID, StorageManager


PARSER_VERSION = "census-imports-hs-v1"


class CensusTradePipeline:
    def __init__(
        self,
        base_dir: Path,
        *,
        source: CensusInternationalTradeSource | None = None,
        port_source: CensusPortInternationalTradeSource | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.source = source or CensusInternationalTradeSource(
            api_key=resolve_optional_credential(
                base_dir,
                ("CENSUS_DATA_API_KEY", "CENSUS_API_KEY", "US_CENSUS_API_KEY"),
            ),
        )
        self.port_source = port_source or CensusPortInternationalTradeSource(
            api_key=getattr(self.source, "api_key", None)
        )

    def run_backfill(
        self,
        *,
        start_month: str | None = None,
        end_month: str | None = None,
        partner_country_code: str = DEFAULT_SOUTH_KOREA_CODE,
        partner_country_codes: list[str] | None = None,
        hs_code: str = DEFAULT_HS_CODE,
    ) -> PipelineResult:
        target_start = start_month or DEFAULT_START_MONTH
        target_end = end_month or _latest_closed_month()
        months = _month_range(target_start, target_end)
        return self._run(
            months,
            command="backfill",
            partner_country_codes=_resolve_partner_codes(partner_country_code, partner_country_codes),
            hs_code=hs_code,
        )

    def run_update_latest(
        self,
        *,
        revenue_month: str | None = None,
        partner_country_code: str = DEFAULT_SOUTH_KOREA_CODE,
        partner_country_codes: list[str] | None = None,
        hs_code: str = DEFAULT_HS_CODE,
    ) -> PipelineResult:
        month = revenue_month or _latest_closed_month()
        _month_range(month, month)
        return self._run(
            [month],
            command="update-latest",
            partner_country_codes=_resolve_partner_codes(partner_country_code, partner_country_codes),
            hs_code=hs_code,
        )

    def run_port_backfill(
        self,
        *,
        start_month: str | None = None,
        end_month: str | None = None,
        partner_country_code: str = DEFAULT_SOUTH_KOREA_CODE,
        partner_country_codes: list[str] | None = None,
        hs_code: str = DEFAULT_HS_CODE,
    ) -> PipelineResult:
        target_start = start_month or DEFAULT_START_MONTH
        target_end = end_month or _latest_closed_month()
        months = _month_range(target_start, target_end)
        return self._run_port(
            months,
            command="port-backfill",
            partner_country_codes=_resolve_partner_codes(partner_country_code, partner_country_codes),
            hs_code=hs_code,
        )

    def run_port_update_latest(
        self,
        *,
        revenue_month: str | None = None,
        partner_country_code: str = DEFAULT_SOUTH_KOREA_CODE,
        partner_country_codes: list[str] | None = None,
        hs_code: str = DEFAULT_HS_CODE,
    ) -> PipelineResult:
        month = revenue_month or _latest_closed_month()
        _month_range(month, month)
        return self._run_port(
            [month],
            command="port-update-latest",
            partner_country_codes=_resolve_partner_codes(partner_country_code, partner_country_codes),
            hs_code=hs_code,
        )

    def validate(self) -> dict[str, int | str | None]:
        dataframe = self.storage.load_dataset()
        if dataframe.empty:
            return {
                "rows": 0,
                "duplicate_keys": 0,
                "missing_general_value": 0,
                "missing_general_quantity": 0,
                "quantity_available_rows": 0,
                "latest_period": None,
            }
        return {
            "rows": int(len(dataframe)),
            "duplicate_keys": int(dataframe.duplicated(subset=["period", "partner_country_code", "hs_code"]).sum()),
            "missing_general_value": int(dataframe["general_import_value_usd"].isna().sum()),
            "missing_general_quantity": int(dataframe["general_import_quantity"].isna().sum()),
            "quantity_available_rows": int(dataframe["general_import_quantity"].notna().sum()),
            "latest_period": str(dataframe["period"].max()),
        }

    def validate_port(self) -> dict[str, int | str | None]:
        dataframe = self.storage.load_dataset(PORT_DATASET_ID)
        if dataframe.empty:
            return {
                "rows": 0,
                "duplicate_keys": 0,
                "missing_general_value": 0,
                "distinct_ports": 0,
                "latest_period": None,
            }
        return {
            "rows": int(len(dataframe)),
            "duplicate_keys": int(
                dataframe.duplicated(
                    subset=["period", "port_code", "partner_country_code", "hs_code"]
                ).sum()
            ),
            "missing_general_value": int(dataframe["general_import_value_usd"].isna().sum()),
            "distinct_ports": int(dataframe["port_code"].nunique()),
            "latest_period": str(dataframe["period"].max()),
        }

    def _run(
        self,
        months: list[str],
        *,
        command: str,
        partner_country_codes: list[str],
        hs_code: str,
    ) -> PipelineResult:
        context = self._create_context()
        snapshots = self.source.fetch_snapshots(
            months,
            partner_country_codes=partner_country_codes,
            hs_code=hs_code,
        )
        points = self.source.extract(snapshots, run_id=context.run_id, scraped_at=context.scraped_at_iso)
        manifest = {
            "run_id": context.run_id,
            "scraped_at": context.scraped_at_iso,
            "source": "census-international-trade-imports-hs",
            "command": command,
            "months": months,
            "partner_country_codes": partner_country_codes,
            "hs_code": hs_code,
            "parser_version": PARSER_VERSION,
            "row_count": len(points),
            "returned_months": sorted({point.period for point in points}),
            "missing_month_partner_pairs": _missing_month_partner_pairs(
                months, partner_country_codes, points
            ),
            "snapshots": [{"name": item.name, "source_url": item.source_url} for item in snapshots],
        }
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)
        missing = manifest["missing_month_partner_pairs"]
        if missing:
            raise SourceResponseError(
                "Census national import data missing requested month/partner pairs: "
                + ", ".join(missing)
            )
        existing = self.storage.load_dataset()
        written = self.storage.upsert_dataset(points)
        return PipelineResult(
            run_id=context.run_id,
            datasets_written={DATASET_ID: len(written)},
            raw_run_dir=str(raw_run_dir),
            dataset_row_deltas={DATASET_ID: max(len(written) - len(existing), 0)},
        )

    def _run_port(
        self,
        months: list[str],
        *,
        command: str,
        partner_country_codes: list[str],
        hs_code: str,
    ) -> PipelineResult:
        context = self._create_context()
        snapshots = self.port_source.fetch_port_snapshots(
            months,
            partner_country_codes=partner_country_codes,
            hs_code=hs_code,
        )
        points = self.port_source.extract_port_snapshots(
            snapshots,
            run_id=context.run_id,
            scraped_at=context.scraped_at_iso,
        )
        manifest = {
            "run_id": context.run_id,
            "scraped_at": context.scraped_at_iso,
            "source": "census-international-trade-imports-porths",
            "command": command,
            "months": months,
            "partner_country_codes": partner_country_codes,
            "hs_code": hs_code,
            "parser_version": "census-imports-porths-v1",
            "row_count": len(points),
            "returned_months": sorted({point.period for point in points}),
            "missing_month_partner_pairs": _missing_month_partner_pairs(
                months, partner_country_codes, points
            ),
            "snapshots": [{"name": item.name, "source_url": item.source_url} for item in snapshots],
        }
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)
        missing = manifest["missing_month_partner_pairs"]
        if missing:
            raise SourceResponseError(
                "Census port import data missing requested month/partner pairs: "
                + ", ".join(missing)
            )
        existing = self.storage.load_dataset(PORT_DATASET_ID)
        written = self.storage.upsert_dataset(points, PORT_DATASET_ID)
        return PipelineResult(
            run_id=context.run_id,
            datasets_written={PORT_DATASET_ID: len(written)},
            raw_run_dir=str(raw_run_dir),
            dataset_row_deltas={PORT_DATASET_ID: max(len(written) - len(existing), 0)},
        )

    @staticmethod
    def _create_context() -> RunContext:
        return RunContext(
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            scraped_at=datetime.now(timezone.utc),
        )


def _latest_closed_month() -> str:
    now = datetime.now(timezone.utc)
    period = pd.Period(now.strftime("%Y-%m"), freq="M") - 1
    return period.strftime("%Y-%m")


def _month_range(start_month: str, end_month: str) -> list[str]:
    start = pd.Period(start_month, freq="M")
    end = pd.Period(end_month, freq="M")
    if end < start:
        raise ValueError("end_month must be greater than or equal to start_month")
    if start.year < 2010:
        raise ValueError("Census monthly trade data starts in 2010")
    return [period.strftime("%Y-%m") for period in pd.period_range(start=start, end=end, freq="M")]


def _resolve_partner_codes(
    partner_country_code: str | None,
    partner_country_codes: list[str] | None,
) -> list[str]:
    if partner_country_codes:
        values = partner_country_codes
    elif partner_country_code:
        values = [partner_country_code]
    else:
        values = list(DEFAULT_COMPARISON_COUNTRY_CODES)
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _missing_month_partner_pairs(
    months: list[str], partner_country_codes: list[str], points: list[object]
) -> list[str]:
    returned = {(point.period, point.partner_country_code) for point in points}
    expected = {(month, partner) for month in months for partner in partner_country_codes}
    return [f"{month}/{partner}" for month, partner in sorted(expected - returned)]
