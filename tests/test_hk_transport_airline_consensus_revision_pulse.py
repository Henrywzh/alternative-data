from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_consensus_revision_pulse.csv"


def test_revision_pulse_is_a_dated_public_sample_aggregation() -> None:
    frame = pd.read_csv(PATH)
    assert len(frame) >= 140
    assert frame.duplicated(
        ["company", "ticker", "event_date", "estimate_metric", "fiscal_year"]
    ).sum() == 0
    assert frame["event_date"].notna().all()
    assert frame["current_value_median_native"].notna().all()
    assert frame["prior_value_median_native"].notna().all()
    assert frame["public_revision_sample_count"].ge(1).all()
    assert frame["institution_count"].ge(1).all()
    assert frame["source_scope"].eq("dated_public_revision_subset").all()


def test_revision_pulse_preserves_direction_counts_and_single_build_timestamp() -> None:
    frame = pd.read_csv(PATH)
    assert frame["up_revision_count"].ge(0).all()
    assert frame["down_revision_count"].ge(0).all()
    assert frame["flat_revision_count"].ge(0).all()
    assert (
        frame["up_revision_count"]
        + frame["down_revision_count"]
        + frame["flat_revision_count"]
        == frame["public_revision_sample_count"]
    ).all()
    assert frame["retrieved_at"].nunique() == 1


def test_revision_pulse_keeps_canonical_eastern_ticker() -> None:
    frame = pd.read_csv(PATH)
    assert not frame["ticker"].astype(str).str.contains("00670\\.HK", regex=True).any()
    eastern = frame.loc[frame["company"].eq("China Eastern Airlines")]
    assert not eastern.empty
    assert eastern["ticker"].eq("0670.HK / 600115.SH").all()
