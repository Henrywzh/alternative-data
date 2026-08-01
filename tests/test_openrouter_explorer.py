from __future__ import annotations

from pathlib import Path

import pandas as pd

from dashboard.data import DatasetLoadResult
from dashboard.sections.openrouter import (
    _catalog_alias_map,
    _clean_provider_request_frame,
    _combine_explorer_activity,
    _comparison_merge_sources,
    _comparison_interpolate_internal_weekly_request_gaps,
    _comparison_metric_frame,
    _comparison_first_week_coverage,
    _comparison_weekly_rankings,
    _comparison_chart,
    _comparison_rolling_7d_frame,
    _context_length_bucket_pivot,
    _drop_known_model_activity_test_rows,
    _format_token_axis_label,
    _market_share_weekly_totals,
    _drop_identical_route_alias_rows,
    _format_price_per_m,
    build_openrouter_explorer_views,
    _normalize_explorer_activity,
    _prepare_explorer_catalog,
    company_explorer_state,
    model_explorer_state,
)
from openrouter_data.models import DatasetRecord
from openrouter_data.storage import StorageManager
from dashboard.theme import MODEL_COLORS


def _dataset_result(dataset_id: str, frame: pd.DataFrame) -> DatasetLoadResult:
    return DatasetLoadResult(
        dataset_id=dataset_id,
        label=dataset_id,
        domain="rankings",
        primary_date_column="week_start_date",
        metric_column="metric_value",
        frame=frame,
        source_format="parquet",
        source_path=None,
        missing_columns=[],
        duplicate_rows=0,
        first_date=None,
        latest_date=None,
        latest_scraped_at=None,
        row_count=len(frame),
    )


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


def test_unavailable_catalog_prices_are_missing_not_negative_prices() -> None:
    catalog = _prepare_explorer_catalog(pd.DataFrame([
        {
            "model_id": "openrouter/auto",
            "canonical_slug": "openrouter/auto",
            "model_name": "OpenRouter Auto",
            "provider_prefix": "openrouter",
            "created_at": 1_782_864_000,
            "context_length": 128000,
            "architecture": "text->text",
            "pricing_prompt": -1.0,
            "pricing_completion": -1.0,
        }
    ]))

    row = catalog.iloc[0]
    assert pd.isna(row["pricing_prompt"])
    assert pd.isna(row["input_price_per_m"])
    assert _format_price_per_m(-1.0) == "n/a"


def test_legacy_provider_request_rows_that_duplicate_market_share_are_ignored() -> None:
    request = pd.DataFrame([
        {"week_start_date": "2026-07-13", "entity_id": "openai", "metric_value": 500.0},
        {"week_start_date": "2026-07-13", "entity_id": "anthropic", "metric_value": 42.0},
    ])
    market = pd.DataFrame([
        {"week_start_date": "2026-07-13", "entity_id": "openai", "metric_value": 500.0},
    ])

    cleaned = _clean_provider_request_frame(request, market)

    assert cleaned[["week_start_date", "entity_id"]].to_dict("records") == [
        {"week_start_date": "2026-07-13", "entity_id": "anthropic"}
    ]


def test_meta_and_meta_llama_share_one_company_in_catalog_and_activity() -> None:
    catalog = _prepare_explorer_catalog(pd.DataFrame([
        {
            "model_id": "meta/muse-spark",
            "canonical_slug": "meta/muse-spark",
            "model_name": "Meta: Muse Spark",
            "provider_prefix": "meta",
            "created_at": 1_782_864_000,
            "context_length": 1_000_000,
            "architecture": "text->text",
            "pricing_prompt": 0.000001,
            "pricing_completion": 0.000003,
        },
        {
            "model_id": "meta-llama/llama-4",
            "canonical_slug": "meta-llama/llama-4",
            "model_name": "Meta: Llama 4",
            "provider_prefix": "meta-llama",
            "created_at": 1_782_864_000,
            "context_length": 1_000_000,
            "architecture": "text->text",
            "pricing_prompt": 0.000001,
            "pricing_completion": 0.000003,
        },
    ]))
    activity = _normalize_explorer_activity(pd.DataFrame([
        {"usage_date": "2026-07-20", "model_permaslug": "meta/muse-spark", "entity_id": "meta", "total_tokens": 100},
        {"usage_date": "2026-07-20", "model_permaslug": "meta-llama/llama-4", "entity_id": "meta-llama", "total_tokens": 200},
    ]), _catalog_alias_map(catalog))

    assert set(catalog["provider_slug"]) == {"meta"}
    assert set(catalog["company"]) == {"Meta"}
    assert set(activity["entity_id"]) == {"meta"}


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


