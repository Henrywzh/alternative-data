from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from event_consensus.domain import enrich_event_row
from event_consensus.pipeline import run_pipeline
from event_consensus.storage import save_artifact


NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def test_failed_calendar_retains_last_valid_timeline(monkeypatch, tmp_path) -> None:
    path = tmp_path / "latest.json"
    prior = enrich_event_row(
        {
            "event_id": "tradingview:1",
            "country": "US",
            "title": "Fed Interest Rate Decision",
            "scheduled_at_utc": "2026-09-16T18:00:00Z",
            "importance": 1,
            "forecast": 4.0,
            "previous": 3.75,
            "actual": None,
            "retrieved_at_utc": NOW,
            "trigger_type": "scheduled",
        },
        now_utc=NOW,
    )
    save_artifact(
        {
            "schema_version": "1.0",
            "events": [prior],
            "quotes": [],
            "source_health": [],
        },
        path=path,
    )

    def fail_calendar(*_args, **_kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr("event_consensus.pipeline.fetch_calendar", fail_calendar)
    monkeypatch.setattr(
        "event_consensus.pipeline.fetch_official_components",
        lambda **_kwargs: (pd.DataFrame(), {"source_id": "official_bls", "status": "Unavailable", "records": 0}),
    )
    monkeypatch.setattr(
        "event_consensus.pipeline.fetch_quotes",
        lambda *_args, **_kwargs: (pd.DataFrame(), {"source_id": "finnhub_quotes", "status": "Unavailable", "records": 0}),
    )
    result = run_pipeline(
        trigger_type="manual",
        from_date="2026-09-15",
        to_date="2026-09-20",
        write=False,
        artifact_path=path,
        now_utc=NOW,
    )
    assert len(result["artifact"]["events"]) == 1
    assert result["artifact"]["events"][0]["fallback_status"] == "retained_last_valid_artifact"
    assert result["artifact"]["source_health"][0]["status"] == "Unavailable"


def test_no_quotes_refresh_retains_previous_quote_snapshot(monkeypatch, tmp_path) -> None:
    path = tmp_path / "latest.json"
    prior_event = enrich_event_row(
        {
            "event_id": "tradingview:1",
            "country": "US",
            "title": "Fed Interest Rate Decision",
            "scheduled_at_utc": "2026-09-16T18:00:00Z",
            "importance": 1,
            "forecast": 4.0,
            "previous": 3.75,
            "actual": None,
            "retrieved_at_utc": NOW,
            "trigger_type": "scheduled",
        },
        now_utc=NOW,
    )
    save_artifact(
        {
            "schema_version": "1.0",
            "events": [prior_event],
            "quotes": [{"symbol": "SPY", "current": 500.0}],
            "source_health": [],
        },
        path=path,
    )

    monkeypatch.setattr(
        "event_consensus.pipeline.fetch_calendar",
        lambda *_args, **_kwargs: (
            pd.DataFrame([prior_event]),
            {"source_id": "tradingview_calendar", "status": "Healthy", "records": 1},
        ),
    )
    monkeypatch.setattr(
        "event_consensus.pipeline.fetch_official_components",
        lambda **_kwargs: (
            pd.DataFrame(),
            {"source_id": "official_bls", "status": "Unavailable", "records": 0},
        ),
    )
    result = run_pipeline(
        trigger_type="manual",
        from_date="2026-09-15",
        to_date="2026-09-20",
        include_quotes=False,
        write=False,
        artifact_path=path,
        now_utc=NOW,
    )
    assert result["artifact"]["quotes"] == [{"symbol": "SPY", "current": 500.0}]
    assert any(
        row["source_id"] == "finnhub_quotes" and row["status"] == "Skipped"
        for row in result["artifact"]["source_health"]
    )


def test_partial_calendar_response_retains_missing_prior_event(monkeypatch, tmp_path) -> None:
    path = tmp_path / "latest.json"
    first = enrich_event_row(
        {
            "event_id": "tradingview:1",
            "country": "US",
            "title": "Fed Interest Rate Decision",
            "scheduled_at_utc": "2026-09-16T18:00:00Z",
            "importance": 1,
            "forecast": 4.0,
            "previous": 3.75,
            "actual": None,
            "retrieved_at_utc": NOW,
            "trigger_type": "scheduled",
        },
        now_utc=NOW,
    )
    second = enrich_event_row(
        {
            "event_id": "tradingview:2",
            "country": "US",
            "title": "Retail Sales MoM",
            "scheduled_at_utc": "2026-09-17T12:30:00Z",
            "importance": 1,
            "forecast": 0.3,
            "previous": 0.1,
            "actual": None,
            "retrieved_at_utc": NOW,
            "trigger_type": "scheduled",
        },
        now_utc=NOW,
    )
    save_artifact(
        {"schema_version": "1.0", "events": [first, second], "quotes": [], "source_health": []},
        path=path,
    )
    monkeypatch.setattr(
        "event_consensus.pipeline.fetch_calendar",
        lambda *_args, **_kwargs: (
            pd.DataFrame([first]),
            {"source_id": "tradingview_calendar", "status": "Healthy", "records": 1, "notes": "partial"},
        ),
    )
    monkeypatch.setattr(
        "event_consensus.pipeline.fetch_official_components",
        lambda **_kwargs: (
            pd.DataFrame(),
            {"source_id": "official_bls", "status": "Unavailable", "records": 0},
        ),
    )
    result = run_pipeline(
        trigger_type="scheduled",
        from_date="2026-09-15",
        to_date="2026-09-20",
        include_quotes=False,
        write=False,
        artifact_path=path,
        now_utc=NOW,
    )
    assert {row["event_id"] for row in result["artifact"]["events"]} == {
        "tradingview:1",
        "tradingview:2",
    }
    assert result["artifact"]["source_health"][0]["status"] == "Partial"
    assert "Retained 1 prior-window event(s)" in result["artifact"]["source_health"][0]["notes"]


def test_empty_quote_and_component_refreshes_retain_prior_artifact(monkeypatch, tmp_path) -> None:
    path = tmp_path / "latest.json"
    event = enrich_event_row(
        {
            "event_id": "tradingview:1",
            "country": "US",
            "title": "Fed Interest Rate Decision",
            "scheduled_at_utc": "2026-09-16T18:00:00Z",
            "importance": 1,
            "forecast": 4.0,
            "previous": 3.75,
            "actual": None,
            "retrieved_at_utc": NOW,
            "trigger_type": "scheduled",
        },
        now_utc=NOW,
    )
    prior_component = {
        "source_id": "official_bls",
        "series_id": "SERIES",
        "event_family": "cpi",
        "component_id": "headline",
        "reference_period": "2026-08",
        "latest_value": 100.0,
    }
    save_artifact(
        {
            "schema_version": "1.0",
            "events": [event],
            "quotes": [{"symbol": "SPY", "current": 500.0}],
            "official_components": [prior_component],
            "source_health": [],
        },
        path=path,
    )
    monkeypatch.setattr(
        "event_consensus.pipeline.fetch_calendar",
        lambda *_args, **_kwargs: (
            pd.DataFrame([event]),
            {"source_id": "tradingview_calendar", "status": "Healthy", "records": 1},
        ),
    )
    monkeypatch.setattr(
        "event_consensus.pipeline.fetch_official_components",
        lambda **_kwargs: (
            pd.DataFrame(),
            {"source_id": "official_bls", "status": "Unavailable", "records": 0},
        ),
    )
    monkeypatch.setattr(
        "event_consensus.pipeline.fetch_quotes",
        lambda *_args, **_kwargs: (
            pd.DataFrame(),
            {"source_id": "finnhub_quotes", "status": "Unavailable", "records": 0},
        ),
    )
    monkeypatch.setattr(
        "event_consensus.pipeline.fetch_futu_quotes",
        lambda **_kwargs: (
            pd.DataFrame(),
            {"source_id": "futu_opend", "status": "Unavailable", "records": 0},
        ),
    )
    monkeypatch.setattr(
        "event_consensus.pipeline.load_component_ledger",
        lambda: pd.DataFrame(),
    )
    result = run_pipeline(
        trigger_type="manual",
        from_date="2026-09-15",
        to_date="2026-09-20",
        write=False,
        artifact_path=path,
        now_utc=NOW,
    )
    assert result["artifact"]["quotes"][0]["symbol"] == "SPY"
    assert result["artifact"]["official_components"][0]["series_id"] == "SERIES"
