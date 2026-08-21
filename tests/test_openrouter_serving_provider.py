from __future__ import annotations

import json

import pandas as pd
import pytest

from openrouter_data.exceptions import ExtractionError
from openrouter_data.models import DatasetRecord, RunContext, Snapshot
from openrouter_data.pipeline import ServingProviderActivityPipeline
from openrouter_data.serving_provider import (
    classify_serving_provider,
    flag_latest_likely_incomplete_day,
    is_first_party_route,
)
from openrouter_data.sources.serving_provider_activity import (
    ServingProviderActivitySource,
)
from openrouter_data.storage import StorageManager
from openrouter_revenue import build_serving_provider_economics


def test_serving_provider_taxonomy_fails_new_slugs_to_unknown() -> None:
    assert classify_serving_provider("google-vertex") == "hyperscaler"
    assert classify_serving_provider("google-ai-studio") == "hyperscaler"
    assert classify_serving_provider("coreweave") == "independent_inference"
    assert classify_serving_provider("seed") == "first_party_lab"
    assert classify_serving_provider("anthropic") == "first_party_lab"
    assert classify_serving_provider("brand-new-provider") == "unknown"


def test_first_party_route_uses_company_aliases_not_provider_type_alone() -> None:
    assert is_first_party_route("qwen/qwen3", "alibaba") is True
    assert is_first_party_route("google/gemini-3", "google-vertex") is True
    assert is_first_party_route("google/gemini-3", "google-ai-studio") is True
    assert is_first_party_route("mistralai/mistral-large", "mistral") is True
    assert is_first_party_route("x-ai/grok-4", "xai") is True
    assert is_first_party_route("anthropic/claude-opus", "google-vertex") is False
    assert is_first_party_route("openai/gpt-5", "anthropic") is False


def test_latest_previous_day_is_flagged_when_volume_is_clearly_partial() -> None:
    dates = pd.date_range("2026-08-12", periods=9, freq="D")
    rows = [
        {
            "usage_date": day.strftime("%Y-%m-%d"),
            "total_tokens": 25.0 if index == 8 else 100.0,
        }
        for index, day in enumerate(dates)
    ]

    flagged = flag_latest_likely_incomplete_day(
        pd.DataFrame(rows), scraped_at="2026-08-21T03:00:00Z"
    )

    latest = flagged[flagged["usage_date"].eq("2026-08-20")].iloc[0]
    assert latest["is_complete_day"] == False  # noqa: E712
    assert latest["include_in_default_kpis"] == False  # noqa: E712
    assert latest["observation_status"] == "latest_likely_incomplete_volume"


def test_latest_previous_day_remains_complete_at_normal_volume() -> None:
    dates = pd.date_range("2026-08-12", periods=9, freq="D")
    frame = pd.DataFrame(
        {"usage_date": dates.strftime("%Y-%m-%d"), "total_tokens": [100.0] * 9}
    )

    flagged = flag_latest_likely_incomplete_day(
        frame, scraped_at="2026-08-21T03:00:00Z"
    )

    assert flagged.iloc[-1]["is_complete_day"] == True  # noqa: E712
    assert flagged.iloc[-1]["observation_status"] == "complete"


def test_latest_current_day_default_clock_handles_timezone_without_crashing() -> None:
    today = pd.Timestamp.now(tz="UTC").normalize()
    dates = pd.date_range(today - pd.Timedelta(days=3), periods=4, freq="D")
    frame = pd.DataFrame(
        {"usage_date": dates.strftime("%Y-%m-%d"), "total_tokens": [100.0] * 4}
    )

    flagged = flag_latest_likely_incomplete_day(frame)

    assert flagged.iloc[-1]["is_complete_day"] == False  # noqa: E712
    assert flagged.iloc[-1]["include_in_default_kpis"] == False  # noqa: E712
    assert flagged.iloc[-1]["observation_status"] == "latest_likely_incomplete"


