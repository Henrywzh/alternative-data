from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
import dashboard.app as dashboard_app

from dashboard.app import (
    _compute_revenue_views,
    _derive_provider_name,
    build_domain_signature,
    build_manifest_signature,
    build_normalized_signature,
    compute_compute_availability_views,
    compute_artificial_analysis_views,
    compute_openrouter_views,
    compute_semiconductor_views,
    compute_provider_adoption_views,
    format_scraped_at_display,
    grouped_revenue_token_pivots,
    load_domain_state_cached,
    make_line_chart,
    make_stacked_area_chart,
    order_provider_columns,
    prepare_hf_models_table,
    resolve_hf_metric_config,
    section_domains,
    regroup_provider_pivot_for_display,
    _top_n_with_others,
    rankings_bucket_warning,
    rankings_week_context,
)
from dashboard.checks import run_checks
from dashboard.data import (
    EXPECTED_COLUMNS,
    DATASET_REGISTRY,
    DatasetLoadResult,
    DOMAIN_ORDER,
    OPENROUTER_LOAD_COLUMNS,
    dataset_source_for_domain,
    domain_dataset_ids,
    load_all_datasets,
    load_dataset,
    load_domain_datasets,
    load_latest_manifest,
)
from dashboard.sections.openrouter import (
    _average_price_section_state,
    _cap_change_percent_for_display,
    _compute_task_spend_views,
    _default_task_spend_window,
    _estimator_coverage_summary,
    _latest_provider_market_coverage,
    _drop_first_valid_change_point,
    _nowcast_latest_partial_period,
    _pivot_to_aggregate_change_percent,
    _pivot_to_change_percent,
    _pivot_to_share_percent,
    _workload_intensity_section_state,
    _weekly_usage_section_state,
    _derived_metric_pivot,
    _legacy_original_price_series,
    model_explorer_state,
)
from dashboard.sections.semiconductor import (
    _private_panel_code_matches,
    _private_panel_expected_code,
)


def _base_row(dataset_id: str) -> dict:
    return {
        "dataset_id": dataset_id,
        "source_url": "https://example.test",
        "source_run_id": "run-1",
        "scraped_at": "2026-04-05T00:00:00Z",
        "week_label": None,
        "week_start_date": None,
        "entity_id": None,
        "entity_name": None,
        "parent_entity_id": None,
        "parent_entity_name": None,
        "metric_name": None,
        "metric_unit": None,
        "metric_value": None,
        "rank": None,
        "category_slug": None,
        "app_id": None,
        "app_name": None,
        "origin_url": None,
        "main_url": None,
        "description": None,
        "categories": None,
        "group_by_origin": None,
        "is_private": None,
        "is_hidden": None,
        "created_at": None,
        "scrape_date": None,
        "usage_date": None,
        "model_permaslug": None,
        "total_tokens": None,
        "snapshot_date": None,
        "observed_at": None,
        "period": None,
        "tokens": None,
        "growth_percent": None,
        "window_days": None,
        "macro_category": None,
        "task_share_of_total": None,
        "model_share": None,
        "delta_pp": None,
        "provider": None,
        "provider_display_name": None,
        "package_name": None,
        "package_type": None,
        "with_mirrors": None,
        "download_date": None,
        "downloads": None,
        "repo_full_name": None,
        "repo_owner": None,
        "repo_name": None,
        "repo_html_url": None,
        "repo_created_date": None,
        "repo_created_at": None,
        "repo_pushed_at": None,
        "repo_default_branch": None,
        "language_bucket": None,
        "signal_date": None,
        "signal_type": None,
        "matched_file_path": None,
        "matched_pattern": None,
        "is_fork": None,
        "is_archived": None,
        "stargazers_count": None,
        "has_manifest_dependency": None,
        "has_code_import": None,
        "has_env_var": None,
        "has_model_name": None,
        "matched_signal_count": None,
        "pypi_7d_avg": None,
        "pypi_28d_avg": None,
        "pypi_share_28d": None,
        "pypi_growth_28d": None,
        "github_new_repo_count": None,
        "github_signal_repo_count": None,
        "github_manifest_repo_count": None,
        "github_repo_share": None,
        "github_import_repo_count": None,
        "github_env_repo_count": None,
        "github_model_repo_count": None,
        "momentum_score": None,
    }


def _rankings_frame(dataset_id: str) -> pd.DataFrame:
    rows = []
    for week, entity, metric, rank in [
        ("2026-03-09", "openai/gpt-4o-mini", 100.0, 1),
        ("2026-03-16", "anthropic/claude", 200.0, 1),
    ]:
        row = _base_row(dataset_id)
        row.update(
            {
                "week_label": week,
                "week_start_date": week,
                "entity_id": entity,
                "entity_name": entity,
                "parent_entity_id": entity.split("/")[0],
                "parent_entity_name": entity.split("/")[0],
                "metric_name": "tokens",
                "metric_unit": "tokens",
                "metric_value": metric,
                "rank": rank,
                "category_slug": "programming" if dataset_id == "categories_programming" else None,
                "source_run_id": f"run-{week}",
                "scraped_at": f"{week}T00:00:00Z",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _provider_weekly_requests_frame() -> pd.DataFrame:
    rows = []
    for week, provider, requests, rank in [
        ("2026-03-30", "openai", 1_200_000.0, 1),
        ("2026-03-30", "anthropic", 800_000.0, 2),
        ("2026-04-06", "openai", 1_500_000.0, 1),
        ("2026-04-06", "anthropic", 700_000.0, 2),
    ]:
        row = _base_row("provider_weekly_requests")
        row.update(
            {
                "week_label": week,
                "week_start_date": week,
                "entity_id": provider,
                "entity_name": provider.title(),
                "metric_name": "requests",
                "metric_unit": "requests",
                "metric_value": requests,
                "rank": rank,
                "source_run_id": f"requests-{week}",
                "scraped_at": f"{week}T00:00:00Z",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _write_dataset(base_dir: Path, dataset_id: str, frame: pd.DataFrame) -> None:
    domain = DATASET_REGISTRY[dataset_id]["domain"]
    root = base_dir / "data" / "normalized" / dataset_source_for_domain(str(domain))
    root.mkdir(parents=True, exist_ok=True)
    frame.to_csv(root / f"{dataset_id}.csv", index=False)


def _artificial_analysis_models_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "dataset_id": "artificial_analysis_models_daily",
                "as_of_date": "2026-04-25",
                "model_id": "model-openai-a",
                "model_slug": "openai-a",
                "model_name": "OpenAI A",
                "creator_id": "creator-openai",
                "creator_name": "OpenAI",
                "creator_slug": "openai",
                "creator_country": None,
                "release_date": "2025-01-15",
                "release_quarter": "Q1-2025",
                "intelligence_index": 35.0,
                "price_1m_blended_3_to_1": 3.0,
                "median_output_tokens_per_second": 120.0,
                "open_source_categorization": "Proprietary",
                "is_open_weights": False,
                "source_url": "fixture://aa",
                "source_run_id": "run-aa",
                "scraped_at": "2026-04-25T00:00:00Z",
            },
            {
                "dataset_id": "artificial_analysis_models_daily",
                "as_of_date": "2026-04-25",
                "model_id": "model-openai-b",
                "model_slug": "openai-b",
                "model_name": "OpenAI B",
                "creator_id": "creator-openai",
                "creator_name": "OpenAI",
                "creator_slug": "openai",
                "creator_country": None,
                "release_date": "2025-03-15",
                "release_quarter": "Q1-2025",
                "intelligence_index": 41.0,
                "price_1m_blended_3_to_1": 2.5,
                "median_output_tokens_per_second": 140.0,
                "open_source_categorization": "Proprietary",
                "is_open_weights": False,
                "source_url": "fixture://aa",
                "source_run_id": "run-aa",
                "scraped_at": "2026-04-25T00:00:00Z",
            },
            {
                "dataset_id": "artificial_analysis_models_daily",
                "as_of_date": "2026-04-25",
                "model_id": "model-meta-open",
                "model_slug": "meta-open",
                "model_name": "Meta Open",
                "creator_id": "creator-meta",
                "creator_name": "Meta",
                "creator_slug": "meta",
                "creator_country": None,
                "release_date": "2025-02-20",
                "release_quarter": "Q1-2025",
                "intelligence_index": 33.0,
                "price_1m_blended_3_to_1": 0.4,
                "median_output_tokens_per_second": 180.0,
                "open_source_categorization": "Open Weights (Permissive License)",
                "is_open_weights": True,
                "source_url": "fixture://aa",
                "source_run_id": "run-aa",
                "scraped_at": "2026-04-25T00:00:00Z",
            },
            {
                "dataset_id": "artificial_analysis_models_daily",
                "as_of_date": "2026-04-25",
                "model_id": "model-deepseek",
                "model_slug": "deepseek-frontier",
                "model_name": "DeepSeek Frontier",
                "creator_id": "creator-deepseek",
                "creator_name": "DeepSeek",
                "creator_slug": "deepseek",
                "creator_country": None,
                "release_date": "2025-04-10",
                "release_quarter": "Q2-2025",
                "intelligence_index": 39.0,
                "price_1m_blended_3_to_1": 0.2,
                "median_output_tokens_per_second": 150.0,
                "open_source_categorization": "Open Weights (Permissive License)",
                "is_open_weights": True,
                "source_url": "fixture://aa",
                "source_run_id": "run-aa",
                "scraped_at": "2026-04-25T00:00:00Z",
            },
            {
                "dataset_id": "artificial_analysis_models_daily",
                "as_of_date": "2026-04-25",
                "model_id": "model-alibaba",
                "model_slug": "alibaba-frontier",
                "model_name": "Alibaba Frontier",
                "creator_id": "creator-alibaba",
                "creator_name": "Alibaba",
                "creator_slug": "alibaba",
                "creator_country": "cn",
                "release_date": "2025-05-01",
                "release_quarter": "Q2-2025",
                "intelligence_index": 37.0,
                "price_1m_blended_3_to_1": None,
                "median_output_tokens_per_second": 130.0,
                "open_source_categorization": "Proprietary",
                "is_open_weights": False,
                "source_url": "fixture://aa",
                "source_run_id": "run-aa",
                "scraped_at": "2026-04-25T00:00:00Z",
            },
        ]
    )


def _artificial_analysis_capex_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "dataset_id": "artificial_analysis_capex_quarterly",
                "quarter_id": "2024-q4",
                "quarter_label": "Q4-2024",
                "microsoft": 15.804,
                "google": 14.276,
                "meta": 14.425,
                "amazon": 26.052,
                "oracle": 3.97,
                "apple": 2.94,
                "source_url": "https://artificialanalysis.ai/trends",
                "page_url": "https://artificialanalysis.ai/trends",
                "bundle_url": "https://artificialanalysis.ai/_next/static/chunks/app/(pages)/trends/page-demo.js",
                "source_run_id": "run-aa",
                "scraped_at": "2026-04-25T00:00:00Z",
            },
            {
                "dataset_id": "artificial_analysis_capex_quarterly",
                "quarter_id": "2025-q1",
                "quarter_label": "Q1-2025",
                "microsoft": 16.745,
                "google": 17.197,
                "meta": 12.941,
                "amazon": 24.255,
                "oracle": 5.862,
                "apple": 3.071,
                "source_url": "https://artificialanalysis.ai/trends",
                "page_url": "https://artificialanalysis.ai/trends",
                "bundle_url": "https://artificialanalysis.ai/_next/static/chunks/app/(pages)/trends/page-demo.js",
                "source_run_id": "run-aa",
                "scraped_at": "2026-04-25T00:00:00Z",
            },
        ]
    )


