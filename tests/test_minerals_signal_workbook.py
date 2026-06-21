from __future__ import annotations

from pathlib import Path

import openpyxl
import pandas as pd

from minerals_signal_data.workbook import (
    build_price_universe,
    load_critical_minerals,
    load_expanded_stock_mapping,
    normalize_mineral_id,
    normalize_ticker,
)


def _write_fixture_workbook(path: Path) -> None:
    workbook = openpyxl.Workbook()
    critical = workbook.active
    critical.title = "Critical minerals"
    critical.append(
        [
            "Importance rank (computed)",
            "Importance tier",
            "Mineral",
            "2025 U.S. net import reliance",
            "NIR_numeric_for_sort",
            "Strategic application bucket",
            "Applications (USGS Table 6)",
            "importance_score",
            "Source / note",
        ]
    )
    critical.append(
        [1, "Tier 1 - highest", "Tantalum", "100%", 100, "Semiconductors/electronics", "Capacitors.", 115, "note"]
    )
    critical.append(
        [2, "Tier 1 - highest", "Graphite", "100%", 100, "Battery/energy transition", "Batteries.", 110, "note"]
    )
    critical.append(
        [3, "Tier 2 - very high", "Copper", "45%", 45, "Industrial/other", "Wiring.", 90, "note"]
    )
    critical.append(
        [4, "Tier 3 - high", "Gallium", "100%", 100, "Semiconductors/electronics", "ICs.", 100, "note"]
    )

    stock = workbook.create_sheet("Stock mapping")
    stock.append(
        [
            "Importance rank",
            "Tier",
            "Mineral",
            "2025 U.S. net import reliance",
            "Applications",
            "Strategic application bucket",
            "China A-share / HK related stocks",
            "US-listed related stocks",
            "Exposure purity",
            "Mapping note",
            "Source URL / evidence",
        ]
    )
    stock.append(
        [
            1,
            "Tier 1 - highest",
            "Tantalum",
            "100%",
            "Capacitors.",
            "Semiconductors/electronics",
            "Ningxia Orient Tantalum 000962.SZ; China Tungsten & Hightech 000657.SZ",
            "No clean US-listed producer; NioCorp NB is niobium/scandium adjacent",
            "Primary for 000962; secondary/adjacent for 000657/NB",
            "Closest listed proxy.",
            None,
        ]
    )
    stock.append(
        [
            2,
            "Tier 1 - highest",
            "Graphite",
            "100%",
            "Batteries.",
            "Battery/energy transition",
            "China Graphite 2237.HK; BTR New Material 835185.BJ",
            "Nouveau Monde Graphite NMG; Westwater Resources WWR",
            "Primary for 2237/NMG/WWR; battery-anode downstream for BTR",
            "Separate natural graphite from downstream.",
            None,
        ]
    )
    stock.append(
        [
            3,
            "Tier 2 - very high",
            "Copper",
            "45%",
            "Wiring.",
            "Industrial/other",
            "Jiangxi Copper 600362.SH / 0358.HK; Tongling Nonferrous 000630.SZ",
            "Freeport-McMoRan FCX",
            "Primary/secondary",
            "Diversified copper exposure.",
            None,
        ]
    )

    workbook.save(path)


def test_normalize_ticker_handles_us_hk_and_a_share_formats() -> None:
    assert normalize_ticker("FCX") == ("FCX", "US")
    assert normalize_ticker("000962.SZ") == ("000962.SZ", "CN_A")
    assert normalize_ticker("600362.SH") == ("600362.SH", "CN_A")
    assert normalize_ticker("835185.BJ") == ("835185.BJ", "CN_A")
    assert normalize_ticker("0358.HK") == ("0358.HK", "HK")


def test_load_expanded_stock_mapping_explodes_semicolon_and_dual_listing_cells(tmp_path: Path) -> None:
    workbook_path = tmp_path / "critical_minerals.xlsx"
    _write_fixture_workbook(workbook_path)

    frame = load_expanded_stock_mapping(workbook_path)

    assert set(frame["ticker_normalized"]) == {
        "000962.SZ",
        "000657.SZ",
        "NB",
        "2237.HK",
        "835185.BJ",
        "NMG",
        "WWR",
        "600362.SH",
        "0358.HK",
        "000630.SZ",
        "FCX",
    }
    assert "No clean US-listed producer" not in set(frame["ticker_raw"])
    assert frame.loc[frame["ticker_normalized"] == "000962.SZ", "is_primary_exposure"].iloc[0]
    assert not frame.loc[frame["ticker_normalized"] == "000657.SZ", "is_primary_exposure"].iloc[0]
    assert frame.loc[frame["ticker_normalized"] == "0358.HK", "market"].iloc[0] == "HK"
    assert frame.loc[frame["ticker_normalized"] == "600362.SH", "market"].iloc[0] == "CN_A"


def test_build_price_universe_marks_direct_proxy_and_unsupported_minerals(tmp_path: Path) -> None:
    workbook_path = tmp_path / "critical_minerals.xlsx"
    _write_fixture_workbook(workbook_path)

    minerals = load_critical_minerals(workbook_path)
    frame = build_price_universe(minerals)

    expected = {
        "tantalum": ("direct", "investing_html", True),
        # graphite is a proxy mineral now pointed at a reliable free instrument
        # (LIT, lithium ETF) instead of the dead manual_proxy placeholder.
        "graphite": ("proxy", "yfinance_futures", True),
        "copper": ("direct", "yfinance_futures", True),
        "gallium": ("direct", "investing_html", True),
    }

    for mineral_id, (grade, source_type, active) in expected.items():
        row = frame.loc[frame["normalized_mineral_id"] == mineral_id].iloc[0]
        assert row["trackability_grade"] == grade
        assert row["price_source_type"] == source_type
        assert bool(row["is_active_for_v1"]) is active


def test_load_critical_minerals_preserves_workbook_rank_columns(tmp_path: Path) -> None:
    workbook_path = tmp_path / "critical_minerals.xlsx"
    _write_fixture_workbook(workbook_path)

    frame = load_critical_minerals(workbook_path)

    assert list(frame["mineral_name"]) == ["Tantalum", "Graphite", "Copper", "Gallium"]
    assert list(frame["normalized_mineral_id"]) == [
        normalize_mineral_id("Tantalum"),
        normalize_mineral_id("Graphite"),
        normalize_mineral_id("Copper"),
        normalize_mineral_id("Gallium"),
    ]
    assert pd.api.types.is_integer_dtype(frame["importance_rank"])
