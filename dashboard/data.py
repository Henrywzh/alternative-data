from __future__ import annotations

import io
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from pyarrow.lib import ArrowInvalid

from dashboard import remote


def _read_parquet_projected(source, columns: list[str] | None) -> pd.DataFrame:
    """Read projected Parquet columns with a schema-transition fallback."""
    try:
        return pd.read_parquet(source, columns=columns)
    except (ArrowInvalid, KeyError, ValueError):
        if columns is None:
            raise
        if hasattr(source, "seek"):
            source.seek(0)
        available = set(pq.ParquetFile(source).schema_arrow.names)
        projected = [column for column in columns if column in available]
        if len(projected) == len(columns):
            raise
        if hasattr(source, "seek"):
            source.seek(0)
        # Retry only the available projection. Missing transition columns are
        # supplied later by reindexing without ever loading the full table.
        return pd.read_parquet(source, columns=projected)


DATASET_REGISTRY: dict[str, dict[str, object]] = {
    "top_models": {
        "label": "Top Models",
        "domain": "rankings",
        "natural_keys": ["week_start_date", "entity_id"],
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
        "required_columns": ["week_start_date", "entity_id", "metric_value", "rank"],
    },
    "market_share": {
        "label": "Market Share",
        "domain": "rankings",
        "natural_keys": ["week_start_date", "entity_id"],
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
        "required_columns": ["week_start_date", "entity_id", "metric_value", "rank"],
    },
    "provider_weekly_requests": {
        "label": "Provider Weekly Requests",
        "domain": "rankings",
        # OpenRouter's rankings page does not currently publish a provider
        # request-count feed. Keep this contract for older snapshots, but do
        # not treat its absence/empty state as a pipeline failure.
        "optional": True,
        "natural_keys": ["week_start_date", "entity_id"],
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
        "required_columns": ["week_start_date", "entity_id", "metric_value", "rank"],
    },
    "context_length_requests": {
        "label": "Context Length Requests",
        "domain": "rankings",
        "natural_keys": ["week_start_date", "context_length_bucket", "entity_id"],
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
        "required_columns": [
            "week_start_date",
            "context_length_bucket",
            "entity_id",
            "metric_value",
            "rank",
        ],
    },
    "modality_rankings": {
        "label": "Modality Rankings",
        "domain": "rankings",
        "natural_keys": ["week_start_date", "modality", "entity_id"],
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
        "required_columns": [
            "week_start_date",
            "modality",
            "entity_id",
            "metric_value",
            "rank",
        ],
    },
    # NOTE: This dataset is no longer rendered in the dashboard, but it is still
    # produced by the rankings pipeline and consumed by research marts/tests.
    "categories_programming": {
        "label": "Programming",
        "domain": "rankings",
        "natural_keys": ["week_start_date", "category_slug", "entity_id"],
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
        "required_columns": ["week_start_date", "category_slug", "entity_id", "metric_value", "rank"],
    },
    "vercel_model_leaderboard": {
        "label": "Vercel Model Leaderboard",
        "domain": "vercel_ai",
        "natural_keys": ["date", "name", "metric", "modality"],
        "primary_date_column": "date",
        "metric_column": "share_percent",
        "required_columns": ["date", "name", "metric", "modality", "share_percent"],
    },
    "vercel_lab_leaderboard": {
        "label": "Vercel Lab Leaderboard",
        "domain": "vercel_ai",
        "natural_keys": ["date", "name", "metric", "modality"],
        "primary_date_column": "date",
        "metric_column": "share_percent",
        "required_columns": ["date", "name", "metric", "modality", "share_percent"],
    },
    "vercel_models": {
        "label": "Vercel Models Catalog",
        "domain": "vercel_ai",
        "natural_keys": ["model_id"],
        "primary_date_column": "scraped_at",
        "metric_column": None,
        "required_columns": ["model_id", "name", "owned_by", "type"],
    },
    "app_metadata_snapshots": {
        "label": "App Metadata",
        "domain": "apps",
        "natural_keys": ["app_id", "scrape_date"],
        "primary_date_column": "scrape_date",
        "metric_column": None,
        "required_columns": ["app_id", "app_name", "scrape_date"],
    },
    "app_usage_daily": {
        "label": "App Usage Daily",
        "domain": "apps",
        "natural_keys": ["app_id", "usage_date", "model_permaslug"],
        "primary_date_column": "usage_date",
        "metric_column": "total_tokens",
        "required_columns": ["app_id", "usage_date", "model_permaslug", "total_tokens"],
    },
    "app_top_models_daily_snapshot": {
        "label": "App Top Models",
        "domain": "apps",
        "natural_keys": ["app_id", "snapshot_date", "model_permaslug"],
        "primary_date_column": "snapshot_date",
        "metric_column": "total_tokens",
        "required_columns": ["app_id", "snapshot_date", "model_permaslug", "total_tokens"],
    },
    "apps_global_ranking_snapshots": {
        "label": "Global App Rankings",
        "domain": "apps",
        "natural_keys": ["snapshot_date", "period", "rank"],
        "primary_date_column": "snapshot_date",
        "metric_column": "tokens",
        "required_columns": ["app_id", "snapshot_date", "period", "tokens", "rank"],
    },
    "apps_trending_snapshots": {
        "label": "Trending Apps",
        "domain": "apps",
        "natural_keys": ["snapshot_date", "rank"],
        "primary_date_column": "snapshot_date",
        "metric_column": "tokens",
        "required_columns": ["app_id", "snapshot_date", "growth_percent", "tokens", "rank"],
    },
    "pypi_downloads_daily": {
        "label": "PyPI Downloads Daily",
        "domain": "provider_adoption",
        "natural_keys": ["provider", "package_name", "with_mirrors", "download_date"],
        "primary_date_column": "download_date",
        "metric_column": "downloads",
        "required_columns": ["provider", "package_name", "package_category", "with_mirrors", "download_date", "downloads"],
    },
    "npm_downloads_daily": {
        "label": "npm Downloads Daily",
        "domain": "provider_adoption",
        "natural_keys": ["provider", "package_name", "package_category", "download_date"],
        "primary_date_column": "download_date",
        "metric_column": "downloads",
        "required_columns": ["provider", "package_name", "package_category", "download_date", "downloads"],
    },
    "github_repo_candidates_daily": {
        "label": "GitHub Repo Candidates",
        "domain": "provider_adoption",
        "natural_keys": ["provider", "repo_full_name", "repo_created_date"],
        "primary_date_column": "repo_created_date",
        "metric_column": "stargazers_count",
        "required_columns": ["provider", "repo_full_name", "repo_created_date", "language_bucket", "stargazers_count"],
    },
    "github_provider_signals_daily": {
        "label": "GitHub Provider Signals",
        "domain": "provider_adoption",
        "natural_keys": ["provider", "repo_full_name", "signal_date", "signal_type"],
        "primary_date_column": "signal_date",
        "metric_column": "stargazers_count",
        "required_columns": ["provider", "repo_full_name", "signal_date", "signal_type", "matched_file_path"],
    },
    "github_repo_rollup_daily": {
        "label": "GitHub Repo Rollups",
        "domain": "provider_adoption",
        "natural_keys": ["provider", "repo_full_name", "signal_date"],
        "primary_date_column": "signal_date",
        "metric_column": "matched_signal_count",
        "required_columns": ["provider", "repo_full_name", "signal_date", "matched_signal_count"],
    },
    "github_provider_adoption_daily": {
        "label": "GitHub Provider Adoption",
        "domain": "provider_adoption",
        "natural_keys": ["provider", "signal_date"],
        "primary_date_column": "signal_date",
        "metric_column": "github_signal_repo_count",
        "required_columns": [
            "provider",
            "provider_display_name",
            "signal_date",
            "github_new_repo_count",
            "github_signal_repo_count",
            "github_import_repo_count",
        ],
    },
    "provider_momentum_daily": {
        "label": "Provider Momentum",
        "domain": "provider_adoption",
        "natural_keys": ["provider", "signal_date"],
        "primary_date_column": "signal_date",
        "metric_column": "momentum_score",
        "required_columns": ["provider", "signal_date", "momentum_score", "pypi_share_28d", "github_repo_share"],
    },
    "huggingface_models_daily": {
        "label": "Hugging Face Models",
        "domain": "provider_adoption",
        "natural_keys": ["provider", "author", "model_id", "download_date"],
        "primary_date_column": "download_date",
        "metric_column": "hf_downloads_daily_est",
        "required_columns": ["provider", "author", "model_id", "download_date", "hf_downloads_daily_est"],
    },
    "semiconductor_memory_regime_monthly": {
        "label": "Semiconductor Market Regimes",
        "domain": "semiconductor_memory",
        "natural_keys": ["month"],
        "primary_date_column": "month",
        "metric_column": "fred_ppi_value",
        "required_columns": ["month", "nand_regime_label", "dram_regime_label", "fred_ppi_value"],
    },
    "fred_semiconductor_ppi_monthly": {
        "label": "AI Demand PPI (FRED)",
        "domain": "semiconductor_memory",
        "natural_keys": ["month"],
        "primary_date_column": "month",
        "metric_column": "fred_ppi_value",
        "required_columns": ["month", "fred_ppi_value"],
    },
    "adata_marketwatch_images": {
        "label": "Memory Market Images",
        "domain": "semiconductor_memory",
        "natural_keys": ["month", "image_url"],
        "primary_date_column": "month",
        "metric_column": None,
        "required_columns": ["month", "image_url", "local_path", "image_type"],
    },
    "semiconductor_official_monthly": {
        "label": "Semiconductor Official Monthly",
        "domain": "semiconductor_proxies",
        "natural_keys": ["source_region", "metric_type", "category_id", "flow_code", "period", "partner_scope"],
        "primary_date_column": "period",
        "metric_column": "value",
        "required_columns": [
            "source_region",
            "country_name",
            "metric_type",
            "flow_code",
            "partner_scope",
            "period",
            "category_id",
            "classification_code",
            "value",
        ],
    },
    "semiconductor_backup_check_monthly": {
        "label": "Semiconductor Backup Check Monthly",
        "domain": "semiconductor_proxies",
        "natural_keys": ["source_region", "metric_type", "category_id", "flow_code", "period", "partner_scope", "source_name"],
        "primary_date_column": "period",
        "metric_column": "value",
        "required_columns": [
            "source_region",
            "country_name",
            "metric_type",
            "flow_code",
            "partner_scope",
            "period",
            "category_id",
            "classification_code",
            "value",
            "comparison_gap_pct",
        ],
    },
    "semiconductor_source_catalog": {
        "label": "Semiconductor Source Catalog",
        "domain": "semiconductor_proxies",
        "natural_keys": ["source_region", "source_name", "metric_type", "category_id", "source_tier"],
        "primary_date_column": "latest_period",
        "metric_column": None,
        "required_columns": [
            "source_region",
            "country_name",
            "source_name",
            "source_tier",
            "metric_type",
            "category_id",
            "latest_period",
            "expected_release_window_days",
        ],
    },
    "tw_monthly_revenue": {
        "label": "Taiwan Monthly Revenue",
        "domain": "taiwan_semiconductor_revenue",
        "natural_keys": ["company_code", "revenue_month"],
        "primary_date_column": "revenue_month",
        "metric_column": "monthly_revenue_ntd",
        "required_columns": [
            "company_code",
            "company_name",
            "market",
            "industry",
            "filing_date",
            "revenue_month",
            "monthly_revenue_ntd",
            "yoy_pct",
            "ytd_revenue_ntd",
            "ytd_yoy_pct",
        ],
    },
    "llm_benchmarks": {
        "label": "LLM Benchmarks",
        "domain": "ai_frontier",
        "natural_keys": ["model_id"],
        "primary_date_column": "release_date",
        "metric_column": "gpqa",
        "required_columns": ["model_id", "name", "organization", "release_date", "gpqa", "swe_bench", "context_window"],
    },
    # NOTE: "compute_availability" is a legacy domain name. After removing AWS Spot +
    # Lambda Cloud, this domain holds only the OpenRouter model catalog. Kept for
    # file-path stability (data/normalized/compute_availability/).
    "raw_openrouter_models": {
        "label": "OpenRouter Catalog",
        "domain": "compute_availability",
        "natural_keys": ["model_id", "snapshot_ts"],
        "primary_date_column": "snapshot_ts",
        "metric_column": "pricing_prompt",
        "required_columns": [
            "model_id",
            "snapshot_ts",
            "pricing_prompt",
            "pricing_completion",
            "context_length",
            "top_provider_id",
            "canonical_slug",
            "provider_prefix",
        ],
    },
    "openrouter_model_activity": {
        "label": "Model Activity Splits",
        "domain": "rankings",
        "natural_keys": ["usage_date", "model_permaslug", "category_slug"],
        "primary_date_column": "usage_date",
        "metric_column": "prompt_tokens",
        "required_columns": ["usage_date", "model_permaslug", "category_slug", "prompt_tokens", "completion_tokens", "request_count"],
    },
    "provider_daily_activity": {
        "label": "Provider Daily Activity",
        "domain": "rankings",
        # Provider pages include the synthetic `Others` bucket alongside the
        # named provider/model rows.  The same model key can therefore occur
        # on multiple provider pages on one day; provider identity is part of
        # the stored grain (matching openrouter_data.storage.NATURAL_KEYS).
        "natural_keys": ["usage_date", "entity_id", "model_permaslug"],
        "primary_date_column": "usage_date",
        "metric_column": "total_tokens",
        "required_columns": ["usage_date", "entity_id", "model_permaslug", "total_tokens"],
    },
    "cloud_infra_daily_activity": {
        "label": "Serving-Provider Daily Activity",
        "domain": "openrouter_derived",
        "natural_keys": ["usage_date", "serving_provider", "model_permaslug"],
        "primary_date_column": "usage_date",
        "metric_column": "total_tokens",
        "required_columns": [
            "usage_date",
            "serving_provider",
            "serving_provider_name",
            "serving_provider_type",
            "model_origin_company",
            "model_permaslug",
            "total_tokens",
            "is_first_party_route",
            "is_complete_day",
            "include_in_default_kpis",
            "observation_status",
        ],
    },
    "openrouter_task_spend": {
        "label": "Task Spend Rankings",
        "domain": "rankings",
        "natural_keys": ["snapshot_date", "period", "window_days", "category_slug", "model_permaslug"],
        "primary_date_column": "snapshot_date",
        "metric_column": "model_share",
        "required_columns": [
            "snapshot_date",
            "period",
            "window_days",
            "category_slug",
            "macro_category",
            "task_share_of_total",
            "model_permaslug",
            "model_share",
            "rank",
        ],
    },
    "artificial_analysis_models_daily": {
        "label": "Artificial Analysis Models",
        "domain": "artificial_analysis",
        "natural_keys": ["as_of_date", "model_id"],
        "primary_date_column": "as_of_date",
        "metric_column": "intelligence_index",
        "required_columns": ["as_of_date", "model_id", "model_name", "creator_name", "release_date", "intelligence_index"],
    },
    "artificial_analysis_leading_models_by_lab_daily": {
        "label": "Artificial Analysis Leading Models",
        "domain": "artificial_analysis",
        "natural_keys": ["as_of_date", "creator_id"],
        "primary_date_column": "as_of_date",
        "metric_column": "intelligence_index",
        "required_columns": ["as_of_date", "creator_name", "model_id", "model_name", "intelligence_index"],
    },
    "artificial_analysis_capex_quarterly": {
        "label": "Artificial Analysis Capex",
        "domain": "artificial_analysis",
        "natural_keys": ["quarter_id"],
        "primary_date_column": "quarter_id",
        "metric_column": "microsoft",
        "required_columns": ["quarter_id", "quarter_label", "microsoft", "google", "meta", "amazon", "oracle", "apple"],
    },
    "ramp_vendor_adoption_monthly": {
        "label": "Ramp Vendor Adoption",
        "domain": "ramp",
        "natural_keys": ["vendor_slug", "spend_month"],
        "primary_date_column": "spend_month",
        "metric_column": "adoption_rate",
        "required_columns": ["vendor_slug", "spend_month", "adoption_rate", "adoption_rank"],
    },
    "ramp_category_vendors": {
        "label": "Ramp Category Vendors",
        "domain": "ramp",
        "natural_keys": ["category_slug", "vendor_slug"],
        "primary_date_column": "scraped_at",
        "metric_column": "adoption_rate",
        "required_columns": ["category_slug", "vendor_slug", "adoption_rate"],
    },
    "ramp_ai_adoption_overall": {
        "label": "Ramp AI Adoption (Overall)",
        "domain": "ramp",
        "natural_keys": ["date_month"],
        "primary_date_column": "date_month",
        "metric_column": "adoption_rate_pct",
        "required_columns": ["date_month", "adoption_rate_pct"],
    },
    "ramp_ai_adoption_by_size": {
        "label": "Ramp AI Adoption by Business Size",
        "domain": "ramp",
        "natural_keys": ["date_month", "business_size"],
        "primary_date_column": "date_month",
        "metric_column": "adoption_rate_pct",
        "required_columns": ["date_month", "business_size", "adoption_rate_pct"],
    },
    "ramp_ai_adoption_by_sector": {
        "label": "Ramp AI Adoption by Sector",
        "domain": "ramp",
        "natural_keys": ["date_month", "naics_sector"],
        "primary_date_column": "date_month",
        "metric_column": "adoption_rate_pct",
        "required_columns": ["date_month", "naics_sector", "adoption_rate_pct"],
    },
    "ramp_ai_adoption_by_state": {
        "label": "Ramp AI Adoption by State",
        "domain": "ramp",
        "natural_keys": ["date_month", "state_code"],
        "primary_date_column": "date_month",
        "metric_column": "adoption_rate_pct",
        "required_columns": ["date_month", "state_code", "adoption_rate_pct"],
    },
    "ramp_ai_adoption_by_vendor": {
        "label": "Ramp AI Adoption by Vendor",
        "domain": "ramp",
        "natural_keys": ["date_month", "vendor"],
        "primary_date_column": "date_month",
        "metric_column": "adoption_rate_pct",
        "required_columns": ["date_month", "vendor", "adoption_rate_pct"],
    },
    "ramp_ai_pepm_spend": {
        "label": "Ramp AI Spend per Employee",
        "domain": "ramp",
        "natural_keys": ["date_month"],
        "primary_date_column": "date_month",
        "metric_column": "median_pepm",
        "required_columns": ["date_month", "median_pepm"],
    },
    "ramp_ai_pepm_spend_by_dimension": {
        "label": "Ramp AI Spend per Employee by Dimension",
        "domain": "ramp",
        "natural_keys": ["date_month", "dimension_type", "dimension_value"],
        "primary_date_column": "date_month",
        "metric_column": "median_pepm",
        "required_columns": ["date_month", "dimension_type", "dimension_value", "median_pepm"],
    },
    "ramp_ai_spend_share_by_category": {
        "label": "Ramp AI Spend Share by Category",
        "domain": "ramp",
        "natural_keys": ["date_month", "dimension_type", "dimension_value", "spend_category_key"],
        "primary_date_column": "date_month",
        "metric_column": "spend_share",
        "required_columns": ["date_month", "spend_category_key", "spend_share"],
    },
    "ramp_ai_provider_model_share": {
        "label": "Ramp AI Provider Model Share",
        "domain": "ramp",
        "natural_keys": ["date_month", "dimension_type", "dimension_value", "ai_provider", "model_bucket_key"],
        "primary_date_column": "date_month",
        "metric_column": "model_share",
        "required_columns": ["date_month", "ai_provider", "model_share"],
    },
    "ramp_ai_spend_breakdown": {
        "label": "Ramp AI Spend Breakdown (history)",
        "domain": "ramp",
        "natural_keys": ["date_month", "spend_category"],
        "primary_date_column": "date_month",
        "metric_column": "spend_usd",
        "required_columns": ["date_month", "spend_category", "spend_usd"],
    },
    "ramp_ai_model_breakdown": {
        "label": "Ramp AI Model Breakdown (history)",
        "domain": "ramp",
        "natural_keys": ["date_month", "ai_provider", "model_bucket_key"],
        "primary_date_column": "date_month",
        "metric_column": "model_share",
        "required_columns": ["date_month", "ai_provider", "model_share"],
    },
    "ramp_ai_filter_spend_share": {
        "label": "Ramp AI Filter-mode Spend Share",
        "domain": "ramp",
        "natural_keys": ["date_month", "business_office_state", "fte_segment", "naics_sector", "company_financing_status", "pepm_spend_type"],
        "primary_date_column": "date_month",
        "metric_column": "spend_share",
        "required_columns": ["date_month", "pepm_spend_type", "spend_share"],
    },
    "ramp_ai_filter_model_share": {
        "label": "Ramp AI Filter-mode Model Share",
        "domain": "ramp",
        "natural_keys": ["date_month", "business_office_state", "fte_segment", "naics_sector", "company_financing_status", "ai_provider", "model_bucket_key"],
        "primary_date_column": "date_month",
        "metric_column": "model_share",
        "required_columns": ["date_month", "ai_provider", "model_share"],
    },
    "ramp_ai_filter_pepm": {
        "label": "Ramp AI Filter-mode Spend per Employee",
        "domain": "ramp",
        "natural_keys": ["date_month", "business_office_state", "fte_segment", "naics_sector", "company_financing_status"],
        "primary_date_column": "date_month",
        "metric_column": "median_pepm",
        "required_columns": ["date_month", "median_pepm"],
    },
    "ramp_ai_jobs_impact": {
        "label": "Ramp AI Jobs Impact",
        "domain": "ramp",
        "natural_keys": ["figure", "month_relative_to_adoption"],
        "primary_date_column": "scraped_at",
        "metric_column": "high_intensity_effect",
        "required_columns": ["figure", "month_relative_to_adoption", "high_intensity_effect"],
    },
    "ramp_category_adoption_monthly": {
        "label": "Ramp Category Adoption (monthly)",
        "domain": "ramp",
        "natural_keys": ["category_slug", "spend_month", "vendor_name"],
        "primary_date_column": "spend_month",
        "metric_column": "adoption_rate",
        "required_columns": ["category_slug", "spend_month", "vendor_name", "adoption_rate"],
    },
    "ramp_category_spend_share_quarterly": {
        "label": "Ramp Category Spend Share (quarterly)",
        "domain": "ramp",
        "natural_keys": ["category_slug", "quarter", "vendor_name"],
        "primary_date_column": "quarter",
        "metric_column": "spend_share",
        "required_columns": ["category_slug", "quarter", "vendor_name", "spend_share"],
    },
    "ramp_category_adoption_yoy_comparison": {
        "label": "Ramp Category Adoption YoY Comparison",
        "domain": "ramp",
        "natural_keys": ["category_slug", "vendor_name", "date_month"],
        "primary_date_column": "date_month",
        "metric_column": "adoption_rate",
        "required_columns": ["category_slug", "vendor_name", "date_month", "adoption_rate"],
    },
    "official_model_rankings_daily": {
        "label": "Official OpenRouter Model Rankings (daily)",
        "domain": "openrouter_official",
        "natural_keys": ["usage_date", "model_permaslug", "period", "modality", "context_bucket", "category", "language_type"],
        "primary_date_column": "usage_date",
        "metric_column": "total_tokens",
        "required_columns": ["usage_date", "model_permaslug", "total_tokens", "period", "is_other"],
    },
    "official_app_rankings": {
        "label": "Official OpenRouter App Rankings",
        "domain": "openrouter_official",
        "natural_keys": ["snapshot_date", "ranking_type", "app_id"],
        "primary_date_column": "snapshot_date",
        "metric_column": "total_tokens",
        "required_columns": ["snapshot_date", "ranking_type", "app_id", "rank", "total_tokens", "total_requests"],
    },
    "official_task_classifications": {
        "label": "Official OpenRouter Task Classifications",
        "domain": "openrouter_official",
        "natural_keys": ["snapshot_date", "window_days", "tag"],
        "primary_date_column": "snapshot_date",
        "metric_column": "usage_share",
        "required_columns": ["snapshot_date", "window_days", "tag", "usage_share", "token_share"],
    },
    "official_task_models": {
        "label": "Official OpenRouter Task Models",
        "domain": "openrouter_official",
        "natural_keys": ["snapshot_date", "window_days", "tag", "model_permaslug"],
        "primary_date_column": "snapshot_date",
        "metric_column": "tag_usage_share",
        "required_columns": ["snapshot_date", "window_days", "tag", "model_permaslug", "rank", "tag_usage_share"],
    },
    "official_task_macro_categories": {
        "label": "Official OpenRouter Task Macro Categories",
        "domain": "openrouter_official",
        "natural_keys": ["snapshot_date", "window_days", "macro_category"],
        "primary_date_column": "snapshot_date",
        "metric_column": "usage_share",
        "required_columns": ["snapshot_date", "window_days", "macro_category", "usage_share", "token_share"],
    },
    "official_providers": {
        "label": "Official OpenRouter Providers",
        "domain": "openrouter_official",
        "natural_keys": ["snapshot_date", "provider_slug"],
        "primary_date_column": "snapshot_date",
        "metric_column": None,
        "required_columns": ["snapshot_date", "provider_slug", "provider_name"],
    },
    "official_benchmarks": {
        "label": "Official OpenRouter Benchmarks",
        "domain": "openrouter_official",
        "natural_keys": ["snapshot_date", "benchmark_source", "model_permaslug", "display_name", "arena", "category", "variant_index"],
        "primary_date_column": "snapshot_date",
        "metric_column": "intelligence_index",
        "required_columns": ["snapshot_date", "benchmark_source", "model_permaslug", "display_name", "variant_index"],
    },
    "official_legacy_reconciliation": {
        "label": "OpenRouter Official / Legacy Reconciliation",
        "domain": "openrouter_official",
        "natural_keys": ["usage_date"],
        "primary_date_column": "usage_date",
        "metric_column": "official_total_tokens",
        "required_columns": ["usage_date", "official_total_tokens", "official_named_tokens", "official_other_tokens"],
    },
    "official_source_health": {
        "label": "OpenRouter Official Source Health",
        "domain": "openrouter_official",
        "natural_keys": ["source_run_id", "dataset_id"],
        "primary_date_column": "scraped_at",
        "metric_column": "row_count",
        "required_columns": ["dataset_id", "source_run_id", "scraped_at", "row_count", "status"],
    },
    "market_pulse_daily": {
        "label": "Market Pulse (daily)",
        "domain": "overview",
        "natural_keys": ["pulse_date"],
        "primary_date_column": "pulse_date",
        "metric_column": "openrouter_total_tokens",
        "required_columns": ["pulse_date", "openrouter_total_tokens", "openrouter_top_model"],
    },
    "overview_signal_series": {
        "label": "Overview Signal Series",
        "domain": "overview",
        "natural_keys": ["signal_id", "signal_date"],
        "primary_date_column": "signal_date",
        "metric_column": "value",
        "required_columns": ["signal_id", "signal_date", "value", "unit", "source_dataset"],
    },
    "provider_incidents": {
        "label": "Provider-reported Incidents",
        "domain": "provider_incidents",
        "natural_keys": ["provider_id", "source_incident_id"],
        "primary_date_column": "published_at",
        "metric_column": "duration_minutes",
        "required_columns": ["provider_id", "source_incident_id", "title", "normalized_status", "started_at"],
    },
    "provider_incident_updates": {
        "label": "Provider Incident Updates",
        "domain": "provider_incidents",
        "natural_keys": ["provider_id", "source_incident_id", "source_update_id"],
        "primary_date_column": "update_at",
        "metric_column": None,
        "required_columns": ["provider_id", "source_incident_id", "source_update_id", "update_at"],
    },
    "provider_incident_components": {
        "label": "Provider Incident Components",
        "domain": "provider_incidents",
        "natural_keys": ["provider_id", "source_incident_id", "component_id"],
        "primary_date_column": "scraped_at",
        "metric_column": None,
        "required_columns": ["provider_id", "source_incident_id", "component_id", "component_name"],
    },
    "provider_incident_source_health": {
        "label": "Provider Incident Source Health",
        "domain": "provider_incidents",
        "natural_keys": ["provider_id"],
        "primary_date_column": "scraped_at",
        "metric_column": "incident_rows",
        "required_columns": ["provider_id", "source_url", "status", "scraped_at"],
    },
    "indeed_ai_posting_share_daily": {
        "label": "Indeed AI Posting Share",
        "domain": "ai_hiring",
        "natural_keys": ["date", "jobcountry"],
        "primary_date_column": "date",
        "metric_column": "ai_share_pct",
        "required_columns": ["date", "jobcountry", "ai_share_pct", "license"],
    },
    "hiring_companies": {
        "label": "AI Hiring Company Registry",
        "domain": "ai_hiring",
        "natural_keys": ["company_id"],
        "primary_date_column": "coverage_start_date",
        "metric_column": None,
        "required_columns": ["company_id", "company_name", "source_id", "coverage_start_date"],
    },
    "hiring_jobs": {
        "label": "AI Company Job Lifecycle",
        "domain": "ai_hiring",
        "natural_keys": ["company_id", "source_job_id"],
        "primary_date_column": "first_seen_at",
        "metric_column": None,
        "required_columns": ["company_id", "source_job_id", "title", "job_url", "status", "role_family"],
    },
    "hiring_job_events": {
        "label": "AI Hiring Job Events",
        "domain": "ai_hiring",
        "natural_keys": ["company_id", "source_job_id", "event_at", "event_type"],
        "primary_date_column": "event_at",
        "metric_column": None,
        "required_columns": ["company_id", "source_job_id", "event_at", "event_type"],
    },
    "hiring_demand_daily": {
        "label": "AI Hiring Demand Daily",
        "domain": "ai_hiring",
        "natural_keys": ["snapshot_date", "company_id", "role_family"],
        "primary_date_column": "snapshot_date",
        "metric_column": "active_requisitions",
        "required_columns": ["snapshot_date", "company_id", "role_family", "active_postings", "active_requisitions"],
    },
    "hiring_source_health": {
        "label": "AI Hiring Source Health",
        "domain": "ai_hiring",
        "natural_keys": ["source_id"],
        "primary_date_column": "scraped_at",
        "metric_column": "row_count",
        "required_columns": ["source_id", "source_kind", "status", "row_count"],
    },
    "opencode_market_share": {
        "label": "OpenCode Market Share",
        "domain": "opencode",
        "requires_core_provenance": False,
        "natural_keys": ["timeframe", "usage_date", "date_occurrence", "author"],
        "primary_date_column": "usage_date",
        "metric_column": "tokens_trillion",
        "required_columns": [
            "timeframe", "usage_date", "date_occurrence", "author",
            "share_pct", "tokens_trillion", "total_tokens_trillion", "scraped_at",
        ],
    },
    "opencode_usage_daily": {
        "label": "OpenCode Usage Daily",
        "domain": "opencode",
        "requires_core_provenance": False,
        "natural_keys": ["user_tier", "timeframe", "usage_date", "date_occurrence", "model_slug"],
        "primary_date_column": "usage_date",
        "metric_column": "token_value",
        "required_columns": [
            "user_tier", "timeframe", "usage_date", "date_occurrence", "model_slug", "token_value", "scraped_at",
        ],
    },
    "opencode_users_daily": {
        "label": "OpenCode Active Users Daily",
        "domain": "opencode",
        "requires_core_provenance": False,
        "natural_keys": ["user_tier", "timeframe", "usage_date", "date_occurrence", "model_slug"],
        "primary_date_column": "usage_date",
        "metric_column": "active_users",
        "required_columns": [
            "user_tier", "timeframe", "usage_date", "date_occurrence", "model_slug", "active_users", "scraped_at",
        ],
    },
    "opencode_leaderboard": {
        "label": "OpenCode Leaderboard",
        "domain": "opencode",
        "requires_core_provenance": False,
        "natural_keys": ["snapshot_date", "user_tier", "timeframe", "model_slug"],
        "primary_date_column": "snapshot_date",
        "metric_column": "tokens",
        "required_columns": [
            "snapshot_date", "user_tier", "timeframe", "rank", "model_slug",
            "provider", "author", "tokens", "rank_change", "scraped_at",
        ],
    },
    "opencode_country_usage": {
        "label": "OpenCode Country Usage",
        "domain": "opencode",
        "requires_core_provenance": False,
        "natural_keys": ["snapshot_date", "timeframe", "country_code"],
        "primary_date_column": "snapshot_date",
        "metric_column": "tokens_trillion",
        "required_columns": [
            "snapshot_date", "timeframe", "country_code", "continent", "tokens_trillion", "share_pct", "rank", "scraped_at",
        ],
    },
    "opencode_model_catalog": {
        "label": "OpenCode Model Catalog",
        "domain": "opencode",
        "requires_core_provenance": False,
        "natural_keys": ["snapshot_date", "slug"],
        "primary_date_column": "snapshot_date",
        "metric_column": "input_cost_per_m",
        "required_columns": [
            "snapshot_date", "model_id", "lab", "slug", "name", "description", "family", "release_date",
            "last_updated", "context_limit", "output_limit", "input_modalities", "output_modalities",
            "open_weights", "reasoning", "tool_call", "attachment", "temperature",
            "input_cost_per_m", "output_cost_per_m", "cache_read_cost_per_m", "cache_write_cost_per_m", "scraped_at",
        ],
    },
    "opencode_benchmarks": {
        "label": "OpenCode Benchmarks",
        "domain": "opencode",
        "requires_core_provenance": False,
        "natural_keys": ["snapshot_date", "model_slug", "benchmark_name", "metric", "harness", "variant", "dataset", "version"],
        "primary_date_column": "snapshot_date",
        "metric_column": "score",
        "required_columns": [
            "snapshot_date", "model_id", "model_slug", "benchmark_name", "score", "metric",
            "harness", "variant", "dataset", "version", "source_url", "scraped_at",
        ],
    },
    "opencode_model_deepdives": {
        "label": "OpenCode Model Deepdives",
        "domain": "opencode",
        "requires_core_provenance": False,
        "natural_keys": ["snapshot_date", "model_slug"],
        "primary_date_column": "snapshot_date",
        "metric_column": "tokens_total",
        "required_columns": [
            "snapshot_date", "model_slug", "provider", "author", "rank", "previous_rank", "total_models",
            "token_share_pct", "token_change", "sessions", "unique_users", "tokens_total", "cost_total_usd",
            "tokens_per_session", "cost_per_session_usd", "cost_per_million_usd", "cache_ratio_pct",
            "input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens", "scraped_at",
        ],
    },
    "replicate_model_catalog": {
        "label": "Replicate Model Catalog",
        "domain": "replicate",
        "requires_core_provenance": False,
        "natural_keys": ["snapshot_date", "slug"],
        "primary_date_column": "snapshot_date",
        "metric_column": "run_count",
        "required_columns": [
            "snapshot_date", "slug", "owner", "name", "collection", "run_count", "is_official",
            "latest_version_created_at", "hardware", "price", "description", "url", "scraped_at",
        ],
    },
    "replicate_collections_summary": {
        "label": "Replicate Collections Summary",
        "domain": "replicate",
        "requires_core_provenance": False,
        "natural_keys": ["snapshot_date", "collection_slug"],
        "primary_date_column": "snapshot_date",
        "metric_column": "total_models",
        "required_columns": ["snapshot_date", "collection_slug", "total_models", "url", "scraped_at"],
    },
    "openrouter_usage_economics_daily": {
        "label": "OpenRouter Usage Economics Daily",
        "domain": "openrouter_derived",
        "natural_keys": ["usage_date", "metric_id", "cohort_id", "rolling_window_days"],
        "primary_date_column": "usage_date",
        "metric_column": "value",
        "required_columns": [
            "dataset_id",
            "source_url",
            "source_run_id",
            "scraped_at",
            "usage_date",
            "metric_id",
            "cohort_id",
            "value",
            "numerator",
            "denominator",
            "rolling_window_days",
            "benchmark_snapshot_date",
            "pricing_snapshot_date",
            "expected_family_count",
            "priced_family_count",
            "observed_family_count",
            "observed_model_count",
            "included_tokens",
            "excluded_free_tokens",
            "excluded_unpriced_tokens",
            "excluded_zero_request_rows",
            "pricing_join_status",
            "methodology_version",
        ],
    },
    "daily_provider_economics": {
        "label": "Daily Model-Origin Economics",
        "domain": "openrouter_derived",
        "requires_core_provenance": False,
        "natural_keys": ["usage_date", "provider_slug", "model_permaslug"],
        "primary_date_column": "usage_date",
        "metric_column": "estimated_revenue",
        "required_columns": [
            "usage_date",
            "provider_slug",
            "provider_name",
            "model_permaslug",
            "total_tokens",
            "estimated_revenue",
            "pricing_join_status",
            "has_pricing",
            "has_split_tokens",
            "revenue_method",
        ],
    },
    "daily_provider_revenue_estimates": {
        "label": "Daily Provider Revenue Estimates",
        "domain": "openrouter_derived",
        # Compact mart derived from already-provenanced provider activity;
        # stores no per-row source metadata (see daily_provider_economics).
        "requires_core_provenance": False,
        # provider_slug alone doesn't disambiguate rows: it's derived from
        # model_permaslug's prefix, which is null for the synthetic "Others"
        # bucket every provider page emits. entity_id (the source page) is
        # what actually makes the row unique, matching provider_daily_activity's
        # own natural key.
        "natural_keys": ["usage_date", "entity_id", "model_permaslug"],
        "primary_date_column": "usage_date",
        "metric_column": "estimated_revenue",
        "required_columns": [
            "usage_date",
            "entity_id",
            "provider_slug",
            "model_permaslug",
            "total_tokens",
            "estimated_revenue",
            "pricing_join_status",
        ],
    },
    "daily_cloud_infra_economics": {
        "label": "Daily Serving-Provider Economics",
        "domain": "openrouter_derived",
        "requires_core_provenance": False,
        "natural_keys": ["usage_date", "serving_provider", "model_permaslug"],
        "primary_date_column": "usage_date",
        "metric_column": "estimated_revenue",
        "required_columns": [
            "usage_date",
            "serving_provider",
            "serving_provider_name",
            "serving_provider_type",
            "model_origin_company",
            "model_permaslug",
            "total_tokens",
            "estimated_revenue",
            "pricing_join_status",
            "pricing_coverage_status",
            "has_pricing",
            "priced_tokens",
            "unpriced_tokens",
            "is_first_party_route",
            "is_complete_day",
            "include_in_default_kpis",
            "observation_status",
        ],
    },
    "openrouter_workload_intensity_models": {
        "label": "OpenRouter Workload Intensity Models",
        "domain": "openrouter_derived",
        "natural_keys": ["window_end_date", "model_id"],
        "primary_date_column": "window_end_date",
        "metric_column": "intensity_ratio",
        # The compact workload mart is derived from already-provenanced daily
        # activity and intentionally stores no per-row source metadata.
        "requires_core_provenance": False,
        "required_columns": [
            "window_start_date",
            "window_end_date",
            "model_id",
            "company_id",
            "total_tokens",
            "prompt_tokens",
            "completion_tokens",
            "request_count",
            "token_share",
            "request_share",
            "tokens_per_request",
            "intensity_ratio",
            "model_match_status",
            "methodology_version",
        ],
    },
}


