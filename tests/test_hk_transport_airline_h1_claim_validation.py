from __future__ import annotations

import pytest
import pandas as pd

from src.hk_transport.sources.airline_h1_claim_validation import (
    build_airline_h1_claim_validation_queue,
)


def test_h1_claim_queue_covers_core_financial_and_9air_scope_claims() -> None:
    frame = build_airline_h1_claim_validation_queue()
    assert len(frame) == 16
    assert set(frame["company"]) == {"Spring Airlines", "Juneyao Airlines", "9 Air"}
    assert frame["formal_actual_value"].isna().all()
    assert frame["validation_result"].isna().all()
    assert frame["formal_report_source"].notna().all()
    assert frame["validation_rule"].notna().all()


@pytest.mark.network
def test_h1_claim_queue_preserves_preliminary_warning_and_pending_9air_pnl() -> None:
    frame = build_airline_h1_claim_validation_queue()
    warning = frame[frame.claim_id.eq("603885.SH__h1_warning_reconciliation")].iloc[0]
    assert warning["pre_h1_observation_value"] == 175.0
    assert warning["validation_status"] == "preliminary_warning_pending_formal_interim"
    nine = frame[frame.claim_id.eq("603885.SH__9air_standalone_pnl")].iloc[0]
    assert pd.isna(nine["pre_h1_observation_value"])
    assert nine["validation_status"] == "standalone_pnl_pending"
    assert "not zero" in nine["source_note"]
