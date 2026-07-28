from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from openrouter_data.models import DatasetRecord, RunContext, Snapshot
from openrouter_data.exceptions import ExtractionError
from openrouter_data.pipeline import ActivityPipeline, ProviderActivityPipeline
from openrouter_data.sources.activity import ActivitySource
from openrouter_data.sources.provider_activity import PROVIDER_SLUGS, ProviderActivitySource
from openrouter_data.storage import StorageManager


def _make_next_f_script(label: str, payload: list) -> str:
    encoded = json.dumps(f"{label}:{json.dumps(payload, separators=(',', ':'))}")
    return f"<script>self.__next_f.push([1,{encoded}])</script>"


def _build_activity_html(items: list[dict]) -> str:
    payload = [
        "$",
        "$L53",
        None,
        {
            "slug": "anthropic/claude-opus-4.7",
            "categories": items,
        },
    ]
    return f"<html><body>{_make_next_f_script('44', payload)}</body></html>"


def test_activity_source_extracts_requests_prompt_completion_and_reasoning_tokens() -> None:
    html = _build_activity_html(
        [
            {
                "date": "2026-04-24",
                "model": "anthropic/claude-opus-4.7",
                "category": "programming",
                "count": 123,
                "total_prompt_tokens": 1000,
                "total_completion_tokens": 250,
                "total_reasoning_tokens": 75,
            }
        ]
    )
    source = ActivitySource()
    context = RunContext(run_id="activity-test", scraped_at=pd.Timestamp("2026-04-24T00:00:00Z").to_pydatetime())

    extracted = source.extract(
        [Snapshot(name="activity", source_url="fixture://anthropic/claude-opus-4.7/activity", body=html)],
        context,
    )

    records = extracted["openrouter_model_activity"]
    assert len(records) == 1
    record = records[0]
    assert record.request_count == 123
    assert record.prompt_tokens == 1000.0
    assert record.completion_tokens == 250.0
    assert record.reasoning_tokens == 75.0
    assert record.total_tokens == 1250.0


def test_activity_source_extracts_current_stats_api_payload() -> None:
    payload = {
        "data": {
            "analytics": [{
                "date": "2026-07-17 00:00:00",
                "model_permaslug": "meta/muse-spark-1.1-20260709",
                "total_prompt_tokens": 1000,
                "total_completion_tokens": 250,
                "total_native_tokens_reasoning": 75,
                "count": 123,
            }]
        }
    }
    source = ActivitySource()
    context = RunContext(run_id="activity-api-test", scraped_at=pd.Timestamp("2026-07-17T00:00:00Z").to_pydatetime())
    records = source.extract(
        [Snapshot(name="activity_meta_muse_spark", source_url="https://openrouter.ai/api/frontend/v1/stats/model-activity", body=json.dumps(payload))],
        context,
    )["openrouter_model_activity"]

    assert len(records) == 1
    assert records[0].model_permaslug == "meta/muse-spark-1.1-20260709"
    assert records[0].category_slug == "all"
    assert records[0].request_count == 123
    assert records[0].total_tokens == 1250.0


def test_activity_source_preserves_requested_route_variant() -> None:
    payload = {
        "data": {
            "analytics": [{
                "date": "2026-07-20 00:00:00",
                # OpenRouter currently strips :free from the response slug.
                "model_permaslug": "tencent/hy3-20260706",
                "total_prompt_tokens": 100,
                "total_completion_tokens": 25,
                "count": 10,
            }]
        }
    }
    source = ActivitySource()
    context = RunContext(run_id="activity-variant-test", scraped_at=pd.Timestamp("2026-07-21T00:00:00Z").to_pydatetime())
    snapshots = [
        Snapshot(
            name="paid",
            source_url="https://openrouter.ai/api/frontend/v1/stats/model-activity?permaslug=tencent%2Fhy3-20260706&variant=standard",
            body=json.dumps(payload),
        ),
        Snapshot(
            name="free",
            source_url="https://openrouter.ai/api/frontend/v1/stats/model-activity?permaslug=tencent%2Fhy3-20260706%3Afree&variant=standard",
            body=json.dumps(payload),
        ),
    ]

    records = source.extract(snapshots, context)["openrouter_model_activity"]
    assert {record.model_permaslug for record in records} == {
        "tencent/hy3-20260706",
        "tencent/hy3-20260706:free",
    }


