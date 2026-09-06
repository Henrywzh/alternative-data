from __future__ import annotations

import json
import sys
from pathlib import Path
import tomllib

import pandas as pd
import pytest

from dashboard import data as dashboard_data
from openrouter_revenue import (
    build_conservative_provider_economics,
    build_provider_revenue_estimates,
    estimate_usage_revenue,
)
from pricing_model_aliases import generate_candidate_aliases
from research_data.api import monthly_model_releases, provider_revenue_daily
from research_data.cli import main as research_cli_main
from research_data.catalog import catalog
from research_data.marts import (
    build_daily_provider_economics,
    build_frontier_model_registry,
    build_weekly_openrouter_usage,
    mart_paths,
)


def _normalized_dir(base_dir: Path, dataset_id: str) -> Path:
    domain = dashboard_data.DATASET_REGISTRY[dataset_id]["domain"]
    source = dashboard_data.dataset_source_for_domain(str(domain))
    root = base_dir / "data" / "normalized" / source
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_dataset(base_dir: Path, dataset_id: str, rows: list[dict[str, object]]) -> None:
    frame = pd.DataFrame(rows)
    root = _normalized_dir(base_dir, dataset_id)
    frame.to_csv(root / f"{dataset_id}.csv", index=False)


def _seed_research_inputs(base_dir: Path) -> None:
    _write_dataset(
        base_dir,
        "top_models",
        [
            {
                "dataset_id": "top_models",
                "source_url": "https://openrouter.ai/rankings",
                "source_run_id": "run-1",
                "scraped_at": "2026-04-18T00:00:00Z",
                "week_start_date": "2026-04-07",
                "entity_id": "openai/gpt-4.1",
                "entity_name": "openai/gpt-4.1",
                "parent_entity_id": "openai",
                "parent_entity_name": "OpenAI",
                "metric_name": "tokens",
                "metric_unit": "tokens",
                "metric_value": 1000.0,
                "rank": 1,
                "category_slug": None,
            },
            {
                "dataset_id": "top_models",
                "source_url": "https://openrouter.ai/rankings",
                "source_run_id": "run-1",
                "scraped_at": "2026-04-18T00:00:00Z",
                "week_start_date": "2026-04-14",
                "entity_id": "anthropic/claude-sonnet-4",
                "entity_name": "anthropic/claude-sonnet-4",
                "parent_entity_id": "anthropic",
                "parent_entity_name": "Anthropic",
                "metric_name": "tokens",
                "metric_unit": "tokens",
                "metric_value": 1500.0,
                "rank": 1,
                "category_slug": None,
            },
        ],
    )
    _write_dataset(
        base_dir,
        "market_share",
        [
            {
                "dataset_id": "market_share",
                "source_url": "https://openrouter.ai/rankings",
                "source_run_id": "run-1",
                "scraped_at": "2026-04-18T00:00:00Z",
                "week_start_date": "2026-04-07",
                "entity_id": "openai",
                "entity_name": "OpenAI",
                "parent_entity_id": None,
                "parent_entity_name": None,
                "metric_name": "token_share_pct",
                "metric_unit": "share",
                "metric_value": 60.0,
                "rank": 1,
                "category_slug": None,
            }
        ],
    )
    _write_dataset(
        base_dir,
        "categories_programming",
        [
            {
                "dataset_id": "categories_programming",
                "source_url": "https://openrouter.ai/rankings/programming",
                "source_run_id": "run-1",
                "scraped_at": "2026-04-18T00:00:00Z",
                "week_start_date": "2026-04-14",
                "entity_id": "openai/gpt-4.1",
                "entity_name": "openai/gpt-4.1",
                "parent_entity_id": "openai",
                "parent_entity_name": "OpenAI",
                "metric_name": "tokens",
                "metric_unit": "tokens",
                "metric_value": 750.0,
                "rank": 1,
                "category_slug": "programming",
            }
        ],
    )
    _write_dataset(
        base_dir,
        "provider_daily_activity",
        [
            {
                "dataset_id": "provider_daily_activity",
                "source_url": "https://openrouter.ai/openai",
                "source_run_id": "run-2",
                "scraped_at": "2026-04-18T00:00:00Z",
                "entity_id": "openai",
                "entity_name": "OpenAI",
                "usage_date": "2026-04-16",
                "model_permaslug": "openai/gpt-4.1",
                "total_tokens": 100.0,
                "prompt_tokens": 60.0,
                "completion_tokens": 40.0,
            },
            {
                "dataset_id": "provider_daily_activity",
                "source_url": "https://openrouter.ai/openai",
                "source_run_id": "run-2",
                "scraped_at": "2026-04-18T00:00:00Z",
                "entity_id": "openai",
                "entity_name": "OpenAI",
                "usage_date": "2026-04-16",
                "model_permaslug": "unknown/model",
                "total_tokens": 50.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            },
            {
                "dataset_id": "provider_daily_activity",
                "source_url": "https://openrouter.ai/openai",
                "source_run_id": "run-2",
                "scraped_at": "2026-04-18T00:00:00Z",
                "entity_id": "openai",
                "entity_name": "OpenAI",
                "usage_date": "2026-04-16",
                "model_permaslug": "openai/gpt-5.4-20260305",
                "total_tokens": 200.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            },
            {
                "dataset_id": "provider_daily_activity",
                "source_url": "https://openrouter.ai/anthropic",
                "source_run_id": "run-2",
                "scraped_at": "2026-04-18T00:00:00Z",
                "entity_id": "anthropic",
                "entity_name": "Anthropic",
                "usage_date": "2026-04-16",
                "model_permaslug": "anthropic/claude-4.6-sonnet-20260217",
                "total_tokens": 100.0,
                "prompt_tokens": 60.0,
                "completion_tokens": 40.0,
            },
            {
                "dataset_id": "provider_daily_activity",
                "source_url": "https://openrouter.ai/qwen",
                "source_run_id": "run-2",
                "scraped_at": "2026-04-18T00:00:00Z",
                "entity_id": "qwen",
                "entity_name": "Qwen",
                "usage_date": "2026-04-16",
                "model_permaslug": "qwen/qwen3.5-flash-20260224",
                "total_tokens": 300.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            },
            {
                "dataset_id": "provider_daily_activity",
                "source_url": "https://openrouter.ai/openai",
                "source_run_id": "run-2",
                "scraped_at": "2026-04-18T00:00:00Z",
                "entity_id": "openai",
                "entity_name": "OpenAI",
                "usage_date": "2026-04-16",
                "model_permaslug": "openai/new-unpriced-model",
                "total_tokens": 80.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            },
            {
                "dataset_id": "provider_daily_activity",
                "source_url": "https://openrouter.ai/xiaomi",
                "source_run_id": "run-2",
                "scraped_at": "2026-04-18T00:00:00Z",
                "entity_id": "xiaomi",
                "entity_name": "Xiaomi",
                "usage_date": "2026-04-16",
                "model_permaslug": "xiaomi/missing-model",
                "total_tokens": 90.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            },
            {
                "dataset_id": "provider_daily_activity",
                "source_url": "https://openrouter.ai/openai",
                "source_run_id": "run-2",
                "scraped_at": "2026-04-18T00:00:00Z",
                "entity_id": "openai",
                "entity_name": "OpenAI",
                "usage_date": "2026-04-16",
                "model_permaslug": "Others",
                "total_tokens": 70.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            },
        ],
    )
    _write_dataset(
        base_dir,
        "raw_openrouter_models",
        [
            {
                "dataset_id": "raw_openrouter_models",
                "source_url": "https://openrouter.ai/api/v1/models",
                "source_run_id": "run-3",
                "scraped_at": "2026-04-15T12:00:00Z",
                "snapshot_ts": "2026-04-15T12:00:00Z",
                "model_id": "openai/gpt-4.1",
                "canonical_slug": "openai/gpt-4.1",
                "model_name": "OpenAI GPT-4.1",
                "context_length": 131072,
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
                "provider_prefix": "openai",
            },
            {
                "dataset_id": "raw_openrouter_models",
                "source_url": "https://openrouter.ai/api/v1/models",
                "source_run_id": "run-3",
                "scraped_at": "2026-04-17T12:00:00Z",
                "snapshot_ts": "2026-04-17T12:00:00Z",
                "model_id": "openai/gpt-4.1",
                "canonical_slug": "openai/gpt-4.1",
                "model_name": "OpenAI GPT-4.1",
                "context_length": 262144,
                "pricing_prompt": 0.010,
                "pricing_completion": 0.020,
                "provider_prefix": "openai",
            },
            {
                "dataset_id": "raw_openrouter_models",
                "source_url": "https://openrouter.ai/api/v1/models",
                "source_run_id": "run-3",
                "scraped_at": "2026-04-15T12:00:00Z",
                "snapshot_ts": "2026-04-15T12:00:00Z",
                "model_id": "openai/gpt-5.4",
                "canonical_slug": "openai/gpt-5.4-20260305",
                "model_name": "OpenAI GPT-5.4",
                "context_length": 262144,
                "pricing_prompt": 0.003,
                "pricing_completion": 0.009,
                "provider_prefix": "openai",
            },
            {
                "dataset_id": "raw_openrouter_models",
                "source_url": "https://openrouter.ai/api/v1/models",
                "source_run_id": "run-3",
                "scraped_at": "2026-04-15T12:00:00Z",
                "snapshot_ts": "2026-04-15T12:00:00Z",
                "model_id": "anthropic/claude-sonnet-4.6",
                "canonical_slug": "anthropic/claude-4.6-sonnet-20260217",
                "model_name": "Claude Sonnet 4.6",
                "context_length": 200000,
                "pricing_prompt": 0.004,
                "pricing_completion": 0.008,
                "provider_prefix": "anthropic",
            },
            {
                "dataset_id": "raw_openrouter_models",
                "source_url": "https://openrouter.ai/api/v1/models",
                "source_run_id": "run-3",
                "scraped_at": "2026-04-15T12:00:00Z",
                "snapshot_ts": "2026-04-15T12:00:00Z",
                "model_id": "qwen/qwen3.5-flash-02-23",
                "canonical_slug": "qwen/qwen3.5-flash-20260224",
                "model_name": "Qwen 3.5 Flash",
                "context_length": 1000000,
                "pricing_prompt": 0.000000065,
                "pricing_completion": 0.00000026,
                "provider_prefix": "qwen",
            },
        ],
    )
    _write_dataset(
        base_dir,
        "llm_benchmarks",
        [
            {
                "dataset_id": "llm_benchmarks",
                "source_url": "https://example.com/benchmarks",
                "source_run_id": "run-4",
                "scraped_at": "2026-04-18T00:00:00Z",
                "model_id": "openai/gpt-4.1",
                "name": "GPT-4.1",
                "organization": "OpenAI",
                "release_date": "2026-04-01",
                "context_window": 131072,
                "gpqa": 0.95,
                "swe_bench": 0.72,
            },
            {
                "dataset_id": "llm_benchmarks",
                "source_url": "https://example.com/benchmarks",
                "source_run_id": "run-4",
                "scraped_at": "2026-04-18T00:00:00Z",
                "model_id": "anthropic/claude-sonnet-4",
                "name": "Claude Sonnet 4",
                "organization": "Anthropic",
                "release_date": "2026-04-10",
                "context_window": 32000,
                "gpqa": 0.20,
                "swe_bench": 0.15,
            },
            {
                "dataset_id": "llm_benchmarks",
                "source_url": "https://example.com/benchmarks",
                "source_run_id": "run-4",
                "scraped_at": "2026-04-18T00:00:00Z",
                "model_id": "moonshot/kimi-lite",
                "name": "Kimi Lite",
                "organization": "Moonshot",
                "release_date": "2026-04-12",
                "context_window": 16000,
                "gpqa": 0.10,
                "swe_bench": 0.05,
            },
        ],
    )
    _write_dataset(
        base_dir,
        "huggingface_models_daily",
        [
            {
                "dataset_id": "huggingface_models_daily",
                "source_url": "https://huggingface.co/api/models",
                "source_run_id": "run-5",
                "scraped_at": "2026-04-18T00:00:00Z",
                "provider": "openai",
                "provider_display_name": "OpenAI",
                "author": "openai",
                "model_id": "openai/gpt-4.1",
                "download_date": "2026-04-17",
                "hf_downloads_daily_est": 42.0,
                "hf_downloads_all_time": 1000.0,
            }
        ],
    )
    manifest_dir = base_dir / "data" / "raw" / "openrouter" / "20260418T000000Z-test"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "manifest.json").write_text(
        json.dumps({"run_id": "20260418T000000Z-test", "scraped_at": "2026-04-18T00:00:00Z"}),
        encoding="utf-8",
    )


