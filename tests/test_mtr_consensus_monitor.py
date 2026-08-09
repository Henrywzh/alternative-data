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
