"""Two-branch conditional thesis matrix for each priority airline pair."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

WORKING_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"
TRADE_PATH = NORMALIZED_DIR / "airline_pair_trade_thesis_scenarios.csv"
PB_TRADE_PATH = NORMALIZED_DIR / "airline_pair_pb_trade_diagnostic.csv"
RISK_PATH = NORMALIZED_DIR / "airline_pair_risk_metrics.csv"
TRIGGER_PATH = NORMALIZED_DIR / "airline_pair_event_trade_triggers.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_branch_thesis.csv"


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


def _branch_payoff(
    *,
    return_a: float | None,
    return_b: float | None,
    long_is_a: bool,
    beta: float,
) -> float | None:
    if return_a is None or return_b is None:
        return None
    long_return, short_return = (return_a, return_b) if long_is_a else (return_b, return_a)
    return long_return - beta * short_return


def build_airline_pair_branch_thesis(
    *,
    working: pd.DataFrame | None = None,
    trade: pd.DataFrame | None = None,
    pb_trade: pd.DataFrame | None = None,
    risk: pd.DataFrame | None = None,
    triggers: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    working = working if working is not None else pd.read_csv(WORKING_PATH)
    trade = trade if trade is not None else pd.read_csv(TRADE_PATH)
    pb_trade = pb_trade if pb_trade is not None else pd.read_csv(PB_TRADE_PATH)
    risk = risk if risk is not None else pd.read_csv(RISK_PATH)
    triggers = triggers if triggers is not None else pd.read_csv(TRIGGER_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []

    for _, pair in working.iterrows():
        pair_id = str(pair["pair_id"])
        t = _row(trade, pair_id=pair_id, scenario="base")
        pb = _row(pb_trade, pair_id=pair_id, scenario="base")
        risk_row = _row(risk, asset_a=pair["asset_a"], asset_b=pair["asset_b"])
        trigger = _row(triggers, pair_id=pair_id)
        if t.empty or pb.empty or risk_row.empty:
            continue
        model_a, model_b = _num(t.get("model_revenue_gap_a_pct")), _num(t.get("model_revenue_gap_b_pct"))
        pb_a, pb_b = _num(pb.get("pb_target_return_a_pct")), _num(pb.get("pb_target_return_b_pct"))
        model_long_asset, model_short_asset = str(t["long_asset"]), str(t["short_asset"])
        pb_long_asset = str(pair["asset_a"]) if pb_a is not None and pb_b is not None and pb_a > pb_b else str(pair["asset_b"])
        pb_short_asset = str(pair["asset_b"]) if pb_long_asset == str(pair["asset_a"]) else str(pair["asset_a"])
        branches = [
            {
                "branch": "fundamental_resilience",
                "long_asset": model_long_asset,
                "short_asset": model_short_asset,
                "long_leg": t["long_leg"],
                "short_leg": t["short_leg"],
                "variant_perception": "The long leg's independent H1-driven earnings gap is better than the short leg's gap; trade only if the interim surprise and revisions confirm the operating advantage.",
                "entry_rule": trigger.get("entry_trigger", "pending") if not trigger.empty else "pending",
                "invalidation_rule": trigger.get("invalidation_rule", "pending") if not trigger.empty else "pending",
            },
            {
                "branch": "valuation_mean_reversion",
                "long_asset": pb_long_asset,
                "short_asset": pb_short_asset,
                "long_leg": pair["company_a"] if pb_long_asset == str(pair["asset_a"]) else pair["company_b"],
                "short_leg": pair["company_b"] if pb_short_asset == str(pair["asset_b"]) else pair["company_a"],
                "variant_perception": "The one-year P/B median and current P/S premium imply that valuation compression or asset-value mean reversion can dominate the earnings-resilience narrative.",
                "entry_rule": "Enter only if post-result P/B/P/S direction remains in favour of the valuation leg, the valuation leg does not miss profit/revenue versus the other leg by more than half the model gap, and the valuation lower-bound payoff is non-negative.",
                "invalidation_rule": "Invalidate if the earnings-resilience leg delivers the required surprise and fresh revisions, or if the valuation premium compresses without the expected relative earnings deterioration.",
            },
        ]
        for branch in branches:
            long_is_a = branch["long_asset"] == str(pair["asset_a"])
            beta = _num(risk_row.get("beta_a_to_b" if long_is_a else "beta_b_to_a")) or 1.0
            drawdown = _num(risk_row.get("hedged_spread_max_drawdown_a_minus_beta_b_pct" if long_is_a else "hedged_spread_max_drawdown_b_minus_beta_a_pct"))
            vol = _num(risk_row.get("hedged_spread_vol_a_minus_beta_b_pct" if long_is_a else "hedged_spread_vol_b_minus_beta_a_pct"))
            model_payoff = _branch_payoff(return_a=model_a, return_b=model_b, long_is_a=long_is_a, beta=beta)
            pb_payoff = _branch_payoff(return_a=pb_a, return_b=pb_b, long_is_a=long_is_a, beta=beta)
            payoff_low = min(model_payoff, pb_payoff) if model_payoff is not None and pb_payoff is not None else None
            payoff_high = max(model_payoff, pb_payoff) if model_payoff is not None and pb_payoff is not None else None
            gross_notional = 0.5 / abs(drawdown) * (1.0 + beta) * 100.0 if drawdown not in (None, 0) else None
            rows.append(
                {
                    "dataset_id": "airline_pair_branch_thesis",
                    "pair_id": pair_id,
                    "selection_bucket": pair["selection_bucket"],
                    "branch": branch["branch"],
                    "branch_status": "conditional_pre_event_no_entry",
                    "long_leg": branch["long_leg"],
                    "long_asset": branch["long_asset"],
                    "short_leg": branch["short_leg"],
                    "short_asset": branch["short_asset"],
                    "variant_perception": branch["variant_perception"],
                    "model_beta_hedged_payoff_pct": model_payoff,
                    "pb_beta_hedged_payoff_pct": pb_payoff,
                    "target_payoff_low_pct": payoff_low,
                    "target_payoff_high_pct": payoff_high,
                    "beta_hedge_ratio_long_to_short": beta,
                    "direction_aware_drawdown_pct": drawdown,
                    "direction_aware_volatility_pct": vol,
                    "diagnostic_gross_notional_at_0_5pct_loss_budget_pct_nav": gross_notional,
                    "current_gate_status": trigger.get("current_direction_status", "missing") if not trigger.empty else "missing",
                    "revision_gate_status": trigger.get("current_revision_status", "missing") if not trigger.empty else "missing",
                    "catalyst": trigger.get("event_window", "pending") if not trigger.empty else "pending",
                    "entry_rule": branch["entry_rule"],
                    "invalidation_rule": branch["invalidation_rule"],
                    "risk_rule": "Use direction-aware drawdown and mechanical beta only as diagnostics; cap loss at the approved portfolio budget and do not enter while borrow/factor/valuation gates are unresolved.",
                    "source_quality": "derived_two_branch_conditional_thesis",
                    "source_paths": f"{WORKING_PATH};{TRADE_PATH};{PB_TRADE_PATH};{RISK_PATH};{TRIGGER_PATH}",
                    "retrieved_at": retrieved,
                }
            )
    return pd.DataFrame(rows)


def fetch_airline_pair_branch_thesis() -> pd.DataFrame:
    result = build_airline_pair_branch_thesis()
    result.to_csv(OUTPUT_PATH, index=False)
    return result
