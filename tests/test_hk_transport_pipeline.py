"""Unit tests for HK Transport sector pipeline."""

from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.pipeline import run_stage_1_pipeline
from src.hk_transport.sources.cathay_traffic import (
    _discover_cathay_traffic_pdfs,
    _extract_metrics_from_tables,
    _find_metric_tables,
    fetch_cathay_traffic,
)
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
    # Real archive-crawl discovery recovers Cathay traffic figures back to
    # Dec 2012 (filed Jan 2013) -- a ~10x improvement over the old
    # deterministic-URL-pattern floor of ~18 months. Threshold is set well
    # below the ~133 real months currently recoverable so the test tolerates
    # a handful of genuinely-missing announcement months without being
    # fragile to Cathay's own disclosure gaps.
    assert len(df) >= 100
    assert df["month"].min() < "2015-01"


def test_hk_transport_stage_1_execution():
    results = run_stage_1_pipeline()
    assert results is not None
    assert "mtr_patronage_monthly" in results
    assert "cathay_hkia_traffic_monthly" in results
    assert "td_private_car_first_reg_monthly" in results
    assert "td_first_registered_vehicle_details_monthly" in results
    assert "td_parking_vacancy_current" in results


def test_cathay_discover_traffic_pdfs_real_archive():
    """The archive-crawl discovery step should find real per-month PDF links
    (not guessed URLs), including months well before the old pipeline's
    deterministic-URL-pattern floor."""
    import requests

    session = requests.Session()
    entries = _discover_cathay_traffic_pdfs(session)
    assert len(entries) >= 100

    by_month = {e["month"]: e for e in entries}
    assert "2012-12" in by_month
    assert by_month["2012-12"]["url"].startswith("https://www.cathaypacific.com/")

    # The "Clarification Announcement July 2021 Traffic Figures" amendment
    # must not clobber the real "July 2021 Traffic Figures" primary entry.
    assert "2021-07" in by_month
    assert "clarification" not in by_month["2021-07"]["title"].lower()


@pytest.mark.parametrize(
    "header",
    [
        "CATHAY PACIFIC /\nDRAGONAIR COMBINED\nTRAFFIC",
        "CATHAY PACIFIC",
        "AIRLINES COMBINED\nTRAFFIC",
        "AIRLINES COMBINED\nCAPACITY",
    ],
)
def test_find_metric_tables_matches_all_known_headers(header):
    tables = [[[header, "col"], ["row", "val"]]]
    matched = _find_metric_tables(tables)
    assert len(matched) == 1


def test_find_metric_tables_ignores_unrelated_tables():
    tables = [[["Some Other Announcement", "col"], ["row", "val"]]]
    assert _find_metric_tables(tables) == []


def test_extract_metrics_pre2025_two_table_regional_layout():
    """2013-2024-era layout: two tables (TRAFFIC + CAPACITY), metrics on
    'RPK Total (000)' / 'ASK Total (000)' / 'Passengers carried' /
    'Passenger load factor' rows, mirroring a real downloaded 2023 PDF."""
    traffic_table = [
        ["CATHAY PACIFIC TRAFFIC", "MAY\n2023", "% Change", "Cumulative", "% Change"],
        ["- Chinese Mainland", "265,947", "1,018.0%", "1,130,586", "982.5%"],
        ["RPK Total (000)", "5,814,059", "1,664.0%", "26,135,475", "3,062.1%"],
        ["Passengers carried", "1,417,906", "2,345.4%", "6,267,779", "3,281.0%"],
    ]
    capacity_table = [
        ["CATHAY PACIFIC CAPACITY", "MAY\n2023", "% Change", "Cumulative", "% Change"],
        ["- Chinese Mainland", "367,522", "412.7%", "1,590,852", "292.8%"],
        ["ASK Total (000)", "6,828,143", "1,152.4%", "30,016,269", "1,785.7%"],
        ["Passenger load factor", "85.1%", "24.7%pt", "87.1%", "35.1%pt"],
    ]
    metrics = _extract_metrics_from_tables([traffic_table, capacity_table])
    assert metrics == {
        "cathay_rpk_thousands": 5814059.0,
        "cathay_passengers": 1417906.0,
        "cathay_ask_thousands": 6828143.0,
        "cathay_passenger_load_factor_pct": 85.1,
    }


def test_extract_metrics_2025_consolidated_layout():
    """Jan-2025-onward layout: one table with spelled-out labels."""
    table = [
        ["CATHAY PACIFIC", "JAN\n2025", "% Change", "Cumulative", "% Change"],
        ["Available Seat Kilometres\n(000)", "11,269,213", "30.9%", "11,269,213", "30.9%"],
        ["Revenue Passenger\nKilometres (000)", "9,732,981", "36.6%", "9,732,981", "36.6%"],
        ["Passengers carried", "2,352,242", "37.0%", "2,352,242", "37.0%"],
        ["Passenger load factor", "86.4%", "3.6%pt", "86.4%", "3.6%pt"],
    ]
    metrics = _extract_metrics_from_tables([table])
    assert metrics == {
        "cathay_ask_thousands": 11269213.0,
        "cathay_rpk_thousands": 9732981.0,
        "cathay_passengers": 2352242.0,
        "cathay_passenger_load_factor_pct": 86.4,
    }


def test_extract_metrics_missing_fields_returns_partial_dict():
    """When a table is missing rows, extraction should return only what it
    found -- callers (_parse_cathay_pdf) are responsible for treating an
    incomplete result as an honest exclusion, never fabricating values."""
    table = [
        ["CATHAY PACIFIC TRAFFIC", "col"],
        ["Passengers carried", "1,000"],
    ]
    metrics = _extract_metrics_from_tables([table])
    assert metrics == {"cathay_passengers": 1000.0}
