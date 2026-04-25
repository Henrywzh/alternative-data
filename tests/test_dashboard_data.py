from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
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
    market_share_legend_rows,
    prepare_hf_models_table,
    resolve_hf_metric_config,
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
    dataset_source_for_domain,
    domain_dataset_ids,
    load_all_datasets,
    load_dataset,
    load_domain_datasets,
    load_latest_manifest,
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
                "creator_country": "us",
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
                "creator_country": "us",
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
                "creator_country": "us",
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


def test_load_all_datasets_supports_every_registered_dataset(tmp_path: Path) -> None:
    for dataset_id in DATASET_REGISTRY:
        domain = DATASET_REGISTRY[dataset_id]["domain"]
        source = "openrouter"
        if domain == "github":
            source = "github_trending"
        elif domain == "provider_adoption":
            source = "provider_adoption"
        root = tmp_path / "data" / "normalized" / source
        root.mkdir(parents=True, exist_ok=True)
        _frame_for_dataset(dataset_id).to_csv(root / f"{dataset_id}.csv", index=False)

    datasets = load_all_datasets(base_dir=tmp_path)

    assert set(datasets) == set(DATASET_REGISTRY)
    assert datasets["apps_global_ranking_snapshots"].latest_date == "2026-04-05"
    assert datasets["top_models"].latest_date == "2026-03-16"
    assert datasets["provider_momentum_daily"].latest_date == "2026-04-05"


def test_compute_provider_adoption_views_includes_hf_aggregates_and_latest_models(tmp_path: Path) -> None:
    root = tmp_path / "data" / "normalized" / "provider_adoption"
    root.mkdir(parents=True, exist_ok=True)
    _provider_pypi_frame().to_csv(root / "pypi_downloads_daily.csv", index=False)
    _provider_npm_frame().to_csv(root / "npm_downloads_daily.csv", index=False)
    _provider_hf_frame().to_csv(root / "huggingface_models_daily.csv", index=False)
    _provider_candidates_frame().to_csv(root / "github_repo_candidates_daily.csv", index=False)
    _provider_signals_frame().to_csv(root / "github_provider_signals_daily.csv", index=False)
    _provider_rollup_frame().to_csv(root / "github_repo_rollup_daily.csv", index=False)
    _provider_momentum_frame().to_csv(root / "provider_momentum_daily.csv", index=False)

    datasets = load_all_datasets(base_dir=tmp_path)
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
    _provider_candidates_frame().to_csv(root / "github_repo_candidates_daily.csv", index=False)
    _provider_signals_frame().to_csv(root / "github_provider_signals_daily.csv", index=False)

    rollup = _provider_rollup_frame()
    zero_row = _base_row("github_repo_rollup_daily")
    zero_row.update(
        {
            "provider": "openai",
            "provider_display_name": "OpenAI",
            "repo_full_name": "openai/zero-signal-repo",
            "repo_owner": "openai",
            "repo_name": "zero-signal-repo",
            "repo_html_url": "https://github.com/openai/zero-signal-repo",
            "repo_created_date": "2026-04-05",
            "repo_created_at": "2026-04-05T12:00:00Z",
            "repo_pushed_at": "2026-04-05T12:30:00Z",
            "repo_default_branch": "main",
            "language_bucket": "python",
            "signal_date": "2026-04-05",
            "has_manifest_dependency": False,
            "has_code_import": False,
            "has_env_var": False,
            "has_model_name": False,
            "matched_signal_count": 0,
            "stargazers_count": 1,
            "is_fork": False,
            "is_archived": False,
        }
    )
    rollup = pd.concat([rollup, pd.DataFrame([zero_row], columns=EXPECTED_COLUMNS)], ignore_index=True)
    rollup.to_csv(root / "github_repo_rollup_daily.csv", index=False)
    _provider_momentum_frame().to_csv(root / "provider_momentum_daily.csv", index=False)

    datasets = load_all_datasets(base_dir=tmp_path)
    views = compute_provider_adoption_views(datasets)

    rollup_daily = views["rollup_daily"].sort_values(["signal_date", "provider_display_name"]).reset_index(drop=True)
    candidates_daily = views["candidates_daily"].sort_values(["repo_created_date"]).reset_index(drop=True)

    openai_rollup = rollup_daily[rollup_daily["provider_display_name"] == "OpenAI"].iloc[0]
    assert int(openai_rollup["signal_repos"]) == 1
    assert int(openai_rollup["manifest_repos"]) == 1
    assert int(openai_rollup["import_repos"]) == 1
    assert int(openai_rollup["model_repos"]) == 1

    assert list(candidates_daily.columns) == ["repo_created_date", "repo_candidates"]
    assert int(candidates_daily.iloc[0]["repo_candidates"]) == 3


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


