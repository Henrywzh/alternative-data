"""Cathay Pacific FY2025 official annual-report driver layer."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber
import requests

from ..config import DEFAULT_HEADERS, NORMALIZED_DIR, RAW_DIR


CATHAY_ANNUAL_REPORT_URL = (
    "https://www.cathaypacific.com/content/dam/cx/about-us/investor-relations/"
    "interim-annual-reports/en/2025_cx_annual_report_en.pdf"
)
CATHAY_ANNUAL_RESULTS_URL = "https://news.cathaypacific.com/the-cathay-group-announces-2025-annual-results-d8fv9x"
CACHE_PATH = RAW_DIR / "cathay_2025_annual_report.pdf"
OUTPUT_PATH = NORMALIZED_DIR / "airline_cathay_annual_driver_snapshot.csv"

DRIVER_COLUMNS = [
    "observation_id", "ticker", "company", "statement_period", "period_end", "metric",
    "value_native", "native_unit", "native_currency", "value_usd", "usd_unit",
    "fx_pair", "fx_observation_date", "fx_value", "source_quality", "source_url",
    "source_page", "source_note", "retrieved_at",
]


def _fx_asof() -> tuple[str | None, float | None]:
    path = NORMALIZED_DIR / "airline_fx_rates.parquet"
    if not path.exists():
        return None, None
    frame = pd.read_parquet(path)
    frame = frame.loc[frame["pair"].eq("USD_HKD")].copy()
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.loc[frame["observation_date"].le(pd.Timestamp("2025-12-31"))].dropna(subset=["observation_date", "value"])
    if frame.empty:
        return None, None
    row = frame.sort_values("observation_date").iloc[-1]
    return row["observation_date"].strftime("%Y-%m-%d"), float(row["value"])


def _download_report(session: requests.Session | None = None) -> bytes:
    if CACHE_PATH.exists() and CACHE_PATH.stat().st_size > 0:
        return CACHE_PATH.read_bytes()
    http = session or requests.Session()
    response = http.get(CATHAY_ANNUAL_REPORT_URL, headers=DEFAULT_HEADERS, timeout=45)
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise ValueError("Cathay annual-report URL did not return a PDF")
    CACHE_PATH.write_bytes(response.content)
    return response.content


def extract_cathay_annual_drivers(
    content: bytes,
    *,
    fx_date: str | None = None,
    fx_value: float | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Extract curated FY2025 rows after asserting official table anchors."""
    page_text: dict[int, str] = {}
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text[page_number] = page.extract_text() or ""
    anchors = {
        5: ("Revenue HK$ million 116,766", "Available seat kilometres (ASK) Million 140,681"),
        36: ("Fuel, including hedging losses/(gains) 31,344", "Operating expenses 102,693"),
        85: ("Passenger services 78,848", "Total revenue 116,766"),
        134: ("Change in fair value of the derivative instruments during the year (1,699)",),
    }
    for page_number, required in anchors.items():
        text = page_text.get(page_number, "")
        if not all(anchor in text for anchor in required):
            raise ValueError(f"Cathay FY2025 annual-report anchor missing on page {page_number}")

    # Values are transcribed from the asserted official tables above and kept
    # in issuer-native units. The page reference is the audit location.
    raw_rows = [
        ("total_revenue", 116766.0, "HKD million", 85),
        ("passenger_revenue", 78848.0, "HKD million", 85),
        ("cargo_revenue", 27572.0, "HKD million", 85),
        ("other_revenue", 10346.0, "HKD million", 85),
        ("operating_cost", 102693.0, "HKD million", 36),
        ("fuel_cost", 31344.0, "HKD million", 36),
        ("staff_cost", 20080.0, "HKD million", 36),
        ("airport_landing_cost", 17203.0, "HKD million", 36),
        ("maintenance_cost", 9877.0, "HKD million", 36),
        ("aircraft_depreciation_rentals", 9285.0, "HKD million", 36),
        ("group_attributable_profit", 10828.0, "HKD million", 85),
        ("net_borrowings", 46812.0, "HKD million", 5),
        ("available_unrestricted_liquidity", 25435.0, "HKD million", 5),
        ("ask", 140681.0, "ASK million", 5),
        ("rpk", 119875.0, "RPK million", 5),
        ("passengers_carried", 28871.0, "thousand passengers", 5),
        ("passenger_load_factor", 85.2, "percent", 5),
        ("passenger_yield", 60.4, "HK cents per RPK", 5),
        ("passenger_revenue_per_ask", 51.5, "HK cents per ASK", 5),
        ("aftk", 15373.0, "AFTK million", 5),
        ("rftk", 9037.0, "RFTK million", 5),
        ("cargo_tonnes", 1677.0, "thousand tonnes", 5),
        ("cargo_load_factor", 58.8, "percent", 5),
        ("cargo_yield", 2.69, "HKD per RFTK", 5),
        ("atk", 28773.0, "ATK million", 5),
        ("rtk", 20461.0, "RTK million", 5),
        ("cost_per_atk_incl_fuel", 3.32, "HKD per ATK", 5),
        ("cost_per_atk_ex_fuel", 2.32, "HKD per ATK", 36),
        ("fuel_consumption_per_million_atk", 1327.0, "barrels per million ATK", 5),
        ("fuel_hedge_fair_value_change", -1699.0, "HKD million", 134),
        ("fuel_hedge_ending_fair_value", -1330.0, "HKD million", 134),
    ]
    monetary_units = {"HKD million", "HK cents per RPK", "HK cents per ASK", "HKD per RFTK", "HKD per ATK"}
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for metric, value, unit, page in raw_rows:
        is_monetary = unit in monetary_units
        value_usd = value / fx_value if is_monetary and fx_value else None
        usd_unit = None
        if is_monetary:
            usd_unit = {
                "HKD million": "USD million",
                "HK cents per RPK": "USD cents per RPK",
                "HK cents per ASK": "USD cents per ASK",
                "HKD per RFTK": "USD per RFTK",
                "HKD per ATK": "USD per ATK",
            }[unit]
        rows.append({
            "observation_id": f"2025FY_0293_{metric}",
            "ticker": "0293.HK",
            "company": "Cathay Pacific",
            "statement_period": "FY2025",
            "period_end": "2025-12-31",
            "metric": metric,
            "value_native": value,
            "native_unit": unit,
            "native_currency": "HKD" if is_monetary else None,
            "value_usd": value_usd,
            "usd_unit": usd_unit,
            "fx_pair": "USD_HKD" if is_monetary and fx_value else None,
            "fx_observation_date": fx_date if is_monetary and fx_value else None,
            "fx_value": fx_value if is_monetary and fx_value else None,
            "source_quality": "primary_issuer",
            "source_url": CATHAY_ANNUAL_REPORT_URL,
            "source_page": page,
            "source_note": (
                "Cathay Pacific FY2025 Annual Report official table; report announcement "
                "date is 2026-03-11 from the issuer annual-results announcement."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=DRIVER_COLUMNS)


def fetch_cathay_annual_drivers() -> pd.DataFrame:
    fx_date, fx_value = _fx_asof()
    retrieved = datetime.now(timezone.utc).isoformat()
    result = extract_cathay_annual_drivers(
        _download_report(), fx_date=fx_date, fx_value=fx_value, retrieved_at=retrieved
    )
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
