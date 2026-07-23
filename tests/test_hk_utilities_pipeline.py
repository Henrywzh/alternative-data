"""Unit tests for HK Utilities sector pipeline."""

from __future__ import annotations

import pandas as pd
import pytest

from src.hk_utilities.pipeline import run_stage_1_pipeline
from src.hk_utilities.sources.clp_electricity import fetch_clp_electricity
from src.hk_utilities.sources.hko_temperature import fetch_hko_temperature
from src.hk_utilities.sources.towngas_proxy import fetch_towngas_proxy


def test_fetch_clp_electricity():
    df = fetch_clp_electricity()
    assert not df.empty
    assert "quarter" in df.columns
    assert "commercial_gwh" in df.columns
    assert "total_local_gwh" in df.columns
    assert "ai_data_centre_yoy_pct" in df.columns
    assert len(df) >= 10


def test_fetch_towngas_proxy():
    df = fetch_towngas_proxy()
    assert not df.empty
    assert "month" in df.columns
    assert "domestic_gas_tj" in df.columns
    assert "commercial_gas_tj" in df.columns
    assert "total_gas_tj" in df.columns
    assert len(df) >= 50


def test_fetch_hko_temperature():
    df = fetch_hko_temperature()
    assert not df.empty
    assert "mean_temp_c" in df.columns
    assert "month_avg_temp_c" in df.columns
    assert len(df) >= 100


def test_hk_utilities_stage_1_execution():
    results = run_stage_1_pipeline()
    assert results is not None
    assert "clp_electricity_quarterly" in results
    assert "towngas_proxy_gas_monthly" in results
    assert "hko_mean_temperature_daily" in results
