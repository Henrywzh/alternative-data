import pandas as pd
import pytest
from scripts.mtr_property_expected_profit import POOL, KNOWN_VALUES, SCENARIO_VALUES
from scripts.mtr_property_eps_bridge import (
    PROPERTY_BASE, PROPERTY_LOW, PROPERTY_HIGH, SHARES_M,
)


def test_expected_profit_has_measured_and_scenario_layers():
    assert "tai-wai" in KNOWN_VALUES
    assert KNOWN_VALUES["tai-wai"] == pytest.approx(8808.0)
    assert "lohas-park-p12" in SCENARIO_VALUES
    assert len(POOL) == 8
    # every pool phase must have a value path (known or scenario)
    for p in POOL:
        pid = p["project_id"]
        assert pid in KNOWN_VALUES or pid in SCENARIO_VALUES


def test_eps_bridge_math():
    """reported_eps = (recurrent + property + ip_reval) / shares."""
    recurrent = 5653.0 * 1.03
    eps = (recurrent + PROPERTY_BASE - 1500.0) / SHARES_M
    assert eps == pytest.approx(1.62, abs=0.01)


def test_eps_bridge_csv_exists():
    df = pd.read_csv("data/normalized/hk_transport/mtr_property_eps_bridge.csv")
    assert df["scenario"].tolist() == ["bear", "base", "bull"]
    assert (df["reported_eps_est_hkd"] > 0).all()
    # ordering: bull > base > bear
    assert df["reported_eps_est_hkd"].is_monotonic_increasing


def test_eps_risk_ranking_priorities():
    """LP12/Tai Wai/P5 top the targeted-enrichment priority list."""
    df = pd.read_csv("data/normalized/hk_transport/mtr_property_eps_risk_ranking.csv")
    top = df.head(3)["project_id"].tolist()
    assert "lohas-park-p12" in top
    assert "the-southside-p5" in top
    assert df["eps_risk_hkd"].is_monotonic_decreasing
