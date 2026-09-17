from __future__ import annotations

from datetime import datetime, timezone

from event_consensus.domain import (
    checkpoint_stage,
    classify_event_family,
    enrich_event_row,
    payload_checksum,
)


NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def test_checkpoint_stages_follow_event_lifecycle() -> None:
    assert checkpoint_stage("2026-09-22T12:00:00Z", now_utc=NOW) == "watch"
    assert checkpoint_stage("2026-09-18T12:00:00Z", now_utc=NOW) == "t_minus_5d"
    assert checkpoint_stage("2026-09-16T11:00:00Z", now_utc=NOW) == "t_minus_1d"
    assert checkpoint_stage("2026-09-15T12:30:00Z", now_utc=NOW) == "t_minus_60m"
    assert checkpoint_stage("2026-09-15T11:59:00Z", now_utc=NOW) == "t_plus_2m"
    assert checkpoint_stage("2026-09-15T11:45:00Z", now_utc=NOW) == "t_plus_30m"


def test_event_family_and_score_are_explicit() -> None:
    assert classify_event_family("Fed Interest Rate Decision") == "fomc"
    row = enrich_event_row(
        {
            "event_id": "provider:1",
            "title": "Core CPI MoM",
            "scheduled_at_utc": "2026-09-15T12:30:00Z",
            "importance": 1,
            "forecast": 0.3,
            "previous": 0.2,
            "actual": None,
            "retrieved_at_utc": NOW,
            "trigger_type": "manual",
        },
        now_utc=NOW,
    )
    assert row["event_family"] == "cpi"
    assert row["snapshot_stage"] == "t_minus_60m"
    assert row["risk_importance"] == 45.0
    assert row["risk_consensus"] == 10.0
    assert 0 < row["risk_score"] <= 100
    assert row["snapshot_id"]
    assert row["observation_signature"]


def test_payload_checksum_is_stable_and_order_insensitive() -> None:
    assert payload_checksum({"b": 2, "a": 1}) == payload_checksum({"a": 1, "b": 2})
    assert len(payload_checksum({"a": 1})) == 64
