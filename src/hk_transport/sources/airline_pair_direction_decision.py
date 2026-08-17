"""Evidence-concordance direction gate for the provisional airline pairs."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

WORKING_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"
TRADE_PATH = NORMALIZED_DIR / "airline_pair_trade_thesis_scenarios.csv"
PB_TRADE_PATH = NORMALIZED_DIR / "airline_pair_pb_trade_diagnostic.csv"
FACTOR_PATH = NORMALIZED_DIR / "airline_pair_valuation_factor_review.csv"
RISK_BUDGET_PATH = NORMALIZED_DIR / "airline_pair_risk_budget_sizing.csv"
REVISION_PATH = NORMALIZED_DIR / "airline_pair_revision_confirmation.csv"
INDEPENDENT_FORECAST_PATH = NORMALIZED_DIR / "airline_independent_forecast_view.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_direction_decision.csv"


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


def build_airline_pair_direction_decision(
    *,
    working: pd.DataFrame | None = None,
    trade: pd.DataFrame | None = None,
    pb_trade: pd.DataFrame | None = None,
    factor_review: pd.DataFrame | None = None,
    risk_budget: pd.DataFrame | None = None,
    revision_confirmation: pd.DataFrame | None = None,
    independent_forecast: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    working = working if working is not None else pd.read_csv(WORKING_PATH)
    trade = trade if trade is not None else pd.read_csv(TRADE_PATH)
    pb_trade = pb_trade if pb_trade is not None else pd.read_csv(PB_TRADE_PATH)
    factor_review = factor_review if factor_review is not None else pd.read_csv(FACTOR_PATH)
    risk_budget = risk_budget if risk_budget is not None else pd.read_csv(RISK_BUDGET_PATH)
    independent_forecast = independent_forecast if independent_forecast is not None else (
        pd.read_csv(INDEPENDENT_FORECAST_PATH) if INDEPENDENT_FORECAST_PATH.exists() else pd.DataFrame()
    )
    if revision_confirmation is None:
        if REVISION_PATH.exists():
            revision_confirmation = pd.read_csv(REVISION_PATH)
        else:
            from .airline_pair_revision_confirmation import build_airline_pair_revision_confirmation

            revision_confirmation = build_airline_pair_revision_confirmation()
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []

    for _, pair in working.iterrows():
        pair_id = str(pair["pair_id"])
        base_trade = _row(trade, pair_id=pair_id, scenario="base")
        base_pb = _row(pb_trade, pair_id=pair_id, scenario="base")
        review = _row(factor_review, pair_id=pair_id)
        budget = _row(risk_budget, pair_id=pair_id, portfolio_loss_budget_pct=0.5)
        revision = _row(revision_confirmation, pair_id=pair_id)
        if not independent_forecast.empty and {"pair_id", "scenario"}.issubset(independent_forecast.columns):
            independent_base = independent_forecast.loc[
                independent_forecast.pair_id.eq(pair_id) & independent_forecast.scenario.eq("base")
            ]
        else:
            independent_base = pd.DataFrame()
        independent_long = (
            independent_base.loc[independent_base.view_direction.eq("long_candidate")].iloc[0]
            if not independent_base.empty and "view_direction" in independent_base.columns and independent_base.view_direction.eq("long_candidate").any()
            else pd.Series(dtype=object)
        )
        independent_short = (
            independent_base.loc[independent_base.view_direction.eq("short_candidate")].iloc[0]
            if not independent_base.empty and "view_direction" in independent_base.columns and independent_base.view_direction.eq("short_candidate").any()
            else pd.Series(dtype=object)
        )
        if not independent_long.empty and not independent_short.empty:
            independent_view_status = "pre_event_view_defined"
            independent_direction = f"long {independent_long.get('company')} / short {independent_short.get('company')}"
            independent_long_gap = _num(independent_long.get("profit_gap_vs_consensus_pct"))
            independent_short_gap = _num(independent_short.get("profit_gap_vs_consensus_pct"))
            independent_gap_spread = (
                independent_long_gap - independent_short_gap
                if independent_long_gap is not None and independent_short_gap is not None
                else None
            )
            independent_note = "Independent base view is defined before 1H2026 actuals; results validate or falsify it."
        else:
            independent_view_status = "not_available_for_pair"
            independent_direction = "no_pre_event_independent_view"
            independent_long_gap = independent_short_gap = independent_gap_spread = None
            independent_note = "No independent company-level pre-event view is currently mapped to this pair."
        if base_trade.empty or base_pb.empty:
            continue
        model_long = str(base_trade.get("long_asset"))
        model_short = str(base_trade.get("short_asset"))
        pb_a = _num(base_pb.get("pb_target_return_a_pct"))
        pb_b = _num(base_pb.get("pb_target_return_b_pct"))
        if pb_a is None or pb_b is None or pb_a == pb_b:
            pb_long, pb_short, pb_direction = None, None, "pb_direction_indeterminate"
        elif pb_a > pb_b:
            pb_long, pb_short, pb_direction = str(pair["asset_a"]), str(pair["asset_b"]), "long_a_short_b"
        else:
            pb_long, pb_short, pb_direction = str(pair["asset_b"]), str(pair["asset_a"]), "long_b_short_a"
        if pb_long is None:
            concordance = "indeterminate"
        elif pb_long == model_long and pb_short == model_short:
            concordance = "earnings_and_pb_direction_aligned"
        else:
            concordance = "earnings_and_pb_direction_conflict"
        revision_status = revision.get("revision_confirmation_status", "missing") if not revision.empty else "missing"
        ps_reversion_a = _num(base_trade.get("valuation_reversion_return_a_pct"))
        ps_reversion_b = _num(base_trade.get("valuation_reversion_return_b_pct"))
        if ps_reversion_a is None or ps_reversion_b is None or ps_reversion_a == ps_reversion_b:
            ps_reversion_direction = "historical_ps_reversion_indeterminate"
        elif ps_reversion_a > ps_reversion_b:
            ps_reversion_direction = "long_a_short_b"
        else:
            ps_reversion_direction = "long_b_short_a"
        if concordance == "earnings_and_pb_direction_aligned" and revision_status == "supports_model_direction":
            decision_status = "provisional_candidate_not_trade_ready"
            next_bucket = "promote_to_1H2026_and_factor_validation"
            selected_direction = f"long {base_trade.get('long_leg')} / short {base_trade.get('short_leg')}"
        elif concordance == "earnings_and_pb_direction_aligned":
            decision_status = "no_direction_due_revision_unconfirmed"
            next_bucket = "retain_monitor_until_revision_confirmation"
            selected_direction = "no_approved_direction"
        elif concordance == "earnings_and_pb_direction_conflict":
            decision_status = "no_direction_due_valuation_conflict"
            next_bucket = "retain_monitor_until_valuation_reconciled"
            selected_direction = "no_approved_direction"
        else:
            decision_status = "no_direction_due_indeterminate_evidence"
            next_bucket = "retain_monitor_until_evidence_improves"
            selected_direction = "no_approved_direction"
        rows.append(
            {
                "dataset_id": "airline_pair_direction_decision",
                "pair_id": pair_id,
                "selection_bucket": pair["selection_bucket"],
                "earnings_model_direction": f"long {base_trade.get('long_leg')} / short {base_trade.get('short_leg')}",
                "earnings_model_long_asset": model_long,
                "earnings_model_short_asset": model_short,
                "pb_median_direction": pb_direction,
                "pb_median_long_asset": pb_long,
                "pb_median_short_asset": pb_short,
                "direction_concordance": concordance,
                "revision_confirmation_status": revision_status,
                "revision_long_signal_direction": revision.get("long_latest_signal_direction", "missing") if not revision.empty else "missing",
                "revision_short_signal_direction": revision.get("short_latest_signal_direction", "missing") if not revision.empty else "missing",
                "revision_long_signal_date": revision.get("long_latest_signal_date", "") if not revision.empty else "",
                "revision_short_signal_date": revision.get("short_latest_signal_date", "") if not revision.empty else "",
                "selected_direction_status": decision_status,
                "selected_direction": selected_direction,
                "model_variant_perception": pair.get("variant_perception_gap_difference_pct"),
                "model_base_beta_hedged_payoff_pct": _num(base_trade.get("beta_hedged_pair_payoff_pct")),
                "historical_ps_reversion_a_pct": ps_reversion_a,
                "historical_ps_reversion_b_pct": ps_reversion_b,
                "historical_ps_reversion_direction": ps_reversion_direction,
                "pb_median_equal_notional_payoff_pct": _num(base_pb.get("equal_notional_gross_pair_payoff_pct")),
                "pb_median_beta_hedged_payoff_pct": _num(base_pb.get("beta_hedged_pair_payoff_pct")),
                "direction_aware_drawdown_pct": _num(budget.get("direction_aware_hedged_spread_max_drawdown_pct")),
                "diagnostic_gross_notional_at_0_5pct_loss_budget_pct_nav": _num(budget.get("diagnostic_gross_notional_pct_nav")),
                "factor_review_status": review.get("trade_readiness_status", "missing") if not review.empty else "missing",
                "factor_risk_status": review.get("factor_risk_status", "missing") if not review.empty else "missing",
                "residual_test_status": review.get("residual_test_status", "missing") if not review.empty else "missing",
                "residual_alpha_annualized_pct": _num(review.get("residual_alpha_annualized_pct")) if not review.empty else None,
                "pre_event_independent_view_status": independent_view_status,
                "pre_event_independent_direction": independent_direction,
                "pre_event_independent_long_company": independent_long.get("company", "") if not independent_long.empty else "",
                "pre_event_independent_short_company": independent_short.get("company", "") if not independent_short.empty else "",
                "pre_event_independent_long_profit_gap_vs_consensus_pct": independent_long_gap,
                "pre_event_independent_short_profit_gap_vs_consensus_pct": independent_short_gap,
                "pre_event_independent_profit_gap_spread_pct": independent_gap_spread,
                "pre_event_independent_view_note": independent_note,
                "risk_status_at_0_5pct_budget": budget.get("risk_status", "missing") if not budget.empty else "missing",
                "catalyst": f"{base_trade.get('catalyst_a')}; {base_trade.get('catalyst_b')}",
                "invalidation_rule": "Invalidate if the long leg loses its route-level demand/yield advantage, the first post-result consensus revision confirms the opposite direction, or the direction-aware spread breaches the approved risk budget.",
                "next_decision_bucket": next_bucket,
                "required_next_evidence": "Form and document the independent pre-event view now; use 1H2026 actuals as the defined validation catalyst, then compare surprise versus forecast and consensus revisions. Reconcile historical P/S/P/E/P/B, residual factor alpha across windows, business scope and borrow/recall before trade approval.",
                "source_quality": "derived_direction_concordance_gate",
                "source_paths": f"{WORKING_PATH};{TRADE_PATH};{PB_TRADE_PATH};{FACTOR_PATH};{RISK_BUDGET_PATH};{REVISION_PATH};{INDEPENDENT_FORECAST_PATH}",
                "retrieved_at": retrieved,
            }
        )
    return pd.DataFrame(rows)


def fetch_airline_pair_direction_decision() -> pd.DataFrame:
    result = build_airline_pair_direction_decision()
    result.to_csv(OUTPUT_PATH, index=False)
    return result