def test_company_model_chart_selects_recent_leaders_but_keeps_history() -> None:
    catalog = _catalog()
    recent_model = catalog.iloc[[0]].copy()
    recent_model["model_id"] = "openai/recent-model"
    recent_model["canonical_slug"] = "openai/recent-model"
    recent_model["model_name"] = "OpenAI: Recent Model"
    recent_model["provider_slug"] = "openai"
    recent_model["company"] = "OpenAI"
    extra_models = []
    for index in range(8):
        row = recent_model.copy()
        row["model_id"] = f"openai/old-model-{index}"
        row["canonical_slug"] = f"openai/old-model-{index}"
        row["model_name"] = f"OpenAI: Old Model {index}"
        extra_models.append(row)
    catalog = pd.concat([catalog, recent_model, *extra_models], ignore_index=True)
    catalog["tokens_30d"] = 0.0
    catalog.loc[catalog["model_id"].eq("openai/recent-model"), "tokens_30d"] = 100.0
    aliases = _catalog_alias_map(catalog)
    activity_rows = [
        {"usage_date": "2026-04-13", "model_permaslug": "openai/gpt-test", "entity_id": "openai", "total_tokens": 10_000},
        {"usage_date": "2026-07-25", "model_permaslug": "openai/gpt-test", "entity_id": "openai", "total_tokens": 10},
        {"usage_date": "2026-07-25", "model_permaslug": "openai/recent-model", "entity_id": "openai", "total_tokens": 100},
    ]
    activity_rows.extend(
        {"usage_date": "2026-07-25", "model_permaslug": f"openai/old-model-{index}", "entity_id": "openai", "total_tokens": 20}
        for index in range(8)
    )
    activity = _normalize_explorer_activity(pd.DataFrame(activity_rows), aliases)
    state = company_explorer_state(
        {"catalog": catalog, "combined_activity": activity, "provider_activity": activity, "model_activity": pd.DataFrame()},
        "openai",
    )

    assert pd.Timestamp("2026-04-13") in state["model_pivot"].index
    assert "openai/recent-model" in state["model_pivot"].columns
    assert "openai/gpt-test" not in state["model_pivot"].columns
    assert "Other models" in state["model_pivot"].columns
    assert "openai/recent-model" in state["weekly_model_pivot"].columns


def test_explorer_drops_identical_free_alias_rows_and_keeps_distinct_rows() -> None:
    frame = pd.DataFrame([
        {"usage_date_dt": pd.Timestamp("2026-07-20"), "category_slug": "all", "model_permaslug": "tencent/hy3-20260706", "total_tokens": 100.0, "request_count": 10},
        {"usage_date_dt": pd.Timestamp("2026-07-20"), "category_slug": "all", "model_permaslug": "tencent/hy3-20260706:free", "total_tokens": 100.0, "request_count": 10},
        {"usage_date_dt": pd.Timestamp("2026-07-21"), "category_slug": "all", "model_permaslug": "tencent/hy3-20260706", "total_tokens": 100.0, "request_count": 10},
        {"usage_date_dt": pd.Timestamp("2026-07-21"), "category_slug": "all", "model_permaslug": "tencent/hy3-20260706:free", "total_tokens": 250.0, "request_count": 25},
    ])
    cleaned = _drop_identical_route_alias_rows(frame)
    assert len(cleaned) == 3
    assert cleaned["model_permaslug"].tolist() == [
        "tencent/hy3-20260706",
        "tencent/hy3-20260706",
        "tencent/hy3-20260706:free",
    ]