def test_catalog_includes_source_metadata(tmp_path: Path) -> None:
    _seed_research_inputs(tmp_path)

    result = catalog(base_dir=tmp_path)

    top_models_row = result[result["dataset_id"] == "top_models"].iloc[0]
    assert top_models_row["domain"] == "rankings"
    assert top_models_row["row_count"] == 2
    assert top_models_row["first_date"] == "2026-04-07"
    assert top_models_row["latest_date"] == "2026-04-14"
    assert top_models_row["source_path"].endswith("top_models.csv")
    assert top_models_row["latest_manifest_run_id"] == "20260418T000000Z-test"


def test_build_weekly_openrouter_usage_standardizes_rankings_tables(tmp_path: Path) -> None:
    _seed_research_inputs(tmp_path)

    mart = build_weekly_openrouter_usage(base_dir=tmp_path, refresh=True)

    assert set(mart["dataset_source"]) == {"top_models", "market_share", "categories_programming"}
    assert {"week_start_date", "dataset_source", "entity_type", "entity_id", "metric_value", "category_slug"} <= set(
        mart.columns
    )
    assert mart[mart["dataset_source"] == "market_share"]["entity_type"].eq("author").all()


def test_build_daily_provider_economics_uses_latest_prior_snapshot_and_marks_missing(tmp_path: Path) -> None:
    _seed_research_inputs(tmp_path)

    mart = build_daily_provider_economics(base_dir=tmp_path, refresh=True)

    matched = mart[mart["model_permaslug"] == "openai/gpt-4.1"].iloc[0]
    assert matched["pricing_snapshot_ts"] == "2026-04-15T12:00:00Z"
    assert matched["pricing_join_status"] == "matched_asof"
    assert matched["revenue_method"] == "exact_split_priced"
    assert matched["estimated_revenue"] == pytest.approx(0.14)

    missing = mart[mart["model_permaslug"] == "unknown/model"].iloc[0]
    assert missing["pricing_join_status"] == "unresolved_missing_pricing"
    assert missing["revenue_method"] == "unpriced"
    assert pd.isna(missing["estimated_revenue"])


