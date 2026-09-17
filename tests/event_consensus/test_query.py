from __future__ import annotations

import pytest

from event_consensus.query import EventQueryService, QueryError
from conftest import NOW


def test_capabilities_describe_loaded_artifact(artifact_path):
    service = EventQueryService(artifact_path=artifact_path)

    result = service.capabilities()

    assert result["query"] == "capabilities"
    assert result["artifact_schema_version"] == "1.0"
    assert result["data"]["countries"] == ["CN", "US"]
    assert "brief" in result["data"]["commands"]


def test_missing_artifact_fails_closed(tmp_path):
    with pytest.raises(QueryError, match="latest artifact"):
        EventQueryService(artifact_path=tmp_path / "missing.json").health()


def test_brief_keeps_provider_importance_one_high_even_with_low_score(artifact_path):
    service = EventQueryService(
        artifact_path=artifact_path,
        now_utc=NOW,
    )

    rows = service.brief(horizon_hours=48)["data"]["events"]

    assert rows[0]["event_id"] == "tradingview:importance-one"
    assert rows[0]["priority"] == "high"
    assert rows[0]["priority_reason"] == "provider_importance_1"


def test_list_events_filters_country_priority_and_release_state(artifact_path):
    service = EventQueryService(
        artifact_path=artifact_path,
        now_utc=NOW,
    )

    rows = service.list_events(
        countries=["US"],
        priority="high",
        released=False,
    )["data"]["events"]

    assert [row["country"] for row in rows] == ["US"]
    assert all(row["priority"] == "high" for row in rows)
    assert all(row["released"] is False for row in rows)


def test_research_joins_consensus_components_quotes_and_scenarios(artifact_path, event_ledger_path):
    service = EventQueryService(
        artifact_path=artifact_path,
        event_ledger_path=event_ledger_path,
        now_utc=NOW,
    )

    data = service.research("tradingview:importance-one")["data"]

    assert data["event"]["event_id"] == "tradingview:importance-one"
    assert len(data["consensus_history"]) == 2
    assert data["quotes"][0]["symbol"] == "SPY"
    assert data["scenario_templates"][0]["scenario"] == "hot"
    assert data["official_components"][0]["component_id"] == "headline"


def test_history_preserves_snapshot_lineage_and_does_not_collapse_pit_rows(artifact_path, event_ledger_path):
    service = EventQueryService(
        artifact_path=artifact_path,
        event_ledger_path=event_ledger_path,
    )

    rows = service.history("tradingview:importance-one")["data"]["observations"]

    assert [row["snapshot_id"] for row in rows] == ["old", "new"]
    assert [row["trigger_type"] for row in rows] == ["scheduled", "manual"]


def test_postmortem_explains_insufficient_history_without_inventing_reaction(artifact_path):
    service = EventQueryService(
        artifact_path=artifact_path,
        now_utc=NOW,
    )

    data = service.postmortem("tradingview:importance-one")["data"]

    assert data["market_reaction"]["status"] == "insufficient_history"
    assert data["market_reaction"]["observations"] == []
