from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from openrouter_data.models import DatasetRecord, RunContext, Snapshot
from openrouter_data.pipeline import ActivityPipeline
from openrouter_data.sources.activity import ActivitySource
from openrouter_data.sources.provider_activity import ProviderActivitySource
from openrouter_data.storage import StorageManager


def _make_next_f_script(label: str, payload: list) -> str:
    encoded = json.dumps(f"{label}:{json.dumps(payload, separators=(',', ':'))}")
    return f"<script>self.__next_f.push([1,{encoded}])</script>"


def _build_activity_html(items: list[dict]) -> str:
    payload = [
        "$",
        "$L53",
        None,
        {
            "slug": "anthropic/claude-opus-4.7",
            "categories": items,
        },
    ]
    return f"<html><body>{_make_next_f_script('44', payload)}</body></html>"


def test_activity_source_extracts_requests_prompt_completion_and_reasoning_tokens() -> None:
    html = _build_activity_html(
        [
            {
                "date": "2026-04-24",
                "model": "anthropic/claude-opus-4.7",
                "category": "programming",
                "count": 123,
                "total_prompt_tokens": 1000,
                "total_completion_tokens": 250,
                "total_reasoning_tokens": 75,
            }
        ]
    )
    source = ActivitySource()
    context = RunContext(run_id="activity-test", scraped_at=pd.Timestamp("2026-04-24T00:00:00Z").to_pydatetime())

    extracted = source.extract(
        [Snapshot(name="activity", source_url="fixture://anthropic/claude-opus-4.7/activity", body=html)],
        context,
    )

    records = extracted["openrouter_model_activity"]
    assert len(records) == 1
    record = records[0]
    assert record.request_count == 123
    assert record.prompt_tokens == 1000.0
    assert record.completion_tokens == 250.0
    assert record.reasoning_tokens == 75.0
    assert record.total_tokens == 1250.0


def test_activity_source_leaves_reasoning_tokens_null_when_missing() -> None:
    html = _build_activity_html(
        [
            {
                "date": "2026-04-24",
                "model": "anthropic/claude-opus-4.7",
                "category": "general",
                "count": 55,
                "total_prompt_tokens": 900,
                "total_completion_tokens": 100,
            }
        ]
    )
    source = ActivitySource()
    context = RunContext(run_id="activity-test", scraped_at=pd.Timestamp("2026-04-24T00:00:00Z").to_pydatetime())

    extracted = source.extract(
        [Snapshot(name="activity", source_url="fixture://anthropic/claude-opus-4.7/activity", body=html)],
        context,
    )

    record = extracted["openrouter_model_activity"][0]
    assert record.reasoning_tokens is None
    assert record.total_tokens == 1000.0


def test_openrouter_model_activity_storage_roundtrips_reasoning_tokens(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)

    records = [
        DatasetRecord(
            dataset_id="openrouter_model_activity",
            source_url="fixture://activity",
            source_run_id="run-1",
            scraped_at="2026-04-24T00:00:00Z",
            usage_date="2026-04-24",
            model_permaslug="anthropic/claude-opus-4.7",
            category_slug="programming",
            request_count=123,
            prompt_tokens=1000.0,
            completion_tokens=250.0,
            reasoning_tokens=75.0,
            total_tokens=1250.0,
        )
    ]

    written = storage.upsert_dataset("openrouter_model_activity", records)

    assert "reasoning_tokens" in written.columns
    assert float(written.loc[0, "reasoning_tokens"]) == 75.0

    loaded = storage.load_dataset("openrouter_model_activity")
    assert "reasoning_tokens" in loaded.columns
    assert float(loaded.loc[0, "reasoning_tokens"]) == 75.0


