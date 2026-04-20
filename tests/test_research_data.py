from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from dashboard import data as dashboard_data
from openrouter_revenue import estimate_usage_revenue
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
    assert matched["pricing_join_status"] == "matched_model_split_median"
    assert matched["estimated_revenue"] == pytest.approx(0.14)

    missing = mart[mart["model_permaslug"] == "unknown/model"].iloc[0]
    assert missing["pricing_join_status"] == "fallback_provider_median"
    assert missing["estimated_revenue"] == pytest.approx(0.104025)


def test_build_daily_provider_economics_canonicalizes_model_ids(tmp_path: Path) -> None:
    _seed_research_inputs(tmp_path)

    mart = build_daily_provider_economics(base_dir=tmp_path, refresh=True)

    openai_row = mart[mart["model_permaslug"] == "openai/gpt-5.4-20260305"].iloc[0]
    assert openai_row["pricing_snapshot_ts"] == "2026-04-15T12:00:00Z"
    assert openai_row["pricing_join_status"] == "matched_model_median"
    assert openai_row["estimated_revenue"] == pytest.approx(0.6276)

    anthropic_row = mart[mart["model_permaslug"] == "anthropic/claude-4.6-sonnet-20260217"].iloc[0]
    assert anthropic_row["pricing_join_status"] == "matched_model_split_median"
    assert anthropic_row["estimated_revenue"] == pytest.approx(0.56)

    qwen_row = mart[mart["model_permaslug"] == "qwen/qwen3.5-flash-20260224"].iloc[0]
    assert qwen_row["pricing_join_status"] == "matched_model_median"
    assert qwen_row["estimated_revenue"] == pytest.approx(0.0000208455)


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
    assert kimi_row["pricing_join_status"] == "matched_model_median"
    assert kimi_row["estimated_revenue"] == pytest.approx(0.0006552)


def test_provider_revenue_daily_defaults_to_dashboard_estimate_with_model_medians_and_fallbacks(tmp_path: Path) -> None:
    _seed_research_inputs(tmp_path)

    revenue = provider_revenue_daily(
        ["openai", "anthropic", "qwen", "xiaomi"],
        base_dir=tmp_path,
        refresh=True,
    )

    split_match = revenue[revenue["model_permaslug"] == "openai/gpt-4.1"].iloc[0]
    assert split_match["pricing_join_status"] == "matched_model_split_median"
    assert split_match["estimated_revenue"] == pytest.approx(0.14)

    blended_match = revenue[revenue["model_permaslug"] == "openai/gpt-5.4-20260305"].iloc[0]
    assert blended_match["pricing_join_status"] == "matched_model_median"
    assert blended_match["estimated_revenue"] == pytest.approx(0.6276)

    provider_fallback = revenue[revenue["model_permaslug"] == "openai/new-unpriced-model"].iloc[0]
    assert provider_fallback["pricing_join_status"] == "fallback_provider_median"
    assert provider_fallback["estimated_revenue"] == pytest.approx(0.16644)

    global_fallback = revenue[revenue["model_permaslug"] == "xiaomi/missing-model"].iloc[0]
    assert global_fallback["pricing_join_status"] == "fallback_global_median"
    assert global_fallback["estimated_revenue"] == pytest.approx(0.187245)

    qwen_row = revenue[revenue["model_permaslug"] == "qwen/qwen3.5-flash-20260224"].iloc[0]
    assert qwen_row["pricing_join_status"] == "matched_model_median"
    assert qwen_row["estimated_revenue"] == pytest.approx(0.0000208455)

    synthetic = revenue[revenue["model_permaslug"] == "Others"].iloc[0]
    assert synthetic["pricing_join_status"] == "synthetic_unpriced"
    assert pd.isna(synthetic["estimated_revenue"])


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


def test_notebook_style_rollup_uses_dashboard_estimate_defaults(tmp_path: Path) -> None:
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
    assert xiaomi_row["estimated_revenue"] == pytest.approx(0.187245)


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

    pd.testing.assert_frame_equal(first, second, check_dtype=False)
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
