from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from dashboard import data as dashboard_data
from research_data.api import monthly_model_releases
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
                "model_name": "OpenAI GPT-4.1",
                "context_length": 131072,
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
            },
            {
                "dataset_id": "raw_openrouter_models",
                "source_url": "https://openrouter.ai/api/v1/models",
                "source_run_id": "run-3",
                "scraped_at": "2026-04-17T12:00:00Z",
                "snapshot_ts": "2026-04-17T12:00:00Z",
                "model_id": "openai/gpt-4.1",
                "model_name": "OpenAI GPT-4.1",
                "context_length": 262144,
                "pricing_prompt": 0.010,
                "pricing_completion": 0.020,
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
    assert matched["pricing_join_status"] == "matched_exact_split"
    assert matched["estimated_revenue"] == 0.14

    missing = mart[mart["model_permaslug"] == "unknown/model"].iloc[0]
    assert pd.isna(missing["estimated_revenue"])
    assert missing["pricing_join_status"] == "missing_snapshot"


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
