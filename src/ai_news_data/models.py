from __future__ import annotations

from dataclasses import dataclass
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
        return self.scraped_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class GenericRecord:
    """A config-driven record: fixed provenance columns + a free-form payload.

    Each source dataset has its own schema, so storage projects ``to_dict``
    onto that dataset's configured columns rather than forcing one mega-schema.
    """

    dataset_id: str
    source_url: str
    source_run_id: str
    scraped_at: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "source_url": self.source_url,
            "source_run_id": self.source_run_id,
            "scraped_at": self.scraped_at,
            **self.payload,
        }
