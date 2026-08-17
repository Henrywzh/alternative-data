"""Pre-event candidate card for an airline earnings bet.

This layer converts the independent Spring/Juneyao forecast into a small,
explicit research trade expression before the scheduled interim reports.  It
does not erase the P/B conflict or borrow uncertainty: those are carried as
downside and execution gates.  The candidate is a controlled-risk research
expression, not an approved live position.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR


WORKING_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"
TRADE_PATH = NORMALIZED_DIR / "airline_pair_trade_thesis_scenarios.csv"
INDEPENDENT_PATH = NORMALIZED_DIR / "airline_independent_forecast_view.csv"
FACTOR_REVIEW_PATH = NORMALIZED_DIR / "airline_pair_valuation_factor_review.csv"
PB_PATH = NORMALIZED_DIR / "airline_pair_pb_trade_diagnostic.csv"
RISK_PATH = NORMALIZED_DIR / "airline_pair_risk_budget_sizing.csv"
DIRECTION_PATH = NORMALIZED_DIR / "airline_pair_direction_decision.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pre_event_trade_candidate.csv"


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


def build_airline_pre_event_trade_candidate(
    *,
    working: pd.DataFrame | None = None,
    trade: pd.DataFrame | None = None,
    independent: pd.DataFrame | None = None,
    factor_review: pd.DataFrame | None = None,
    pb: pd.DataFrame | None = None,
    risk: pd.DataFrame | None = None,
    direction: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    working = working if working is not None else pd.read_csv(WORKING_PATH)
    trade = trade if trade is not None else pd.read_csv(TRADE_PATH)
    independent = independent if independent is not None else pd.read_csv(INDEPENDENT_PATH)
    factor_review = factor_review if factor_review is not None else pd.read_csv(FACTOR_REVIEW_PATH)
    pb = pb if pb is not None else pd.read_csv(PB_PATH)
    risk = risk if risk is not None else pd.read_csv(RISK_PATH)
    direction = direction if direction is not None else pd.read_csv(DIRECTION_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []

    for _, pair in working.iterrows():
        pair_id = str(pair["pair_id"])
        trade_row = _row(trade, pair_id=pair_id, scenario="base")
        factor_row = _row(factor_review, pair_id=pair_id)
        direction_row = _row(direction, pair_id=pair_id)
        pb_row = _row(pb, pair_id=pair_id, scenario="base")
        risk_row = _row(risk, pair_id=pair_id, portfolio_loss_budget_pct=0.25)
        independent_rows = independent[
            independent.get("pair_id", pd.Series(dtype=object)).eq(pair_id)
            & independent.get("scenario", pd.Series(dtype=object)).eq("base")
        ] if not independent.empty else pd.DataFrame()
        independent_long = (
            independent_rows.loc[independent_rows.view_direction.eq("long_candidate")].iloc[0]
            if not independent_rows.empty and "view_direction" in independent_rows.columns and independent_rows.view_direction.eq("long_candidate").any()
            else pd.Series(dtype=object)
        )
        independent_short = (
            independent_rows.loc[independent_rows.view_direction.eq("short_candidate")].iloc[0]
            if not independent_rows.empty and "view_direction" in independent_rows.columns and independent_rows.view_direction.eq("short_candidate").any()
            else pd.Series(dtype=object)
        )
        view_defined = not independent_long.empty and not independent_short.empty
        independent_payoff = _num(factor_row.get("pre_event_independent_beta_hedged_pair_payoff_pct")) if not factor_row.empty else None
        pb_payoff = _num(pb_row.get("beta_hedged_pair_payoff_pct")) if not pb_row.empty else None
        pb_equal_payoff = _num(pb_row.get("equal_notional_gross_pair_payoff_pct")) if not pb_row.empty else None
        payoff_candidates = [value for value in (independent_payoff, pb_payoff, pb_equal_payoff) if value is not None]
        valuation_low = min(payoff_candidates) if payoff_candidates else None
        valuation_high = max(payoff_candidates) if payoff_candidates else None
        residual_status = str(factor_row.get("residual_test_status", "missing")) if not factor_row.empty else "missing"
        risk_status = str(risk_row.get("risk_status", "missing")) if not risk_row.empty else "missing"
        independent_view_status = str(factor_row.get("pre_event_independent_view_status", "missing")) if not factor_row.empty else "missing"
        valuation_conflict = (
            (pb_equal_payoff is not None and pb_equal_payoff < 0)
            or str(direction_row.get("direction_concordance", "")).endswith("conflict")
        )
        candidate = view_defined and independent_view_status == "pre_event_view_defined" and independent_payoff is not None and independent_payoff > 0 and residual_status == "estimated" and not risk_row.empty
        if candidate and valuation_conflict:
            candidate_status = "conditional_pre_event_candidate_with_valuation_conflict"
        elif candidate:
            candidate_status = "conditional_pre_event_candidate"
        elif not view_defined:
            candidate_status = "not_available_no_mapped_independent_view"
        else:
            candidate_status = "not_candidate_missing_factor_or_risk_evidence"
        report_dates = sorted({
            str(value) for value in (pair.get("report_date_a"), pair.get("report_date_b"))
            if pd.notna(value) and str(value) not in {"", "pending", "nan"}
        })
        event_window = "; ".join(report_dates) if report_dates else "pending"
        long_company = str(trade_row.get("long_leg", independent_long.get("company", ""))) if not trade_row.empty else str(independent_long.get("company", ""))
        short_company = str(trade_row.get("short_leg", independent_short.get("company", ""))) if not trade_row.empty else str(independent_short.get("company", ""))
        direction_text = f"long {long_company} / short {short_company}" if long_company and short_company else "no_pre_event_direction"
        long_asset = str(trade_row.get("long_asset", "")) if not trade_row.empty else str(independent_long.get("ticker", ""))
        short_asset = str(trade_row.get("short_asset", "")) if not trade_row.empty else str(independent_short.get("ticker", ""))
        asset_a = str(pair.get("asset_a", ""))
        long_price = _num(trade_row.get("current_price_a_native" if long_asset == asset_a else "current_price_b_native")) if not trade_row.empty else None
        short_price = _num(trade_row.get("current_price_b_native" if long_asset == asset_a else "current_price_a_native")) if not trade_row.empty else None
        long_ps = _num(trade_row.get("current_ps_a" if long_asset == asset_a else "current_ps_b")) if not trade_row.empty else None
        short_ps = _num(trade_row.get("current_ps_b" if long_asset == asset_a else "current_ps_a")) if not trade_row.empty else None
        long_target = _num(factor_row.get("pre_event_independent_target_long_native")) if not factor_row.empty else None
        short_target = _num(factor_row.get("pre_event_independent_target_short_native")) if not factor_row.empty else None
        variant = str(independent_long.get("variant_perception", "")) if not independent_long.empty else ""
        invalidation = (
            "Reduce/exit if Spring RPK-minus-ASK is <=0 for the validation window, yield/RASK and margin fall below the base case, "
            "Juneyao margin recovers toward consensus, fuel/FX shock is not passed through as assumed, or the direction-aware spread breaches the 0.25% NAV loss budget."
        )
        entry_rule = (
            f"Research entry may be taken before the later report in {event_window} only while the independent view remains valid; "
            "use the 0.25% NAV loss-budget diagnostic, do not size from the illustrative target alone, and re-underwrite after each report."
        )
        rows.append(
            {
                "dataset_id": "airline_pre_event_trade_candidate",
                "as_of_date": str(independent_long.get("as_of_date", retrieved[:10])) if not independent_long.empty else retrieved[:10],
                "pair_id": pair_id,
                "selection_bucket": pair.get("selection_bucket", ""),
                "candidate_status": candidate_status,
                "direction": direction_text,
                "long_asset": long_asset,
                "short_asset": short_asset,
                "current_price_long_native": long_price,
                "current_price_short_native": short_price,
                "current_ps_long": long_ps,
                "current_ps_short": short_ps,
                "independent_view_status": independent_view_status,
                "independent_profit_gap_long_vs_consensus_pct": _num(independent_long.get("profit_gap_vs_consensus_pct")) if not independent_long.empty else None,
                "independent_profit_gap_short_vs_consensus_pct": _num(independent_short.get("profit_gap_vs_consensus_pct")) if not independent_short.empty else None,
                "independent_profit_gap_spread_pct": (
                    _num(independent_long.get("profit_gap_vs_consensus_pct")) - _num(independent_short.get("profit_gap_vs_consensus_pct"))
                    if not independent_long.empty and not independent_short.empty
                    else None
                ),
                "independent_target_long_native": long_target,
                "independent_target_short_native": short_target,
                "independent_target_long_return_pct": (100.0 * long_target / long_price - 100.0) if long_target is not None and long_price else None,
                "independent_target_short_return_pct": (100.0 * short_target / short_price - 100.0) if short_target is not None and short_price else None,
                "independent_beta_hedged_payoff_pct": independent_payoff,
                "pb_beta_hedged_payoff_pct": pb_payoff,
                "pb_equal_notional_payoff_pct": pb_equal_payoff,
                "valuation_payoff_low_pct": valuation_low,
                "valuation_payoff_high_pct": valuation_high,
                "valuation_conflict_status": "pb_cross_check_negative" if valuation_conflict else "pb_cross_check_not_negative",
                "residual_alpha_annualized_pct": _num(factor_row.get("residual_alpha_annualized_pct")) if not factor_row.empty else None,
                "residual_r_squared": _num(factor_row.get("residual_r_squared")) if not factor_row.empty else None,
                "residual_max_drawdown_pct": _num(factor_row.get("residual_max_drawdown_pct")) if not factor_row.empty else None,
                "factor_test_status": residual_status,
                "portfolio_loss_budget_pct": _num(risk_row.get("portfolio_loss_budget_pct")) if not risk_row.empty else None,
                "diagnostic_gross_notional_pct_nav": _num(risk_row.get("diagnostic_gross_notional_pct_nav")) if not risk_row.empty else None,
                "direction_aware_drawdown_pct": _num(risk_row.get("direction_aware_hedged_spread_max_drawdown_pct")) if not risk_row.empty else None,
                "risk_status": risk_status,
                "event_window": event_window,
                "revision_confirmation_status": direction_row.get("revision_confirmation_status", "missing") if not direction_row.empty else "missing",
                "variant_perception": variant,
                "catalyst": f"Reports scheduled for {event_window}; first post-result consensus revision is the second catalyst.",
                "entry_rule": entry_rule,
                "invalidation_rule": invalidation,
                "execution_caveat": "Borrow/recall and live liquidity are not verified in the free research layer; this is a conditional research expression, not an approved live order.",
                "source_quality": "derived_pre_event_candidate_card",
                "source_paths": ";".join(str(path) for path in (WORKING_PATH, TRADE_PATH, INDEPENDENT_PATH, FACTOR_REVIEW_PATH, PB_PATH, RISK_PATH, DIRECTION_PATH)),
                "retrieved_at": retrieved,
            }
        )
    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_pre_event_trade_candidate() -> pd.DataFrame:
    return build_airline_pre_event_trade_candidate()


def source_path() -> str:
    return str(OUTPUT_PATH)
