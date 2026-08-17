from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Snapshot:
    name: str
    source_url: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunContext:
    run_id: str
    scraped_at: datetime

    @property
    def scraped_at_iso(self) -> str:
        value = self.scraped_at
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class KcsTenDayPoint:
    dataset_id: str
    period: str
    period_start: str | None
    period_end: str | None
    period_month: str | None
    release_date: str | None
    release_date_inferred: bool
    metric: str
    value: float
    unit: str
    currency: str
    is_preliminary: bool
    is_revised: bool | None
    source_url: str
    source_run_id: str
    scraped_at: str
    parser_version: str
    raw_period_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KcsMemoryMonthlyPoint:
    dataset_id: str
    period: str
    country_scope: str
    country_code: str
    country_name: str | None
    hs_code: str
    item_name: str | None
    export_value_usd: float | None
    export_weight_kg: float | None
    import_value_usd: float | None
    import_weight_kg: float | None
    trade_balance_usd: float | None
    export_value_per_kg_usd: float | None
    release_date: str | None
    is_preliminary: bool | None
    is_revised: bool | None
    source_url: str
    source_run_id: str
    scraped_at: str
    parser_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KrxPositioningPoint:
    dataset_id: str
    trade_date: str
    instrument_code: str
    instrument_name: str | None
    market: str | None
    data_family: str
    investor_type: str | None
    measure: str
    value: float
    unit: str
    currency: str | None
    availability_lag_days: int
    source_url: str
    source_run_id: str
    scraped_at: str
    parser_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KosisIndustryIndexPoint:
    dataset_id: str
    period: str
    industry_code: str | None
    industry_name: str | None
    measure: str
    value: float | None
    unit: str | None
    seasonal_adjustment: str
    item_code: str | None
    item_name: str | None
    object_code: str | None
    object_name: str | None
    release_date: str | None
    source_table_id: str
    source_org_id: str
    source_url: str
    source_run_id: str
    scraped_at: str
    parser_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: str
    dataset_row_deltas: dict[str, int] = field(default_factory=dict)