DOMAIN_ORDER = {
    "overview": [
        "market_pulse_daily",
        "overview_signal_series",
    ],
    "provider_incidents": [
        "provider_incidents",
        "provider_incident_updates",
        "provider_incident_components",
        "provider_incident_source_health",
    ],
    "ai_hiring": [
        "indeed_ai_posting_share_daily",
        "hiring_companies",
        "hiring_jobs",
        "hiring_job_events",
        "hiring_demand_daily",
        "hiring_source_health",
    ],
    "opencode": [
        "opencode_market_share",
        "opencode_usage_daily",
        "opencode_users_daily",
        "opencode_leaderboard",
        "opencode_country_usage",
        "opencode_model_catalog",
        "opencode_benchmarks",
        "opencode_model_deepdives",
    ],
    "replicate": [
        "replicate_model_catalog",
        "replicate_collections_summary",
    ],
    "rankings": [
        "top_models",
        "market_share",
        "provider_weekly_requests",
        "context_length_requests",
        "modality_rankings",
        "categories_programming",
        "openrouter_model_activity",
        "provider_daily_activity",
        "openrouter_task_spend",
    ],
    # Focused OpenRouter page domains keep the large Intelligence surface and
    # workload composition views from loading one another's datasets.
    "openrouter_intelligence": [
        "top_models",
        "market_share",
        "provider_weekly_requests",
        "categories_programming",
        "openrouter_model_activity",
        "provider_daily_activity",
        "openrouter_task_spend",
    ],
    "openrouter_derived": [
        "openrouter_usage_economics_daily",
        "daily_provider_economics",
        "daily_provider_revenue_estimates",
        "cloud_infra_daily_activity",
        "daily_cloud_infra_economics",
        "openrouter_workload_intensity_models",
    ],
    "openrouter_workloads": [
        "context_length_requests",
        "modality_rankings",
    ],
    "apps": [
        "app_metadata_snapshots",
        "app_usage_daily",
        "app_top_models_daily_snapshot",
        "apps_global_ranking_snapshots",
        "apps_trending_snapshots",
    ],
    # The dedicated Models tab needs catalog, activity, weekly ranking context,
    # compact economics, and app-usage detail. Keeping these focused domains
    # separate avoids loading every rankings and Apps panel merely to render
    # the explorer.
    "openrouter_model_explorer": [
        "top_models",
        "market_share",
        "provider_weekly_requests",
        "openrouter_model_activity",
        "provider_daily_activity",
        "app_metadata_snapshots",
        "app_usage_daily",
    ],
    "openrouter_catalog": [
        "raw_openrouter_models",
    ],
    "provider_adoption": [
        "pypi_downloads_daily",
        "npm_downloads_daily",
        "provider_momentum_daily",
        "huggingface_models_daily",
        "github_provider_adoption_daily",
    ],
    "semiconductor_memory": [
        "fred_semiconductor_ppi_monthly",
        "semiconductor_memory_regime_monthly",
        "adata_marketwatch_images",
    ],
    "semiconductor_proxies": [
        "semiconductor_official_monthly",
        "semiconductor_backup_check_monthly",
        "semiconductor_source_catalog",
    ],
    "taiwan_semiconductor_revenue": [
        "tw_monthly_revenue",
    ],
    "ai_frontier": [
        "llm_benchmarks",
    ],
    "compute_availability": [
        "raw_openrouter_models",
    ],
    "openrouter_official": [
        "official_model_rankings_daily",
        "official_app_rankings",
        "official_task_classifications",
        "official_task_models",
        "official_task_macro_categories",
        "official_providers",
        "official_benchmarks",
        "official_legacy_reconciliation",
        "official_source_health",
    ],
    # Only this compact subset is loaded by OpenRouter Intelligence. The larger
    # benchmarks/tasks/apps history remains queryable without inflating the tab.
    # official_legacy_reconciliation and official_source_health are part of the
    # full "openrouter_official" domain below, not read by anything on the
    # Intelligence tab - keep this list to the one dataset it actually renders
    # (see _latest_provider_market_coverage) so the tab isn't fetching and
    # parsing data nothing displays.
    "openrouter_official_market": [
        "official_model_rankings_daily",
    ],
    "vercel_ai": [
        "vercel_model_leaderboard",
        "vercel_lab_leaderboard",
        "vercel_models",
    ],
    "artificial_analysis": [
        "artificial_analysis_models_daily",
        "artificial_analysis_leading_models_by_lab_daily",
        "artificial_analysis_capex_quarterly",
    ],
    "ramp": [
        "ramp_vendor_adoption_monthly",
        "ramp_category_vendors",
        "ramp_ai_adoption_overall",
        "ramp_ai_adoption_by_size",
        "ramp_ai_adoption_by_sector",
        "ramp_ai_adoption_by_state",
        "ramp_ai_adoption_by_vendor",
        "ramp_ai_pepm_spend",
        "ramp_ai_pepm_spend_by_dimension",
        "ramp_ai_spend_share_by_category",
        "ramp_ai_provider_model_share",
        "ramp_ai_spend_breakdown",
        "ramp_ai_model_breakdown",
        "ramp_ai_filter_spend_share",
        "ramp_ai_filter_model_share",
        "ramp_ai_filter_pepm",
        "ramp_ai_jobs_impact",
        "ramp_category_adoption_monthly",
        "ramp_category_spend_share_quarterly",
        "ramp_category_adoption_yoy_comparison",
    ],
}

