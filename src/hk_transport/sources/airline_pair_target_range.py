"""Transparent target/payoff ranges combining earnings and P/B diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

TRADE_PATH = NORMALIZED_DIR / "airline_pair_trade_thesis_scenarios.csv"
PB_PATH = NORMALIZED_DIR / "airline_pair_pb_trade_diagnostic.csv"
BANDS_PATH = NORMALIZED_DIR / "airline_historical_valuation_bands.csv"
DIRECTION_PATH = NORMALIZED_DIR / "airline_pair_direction_decision.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_target_range.csv"

SCENARIOS = ("bear", "base", "bull")


def _num(value: object) -> float | None:
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


def _range_payoff(
    *,
    return_a_model: float | None,
    return_b_model: float | None,
    return_a_pb: float | None,
    return_b_pb: float | None,
    long_is_a: bool,
    beta: float,
) -> tuple[float | None, float | None, float | None, float | None, float | None, float | None]:
    values = (return_a_model, return_b_model, return_a_pb, return_b_pb)
    if any(value is None for value in values):
        return None, None, None, None, None, None
    a_low, a_high = min(return_a_model, return_a_pb), max(return_a_model, return_a_pb)
    b_low, b_high = min(return_b_model, return_b_pb), max(return_b_model, return_b_pb)
    long_low, long_high = (a_low, a_high) if long_is_a else (b_low, b_high)
    short_low, short_high = (b_low, b_high) if long_is_a else (a_low, a_high)
    equal_low = long_low - short_high
    equal_high = long_high - short_low
    beta_low = long_low - beta * short_high
    beta_high = long_high - beta * short_low
    return long_low, long_high, equal_low, equal_high, beta_low, beta_high


def build_airline_pair_target_range(
    *,
    trade: pd.DataFrame | None = None,
    pb_trade: pd.DataFrame | None = None,
    direction: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    trade = trade if trade is not None else pd.read_csv(TRADE_PATH)
    pb_trade = pb_trade if pb_trade is not None else pd.read_csv(PB_PATH)
    direction = direction if direction is not None else pd.read_csv(DIRECTION_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []

    for _, t in trade.iterrows():
        pair_id = str(t["pair_id"])
        scenario = str(t["scenario"])
        pb_scenario = _row(pb_trade, pair_id=pair_id, scenario=scenario)
        decision = _row(direction, pair_id=pair_id)
        if pb_scenario.empty or decision.empty:
            continue
        long_is_a = str(t["long_asset"]) == str(t["asset_a"])
        beta = _num(t.get("beta_hedge_ratio_long_to_short")) or 1.0
        model_a = _num(t.get("model_revenue_gap_a_pct"))
        model_b = _num(t.get("model_revenue_gap_b_pct"))
        pb_a = _num(pb_scenario.get("pb_target_return_a_pct"))
        pb_b = _num(pb_scenario.get("pb_target_return_b_pct"))
        long_low, long_high, pair_low, pair_high, beta_pair_low, beta_pair_high = _range_payoff(
            return_a_model=model_a,
            return_b_model=model_b,
            return_a_pb=pb_a,
            return_b_pb=pb_b,
            long_is_a=long_is_a,
            beta=beta,
        )
        short_asset = str(t["short_asset"])
        long_asset = str(t["long_asset"])
        if model_a is not None and model_b is not None:
            model_pair = _num(t.get("beta_hedged_pair_payoff_pct"))
        else:
            model_pair = None
        rows.append(
            {
                "dataset_id": "airline_pair_target_range",
                "pair_id": pair_id,
                "selection_bucket": t["selection_bucket"],
                "scenario": scenario,
                "earnings_model_direction": decision["earnings_model_direction"],
                "selected_direction_status": decision["selected_direction_status"],
                "selected_direction": decision["selected_direction"],
                "long_leg": t["long_leg"],
                "long_asset": long_asset,
                "short_leg": t["short_leg"],
                "short_asset": short_asset,
                "model_return_a_pct": model_a,
                "model_return_b_pct": model_b,
                "pb_return_a_pct": pb_a,
                "pb_return_b_pct": pb_b,
                "long_leg_return_low_pct": long_low,
                "long_leg_return_high_pct": long_high,
                "equal_notional_pair_payoff_low_pct": pair_low,
                "equal_notional_pair_payoff_high_pct": pair_high,
                "beta_hedged_pair_payoff_low_pct": beta_pair_low,
                "beta_hedged_pair_payoff_high_pct": beta_pair_high,
                "model_beta_hedged_pair_payoff_pct": model_pair,
                "pb_beta_hedged_pair_payoff_pct": _num(pb_scenario.get("beta_hedged_pair_payoff_pct")),
                "beta_hedge_ratio_long_to_short": beta,
                "target_range_method": "min_max_of_model_plus_historical_annual_ps_and_historical_pb_diagnostics_not_confidence_interval",
                "valuation_conflict_flag": decision["direction_concordance"],
                "catalyst": t.get("catalyst_a", "") + "; " + t.get("catalyst_b", ""),
                "invalidation_rule": "Invalidate if route-level demand/yield advantage reverses, post-result consensus revision confirms the opposite, or direction-aware spread breaches the risk budget.",
                "risk_status": decision["risk_status_at_0_5pct_budget"],
                "source_quality": "derived_earnings_pb_target_range_diagnostic",
                "source_paths": f"{TRADE_PATH};{PB_PATH};{BANDS_PATH};{DIRECTION_PATH}",
                "retrieved_at": retrieved,
            }
        )
    result = pd.DataFrame(rows)
    return result


def fetch_airline_pair_target_range() -> pd.DataFrame:
    result = build_airline_pair_target_range()
    result.to_csv(OUTPUT_PATH, index=False)
    return result