def test_build_conservative_economics_forward_fills_target_routes_with_explicit_status() -> None:
    activity = pd.DataFrame([
        {
            "usage_date": "2026-01-16",
            "entity_id": "x-ai",
            "entity_name": "xAI",
            "model_permaslug": "x-ai/grok-4.5-20260708",
            "total_tokens": 100.0,
            "prompt_tokens": 70.0,
            "completion_tokens": 30.0,
        },
        {
            "usage_date": "2026-01-16",
            "entity_id": "openai",
            "entity_name": "OpenAI",
            "model_permaslug": "openai/gpt-5.4-20260305",
            "total_tokens": 100.0,
            "prompt_tokens": 70.0,
            "completion_tokens": 30.0,
        },
        {
            "usage_date": "2026-01-16",
            "entity_id": "openai",
            "entity_name": "OpenAI",
            "model_permaslug": "openai/unknown-model",
            "total_tokens": 100.0,
            "prompt_tokens": 70.0,
            "completion_tokens": 30.0,
        },
    ])
    pricing = pd.DataFrame([
        {
            "snapshot_ts": "2026-07-17T00:00:00Z",
            "model_id": "x-ai/grok-4.5",
            "canonical_slug": "x-ai/grok-4.5-20260708",
            "provider_prefix": "x-ai",
            "pricing_prompt": 0.000002,
            "pricing_completion": 0.000006,
        },
        {
            "snapshot_ts": "2026-07-17T00:00:00Z",
            "model_id": "openai/gpt-5.4",
            "canonical_slug": "openai/gpt-5.4-20260305",
            "provider_prefix": "openai",
            "pricing_prompt": 0.000001,
            "pricing_completion": 0.000003,
        },
    ])

    mart = build_conservative_provider_economics(activity, pricing)
    filled = mart[mart["model_permaslug"] == "x-ai/grok-4.5-20260708"].iloc[0]
    unresolved = mart[mart["model_permaslug"] == "openai/unknown-model"].iloc[0]

    assert filled["pricing_join_status"] == "historical_route_price_fill"
    assert filled["revenue_method"] == "historical_exact_split_priced"
    assert filled["pricing_snapshot_ts"] == "2026-07-17T00:00:00Z"
    assert filled["estimated_revenue"] == pytest.approx(0.00032)
    openai_filled = mart[mart["model_permaslug"] == "openai/gpt-5.4-20260305"].iloc[0]
    assert openai_filled["pricing_join_status"] == "historical_route_price_fill"
    assert openai_filled["revenue_method"] == "historical_exact_split_priced"
    assert openai_filled["pricing_snapshot_ts"] == "2026-07-17T00:00:00Z"
    assert openai_filled["estimated_revenue"] == pytest.approx(0.00016)
    assert unresolved["pricing_join_status"] == "unresolved_missing_pricing"
    assert pd.isna(unresolved["estimated_revenue"])


def test_build_daily_provider_economics_canonicalizes_model_ids(tmp_path: Path) -> None:
    _seed_research_inputs(tmp_path)

    mart = build_daily_provider_economics(base_dir=tmp_path, refresh=True)

    openai_row = mart[mart["model_permaslug"] == "openai/gpt-5.4-20260305"].iloc[0]
    assert openai_row["pricing_snapshot_ts"] == "2026-04-15T12:00:00Z"
    assert openai_row["pricing_join_status"] == "matched_asof"
    assert openai_row["revenue_method"] == "model_blended_no_split"
    assert openai_row["estimated_revenue"] == pytest.approx(0.6276)

    anthropic_row = mart[mart["model_permaslug"] == "anthropic/claude-4.6-sonnet-20260217"].iloc[0]
    assert anthropic_row["pricing_join_status"] == "matched_asof"
    assert anthropic_row["revenue_method"] == "exact_split_priced"
    assert anthropic_row["estimated_revenue"] == pytest.approx(0.56)

    qwen_row = mart[mart["model_permaslug"] == "qwen/qwen3.5-flash-20260224"].iloc[0]
    assert qwen_row["pricing_join_status"] == "matched_asof"
    assert qwen_row["revenue_method"] == "model_blended_no_split"
    assert qwen_row["estimated_revenue"] == pytest.approx(0.0000208455)


