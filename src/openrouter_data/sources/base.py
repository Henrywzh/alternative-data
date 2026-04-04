from __future__ import annotations

from abc import ABC, abstractmethod

from openrouter_data.models import DatasetRecord, RunContext, Snapshot


class SourceExtractor(ABC):
    name: str

    @abstractmethod
    def fetch_snapshots(self) -> list[Snapshot]:
        """Return raw snapshots required for extraction."""

    @abstractmethod
    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[DatasetRecord]]:
        """Convert snapshots into normalized records keyed by dataset id."""
