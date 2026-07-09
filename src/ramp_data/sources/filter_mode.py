"""Ramp AI Index "Filter mode" source.

Each breakdown chart on ramp.com/data/ai-index has a "Filter mode" option that,
when selected, loads the full monthly timeseries for every cohort from dedicated
JSON endpoints (NOT the page's hydration payload):

    https://ramp.com/data/ai-index/filter-mode/spendShare?version=<token>
    https://ramp.com/data/ai-index/filter-mode/modelShare?version=<token>
    https://ramp.com/data/ai-index/filter-mode/spendPerEmployee?version=<token>

Each row is one month for one combination of the four cohort dimensions
(business_office_state, fte_segment, naics_sector, company_financing_status),
each either a specific value or "ALL". The endpoints require a version token,
published in the page payload as ``filterModeBundleVersion`` — so we scrape the
page to resolve it, then fetch the endpoints. The API field ``my_date`` is
renamed to ``date_month`` to match the other ramp datasets.
"""
from __future__ import annotations

import json
import re
import time

import requests

from ramp_data.models import GenericRecord, RunContext, Snapshot
from ramp_data.schemas import (
    FILTER_MODE_DATASETS,
    FILTER_MODE_ENDPOINT_BASE,
    FILTER_MODE_VERSION_KEY,
)
from ramp_data.sources import rsc
from ramp_data.sources.base import SourceExtractor

AI_INDEX_URL = "https://ramp.com/data/ai-index"
_VERSION_RE = re.compile(rf'"{FILTER_MODE_VERSION_KEY}":"([^"]+)"')


class RampFilterModeSource(SourceExtractor):
    name = "ramp_filter_mode"

    def __init__(self, timeout: int = 40, max_retries: int = 3) -> None:
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
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def _get(self, url: str) -> requests.Response | None:
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(f"status {response.status_code}")
                response.raise_for_status()
                return response
            except Exception as exc:  # noqa: BLE001 - retry any transport error
                if attempt == self.max_retries:
                    print(f"Warning: giving up on {url} after {attempt} attempts: {exc}")
                    return None
                time.sleep(0.5 * (2 ** attempt))
        return None

    def _resolve_version(self) -> str | None:
        response = self._get(AI_INDEX_URL)
        if response is None:
            return None
        match = _VERSION_RE.search(rsc.decode_payload(response.text))
        if not match:
            print("Warning: filterModeBundleVersion not found in AI Index payload")
            return None
        return match.group(1)

    def fetch_snapshots(self) -> list[Snapshot]:
        version = self._resolve_version()
        if not version:
            return []

        snapshots: list[Snapshot] = []
        for dataset_id, cfg in FILTER_MODE_DATASETS.items():
            url = f"{FILTER_MODE_ENDPOINT_BASE}/{cfg['endpoint']}?version={version}"
            response = self._get(url)
            if response is None:
                continue
            snapshots.append(Snapshot(name=dataset_id, source_url=url, body=response.text))
        return snapshots

    def extract(
        self,
        snapshots: list[Snapshot],
        context: RunContext,
    ) -> dict[str, list[GenericRecord]]:
        extracted: dict[str, list[GenericRecord]] = {dsid: [] for dsid in FILTER_MODE_DATASETS}

        by_name = {s.name: s for s in snapshots}
        for dataset_id, cfg in FILTER_MODE_DATASETS.items():
            snapshot = by_name.get(dataset_id)
            if snapshot is None:
                continue
            try:
                rows = json.loads(snapshot.body)
            except json.JSONDecodeError as exc:
                print(f"Warning: bad JSON for {dataset_id}: {exc}")
                continue
            if not isinstance(rows, list):
                continue
            fields = cfg["fields"]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                # The endpoint keys the month as ``my_date``; alias to date_month.
                payload = {
                    field: (row.get("my_date") if field == "date_month" else row.get(field))
                    for field in fields
                }
                extracted[dataset_id].append(
                    GenericRecord(
                        dataset_id=dataset_id,
                        source_url=snapshot.source_url,
                        source_run_id=context.run_id,
                        scraped_at=context.scraped_at_iso,
                        payload=payload,
                    )
                )
        return extracted
