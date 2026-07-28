from __future__ import annotations

from pathlib import Path

import pandas as pd

from dashboard.data import DatasetLoadResult
from dashboard.sections.openrouter import (
    _catalog_alias_map,
    _clean_provider_request_frame,
    _combine_explorer_activity,
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
