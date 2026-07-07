from __future__ import annotations

import json
import requests

from vercel_ai_data.models import DatasetRecord, RunContext, Snapshot
from vercel_ai_data.sources.base import SourceExtractor


class VercelModelsCatalogSource(SourceExtractor):
    name = "vercel_models_catalog"

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
        )

    def fetch_snapshots(self) -> list[Snapshot]:
        snapshots: list[Snapshot] = []
        url = "https://ai-gateway.vercel.sh/v1/models"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            snapshots.append(
                Snapshot(
                    name="vercel_models",
                    source_url=url,
                    body=response.text,
                )
            )
        except Exception as exc:
            print(f"Warning: Failed to fetch Vercel models catalog snapshot: {exc}")
        return snapshots

    def extract(
        self,
        snapshots: list[Snapshot],
        context: RunContext,
    ) -> dict[str, list[DatasetRecord]]:
        extracted: dict[str, list[DatasetRecord]] = {
            "vercel_models": [],
        }

        for snapshot in snapshots:
            if snapshot.name != "vercel_models":
                continue

            try:
                data = json.loads(snapshot.body)
            except Exception as exc:
                print(f"Error parsing JSON from vercel_models catalog: {exc}")
                continue

            models_list = data.get("data", [])
            if not isinstance(models_list, list):
                print("Warning: Expected 'data' to be a list in models catalog")
                continue

            for m in models_list:
                if not isinstance(m, dict):
                    continue

                model_id = m.get("id")
                if not model_id:
                    continue

                # Parse pricing details
                pricing = m.get("pricing", {})
                pricing_input = None
                pricing_output = None
                pricing_cache_read = None
                pricing_cache_write = None

                if isinstance(pricing, dict):
                    pricing_input = pricing.get("input")
                    pricing_output = pricing.get("output")
                    pricing_cache_read = pricing.get("input_cache_read")
                    pricing_cache_write = pricing.get("input_cache_write")

                # Parse tags
                tags = m.get("tags", [])
                tags_str = None
                if isinstance(tags, list):
                    tags_str = ", ".join(str(t) for t in tags)
                elif isinstance(tags, str):
                    tags_str = tags

                record = DatasetRecord(
                    dataset_id="vercel_models",
                    source_url=snapshot.source_url,
                    source_run_id=context.run_id,
                    scraped_at=context.scraped_at_iso,
                    model_id=model_id,
                    name=m.get("name"),
                    owned_by=m.get("owned_by"),
                    description=m.get("description"),
                    context_window=m.get("context_window"),
                    max_tokens=m.get("max_tokens"),
                    type=m.get("type"),
                    pricing_input=pricing_input,
                    pricing_output=pricing_output,
                    pricing_cache_read=pricing_cache_read,
                    pricing_cache_write=pricing_cache_write,
                    tags=tags_str,
                    raw_pricing_json=json.dumps(pricing) if pricing else None,
                )
                extracted["vercel_models"].append(record)

        return extracted