def test_provider_economics_combines_meta_and_meta_llama_under_meta() -> None:
    activity = pd.DataFrame([
        {
            "usage_date": "2026-07-20",
            "entity_id": "meta",
            "entity_name": "Meta",
            "model_permaslug": "meta/muse-spark",
            "total_tokens": 100.0,
            "prompt_tokens": 70.0,
            "completion_tokens": 30.0,
        },
        {
            "usage_date": "2026-07-20",
            "entity_id": "meta-llama",
            "entity_name": "Meta (Llama)",
            "model_permaslug": "meta-llama/llama-4",
            "total_tokens": 200.0,
            "prompt_tokens": 140.0,
            "completion_tokens": 60.0,
        },
    ])
    pricing = pd.DataFrame([
        {
            "snapshot_ts": "2026-07-20T00:00:00Z",
            "model_id": "meta/muse-spark",
            "canonical_slug": "meta/muse-spark",
            "provider_prefix": "meta",
            "pricing_prompt": 0.000001,
            "pricing_completion": 0.000003,
        },
        {
            "snapshot_ts": "2026-07-20T00:00:00Z",
            "model_id": "meta-llama/llama-4",
            "canonical_slug": "meta-llama/llama-4",
            "provider_prefix": "meta-llama",
            "pricing_prompt": 0.000001,
            "pricing_completion": 0.000003,
        },
    ])

    economics = build_conservative_provider_economics(activity, pricing)

    assert set(economics["provider_slug"]) == {"meta"}
    assert set(economics["provider_name"]) == {"Meta"}
    assert economics["total_tokens"].sum() == pytest.approx(300.0)


def test_build_daily_provider_economics_infers_split_tokens_from_model_activity(tmp_path: Path) -> None:
    _seed_research_inputs(tmp_path)
    _write_dataset(
        tmp_path,
        "provider_daily_activity",
        [
            {
                "dataset_id": "provider_daily_activity",
                "source_url": "https://openrouter.ai/openai",
                "source_run_id": "run-2",
                "scraped_at": "2026-04-18T00:00:00Z",
                "entity_id": "openai",
                "entity_name": "OpenAI",
                "usage_date": "2026-04-16",
                "model_permaslug": "openai/gpt-4.1",
                "total_tokens": 1000.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            }
        ],
    )
    _write_dataset(
        tmp_path,
        "openrouter_model_activity",
        [
            {
                "dataset_id": "openrouter_model_activity",
                "source_url": "https://openrouter.ai/openai/gpt-4.1/activity",
                "source_run_id": "run-4",
                "scraped_at": "2026-04-18T00:00:00Z",
                "usage_date": "2026-04-16",
                "model_permaslug": "openai/gpt-4.1",
                "category_slug": "programming",
                "prompt_tokens": 800.0,
                "completion_tokens": 200.0,
                "reasoning_tokens": 50.0,
                "total_tokens": 1000.0,
                "request_count": 100,
            }
        ],
    )

    mart = build_daily_provider_economics(base_dir=tmp_path, refresh=True)

    row = mart[mart["model_permaslug"] == "openai/gpt-4.1"].iloc[0]
    assert row["revenue_method"] == "model_split_inferred"
    assert row["split_source"] == "model_activity"
    assert row["prompt_tokens"] == pytest.approx(800.0)
    assert row["completion_tokens"] == pytest.approx(200.0)
    assert row["reasoning_tokens"] == pytest.approx(50.0)
    assert row["estimated_revenue"] == pytest.approx(1.2)


