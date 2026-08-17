"""Tests for the compact pre-H1 thesis-input join."""

from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_thesis_v2_inputs import build_airline_thesis_v2_inputs


@pytest.fixture(scope="module")
def thesis_inputs(tmp_path_factory: pytest.TempPathFactory):
    # The builder writes canonical artifacts by design. The fixture only
    # exercises the existing normalized layers and keeps the assertions small.
    return build_airline_thesis_v2_inputs(as_of_date="2026-08-09")


def test_coverage_contains_all_company_rows_and_current_model_rows(thesis_inputs) -> None:
    coverage, forecast, pairs = thesis_inputs
    assert len(coverage) == 7
    assert set(coverage["company"]) == {
        "Cathay Pacific",
        "Air China",
        "China Southern Airlines",
        "China Eastern Airlines",
        "Hainan Airlines Holdings",
        "Spring Airlines",
        "Juneyao Airlines",
    }
    assert len(forecast) == 30
    assert set(forecast["period"]) == {"H1"}
    assert len(pairs) == 6


def test_thin_consensus_is_explicit_for_juneyao(thesis_inputs) -> None:
    coverage, _, _ = thesis_inputs
    juneyao = coverage.loc[coverage["company"].eq("Juneyao Airlines")].iloc[0]
    assert juneyao["consensus_status"] == "thin_consensus"
    assert juneyao["consensus_revenue_analyst_count"] == 1


def test_pair_layer_does_not_assign_long_or_short(thesis_inputs) -> None:
    _, _, pairs = thesis_inputs
    assert pairs["direction_status"].eq("not_selected_by_v2").all()
    assert pairs["leg_a"].notna().all()
    assert pairs["leg_b"].notna().all()


def test_pair_spreads_are_operating_diagnostics_not_missing_values(thesis_inputs) -> None:
    _, _, pairs = thesis_inputs
    spring_juneyao = pairs.loc[pairs["pair_id"].eq("Spring__Juneyao")].iloc[0]
    assert pd.notna(spring_juneyao["v2_base_case_revenue_growth_spread_a_minus_b_pp"])
    assert pd.notna(spring_juneyao["v2_base_case_operating_margin_spread_a_minus_b_pp"])
