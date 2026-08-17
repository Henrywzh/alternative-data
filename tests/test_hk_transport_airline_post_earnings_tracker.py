"""Tests for the post-earnings tracking ledger."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources.airline_post_earnings_tracker import (
    OUTPUT_PATH,
    build_airline_post_earnings_tracker,
)


@pytest.fixture(scope="module")
def tracker() -> pd.DataFrame:
    return build_airline_post_earnings_tracker()


def test_builds_expected_rows(tracker: pd.DataFrame) -> None:
    # 6 mainland carriers (9 Air excluded: no consensus/filing line) + Cathay.
    assert len(tracker) == 7
    assert set(tracker.company) == {
        "Air China",
        "China Eastern Airlines",
        "China Southern Airlines",
        "Hainan Airlines Holdings",
        "Juneyao Airlines",
        "Spring Airlines",
        "Cathay Pacific",
    }


def test_mainland_rows_awaiting(tracker: pd.DataFrame) -> None:
    mainland = tracker[tracker.validation_status.eq("awaiting_report")]
    assert len(mainland) == 6
    assert mainland.actual_h1_net_profit_native_mn.isna().all()
    assert mainland.t1_return_pct.isna().all()
    assert mainland.filing_scheduled_date.notna().all()
    assert (mainland.pre_event_consensus_fy2026_net_profit_usd_mn > 0).all()


def test_cathay_row_filled_with_market_reaction(tracker: pd.DataFrame) -> None:
    cathay = tracker[tracker.company.eq("Cathay Pacific")].iloc[0]
    assert cathay.validation_status == "filled"
    assert cathay.announcement_date == "2026-08-05"
    assert cathay.actual_h1_net_profit_native_mn == pytest.approx(6243.0)
    assert cathay.h1_share_of_consensus_fy_pct == pytest.approx(58.03, abs=0.05)
    # T0 reaction (announcement-day close vs prior close) should be present.
    assert cathay.return_day0_pct is not None
    assert abs(float(cathay.return_day0_pct)) < 15.0
    # T+5 has not elapsed yet relative to the price capture.
    assert cathay.t5_return_pct is None
    assert cathay.market_reaction_status == "t5_pending"


def test_nci_leg_transparency(tracker: pd.DataFrame) -> None:
    southern = tracker[tracker.company.eq("China Southern Airlines")].iloc[0]
    assert southern.net_income_leg == "share_based_nci_forward"
    assert "NCI" in str(southern.source_note) or "not attributable" in str(southern.source_note)


def test_mainland_rows_carry_locked_v4_pre_event_fields(tracker: pd.DataFrame) -> None:
    spring = tracker[tracker.company.eq("Spring Airlines")].iloc[0]
    assert spring.pre_event_v4_model_version == "v4_decomposition_ask_x_lf_x_yield"
    assert spring.pre_event_v4_h1_revenue_native_mn > 0
    assert spring.pre_event_v4_h1_eps_rmb > 0
    assert spring.pre_event_v4_surprise_season_adjusted_pct > spring.pre_event_v4_surprise_x2_pct


def test_output_written(tracker: pd.DataFrame) -> None:
    assert OUTPUT_PATH.exists()
    on_disk = pd.read_csv(OUTPUT_PATH)
    assert len(on_disk) == len(tracker)
