import pytest
import pandas as pd
from src.hk_transport.sources.mtr_historical_earnings_bridge import load_mtr_historical_earnings_bridge


def test_load_mtr_historical_earnings_bridge():
    df = load_mtr_historical_earnings_bridge()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 16  # FY2010 - FY2025
    assert list(df["year"]) == list(range(2010, 2026))
    assert "underlying_profit" in df.columns
    assert "reported_npat" in df.columns
    assert "hk_pdp_post_tax" in df.columns
    assert "recurrent_post_tax_profit" in df.columns


@pytest.mark.parametrize(
    "year,column,expected",
    [
        (2025, "reported_npat", 14677),
        (2025, "hk_transport_rev", 23595),
        (2025, "total_revenue", 55465),
        (2024, "reported_npat", 15772),
        (2024, "hk_transport_rev", 23013),
        (2024, "total_revenue", 60011),
        (2020, "reported_npat", -4809),
        (2017, "reported_npat", 16829),
        (2019, "hk_transport_rev", 19938),
        (2023, "eps_basic", 1.26),
    ],
)
def test_official_anchor_values(year, column, expected):
    df = load_mtr_historical_earnings_bridge()
    row = df[df["year"] == year].iloc[0]
    assert row[column] == pytest.approx(expected, abs=0.01)


def test_underlying_reconciles_to_recurrent_plus_property_dev():
    """Official definition: underlying = recurrent post-tax + property development post-tax."""
    df = load_mtr_historical_earnings_bridge()
    check = df[df["year"] >= 2014]
    assert len(check) == 12
    for _, r in check.iterrows():
        assert r["underlying_profit"] == pytest.approx(
            r["recurrent_post_tax_profit"] + r["hk_pdp_post_tax"], abs=1.0
        )


def test_fy2025_live_oos_transport_revenue_anchor():
    """FY2025 HK transport ops revenue must match the reported figure used in the farebox
    nowcast validation (23,595)."""
    df = load_mtr_historical_earnings_bridge()
    assert df[df["year"] == 2025]["hk_transport_rev"].iloc[0] == pytest.approx(23595.0)
