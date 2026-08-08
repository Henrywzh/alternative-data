from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_pair_revision_confirmation import (
    build_airline_pair_revision_confirmation,
)


def test_revision_confirmation_supports_and_contradicts_direction() -> None:
    working = pd.DataFrame([{"pair_id": "A__B", "selection_bucket": "core"}])
    trade = pd.DataFrame([{"pair_id": "A__B", "scenario": "base", "long_leg": "A", "short_leg": "B"}])
    revisions = pd.DataFrame([
        {"company": "A", "evidence_type": "vendor_revision_signal", "fiscal_year": 2026, "evidence_date": "2026-08-07", "signal_window": "7d", "direction": "up", "source_quality": "test"},
        {"company": "B", "evidence_type": "vendor_revision_signal", "fiscal_year": 2026, "evidence_date": "2026-08-07", "signal_window": "7d", "direction": "down", "source_quality": "test"},
    ])
    pulse = pd.DataFrame(columns=["company", "fiscal_year", "estimate_metric", "event_date", "median_change_pct"])
    frame = build_airline_pair_revision_confirmation(working=working, trade=trade, revisions=revisions, pulse=pulse)
    assert frame.iloc[0].revision_confirmation_status == "supports_model_direction"


def test_priority_revision_status_is_not_treated_as_full_broker_vintage() -> None:
    frame = build_airline_pair_revision_confirmation()
    assert len(frame) == 5
    assert frame.revision_confirmation_status.notna().all()
    assert frame.point_in_time_status.str.contains("numeric_revision_pulse_is_older").all()
    assert "supports_model_direction" not in set(frame.revision_confirmation_status)
    assert "not_confirmed_no_signal" in set(frame.revision_confirmation_status)
    assert "not_confirmed_missing_leg_signal" in set(frame.revision_confirmation_status)
