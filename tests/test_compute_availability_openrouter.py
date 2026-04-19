from __future__ import annotations

import json
from pathlib import Path

from compute_availability_data.models import Snapshot
from compute_availability_data.sources.openrouter import OpenRouterSource
from compute_availability_data.storage import StorageManager


def test_openrouter_extract_persists_canonical_slug_and_provider_prefix() -> None:
    source = OpenRouterSource()
    snapshot = Snapshot(
        name="openrouter_models",
        source_url=source.URL,
        body=json.dumps(
            {
                "data": [
                    {
                        "id": "qwen/qwen3.5-flash-02-23",
                        "canonical_slug": "qwen/qwen3.5-flash-20260224",
                        "name": "Qwen 3.5 Flash",
                        "created": 1710000000,
                        "context_length": 1_000_000,
                        "architecture": {"modality": "text"},
                        "pricing": {"prompt": "0.000000065", "completion": "0.00000026"},
                        "top_provider": {"id": "alibaba"},
                    }
                ]
            }
        ),
    )

    records = source.extract(snapshot, run_id="run-1", scraped_at="2026-04-20T00:00:00Z")

    assert len(records) == 1
    record = records[0]
    assert record.model_id == "qwen/qwen3.5-flash-02-23"
    assert record.canonical_slug == "qwen/qwen3.5-flash-20260224"
    assert record.provider_prefix == "qwen"


def test_storage_round_trips_openrouter_identity_columns(tmp_path: Path) -> None:
    source = OpenRouterSource()
    snapshot = Snapshot(
        name="openrouter_models",
        source_url=source.URL,
        body=json.dumps(
            {
                "data": [
                    {
                        "id": "moonshotai/kimi-k2.5",
                        "canonical_slug": "moonshotai/kimi-k2.5-0127",
                        "name": "Kimi K2.5",
                        "created": 1710000000,
                        "context_length": 262144,
                        "architecture": {"modality": "text"},
                        "pricing": {"prompt": "0.0000006", "completion": "0.000003"},
                        "top_provider": {"id": "moonshot"},
                    }
                ]
            }
        ),
    )
    records = source.extract(snapshot, run_id="run-1", scraped_at="2026-04-20T00:00:00Z")

    storage = StorageManager(tmp_path)
    storage.upsert_dataset("raw_openrouter_models", records)
    loaded = storage.load_dataset("raw_openrouter_models")

    row = loaded.iloc[0]
    assert row["model_id"] == "moonshotai/kimi-k2.5"
    assert row["canonical_slug"] == "moonshotai/kimi-k2.5-0127"
    assert row["provider_prefix"] == "moonshotai"