CORE_COLUMNS = [
    "dataset_id",
    "source_url",
    "source_run_id",
    "scraped_at",
]

RANKINGS_COLUMNS = [
    "week_label",
    "week_start_date",
    "entity_id",
    "entity_name",
    "parent_entity_id",
    "parent_entity_name",
    "metric_name",
    "metric_unit",
    "metric_value",
    "rank",
    "category_slug",
    "context_length_bucket",
    "modality",
]

APPS_COLUMNS = [
    "app_id",
    "app_name",
    "origin_url",
    "main_url",
    "description",
    "categories",
    "group_by_origin",
    "is_private",
    "is_hidden",
    "created_at",
    "scrape_date",
    "usage_date",
    "model_permaslug",
    "total_tokens",
    "snapshot_date",
    "observed_at",
    "period",
    "tokens",
    "growth_percent",
]

GITHUB_COLUMNS = [
    "author",
    "name",
    "link",
    "stars_today",
    "total_stars",
]

PROVIDER_ADOPTION_COLUMNS = [
    "provider",
    "provider_display_name",
    "package_name",
    "package_type",
    "package_category",
    "with_mirrors",
    "download_date",
    "downloads",
    "model_id",
    "hf_downloads_30d",
    "hf_downloads_all_time",
    "hf_downloads_daily_est",
    "hf_likes",
    "hf_last_modified",
    "repo_full_name",
    "repo_owner",
    "repo_name",
    "repo_html_url",
    "repo_created_date",
    "repo_created_at",
    "repo_pushed_at",
    "repo_default_branch",
    "language_bucket",
    "signal_date",
    "signal_type",
    "matched_file_path",
    "matched_pattern",
    "is_fork",
    "is_archived",
    "stargazers_count",
    "has_manifest_dependency",
    "has_code_import",
    "has_env_var",
    "has_model_name",
    "matched_signal_count",
    "pypi_7d_avg",
    "pypi_28d_avg",
    "pypi_share_28d",
    "pypi_growth_28d",
    "github_new_repo_count",
    "github_signal_repo_count",
    "github_manifest_repo_count",
    "github_repo_share",
    "github_import_repo_count",
    "github_env_repo_count",
    "github_model_repo_count",
    "momentum_score",
]
SEMICONDUCTOR_COLUMNS = [
    "month",
    "fetch_time",
    "title",
    "raw_text",
    "raw_html_path",
    "page_url",
    "image_url",
    "local_path",
    "image_type",
    "vision_extracted",
    "vision_result_json",
    "extracted_at",
    "narrative_nand_supply",
    "narrative_nand_price",
    "narrative_dram_supply",
    "narrative_dram_price",
    "mentions_hbm",
    "mentions_csp",
    "mentions_server",
    "mentions_ddr4",
    "mentions_reallocate_capacity",
    "mentions_shortage",
    "mentions_oversupply",
    "nand_regime_label",
    "dram_regime_label",
    "date",
    "series_id",
    "series_name",
    "value",
    "fred_ppi_value",
    "fred_ppi_mom_pct",
    "fred_ppi_3m_trend",
    "component_coverage",
    "missing_components",
    "ppi_component_pcu33443344_rebased",
    "ppi_component_pcu33423342_rebased",
    "ppi_component_pcu335313335313_rebased",
    "ppi_component_pcu334111334111_rebased",
    "ppi_component_pcu3341123341121_rebased",
    "adata_freshness_days",
    "fred_release_lag_days",
    "data_completeness",
    "source_region",
    "country_name",
    "metric_type",
    "flow_code",
    "partner_scope",
    "period",
    "release_date",
    "expected_release_window_days",
    "lag_days",
    "category_id",
    "category_label",
    "classification_system",
    "classification_code",
    "unit",
    "currency",
    "comparison_gap_pct",
    "source_name",
    "source_tier",
    "coverage_start",
    "latest_period",
    "cadence",
    "default_unit",
    "default_currency",
    "notes",
    "company_code",
    "company_name",
    "market",
    "industry",
    "filing_date",
    "revenue_month",
    "monthly_revenue_ntd",
    "mom_pct",
    "yoy_pct",
    "ytd_revenue_ntd",
    "ytd_yoy_pct",
    "parser_version",
    "raw_company_name_text",
    "raw_monthly_revenue_text",
    "raw_mom_pct_text",
    "raw_yoy_pct_text",
    "raw_ytd_revenue_text",
    "raw_ytd_yoy_pct_text",
]