def test_combined_activity_uses_provider_free_route_after_api_alias_deduplication() -> None:
    provider = pd.DataFrame([
        {"usage_date_dt": pd.Timestamp("2026-07-20"), "model_permaslug": "tencent/hy3-20260706", "total_tokens": 10.0},
        {"usage_date_dt": pd.Timestamp("2026-07-20"), "model_permaslug": "tencent/hy3-20260706:free", "total_tokens": 1_000.0},
    ])
    model = pd.DataFrame([
        {"usage_date_dt": pd.Timestamp("2026-07-20"), "category_slug": "all", "model_permaslug": "tencent/hy3-20260706", "total_tokens": 10.0, "request_count": 1},
        {"usage_date_dt": pd.Timestamp("2026-07-20"), "category_slug": "all", "model_permaslug": "tencent/hy3-20260706:free", "total_tokens": 10.0, "request_count": 1},
    ])
    combined = _combine_explorer_activity(provider, model)
    assert combined["total_tokens"].sum() == 1_010.0
    assert set(combined["model_permaslug"]) == {"tencent/hy3-20260706", "tencent/hy3-20260706:free"}


def test_company_explorer_builds_source_aware_metric_views() -> None:
    catalog = _catalog()
    aliases = _catalog_alias_map(catalog)
    provider_activity = _normalize_explorer_activity(pd.DataFrame([
        {"usage_date": "2026-06-16", "model_permaslug": "openai/gpt-test-20260701", "entity_id": "openai", "total_tokens": 500},
        {"usage_date": "2026-06-17", "model_permaslug": "openai/gpt-test-20260701", "entity_id": "openai", "total_tokens": 1000},
        {"usage_date": "2026-06-18", "model_permaslug": "openai/gpt-test-20260701", "entity_id": "openai", "total_tokens": 1500},
    ]), aliases)
    model_activity = _normalize_explorer_activity(pd.DataFrame([
        {
            "usage_date": "2026-04-22", "model_permaslug": "openai/gpt-test-20260701",
            "category_slug": "programming", "total_tokens": 50, "request_count": 7,
        },
        {
            "usage_date": "2026-06-17", "model_permaslug": "openai/gpt-test-20260701",
            "category_slug": "all", "total_tokens": 1000, "request_count": 100,
        },
        {
            "usage_date": "2026-06-18", "model_permaslug": "openai/gpt-test-20260701",
            "category_slug": "all", "total_tokens": 1500, "request_count": 100,
        },
    ]), aliases)
    economics = pd.DataFrame([
        {
            "usage_date_dt": pd.Timestamp("2026-06-17"), "provider_slug": "openai",
            "model_permaslug": "openai/gpt-test", "total_tokens": 1000.0,
            "estimated_revenue": 0.003,  # $3/M
        },
        {
            "usage_date_dt": pd.Timestamp("2026-06-18"), "provider_slug": "openai",
            "model_permaslug": "openai/gpt-test", "total_tokens": 1500.0,
            "estimated_revenue": 0.006,  # $4/M
        },
    ])
    catalog["tokens_30d"] = [2500.0, 0.0]
    views = {
        "catalog": catalog,
        "combined_activity": provider_activity,
        "model_activity": model_activity,
        "economics": economics,
        "weekly_company_tokens": pd.DataFrame([
            {"usage_week": pd.Timestamp("2025-08-04"), "company_slug": "openai", "tokens": 10_000.0},
            {"usage_week": pd.Timestamp("2025-08-11"), "company_slug": "openai", "tokens": 20_000.0},
        ]),
        "weekly_company_requests": pd.DataFrame([
            {"usage_week": pd.Timestamp("2025-08-04"), "company_slug": "openai", "requests": 100.0},
            {"usage_week": pd.Timestamp("2025-08-11"), "company_slug": "openai", "requests": 100.0},
        ]),
    }

    state = company_explorer_state(views, "openai")

    assert state["weekly_metrics"]["Tokens"].index.tolist() == [pd.Timestamp("2025-08-04"), pd.Timestamp("2025-08-11")]
    assert state["weekly_metrics"]["Tokens / Request"].iloc[-1, 0] == 200.0
    assert state["daily_metrics"]["Requests"].index[0] == pd.Timestamp("2026-04-16")
    assert state["daily_metrics"]["Requests"].loc[pd.Timestamp("2026-04-22"), "Requests"] == 7
    assert state["daily_request_proxy"] is True
    assert state["daily_metrics"]["Tokens / Request"].index[0] == pd.Timestamp("2026-04-16")
    assert state["daily_metrics"]["Realized Price"].index[0] == pd.Timestamp("2026-04-16")
    assert state["daily_metrics"]["Tokens / Request"].iloc[-1, 0] == 15.0
    assert state["daily_metrics"]["Realized Price"].iloc[-1, 0] == 4.0
    assert state["price_coverage_daily"].iloc[-1, 0] == 100.0
    assert state["historical_pricing_coverage"] == 100.0


