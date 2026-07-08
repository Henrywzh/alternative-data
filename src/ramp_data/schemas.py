"""Dataset configuration for the config-driven Ramp datasets.

This is a dependency-free module (pure data) imported by ``storage`` (to build
its column/key maps), by the ``ai_index`` / ``jobs_impact`` sources (to extract),
and by ``pipeline`` (for quality gates). Keeping it neutral avoids an import
cycle between storage and sources.

The AI Index datasets come straight out of the ``ramp.com/data/ai-index`` RSC
payload — each is a JSON array under ``payload_key`` whose object fields already
use the snake_case names we keep, so extraction is near-passthrough. They are
history/append datasets keyed on ``date_month`` (+ any breakdown dimension).
"""
from __future__ import annotations

CORE_COLUMNS = ["dataset_id", "source_url", "source_run_id", "scraped_at"]


AI_INDEX_DATASETS: dict[str, dict] = {
    "ramp_ai_adoption_overall": {
        "payload_key": "adoptionOverall",
        "fields": ["date_month", "adoption_rate_pct", "mom_change_pp", "yoy_change_pp"],
        "natural_keys": ["date_month"],
        "sort_keys": ["date_month"],
        "numeric": ["adoption_rate_pct", "mom_change_pp", "yoy_change_pp"],
        "min_rows": 24,
    },
    "ramp_ai_adoption_by_size": {
        "payload_key": "adoptionSize",
        "fields": ["date_month", "business_size", "adoption_rate_pct", "mom_change_pp"],
        "natural_keys": ["date_month", "business_size"],
        "sort_keys": ["date_month", "business_size"],
        "numeric": ["adoption_rate_pct", "mom_change_pp"],
        "min_rows": 60,
    },
    "ramp_ai_adoption_by_sector": {
        "payload_key": "adoptionIndustry",
        "fields": ["date_month", "naics_sector", "adoption_rate_pct", "mom_change_pp"],
        "natural_keys": ["date_month", "naics_sector"],
        "sort_keys": ["date_month", "naics_sector"],
        "numeric": ["adoption_rate_pct", "mom_change_pp"],
        "min_rows": 120,
    },
    "ramp_ai_adoption_by_state": {
        "payload_key": "adoptionState",
        "fields": ["date_month", "state_code", "adoption_rate_pct", "n_firms", "ai_firms"],
        "natural_keys": ["date_month", "state_code"],
        "sort_keys": ["date_month", "state_code"],
        "numeric": ["adoption_rate_pct", "n_firms", "ai_firms"],
        "min_rows": 500,
    },
    "ramp_ai_adoption_by_vendor": {
        "payload_key": "adoptionVendor",
        "fields": ["date_month", "vendor", "adoption_rate_pct", "mom_change_pp"],
        "natural_keys": ["date_month", "vendor"],
        "sort_keys": ["date_month", "vendor"],
        "numeric": ["adoption_rate_pct", "mom_change_pp"],
        "min_rows": 100,
    },
    "ramp_ai_pepm_spend": {
        "payload_key": "spendPerEmployee",
        "fields": [
            "date_month", "median_pepm", "p90_pepm", "p99_pepm",
            "p99_winsorized_weighted_pepm", "raw_weighted_pepm",
            "top_10_percent_median_pepm", "top_1_percent_median_pepm",
            "business_count", "spend_usd", "total_fte_denominator", "is_publishable",
        ],
        "natural_keys": ["date_month"],
        "sort_keys": ["date_month"],
        "numeric": [
            "median_pepm", "p90_pepm", "p99_pepm", "p99_winsorized_weighted_pepm",
            "raw_weighted_pepm", "top_10_percent_median_pepm", "top_1_percent_median_pepm",
            "business_count", "spend_usd", "total_fte_denominator",
        ],
        "min_rows": 24,
    },
    "ramp_ai_spend_share_by_category": {
        "payload_key": "spendShareCurated",
        "fields": [
            "date_month", "dimension_type", "dimension_value", "dimension_label",
            "display_order", "spend_category_key", "spend_category",
            "spend_category_display_order", "spend_share",
        ],
        "natural_keys": ["date_month", "dimension_type", "dimension_value", "spend_category_key"],
        "sort_keys": ["date_month", "dimension_type", "dimension_value", "spend_category_display_order"],
        "numeric": ["display_order", "spend_category_display_order", "spend_share"],
        "min_rows": 40,
    },
    "ramp_ai_provider_model_share": {
        "payload_key": "modelShareCurated",
        "fields": [
            "date_month", "dimension_type", "dimension_value", "dimension_label",
            "display_order", "ai_provider", "provider_display_order",
            "model_bucket_key", "model_label", "model_display_order",
            "model_spend_type", "model_share",
        ],
        "natural_keys": ["date_month", "dimension_type", "dimension_value", "ai_provider", "model_bucket_key"],
        "sort_keys": ["date_month", "dimension_type", "dimension_value", "provider_display_order", "model_display_order"],
        "numeric": ["display_order", "provider_display_order", "model_display_order", "model_share"],
        "min_rows": 100,
    },
}


# AI Jobs Impact — client-rendered event study (Playwright). Static annual paper.
JOBS_IMPACT_DATASET = "ramp_ai_jobs_impact"
JOBS_IMPACT = {
    "fields": [
        "figure", "month_relative_to_adoption",
        "high_intensity_effect", "high_intensity_ci_low", "high_intensity_ci_high",
        "low_intensity_effect", "low_intensity_ci_low", "low_intensity_ci_high",
        "units",
    ],
    "natural_keys": ["figure", "month_relative_to_adoption"],
    "sort_keys": ["figure", "month_relative_to_adoption"],
    "numeric": [
        "month_relative_to_adoption",
        "high_intensity_effect", "high_intensity_ci_low", "high_intensity_ci_high",
        "low_intensity_effect", "low_intensity_ci_low", "low_intensity_ci_high",
    ],
    "min_rows": 30,
}
