import pandas as pd
import pytest
from scripts.mtr_ip_reval_nowcast import IP_VALUE, CAP_RATE, CALIBRATION, SHARES_M, AFTER_TAX


def test_unit_conversion_and_calibration():
    """-21bp YTD at 0.42 calibration -> ~+2,163m pre-tax, EPS +0.29."""
    ytd_bp = -21.0
    reval = -IP_VALUE * (ytd_bp / 10000.0) / CAP_RATE * CALIBRATION
    assert reval == pytest.approx(2163.0, abs=10.0)
    eps = reval * AFTER_TAX / SHARES_M
    assert eps == pytest.approx(0.29, abs=0.01)


def test_nowcast_csv_shape():
    df = pd.read_csv("data/normalized/hk_transport/mtr_ip_reval_nowcast.csv")
    assert len(df) >= 350  # 1997-01 .. 2026-05
    assert "ip_reval_calibrated_hkdm" in df.columns
    assert "eps_impact_hkd" in df.columns
    # monthly single-bp moves stay bounded (sanity)
    assert df["eps_impact_hkd"].abs().max() < 1.0


def test_calibration_anchor_2024():
    """FY2024: +37bp CRI -> official -3,821m loss; factor ~0.42."""
    raw = IP_VALUE * (37 / 10000.0) / CAP_RATE
    factor = 3821.0 / raw
    assert factor == pytest.approx(CALIBRATION, abs=0.02)