def test_company_explorer_reports_historical_pricing_coverage() -> None:
    catalog = _catalog()
    catalog["tokens_30d"] = [0.0, 0.0]
    state = company_explorer_state(
        {
            "catalog": catalog,
            "combined_activity": pd.DataFrame(),
            "model_activity": pd.DataFrame(),
            "economics": pd.DataFrame([
                {
                    "usage_date_dt": pd.Timestamp("2026-04-16"),
                    "provider_slug": "openai",
                    "total_tokens": 100.0,
                    "estimated_revenue": 0.001,
                },
                {
                    "usage_date_dt": pd.Timestamp("2026-04-17"),
                    "provider_slug": "openai",
                    "total_tokens": 100.0,
                    "estimated_revenue": pd.NA,
                },
            ]),
        },
        "openai",
    )

    assert state["historical_pricing_coverage"] == 50.0


def test_company_explorer_falls_back_to_daily_activity_for_missing_weekly_company_rows() -> None:
    catalog = _catalog()
    aliases = _catalog_alias_map(catalog)
    provider_activity = _normalize_explorer_activity(pd.DataFrame([
        {"usage_date": "2026-06-17", "model_permaslug": "openai/gpt-test-20260701", "entity_id": "openai", "total_tokens": 1000},
        {"usage_date": "2026-06-18", "model_permaslug": "openai/gpt-test-20260701", "entity_id": "openai", "total_tokens": 1500},
    ]), aliases)
    model_activity = _normalize_explorer_activity(pd.DataFrame([
        {
            "usage_date": "2026-06-17", "model_permaslug": "openai/gpt-test-20260701",
            "category_slug": "all", "total_tokens": 1000, "request_count": 100,
        },
        {
            "usage_date": "2026-06-18", "model_permaslug": "openai/gpt-test-20260701",
            "category_slug": "all", "total_tokens": 1500, "request_count": 100,
        },
    ]), aliases)
    catalog["tokens_30d"] = [2500.0, 0.0]
    state = company_explorer_state(
        {
            "catalog": catalog,
            "combined_activity": provider_activity,
            "model_activity": model_activity,
            "weekly_company_tokens": pd.DataFrame(columns=["usage_week", "company_slug", "tokens"]),
            "weekly_company_requests": pd.DataFrame(columns=["usage_week", "company_slug", "requests"]),
        },
        "openai",
    )

    assert not state["weekly_metrics"]["Tokens"].empty
    assert not state["weekly_metrics"]["Requests"].empty
    assert state["weekly_token_source"] == "Daily activity aggregated to weekly totals"
    assert state["weekly_request_source"] == "Daily model activity aggregated to weekly totals"


def test_company_weekly_tokens_use_complete_provider_activity_not_top_model_ranking(monkeypatch) -> None:
    catalog_frame = pd.DataFrame([
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
        }
    ])
    monkeypatch.setattr(
        "dashboard.sections.openrouter.compute_compute_availability_views",
        lambda datasets: {
            "models_latest": catalog_frame,
            "models_history_start": pd.Timestamp("2026-01-01"),
            "models_history_end": pd.Timestamp("2026-07-06"),
        },
    )
    top_models = pd.DataFrame([
        {"week_start_date": "2026-06-29", "entity_id": "openai/gpt-test", "metric_value": 999_000.0},
    ])
    provider_activity = pd.DataFrame([
        {"usage_date": "2026-07-06", "model_permaslug": "openai/gpt-test", "total_tokens": 100_000.0},
        {"usage_date": "2026-07-07", "model_permaslug": "openai/gpt-test", "total_tokens": 50_000.0},
        {"usage_date": "2026-07-13", "model_permaslug": "openai/gpt-test", "total_tokens": 200_000.0},
    ])
    provider_requests = pd.DataFrame([
        {"week_start_date": "2026-06-29", "entity_id": "openai", "metric_value": 1_000.0},
        {"week_start_date": "2026-07-06", "entity_id": "openai", "metric_value": 2_000.0},
    ])

    views = build_openrouter_explorer_views({
        "raw_openrouter_models": _dataset_result("raw_openrouter_models", catalog_frame),
        "top_models": _dataset_result("top_models", top_models),
        "provider_daily_activity": _dataset_result("provider_daily_activity", provider_activity),
        "provider_weekly_requests": _dataset_result("provider_weekly_requests", provider_requests),
    })

    company_tokens = views["weekly_company_tokens"]
    assert company_tokens["company_slug"].eq("openai").all()
    assert company_tokens["usage_week"].tolist() == [
        pd.Timestamp("2026-07-06"),
        pd.Timestamp("2026-07-13"),
    ]
    assert company_tokens["tokens"].tolist() == [150_000.0, 200_000.0]
    state = company_explorer_state(views, "openai")
    assert "openai/gpt-test" in state["weekly_model_pivot"].columns
    assert state["weekly_token_source"] == "Provider daily model activity aggregated to weekly totals"


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
    archive_path = tmp_path / "data" / "normalized" / "openrouter_archive" / "openrouter_model_activity_2025.parquet"
    assert archive_path.exists()
    archived = pd.read_parquet(archive_path)
    assert archived["usage_date"].tolist() == ["2025-12-01"]


