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
    # NOTE: AWS Spot + Lambda Cloud fields were removed along with their source collectors.
    model_id: str | None = None
    canonical_slug: str | None = None
    model_name: str | None = None
    created_at: float | None = None
    context_length: float | None = None
    architecture: str | None = None
    description: str | None = None
    hugging_face_id: str | None = None
    architecture_modality: str | None = None
    input_modalities_json: str | None = None
    output_modalities_json: str | None = None
    tokenizer: str | None = None
    instruct_type: str | None = None
    supported_parameters_json: str | None = None
    default_parameters_json: str | None = None
    per_request_limits_json: str | None = None
    pricing_prompt: float | None = None
    pricing_completion: float | None = None
    pricing_request: float | None = None
    pricing_image: float | None = None
    pricing_web_search: float | None = None
    pricing_internal_reasoning: float | None = None
    pricing_input_cache_read: float | None = None
    pricing_input_cache_write: float | None = None
    top_provider_id: str | None = None
    top_provider_context_length: float | None = None
    top_provider_max_completion_tokens: float | None = None
    top_provider_is_moderated: bool | None = None
    provider_prefix: str | None = None
    expiration_date: str | None = None
    knowledge_cutoff: str | None = None
    benchmarks_json: str | None = None
    links_json: str | None = None
    reasoning_json: str | None = None
    supported_voices_json: str | None = None

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
