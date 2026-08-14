"""Unit tests for HK Utilities sector pipeline."""

from __future__ import annotations

import requests
import pandas as pd
import pytest

from src.hk_utilities.pipeline import run_stage_1_pipeline
from src.hk_utilities.sources.clp_electricity import fetch_clp_electricity
from src.hk_utilities.sources.hko_temperature import fetch_hko_temperature
from src.hk_utilities.sources.power_assets_segments import fetch_power_assets_segments
from src.hk_utilities.sources.towngas_proxy import fetch_towngas_proxy


def test_fetch_clp_electricity():
    df = fetch_clp_electricity()
    assert not df.empty
    assert "quarter" in df.columns
    assert "commercial_gwh" in df.columns
    assert "total_local_gwh" in df.columns
    assert "ai_data_centre_yoy_pct" in df.columns
    # CLP only publishes a standalone Q1 "Quarterly Statement" (other
    # quarters are cumulative/narrative-only and intentionally excluded to
    # avoid fabricating a discrete quarter's figures) -- so history is one
    # real, parsed row per year since 2023, not a fixed large count.
    assert len(df) >= 3


def test_fetch_towngas_proxy():
    df = fetch_towngas_proxy()
    assert not df.empty
    assert "month" in df.columns
    assert "domestic_gas_tj" in df.columns
    assert "commercial_gas_tj" in df.columns
    assert "total_gas_tj" in df.columns
    assert len(df) >= 50


def test_fetch_hko_temperature():
    try:
        df = fetch_hko_temperature()
    except requests.RequestException as exc:
        pytest.skip(f"HKO temperature API unavailable in this environment: {exc}")
    assert not df.empty
    assert "mean_temp_c" in df.columns
    assert "month_avg_temp_c" in df.columns
    assert len(df) >= 100


def test_fetch_power_assets_segments():
    df = fetch_power_assets_segments()
    assert not df.empty
    assert "period" in df.columns
    assert "revenue_uk_hkdm" in df.columns
    assert "revenue_australia_hkdm" in df.columns
    assert "segment_profit_total_hkdm" in df.columns
    assert "jv_associate_results_total_hkdm" in df.columns
    # Semi-annual disclosure -- expect at least the one currently-published
    # H1 period, not a large history.
    assert len(df) >= 1


def test_hk_utilities_stage_1_execution():
    results = run_stage_1_pipeline()
    assert results is not None
    assert "clp_electricity_quarterly" in results
    assert "towngas_proxy_gas_monthly" in results
    assert "hko_mean_temperature_daily" in results
    assert "power_assets_segments_semiannual" in results
    assert "dsd_sewage_flow_lab_daily" in results
    assert "wsd_water_suspension_events" in results