BENCHMARK_COLUMNS = [
    "organization",
    "release_date",
    "gpqa",
    "swe_bench",
    "context_window",
]

ACTIVITY_COLUMNS = [
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "request_count",
    "window_days",
    "macro_category",
    "task_share_of_total",
    "model_share",
    "delta_pp",
]

OPENROUTER_MODEL_COLUMNS = [
    "snapshot_ts",
    "model_id",
    "canonical_slug",
    "model_name",
    "created_at",
    "context_length",
    "architecture",
    "description",
    "hugging_face_id",
    "architecture_modality",
    "input_modalities_json",
    "output_modalities_json",
    "tokenizer",
    "instruct_type",
    "supported_parameters_json",
    "default_parameters_json",
    "per_request_limits_json",
    "pricing_prompt",
    "pricing_completion",
    "pricing_request",
    "pricing_image",
    "pricing_web_search",
    "pricing_internal_reasoning",
    "pricing_input_cache_read",
    "pricing_input_cache_write",
    "top_provider_id",
    "top_provider_context_length",
    "top_provider_max_completion_tokens",
    "top_provider_is_moderated",
    "provider_prefix",
    "expiration_date",
    "knowledge_cutoff",
    "benchmarks_json",
    "links_json",
    "reasoning_json",
    "supported_voices_json",
]

