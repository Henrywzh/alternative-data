"""Tests for the pre-event locked baseline snapshot."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources.airline_pre_event_locked_baseline import (
    OUTPUT_PATH,
    build_airline_pre_event_locked_baseline,
)


@pytest.fixture(scope="module")
def baseline() -> pd.DataFrame:
    return build_airline_pre_event_locked_baseline()


def test_covers_six_mainland_carriers(baseline: pd.DataFrame) -> None:
    assert len(baseline) == 6
    assert set(baseline.company) == {
        "Air China",
        "China Eastern Airlines",
        "China Southern Airlines",
        "Hainan Airlines Holdings",
        "Juneyao Airlines",
        "Spring Airlines",
    }


def test_every_row_locked_with_schedule_and_consensus(baseline: pd.DataFrame) -> None:
    assert (baseline.lock_status == "locked").all()
    assert baseline.filing_scheduled_date.notna().all()
    assert (baseline.consensus_fy2026_profit_usd_mn > 0).all()
    assert baseline.snapshot_date.notna().all()


def test_flat_yield_revenue_and_fuel_present(baseline: pd.DataFrame) -> None:
    assert baseline.h1_2026_flat_yield_revenue_native_mn.notna().all()
    assert (baseline.h1_2026_flat_yield_revenue_native_mn > 0).all()
    assert (baseline.fuel_price_usd_per_gallon > 2.0).all()
    assert baseline.fuel_cask_forecast_native.notna().all()


def test_southern_nci_fix_reflected(baseline: pd.DataFrame) -> None:
    southern = baseline[baseline.company.eq("China Southern Airlines")].iloc[0]
    assert southern.v3_net_income_leg == "share_based_nci_forward"
    # Post-fix the model is conservative but comparable, not 5.9x consensus.
    assert -80.0 < southern.model_vs_consensus_gap_pct < 0.0


def test_output_written(baseline: pd.DataFrame) -> None:
    assert OUTPUT_PATH.exists()
    on_disk = pd.read_csv(OUTPUT_PATH)
    assert len(on_disk) == len(baseline)
