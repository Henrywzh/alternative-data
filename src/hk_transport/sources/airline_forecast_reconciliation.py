"""Reconcile the broad mechanical bridge with the opinionated core-pair view.

The two upstream models have different purposes and should not be silently
collapsed:

* ``airline_company_financial_forecast_bridge.csv`` is a six-company,
  direction-neutral screen.  It separates passenger RASK from non-passenger
  revenue and uses a simple CASK stress.
* ``airline_independent_forecast_view.csv`` is the analyst view for the
  Spring/Juneyao pair.  It uses all-in revenue-per-ASK and an explicit
  non-fuel cost-per-ASK judgement.

This output makes the difference auditable before a pair direction is chosen.
It is not a new forecast and does not select a trade.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR


BRIDGE_PATH = NORMALIZED_DIR / "airline_company_financial_forecast_bridge.csv"
INDEPENDENT_PATH = NORMALIZED_DIR / "airline_independent_forecast_view.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_forecast_reconciliation.csv"
COMPANIES = ("Spring Airlines", "Juneyao Airlines")


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _as_of(*frames: pd.DataFrame) -> str:
    values: list[str] = []
    for frame in frames:
        for column in ("as_of_date", "forecast_horizon", "retrieved_at"):
            if column in frame.columns:
                values.extend(str(value)[:10] for value in frame[column].dropna())
    valid = [value for value in values if len(value) == 10 and value[4] == "-" and value[7] == "-"]
    return max(valid) if valid else datetime.now(timezone.utc).date().isoformat()


def build_airline_forecast_reconciliation(
    *,
    bridge: pd.DataFrame | None = None,
    independent: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build a base-case reconciliation for the two core-pair names."""
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    independent = independent if independent is not None else pd.read_csv(INDEPENDENT_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    as_of = _as_of(bridge, independent)
    bridge_base = bridge[bridge["company"].isin(COMPANIES) & bridge["scenario"].eq("base")].copy()
    independent_base = independent[
        independent["company"].isin(COMPANIES) & independent["scenario"].eq("base")
    ].copy()

    rows: list[dict[str, object]] = []
    for company in COMPANIES:
        b = bridge_base[bridge_base["company"].eq(company)]
        i = independent_base[independent_base["company"].eq(company)]
        if b.empty or i.empty:
            continue
        b = b.iloc[0]
        i = i.iloc[0]
        fx = _num(i.get("fx_native_per_usd"))
        independent_cost_usd = (
            _num(i.get("independent_operating_cost_native_mn")) / fx
            if _num(i.get("independent_operating_cost_native_mn")) is not None and fx
            else None
        )
        independent_operating_profit_usd = (
            _num(i.get("independent_operating_profit_native_mn")) / fx
            if _num(i.get("independent_operating_profit_native_mn")) is not None and fx
            else None
        )
        bridge_revenue = _num(b.get("forecast_revenue_usd_mn"))
        independent_revenue = _num(i.get("independent_revenue_usd_mn"))
        bridge_cost = _num(b.get("forecast_operating_cost_usd_mn"))
        bridge_profit = _num(b.get("earnings_proxy_after_fuel_usd_mn"))
        independent_profit = _num(i.get("independent_profit_usd_mn"))
        revenue_delta = bridge_revenue - independent_revenue if bridge_revenue is not None and independent_revenue is not None else None
        cost_delta = bridge_cost - independent_cost_usd if bridge_cost is not None and independent_cost_usd is not None else None
        profit_delta = bridge_profit - independent_profit if bridge_profit is not None and independent_profit is not None else None
        if revenue_delta is None or cost_delta is None:
            primary_driver = "insufficient_reconciliation_inputs"
        elif abs(cost_delta) > abs(revenue_delta):
            primary_driver = "cost_assumption_difference"
        else:
            primary_driver = "revenue_scope_or_RASK_difference"

        rows.append(
            {
                "dataset_id": "airline_forecast_reconciliation",
                "company": company,
                "scenario": "base",
                "as_of_date": as_of,
                "bridge_model": "six_company_mechanical_bridge",
                "independent_model": "core_pair_analyst_view",
                "bridge_revenue_definition": "passenger_RASK_times_ASK_plus_nonpassenger_revenue_proxy",
                "independent_revenue_definition": "all_in_FY2025_revenue_per_ASK_times_forecast_ASK_and_yield_mix",
                "bridge_revenue_usd_mn": bridge_revenue,
                "independent_revenue_usd_mn": independent_revenue,
                "revenue_delta_bridge_minus_independent_usd_mn": revenue_delta,
                "revenue_delta_pct_vs_independent": 100.0 * revenue_delta / independent_revenue if revenue_delta is not None and independent_revenue else None,
                "bridge_operating_cost_usd_mn": bridge_cost,
                "independent_operating_cost_usd_mn": independent_cost_usd,
                "operating_cost_delta_bridge_minus_independent_usd_mn": cost_delta,
                "bridge_operating_profit_usd_mn": _num(b.get("forecast_operating_profit_usd_mn")),
                "independent_operating_profit_usd_mn": independent_operating_profit_usd,
                "bridge_earnings_proxy_usd_mn": bridge_profit,
                "independent_profit_usd_mn": independent_profit,
                "profit_delta_bridge_minus_independent_usd_mn": profit_delta,
                "bridge_ask_growth_pct": _num(b.get("ask_growth_assumption_pct")),
                "independent_ask_growth_pct": _num(i.get("ask_growth_assumption_pct")),
                "bridge_rpk_growth_pct": _num(b.get("rpk_growth_assumption_pct")),
                "independent_rpk_growth_pct": _num(i.get("rpk_growth_assumption_pct")),
                "bridge_passenger_rask_growth_pct": _num(b.get("rask_growth_assumption_pct_vs_fy2025")),
                "independent_yield_mix_growth_pct": _num(i.get("yield_mix_growth_assumption_pct")),
                "bridge_cask_growth_pct": _num(b.get("cask_growth_assumption_pct_vs_fy2025")),
                "independent_nonfuel_cost_per_ask_growth_pct": _num(i.get("nonfuel_cost_per_ask_growth_assumption_pct")),
                "bridge_nonpassenger_revenue_growth_pct": _num(b.get("nonpassenger_revenue_growth_assumption_pct")),
                "bridge_fuel_shock_pct": _num(b.get("fuel_shock_pct")),
                "independent_fuel_shock_pct": _num(i.get("fuel_price_shock_assumption_pct")),
                "consensus_profit_usd_mn": _num(b.get("consensus_fy2026_profit_usd_mn")),
                "bridge_profit_gap_vs_consensus_pct": _num(b.get("earnings_gap_to_consensus_pct")),
                "independent_profit_gap_vs_consensus_pct": _num(i.get("profit_gap_vs_consensus_pct")),
                "primary_difference_driver": primary_driver,
                "bridge_profit_method": str(b.get("profit_proxy_method", "")),
                "independent_profit_method": str(i.get("forecast_method", "")),
                "scope_note": "Juneyao consolidated group includes 9 Air; standalone 9 Air P&L remains unavailable." if company == "Juneyao Airlines" else "Spring is listed-company scope.",
                "interpretation": (
                    "The two models have similar revenue but the mechanical bridge assumes lower cost growth; reconcile CASK/non-fuel cost before using the profit gap."
                    if primary_driver == "cost_assumption_difference"
                    else "Revenue definition or RASK/yield assumptions are the larger difference; validate passenger yield and cargo/other revenue."
                ),
                "source_bridge_path": str(BRIDGE_PATH),
                "source_independent_path": str(INDEPENDENT_PATH),
                "source_quality": "derived_reconciliation_not_new_forecast",
                "retrieved_at": retrieved,
            }
        )

    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_forecast_reconciliation() -> pd.DataFrame:
    return build_airline_forecast_reconciliation()
