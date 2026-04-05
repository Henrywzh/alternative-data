from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class DatasetRecord:
    dataset_id: str
    source_url: str
    source_run_id: str
    scraped_at: str
    week_label: str | None = None
    week_start_date: str | None = None
    entity_id: str | None = None
    entity_name: str | None = None
    parent_entity_id: str | None = None
    parent_entity_name: str | None = None
    metric_name: str | None = None
    metric_unit: str | None = None
    metric_value: float | None = None
    rank: int | None = None
    category_slug: str | None = None
    app_id: str | None = None
    app_name: str | None = None
    origin_url: str | None = None
    main_url: str | None = None
    description: str | None = None
    categories: str | None = None
    group_by_origin: bool | None = None
    is_private: bool | None = None
    is_hidden: bool | None = None
    created_at: str | None = None
    scrape_date: str | None = None
    usage_date: str | None = None
    model_permaslug: str | None = None
    total_tokens: float | None = None
    snapshot_date: str | None = None
    observed_at: str | None = None
    period: str | None = None
    tokens: float | None = None
    growth_percent: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        return self.scraped_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
