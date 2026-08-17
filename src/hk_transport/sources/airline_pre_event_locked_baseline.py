"""Pre-event locked baseline for the 1H2026 report cycle (goal item 2).

Freezes the six mainland carriers' pre-report forecast positions into one
point-in-time snapshot, so that after each 1H2026 print the validation
playbook and post-earnings tracker can be reconciled against exactly what
was on the table before the catalyst - not against whatever the model says
after the fact.

The baseline joins:

    filing calendar dates
      + H1-2026 ASK/RPK YoY from the expectation bridge
      + H1-2026 revenue forecast from the residual-yield (flat-yield) model
      + fuel price / fuel-CASK / total-CASK from the driver-based CASK model
      + FY2026 v3 base net profit (post NCI/operating-contribution fix)
      + FY2026 consensus net profit and implied margin

Every row is stamped with the snapshot date; ``locked`` means the numbers
are final pre-event values and must not be silently revised after the
report (any correction becomes a new row / explicit amendment note).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_pre_event_locked_baseline.csv"
DATASET_ID = "airline_pre_event_locked_baseline"

FILING_PATH = NORMALIZED_DIR / "airline_filing_calendar.csv"
EXPECTATION_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
YIELD_PATH = NORMALIZED_DIR / "airline_residual_yield_model.csv"
CASK_PATH = NORMALIZED_DIR / "airline_cask_driver_model.csv"
V3_PATH = NORMALIZED_DIR / "airline_earnings_model_v3.csv"
CONSENSUS_REVERSE_PATH = NORMALIZED_DIR / "airline_consensus_reverse.csv"

COMPANIES = [
    "Air China",
    "China Eastern Airlines",
    "China Southern Airlines",
    "Hainan Airlines Holdings",
    "Juneyao Airlines",
    "Spring Airlines",
]

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "ticker",
    "filing_scheduled_date",
    "h1_2026_ask_yoy_pct",
    "h1_2026_rpk_yoy_pct",
    "h1_2026_flat_yield_revenue_native_mn",
    "fuel_price_usd_per_gallon",
    "fuel_cask_forecast_native",
    "total_cask_forecast_native",
    "v3_base_fy2026_net_profit_usd_mn",
    "v3_net_income_leg",
    "consensus_fy2026_profit_usd_mn",
    "model_vs_consensus_gap_pct",
    "consensus_implied_net_margin_pct",
    "snapshot_date",
    "lock_status",
    "source_note",
    "retrieved_at",
]


def _num(value: object) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _row(frame: pd.DataFrame, **criteria: object) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=object)
    mask = pd.Series(True, index=frame.index)
    for column, value in criteria.items():
        if column not in frame.columns:
            return pd.Series(dtype=object)
        mask &= frame[column].eq(value)
    rows = frame.loc[mask]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def build_airline_pre_event_locked_baseline(*, overwrite: bool = False) -> pd.DataFrame:
    """Build or read the locked pre-event baseline snapshot (1H2026).

    Normal pipeline runs must not silently replace a pre-event anchor after
    new data or post-report information arrives.  A deliberate ``overwrite``
    is available for creating a new explicit lock after reviewing the inputs.
    """
    if OUTPUT_PATH.exists() and not overwrite:
        return pd.read_csv(OUTPUT_PATH)
    retrieved = datetime.now(timezone.utc).isoformat()
    snapshot_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filing = pd.read_csv(FILING_PATH)
    expectation = pd.read_csv(EXPECTATION_PATH)
    yield_model = pd.read_csv(YIELD_PATH)
    cask = pd.read_csv(CASK_PATH)
    v3 = pd.read_csv(V3_PATH)
    reverse = pd.read_csv(CONSENSUS_REVERSE_PATH)

    rows: list[dict[str, Any]] = []
    for company in COMPANIES:
        cal = _row(filing, company=company, statement_period="1H2026")
        exp = _row(expectation, company=company)
        yld = _row(
            yield_model,
            company=company,
            period="H1",
            target_year=2026,
            row_status="current_forecast",
        )
        ck = _row(cask, company=company, period="H1", target_year=2026)
        v3b = _row(v3, company=company, scenario="base")
        rev = _row(reverse, company=company, fiscal_year=2026)

        ask_yoy = _num(exp.get("h1_ask_yoy_pct"))
        rpk_yoy = _num(exp.get("h1_rpk_yoy_pct"))
        flat_yield_revenue = _num(yld.get("flat_yield_revenue_native_mn"))
        fuel_price = _num(ck.get("fuel_price_usd_per_gallon"))
        fuel_cask = _num(ck.get("fuel_cask_forecast"))
        total_cask = _num(ck.get("cask_forecast"))
        model_profit = _num(v3b.get("v3_net_profit_proxy_usd_mn"))
        consensus_profit = _num(v3b.get("consensus_fy2026_profit_usd_mn"))
        model_vs_consensus = (
            (model_profit / consensus_profit - 1.0) * 100.0
            if model_profit is not None and consensus_profit
            else None
        )
        implied_margin = _num(rev.get("consensus_net_margin_pct"))
        if implied_margin is None:
            implied_margin = _num(v3b.get("consensus_implied_margin_pct"))

        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "ticker": str(cal.get("ticker", "")) if not cal.empty else "",
                "filing_scheduled_date": str(cal.get("first_scheduled_date", "")) if not cal.empty else "",
                "h1_2026_ask_yoy_pct": ask_yoy,
                "h1_2026_rpk_yoy_pct": rpk_yoy,
                "h1_2026_flat_yield_revenue_native_mn": flat_yield_revenue,
                "fuel_price_usd_per_gallon": fuel_price,
                "fuel_cask_forecast_native": fuel_cask,
                "total_cask_forecast_native": total_cask,
                "v3_base_fy2026_net_profit_usd_mn": model_profit,
                "v3_net_income_leg": str(v3b.get("net_income_leg", "")),
                "consensus_fy2026_profit_usd_mn": consensus_profit,
                "model_vs_consensus_gap_pct": model_vs_consensus,
                "consensus_implied_net_margin_pct": implied_margin,
                "snapshot_date": snapshot_date,
                "lock_status": "locked",
                "source_note": (
                    "Pre-event locked baseline for the 1H2026 report cycle. "
                    "H1 revenue is the residual-yield flat-yield forecast "
                    "(ASK x prior RASK); CASK is the driver-based model at "
                    "the snapshot fuel price; FY2026 profit is the v3 base "
                    "post NCI/operating-contribution fix. Locked numbers "
                    "are the pre-report position; post-print corrections "
                    "belong in the validation playbook / post-earnings "
                    "tracker, not here."
                ),
                "retrieved_at": retrieved,
            }
        )

    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    result = result.sort_values("company").reset_index(drop=True)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "build_airline_pre_event_locked_baseline",
    "source_path",
]
