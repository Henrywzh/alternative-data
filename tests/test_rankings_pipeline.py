from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from openrouter_data.exceptions import ExtractionError
from openrouter_data.models import RunContext, Snapshot
from openrouter_data.pipeline import RankingsPipeline
from openrouter_data.sources.rankings import RankingsSource


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "rankings_payloads.json"


def _load_payloads() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _make_next_f_script(label: str, payload: list) -> str:
    encoded = json.dumps(f"{label}:{json.dumps(payload, separators=(',', ':'))}")
    return f"<script>self.__next_f.push([1,{encoded}])</script>"


def build_fixture_html(
    *,
    top_models: list[dict] | None = None,
    market_share: list[dict] | None = None,
    categories_programming: list[dict] | None = None,
) -> str:
    payloads = _load_payloads()
    top_models = payloads["top_models"] if top_models is None else top_models
    market_share = payloads["market_share"] if market_share is None else market_share
    categories_programming = payloads["categories_programming"] if categories_programming is None else categories_programming

    top_models_payload = [
        "$",
        "$L53",
        None,
        {
            "rootMargin": "100px",
            "children": [
                "$",
                "$L54",
                None,
                {
                    "data": top_models,
                    "forecast": "forecast-1w",
                    "forecastFromTimestamp": 1700000000000,
                },
            ],
        },
    ]
    market_share_payload = [
        "$",
        "$L53",
        None,
        {
            "children": [
                "$",
                "$L55",
                None,
                {
                    "data": market_share,
                },
            ],
        },
    ]
    categories_payload = [
        "$",
        "$L52",
        None,
        {
            "children": [
                "$",
                "$L58",
                None,
                {
                    "data": categories_programming,
                    "testId": "model-rankings-categories-chart",
                },
            ],
        },
    ]
    return (
        "<html><body>"
        f"{_make_next_f_script('44', top_models_payload)}"
        f"{_make_next_f_script('46', market_share_payload)}"
        f"{_make_next_f_script('4c', categories_payload)}"
        "</body></html>"
    )


def make_snapshots(html: str) -> list[Snapshot]:
    return [
        Snapshot(name="rankings", source_url="fixture://rankings", body=html),
        Snapshot(name="rankings_programming", source_url="fixture://rankings/programming", body=html),
    ]


def _runtime_fallback_charts() -> dict[str, dict]:
    payloads = _load_payloads()
    return {
        "top_models": {"data": payloads["top_models"], "forecast": "forecast-1w"},
        "market_share": {"data": payloads["market_share"]},
        "categories_programming": {
            "data": payloads["categories_programming"],
            "testId": "model-rankings-categories-chart",
        },
    }


def test_parse_fixture_snapshots_for_all_three_datasets() -> None:
    html = build_fixture_html()
    source = RankingsSource()
    context = RunContext(run_id="test-run", scraped_at=pd.Timestamp("2024-02-01", tz="UTC").to_pydatetime())

    extracted = source.extract(make_snapshots(html), context)

    assert set(extracted) == {"top_models", "market_share", "categories_programming"}
    assert len(extracted["top_models"]) == 9
    assert len(extracted["market_share"]) == 9
    assert len(extracted["categories_programming"]) == 9
    assert extracted["top_models"][0].rank == 1
    assert extracted["categories_programming"][0].category_slug == "programming"


def test_selector_drift_raises_clear_error() -> None:
    broken_html = build_fixture_html(categories_programming=[])
    source = RankingsSource()
    context = RunContext(run_id="broken", scraped_at=pd.Timestamp("2024-02-01", tz="UTC").to_pydatetime())
    source._extract_chart_payloads_with_playwright = lambda: {}

    with pytest.raises(ExtractionError, match="categories_programming"):
        source.extract(make_snapshots(broken_html), context)


def test_browser_fallback_is_used_when_static_chart_payloads_are_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    source = RankingsSource()
    context = RunContext(run_id="fallback", scraped_at=pd.Timestamp("2024-02-01", tz="UTC").to_pydatetime())
    called = {"value": False}

    def fake_fallback() -> dict[str, dict]:
        called["value"] = True
        return _runtime_fallback_charts()

    monkeypatch.setattr(source, "_extract_chart_payloads_with_playwright", fake_fallback)

    extracted = source.extract(make_snapshots("<html><body>missing</body></html>"), context)

    assert called["value"] is True
    assert set(extracted) == {"top_models", "market_share", "categories_programming"}
    assert len(extracted["top_models"]) == 9


def test_browser_fallback_failure_raises_clear_missing_dataset_error(monkeypatch: pytest.MonkeyPatch) -> None:
    source = RankingsSource()
    context = RunContext(run_id="fallback-broken", scraped_at=pd.Timestamp("2024-02-01", tz="UTC").to_pydatetime())
    monkeypatch.setattr(source, "_extract_chart_payloads_with_playwright", lambda: {})

    with pytest.raises(ExtractionError, match="top_models"):
        source.extract(make_snapshots("<html><body>missing</body></html>"), context)