def test_activity_source_drops_identical_paid_free_payloads_only() -> None:
    records = [
        DatasetRecord(
            dataset_id="openrouter_model_activity", source_url="fixture://paid", source_run_id="run",
            scraped_at="2026-07-21T00:00:00Z", usage_date="2026-07-20",
            model_permaslug="tencent/hy3-20260706", category_slug="all",
            total_tokens=100.0, request_count=10, prompt_tokens=80.0, completion_tokens=20.0,
        ),
        DatasetRecord(
            dataset_id="openrouter_model_activity", source_url="fixture://free", source_run_id="run",
            scraped_at="2026-07-21T00:00:00Z", usage_date="2026-07-20",
            model_permaslug="tencent/hy3-20260706:free", category_slug="all",
            total_tokens=100.0, request_count=10, prompt_tokens=80.0, completion_tokens=20.0,
        ),
        DatasetRecord(
            dataset_id="openrouter_model_activity", source_url="fixture://free", source_run_id="run",
            scraped_at="2026-07-22T00:00:00Z", usage_date="2026-07-21",
            model_permaslug="tencent/hy3-20260706:free", category_slug="all",
            total_tokens=250.0, request_count=25, prompt_tokens=200.0, completion_tokens=50.0,
        ),
    ]
    cleaned = ActivitySource.drop_identical_route_alias_records(records)
    assert [record.model_permaslug for record in cleaned] == [
        "tencent/hy3-20260706", "tencent/hy3-20260706:free"
    ]


def test_activity_source_leaves_reasoning_tokens_null_when_missing() -> None:
    html = _build_activity_html(
        [
            {
                "date": "2026-04-24",
                "model": "anthropic/claude-opus-4.7",
                "category": "general",
                "count": 55,
                "total_prompt_tokens": 900,
                "total_completion_tokens": 100,
            }
        ]
    )
    source = ActivitySource()
    context = RunContext(run_id="activity-test", scraped_at=pd.Timestamp("2026-04-24T00:00:00Z").to_pydatetime())

    extracted = source.extract(
        [Snapshot(name="activity", source_url="fixture://anthropic/claude-opus-4.7/activity", body=html)],
        context,
    )

    record = extracted["openrouter_model_activity"][0]
    assert record.reasoning_tokens is None
    assert record.total_tokens == 1000.0


def test_model_activity_validation_rejects_partial_latest_scrape() -> None:
    records = [
        DatasetRecord(
            dataset_id="openrouter_model_activity",
            source_url="fixture://activity",
            source_run_id="run-1",
            scraped_at="2026-07-20T00:00:00Z",
            usage_date="2026-07-20",
            model_permaslug="openai/gpt-5.6",
            category_slug="all",
            request_count=10,
            total_tokens=1000,
        )
    ]

    with pytest.raises(ExtractionError, match="latest complete date has 1 models"):
        ActivitySource.validate_records(
            records,
            scraped_at=pd.Timestamp("2026-07-20T00:00:00Z").to_pydatetime(),
            min_models_latest=2,
        )


def test_model_activity_validation_accepts_complete_latest_scrape() -> None:
    records = [
        DatasetRecord(
            dataset_id="openrouter_model_activity",
            source_url="fixture://activity",
            source_run_id="run-1",
            scraped_at="2026-07-20T00:00:00Z",
            usage_date="2026-07-20",
            model_permaslug=f"openai/model-{index}",
            category_slug="all",
            request_count=10,
            total_tokens=1000,
        )
        for index in range(2)
    ]

    summary = ActivitySource.validate_records(
        records,
        scraped_at=pd.Timestamp("2026-07-20T00:00:00Z").to_pydatetime(),
        min_models_latest=2,
    )

    assert summary["latest_model_count"] == 2


def test_openrouter_model_activity_storage_roundtrips_reasoning_tokens(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)

    records = [
        DatasetRecord(
            dataset_id="openrouter_model_activity",
            source_url="fixture://activity",
            source_run_id="run-1",
            scraped_at="2026-04-24T00:00:00Z",
            usage_date="2026-04-24",
            model_permaslug="anthropic/claude-opus-4.7",
            category_slug="programming",
            request_count=123,
            prompt_tokens=1000.0,
            completion_tokens=250.0,
            reasoning_tokens=75.0,
            total_tokens=1250.0,
        )
    ]

    written = storage.upsert_dataset("openrouter_model_activity", records)

    assert "reasoning_tokens" in written.columns
    assert float(written.loc[0, "reasoning_tokens"]) == 75.0

    loaded = storage.load_dataset("openrouter_model_activity")
    assert "reasoning_tokens" in loaded.columns
    assert float(loaded.loc[0, "reasoning_tokens"]) == 75.0


