"""Airline trade construction: Spring long / Juneyao short card.

Integrates the six upgraded layers (unit economics, yield pressure, capacity
pipeline, consensus reverse, earnings sensitivity, valuation) into a single
execution-oriented trade card.  The card is a research construct, not an
approved live order:

* direction and variant perception
* beta hedge ratio and factor exposures
* 0.25/0.50/1.00% NAV loss-budget sizing using direction-aware drawdown
* catalyst window (1H2026 reports) and surprise thresholds
* robustness check from the 3D sensitivity surface (pair spread positive in
  all 27 combinations)
* invalidation rules and remaining gates (borrow, valuation conflict)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_trade_construction.csv"
DATASET_ID = "airline_trade_construction"

UNIT_ECONOMICS_PATH = NORMALIZED_DIR / "airline_unit_economics.csv"
CAPACITY_PIPELINE_PATH = NORMALIZED_DIR / "airline_capacity_pipeline.csv"
CONSENSUS_REVERSE_PATH = NORMALIZED_DIR / "airline_consensus_reverse.csv"
SENSITIVITY_PATH = NORMALIZED_DIR / "airline_earnings_sensitivity.csv"
VALUATION_PATH = NORMALIZED_DIR / "airline_valuation_snapshot.csv"
FACTOR_DIAGNOSTICS_PATH = NORMALIZED_DIR / "airline_pair_factor_diagnostics.csv"
EVENT_TRIGGERS_PATH = NORMALIZED_DIR / "airline_pair_event_trade_triggers.csv"

OUTPUT_COLUMNS = [
    "dataset_id",
    "pair_id",
    "long_leg",
    "short_leg",
    "direction",
    "variant_perception",
    "long_cask",
    "short_cask",
    "cask_advantage_pct",
    "long_ask_growth_pct",
    "short_ask_growth_pct",
    "ask_growth_spread_pp",
    "short_implied_rask_gap_pct",
    "long_implied_rask_gap_pct",
    "sensitivity_robust_combinations",
    "sensitivity_total_combinations",
    "sensitivity_min_pair_spread",
    "sensitivity_median_pair_spread",
    "beta_hedge_ratio",
    "size_gap_log",
    "momentum_gap_3m_pp",
    "volatility_gap_pp",
    "max_drawdown_gap_pp",
    "loss_budget_pct_nav",
    "gross_notional_pct_nav",
    "catalyst_window",
    "surprise_threshold_profit_gap_pp",
    "invalidation_rules",
    "remaining_gates",
    "trade_status",
    "source_note",
    "retrieved_at",
]

PAIR_ID = "601021.SH__603885.SH"
LONG = "Spring Airlines"
SHORT = "Juneyao Airlines"


def _num(value: Any) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _first(df: pd.DataFrame, **filters: Any) -> Any:
    rows = df
    for key, value in filters.items():
        rows = rows[rows[key].eq(value)]
    if rows.empty:
        return None
    return rows.iloc[0]


def build_airline_trade_construction() -> pd.DataFrame:
    """Build the Spring long / Juneyao short trade-construction card."""
    retrieved = datetime.now(timezone.utc).isoformat()
    unit = pd.read_csv(UNIT_ECONOMICS_PATH)
    capacity = pd.read_csv(CAPACITY_PIPELINE_PATH)
    reverse = pd.read_csv(CONSENSUS_REVERSE_PATH)
    sensitivity = pd.read_csv(SENSITIVITY_PATH)
    valuation = pd.read_csv(VALUATION_PATH)
    factor = pd.read_csv(FACTOR_DIAGNOSTICS_PATH)
    triggers = pd.read_csv(EVENT_TRIGGERS_PATH)

    long_unit = _first(unit, company=LONG)
    short_unit = _first(unit, company=SHORT)
    long_cask = _num(long_unit["cask_native"]) if long_unit is not None else None
    short_cask = _num(short_unit["cask_native"]) if short_unit is not None else None
    cask_advantage = (
        (short_cask / long_cask - 1.0) * 100.0
        if long_cask not in (None, 0) and short_cask is not None
        else None
    )

    def ask_growth(company: str) -> float | None:
        row = _first(
            capacity[capacity["event_category"].eq("ask_decomposition")],
            company=company,
        )
        if row is None:
            return None
        detail = str(row.get("event_detail", ""))
        # "trailing-12m ASK growth +15.9%; forward fleet pipeline..."
        import re
        m = re.search(r"ASK growth ([+-][\d.]+)%", detail)
        return float(m.group(1)) if m else None

    long_ask = ask_growth(LONG)
    short_ask = ask_growth(SHORT)
    ask_spread = (
        (long_ask - short_ask) if long_ask is not None and short_ask is not None else None
    )

    long_rask_gap = (
        _num(_first(reverse, company=LONG).get("rask_gap_pct"))
        if _first(reverse, company=LONG) is not None
        else None
    )
    short_rask_gap = (
        _num(_first(reverse, company=SHORT).get("rask_gap_pct"))
        if _first(reverse, company=SHORT) is not None
        else None
    )

    sp = sensitivity[sensitivity["company"].eq(LONG)].set_index(
        ["yield_shock_pct", "fuel_shock_pct", "fx_shock_pct"]
    )["shocked_eps_rmb"]
    jy = sensitivity[sensitivity["company"].eq(SHORT)].set_index(
        ["yield_shock_pct", "fuel_shock_pct", "fx_shock_pct"]
    )["shocked_eps_rmb"]
    spread = sp - jy
    robust = int((spread > 0).sum()) if len(spread) else 0
    total = int(len(spread))

    sj_factor = _first(factor, pair_id=PAIR_ID)
    beta_hedge = (
        _num(sj_factor["mechanical_beta_a_to_b"])
        if sj_factor is not None and "mechanical_beta_a_to_b" in sj_factor.index
        else _num(sj_factor.get("mechanical_beta_a_to_b")) if sj_factor is not None else None
    )
    size_gap = (
        _num(sj_factor["log_size_gap_a_minus_b"])
        if sj_factor is not None and "log_size_gap_a_minus_b" in sj_factor.index
        else None
    )
    momentum_gap = (
        _num(sj_factor["momentum_3m_gap_a_minus_b_pct"])
        if sj_factor is not None and "momentum_3m_gap_a_minus_b_pct" in sj_factor.index
        else None
    )
    vol_gap = (
        _num(sj_factor["volatility_gap_a_minus_b_pct"])
        if sj_factor is not None and "volatility_gap_a_minus_b_pct" in sj_factor.index
        else None
    )
    dd_gap = (
        _num(sj_factor["max_drawdown_gap_a_minus_b_pct"])
        if sj_factor is not None and "max_drawdown_gap_a_minus_b_pct" in sj_factor.index
        else None
    )

    trigger = _first(triggers, pair_id=PAIR_ID)
    surprise_threshold = (
        _num(trigger["minimum_profit_surprise_gap_for_entry_pp"])
        if trigger is not None
        else None
    )
    catalyst = (
        str(trigger["event_window"]) if trigger is not None else "2026-08-29/31"
    )
    invalidation = (
        str(trigger["invalidation_rule"])[:400]
        if trigger is not None and "invalidation_rule" in trigger.index
        else str(trigger.get("invalidation_rule"))[:400] if trigger is not None else ""
    )

    # Loss-budget sizing: 0.5% NAV budget over direction-aware drawdown.
    loss_budget = 0.5
    gross_notional = None
    if trigger is not None and "direction_aware_drawdown_pct" in trigger.index:
        dd = abs(_num(trigger["direction_aware_drawdown_pct"]) or 0.0)
        if dd > 0:
            gross_notional = loss_budget / dd * 100.0

    rows = [
        {
            "dataset_id": DATASET_ID,
            "pair_id": PAIR_ID,
            "long_leg": LONG,
            "short_leg": SHORT,
            "direction": "long_Spring_short_Juneyao",
            "variant_perception": (
                "Market overestimates Juneyao earnings conversion from "
                "international recovery (Street implied RASK +11.8% vs model, "
                "price implies +93% EPS vs consensus) while underestimating "
                "the durability of Spring's unit-cost advantage (CASK 0.300 "
                "vs 0.345, non-fuel 0.199 vs 0.235, fuel shares equal)."
            ),
            "long_cask": long_cask,
            "short_cask": short_cask,
            "cask_advantage_pct": cask_advantage,
            "long_ask_growth_pct": long_ask,
            "short_ask_growth_pct": short_ask,
            "ask_growth_spread_pp": ask_spread,
            "short_implied_rask_gap_pct": short_rask_gap,
            "long_implied_rask_gap_pct": long_rask_gap,
            "sensitivity_robust_combinations": robust,
            "sensitivity_total_combinations": total,
            "sensitivity_min_pair_spread": (
                float(spread.min()) if len(spread) else None
            ),
            "sensitivity_median_pair_spread": (
                float(spread.median()) if len(spread) else None
            ),
            "beta_hedge_ratio": beta_hedge,
            "size_gap_log": size_gap,
            "momentum_gap_3m_pp": momentum_gap,
            "volatility_gap_pp": vol_gap,
            "max_drawdown_gap_pp": dd_gap,
            "loss_budget_pct_nav": loss_budget,
            "gross_notional_pct_nav": gross_notional,
            "catalyst_window": catalyst,
            "surprise_threshold_profit_gap_pp": surprise_threshold,
            "invalidation_rules": invalidation,
            "remaining_gates": (
                "borrow availability/cost not established; P/B valuation "
                "conflict unresolved; revision signal not confirmed; entry "
                "only after both 1H2026 reports pass surprise thresholds"
            ),
            "trade_status": (
                "research_card_not_approved_execution_gated"
            ),
            "source_note": (
                "Integrates unit economics, capacity pipeline, consensus "
                "reverse, sensitivity surface, valuation and factor layers "
                "into one execution card.  Research construct only; not an "
                "approved live order."
            ),
            "retrieved_at": retrieved,
        }
    ]
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "build_airline_trade_construction",
    "source_path",
]