LEGACY_COMPUTE_AVAILABILITY_COLUMNS = [
    "instance_type_name",
    "gpu_type",
    "gpu_count",
    "gpu_description",
    "instance_vcpus",
    "instance_memory_gib",
    "region",
    "availability_zone",
    "instance_type",
    "product_description",
    "spot_price",
    "price_timestamp",
]

COMPUTE_AVAILABILITY_COLUMNS = [
    *OPENROUTER_MODEL_COLUMNS,
    *LEGACY_COMPUTE_AVAILABILITY_COLUMNS,
]

ARTIFICIAL_ANALYSIS_COLUMNS = [
    "as_of_date",
    "model_slug",
    "model_name",
    "creator_id",
    "creator_name",
    "creator_slug",
    "creator_country",
    "release_quarter",
    "intelligence_index",
    "coding_index",
    "math_index",
    "scicode",
    "price_1m_blended_3_to_1",
    "price_1m_input_tokens",
    "price_1m_output_tokens",
    "median_output_tokens_per_second",
    "median_time_to_first_token_seconds",
    "context_window_tokens",
    "total_parameters_billions",
    "active_parameters_billions",
    "training_tokens_trillions",
    "open_source_categorization",
    "license_name",
    "is_open_weights",
    "quarter_id",
    "quarter_label",
    "microsoft",
    "google",
    "meta",
    "amazon",
    "oracle",
    "apple",
    "page_url",
    "bundle_url",
]

EXPECTED_COLUMNS = list(dict.fromkeys(
    CORE_COLUMNS + RANKINGS_COLUMNS + APPS_COLUMNS + GITHUB_COLUMNS +
    PROVIDER_ADOPTION_COLUMNS + SEMICONDUCTOR_COLUMNS + BENCHMARK_COLUMNS +
    ACTIVITY_COLUMNS + COMPUTE_AVAILABILITY_COLUMNS + ARTIFICIAL_ANALYSIS_COLUMNS
))

# The OpenRouter storage layer intentionally keeps a stable, unioned schema so
# old and new snapshots remain append-compatible. The dashboard should not
# carry that storage schema (or the still larger EXPECTED_COLUMNS union) into
# memory. These projections are the per-dataset analytical contracts consumed
# by the current Streamlit views.
OPENROUTER_LOAD_COLUMNS: dict[str, list[str]] = {
    "top_models": [*CORE_COLUMNS, *RANKINGS_COLUMNS],
    "market_share": [*CORE_COLUMNS, *RANKINGS_COLUMNS],
    "provider_weekly_requests": [*CORE_COLUMNS, *RANKINGS_COLUMNS],
    "context_length_requests": [*CORE_COLUMNS, *RANKINGS_COLUMNS],
    "modality_rankings": [*CORE_COLUMNS, *RANKINGS_COLUMNS],
    "categories_programming": [*CORE_COLUMNS, *RANKINGS_COLUMNS],
    "openrouter_model_activity": [
        *CORE_COLUMNS,
        "usage_date",
        "model_permaslug",
        "entity_id",
        "entity_name",
        "category_slug",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "request_count",
    ],
    "provider_daily_activity": [
        *CORE_COLUMNS,
        "usage_date",
        "model_permaslug",
        "entity_id",
        "entity_name",
        "category_slug",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "request_count",
    ],
    "cloud_infra_daily_activity": [
        *CORE_COLUMNS,
        "usage_date",
        "model_permaslug",
        "entity_id",
        "entity_name",
        "provider_slug",
        "provider_name",
        "serving_provider",
        "serving_provider_name",
        "serving_provider_type",
        "model_origin_company",
        "total_tokens",
        "is_first_party_route",
        "is_complete_day",
        "include_in_default_kpis",
        "observation_status",
        "headquarters",
        "datacenters",
    ],
    "openrouter_task_spend": [
        *CORE_COLUMNS,
        "snapshot_date",
        "period",
        "window_days",
        "category_slug",
        "macro_category",
        "task_share_of_total",
        "model_permaslug",
        "model_share",
        "rank",
    ],
    "app_metadata_snapshots": [
        *CORE_COLUMNS,
        "app_id",
        "app_name",
        "origin_url",
        "main_url",
        "description",
        "categories",
        "group_by_origin",
        "is_private",
        "is_hidden",
        "created_at",
        "scrape_date",
    ],
    "app_usage_daily": [
        *CORE_COLUMNS,
        "app_id",
        "app_name",
        "usage_date",
        "model_permaslug",
        "total_tokens",
    ],
    "app_top_models_daily_snapshot": [
        *CORE_COLUMNS,
        "app_id",
        "app_name",
        "snapshot_date",
        "model_permaslug",
        "total_tokens",
        "rank",
        "observed_at",
    ],
    "apps_global_ranking_snapshots": [
        *CORE_COLUMNS,
        "snapshot_date",
        "period",
        "rank",
        "app_id",
        "app_name",
        "categories",
        "tokens",
    ],
    "apps_trending_snapshots": [
        *CORE_COLUMNS,
        "snapshot_date",
        "rank",
        "app_id",
        "app_name",
        "categories",
        "tokens",
        "growth_percent",
    ],
    "raw_openrouter_models": [*CORE_COLUMNS, *OPENROUTER_MODEL_COLUMNS],
    # These marts are the dashboard contract for usage economics. Keep their
    # compact storage schemas exact: the dashboard must not load raw activity,
    # pricing, or benchmark tables to reconstruct these views at runtime.
    "openrouter_usage_economics_daily": [
        "dataset_id",
        "source_url",
        "source_run_id",
        "scraped_at",
        "usage_date",
        "metric_id",
        "cohort_id",
        "value",
        "numerator",
        "denominator",
        "rolling_window_days",
        "benchmark_snapshot_date",
        "pricing_snapshot_date",
        "expected_family_count",
        "priced_family_count",
        "observed_family_count",
        "observed_model_count",
        "included_tokens",
        "excluded_free_tokens",
        "excluded_unpriced_tokens",
        "excluded_zero_request_rows",
        "pricing_join_status",
        "methodology_version",
    ],
    "daily_provider_economics": [
        "usage_date",
        "provider_slug",
        "provider_name",
        "model_permaslug",
        "total_tokens",
        "estimated_revenue",
        "pricing_join_status",
        "has_pricing",
        "has_split_tokens",
        "revenue_method",
    ],
    "daily_provider_revenue_estimates": [
        "usage_date",
        "entity_id",
        "provider_slug",
        "model_permaslug",
        "total_tokens",
        "estimated_revenue",
        "pricing_join_status",
    ],
    "daily_cloud_infra_economics": [
        "usage_date",
        "serving_provider",
        "serving_provider_name",
        "serving_provider_type",
        "provider_slug",
        "provider_name",
        "model_origin_company",
        "model_permaslug",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "estimated_revenue",
        "pricing_snapshot_ts",
        "pricing_prompt",
        "pricing_completion",
        "pricing_join_status",
        "pricing_coverage_status",
        "revenue_method",
        "has_pricing",
        "has_split_tokens",
        "split_source",
        "priced_tokens",
        "unpriced_tokens",
        "is_first_party_route",
        "is_complete_day",
        "include_in_default_kpis",
        "observation_status",
        "headquarters",
        "datacenters",
    ],
    "openrouter_workload_intensity_models": [
        "window_start_date",
        "window_end_date",
        "model_id",
        "company_id",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "request_count",
        "token_share",
        "request_share",
        "tokens_per_request",
        "intensity_ratio",
        "model_match_status",
        "methodology_version",
    ],
}