def test_incomplete_volume_is_detected_per_serving_provider() -> None:
    dates = pd.date_range("2026-08-12", periods=9, freq="D")
    rows = []
    for provider, latest_tokens, normal_tokens in [
        ("small-partial", 10.0, 100.0),
        ("large-complete", 10_000.0, 10_000.0),
    ]:
        rows.extend(
            {
                "usage_date": day.strftime("%Y-%m-%d"),
                "serving_provider": provider,
                "total_tokens": latest_tokens if index == 8 else normal_tokens,
            }
            for index, day in enumerate(dates)
        )

    flagged = flag_latest_likely_incomplete_day(
        pd.DataFrame(rows),
        scraped_at="2026-08-21T03:00:00Z",
        group_columns=["serving_provider"],
    )
    latest = flagged[flagged["usage_date"].eq("2026-08-20")].set_index(
        "serving_provider"
    )

    assert latest.loc["small-partial", "include_in_default_kpis"] == False  # noqa: E712
    assert latest.loc["large-complete", "include_in_default_kpis"] == True  # noqa: E712


def test_serving_provider_source_extracts_owner_and_serving_dimensions() -> None:
    chart = {
        "data": [
            {"x": "2026-08-18 00:00:00", "ys": {"openai/gpt-5": 100}},
            {"x": "2026-08-19 00:00:00", "ys": {"openai/gpt-5": 120}},
            {"x": "2026-08-20 00:00:00", "ys": {"openai/gpt-5": 110}},
        ]
    }
    encoded = json.dumps(f"44:{json.dumps(chart, separators=(',', ':'))}")
    html = f"<script>self.__next_f.push([1,{encoded}])</script>"
    source = ServingProviderActivitySource()
    source.provider_metadata["coreweave"] = {
        "slug": "coreweave",
        "name": "CoreWeave",
        "headquarters": "US",
        "datacenters": ["US"],
    }
    context = RunContext(
        run_id="serving-provider-test",
        scraped_at=pd.Timestamp("2026-08-21T00:00:00Z").to_pydatetime(),
    )

    records = source.extract(
        [
            Snapshot(
                name="serving_provider_coreweave",
                source_url="fixture://provider/coreweave",
                body=html,
            )
        ],
        context,
    )["cloud_infra_daily_activity"]

    assert len(records) == 3
    assert {record.serving_provider for record in records} == {"coreweave"}
    assert {record.model_origin_company for record in records} == {"OpenAI"}
    assert {record.serving_provider_type for record in records} == {
        "independent_inference"
    }
    assert not any(record.is_first_party_route for record in records)


def test_serving_provider_economics_never_fabricates_unpriced_revenue() -> None:
    activity = pd.DataFrame(
        [
            {
                "usage_date": "2026-08-19",
                "serving_provider": "coreweave",
                "serving_provider_name": "CoreWeave",
                "model_permaslug": "openai/gpt-5",
                "total_tokens": 1000.0,
            },
            {
                "usage_date": "2026-08-19",
                "serving_provider": "coreweave",
                "serving_provider_name": "CoreWeave",
                "model_permaslug": "openai/free-route:free",
                "total_tokens": 500.0,
            },
            {
                "usage_date": "2026-08-19",
                "serving_provider": "coreweave",
                "serving_provider_name": "CoreWeave",
                "model_permaslug": "openai/unpriced",
                "total_tokens": 250.0,
            },
        ]
    )
    pricing = pd.DataFrame(
        [
            {
                "snapshot_ts": "2026-08-18T00:00:00Z",
                "model_id": "openai/gpt-5",
                "canonical_slug": "openai/gpt-5",
                "provider_prefix": "openai",
                "pricing_prompt": 0.000001,
                "pricing_completion": 0.000003,
            }
        ]
    )

    economics = build_serving_provider_economics(
        activity,
        pricing,
        scraped_at="2026-08-21T00:00:00Z",
    ).set_index("model_permaslug")

    assert pd.notna(economics.loc["openai/gpt-5", "estimated_revenue"])
    assert economics.loc["openai/free-route:free", "estimated_revenue"] == 0.0
    assert economics.loc["openai/free-route:free", "pricing_coverage_status"] == "free_zero_revenue"
    assert pd.isna(economics.loc["openai/unpriced", "estimated_revenue"])
    assert economics.loc["openai/unpriced", "pricing_coverage_status"] == "unpriced"
    assert economics.loc["openai/unpriced", "unpriced_tokens"] == 250.0


