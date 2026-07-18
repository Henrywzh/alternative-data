from __future__ import annotations

from pathlib import Path

import pandas as pd

from dashboard.sections.openrouter import (
    _catalog_alias_map,
    _combine_explorer_activity,
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


def test_model_activity_precedes_provider_fallback_for_same_model_day() -> None:
    aliases = {"openai/gpt-test": "openai/gpt-test"}
    provider = _normalize_explorer_activity(pd.DataFrame([
        {"usage_date": "2026-07-15", "model_permaslug": "openai/gpt-test", "total_tokens": 100},
        {"usage_date": "2026-07-16", "model_permaslug": "openai/gpt-test", "total_tokens": 200},
        {"usage_date": "2026-07-17", "model_permaslug": "openai/gpt-test", "total_tokens": 300},
    ]), aliases)
    detail = _normalize_explorer_activity(pd.DataFrame([
        {
            "usage_date": "2026-07-16", "model_permaslug": "openai/gpt-test",
            "category_slug": "all", "total_tokens": 150, "request_count": 10,
        },
        {
            "usage_date": "2026-07-17", "model_permaslug": "openai/gpt-test",
            "category_slug": "programming", "total_tokens": 25, "request_count": 2,
        },
    ]), aliases)

    combined = _combine_explorer_activity(provider, detail)
    by_date = combined.groupby("usage_date_dt").agg(
        tokens=("total_tokens", "sum"), source=("activity_source", "first"),
    )
    assert by_date.loc[pd.Timestamp("2026-07-15"), "tokens"] == 100
    assert by_date.loc[pd.Timestamp("2026-07-15"), "source"] == "Provider fallback"
    assert by_date.loc[pd.Timestamp("2026-07-16"), "tokens"] == 150
    assert by_date.loc[pd.Timestamp("2026-07-16"), "source"] == "Model activity"
    assert by_date.loc[pd.Timestamp("2026-07-17"), "tokens"] == 300
    assert by_date.loc[pd.Timestamp("2026-07-17"), "source"] == "Provider fallback"


def test_free_variant_is_not_collapsed_into_paid_model_activity() -> None:
    catalog = _prepare_explorer_catalog(pd.DataFrame([
        {
            "model_id": "tencent/hy3",
            "canonical_slug": "tencent/hy3-20260706",
            "model_name": "Tencent: Hy3",
            "provider_prefix": "tencent",
            "created_at": 1_783_000_000,
            "context_length": 262144,
            "architecture": "text->text",
            "pricing_prompt": 0.0000002,
            "pricing_completion": 0.0000008,
        },
        {
            "model_id": "tencent/hy3:free",
            "canonical_slug": "tencent/hy3-20260706",
            "model_name": "Tencent: Hy3 (free)",
            "provider_prefix": "tencent",
            "created_at": 1_783_000_000,
            "context_length": 262144,
            "architecture": "text->text",
            "pricing_prompt": 0.0,
            "pricing_completion": 0.0,
        },
    ]))
    aliases = _catalog_alias_map(catalog)
    assert aliases["tencent/hy3-20260706"] == "tencent/hy3"
    assert aliases["tencent/hy3-20260706:free"] == "tencent/hy3:free"

    provider = _normalize_explorer_activity(pd.DataFrame([
        {
            "usage_date": "2026-07-16",
            "model_permaslug": "tencent/hy3-20260706",
            "entity_id": "tencent",
            "total_tokens": 100,
        },
        {
            "usage_date": "2026-07-16",
            "model_permaslug": "tencent/hy3-20260706:free",
            "entity_id": "tencent",
            "total_tokens": 900,
        },
    ]), aliases)
    detail = _normalize_explorer_activity(pd.DataFrame([
        {
            "usage_date": "2026-07-16",
            "model_permaslug": "tencent/hy3-20260706",
            "category_slug": "all",
            "total_tokens": 80,
            "request_count": 10,
        },
    ]), aliases)

    combined = _combine_explorer_activity(provider, detail)
    assert combined.groupby("model_id")["total_tokens"].sum().to_dict() == {
        "tencent/hy3": 80,
        "tencent/hy3:free": 900,
    }


def test_openrouter_latest_aliases_group_under_underlying_company() -> None:
    catalog = _prepare_explorer_catalog(pd.DataFrame([{
        "model_id": "~anthropic/claude-opus-latest",
        "canonical_slug": "~anthropic/claude-opus-latest",
        "model_name": "Anthropic: Claude Opus Latest",
        "provider_prefix": "~anthropic",
        "created_at": 1_782_864_000,
        "context_length": 200_000,
        "architecture": "text->text",
        "pricing_prompt": 0.000005,
        "pricing_completion": 0.000025,
    }]))

    row = catalog.iloc[0]
    assert row["provider_slug"] == "anthropic"
    assert row["company"] == "Anthropic"
    assert row["model_type"] == "OpenRouter latest alias"


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
