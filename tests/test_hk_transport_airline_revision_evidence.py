from __future__ import annotations

from pathlib import Path

import pandas as pd

from hk_transport.sources.airline_revision_evidence import build_airline_revision_evidence


ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = ROOT / "data" / "normalized" / "hk_transport"


def test_revision_evidence_preserves_dated_and_vendor_classes() -> None:
    frame = pd.read_csv(TRANSPORT / "airline_revision_evidence.csv")

    assert len(frame) == 366
    assert set(frame["evidence_type"]) == {
        "dated_estimate_revision", "dated_rating_event", "vendor_revision_signal"
    }
    assert frame.duplicated(
        [
            "ticker", "evidence_date", "evidence_type", "metric", "fiscal_year",
            "institution", "prior_evidence_date", "signal_window", "source_url",
        ]
    ).sum() == 0
    assert frame[["evidence_date", "source_quality", "source_url", "source_note", "retrieved_at"]].notna().all().all()
    assert not frame["ticker"].astype(str).str.contains("00670\\.HK", regex=True).any()

    dated = frame.loc[frame["evidence_type"].eq("dated_estimate_revision")]
    assert len(dated) == 162
    assert dated["revision_history_available"].eq(True).all()
    assert dated["prior_evidence_date"].notna().all()
    assert dated["current_value_native"].notna().all()
    assert dated["direction"].isin(["up", "down", "flat"]).all()

    vendor = frame.loc[frame["evidence_type"].eq("vendor_revision_signal")]
    assert len(vendor) == 36
    assert vendor["revision_history_available"].eq(False).all()
    assert vendor["information_scope"].eq("vendor_short_horizon_snapshot").all()
    assert set(vendor["signal_window"]) == {"7d", "30d"}
    assert vendor["current_value_native"].isna().all()
    assert vendor["direction"].isin(["up", "down", "flat", "no_signal"]).all()


def test_revision_evidence_builder_accepts_explicit_input_frames() -> None:
    all_events = pd.read_csv(TRANSPORT / "airline_consensus_events.csv")
    events = pd.concat([
        all_events.loc[all_events["event_type"].eq("estimate_revision")].head(1),
        all_events.loc[all_events["event_type"].eq("rating_event")].head(1),
    ], ignore_index=True)
    yahoo = pd.read_csv(TRANSPORT / "airline_yahoo_analyst_snapshot.csv")
    yahoo = yahoo.loc[yahoo["metric"].eq("eps_revision_signal")].head(1)
    result = build_airline_revision_evidence(
        events=events,
        yahoo=yahoo,
        retrieved_at="2026-08-07T00:00:00+00:00",
    )
    assert not result.empty
    assert result["retrieved_at"].eq("2026-08-07T00:00:00+00:00").all()
    assert set(result["evidence_type"]) == {
        "dated_estimate_revision", "dated_rating_event", "vendor_revision_signal"
    }
