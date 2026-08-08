"""Pair-level P/B valuation diagnostics for the provisional airline directions."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

PB_PATH = NORMALIZED_DIR / "airline_historical_pb_valuation.csv"
TRADE_PATH = NORMALIZED_DIR / "airline_pair_trade_thesis_scenarios.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_pb_trade_diagnostic.csv"

SCENARIO_TO_COLUMN = {"bear": "pb_target_return_p25_pct", "base": "pb_target_return_median_pct", "bull": "pb_target_return_p75_pct"}


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def build_airline_pair_pb_trade_diagnostic(
    *,
    pb: pd.DataFrame | None = None,
    trade: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    pb = pb if pb is not None else pd.read_csv(PB_PATH)
    trade = trade if trade is not None else pd.read_csv(TRADE_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    base_trade = trade[trade["scenario"].eq("base")].copy()
    rows: list[dict[str, object]] = []

    for _, pair in base_trade.iterrows():
        a = pb[pb["asset"].eq(pair["asset_a"])]
        b = pb[pb["asset"].eq(pair["asset_b"])]
        if a.empty or b.empty:
            continue
        a = a.iloc[0]
        b = b.iloc[0]
        long_is_a = pair["long_asset"] == pair["asset_a"]
        beta_hedge = _num(pair.get("beta_hedge_ratio_long_to_short")) or 1.0
        drawdown = _num(pair.get("observed_hedged_spread_max_drawdown_pct"))
        for scenario, target_column in SCENARIO_TO_COLUMN.items():
            return_a = _num(a.get(target_column))
            return_b = _num(b.get(target_column))
            long_return = return_a if long_is_a else return_b
            short_return = return_b if long_is_a else return_a
            gross = long_return - short_return if long_return is not None and short_return is not None else None
            hedged = long_return - beta_hedge * short_return if long_return is not None and short_return is not None else None
            rows.append(
                {
                    "dataset_id": "airline_pair_pb_trade_diagnostic",
                    "pair_id": pair["pair_id"],
                    "selection_bucket": pair["selection_bucket"],
                    "scenario": scenario,
                    "company_a": pair["company_a"],
                    "asset_a": pair["asset_a"],
                    "company_b": pair["company_b"],
                    "asset_b": pair["asset_b"],
                    "direction_status": "provisional_mechanical_direction_requires_review",
                    "long_leg": pair["long_leg"],
                    "short_leg": pair["short_leg"],
                    "pb_target_return_a_pct": return_a,
                    "pb_target_return_b_pct": return_b,
                    "equal_notional_gross_pair_payoff_pct": gross,
                    "beta_hedge_ratio_long_to_short": beta_hedge,
                    "beta_hedged_pair_payoff_pct": hedged,
                    "observed_hedged_spread_max_drawdown_pct": drawdown,
                    "payoff_to_observed_max_drawdown": hedged / abs(drawdown) if hedged is not None and drawdown not in (None, 0) else None,
                    "valuation_method": "one_year_historical_pb_percentile_applied_to_latest_primary_equity_diagnostic",
                    "valuation_scope_status": "latest_equity_is_not_1H2026_and_business_model_scope_requires_review",
                    "valuation_conflict_flag": "pb_cross_check_disagrees_with_or_is_weaker_than_constant_ps_direction" if gross is not None and gross < 0 else "pb_cross_check_not_negative_on_equal_notional_basis",
                    "catalyst": f"{pair.get('catalyst_a')}; {pair.get('catalyst_b')}",
                    "risk_rule": "Do not approve from P/B alone; refresh equity after 1H2026, reconcile fleet/lease asset quality, and reduce or exit if the operating KPI advantage reverses or spread drawdown breaches the risk budget.",
                    "source_quality": "derived_pb_pair_trade_diagnostic",
                    "source_paths": f"{PB_PATH};{TRADE_PATH}",
                    "retrieved_at": retrieved,
                }
            )
    result = pd.DataFrame(rows)
    return result


def fetch_airline_pair_pb_trade_diagnostic() -> pd.DataFrame:
    result = build_airline_pair_pb_trade_diagnostic()
    result.to_csv(OUTPUT_PATH, index=False)
    return result
