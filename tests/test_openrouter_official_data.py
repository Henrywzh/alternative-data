from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from openrouter_official_data.extract import extract_snapshots
from openrouter_official_data.quality import build_legacy_reconciliation, validate_dataset
from openrouter_official_data.source import OpenRouterOfficialSource, Snapshot
from openrouter_official_data.storage import OfficialStorage


def _snapshot(name: str, payload: dict, **query) -> Snapshot:
    return Snapshot(name=name, source_url=f"https://openrouter.ai/api/v1/{name}", body=json.dumps(payload), query=query)


def test_extracts_official_datasets_without_coercing_their_grains() -> None:
    snapshots = [
        _snapshot(
            "rankings_daily",
            {
                "data": [
                    {"date": "2026-07-17", "model_permaslug": "openai/gpt-5.6", "total_tokens": "1000"},
                    {"date": "2026-07-17", "model_permaslug": "other", "total_tokens": "250"},
                ],
                "meta": {"as_of": "2026-07-18T02:00:00Z", "start_date": "2026-07-17", "end_date": "2026-07-17", "version": "v1"},
            },
            period="day",
        ),
        _snapshot(
            "task_classifications",
            {
                "data": {
                    "as_of": "2026-07-17",
                    "window_days": 7,
                    "classifications": [
                        {
                            "tag": "code:general_impl",
                            "display_name": "Code Generation",
                            "macro_category": "code",
                            "usage_share": 0.4,
                            "token_share": 0.5,
                            "category_usage_share": 0.8,
                            "category_token_share": 0.9,
                            "models": [{"id": "openai/gpt-5.6", "tag_usage_share": 0.6, "tag_token_share": 0.7}],
                        }
                    ],
                    "macro_categories": [{"key": "code", "label": "Code", "usage_share": 0.5, "token_share": 0.6}],
                }
            },
            window="7d",
        ),
        _snapshot(
            "app_rankings_popular_0",
            {
                "data": [{"app_id": 1, "app_name": "Example", "rank": 1, "total_requests": 12, "total_tokens": "345"}],
                "meta": {"as_of": "2026-07-18T02:00:00Z", "start_date": "2026-06-18", "end_date": "2026-07-17", "version": "v1"},
            },
            sort="popular",
            limit=100,
            offset=0,
        ),
    ]

    result = extract_snapshots(snapshots, run_id="run-1", scraped_at="2026-07-18T03:00:00Z")

    ranking = result["official_model_rankings_daily"]
    assert len(ranking) == 2
    assert ranking[0]["rank"] == 1
    assert ranking[1]["is_other"] is True
    assert ranking[1]["rank"] is None
    assert ranking[0]["is_sampled"] is False

    classification = result["official_task_classifications"][0]
    assert classification["usage_share"] == 0.4
    assert classification["is_sampled"] is True
    assert result["official_task_models"][0]["tag_token_share"] == 0.7
    assert result["official_task_macro_categories"][0]["macro_category"] == "code"

    app = result["official_app_rankings"][0]
    assert app["ranking_type"] == "popular"
    assert app["total_requests"] == 12


def test_official_storage_is_additive_and_keeps_legacy_files_untouched(tmp_path: Path) -> None:
    legacy_root = tmp_path / "data" / "normalized" / "openrouter"
    legacy_root.mkdir(parents=True)
    legacy_path = legacy_root / "top_models.parquet"
    pd.DataFrame([{"week_start_date": "2026-07-06", "entity_id": "legacy", "metric_value": 1}]).to_parquet(legacy_path, index=False)
    before = legacy_path.read_bytes()

    storage = OfficialStorage(tmp_path)
    rows = [
        {
            "usage_date": "2026-07-17",
            "model_permaslug": "openai/gpt-5.6",
            "total_tokens": 1000.0,
            "rank": 1,
            "is_other": False,
            "period": "day",
            "modality": None,
            "context_bucket": None,
            "category": None,
            "language_type": None,
        }
    ]
    first = storage.upsert("official_model_rankings_daily", rows)
    second = storage.upsert("official_model_rankings_daily", rows)

    assert len(first) == 1
    assert len(second) == 1
    assert legacy_path.read_bytes() == before
    assert (tmp_path / "data" / "normalized" / "openrouter_official" / "official_model_rankings_daily.parquet").exists()


def test_official_storage_replaces_revised_ranking_partition(tmp_path: Path) -> None:
    storage = OfficialStorage(tmp_path)

    def ranking_rows(start: int) -> list[dict]:
        rows = [
            {
                "usage_date": "2026-07-17",
                "model_permaslug": f"provider/model-{index}",
                "total_tokens": float(10_000 - index),
                "rank": index - start + 1,
                "is_other": False,
                "period": "day",
                "modality": None,
                "context_bucket": None,
                "category": None,
                "language_type": None,
            }
            for index in range(start, start + 50)
        ]
        rows.append(
            {
                "usage_date": "2026-07-17",
                "model_permaslug": "other",
                "total_tokens": 1_000.0,
                "rank": None,
                "is_other": True,
                "period": "day",
                "modality": None,
                "context_bucket": None,
                "category": None,
                "language_type": None,
            }
        )
        return rows

    storage.upsert("official_model_rankings_daily", ranking_rows(0))
    revised = storage.upsert("official_model_rankings_daily", ranking_rows(1))

    assert len(revised) == 51
    assert "provider/model-0" not in set(revised["model_permaslug"])
    assert "provider/model-50" in set(revised["model_permaslug"])
    assert not revised[revised["rank"].notna()]["rank"].duplicated().any()


