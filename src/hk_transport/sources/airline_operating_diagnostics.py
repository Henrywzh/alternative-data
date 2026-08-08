"""Monthly operating diagnostics for the six mainland listed airlines.

This layer preserves the monthly issuer-release grain while making the Q2
post-shock comparison explicit.  It is a descriptive diagnostic: it does not
infer fares, yield or causality from traffic data alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR, ROOT_DIR


MONTHLY_PATH = ROOT_DIR / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
OUTPUT_PATH = NORMALIZED_DIR / "airline_operating_diagnostics.csv"

COMPANIES = {
    "600029": "China Southern Airlines",
    "600115": "China Eastern Airlines",
    "600221": "Hainan Airlines Holdings",
    "601021": "Spring Airlines",
    "601111": "Air China",
    "603885": "Juneyao Airlines",
}

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "airline_code", "snapshot_date",
    "current_period", "prior_period", "q2_ask_yoy_pct", "q2_rpk_yoy_pct",
    "q2_passengers_yoy_pct", "q2_rpk_minus_ask_gap_pp", "q2_cargo_tonnes_yoy_pct",
    "q2_passenger_lf_pct", "q1_passenger_lf_pct", "q2_passenger_lf_minus_q1_pp",
    "q2_freight_lf_pct", "q1_freight_lf_pct", "q2_freight_lf_minus_q1_pp",
    "june_ask_yoy_pct", "june_rpk_yoy_pct", "june_passengers_yoy_pct",
    "june_rpk_minus_ask_gap_pp", "june_passenger_lf_pct", "june_2025_passenger_lf_pct",
    "june_passenger_lf_yoy_pp", "source_quality", "source_path", "source_note", "retrieved_at",
]

TICKERS = {
    "600029": "01055.HK / 600029.SH", "600115": "0670.HK / 600115.SH",
    "600221": "600221.SH", "601021": "601021.SH", "601111": "0753.HK / 601111.SH",
    "603885": "603885.SH",
}


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _monthly_value(frame: pd.DataFrame, code: str, month: str, metric: str) -> float | None:
    rows = frame.loc[
        frame["airline_code"].eq(code)
        & frame["month"].eq(month)
        & frame["metric"].eq(metric)
    ]
    if rows.empty:
        return None
    direct = rows.loc[rows["region"].eq("Total"), "value"]
    if not direct.empty and direct.notna().any():
        return _number(direct.dropna().iloc[0])
    regional = rows.loc[~rows["region"].eq("Total"), "value"]
    return _number(regional.sum(min_count=1)) if regional.notna().any() else None


def _load_factor(frame: pd.DataFrame, code: str, month: str, kind: str) -> float | None:
    metric = f"{kind}_load_factor_pct"
    direct = frame.loc[
        frame["airline_code"].eq(code)
        & frame["month"].eq(month)
        & frame["metric"].eq(metric)
        & frame["region"].eq("Total"),
        "value",
    ]
    if not direct.empty and direct.notna().any():
        return _number(direct.dropna().iloc[0])
    numerator = "rpk" if kind == "passenger" else "rftk"
    denominator = "ask" if kind == "passenger" else "aftk"
    num = _monthly_value(frame, code, month, numerator)
    den = _monthly_value(frame, code, month, denominator)
    return 100.0 * num / den if num is not None and den else None


def _period_sum(frame: pd.DataFrame, code: str, months: list[str], metric: str) -> float | None:
    values = [_monthly_value(frame, code, month, metric) for month in months]
    values = [value for value in values if value is not None]
    return float(sum(values)) if values else None


def _growth(frame: pd.DataFrame, code: str, current: list[str], prior: list[str], metric: str) -> float | None:
    current_value = _period_sum(frame, code, current, metric)
    prior_value = _period_sum(frame, code, prior, metric)
    if current_value is None or prior_value in (None, 0):
        return None
    return 100.0 * (current_value / prior_value - 1.0)


def _weighted_lf(frame: pd.DataFrame, code: str, months: list[str], kind: str) -> float | None:
    numerator = "rpk" if kind == "passenger" else "rftk"
    denominator = "ask" if kind == "passenger" else "aftk"
    num = _period_sum(frame, code, months, numerator)
    den = _period_sum(frame, code, months, denominator)
    return 100.0 * num / den if num is not None and den else None


def _build_row(frame: pd.DataFrame, code: str, *, snapshot_date: str, retrieved_at: str) -> dict[str, Any]:
    q1_2026 = [f"2026-{month:02d}" for month in (1, 2, 3)]
    q2_2026 = [f"2026-{month:02d}" for month in (4, 5, 6)]
    q2_2025 = [f"2025-{month:02d}" for month in (4, 5, 6)]
    june_2026 = ["2026-06"]
    june_2025 = ["2025-06"]
    q2_ask = _growth(frame, code, q2_2026, q2_2025, "ask")
    q2_rpk = _growth(frame, code, q2_2026, q2_2025, "rpk")
    june_ask = _growth(frame, code, june_2026, june_2025, "ask")
    june_rpk = _growth(frame, code, june_2026, june_2025, "rpk")
    q2_lf = _weighted_lf(frame, code, q2_2026, "passenger")
    q1_lf = _weighted_lf(frame, code, q1_2026, "passenger")
    q2_freight_lf = _weighted_lf(frame, code, q2_2026, "freight")
    q1_freight_lf = _weighted_lf(frame, code, q1_2026, "freight")
    june_lf = _load_factor(frame, code, "2026-06", "passenger")
    june_2025_lf = _load_factor(frame, code, "2025-06", "passenger")
    return {
        "dataset_id": "airline_operating_diagnostics",
        "company": COMPANIES[code], "ticker": TICKERS[code], "market": "CN_A",
        "airline_code": code, "snapshot_date": snapshot_date,
        "current_period": "2026Q2/Jun", "prior_period": "2025Q2/Jun",
        "q2_ask_yoy_pct": q2_ask, "q2_rpk_yoy_pct": q2_rpk,
        "q2_passengers_yoy_pct": _growth(frame, code, q2_2026, q2_2025, "passengers"),
        "q2_rpk_minus_ask_gap_pp": q2_rpk - q2_ask if q2_rpk is not None and q2_ask is not None else None,
        "q2_cargo_tonnes_yoy_pct": _growth(frame, code, q2_2026, q2_2025, "cargo_tonnes"),
        "q2_passenger_lf_pct": q2_lf, "q1_passenger_lf_pct": q1_lf,
        "q2_passenger_lf_minus_q1_pp": q2_lf - q1_lf if q2_lf is not None and q1_lf is not None else None,
        "q2_freight_lf_pct": q2_freight_lf, "q1_freight_lf_pct": q1_freight_lf,
        "q2_freight_lf_minus_q1_pp": q2_freight_lf - q1_freight_lf if q2_freight_lf is not None and q1_freight_lf is not None else None,
        "june_ask_yoy_pct": june_ask, "june_rpk_yoy_pct": june_rpk,
        "june_passengers_yoy_pct": _growth(frame, code, june_2026, june_2025, "passengers"),
        "june_rpk_minus_ask_gap_pp": june_rpk - june_ask if june_rpk is not None and june_ask is not None else None,
        "june_passenger_lf_pct": june_lf, "june_2025_passenger_lf_pct": june_2025_lf,
        "june_passenger_lf_yoy_pp": june_lf - june_2025_lf if june_lf is not None and june_2025_lf is not None else None,
        "source_quality": "derived_issuer_monthly_operating_release",
        "source_path": str(MONTHLY_PATH),
        "source_note": (
            "Derived from monthly issuer operating releases. Q2 and June growth compare equal calendar periods; "
            "Total rows are preferred and regional rows are summed only when an issuer Total is absent. "
            "Load factors are weighted from traffic/capacity, and no yield or fare inference is made."
        ),
        "retrieved_at": retrieved_at,
    }


def build_airline_operating_diagnostics(
    frame: pd.DataFrame | None = None,
    *,
    snapshot_date: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    source = frame.copy() if frame is not None else pd.read_parquet(MONTHLY_PATH)
    required = {"month", "airline_code", "region", "metric", "value"}
    missing = required.difference(source.columns)
    if missing:
        raise ValueError(f"monthly airline data is missing columns: {sorted(missing)}")
    source["airline_code"] = source["airline_code"].astype(str)
    source["month"] = source["month"].astype(str)
    source["value"] = pd.to_numeric(source["value"], errors="coerce")
    source = source.loc[source["airline_code"].isin(COMPANIES)].copy()
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    snap = snapshot_date or pd.Timestamp(retrieved).strftime("%Y-%m-%d")
    result = pd.DataFrame(
        [_build_row(source, code, snapshot_date=snap, retrieved_at=retrieved) for code in COMPANIES],
        columns=OUTPUT_COLUMNS,
    )
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_operating_diagnostics() -> pd.DataFrame:
    return build_airline_operating_diagnostics()


def source_path() -> Path:
    return OUTPUT_PATH