def _apps_usage_frame() -> pd.DataFrame:
    rows = []
    for usage_date, model, tokens, rank in [
        ("2026-04-03", "stepfun/step-3.5-flash", 1000.0, 1),
        ("2026-04-04", "moonshotai/kimi-k2.5-0127", 2000.0, 2),
    ]:
        row = _base_row("app_usage_daily")
        row.update(
            {
                "app_id": "1",
                "app_name": "OpenClaw",
                "origin_url": "https://openclaw.ai/",
                "categories": "personal-agent",
                "usage_date": usage_date,
                "model_permaslug": model,
                "total_tokens": tokens,
                "rank": rank,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _apps_metadata_frame() -> pd.DataFrame:
    row = _base_row("app_metadata_snapshots")
    row.update(
        {
            "app_id": "1",
            "app_name": "OpenClaw",
            "origin_url": "https://openclaw.ai/",
            "description": "The AI that actually does things",
            "categories": "personal-agent",
            "scrape_date": "2026-04-05",
            "created_at": "2026-01-30T06:12:11Z",
        }
    )
    return pd.DataFrame([row], columns=EXPECTED_COLUMNS)


def _apps_top_models_frame() -> pd.DataFrame:
    rows = []
    for snapshot_date, model, total_tokens, rank in [
        ("2026-04-04", "stepfun/step-3.5-flash", 3000.0, 1),
        ("2026-04-05", "xiaomi/mimo-v2-pro-20260318", 4000.0, 2),
    ]:
        row = _base_row("app_top_models_daily_snapshot")
        row.update(
            {
                "app_id": "1",
                "app_name": "OpenClaw",
                "origin_url": "https://openclaw.ai/",
                "snapshot_date": snapshot_date,
                "model_permaslug": model,
                "total_tokens": total_tokens,
                "rank": rank,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _apps_global_ranking_frame() -> pd.DataFrame:
    rows = []
    for period, rank, tokens in [("day", 1, 1000.0), ("week", 1, 2000.0), ("month", 1, 3000.0)]:
        row = _base_row("apps_global_ranking_snapshots")
        row.update(
            {
                "app_id": "1",
                "app_name": "OpenClaw",
                "origin_url": "https://openclaw.ai/",
                "categories": "personal-agent",
                "snapshot_date": "2026-04-05",
                "period": period,
                "tokens": tokens,
                "rank": rank,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _apps_trending_frame() -> pd.DataFrame:
    rows = []
    for rank, app_name, growth, tokens in [(1, "Ito", 6516.0, 39300000000.0), (2, "Nexu Link", 2596.0, 27800000000.0)]:
        row = _base_row("apps_trending_snapshots")
        row.update(
            {
                "app_id": str(rank),
                "app_name": app_name,
                "origin_url": f"https://{app_name.lower().replace(' ', '')}.ai/",
                "snapshot_date": "2026-04-05",
                "tokens": tokens,
                "growth_percent": growth,
                "rank": rank,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _github_trending_frame(dataset_id: str) -> pd.DataFrame:
    rows = []
    for scrape_date, name, stars_today in [
        ("2026-04-04", "repo-alpha", 120),
        ("2026-04-05", "repo-beta", 240),
    ]:
        row = _base_row(dataset_id)
        row.update(
            {
                "scrape_date": scrape_date,
                "author": "openai",
                "name": name,
                "link": f"https://github.com/openai/{name}",
                "stars_today": stars_today,
                "total_stars": stars_today * 10,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _provider_pypi_frame() -> pd.DataFrame:
    rows = []
    for provider, package_name, date_value, downloads in [
        ("openai", "openai", "2026-04-04", 1000),
        ("openai", "openai", "2026-04-05", 1200),
        ("anthropic", "anthropic", "2026-04-04", 800),
        ("anthropic", "anthropic", "2026-04-05", 900),
        ("google", "google-genai", "2026-04-04", 700),
        ("google", "google-genai", "2026-04-05", 750),
    ]:
        row = _base_row("pypi_downloads_daily")
        row.update(
            {
                "provider": provider,
                "provider_display_name": provider.title(),
                "package_name": package_name,
                "package_type": "sdk",
                "with_mirrors": False,
                "download_date": date_value,
                "downloads": downloads,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _provider_npm_frame() -> pd.DataFrame:
    rows = []
    for provider, display_name, package_name, package_category, package_type, date_value, downloads in [
        ("openai", "OpenAI", "openai", "core_sdk", "sdk", "2026-04-04", 1500),
        ("openai", "OpenAI", "openai", "core_sdk", "sdk", "2026-04-05", 1700),
        ("anthropic", "Anthropic", "@anthropic-ai/sdk", "core_sdk", "sdk", "2026-04-04", 900),
        ("anthropic", "Anthropic", "@anthropic-ai/sdk", "core_sdk", "sdk", "2026-04-05", 1100),
        ("google", "Google", "@google/genai", "core_sdk", "sdk", "2026-04-04", 800),
        ("google", "Google", "@google/genai", "core_sdk", "sdk", "2026-04-05", 950),
        ("openai", "OpenAI", "@openai/agents", "agent_sdk", "sdk", "2026-04-05", 300),
        ("anthropic", "Anthropic", "@anthropic-ai/claude-code", "cli", "cli", "2026-04-05", 200),
        ("google", "Google", "@google/generative-ai", "legacy_sdk", "sdk", "2026-04-05", 150),
    ]:
        row = _base_row("npm_downloads_daily")
        row.update(
            {
                "provider": provider,
                "provider_display_name": display_name,
                "package_name": package_name,
                "package_type": package_type,
                "package_category": package_category,
                "download_date": date_value,
                "downloads": downloads,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _provider_hf_frame() -> pd.DataFrame:
    rows = []
    for provider, display_name, model_id, date_value, downloads_30d, downloads_all_time, daily_est, likes in [
        ("openai", "OpenAI", "openai/gpt-oss-20b", "2026-04-05", 1000, 5000, None, 100),
        ("openai", "OpenAI", "openai/gpt-oss-120b", "2026-04-06", 1200, 6200, 200, 140),
        ("anthropic", "Anthropic", "anthropic/claude-lite", "2026-04-05", 700, 2400, None, 80),
        ("anthropic", "Anthropic", "anthropic/claude-lite", "2026-04-06", 850, 2650, 250, 90),
    ]:
        row = _base_row("huggingface_models_daily")
        row.update(
            {
                "provider": provider,
                "provider_display_name": display_name,
                "author": model_id.split("/")[0],
                "model_id": model_id,
                "download_date": date_value,
                "hf_downloads_30d": downloads_30d,
                "hf_downloads_all_time": downloads_all_time,
                "hf_downloads_daily_est": daily_est,
                "hf_likes": likes,
                "hf_last_modified": f"{date_value}T12:00:00Z",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _provider_hf_large_frame() -> pd.DataFrame:
    rows = []
    for idx in range(25):
        row = _base_row("huggingface_models_daily")
        row.update(
            {
                "provider": "qwen",
                "provider_display_name": "Qwen",
                "author": "Qwen",
                "model_id": f"Qwen/model-{idx:02d}",
                "download_date": "2026-04-06",
                "hf_downloads_30d": 1000 - idx,
                "hf_downloads_all_time": 5000 - idx,
                "hf_downloads_daily_est": 10 + idx,
                "hf_likes": 100 + idx,
                "hf_last_modified": "2026-04-06T12:00:00Z",
            }
        )
        rows.append(row)

    tie_high = _base_row("huggingface_models_daily")
    tie_high.update(
        {
            "provider": "openai",
            "provider_display_name": "OpenAI",
            "author": "openai",
            "model_id": "openai/tie-high",
            "download_date": "2026-04-06",
            "hf_downloads_30d": 500,
            "hf_downloads_all_time": 9000,
            "hf_downloads_daily_est": 50,
            "hf_likes": 10,
            "hf_last_modified": "2026-04-06T12:00:00Z",
        }
    )
    tie_low = _base_row("huggingface_models_daily")
    tie_low.update(
        {
            "provider": "openai",
            "provider_display_name": "OpenAI",
            "author": "openai",
            "model_id": "openai/tie-low",
            "download_date": "2026-04-06",
            "hf_downloads_30d": 500,
            "hf_downloads_all_time": 8000,
            "hf_downloads_daily_est": 40,
            "hf_likes": 9,
            "hf_last_modified": "2026-04-06T12:00:00Z",
        }
    )
    rows.extend([tie_low, tie_high])
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _provider_candidates_frame() -> pd.DataFrame:
    rows = []
    for provider, display_name, repo_name in [
        ("openai", "OpenAI", "openai/sample-repo"),
        ("anthropic", "Anthropic", "anthropic/sample-repo"),
        ("google", "Google", "google/sample-repo"),
    ]:
        row = _base_row("github_repo_candidates_daily")
        owner, name = repo_name.split("/", 1)
        row.update(
            {
                "provider": provider,
                "provider_display_name": display_name,
                "repo_full_name": repo_name,
                "repo_owner": owner,
                "repo_name": name,
                "repo_html_url": f"https://github.com/{repo_name}",
                "repo_created_date": "2026-04-05",
                "repo_created_at": "2026-04-05T10:00:00Z",
                "repo_pushed_at": "2026-04-05T11:00:00Z",
                "repo_default_branch": "main",
                "language_bucket": "python",
                "stargazers_count": 4,
                "is_fork": False,
                "is_archived": False,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _provider_signals_frame() -> pd.DataFrame:
    rows = []
    for provider, display_name, repo_name, signal_type, matched_pattern in [
        ("openai", "OpenAI", "openai/sample-repo", "code_import", "from openai import"),
        ("anthropic", "Anthropic", "anthropic/sample-repo", "env_var", "ANTHROPIC_API_KEY"),
        ("google", "Google", "google/sample-repo", "manifest_dependency", "google-genai"),
    ]:
        row = _base_row("github_provider_signals_daily")
        owner, name = repo_name.split("/", 1)
        row.update(
            {
                "provider": provider,
                "provider_display_name": display_name,
                "repo_full_name": repo_name,
                "repo_owner": owner,
                "repo_name": name,
                "repo_html_url": f"https://github.com/{repo_name}",
                "repo_created_date": "2026-04-05",
                "repo_created_at": "2026-04-05T10:00:00Z",
                "repo_pushed_at": "2026-04-05T11:00:00Z",
                "repo_default_branch": "main",
                "language_bucket": "python",
                "signal_date": "2026-04-05",
                "signal_type": signal_type,
                "matched_file_path": "src/main.py",
                "matched_pattern": matched_pattern,
                "stargazers_count": 4,
                "is_fork": False,
                "is_archived": False,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _provider_rollup_frame() -> pd.DataFrame:
    rows = []
    for provider, display_name, repo_name, manifest, code_import, env_var, model_name, count in [
        ("openai", "OpenAI", "openai/sample-repo", True, True, False, True, 3),
        ("anthropic", "Anthropic", "anthropic/sample-repo", False, False, True, False, 1),
        ("google", "Google", "google/sample-repo", True, False, False, False, 1),
    ]:
        row = _base_row("github_repo_rollup_daily")
        owner, name = repo_name.split("/", 1)
        row.update(
            {
                "provider": provider,
                "provider_display_name": display_name,
                "repo_full_name": repo_name,
                "repo_owner": owner,
                "repo_name": name,
                "repo_html_url": f"https://github.com/{repo_name}",
                "repo_created_date": "2026-04-05",
                "repo_created_at": "2026-04-05T10:00:00Z",
                "repo_pushed_at": "2026-04-05T11:00:00Z",
                "repo_default_branch": "main",
                "language_bucket": "python",
                "signal_date": "2026-04-05",
                "has_manifest_dependency": manifest,
                "has_code_import": code_import,
                "has_env_var": env_var,
                "has_model_name": model_name,
                "matched_signal_count": count,
                "stargazers_count": 4,
                "is_fork": False,
                "is_archived": False,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _provider_github_adoption_frame() -> pd.DataFrame:
    rows = []
    for provider, display_name, candidates, signals, manifest, imports, env, models, count in [
        ("openai", "OpenAI", 600, 1, 1, 1, 0, 1, 3),
        ("anthropic", "Anthropic", 600, 1, 0, 0, 1, 0, 1),
        ("google", "Google", 600, 1, 1, 0, 0, 0, 1),
    ]:
        row = _base_row("github_provider_adoption_daily")
        row.update(
            {
                "provider": provider,
                "provider_display_name": display_name,
                "signal_date": "2026-04-05",
                "github_new_repo_count": candidates,
                "github_signal_repo_count": signals,
                "github_manifest_repo_count": manifest,
                "github_import_repo_count": imports,
                "github_env_repo_count": env,
                "github_model_repo_count": models,
                "matched_signal_count": count,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def _provider_momentum_frame() -> pd.DataFrame:
    rows = []
    for signal_date, provider, score in [
        ("2026-04-04", "openai", 0.45),
        ("2026-04-05", "anthropic", 0.57),
    ]:
        row = _base_row("provider_momentum_daily")
        row.update(
            {
                "provider": provider,
                "provider_display_name": provider.title(),
                "signal_date": signal_date,
                "momentum_score": score,
                "github_new_repo_count": 3,
                "github_repo_share": 0.4,
                "pypi_7d_avg": 1000,
                "pypi_28d_avg": 900,
                "pypi_share_28d": 0.35,
                "pypi_growth_28d": 0.2,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=EXPECTED_COLUMNS)


def test_provider_adoption_scraped_datasets_load_without_momentum_dependency(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "provider_adoption"
    root.mkdir(parents=True)
    _provider_pypi_frame().to_csv(root / "pypi_downloads_daily.csv", index=False)
    _provider_npm_frame().to_csv(root / "npm_downloads_daily.csv", index=False)
    _provider_hf_frame().to_csv(root / "huggingface_models_daily.csv", index=False)
    _provider_candidates_frame().to_csv(root / "github_repo_candidates_daily.csv", index=False)
    _provider_signals_frame().to_csv(root / "github_provider_signals_daily.csv", index=False)
    _provider_rollup_frame().to_csv(root / "github_repo_rollup_daily.csv", index=False)

    datasets = load_all_datasets(base_dir=tmp_path)
    checks = run_checks(datasets, load_latest_manifest(base_dir=tmp_path), base_dir=tmp_path)

    assert datasets["pypi_downloads_daily"].row_count == 6
    assert datasets["npm_downloads_daily"].row_count == 9
    assert datasets["huggingface_models_daily"].row_count == 4
    assert datasets["github_repo_rollup_daily"].row_count == 3
    assert datasets["provider_momentum_daily"].row_count == 0
    assert all(check.title != "provider_momentum_daily is empty" for check in checks)


def _frame_for_dataset(dataset_id: str) -> pd.DataFrame:
    if dataset_id in domain_dataset_ids("rankings"):
        return _rankings_frame(dataset_id)
    mapping = {
        "app_metadata_snapshots": _apps_metadata_frame,
        "app_usage_daily": _apps_usage_frame,
        "app_top_models_daily_snapshot": _apps_top_models_frame,
        "apps_global_ranking_snapshots": _apps_global_ranking_frame,
        "apps_trending_snapshots": _apps_trending_frame,
        "github_trending_daily": lambda: _github_trending_frame("github_trending_daily"),
        "github_trending_weekly": lambda: _github_trending_frame("github_trending_weekly"),
        "github_trending_monthly": lambda: _github_trending_frame("github_trending_monthly"),
        "pypi_downloads_daily": _provider_pypi_frame,
        "npm_downloads_daily": _provider_npm_frame,
        "huggingface_models_daily": _provider_hf_frame,
        "github_repo_candidates_daily": _provider_candidates_frame,
        "github_provider_signals_daily": _provider_signals_frame,
        "github_repo_rollup_daily": _provider_rollup_frame,
        "github_provider_adoption_daily": _provider_github_adoption_frame,
        "provider_momentum_daily": _provider_momentum_frame,
    }
    if dataset_id in mapping:
        return mapping[dataset_id]()

    row = _base_row(dataset_id)
    row.update(
        {
            "month": "2026-04",
            "nand_regime_label": "tightening",
            "dram_regime_label": "stable",
            "fred_ppi_value": 100.0,
            "fred_ppi_mom_pct": 2.5,
            "fred_ppi_3m_trend": 99.0,
            "ppi_component_pcu33443344_rebased": 100.0,
            "ppi_component_pcu33423342_rebased": 101.0,
            "ppi_component_pcu335313335313_rebased": 102.0,
            "ppi_component_pcu334111334111_rebased": 103.0,
            "ppi_component_pcu3341123341121_rebased": 104.0,
            "image_url": "https://example.test/memory.png",
            "local_path": "/tmp/memory.png",
            "image_type": "marketwatch",
            "model_id": "openai/gpt-4.1",
            "name": "GPT-4.1",
            "organization": "OpenAI",
            "release_date": "2026-04-01",
            "gpqa": 0.5,
            "swe_bench": 0.4,
            "context_window": 128000,
            "snapshot_ts": "2026-04-05T00:00:00Z",
            "pricing_prompt": 0.000002,
            "pricing_completion": 0.000004,
            "context_length": 128000,
            "top_provider_id": "openai",
            "instance_type_name": "gpu_1x_a100_sxm4",
            "gpu_type": "A100",
            "gpu_count": 1,
            "region": "us-east-1",
            "availability_zone": "us-east-1a",
            "instance_type": "p5.48xlarge",
            "spot_price": 12.34,
            "price_timestamp": "2026-04-05T00:00:00Z",
        }
    )
    return pd.DataFrame([row], columns=EXPECTED_COLUMNS)


def test_expected_columns_are_unique() -> None:
    assert len(EXPECTED_COLUMNS) == len(set(EXPECTED_COLUMNS))


def test_openrouter_analytical_schemas_cover_registry_contracts() -> None:
    for dataset_id, columns in OPENROUTER_LOAD_COLUMNS.items():
        assert len(columns) == len(set(columns)), dataset_id
        required = {
            *DATASET_REGISTRY[dataset_id]["required_columns"],
        }
        if DATASET_REGISTRY[dataset_id].get("requires_core_provenance", True):
            required.update({"dataset_id", "source_url", "source_run_id", "scraped_at"})
        assert required.issubset(columns), dataset_id


def test_load_dataset_prefers_parquet(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "openrouter"
    root.mkdir(parents=True)
    frame = _rankings_frame("top_models")
    frame.to_csv(root / "top_models.csv", index=False)
    updated = frame.copy()
    updated.loc[0, "metric_value"] = 999.0
    updated.to_parquet(root / "top_models.parquet", index=False)

    result = load_dataset("top_models", base_dir=tmp_path)

    assert result.source_format == "parquet"
    assert result.row_count == 2
    assert float(result.frame.iloc[0]["metric_value"]) == 999.0


def test_provider_adoption_loader_prunes_unneeded_parquet_columns(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "provider_adoption"
    root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "dataset_id": "huggingface_models_daily",
                "source_url": "fixture://hf",
                "source_run_id": "run-hf",
                "scraped_at": "2026-06-30T00:00:00Z",
                "provider": "openai",
                "provider_display_name": "OpenAI",
                "author": "openai",
                "model_id": "openai/gpt-test",
                "download_date": "2026-06-30",
                "hf_downloads_30d": 100,
                "hf_downloads_all_time": 1000,
                "hf_downloads_daily_est": 10,
                "hf_likes": 5,
                "hf_last_modified": "2026-06-29T00:00:00Z",
                "repo_full_name": "heavy/detail-column",
                "pricing_prompt": 0.123,
            }
        ]
    ).to_parquet(root / "huggingface_models_daily.parquet", index=False)

    result = load_dataset("huggingface_models_daily", base_dir=tmp_path)

    assert result.row_count == 1
    assert "hf_downloads_30d" in result.frame.columns
    assert "provider_display_name" in result.frame.columns
    assert "repo_full_name" not in result.frame.columns
    assert "pricing_prompt" not in result.frame.columns


def test_openrouter_loader_uses_compact_dataset_schema_and_arrow_strings(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "openrouter"
    root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "dataset_id": "provider_daily_activity",
                "source_url": "fixture://provider-activity",
                "source_run_id": "run-provider",
                "scraped_at": "2026-07-18T00:00:00Z",
                "usage_date": "2026-07-17",
                "model_permaslug": "openai/gpt-test",
                "entity_id": "openai",
                "entity_name": "OpenAI",
                "category_slug": "all",
                "total_tokens": 1234,
                "prompt_tokens": 800,
                "completion_tokens": 434,
                "reasoning_tokens": 0,
                "request_count": 12,
                # Deliberately present in the storage union but not consumed by
                # the provider-activity analytical contract.
                "description": "unused wide storage column",
            }
        ]
    ).to_parquet(root / "provider_daily_activity.parquet", index=False)

    result = load_dataset("provider_daily_activity", base_dir=tmp_path)

    assert result.row_count == 1
    assert list(result.frame.columns) == OPENROUTER_LOAD_COLUMNS["provider_daily_activity"]
    assert "description" not in result.frame.columns
    assert result.frame.iloc[0]["total_tokens"] == 1234
    assert isinstance(result.frame["model_permaslug"].dtype, pd.StringDtype)
    assert result.frame["model_permaslug"].dtype.storage == "pyarrow"


def test_openrouter_derived_registry_uses_compact_mart_projection() -> None:
    assert dataset_source_for_domain("openrouter_derived") == "marts"
    assert DOMAIN_ORDER["openrouter_derived"] == [
        "openrouter_usage_economics_daily",
        "openrouter_workload_intensity_models",
    ]
    assert len(OPENROUTER_LOAD_COLUMNS["openrouter_usage_economics_daily"]) < 30
    assert len(OPENROUTER_LOAD_COLUMNS["openrouter_workload_intensity_models"]) < 25
    assert "openrouter_derived" in section_domains("OpenRouter Intelligence")
    assert "openrouter_derived" not in section_domains("OpenRouter Models")
    assert "openrouter_derived" not in section_domains("OpenRouter Workloads")


def test_openrouter_derived_marts_load_only_compact_projected_schemas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mart_root = tmp_path / "data" / "normalized" / "marts"
    mart_root.mkdir(parents=True)
    rows = {
        "openrouter_usage_economics_daily": {
            "dataset_id": "openrouter_usage_economics_daily",
            "source_url": "fixture://activity",
            "source_run_id": "derived-run",
            "scraped_at": "2026-07-18T00:00:00Z",
            "usage_date": "2026-07-17",
            "metric_id": "total_tokens_per_request",
            "cohort_id": "all_models",
            "value": 120.0,
            "numerator": 1200.0,
            "denominator": 10.0,
            "rolling_window_days": 7,
            "benchmark_snapshot_date": "2026-07-16",
            "pricing_snapshot_date": "2026-07-16",
            "expected_family_count": 5,
            "priced_family_count": 5,
            "observed_family_count": 4,
            "observed_model_count": 7,
            "included_tokens": 1200.0,
            "excluded_free_tokens": 0.0,
            "excluded_unpriced_tokens": 0.0,
            "excluded_zero_request_rows": 0.0,
            "pricing_join_status": "as_recorded_pricing",
            "methodology_version": "openrouter-derived-v1",
        },
        "openrouter_workload_intensity_models": {
            "window_start_date": "2026-06-18",
            "window_end_date": "2026-07-17",
            "model_id": "openai/gpt-test",
            "company_id": "openai",
            "total_tokens": 1200.0,
            "prompt_tokens": 900.0,
            "completion_tokens": 300.0,
            "request_count": 10,
            "token_share": 0.75,
            "request_share": 0.5,
            "tokens_per_request": 120.0,
            "intensity_ratio": 1.5,
            "model_match_status": "canonical",
            "methodology_version": "openrouter-derived-v1",
        },
    }
    remote_payloads: dict[str, bytes] = {}
    for dataset_id, row in rows.items():
        frame = pd.DataFrame([{**row, "unused_raw_payload": "x" * 10_000}])
        path = mart_root / f"{dataset_id}.parquet"
        frame.to_parquet(path, index=False)
        remote_payloads[
            f"data/normalized/marts/{dataset_id}.parquet"
        ] = path.read_bytes()

    local = load_domain_datasets("openrouter_derived", base_dir=tmp_path)

    assert set(local) == set(rows)
    for dataset_id, result in local.items():
        assert list(result.frame.columns) == OPENROUTER_LOAD_COLUMNS[dataset_id]
        assert result.missing_columns == []
        assert "unused_raw_payload" not in result.frame.columns
        assert result.source_path == mart_root / f"{dataset_id}.parquet"

    fetched_paths: list[str] = []

    def fetch_mart_bytes(path: str, sha: str) -> bytes | None:
        assert sha == "derived-sha"
        fetched_paths.append(path)
        return remote_payloads.get(path)

    monkeypatch.setattr("dashboard.data.remote.remote_enabled", lambda: True)
    monkeypatch.setattr("dashboard.data.remote.fetch_bytes", fetch_mart_bytes)

    remote_datasets = load_domain_datasets(
        "openrouter_derived", data_sha="derived-sha"
    )

    assert fetched_paths == [
        "data/normalized/marts/openrouter_usage_economics_daily.parquet",
        "data/normalized/marts/openrouter_workload_intensity_models.parquet",
    ]
    assert all("data/raw/" not in path for path in fetched_paths)
    for dataset_id, result in remote_datasets.items():
        assert list(result.frame.columns) == OPENROUTER_LOAD_COLUMNS[dataset_id]
        assert result.missing_columns == []


def test_unprojected_legacy_dataset_keeps_stored_schema_without_global_padding(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "llm_benchmarks"
    root.mkdir(parents=True)
    stored = pd.DataFrame(
        [
            {
                "dataset_id": "llm_benchmarks",
                "source_url": "fixture://benchmarks",
                "source_run_id": "run-benchmarks",
                "scraped_at": "2026-07-18T00:00:00Z",
                "model_id": "model-a",
                "name": "Model A",
                "organization": "Lab A",
                "release_date": "2026-07-01",
                "gpqa": 0.8,
                "swe_bench": 0.7,
                "context_window": 128000,
            }
        ]
    )
    stored.to_parquet(root / "llm_benchmarks.parquet", index=False)

    result = load_dataset("llm_benchmarks", base_dir=tmp_path)

    assert list(result.frame.columns) == list(stored.columns)
    assert "tokens" not in result.frame.columns
    assert len(result.frame.columns) < len(EXPECTED_COLUMNS)


def test_projected_loader_survives_new_column_before_dataset_migration(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "openrouter_official"
    root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "dataset_id": "official_legacy_reconciliation",
                "usage_date": "2026-07-17",
                "official_total_tokens": 1000,
                "official_named_tokens": 800,
                "official_other_tokens": 200,
                "source_run_id": "run-1",
                "scraped_at": "2026-07-18T00:00:00Z",
                # source_url intentionally represents the previous schema.
            }
        ]
    ).to_parquet(root / "official_legacy_reconciliation.parquet", index=False)

    result = load_dataset("official_legacy_reconciliation", base_dir=tmp_path)

    assert result.row_count == 1
    assert result.frame.iloc[0]["official_total_tokens"] == 1000
    assert "source_url" in result.missing_columns


def test_load_dataset_falls_back_to_csv_for_app_dataset(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "openrouter"
    root.mkdir(parents=True)
    _apps_usage_frame().to_csv(root / "app_usage_daily.csv", index=False)

    result = load_dataset("app_usage_daily", base_dir=tmp_path)

    assert result.source_format == "csv"
    assert result.latest_date == "2026-04-04"
    assert result.duplicate_rows == 0
    assert result.domain == "apps"


def test_checks_flag_missing_and_duplicate_data_across_domains(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "openrouter"
    root.mkdir(parents=True)
    rankings = _rankings_frame("top_models")
    duplicated = pd.concat([rankings, rankings.iloc[[0]]], ignore_index=True)
    duplicated.to_csv(root / "top_models.csv", index=False)
    _apps_usage_frame().to_csv(root / "app_usage_daily.csv", index=False)

    datasets = load_all_datasets(base_dir=tmp_path)
    freshness = load_latest_manifest(base_dir=tmp_path)
    checks = run_checks(datasets, freshness, base_dir=tmp_path)
    titles = [check.title for check in checks]

    assert "Missing datasets" in titles
    assert "top_models duplicate natural keys" in titles
    assert "categories_programming is empty" in titles
    assert "apps_trending_snapshots is empty" in titles


def test_checks_only_report_missing_files_for_provided_domain_dataset_subset(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "openrouter"
    root.mkdir(parents=True)
    _rankings_frame("top_models").to_csv(root / "top_models.csv", index=False)

    datasets = load_domain_datasets("rankings", base_dir=tmp_path)
    freshness = load_latest_manifest(base_dir=tmp_path)
    checks = run_checks(datasets, freshness, base_dir=tmp_path)

    missing = [check for check in checks if check.title == "Missing datasets"]
    assert len(missing) == 1
    assert "market_share" in missing[0].detail
    assert "app_usage_daily" not in missing[0].detail
    assert "raw_openrouter_models" not in missing[0].detail


def test_checks_only_report_missing_files_for_empty_provided_domain_dataset_subset(tmp_path: Path) -> None:
    freshness = load_latest_manifest(base_dir=tmp_path)
    checks = run_checks({}, freshness, base_dir=tmp_path, expected_dataset_ids=domain_dataset_ids("rankings"))

    missing = [check for check in checks if check.title == "Missing datasets"]
    assert len(missing) == 1
    assert "top_models" in missing[0].detail
    assert "market_share" in missing[0].detail
    assert "app_usage_daily" not in missing[0].detail
    assert "raw_openrouter_models" not in missing[0].detail


def test_load_domain_state_cached_supports_legacy_run_checks_signature(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def legacy_run_checks(datasets, freshness, base_dir=None):
        captured["datasets"] = datasets
        captured["freshness"] = freshness
        captured["base_dir"] = base_dir
        return []

    monkeypatch.setattr(dashboard_app, "run_checks", legacy_run_checks)

    datasets, freshness, checks = load_domain_state_cached.__wrapped__(
        tmp_path,
        "rankings",
        build_domain_signature(tmp_path, "rankings"),
    )

    assert checks == []
    assert captured["datasets"] == datasets
    assert captured["freshness"] == freshness
    assert captured["base_dir"] == tmp_path


def test_load_latest_manifest_reads_latest_run(tmp_path: Path) -> None:
    raw_root = tmp_path / "data" / "raw" / "openrouter" / "20260404T120606Z-ef7072ee"
    raw_root.mkdir(parents=True)
    payload = {
        "run_id": "20260404T120606Z-ef7072ee",
        "scraped_at": "2026-04-04T12:06:06Z",
    }
    (raw_root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    freshness = load_latest_manifest(base_dir=tmp_path)

    assert freshness.latest_run_id == payload["run_id"]
    assert freshness.latest_manifest_scraped_at == payload["scraped_at"]


def test_load_latest_manifest_can_skip_raw_manifest_scan_when_datasets_provided(tmp_path: Path) -> None:
    raw_root = tmp_path / "data" / "raw" / "openrouter" / "20260404T120606Z-ef7072ee"
    raw_root.mkdir(parents=True)
    (raw_root / "manifest.json").write_text(
        json.dumps({"run_id": "raw-run", "scraped_at": "2026-04-04T12:06:06Z"}),
        encoding="utf-8",
    )
    result = DatasetLoadResult(
        dataset_id="top_models",
        label="Top Models",
        domain="rankings",
        primary_date_column="week_start_date",
        metric_column="metric_value",
        frame=pd.DataFrame(),
        source_format="csv",
        source_path=tmp_path / "data" / "normalized" / "openrouter" / "top_models.csv",
        missing_columns=[],
        duplicate_rows=0,
        first_date="2026-04-01",
        latest_date="2026-04-01",
        latest_scraped_at="2026-04-05T00:00:00Z",
        row_count=1,
    )

    freshness = load_latest_manifest(base_dir=tmp_path, datasets={"top_models": result}, scan_raw_manifests=False)

    assert freshness.latest_scraped_at == "2026-04-05T00:00:00Z"
    assert freshness.latest_run_id is None
    assert freshness.latest_manifest_path is None


def test_section_domains_loads_only_selected_dashboard_inputs() -> None:
    assert section_domains("Overview") == ("overview",)
    assert section_domains("OpenRouter Intelligence") == (
        "openrouter_intelligence", "compute_availability", "openrouter_official_market", "openrouter_derived",
    )
    assert section_domains("OpenRouter Models") == (
        "openrouter_model_explorer", "openrouter_catalog",
    )
    assert section_domains("OpenRouter Workloads") == ("openrouter_workloads", "apps")
    assert section_domains("Provider Adoption") == ("provider_adoption",)
    assert section_domains("Artificial Analysis") == ("artificial_analysis",)
    assert section_domains("Semiconductor Analysis") == (
        "semiconductor_memory",
        "semiconductor_proxies",
        "taiwan_semiconductor_revenue",
    )


def test_load_all_datasets_supports_every_registered_dataset(tmp_path: Path) -> None:
    for dataset_id in DATASET_REGISTRY:
        domain = DATASET_REGISTRY[dataset_id]["domain"]
        source = dataset_source_for_domain(str(domain))
        root = tmp_path / "data" / "normalized" / source
        root.mkdir(parents=True, exist_ok=True)
        _frame_for_dataset(dataset_id).to_csv(root / f"{dataset_id}.csv", index=False)

    datasets = load_all_datasets(base_dir=tmp_path)

    assert set(datasets) == set(DATASET_REGISTRY)
    assert datasets["apps_global_ranking_snapshots"].latest_date == "2026-04-05"
    assert datasets["top_models"].latest_date == "2026-03-16"
    assert datasets["provider_momentum_daily"].latest_date == "2026-04-05"


def test_provider_adoption_domain_loads_gold_github_table_not_repo_detail(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "provider_adoption"
    root.mkdir(parents=True, exist_ok=True)
    _provider_pypi_frame().to_csv(root / "pypi_downloads_daily.csv", index=False)
    _provider_npm_frame().to_csv(root / "npm_downloads_daily.csv", index=False)
    _provider_hf_frame().to_csv(root / "huggingface_models_daily.csv", index=False)
    _provider_github_adoption_frame().to_csv(root / "github_provider_adoption_daily.csv", index=False)
    _provider_momentum_frame().to_csv(root / "provider_momentum_daily.csv", index=False)
    _provider_candidates_frame().to_csv(root / "github_repo_candidates_daily.csv", index=False)
    _provider_signals_frame().to_csv(root / "github_provider_signals_daily.csv", index=False)
    _provider_rollup_frame().to_csv(root / "github_repo_rollup_daily.csv", index=False)

    datasets = load_domain_datasets("provider_adoption", base_dir=tmp_path)

    assert "github_provider_adoption_daily" in datasets
    assert "github_repo_candidates_daily" not in datasets
    assert "github_repo_rollup_daily" not in datasets
    assert "github_provider_signals_daily" not in datasets
    assert sum(result.row_count for result in datasets.values()) < 100


def test_compute_provider_adoption_views_includes_hf_aggregates_and_latest_models(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "provider_adoption"
    root.mkdir(parents=True, exist_ok=True)
    _provider_pypi_frame().to_csv(root / "pypi_downloads_daily.csv", index=False)
    _provider_npm_frame().to_csv(root / "npm_downloads_daily.csv", index=False)
    _provider_hf_frame().to_csv(root / "huggingface_models_daily.csv", index=False)
    _provider_github_adoption_frame().to_csv(root / "github_provider_adoption_daily.csv", index=False)
    _provider_momentum_frame().to_csv(root / "provider_momentum_daily.csv", index=False)

    datasets = load_domain_datasets("provider_adoption", base_dir=tmp_path)
    views = compute_provider_adoption_views(datasets)

    assert views["latest_hf_date"] == "2026-04-06"
    assert sorted(views["latest_hf"]["provider_display_name"].tolist()) == ["Anthropic", "OpenAI"]
    latest_hf_models = views["latest_hf_models"]
    assert set(latest_hf_models["model_id"]) == {"openai/gpt-oss-120b", "anthropic/claude-lite"}
    openai_row = latest_hf_models[latest_hf_models["provider_display_name"] == "OpenAI"].iloc[0]
    assert float(openai_row["hf_downloads_daily_est"]) == 200.0


def test_compute_provider_adoption_views_rollup_daily_counts_only_signal_bearing_repos(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "provider_adoption"
    root.mkdir(parents=True, exist_ok=True)
    _provider_pypi_frame().to_csv(root / "pypi_downloads_daily.csv", index=False)
    _provider_npm_frame().to_csv(root / "npm_downloads_daily.csv", index=False)
    _provider_hf_frame().to_csv(root / "huggingface_models_daily.csv", index=False)
    _provider_github_adoption_frame().to_csv(root / "github_provider_adoption_daily.csv", index=False)
    _provider_momentum_frame().to_csv(root / "provider_momentum_daily.csv", index=False)

    datasets = load_domain_datasets("provider_adoption", base_dir=tmp_path)
    views = compute_provider_adoption_views(datasets)

    rollup_daily = views["rollup_daily"].sort_values(["signal_date", "provider_display_name"]).reset_index(drop=True)
    candidates_daily = views["candidates_daily"].sort_values(["repo_created_date"]).reset_index(drop=True)

    openai_rollup = rollup_daily[rollup_daily["provider_display_name"] == "OpenAI"].iloc[0]
    assert int(openai_rollup["signal_repos"]) == 1
    assert int(openai_rollup["manifest_repos"]) == 1
    assert int(openai_rollup["import_repos"]) == 1
    assert int(openai_rollup["model_repos"]) == 1

    assert list(candidates_daily.columns) == ["repo_created_date", "repo_candidates"]
    assert int(candidates_daily.iloc[0]["repo_candidates"]) == 600
    assert int(views["latest_github_candidate_count"]) == 600


def test_provider_adoption_parquet_only_repo_detail_datasets_remain_dashboard_compatible(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "provider_adoption"
    root.mkdir(parents=True, exist_ok=True)
    _provider_pypi_frame().to_csv(root / "pypi_downloads_daily.csv", index=False)
    _provider_npm_frame().to_csv(root / "npm_downloads_daily.csv", index=False)
    _provider_hf_frame().to_csv(root / "huggingface_models_daily.csv", index=False)
    _provider_github_adoption_frame().to_csv(root / "github_provider_adoption_daily.csv", index=False)
    _provider_momentum_frame().to_csv(root / "provider_momentum_daily.csv", index=False)
    _provider_signals_frame().to_csv(root / "github_provider_signals_daily.csv", index=False)
    _provider_candidates_frame().to_parquet(root / "github_repo_candidates_daily.parquet", index=False)
    _provider_rollup_frame().to_parquet(root / "github_repo_rollup_daily.parquet", index=False)

    candidates_result = load_dataset("github_repo_candidates_daily", base_dir=tmp_path)
    rollup_result = load_dataset("github_repo_rollup_daily", base_dir=tmp_path)
    datasets = load_domain_datasets("provider_adoption", base_dir=tmp_path)
    views = compute_provider_adoption_views(datasets)

    assert candidates_result.source_format == "parquet"
    assert rollup_result.source_format == "parquet"
    assert candidates_result.row_count == 3
    assert rollup_result.row_count == 3
    assert int(views["latest_github_candidate_count"]) == 600
    openai_rollup = views["rollup_daily"][views["rollup_daily"]["provider_display_name"] == "OpenAI"].iloc[0]
    assert int(openai_rollup["signal_repos"]) == 1
    assert int(openai_rollup["manifest_repos"]) == 1


def test_compute_semiconductor_views_exposes_proxy_and_component_columns() -> None:
    frame = pd.DataFrame(
        [
            {
                **_base_row("semiconductor_memory_regime_monthly"),
                "month": "2026-02",
                "fred_ppi_value": 100.0,
                "fred_ppi_mom_pct": 1.2,
                "fred_ppi_3m_trend": 99.5,
                "ppi_component_pcu33443344_rebased": 100.0,
                "ppi_component_pcu33423342_rebased": 100.0,
                "ppi_component_pcu335313335313_rebased": 100.0,
                "ppi_component_pcu334111334111_rebased": 100.0,
                "ppi_component_pcu3341123341121_rebased": 100.0,
            },
            {
                **_base_row("semiconductor_memory_regime_monthly"),
                "month": "2026-03",
                "fred_ppi_value": 103.0,
                "fred_ppi_mom_pct": 3.0,
                "fred_ppi_3m_trend": 101.5,
                "ppi_component_pcu33443344_rebased": 104.0,
                "ppi_component_pcu33423342_rebased": 102.0,
                "ppi_component_pcu335313335313_rebased": 101.0,
                "ppi_component_pcu334111334111_rebased": 99.0,
                "ppi_component_pcu3341123341121_rebased": 98.0,
            },
            {
                **_base_row("semiconductor_memory_regime_monthly"),
                "month": "2026-04",
                "fred_ppi_value": None,
                "fred_ppi_mom_pct": None,
                "fred_ppi_3m_trend": None,
                "ppi_component_pcu33443344_rebased": None,
                "ppi_component_pcu33423342_rebased": None,
                "ppi_component_pcu335313335313_rebased": None,
                "ppi_component_pcu334111334111_rebased": None,
                "ppi_component_pcu3341123341121_rebased": None,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )

    result = compute_semiconductor_views(
        {
            "semiconductor_memory_regime_monthly": DatasetLoadResult(
                dataset_id="semiconductor_memory_regime_monthly",
                label="Semiconductor Market Regimes",
                domain="semiconductor_memory",
                primary_date_column="month",
                metric_column="fred_ppi_value",
                frame=frame,
                source_format="csv",
                source_path=None,
                missing_columns=[],
                duplicate_rows=0,
                first_date="2026-02",
                row_count=len(frame),
                latest_date="2026-04",
                latest_scraped_at="2026-04-05T00:00:00Z",
            ),
            "fred_semiconductor_ppi": DatasetLoadResult(
                dataset_id="fred_semiconductor_ppi",
                label="FRED Semiconductor PPI",
                domain="semiconductor_memory",
                primary_date_column="date",
                metric_column="value",
                frame=pd.DataFrame(
                    [
                        {
                            **_base_row("fred_semiconductor_ppi"),
                            "date": "2026-03-01",
                            "series_id": "PCU33443344",
                            "series_name": "Semiconductors and Other Electronic Components",
                            "value": 1.0,
                        },
                        {
                            **_base_row("fred_semiconductor_ppi"),
                            "date": "2026-04-01",
                            "series_id": "PCU33443344",
                            "series_name": "Semiconductors and Other Electronic Components",
                            "value": 1.1,
                        },
                    ],
                    columns=EXPECTED_COLUMNS,
                ),
                source_format="csv",
                source_path=None,
                missing_columns=[],
                duplicate_rows=0,
                first_date="2026-03-01",
                latest_date="2026-04-01",
                latest_scraped_at="2026-04-05T00:00:00Z",
                row_count=2,
            ),
        }
    )

    assert result["latest_month"] == "2026-04"
    assert result["base_month"] == "2026-02"
    assert result["latest_proxy_month"] == "2026-03"
    assert result["latest_fred_month"] == "2026-04"
    assert len(result["component_columns"]) == 5
    assert list(result["proxy_df"]["month"]) == ["2026-02", "2026-03"]


def test_compute_semiconductor_views_ppi_survives_collapsed_regime_table() -> None:
    # Regime table collapsed to a single ADATA-only row with a null PPI (the exact
    # failure mode that blanked the panel). The dedicated FRED-only PPI table must
    # keep the panel populated.
    regime_frame = pd.DataFrame(
        [
            {
                **_base_row("semiconductor_memory_regime_monthly"),
                "month": "2026-06",
                "nand_regime_label": "stable",
                "dram_regime_label": "stable",
                "fred_ppi_value": None,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )
    ppi_frame = pd.DataFrame(
        [
            {
                **_base_row("fred_semiconductor_ppi_monthly"),
                "month": "2026-04",
                "fred_ppi_value": 100.0,
                "fred_ppi_mom_pct": 1.0,
                "fred_ppi_3m_trend": 99.0,
                "ppi_component_pcu33443344_rebased": 100.0,
                "ppi_component_pcu33423342_rebased": 100.0,
                "ppi_component_pcu335313335313_rebased": 100.0,
                "ppi_component_pcu334111334111_rebased": 100.0,
                "ppi_component_pcu3341123341121_rebased": 100.0,
            },
            {
                **_base_row("fred_semiconductor_ppi_monthly"),
                "month": "2026-05",
                "fred_ppi_value": 103.0,
                "fred_ppi_mom_pct": 3.0,
                "fred_ppi_3m_trend": 101.5,
                "ppi_component_pcu33443344_rebased": 104.0,
                "ppi_component_pcu33423342_rebased": 102.0,
                "ppi_component_pcu335313335313_rebased": 101.0,
                "ppi_component_pcu334111334111_rebased": 99.0,
                "ppi_component_pcu3341123341121_rebased": 98.0,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )

    def _result(dataset_id: str, frame: pd.DataFrame, latest: str) -> DatasetLoadResult:
        return DatasetLoadResult(
            dataset_id=dataset_id,
            label=dataset_id,
            domain="semiconductor_memory",
            primary_date_column="month",
            metric_column="fred_ppi_value",
            frame=frame,
            source_format="csv",
            source_path=None,
            missing_columns=[],
            duplicate_rows=0,
            first_date=str(frame["month"].min()),
            row_count=len(frame),
            latest_date=latest,
            latest_scraped_at="2026-06-05T00:00:00Z",
        )

    result = compute_semiconductor_views(
        {
            "semiconductor_memory_regime_monthly": _result(
                "semiconductor_memory_regime_monthly", regime_frame, "2026-06"
            ),
            "fred_semiconductor_ppi_monthly": _result(
                "fred_semiconductor_ppi_monthly", ppi_frame, "2026-05"
            ),
        }
    )

    assert list(result["proxy_df"]["month"]) == ["2026-04", "2026-05"]
    assert result["base_month"] == "2026-04"
    assert result["latest_proxy_month"] == "2026-05"
    assert result["latest_proxy_data"]["fred_ppi_value"] == 103.0
    assert len(result["component_columns"]) == 5


def test_compute_semiconductor_views_includes_tiered_official_backup_and_production_data() -> None:
    official_frame = pd.DataFrame(
        [
            {
                **_base_row("semiconductor_official_monthly"),
                "source_region": "korea",
                "country_name": "South Korea",
                "metric_type": "exports",
                "flow_code": "X",
                "partner_scope": "world",
                "period": "2026-03",
                "release_date": "2026-04-15",
                "expected_release_window_days": 21,
                "lag_days": 15,
                "category_id": "ic_only",
                "category_label": "IC-only",
                "classification_system": "HS",
                "classification_code": "8542",
                "unit": "usd",
                "currency": "USD",
                "value": 12500000000.0,
                "comparison_gap_pct": 6.5,
                "is_official_primary": True,
                "source_name": "Korea Customs Service",
                "parser_version": "test-v1",
            },
            {
                **_base_row("semiconductor_official_monthly"),
                "source_region": "china",
                "country_name": "China",
                "metric_type": "production",
                "flow_code": "",
                "partner_scope": "domestic",
                "period": "2026-03",
                "release_date": "2026-04-17",
                "expected_release_window_days": 20,
                "lag_days": 17,
                "category_id": "ic_only",
                "category_label": "IC-only",
                "classification_system": "NBS",
                "classification_code": "A02092C",
                "unit": "100m_pieces",
                "currency": "",
                "value": 350.0,
                "is_official_primary": True,
                "source_name": "NBS",
                "parser_version": "test-v1",
            },
        ],
        columns=EXPECTED_COLUMNS,
    )
    backup_frame = pd.DataFrame(
        [
            {
                **_base_row("semiconductor_backup_check_monthly"),
                "source_region": "korea",
                "country_name": "South Korea",
                "metric_type": "exports",
                "flow_code": "X",
                "partner_scope": "world",
                "period": "2026-03",
                "release_date": "2026-04-30",
                "expected_release_window_days": 45,
                "lag_days": 30,
                "category_id": "ic_only",
                "category_label": "IC-only",
                "classification_system": "HS",
                "classification_code": "8542",
                "unit": "usd",
                "currency": "USD",
                "value": 11700000000.0,
                "comparison_gap_pct": 6.5,
                "is_official_primary": False,
                "source_name": "UN Comtrade",
                "parser_version": "test-v1",
            }
        ],
        columns=EXPECTED_COLUMNS,
    )

    result = compute_semiconductor_views(
        {
            "semiconductor_official_monthly": DatasetLoadResult(
                dataset_id="semiconductor_official_monthly",
                label="Semiconductor Official Monthly",
                domain="semiconductor_proxies",
                primary_date_column="period",
                metric_column="value",
                frame=official_frame,
                source_format="parquet",
                source_path=None,
                missing_columns=[],
                duplicate_rows=0,
                first_date="2026-03",
                row_count=len(official_frame),
                latest_date="2026-03",
                latest_scraped_at="2026-03-15T00:00:00Z",
            ),
            "semiconductor_backup_check_monthly": DatasetLoadResult(
                dataset_id="semiconductor_backup_check_monthly",
                label="Semiconductor Backup Check Monthly",
                domain="semiconductor_proxies",
                primary_date_column="period",
                metric_column="value",
                frame=backup_frame,
                source_format="parquet",
                source_path=None,
                missing_columns=[],
                duplicate_rows=0,
                first_date="2026-03",
                row_count=len(backup_frame),
                latest_date="2026-03",
                latest_scraped_at="2026-03-15T00:00:00Z",
            ),
            "semiconductor_source_catalog": DatasetLoadResult(
                dataset_id="semiconductor_source_catalog",
                label="Semiconductor Source Catalog",
                domain="semiconductor_proxies",
                primary_date_column="latest_period",
                metric_column=None,
                frame=pd.DataFrame(
                    [
                        {
                            **_base_row("semiconductor_source_catalog"),
                            "source_region": "korea",
                            "country_name": "South Korea",
                            "source_name": "Korea Customs Service",
                            "source_tier": "official",
                            "metric_type": "exports",
                            "category_id": "ic_only",
                            "category_label": "IC-only",
                            "coverage_start": "2025-01",
                            "latest_period": "2026-03",
                            "cadence": "monthly",
                            "expected_release_window_days": 21,
                            "default_unit": "usd",
                            "default_currency": "USD",
                            "is_official_primary": True,
                            "notes": "Fixture catalog row",
                        }
                    ],
                    columns=EXPECTED_COLUMNS,
                ),
                source_format="parquet",
                source_path=None,
                missing_columns=[],
                duplicate_rows=0,
                first_date="2026-03",
                row_count=1,
                latest_date="2026-03",
                latest_scraped_at="2026-03-15T00:00:00Z",
            ),
        }
    )

    assert not result["official_df"].empty
    assert not result["backup_df"].empty
    assert not result["production_df"].empty
    korea_official = result["official_df"][result["official_df"]["source_region"] == "korea"].iloc[0]
    assert korea_official["value"] == 12500000000.0
    assert result["backup_df"].iloc[0]["comparison_gap_pct"] == 6.5
    assert result["production_df"].iloc[0]["value"] == 350.0
    assert result["latest_official_period"] == "2026-03"


def test_compute_semiconductor_views_includes_taiwan_monthly_revenue() -> None:
    taiwan_frame = pd.DataFrame(
        [
            {
                **_base_row("tw_monthly_revenue"),
                "company_code": "2330",
                "company_name": "台積電",
                "market": "TWSE",
                "industry": "Foundry",
                "filing_date": "2026-06-10",
                "revenue_month": "2026-05",
                "monthly_revenue_ntd": 416975163.0,
                "yoy_pct": 30.09,
                "ytd_revenue_ntd": 1961803721.0,
                "ytd_yoy_pct": 29.98,
            },
            {
                **_base_row("tw_monthly_revenue"),
                "company_code": "2303",
                "company_name": "聯電",
                "market": "TWSE",
                "industry": "Foundry",
                "filing_date": "2026-06-10",
                "revenue_month": "2026-05",
                "monthly_revenue_ntd": 22943755.0,
                "yoy_pct": 17.78,
                "ytd_revenue_ntd": 106645602.0,
                "ytd_yoy_pct": 9.05,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )

    result = compute_semiconductor_views(
        {
            "tw_monthly_revenue": DatasetLoadResult(
                dataset_id="tw_monthly_revenue",
                label="Taiwan Monthly Revenue",
                domain="taiwan_semiconductor_revenue",
                primary_date_column="revenue_month",
                metric_column="monthly_revenue_ntd",
                frame=taiwan_frame,
                source_format="parquet",
                source_path=None,
                missing_columns=[],
                duplicate_rows=0,
                first_date="2026-05",
                row_count=len(taiwan_frame),
                latest_date="2026-05",
                latest_scraped_at="2026-06-10T00:00:00Z",
            )
        }
    )

    assert result["latest_taiwan_revenue_month"] == "2026-05"
    assert list(result["latest_taiwan_revenue"]["company_code"]) == ["2330", "2303"]
    assert float(result["taiwan_revenue_pivot"].loc["2026-05", "台積電"]) == 416975163.0
    assert float(result["taiwan_yoy_pivot"].loc["2026-05", "聯電"]) == 17.78


def test_private_panel_expected_code_uses_neutral_secret_or_env_name() -> None:
    assert _private_panel_expected_code({"PRIVATE_PANEL_ACCESS_CODE": "secret"}, {}) == "secret"
    assert _private_panel_expected_code({}, {"PRIVATE_PANEL_ACCESS_CODE": "local"}) == "local"
    assert _private_panel_expected_code({}, {}) == ""


def test_private_panel_code_matches_requires_configured_exact_match() -> None:
    assert _private_panel_code_matches("secret", "secret") is True
    assert _private_panel_code_matches("secret", "other") is False
    assert _private_panel_code_matches("secret", "") is False
    assert _private_panel_code_matches("", "secret") is False


def test_compute_semiconductor_views_preserves_empty_semiconductor_schema() -> None:
    result = compute_semiconductor_views({})

    assert "metric_type" in result["official_df"].columns
    assert "partner_scope" in result["official_df"].columns
    assert "category_id" in result["official_df"].columns
    assert "metric_type" in result["backup_df"].columns
    assert "source_tier" in result["source_catalog_df"].columns


def test_prepare_hf_models_table_returns_empty_for_all_view() -> None:
    table = prepare_hf_models_table(_provider_hf_frame(), provider_display_name="All")

    assert table.empty
    assert list(table.columns) == ["Provider", "Model", "30d Downloads", "All-Time Downloads", "Daily (Est)", "Likes", "Last Modified"]


def test_prepare_hf_models_table_limits_to_top_20_for_selected_provider() -> None:
    table = prepare_hf_models_table(_provider_hf_large_frame(), provider_display_name="Qwen", limit=20)

    assert len(table) == 20
    assert table.iloc[0]["Model"] == "Qwen/model-00"
    assert table.iloc[-1]["Model"] == "Qwen/model-19"


def test_domain_dataset_ids_returns_empty_for_unknown_domain() -> None:
    assert domain_dataset_ids("does_not_exist") == []


def test_prepare_hf_models_table_uses_all_time_as_tiebreaker() -> None:
    table = prepare_hf_models_table(_provider_hf_large_frame(), provider_display_name="OpenAI", limit=20)

    assert len(table) == 2
    assert table.iloc[0]["Model"] == "openai/tie-high"
    assert table.iloc[1]["Model"] == "openai/tie-low"


def test_prepare_hf_models_table_daily_est_sorts_nulls_last() -> None:
    table = prepare_hf_models_table(
        _provider_hf_frame(),
        provider_display_name="OpenAI",
        metric_label="Daily (Est)",
        limit=20,
    )

    assert len(table) == 2
    assert table.iloc[0]["Model"] == "openai/gpt-oss-120b"
    assert table.iloc[1]["Model"] == "openai/gpt-oss-20b"


def test_prepare_hf_models_table_all_time_uses_30d_as_tiebreaker() -> None:
    rows = []
    for model_id, downloads_30d in [("openai/tie-high-30d", 600), ("openai/tie-low-30d", 500)]:
        row = _base_row("huggingface_models_daily")
        row.update(
            {
                "provider": "openai",
                "provider_display_name": "OpenAI",
                "author": "openai",
                "model_id": model_id,
                "download_date": "2026-04-06",
                "hf_downloads_30d": downloads_30d,
                "hf_downloads_all_time": 9000,
                "hf_downloads_daily_est": 50,
                "hf_likes": 10,
                "hf_last_modified": "2026-04-06T12:00:00Z",
            }
        )
        rows.append(row)

    table = prepare_hf_models_table(
        pd.DataFrame(rows, columns=EXPECTED_COLUMNS),
        provider_display_name="OpenAI",
        metric_label="All-time",
        limit=20,
    )

    assert len(table) == 2
    assert table.iloc[0]["Model"] == "openai/tie-high-30d"
    assert table.iloc[1]["Model"] == "openai/tie-low-30d"


def test_resolve_hf_metric_config_supports_all_metric_modes() -> None:
    trailing = resolve_hf_metric_config("Trailing 30d")
    daily = resolve_hf_metric_config("Daily (Est)")
    all_time = resolve_hf_metric_config("All-time")

    assert trailing["value_column"] == "downloads_30d"
    assert trailing["models_caption_metric"] == "trailing 30d downloads"
    assert daily["value_column"] == "downloads_daily_est"
    assert daily["downloads_title"] == "Hugging Face Daily Downloads (Est)"
    assert daily["models_caption_metric"] == "estimated daily downloads"
    assert all_time["value_column"] == "downloads_all_time"
    assert all_time["models_caption_metric"] == "all-time downloads"


def test_compute_provider_adoption_views_exposes_hf_daily_est_rollups(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "provider_adoption"
    root.mkdir(parents=True, exist_ok=True)
    _provider_pypi_frame().to_csv(root / "pypi_downloads_daily.csv", index=False)
    _provider_npm_frame().to_csv(root / "npm_downloads_daily.csv", index=False)
    _provider_hf_frame().to_csv(root / "huggingface_models_daily.csv", index=False)
    _provider_github_adoption_frame().to_csv(root / "github_provider_adoption_daily.csv", index=False)
    _provider_momentum_frame().to_csv(root / "provider_momentum_daily.csv", index=False)

    datasets = load_domain_datasets("provider_adoption", base_dir=tmp_path)
    views = compute_provider_adoption_views(datasets)

    hf_grouped = views["hf_grouped"].sort_values(["download_date", "provider_display_name"]).reset_index(drop=True)
    openai_latest = hf_grouped[
        (hf_grouped["download_date"] == "2026-04-06") & (hf_grouped["provider_display_name"] == "OpenAI")
    ].iloc[0]
    anthropic_latest = hf_grouped[
        (hf_grouped["download_date"] == "2026-04-06") & (hf_grouped["provider_display_name"] == "Anthropic")
    ].iloc[0]

    assert float(openai_latest["downloads_daily_est"]) == 200.0
    assert float(anthropic_latest["downloads_daily_est"]) == 250.0


def test_dataset_source_for_domain_maps_expected_roots() -> None:
    assert dataset_source_for_domain("rankings") == "openrouter"
    assert dataset_source_for_domain("apps") == "openrouter"
    assert dataset_source_for_domain("openrouter_model_explorer") == "openrouter"
    assert dataset_source_for_domain("openrouter_catalog") == "compute_availability"
    assert dataset_source_for_domain("github") == "github_trending"
    assert dataset_source_for_domain("provider_adoption") == "provider_adoption"


def test_load_domain_datasets_only_loads_requested_domain(tmp_path: Path) -> None:
    openrouter_root = tmp_path / "data" / "normalized" / "openrouter"
    github_root = tmp_path / "data" / "normalized" / "github_trending"
    openrouter_root.mkdir(parents=True, exist_ok=True)
    github_root.mkdir(parents=True, exist_ok=True)

    _rankings_frame("top_models").to_csv(openrouter_root / "top_models.csv", index=False)
    _rankings_frame("market_share").to_csv(openrouter_root / "market_share.csv", index=False)
    _rankings_frame("categories_programming").to_csv(openrouter_root / "categories_programming.csv", index=False)
    _github_trending_frame("github_trending_daily").to_csv(github_root / "github_trending_daily.csv", index=False)

    datasets = load_domain_datasets("rankings", base_dir=tmp_path)

    assert set(datasets) == set(domain_dataset_ids("rankings"))
    assert datasets["top_models"].row_count == 2


def test_signatures_ignore_unrelated_raw_files_for_rankings(tmp_path: Path) -> None:
    normalized_openrouter = tmp_path / "data" / "normalized" / "openrouter"
    raw_provider = tmp_path / "data" / "raw" / "provider_adoption" / "run-1"
    raw_openrouter = tmp_path / "data" / "raw" / "openrouter" / "run-2"
    normalized_openrouter.mkdir(parents=True, exist_ok=True)
    raw_provider.mkdir(parents=True, exist_ok=True)
    raw_openrouter.mkdir(parents=True, exist_ok=True)

    _rankings_frame("top_models").to_csv(normalized_openrouter / "top_models.csv", index=False)
    (raw_provider / "manifest.json").write_text(json.dumps({"run_id": "provider-run", "scraped_at": "2026-04-05T00:00:00Z"}), encoding="utf-8")
    (raw_openrouter / "manifest.json").write_text(json.dumps({"run_id": "openrouter-run", "scraped_at": "2026-04-06T00:00:00Z"}), encoding="utf-8")

    normalized_sig = build_normalized_signature(tmp_path, "rankings")
    manifest_sig = build_manifest_signature(tmp_path, "rankings")
    domain_sig = build_domain_signature(tmp_path, "rankings")

    assert any("data/normalized/openrouter/top_models.csv" in item[0] for item in normalized_sig)
    assert all("provider_adoption" not in item[0] for item in normalized_sig)
    assert len(manifest_sig) == 1
    assert "data/raw/openrouter" in manifest_sig[0][0]
    assert all("provider_adoption" not in item[0] for item in domain_sig)


def test_format_scraped_at_display_formats_utc_timestamp() -> None:
    assert format_scraped_at_display("2026-04-06T08:19:47.193085Z") == "2026-04-06 08:19 UTC"


def test_rankings_week_context_detects_divergent_week_buckets(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "openrouter"
    root.mkdir(parents=True)

    top_models = _rankings_frame("top_models")
    top_models.loc[:, "week_start_date"] = ["2026-03-23", "2026-03-30"]
    top_models.loc[:, "week_label"] = top_models["week_start_date"]
    top_models.loc[:, "scraped_at"] = "2026-04-06T08:19:47.193085Z"
    top_models.to_csv(root / "top_models.csv", index=False)

    categories = _rankings_frame("categories_programming")
    categories.loc[:, "week_start_date"] = ["2026-03-23", "2026-03-30"]
    categories.loc[:, "week_label"] = categories["week_start_date"]
    categories.loc[:, "scraped_at"] = "2026-04-06T08:19:47.193085Z"
    categories.to_csv(root / "categories_programming.csv", index=False)

    market_share = _rankings_frame("market_share")
    market_share.loc[:, "week_start_date"] = ["2026-03-30", "2026-04-05"]
    market_share.loc[:, "week_label"] = market_share["week_start_date"]
    market_share.loc[:, "entity_id"] = ["openai", "anthropic"]
    market_share.loc[:, "entity_name"] = market_share["entity_id"]
    market_share.loc[:, "parent_entity_id"] = pd.NA
    market_share.loc[:, "parent_entity_name"] = pd.NA
    market_share.loc[:, "scraped_at"] = "2026-04-06T08:19:47.193085Z"
    market_share.to_csv(root / "market_share.csv", index=False)

    datasets = load_all_datasets(base_dir=tmp_path)
    context = rankings_week_context(datasets)

    assert context["model_week"] == "2026-03-30"
    assert context["market_share_week"] == "2026-04-05"
    assert context["has_divergent_weeks"] is True
    assert context["model_scraped_at"] == "2026-04-06T08:19:47.193085Z"
    assert rankings_bucket_warning(context) is not None


def test_rankings_bucket_warning_is_empty_when_weeks_match() -> None:
    context = {
        "model_week": "2026-03-30",
        "market_share_week": "2026-03-30",
        "programming_week": "2026-03-30",
        "model_scraped_at": "2026-04-06T08:19:47.193085Z",
        "market_share_scraped_at": "2026-04-06T08:19:47.193085Z",
        "programming_scraped_at": "2026-04-06T08:19:47.193085Z",
        "has_divergent_weeks": False,
    }

    assert rankings_bucket_warning(context) is None


def test_regroup_provider_pivot_for_display_weekly_monthly_merges_into_others() -> None:
    pivot = pd.DataFrame(
        {
            "OpenAI": [100.0, 120.0],
            "Tngtech": [5.0, 6.0],
            "StepFun": [7.0, 8.0],
            "OpenRouter": [9.0, 10.0],
            "Others": [11.0, 12.0],
            "Arcee AI": [13.0, 14.0],
            "Nousresearch": [15.0, 16.0],
            "NVIDIA": [17.0, 18.0],
            "Tencent": [19.0, 20.0],
        },
        index=["2026-01-05", "2026-01-12"],
    )

    regrouped = regroup_provider_pivot_for_display(pivot, "weekly")

    assert list(regrouped.columns) == ["OpenAI", "Tencent", "StepFun", "Others"]
    assert regrouped.loc["2026-01-05", "Others"] == 70.0
    assert regrouped.loc["2026-01-12", "Others"] == 76.0
    assert regrouped.loc["2026-01-05", "Tencent"] == 19.0
    assert regrouped.loc["2026-01-05", "StepFun"] == 7.0


def test_regroup_provider_pivot_for_display_daily_uses_daily_bucket_rules() -> None:
    pivot = pd.DataFrame(
        {
            "OpenAI": [100.0],
            "Microsoft": [20.0],
            "Meta (Llama)": [30.0],
            "Mistral AI": [40.0],
            "Google": [50.0],
            "Tencent": [60.0],
        },
        index=["2026-04-05"],
    )

    regrouped = regroup_provider_pivot_for_display(pivot, "daily")

    assert list(regrouped.columns) == ["OpenAI", "Google", "Tencent", "Others"]
    assert regrouped.loc["2026-04-05", "Others"] == 90.0
    assert regrouped.loc["2026-04-05", "Tencent"] == 60.0


def test_regroup_provider_pivot_for_display_is_noop_when_no_targets_present() -> None:
    pivot = pd.DataFrame(
        {
            "OpenAI": [10.0],
            "Anthropic": [20.0],
        },
        index=["2026-04-05"],
    )

    regrouped = regroup_provider_pivot_for_display(pivot, "daily")

    pd.testing.assert_frame_equal(regrouped, pivot)


def test_order_provider_columns_groups_us_china_other_and_others_last() -> None:
    pivot = pd.DataFrame(
        {
            "Mistral AI": [1.0],
            "Tencent": [2.0],
            "Others": [3.0],
            "Anthropic": [4.0],
            "StepFun": [5.0],
            "OpenAI": [6.0],
            "Arcee AI": [7.0],
            "DeepSeek": [8.0],
            "Google": [9.0],
        },
        index=["2026-05-01"],
    )

    ordered = order_provider_columns(pivot)

    assert list(ordered.columns) == [
        "OpenAI",
        "Anthropic",
        "Google",
        "DeepSeek",
        "Tencent",
        "StepFun",
        "Arcee AI",
        "Mistral AI",
        "Others",
    ]


def test_derive_provider_name_normalizes_meta_llama_slug() -> None:
    assert _derive_provider_name("meta-llama/model", None) == "Meta (Llama)"


def test_derive_provider_name_normalizes_tencent_slug() -> None:
    assert _derive_provider_name("tencent/hy3-preview:free", None) == "Tencent"


def test_derive_provider_name_normalizes_z_ai_slug() -> None:
    assert _derive_provider_name("z-ai/model", None) == "智谱AI (Z.ai)"


def test_derive_provider_name_normalizes_stepfun_slug() -> None:
    assert _derive_provider_name("stepfun/step-3.5-flash", None) == "StepFun"


def test_tencent_surfaces_in_daily_token_and_revenue_views(tmp_path: Path) -> None:
    provider_daily_activity = pd.DataFrame(
        [
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-05-01",
                "entity_id": "tencent",
                "entity_name": "Tencent",
                "category_slug": "tencent",
                "model_permaslug": "tencent/hy3-preview-20260421:free",
                "total_tokens": 400.0,
            },
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-05-01",
                "entity_id": "tencent",
                "entity_name": "Tencent",
                "category_slug": "tencent",
                "model_permaslug": "tencent/hunyuan-a13b-instruct",
                "total_tokens": 100.0,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )
    raw_openrouter_models = pd.DataFrame(
        [
            {
                **_base_row("raw_openrouter_models"),
                "snapshot_ts": "2026-04-30T00:00:00Z",
                "model_id": "tencent/hunyuan-a13b-instruct",
                "canonical_slug": "tencent/hunyuan-a13b-instruct",
                "provider_prefix": "tencent",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )

    _write_dataset(tmp_path, "provider_daily_activity", provider_daily_activity)
    _write_dataset(tmp_path, "raw_openrouter_models", raw_openrouter_models)

    datasets = load_all_datasets(base_dir=tmp_path)
    views = _compute_revenue_views(datasets)
    token_daily = regroup_provider_pivot_for_display(views["token_volume"]["pivot_daily"], "daily")
    revenue_daily = regroup_provider_pivot_for_display(views["revenue_estimator"]["pivot_rev_daily"], "daily")

    assert "Tencent" in token_daily.columns
    assert "Tencent" in revenue_daily.columns
    assert token_daily.loc["2026-05-01", "Tencent"] == 500.0
    assert revenue_daily.loc["2026-05-01", "Tencent"] == 0.1023


def test_stepfun_surfaces_in_daily_token_and_revenue_views(tmp_path: Path) -> None:
    provider_daily_activity = pd.DataFrame(
        [
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-05-01",
                "entity_id": "stepfun",
                "entity_name": "StepFun",
                "category_slug": "stepfun",
                "model_permaslug": "stepfun/step-3.5-flash",
                "total_tokens": 100.0,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )
    raw_openrouter_models = pd.DataFrame(
        [
            {
                **_base_row("raw_openrouter_models"),
                "snapshot_ts": "2026-04-30T00:00:00Z",
                "model_id": "stepfun/step-3.5-flash",
                "canonical_slug": "stepfun/step-3.5-flash",
                "provider_prefix": "stepfun",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )

    _write_dataset(tmp_path, "provider_daily_activity", provider_daily_activity)
    _write_dataset(tmp_path, "raw_openrouter_models", raw_openrouter_models)

    datasets = load_all_datasets(base_dir=tmp_path)
    views = _compute_revenue_views(datasets)
    token_daily = regroup_provider_pivot_for_display(views["token_volume"]["pivot_daily"], "daily")
    revenue_daily = regroup_provider_pivot_for_display(views["revenue_estimator"]["pivot_rev_daily"], "daily")

    assert "StepFun" in token_daily.columns
    assert "StepFun" in revenue_daily.columns
    assert token_daily.loc["2026-05-01", "StepFun"] == 100.0
    assert revenue_daily.loc["2026-05-01", "StepFun"] == 0.1023


def test_dashboard_modern_revenue_does_not_back_apply_future_xiaomi_pricing(tmp_path: Path) -> None:
    provider_daily_activity = pd.DataFrame(
        [
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-03-30",
                "entity_id": "xiaomi",
                "entity_name": "Xiaomi",
                "category_slug": "xiaomi",
                "model_permaslug": "xiaomi/mimo-v2-pro-20260318",
                "total_tokens": 1_000_000.0,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )
    raw_openrouter_models = pd.DataFrame(
        [
            {
                **_base_row("raw_openrouter_models"),
                "snapshot_ts": "2026-04-15T00:00:00Z",
                "model_id": "xiaomi/mimo-v2-pro",
                "canonical_slug": "xiaomi/mimo-v2-pro-20260318",
                "provider_prefix": "xiaomi",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.003,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )

    _write_dataset(tmp_path, "provider_daily_activity", provider_daily_activity)
    _write_dataset(tmp_path, "raw_openrouter_models", raw_openrouter_models)

    datasets = load_all_datasets(base_dir=tmp_path)
    views = _compute_revenue_views(datasets)
    token_daily = regroup_provider_pivot_for_display(views["token_volume"]["pivot_daily"], "daily")
    revenue_daily = regroup_provider_pivot_for_display(views["revenue_estimator"]["pivot_rev_daily"], "daily")
    revenue_weekly = regroup_provider_pivot_for_display(views["revenue_estimator"]["pivot_rev_weekly"], "weekly")
    revenue_monthly = regroup_provider_pivot_for_display(views["revenue_estimator"]["pivot_rev_monthly"], "monthly")
    economics = views["revenue_estimator"]["economics"]
    xiaomi_row = economics[economics["provider_slug"] == "xiaomi"].iloc[0]

    assert token_daily.loc["2026-03-30", "Xiaomi"] == 1_000_000.0
    assert "Xiaomi" not in revenue_daily.columns or revenue_daily.loc["2026-03-30", "Xiaomi"] == 0
    assert "Xiaomi" not in revenue_weekly.columns or revenue_weekly.loc["2026-03-30", "Xiaomi"] == 0
    assert (
        "Xiaomi" not in revenue_monthly.columns
        or "2026-03" not in revenue_monthly.index
        or revenue_monthly.loc["2026-03", "Xiaomi"] == 0
    )
    assert xiaomi_row["pricing_join_status"] == "unresolved_missing_pricing"
    assert xiaomi_row["revenue_method"] == "unpriced"
    assert pd.isna(xiaomi_row["estimated_revenue"])


def test_dashboard_modern_revenue_keeps_non_xiaomi_fallback_before_pricing_history(tmp_path: Path) -> None:
    provider_daily_activity = pd.DataFrame(
        [
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-03-30",
                "entity_id": "openai",
                "entity_name": "OpenAI",
                "category_slug": "openai",
                "model_permaslug": "openai/gpt-4o-mini",
                "total_tokens": 1_000_000.0,
                "prompt_tokens": 600_000.0,
                "completion_tokens": 400_000.0,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )
    raw_openrouter_models = pd.DataFrame(
        [
            {
                **_base_row("raw_openrouter_models"),
                "snapshot_ts": "2026-04-15T00:00:00Z",
                "model_id": "openai/gpt-4o-mini",
                "canonical_slug": "openai/gpt-4o-mini",
                "provider_prefix": "openai",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )

    _write_dataset(tmp_path, "provider_daily_activity", provider_daily_activity)
    _write_dataset(tmp_path, "raw_openrouter_models", raw_openrouter_models)

    datasets = load_all_datasets(base_dir=tmp_path)
    views = _compute_revenue_views(datasets)
    revenue_daily = regroup_provider_pivot_for_display(views["revenue_estimator"]["pivot_rev_daily"], "daily")

    assert "OpenAI" in revenue_daily.columns
    assert revenue_daily.loc["2026-03-30", "OpenAI"] > 0


def test_dashboard_monthly_revenue_excludes_post_legacy_market_share_topups(tmp_path: Path) -> None:
    top_models = pd.DataFrame(
        [
            {
                **_base_row("top_models"),
                "week_start_date": "2026-03-30",
                "entity_id": "xiaomi/mimo-v2-pro-20260318",
                "entity_name": "xiaomi/mimo-v2-pro-20260318",
                "parent_entity_id": "xiaomi",
                "parent_entity_name": "Xiaomi",
                "metric_value": 100.0,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )
    market_share = pd.DataFrame(
        [
            {
                **_base_row("market_share"),
                "week_start_date": "2026-03-30",
                "entity_id": "xiaomi",
                "entity_name": "xiaomi",
                "metric_value": 1_000_000.0,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )
    raw_openrouter_models = pd.DataFrame(
        [
            {
                **_base_row("raw_openrouter_models"),
                "snapshot_ts": "2026-04-15T00:00:00Z",
                "model_id": "xiaomi/mimo-v2-pro",
                "canonical_slug": "xiaomi/mimo-v2-pro-20260318",
                "provider_prefix": "xiaomi",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.003,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )

    _write_dataset(tmp_path, "top_models", top_models)
    _write_dataset(tmp_path, "market_share", market_share)
    _write_dataset(tmp_path, "raw_openrouter_models", raw_openrouter_models)

    datasets = load_all_datasets(base_dir=tmp_path)
    views = _compute_revenue_views(datasets)
    revenue_monthly = regroup_provider_pivot_for_display(views["revenue_estimator"]["pivot_rev_monthly"], "monthly")

    assert (
        "Xiaomi" not in revenue_monthly.columns
        or "2026-03" not in revenue_monthly.index
        or revenue_monthly.loc["2026-03", "Xiaomi"] == 0
    )


def test_legacy_token_volume_uses_market_share_for_providers_missing_from_top_models(tmp_path: Path) -> None:
    top_models = pd.DataFrame(
        [
            {
                **_base_row("top_models"),
                "week_label": "2026-01-04",
                "week_start_date": "2026-01-04",
                "entity_id": "openai/gpt-4o-mini",
                "entity_name": "openai/gpt-4o-mini",
                "parent_entity_id": "openai",
                "parent_entity_name": "openai",
                "metric_name": "tokens",
                "metric_unit": "tokens",
                "metric_value": 100.0,
                "rank": 1,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )
    market_share = pd.DataFrame(
        [
            {
                **_base_row("market_share"),
                "week_label": "2026-01-04",
                "week_start_date": "2026-01-04",
                "entity_id": "z-ai",
                "entity_name": "z ai",
                "metric_name": "token_share_pct",
                "metric_unit": "share",
                "metric_value": 250.0,
                "rank": 9,
            },
            {
                **_base_row("market_share"),
                "week_label": "2026-01-04",
                "week_start_date": "2026-01-04",
                "entity_id": "openai",
                "entity_name": "openai",
                "metric_name": "token_share_pct",
                "metric_unit": "share",
                "metric_value": 500.0,
                "rank": 1,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )
    provider_daily_activity = pd.DataFrame(
        [
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-01-16",
                "entity_id": "z-ai",
                "entity_name": "智谱AI (Z.ai)",
                "category_slug": "z-ai",
                "model_permaslug": "z-ai/glm-4.6",
                "total_tokens": 90.0,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )
    raw_openrouter_models = pd.DataFrame(
        [
            {
                **_base_row("raw_openrouter_models"),
                "snapshot_ts": "2026-01-15T00:00:00Z",
                "model_id": "openai/gpt-4o-mini",
                "pricing_prompt": 0.002,
                "pricing_completion": 0.004,
                "context_length": 128000,
            },
            {
                **_base_row("raw_openrouter_models"),
                "snapshot_ts": "2026-01-15T00:00:00Z",
                "model_id": "z-ai/glm-4.6",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
                "context_length": 128000,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )

    _write_dataset(tmp_path, "top_models", top_models)
    _write_dataset(tmp_path, "market_share", market_share)
    _write_dataset(tmp_path, "app_usage_daily", _apps_usage_frame())
    _write_dataset(tmp_path, "provider_daily_activity", provider_daily_activity)
    _write_dataset(tmp_path, "raw_openrouter_models", raw_openrouter_models)

    datasets = load_all_datasets(base_dir=tmp_path)
    views = _compute_revenue_views(datasets)
    token_weekly = views["token_volume"]["pivot_weekly"]
    token_monthly = views["token_volume"]["pivot_monthly"]
    revenue_weekly = views["revenue_estimator"]["pivot_rev_weekly"]

    assert "智谱AI (Z.ai)" in token_weekly.columns
    assert token_weekly.loc["2026-01-05", "智谱AI (Z.ai)"] == 250.0
    assert token_monthly.loc["2026-01", "智谱AI (Z.ai)"] == 340.0
    assert "智谱AI (Z.ai)" in revenue_weekly.columns
    assert "2026-01-05" in revenue_weekly.index
    assert revenue_weekly.loc["2026-01-05", "智谱AI (Z.ai)"] > 0
    assert revenue_weekly.loc["2026-01-12", "智谱AI (Z.ai)"] > 0


def test_market_share_legacy_and_modern_provider_logs_stitch_into_one_provider_series(tmp_path: Path) -> None:
    top_models = pd.DataFrame(
        [
            {
                **_base_row("top_models"),
                "week_label": "2026-01-04",
                "week_start_date": "2026-01-04",
                "entity_id": "openai/gpt-4o-mini",
                "entity_name": "openai/gpt-4o-mini",
                "parent_entity_id": "openai",
                "parent_entity_name": "openai",
                "metric_name": "tokens",
                "metric_unit": "tokens",
                "metric_value": 100.0,
                "rank": 1,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )
    market_share = pd.DataFrame(
        [
            {
                **_base_row("market_share"),
                "week_label": "2026-01-04",
                "week_start_date": "2026-01-04",
                "entity_id": "z-ai",
                "entity_name": "z ai",
                "metric_name": "token_share_pct",
                "metric_unit": "share",
                "metric_value": 250.0,
                "rank": 9,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )
    provider_daily_activity = pd.DataFrame(
        [
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-01-16",
                "entity_id": "z-ai",
                "entity_name": "智谱AI (Z.ai)",
                "category_slug": "z-ai",
                "model_permaslug": "z-ai/glm-4.6",
                "total_tokens": 90.0,
            },
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-01-17",
                "entity_id": "z-ai",
                "entity_name": "智谱AI (Z.ai)",
                "category_slug": "z-ai",
                "model_permaslug": "z-ai/glm-4.6",
                "total_tokens": 110.0,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )
    raw_openrouter_models = pd.DataFrame(
        [
            {
                **_base_row("raw_openrouter_models"),
                "snapshot_ts": "2026-01-15T00:00:00Z",
                "model_id": "openai/gpt-4o-mini",
                "pricing_prompt": 0.002,
                "pricing_completion": 0.004,
                "context_length": 128000,
            },
            {
                **_base_row("raw_openrouter_models"),
                "snapshot_ts": "2026-01-15T00:00:00Z",
                "model_id": "z-ai/glm-4.6",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
                "context_length": 128000,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )

    _write_dataset(tmp_path, "top_models", top_models)
    _write_dataset(tmp_path, "market_share", market_share)
    _write_dataset(tmp_path, "app_usage_daily", _apps_usage_frame())
    _write_dataset(tmp_path, "provider_daily_activity", provider_daily_activity)
    _write_dataset(tmp_path, "raw_openrouter_models", raw_openrouter_models)

    datasets = load_all_datasets(base_dir=tmp_path)
    views = _compute_revenue_views(datasets)
    token_weekly = views["token_volume"]["pivot_weekly"]

    assert list(token_weekly.index) == ["2026-01-05", "2026-01-12"]
    assert "智谱AI (Z.ai)" in token_weekly.columns
    assert token_weekly.loc["2026-01-05", "智谱AI (Z.ai)"] == 250.0
    assert token_weekly.loc["2026-01-12", "智谱AI (Z.ai)"] > 0


def test_partial_handover_week_token_volume_backfills_missing_weekdays_from_following_week(tmp_path: Path) -> None:
    top_models = pd.DataFrame(
        [
            {
                **_base_row("top_models"),
                "week_label": "2026-01-04",
                "week_start_date": "2026-01-04",
                "entity_id": "openai/gpt-4o-mini",
                "entity_name": "openai/gpt-4o-mini",
                "parent_entity_id": "openai",
                "parent_entity_name": "openai",
                "metric_name": "tokens",
                "metric_unit": "tokens",
                "metric_value": 100.0,
                "rank": 1,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )
    market_share = pd.DataFrame(
        [
            {
                **_base_row("market_share"),
                "week_label": "2026-01-04",
                "week_start_date": "2026-01-04",
                "entity_id": "z-ai",
                "entity_name": "z ai",
                "metric_name": "token_share_pct",
                "metric_unit": "share",
                "metric_value": 250.0,
                "rank": 9,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )
    provider_daily_activity = pd.DataFrame(
        [
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-01-16",
                "entity_id": "z-ai",
                "entity_name": "智谱AI (Z.ai)",
                "category_slug": "z-ai",
                "model_permaslug": "z-ai/glm-4.6",
                "total_tokens": 90.0,
            },
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-01-17",
                "entity_id": "z-ai",
                "entity_name": "智谱AI (Z.ai)",
                "category_slug": "z-ai",
                "model_permaslug": "z-ai/glm-4.6",
                "total_tokens": 110.0,
            },
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-01-18",
                "entity_id": "z-ai",
                "entity_name": "智谱AI (Z.ai)",
                "category_slug": "z-ai",
                "model_permaslug": "z-ai/glm-4.6",
                "total_tokens": 100.0,
            },
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-01-19",
                "entity_id": "z-ai",
                "entity_name": "智谱AI (Z.ai)",
                "category_slug": "z-ai",
                "model_permaslug": "z-ai/glm-4.6",
                "total_tokens": 120.0,
            },
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-01-20",
                "entity_id": "z-ai",
                "entity_name": "智谱AI (Z.ai)",
                "category_slug": "z-ai",
                "model_permaslug": "z-ai/glm-4.6",
                "total_tokens": 130.0,
            },
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-01-21",
                "entity_id": "z-ai",
                "entity_name": "智谱AI (Z.ai)",
                "category_slug": "z-ai",
                "model_permaslug": "z-ai/glm-4.6",
                "total_tokens": 140.0,
            },
            {
                **_base_row("provider_daily_activity"),
                "usage_date": "2026-01-22",
                "entity_id": "z-ai",
                "entity_name": "智谱AI (Z.ai)",
                "category_slug": "z-ai",
                "model_permaslug": "z-ai/glm-4.6",
                "total_tokens": 150.0,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )
    raw_openrouter_models = pd.DataFrame(
        [
            {
                **_base_row("raw_openrouter_models"),
                "snapshot_ts": "2026-01-15T00:00:00Z",
                "model_id": "z-ai/glm-4.6",
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
                "context_length": 128000,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )

    _write_dataset(tmp_path, "top_models", top_models)
    _write_dataset(tmp_path, "market_share", market_share)
    _write_dataset(tmp_path, "app_usage_daily", _apps_usage_frame())
    _write_dataset(tmp_path, "provider_daily_activity", provider_daily_activity)
    _write_dataset(tmp_path, "raw_openrouter_models", raw_openrouter_models)

    datasets = load_all_datasets(base_dir=tmp_path)
    views = _compute_revenue_views(datasets)
    token_weekly = views["token_volume"]["pivot_weekly"]
    weekly_coverage = views["token_volume"]["weekly_coverage"]

    assert token_weekly.loc["2026-01-05", "智谱AI (Z.ai)"] == 250.0
    assert token_weekly.loc["2026-01-12", "智谱AI (Z.ai)"] == 840.0
    partial_week = weekly_coverage[weekly_coverage["usage_week"] == "2026-01-12"].iloc[0]
    assert partial_week["observed_days"] == 3
    assert partial_week["expected_days"] == 7
    assert bool(partial_week["is_partial_period"]) is True


def test_make_stacked_area_chart_allows_metric_specific_hover_formatting() -> None:
    pivot = pd.DataFrame({"OpenAI": [1234.0]}, index=["2026-04-05"])

    revenue_fig = make_stacked_area_chart(
        pivot,
        ["2026-04-05"],
        ["#4285F4"],
        y_title="Revenue (USD)",
        hover_prefix="$",
    )
    token_fig = make_stacked_area_chart(
        pivot,
        ["2026-04-05"],
        ["#4285F4"],
        y_title="Tokens",
        value_format=",.0f",
        hover_suffix="tokens",
    )

    assert "$%{y:,.2f}" in revenue_fig.data[0].hovertemplate
    assert "$" not in token_fig.data[0].hovertemplate
    assert "%{y:,.0f} tokens" in token_fig.data[0].hovertemplate


def test_revenue_share_pivot_normalizes_each_period_to_100_percent() -> None:
    pivot = pd.DataFrame(
        {
            "OpenAI": [25.0, 0.0],
            "Anthropic": [75.0, 0.0],
        },
        index=["2026-06-24", "2026-06-25"],
    )

    share = _pivot_to_share_percent(pivot)

    assert share.loc["2026-06-24", "OpenAI"] == 25.0
    assert share.loc["2026-06-24", "Anthropic"] == 75.0
    assert share.loc["2026-06-24"].sum() == 100.0
    assert share.loc["2026-06-25"].sum() == 0.0


def test_estimator_coverage_summary_separates_model_fallback_and_unpriced_tokens() -> None:
    estimated = pd.DataFrame(
        [
            {"total_tokens": 90.0, "pricing_join_status": "matched_model_median"},
            {"total_tokens": 5.0, "pricing_join_status": "fallback_provider_median"},
            {"total_tokens": 3.0, "pricing_join_status": "free_model_zero_revenue"},
            {"total_tokens": 2.0, "pricing_join_status": "synthetic_unpriced"},
        ]
    )

    coverage = _estimator_coverage_summary(estimated)

    assert coverage["model_priced_token_coverage"] == 0.93
    assert coverage["fallback_priced_token_coverage"] == 0.05
    assert coverage["unpriced_token_share"] == 0.02


def test_compute_task_spend_views_prepares_latest_task_and_model_rankings() -> None:
    frame = pd.DataFrame(
        [
            {
                **_base_row("openrouter_task_spend"),
                "snapshot_date": "2026-06-29",
                "period": "spend",
                "window_days": 30,
                "category_slug": "agent:workflow_execution",
                "macro_category": "agent",
                "task_share_of_total": 0.10,
                "model_permaslug": "openai/gpt-5.5",
                "model_share": 0.60,
                "rank": 1,
            },
            {
                **_base_row("openrouter_task_spend"),
                "snapshot_date": "2026-06-30",
                "period": "spend",
                "window_days": 30,
                "category_slug": "agent:workflow_execution",
                "macro_category": "agent",
                "task_share_of_total": 0.30,
                "model_permaslug": "anthropic/claude-opus-4.7",
                "model_share": 0.70,
                "rank": 1,
            },
            {
                **_base_row("openrouter_task_spend"),
                "snapshot_date": "2026-06-30",
                "period": "spend",
                "window_days": 30,
                "category_slug": "agent:workflow_execution",
                "macro_category": "agent",
                "task_share_of_total": 0.30,
                "model_permaslug": "openai/gpt-5.5",
                "model_share": 0.20,
                "rank": 2,
            },
            {
                **_base_row("openrouter_task_spend"),
                "snapshot_date": "2026-06-30",
                "period": "spend",
                "window_days": 30,
                "category_slug": "code:general_impl",
                "macro_category": "code",
                "task_share_of_total": 0.20,
                "model_permaslug": "anthropic/claude-sonnet-4.6",
                "model_share": 0.50,
                "rank": 1,
            },
            {
                **_base_row("openrouter_task_spend"),
                "snapshot_date": "2026-06-30",
                "period": "tokens",
                "window_days": 7,
                "category_slug": "classification_tagging",
                "macro_category": "general",
                "task_share_of_total": 0.40,
                "model_permaslug": "google/gemini-2.5-flash",
                "model_share": 0.55,
                "rank": 1,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )

    views = _compute_task_spend_views(frame)

    assert views["latest_snapshot_date"] == "2026-06-30"
    assert views["windows"] == [7, 30]
    assert views["periods"] == ["spend", "tokens"]
    spend_30 = views["by_selection"][("spend", 30)]
    assert spend_30["top_task"] == "agent:workflow_execution"
    assert spend_30["top_model"] == "anthropic/claude-opus-4.7"
    assert spend_30["task_summary"]["task_share_pct"].tolist() == [30.0, 20.0]
    assert spend_30["model_rows"].iloc[0]["model_share_pct"] == 70.0


def test_default_task_spend_window_prefers_seven_days() -> None:
    assert _default_task_spend_window([7, 30, 90]) == 7
    assert _default_task_spend_window([30, 90]) == 30


def test_compute_openrouter_views_exposes_total_weekly_tokens_for_top_models() -> None:
    top_models = pd.DataFrame(
        [
            {
                **_base_row("top_models"),
                "week_label": "2026-03-09",
                "week_start_date": "2026-03-09",
                "entity_id": "openai/gpt-4o-mini",
                "entity_name": "openai/gpt-4o-mini",
                "parent_entity_id": "openai",
                "parent_entity_name": "openai",
                "metric_name": "tokens",
                "metric_unit": "tokens",
                "metric_value": 100.0,
                "rank": 1,
            },
            {
                **_base_row("top_models"),
                "week_label": "2026-03-09",
                "week_start_date": "2026-03-09",
                "entity_id": "anthropic/claude-sonnet",
                "entity_name": "anthropic/claude-sonnet",
                "parent_entity_id": "anthropic",
                "parent_entity_name": "anthropic",
                "metric_name": "tokens",
                "metric_unit": "tokens",
                "metric_value": 250.0,
                "rank": 2,
            },
            {
                **_base_row("top_models"),
                "week_label": "2026-03-16",
                "week_start_date": "2026-03-16",
                "entity_id": "openai/gpt-4o-mini",
                "entity_name": "openai/gpt-4o-mini",
                "parent_entity_id": "openai",
                "parent_entity_name": "openai",
                "metric_name": "tokens",
                "metric_unit": "tokens",
                "metric_value": 300.0,
                "rank": 1,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )

    empty_result = DatasetLoadResult(
        dataset_id="empty",
        label="Empty",
        domain="rankings",
        primary_date_column=None,
        metric_column=None,
        frame=pd.DataFrame(),
        source_format=None,
        source_path=None,
        missing_columns=[],
        duplicate_rows=0,
        first_date=None,
        latest_date=None,
        latest_scraped_at=None,
        row_count=0,
    )

    datasets = {
        "top_models": DatasetLoadResult(
            dataset_id="top_models",
            label="Top Models",
            domain="rankings",
            primary_date_column="week_start_date",
            metric_column="metric_value",
            frame=top_models,
            source_format="csv",
            source_path=Path("data/normalized/openrouter/top_models.csv"),
            missing_columns=[],
            duplicate_rows=0,
            first_date="2026-03-09",
            latest_date="2026-03-16",
            latest_scraped_at="2026-04-05T00:00:00Z",
            row_count=len(top_models),
        ),
        "categories_programming": empty_result,
        "market_share": empty_result,
    }

    views = compute_openrouter_views(datasets)
    pivot_total = views["top_models"]["pivot_total"]

    assert list(pivot_total.columns) == ["Total Tokens"]
    assert list(pivot_total.index) == ["2026-03-09", "2026-03-16"]
    assert pivot_total.loc["2026-03-09", "Total Tokens"] == 350.0
    assert pivot_total.loc["2026-03-16", "Total Tokens"] == 300.0


def test_compute_openrouter_views_prefers_market_share_for_platform_total_tokens() -> None:
    top_models = pd.DataFrame(
        [
            {
                **_base_row("top_models"),
                "week_start_date": "2026-03-09",
                "entity_id": "openai/gpt-4o-mini",
                "metric_value": 100.0,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )
    market_share = pd.DataFrame(
        [
            {
                **_base_row("market_share"),
                "week_start_date": "2026-03-08",
                "entity_id": "openai",
                "metric_value": 500.0,
            },
            {
                **_base_row("market_share"),
                "week_start_date": "2026-03-08",
                "entity_id": "others",
                "metric_value": 50.0,
            },
        ],
        columns=EXPECTED_COLUMNS,
    )
    result_kwargs = {
        "domain": "rankings",
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
        "source_format": "csv",
        "source_path": None,
        "missing_columns": [],
        "duplicate_rows": 0,
        "first_date": "2026-03-08",
        "latest_date": "2026-03-08",
        "latest_scraped_at": "2026-04-05T00:00:00Z",
    }
    datasets = {
        "top_models": DatasetLoadResult(
            dataset_id="top_models",
            label="Top Models",
            frame=top_models,
            row_count=len(top_models),
            **result_kwargs,
        ),
        "market_share": DatasetLoadResult(
            dataset_id="market_share",
            label="Market Share",
            frame=market_share,
            row_count=len(market_share),
            **result_kwargs,
        ),
    }

    views = compute_openrouter_views(datasets)

    assert views["top_models"]["total_source"] == "hybrid"
    assert views["top_models"]["pivot_total"].loc["2026-03-09", "Total Tokens"] == 550.0


def test_compute_openrouter_views_exposes_provider_weekly_request_volume() -> None:
    provider_requests = _provider_weekly_requests_frame()
    result_kwargs = {
        "domain": "rankings",
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
        "source_format": "csv",
        "source_path": None,
        "missing_columns": [],
        "duplicate_rows": 0,
        "first_date": "2026-03-30",
        "latest_date": "2026-04-06",
        "latest_scraped_at": "2026-04-06T00:00:00Z",
    }

    views = compute_openrouter_views(
        {
            "provider_weekly_requests": DatasetLoadResult(
                dataset_id="provider_weekly_requests",
                label="Provider Weekly Requests",
                frame=provider_requests,
                row_count=len(provider_requests),
                **result_kwargs,
            )
        }
    )

    request_view = views["provider_weekly_requests"]
    pivot = request_view["pivot_weekly"]

    assert request_view["weeks"] == ["2026-04-06", "2026-03-30"]
    assert pivot.loc["2026-04-06", "OpenAI"] == 1_500_000.0
    assert pivot.loc["2026-04-06", "Anthropic"] == 700_000.0


def test_weekly_usage_section_state_switches_between_tokens_and_requests() -> None:
    token_pivot = pd.DataFrame({"Total Tokens": [100.0, 150.0]}, index=["2026-03-30", "2026-04-06"])
    request_pivot = pd.DataFrame({"OpenAI": [1_200.0, 1_500.0], "Anthropic": [800.0, 700.0]}, index=["2026-03-30", "2026-04-06"])
    top_models = pd.DataFrame(
        [
            {**_base_row("top_models"), "week_start_date": "2026-04-06", "entity_id": "openai/gpt-4o", "metric_value": 500.0, "rank": 1},
            {**_base_row("top_models"), "week_start_date": "2026-04-06", "entity_id": "anthropic/claude", "metric_value": 300.0, "rank": 2},
        ],
        columns=EXPECTED_COLUMNS,
    )
    market_share = pd.DataFrame(
        [
            {**_base_row("market_share"), "week_start_date": "2026-04-06", "entity_id": "google", "metric_value": 900.0, "rank": 1},
            {**_base_row("market_share"), "week_start_date": "2026-04-06", "entity_id": "openai", "metric_value": 600.0, "rank": 2},
        ],
        columns=EXPECTED_COLUMNS,
    )
    openrouter_views = {
        "top_models": {
            "pivot_total": token_pivot,
            "total_source": "hybrid",
            "source_by_week": {"2026-04-06": "top_models"},
        },
        "provider_weekly_requests": {
            "pivot_weekly": request_pivot,
            "weeks": ["2026-04-06", "2026-03-30"],
        },
    }
    result_kwargs = {
        "domain": "rankings",
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
        "source_format": "csv",
        "source_path": None,
        "missing_columns": [],
        "duplicate_rows": 0,
        "first_date": "2026-03-30",
        "latest_date": "2026-04-06",
        "latest_scraped_at": "2026-04-06T00:00:00Z",
    }
    datasets = {
        "top_models": DatasetLoadResult(
            dataset_id="top_models",
            label="Top Models",
            frame=top_models,
            row_count=2,
            **result_kwargs,
        ),
        "market_share": DatasetLoadResult(
            dataset_id="market_share",
            label="Market Share",
            frame=market_share,
            row_count=2,
            **result_kwargs,
        ),
        "provider_weekly_requests": DatasetLoadResult(
            dataset_id="provider_weekly_requests",
            label="Provider Weekly Requests",
            frame=_provider_weekly_requests_frame(),
            row_count=4,
            **result_kwargs,
        ),
    }

    token_state = _weekly_usage_section_state(datasets, openrouter_views, "Tokens")
    request_state = _weekly_usage_section_state(datasets, openrouter_views, "Requests")

    assert token_state["metric"] == "Tokens"
    assert token_state["pivot"].equals(token_pivot)
    assert token_state["y_title"] == "Tokens"
    assert token_state["latest_total"] == 150.0
    assert token_state["top_model"] == "openai/gpt-4o"
    assert token_state["market_leader"] == "google"
    assert token_state["market_leader_pct"] == 60.0
    assert request_state["metric"] == "Requests"
    assert request_state["pivot"].equals(pd.DataFrame({"Total Requests": [2000.0, 2200.0]}, index=request_pivot.index))
    assert request_state["y_title"] == "Requests"
    assert request_state["latest_total"] == 2200.0
    assert request_state["dominant_label"] is None


def test_usage_window_defaults_to_weekly_and_supports_daily_totals() -> None:
    provider_daily = pd.DataFrame(
        {
            "usage_date": ["2026-06-17", "2026-06-18"],
            "entity_name": ["OpenAI", "Anthropic"],
            "total_tokens": [1000.0, 2500.0],
        }
    )
    model_activity = pd.DataFrame(
        {
            "usage_date": ["2026-06-17", "2026-06-18"],
            "category_slug": ["all", "all"],
            "request_count": [10.0, 25.0],
        }
    )
    result_kwargs = {
        "domain": "rankings",
        "primary_date_column": "usage_date",
        "metric_column": "total_tokens",
        "source_format": "parquet",
        "source_path": None,
        "missing_columns": [],
        "duplicate_rows": 0,
        "first_date": "2026-06-17",
        "latest_date": "2026-06-18",
        "latest_scraped_at": "2026-06-18T00:00:00Z",
    }
    datasets = {
        "provider_daily_activity": DatasetLoadResult(
            dataset_id="provider_daily_activity",
            label="Provider Daily Activity",
            frame=provider_daily,
            row_count=2,
            **result_kwargs,
        ),
        "openrouter_model_activity": DatasetLoadResult(
            dataset_id="openrouter_model_activity",
            label="Model Activity",
            frame=model_activity,
            row_count=2,
            **result_kwargs,
        ),
    }

    weekly = _weekly_usage_section_state(datasets, {}, "Tokens")
    daily_tokens = _weekly_usage_section_state(datasets, {}, "Tokens", window="Daily")
    daily_requests = _weekly_usage_section_state(datasets, {}, "Requests", window="Daily")

    assert weekly["window"] == "Weekly"
    assert daily_tokens["window"] == "Daily"
    assert daily_tokens["pivot"].columns.tolist() == ["Total Tokens"]
    assert daily_tokens["pivot"].loc["2026-06-18", "Total Tokens"] == 2500.0
    assert daily_requests["pivot"].columns.tolist() == ["Total Requests"]
    assert daily_requests["pivot"].loc["2026-06-18", "Total Requests"] == 25.0


def test_workload_intensity_state_is_total_only_for_usage_chart() -> None:
    state = _weekly_usage_section_state(_derived_datasets(), {}, "Workload Intensity")

    assert state["component"] == "Total"
    assert state["metric_id"] == "total_tokens_per_request"


def test_workload_intensity_defaults_to_weekly_snapshots() -> None:
    state = _weekly_usage_section_state(_derived_datasets(), {}, "Workload Intensity")

    assert state["window"] == "Weekly"
    assert state["pivot"].index.tolist() == ["2026-07-06", "2026-07-13"]
    assert state["pivot"].iloc[-1, 0] == 120.0


def test_daily_usage_totals_are_continuous_from_june_17_and_preserve_gaps() -> None:
    provider_daily = pd.DataFrame(
        {
            "usage_date": ["2026-06-17", "2026-06-19"],
            "entity_name": ["OpenAI", "OpenAI"],
            "total_tokens": [1000.0, 2500.0],
        }
    )
    datasets = {
        "provider_daily_activity": DatasetLoadResult(
            dataset_id="provider_daily_activity",
            label="Provider Daily Activity",
            frame=provider_daily,
            row_count=2,
            domain="rankings",
            primary_date_column="usage_date",
            metric_column="total_tokens",
            source_format="parquet",
            source_path=None,
            missing_columns=[],
            duplicate_rows=0,
            first_date="2026-06-17",
            latest_date="2026-06-19",
            latest_scraped_at="2026-06-19T00:00:00Z",
        )
    }

    state = _weekly_usage_section_state(datasets, {}, "Tokens", window="Daily")

    assert state["pivot"].index.tolist() == ["2026-06-17", "2026-06-18", "2026-06-19"]
    assert pd.isna(state["pivot"].loc["2026-06-18", "Total Tokens"])


def test_legacy_original_price_series_backfills_and_smooths_all_calendar_dates() -> None:
    economics = pd.DataFrame(
        [
            {
                "usage_date": "2026-01-01",
                "model_permaslug": "provider/model",
                "total_tokens": 100.0,
                "prompt_tokens": 80.0,
                "completion_tokens": 20.0,
                "pricing_prompt": pd.NA,
                "pricing_completion": pd.NA,
            },
            {
                "usage_date": "2026-01-03",
                "model_permaslug": "provider/model",
                "total_tokens": 100.0,
                "prompt_tokens": 80.0,
                "completion_tokens": 20.0,
                "pricing_prompt": 2e-6,
                "pricing_completion": 4e-6,
            },
        ]
    )

    series = _legacy_original_price_series(economics)

    assert series.index.tolist() == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert series[["Spend-Weighted TEI", "Original Volume-Weighted TEI", "Frontier"]].notna().all().all()
    assert series.loc["2026-01-02", "Original Volume-Weighted TEI"] == series.loc["2026-01-01", "Original Volume-Weighted TEI"]


def _derived_datasets() -> dict[str, DatasetLoadResult]:
    daily_rows: list[dict[str, object]] = []
    workload_values = {
        "2026-07-10": {
            "total_tokens_per_request": 100.0,
            "prompt_tokens_per_request": 70.0,
            "completion_tokens_per_request": 30.0,
        },
        "2026-07-17": {
            "total_tokens_per_request": 120.0,
            "prompt_tokens_per_request": 80.0,
            "completion_tokens_per_request": 40.0,
        },
    }
    for usage_date, values in workload_values.items():
        for rolling_window_days in (1, 7):
            for metric_id, value in values.items():
                daily_rows.append(
                    {
                        "usage_date": usage_date,
                        "metric_id": metric_id,
                        "value": value - (5.0 if rolling_window_days == 1 else 0.0),
                        "rolling_window_days": rolling_window_days,
                        "observed_model_count": 4 if metric_id != "prompt_tokens_per_request" else 3,
                    }
                )

    price_values = {
        "2026-07-10": {
            "realized_market_average": 2.0,
            "sota_median_list_price": 3.0,
            "realized_sota_price": 2.5,
            "original_spend_weighted_tei": 2.1,
            "original_cpi_workload_basket": 1.7,
            "original_volume_weighted_tei": 2.0,
            "original_frontier_tei": 3.4,
            "original_value_tei": 0.3,
            "sota_volume_weighted_atp": 2.5,
        },
        "2026-07-17": {
            "realized_market_average": 1.8,
            "sota_median_list_price": 3.2,
            "realized_sota_price": 2.8,
            "original_spend_weighted_tei": 1.9,
            "original_cpi_workload_basket": 1.6,
            "original_volume_weighted_tei": 1.8,
            "original_frontier_tei": 3.1,
            "original_value_tei": 0.25,
            "sota_volume_weighted_atp": 2.8,
            "frontier_contenders_median_list_price": 2.4,
            "premium_priced_realized": 4.1,
            "mid_priced_realized": 1.1,
            "low_priced_realized": 0.2,
            "fixed_workload_basket": 2.51,
        },
    }
    for usage_date, values in price_values.items():
        for metric_id, value in values.items():
            rolling_window_days = 1 if metric_id in {"sota_median_list_price", "frontier_contenders_median_list_price"} else 7
            daily_rows.append(
                {
                    "usage_date": usage_date,
                    "metric_id": metric_id,
                    "value": value,
                    "rolling_window_days": rolling_window_days,
                    "expected_family_count": 5 if "sota" in metric_id else pd.NA,
                    "priced_family_count": 5 if "sota" in metric_id else pd.NA,
                    "observed_family_count": 4 if metric_id in {"realized_sota_price", "sota_volume_weighted_atp"} else pd.NA,
                    "observed_model_count": 4 if metric_id == "realized_sota_price" else pd.NA,
                    "pricing_join_status": (
                        "matched_model_median|backcast_earliest_pricing"
                        if metric_id == "realized_market_average"
                        else "strict_asof_pricing"
                    ),
                }
            )

    daily = pd.DataFrame(daily_rows)
    models = pd.DataFrame(
        [
            {
                "window_start_date": "2026-06-18",
                "window_end_date": "2026-07-17",
                "model_id": f"provider/model-{index}",
                "company_id": "provider",
                "total_tokens": 1_000.0 * index,
                "prompt_tokens": 700.0 * index,
                "completion_tokens": 300.0 * index,
                "request_count": 10.0 * index,
                "token_share": 0.1 * index,
                "request_share": 0.1 * index,
                "tokens_per_request": 100.0,
                "intensity_ratio": 1.0,
            }
            for index in range(1, 5)
        ]
    )

    def result(dataset_id: str, frame: pd.DataFrame, primary_date_column: str, metric_column: str) -> DatasetLoadResult:
        return DatasetLoadResult(
            dataset_id=dataset_id,
            label=dataset_id.replace("_", " ").title(),
            domain="openrouter_derived",
            primary_date_column=primary_date_column,
            metric_column=metric_column,
            frame=frame,
            source_format="parquet",
            source_path=None,
            missing_columns=[],
            duplicate_rows=0,
            first_date="2026-06-18",
            latest_date="2026-07-17",
            latest_scraped_at=pd.Timestamp("2026-07-18 12:00:00"),
            row_count=len(frame),
        )

    return {
        "openrouter_usage_economics_daily": result(
            "openrouter_usage_economics_daily", daily, "usage_date", "value"
        ),
        "openrouter_workload_intensity_models": result(
            "openrouter_workload_intensity_models", models, "window_end_date", "intensity_ratio"
        ),
    }


def test_usage_economics_state_exposes_workload_and_guarded_sota_lines() -> None:
    workload = _weekly_usage_section_state(_derived_datasets(), {}, "Workload Intensity")
    assert workload["metric"] == "Workload Intensity"
    assert workload["pivot"].columns.tolist() == ["Total tokens/request"]
    assert workload["latest_values"]["observed_model_count"] == 4
    assert workload["model_table"].columns.tolist() == [
        "Model",
        "Company",
        "Token share",
        "Request share",
        "Tokens/request",
        "Intensity ratio",
    ]

    price = _weekly_usage_section_state(_derived_datasets(), {}, "Average Price")
    assert price["pivot"].columns.tolist() == [
        "Spend-Weighted TEI",
        "CPI Workload Basket Index (50/40/10)",
        "Original Volume-Weighted TEI",
        "Frontier",
        "Value",
        "SOTA Volume-Weighted ATP (backfilled AA score)",
    ]
    assert price["pivot"].loc["2026-07-17", "SOTA Volume-Weighted ATP (backfilled AA score)"] == 2.8
    assert price["coverage_label"] == "Observed 4/5 SOTA families · priced 5/5"


def test_workload_intensity_state_selects_prompt_and_completion_metric_ids() -> None:
    datasets = _derived_datasets()

    prompt = _workload_intensity_section_state(datasets, "Prompt")
    completion = _workload_intensity_section_state(datasets, "Completion")

    assert prompt["metric_id"] == "prompt_tokens_per_request"
    assert prompt["pivot"].columns.tolist() == ["Prompt tokens/request"]
    assert prompt["raw_daily_pivot"].iloc[-1, 0] == 75.0
    assert completion["metric_id"] == "completion_tokens_per_request"
    assert completion["pivot"].columns.tolist() == ["Completion tokens/request"]


def test_average_price_state_keeps_sota_gaps_and_displays_all_approved_lines() -> None:
    datasets = _derived_datasets()
    daily = datasets["openrouter_usage_economics_daily"].frame
    daily.loc[
        daily["usage_date"].eq("2026-07-17")
        & daily["metric_id"].eq("sota_volume_weighted_atp"),
        "value",
    ] = pd.NA

    default = _weekly_usage_section_state(datasets, {}, "Average Price")
    assert pd.isna(default["pivot"].loc["2026-07-17", "SOTA Volume-Weighted ATP (backfilled AA score)"])
    assert "Premium-priced Realized Price" not in default["pivot"].columns
    assert default["metric_ids"] == [
        "original_spend_weighted_tei",
        "original_cpi_workload_basket",
        "original_volume_weighted_tei",
        "original_frontier_tei",
        "original_value_tei",
        "sota_volume_weighted_atp",
    ]


def test_average_price_state_combines_production_cadences_without_filling_gaps() -> None:
    datasets = _derived_datasets()
    daily = datasets["openrouter_usage_economics_daily"].frame
    daily.loc[
        daily["usage_date"].eq("2026-07-10")
        & daily["metric_id"].eq("sota_volume_weighted_atp"),
        "value",
    ] = pd.NA

    state = _average_price_section_state(datasets)

    assert state["pivot"].loc["2026-07-17", "SOTA Volume-Weighted ATP (backfilled AA score)"] == 2.8
    assert state["pivot"].loc["2026-07-17", "Frontier"] == 3.1
    assert pd.isna(state["pivot"].loc["2026-07-10", "SOTA Volume-Weighted ATP (backfilled AA score)"])


def test_derived_metric_pivot_removes_dates_with_no_selected_values() -> None:
    frame = pd.DataFrame(
        [
            {"usage_date": "2026-01-01", "metric_id": "realized_market_average", "value": pd.NA, "rolling_window_days": 7},
            {"usage_date": "2026-01-01", "metric_id": "sota_median_list_price", "value": pd.NA, "rolling_window_days": 1},
            {"usage_date": "2026-01-02", "metric_id": "realized_market_average", "value": 1.25, "rolling_window_days": 7},
            {"usage_date": "2026-01-02", "metric_id": "sota_median_list_price", "value": pd.NA, "rolling_window_days": 1},
        ]
    )

    pivot = _derived_metric_pivot(
        frame,
        ["realized_market_average", "sota_median_list_price"],
        rolling_window_days=7,
    )

    assert pivot.index.tolist() == ["2026-01-02"]
    assert pivot.loc["2026-01-02", "Realized Market Average"] == 1.25


def test_model_explorer_aggregates_sparse_request_detail_weekly() -> None:
    token_activity = pd.DataFrame(
        {
            "usage_date_dt": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
            "model_id": ["provider/model"] * 4,
            "total_tokens": [100.0, 100.0, 100.0, 100.0],
        }
    )
    request_activity = pd.DataFrame(
        {
            "usage_date_dt": pd.to_datetime(["2026-01-01", "2026-01-08"]),
            "model_id": ["provider/model"] * 2,
            "total_tokens": [100.0, 200.0],
            "request_count": [10.0, 20.0],
            "category_slug": ["all", "all"],
        }
    )

    state = model_explorer_state(
        {"catalog": pd.DataFrame(), "combined_activity": token_activity, "model_activity": request_activity},
        "provider/model",
    )

    assert state["request_granularity"] == "weekly"
    requests = state["activity"]["Requests"].dropna()
    assert requests.index.tolist() == [pd.Timestamp("2025-12-29"), pd.Timestamp("2026-01-05")]
    assert requests.tolist() == [10.0, 20.0]


def test_average_price_state_describes_strict_and_as_recorded_provenance() -> None:
    state = _average_price_section_state(_derived_datasets())

    assert "SOTA ATP uses the latest available Artificial Analysis intelligence score" in state["backcast_note"]
    assert "pricing routes remain exact" in state["backcast_note"]


def test_average_price_freshness_uses_only_price_rows() -> None:
    datasets = _derived_datasets()
    daily = datasets["openrouter_usage_economics_daily"].frame
    workload_mask = daily["metric_id"].astype("string").str.endswith("tokens_per_request")
    daily.loc[workload_mask, "scraped_at"] = "2026-07-19T12:00:00Z"
    daily.loc[~workload_mask, "scraped_at"] = "2026-07-18T06:00:00Z"
    datasets["openrouter_usage_economics_daily"] = replace(
        datasets["openrouter_usage_economics_daily"],
        latest_scraped_at=pd.Timestamp("2026-07-19T12:00:00Z"),
    )

    state = _average_price_section_state(datasets)

    assert state["scraped_at"] == pd.Timestamp("2026-07-18T06:00:00Z")


def test_workload_freshness_uses_only_workload_rows() -> None:
    datasets = _derived_datasets()
    daily = datasets["openrouter_usage_economics_daily"].frame
    workload_mask = daily["metric_id"].astype("string").str.endswith("tokens_per_request")
    daily.loc[workload_mask, "scraped_at"] = "2026-07-18T06:00:00Z"
    daily.loc[~workload_mask, "scraped_at"] = "2026-07-19T12:00:00Z"
    datasets["openrouter_usage_economics_daily"] = replace(
        datasets["openrouter_usage_economics_daily"],
        latest_scraped_at=pd.Timestamp("2026-07-19T12:00:00Z"),
    )

    state = _workload_intensity_section_state(datasets, "Total")

    assert state["scraped_at"] == pd.Timestamp("2026-07-18T06:00:00Z")


def test_usage_economics_state_missing_marts_is_scoped_from_tokens_and_requests() -> None:
    token_pivot = pd.DataFrame({"Total Tokens": [100.0]}, index=["2026-07-14"])
    request_pivot = pd.DataFrame({"OpenAI": [50.0]}, index=["2026-07-14"])
    views = {
        "top_models": {
            "pivot_total": token_pivot,
            "total_source": "top_models",
            "source_by_week": {"2026-07-14": "top_models"},
        },
        "provider_weekly_requests": {"pivot_weekly": request_pivot},
    }

    workload = _weekly_usage_section_state({}, views, "Workload Intensity")
    price = _weekly_usage_section_state({}, views, "Average Price")
    tokens = _weekly_usage_section_state({}, views, "Tokens")
    requests = _weekly_usage_section_state({}, views, "Requests")

    assert workload["pivot"].empty
    assert workload["empty_message"] == "No derived workload-intensity data is available yet."
    assert price["pivot"].empty
    assert price["empty_message"] == "No derived OpenRouter price data is available yet."
    assert tokens["pivot"].equals(token_pivot)
    assert requests["pivot"].equals(pd.DataFrame({"Total Requests": [50.0]}, index=request_pivot.index))


def test_compute_openrouter_views_falls_back_to_top_models_when_market_share_undercounts() -> None:
    top_models = pd.DataFrame(
        [
            {**_base_row("top_models"), "week_start_date": "2026-04-13", "entity_id": "openai/gpt-4o", "metric_value": 2000.0},
            {**_base_row("top_models"), "week_start_date": "2026-04-13", "entity_id": "anthropic/claude-sonnet", "metric_value": 1000.0},
        ],
        columns=EXPECTED_COLUMNS,
    )
    market_share = pd.DataFrame(
        [
            {**_base_row("market_share"), "week_start_date": "2026-04-12", "entity_id": "openai", "metric_value": 900.0},
            {**_base_row("market_share"), "week_start_date": "2026-04-12", "entity_id": "others", "metric_value": 100.0},
        ],
        columns=EXPECTED_COLUMNS,
    )
    result_kwargs = {
        "domain": "rankings",
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
        "source_format": "csv",
        "source_path": None,
        "missing_columns": [],
        "duplicate_rows": 0,
        "first_date": "2026-04-12",
        "latest_date": "2026-04-12",
        "latest_scraped_at": "2026-04-20T00:00:00Z",
    }
    datasets = {
        "top_models": DatasetLoadResult(
            dataset_id="top_models",
            label="Top Models",
            frame=top_models,
            row_count=len(top_models),
            **result_kwargs,
        ),
        "market_share": DatasetLoadResult(
            dataset_id="market_share",
            label="Market Share",
            frame=market_share,
            row_count=len(market_share),
            **result_kwargs,
        ),
    }

    views = compute_openrouter_views(datasets)

    assert views["top_models"]["total_source"] == "hybrid"
    assert views["top_models"]["pivot_total"].loc["2026-04-13", "Total Tokens"] == 3000.0
    assert views["top_models"]["source_by_week"]["2026-04-13"] == "top_models"


def test_compute_openrouter_views_deduplicates_sunday_and_monday_market_share_totals() -> None:
    top_models = pd.DataFrame(
        [
            {
                **_base_row("top_models"),
                "week_start_date": "2026-03-30",
                "entity_id": "openai/gpt-4o",
                "metric_value": 25_000.0,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )
    market_share = pd.DataFrame(
        [
            {**_base_row("market_share"), "week_start_date": "2026-03-29", "entity_id": "openai", "metric_value": 20_000.0},
            {**_base_row("market_share"), "week_start_date": "2026-03-29", "entity_id": "others", "metric_value": 4_400.0},
            {**_base_row("market_share"), "week_start_date": "2026-03-30", "entity_id": "openai", "metric_value": 22_000.0},
            {**_base_row("market_share"), "week_start_date": "2026-03-30", "entity_id": "others", "metric_value": 5_000.0},
        ],
        columns=EXPECTED_COLUMNS,
    )
    result_kwargs = {
        "domain": "rankings",
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
        "source_format": "csv",
        "source_path": None,
        "missing_columns": [],
        "duplicate_rows": 0,
        "first_date": "2026-03-29",
        "latest_date": "2026-03-30",
        "latest_scraped_at": "2026-04-05T00:00:00Z",
    }
    datasets = {
        "top_models": DatasetLoadResult(dataset_id="top_models", label="Top Models", frame=top_models, row_count=len(top_models), **result_kwargs),
        "market_share": DatasetLoadResult(dataset_id="market_share", label="Market Share", frame=market_share, row_count=len(market_share), **result_kwargs),
    }

    views = compute_openrouter_views(datasets)

    assert views["top_models"]["pivot_total"].loc["2026-03-30", "Total Tokens"] == 27_000.0
    assert views["top_models"]["pivot_total"].loc["2026-03-30", "Total Tokens"] != 51_400.0
    assert views["top_models"]["source_by_week"]["2026-03-30"] == "market_share"


def test_compute_openrouter_views_keeps_sunday_market_share_when_no_monday_snapshot_exists() -> None:
    top_models = pd.DataFrame(
        [
            {
                **_base_row("top_models"),
                "week_start_date": "2026-04-13",
                "entity_id": "openai/gpt-4o",
                "metric_value": 1_000.0,
            }
        ],
        columns=EXPECTED_COLUMNS,
    )
    market_share = pd.DataFrame(
        [
            {**_base_row("market_share"), "week_start_date": "2026-04-12", "entity_id": "openai", "metric_value": 8_000.0},
            {**_base_row("market_share"), "week_start_date": "2026-04-12", "entity_id": "others", "metric_value": 2_000.0},
        ],
        columns=EXPECTED_COLUMNS,
    )
    result_kwargs = {
        "domain": "rankings",
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
        "source_format": "csv",
        "source_path": None,
        "missing_columns": [],
        "duplicate_rows": 0,
        "first_date": "2026-04-12",
        "latest_date": "2026-04-12",
        "latest_scraped_at": "2026-04-13T00:00:00Z",
    }
    datasets = {
        "top_models": DatasetLoadResult(dataset_id="top_models", label="Top Models", frame=top_models, row_count=len(top_models), **result_kwargs),
        "market_share": DatasetLoadResult(dataset_id="market_share", label="Market Share", frame=market_share, row_count=len(market_share), **result_kwargs),
    }

    views = compute_openrouter_views(datasets)

    assert views["top_models"]["pivot_total"].loc["2026-04-13", "Total Tokens"] == 10_000.0
    assert views["top_models"]["source_by_week"]["2026-04-13"] == "market_share"


def test_compute_availability_views_reconstruct_catalog_from_full_and_delta_snapshots() -> None:
    rows: list[dict] = []

    for model_id in [f"model-{idx}" for idx in range(1, 6)]:
        row = _base_row("raw_openrouter_models")
        row.update(
            {
                "snapshot_ts": "2026-01-15T00:00:00Z",
                "model_id": model_id,
                "pricing_prompt": 0.001,
                "pricing_completion": 0.002,
                "context_length": 128000,
            }
        )
        rows.append(row)

    for model_id, prompt in [("model-3", 0.003), ("model-6", 0.0015)]:
        row = _base_row("raw_openrouter_models")
        row.update(
            {
                "snapshot_ts": "2026-01-16T00:00:00Z",
                "model_id": model_id,
                "pricing_prompt": prompt,
                "pricing_completion": prompt * 2,
                "context_length": 256000,
            }
        )
        rows.append(row)

    for model_id in [f"model-{idx}" for idx in range(1, 5)]:
        row = _base_row("raw_openrouter_models")
        row.update(
            {
                "snapshot_ts": "2026-01-17T00:00:00Z",
                "model_id": model_id,
                "pricing_prompt": 0.004,
                "pricing_completion": 0.008,
                "context_length": 512000,
            }
        )
        rows.append(row)

    raw_openrouter_models = pd.DataFrame(rows, columns=EXPECTED_COLUMNS)

    datasets = {
        "raw_openrouter_models": DatasetLoadResult(
            dataset_id="raw_openrouter_models",
            label="OpenRouter Catalog",
            domain="compute_availability",
            primary_date_column="snapshot_ts",
            metric_column="pricing_prompt",
            frame=raw_openrouter_models,
            source_format="csv",
            source_path=Path("data/normalized/compute_availability/raw_openrouter_models.csv"),
            missing_columns=[],
            duplicate_rows=0,
            first_date="2026-01-15",
            latest_date="2026-01-17",
            latest_scraped_at="2026-01-17T00:00:00Z",
            row_count=len(raw_openrouter_models),
        )
    }

    views = compute_compute_availability_views(datasets)
    models_growth = views["models_growth"]
    models_latest = views["models_latest"]

    assert models_growth["model_count"].tolist() == [5, 6, 4]
    assert set(models_latest["model_id"]) == {"model-1", "model-2", "model-3", "model-4"}
    latest_model_3 = models_latest[models_latest["model_id"] == "model-3"].iloc[0]
    assert latest_model_3["pricing_prompt"] == 0.004
    assert str(views["models_history_start"]).startswith("2026-01-15")
    assert str(views["models_history_end"]).startswith("2026-01-17")


def test_make_line_chart_handles_single_total_series_for_top_models() -> None:
    pivot = pd.DataFrame({"Total Tokens": [350.0, 300.0]}, index=["2026-03-09", "2026-03-16"])

    fig = make_line_chart(
        pivot,
        ["#4285F4"],
        y_title="Tokens",
        x_title="Usage Week (Starting)",
        hover_suffix="tokens",
    )

    assert len(fig.data) == 1
    assert fig.data[0].name == "Total Tokens"
    assert list(fig.data[0].x) == ["2026-03-09", "2026-03-16"]
    assert list(fig.data[0].y) == [350.0, 300.0]
    assert "%{y:,.0f} tokens" in fig.data[0].hovertemplate


def test_grouped_revenue_token_pivots_share_aligned_display_provider_buckets() -> None:
    rev_data = {
        "pivot_rev_weekly": pd.DataFrame(
            {
                "OpenAI": [100.0],
                "Microsoft": [20.0],
                "StepFun": [5.0],
                "Others": [3.0],
            },
            index=["2026-01-05"],
        )
    }
    tok_data = {
        "pivot_weekly": pd.DataFrame(
            {
                "OpenAI": [1000.0],
                "Microsoft": [200.0],
                "StepFun": [50.0],
                "Others": [30.0],
            },
            index=["2026-01-05"],
        )
    }

    rev_grouped, tok_grouped = grouped_revenue_token_pivots(rev_data, tok_data, "weekly")

    assert list(rev_grouped.columns) == ["OpenAI", "StepFun", "Others"]
    assert list(tok_grouped.columns) == ["OpenAI", "StepFun", "Others"]
    assert rev_grouped.loc["2026-01-05", "StepFun"] == 5.0
    assert tok_grouped.loc["2026-01-05", "StepFun"] == 50.0
    assert rev_grouped.loc["2026-01-05", "Others"] == 23.0
    assert tok_grouped.loc["2026-01-05", "Others"] == 230.0


def test_pivot_to_change_percent_computes_provider_week_over_week() -> None:
    pivot = pd.DataFrame(
        {
            "OpenAI": [100.0, 125.0, 100.0],
            "Google": [50.0, 50.0, 75.0],
        },
        index=["2026-01-05", "2026-01-12", "2026-01-19"],
    )

    changed = _pivot_to_change_percent(pivot, "weekly")

    assert pd.isna(changed.loc["2026-01-05", "OpenAI"])
    assert changed.loc["2026-01-12", "OpenAI"] == 25.0
    assert changed.loc["2026-01-19", "OpenAI"] == -20.0
    assert changed.loc["2026-01-19", "Google"] == 50.0


def test_pivot_to_change_percent_daily_uses_trailing_seven_day_average_change() -> None:
    pivot = pd.DataFrame(
        {
            "OpenAI": [100.0] * 7 + [110.0] * 7,
            "Google": [50.0] * 7 + [25.0] * 7,
        },
        index=pd.date_range("2026-01-01", periods=14, freq="D").strftime("%Y-%m-%d"),
    )

    changed = _pivot_to_change_percent(pivot, "daily")

    assert changed.iloc[6].isna().all()
    assert changed.iloc[13]["OpenAI"] == 10.0
    assert changed.iloc[13]["Google"] == -50.0


def test_pivot_to_aggregate_change_percent_uses_total_period_values() -> None:
    pivot = pd.DataFrame(
        {
            "OpenAI": [100.0, 125.0, 100.0],
            "Google": [50.0, 75.0, 100.0],
        },
        index=["2026-01-05", "2026-01-12", "2026-01-19"],
    )

    changed = _pivot_to_aggregate_change_percent(pivot, "weekly", "Total Tokens")

    assert list(changed.columns) == ["Total Tokens"]
    assert pd.isna(changed.loc["2026-01-05", "Total Tokens"])
    assert changed.loc["2026-01-12", "Total Tokens"] == pytest.approx(33.3333333333)
    assert changed.loc["2026-01-19", "Total Tokens"] == 0.0


def test_pivot_to_aggregate_change_percent_daily_uses_total_trailing_average() -> None:
    pivot = pd.DataFrame(
        {
            "OpenAI": [100.0] * 7 + [110.0] * 7,
            "Google": [50.0] * 7 + [40.0] * 7,
        },
        index=pd.date_range("2026-01-01", periods=14, freq="D").strftime("%Y-%m-%d"),
    )

    changed = _pivot_to_aggregate_change_percent(pivot, "daily", "Total Revenue")

    assert list(changed.columns) == ["Total Revenue"]
    assert changed.iloc[6]["Total Revenue"] is pd.NA or pd.isna(changed.iloc[6]["Total Revenue"])
    assert changed.iloc[13]["Total Revenue"] == 0.0


def test_drop_first_valid_change_point_removes_initial_weekly_spike() -> None:
    changed = pd.DataFrame(
        {"Total Revenue": [pd.NA, 300.0, 20.0]},
        index=["2026-01-05", "2026-01-12", "2026-01-19"],
    )

    cleaned = _drop_first_valid_change_point(changed)

    assert pd.isna(cleaned.loc["2026-01-05", "Total Revenue"])
    assert pd.isna(cleaned.loc["2026-01-12", "Total Revenue"])
    assert cleaned.loc["2026-01-19", "Total Revenue"] == 20.0


def test_nowcast_latest_partial_week_scales_from_daily_observations() -> None:
    weekly = pd.DataFrame(
        {"OpenAI": [700.0, 200.0]},
        index=["2026-06-22", "2026-06-29"],
    )
    daily = pd.DataFrame(
        {"OpenAI": [100.0, 100.0]},
        index=["2026-06-29", "2026-06-30"],
    )

    nowcast, estimates = _nowcast_latest_partial_period(weekly, daily, "weekly")

    assert estimates == {"2026-06-29"}
    assert nowcast.loc["2026-06-29", "OpenAI"] == 700.0


def test_nowcast_latest_partial_month_scales_from_daily_observations() -> None:
    monthly = pd.DataFrame(
        {"OpenAI": [3000.0, 200.0]},
        index=["2026-06", "2026-07"],
    )
    daily = pd.DataFrame(
        {"OpenAI": [100.0, 100.0]},
        index=["2026-07-01", "2026-07-02"],
    )

    nowcast, estimates = _nowcast_latest_partial_period(monthly, daily, "monthly")

    assert estimates == {"2026-07"}
    assert nowcast.loc["2026-07", "OpenAI"] == 3100.0


def test_cap_change_percent_for_display_preserves_readable_momentum_range() -> None:
    pivot = pd.DataFrame(
        {
            "OpenAI": [25.0, 500.0],
            "Google": [-25.0, -150.0],
            "Anthropic": [pd.NA, 75.0],
        },
        index=["2026-01-05", "2026-01-12"],
    )

    capped = _cap_change_percent_for_display(pivot)

    assert capped.loc["2026-01-12", "OpenAI"] == 300.0
    assert capped.loc["2026-01-12", "Google"] == -100.0
    assert pd.isna(capped.loc["2026-01-05", "Anthropic"])
    assert capped.loc["2026-01-12", "Anthropic"] == 75.0


def test_top_n_with_others_preserves_existing_others_bucket() -> None:
    pivot = pd.DataFrame(
        {
            "A": [100.0, 10.0],
            "B": [90.0, 9.0],
            "Others": [80.0, 8.0],
            "C": [70.0, 7.0],
        },
        index=["w1", "w2"],
    )

    top = _top_n_with_others(pivot, top_n_count=3)

    assert list(top.columns) == ["A", "B", "Others"]
    assert top.loc["w1", "Others"] == 150.0
    assert top.loc["w2", "Others"] == 15.0


def test_artificial_analysis_domain_loads_normalized_datasets(tmp_path: Path) -> None:
    _write_dataset(tmp_path, "artificial_analysis_models_daily", _artificial_analysis_models_frame())
    _write_dataset(tmp_path, "artificial_analysis_capex_quarterly", _artificial_analysis_capex_frame())

    datasets = load_domain_datasets("artificial_analysis", base_dir=tmp_path)

    assert set(datasets) == {
        "artificial_analysis_models_daily",
        "artificial_analysis_leading_models_by_lab_daily",
        "artificial_analysis_capex_quarterly",
    }
    assert datasets["artificial_analysis_models_daily"].row_count == 5
    assert datasets["artificial_analysis_capex_quarterly"].row_count == 2
    assert datasets["artificial_analysis_models_daily"].latest_date == "2026-04-25"
    assert datasets["artificial_analysis_models_daily"].missing_columns == []
    assert datasets["artificial_analysis_capex_quarterly"].missing_columns == []


def test_compute_artificial_analysis_views_builds_priority_charts(tmp_path: Path) -> None:
    _write_dataset(tmp_path, "artificial_analysis_models_daily", _artificial_analysis_models_frame())
    _write_dataset(tmp_path, "artificial_analysis_capex_quarterly", _artificial_analysis_capex_frame())
    datasets = load_domain_datasets("artificial_analysis", base_dir=tmp_path)

    views = compute_artificial_analysis_views(datasets)

    capex = views["capex_pivot"]
    frontier = views["frontier_by_lab_pivot"]
    price = views["price_models"]
    country = views["frontier_by_country_pivot"]
    country_points = views["frontier_by_country_points"]
    china_lag = views["china_catchup_lag"]
    openness = views["open_vs_proprietary_pivot"]

    assert capex.index.tolist() == ["Q4-2024", "Q1-2025"]
    assert "Microsoft" in capex.columns
    assert frontier.loc[pd.Timestamp("2025-03-15"), "OpenAI"] == 41.0
    assert price["price_1m_blended_3_to_1"].tolist() == [3.0, 0.4, 2.5, 0.2]
    assert set(country.columns) == {"United States", "China"}
    assert country.loc[pd.Timestamp("2025-03-15"), "United States"] == 41.0
    assert country.loc[pd.Timestamp("2025-04-10"), "China"] == 39.0
    us_frontier = country_points[
        (country_points["country_label"] == "United States")
        & (country_points["release_date"] == pd.Timestamp("2025-03-15"))
    ].iloc[0]
    china_frontier = country_points[
        (country_points["country_label"] == "China")
        & (country_points["release_date"] == pd.Timestamp("2025-04-10"))
    ].iloc[0]
    assert us_frontier["model_name"] == "OpenAI B"
    assert us_frontier["creator_name"] == "OpenAI"
    assert china_frontier["model_name"] == "DeepSeek Frontier"
    assert china_frontier["creator_name"] == "DeepSeek"
    assert china_lag["status"].tolist() == ["caught_up", "not_yet_caught"]
    assert china_lag["us_intelligence_index"].tolist() == [35.0, 41.0]
    assert china_lag.loc[0, "china_catchup_date"] == "2025-04-10"
    assert pd.isna(china_lag.loc[1, "china_catchup_date"])
    assert china_lag["lag_months"].round(1).tolist() == [2.8, 1.5]
    assert openness.loc[pd.Timestamp("2025-03-15"), "Proprietary"] == 41.0
    assert openness.loc[pd.Timestamp("2025-03-15"), "Open Weights"] == 33.0

    capex_yoy = views["capex_yoy_growth"]
    assert capex_yoy.empty


def test_compute_artificial_analysis_views_calculates_yoy(tmp_path: Path) -> None:
    # Create 5 quarters of capex data
    quarters = ["2024-q1", "2024-q2", "2024-q3", "2024-q4", "2025-q1"]
    quarter_labels = ["Q1-2024", "Q2-2024", "Q3-2024", "Q4-2024", "Q1-2025"]
    rows = []
    for q_id, q_label in zip(quarters, quarter_labels):
        rows.append({
            "dataset_id": "artificial_analysis_capex_quarterly",
            "quarter_id": q_id,
            "quarter_label": q_label,
            "microsoft": 10.0,
            "google": 10.0,
            "meta": 10.0,
            "amazon": 10.0,
            "oracle": 10.0,
            "apple": 10.0,
            "source_url": "https://artificialanalysis.ai/trends",
            "page_url": "https://artificialanalysis.ai/trends",
            "bundle_url": "https://artificialanalysis.ai/_next/static/chunks/app/(pages)/trends/page-demo.js",
            "source_run_id": "run-aa",
            "scraped_at": "2026-04-25T00:00:00Z",
        })
    
    # For the last quarter (Q1-2025), let's make microsoft have 15.0 (+50% YoY growth),
    # Google have 5.0 (-50% YoY growth), and others stay 10.0.
    rows[-1]["microsoft"] = 15.0
    rows[-1]["google"] = 5.0
    
    _write_dataset(tmp_path, "artificial_analysis_models_daily", _artificial_analysis_models_frame())
    _write_dataset(tmp_path, "artificial_analysis_capex_quarterly", pd.DataFrame(rows))
    datasets = load_domain_datasets("artificial_analysis", base_dir=tmp_path)

    views = compute_artificial_analysis_views(datasets)
    capex_yoy = views["capex_yoy_growth"]
    
    # It should have exactly 1 row (since first 4 are dropped)
    assert len(capex_yoy) == 1
    assert capex_yoy.index.tolist() == ["Q1-2025"]
    
    # microsoft went from 10.0 to 15.0 (+50%)
    assert capex_yoy.loc["Q1-2025", "Microsoft"] == 50.0
    # google went from 10.0 to 5.0 (-50%)
    assert capex_yoy.loc["Q1-2025", "Google"] == -50.0
    # others stayed the same (0%)
    assert capex_yoy.loc["Q1-2025", "Meta"] == 0.0
    
    # Aggregated:
    # Q1-2024 sum: 10 + 10 + 10 + 10 + 10 + 10 = 60
    # Q1-2025 sum: 15 + 5 + 10 + 10 + 10 + 10 = 60
    # YoY growth of sum: 0%
    assert capex_yoy.loc["Q1-2025", "Aggregated"] == 0.0


def test_latest_provider_market_coverage_reconciles_to_official_total() -> None:
    def result(dataset_id: str, frame: pd.DataFrame) -> DatasetLoadResult:
        return DatasetLoadResult(
            dataset_id=dataset_id,
            label=dataset_id,
            domain="rankings",
            primary_date_column="usage_date",
            metric_column="total_tokens",
            frame=frame,
            source_format="parquet",
            source_path=None,
            missing_columns=[],
            duplicate_rows=0,
            first_date="2026-07-16",
            latest_date="2026-07-17",
            latest_scraped_at="2026-07-18T00:00:00Z",
            row_count=len(frame),
        )

    official = pd.DataFrame(
        {
            "usage_date": ["2026-07-16", "2026-07-17", "2026-07-17"],
            "total_tokens": [80.0, 60.0, 40.0],
        }
    )
    providers = pd.DataFrame(
        {
            "usage_date": ["2026-07-17", "2026-07-17"],
            "entity_id": ["openai", "anthropic"],
        }
    )
    plotted = pd.DataFrame(
        {"OpenAI": [55.0], "Anthropic": [35.0]},
        index=["2026-07-17"],
    )

    coverage, coverage_date, provider_count = _latest_provider_market_coverage(
        {
            "official_model_rankings_daily": result("official_model_rankings_daily", official),
            "provider_daily_activity": result("provider_daily_activity", providers),
        },
        plotted,
    )

    assert coverage == pytest.approx(0.9)
    assert coverage_date == "2026-07-17"
    assert provider_count == 2