PROVIDER_ADOPTION_LOAD_COLUMNS: dict[str, list[str]] = {
    "pypi_downloads_daily": [
        *CORE_COLUMNS,
        "provider",
        "provider_display_name",
        "package_name",
        "package_category",
        "with_mirrors",
        "download_date",
        "downloads",
    ],
    "npm_downloads_daily": [
        *CORE_COLUMNS,
        "provider",
        "provider_display_name",
        "package_name",
        "package_category",
        "download_date",
        "downloads",
    ],
    "provider_momentum_daily": [
        *CORE_COLUMNS,
        "provider",
        "provider_display_name",
        "signal_date",
        "momentum_score",
        "pypi_share_28d",
        "github_repo_share",
    ],
    "huggingface_models_daily": [
        *CORE_COLUMNS,
        "provider",
        "provider_display_name",
        "author",
        "model_id",
        "download_date",
        "hf_downloads_30d",
        "hf_downloads_all_time",
        "hf_downloads_daily_est",
        "hf_likes",
        "hf_last_modified",
    ],
    "github_provider_adoption_daily": [
        *CORE_COLUMNS,
        "provider",
        "provider_display_name",
        "signal_date",
        "github_new_repo_count",
        "github_signal_repo_count",
        "github_manifest_repo_count",
        "github_import_repo_count",
        "github_env_repo_count",
        "github_model_repo_count",
    ],
}

# Vercel datasets carry columns that are not in EXPECTED_COLUMNS, so — like
# provider_adoption — they need an explicit load_columns override or the generic
# reindex(columns=EXPECTED_COLUMNS) in load_dataset would drop them.
VERCEL_AI_LOAD_COLUMNS: dict[str, list[str]] = {
    "vercel_model_leaderboard": [
        *CORE_COLUMNS,
        "date",
        "group",
        "name",
        "metric",
        "modality",
        "share_percent",
    ],
    "vercel_lab_leaderboard": [
        *CORE_COLUMNS,
        "date",
        "group",
        "name",
        "metric",
        "modality",
        "share_percent",
    ],
    "vercel_models": [
        *CORE_COLUMNS,
        "model_id",
        "name",
        "owned_by",
        "description",
        "context_window",
        "max_tokens",
        "type",
        "pricing_input",
        "pricing_output",
        "pricing_cache_read",
        "pricing_cache_write",
        "tags",
        "raw_pricing_json",
    ],
}

# Ramp datasets carry columns not in EXPECTED_COLUMNS, so — like vercel_ai and
# provider_adoption — they need an explicit load_columns override, else the
# generic reindex(columns=EXPECTED_COLUMNS) in load_dataset would drop them.
RAMP_LOAD_COLUMNS: dict[str, list[str]] = {
    "ramp_vendor_adoption_monthly": [
        *CORE_COLUMNS,
        "vendor_slug",
        "vendor_name",
        "vendor_domain",
        "spend_month",
        "adoption_rate",
        "adoption_rate_yoy",
        "adoption_rank",
        "adoption_rank_mom",
        "adoption_rate_ent",
        "adoption_rate_mm",
        "adoption_rate_smb",
        "adoption_rate_growth_delta_mom",
        "adoption_rate_growth_rank_mom",
        "competitor_switch_rate",
        "new_adopter_share",
        "dominant_fte_segment",
        "dominant_fte_segment_pct",
    ],
    "ramp_category_vendors": [
        *CORE_COLUMNS,
        "category_slug",
        "category_name",
        "vendor_slug",
        "vendor_name",
        "vendor_domain",
        "adoption_rate",
        "adoption_rate_yoy",
    ],
    "ramp_ai_adoption_overall": [*CORE_COLUMNS, "date_month", "adoption_rate_pct", "mom_change_pp", "yoy_change_pp"],
    "ramp_ai_adoption_by_size": [*CORE_COLUMNS, "date_month", "business_size", "adoption_rate_pct", "mom_change_pp"],
    "ramp_ai_adoption_by_sector": [*CORE_COLUMNS, "date_month", "naics_sector", "adoption_rate_pct", "mom_change_pp"],
    "ramp_ai_adoption_by_state": [*CORE_COLUMNS, "date_month", "state_code", "adoption_rate_pct", "n_firms", "ai_firms"],
    "ramp_ai_adoption_by_vendor": [*CORE_COLUMNS, "date_month", "vendor", "adoption_rate_pct", "mom_change_pp"],
    "ramp_ai_pepm_spend": [
        *CORE_COLUMNS, "date_month", "median_pepm", "p90_pepm", "p99_pepm",
        "p99_winsorized_weighted_pepm", "raw_weighted_pepm", "top_10_percent_median_pepm",
        "top_1_percent_median_pepm", "business_count", "spend_usd", "total_fte_denominator", "is_publishable",
    ],
    "ramp_ai_spend_share_by_category": [
        *CORE_COLUMNS, "date_month", "dimension_type", "dimension_value", "dimension_label",
        "display_order", "spend_category_key", "spend_category", "spend_category_display_order", "spend_share",
    ],
    "ramp_ai_provider_model_share": [
        *CORE_COLUMNS, "date_month", "dimension_type", "dimension_value", "dimension_label",
        "display_order", "ai_provider", "provider_display_order", "model_bucket_key",
        "model_label", "model_display_order", "model_spend_type", "model_share",
    ],
    "ramp_ai_pepm_spend_by_dimension": [
        *CORE_COLUMNS, "date_month", "dimension_type", "dimension_value", "dimension_label",
        "display_order", "median_pepm", "p99_winsorized_weighted_pepm",
    ],
    "ramp_ai_spend_breakdown": [*CORE_COLUMNS, "date_month", "spend_category", "spend_usd", "business_count"],
    "ramp_ai_model_breakdown": [
        *CORE_COLUMNS, "date_month", "ai_provider", "provider_display_order",
        "model_bucket_key", "model_label", "model_display_order", "model_spend_type", "model_share",
    ],
    "ramp_ai_filter_spend_share": [
        *CORE_COLUMNS, "business_office_state", "fte_segment", "naics_sector",
        "company_financing_status", "date_month", "is_latest_complete_month",
        "pepm_spend_type", "spend_share",
    ],
    "ramp_ai_filter_model_share": [
        *CORE_COLUMNS, "business_office_state", "fte_segment", "naics_sector",
        "company_financing_status", "date_month", "is_latest_complete_month", "ai_provider",
        "provider_display_order", "model_bucket_key", "model_label", "model_display_order",
        "model_spend_type", "model_share",
    ],
    "ramp_ai_filter_pepm": [
        *CORE_COLUMNS, "business_office_state", "fte_segment", "naics_sector",
        "company_financing_status", "date_month", "is_latest_complete_month", "median_pepm",
        "p90_pepm", "p99_pepm", "top_10_percent_median_pepm", "top_1_percent_median_pepm",
    ],
    "ramp_ai_jobs_impact": [
        *CORE_COLUMNS, "figure", "month_relative_to_adoption",
        "high_intensity_effect", "high_intensity_ci_low", "high_intensity_ci_high",
        "low_intensity_effect", "low_intensity_ci_low", "low_intensity_ci_high", "units",
    ],
    "ramp_category_adoption_monthly": [
        *CORE_COLUMNS, "category_slug", "spend_month", "vendor_name", "adoption_rate",
    ],
    "ramp_category_spend_share_quarterly": [
        *CORE_COLUMNS, "category_slug", "quarter", "vendor_name", "spend_share",
    ],
    "ramp_category_adoption_yoy_comparison": [
        *CORE_COLUMNS, "category_slug", "vendor_name", "date_month", "adoption_rate",
    ],
}

OPENROUTER_OFFICIAL_LOAD_COLUMNS: dict[str, list[str]] = {
    "official_model_rankings_daily": [
        *CORE_COLUMNS, "usage_date", "model_permaslug", "total_tokens", "rank", "is_other",
        "period", "modality", "context_bucket", "category", "language_type", "is_sampled",
        "as_of", "window_start_date", "window_end_date", "api_version",
    ],
    "official_app_rankings": [
        *CORE_COLUMNS, "snapshot_date", "ranking_type", "app_id", "app_name", "rank",
        "total_tokens", "total_requests", "window_start_date", "window_end_date", "as_of", "api_version",
    ],
    "official_task_classifications": [
        *CORE_COLUMNS, "snapshot_date", "window_days", "as_of", "is_sampled", "tag",
        "display_name", "macro_category", "usage_share", "token_share",
        "category_usage_share", "category_token_share",
    ],
    "official_task_models": [
        *CORE_COLUMNS, "snapshot_date", "window_days", "as_of", "is_sampled", "tag",
        "model_permaslug", "rank", "tag_usage_share", "tag_token_share",
    ],
    "official_task_macro_categories": [
        *CORE_COLUMNS, "snapshot_date", "window_days", "as_of", "is_sampled",
        "macro_category", "display_name", "usage_share", "token_share",
    ],
    "official_providers": [
        *CORE_COLUMNS, "snapshot_date", "provider_slug", "provider_name", "headquarters",
        "datacenters_json", "status_page_url", "privacy_policy_url", "terms_of_service_url",
    ],
    "official_benchmarks": [
        *CORE_COLUMNS, "snapshot_date", "benchmark_source", "model_permaslug", "display_name",
        "variant_index", "arena", "category", "intelligence_index", "coding_index", "agentic_index",
        "elo", "win_rate", "avg_generation_time_ms", "first_place", "second_place", "third_place",
        "fourth_place", "tournament_total", "pricing_prompt", "pricing_completion", "as_of",
        "api_version", "citation",
    ],
    "official_legacy_reconciliation": [
        *CORE_COLUMNS, "usage_date", "official_total_tokens", "official_named_tokens",
        "official_other_tokens", "official_models", "matched_activity_models",
        "official_tokens_with_activity_match", "legacy_activity_tokens_on_official_models",
        "matched_provider_models", "official_tokens_with_provider_match",
        "legacy_provider_tokens_on_official_models", "activity_official_token_coverage",
        "provider_official_token_coverage",
    ],
    "official_source_health": [
        *CORE_COLUMNS, "row_count", "first_date", "latest_date", "duplicate_rows", "status", "detail",
    ],
}

OVERVIEW_LOAD_COLUMNS: dict[str, list[str]] = {
    "market_pulse_daily": [
        *CORE_COLUMNS,
        "pulse_date",
        "openrouter_total_tokens",
        "openrouter_named_tokens",
        "openrouter_other_tokens",
        "openrouter_other_share_pct",
        "openrouter_top_model",
        "openrouter_top_model_tokens",
        "openrouter_top_model_share_pct",
        "openrouter_source_url",
        "openrouter_as_of",
        "catalog_model_count",
        "catalog_models_added_30d",
        "catalog_as_of",
        "catalog_source_url",
        "official_provider_count",
        "official_provider_as_of",
        "top_app",
        "top_app_tokens",
        "top_app_requests",
        "top_app_as_of",
        "top_app_source_url",
        "top_task",
        "top_task_share_pct",
        "top_task_window_days",
        "top_task_as_of",
        "top_task_source_url",
        "ramp_as_of",
        "ramp_ai_adoption_pct",
        "ramp_ai_adoption_mom_pp",
        "ramp_ai_adoption_yoy_pp",
        "ramp_source_url",
        "semiconductor_as_of",
        "ai_demand_ppi",
        "ai_demand_ppi_mom_pct",
        "ai_demand_ppi_3m_trend",
        "semiconductor_source_url",
        "momentum_provider",
        "momentum_score",
        "momentum_as_of",
        "momentum_source_url",
        "frontier_model",
        "frontier_creator",
        "frontier_intelligence_index",
        "frontier_price_1m",
        "frontier_as_of",
        "frontier_source_url",
    ],
    "overview_signal_series": [
        *CORE_COLUMNS,
        "signal_id",
        "signal_label",
        "signal_date",
        "time_grain",
        "value",
        "unit",
        "detail_label",
        "source_dataset",
        "is_complete",
    ],
}

