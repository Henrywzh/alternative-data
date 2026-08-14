"""Unit tests for HK Transport sector pipeline."""

from __future__ import annotations

import os

import pandas as pd
import pytest

from src.hk_transport.pipeline import run_stage_1_pipeline
from src.hk_transport.sources.cathay_traffic import (
    _discover_cathay_traffic_pdfs,
    _extract_metrics_from_tables,
    _find_metric_tables,
    fetch_cathay_traffic,
)
from src.hk_transport.sources.cathay_fleet import _parse_fleet_profile
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
    for field in (
        "cathay_cargo_tonnes",
        "cathay_aftk_thousands",
        "cathay_rftk_thousands",
        "cathay_cargo_load_factor_pct",
        "cathay_flight_sectors",
    ):
        assert field in df.columns
        assert df[field].notna().sum() >= 100
    # Real archive-crawl discovery recovers Cathay traffic figures back to
    # Dec 2012 (filed Jan 2013) -- a ~10x improvement over the old
    # deterministic-URL-pattern floor of ~18 months. Threshold is set well
    # below the ~133 real months currently recoverable so the test tolerates
    # a handful of genuinely-missing announcement months without being
    # fragile to Cathay's own disclosure gaps.
    assert len(df) >= 100
    assert df["month"].min() < "2015-01"


@pytest.mark.skipif(
    os.getenv("GITHUB_ACTIONS", "").lower() == "true",
    reason="live HK Transport stage-1 integration test is not deterministic on GitHub runners",
)
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
        "CATHAY CARGO",
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


def test_extract_metrics_cargo_and_flight_fields():
    tables = [
        [
            ["CATHAY PACIFIC", "MAY 2026", "% Change"],
            ["Revenue Passenger Kilometres (000)", "10,988,053", "13.1%"],
            ["Number of passenger flight sectors", "10,645", "12.4%"],
        ],
        [
            ["CATHAY CARGO", "MAY 2026", "% Change"],
            ["Available Freight Tonne Kilometres (000)", "1,310,668", "6.1%"],
            ["Revenue Freight Tonne Kilometres (000)", "783,148", "6.7%"],
            ["Number of freighter flight sectors", "1,272", "0.6%"],
            ["Cargo carried (000kg)", "150,089", "10.5%"],
            ["Cargo load factor", "59.8%", "0.3%pt"],
        ],
    ]
    metrics = _extract_metrics_from_tables(tables)
    assert metrics == {
        "cathay_rpk_thousands": 10988053.0,
        "cathay_aftk_thousands": 1310668.0,
        "cathay_rftk_thousands": 783148.0,
        "cathay_passenger_flight_sectors": 10645.0,
        "cathay_freighter_flight_sectors": 1272.0,
        "cathay_cargo_tonnes": 150089.0,
        "cathay_cargo_load_factor_pct": 59.8,
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


def test_parse_fleet_profile_preserves_published_dash_columns():
    """Fleet Profile rows use dashes for zero owned/leased aircraft; dashes
    must not shift the fourth (total fleet) column left."""
    import src.hk_transport.sources.cathay_fleet as fleet_source

    class FakePage:
        def extract_text(self):
            return "\n".join(
                [
                    "FLEET PROFILE",
                    "The Company (Passenger aircraft):",
                    "Total of the",
                    "Company 133 24 23 180 11.8",
                    "HK Express:",
                    "Total 10 7 24 41 7.1",
                    "Air Hong Kong:",
                    "Total - - 15 15 14.1",
                    "Grand total 143 31 62 236 11.1",
                ]
            )

    class FakePdf:
        pages = [FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(fleet_source.pdfplumber, "open", lambda _: FakePdf())
    try:
        parsed = _parse_fleet_profile(b"%PDF-fake", "2024-12-31", "annual", "https://example.test/report.pdf")
    finally:
        monkeypatch.undo()
    values = dict(zip(parsed["scope"], parsed["fleet_total_aircraft"]))
    assert values == {"Company": 180.0, "HK Express": 41.0, "Air Hong Kong": 15.0, "Grand total": 236.0}
