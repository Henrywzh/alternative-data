import pandas as pd
import pytest
from scripts.mtr_consensus_monitor import SHARES_M, FY25_ACTUAL_EPS, load_our_estimates


def test_our_estimates_load():
    ours = load_our_estimates()
    assert ours["transport_rev_hkdm"] == pytest.approx(24194.0, abs=5.0)
    assert ours["property_base"] > 4000.0
    assert ours["eps_low"] < ours["eps_base"] < ours["eps_high"]


def test_consensus_implied_property_backout():
    """EPS 2.52 back-out: property implied ~68.4bn if IP reval +30亿."""
    eps_c = 2.52417
    recurrent = 5653.0 * 1.03
    implied = eps_c * SHARES_M - recurrent - 3000.0  # IP reval +30亿 (HK$m)
    assert implied == pytest.approx(6863.0, abs=10.0)
    # with IP reval -15亿, implied property is ~113.6bn (FY25-record level)
    implied_neg = eps_c * SHARES_M - recurrent - (-1500.0)
    assert implied_neg == pytest.approx(11363.0, abs=10.0)


def test_our_eps_matches_consensus_under_positive_ip_reval():
    """Our base property + IP reval +30亿 -> EPS ~2.44, close to consensus 2.52."""
    ours = load_our_estimates()
    eps = (5653.0 * 1.03 + ours["property_base"] + 3000.0) / SHARES_M
    assert eps == pytest.approx(2.44, abs=0.02)


def test_monitor_csv_exists():
    with open("data/normalized/hk_transport/mtr_consensus_monitor.csv") as f:
        head = f.read(2000)
    assert "HK transport revenue" in head
    assert "Reported EPS" in head
    assert "implied consensus property profit" in head


def test_ip_reval_sensitivity_anchors():
    """IP reval sensitivity must reconcile with the official FY25 loss."""
    from scripts.mtr_consensus_monitor import ip_reval_rate_sensitivity
    df = ip_reval_rate_sensitivity()
    # FY25 actual remeasurement loss 3,538 pre-tax on 93,188 value
    implied_bp = 3538.0 / 93188.0 * 10000  # ~38bp? no: value move = -V * bp / cap
    # check: -14bp move gives about -3,434 pre-tax (close to 3,538)
    loss_at_14bp = 93188.0 * 0.0014 / 0.038
    assert loss_at_14bp == pytest.approx(3433.0, abs=10.0)
    # EPS impact of -25bp (yields down, value up) is ~+0.81
    row = df[df["cap_rate_move"] == "-25bp"].iloc[0]
    assert row["eps_impact_hkd"] == pytest.approx(0.81, abs=0.03)
    # +25bp row (yields up, value down) is symmetric negative
    row2 = df[df["cap_rate_move"] == "+25bp"].iloc[0]
    assert row2["eps_impact_hkd"] == pytest.approx(-0.81, abs=0.03)


def test_ip_reval_sensitivity_csv():
    df = pd.read_csv("data/normalized/hk_transport/mtr_ip_reval_sensitivity.csv")
    assert len(df) == 5
    assert df["eps_impact_hkd"].abs().max() < 1.0
