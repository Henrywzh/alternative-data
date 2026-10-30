"""Weekly token activity and daily rolling-seven-day costs from Ramp's TSM sample."""
import json
import re
import time

import requests

from ramp_data.models import GenericRecord, Snapshot
from ramp_data.schemas import TOKENOMICS_DATASETS
from ramp_data.sources.ai_index import RampAiIndexSource


class RampTokenomicsSource(RampAiIndexSource):
    # Reuse the existing transport and RSC decoder, with independent quality
    # gates so a change to monthly adoption cannot silently discard TSM data.
    name = "ramp_tokenomics"
    datasets = TOKENOMICS_DATASETS

    def fetch_snapshots(self):
        snapshots = super().fetch_snapshots()
        if not snapshots:
            return []
        match = re.search(r'"dataVersion":"([^"]+)"', snapshots[0].body)
        if not match:
            return snapshots  # legacy embedded payload is still supported
        for cfg in self.datasets.values():
            key = cfg["payload_key"]
            url = f"https://ramp.com/data/ai-index/chart-data/{key}"
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = self.session.get(url, params={"version": match.group(1)}, timeout=self.timeout)
                    response.raise_for_status()
                    snapshots.append(Snapshot(name=key, source_url=response.url, body=response.text))
                    break
                except requests.RequestException as exc:
                    if attempt == self.max_retries:
                        print(f"Warning: Ramp chart-data {key} unavailable: {exc}")
                    else:
                        time.sleep(0.5 * (2 ** attempt))
        return snapshots

    def extract(self, snapshots, context):
        extracted = super().extract(snapshots, context)
        by_name = {snapshot.name: snapshot for snapshot in snapshots}
        for dataset_id, cfg in self.datasets.items():
            snapshot = by_name.get(cfg["payload_key"])
            if snapshot is None:
                continue
            try:
                rows = json.loads(snapshot.body)
            except (TypeError, ValueError):
                rows = []
            if not isinstance(rows, list):
                rows = []
            extracted[dataset_id] = [
                GenericRecord(dataset_id=dataset_id, source_url=snapshot.source_url,
                              source_run_id=context.run_id, scraped_at=context.scraped_at_iso,
                              payload={field: row.get(field) for field in cfg["fields"]})
                for row in rows if isinstance(row, dict)
            ]
        return extracted
