"""Provisional long/short trade-thesis scenarios for priority airline pairs.

The target-price bridge holds each leg's current consensus-revenue multiple
constant and applies the independent company forecast gap to revenue.  This is
an intentionally simple payoff diagnostic, not a valuation recommendation.
The output keeps valuation premium, beta hedge, drawdown, catalyst and
invalidation gates visible so the main analyst can approve or reject a trade.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

WORKING_SET_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"
BRIDGE_PATH = NORMALIZED_DIR / "airline_forward_earnings_bridge.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_trade_thesis_scenarios.csv"

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


def build_airline_pair_trade_thesis_scenarios(
    *,
    working_set: pd.DataFrame | None = None,
    bridge: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    working_set = working_set if working_set is not None else pd.read_csv(WORKING_SET_PATH)
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []

    for _, pair in working_set.iterrows():
        company_a, company_b = str(pair["company_a"]), str(pair["company_b"])
        asset_a, asset_b = str(pair["asset_a"]), str(pair["asset_b"])
        base_a = _row(bridge, company=company_a, scenario="base")
        base_b = _row(bridge, company=company_b, scenario="base")
        a_base_gap = _num(base_a.get("revenue_gap_to_consensus_pct"))
        b_base_gap = _num(base_b.get("revenue_gap_to_consensus_pct"))
        long_leg = "a" if a_base_gap is not None and b_base_gap is not None and a_base_gap > b_base_gap else "b"
        short_leg = "b" if long_leg == "a" else "a"
        price_a = _num(pair.get("current_price_a_native"))
        price_b = _num(pair.get("current_price_b_native"))
        ps_a = _num(pair.get("ps_consensus_revenue_a"))
        ps_b = _num(pair.get("ps_consensus_revenue_b"))
        valuation_flag = (
            "long_leg_trades_at_higher_P/S_execution_must_beat_valuation"
            if (long_leg == "a" and ps_a is not None and ps_b is not None and ps_a > ps_b)
            or (long_leg == "b" and ps_a is not None and ps_b is not None and ps_b > ps_a)
            else "relative_P/S_does_not_penalize_long_leg"
        )
        beta = _num(pair.get("beta_a_to_b")) if long_leg == "a" else _num(pair.get("beta_b_to_a"))
        # Directional beta is selected according to the proposed long leg;
        # reciprocal hedge ratios are not interchangeable.
        beta_hedge = beta if beta is not None else 1.0
        for scenario in SCENARIOS:
            a = _row(bridge, company=company_a, scenario=scenario)
            b = _row(bridge, company=company_b, scenario=scenario)
            gap_a = _num(a.get("revenue_gap_to_consensus_pct"))
            gap_b = _num(b.get("revenue_gap_to_consensus_pct"))
            target_a = price_a * (1.0 + gap_a / 100.0) if price_a is not None and gap_a is not None else None
            target_b = price_b * (1.0 + gap_b / 100.0) if price_b is not None and gap_b is not None else None
            return_a, return_b = gap_a, gap_b
            long_return = return_a if long_leg == "a" else return_b
            short_return = return_b if short_leg == "b" else return_a
            gross_payoff = long_return - short_return if long_return is not None and short_return is not None else None
            beta_payoff = long_return - beta_hedge * short_return if long_return is not None and short_return is not None else None
            max_drawdown = _num(pair.get("hedged_spread_max_drawdown_pct"))
            payoff_to_drawdown = beta_payoff / abs(max_drawdown) if beta_payoff is not None and max_drawdown not in (None, 0) else None
            rows.append({
                "dataset_id": "airline_pair_trade_thesis_scenarios",
                "pair_id": pair["pair_id"], "selection_bucket": pair["selection_bucket"],
                "scenario": scenario, "company_a": company_a, "asset_a": asset_a,
                "company_b": company_b, "asset_b": asset_b,
                "direction_status": "provisional_mechanical_direction_requires_review",
                "long_leg": company_a if long_leg == "a" else company_b,
                "long_asset": asset_a if long_leg == "a" else asset_b,
                "short_leg": company_b if short_leg == "b" else company_a,
                "short_asset": asset_b if short_leg == "b" else asset_a,
                "variant_perception": f"The model gives {company_a} revenue gap {gap_a:.2f}% versus {company_b} {gap_b:.2f}%; the less-negative/better leg is mechanically long.",
                "current_price_a_native": price_a, "current_price_b_native": price_b,
                "current_ps_a": ps_a, "current_ps_b": ps_b,
                "target_price_a_native": target_a, "target_price_b_native": target_b,
                "target_price_method": "constant_current_leg_P/S_applied_to_model_revenue_gap",
                "model_revenue_gap_a_pct": gap_a, "model_revenue_gap_b_pct": gap_b,
                "equal_notional_gross_pair_payoff_pct": gross_payoff,
                "beta_hedge_ratio_long_to_short": beta_hedge,
                "beta_hedged_pair_payoff_pct": beta_payoff,
                "payoff_to_observed_max_drawdown": payoff_to_drawdown,
                "observed_hedged_spread_max_drawdown_pct": max_drawdown,
                "valuation_flag": valuation_flag,
                "catalyst_a": f"report={pair.get('report_date_a')}; warning={pair.get('warning_date_a')}",
                "catalyst_b": f"report={pair.get('report_date_b')}; warning={pair.get('warning_date_b')}",
                "invalidation_rule_count_a": pair.get("invalidation_rule_count_a"),
                "invalidation_rule_count_b": pair.get("invalidation_rule_count_b"),
                "risk_rule": "Reduce/exit if the long leg's RPK−ASK/yield advantage reverses, consensus revisions confirm the opposite direction, or spread drawdown breaches the portfolio risk budget.",
                "trade_construction_rule": "Use the mechanical beta hedge as a starting diagnostic only; set notional from approved spread-risk budget after factor and borrow review.",
                "source_quality": "derived_provisional_trade_thesis",
                "source_paths": f"{WORKING_SET_PATH};{BRIDGE_PATH}",
                "retrieved_at": retrieved,
            })
    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_pair_trade_thesis_scenarios() -> pd.DataFrame:
    return build_airline_pair_trade_thesis_scenarios()
