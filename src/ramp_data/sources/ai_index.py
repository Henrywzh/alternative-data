"""Ramp AI Index source.

``ramp.com/data/ai-index`` server-renders the full Ramp AI Index as JSON arrays
embedded in its Next.js RSC payload — one array per dataset, under a named key
(``adoptionOverall``, ``adoptionState``, ``spendPerEmployee`` …). The object
fields already use the snake_case names we keep, so extraction is a near
passthrough via the existing string-safe ``rsc.extract_array_after_key``.

Each dataset is a monthly time series; they accumulate as history (never REPLACE)
so committed months survive even though every fetch returns the full series.
"""
from __future__ import annotations

import time

import requests

from ramp_data.models import GenericRecord, RunContext, Snapshot
from ramp_data.schemas import AI_INDEX_DATASETS
from ramp_data.sources import rsc
from ramp_data.sources.base import SourceExtractor

AI_INDEX_URL = "https://ramp.com/data/ai-index"
SNAPSHOT_NAME = "ai_index"


class RampAiIndexSource(SourceExtractor):
    name = "ramp_ai_index"

    def __init__(self, timeout: int = 30, max_retries: int = 3) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def fetch_snapshots(self) -> list[Snapshot]:
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(AI_INDEX_URL, timeout=self.timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(f"status {response.status_code}")
                response.raise_for_status()
                payload = rsc.decode_payload(response.text)
                return [Snapshot(name=SNAPSHOT_NAME, source_url=AI_INDEX_URL, body=payload)]
            except Exception as exc:  # noqa: BLE001 - retry any transport error
                if attempt == self.max_retries:
                    print(f"Warning: failed to fetch Ramp AI Index after {attempt} attempts: {exc}")
                    return []
                time.sleep(0.5 * (2 ** attempt))
        return []

    def extract(
        self,
        snapshots: list[Snapshot],
        context: RunContext,
    ) -> dict[str, list[GenericRecord]]:
        extracted: dict[str, list[GenericRecord]] = {dsid: [] for dsid in AI_INDEX_DATASETS}

        payload = next((s.body for s in snapshots if s.name == SNAPSHOT_NAME), "")
        if not payload:
            return extracted

        for dataset_id, cfg in AI_INDEX_DATASETS.items():
            rows = rsc.extract_array_after_key(payload, cfg["payload_key"])
            fields = cfg["fields"]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                extracted[dataset_id].append(
                    GenericRecord(
                        dataset_id=dataset_id,
                        source_url=AI_INDEX_URL,
                        source_run_id=context.run_id,
                        scraped_at=context.scraped_at_iso,
                        payload={field: row.get(field) for field in fields},
                    )
                )

        return extracted