def test_serving_provider_economics_migrates_padded_legacy_provider_columns() -> None:
    activity = pd.DataFrame(
        [
            {
                "usage_date": "2026-08-19",
                "provider_slug": "coreweave",
                "provider_name": "CoreWeave",
                "entity_id": pd.NA,
                "entity_name": pd.NA,
                "serving_provider": pd.NA,
                "serving_provider_name": pd.NA,
                "model_permaslug": "openai/gpt-5",
                "total_tokens": 1000.0,
            }
        ]
    )
    pricing = pd.DataFrame(
        [
            {
                "snapshot_ts": "2026-08-18T00:00:00Z",
                "model_id": "openai/gpt-5",
                "canonical_slug": "openai/gpt-5",
                "provider_prefix": "openai",
                "pricing_prompt": 0.000001,
                "pricing_completion": 0.000003,
            }
        ]
    )

    economics = build_serving_provider_economics(
        activity,
        pricing,
        scraped_at="2026-08-21T00:00:00Z",
    )

    assert economics.iloc[0]["serving_provider"] == "coreweave"
    assert economics.iloc[0]["serving_provider_name"] == "CoreWeave"
    assert economics.iloc[0]["provider_slug"] == "coreweave"
    assert economics.iloc[0]["model_origin_company"] == "OpenAI"


def test_serving_provider_economics_preserves_raw_meta_route_identity() -> None:
    activity = pd.DataFrame(
        [
            {
                "usage_date": "2026-08-19",
                "serving_provider": route,
                "serving_provider_name": name,
                "model_permaslug": "meta-llama/llama-4",
                "total_tokens": tokens,
            }
            for route, name, tokens in [
                ("meta", "Meta", 1000.0),
                ("meta-llama", "Meta Llama", 2000.0),
            ]
        ]
    )
    pricing = pd.DataFrame(
        [
            {
                "snapshot_ts": "2026-08-18T00:00:00Z",
                "model_id": "meta-llama/llama-4",
                "canonical_slug": "meta-llama/llama-4",
                "provider_prefix": "meta",
                "pricing_prompt": 0.000001,
                "pricing_completion": 0.000003,
            }
        ]
    )

    economics = build_serving_provider_economics(
        activity,
        pricing,
        scraped_at="2026-08-21T00:00:00Z",
    )

    assert len(economics) == 2
    assert economics.set_index("serving_provider")["total_tokens"].to_dict() == {
        "meta": 1000.0,
        "meta-llama": 2000.0,
    }
    assert set(economics["provider_slug"]) == {"meta"}


def test_serving_provider_fields_do_not_widen_unrelated_openrouter_datasets(
    tmp_path,
) -> None:
    storage = StorageManager(tmp_path)
    storage.upsert_dataset(
        "top_models",
        [
            DatasetRecord(
                dataset_id="top_models",
                source_url="fixture://rankings",
                source_run_id="run",
                scraped_at="2026-08-21T00:00:00Z",
                week_start_date="2026-08-17",
                entity_id="openai/gpt-5",
                metric_value=1.0,
            )
        ],
    )

    columns = pd.read_parquet(
        tmp_path / "data/normalized/openrouter/top_models.parquet"
    ).columns
    assert "serving_provider" not in columns
    assert "model_origin_company" not in columns