def test_prepare_hf_models_table_returns_empty_for_all_view() -> None:
    table = prepare_hf_models_table(_provider_hf_frame(), provider_display_name="All")

    assert table.empty
    assert list(table.columns) == ["Provider", "Model", "30d Downloads", "All-Time Downloads", "Daily (Est)", "Likes", "Last Modified"]


def test_prepare_hf_models_table_limits_to_top_20_for_selected_provider() -> None:
    table = prepare_hf_models_table(_provider_hf_large_frame(), provider_display_name="Qwen", limit=20)

    assert len(table) == 20
    assert table.iloc[0]["Model"] == "Qwen/model-00"
    assert table.iloc[-1]["Model"] == "Qwen/model-19"


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
    _provider_candidates_frame().to_csv(root / "github_repo_candidates_daily.csv", index=False)
    _provider_signals_frame().to_csv(root / "github_provider_signals_daily.csv", index=False)
    _provider_rollup_frame().to_csv(root / "github_repo_rollup_daily.csv", index=False)
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
        },
        index=["2026-01-05", "2026-01-12"],
    )

    regrouped = regroup_provider_pivot_for_display(pivot, "weekly")

    assert list(regrouped.columns) == ["OpenAI", "Others"]
    assert regrouped.loc["2026-01-05", "Others"] == 77.0
    assert regrouped.loc["2026-01-12", "Others"] == 84.0


def test_regroup_provider_pivot_for_display_daily_uses_daily_bucket_rules() -> None:
    pivot = pd.DataFrame(
        {
            "OpenAI": [100.0],
            "Microsoft": [20.0],
            "Meta (Llama)": [30.0],
            "Mistral AI": [40.0],
            "Google": [50.0],
        },
        index=["2026-04-05"],
    )

    regrouped = regroup_provider_pivot_for_display(pivot, "daily")

    assert list(regrouped.columns) == ["OpenAI", "Google", "Others"]
    assert regrouped.loc["2026-04-05", "Others"] == 90.0


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


def test_derive_provider_name_normalizes_meta_llama_slug() -> None:
    assert _derive_provider_name("meta-llama/model", None) == "Meta (Llama)"


def test_derive_provider_name_normalizes_z_ai_slug() -> None:
    assert _derive_provider_name("z-ai/model", None) == "智谱AI (Z.ai)"


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
    assert revenue_weekly.loc["2026-01-05", "智谱AI (Z.ai)"] > 0


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

    assert token_weekly.loc["2026-01-05", "智谱AI (Z.ai)"] == 250.0
    assert token_weekly.loc["2026-01-12", "智谱AI (Z.ai)"] == 840.0


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

    assert list(rev_grouped.columns) == ["OpenAI", "Others"]
    assert list(tok_grouped.columns) == ["OpenAI", "Others"]
    assert rev_grouped.loc["2026-01-05", "Others"] == 28.0
    assert tok_grouped.loc["2026-01-05", "Others"] == 280.0


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


def test_market_share_legend_rows_use_selected_week_tokens_not_cumulative() -> None:
    frame = pd.DataFrame(
        {
            "week_start_date": ["2026-04-05", "2026-04-05", "2026-04-12", "2026-04-12"],
            "entity_id": ["qwen", "google", "qwen", "google"],
            "metric_value": [100.0, 50.0, 1000.0, 200.0],
        }
    )

    rows = market_share_legend_rows(frame, "2026-04-05", limit=8)

    assert rows["entity_id"].tolist() == ["qwen", "google"]
    assert rows["metric_value"].tolist() == [100.0, 50.0]
    assert rows["share_pct"].round(1).tolist() == [66.7, 33.3]


def test_artificial_analysis_domain_loads_normalized_datasets(tmp_path: Path) -> None:
    _write_dataset(tmp_path, "artificial_analysis_models_daily", _artificial_analysis_models_frame())
    _write_dataset(tmp_path, "artificial_analysis_capex_quarterly", _artificial_analysis_capex_frame())

    datasets = load_domain_datasets("artificial_analysis", base_dir=tmp_path)

    assert set(datasets) == {
        "artificial_analysis_models_daily",
        "artificial_analysis_leading_models_by_lab_daily",
        "artificial_analysis_capex_quarterly",
    }
    assert datasets["artificial_analysis_models_daily"].row_count == 3
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
    openness = views["open_vs_proprietary_pivot"]

    assert capex.index.tolist() == ["Q4-2024", "Q1-2025"]
    assert "Microsoft" in capex.columns
    assert frontier.loc[pd.Timestamp("2025-03-15"), "OpenAI"] == 41.0
    assert price["price_1m_blended_3_to_1"].tolist() == [3.0, 0.4, 2.5]
    assert country.loc[pd.Timestamp("2025-03-15"), "US"] == 41.0
    assert openness.loc[pd.Timestamp("2025-03-15"), "Proprietary"] == 41.0
    assert openness.loc[pd.Timestamp("2025-03-15"), "Open Weights"] == 33.0
