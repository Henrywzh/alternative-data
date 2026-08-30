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
    # Historical (overall) time series. The *Curated datasets above are single-month
    # cross-sections by dimension; these *Breakdown arrays carry the full monthly
    # history the AI Index charts plot over time.
    "ramp_ai_spend_breakdown": {
        "payload_key": "spendBreakdown",
        "fields": ["date_month", "spend_category", "spend_usd", "business_count"],
        "natural_keys": ["date_month", "spend_category"],
        "sort_keys": ["date_month", "spend_category"],
        "numeric": ["spend_usd", "business_count"],
        "min_rows": 60,
    },
    "ramp_ai_model_breakdown": {
        "payload_key": "modelBreakdown",
        "fields": [
            "date_month", "ai_provider", "provider_display_order",
            "model_bucket_key", "model_label", "model_display_order",
            "model_spend_type", "model_share",
        ],
        "natural_keys": ["date_month", "ai_provider", "model_bucket_key"],
        "sort_keys": ["date_month", "provider_display_order", "model_display_order"],
        "numeric": ["provider_display_order", "model_display_order", "model_share"],
        "min_rows": 60,
    },
    # PEPM (a level, not a share) IS published monthly by dimension, so this
    # powers a true monthly time series under the spend-per-employee filter.
    "ramp_ai_pepm_spend_by_dimension": {
        "payload_key": "spendPerEmployeeCurated",
        "fields": [
            "date_month", "dimension_type", "dimension_value", "dimension_label",
            "display_order", "median_pepm", "p99_winsorized_weighted_pepm",
        ],
        "natural_keys": ["date_month", "dimension_type", "dimension_value"],
        "sort_keys": ["date_month", "dimension_type", "display_order"],
        "numeric": ["display_order", "median_pepm", "p99_winsorized_weighted_pepm"],
        "min_rows": 200,
    },
}

# --------------------------------------------------------------- Filter mode
#
# The AI Index "Filter mode" (a dropdown option under each breakdown chart) loads
# the full monthly timeseries for every cohort from dedicated JSON endpoints —
# NOT the page's hydration payload. Each row is one month for one combination of
# the four filter dimensions (each either a specific value or "ALL").
#
# The endpoints require a version token found in the page payload as
# ``filterModeBundleVersion``, so the source scrapes the page first to resolve it.
FILTER_MODE_ENDPOINT_BASE = "https://ramp.com/data/ai-index/filter-mode"
FILTER_MODE_VERSION_KEY = "filterModeBundleVersion"

# The four cohort dimensions, shared across all filter-mode datasets.
FILTER_DIMS = [
    "business_office_state",
    "fte_segment",
    "naics_sector",
    "company_financing_status",
]

# The API returns the month under ``my_date``; the source renames it to
# ``date_month`` for consistency with the rest of the ramp datasets.
FILTER_MODE_DATASETS: dict[str, dict] = {
    "ramp_ai_filter_spend_share": {
        "endpoint": "spendShare",
        "fields": [*FILTER_DIMS, "date_month", "is_latest_complete_month", "pepm_spend_type", "spend_share"],
        "natural_keys": ["date_month", *FILTER_DIMS, "pepm_spend_type"],
        "sort_keys": ["date_month", *FILTER_DIMS, "pepm_spend_type"],
        "numeric": ["spend_share"],
        "min_rows": 5000,
    },
    "ramp_ai_filter_model_share": {
        "endpoint": "modelShare",
        "fields": [
            *FILTER_DIMS, "date_month", "is_latest_complete_month", "ai_provider",
            "provider_display_order", "model_bucket_key", "model_label",
            "model_display_order", "model_spend_type", "model_share",
        ],
        "natural_keys": ["date_month", *FILTER_DIMS, "ai_provider", "model_bucket_key"],
        "sort_keys": ["date_month", *FILTER_DIMS, "provider_display_order", "model_display_order"],
        "numeric": ["provider_display_order", "model_display_order", "model_share"],
        "min_rows": 5000,
    },
    "ramp_ai_filter_pepm": {
        "endpoint": "spendPerEmployee",
        "fields": [
            *FILTER_DIMS, "date_month", "is_latest_complete_month", "median_pepm",
            "p90_pepm", "p99_pepm", "top_10_percent_median_pepm", "top_1_percent_median_pepm",
        ],
        "natural_keys": ["date_month", *FILTER_DIMS],
        "sort_keys": ["date_month", *FILTER_DIMS],
        "numeric": [
            "median_pepm", "p90_pepm", "p99_pepm",
            "top_10_percent_median_pepm", "top_1_percent_median_pepm",
        ],
        "min_rows": 2000,
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


# ------------------------------------------------------------- Category Charts
#
# Scraped from the Datawrapper chart widgets embedded inside each category page
# at ramp.com/vendors/categories/<slug>. Contains category-level adoption trends,
# quarterly share of category spend, and annual YoY comparison snapshots.
CATEGORY_CHARTS_DATASETS: dict[str, dict] = {
    "ramp_category_adoption_monthly": {
        "fields": ["category_slug", "spend_month", "vendor_name", "adoption_rate"],
        "natural_keys": ["category_slug", "spend_month", "vendor_name"],
        "sort_keys": ["category_slug", "spend_month", "vendor_name"],
        "numeric": ["adoption_rate"],
        "min_rows": 100,
    },
    "ramp_category_spend_share_quarterly": {
        "fields": ["category_slug", "quarter", "vendor_name", "spend_share"],
        "natural_keys": ["category_slug", "quarter", "vendor_name"],
        "sort_keys": ["category_slug", "quarter", "vendor_name"],
        "numeric": ["spend_share"],
        "min_rows": 20,
        # Retired upstream. This was an optional secondary toggle chart, linked
        # from inside the category's primary Datawrapper chart (2/33 categories
        # as of 2026-08-04). Ramp has since removed those links: every one of
        # the 33 category pages now embeds exactly one chart, the adoption
        # series, and no page or chart references a second Datawrapper id.
        # Nothing is fetchable, so the min_rows floor can only ever fail --
        # and because the gate is all-or-nothing, it was failing the whole
        # category-charts run and discarding the 33 healthy adoption CSVs
        # with it. Keep the schema so the committed history stays readable.
        "retired": "2026-08-30: Ramp removed the secondary chart from every category page",
    },
    "ramp_category_adoption_yoy_comparison": {
        "fields": ["category_slug", "vendor_name", "date_month", "adoption_rate"],
        "natural_keys": ["category_slug", "vendor_name", "date_month"],
        "sort_keys": ["category_slug", "vendor_name", "date_month"],
        "numeric": ["adoption_rate"],
        "min_rows": 20,
        # Retired upstream alongside spend_share_quarterly -- same toggle
        # mechanism, same disappearance (it covered 4/33 categories, ~51 rows).
        # Note this dataset was never a time series: it holds exactly two
        # months, Feb 2025 and Feb 2026, because the chart itself is a
        # year-over-year pair.
        "retired": "2026-08-30: Ramp removed the secondary chart from every category page",
    },
}
