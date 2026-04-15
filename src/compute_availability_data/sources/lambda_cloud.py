from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import requests

from compute_availability_data.models import DatasetRecord, Snapshot


class LambdaCloudSource:
    URL = "https://cloud.lambdalabs.com/api/v1/instance-types"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("LAMBDA_CLOUD_API_KEY")

    def fetch_snapshot(self) -> Snapshot:
        if not self.api_key:
            raise ValueError("LAMBDA_CLOUD_API_KEY is required")
        
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = requests.get(self.URL, headers=headers, timeout=30)
        response.raise_for_status()
        return Snapshot(
            name="lambda_instance_types",
            source_url=self.URL,
            body=response.text,
        )

    def extract(self, snapshot: Snapshot, run_id: str, scraped_at: str) -> list[DatasetRecord]:
        data = json.loads(snapshot.body)
        instance_types = data.get("data", {})
        snapshot_ts = scraped_at

        records = []
        for name, details in instance_types.items():
            instance_config = details.get("instance_type", {})
            gpu_config = instance_config.get("specs", {})
            
            # Lambda Cloud doesn't explicitly return region in instance-types yet, 
            # but availability is often tied to regions in other endpoints.
            # We'll store what we have.
            records.append(
                DatasetRecord(
                    dataset_id="raw_lambda_instance_types",
                    source_url=self.URL,
                    source_run_id=run_id,
                    scraped_at=scraped_at,
                    snapshot_ts=snapshot_ts,
                    instance_type_name=name,
                    gpu_type=gpu_config.get("vram_type") or name.split(".")[0],
                    gpu_count=float(gpu_config.get("gpus")) if gpu_config.get("gpus") else None,
                    region="global", # Default as it's a global catalog
                )
            )
        return records