def test_build_daily_provider_economics_uses_base_alias_before_canonical_slug_exists(tmp_path: Path) -> None:
    _seed_research_inputs(tmp_path)

    _write_dataset(
        tmp_path,
        "provider_daily_activity",
        pd.concat(
            [
                pd.read_csv(_normalized_dir(tmp_path, "provider_daily_activity") / "provider_daily_activity.csv"),
                pd.DataFrame(
                    [
                        {
                            "dataset_id": "provider_daily_activity",
                            "source_url": "https://openrouter.ai/moonshotai",
                            "source_run_id": "run-2",
                            "scraped_at": "2026-04-18T00:00:00Z",
                            "entity_id": "moonshotai",
                            "entity_name": "Moonshot AI",
                            "usage_date": "2026-04-16",
                            "model_permaslug": "moonshotai/kimi-k2.5-0127",
                            "total_tokens": 1000.0,
                            "prompt_tokens": 0.0,
                            "completion_tokens": 0.0,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        ).to_dict(orient="records"),
    )
    _write_dataset(
        tmp_path,
        "raw_openrouter_models",
        pd.concat(
            [
                pd.read_csv(_normalized_dir(tmp_path, "raw_openrouter_models") / "raw_openrouter_models.csv"),
                pd.DataFrame(
                    [
                        {
                            "dataset_id": "raw_openrouter_models",
                            "source_url": "https://openrouter.ai/api/v1/models",
                            "source_run_id": "run-3",
                            "scraped_at": "2026-04-15T12:00:00Z",
                            "snapshot_ts": "2026-04-15T12:00:00Z",
                            "model_id": "moonshotai/kimi-k2.5",
                            "canonical_slug": pd.NA,
                            "model_name": "Kimi K2.5",
                            "context_length": 262144,
                            "pricing_prompt": 0.0000006,
                            "pricing_completion": 0.000003,
                            "provider_prefix": "moonshotai",
                        },
                        {
                            "dataset_id": "raw_openrouter_models",
                            "source_url": "https://openrouter.ai/api/v1/models",
                            "source_run_id": "run-3",
                            "scraped_at": "2026-04-19T12:00:00Z",
                            "snapshot_ts": "2026-04-19T12:00:00Z",
                            "model_id": "moonshotai/kimi-k2.5",
                            "canonical_slug": "moonshotai/kimi-k2.5-0127",
                            "model_name": "Kimi K2.5",
                            "context_length": 262144,
                            "pricing_prompt": 0.0000006,
                            "pricing_completion": 0.000003,
                            "provider_prefix": "moonshotai",
                        },
                    ]
                ),
            ],
            ignore_index=True,
        ).to_dict(orient="records"),
    )

    mart = build_daily_provider_economics(base_dir=tmp_path, refresh=True)

    kimi_row = mart[mart["model_permaslug"] == "moonshotai/kimi-k2.5-0127"].iloc[0]
    assert kimi_row["pricing_snapshot_ts"] == "2026-04-15T12:00:00Z"
    assert kimi_row["pricing_join_status"] == "matched_asof"
    assert kimi_row["revenue_method"] == "model_blended_no_split"
    assert kimi_row["estimated_revenue"] == pytest.approx(0.0006552)


def test_provider_revenue_daily_defaults_to_conservative_observed_estimate(tmp_path: Path) -> None:
    _seed_research_inputs(tmp_path)

    revenue = provider_revenue_daily(
        ["openai", "anthropic", "qwen", "xiaomi"],
        base_dir=tmp_path,
        refresh=True,
    )

    split_match = revenue[revenue["model_permaslug"] == "openai/gpt-4.1"].iloc[0]
    assert split_match["pricing_join_status"] == "matched_asof"
    assert split_match["revenue_method"] == "exact_split_priced"
    assert split_match["estimated_revenue"] == pytest.approx(0.14)

    blended_match = revenue[revenue["model_permaslug"] == "openai/gpt-5.4-20260305"].iloc[0]
    assert blended_match["pricing_join_status"] == "matched_asof"
    assert blended_match["revenue_method"] == "model_blended_no_split"
    assert blended_match["estimated_revenue"] == pytest.approx(0.6276)

    unpriced_provider = revenue[revenue["model_permaslug"] == "openai/new-unpriced-model"].iloc[0]
    assert unpriced_provider["pricing_join_status"] == "unresolved_missing_pricing"
    assert unpriced_provider["revenue_method"] == "unpriced"
    assert pd.isna(unpriced_provider["estimated_revenue"])

    unpriced_global = revenue[revenue["model_permaslug"] == "xiaomi/missing-model"].iloc[0]
    assert unpriced_global["pricing_join_status"] == "unresolved_missing_pricing"
    assert unpriced_global["revenue_method"] == "unpriced"
    assert pd.isna(unpriced_global["estimated_revenue"])

    qwen_row = revenue[revenue["model_permaslug"] == "qwen/qwen3.5-flash-20260224"].iloc[0]
    assert qwen_row["pricing_join_status"] == "matched_asof"
    assert qwen_row["revenue_method"] == "model_blended_no_split"
    assert qwen_row["estimated_revenue"] == pytest.approx(0.0000208455)

    synthetic = revenue[revenue["model_permaslug"] == "Others"].iloc[0]
    assert synthetic["pricing_join_status"] == "synthetic_unpriced"
    assert pd.isna(synthetic["estimated_revenue"])


def test_conservative_economics_breaks_pricing_ties_by_lowest_alias_priority() -> None:
    # Two different pricing model_ids can alias to the same lookup key at the
    # exact same snapshot_ts (e.g. a plain "provider/model" slug and a dated
    # "provider/model-20260101" variant that also strips down to "provider/
    # model"). The exact match (lowest alias_priority) must win, matching the
    # tie-break rule build_price_context and _forward_fill_target_route_pricing
    # already use elsewhere for this exact kind of ambiguity - not whichever
    # row an unrelated sort happens to leave last.
    provider_activity = pd.DataFrame(
        [
            {
                "usage_date": "2026-01-02",
                "entity_id": "testprovider",
                "entity_name": "TestProvider",
                "model_permaslug": "testprovider/base-model",
                "total_tokens": 1_000_000.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            }
        ]
    )
    pricing = pd.DataFrame(
        [
            {
                "snapshot_ts": "2026-01-01T00:00:00Z",
                "model_id": "testprovider/base-model-20260101",
                "canonical_slug": "testprovider/base-model-20260101",
                "provider_prefix": "testprovider",
                "pricing_prompt": 0.005,
                "pricing_completion": 0.006,
            },
            {
                "snapshot_ts": "2026-01-01T00:00:00Z",
                "model_id": "testprovider/base-model",
                "canonical_slug": "testprovider/base-model",
                "provider_prefix": "testprovider",
                "pricing_prompt": 0.002,
                "pricing_completion": 0.003,
            },
        ]
    )

    economics = build_conservative_provider_economics(provider_activity, pricing)

    row = economics.iloc[0]
    assert row["pricing_prompt"] == pytest.approx(0.002)
    assert row["pricing_completion"] == pytest.approx(0.003)
    # No prompt/completion split, so revenue uses the blended rate.
    blended = 0.002 * 0.977 + 0.003 * 0.023
    assert row["estimated_revenue"] == pytest.approx(1_000_000.0 * blended)


def test_route_specific_prices_do_not_contaminate_shared_canonical_slug() -> None:
    provider_activity = pd.DataFrame(
        [
            {
                "usage_date": "2026-08-26",
                "entity_id": "minimax",
                "entity_name": "MiniMax",
                "model_permaslug": model,
                "total_tokens": 1_000_000.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            }
            for model in [
                "minimax/minimax-m3-20260531",
                "minimax/minimax-m3-20260531:batch",
                "minimax/minimax-m3-20260531:free",
            ]
        ]
    )
    pricing = pd.DataFrame(
        [
            {
                "snapshot_ts": "2026-08-25T00:00:00Z",
                "model_id": "minimax/minimax-m3",
                "canonical_slug": "minimax/minimax-m3-20260531",
                "provider_prefix": "minimax",
                "pricing_prompt": 0.0000003,
                "pricing_completion": 0.0000012,
            },
            {
                "snapshot_ts": "2026-08-25T00:00:00Z",
                "model_id": "minimax/minimax-m3:batch",
                "canonical_slug": "minimax/minimax-m3-20260531",
                "provider_prefix": "minimax",
                "pricing_prompt": 0.00000015,
                "pricing_completion": 0.0000006,
            },
            {
                "snapshot_ts": "2026-08-25T00:00:00Z",
                "model_id": "minimax/minimax-m3:free",
                "canonical_slug": "minimax/minimax-m3-20260531",
                "provider_prefix": "minimax",
                "pricing_prompt": 0.0,
                "pricing_completion": 0.0,
            },
        ]
    )

    conservative = build_conservative_provider_economics(provider_activity, pricing).set_index(
        "model_permaslug"
    )
    estimated = build_provider_revenue_estimates(provider_activity, pricing).set_index(
        "model_permaslug"
    )

    paid_blended = (0.0000003 * 0.977) + (0.0000012 * 0.023)
    batch_blended = (0.00000015 * 0.977) + (0.0000006 * 0.023)
    for frame in [conservative, estimated]:
        assert frame.loc["minimax/minimax-m3-20260531", "estimated_revenue"] == pytest.approx(
            1_000_000.0 * paid_blended
        )
        assert frame.loc[
            "minimax/minimax-m3-20260531:batch", "estimated_revenue"
        ] == pytest.approx(1_000_000.0 * batch_blended)
        assert (
            frame.loc["minimax/minimax-m3-20260531:free", "estimated_revenue"]
            == 0.0
        )


def test_estimate_usage_revenue_uses_asof_snapshot_for_historical_usage() -> None:
    usage = pd.DataFrame(
        [
            {
                "usage_date": "2026-04-16",
                "provider_slug": "openai",
                "model_permaslug": "openai/gpt-4.1",
                "total_tokens": 100.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            }
        ]
    )
    pricing = pd.DataFrame(
        [
            {
                "snapshot_ts": "2026-04-15T12:00:00Z",
                "model_id": "openai/gpt-4.1",
                "canonical_slug": "openai/gpt-4.1",
                "provider_prefix": "openai",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
            },
            {
                "snapshot_ts": "2026-04-17T12:00:00Z",
                "model_id": "openai/gpt-4.1",
                "canonical_slug": "openai/gpt-4.1",
                "provider_prefix": "openai",
                "pricing_prompt": 0.010,
                "pricing_completion": 0.020,
            },
        ]
    )

    estimated = estimate_usage_revenue(
        usage,
        pricing,
        slug_strategy="canonical",
        pricing_strategy="provider_fallback",
    )

    row = estimated.iloc[0]
    assert pd.Timestamp(row["pricing_snapshot_ts"]) == pd.Timestamp("2026-04-15T12:00:00Z")
    assert row["pricing_join_status"] == "matched_model_median"
    assert row["estimated_revenue"] == pytest.approx(0.1023)


def test_anthropic_fast_aliases_do_not_collapse_into_plain_opus() -> None:
    assert generate_candidate_aliases("anthropic/claude-4.7-opus-20260416")[-1] == "anthropic/claude-opus-4.7"
    assert generate_candidate_aliases("anthropic/claude-4.7-opus-fast-20260512")[-1] == "anthropic/claude-opus-4.7-fast"
    assert "anthropic/claude-opus-4.7" not in generate_candidate_aliases(
        "anthropic/claude-4.7-opus-fast-20260512"
    )


def test_estimate_usage_revenue_keeps_anthropic_opus_fast_pricing_separate() -> None:
    usage = pd.DataFrame(
        [
            {
                "usage_date": "2026-06-24",
                "provider_slug": "anthropic",
                "model_permaslug": "anthropic/claude-4.7-opus-20260416",
                "total_tokens": 1_000_000.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            }
        ]
    )
    pricing = pd.DataFrame(
        [
            {
                "snapshot_ts": "2026-06-27T09:35:09Z",
                "model_id": "anthropic/claude-opus-4.7",
                "canonical_slug": "anthropic/claude-4.7-opus-20260416",
                "provider_prefix": "anthropic",
                "pricing_prompt": 0.000005,
                "pricing_completion": 0.000025,
            },
            {
                "snapshot_ts": "2026-06-27T09:35:09Z",
                "model_id": "anthropic/claude-opus-4.7-fast",
                "canonical_slug": "anthropic/claude-4.7-opus-fast-20260512",
                "provider_prefix": "anthropic",
                "pricing_prompt": 0.000030,
                "pricing_completion": 0.000150,
            },
        ]
    )

    estimated = estimate_usage_revenue(
        usage,
        pricing,
        slug_strategy="canonical",
        pricing_strategy="provider_fallback",
    )

    row = estimated.iloc[0]
    assert row["matched_model_key"] == "anthropic/claude-opus-4.7"
    assert row["pricing_prompt"] == pytest.approx(0.000005)
    assert row["pricing_completion"] == pytest.approx(0.000025)
    assert row["estimated_revenue"] == pytest.approx(5.46)


def test_estimate_usage_revenue_falls_back_to_earliest_snapshot_before_pricing_history_starts() -> None:
    usage = pd.DataFrame(
        [
            {
                "usage_date": "2026-01-16",
                "provider_slug": "openai",
                "model_permaslug": "openai/gpt-4.1",
                "total_tokens": 100.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            }
        ]
    )
    pricing = pd.DataFrame(
        [
            {
                "snapshot_ts": "2026-04-15T12:00:00Z",
                "model_id": "openai/gpt-4.1",
                "canonical_slug": "openai/gpt-4.1",
                "provider_prefix": "openai",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
            },
            {
                "snapshot_ts": "2026-04-17T12:00:00Z",
                "model_id": "openai/gpt-4.1",
                "canonical_slug": "openai/gpt-4.1",
                "provider_prefix": "openai",
                "pricing_prompt": 0.010,
                "pricing_completion": 0.020,
            },
        ]
    )

    estimated = estimate_usage_revenue(
        usage,
        pricing,
        slug_strategy="canonical",
        pricing_strategy="provider_fallback",
    )

    row = estimated.iloc[0]
    assert pd.Timestamp(row["pricing_snapshot_ts"]) == pd.Timestamp("2026-04-15T12:00:00Z")
    assert row["pricing_join_status"] == "matched_model_median"
    assert row["estimated_revenue"] == pytest.approx(0.1023)


def test_estimate_usage_revenue_falls_back_to_full_pricing_when_usage_date_missing() -> None:
    usage = pd.DataFrame(
        [
            {
                "usage_date": None,
                "provider_slug": "openai",
                "model_permaslug": "openai/unknown-model",
                "total_tokens": 100.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            }
        ]
    )
    pricing = pd.DataFrame(
        [
            {
                "snapshot_ts": "2026-04-15T12:00:00Z",
                "model_id": "openai/gpt-4.1",
                "canonical_slug": "openai/gpt-4.1",
                "provider_prefix": "openai",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
            }
        ]
    )

    estimated = estimate_usage_revenue(
        usage,
        pricing,
        slug_strategy="canonical",
        pricing_strategy="provider_fallback",
    )

    row = estimated.iloc[0]
    assert pd.Timestamp(row["pricing_snapshot_ts"]) == pd.Timestamp("2026-04-15T12:00:00Z")
    assert row["pricing_join_status"] == "fallback_provider_median"
    assert row["estimated_revenue"] == pytest.approx(0.1023)


def test_estimate_usage_revenue_fast_path_matches_shuffled_fallback_path() -> None:
    # The as-of price-context builder has a fast, incremental path that only
    # applies when pricing rows are already chronologically ordered, and a
    # slower per-cutoff fallback used otherwise (see
    # openrouter_revenue._price_contexts_by_cutoff). Both must produce the
    # exact same result - feed the same multi-cutoff, multi-model data
    # through in original (sorted) order and shuffled order and compare.
    pricing = pd.DataFrame(
        [
            {
                "snapshot_ts": "2026-01-01T00:00:00Z",
                "model_id": "openai/gpt-5",
                "canonical_slug": "openai/gpt-5",
                "provider_prefix": "openai",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
            },
            {
                "snapshot_ts": "2026-01-01T00:00:00Z",
                "model_id": "anthropic/claude-5-sonnet",
                "canonical_slug": "anthropic/claude-5-sonnet",
                "provider_prefix": "anthropic",
                "pricing_prompt": 0.003,
                "pricing_completion": 0.004,
            },
            {
                "snapshot_ts": "2026-01-05T00:00:00Z",
                "model_id": "openai/gpt-5",
                "canonical_slug": "openai/gpt-5",
                "provider_prefix": "openai",
                "pricing_prompt": 0.0012,
                "pricing_completion": 0.0022,
            },
            {
                "snapshot_ts": "2026-01-10T00:00:00Z",
                "model_id": "anthropic/claude-5-sonnet",
                "canonical_slug": "anthropic/claude-5-sonnet",
                "provider_prefix": "anthropic",
                "pricing_prompt": 0.0032,
                "pricing_completion": 0.0042,
            },
            {
                "snapshot_ts": "2026-01-15T00:00:00Z",
                "model_id": "openai/gpt-5",
                "canonical_slug": "openai/gpt-5",
                "provider_prefix": "openai",
                "pricing_prompt": 0.0014,
                "pricing_completion": 0.0024,
            },
        ]
    )
    usage = pd.DataFrame(
        [
            {
                "usage_date": usage_date,
                "provider_slug": provider,
                "model_permaslug": model,
                "total_tokens": 1_000_000.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            }
            for usage_date in ("2026-01-02", "2026-01-06", "2026-01-11", "2026-01-16", "2026-01-20")
            for provider, model in (("openai", "openai/gpt-5"), ("anthropic", "anthropic/claude-5-sonnet"))
        ]
    )

    sorted_result = estimate_usage_revenue(
        usage, pricing, slug_strategy="canonical", pricing_strategy="provider_fallback"
    )
    shuffled_pricing = pricing.sample(frac=1.0, random_state=7).reset_index(drop=True)
    shuffled_result = estimate_usage_revenue(
        usage, shuffled_pricing, slug_strategy="canonical", pricing_strategy="provider_fallback"
    )

    sort_cols = ["usage_date", "provider_slug", "model_permaslug"]
    pd.testing.assert_frame_equal(
        sorted_result.sort_values(sort_cols).reset_index(drop=True),
        shuffled_result.sort_values(sort_cols).reset_index(drop=True),
    )
    # Sanity check the fast path actually engaged and produced live prices,
    # not an accidental all-empty/all-fallback result that would trivially match.
    assert sorted_result["pricing_join_status"].eq("matched_model_median").all()


def test_price_contexts_by_cutoff_falls_back_on_unordered_pricing() -> None:
    from openrouter_revenue import _price_contexts_by_cutoff

    pricing = pd.DataFrame(
        [
            {"snapshot_ts": "2026-01-01T00:00:00Z", "model_id": "openai/gpt-5", "pricing_prompt": 0.001, "pricing_completion": 0.002},
            {"snapshot_ts": "2026-01-05T00:00:00Z", "model_id": "openai/gpt-5", "pricing_prompt": 0.0012, "pricing_completion": 0.0022},
        ]
    )
    ordered = pricing.copy()
    ordered["_pricing_date"] = pd.to_datetime(ordered["snapshot_ts"], utc=True).dt.normalize()
    assert _price_contexts_by_cutoff(ordered) is not None

    shuffled = pricing.iloc[::-1].reset_index(drop=True).copy()
    shuffled["_pricing_date"] = pd.to_datetime(shuffled["snapshot_ts"], utc=True).dt.normalize()
    assert _price_contexts_by_cutoff(shuffled) is None


def test_estimate_usage_revenue_zero_rates_free_models_without_fallback_pricing() -> None:
    usage = pd.DataFrame(
        [
            {
                "usage_date": "2026-05-01",
                "provider_slug": "tencent",
                "model_permaslug": "tencent/hy3-preview:free",
                "total_tokens": 10_000_000.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            }
        ]
    )
    pricing = pd.DataFrame(
        [
            {
                "snapshot_ts": "2026-04-30T00:00:00Z",
                "model_id": "openai/gpt-4.1",
                "canonical_slug": "openai/gpt-4.1",
                "provider_prefix": "openai",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
            }
        ]
    )

    estimated = estimate_usage_revenue(
        usage,
        pricing,
        slug_strategy="canonical",
        pricing_strategy="provider_fallback",
    )

    row = estimated.iloc[0]
    assert row["pricing_join_status"] == "free_model_zero_revenue"
    assert row["estimated_revenue"] == 0.0
    assert row["pricing_prompt"] == 0.0
    assert row["pricing_completion"] == 0.0


def test_conservative_economics_zero_rates_free_models_and_keeps_token_volume() -> None:
    provider_activity = pd.DataFrame(
        [
            {
                "usage_date": "2026-05-01",
                "entity_id": "tencent",
                "entity_name": "Tencent",
                "model_permaslug": "tencent/hy3-preview:free",
                "total_tokens": 10_000_000.0,
                "prompt_tokens": 0.0,
                "completion_tokens": 0.0,
            }
        ]
    )
    pricing = pd.DataFrame(
        [
            {
                "snapshot_ts": "2026-04-30T00:00:00Z",
                "model_id": "openai/gpt-4.1",
                "canonical_slug": "openai/gpt-4.1",
                "provider_prefix": "openai",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
            }
        ]
    )

    economics = build_conservative_provider_economics(provider_activity, pricing)

    row = economics.iloc[0]
    assert row["provider_slug"] == "tencent"
    assert row["provider_name"] == "Tencent"
    assert row["total_tokens"] == 10_000_000.0
    assert row["pricing_join_status"] == "free_model_zero_revenue"
    assert row["revenue_method"] == "free_model"
    assert row["estimated_revenue"] == 0.0


def test_notebook_style_rollup_preserves_unpriced_coverage_gaps(tmp_path: Path) -> None:
    _seed_research_inputs(tmp_path)

    revenue_daily = provider_revenue_daily(["xiaomi"], base_dir=tmp_path, refresh=True)
    daily_rollup = (
        revenue_daily.groupby(["usage_date", "provider_slug"], as_index=False)
        .agg(
            total_tokens=("total_tokens", "sum"),
            estimated_revenue=("estimated_revenue", lambda s: s.sum(min_count=1)),
        )
        .sort_values(["usage_date", "provider_slug"])
    )

    xiaomi_row = daily_rollup.iloc[0]
    assert xiaomi_row["provider_slug"] == "xiaomi"
    assert pd.isna(xiaomi_row["estimated_revenue"])


def test_build_frontier_model_registry_preserves_unmatched_rows_and_flags_large_models(tmp_path: Path) -> None:
    _seed_research_inputs(tmp_path)

    mart = build_frontier_model_registry(base_dir=tmp_path, refresh=True)

    assert set(mart["model_id"]) == {
        "openai/gpt-4.1",
        "anthropic/claude-sonnet-4",
        "moonshot/kimi-lite",
    }
    openai_row = mart[mart["model_id"] == "openai/gpt-4.1"].iloc[0]
    assert bool(openai_row["is_on_openrouter"]) is True
    assert bool(openai_row["is_large_model"]) is True
    assert openai_row["hf_downloads_daily_est_latest"] == 42.0

    moonshot_row = mart[mart["model_id"] == "moonshot/kimi-lite"].iloc[0]
    assert bool(moonshot_row["is_on_openrouter"]) is False
    assert pd.isna(moonshot_row["pricing_prompt"])
    assert bool(moonshot_row["is_large_model"]) is False


def test_monthly_model_releases_aggregates_frontier_registry(tmp_path: Path) -> None:
    _seed_research_inputs(tmp_path)
    build_frontier_model_registry(base_dir=tmp_path, refresh=True)

    monthly = monthly_model_releases(base_dir=tmp_path, refresh=False)

    april = monthly[monthly["release_month"] == "2026-04"].iloc[0]
    assert april["model_count"] == 3
    assert april["large_model_count"] == 1


def test_mart_builds_are_idempotent_and_write_csv_and_parquet(tmp_path: Path) -> None:
    _seed_research_inputs(tmp_path)

    first = build_weekly_openrouter_usage(base_dir=tmp_path, refresh=True)
    second = build_weekly_openrouter_usage(base_dir=tmp_path, refresh=False)

    pd.testing.assert_frame_equal(first.fillna(value=float("nan")), second.fillna(value=float("nan")), check_dtype=False)
    csv_path, parquet_path = mart_paths("weekly_openrouter_usage", base_dir=tmp_path)
    assert csv_path.exists()
    assert parquet_path.exists()


def test_research_cli_accepts_base_dir_after_subcommand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _seed_research_inputs(tmp_path)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "research-data",
            "build-mart",
            "weekly_openrouter_usage",
            "--base-dir",
            str(tmp_path),
        ],
    )

    research_cli_main()

    captured = capsys.readouterr()
    assert "weekly_openrouter_usage:" in captured.out


def test_frontier_notebook_surfaces_current_source_freshness_and_coverage_note() -> None:
    notebook_path = Path(__file__).resolve().parents[1] / "notebooks" / "03_frontier_intelligence_dynamics.ipynb"
    notebook = json.loads(notebook_path.read_text())

    markdown_text = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "markdown"
    )
    code_text = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    )

    assert "Artificial Analysis" in markdown_text
    assert "Model coverage reflects" in markdown_text
    assert "as_of_date" in code_text
    assert "scraped_at" in code_text
    assert "release_date" in code_text


