"""Forward FX and tax assumptions for the airline earnings model v3.

The v3 net-income bridge carries FY2025 absolute below-operating rows when a
formal statement reconciles.  This module adds two explicit forward
assumptions so the bridge can be stress-tested instead of frozen at FY2025
values:

- Effective tax rate: FY2025 reported income-tax expense divided by reported
  profit before tax, where both are available and the rate is interpretable.
  Loss-making issuers with tax expense from deferred-tax reversals keep the
  absolute FY2025 tax carry and are flagged ``loss_with_reversal_tax``.
- Forward FX: the latest ECB USD/CNY reference rate, labelled as a carry
  assumption rather than a forecast.

Neither assumption is issuer guidance.  They are research assumptions with
explicit status and source fields.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


OFFICIAL_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
FX_PATH = NORMALIZED_DIR / "airline_fx_rates.parquet"
OUTPUT_PATH = NORMALIZED_DIR / "airline_forward_assumptions.csv"
DATASET_ID = "airline_forward_assumptions"

COMPANIES = (
    "Air China",
    "China Southern Airlines",
    "China Eastern Airlines",
    "Spring Airlines",
    "Hainan Airlines Holdings",
    "Juneyao Airlines",
)

# FY2025 income-tax expense rows that the generic PDF parser cannot safely
# read from the annual report layout. Each value is hand-verified against the
# cited issuer document page. Spring and Juneyao annual reports do not contain
# a consolidated income statement; the tax line is disclosed in the notes
# (Spring p25 management table, Juneyao p165 tax reconciliation). Eastern's
# income statement is not in the annual report; the narrative on p12 states
# deferred-tax reversal increased tax expense, and the main data table on
# p11-12 supports a 1,907 RMBm tax figure.
CURATED_FY2025_TAX_ANCHORS: dict[str, dict[str, object]] = {
    "Spring Airlines": {
        "value_native_mn": 712.853155,
        "source_page": 25,
        "source_note": "Spring FY2025 annual report main financial-data table: income tax expense 712,853,155 yuan (page 25).",
    },
    "Juneyao Airlines": {
        "value_native_mn": 347.329900,
        "source_page": 165,
        "source_note": "Juneyao FY2025 annual report note 51 tax reconciliation: income tax expense 347,329,899.66 yuan (page 165).",
    },
    "China Eastern Airlines": {
        "value_native_mn": 1907.0,
        "source_page": 12,
        "source_note": "Eastern FY2025 annual report main financial-data table and p12 narrative: income tax expense RMB1,907m (deferred-tax reversal).",
    },
}

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "fy2025_profit_before_tax_native_mn",
    "fy2025_income_tax_expense_native_mn",
    "income_tax_source_page",
    "income_tax_source_note",
    "fy2025_effective_tax_rate_pct",
    "tax_assumption_status",
    "forward_fx_usd_cny",
    "forward_fx_observation_date",
    "forward_fx_status",
    "source_note",
    "retrieved_at",
]


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def build_airline_forward_assumptions(
    *,
    official: pd.DataFrame | None = None,
    fx: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build the forward tax-rate and FX assumption table."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    official = official if official is not None else (
        pd.read_csv(OFFICIAL_PATH) if OFFICIAL_PATH.exists() else pd.DataFrame()
    )
    fx = fx if fx is not None else (
        pd.read_parquet(FX_PATH) if FX_PATH.exists() else pd.DataFrame()
    )
    rows: list[dict[str, Any]] = []
    fx_row = None
    if not fx.empty:
        usd_cny = fx.loc[fx["pair"].eq("USD_CNY")].copy()
        usd_cny["date_parsed"] = pd.to_datetime(usd_cny["observation_date"], errors="coerce")
        usd_cny = usd_cny.dropna(subset=["date_parsed"])
        if not usd_cny.empty:
            latest = usd_cny.sort_values("date_parsed").iloc[-1]
            fx_row = {
                "value": _num(latest.get("value")),
                "date": str(latest.get("observation_date")),
            }
    for company in COMPANIES:
        def metric_value(period: str, metric: str) -> float | None:
            if official.empty:
                return None
            selected = official.loc[
                official["company"].eq(company)
                & official["statement_period"].eq(period)
                & official["metric"].eq(metric)
            ]
            return _num(selected.iloc[0].get("value_native")) if not selected.empty else None

        profit_total = metric_value("FY2025", "profit_total")
        tax = metric_value("FY2025", "income_tax_expense")
        tax_source_page = None
        tax_source_note = None
        if tax is None and company in CURATED_FY2025_TAX_ANCHORS:
            anchor = CURATED_FY2025_TAX_ANCHORS[company]
            tax = _num(anchor.get("value_native_mn"))
            tax_source_page = anchor.get("source_page")
            tax_source_note = str(anchor.get("source_note"))
        if profit_total is not None and tax is not None and profit_total > 0:
            effective_rate = 100.0 * tax / profit_total
            tax_status = (
                "fy2025_effective_tax_rate_carry"
                if effective_rate <= 100.0
                else "extreme_rate_deferred_tax_effects_absolute_carry_required"
            )
            if effective_rate > 100.0:
                effective_rate = None
        elif profit_total is not None and tax is not None and profit_total <= 0:
            effective_rate = None
            tax_status = "loss_with_reversal_tax_absolute_carry_required"
        elif profit_total is not None and tax is not None:
            effective_rate = 100.0 * tax / profit_total
            tax_status = "fy2025_effective_tax_rate_carry"
        else:
            effective_rate = None
            tax_status = "missing_fy2025_tax_anchor"
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "fy2025_profit_before_tax_native_mn": profit_total,
                "fy2025_income_tax_expense_native_mn": tax,
                "income_tax_source_page": tax_source_page,
                "income_tax_source_note": tax_source_note,
                "fy2025_effective_tax_rate_pct": effective_rate,
                "tax_assumption_status": tax_status,
                "forward_fx_usd_cny": fx_row["value"] if fx_row else None,
                "forward_fx_observation_date": fx_row["date"] if fx_row else None,
                "forward_fx_status": (
                    "latest_ecb_reference_carry_not_forecast"
                    if fx_row
                    else "missing_fx_reference"
                ),
                "source_note": (
                    "Tax rate is FY2025 reported tax/profit-before-tax and is not a forward tax "
                    "regime view; issuers with deferred-tax reversals on losses keep the absolute "
                    "FY2025 tax carry. FX is the latest ECB reference rate carried forward, not a "
                    "forecast."
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
    "build_airline_forward_assumptions",
    "source_path",
]
