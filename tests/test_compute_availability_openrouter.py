from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from compute_availability_data.models import DatasetRecord, Snapshot
from compute_availability_data.sources.openrouter import OpenRouterSource
from compute_availability_data.storage import StorageManager


def test_openrouter_extract_persists_canonical_slug_and_provider_prefix() -> None:
    source = OpenRouterSource()
    snapshot = Snapshot(
        name="openrouter_models",
        source_url=source.URL,
        body=json.dumps(
            {
                "data": [
                    {
                        "id": "qwen/qwen3.5-flash-02-23",
                        "canonical_slug": "qwen/qwen3.5-flash-20260224",
                        "name": "Qwen 3.5 Flash",
                        "created": 1710000000,
                        "context_length": 1_000_000,
                        "architecture": {"modality": "text"},
                        "pricing": {"prompt": "0.000000065", "completion": "0.00000026"},
                        "top_provider": {"id": "alibaba"},
                    }
                ]
            }
        ),
    )

    records = source.extract(snapshot, run_id="run-1", scraped_at="2026-04-20T00:00:00Z")

    assert len(records) == 1
    record = records[0]
    assert record.model_id == "qwen/qwen3.5-flash-02-23"
    assert record.canonical_slug == "qwen/qwen3.5-flash-20260224"
    assert record.provider_prefix == "qwen"


def test_openrouter_extract_preserves_rich_official_catalog_fields() -> None:
    source = OpenRouterSource()
    snapshot = Snapshot(
        name="openrouter_models",
        source_url=source.URL,
        body=json.dumps(
            {
                "data": [
                    {
                        "id": "example/multimodal-model",
                        "canonical_slug": "example/multimodal-model-20260718",
                        "name": "Multimodal Model",
                        "description": "A rich model record.",
                        "hugging_face_id": "example/model",
                        "created": 1710000000,
                        "context_length": 1_000_000,
                        "architecture": {
                            "modality": "text+image->text",
                            "input_modalities": ["text", "image"],
                            "output_modalities": ["text"],
                            "tokenizer": "Example",
                            "instruct_type": "chatml",
                        },
                        "supported_parameters": ["temperature", "tools"],
                        "default_parameters": {"temperature": 0.2},
                        "per_request_limits": {"prompt_tokens": "1000000"},
                        "pricing": {
                            "prompt": "0.000001",
                            "completion": "0.000004",
                            "input_cache_read": "0.0000001",
                            "request": "0",
                        },
                        "top_provider": {
                            "context_length": 1_000_000,
                            "max_completion_tokens": 65_536,
                            "is_moderated": False,
                        },
                        "expiration_date": "2027-01-01",
                        "knowledge_cutoff": "2026-06",
                        "benchmarks": {"quality": 0.9},
                        "links": {"documentation": "https://example.com"},
                        "reasoning": {"supported": True},
                        "supported_voices": ["alloy"],
                    }
                ]
            }
        ),
    )

    record = source.extract(snapshot, run_id="run-1", scraped_at="2026-07-18T00:00:00Z")[0]

    assert record.description == "A rich model record."
    assert record.architecture_modality == "text+image->text"
    assert json.loads(record.input_modalities_json or "[]") == ["text", "image"]
    assert json.loads(record.supported_parameters_json or "[]") == ["temperature", "tools"]
    assert record.pricing_request == 0.0
    assert record.pricing_input_cache_read == 0.0000001
    assert record.top_provider_context_length == 1_000_000
    assert record.top_provider_is_moderated is False
    assert record.knowledge_cutoff == "2026-06"
    assert json.loads(record.benchmarks_json or "{}") == {"quality": 0.9}


