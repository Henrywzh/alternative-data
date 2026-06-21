from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Snapshot:
    name: str
    source_url: str
    body: str


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


@dataclass
class MonthlyPoint:
    dataset_id: str
    source_region: str
    country_name: str
    metric_type: str
    flow_code: str
    partner_scope: str
    period: str
    release_date: str | None
    expected_release_window_days: int | None
    lag_days: int | None
    category_id: str
    category_label: str
    classification_system: str
    classification_code: str
    unit: str
    currency: str
    value: float | None
    yoy_pct: float | None
    mom_pct: float | None
    is_preliminary: bool
    is_revised: bool
    is_official_primary: bool
    comparison_gap_pct: float | None
    source_name: str
    source_url: str
    source_run_id: str
    scraped_at: str
    parser_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OfficialMonthlyPoint(MonthlyPoint):
    pass


@dataclass
class BackupCheckPoint(MonthlyPoint):
    pass


@dataclass
class SourceCatalogPoint:
    dataset_id: str
    source_region: str
    country_name: str
    source_name: str
    source_tier: str
    metric_type: str
    category_id: str
    category_label: str
    coverage_start: str | None
    latest_period: str | None
    cadence: str
    expected_release_window_days: int | None
    default_unit: str
    default_currency: str
    is_official_primary: bool
    notes: str | None
    source_url: str
    source_run_id: str
    scraped_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: str
    dataset_row_deltas: dict[str, int] = field(default_factory=dict)