PROVIDER_INCIDENT_LOAD_COLUMNS: dict[str, list[str]] = {
    "provider_incidents": [
        *CORE_COLUMNS, "provider_id", "provider_name", "source_system", "source_incident_id",
        "incident_url", "title", "incident_type", "raw_status", "normalized_status", "raw_severity",
        "severity_level", "started_at", "published_at", "resolved_at", "duration_minutes", "is_active",
        "affected_components_json", "affected_regions_json", "latest_message", "source_confidence", "rule_version",
    ],
    "provider_incident_updates": [
        *CORE_COLUMNS, "provider_id", "provider_name", "source_system", "source_incident_id",
        "source_update_id", "update_at", "raw_status", "message",
    ],
    "provider_incident_components": [
        *CORE_COLUMNS, "provider_id", "provider_name", "source_system", "source_incident_id",
        "component_id", "component_name",
    ],
    "provider_incident_source_health": [
        *CORE_COLUMNS, "provider_id", "provider_name", "source_system", "status", "status_code",
        "response_ms", "content_bytes", "content_hash", "etag", "last_modified", "incident_rows",
        "last_good_incident_rows", "detail",
    ],
}

AI_HIRING_LOAD_COLUMNS: dict[str, list[str]] = {
    "indeed_ai_posting_share_daily": [
        *CORE_COLUMNS, "date", "jobcountry", "ai_share_pct", "source_frequency",
        "source_refresh_cadence", "license",
    ],
    "hiring_companies": [
        *CORE_COLUMNS, "company_id", "company_name", "company_segment", "source_id",
        "source_platform", "board_token", "careers_url", "coverage_start_date", "cohort_version", "is_active",
        "continuous_coverage_start_date",
    ],
    "hiring_jobs": [
        *CORE_COLUMNS, "source_id", "company_id", "company_name", "company_segment", "source_platform",
        "board_token", "source_job_id", "source_requisition_id", "title", "department", "team",
        "location_raw", "country_code", "workplace_type", "employment_type", "published_at",
        "source_updated_at", "job_url", "apply_url", "role_family", "seniority", "is_ai_role",
        "ai_role_confidence", "classifier_version", "content_hash", "first_seen_at", "last_changed_at",
        "missing_since_at", "closed_at", "status", "consecutive_missing_runs",
    ],
    "hiring_job_events": [
        *CORE_COLUMNS, "company_id", "company_name", "source_job_id", "event_at", "event_date",
        "event_type", "previous_status", "new_status", "changed_fields_json", "title", "role_family",
    ],
    "hiring_demand_daily": [
        *CORE_COLUMNS, "snapshot_date", "company_id", "company_name", "company_segment", "cohort_version",
        "role_family", "active_postings", "active_requisitions", "ai_role_postings", "new_postings_28d",
        "closed_postings_28d", "net_posting_flow_28d", "source_status", "coverage_start_date", "same_store_28d",
        "continuous_coverage_start_date",
    ],
    "hiring_source_health": [
        *CORE_COLUMNS, "source_id", "source_kind", "company_id", "company_name", "status", "status_code",
        "response_ms", "content_bytes", "content_hash", "etag", "last_modified", "row_count",
        "last_good_row_count", "detail",
    ],
}

# opencode/replicate marts carry no dataset_id/source_url/source_run_id
# provenance columns (see requires_core_provenance=False on their registry
# entries), so unlike the dicts above these deliberately omit *CORE_COLUMNS.
OPENCODE_LOAD_COLUMNS: dict[str, list[str]] = {
    "opencode_market_share": [
        "timeframe", "usage_date", "date_occurrence", "author",
        "share_pct", "tokens_trillion", "total_tokens_trillion", "scraped_at",
    ],
    "opencode_usage_daily": [
        "user_tier", "timeframe", "usage_date", "date_occurrence", "model_slug", "token_value", "scraped_at",
    ],
    "opencode_users_daily": [
        "user_tier", "timeframe", "usage_date", "date_occurrence", "model_slug", "active_users", "scraped_at",
    ],
    "opencode_leaderboard": [
        "snapshot_date", "user_tier", "timeframe", "rank", "model_slug",
        "provider", "author", "tokens", "rank_change", "scraped_at",
    ],
    "opencode_country_usage": [
        "snapshot_date", "timeframe", "country_code", "continent", "tokens_trillion", "share_pct", "rank", "scraped_at",
    ],
    "opencode_model_catalog": [
        "snapshot_date", "model_id", "lab", "slug", "name", "description", "family", "release_date",
        "last_updated", "context_limit", "output_limit", "input_modalities", "output_modalities",
        "open_weights", "reasoning", "tool_call", "attachment", "temperature",
        "input_cost_per_m", "output_cost_per_m", "cache_read_cost_per_m", "cache_write_cost_per_m", "scraped_at",
    ],
    "opencode_benchmarks": [
        "snapshot_date", "model_id", "model_slug", "benchmark_name", "score", "metric",
        "harness", "variant", "dataset", "version", "source_url", "scraped_at",
    ],
    "opencode_model_deepdives": [
        "snapshot_date", "model_slug", "provider", "author", "rank", "previous_rank", "total_models",
        "token_share_pct", "token_change", "sessions", "unique_users", "tokens_total", "cost_total_usd",
        "tokens_per_session", "cost_per_session_usd", "cost_per_million_usd", "cache_ratio_pct",
        "input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens", "scraped_at",
    ],
}

REPLICATE_LOAD_COLUMNS: dict[str, list[str]] = {
    "replicate_model_catalog": [
        "snapshot_date", "slug", "owner", "name", "collection", "run_count", "is_official",
        "latest_version_created_at", "hardware", "price", "description", "url", "scraped_at",
    ],
    "replicate_collections_summary": ["snapshot_date", "collection_slug", "total_models", "url", "scraped_at"],
}

DATE_COLUMNS = [
    "pulse_date",
    "week_start_date",
    "scrape_date",
    "usage_date",
    "snapshot_date",
    "scraped_at",
    "observed_at",
    "created_at",
    "download_date",
    "repo_created_date",
    "repo_created_at",
    "repo_pushed_at",
    "signal_date",
    "month",
    "date",
    "filing_date",
    "revenue_month",
    "release_date",
    "price_timestamp",
    "snapshot_ts",
    "as_of_date",
    "spend_month",
    "date_month",
    "quarter",
    "started_at",
    "published_at",
    "resolved_at",
    "update_at",
    "coverage_start_date",
    "continuous_coverage_start_date",
    "first_seen_at",
    "last_changed_at",
    "missing_since_at",
    "closed_at",
    "event_at",
    "event_date",
    "source_updated_at",
]
NUMERIC_COLUMNS = [
    "openrouter_total_tokens",
    "openrouter_named_tokens",
    "openrouter_other_tokens",
    "openrouter_other_share_pct",
    "openrouter_top_model_tokens",
    "openrouter_top_model_share_pct",
    "catalog_model_count",
    "catalog_models_added_30d",
    "official_provider_count",
    "top_app_tokens",
    "top_app_requests",
    "top_task_share_pct",
    "top_task_window_days",
    "ramp_ai_adoption_pct",
    "ramp_ai_adoption_mom_pp",
    "ramp_ai_adoption_yoy_pp",
    "ai_demand_ppi",
    "ai_demand_ppi_mom_pct",
    "ai_demand_ppi_3m_trend",
    "frontier_intelligence_index",
    "frontier_price_1m",
    "total_requests",
    "usage_share",
    "token_share",
    "category_usage_share",
    "category_token_share",
    "tag_usage_share",
    "tag_token_share",
    "variant_index",
    "elo",
    "win_rate",
    "avg_generation_time_ms",
    "tournament_total",
    "official_total_tokens",
    "official_named_tokens",
    "official_other_tokens",
    "activity_official_token_coverage",
    "provider_official_token_coverage",
    "row_count",
    "adoption_rate",
    "adoption_rate_yoy",
    "adoption_rank",
    "adoption_rank_mom",
    "adoption_rate_ent",
    "adoption_rate_mm",
    "adoption_rate_smb",
    "adoption_rate_growth_delta_mom",
    "adoption_rate_growth_rank_mom",
    "competitor_switch_rate",
    "new_adopter_share",
    "dominant_fte_segment_pct",
    # ramp AI Index + jobs impact
    "adoption_rate_pct",
    "mom_change_pp",
    "yoy_change_pp",
    "n_firms",
    "ai_firms",
    "median_pepm",
    "p90_pepm",
    "p99_pepm",
    "p99_winsorized_weighted_pepm",
    "raw_weighted_pepm",
    "top_10_percent_median_pepm",
    "top_1_percent_median_pepm",
    "business_count",
    "spend_usd",
    "total_fte_denominator",
    "display_order",
    "spend_category_display_order",
    "spend_share",
    "provider_display_order",
    "model_display_order",
    "model_share",
    "month_relative_to_adoption",
    "high_intensity_effect",
    "high_intensity_ci_low",
    "high_intensity_ci_high",
    "low_intensity_effect",
    "low_intensity_ci_low",
    "low_intensity_ci_high",
    "metric_value",
    "rank",
    "total_tokens",
    "estimated_revenue",
    "pricing_blended",
    "priced_tokens",
    "unpriced_tokens",
    "tokens",
    "growth_percent",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "request_count",
    "stars_today",
    "total_stars",
    "downloads",
    "hf_downloads_30d",
    "hf_downloads_all_time",
    "hf_downloads_daily_est",
    "hf_likes",
    "stargazers_count",
    "matched_signal_count",
    "pypi_7d_avg",
    "pypi_28d_avg",
    "pypi_share_28d",
    "pypi_growth_28d",
    "github_new_repo_count",
    "github_signal_repo_count",
    "github_manifest_repo_count",
    "github_repo_share",
    "github_import_repo_count",
    "github_env_repo_count",
    "github_model_repo_count",
    "momentum_score",
    "monthly_revenue_ntd",
    "mom_pct",
    "yoy_pct",
    "ytd_revenue_ntd",
    "ytd_yoy_pct",
    "fred_ppi_value",
    "fred_ppi_mom_pct",
    "fred_ppi_3m_trend",
    "ppi_component_pcu33443344_rebased",
    "ppi_component_pcu33423342_rebased",
    "ppi_component_pcu335313335313_rebased",
    "ppi_component_pcu334111334111_rebased",
    "ppi_component_pcu3341123341121_rebased",
    "adata_freshness_days",
    "fred_release_lag_days",
    "gpqa",
    "swe_bench",
    "context_window",
    "pricing_prompt",
    "pricing_completion",
    "context_length",
    "gpu_count",
    "spot_price",
    "instance_vcpus",
    "instance_memory_gib",
    "intelligence_index",
    "coding_index",
    "math_index",
    "scicode",
    "price_1m_blended_3_to_1",
    "price_1m_input_tokens",
    "price_1m_output_tokens",
    "median_output_tokens_per_second",
    "median_time_to_first_token_seconds",
    "context_window_tokens",
    "total_parameters_billions",
    "active_parameters_billions",
    "training_tokens_trillions",
    "microsoft",
    "google",
    "meta",
    "amazon",
    "oracle",
    "apple",
    "share_percent",
    "max_tokens",
    "pricing_input",
    "pricing_output",
    "pricing_cache_read",
    "pricing_cache_write",
    "severity_level",
    "duration_minutes",
    "status_code",
    "response_ms",
    "content_bytes",
    "incident_rows",
    "ai_share_pct",
    "consecutive_missing_runs",
    "active_postings",
    "active_requisitions",
    "ai_role_postings",
    "new_postings_28d",
    "closed_postings_28d",
    "net_posting_flow_28d",
    "last_good_row_count",
]


