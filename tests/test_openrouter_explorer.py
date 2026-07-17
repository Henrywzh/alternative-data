from __future__ import annotations

from pathlib import Path

import pandas as pd

from dashboard.sections.openrouter import (
    _catalog_alias_map,
    _normalize_explorer_activity,
    _prepare_explorer_catalog,
    company_explorer_state,
    model_explorer_state,
)
from openrouter_data.models import DatasetRecord
from openrouter_data.storage import StorageManager


def _catalog() -> pd.DataFrame:
    return _prepare_explorer_catalog(pd.DataFrame([
        {
            "model_id": "openai/gpt-test",
            "canonical_slug": "openai/gpt-test-20260701",
            "model_name": "OpenAI: GPT Test",
            "provider_prefix": "openai",
            "created_at": 1_782_864_000,
            "context_length": 1_048_576,
            "architecture": "text->text",
            "pricing_prompt": 0.000001,
            "pricing_completion": 0.000006,
        },
        {
            "model_id": "anthropic/claude-test",
            "canonical_slug": "anthropic/claude-test-20260601",
            "model_name": "Anthropic: Claude Test",
            "provider_prefix": "anthropic",
            "created_at": 1_780_272_000,
            "context_length": 200_000,
            "architecture": "text->text",
            "pricing_prompt": 0.000003,
            "pricing_completion": 0.000015,
        },
    ]))


def test_company_and_model_explorer_states_join_catalog_activity_and_apps() -> None:
    catalog = _catalog()
    aliases = _catalog_alias_map(catalog)
    provider_activity = _normalize_explorer_activity(pd.DataFrame([
        {"usage_date": "2026-07-15", "model_permaslug": "openai/gpt-test-20260701", "entity_id": "openai", "total_tokens": 100},
        {"usage_date": "2026-07-16", "model_permaslug": "openai/gpt-test-20260701", "entity_id": "openai", "total_tokens": 150},
    ]), aliases)
    model_activity = _normalize_explorer_activity(pd.DataFrame([
        {
            "usage_date": "2026-07-16", "model_permaslug": "openai/gpt-test-20260701",
            "category_slug": "programming", "total_tokens": 80, "request_count": 12,
        },
        {
            "usage_date": "2026-07-16", "model_permaslug": "openai/gpt-test-20260701",
            "category_slug": "roleplay", "total_tokens": 70, "request_count": 8,
        },
    ]), aliases)
    app_usage = _normalize_explorer_activity(pd.DataFrame([
        {
            "usage_date": "2026-07-16", "model_permaslug": "openai/gpt-test-20260701",
            "app_id": "app-1", "app_name": "Example App", "total_tokens": 50,
        }
    ]), aliases)
    catalog["tokens_30d"] = [250.0, 0.0]
    views = {
        "catalog": catalog,
        "provider_activity": provider_activity,
        "model_activity": model_activity,
        "app_usage": app_usage,
        "app_metadata": pd.DataFrame([{
            "app_id": "app-1", "scrape_date": "2026-07-16",
            "origin_url": "https://example.test", "categories": "coding",
        }]),
    }

    company = company_explorer_state(views, "openai")
    assert company["total_tokens"] == 250
    assert list(company["catalog"]["model_id"]) == ["openai/gpt-test"]
    assert company["model_pivot"].sum().sum() == 250

    model = model_explorer_state(views, "openai/gpt-test")
    assert model["activity"].loc[pd.Timestamp("2026-07-16"), "Tokens"] == 150
    assert model["activity"].loc[pd.Timestamp("2026-07-16"), "Requests"] == 20
    assert set(model["categories"]["category_slug"]) == {"programming", "roleplay"}
    assert model["apps"].iloc[0]["App"] == "Example App"


def test_model_activity_storage_is_parquet_only_and_retains_180_days(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    common = {
        "dataset_id": "openrouter_model_activity",
        "source_url": "https://openrouter.ai/openai/gpt-test/activity",
        "source_run_id": "run-1",
        "scraped_at": "2026-07-16T00:00:00Z",
        "model_permaslug": "openai/gpt-test",
        "category_slug": "programming",
        "total_tokens": 100,
        "request_count": 10,
    }
    records = [
        DatasetRecord(**common, usage_date="2025-12-01"),
        DatasetRecord(**common, usage_date="2026-07-16"),
    ]

    stored = storage.upsert_dataset("openrouter_model_activity", records)

    assert stored["usage_date"].tolist() == ["2026-07-16"]
    root = tmp_path / "data" / "normalized" / "openrouter"
    assert (root / "openrouter_model_activity.parquet").exists()
    assert not (root / "openrouter_model_activity.csv").exists()
