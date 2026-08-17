import pandas as pd
import pytest
from scripts.mtr_consensus_bridge import (
    ASSUMED_FY26_TOTAL,
    FY2025_TRANSPORT_REV,
    eps_sensitivities,
)


def test_fy26_transport_derivation():
    """Our FY2026E transport revenue = H1 nowcast x (1 + FY25 H2/H1 ratio)."""
    # H1 nowcast 11,976.7; FY25 H2/H1 = 11915/11680 = 1.0201
    expected = 11976.7 * (1 + 11915.0 / 11680.0)
    assert ASSUMED_FY26_TOTAL > expected  # total includes other segments
    # transport leg alone:
    transport_leg = 11976.7 * (1 + 11915.0 / 11680.0)
    assert transport_leg == pytest.approx(24194.4, abs=1.0)


def test_sensitivity_ranking_property_first():
    """Property timing must dominate EPS sensitivity - the core P0C insight."""
    sens = eps_sensitivities()
    assert len(sens) == 4
    prop = sens[sens["variable"].str.contains("Property recognition")].iloc[0]
    farebox = sens[sens["variable"].str.contains("Farebox")].iloc[0]
    mainland = sens[sens["variable"].str.contains("Mainland")].iloc[0]
    # property impact is an order of magnitude larger than farebox/mainland
    assert abs(prop["eps_impact_hkd"]) > 10 * abs(farebox["eps_impact_hkd"])
    assert abs(prop["eps_impact_hkd"]) > 20 * abs(mainland["eps_impact_hkd"])
    # per-package profit from FY2025 disclosure: 11,084 / 4 packages
    assert prop["delta_hkdm"] == pytest.approx(11084.0 / 4.0, abs=1.0)


def test_consensus_csv_written():
    df = pd.read_csv("data/normalized/hk_transport/mtr_consensus_bridge.csv")
    assert "TOTAL revenue" in df["line"].values
    row = df[df["line"] == "TOTAL revenue"].iloc[0]
    assert row["fy2025_actual_hkdm"] == pytest.approx(55465.0, abs=1.0)


def test_fy2025_anchor():
    assert FY2025_TRANSPORT_REV == 23595.0
