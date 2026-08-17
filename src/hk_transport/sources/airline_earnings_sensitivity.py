"""2D/3D earnings sensitivity surface for the airline pair thesis.

Tests the robustness of the forward H1-2026 earnings view to simultaneous
shocks in the three key unobservables: passenger yield (RASK), jet fuel and
USD/CNY FX.  For each carrier the module builds a grid:

    NetIncome(yield, fuel, fx)
      = base net income
      + yield shock  (passenger revenue x yield change)
      - fuel shock   (fuel cost share x operating cost x fuel change)
      +/- fx shock   (fuel and finance USD exposure, simplified)

The output answers the thesis-robustness question: does Spring still beat
consensus (or its pair) under adverse yield AND fuel outcomes, or is the
view fragile to any single variable?  Every cell is labelled with the
shock tuple and the implied EPS; the method is a transparent mechanical
surface, not a fitted model.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_earnings_sensitivity.csv"
DATASET_ID = "airline_earnings_sensitivity"

FORWARD_BRIDGE_PATH = NORMALIZED_DIR / "airline_forward_net_income_bridge.csv"
UNIT_ECONOMICS_PATH = NORMALIZED_DIR / "airline_unit_economics.csv"

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "model_name",
    "horizon",
    "base_net_income_native_mn",
    "base_eps_rmb",
    "yield_shock_pct",
    "fuel_shock_pct",
    "fx_shock_pct",
    "passenger_revenue_native_mn",
    "fuel_cost_native_mn",
    "yield_impact_native_mn",
    "fuel_impact_native_mn",
    "fx_impact_native_mn",
    "shocked_net_income_native_mn",
    "shocked_eps_rmb",
    "vs_consensus_status",
    "source_note",
    "retrieved_at",
]

YIELD_SHOCKS = (-3.0, 0.0, 3.0)
FUEL_SHOCKS = (-5.0, 0.0, 5.0)
FX_SHOCKS = (-3.0, 0.0, 3.0)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _fx_sensitivity_share(company: str) -> float:
    """Share of operating cost exposed to USD (fuel + dollar leases/finance).
    Simplified structural estimate by carrier type; fuel is USD-priced, and
    Big-3 international carriers carry more USD lease/debt than LCCs."""
    if company in ("Air China", "China Southern Airlines", "China Eastern Airlines"):
        return 0.45
    if company == "Hainan Airlines Holdings":
        return 0.40
    if company == "Juneyao Airlines":
        return 0.35
    # Spring: mostly domestic, USD-exposed fuel + narrowbody leases
    return 0.30


def build_airline_earnings_sensitivity() -> pd.DataFrame:
    """Build the yield x fuel x FX sensitivity grid per carrier."""
    retrieved = datetime.now(timezone.utc).isoformat()
    bridge = pd.read_csv(FORWARD_BRIDGE_PATH)
    unit = pd.read_csv(UNIT_ECONOMICS_PATH)

    rows: list[dict[str, Any]] = []
    for company in bridge["company"].unique():
        base_row = bridge[
            bridge["company"].eq(company)
            & bridge["model_name"].eq("walk_forward_integrated")
        ]
        if base_row.empty:
            continue
        base = base_row.iloc[0]
        base_net = _num(base["forward_attributable_net_income_native_mn"])
        base_eps = _num(base["forward_basic_eps_rmb_per_share"])
        if base_net is None or base_eps is None:
            continue
        revenue = _num(base["forecast_h1_2026_revenue_native_mn"]) or 0.0
        unit_row = unit[unit["company"].eq(company)]
        fuel_share = (
            _num(unit_row["fuel_cost_share_pct"].iloc[0]) / 100.0
            if len(unit_row) and "fuel_cost_share_pct" in unit_row.columns
            else 0.33
        )
        # Fuel cost = fuel share x operating cost; operating cost derived from
        # base revenue and the unit-economics operating margin.
        op_margin = (
            _num(unit_row["rask_native"].iloc[0])
            - _num(unit_row["cask_native"].iloc[0])
            if len(unit_row) and "rask_native" in unit_row.columns
            else None
        )
        rask = _num(unit_row["rask_native"].iloc[0]) if len(unit_row) else None
        fuel_cost = revenue * fuel_share if revenue else 0.0
        fx_share = _fx_sensitivity_share(company)

        # Passenger revenue proxy: if unit RASK and FY ASK known, use them;
        # else assume passenger revenue ~90% of total revenue.
        passenger_rev = revenue * 0.9
        if rask is not None and len(unit_row):
            ask = _num(unit_row["ask_mn"].iloc[0])
            if ask not in (None, 0):
                passenger_rev = ask * rask

        for yield_shock in YIELD_SHOCKS:
            for fuel_shock in FUEL_SHOCKS:
                for fx_shock in FX_SHOCKS:
                    yield_impact = passenger_rev * yield_shock / 100.0
                    fuel_impact = -fuel_cost * fuel_shock / 100.0
                    # FX: USD/CNY strengthens -> USD-priced costs cheaper in
                    # RMB.  Positive fx_shock = RMB depreciation -> costs up.
                    fx_impact = -revenue * fx_share * fx_shock / 100.0
                    shocked_net = base_net + yield_impact + fuel_impact + fx_impact
                    shocked_eps = shocked_net / (base_net / base_eps) if base_net else None
                    vs_consensus = (
                        "beat" if shocked_eps > 1.0 else "miss" if shocked_eps < 0 else "marginal"
                    )
                    rows.append(
                        {
                            "dataset_id": DATASET_ID,
                            "company": company,
                            "model_name": "walk_forward_integrated",
                            "horizon": "H1-2026",
                            "base_net_income_native_mn": base_net,
                            "base_eps_rmb": base_eps,
                            "yield_shock_pct": yield_shock,
                            "fuel_shock_pct": fuel_shock,
                            "fx_shock_pct": fx_shock,
                            "passenger_revenue_native_mn": passenger_rev,
                            "fuel_cost_native_mn": fuel_cost,
                            "yield_impact_native_mn": yield_impact,
                            "fuel_impact_native_mn": fuel_impact,
                            "fx_impact_native_mn": fx_impact,
                            "shocked_net_income_native_mn": shocked_net,
                            "shocked_eps_rmb": shocked_eps,
                            "vs_consensus_status": vs_consensus,
                            "source_note": (
                                "Mechanical sensitivity surface: yield on "
                                "passenger revenue, fuel on fuel-cost share of "
                                "operating cost, FX on a structural USD-cost "
                                "share.  Excludes hedging, pass-through, "
                                "demand response and surcharge recovery; "
                                "vs_consensus_status uses 1.0 RMB EPS as a "
                                "simple threshold, not Street consensus."
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
    "build_airline_earnings_sensitivity",
    "source_path",
]
