"""Unit tests for HK Transport sector pipeline."""

from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.pipeline import run_stage_1_pipeline
from src.hk_transport.sources.cathay_traffic import fetch_cathay_traffic
from src.hk_transport.sources.mtr_patronage import fetch_mtr_patronage


def test_fetch_mtr_patronage():
    df = fetch_mtr_patronage()
    assert not df.empty
    assert "month" in df.columns
    assert "domestic_service_thousands" in df.columns
    assert "cross_boundary_thousands" in df.columns
    assert "total_mtr_patronage_thousands" in df.columns
    assert len(df) >= 6


def test_fetch_cathay_traffic():
    df = fetch_cathay_traffic()
    assert not df.empty
    assert "hkia_passengers" in df.columns
    assert "cathay_passengers" in df.columns
    assert "cathay_passenger_load_factor_pct" in df.columns
    assert len(df) >= 10


def test_hk_transport_stage_1_execution():
    results = run_stage_1_pipeline()
    assert results is not None
    assert "mtr_patronage_monthly" in results
    assert "cathay_hkia_traffic_monthly" in results