def test_model_activity_archive_upserts_without_duplicates(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    common = {
        "dataset_id": "openrouter_model_activity",
        "source_url": "fixture://activity",
        "scraped_at": "2026-07-16T00:00:00Z",
        "model_permaslug": "openai/gpt-test",
        "category_slug": "all",
        "request_count": 10,
    }
    first = [
        DatasetRecord(**common, source_run_id="run-1", usage_date="2025-12-01", total_tokens=100),
        DatasetRecord(**common, source_run_id="run-1", usage_date="2026-07-16", total_tokens=200),
    ]
    second = [
        DatasetRecord(**common, source_run_id="run-2", usage_date="2025-12-01", total_tokens=150),
        DatasetRecord(**common, source_run_id="run-2", usage_date="2026-07-17", total_tokens=250),
    ]

    storage.upsert_dataset("openrouter_model_activity", first)
    storage.upsert_dataset("openrouter_model_activity", second)

    archive_path = tmp_path / "data" / "normalized" / "openrouter_archive" / "openrouter_model_activity_2025.parquet"
    archived = pd.read_parquet(archive_path)
    assert len(archived) == 1
    assert float(archived.iloc[0]["total_tokens"]) == 150.0
    assert archived.iloc[0]["source_run_id"] == "run-2"


def test_comparison_source_merge_does_not_add_overlapping_periods() -> None:
    legacy = pd.DataFrame([
        {"period_start": "2026-07-06", "entity_id": "openai", "value": 100.0},
        {"period_start": "2026-07-13", "entity_id": "openai", "value": 110.0},
    ])
    modern = pd.DataFrame([
        {"period_start": "2026-07-13", "entity_id": "openai", "value": 40.0},
        {"period_start": "2026-07-20", "entity_id": "openai", "value": 50.0},
    ])

    prefer_modern = _comparison_merge_sources(legacy, modern, prefer_modern=True)
    prefer_legacy = _comparison_merge_sources(legacy, modern, prefer_modern=False)

    assert prefer_modern.set_index("period_start").loc["2026-07-13", "value"] == 40.0
    assert prefer_legacy.set_index("period_start").loc["2026-07-13", "value"] == 110.0
    assert len(prefer_modern) == 3


def test_comparison_interpolates_only_isolated_pre_2026_request_gaps() -> None:
    frame = pd.DataFrame([
        {"period_start": "2025-12-22", "entity_id": "anthropic", "value": 34_724_923.0},
        {"period_start": "2026-01-05", "entity_id": "anthropic", "value": 48_960_735.0},
        {"period_start": "2025-08-11", "entity_id": "z-ai", "value": 6_795_814.0},
        {"period_start": "2025-08-25", "entity_id": "z-ai", "value": 6_492_824.0},
        {"period_start": "2025-10-06", "entity_id": "deepseek", "value": 10.0},
        {"period_start": "2025-10-27", "entity_id": "deepseek", "value": 20.0},
    ])

    result, notes = _comparison_interpolate_internal_weekly_request_gaps(frame)

    estimates = result.set_index(["entity_id", "period_start"])["value"]
    assert estimates.loc["anthropic", pd.Timestamp("2025-12-29")] == (34_724_923.0 + 48_960_735.0) / 2
    assert estimates.loc["z-ai", pd.Timestamp("2025-08-18")] == (6_795_814.0 + 6_492_824.0) / 2
    assert "deepseek" not in {str(note["entity_id"]) for note in notes}
    assert {(str(note["entity_id"]), note["period_start"]) for note in notes} == {
        ("anthropic", pd.Timestamp("2025-12-29")),
        ("z-ai", pd.Timestamp("2025-08-18")),
    }


def test_comparison_does_not_interpolate_multi_week_or_post_cutoff_gaps() -> None:
    frame = pd.DataFrame([
        {"period_start": "2025-08-04", "entity_id": "provider", "value": 10.0},
        {"period_start": "2025-09-01", "entity_id": "provider", "value": 20.0},
        {"period_start": "2026-01-05", "entity_id": "provider", "value": 30.0},
        {"period_start": "2026-01-19", "entity_id": "provider", "value": 50.0},
    ])

    result, notes = _comparison_interpolate_internal_weekly_request_gaps(frame)

    assert len(result) == len(frame)
    assert notes == []


def test_comparison_rankings_select_one_coherent_snapshot() -> None:
    frame = pd.DataFrame([
        {"week_start_date": "2026-07-05", "entity_id": "openai", "metric_value": 10.0, "source_run_id": "partial", "scraped_at": "2026-07-06"},
        {"week_start_date": "2026-07-06", "entity_id": "openai", "metric_value": 100.0, "source_run_id": "complete", "scraped_at": "2026-07-07"},
        {"week_start_date": "2026-07-06", "entity_id": "anthropic", "metric_value": 200.0, "source_run_id": "complete", "scraped_at": "2026-07-07"},
    ])

    result = _comparison_weekly_rankings(
        frame,
        date_column="week_start_date",
        entity_column="entity_id",
        value_column="metric_value",
        entity_mapper=lambda value: str(value),
        sunday_alignment=True,
    )

    assert result["value"].sum() == 300.0
    assert result["period_start"].nunique() == 1


def test_duplicate_aligned_market_snapshots_prefer_complete_sunday_snapshot() -> None:
    rows = []
    for index in range(10):
        entity = f"provider-{index}"
        rows.append({
            "week_start_date": "2025-07-27",
            "entity_id": entity,
            "metric_value": 100.0,
            "source_run_id": "sunday-complete",
            "scraped_at": "2026-04-04T12:00:00Z",
        })
        rows.append({
            "week_start_date": "2025-07-28",
            "entity_id": entity,
            "metric_value": 1.0,
            "source_run_id": "monday-malformed",
            "scraped_at": "2026-07-06T09:00:00Z",
        })
    frame = pd.DataFrame(rows)

    weekly = _comparison_weekly_rankings(
        frame,
        date_column="week_start_date",
        entity_column="entity_id",
        value_column="metric_value",
        entity_mapper=lambda value: str(value),
        sunday_alignment=True,
    )
    totals = _market_share_weekly_totals(frame)

    assert weekly["value"].sum() == 1_000.0
    assert totals.loc["2025-07-28"] == 1_000.0


def test_comparison_metric_frame_uses_priced_tokens_for_realized_price() -> None:
    tokens = pd.DataFrame([{"period_start": pd.Timestamp("2026-07-06"), "entity_id": "openai", "value": 1_000_000.0}])
    requests = pd.DataFrame([{"period_start": pd.Timestamp("2026-07-06"), "entity_id": "openai", "value": 100.0}])
    economics = pd.DataFrame([
        {"period_start": pd.Timestamp("2026-07-06"), "entity_id": "openai", "revenue": 2.5, "priced_tokens": 500_000.0}
    ])

    result = _comparison_metric_frame(tokens, requests, economics).iloc[0]

    assert result["Tokens / request"] == 10_000.0
    assert result["Realized price"] == 5.0


def test_token_axis_uses_dashboard_billion_and_trillion_units() -> None:
    assert _format_token_axis_label(800_000_000_000) == "800B"
    assert _format_token_axis_label(1_200_000_000_000) == "1.2T"


def test_known_model_activity_test_runs_are_removed_but_other_category_rows_remain() -> None:
    frame = pd.DataFrame([
        {"source_run_id": "20260416T134419Z-9c52eb4a", "model_permaslug": "openai/test", "request_count": 1},
        {"source_run_id": "20260424T163607Z-e27b0c04", "model_permaslug": "openai/test", "request_count": 2},
        {"source_run_id": "20260718T042655Z-85d677c5", "model_permaslug": "openai/live", "request_count": 3},
    ])

    cleaned = _drop_known_model_activity_test_rows(frame)

    assert cleaned["source_run_id"].tolist() == ["20260718T042655Z-85d677c5"]


def test_comparison_chart_supports_up_to_five_companies() -> None:
    frame = pd.DataFrame([
        {"period_start": "2026-07-01", "entity_id": company, "Tokens": value}
        for company, value in zip(("openai", "anthropic", "google", "deepseek", "qwen"), (10, 20, 30, 40, 50))
    ])

    figure = _comparison_chart(
        frame,
        entity_ids=("openai", "anthropic", "google", "deepseek", "qwen"),
        entity_labels={company: company.title() for company in frame["entity_id"]},
        metric="Tokens",
        window="Daily",
        normalized=False,
    )

    assert len(figure.data) == 5
    assert [trace.line.color for trace in figure.data] == MODEL_COLORS[:5]
    assert len({trace.line.color for trace in figure.data}) == 5


def test_comparison_rolling_7d_frame_uses_request_weighted_intensity() -> None:
    frame = pd.DataFrame([
        {
            "period_start": date,
            "entity_id": "openai",
            "Tokens": float(index + 1),
            "Requests": 1.0,
            "Estimated revenue": 2.0,
            "Realized price": 2.0,
        }
        for index, date in enumerate(pd.date_range("2026-07-01", periods=8, freq="D"))
    ])

    rolling = _comparison_rolling_7d_frame(frame)
    last = rolling.iloc[-1]

    assert last["Tokens"] == 5.0
    assert last["Requests"] == 1.0
    assert last["Tokens / request"] == 5.0
    assert last["Estimated revenue"] == 2.0


def test_comparison_rolling_7d_ratio_excludes_token_only_days() -> None:
    frame = pd.DataFrame([
        {
            "period_start": date,
            "entity_id": "anthropic",
            "Tokens": tokens,
            "Requests": requests,
        }
        for date, tokens, requests in (
            ("2026-06-15", 1_000_000.0, None),
            ("2026-06-16", 1_100_000.0, None),
            ("2026-06-17", 500_000.0, 100.0),
        )
    ])

    rolling = _comparison_rolling_7d_frame(frame)
    first_valid = rolling.dropna(subset=["Tokens / request"]).iloc[0]

    assert first_valid["period_start"] == pd.Timestamp("2026-06-17")
    assert first_valid["Tokens / request"] == 5_000.0


def test_context_length_bucket_pivot_aggregates_models_in_fixed_bucket_order() -> None:
    frame = pd.DataFrame([
        {"week_start_date": "2026-07-06", "context_length_bucket": "10K-100K", "entity_id": "a", "metric_value": 30},
        {"week_start_date": "2026-07-06", "context_length_bucket": "10K-100K", "entity_id": "b", "metric_value": 20},
        {"week_start_date": "2026-07-06", "context_length_bucket": "1K-10K", "entity_id": "a", "metric_value": 50},
        {"week_start_date": "2026-07-13", "context_length_bucket": "1K-10K", "entity_id": "a", "metric_value": 60},
    ])

    pivot = _context_length_bucket_pivot(frame)

    assert list(pivot.columns) == ["1K-10K", "10K-100K"]
    assert pivot.loc[pd.Timestamp("2026-07-06"), "10K-100K"] == 50
    assert pivot.loc[pd.Timestamp("2026-07-06"), "1K-10K"] == 50


def test_first_week_coverage_marks_midweek_source_start_as_partial() -> None:
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-01-16", "2026-01-17", "2026-01-18"])})

    first_week, first_complete_week, observed_days = _comparison_first_week_coverage(
        frame,
        date_column="date",
    )

    assert first_week == pd.Timestamp("2026-01-12")
    assert first_complete_week == pd.Timestamp("2026-01-19")
    assert observed_days == 3
