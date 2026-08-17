"""Airport cargo-throughput versus company cargo bridge validation layer.

This module compares official issuer airport cargo throughput (Shanghai
Pudong/Hongqiao, Shenzhen, Guangzhou) with company cargo tonnage and reported
cargo revenue.  The airport series is a hub-demand proxy: a large share of the
covered carriers' freight moves through these hubs, but airport throughput
includes many carriers and is not company revenue.

The output is a calibration/validation layer, not a cargo revenue forecast.
It supports the v3 cargo bridge by checking whether the external airport
signal and the company tonnage series move together and by providing a
reported revenue-per-tonne anchor where an official revenue row exists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


AIRPORT_PATH = NORMALIZED_DIR / "airline_airport_traffic.csv"
MONTHLY_PATH = (
    Path(__file__).resolve().parents[3]
    / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
)
OFFICIAL_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_cargo_airport_bridge.csv"
DATASET_ID = "airline_cargo_airport_bridge"

# Directional hub mapping only: Shanghai is the primary domestic LCC hub for
# Spring/Juneyao/9 Air, Shenzhen for 9 Air, and Guangzhou/Shenzhen for China
# Southern.  These are not ownership or revenue-attribution mappings.
COMPANY_AIRPORTS = {
    "Spring Airlines": ("SHA-PVG", "SHA-SHA"),
    "Juneyao Airlines": ("SHA-PVG", "SHA-SHA"),
    "9 Air": ("SZX",),
    "China Southern Airlines": ("CAN", "SZX"),
}

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "period",
    "hub_airports",
    "airport_cargo_tonnes",
    "airport_cargo_yoy_pct",
    "company_cargo_tonnes",
    "company_cargo_tonnes_yoy_pct",
    "cargo_tonnage_bridge_gap_pp",
    "airport_cargo_as_pct_of_company_cargo",
    "reported_cargo_revenue_native_mn",
    "reported_cargo_revenue_per_tonne_native",
    "bridge_status",
    "source_note",
    "retrieved_at",
]


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _company_cargo_tonnage(
    monthly: pd.DataFrame,
    company: str,
    *,
    start_month: str,
    end_month: str,
) -> tuple[float | None, float | None, float | None]:
    """Aggregate company cargo tonnes for the window and the prior year."""
    code_map = {
        "Spring Airlines": "601021",
        "Juneyao Airlines": "603885",
        "9 Air": "9AIR",
        "China Southern Airlines": "600029",
        "China Eastern Airlines": "600115",
        "Air China": "601111",
        "Hainan Airlines Holdings": "600221",
    }
    code = code_map.get(company)
    if code is None or monthly.empty:
        return None, None, None
    rows = monthly.loc[
        monthly["airline_code"].astype(str).eq(code)
        & monthly["metric"].eq("cargo_tonnes")
        & monthly["region"].astype(str).eq("Total")
    ].copy()
    if rows.empty:
        return None, None, None
    rows["month_parsed"] = pd.to_datetime(rows["month"], errors="coerce")
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    current = rows.loc[
        rows["month_parsed"].ge(pd.to_datetime(start_month))
        & rows["month_parsed"].le(pd.to_datetime(end_month))
    ]["value"]
    start_dt = pd.to_datetime(start_month)
    end_dt = pd.to_datetime(end_month)
    prior_start = start_dt - pd.DateOffset(years=1)
    prior_end = end_dt - pd.DateOffset(years=1)
    prior = rows.loc[
        rows["month_parsed"].ge(prior_start)
        & rows["month_parsed"].le(prior_end)
    ]["value"]
    current_total = float(current.sum()) if not current.empty else None
    prior_total = float(prior.sum()) if not prior.empty else None
    yoy = (
        100.0 * current_total / prior_total - 100.0
        if current_total is not None and prior_total not in (None, 0)
        else None
    )
    return current_total, prior_total, yoy


def _airport_cargo_signal(
    airports: pd.DataFrame,
    hub_airports: tuple[str, ...],
    *,
    start_month: str,
    end_month: str,
) -> tuple[float | None, float | None]:
    """Sum airport cargo throughput (10k tonnes -> tonnes) for the window."""
    if airports.empty:
        return None, None
    rows = airports.loc[
        airports["airport"].isin(hub_airports)
        & airports["metric"].eq("cargo_throughput")
        & airports["scope"].eq("total")
    ].copy()
    rows["month_parsed"] = pd.to_datetime(
        rows["observation_month"].astype(str), format="%Y-%m", errors="coerce"
    )
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    current = rows.loc[
        rows["month_parsed"].ge(pd.to_datetime(start_month))
        & rows["month_parsed"].le(pd.to_datetime(end_month))
    ]["value"]
    total = float(current.sum()) * 10_000.0 if not current.empty else None
    yoy_values = rows.loc[
        rows["month_parsed"].ge(pd.to_datetime(start_month))
        & rows["month_parsed"].le(pd.to_datetime(end_month))
    ]["yoy_pct"]
    yoy = float(yoy_values.mean()) if not yoy_values.empty else None
    return total, yoy


def _reported_cargo_anchor(
    official: pd.DataFrame,
    company: str,
) -> tuple[float | None, float | None]:
    if official.empty:
        return None, None
    rows = official.loc[
        official["company"].eq(company)
        & official["statement_period"].eq("FY2025")
        & official["metric"].eq("cargo_revenue")
    ]
    if rows.empty:
        return None, None
    return _num(rows.iloc[0].get("value_native")), None


def build_airline_cargo_airport_bridge(
    *,
    airports: pd.DataFrame | None = None,
    monthly: pd.DataFrame | None = None,
    official: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build the H1-2026 airport-versus-company cargo bridge layer."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    airports = airports if airports is not None else (
        pd.read_csv(AIRPORT_PATH) if AIRPORT_PATH.exists() else pd.DataFrame()
    )
    monthly = monthly if monthly is not None else (
        pd.read_parquet(MONTHLY_PATH) if MONTHLY_PATH.exists() else pd.DataFrame()
    )
    official = official if official is not None else (
        pd.read_csv(OFFICIAL_PATH) if OFFICIAL_PATH.exists() else pd.DataFrame()
    )
    rows: list[dict[str, Any]] = []
    for company, hub_airports in COMPANY_AIRPORTS.items():
        airport_total, airport_yoy = _airport_cargo_signal(
            airports, hub_airports, start_month="2026-01", end_month="2026-06"
        )
        company_total, _, company_yoy = _company_cargo_tonnage(
            monthly, company, start_month="2026-01", end_month="2026-06"
        )
        cargo_revenue, _ = _reported_cargo_anchor(official, company)
        gap = (
            airport_yoy - company_yoy
            if airport_yoy is not None and company_yoy is not None
            else None
        )
        coverage = (
            100.0 * airport_total / company_total
            if airport_total is not None and company_total not in (None, 0)
            else None
        )
        revenue_per_tonne = (
            cargo_revenue / (company_total / 1000.0)
            if cargo_revenue is not None and company_total not in (None, 0)
            else None
        )
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "period": "2026-H1",
                "hub_airports": ",".join(hub_airports),
                "airport_cargo_tonnes": airport_total,
                "airport_cargo_yoy_pct": airport_yoy,
                "company_cargo_tonnes": company_total,
                "company_cargo_tonnes_yoy_pct": company_yoy,
                "cargo_tonnage_bridge_gap_pp": gap,
                "airport_cargo_as_pct_of_company_cargo": coverage,
                "reported_cargo_revenue_native_mn": cargo_revenue,
                "reported_cargo_revenue_per_tonne_native": revenue_per_tonne,
                "bridge_status": (
                    "available_airport_and_company_tonnage"
                    if airport_total is not None and company_total is not None
                    else "partial_missing_company_or_airport_series"
                ),
                "source_note": (
                    "Airport cargo throughput is a hub-demand proxy that includes many carriers; "
                    "company cargo tonnage is issuer-reported monthly. The bridge gap is a calibration "
                    "diagnostic, not a cargo revenue forecast."
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
    "build_airline_cargo_airport_bridge",
    "source_path",
]