def test_openrouter_fetch_requests_all_output_modalities(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        text = '{"data": []}'

        @staticmethod
        def raise_for_status() -> None:
            return None

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr("compute_availability_data.sources.openrouter.requests.get", fake_get)

    snapshot = OpenRouterSource().fetch_snapshot()

    assert snapshot.body == '{"data": []}'
    assert captured["params"] == {"output_modalities": "all"}
    assert captured["headers"]["Authorization"] == "Bearer test-key"


def test_storage_round_trips_openrouter_identity_columns(tmp_path: Path) -> None:
    source = OpenRouterSource()
    snapshot = Snapshot(
        name="openrouter_models",
        source_url=source.URL,
        body=json.dumps(
            {
                "data": [
                    {
                        "id": "moonshotai/kimi-k2.5",
                        "canonical_slug": "moonshotai/kimi-k2.5-0127",
                        "name": "Kimi K2.5",
                        "created": 1710000000,
                        "context_length": 262144,
                        "architecture": {"modality": "text"},
                        "pricing": {"prompt": "0.0000006", "completion": "0.000003"},
                        "top_provider": {"id": "moonshot"},
                    }
                ]
            }
        ),
    )
    records = source.extract(snapshot, run_id="run-1", scraped_at="2026-04-20T00:00:00Z")

    storage = StorageManager(tmp_path)
    storage.upsert_dataset("raw_openrouter_models", records)
    loaded = storage.load_dataset("raw_openrouter_models")

    row = loaded.iloc[0]
    assert row["model_id"] == "moonshotai/kimi-k2.5"
    assert row["canonical_slug"] == "moonshotai/kimi-k2.5-0127"
    assert row["provider_prefix"] == "moonshotai"


def test_storage_skips_unchanged_openrouter_model_snapshots(tmp_path: Path) -> None:
    source = OpenRouterSource()
    storage = StorageManager(tmp_path)
    body = json.dumps(
        {
            "data": [
                {
                    "id": "moonshotai/kimi-k2.5",
                    "canonical_slug": "moonshotai/kimi-k2.5-0127",
                    "name": "Kimi K2.5",
                    "created": 1710000000,
                    "context_length": 262144,
                    "architecture": {"modality": "text"},
                    "pricing": {"prompt": "0.0000006", "completion": "0.000003"},
                    "top_provider": {"id": "moonshot"},
                }
            ]
        }
    )

    first_records = source.extract(
        Snapshot(name="openrouter_models", source_url=source.URL, body=body),
        run_id="run-1",
        scraped_at="2026-04-20T00:00:00Z",
    )
    second_records = source.extract(
        Snapshot(name="openrouter_models", source_url=source.URL, body=body),
        run_id="run-2",
        scraped_at="2026-04-21T00:00:00Z",
    )

    first = storage.upsert_dataset("raw_openrouter_models", first_records)
    second = storage.upsert_dataset("raw_openrouter_models", second_records)

    assert len(first) == 1
    assert len(second) == 1
    assert second.iloc[0]["snapshot_ts"] == "2026-04-20T00:00:00Z"


def test_storage_loads_existing_openrouter_catalog_from_parquet_when_csv_absent(tmp_path: Path) -> None:
    source = OpenRouterSource()
    storage = StorageManager(tmp_path)
    body = json.dumps(
        {
            "data": [
                {
                    "id": "anthropic/claude-opus-4.7",
                    "canonical_slug": "anthropic/claude-4.7-opus-20260416",
                    "name": "Claude Opus 4.7",
                    "created": 1710000000,
                    "context_length": 1_000_000,
                    "architecture": {"modality": "text"},
                    "pricing": {"prompt": "0.000005", "completion": "0.000025"},
                    "top_provider": {"id": "anthropic"},
                }
            ]
        }
    )
    first_records = source.extract(
        Snapshot(name="openrouter_models", source_url=source.URL, body=body),
        run_id="run-1",
        scraped_at="2026-04-20T00:00:00Z",
    )
    second_records = source.extract(
        Snapshot(name="openrouter_models", source_url=source.URL, body=body),
        run_id="run-2",
        scraped_at="2026-04-21T00:00:00Z",
    )

    storage.upsert_dataset("raw_openrouter_models", first_records)
    csv_path = tmp_path / "data" / "normalized" / "compute_availability" / "raw_openrouter_models.csv"
    csv_path.unlink()
    second = storage.upsert_dataset("raw_openrouter_models", second_records)

    assert len(second) == 1
    assert second.iloc[0]["snapshot_ts"] == "2026-04-20T00:00:00Z"


def test_storage_appends_openrouter_model_when_tracked_fields_change(tmp_path: Path) -> None:
    source = OpenRouterSource()
    storage = StorageManager(tmp_path)

    original = json.dumps(
        {
            "data": [
                {
                    "id": "qwen/qwen3.5-flash-02-23",
                    "canonical_slug": "qwen/qwen3.5-flash-20260224",
                    "name": "Qwen 3.5 Flash",
                    "created": 1710000000,
                    "context_length": 1_000_000,
                    "architecture": {"modality": "text"},
                    "pricing": {"prompt": "0.000000065", "completion": "0.00000026"},
                    "top_provider": {"id": "alibaba"},
                }
            ]
        }
    )
    changed = json.dumps(
        {
            "data": [
                {
                    "id": "qwen/qwen3.5-flash-02-23",
                    "canonical_slug": "qwen/qwen3.5-flash-20260224",
                    "name": "Qwen 3.5 Flash",
                    "created": 1710000000,
                    "context_length": 1_000_000,
                    "architecture": {"modality": "text"},
                    "pricing": {"prompt": "0.00000007", "completion": "0.00000040"},
                    "top_provider": {"id": "alibaba"},
                }
            ]
        }
    )

    original_records = source.extract(
        Snapshot(name="openrouter_models", source_url=source.URL, body=original),
        run_id="run-1",
        scraped_at="2026-04-20T00:00:00Z",
    )
    changed_records = source.extract(
        Snapshot(name="openrouter_models", source_url=source.URL, body=changed),
        run_id="run-2",
        scraped_at="2026-04-21T00:00:00Z",
    )

    first = storage.upsert_dataset("raw_openrouter_models", original_records)
    second = storage.upsert_dataset("raw_openrouter_models", changed_records)

    assert len(first) == 1
    assert len(second) == 2
    latest = second.sort_values("snapshot_ts").iloc[-1]
    assert latest["snapshot_ts"] == "2026-04-21T00:00:00Z"
    assert latest["pricing_prompt"] == 0.00000007
    assert latest["pricing_completion"] == 0.00000040


def test_current_catalog_rejects_partial_response_and_preserves_previous_file(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    previous = [
        DatasetRecord(
            dataset_id="raw_openrouter_models",
            source_url="fixture://models",
            source_run_id="run-1",
            scraped_at="2026-07-17T00:00:00Z",
            snapshot_ts="2026-07-17T00:00:00Z",
            model_id=f"provider-{index % 20}/model-{index}",
            canonical_slug=f"provider-{index % 20}/model-{index}",
            provider_prefix=f"provider-{index % 20}",
        )
        for index in range(400)
    ]
    storage.upsert_dataset("raw_openrouter_models", previous)
    before = storage.load_current_catalog()

    partial = [
        DatasetRecord(
            dataset_id="raw_openrouter_models",
            source_url="fixture://models",
            source_run_id="run-2",
            scraped_at="2026-07-18T00:00:00Z",
            snapshot_ts="2026-07-18T00:00:00Z",
            model_id="provider-0/model-0",
            canonical_slug="provider-0/model-0",
            provider_prefix="provider-0",
        )
    ]

    try:
        storage.upsert_dataset("raw_openrouter_models", partial)
    except ValueError as exc:
        assert "collapsed" in str(exc)
    else:
        raise AssertionError("partial catalog response must be rejected")

    after = storage.load_current_catalog()
    assert len(after) == len(before) == 400
    assert set(after["model_id"]) == set(before["model_id"])


def _catalog_records(
    run_id: str,
    snapshot_ts: str,
    *,
    count: int = 400,
    non_text_output: int = 0,
) -> list[DatasetRecord]:
    records = []
    for index in range(count):
        modalities = ["image"] if index < non_text_output else ["text"]
        records.append(
            DatasetRecord(
                dataset_id="raw_openrouter_models",
                source_url="fixture://models",
                source_run_id=run_id,
                scraped_at=snapshot_ts,
                snapshot_ts=snapshot_ts,
                model_id=f"provider-{index % 20}/model-{index}",
                canonical_slug=f"provider-{index % 20}/model-{index}",
                provider_prefix=f"provider-{index % 20}",
                output_modalities_json=json.dumps(modalities),
            )
        )
    return records


def test_catalog_size_counts_the_full_response_not_the_change_filtered_rows(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)

    storage.upsert_dataset("raw_openrouter_models", _catalog_records("run-1", "2026-08-17T00:00:00Z"))
    # Identical catalog: every row is change-filtered out of the history, but
    # the catalog is still 400 models. This is the exact failure the sidecar
    # exists to prevent -- counting history rows would report 0 here.
    storage.upsert_dataset("raw_openrouter_models", _catalog_records("run-2", "2026-08-18T00:00:00Z"))

    sizes = storage.load_catalog_size()
    assert list(sizes["snapshot_ts"]) == ["2026-08-17T00:00:00Z", "2026-08-18T00:00:00Z"]
    assert list(sizes["model_count_all"]) == [400, 400]
    assert set(sizes["capture_source"]) == {"live_api"}
    assert list(sizes["provider_count"]) == [20, 20]

    history = storage.load_dataset("raw_openrouter_models")
    assert history["snapshot_ts"].nunique() == 1


def test_catalog_size_separates_text_output_models_from_the_full_catalog(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    storage.upsert_dataset(
        "raw_openrouter_models",
        _catalog_records("run-1", "2026-08-18T00:00:00Z", count=400, non_text_output=60),
    )

    row = storage.load_catalog_size().iloc[0]
    assert row["model_count_all"] == 400
    # The archived captures only ever saw the text-output subset, so that is
    # the basis the two capture sources can be compared on.
    assert row["model_count_text_output"] == 340


def test_catalog_size_records_archived_captures_on_the_text_output_basis(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    archived = pd.DataFrame(
        [record.to_dict() for record in _catalog_records("wayback-20260101000000-abcd1234", "2026-01-01T00:00:00Z", count=220)]
    )

    storage.record_catalog_size(archived, capture_source="wayback_archive")

    row = storage.load_catalog_size().iloc[0]
    assert row["capture_source"] == "wayback_archive"
    assert row["model_count_text_output"] == 220
    # No all-modality figure exists for a capture of the default response.
    assert pd.isna(row["model_count_all"])


def test_catalog_size_is_not_written_when_the_catalog_is_rejected(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    storage.upsert_dataset("raw_openrouter_models", _catalog_records("run-1", "2026-08-17T00:00:00Z"))

    collapsed = _catalog_records("run-2", "2026-08-18T00:00:00Z", count=5)
    try:
        storage.upsert_dataset("raw_openrouter_models", collapsed)
    except ValueError:
        pass
    else:
        raise AssertionError("collapsed catalog response must be rejected")

    sizes = storage.load_catalog_size()
    assert list(sizes["snapshot_ts"]) == ["2026-08-17T00:00:00Z"]
    assert sizes.iloc[0]["model_count_all"] == 400
