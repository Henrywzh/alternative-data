"""Forward cargo-revenue bridge using reported yield anchors and tonnage.

The v3 cargo leg currently grows reported cargo revenue with an external
trade/CAAC/SPB proxy.  This module builds a competing, more direct bridge:
official H1-2025 cargo revenue divided by H1-2025 issuer cargo tonnage gives a
revenue-per-tonne anchor, which is applied to H1-2026 issuer tonnage to produce
a dated cargo-revenue nowcast.

The output is a research calibration layer.  Cargo yield is not uniform by
route or commodity mix, tonnage is issuer-reported monthly (preliminary), and
the H1-2025 revenue anchor is not disclosed for every company.  The v3 model
carries this bridge beside the external-proxy leg so the two can be compared
instead of silently preferring one.
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
OUTPUT_PATH = NORMALIZED_DIR / "airline_cargo_yield_bridge.csv"
DATASET_ID = "airline_cargo_yield_bridge"

CODE_TO_COMPANY = {
    "600029": "China Southern Airlines",
    "600115": "China Eastern Airlines",
    "600221": "Hainan Airlines Holdings",
    "601021": "Spring Airlines",
    "601111": "Air China",
    "603885": "Juneyao Airlines",
}

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "period",
    "h1_2025_cargo_revenue_native_mn",
    "revenue_anchor_period",
    "revenue_anchor_type",
    "h1_2025_cargo_tonnes",
    "revenue_per_tonne_native",
    "h1_2026_cargo_tonnes",
    "h1_2026_cargo_tonnes_yoy_pct",
    "h1_2026_cargo_revenue_bridge_native_mn",
    "h1_2025_cargo_revenue_proxy_native_mn",
    "bridge_revenue_growth_pct",
    "bridge_status",
    "source_note",
    "retrieved_at",
]


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _tonnage(monthly: pd.DataFrame, code: str, year: int) -> float | None:
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
        rows["month_parsed"].ge(pd.Timestamp(year=year, month=1, day=1))
        & rows["month_parsed"].le(pd.Timestamp(year=year, month=6, day=30))
    ]["value"]
    return float(window.sum()) if not window.empty else None


def _annual_tonnage(monthly: pd.DataFrame, code: str, year: int) -> float | None:
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
        rows["month_parsed"].ge(pd.Timestamp(year=year, month=1, day=1))
        & rows["month_parsed"].le(pd.Timestamp(year=year, month=12, day=31))
    ]["value"]
    return float(window.sum()) if not window.empty else None


def build_airline_cargo_yield_bridge(
    *,
    official: pd.DataFrame | None = None,
    monthly: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build the H1-2026 cargo-revenue bridge for all covered companies."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    official = official if official is not None else (
        pd.read_csv(OFFICIAL_PATH) if OFFICIAL_PATH.exists() else pd.DataFrame()
    )
    monthly = monthly if monthly is not None else (
        pd.read_parquet(MONTHLY_PATH) if MONTHLY_PATH.exists() else pd.DataFrame()
    )
    rows: list[dict[str, Any]] = []
    for code, company in CODE_TO_COMPANY.items():
        revenue_rows = official.loc[
            official["company"].eq(company)
            & official["statement_period"].eq("1H2025")
            & official["metric"].eq("cargo_revenue")
        ]
        h1_25_revenue = (
            _num(revenue_rows.iloc[0].get("value_native")) if not revenue_rows.empty else None
        )
        h1_25_tonnes = _tonnage(monthly, code, 2025)
        revenue_anchor_period = "1H2025"
        revenue_anchor_type = "official_h1_2025_cargo_revenue"
        if h1_25_revenue is None:
            fy_rows = official.loc[
                official["company"].eq(company)
                & official["statement_period"].eq("FY2025")
                & official["metric"].eq("cargo_revenue")
            ]
            fy_revenue = _num(fy_rows.iloc[0].get("value_native")) if not fy_rows.empty else None
            if fy_revenue is not None and h1_25_tonnes not in (None, 0):
                h1_25_revenue = fy_revenue
                revenue_anchor_period = "FY2025"
                revenue_anchor_type = "official_fy2025_cargo_revenue_annualized_anchor"
        h1_26_tonnes = _tonnage(monthly, code, 2026)
        revenue_per_tonne = (
            h1_25_revenue * 1_000_000.0 / h1_25_tonnes
            if h1_25_revenue is not None and h1_25_tonnes not in (None, 0)
            else None
        )
        bridge_revenue = (
            revenue_per_tonne * h1_26_tonnes / 1_000_000.0
            if revenue_per_tonne is not None and h1_26_tonnes is not None
            else None
        )
        tonnes_yoy = (
            100.0 * h1_26_tonnes / h1_25_tonnes - 100.0
            if h1_26_tonnes is not None and h1_25_tonnes not in (None, 0)
            else None
        )
        revenue_growth = (
            100.0 * bridge_revenue / h1_25_revenue - 100.0
            if bridge_revenue is not None and h1_25_revenue not in (None, 0)
            else None
        )
        status = (
            "available_bridge"
            if h1_25_revenue is not None and h1_25_tonnes is not None and h1_26_tonnes is not None
            else "partial_missing_revenue_or_tonnage_anchor"
        )
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "period": "2026-H1",
                "h1_2025_cargo_revenue_native_mn": h1_25_revenue,
                "revenue_anchor_period": revenue_anchor_period,
                "revenue_anchor_type": revenue_anchor_type,
                "h1_2025_cargo_tonnes": h1_25_tonnes,
                "revenue_per_tonne_native": revenue_per_tonne,
                "h1_2026_cargo_tonnes": h1_26_tonnes,
                "h1_2026_cargo_tonnes_yoy_pct": tonnes_yoy,
                "h1_2026_cargo_revenue_bridge_native_mn": bridge_revenue,
                "h1_2025_cargo_revenue_proxy_native_mn": h1_25_revenue,
                "bridge_revenue_growth_pct": revenue_growth,
                "bridge_status": status,
                "source_note": (
                    "H1-2025 official cargo revenue divided by H1-2025 issuer tonnage gives a "
                    "revenue-per-tonne anchor applied to H1-2026 tonnage. Yield is not uniform by "
                    "route/mix; tonnage is issuer preliminary monthly data."
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
    "build_airline_cargo_yield_bridge",
    "source_path",
]
