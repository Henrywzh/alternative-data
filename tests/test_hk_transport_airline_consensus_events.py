from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_consensus_events.csv"


def test_consensus_event_timeline_has_dated_revision_and_rating_events() -> None:
    frame = pd.read_csv(PATH)
    assert len(frame) >= 300
    assert frame.duplicated(
        ["ticker", "event_date", "event_type", "estimate_metric", "fiscal_year", "institution", "source_url", "rating"]
    ).sum() == 0
    assert frame["event_date"].notna().all()
    assert frame["source_url"].notna().all()
    assert set(frame["event_type"]) == {"estimate_revision", "rating_event"}
    assert set(frame.loc[frame["event_type"].eq("estimate_revision"), "estimate_metric"]) == {
        "eps", "revenue"
    }
    assert set(frame.loc[frame["event_type"].eq("rating_event"), "estimate_metric"]) == {"rating"}


def test_estimate_revision_events_have_ordered_prior_dates_and_direction() -> None:
    frame = pd.read_csv(PATH)
    revisions = frame.loc[frame["event_type"].eq("estimate_revision")].copy()
    current = pd.to_datetime(revisions["event_date"])
    prior = pd.to_datetime(revisions["prior_event_date"])
    assert revisions["prior_event_date"].notna().all()
    assert (prior < current).all()
    assert revisions["current_value_native"].notna().all()
    assert revisions["prior_value_native"].notna().all()
    assert revisions["direction"].isin({"up", "down", "flat"}).all()


def test_consensus_event_timeline_keeps_canonical_eastern_identity() -> None:
    frame = pd.read_csv(PATH)
    assert not frame["ticker"].astype(str).str.contains("00670\\.HK", regex=True).any()
    eastern = frame.loc[frame["company"].eq("China Eastern Airlines")]
    assert not eastern.empty
    assert eastern["ticker"].eq("0670.HK / 600115.SH").all()
