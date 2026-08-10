"""Tests for catalyst underwriting + thesis scoreboard."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources import airline_catalyst_underwriting as cu


@pytest.fixture(scope="module")
def outputs() -> dict[str, pd.DataFrame]:
    return cu.build_airline_catalyst_underwriting()


def test_catalyst_tree_built(outputs: dict[str, pd.DataFrame]) -> None:
    c = outputs["catalyst"]
    assert len(c) >= 6
    assert {"event_id", "event_name", "event_window_start", "expected_sign", "magnitude_hypothesis", "invalidation_threshold"}.issubset(c.columns)


def test_earnings_catalyst_is_core(outputs: dict[str, pd.DataFrame]) -> None:
    c = outputs["catalyst"]
    core = c[c.event_id.eq("cat_earnings_1h26")].iloc[0]
    assert "2026-08-29" in str(core.event_window_start)
    assert "Spring" in str(core.expected_sign)
    assert len(str(core.invalidation_threshold)) > 30


def test_scoreboard_covers_thesis_components(outputs: dict[str, pd.DataFrame]) -> None:
    sb = outputs["scoreboard"]
    expected = {
        "Capacity",
        "Load factor",
        "Yield (key uncertainty)",
        "Fuel CASK",
        "Non-fuel CASK",
        "International mix",
        "Earnings vs Street",
        "Valuation",
        "Catalyst",
        "Risk (one-offs)",
    }
    assert expected.issubset(set(sb.component))


def test_scoreboard_spring_edge_consistent(outputs: dict[str, pd.DataFrame]) -> None:
    sb = outputs["scoreboard"].set_index("component")
    assert "Spring" in sb.loc["Earnings vs Street", "edge"]
    assert "Spring" in sb.loc["Valuation", "edge"]
    assert "Spring" in sb.loc["Non-fuel CASK", "edge"]


def test_fuel_sensitivity_honest(outputs: dict[str, pd.DataFrame]) -> None:
    """Juneyao's relative fuel sensitivity is higher - the underwriting must
    say so rather than claim a clean hedge."""
    c = outputs["catalyst"]
    fuel = c[c.event_id.eq("cat_fuel_h2")].iloc[0]
    assert "Juneyao" in str(fuel.invalidation_threshold)
    assert "-36%" in str(fuel.magnitude_hypothesis) or "-35.7" in str(fuel.magnitude_hypothesis)
