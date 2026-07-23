"""Unit tests for HK Telecom sector pipeline.

These tests hit live, public filings/endpoints (HKT's, SmarTone's, and
Hutchison Telecom's own investor-relations sites, plus OFCA's numbering
plan CSV) -- there is no mock/fixture layer for this sector, matching the
existing hk_transport/hk_utilities test style. A network failure or a
source changing its filing format will surface here as a real, actionable
test failure rather than being masked by fabricated data.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.hk_telecom.pipeline import run_stage_1_pipeline
from src.hk_telecom.sources.hkt_operating_drivers import fetch_hkt_operating_drivers
from src.hk_telecom.sources.hutchison_telecom_operating_drivers import fetch_hutchison_telecom_operating_drivers
from src.hk_telecom.sources.numbering_plan import fetch_numbering_plan
from src.hk_telecom.sources.smartone_operating_drivers import fetch_smartone_operating_drivers


def test_fetch_hkt_operating_drivers():
    df = fetch_hkt_operating_drivers()
    assert not df.empty
    assert "period" in df.columns
    assert "mobile_postpaid_subscribers_thousands" in df.columns
    assert "mobile_postpaid_arpu_hkd" in df.columns
    assert len(df) >= 2
    # Postpaid subscribers should be in the millions-of-thousands range for
    # HKT (~3.4-3.5 million), not zero/placeholder.
    assert df["mobile_postpaid_subscribers_thousands"].dropna().gt(1000).all()
    assert df["mobile_postpaid_arpu_hkd"].dropna().gt(0).all()


def test_fetch_smartone_operating_drivers():
    df = fetch_smartone_operating_drivers()
    assert not df.empty
    assert "postpaid_subscribers_thousands" in df.columns
    assert "postpaid_arpu_hkd" in df.columns
    assert df["postpaid_subscribers_thousands"].dropna().gt(1000).all()
    assert df["postpaid_arpu_hkd"].dropna().gt(0).all()


def test_fetch_hutchison_telecom_operating_drivers():
    df = fetch_hutchison_telecom_operating_drivers()
    assert not df.empty
    assert "postpaid_customers_thousands" in df.columns
    assert "postpaid_gross_arpu_hkd" in df.columns
    assert "postpaid_net_arpu_hkd" in df.columns
    assert df["postpaid_customers_thousands"].dropna().gt(500).all()
    # Gross ARPU should always be >= net ARPU (gross precedes net-of-cost margin).
    both = df.dropna(subset=["postpaid_gross_arpu_hkd", "postpaid_net_arpu_hkd"])
    assert not both.empty
    assert (both["postpaid_gross_arpu_hkd"] >= both["postpaid_net_arpu_hkd"]).all()


def test_fetch_numbering_plan():
    df = fetch_numbering_plan()
    assert not df.empty
    assert set(["allocatee", "num_blocks", "total_numbers_allocated"]).issubset(df.columns)
    # All 4 licensed MNOs must be present (this is the whole point of this
    # proxy -- it is genuinely all-operator, unlike the per-operator ARPU
    # filings above).
    allocatees = set(df["allocatee"])
    for expected in ["HKT", "China Mobile Hong Kong (CMHK)", "Hutchison Telephone (3 HK)", "SmarTone"]:
        assert expected in allocatees
    assert df["total_numbers_allocated"].gt(0).all()
    # HKT should hold the largest allocation, consistent with the known
    # real-world subscriber-share ordering (HKT > CMHK > Hutchison > SmarTone).
    top = df.sort_values("total_numbers_allocated", ascending=False).iloc[0]
    assert top["allocatee"] == "HKT"


def test_hk_telecom_stage_1_execution():
    results = run_stage_1_pipeline()
    assert results is not None
    for key in (
        "hkt_operating_drivers_semi_annual",
        "smartone_operating_drivers_semi_annual",
        "hutchison_telecom_operating_drivers_semi_annual",
        "numbering_plan_snapshot",
    ):
        assert key in results
        assert isinstance(results[key], pd.DataFrame), f"{key} failed: {results[key]}"
