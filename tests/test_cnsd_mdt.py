import pytest
import pandas as pd
from src.common.cnsd_mdt import fetch_cnsd_table


def test_fetch_cnsd_table_construction():
    df = fetch_cnsd_table("615-66001")
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "value" in df.columns
    assert "period" in df.columns
    assert df.attrs.get("data_source") in ("live", "fallback_sample")


def test_fetch_cnsd_table_visitors():
    df = fetch_cnsd_table("650-80001")
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "value" in df.columns
    assert df.attrs.get("data_source") in ("live", "fallback_sample")


def test_fetch_cnsd_table_port_containers():
    df = fetch_cnsd_table("410-55294")
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "value" in df.columns
    assert df.attrs.get("data_source") in ("live", "fallback_sample")