def test_benchmark_refresh_workflow_rebuilds_frontier_registry() -> None:
    workflow_path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "llm-benchmarks-weekly.yml"
    workflow = workflow_path.read_text()

    assert 'cron: "0 9 * * 1"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "python -m llm_benchmark_data.cli --base-dir . update" in workflow
    assert "python -m research_data.cli --base-dir . build-mart frontier_model_registry --refresh" in workflow
    assert "data/normalized/llm_benchmarks" in workflow
    assert "data/normalized/marts/frontier_model_registry.csv" in workflow
    assert "data/normalized/marts/frontier_model_registry.parquet" in workflow
    commit_section = workflow.split("git add \\", 1)[1].split("if git diff --staged --quiet; then", 1)[0]
    assert "data/raw/llm_benchmarks" not in commit_section
    assert "path: data/raw/llm_benchmarks/" in workflow


def test_pyproject_exposes_llm_benchmark_cli_script() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    scripts = pyproject["project"]["scripts"]
    assert scripts["llm-benchmark-data"] == "llm_benchmark_data.cli:main"


def test_write_mart_leaves_an_unchanged_file_alone(tmp_path: Path) -> None:
    """An identical rewrite is invisible to git but not to everything else.

    build_*(refresh=False) reuses an existing mart only when it is non-empty,
    so a mart committed empty -- frontier_model_registry is -- was recomputed
    and rewritten on every call, including every execution of
    notebooks/00_data_catalog.ipynb. The bytes never changed, so `git diff`
    showed nothing while the mtime moved on every notebook run.
    """
    from research_data.marts import mart_paths, read_mart, write_mart

    empty = pd.DataFrame({"model_id": pd.Series(dtype="object")})
    write_mart("frontier_model_registry", empty, base_dir=tmp_path)
    _, parquet_path = mart_paths("frontier_model_registry", base_dir=tmp_path)
    first = parquet_path.stat().st_mtime_ns

    write_mart("frontier_model_registry", read_mart("frontier_model_registry", base_dir=tmp_path), base_dir=tmp_path)
    assert parquet_path.stat().st_mtime_ns == first

    changed = pd.DataFrame({"model_id": ["gpt-5"]})
    write_mart("frontier_model_registry", changed, base_dir=tmp_path)
    assert parquet_path.stat().st_mtime_ns != first
    assert read_mart("frontier_model_registry", base_dir=tmp_path)["model_id"].tolist() == ["gpt-5"]