@dataclass(frozen=True)
class DatasetLoadResult:
    dataset_id: str
    label: str
    domain: str
    primary_date_column: str
    metric_column: str | None
    frame: pd.DataFrame
    source_format: str | None
    source_path: Path | None
    missing_columns: list[str]
    duplicate_rows: int
    first_date: str | None
    latest_date: str | None
    latest_scraped_at: str | None
    row_count: int


@dataclass(frozen=True)
class FreshnessInfo:
    latest_scraped_at: str | None
    latest_run_id: str | None
    latest_manifest_path: Path | None
    latest_manifest_scraped_at: str | None


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def normalized_root(base_dir: Path | None = None, source: str = "openrouter") -> Path:
    base = base_dir or repo_root()
    return base / "data" / "normalized" / source


def raw_root(base_dir: Path | None = None, source: str = "openrouter") -> Path:
    base = base_dir or repo_root()
    return base / "data" / "raw" / source


def dataset_ids() -> list[str]:
    return list(DATASET_REGISTRY)


def domain_dataset_ids(domain: str) -> list[str]:
    return list(DOMAIN_ORDER.get(domain, []))


def dataset_source_for_domain(domain: str) -> str:
    if domain == "overview":
        return "overview"
    if domain == "github":
        return "github_trending"
    if domain == "provider_adoption":
        return "provider_adoption"
    if domain == "semiconductor_memory":
        return "semiconductor_memory"
    if domain == "semiconductor_proxies":
        return "semiconductor_proxies"
    if domain == "taiwan_semiconductor_revenue":
        return "taiwan_semiconductor_revenue"
    if domain == "ai_frontier":
        return "llm_benchmarks"
    if domain == "compute_availability":
        return "compute_availability"
    if domain == "openrouter_catalog":
        return "compute_availability"
    if domain == "openrouter_derived":
        return "marts"
    if domain in {"openrouter_official", "openrouter_official_market"}:
        return "openrouter_official"
    if domain == "artificial_analysis":
        return "artificial_analysis"
    if domain == "vercel_ai":
        return "vercel_ai"
    if domain == "ramp":
        return "ramp"
    if domain == "provider_incidents":
        return "provider_incidents"
    if domain == "ai_hiring":
        return "ai_hiring"
    if domain == "opencode":
        return "opencode"
    if domain == "replicate":
        return "replicate"
    return "openrouter"


def load_dataset(
    dataset_id: str,
    base_dir: Path | None = None,
    data_sha: str | None = None,
) -> DatasetLoadResult:
    registry_entry = DATASET_REGISTRY.get(dataset_id, {})
    domain = registry_entry.get("domain", "rankings")
    load_columns = (
        OPENROUTER_LOAD_COLUMNS.get(dataset_id)
        or PROVIDER_ADOPTION_LOAD_COLUMNS.get(dataset_id)
        or VERCEL_AI_LOAD_COLUMNS.get(dataset_id)
        or RAMP_LOAD_COLUMNS.get(dataset_id)
        or OPENROUTER_OFFICIAL_LOAD_COLUMNS.get(dataset_id)
        or OVERVIEW_LOAD_COLUMNS.get(dataset_id)
        or PROVIDER_INCIDENT_LOAD_COLUMNS.get(dataset_id)
        or AI_HIRING_LOAD_COLUMNS.get(dataset_id)
        or OPENCODE_LOAD_COLUMNS.get(dataset_id)
        or REPLICATE_LOAD_COLUMNS.get(dataset_id)
    )

    source = dataset_source_for_domain(str(domain))
    # Serving-provider activity is a normalized OpenRouter source dataset even
    # though it is grouped with the derived economics domain for the focused
    # dashboard load.  Keep the domain grouping and physical source explicit.
    if dataset_id == "cloud_infra_daily_activity":
        source = "openrouter"
    base = normalized_root(base_dir, source=source)
    parquet_path = base / f"{dataset_id}.parquet"
    csv_path = base / f"{dataset_id}.csv"

    required_columns = list(registry_entry.get("required_columns", []))
    if registry_entry.get("requires_core_provenance", True):
        required_columns = list(dict.fromkeys([*CORE_COLUMNS, *required_columns]))
    frame = pd.DataFrame(columns=load_columns or required_columns)
    source_format: str | None = None
    source_path: Path | None = None

    # Prefer fetching committed bytes from GitHub keyed by the latest data SHA, so
    # the running Streamlit Cloud container reflects daily pushes without a reboot.
    # Falls through to the local checkout on any failure (local dev / offline).
    # Remote fetch only applies to the live deployed checkout. When a caller passes
    # a custom base_dir (tests, ad-hoc tooling), read those local files directly so
    # the data source stays predictable and isolated from the production repo.
    root = base_dir if base_dir is not None else repo_root()
    # Explicit base directories are used by CLI pipelines and tests. They must
    # read the files just written in that checkout; fetching the last committed
    # GitHub bytes here can silently feed a mart build the previous day's
    # partial snapshot. The dashboard passes an explicit immutable data_sha when
    # it intentionally wants remote bytes, so preserve that path.
    use_remote_bytes = remote.remote_enabled() and (base_dir is None or data_sha is not None)
    if use_remote_bytes:
        sha = data_sha or remote.latest_data_sha(f"{remote.DATA_PATH_PREFIX}/{source}")
        if sha:
            candidates = (
                (parquet_path, "parquet", lambda b: _read_parquet_projected(io.BytesIO(b), load_columns)),
                (csv_path, "csv", lambda b: pd.read_csv(io.BytesIO(b))),
            )
            for path_obj, fmt, reader in candidates:
                rel = path_obj.relative_to(root).as_posix()
                payload = remote.fetch_bytes(rel, sha)
                if payload is None:
                    continue
                try:
                    frame = reader(payload)
                    source_format = fmt
                    source_path = path_obj
                    break
                except Exception as e:
                    print(f"Warning: remote read failed for {rel}: {e}")

    if source_format is None:
        try:
            if parquet_path.exists():
                frame = _read_parquet_projected(parquet_path, load_columns)
                source_format = "parquet"
                source_path = parquet_path
            elif csv_path.exists():
                frame = pd.read_csv(csv_path)
                source_format = "csv"
                source_path = csv_path
        except Exception as e:
            print(f"Warning: Failed to load dataset {dataset_id} from {parquet_path if parquet_path.exists() else csv_path}: {e}")
            # frame remains an empty DataFrame initialized above
    
    # CRITICAL: Ensure no duplicate columns exist before padding/filtering
    frame = frame.loc[:, ~frame.columns.duplicated()].copy()

    missing_columns = [column for column in required_columns if column not in frame.columns]
    
    # Explicitly projected datasets use their analytical schema. Any legacy
    # dataset without a projection keeps only the columns it actually stored;
    # never pad a frame to the cross-domain EXPECTED_COLUMNS compatibility
    # union, which used to create hundreds of all-null columns in memory.
    target_columns = load_columns or list(frame.columns)
    frame = frame.reindex(columns=target_columns)
    for column in DATE_COLUMNS:
        if column in frame.columns:
            frame[column] = frame[column].astype("string")
    for column in NUMERIC_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    # Python object strings dominate Pandas memory for repeated model/provider
    # labels. Arrow-backed strings preserve nulls and string semantics while
    # storing the values compactly. Keep a compatibility fallback for older
    # local environments even though pyarrow is already a project dependency.
    for column in frame.select_dtypes(include=["object", "string"]).columns:
        try:
            frame[column] = frame[column].astype("string[pyarrow]")
        except (ImportError, TypeError, ValueError):
            frame[column] = frame[column].astype("string")

    keys = registry_entry["natural_keys"]
    duplicate_rows = 0
    if not frame.empty and all(key in frame.columns for key in keys):
        duplicate_rows = int(frame.duplicated(subset=keys).sum())

    primary_date_column = registry_entry["primary_date_column"]
    date_values = (
        sorted(frame[primary_date_column].dropna().astype(str).unique().tolist())
        if primary_date_column in frame.columns
        else []
    )
    scraped_values = sorted(frame["scraped_at"].dropna().astype(str).unique().tolist()) if "scraped_at" in frame.columns else []

    return DatasetLoadResult(
        dataset_id=dataset_id,
        label=str(registry_entry["label"]),
        domain=str(registry_entry["domain"]),
        primary_date_column=str(primary_date_column),
        metric_column=str(registry_entry["metric_column"]) if registry_entry["metric_column"] is not None else None,
        frame=frame,
        source_format=source_format,
        source_path=source_path,
        missing_columns=missing_columns,
        duplicate_rows=duplicate_rows,
        first_date=date_values[0] if date_values else None,
        latest_date=date_values[-1] if date_values else None,
        latest_scraped_at=scraped_values[-1] if scraped_values else None,
        row_count=len(frame),
    )


def load_all_datasets(base_dir: Path | None = None) -> dict[str, DatasetLoadResult]:
    return {dataset_id: load_dataset(dataset_id, base_dir=base_dir) for dataset_id in dataset_ids()}


def load_domain_datasets(
    domain: str,
    base_dir: Path | None = None,
    data_sha: str | None = None,
) -> dict[str, DatasetLoadResult]:
    ids = domain_dataset_ids(domain)
    if len(ids) <= 1:
        return {
            dataset_id: load_dataset(dataset_id, base_dir=base_dir, data_sha=data_sha)
            for dataset_id in ids
        }
    # Each dataset load is an independent, I/O-bound read (local parquet, or an
    # HTTP fetch to raw.githubusercontent.com on Streamlit Cloud). Loading them
    # concurrently turns N sequential round-trips into roughly one round-trip's
    # worth of wall-clock time instead of their sum.
    with ThreadPoolExecutor(max_workers=min(8, len(ids))) as executor:
        results = executor.map(lambda dataset_id: load_dataset(dataset_id, base_dir=base_dir, data_sha=data_sha), ids)
        return dict(zip(ids, results))


def load_latest_manifest(
    base_dir: Path | None = None,
    datasets: dict[str, DatasetLoadResult] | None = None,
    scan_raw_manifests: bool = True,
) -> FreshnessInfo:
    latest_scraped_at: str | None = None
    latest_run_id: str | None = None
    manifest_path: Path | None = None
    manifest_scraped_at: str | None = None

    if scan_raw_manifests:
        # Raw snapshots are stored as data/raw/<source>/<run_id>/manifest.json.
        # Avoid a recursive scan through every captured raw payload on dashboard
        # startup; Streamlit Cloud health checks are sensitive to that overhead.
        raw_base = (base_dir or repo_root()) / "data" / "raw"
        manifests = sorted(raw_base.glob("*/*/manifest.json"))

        if manifests:
            manifest_path = max(manifests, key=lambda p: p.stat().st_mtime_ns)
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                latest_run_id = payload.get("run_id")
                manifest_scraped_at = payload.get("scraped_at")
            except (json.JSONDecodeError, IOError):
                # Handle corrupted manifests gracefully.
                manifest_path = None
        else:
            # Diagnostic: If no manifests found, check if the raw_root even has subdirectories.
            subdirs = list(raw_root(base_dir).iterdir()) if raw_root(base_dir).exists() else []
            if subdirs:
                print(f"Warning: Found {len(subdirs)} directories in raw root, but none contain manifest.json")

    results = datasets if datasets is not None else load_all_datasets(base_dir=base_dir)
    scraped_values = [result.latest_scraped_at for result in results.values() if result.latest_scraped_at]
    if scraped_values:
        latest_scraped_at = max(scraped_values)

    return FreshnessInfo(
        latest_scraped_at=latest_scraped_at,
        latest_run_id=latest_run_id,
        latest_manifest_path=manifest_path,
        latest_manifest_scraped_at=manifest_scraped_at,
    )