def test_serving_provider_dataset_uses_narrow_physical_schema(tmp_path) -> None:
    storage = StorageManager(tmp_path)
    storage.upsert_dataset(
        "cloud_infra_daily_activity",
        [
            DatasetRecord(
                dataset_id="cloud_infra_daily_activity",
                source_url="fixture://provider/coreweave",
                source_run_id="run",
                scraped_at="2026-08-21T00:00:00Z",
                usage_date="2026-08-20",
                entity_id="coreweave",
                entity_name="CoreWeave",
                provider_slug="coreweave",
                provider_name="CoreWeave",
                serving_provider="coreweave",
                serving_provider_name="CoreWeave",
                serving_provider_type="independent_inference",
                model_origin_company="OpenAI",
                model_permaslug="openai/gpt-5",
                total_tokens=1.0,
            )
        ],
    )

    columns = pd.read_parquet(
        tmp_path
        / "data/normalized/openrouter/cloud_infra_daily_activity.parquet"
    ).columns
    assert "serving_provider" in columns
    assert "week_label" not in columns
    assert "app_id" not in columns


def test_serving_provider_pipeline_refuses_fetch_failures(tmp_path) -> None:
    pipeline = ServingProviderActivityPipeline(tmp_path)
    pipeline.source.last_failures = [
        {"slug": "coreweave", "error": "503 after retries"}
    ]
    context = RunContext(
        run_id="failed-fetch",
        scraped_at=pd.Timestamp("2026-08-21T00:00:00Z").to_pydatetime(),
    )

    with pytest.raises(ExtractionError, match="refusing a partial upsert"):
        pipeline._validate_extracted(
            context,
            {"cloud_infra_daily_activity": []},
        )


def test_serving_provider_source_records_chart_parse_omissions() -> None:
    source = ServingProviderActivitySource()
    source.provider_metadata["coreweave"] = {
        "slug": "coreweave",
        "name": "CoreWeave",
    }
    context = RunContext(
        run_id="parse-failure",
        scraped_at=pd.Timestamp("2026-08-21T00:00:00Z").to_pydatetime(),
    )

    extracted = source.extract(
        [
            Snapshot(
                name="serving_provider_coreweave",
                source_url="fixture://provider/coreweave",
                body="<html><body>layout changed</body></html>",
            )
        ],
        context,
    )

    assert extracted["cloud_infra_daily_activity"] == []
    assert source.last_failures == []
    assert source.last_parse_omissions == [
        {
            "slug": "coreweave",
            "status": (
                "provider page returned successfully but no "
                "serving-provider activity chart was parsed"
            ),
        }
    ]


def test_serving_provider_validation_requires_eighty_percent_catalog_coverage() -> None:
    context = RunContext(
        run_id="coverage",
        scraped_at=pd.Timestamp("2026-08-21T00:00:00Z").to_pydatetime(),
    )
    records = [
        DatasetRecord(
            dataset_id="cloud_infra_daily_activity",
            source_url=f"fixture://provider/p{index}",
            source_run_id=context.run_id,
            scraped_at=context.scraped_at_iso,
            usage_date="2026-08-20",
            serving_provider=f"p{index}",
            model_permaslug="openai/gpt-5",
            total_tokens=1.0,
        )
        for index in range(8)
    ]

    summary = ServingProviderActivitySource.validate_records(
        records,
        scraped_at=context.scraped_at,
        expected_provider_count=10,
    )
    assert summary["provider_count"] == 8
    with pytest.raises(ExtractionError, match="covered only 7/10"):
        ServingProviderActivitySource.validate_records(
            records[:7],
            scraped_at=context.scraped_at,
            expected_provider_count=10,
        )


def test_serving_provider_manifest_exposes_parse_omissions(tmp_path) -> None:
    pipeline = ServingProviderActivityPipeline(tmp_path)
    pipeline._serving_provider_health = {
        "provider_count": 8,
        "expected_provider_count": 10,
        "provider_coverage_ratio": 0.8,
        "parse_omission_count": 2,
        "parse_omission_slugs": ["no-chart-a", "no-chart-b"],
    }
    context = RunContext(
        run_id="manifest-health",
        scraped_at=pd.Timestamp("2026-08-21T00:00:00Z").to_pydatetime(),
    )

    manifest = pipeline._build_manifest(
        mode="serving-provider-activity-daily-update",
        context=context,
        extracted={},
    )

    assert manifest["source_health"]["parse_omission_count"] == 2
    assert manifest["source_health"]["parse_omission_slugs"] == [
        "no-chart-a",
        "no-chart-b",
    ]
