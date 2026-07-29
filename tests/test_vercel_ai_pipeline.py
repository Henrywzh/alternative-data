from __future__ import annotations

import json
from pathlib import Path

import pytest

from vercel_ai_data.models import DatasetRecord, RunContext
from vercel_ai_data.pipeline import ValidationError, VercelPipeline
from vercel_ai_data.sources.leaderboard import VercelLeaderboardSource
from vercel_ai_data.sources.models_catalog import VercelModelsCatalogSource
from vercel_ai_data.storage import StorageManager

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _context() -> RunContext:
    from datetime import datetime, timezone

    return RunContext(run_id="run-test", scraped_at=datetime(2026, 5, 9, tzinfo=timezone.utc))


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #

def test_leaderboard_extract_maps_all_fields() -> None:
    from vercel_ai_data.models import Snapshot

    source = VercelLeaderboardSource()
    snapshots = [
        Snapshot("vercel_model_leaderboard", "fixture://models", _fixture("vercel_model_leaderboard.json")),
        Snapshot("vercel_lab_leaderboard", "fixture://labs", _fixture("vercel_lab_leaderboard.json")),
    ]

    extracted = source.extract(snapshots, _context())

    models = extracted["vercel_model_leaderboard"]
    assert len(models) == 12
    first = models[0]
    assert first.date == "2026-05-08"
    assert first.group == "model"
    assert first.name == "Gemini 3 Flash"
    assert first.metric == "tokens"
    assert first.share_percent == 16.4065
    assert first.rank == 1
    assert len(extracted["vercel_lab_leaderboard"]) == 12


def test_catalog_extract_parses_pricing_and_tags() -> None:
    from vercel_ai_data.models import Snapshot

    source = VercelModelsCatalogSource()
    snapshots = [Snapshot("vercel_models", "fixture://catalog", _fixture("vercel_models.json"))]

    records = source.extract(snapshots, _context())["vercel_models"]

    assert len(records) == 5
    claude = next(r for r in records if r.model_id == "anthropic/claude-sonnet-4.6")
    assert claude.pricing_input == "0.000003"
    assert claude.pricing_cache_read == "0.0000003"
    assert claude.tags == "reasoning"
    assert json.loads(claude.raw_pricing_json)["output"] == "0.000015"


# --------------------------------------------------------------------------- #
# Validation gates (finding #1)
# --------------------------------------------------------------------------- #

def test_validate_passes_on_healthy_fixtures(tmp_path: Path) -> None:
    pipeline = VercelPipeline(tmp_path)
    report = pipeline.validate(
        model_leaderboard_json=_fixture("vercel_model_leaderboard.json"),
        lab_leaderboard_json=_fixture("vercel_lab_leaderboard.json"),
        models_json=_fixture("vercel_models.json"),
    )
    assert report["vercel_model_leaderboard"]["share_percent_non_null_ratio"] == 1.0
    assert report["vercel_models"]["priced_models"] == 5


def test_validate_fails_when_share_percent_field_renamed(tmp_path: Path) -> None:
    """Simulate an upstream schema change: the share_percent key is renamed,
    so every row extracts a null share. The gate must reject it rather than let
    the daily upsert overwrite committed history with nulls."""
    payload = json.loads(_fixture("vercel_model_leaderboard.json"))
    for row in payload["rows"]:
        row["sharePercent"] = row.pop("share_percent")
    broken = json.dumps(payload)

    pipeline = VercelPipeline(tmp_path)
    with pytest.raises(ValidationError, match="share_percent"):
        pipeline.validate(
            model_leaderboard_json=broken,
            lab_leaderboard_json=_fixture("vercel_lab_leaderboard.json"),
            models_json=_fixture("vercel_models.json"),
        )


def test_validate_fails_on_empty_fetch(tmp_path: Path) -> None:
    pipeline = VercelPipeline(tmp_path)
    with pytest.raises(ValidationError):
        pipeline.validate(
            model_leaderboard_json='{"rows": []}',
            lab_leaderboard_json='{"rows": []}',
            models_json='{"data": []}',
        )


