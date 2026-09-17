from __future__ import annotations

import pandas as pd

from event_consensus.storage import (
    append_component_snapshots,
    append_event_snapshots,
    append_quote_snapshots,
)


def _row(snapshot_id: str, trigger: str, retrieved: str) -> dict:
    return {
        "snapshot_id": snapshot_id,
        "event_id": "event:1",
        "observation_signature": "same-content",
        "trigger_type": trigger,
        "scheduled_at_utc": "2026-09-16T18:00:00Z",
        "retrieved_at_utc": retrieved,
    }


def test_scheduled_duplicates_collapse_but_manual_observations_remain(tmp_path) -> None:
    path = tmp_path / "events.parquet"
    first = pd.DataFrame(
        [_row("one", "scheduled", "2026-09-15T10:00:00Z")]
    )
    append_event_snapshots(first, path=path)
    second = pd.DataFrame(
        [
            _row("two", "scheduled", "2026-09-15T10:05:00Z"),
            _row("three", "manual", "2026-09-15T10:06:00Z"),
            _row("four", "manual", "2026-09-15T10:07:00Z"),
        ]
    )
    combined = append_event_snapshots(second, path=path)
    assert len(combined) == 3
    assert set(combined["snapshot_id"]) == {"one", "three", "four"}


def test_quote_snapshots_never_overwrite_same_market_timestamp(tmp_path) -> None:
    path = tmp_path / "quotes.parquet"
    first = pd.DataFrame(
        [
            {
                "provider": "finnhub",
                "symbol": "SPY",
                "current": 500.0,
                "market_timestamp_utc": "2026-09-15T14:00:00Z",
                "retrieved_at_utc": "2026-09-15T14:01:00Z",
                "trigger_type": "scheduled",
            }
        ]
    )
    append_quote_snapshots(first, path=path)
    second = first.copy()
    second.loc[0, "current"] = 501.0
    second.loc[0, "retrieved_at_utc"] = "2026-09-15T14:02:00Z"
    combined = append_quote_snapshots(second, path=path)
    assert len(combined) == 2
    assert set(combined["current"]) == {500.0, 501.0}


def test_component_snapshots_deduplicate_only_identical_automatic_rows(tmp_path) -> None:
    path = tmp_path / "components.parquet"
    row = {
        "source_id": "official_bls",
        "series_id": "SERIES",
        "event_family": "cpi",
        "component_id": "headline",
        "reference_period": "2026-08",
        "latest_value": 100.0,
        "previous_value": 99.0,
        "mom_change": 1.0,
        "retrieved_at_utc": "2026-09-15T14:00:00Z",
        "trigger_type": "scheduled",
    }
    append_component_snapshots(pd.DataFrame([row]), path=path)
    duplicate = dict(row)
    duplicate["retrieved_at_utc"] = "2026-09-15T14:01:00Z"
    combined = append_component_snapshots(pd.DataFrame([duplicate]), path=path)
    assert len(combined) == 1
    changed = dict(duplicate)
    changed["latest_value"] = 101.0
    changed["retrieved_at_utc"] = "2026-09-15T14:02:00Z"
    combined = append_component_snapshots(pd.DataFrame([changed]), path=path)
    assert len(combined) == 2