def test_provider_activity_source_still_emits_total_tokens_only() -> None:
    payload = [
        "$",
        "$L53",
        None,
        {
            "data": [
                {"x": "2026-04-20 00:00:00", "ys": {"anthropic/claude-opus-4.7": 12000}},
                {"x": "2026-04-21 00:00:00", "ys": {"anthropic/claude-opus-4.7": 12100}},
                {"x": "2026-04-22 00:00:00", "ys": {"anthropic/claude-opus-4.7": 12200}},
                {"x": "2026-04-23 00:00:00", "ys": {"anthropic/claude-opus-4.7": 12300}},
                {"x": "2026-04-24 00:00:00", "ys": {"anthropic/claude-opus-4.7": 12345}},
            ],
        },
    ]
    html = f"<html><body>{_make_next_f_script('44', payload)}</body></html>"
    source = ProviderActivitySource()
    context = RunContext(run_id="provider-activity-test", scraped_at=pd.Timestamp("2026-04-24T00:00:00Z").to_pydatetime())

    extracted = source.extract(
        [Snapshot(name="provider_anthropic", source_url="fixture://anthropic", body=html)],
        context,
    )

    records = extracted["provider_daily_activity"]
    assert len(records) == 5
    record = next(record for record in records if record.usage_date == "2026-04-24")
    assert record.total_tokens == 12345.0
    assert record.prompt_tokens == 0.0
    assert record.completion_tokens == 0.0
    assert record.request_count is None


def test_activity_pipeline_discovers_major_provider_slugs_from_catalog(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "data" / "normalized" / "compute_availability"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "model_id": "anthropic/claude-opus-4.7",
                "canonical_slug": "anthropic/claude-opus-4.7",
                "provider_prefix": "anthropic",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
            {
                "model_id": "x-ai/grok-4-fast",
                "canonical_slug": "x-ai/grok-4-fast",
                "provider_prefix": "x-ai",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
            {
                "model_id": "nvidia/llama-3.1-nemotron",
                "canonical_slug": "nvidia/llama-3.1-nemotron",
                "provider_prefix": "nvidia",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
        ]
    ).to_csv(catalog_dir / "raw_openrouter_models.csv", index=False)

    pipeline = ActivityPipeline(tmp_path)
    slugs = pipeline._discover_catalog_slugs()

    assert slugs == ["anthropic/claude-opus-4.7", "x-ai/grok-4-fast"]


def test_activity_pipeline_unions_recent_partial_catalog_snapshots(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "data" / "normalized" / "compute_availability"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "model_id": "moonshotai/kimi-k2.6",
                "canonical_slug": "moonshotai/kimi-k2.6-20260420",
                "provider_prefix": "moonshotai",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
            {
                "model_id": "deepseek/deepseek-v4-pro",
                "canonical_slug": "deepseek/deepseek-v4-pro-20260423",
                "provider_prefix": "deepseek",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
            {
                "model_id": "openai/gpt-5.5",
                "canonical_slug": "openai/gpt-5.5-20260423",
                "provider_prefix": "openai",
                "snapshot_ts": "2026-04-25T00:00:00Z",
            },
        ]
    ).to_csv(catalog_dir / "raw_openrouter_models.csv", index=False)

    pipeline = ActivityPipeline(tmp_path)
    slugs = pipeline._discover_catalog_slugs()

    assert slugs == [
        "moonshotai/kimi-k2.6-20260420",
        "deepseek/deepseek-v4-pro-20260423",
        "openai/gpt-5.5-20260423",
    ]


def test_activity_pipeline_prefers_live_catalog_and_keeps_recent_local_releases(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "data" / "normalized" / "compute_availability"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "model_id": "moonshotai/kimi-k2.6",
                "canonical_slug": "moonshotai/kimi-k2.6-20260420",
                "provider_prefix": "moonshotai",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
            {
                "model_id": "deepseek/deepseek-v4-flash",
                "canonical_slug": "deepseek/deepseek-v4-flash-20260423",
                "provider_prefix": "deepseek",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
        ]
    ).to_csv(catalog_dir / "raw_openrouter_models.csv", index=False)

    pipeline = ActivityPipeline(tmp_path)
    pipeline.source.fetch_catalog_slugs = lambda limit=0: ["openai/gpt-5.5-20260423", "nvidia/not-allowed"]

    slugs = pipeline._discover_activity_slugs()

    assert slugs == [
        "openai/gpt-5.5-20260423",
        "moonshotai/kimi-k2.6-20260420",
        "deepseek/deepseek-v4-flash-20260423",
    ]
