import pytest
import pandas as pd
from src.hk_transport.sources.mtr_historical_earnings_bridge import load_mtr_historical_earnings_bridge


def test_load_mtr_historical_earnings_bridge():
    df = load_mtr_historical_earnings_bridge()
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert len(df) >= 32  # 16 years x 2 half-years (2010 H1 to 2025 H2)
    assert "period" in df.columns
    assert "hk_transport_rev" in df.columns
    assert "recurrent_ebit" in df.columns
    assert "property_dev_profit" in df.columns
    assert "underlying_profit" in df.columns
    assert "underlying_eps" in df.columns
