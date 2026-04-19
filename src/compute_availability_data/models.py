from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
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
class DatasetRecord:
    dataset_id: str
    source_url: str
    source_run_id: str
    scraped_at: str
    snapshot_ts: str

    # OpenRouter fields
    model_id: str | None = None
    canonical_slug: str | None = None
    model_name: str | None = None
    created_at: float | None = None
    context_length: float | None = None
    architecture: str | None = None
    pricing_prompt: float | None = None
    pricing_completion: float | None = None
    top_provider_id: str | None = None
    provider_prefix: str | None = None

    # Lambda Cloud fields
    instance_type_name: str | None = None
    gpu_type: str | None = None
    gpu_count: float | None = None
    region: str | None = None

    # AWS Spot fields (region shared with Lambda)
    availability_zone: str | None = None
    instance_type: str | None = None
    product_description: str | None = None
    spot_price: float | None = None
    price_timestamp: str | None = None

    # Raw Payload (Optional if we want to follow the "minimal structured fields" rule)
    raw_json_preview: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    raw_run_dir: str
    dataset_row_deltas: dict[str, int] = field(default_factory=dict)


def coerce_target_date(value: str | date | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)
