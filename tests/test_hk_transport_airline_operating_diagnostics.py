from pathlib import Path

import pandas as pd
import pytest

from hk_transport.sources.airline_operating_diagnostics import (
    build_airline_operating_diagnostics,
)


def test_operating_diagnostics_uses_equal_periods_and_prefers_total_rows() -> None:
    result = build_airline_operating_diagnostics(
        snapshot_date="2026-08-07",
        retrieved_at="2026-08-07T00:00:00+00:00",
    )
    assert len(result) == 6
    assert result["company"].nunique() == 6
    assert result["current_period"].eq("2026Q2/Jun").all()
    assert result["prior_period"].eq("2025Q2/Jun").all()
    southern = result.loc[result["company"].eq("China Southern Airlines")].iloc[0]
    assert southern["q2_rpk_minus_ask_gap_pp"] == pytest.approx(-1.195253, abs=1e-6)
    assert southern["q2_passenger_lf_minus_q1_pp"] == pytest.approx(-0.593080, abs=1e-6)
    assert southern["june_passenger_lf_yoy_pp"] == pytest.approx(-1.15, abs=1e-6)
    assert southern["source_quality"] == "derived_issuer_monthly_operating_release"


def test_current_operating_diagnostics_has_lineage_and_expected_southern_outlier() -> None:
    frame = pd.read_csv(Path("data/normalized/hk_transport/airline_operating_diagnostics.csv"))
    assert len(frame) == 6
    assert frame[["source_path", "source_note", "retrieved_at"]].notna().all().all()
    assert frame["q2_rpk_minus_ask_gap_pp"].notna().all()
    assert frame.loc[frame["company"].eq("China Southern Airlines"), "q2_rpk_minus_ask_gap_pp"].iloc[0] < 0
    assert frame.loc[frame["company"].eq("Spring Airlines"), "q2_rpk_minus_ask_gap_pp"].iloc[0] > 0
