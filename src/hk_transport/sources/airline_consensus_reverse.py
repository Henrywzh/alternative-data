"""Consensus reverse engineering for the airline long/short layer.

Instead of comparing our EPS with consensus as a single number, this module
reverses the Street's FY2026 net-profit consensus into the operating
assumptions it implies - margin, RASK, CASK - and compares those with our
own model's assumptions.  The output is the assumption gap, not a forecast.

Reverse path:

    consensus net profit
      -> + tax (effective rate)          = implied profit before tax
      -> + finance cost - non-operating  = implied operating profit
      -> implied operating margin on consensus revenue
      -> implied RASK = (consensus revenue - non-passenger) / ASK
      -> implied CASK = (consensus revenue - implied op profit) / ASK

Each step is labelled with the anchor used, and the comparison with the v2/v3
model assumptions is explicit.  This is the "what is the market assuming"
layer: for example, consensus Spring revenue with our ASK implies a
consensus RASK that may differ materially from our unit-economics RASK.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_consensus_reverse.csv"
DATASET_ID = "airline_consensus_reverse"

CONSENSUS_ASHARE_PATH = NORMALIZED_DIR / "airline_consensus_ashare_detailed.csv"
V2_BRIDGE_PATH = NORMALIZED_DIR / "airline_company_financial_forecast_bridge.csv"
DRIVERS_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
V3_PATH = NORMALIZED_DIR / "airline_earnings_model_v3.csv"

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "fiscal_year",
    "consensus_revenue_native_mn",
    "consensus_net_profit_native_mn",
    "consensus_net_margin_pct",
    "consensus_profit_before_tax_native_mn",
    "implied_operating_profit_native_mn",
    "implied_operating_margin_pct",
    "model_ask_mn",
    "model_non_passenger_revenue_native_mn",
    "implied_rask_native",
    "implied_cask_native",
    "model_rask_native",
    "model_cask_native",
    "rask_gap_pct",
    "cask_gap_pct",
    "margin_gap_pp",
    "reverse_method",
    "anchor_source",
    "source_note",
    "retrieved_at",
]

COMPANY_ORDER = [
    "Spring Airlines",
    "Juneyao Airlines",
    "China Southern Airlines",
    "China Eastern Airlines",
    "Air China",
    "Hainan Airlines Holdings",
]


def _num(value: Any) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _load_consensus() -> pd.DataFrame:
    if not CONSENSUS_ASHARE_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(CONSENSUS_ASHARE_PATH)


def _load_v2() -> pd.DataFrame:
    if not V2_BRIDGE_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(V2_BRIDGE_PATH)


def _load_drivers() -> pd.DataFrame:
    if not DRIVERS_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(DRIVERS_PATH)


def _load_v3() -> pd.DataFrame:
    if not V3_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(V3_PATH)


def _effective_tax_rate(drivers: pd.DataFrame, company: str) -> float | None:
    # Prefer the interim (1H2025) tax rate: Spring/Juneyao annual statements
    # are scanned-image PDFs with no tax line in the driver layer, while their
    # interim reports disclose it (Spring 1H2025 tax/PBT ~24.3%, Juneyao
    # ~25.9%).  Fall back to the annual rate where both lines exist.
    for report_type in ("interim", "annual"):
        rows = drivers[
            drivers["company"].eq(company) & drivers["report_type"].eq(report_type)
        ]
        pbt = _num(
            rows[rows["metric"].eq("profit_total")]["value_native"].iloc[0]
            if len(rows[rows["metric"].eq("profit_total")])
            else None
        )
        tax = _num(
            rows[rows["metric"].eq("income_tax_expense")]["value_native"].iloc[0]
            if len(rows[rows["metric"].eq("income_tax_expense")])
            else None
        )
        if pbt not in (None, 0) and tax is not None and pbt != 0:
            rate = tax / pbt
            # Guard: loss-year deferred-tax artifacts (e.g. Southern 239%)
            # are not usable as a forward tax rate.
            if 0.0 <= rate <= 0.6:
                return rate
    return None


def _below_operating_anchors(
    drivers: pd.DataFrame,
    company: str,
) -> tuple[float | None, float | None]:
    """Finance cost and non-operating net from the FY2025 annual waterfall,
    used to step from PBT to operating profit (the reverse of the earnings
    bridge)."""
    annual = drivers[
        drivers["company"].eq(company) & drivers["report_type"].eq("annual")
    ]
    finance = _num(
        annual[annual["metric"].eq("finance_cost")]["value_native"].iloc[0]
        if len(annual[annual["metric"].eq("finance_cost")])
        else None
    )
    non_op_income = _num(
        annual[annual["metric"].eq("non_operating_income")]["value_native"].iloc[0]
        if len(annual[annual["metric"].eq("non_operating_income")])
        else None
    )
    non_op_expense = _num(
        annual[annual["metric"].eq("non_operating_expense")]["value_native"].iloc[0]
        if len(annual[annual["metric"].eq("non_operating_expense")])
        else None
    )
    other_income = _num(
        annual[annual["metric"].eq("other_income")]["value_native"].iloc[0]
        if len(annual[annual["metric"].eq("other_income")])
        else None
    )
    investment = _num(
        annual[annual["metric"].eq("investment_income")]["value_native"].iloc[0]
        if len(annual[annual["metric"].eq("investment_income")])
        else None
    )
    # PBT = operating + other + investment - finance - non-op expense
    # => operating = PBT - other - investment + finance + non-op expense
    return finance, (non_op_expense or 0.0) - (non_op_income or 0.0) - (
        other_income or 0.0
    ) - (investment or 0.0)


def build_airline_consensus_reverse(
    *,
    fiscal_year: int = 2026,
) -> pd.DataFrame:
    """Reverse consensus net profit into implied operating assumptions."""
    retrieved = datetime.now(timezone.utc).isoformat()
    consensus = _load_consensus()
    v2 = _load_v2()
    drivers = _load_drivers()
    v3 = _load_v3()

    rows: list[dict[str, Any]] = []
    for company in COMPANY_ORDER:
        c_rev = consensus[
            consensus["company"].eq(company)
            & consensus["fiscal_year"].eq(fiscal_year)
            & consensus["metric"].eq("revenue")
        ]
        c_profit = consensus[
            consensus["company"].eq(company)
            & consensus["fiscal_year"].eq(fiscal_year)
            & consensus["metric"].eq("net_profit_detailed")
        ]
        if c_rev.empty or c_profit.empty:
            continue
        consensus_rev = _num(c_rev["value_avg_native"].iloc[0]) * 100.0  # 亿 -> mn
        consensus_profit = _num(c_profit["value_avg_native"].iloc[0]) * 100.0
        if consensus_rev in (None, 0) or consensus_profit is None:
            continue
        net_margin = consensus_profit / consensus_rev * 100.0

        tax_rate = _effective_tax_rate(drivers, company)
        finance, non_op_net = _below_operating_anchors(drivers, company)
        # Below-operating anchors missing for Spring/Juneyao annual (scanned
        # images) - fall back to the interim report anchors where present.
        if finance is None:
            interim = drivers[
                drivers["company"].eq(company) & drivers["report_type"].eq("interim")
            ]
            finance = _num(
                interim[interim["metric"].eq("finance_cost")]["value_native"].iloc[0]
                if len(interim[interim["metric"].eq("finance_cost")])
                else None
            )
        if tax_rate is not None:
            implied_pbt = consensus_profit / (1 - tax_rate) if tax_rate < 1 else None
            pbt_method = "consensus_net_profit / (1 - effective_tax_rate)"
        else:
            implied_pbt = None
            pbt_method = "tax_anchor_missing"
        implied_op = None
        op_method = "missing_anchors"
        if implied_pbt is not None and finance is not None:
            # operating = PBT + finance - non-operating net (reverse bridge)
            implied_op = implied_pbt + finance - non_op_net
            op_method = "pbt + finance - non_operating_net"

        v2_row = v2[v2["company"].eq(company) & v2["scenario"].eq("base")]
        model_ask = (
            _num(v2_row["forecast_ask_mn_seat_km"].iloc[0])
            if len(v2_row) and "forecast_ask_mn_seat_km" in v2_row.columns
            else None
        )
        v3_row = v3[v3["company"].eq(company) & v3["scenario"].eq("base")]
        model_non_passenger = (
            _num(v3_row["v3_nonpassenger_revenue_native_mn"].iloc[0])
            if len(v3_row) and "v3_nonpassenger_revenue_native_mn" in v3_row.columns
            else None
        )
        model_op = (
            _num(v3_row["v3_operating_profit_native_mn"].iloc[0])
            if len(v3_row) and "v3_operating_profit_native_mn" in v3_row.columns
            else None
        )
        model_revenue = (
            _num(v3_row["v3_revenue_native_mn"].iloc[0])
            if len(v3_row) and "v3_revenue_native_mn" in v3_row.columns
            else None
        )

        implied_rask = None
        implied_cask = None
        if model_ask not in (None, 0) and model_non_passenger is not None:
            implied_rask = (consensus_rev - model_non_passenger) / model_ask
        if model_ask not in (None, 0) and implied_op is not None:
            implied_cask = (consensus_rev - implied_op) / model_ask
        model_rask = (
            (model_revenue - model_non_passenger) / model_ask
            if model_revenue is not None and model_non_passenger is not None
            and model_ask not in (None, 0)
            else None
        )
        model_cask = (
            (model_revenue - model_op) / model_ask
            if model_revenue is not None and model_op is not None
            and model_ask not in (None, 0)
            else None
        )

        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "fiscal_year": fiscal_year,
                "consensus_revenue_native_mn": consensus_rev,
                "consensus_net_profit_native_mn": consensus_profit,
                "consensus_net_margin_pct": net_margin,
                "consensus_profit_before_tax_native_mn": implied_pbt,
                "implied_operating_profit_native_mn": implied_op,
                "implied_operating_margin_pct": (
                    implied_op / consensus_rev * 100.0
                    if implied_op is not None and consensus_rev not in (None, 0)
                    else None
                ),
                "model_ask_mn": model_ask,
                "model_non_passenger_revenue_native_mn": model_non_passenger,
                "implied_rask_native": implied_rask,
                "implied_cask_native": implied_cask,
                "model_rask_native": model_rask,
                "model_cask_native": model_cask,
                "rask_gap_pct": (
                    (implied_rask / model_rask - 1.0) * 100.0
                    if implied_rask is not None and model_rask not in (None, 0)
                    else None
                ),
                "cask_gap_pct": (
                    (implied_cask / model_cask - 1.0) * 100.0
                    if implied_cask is not None and model_cask not in (None, 0)
                    else None
                ),
                "margin_gap_pp": (
                    net_margin
                    - (
                        model_op / model_revenue * 100.0
                        if model_op is not None and model_revenue not in (None, 0)
                        else None
                    )
                    if model_op is not None and model_revenue not in (None, 0)
                    else None
                ),
                "reverse_method": (
                    f"consensus_net->pbt via {pbt_method}; op via {op_method}"
                ),
                "anchor_source": (
                    "consensus_ashare_detailed + fy2025_annual_waterfall + v2/v3_model"
                ),
                "source_note": (
                    "Consensus reverse engineering: implied RASK/CASK use the "
                    "A-share consensus FY2026 revenue and net profit stepped "
                    "back through the tax and below-operating anchors, "
                    "divided by the model's FY2026 ASK.  Implied values are "
                    "what Street revenue/profit implies under our ASK, not "
                    "Street's own RASK/CASK.  Anchors missing -> blank."
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
        "build_airline_consensus_reverse",
        "source_path",
    ]
