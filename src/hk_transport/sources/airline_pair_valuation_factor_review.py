"""Valuation-premium and factor-neutral review for provisional pair directions."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

WORKING_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"
TRADE_PATH = NORMALIZED_DIR / "airline_pair_trade_thesis_scenarios.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_valuation_factor_review.csv"


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def build_airline_pair_valuation_factor_review(
    *,
    working: pd.DataFrame | None = None,
    trade: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    working = working if working is not None else pd.read_csv(WORKING_PATH)
    trade = trade if trade is not None else pd.read_csv(TRADE_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    base = trade[trade.scenario.eq("base")]
    for _, t in base.iterrows():
        w = working[working.pair_id.eq(t.pair_id)].iloc[0]
        long_is_a = t.long_asset == t.asset_a
        long_ps = _num(t.current_ps_a if long_is_a else t.current_ps_b)
        short_ps = _num(t.current_ps_b if long_is_a else t.current_ps_a)
        base_payoff = _num(t.beta_hedged_pair_payoff_pct)
        stress_10 = base_payoff - 10.0 if base_payoff is not None and long_ps is not None and short_ps is not None and long_ps > short_ps else base_payoff
        stress_20 = base_payoff - 20.0 if base_payoff is not None and long_ps is not None and short_ps is not None and long_ps > short_ps else base_payoff
        premium_pct = 100.0 * long_ps / short_ps - 100.0 if long_ps is not None and short_ps not in (None, 0) else None
        beta_gap = _num(w.get("factor_beta_gap_a_minus_b"))
        momentum_gap = _num(w.get("factor_momentum_1y_gap_a_minus_b_pct"))
        volatility_gap = _num(w.get("factor_volatility_gap_a_minus_b_pct"))
        factor_flag = "material_factor_gap" if any(value is not None and abs(value) > threshold for value, threshold in ((beta_gap, 0.25), (momentum_gap, 10.0), (volatility_gap, 10.0))) else "factor_gap_not_material_on_available_diagnostics"
        market_scope_a = "HK_leg" if str(t.asset_a).endswith(".HK") else "CN_A_leg"
        market_scope_b = "HK_leg" if str(t.asset_b).endswith(".HK") else "CN_A_leg"
        scope_status = "mixed_market_legs_CNA_forward_consensus" if market_scope_a != market_scope_b else "same_market_leg"
        quant_screen_passed = base_payoff is not None and stress_10 is not None and stress_10 > 0 and factor_flag != "material_factor_gap" and scope_status == "same_market_leg"
        # Passing the quant screen (survives a 10pp multiple-compression
        # stress, no material factor gap, same-market legs) is necessary but
        # not sufficient: required_next_evidence below lists corroborating
        # work (route-level yield, 1H2026 actuals, HK/A consensus
        # reconciliation, a real factor-residual test, a non-constant P/S
        # target) that nothing in this pipeline has actually gathered yet.
        # This is a research-only chain with no trading signal in v1, so
        # readiness never auto-promotes on the quant screen alone.
        required_evidence_complete = False
        ready = quant_screen_passed and required_evidence_complete
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
            "base_beta_hedged_payoff_pct": base_payoff, "long_multiple_compression_10pct_payoff_pct": stress_10,
            "long_multiple_compression_20pct_payoff_pct": stress_20,
            "factor_beta_gap_a_minus_b": beta_gap, "factor_momentum_1y_gap_a_minus_b_pct": momentum_gap,
            "factor_volatility_gap_a_minus_b_pct": volatility_gap, "factor_risk_status": factor_flag,
            "market_scope_a": market_scope_a, "market_scope_b": market_scope_b,
            "consensus_market_scope_status": scope_status,
            "trade_readiness_status": readiness_status,
            "required_next_evidence": "Validate route-level yield and 1H2026 actuals; reconcile HK/A consensus; test residual after beta/size/momentum controls; replace constant-P/S target with historical/peer-adjusted valuation.",
            "source_quality": "derived_valuation_factor_review",
            "source_paths": f"{WORKING_PATH};{TRADE_PATH}", "retrieved_at": retrieved,
        })
    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_pair_valuation_factor_review() -> pd.DataFrame:
    return build_airline_pair_valuation_factor_review()