def test_normalize_repeated_runs_are_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    html = build_fixture_html(
        top_models=_load_payloads()["top_models"][:2],
        market_share=_load_payloads()["market_share"][:2],
        categories_programming=_load_payloads()["categories_programming"][:2],
    )
    pipeline = RankingsPipeline(tmp_path)
    monkeypatch.setattr(pipeline.source, "fetch_snapshots", lambda: make_snapshots(html))

    first = pipeline.run_initial_backfill()
    second = pipeline.run_initial_backfill()

    top_models = pd.read_csv(tmp_path / "data" / "normalized" / "openrouter" / "top_models.csv")
    assert len(top_models) == 6
    assert first.datasets_written["top_models"] == 6
    assert second.datasets_written["top_models"] == 6
    assert top_models[["week_start_date", "entity_id"]].duplicated().sum() == 0


def test_weekly_update_adds_one_new_week(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payloads = _load_payloads()
    initial_html = build_fixture_html(
        top_models=payloads["top_models"][:2],
        market_share=payloads["market_share"][:2],
        categories_programming=payloads["categories_programming"][:2],
    )
    updated_html = build_fixture_html(
        top_models=payloads["top_models"][:3],
        market_share=payloads["market_share"][:3],
        categories_programming=payloads["categories_programming"][:3],
    )
    pipeline = RankingsPipeline(tmp_path)
    monkeypatch.setattr(pipeline.source, "fetch_snapshots", lambda: make_snapshots(initial_html))
    pipeline.run_initial_backfill()

    monkeypatch.setattr(pipeline.source, "fetch_snapshots", lambda: make_snapshots(updated_html))
    pipeline.run_weekly_update()

    market_share = pd.read_csv(tmp_path / "data" / "normalized" / "openrouter" / "market_share.csv")
    assert sorted(market_share["week_start_date"].unique().tolist()) == ["2024-01-07", "2024-01-14", "2024-01-21"]


def test_validate_and_weekly_update_share_the_same_fallback_extraction_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = RankingsPipeline(tmp_path)
    broken_html = "<html><body>missing</body></html>"
    monkeypatch.setattr(pipeline.source, "fetch_snapshots", lambda: make_snapshots(broken_html))
    monkeypatch.setattr(pipeline.source, "_extract_chart_payloads_with_playwright", _runtime_fallback_charts)

    counts = pipeline.validate()
    weekly = pipeline.run_weekly_update()

    assert counts["top_models"] == 9
    assert weekly.datasets_written["top_models"] == 9
    assert weekly.datasets_written["market_share"] == 9
    assert weekly.datasets_written["categories_programming"] == 9


def test_backfill_missing_fills_multiple_weeks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payloads = _load_payloads()
    sparse_html = build_fixture_html(
        top_models=payloads["top_models"][:1],
        market_share=payloads["market_share"][:1],
        categories_programming=payloads["categories_programming"][:1],
    )
    full_html = build_fixture_html()
    pipeline = RankingsPipeline(tmp_path)
    monkeypatch.setattr(pipeline.source, "fetch_snapshots", lambda: make_snapshots(sparse_html))
    pipeline.run_initial_backfill()

    monkeypatch.setattr(pipeline.source, "fetch_snapshots", lambda: make_snapshots(full_html))
    pipeline.run_backfill_missing()

    categories = pd.read_csv(tmp_path / "data" / "normalized" / "openrouter" / "categories_programming.csv")
    assert sorted(categories["week_start_date"].unique().tolist()) == ["2024-01-01", "2024-01-08", "2024-01-15"]


def test_raw_manifest_written_for_each_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    html = build_fixture_html()
    pipeline = RankingsPipeline(tmp_path)
    monkeypatch.setattr(pipeline.source, "fetch_snapshots", lambda: make_snapshots(html))

    result = pipeline.run_initial_backfill()

    manifest_path = result.raw_run_dir / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == result.run_id
    assert {item["dataset_id"] for item in manifest["datasets"]} == {
        "top_models",
        "market_share",
        "categories_programming",
    }


def test_csv_and_parquet_outputs_stay_schema_consistent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    html = build_fixture_html()
    pipeline = RankingsPipeline(tmp_path)
    monkeypatch.setattr(pipeline.source, "fetch_snapshots", lambda: make_snapshots(html))

    pipeline.run_initial_backfill()

    csv_df = pd.read_csv(tmp_path / "data" / "normalized" / "openrouter" / "top_models.csv")
    parquet_df = pd.read_parquet(tmp_path / "data" / "normalized" / "openrouter" / "top_models.parquet")
    assert list(csv_df.columns) == list(parquet_df.columns)
