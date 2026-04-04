from __future__ import annotations

from openrouter_data.models import DatasetRecord, RunContext, Snapshot
from openrouter_data.sources.base import SourceExtractor


class AppsSource(SourceExtractor):
    """Reserved for phase-2 app and trending-app extraction."""

    name = "openrouter_apps"

    def fetch_snapshots(self) -> list[Snapshot]:
        return []

    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[DatasetRecord]]:
        return {}
