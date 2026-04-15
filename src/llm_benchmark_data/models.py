from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class BenchmarkPoint:
    model_id: str
    name: str
    organization: str
    release_date: str | None
    context_window: int | None
    gpqa: float | None
    swe_bench: float | None
    scraped_at: str
    source_url: str
    dataset_id: str
    source_run_id: str

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
        return self.scraped_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
