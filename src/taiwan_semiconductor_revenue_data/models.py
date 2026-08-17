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


@dataclass(frozen=True)
class CompanyConfig:
    company_code: str
    company_name: str
    market: str
    industry: str
    coverage_start_month: str | None = None


@dataclass
class MonthlyRevenuePoint:
    dataset_id: str
    company_code: str
    company_name: str
    market: str
    industry: str
    filing_date: str | None
    revenue_month: str
    monthly_revenue_ntd: float | None
    mom_pct: float | None
    yoy_pct: float | None
    ytd_revenue_ntd: float | None
    ytd_yoy_pct: float | None
    source_url: str
    source_run_id: str
    scraped_at: str
    parser_version: str
    mom_pct_is_derived: bool = False
    raw_company_name_text: str | None = None
    raw_monthly_revenue_text: str | None = None
    raw_mom_pct_text: str | None = None
    raw_yoy_pct_text: str | None = None
    raw_ytd_revenue_text: str | None = None
    raw_ytd_yoy_pct_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: str
    dataset_row_deltas: dict[str, int] = field(default_factory=dict)
