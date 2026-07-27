"""Tests for HK Stablecoin & Crypto pipeline."""

from __future__ import annotations

import pandas as pd
import pytest

from src.hk_stablecoin_crypto.config import HKEX_ETF_FUNDS, NAMING_COLLISION_NOTE
from src.hk_stablecoin_crypto.pipeline import run_stage_1_pipeline
from src.hk_stablecoin_crypto.sources.crypto_tickers import (
    compute_coinbase_premium,
    fetch_fear_greed_index,
)
from src.hk_stablecoin_crypto.sources.defillama_stablecoins import fetch_stablecoin_supply
from src.hk_stablecoin_crypto.sources.hkex_etf_aum import fetch_all_etf_aum
from src.hk_stablecoin_crypto.sources.hkma_register import fetch_licensed_issuers
from src.hk_stablecoin_crypto.sources.sfc_vatp_register import fetch_vatp_register


def test_fetch_hkma_register():
    df = fetch_licensed_issuers()
    assert not df.empty
    assert "issuer" in df.columns
    assert "licence_number" in df.columns
    assert "effective_date" in df.columns
    assert len(df) == 2
    
    # Verify exact licence numbers and clean issuer names
    licences = df["licence_number"].tolist()
    assert licences == ["FRS01", "FRS02"]
    
    issuers = df["issuer"].tolist()
    assert issuers[0] == "Anchorpoint Financial Limited"
    assert "The Hongkong and Shanghai Banking Corporation" in issuers[1]
    assert not any("Address:" in str(i) for i in issuers)


def test_anchorpoint_is_not_anchorx():
    df = fetch_licensed_issuers()
    issuers = df["issuer"].str.lower().tolist()
    assert not any("anchorx" in str(i) for i in issuers)


def test_fetch_sfc_vatp_register():
    df = fetch_vatp_register()
    assert not df.empty
    assert "status" in df.columns
    assert len(df["status"].unique()) >= 3
    
    licensed = df[df["status"] == "licensed"]["platform_name"].str.lower().tolist()
    assert any("osl" in str(p) for p in licensed)
    assert not any("guotai junan" in str(p) for p in licensed)
    assert len(licensed) >= 13

    # Forced closure count should be exactly 0 (no header/artifact rows)
    forced_closures = df[df["status"] == "forced_closure"]
    assert len(forced_closures) == 0


def test_fetch_stablecoin_supply():
    df = fetch_stablecoin_supply()
    assert not df.empty
    symbols = df["symbol"].tolist()
    assert "USDT" in symbols
    assert "USDC" in symbols
    assert df["circulating_usd"].sum() > 0


def test_hk_china_stablecoins_not_yet_listed():
    df = fetch_stablecoin_supply()
    symbols = df["symbol"].tolist()
    assert "AxCNH" not in symbols
    assert "HKDAP" not in symbols


def test_fetch_etf_aum_known_funds():
    df = fetch_all_etf_aum()
    assert not df.empty
    assert len(df["fund_id"].unique()) == 5
    assert df["aum_usd"].sum() > 0


def test_harvest_ether_fund_id_documented_as_unknown():
    harvest_ether = next(f for f in HKEX_ETF_FUNDS if "3179" in f["ticker"])
    assert harvest_ether["fund_id"] is None
    assert harvest_ether.get("needs_lookup") is True


def test_coinbase_premium_computation():
    res = compute_coinbase_premium()
    assert "coinbase_price_usd" in res
    assert "binance_price_usd" in res
    assert "premium_bps" in res
    if res["coinbase_price_usd"] is not None:
        assert res["coinbase_price_usd"] > 0
    if res["binance_price_usd"] is not None:
        assert res["binance_price_usd"] > 0


def test_fear_greed_index():
    res = fetch_fear_greed_index()
    assert "value" in res
    assert "classification" in res
    if res["value"] is not None:
        assert 0 <= res["value"] <= 100
        assert isinstance(res["classification"], str)
        assert len(res["classification"]) > 0


def test_polymarket_no_tag_param(monkeypatch):
    """Verify fetch_relevant_markets never sends a 'tag' query parameter.

    The tag= filter was confirmed unreliable in testing — only public-search
    with a keyword query should be used.
    """
    import unittest.mock as mock
    import src.hk_stablecoin_crypto.sources.polymarket_events as pm

    captured_kwargs: dict = {}

    def fake_get(url, **kwargs):
        captured_kwargs.update(kwargs)
        mock_resp = mock.MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = []
        return mock_resp

    monkeypatch.setattr("requests.get", fake_get)
    pm.fetch_relevant_markets("stablecoin")

    assert "params" in captured_kwargs, "requests.get must be called with params kwarg"
    assert "tag" not in captured_kwargs["params"], (
        "tag= parameter must NEVER be passed to Polymarket (confirmed unreliable in testing)"
    )


def test_pipeline_stage_1_execution():
    res = run_stage_1_pipeline()
    assert "hkma_licensed_issuers" in res
    assert "sfc_vatp_register" in res
    assert "stablecoin_supply" in res
    assert "hkex_etf_aum" in res
    assert "crypto_signals" in res
    assert "polymarket_catalysts" in res


def test_naming_collision_note_in_config():
    assert "Anchorpoint" in NAMING_COLLISION_NOTE
    assert "AnchorX" in NAMING_COLLISION_NOTE
