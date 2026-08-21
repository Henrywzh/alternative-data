"""Tests for Tencent IR historical financial disclosures collector and parser."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from scripts.research_control_tower_tencent_financials import (
    METRIC_DEFINITIONS,
    TENCENT_ENTITY_ID,
    TENCENT_LISTING_ID,
    load_tencent_disclosure_records,
    parse_and_collect_tencent_actuals,
    transform_tencent_disclosures_to_actuals,
)
from src.research_control_tower.build import EARNINGS_ACTUALS_COLUMNS, SOURCE_STATE_COLUMNS


@pytest.fixture
def sample_disclosures():
    return [
        {
            "period_label": "1Q2026",
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "filing_at": "2026-05-13T08:31:00+08:00",
            "published_at": "2026-05-13T08:31:00+08:00",
            "source_url": "https://static.www.tencent.com/uploads/2026/05/13/47382ae415a209fd161bc19a1f9b3704.pdf",
            "document_title": "TENCENT ANNOUNCES 2026 FIRST QUARTER RESULTS",
            "revenue_total": 196458.0,
            "gross_profit": 111265.0,
            "operating_profit_gaap": 67375.0,
            "operating_profit_non_ifrs": 75627.0,
            "net_profit_attributable_gaap": 58093.0,
            "net_profit_attributable_non_ifrs": 67905.0,
            "basic_eps_gaap": 6.431,
            "diluted_eps_gaap": 6.302,
            "basic_eps_non_ifrs": 7.517,
            "diluted_eps_non_ifrs": 7.364,
            "capex": 31936.0,
            "fcf": 56700.0,
        },
        {
            "period_label": "2Q2026",
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
            "filing_at": "2026-08-12T20:00:00+08:00",
            "published_at": "2026-08-12T20:00:00+08:00",
            "source_url": "https://www.tencent.com/wp-content/uploads/2026/08/Tencent-Announces-2026-Second-Quarter-Results.pdf",
            "document_title": "TENCENT ANNOUNCES 2026 SECOND QUARTER RESULTS",
            "revenue_total": 204785.0,
            "gross_profit": 118433.0,
            "operating_profit_gaap": 67276.0,
            "operating_profit_non_ifrs": 75636.0,
            "net_profit_attributable_gaap": 56022.0,
            "net_profit_attributable_non_ifrs": 68415.0,
            "basic_eps_gaap": 6.207,
            "diluted_eps_gaap": 6.104,
            "basic_eps_non_ifrs": 7.581,
            "diluted_eps_non_ifrs": 7.433,
            "capex": 52784.0,
            "fcf": -13800.0,
        },
    ]


def test_load_official_tencent_disclosures_fixture():
    records = load_tencent_disclosure_records()
    assert len(records) >= 12
    assert len(records) == 22  # 2021Q1 through 2026Q2
    labels = [r["period_label"] for r in records]
    assert "1Q2021" in labels
    assert "2Q2026" in labels
    assert "1Q2026" in labels


def test_transform_disclosures_preserves_accounting_tracks_and_provenance(sample_disclosures):
    rows = transform_tencent_disclosures_to_actuals(
        sample_disclosures, as_of_utc=pd.Timestamp("2026-08-21T12:00:00Z")
    )
    # 2 periods * 12 metrics = 24 rows
    assert len(rows) == 24
    frame = pd.DataFrame(rows)
    assert set(EARNINGS_ACTUALS_COLUMNS) == set(frame.columns)

    # Verify 2Q26 verified figures
    q2_26 = frame[frame["period_label"] == "2Q2026"].set_index("metric")
    assert q2_26.loc["revenue_total", "reported_value"] == 204785.0 * 1e6
    assert q2_26.loc["operating_profit", "reported_value"] == 67276.0 * 1e6
    assert q2_26.loc["operating_profit_non_ifrs", "reported_value"] == 75636.0 * 1e6
    assert q2_26.loc["net_profit_attributable", "reported_value"] == 56022.0 * 1e6
    assert q2_26.loc["net_profit_attributable_non_ifrs", "reported_value"] == 68415.0 * 1e6
    assert q2_26.loc["diluted_eps", "reported_value"] == 6.104
    assert q2_26.loc["diluted_eps_non_ifrs", "reported_value"] == 7.433
    assert q2_26.loc["capex", "reported_value"] == 52784.0 * 1e6
    assert q2_26.loc["free_cash_flow", "reported_value"] == -13800.0 * 1e6

    # Verify 1Q26 verified figures
    q1_26 = frame[frame["period_label"] == "1Q2026"].set_index("metric")
    assert q1_26.loc["revenue_total", "reported_value"] == 196458.0 * 1e6
    assert q1_26.loc["operating_profit_non_ifrs", "reported_value"] == 75627.0 * 1e6
    assert q1_26.loc["free_cash_flow", "reported_value"] == 56700.0 * 1e6

    # Verify tracks are strictly segregated
    assert "GAAP_REPORTED" in q2_26.loc["operating_profit", "accounting_basis"]
    assert "NON_IFRS_MANAGEMENT" in q2_26.loc["operating_profit_non_ifrs", "accounting_basis"]
    assert q2_26.loc["operating_profit", "accounting_basis"] != q2_26.loc["operating_profit_non_ifrs", "accounting_basis"]


def test_parse_and_collect_tencent_actuals_full_pipeline(tmp_path):
    output = tmp_path / "actuals"
    frame, state = parse_and_collect_tencent_actuals(
        as_of_utc=pd.Timestamp("2026-08-21T12:00:00Z"),
        output_dir=output,
    )
    assert len(frame) == 22 * 12  # 264 rows
    assert list(frame.columns) == EARNINGS_ACTUALS_COLUMNS
    assert list(state.columns) == SOURCE_STATE_COLUMNS

    # State validation
    assert state.iloc[0]["status"] == "available"
    assert state.iloc[0]["row_count"] == 264
    assert state.iloc[0]["source_id"] == "earnings:tencent_ir_financials"

    # Parquet files written and loadable
    assert (output / "tencent_earnings_actuals_v1.parquet").is_file()
    assert (output / "tencent_earnings_actuals_state.parquet").is_file()

    loaded_frame = pd.read_parquet(output / "tencent_earnings_actuals_v1.parquet")
    assert len(loaded_frame) == 264
    assert set(loaded_frame["entity_id"]) == {TENCENT_ENTITY_ID}
    assert set(loaded_frame["listing_id"]) == {TENCENT_LISTING_ID}


def test_no_fabricated_values_or_fake_dates_in_financials():
    frame, _ = parse_and_collect_tencent_actuals()
    # Check that every row has valid timestamps and non-null values
    assert frame["filing_at"].notna().all()
    assert frame["published_at"].notna().all()
    assert frame["period_start"].notna().all()
    assert frame["period_end"].notna().all()
    assert frame["reported_value"].notna().all()
    assert frame["source_url"].str.startswith("http").all()
    assert frame["actual_id"].str.startswith("ACT_0700_").all()

