"""Historical backtest of the cargo-yield and airport-signal bridges.

Only one official cargo-revenue vintage (FY2025/1H2025) exists in the report
layer, so the backtest is deliberately small and honest:

1. FY2025 revenue-per-tonne anchor: FY2025 reported cargo revenue divided by
   FY2025 issuer tonnage is applied to 1H2025 tonnage to predict 1H2025 cargo
   revenue, which is compared with the reported 1H2025 figure. This is a real
   holdout test of the yield method.
2. Airport signal direction: H1-2026 airport cargo YoY is compared with
   company cargo-tonnage YoY. With one airport-vintage year, this is a
   direction/calibration check rather than a fitted regression.

The output is calibration evidence, not a fitted forecast.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


OFFICIAL_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
MONTHLY_PATH = (
    Path(__file__).resolve().parents[3]
    / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
)
AIRPORT_PATH = NORMALIZED_DIR / "airline_airport_traffic.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_cargo_bridge_backtest.csv"
DATASET_ID = "airline_cargo_bridge_backtest"

CODE_TO_COMPANY = {
    "600029": "China Southern Airlines",
    "600115": "China Eastern Airlines",
    "600221": "Hainan Airlines Holdings",
    "601021": "Spring Airlines",
    "601111": "Air China",
    "603885": "Juneyao Airlines",
}

COMPANY_AIRPORTS = {
    "Spring Airlines": ("SHA-PVG", "SHA-SHA"),
    "Juneyao Airlines": ("SHA-PVG", "SHA-SHA"),
    "China Southern Airlines": ("CAN", "SZX"),
}

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "fy2025_cargo_revenue_native_mn",
    "fy2025_cargo_tonnes",
    "fy2025_revenue_per_tonne_native",
    "predicted_h1_2025_cargo_revenue_native_mn",
    "actual_h1_2025_cargo_revenue_native_mn",
    "h1_2025_revenue_error_pct",
    "airport_cargo_h1_2026_yoy_pct",
    "company_cargo_h1_2026_yoy_pct",
    "airport_signal_gap_pp",
    "backtest_status",
    "source_note",
    "retrieved_at",
]


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _tonnage(monthly: pd.DataFrame, code: str, start: str, end: str) -> float | None:
    rows = monthly.loc[
        monthly["airline_code"].astype(str).eq(code)
        & monthly["metric"].eq("cargo_tonnes")
        & monthly["region"].astype(str).eq("Total")
    ].copy()
    if rows.empty:
        return None
    rows["month_parsed"] = pd.to_datetime(rows["month"], errors="coerce")
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    window = rows.loc[
        rows["month_parsed"].ge(pd.to_datetime(start))
        & rows["month_parsed"].le(pd.to_datetime(end))
    ]["value"]
    return float(window.sum()) if not window.empty else None


def build_airline_cargo_bridge_backtest(
    *,
    official: pd.DataFrame | None = None,
    monthly: pd.DataFrame | None = None,
    airports: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build the cargo-bridge backtest with one genuine holdout leg."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    official = official if official is not None else (
        pd.read_csv(OFFICIAL_PATH) if OFFICIAL_PATH.exists() else pd.DataFrame()
    )
    monthly = monthly if monthly is not None else (
        pd.read_parquet(MONTHLY_PATH) if MONTHLY_PATH.exists() else pd.DataFrame()
    )
    airports = airports if airports is not None else (
        pd.read_csv(AIRPORT_PATH) if AIRPORT_PATH.exists() else pd.DataFrame()
    )
    rows: list[dict[str, Any]] = []
    for code, company in CODE_TO_COMPANY.items():
        def official_value(period: str, metric: str) -> float | None:
            if official.empty:
                return None
            selected = official.loc[
                official["company"].eq(company)
                & official["statement_period"].eq(period)
                & official["metric"].eq(metric)
            ]
            return _num(selected.iloc[0].get("value_native")) if not selected.empty else None

        fy_revenue = official_value("FY2025", "cargo_revenue")
        h1_25_actual = official_value("1H2025", "cargo_revenue")
        fy_tonnes = _tonnage(monthly, code, "2025-01-01", "2025-12-31")
        h1_25_tonnes = _tonnage(monthly, code, "2025-01-01", "2025-06-30")
        h1_26_tonnes = _tonnage(monthly, code, "2026-01-01", "2026-06-30")
        yield_per_tonne = (
            fy_revenue * 1_000_000.0 / fy_tonnes
            if fy_revenue is not None and fy_tonnes not in (None, 0)
            else None
        )
        predicted_h1_25 = (
            yield_per_tonne * h1_25_tonnes / 1_000_000.0
            if yield_per_tonne is not None and h1_25_tonnes is not None
            else None
        )
        error = (
            100.0 * predicted_h1_25 / h1_25_actual - 100.0
            if predicted_h1_25 is not None and h1_25_actual not in (None, 0)
            else None
        )
        airport_yoy = None
        company_yoy = None
        hub = COMPANY_AIRPORTS.get(company)
        if hub and not airports.empty:
            airport_rows = airports.loc[
                airports["airport"].isin(hub)
                & airports["metric"].eq("cargo_throughput")
                & airports["scope"].eq("total")
                & airports["observation_month"].astype(str).ge("2026-01")
                & airports["observation_month"].astype(str).le("2026-06")
            ]
            if not airport_rows.empty:
                airport_yoy = float(pd.to_numeric(airport_rows["yoy_pct"], errors="coerce").mean())
        # Same-basis YoY: H1-2026 versus H1-2025, matching the airport
        # bulletin YoY which compares the same calendar period.
        if h1_26_tonnes is not None and h1_25_tonnes not in (None, 0):
            company_yoy = 100.0 * h1_26_tonnes / h1_25_tonnes - 100.0
        gap = (
            airport_yoy - company_yoy
            if airport_yoy is not None and company_yoy is not None
            else None
        )
        status = (
            "available_holdout_and_airport_signal"
            if error is not None and airport_yoy is not None and company_yoy is not None
            else "partial_holdout_only"
            if error is not None
            else "missing_anchor"
        )
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "fy2025_cargo_revenue_native_mn": fy_revenue,
                "fy2025_cargo_tonnes": fy_tonnes,
                "fy2025_revenue_per_tonne_native": yield_per_tonne,
                "predicted_h1_2025_cargo_revenue_native_mn": predicted_h1_25,
                "actual_h1_2025_cargo_revenue_native_mn": h1_25_actual,
                "h1_2025_revenue_error_pct": error,
                "airport_cargo_h1_2026_yoy_pct": airport_yoy,
                "company_cargo_h1_2026_yoy_pct": company_yoy,
                "airport_signal_gap_pp": gap,
                "backtest_status": status,
                "source_note": (
                    "FY2025 revenue-per-tonne anchor applied to 1H2025 tonnage versus reported "
                    "1H2025 cargo revenue is a genuine holdout test. Airport-cargo YoY versus "
                    "company-tonnage YoY for H1-2026 is a single-vintage direction check."
                ),
                "retrieved_at": retrieved,
            }
        )
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "build_airline_cargo_bridge_backtest",
    "source_path",
]