def test_quality_rejects_duplicates_negative_counts_and_invalid_shares() -> None:
    duplicate = pd.DataFrame(
        [
            {"usage_date": "2026-07-17", "model_permaslug": "a/model", "period": "day", "modality": None, "context_bucket": None, "category": None, "language_type": None, "total_tokens": 1, "is_other": False},
            {"usage_date": "2026-07-17", "model_permaslug": "a/model", "period": "day", "modality": None, "context_bucket": None, "category": None, "language_type": None, "total_tokens": 2, "is_other": False},
        ]
    )
    try:
        validate_dataset("official_model_rankings_daily", duplicate)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate keys should fail validation")

    invalid_share = pd.DataFrame(
        [{"snapshot_date": "2026-07-17", "window_days": 7, "tag": "code:test", "usage_share": 1.2}]
    )
    try:
        validate_dataset("official_task_classifications", invalid_share)
    except ValueError as exc:
        assert "outside [0, 1]" in str(exc)
    else:
        raise AssertionError("invalid shares should fail validation")


def test_reconciliation_reports_coverage_without_replacing_legacy_totals(tmp_path: Path) -> None:
    legacy_root = tmp_path / "data" / "normalized" / "openrouter"
    legacy_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {"usage_date": "2026-07-17", "model_permaslug": "openai/gpt-5.6", "category_slug": "all", "total_tokens": 900},
            {"usage_date": "2026-07-17", "model_permaslug": "other/model", "category_slug": "programming", "total_tokens": 20},
        ]
    ).to_parquet(legacy_root / "openrouter_model_activity.parquet", index=False)
    pd.DataFrame(
        [{"usage_date": "2026-07-17", "model_permaslug": "openai/gpt-5.6", "total_tokens": 950}]
    ).to_parquet(legacy_root / "provider_daily_activity.parquet", index=False)

    official = pd.DataFrame(
        [
            {"usage_date": "2026-07-17", "model_permaslug": "openai/gpt-5.6", "total_tokens": 1000, "is_other": False},
            {"usage_date": "2026-07-17", "model_permaslug": "anthropic/claude", "total_tokens": 500, "is_other": False},
            {"usage_date": "2026-07-17", "model_permaslug": "other", "total_tokens": 250, "is_other": True},
        ]
    )
    result = build_legacy_reconciliation(tmp_path, official)

    row = result.iloc[0]
    assert row["official_total_tokens"] == 1750
    assert row["official_named_tokens"] == 1500
    assert row["legacy_activity_tokens_on_official_models"] == 900
    assert row["activity_official_token_coverage"] == 1000 / 1500


def test_optional_endpoint_failure_does_not_drop_core_rankings(monkeypatch) -> None:
    source = OpenRouterOfficialSource("test-key")

    def fake_fetch(name, path, **params):
        if name == "benchmarks":
            import requests

            raise requests.HTTPError("temporary benchmark outage")
        return Snapshot(name=name, source_url=f"fixture://{name}", body='{"data": []}', query=params)

    monkeypatch.setattr(source, "_fetch", fake_fetch)

    snapshots = source.fetch_daily_snapshots(target_date=date(2026, 7, 17))

    assert any(snapshot.name == "rankings_daily" for snapshot in snapshots)
    assert not any(snapshot.name == "benchmarks" for snapshot in snapshots)
    assert source.last_failures[0]["name"] == "benchmarks"
    assert len(snapshots) == 7


def test_pipeline_rejects_empty_successful_core_rankings_payload(tmp_path: Path, monkeypatch) -> None:
    from openrouter_official_data.pipeline import OpenRouterOfficialPipeline

    pipeline = OpenRouterOfficialPipeline(tmp_path, "test-key")
    monkeypatch.setattr(
        pipeline.source,
        "fetch_daily_snapshots",
        lambda **_: [
            _snapshot(
                "rankings_daily",
                {"data": [], "meta": {"start_date": "2026-07-17", "end_date": "2026-07-17"}},
                period="day",
                start_date="2026-07-17",
                end_date="2026-07-17",
            )
        ],
    )

    try:
        pipeline.run_daily_update(target_date=date(2026, 7, 17))
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("empty core rankings must fail the run")


def test_pipeline_isolates_malformed_optional_payload(tmp_path: Path, monkeypatch) -> None:
    from openrouter_official_data.pipeline import OpenRouterOfficialPipeline

    ranking_data = [
        {"date": "2026-07-17", "model_permaslug": f"provider/model-{index}", "total_tokens": 1000 - index}
        for index in range(50)
    ]
    ranking_data.append({"date": "2026-07-17", "model_permaslug": "other", "total_tokens": 100})
    pipeline = OpenRouterOfficialPipeline(tmp_path, "test-key")
    monkeypatch.setattr(
        pipeline.source,
        "fetch_daily_snapshots",
        lambda **_: [
            _snapshot(
                "rankings_daily",
                {"data": ranking_data, "meta": {"start_date": "2026-07-17", "end_date": "2026-07-17"}},
                period="day",
                start_date="2026-07-17",
                end_date="2026-07-17",
            ),
            Snapshot(
                name="benchmarks",
                source_url="https://openrouter.ai/api/v1/benchmarks",
                body="not-json",
                query={},
            ),
        ],
    )

    result = pipeline.run_daily_update(target_date=date(2026, 7, 17))

    assert result["official_model_rankings_daily"] == 51
    health = pipeline.storage.load("official_source_health")
    benchmark_health = health[health["dataset_id"] == "official_benchmarks"].iloc[-1]
    assert benchmark_health["status"] == "warning"
    assert "JSONDecodeError" in benchmark_health["detail"]
