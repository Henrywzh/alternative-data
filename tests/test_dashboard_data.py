from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from dashboard.checks import run_checks
from dashboard.data import (
    EXPECTED_COLUMNS,
    DATASET_REGISTRY,
    domain_dataset_ids,
    load_all_datasets,
    load_dataset,
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
    _provider_candidates_frame().to_csv(root / "github_repo_candidates_daily.csv", index=False)
    _provider_signals_frame().to_csv(root / "github_provider_signals_daily.csv", index=False)
    _provider_rollup_frame().to_csv(root / "github_repo_rollup_daily.csv", index=False)

    datasets = load_all_datasets(base_dir=tmp_path)
    checks = run_checks(datasets, load_latest_manifest(base_dir=tmp_path), base_dir=tmp_path)

    assert datasets["pypi_downloads_daily"].row_count == 6
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
        "github_repo_candidates_daily": _provider_candidates_frame,
        "github_provider_signals_daily": _provider_signals_frame,
        "github_repo_rollup_daily": _provider_rollup_frame,
        "provider_momentum_daily": _provider_momentum_frame,
    }
    return mapping[dataset_id]()


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
