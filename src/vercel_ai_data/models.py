from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class DatasetRecord:
    dataset_id: str
    source_url: str
    source_run_id: str
    scraped_at: str

    # Leaderboard fields
    date: str | None = None
    group: str | None = None          # "model" or "lab"
    name: str | None = None           # Name of model/lab
    metric: str | None = None         # "tokens", "requests", "spend", "imageCount", "videoCount"
    modality: str | None = None       # "all", "text", "image", "video"
    share_percent: float | None = None
    rank: int | None = None           # Rank within date / metric / modality

    # Catalog fields
    model_id: str | None = None
    owned_by: str | None = None
    description: str | None = None
    context_window: int | None = None
    max_tokens: int | None = None
    type: str | None = None           # "language", "image", "video", "embedding"
    pricing_input: float | None = None
    pricing_output: float | None = None
    pricing_cache_read: float | None = None
    pricing_cache_write: float | None = None
    tags: str | None = None           # Comma-separated tags
    raw_pricing_json: str | None = None

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
        return self.scraped_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
