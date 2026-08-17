"""Conditional event-trade trigger matrix for the five airline pairs."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

WORKING_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"
TRADE_PATH = NORMALIZED_DIR / "airline_pair_trade_thesis_scenarios.csv"
DIRECTION_PATH = NORMALIZED_DIR / "airline_pair_direction_decision.csv"
REVISION_PATH = NORMALIZED_DIR / "airline_pair_revision_confirmation.csv"
TARGET_PATH = NORMALIZED_DIR / "airline_pair_target_range.csv"
RISK_PATH = NORMALIZED_DIR / "airline_pair_risk_budget_sizing.csv"
INDEPENDENT_FORECAST_PATH = NORMALIZED_DIR / "airline_independent_forecast_view.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_event_trade_triggers.csv"


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


def build_airline_pair_event_trade_triggers(
    *,
    working: pd.DataFrame | None = None,
    trade: pd.DataFrame | None = None,
    direction: pd.DataFrame | None = None,
    revision: pd.DataFrame | None = None,
    target_range: pd.DataFrame | None = None,
    risk: pd.DataFrame | None = None,
    independent_forecast: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    working = working if working is not None else pd.read_csv(WORKING_PATH)
    trade = trade if trade is not None else pd.read_csv(TRADE_PATH)
    direction = direction if direction is not None else pd.read_csv(DIRECTION_PATH)
    revision = revision if revision is not None else pd.read_csv(REVISION_PATH)
    target_range = target_range if target_range is not None else pd.read_csv(TARGET_PATH)
    risk = risk if risk is not None else pd.read_csv(RISK_PATH)
    independent_forecast = independent_forecast if independent_forecast is not None else (
        pd.read_csv(INDEPENDENT_FORECAST_PATH) if INDEPENDENT_FORECAST_PATH.exists() else pd.DataFrame()
    )
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []

    for _, pair in working.iterrows():
        pair_id = str(pair["pair_id"])
        t = _row(trade, pair_id=pair_id, scenario="base")
        d = _row(direction, pair_id=pair_id)
        rev = _row(revision, pair_id=pair_id)
        target = _row(target_range, pair_id=pair_id, scenario="base")
        budget = _row(risk, pair_id=pair_id, portfolio_loss_budget_pct=0.5)
        if t.empty or d.empty or target.empty or budget.empty:
            continue
        long_profit_gap = _num(pair.get("variant_perception_b_gap_pct")) if str(t.get("long_asset")) == str(pair.get("asset_b")) else _num(pair.get("variant_perception_a_gap_pct"))
        short_profit_gap = _num(pair.get("variant_perception_a_gap_pct")) if str(t.get("short_asset")) == str(pair.get("asset_a")) else _num(pair.get("variant_perception_b_gap_pct"))
        long_revenue_gap = _num(pair.get("base_revenue_gap_b_pct")) if str(t.get("long_asset")) == str(pair.get("asset_b")) else _num(pair.get("base_revenue_gap_a_pct"))
        short_revenue_gap = _num(pair.get("base_revenue_gap_a_pct")) if str(t.get("short_asset")) == str(pair.get("asset_a")) else _num(pair.get("base_revenue_gap_b_pct"))
        profit_advantage = long_profit_gap - short_profit_gap if long_profit_gap is not None and short_profit_gap is not None else None
        revenue_advantage = long_revenue_gap - short_revenue_gap if long_revenue_gap is not None and short_revenue_gap is not None else None
        independent_long = _row(
            independent_forecast,
            pair_id=pair_id,
            scenario="base",
            ticker=str(t.get("long_asset")),
        ) if not independent_forecast.empty else pd.Series(dtype=object)
        independent_short = _row(
            independent_forecast,
            pair_id=pair_id,
            scenario="base",
            ticker=str(t.get("short_asset")),
        ) if not independent_forecast.empty else pd.Series(dtype=object)
        if not independent_long.empty and not independent_short.empty:
            forecast_basis = "independent_pre_event_forecast"
            entry_profit_advantage = _num(independent_long.get("profit_gap_vs_consensus_pct"))
            short_independent_profit_gap = _num(independent_short.get("profit_gap_vs_consensus_pct"))
            entry_revenue_advantage = _num(independent_long.get("revenue_gap_vs_consensus_pct"))
            short_independent_revenue_gap = _num(independent_short.get("revenue_gap_vs_consensus_pct"))
            entry_profit_advantage = (
                entry_profit_advantage - short_independent_profit_gap
                if entry_profit_advantage is not None and short_independent_profit_gap is not None
                else None
            )
            entry_revenue_advantage = (
                entry_revenue_advantage - short_independent_revenue_gap
                if entry_revenue_advantage is not None and short_independent_revenue_gap is not None
                else None
            )
        else:
            forecast_basis = "mechanical_forward_bridge"
            entry_profit_advantage = profit_advantage
            entry_revenue_advantage = revenue_advantage
            short_independent_profit_gap = None
            short_independent_revenue_gap = None
        half_profit_advantage = abs(entry_profit_advantage) / 2.0 if entry_profit_advantage is not None else None
        half_revenue_advantage = abs(entry_revenue_advantage) / 2.0 if entry_revenue_advantage is not None else None
        report_dates = [str(value) for value in (pair.get("report_date_a"), pair.get("report_date_b")) if pd.notna(value) and str(value) not in {"", "pending"}]
        catalyst = "; ".join(sorted(set(report_dates))) if report_dates else "pending"
        revision_status = rev.get("revision_confirmation_status", "missing") if not rev.empty else "missing"
        target_low = _num(target.get("beta_hedged_pair_payoff_low_pct"))
        target_high = _num(target.get("beta_hedged_pair_payoff_high_pct"))
        risk_status = str(budget.get("risk_status", "missing"))
        rows.append(
            {
                "dataset_id": "airline_pair_event_trade_triggers",
                "pair_id": pair_id,
                "selection_bucket": pair["selection_bucket"],
                "conditional_direction": f"long {t.get('long_leg')} / short {t.get('short_leg')}",
                "current_direction_status": d.get("selected_direction_status", "missing"),
                "current_revision_status": revision_status,
                "event_window": catalyst,
                "surprise_threshold_basis": forecast_basis,
                "model_long_minus_short_profit_gap_pp": profit_advantage,
                "model_long_minus_short_revenue_gap_pp": revenue_advantage,
                "pre_event_long_profit_gap_vs_consensus_pp": _num(independent_long.get("profit_gap_vs_consensus_pct")) if not independent_long.empty else None,
                "pre_event_short_profit_gap_vs_consensus_pp": short_independent_profit_gap,
                "pre_event_profit_gap_spread_pp": entry_profit_advantage if forecast_basis == "independent_pre_event_forecast" else None,
                "pre_event_long_revenue_gap_vs_consensus_pp": _num(independent_long.get("revenue_gap_vs_consensus_pct")) if not independent_long.empty else None,
                "pre_event_short_revenue_gap_vs_consensus_pp": short_independent_revenue_gap,
                "pre_event_revenue_gap_spread_pp": entry_revenue_advantage if forecast_basis == "independent_pre_event_forecast" else None,
                "minimum_profit_surprise_gap_for_entry_pp": half_profit_advantage,
                "minimum_revenue_surprise_gap_for_entry_pp": half_revenue_advantage,
                "model_long_minus_short_gap_pp": profit_advantage,
                "minimum_surprise_gap_for_entry_pp": half_profit_advantage,
                "base_beta_hedged_payoff_low_pct": target_low,
                "base_beta_hedged_payoff_high_pct": target_high,
                "direction_aware_drawdown_pct": _num(budget.get("direction_aware_hedged_spread_max_drawdown_pct")),
                "diagnostic_gross_notional_at_0_5pct_loss_budget_pct_nav": _num(budget.get("diagnostic_gross_notional_pct_nav")),
                "entry_trigger": f"Enter only after both issuer reports: realized long-minus-short profit surprise >= {half_profit_advantage:.2f}pp and revenue surprise >= {half_revenue_advantage:.2f}pp versus the {forecast_basis} threshold; a fresh revision signal supports long-up/short-down; and the post-result valuation range has a non-negative lower bound or an explicitly reconciled scope explanation." if half_profit_advantage is not None and half_revenue_advantage is not None else "Enter only after both issuer reports provide measurable revenue and profit surprises, fresh long-up/short-down revision confirmation, and a reconciled post-result valuation range.",
                "catalyst_confirmation": "Wait for the later of the two formal interim reports and the first post-result consensus revision; scheduled date is not evidence of actual disclosure.",
                "invalidation_rule": "Do not enter, or exit, if either report misses the surprise threshold, revision remains no_signal/mixed, the P/B/P/S direction remains conflicted, or direction-aware drawdown breaches the approved loss budget.",
                "risk_status": risk_status,
                "trade_status": "wait_for_event_trigger_no_pre_event_trade",
                "source_quality": "derived_event_trade_trigger_matrix",
                "source_paths": f"{WORKING_PATH};{TRADE_PATH};{DIRECTION_PATH};{REVISION_PATH};{TARGET_PATH};{RISK_PATH};{INDEPENDENT_FORECAST_PATH}",
                "retrieved_at": retrieved,
            }
        )
    return pd.DataFrame(rows)


def fetch_airline_pair_event_trade_triggers() -> pd.DataFrame:
    result = build_airline_pair_event_trade_triggers()
    result.to_csv(OUTPUT_PATH, index=False)
    return result
