import pytest
import pandas as pd

from src.hk_local_consumer.sources.consumer_council_pricewatch import fetch_consumer_council_pricewatch
from src.hk_local_consumer.sources.consumer_council_oilprice import fetch_consumer_council_oilprice
from src.hk_local_consumer.sources.consumer_council_complaints import fetch_consumer_council_complaints


def test_fetch_consumer_council_pricewatch():
    df = fetch_consumer_council_pricewatch()
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "price" in df.columns
    assert "category_1" in df.columns
    assert df.attrs.get("data_source") in ("live", "fallback_sample")


def test_fetch_consumer_council_oilprice():
    df = fetch_consumer_council_oilprice()
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "discounted_price_hkd" in df.columns
    assert "company" in df.columns
    assert df.attrs.get("data_source") in ("live", "fallback_sample")


def test_fetch_consumer_council_complaints():
    df = fetch_consumer_council_complaints()
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "amount" in df.columns
    assert "category" in df.columns
    assert df.attrs.get("data_source") in ("live", "fallback_sample")
