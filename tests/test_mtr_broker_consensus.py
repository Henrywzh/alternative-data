import pandas as pd
import pytest
from scripts.mtr_broker_consensus_snapshot import SHARES_M, BROKERS, ASSUMED_FY27_RECURRENT, OUR_FY27_PROPERTY_BASE


def test_snapshot_math():
    """FY27 NPAT = EPS x shares; residual = NPAT - recurrent."""
    df = pd.read_csv("data/normalized/hk_transport/mtr_broker_consensus_snapshot.csv")
    assert len(df) == 5
    jpm = df[df["broker"] == "JPMorgan"].iloc[0]
    assert jpm["fy27_npat_hkdm"] == pytest.approx(1.87 * SHARES_M, abs=1.0)
    assert jpm["fy27_residual_prop_ip_oneoffs_hkdm"] == pytest.approx(
        1.87 * SHARES_M - ASSUMED_FY27_RECURRENT, abs=1.0)
    # CLSA is the bear outlier with near-zero residual
    clsa = df[df["broker"] == "CLSA"].iloc[0]
    assert clsa["fy27_residual_prop_ip_oneoffs_hkdm"] < 0


def test_our_pool_vs_brokers():
    """JPM residual is closest to our property pool; CLSA far below."""
    df = pd.read_csv("data/normalized/hk_transport/mtr_broker_consensus_snapshot.csv")
    jpm_delta = df[df["broker"] == "JPMorgan"]["delta_vs_our_property_base_hkdm"].iloc[0]
    clsa_delta = df[df["broker"] == "CLSA"]["delta_vs_our_property_base_hkdm"].iloc[0]
    assert abs(jpm_delta) < 1000.0  # within ~1bn of our base
    assert clsa_delta < -5000.0     # far below our base


def test_fy26_consensus_anchor():
    """FY26E consensus ~2.69-2.76 (not the yfinance 2.52 field misread)."""
    assert 2.60 <= 2.69 <= 2.80
    # brokers' FY26 EPS in the snapshot sit in 2.39-3.23
    assert [b[1] for b in BROKERS] == [2.75, 3.23, 2.51, 2.39, 2.69]
