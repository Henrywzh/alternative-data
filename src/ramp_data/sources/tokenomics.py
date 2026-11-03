"""Weekly token activity and daily rolling-seven-day costs from Ramp's TSM sample.

The AI Index page loads both series as JSON arrays from
``https://ramp.com/data/ai-index/chart-data/<endpoint>`` (tokenVolumes,
tokenPrices), whose object fields are the dataset columns. The page passes the
same version token as the filter-mode endpoints; it is optional, so a page
that no longer publishes it does not stop the fetch.
"""
from __future__ import annotations

import json

from ramp_data.models import GenericRecord, RunContext, Snapshot
from ramp_data.schemas import TOKENOMICS_DATASETS, TOKENOMICS_ENDPOINT_BASE
from ramp_data.sources import rsc
from ramp_data.sources.filter_mode import AI_INDEX_URL, RampFilterModeSource, find_version


class RampTokenomicsSource(RampFilterModeSource):
    # Reuses the filter-mode transport (JSON endpoints, retries), with its own
    # quality gate so a change to monthly adoption cannot discard TSM data.
    name = "ramp_tokenomics"
    datasets = TOKENOMICS_DATASETS

    def fetch_snapshots(self) -> list[Snapshot]:
        page = self._get(AI_INDEX_URL)
        version = find_version(rsc.decode_payload(page.text)) if page is not None else None
        snapshots: list[Snapshot] = []
        for dataset_id, cfg in TOKENOMICS_DATASETS.items():
            url = f"{TOKENOMICS_ENDPOINT_BASE}/{cfg['endpoint']}" + (f"?version={version}" if version else "")
            response = self._get(url)
            if response is not None:
                snapshots.append(Snapshot(name=dataset_id, source_url=url, body=response.text))
        return snapshots

    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[GenericRecord]]:
        extracted: dict[str, list[GenericRecord]] = {dsid: [] for dsid in TOKENOMICS_DATASETS}
        for snapshot in snapshots:
            cfg = TOKENOMICS_DATASETS.get(snapshot.name)
            if cfg is None:
                continue
            try:
                rows = json.loads(snapshot.body)
            except json.JSONDecodeError as exc:
                print(f"Warning: bad JSON for {snapshot.name}: {exc}")
                continue
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict):
                    extracted[snapshot.name].append(GenericRecord(
                        dataset_id=snapshot.name,
                        source_url=snapshot.source_url,
                        source_run_id=context.run_id,
                        scraped_at=context.scraped_at_iso,
                        payload={field: row.get(field) for field in cfg["fields"]},
                    ))
        return extracted
