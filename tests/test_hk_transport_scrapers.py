"""Regression tests for the three HK Transport Department scrapers.

An earlier version of scrape_hk_passenger_journeys.py and
scrape_hk_vehicle_stock.py each mapped a fixed positional column index (or
sheet index) to a field name without ever validating it against the file's
own header text -- and both were wrong. Confirmed against a fresh fetch of
the live TD workbooks: every column in the passenger-journeys output held a
different operator's data than its own name claimed (the column named MTR
heavy rail held KMB's bus figures, "total" held Citybus's own subtotal), and
the vehicle-stock script read sheet index 0 (Motor Cycles) while labelling
the output "private_cars_registered" -- real private car stock is
~630k-650k, not the ~110k the script reported.

These tests exercise the two guards added to prevent that recurring
silently: the header-keyword check (a column's own header text must contain
its expected keyword) and the arithmetic-identity check (every subtotal TD
publishes must reconcile against its own stated parts). Both are tested
positively (pass on real header text / consistent numbers) and negatively
(deliberately broken input must raise), since a guard that cannot be shown
to fail is not verified to guard anything.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _header_df(column_texts: dict[int, str], ncols: int) -> pd.DataFrame:
    """A minimal frame whose header block (rows 0-9) carries the given text
    at the given column indices, matching the shape _header_text() scans."""
    rows = {c: [column_texts.get(c, None)] + [None] * 9 for c in range(ncols)}
    return pd.DataFrame(rows)


# --- scrape_hk_passenger_journeys.py -----------------------------------


def test_passenger_journeys_header_validation_passes_on_real_header_text():
    m = _load("scrape_hk_passenger_journeys.py", "pj_header_ok_test")
    ncols = max(m.SHEET_A_COLUMNS) + 1
    df = _header_df({col: keyword for col, (_field, keyword) in m.SHEET_A_COLUMNS.items()}, ncols)
    m._validate_headers(df, m.SHEET_A_COLUMNS, "sheet a")  # must not raise


def test_passenger_journeys_header_validation_rejects_shifted_column():
    m = _load("scrape_hk_passenger_journeys.py", "pj_header_bad_test")
    ncols = max(m.SHEET_A_COLUMNS) + 1
    columns = {col: keyword for col, (_field, keyword) in m.SHEET_A_COLUMNS.items()}
    columns[2] = "Citybus"  # KMB's own column now claims to be Citybus's keyword
    df = _header_df(columns, ncols)
    with pytest.raises(RuntimeError, match="header layout"):
        m._validate_headers(df, m.SHEET_A_COLUMNS, "sheet a")


def test_passenger_journeys_grand_total_identity_passes_on_reconciled_data():
    m = _load("scrape_hk_passenger_journeys.py", "pj_identity_ok_test")
    merged = pd.DataFrame(
        [{"date": "2024-12", "bus_subtotal_k": 118309.486, "rail_subtotal_k": 169135.206,
          "plb_subtotal_k": 45945.581, "ferry_subtotal_k": 3598.819, "taxis_k": 20518.576,
          "residents_services_k": 5777.277, "mtr_buses_k": 5020.264, "total_k": 368305.209}]
    )
    m._check_identity(
        merged,
        ["bus_subtotal_k", "rail_subtotal_k", "plb_subtotal_k", "ferry_subtotal_k",
         "taxis_k", "residents_services_k", "mtr_buses_k"],
        "total_k", "Grand total",
    )  # must not raise -- these are the real Dec-2024 TD figures


def test_passenger_journeys_grand_total_identity_rejects_a_shifted_column():
    m = _load("scrape_hk_passenger_journeys.py", "pj_identity_bad_test")
    merged = pd.DataFrame(
        [{"date": "2024-12", "bus_subtotal_k": 118309.486, "rail_subtotal_k": 169135.206,
          "plb_subtotal_k": 45945.581, "ferry_subtotal_k": 3598.819, "taxis_k": 20518.576,
          "residents_services_k": 5777.277, "mtr_buses_k": 5020.264,
          "total_k": 31078.905}]  # Citybus's own subtotal, not the real grand total
    )
    with pytest.raises(RuntimeError, match="does not reconcile"):
        m._check_identity(
            merged,
            ["bus_subtotal_k", "rail_subtotal_k", "plb_subtotal_k", "ferry_subtotal_k",
             "taxis_k", "residents_services_k", "mtr_buses_k"],
            "total_k", "Grand total",
        )


# --- scrape_hk_vehicle_stock.py -----------------------------------------


def test_vehicle_stock_sheet_selection_finds_the_private_cars_sheet():
    m = _load("scrape_hk_vehicle_stock.py", "vs_sheet_ok_test")

    class FakeXL:
        sheet_names = ["T4.1a(1)", "T4.1a(2)"]

        def parse(self, name, header=None):
            label = "Motor Cycles" if name == "T4.1a(1)" else "Private Cars"
            return _header_df({2: label}, 17)

    assert m._find_private_car_sheet(FakeXL()) == "T4.1a(2)"


def test_vehicle_stock_sheet_selection_raises_if_no_sheet_matches():
    m = _load("scrape_hk_vehicle_stock.py", "vs_sheet_bad_test")

    class FakeXL:
        sheet_names = ["T4.1a(1)"]

        def parse(self, name, header=None):
            return _header_df({2: "Motor Cycles"}, 17)

    with pytest.raises(ValueError, match="Expected exactly one private-car sheet"):
        m._find_private_car_sheet(FakeXL())


def test_vehicle_stock_fuel_subtotal_identity_rejects_a_shifted_column():
    m = _load("scrape_hk_vehicle_stock.py", "vs_identity_bad_test")
    df = pd.DataFrame(
        [{"date": "2026-01", "petrol_total_registered": 460000.0, "electric_total_registered": 150000.0,
          "diesel_total_registered": 11000.0, "other_total_registered": 100.0,
          "all_fuel_total_registered": 999999.0}]  # deliberately wrong
    )
    with pytest.raises(ValueError, match="does not reconcile"):
        m._check_identity(
            df,
            ["petrol_total_registered", "electric_total_registered", "diesel_total_registered", "other_total_registered"],
            "all_fuel_total_registered", "Total-registered subtotal",
        )
