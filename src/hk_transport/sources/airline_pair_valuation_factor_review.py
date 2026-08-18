"""Valuation-premium and factor-neutral review for provisional pair directions."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

WORKING_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"
TRADE_PATH = NORMALIZED_DIR / "airline_pair_trade_thesis_scenarios.csv"
VALUATION_GATE_PATH = NORMALIZED_DIR / "airline_valuation_peer_comparability.csv"
RESIDUAL_TEST_PATH = NORMALIZED_DIR / "airline_pair_factor_residual_test.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_valuation_factor_review.csv"


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def build_airline_pair_valuation_factor_review(
    *,
    working: pd.DataFrame | None = None,
    trade: pd.DataFrame | None = None,
    valuation_gate: pd.DataFrame | None = None,
    residual_test: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    working = working if working is not None else pd.read_csv(WORKING_PATH)
    trade = trade if trade is not None else pd.read_csv(TRADE_PATH)
    valuation_gate = valuation_gate if valuation_gate is not None else (pd.read_csv(VALUATION_GATE_PATH) if VALUATION_GATE_PATH.exists() else pd.DataFrame())
    residual_test = residual_test if residual_test is not None else (pd.read_csv(RESIDUAL_TEST_PATH) if RESIDUAL_TEST_PATH.exists() else pd.DataFrame())
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    base = trade[trade.scenario.eq("base")]
    for _, t in base.iterrows():
        w = working[working.pair_id.eq(t.pair_id)].iloc[0]
        gate = valuation_gate[valuation_gate.pair_id.eq(t.pair_id)].iloc[0] if not valuation_gate.empty and valuation_gate.pair_id.eq(t.pair_id).any() else pd.Series(dtype=object)
        residual = residual_test[residual_test.pair_id.eq(t.pair_id)].iloc[0] if not residual_test.empty and residual_test.pair_id.eq(t.pair_id).any() else pd.Series(dtype=object)
        long_is_a = t.long_asset == t.asset_a
        long_ps = _num(t.current_ps_a if long_is_a else t.current_ps_b)
        short_ps = _num(t.current_ps_b if long_is_a else t.current_ps_a)
        long_ps_ttm = _num(t.current_ps_ttm_a if long_is_a else t.current_ps_ttm_b)
        short_ps_ttm = _num(t.current_ps_ttm_b if long_is_a else t.current_ps_ttm_a)
        long_ps_median = _num(t.historical_ps_median_3y_a if long_is_a else t.historical_ps_median_3y_b)
        short_ps_median = _num(t.historical_ps_median_3y_b if long_is_a else t.historical_ps_median_3y_a)
        long_ps_reversion = _num(t.valuation_reversion_return_a_pct if long_is_a else t.valuation_reversion_return_b_pct)
        short_ps_reversion = _num(t.valuation_reversion_return_b_pct if long_is_a else t.valuation_reversion_return_a_pct)
        ps_reversion_pair = long_ps_reversion - short_ps_reversion if long_ps_reversion is not None and short_ps_reversion is not None else None
        base_payoff = _num(t.beta_hedged_pair_payoff_pct)
        independent_view_status = str(t.get("pre_event_view_status", "missing"))
        independent_payoff = _num(t.get("pre_event_independent_beta_hedged_pair_payoff_pct"))
        independent_target_long = _num(
            t.get("pre_event_independent_target_price_a_native" if long_is_a else "pre_event_independent_target_price_b_native")
        )
        independent_target_short = _num(
            t.get("pre_event_independent_target_price_b_native" if long_is_a else "pre_event_independent_target_price_a_native")
        )
        observed_drawdown = _num(t.get("observed_hedged_spread_max_drawdown_pct"))
        independent_payoff_to_drawdown = (
            independent_payoff / abs(observed_drawdown)
            if independent_payoff is not None and observed_drawdown not in (None, 0)
            else None
        )
        stress_10 = base_payoff - 10.0 if base_payoff is not None and long_ps is not None and short_ps is not None and long_ps > short_ps else base_payoff
        stress_20 = base_payoff - 20.0 if base_payoff is not None and long_ps is not None and short_ps is not None and long_ps > short_ps else base_payoff
        premium_pct = 100.0 * long_ps / short_ps - 100.0 if long_ps is not None and short_ps not in (None, 0) else None
        beta_gap = _num(w.get("factor_beta_gap_a_minus_b"))
        momentum_gap = _num(w.get("factor_momentum_1y_gap_a_minus_b_pct"))
        volatility_gap = _num(w.get("factor_volatility_gap_a_minus_b_pct"))
        factor_flag = "material_factor_gap" if any(value is not None and abs(value) > threshold for value, threshold in ((beta_gap, 0.25), (momentum_gap, 10.0), (volatility_gap, 10.0))) else "factor_gap_not_material_on_available_diagnostics"
        residual_status = str(residual.get("regression_status", "missing")) if not residual.empty else "missing"
        residual_alpha = _num(residual.get("alpha_annualized_pct")) if not residual.empty else None
        residual_r_squared = _num(residual.get("r_squared")) if not residual.empty else None
        residual_drawdown = _num(residual.get("residual_max_drawdown_pct")) if not residual.empty else None
        market_scope_a = "HK_leg" if str(t.asset_a).endswith(".HK") else "CN_A_leg"
        market_scope_b = "HK_leg" if str(t.asset_b).endswith(".HK") else "CN_A_leg"
        scope_status = "mixed_market_legs_CNA_forward_consensus" if market_scope_a != market_scope_b else "same_market_leg"
        valuation_gate_status = str(gate.get("valuation_target_readiness", "missing")) if not gate.empty else "missing"
        valuation_gate_pass = valuation_gate_status.startswith("candidate_")
        # Clearing the quant screen -- a positive beta-hedged payoff that
        # survives a 10pp long-multiple compression, no material factor gap,
        # both legs in the same market -- is necessary but not sufficient.
        # The valuation gate is a separate hurdle, so the two failures are
        # reported separately: collapsing them would label a pair that passed
        # the screen as having a valuation/factor/scope gap it does not have.
        quant_screen_passed = (
            base_payoff is not None
            and stress_10 is not None
            and stress_10 > 0
            and factor_flag != "material_factor_gap"
            and scope_status == "same_market_leg"
        )
        ready = quant_screen_passed and valuation_gate_pass
        if ready:
            readiness_status = "provisional_trade_ready_for_review"
        elif quant_screen_passed:
            readiness_status = "not_trade_ready_pending_required_evidence"
        else:
            readiness_status = "not_trade_ready_valuation_factor_or_scope_gap"
        rows.append({
            "dataset_id": "airline_pair_valuation_factor_review", "pair_id": t.pair_id,
            "selection_bucket": t.selection_bucket, "long_leg": t.long_leg, "short_leg": t.short_leg,
            "long_current_ps": long_ps, "short_current_ps": short_ps, "long_ps_premium_vs_short_pct": premium_pct,
            "long_current_ps_ttm": long_ps_ttm, "short_current_ps_ttm": short_ps_ttm,
            "long_historical_ps_median_3y": long_ps_median, "short_historical_ps_median_3y": short_ps_median,
            "long_ps_reversion_return_pct": long_ps_reversion, "short_ps_reversion_return_pct": short_ps_reversion,
            "historical_ps_reversion_pair_payoff_pct": ps_reversion_pair,
            "base_beta_hedged_payoff_pct": base_payoff, "long_multiple_compression_10pct_payoff_pct": stress_10,
            "long_multiple_compression_20pct_payoff_pct": stress_20,
            "pre_event_independent_view_status": independent_view_status,
            "pre_event_independent_target_long_native": independent_target_long,
            "pre_event_independent_target_short_native": independent_target_short,
            "pre_event_independent_beta_hedged_pair_payoff_pct": independent_payoff,
            "pre_event_independent_payoff_to_observed_drawdown": independent_payoff_to_drawdown,
            "factor_beta_gap_a_minus_b": beta_gap, "factor_momentum_1y_gap_a_minus_b_pct": momentum_gap,
            "factor_volatility_gap_a_minus_b_pct": volatility_gap, "factor_risk_status": factor_flag,
            "residual_alpha_annualized_pct": residual_alpha, "residual_r_squared": residual_r_squared,
            "residual_max_drawdown_pct": residual_drawdown, "residual_test_status": residual_status,
            "valuation_gate_status": valuation_gate_status,
            "market_scope_a": market_scope_a, "market_scope_b": market_scope_b,
            "consensus_market_scope_status": scope_status,
            "quant_screen_status": "passed" if quant_screen_passed else "failed",
            "trade_readiness_status": readiness_status,
            "required_next_evidence": "Use the bottom-up pre-event forecast as the starting view; compare its illustrative P/S target/payoff with P/B and historical-band definitions; stress factor residual alpha across windows and factor definitions; validate route-level yield and 1H2026 actuals as the earnings catalyst; reconcile annual-P/S history to announcement-aligned TTM/forward revenue before treating reversion as fair value.",
            "source_quality": "derived_valuation_factor_review",
            "source_paths": f"{WORKING_PATH};{TRADE_PATH};{VALUATION_GATE_PATH};{RESIDUAL_TEST_PATH}", "retrieved_at": retrieved,
        })
    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_pair_valuation_factor_review() -> pd.DataFrame:
    return build_airline_pair_valuation_factor_review()
