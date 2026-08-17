"""H1-2026 report validation playbook for the airline v3 model.

Every claim in the airline research stack is tested against the H1-2026
interim reports.  This module consolidates the pre-report model forecasts
(KPI bridge, cargo bridge, v3 scenarios, consensus) with the official filing
dates into one reconciliation table.  After the reports are published, the
actual columns can be filled in and the error columns show whether the model
was directionally right.

The output is a validation playbook, not a new forecast.  It is the bridge
between the v3 research model and the formal interim results.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


EXPECTATION_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
FILING_CALENDAR_PATH = NORMALIZED_DIR / "airline_filing_calendar.csv"
CARGO_YIELD_PATH = NORMALIZED_DIR / "airline_cargo_yield_bridge.csv"
V3_PATH = NORMALIZED_DIR / "airline_earnings_model_v3.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_h1_2026_validation_playbook.csv"
DATASET_ID = "airline_h1_2026_validation_playbook"

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "filing_scheduled_date",
    "calendar_status",
    "h1_2026_ask_yoy_pct",
    "h1_2026_rpk_yoy_pct",
    "h1_2026_passengers_yoy_pct",
    "h1_2026_passenger_lf_change_pp",
    "h1_2026_cargo_tonnes_yoy_pct",
    "h1_2026_cargo_revenue_bridge_native_mn",
    "h1_2026_cargo_revenue_anchor_period",
    "fy2026_v3_base_revenue_usd_mn",
    "fy2026_v3_base_net_profit_usd_mn",
    "fy2026_v3_base_net_profit_consensus_guarded_usd_mn",
    "net_income_leg",
    "regime_flip_flag",
    "fy2026_v3_base_eps_rmb_per_share",
    "fy2026_v3_bear_net_profit_usd_mn",
    "fy2026_v3_bull_net_profit_usd_mn",
    "consensus_fy2026_profit_usd_mn",
    "v3_base_vs_consensus_profit_gap_pct",
    "validation_status",
    "source_note",
    "retrieved_at",
]


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def build_airline_h1_2026_validation_playbook(
    *,
    expectations: pd.DataFrame | None = None,
    calendar: pd.DataFrame | None = None,
    cargo_yield: pd.DataFrame | None = None,
    v3: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build the H1-2026 validation reconciliation table."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    expectations = expectations if expectations is not None else (
        pd.read_csv(EXPECTATION_PATH) if EXPECTATION_PATH.exists() else pd.DataFrame()
    )
    calendar = calendar if calendar is not None else (
        pd.read_csv(FILING_CALENDAR_PATH) if FILING_CALENDAR_PATH.exists() else pd.DataFrame()
    )
    cargo_yield = cargo_yield if cargo_yield is not None else (
        pd.read_csv(CARGO_YIELD_PATH) if CARGO_YIELD_PATH.exists() else pd.DataFrame()
    )
    v3 = v3 if v3 is not None else (
        pd.read_csv(V3_PATH) if V3_PATH.exists() else pd.DataFrame()
    )
    rows: list[dict[str, Any]] = []
    if v3.empty:
        result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
        result.to_csv(OUTPUT_PATH, index=False)
        return result
    companies = sorted(v3["company"].dropna().unique())
    for company in companies:
        def first(df: pd.DataFrame, column: str) -> float | None:
            if df.empty or column not in df.columns:
                return None
            return _num(df.iloc[0].get(column))

        exp = expectations.loc[expectations["company"].eq(company)]
        cal = calendar.loc[
            calendar["company"].eq(company) & calendar["statement_period"].eq("1H2026")
        ]
        cargo = cargo_yield.loc[cargo_yield["company"].eq(company)]
        base = v3.loc[v3["company"].eq(company) & v3["scenario"].eq("base")]
        bear = v3.loc[v3["company"].eq(company) & v3["scenario"].eq("bear")]
        bull = v3.loc[v3["company"].eq(company) & v3["scenario"].eq("bull")]
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "filing_scheduled_date": (
                    cal.iloc[0].get("first_scheduled_date") if not cal.empty else None
                ),
                "calendar_status": (
                    cal.iloc[0].get("calendar_status") if not cal.empty else "missing_calendar"
                ),
                "h1_2026_ask_yoy_pct": first(exp, "h1_ask_yoy_pct"),
                "h1_2026_rpk_yoy_pct": first(exp, "h1_rpk_yoy_pct"),
                "h1_2026_passengers_yoy_pct": first(exp, "h1_passengers_yoy_pct"),
                "h1_2026_passenger_lf_change_pp": first(exp, "h1_passenger_lf_change_pp"),
                "h1_2026_cargo_tonnes_yoy_pct": first(exp, "h1_cargo_tonnes_yoy_pct"),
                "h1_2026_cargo_revenue_bridge_native_mn": first(
                    cargo, "h1_2026_cargo_revenue_bridge_native_mn"
                ),
                "h1_2026_cargo_revenue_anchor_period": (
                    cargo.iloc[0].get("revenue_anchor_period") if not cargo.empty else None
                ),
                "fy2026_v3_base_revenue_usd_mn": first(base, "v3_revenue_usd_mn"),
                "fy2026_v3_base_net_profit_usd_mn": first(base, "v3_net_profit_proxy_usd_mn"),
                "fy2026_v3_base_net_profit_consensus_guarded_usd_mn": first(
                    base, "v3_net_profit_consensus_guarded_usd_mn"
                ),
                "net_income_leg": (
                    base.iloc[0].get("net_income_leg") if not base.empty else None
                ),
                "regime_flip_flag": (
                    bool(base.iloc[0].get("regime_flip_flag")) if not base.empty else None
                ),
                "fy2026_v3_base_eps_rmb_per_share": first(
                    base, "v3_basic_eps_proxy_rmb_per_share"
                ),
                "fy2026_v3_bear_net_profit_usd_mn": first(bear, "v3_net_profit_proxy_usd_mn"),
                "fy2026_v3_bull_net_profit_usd_mn": first(bull, "v3_net_profit_proxy_usd_mn"),
                "consensus_fy2026_profit_usd_mn": first(
                    base, "consensus_fy2026_profit_usd_mn"
                ),
                "v3_base_vs_consensus_profit_gap_pct": (
                    (lambda m, c: None if m is None or not c else 100.0 * m / c - 100.0)(
                        first(base, "v3_net_profit_proxy_usd_mn"),
                        first(base, "consensus_fy2026_profit_usd_mn"),
                    )
                ),
                "validation_status": (
                    "awaiting_h1_2026_report"
                    if not cal.empty
                    and pd.isna(cal.iloc[0].get("actual_disclosure_date"))
                    else "actuals_ready_for_reconciliation"
                    if not cal.empty
                    else "missing_calendar"
                ),
                "source_note": (
                    "H1-2026 validation playbook: pre-report model forecasts and filing dates. "
                    "Actual columns are populated after the interim reports are published; error "
                    "columns then measure model versus reported reconciliation."
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
    "build_airline_h1_2026_validation_playbook",
    "source_path",
]
