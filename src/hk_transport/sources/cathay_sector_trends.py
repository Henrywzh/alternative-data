"""Comparable H1 operating-trend summary for Cathay's issuer traffic releases.

Cathay is intentionally kept separate from the six-company mainland universe:
the issuer traffic release has a different group and hub scope, so adding it to
the mainland sector aggregate would create a misleading market-size series.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR, ROOT_DIR
from .cathay_traffic import fetch_cathay_traffic


CATHAY_RAW_GLOB = ROOT_DIR / "data" / "raw" / "hk_transport" / "cathay_hkia_traffic_*.json"
CATHAY_CODE = "0293"
CATHAY_COMPANY = "Cathay Pacific Group"
TREND_COLUMNS = [
    "dataset_id", "scope_type", "airline_code", "company", "region", "metric",
    "current_period", "prior_period", "current_value", "prior_value",
    "yoy_change_abs", "yoy_change_pct", "unit", "calculation_method",
    "quality_flag", "source_quality", "source_path", "source_note", "retrieved_at",
]


def _h1_mask(frame: pd.DataFrame, period: str) -> pd.Series:
    month_dates = pd.to_datetime(frame["month"].astype(str) + "-01", errors="coerce")
    return frame["month"].astype(str).str.startswith(period) & month_dates.dt.month.le(6)


def _latest_raw_path() -> Path | None:
    paths = sorted(CATHAY_RAW_GLOB.parent.glob(CATHAY_RAW_GLOB.name))
    return paths[-1] if paths else None


def _load_latest_raw_snapshot() -> tuple[pd.DataFrame, Path]:
    path = _latest_raw_path()
    if path is None:
        raise FileNotFoundError(f"No Cathay traffic snapshot found under {CATHAY_RAW_GLOB.parent}")
    payload = json.loads(path.read_text())
    return pd.DataFrame(payload.get("data", [])), path


def _trend_row(
    *,
    metric: str,
    current_value: float | None,
    prior_value: float | None,
    unit: str,
    calculation_method: str,
    source_path: str,
    retrieved_at: str,
) -> dict[str, Any]:
    change_abs = None
    change_pct = None
    if current_value is not None and prior_value is not None:
        change_abs = current_value - prior_value
        if prior_value != 0:
            change_pct = 100.0 * change_abs / abs(prior_value)
    quality_flag = "large_yoy_move_review" if change_pct is not None and abs(change_pct) >= 50 else "ok"
    return {
        "dataset_id": "airline_cathay_sector_trend_snapshot",
        "scope_type": "company",
        "airline_code": CATHAY_CODE,
        "company": CATHAY_COMPANY,
        "region": "Total",
        "metric": metric,
        "current_period": "2026H1",
        "prior_period": "2025H1",
        "current_value": current_value,
        "prior_value": prior_value,
        "yoy_change_abs": change_abs,
        "yoy_change_pct": change_pct,
        "unit": unit,
        "calculation_method": calculation_method,
        "quality_flag": quality_flag,
        "source_quality": "issuer_monthly_operating_release",
        "source_path": source_path,
        "source_note": (
            "Derived from Cathay issuer monthly traffic releases after unit normalization. "
            "Cathay issuer/group scope is kept separate from the six-company mainland universe; "
            "monthly operating figures are preliminary/unaudited."
        ),
        "retrieved_at": retrieved_at,
    }


def build_cathay_sector_trends(
    frame: pd.DataFrame | None = None,
    *,
    current_period: str = "2026",
    prior_period: str = "2025",
    source_path: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build a unit-normalized Cathay H1 comparison from monthly disclosures."""
    if frame is None:
        source, raw_path = _load_latest_raw_snapshot()
        source_path = source_path or str(raw_path)
    else:
        source = frame.copy()
        source_path = source_path or "in_memory_cathay_traffic_frame"

    required = {"month", "cathay_passengers", "cathay_rpk_thousands", "cathay_ask_thousands"}
    missing = required.difference(source.columns)
    if missing:
        raise ValueError(f"Cathay traffic data is missing columns: {sorted(missing)}")

    source["month"] = source["month"].astype(str)
    numeric_columns = [
        "cathay_passengers", "cathay_rpk_thousands", "cathay_ask_thousands",
        "cathay_cargo_tonnes", "cathay_aftk_thousands", "cathay_rftk_thousands",
    ]
    for column in numeric_columns:
        if column not in source:
            source[column] = pd.NA
        source[column] = pd.to_numeric(source[column], errors="coerce")

    # Cathay traffic PDFs report passenger counts and tonne figures as absolute
    # values, while ASK/RPK/AFTK/RFTK are in thousands. The comparable schema
    # uses thousand passengers, tonnes, and million traffic units.
    metrics = {
        "ask": ("cathay_ask_thousands", 1 / 1000, "million seat-km"),
        "rpk": ("cathay_rpk_thousands", 1 / 1000, "million passenger-km"),
        "passengers": ("cathay_passengers", 1 / 1000, "thousand passengers"),
        "aftk": ("cathay_aftk_thousands", 1 / 1000, "million freight tonne-km"),
        "rftk": ("cathay_rftk_thousands", 1 / 1000, "million freight tonne-km"),
        "cargo_tonnes": ("cathay_cargo_tonnes", 1, "tonnes"),
    }
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    for metric, (column, scale, unit) in metrics.items():
        current_slice = source.loc[_h1_mask(source, current_period), column]
        prior_slice = source.loc[_h1_mask(source, prior_period), column]
        current = current_slice.sum(min_count=1) * scale if current_slice.notna().any() else None
        prior = prior_slice.sum(min_count=1) * scale if prior_slice.notna().any() else None
        current = None if current is None or pd.isna(current) else float(current)
        prior = None if prior is None or pd.isna(prior) else float(prior)
        if current is None and prior is None:
            continue
        rows.append(_trend_row(
            metric=metric,
            current_value=current,
            prior_value=prior,
            unit=unit,
            calculation_method="sum_monthly_issuer_release_after_unit_normalization",
            source_path=source_path,
            retrieved_at=retrieved,
        ))

    for metric, numerator, denominator, numerator_divisor, denominator_divisor in (
        ("passenger_load_factor_pct", "cathay_rpk_thousands", "cathay_ask_thousands", 1, 1),
        ("freight_load_factor_pct", "cathay_rftk_thousands", "cathay_aftk_thousands", 1, 1),
    ):
        values: dict[str, float | None] = {}
        for period in (current_period, prior_period):
            selected = source.loc[_h1_mask(source, period)]
            num = selected[numerator].sum(min_count=1) / numerator_divisor
            den = selected[denominator].sum(min_count=1) / denominator_divisor
            values[period] = float(100.0 * num / den) if pd.notna(num) and pd.notna(den) and den else None
        if values[current_period] is None and values[prior_period] is None:
            continue
        rows.append(_trend_row(
            metric=metric,
            current_value=values[current_period],
            prior_value=values[prior_period],
            unit="%",
            calculation_method="rpk_over_ask_or_rftk_over_aftk_weighted_H1",
            source_path=source_path,
            retrieved_at=retrieved,
        ))

    return pd.DataFrame(rows, columns=TREND_COLUMNS)


def fetch_cathay_sector_trends() -> pd.DataFrame:
    """Refresh Cathay traffic and persist the comparable H1 trend layer."""
    source = fetch_cathay_traffic()
    result = build_cathay_sector_trends(
        source,
        source_path=str(source.attrs.get("raw_snapshot", "cathay_hkia_traffic_live_fetch")),
    )
    result.to_csv(NORMALIZED_DIR / "airline_cathay_sector_trend_snapshot.csv", index=False)
    return result


def source_path() -> Path:
    return NORMALIZED_DIR / "airline_cathay_sector_trend_snapshot.csv"