def test_daily_update_persists_ranks_and_audits_new_entities(tmp_path: Path, monkeypatch) -> None:
    from vercel_ai_data.models import Snapshot

    pipeline = VercelPipeline(tmp_path)
    leaderboard_snapshots = [
        Snapshot("vercel_model_leaderboard", "fixture://models", _fixture("vercel_model_leaderboard.json")),
        Snapshot("vercel_lab_leaderboard", "fixture://labs", _fixture("vercel_lab_leaderboard.json")),
    ]
    catalog_snapshots = [
        Snapshot("vercel_models", "fixture://catalog", _fixture("vercel_models.json")),
    ]
    monkeypatch.setattr(pipeline.leaderboard_source, "fetch_snapshots", lambda: leaderboard_snapshots)
    monkeypatch.setattr(pipeline.catalog_source, "fetch_snapshots", lambda: catalog_snapshots)

    result = pipeline.run_daily_update()

    stored = pipeline.storage.load_dataset("vercel_model_leaderboard")
    assert stored["rank"].notna().all()
    manifest = json.loads((result.raw_run_dir / "manifest.json").read_text(encoding="utf-8"))
    model_entry = next(row for row in manifest["datasets"] if row["dataset_id"] == "vercel_model_leaderboard")
    assert "Gemini 3 Flash" in model_entry["new_entities"]


# --------------------------------------------------------------------------- #
# Storage merge semantics
# --------------------------------------------------------------------------- #

def _leaderboard_record(date: str, name: str, metric: str, share: float | None) -> DatasetRecord:
    return DatasetRecord(
        dataset_id="vercel_model_leaderboard",
        source_url="fixture://models",
        source_run_id="run-1",
        scraped_at="2026-05-08T00:00:00Z",
        date=date,
        group="model",
        name=name,
        metric=metric,
        modality="all",
        share_percent=share,
    )


def test_history_is_preserved_across_upserts(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    storage.upsert_dataset("vercel_model_leaderboard", [
        _leaderboard_record("2026-05-08", "Gemini 3 Flash", "tokens", 16.4),
    ])
    merged = storage.upsert_dataset("vercel_model_leaderboard", [
        _leaderboard_record("2026-05-09", "Gemini 3 Flash", "tokens", 17.0),
    ])
    dates = set(merged["date"])
    assert dates == {"2026-05-08", "2026-05-09"}


def test_leaderboard_refresh_prunes_stale_rows_within_fetched_partition(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    storage.upsert_dataset("vercel_model_leaderboard", [
        _leaderboard_record("2026-05-08", "Established", "tokens", 20.0),
        _leaderboard_record("2026-05-08", "Stale", "tokens", 10.0),
        _leaderboard_record("2026-05-09", "Prior history", "tokens", 15.0),
    ])

    merged = storage.upsert_dataset("vercel_model_leaderboard", [
        _leaderboard_record("2026-05-08", "Established", "tokens", 25.0),
        _leaderboard_record("2026-05-08", "New entrant", "tokens", 5.0),
    ])

    same_day = merged[merged["date"] == "2026-05-08"]
    assert set(same_day["name"]) == {"Established", "New entrant"}
    assert set(merged[merged["date"] == "2026-05-09"]["name"]) == {"Prior history"}


def test_new_ranked_models_are_added_without_losing_prior_models(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    storage.upsert_dataset("vercel_model_leaderboard", [
        _leaderboard_record("2026-05-08", "Established", "tokens", 20.0),
    ])
    merged = storage.upsert_dataset("vercel_model_leaderboard", [
        _leaderboard_record("2026-05-09", "New entrant", "tokens", 25.0),
    ])

    assert set(merged["name"]) == {"Established", "New entrant"}
    assert set(merged["date"]) == {"2026-05-08", "2026-05-09"}


def test_unchanged_rows_do_not_churn_provenance(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    storage.upsert_dataset("vercel_model_leaderboard", [
        _leaderboard_record("2026-05-08", "Gemini 3 Flash", "tokens", 16.4),
    ])
    parquet = tmp_path / "data" / "normalized" / "vercel_ai" / "vercel_model_leaderboard.parquet"
    first_bytes = parquet.read_bytes()

    # Re-run with the same substantive payload but a new run id / scraped_at.
    rerun = _leaderboard_record("2026-05-08", "Gemini 3 Flash", "tokens", 16.4)
    object.__setattr__(rerun, "source_run_id", "run-2")
    object.__setattr__(rerun, "scraped_at", "2026-05-09T00:00:00Z")
    storage.upsert_dataset("vercel_model_leaderboard", [rerun])

    assert parquet.read_bytes() == first_bytes, "unchanged fetch should not rewrite provenance"


def test_catalog_prunes_delisted_models(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)

    def _model(model_id: str, name: str) -> DatasetRecord:
        return DatasetRecord(
            dataset_id="vercel_models",
            source_url="fixture://catalog",
            source_run_id="run-1",
            scraped_at="2026-05-08T00:00:00Z",
            model_id=model_id,
            name=name,
            owned_by="acme",
        )

    storage.upsert_dataset("vercel_models", [_model("a/one", "One"), _model("a/two", "Two")])
    merged = storage.upsert_dataset("vercel_models", [_model("a/one", "One")])

    assert set(merged["model_id"]) == {"a/one"}
