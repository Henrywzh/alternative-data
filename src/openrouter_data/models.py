from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class DatasetRecord:
    dataset_id: str
    week_label: str
    week_start_date: str
    entity_id: str
    entity_name: str
    parent_entity_id: str | None
    parent_entity_name: str | None
    metric_name: str
    metric_unit: str
    metric_value: float
    rank: int
    source_url: str
    source_run_id: str
    scraped_at: str
    category_slug: str | None = None

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
