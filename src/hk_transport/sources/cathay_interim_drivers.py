"""Cathay Pacific 1H2026 official interim-report driver layer."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber
import requests

from ..config import DEFAULT_HEADERS, NORMALIZED_DIR, RAW_DIR


CATHAY_INTERIM_REPORT_URL = (
    "https://www.cathaypacific.com/content/dam/cx/about-us/investor-relations/"
    "announcements/en/2026_cx_interim_results_en.pdf"
)
CATHAY_FINANCIAL_CALENDAR_URL = (
    "https://www.cathaypacific.com/cx/en_HK/investor-relations/financial-calendar.html"
)
CACHE_PATH = RAW_DIR / "cathay_2026_interim_results.pdf"
OUTPUT_PATH = NORMALIZED_DIR / "airline_cathay_interim_driver_snapshot.csv"

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
    frame = frame.loc[
        frame["observation_date"].le(pd.Timestamp("2026-06-30"))
    ].dropna(subset=["observation_date", "value"])
    if frame.empty:
        return None, None
    row = frame.sort_values("observation_date").iloc[-1]
    return row["observation_date"].strftime("%Y-%m-%d"), float(row["value"])


def _download_report(session: requests.Session | None = None) -> bytes:
    if CACHE_PATH.exists() and CACHE_PATH.stat().st_size > 0:
        return CACHE_PATH.read_bytes()
    http = session or requests.Session()
    response = http.get(CATHAY_INTERIM_REPORT_URL, headers=DEFAULT_HEADERS, timeout=60)
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise ValueError("Cathay interim-report URL did not return a PDF")
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_bytes(response.content)
    return response.content


def extract_cathay_interim_drivers(
    content: bytes,
    *,
    fx_date: str | None = None,
    fx_value: float | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Extract curated 1H2026 rows after asserting official table anchors."""
    page_text: dict[int, str] = {}
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text[page_number] = page.extract_text() or ""

    anchors = {
        2: (
            "Revenue HK$ million 68,061",
            "Available seat kilometres (ASK) Million 74,662",
        ),
        9: (
            "Fuel, including hedging (gains)/losses 23,224",
            "Operating expenses 61,466",
        ),
        10: (
            "Recurring underlying profit attributable to the shareholders of the Cathay Group",
            "Profit attributable to the shareholders of the Cathay Group 6,243",
        ),
        11: ("Gross fuel cost 24,102", "Net fuel cost 23,224"),
        14: (
            "Consolidated Statement of Profit or Loss",
            "Recurring underlying profit attributable to shareholders of the Cathay Group* 5,290",
        ),
    }
    for page_number, required in anchors.items():
        text = page_text.get(page_number, "")
        if not all(anchor in text for anchor in required):
            raise ValueError(f"Cathay 1H2026 interim-report anchor missing on page {page_number}")

    # Values are transcribed from the asserted official tables above and kept
    # in issuer-native units. The page reference is the audit location.
    raw_rows = [
        ("total_revenue", 68061.0, "HKD million", 9),
        ("passenger_revenue", 47342.0, "HKD million", 9),
        ("cargo_revenue", 15702.0, "HKD million", 9),
        ("other_revenue", 5017.0, "HKD million", 9),
        ("operating_cost", 61466.0, "HKD million", 9),
        ("employee_cost", 10287.0, "HKD million", 9),
        ("inflight_service_passenger_cost", 3140.0, "HKD million", 9),
        ("airport_landing_route_cost", 9367.0, "HKD million", 9),
        ("fuel_cost", 23224.0, "HKD million", 9),
        ("gross_fuel_cost", 24102.0, "HKD million", 11),
        ("fuel_hedging_loss_gain", -878.0, "HKD million", 11),
        ("aircraft_maintenance_cost", 5648.0, "HKD million", 9),
        ("aircraft_depreciation_rentals", 4739.0, "HKD million", 9),
        ("operating_profit_before_non_recurring", 6595.0, "HKD million", 14),
        ("company_profit_before_non_recurring_tax", 5076.0, "HKD million", 10),
        ("recurring_underlying_profit", 5290.0, "HKD million", 10),
        ("gain_on_deemed_partial_disposal", 1432.0, "HKD million", 14),
        ("net_loss_on_other_non_recurring_items", -479.0, "HKD million", 14),
        ("group_attributable_profit", 6243.0, "HKD million", 14),
        ("net_borrowings", 47267.0, "HKD million", 2),
        ("available_unrestricted_liquidity", 23575.0, "HKD million", 2),
        ("operating_cash_flow", 13673.0, "HKD million", 17),
        ("atk", 14739.0, "ATK million", 2),
        ("rtk", 10741.0, "RTK million", 2),
        ("cost_per_atk_incl_fuel", 3.87, "HKD per ATK", 2),
        ("cost_per_atk_ex_fuel", 2.42, "HKD per ATK", 2),
        ("fuel_consumption_per_million_atk", 1345.0, "barrels per million ATK", 2),
        ("fuel_consumption_per_million_rtk", 1845.0, "barrels per million RTK", 2),
        ("ask", 74662.0, "ASK million", 2),
        ("rpk", 65334.0, "RPK million", 2),
        ("passengers_carried", 16006.0, "thousand passengers", 2),
        ("passenger_load_factor", 87.5, "percent", 2),
        ("passenger_yield", 66.1, "HK cents per RPK", 2),
        ("passenger_revenue_per_ask", 57.9, "HK cents per ASK", 2),
        ("aftk", 7626.0, "AFTK million", 2),
        ("rftk", 4514.0, "RFTK million", 2),
        ("cargo_tonnes", 869.0, "thousand tonnes", 2),
        ("cargo_load_factor", 59.2, "percent", 2),
        ("cargo_yield", 3.06, "HKD per RFTK", 2),
        ("hkexpress_ask", 9426.0, "ASK million", 2),
        ("hkexpress_rpk", 7623.0, "RPK million", 2),
        ("hkexpress_passengers_carried", 4163.0, "thousand passengers", 2),
        ("hkexpress_load_factor", 80.9, "percent", 2),
    ]
    monetary_units = {
        "HKD million", "HK cents per RPK", "HK cents per ASK", "HKD per RFTK", "HKD per ATK"
    }
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
            "observation_id": f"2026H1_0293_{metric}",
            "ticker": "0293.HK",
            "company": "Cathay Pacific",
            "statement_period": "1H2026",
            "period_end": "2026-06-30",
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
            "source_url": CATHAY_INTERIM_REPORT_URL,
            "source_page": page,
            "source_note": (
                "Cathay Pacific 2026 Interim Results official unaudited interim report; "
                "authorised for issue and announced 2026-08-05."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=DRIVER_COLUMNS)


def fetch_cathay_interim_drivers() -> pd.DataFrame:
    fx_date, fx_value = _fx_asof()
    retrieved = datetime.now(timezone.utc).isoformat()
    result = extract_cathay_interim_drivers(
        _download_report(), fx_date=fx_date, fx_value=fx_value, retrieved_at=retrieved
    )
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
