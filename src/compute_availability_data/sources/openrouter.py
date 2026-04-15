from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import requests

from compute_availability_data.models import DatasetRecord, Snapshot


class OpenRouterSource:
    URL = "https://openrouter.ai/api/v1/models"

    def fetch_snapshot(self) -> Snapshot:
        response = requests.get(self.URL, timeout=30)
        response.raise_for_status()
        return Snapshot(
            name="openrouter_models",
            source_url=self.URL,
            body=response.text,
        )

    def extract(self, snapshot: Snapshot, run_id: str, scraped_at: str) -> list[DatasetRecord]:
        data = json.loads(snapshot.body)
        models = data.get("data", [])
        snapshot_ts = scraped_at  # Use scraped_at as snapshot_ts for consistency

        records = []
        for model in models:
            pricing = model.get("pricing", {})
            architecture = model.get("architecture", {})
            top_provider = model.get("top_provider", {})
            
            records.append(
                DatasetRecord(
                    dataset_id="raw_openrouter_models",
                    source_url=self.URL,
                    source_run_id=run_id,
                    scraped_at=scraped_at,
                    snapshot_ts=snapshot_ts,
                    model_id=model.get("id"),
                    model_name=model.get("name"),
                    created_at=float(model.get("created")) if model.get("created") else None,
                    context_length=float(model.get("context_length")) if model.get("context_length") else None,
                    architecture=architecture.get("modality") or architecture.get("tokenizer"),
                    pricing_prompt=float(pricing.get("prompt")) if pricing.get("prompt") else None,
                    pricing_completion=float(pricing.get("completion")) if pricing.get("completion") else None,
                    top_provider_id=top_provider.get("id"),
                )
            )
        return records
