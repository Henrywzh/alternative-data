"""Unit tests for HK Telecom sector pipeline."""

from __future__ import annotations

import pandas as pd
import pytest

from src.hk_telecom.pipeline import run_stage_1_pipeline
from src.hk_telecom.sources.hkt_operating_drivers import fetch_hkt_operating_drivers


def test_fetch_hkt_operating_drivers():
    df = fetch_hkt_operating_drivers()
    assert not df.empty
    assert "period" in df.columns
    assert "mobile_postpaid_subscribers_thousands" in df.columns
    assert "mobile_postpaid_arpu_hkd" in df.columns
    assert len(df) >= 5


def test_hk_telecom_stage_1_execution():
    results = run_stage_1_pipeline()
    assert results is not None
    assert "hkt_operating_drivers_semi_annual" in results
