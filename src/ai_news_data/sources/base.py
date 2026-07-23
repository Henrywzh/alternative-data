from __future__ import annotations

from abc import ABC, abstractmethod

from ai_news_data.models import GenericRecord, RunContext, Snapshot


class SourceExtractor(ABC):
    name: str

    @abstractmethod
    def fetch_snapshots(self) -> list[Snapshot]:
        """Return raw snapshots required for extraction."""

    @abstractmethod
    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[GenericRecord]]:
        """Convert snapshots into normalized records keyed by dataset id."""