def test_provider_daily_activity_storage_is_parquet_only(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)

    records = [
        DatasetRecord(
            dataset_id="provider_daily_activity",
            source_url="fixture://provider/openai",
            source_run_id="run-1",
            scraped_at="2026-04-24T00:00:00Z",
            entity_id="openai",
            entity_name="OpenAI",
            usage_date="2026-04-24",
            model_permaslug="openai/gpt-4.1",
            prompt_tokens=0.0,
            completion_tokens=0.0,
            total_tokens=1250.0,
        )
    ]

    storage.upsert_dataset("provider_daily_activity", records)

    root = tmp_path / "data" / "normalized" / "openrouter"
    assert not (root / "provider_daily_activity.csv").exists()
    assert (root / "provider_daily_activity.parquet").exists()

    loaded = storage.load_dataset("provider_daily_activity")
    assert len(loaded) == 1
    assert loaded.loc[0, "model_permaslug"] == "openai/gpt-4.1"
    assert float(loaded.loc[0, "total_tokens"]) == 1250.0


def test_provider_daily_activity_keeps_same_day_others_per_provider(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    records = [
        DatasetRecord(
            dataset_id="provider_daily_activity",
            source_url=f"fixture://provider/{provider}",
            source_run_id="run-1",
            scraped_at="2026-04-24T00:00:00Z",
            entity_id=provider,
            entity_name=display,
            usage_date="2026-04-24",
            model_permaslug="Others",
            total_tokens=tokens,
        )
        for provider, display, tokens in (("openai", "OpenAI", 100.0), ("meta", "Meta", 200.0))
    ]

    written = storage.upsert_dataset("provider_daily_activity", records)

    assert len(written) == 2
    assert set(written["entity_id"]) == {"openai", "meta"}
    assert written["total_tokens"].sum() == 300.0


def test_provider_activity_source_still_emits_total_tokens_only() -> None:
    payload = [
        "$",
        "$L53",
        None,
        {
            "data": [
                {"x": "2026-04-20 00:00:00", "ys": {"anthropic/claude-opus-4.7": 12000}},
                {"x": "2026-04-21 00:00:00", "ys": {"anthropic/claude-opus-4.7": 12100}},
                {"x": "2026-04-22 00:00:00", "ys": {"anthropic/claude-opus-4.7": 12200}},
                {"x": "2026-04-23 00:00:00", "ys": {"anthropic/claude-opus-4.7": 12300}},
                {"x": "2026-04-24 00:00:00", "ys": {"anthropic/claude-opus-4.7": 12345}},
            ],
        },
    ]
    html = f"<html><body>{_make_next_f_script('44', payload)}</body></html>"
    source = ProviderActivitySource()
    context = RunContext(run_id="provider-activity-test", scraped_at=pd.Timestamp("2026-04-24T00:00:00Z").to_pydatetime())

    extracted = source.extract(
        [Snapshot(name="provider_anthropic", source_url="fixture://anthropic", body=html)],
        context,
    )

    records = extracted["provider_daily_activity"]
    assert len(records) == 5
    record = next(record for record in records if record.usage_date == "2026-04-24")
    assert record.total_tokens == 12345.0
    assert record.prompt_tokens == 0.0
    assert record.completion_tokens == 0.0
    assert record.request_count is None


def test_provider_activity_validation_accepts_healthy_provider_rows() -> None:
    records = [
        DatasetRecord(
            dataset_id="provider_daily_activity",
            source_url="fixture://provider/openai",
            source_run_id="run-1",
            scraped_at="2026-06-30T00:00:00Z",
            entity_id="openai",
            entity_name="OpenAI",
            usage_date=f"2026-06-{day:02d}",
            model_permaslug="openai/gpt-5.5",
            total_tokens=1_000_000.0,
        )
        for day in range(25, 31)
    ]

    summary = ProviderActivitySource.validate_records(
        records,
        expected_providers={"openai": "OpenAI"},
        scraped_at=pd.Timestamp("2026-06-30T00:00:00Z").to_pydatetime(),
        min_days=5,
        max_lag_days=1,
    )

    assert summary["openai"]["date_count"] == 6
    assert summary["openai"]["latest_date"] == "2026-06-30"


def test_provider_activity_validation_allows_new_provider_short_history() -> None:
    records = [
        DatasetRecord(
            dataset_id="provider_daily_activity",
            source_url="fixture://provider/meta",
            source_run_id="run-1",
            scraped_at="2026-06-30T00:00:00Z",
            entity_id="meta",
            entity_name="Meta",
            usage_date=f"2026-06-{day:02d}",
            model_permaslug="meta/muse-spark-1.1-20260709",
            total_tokens=1_000_000.0,
        )
        for day in range(26, 31)
    ]

    summary = ProviderActivitySource.validate_records(
        records,
        expected_providers={"meta": "Meta"},
        scraped_at=pd.Timestamp("2026-06-30T00:00:00Z").to_pydatetime(),
        min_days_by_provider={"meta": 5},
        max_lag_days=1,
    )

    assert summary["meta"]["date_count"] == 5


def test_provider_activity_validation_rejects_html_drift_partial_rows() -> None:
    records = [
        DatasetRecord(
            dataset_id="provider_daily_activity",
            source_url="fixture://provider/openai",
            source_run_id="run-1",
            scraped_at="2026-06-30T00:00:00Z",
            entity_id="openai",
            entity_name="OpenAI",
            usage_date="2026-06-01",
            model_permaslug="malformed-model-key",
            total_tokens=0.0,
        )
    ]

    with pytest.raises(ExtractionError, match="Provider activity extraction failed health checks"):
        ProviderActivitySource.validate_records(
            records,
            expected_providers={"openai": "OpenAI", "anthropic": "Anthropic"},
            scraped_at=pd.Timestamp("2026-06-30T00:00:00Z").to_pydatetime(),
            min_days=5,
            max_lag_days=1,
        )


def test_provider_activity_validation_allows_others_synthetic_bucket() -> None:
    records = []
    for day in range(25, 31):
        records.append(
            DatasetRecord(
                dataset_id="provider_daily_activity",
                source_url="fixture://provider/openai",
                source_run_id="run-1",
                scraped_at="2026-06-30T00:00:00Z",
                entity_id="openai",
                entity_name="OpenAI",
                usage_date=f"2026-06-{day:02d}",
                model_permaslug="Others",
                total_tokens=100_000.0,
            )
        )

    summary = ProviderActivitySource.validate_records(
        records,
        expected_providers={"openai": "OpenAI"},
        scraped_at=pd.Timestamp("2026-06-30T00:00:00Z").to_pydatetime(),
        min_days=5,
        max_lag_days=1,
    )

    assert summary["openai"]["model_count"] == 1


def test_provider_activity_pipeline_blocks_bad_extraction_before_storage(tmp_path: Path) -> None:
    pipeline = ProviderActivityPipeline(tmp_path, provider_slugs={"openai": "OpenAI"})
    bad_record = DatasetRecord(
        dataset_id="provider_daily_activity",
        source_url="fixture://provider/openai",
        source_run_id="run-1",
        scraped_at="2026-06-30T00:00:00Z",
        entity_id="openai",
        entity_name="OpenAI",
        usage_date="2026-06-01",
        model_permaslug="openai/gpt-5.5",
        total_tokens=1.0,
    )

    with pytest.raises(ExtractionError):
        pipeline._filter_for_mode("provider-activity-daily-update", {"provider_daily_activity": [bad_record]})

    assert not (tmp_path / "data" / "normalized" / "openrouter" / "provider_daily_activity.parquet").exists()


def test_provider_config_tracks_tencent() -> None:
    assert PROVIDER_SLUGS["tencent"] == "Tencent"


def test_provider_config_tracks_stepfun() -> None:
    assert PROVIDER_SLUGS["stepfun"] == "StepFun"


def test_provider_config_tracks_meta() -> None:
    assert PROVIDER_SLUGS["meta"] == "Meta"


def test_provider_activity_source_emits_tencent_rows() -> None:
    payload = [
        "$",
        "$L53",
        None,
        {
            "data": [
                {"x": "2026-05-01 00:00:00", "ys": {"tencent/hy3-preview:free": 123456}},
                {"x": "2026-05-02 00:00:00", "ys": {"tencent/hy3-preview:free": 234567}},
                {"x": "2026-05-03 00:00:00", "ys": {"tencent/hy3-preview:free": 345678}},
                {"x": "2026-05-04 00:00:00", "ys": {"tencent/hy3-preview:free": 456789}},
                {"x": "2026-05-05 00:00:00", "ys": {"tencent/hy3-preview:free": 567890}},
            ],
        },
    ]
    html = f"<html><body>{_make_next_f_script('44', payload)}</body></html>"
    source = ProviderActivitySource()
    context = RunContext(run_id="provider-activity-test", scraped_at=pd.Timestamp("2026-05-02T00:00:00Z").to_pydatetime())

    extracted = source.extract(
        [Snapshot(name="provider_tencent", source_url="fixture://tencent", body=html)],
        context,
    )

    record = extracted["provider_daily_activity"][0]
    assert record.entity_id == "tencent"
    assert record.entity_name == "Tencent"
    assert record.model_permaslug == "tencent/hy3-preview:free"
    assert record.total_tokens == 123456.0


def test_provider_activity_source_emits_stepfun_rows() -> None:
    payload = [
        "$",
        "$L53",
        None,
        {
            "data": [
                {"x": "2026-05-01 00:00:00", "ys": {"stepfun/step-3.5-flash": 123456}},
                {"x": "2026-05-02 00:00:00", "ys": {"stepfun/step-3.5-flash": 234567}},
                {"x": "2026-05-03 00:00:00", "ys": {"stepfun/step-3.5-flash": 345678}},
                {"x": "2026-05-04 00:00:00", "ys": {"stepfun/step-3.5-flash": 456789}},
                {"x": "2026-05-05 00:00:00", "ys": {"stepfun/step-3.5-flash": 567890}},
            ],
        },
    ]
    html = f"<html><body>{_make_next_f_script('44', payload)}</body></html>"
    source = ProviderActivitySource()
    context = RunContext(run_id="provider-activity-test", scraped_at=pd.Timestamp("2026-05-02T00:00:00Z").to_pydatetime())

    extracted = source.extract(
        [Snapshot(name="provider_stepfun", source_url="fixture://stepfun", body=html)],
        context,
    )

    record = extracted["provider_daily_activity"][0]
    assert record.entity_id == "stepfun"
    assert record.entity_name == "StepFun"
    assert record.model_permaslug == "stepfun/step-3.5-flash"
    assert record.total_tokens == 123456.0


def test_activity_pipeline_discovers_major_provider_slugs_from_catalog(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "data" / "normalized" / "compute_availability"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "model_id": "anthropic/claude-opus-4.7",
                "canonical_slug": "anthropic/claude-opus-4.7",
                "provider_prefix": "anthropic",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
            {
                "model_id": "x-ai/grok-4-fast",
                "canonical_slug": "x-ai/grok-4-fast",
                "provider_prefix": "x-ai",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
            {
                "model_id": "tencent/hy3-preview:free",
                "canonical_slug": "tencent/hy3-preview:free",
                "provider_prefix": "tencent",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
            {
                "model_id": "stepfun/step-3.5-flash",
                "canonical_slug": "stepfun/step-3.5-flash",
                "provider_prefix": "stepfun",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
            {
                "model_id": "nvidia/llama-3.1-nemotron",
                "canonical_slug": "nvidia/llama-3.1-nemotron",
                "provider_prefix": "nvidia",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
        ]
    ).to_csv(catalog_dir / "raw_openrouter_models.csv", index=False)

    pipeline = ActivityPipeline(tmp_path)
    slugs = pipeline._discover_catalog_slugs()

    assert slugs == [
        "anthropic/claude-opus-4.7",
        "x-ai/grok-4-fast",
        "tencent/hy3-preview:free",
        "stepfun/step-3.5-flash",
    ]


def test_activity_pipeline_discovers_major_provider_slugs_from_parquet_catalog(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "data" / "normalized" / "compute_availability"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "model_id": "anthropic/claude-opus-4.7",
                "canonical_slug": "anthropic/claude-opus-4.7",
                "provider_prefix": "anthropic",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
            {
                "model_id": "nvidia/llama-3.1-nemotron",
                "canonical_slug": "nvidia/llama-3.1-nemotron",
                "provider_prefix": "nvidia",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
        ]
    ).to_parquet(catalog_dir / "raw_openrouter_models.parquet", index=False)

    pipeline = ActivityPipeline(tmp_path)
    slugs = pipeline._discover_catalog_slugs()

    assert slugs == ["anthropic/claude-opus-4.7"]


def test_activity_pipeline_unions_recent_partial_catalog_snapshots(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "data" / "normalized" / "compute_availability"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "model_id": "moonshotai/kimi-k2.6",
                "canonical_slug": "moonshotai/kimi-k2.6-20260420",
                "provider_prefix": "moonshotai",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
            {
                "model_id": "deepseek/deepseek-v4-pro",
                "canonical_slug": "deepseek/deepseek-v4-pro-20260423",
                "provider_prefix": "deepseek",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
            {
                "model_id": "openai/gpt-5.5",
                "canonical_slug": "openai/gpt-5.5-20260423",
                "provider_prefix": "openai",
                "snapshot_ts": "2026-04-25T00:00:00Z",
            },
        ]
    ).to_csv(catalog_dir / "raw_openrouter_models.csv", index=False)

    pipeline = ActivityPipeline(tmp_path)
    slugs = pipeline._discover_catalog_slugs()

    assert slugs == [
        "moonshotai/kimi-k2.6-20260420",
        "deepseek/deepseek-v4-pro-20260423",
        "openai/gpt-5.5-20260423",
    ]


def test_activity_pipeline_prefers_live_catalog_and_keeps_recent_local_releases(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "data" / "normalized" / "compute_availability"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "model_id": "moonshotai/kimi-k2.6",
                "canonical_slug": "moonshotai/kimi-k2.6-20260420",
                "provider_prefix": "moonshotai",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
            {
                "model_id": "deepseek/deepseek-v4-flash",
                "canonical_slug": "deepseek/deepseek-v4-flash-20260423",
                "provider_prefix": "deepseek",
                "snapshot_ts": "2026-04-24T00:00:00Z",
            },
        ]
    ).to_csv(catalog_dir / "raw_openrouter_models.csv", index=False)

    pipeline = ActivityPipeline(tmp_path)
    pipeline.source.fetch_catalog_slugs = lambda limit=0: [
        "openai/gpt-5.5-20260423",
        "tencent/hy3-preview:free",
        "nvidia/not-allowed",
    ]

    slugs = pipeline._discover_activity_slugs()

    assert slugs == [
        "openai/gpt-5.5-20260423",
        "tencent/hy3-preview:free",
        "moonshotai/kimi-k2.6-20260420",
        "deepseek/deepseek-v4-flash-20260423",
    ]


def test_activity_pipeline_prioritizes_recent_high_traffic_models_when_limited(tmp_path: Path) -> None:
    activity_dir = tmp_path / "data" / "normalized" / "openrouter"
    activity_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([
        {"usage_date": "2026-07-15", "model_permaslug": "openai/quiet", "total_tokens": 10},
        {"usage_date": "2026-07-15", "model_permaslug": "deepseek/busy", "total_tokens": 1_000},
        {"usage_date": "2026-07-15", "model_permaslug": "nvidia/not-tracked", "total_tokens": 9_000},
    ]).to_parquet(activity_dir / "provider_daily_activity.parquet", index=False)

    pipeline = ActivityPipeline(tmp_path)
    pipeline.source.fetch_catalog_slugs = lambda limit=0: ["anthropic/new-model"]

    assert pipeline._discover_activity_slugs(limit=2) == ["deepseek/busy", "openai/quiet"]


def test_activity_pipeline_keeps_newly_released_catalog_models_in_capped_scrape(tmp_path: Path) -> None:
    pipeline = ActivityPipeline(tmp_path)
    pipeline.source.fetch_catalog_slugs = lambda limit=0: [
        "meta/muse-spark-1.1-20260709",
        "openai/gpt-5.6-luna-20260709",
        "anthropic/older-model",
    ]

    assert pipeline._discover_activity_slugs(limit=2) == [
        "meta/muse-spark-1.1-20260709",
        "openai/gpt-5.6-luna-20260709",
    ]
