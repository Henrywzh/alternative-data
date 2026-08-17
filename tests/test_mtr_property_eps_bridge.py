import pandas as pd
import pytest
from scripts.mtr_property_expected_profit import POOL, KNOWN_VALUES, SCENARIO_VALUES
from scripts.mtr_property_eps_bridge import (
    PROPERTY_BASE, PROPERTY_LOW, PROPERTY_HIGH, SHARES_M,
)


def test_expected_profit_has_measured_and_scenario_layers():
    assert "tai-wai" in KNOWN_VALUES
    assert KNOWN_VALUES["tai-wai"] == pytest.approx(8808.0)
    # targeted round moved LP12/P5/凱柏峰 II/III/朗賢峯/LP13 into measured data
    assert "lohas-park-p12" in KNOWN_VALUES
    assert KNOWN_VALUES["lohas-park-p12"] == pytest.approx(8735.0, rel=0.01)
    assert KNOWN_VALUES["the-southside-p5"] == pytest.approx(13975.0, rel=0.01)
    assert KNOWN_VALUES["lohas-park-p11-ii-iii"] == pytest.approx(9312.0, rel=0.01)
    assert "lohas-park-p13" in KNOWN_VALUES
    # only P6 and Yau Tong remain scenario-based
    assert set(SCENARIO_VALUES) == {"the-southside-p6", "yau-tong-vb"}
    assert len(POOL) == 8
    for p in POOL:
        pid = p["project_id"]
        assert pid in KNOWN_VALUES or pid in SCENARIO_VALUES


def test_eps_bridge_math():
    """reported_eps = (recurrent + property + ip_reval) / shares (dynamic)."""
    from scripts.mtr_property_eps_bridge import IP_REVAL_SCENARIOS
    recurrent = 5653.0 * 1.03
    eps = (recurrent + PROPERTY_BASE + IP_REVAL_SCENARIOS["base"]) / SHARES_M
    # base reported EPS lands ~2.36 with +2.5bn IP reval
    assert eps == pytest.approx(2.36, abs=0.02)
    # underlying (no IP reval) is ~1.96
    underlying = (recurrent + PROPERTY_BASE) / SHARES_M
    assert underlying == pytest.approx(1.96, abs=0.02)
    assert PROPERTY_BASE > 4000.0
    assert PROPERTY_LOW < PROPERTY_BASE < PROPERTY_HIGH
    # reported eps ordering with scenario IP reval: bull > base > bear
    reported = {s: (recurrent + {"bear": PROPERTY_LOW, "base": PROPERTY_BASE,
                                 "bull": PROPERTY_HIGH}[s] + ip) / SHARES_M
                for s, ip in IP_REVAL_SCENARIOS.items()}
    assert reported["bear"] < reported["base"] < reported["bull"]


def test_eps_bridge_csv_exists():
    df = pd.read_csv("data/normalized/hk_transport/mtr_property_eps_bridge.csv")
    assert df["scenario"].tolist() == ["bear", "base", "bull"]
    assert (df["reported_eps_est_hkd"] > 0).all()
    # ordering: bull > base > bear
    assert df["reported_eps_est_hkd"].is_monotonic_increasing
    # base reported EPS ~2.36 after the IP-reval scenario update
    base = df[df["scenario"] == "base"].iloc[0]
    assert base["reported_eps_est_hkd"] == pytest.approx(2.36, abs=0.02)
    assert base["underlying_eps_hkd"] == pytest.approx(1.96, abs=0.02)


def test_pit_aligned_eligible_values():
    """FY26 eligible uses sales registered as of FY25 year end (PIT-safe)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mtr_pep", "scripts/mtr_property_expected_profit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # P5 滶晨: 121.8bn as of FY25 year end vs 139.8bn current
    assert mod._AS_OF_FY25["the-southside-p5"] == pytest.approx(12183.0, rel=0.01)
    assert mod.KNOWN_VALUES["the-southside-p5"] == pytest.approx(13975.0, rel=0.01)
    # LP12 海瑅灣: zero deals before FY25 year end (kept at current value with note)
    assert mod._AS_OF_FY25["lohas-park-p12"] == pytest.approx(8735.0, rel=0.01)


def test_eps_risk_ranking_priorities():
    """LP12/Tai Wai/P5 top the targeted-enrichment priority list."""
    df = pd.read_csv("data/normalized/hk_transport/mtr_property_eps_risk_ranking.csv")
    top = df.head(3)["project_id"].tolist()
    assert "lohas-park-p12" in top
    assert "the-southside-p5" in top
    assert df["eps_risk_hkd"].is_monotonic_decreasing
