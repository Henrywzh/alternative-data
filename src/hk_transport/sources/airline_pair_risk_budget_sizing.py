"""Direction-aware risk-budget and sizing diagnostics for priority pairs."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

WORKING_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"
TRADE_PATH = NORMALIZED_DIR / "airline_pair_trade_thesis_scenarios.csv"
RISK_PATH = NORMALIZED_DIR / "airline_pair_risk_metrics.csv"
FACTOR_PATH = NORMALIZED_DIR / "airline_pair_factor_diagnostics.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_risk_budget_sizing.csv"

DEFAULT_LOSS_BUDGETS = (0.25, 0.50, 1.00)


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


def _oriented_gap(row: pd.Series, field: str, *, long_is_a: bool) -> float | None:
    value = _num(row.get(field))
    return value if long_is_a else (-value if value is not None else None)


def build_airline_pair_risk_budget_sizing(
    *,
    working: pd.DataFrame | None = None,
    trade: pd.DataFrame | None = None,
    risk: pd.DataFrame | None = None,
    factors: pd.DataFrame | None = None,
    loss_budgets_pct: tuple[float, ...] = DEFAULT_LOSS_BUDGETS,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build sizing diagnostics for configurable portfolio loss budgets.

    ``loss_budgets_pct`` is deliberately an input rather than a recommendation.
    Sizing assumes equal long-leg base notional and a mechanical beta hedge;
    borrow, factor-model neutrality and portfolio correlations remain gates.
    """

    working = working if working is not None else pd.read_csv(WORKING_PATH)
    trade = trade if trade is not None else pd.read_csv(TRADE_PATH)
    risk = risk if risk is not None else pd.read_csv(RISK_PATH)
    factors = factors if factors is not None else pd.read_csv(FACTOR_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []

    for _, pair in working.iterrows():
        pair_id = str(pair["pair_id"])
        base_trade = _row(trade, pair_id=pair_id, scenario="base")
        risk_row = _row(risk, asset_a=pair["asset_a"], asset_b=pair["asset_b"])
        factor_row = _row(factors, pair_id=pair_id)
        if base_trade.empty or risk_row.empty:
            continue
        long_asset = str(base_trade.get("long_asset"))
        short_asset = str(base_trade.get("short_asset"))
        long_is_a = long_asset == str(pair["asset_a"])
        beta = _num(risk_row.get("beta_a_to_b" if long_is_a else "beta_b_to_a"))
        beta = beta if beta is not None and beta > 0 else 1.0
        drawdown_column = "hedged_spread_max_drawdown_a_minus_beta_b_pct" if long_is_a else "hedged_spread_max_drawdown_b_minus_beta_a_pct"
        volatility_column = "hedged_spread_vol_a_minus_beta_b_pct" if long_is_a else "hedged_spread_vol_b_minus_beta_a_pct"
        direction_drawdown = _num(risk_row.get(drawdown_column))
        direction_volatility = _num(risk_row.get(volatility_column))
        factor_beta = _oriented_gap(factor_row, "beta_gap_a_minus_b", long_is_a=long_is_a)
        factor_size = _oriented_gap(factor_row, "log_size_gap_a_minus_b", long_is_a=long_is_a)
        factor_momentum = _oriented_gap(factor_row, "momentum_1y_gap_a_minus_b_pct", long_is_a=long_is_a)
        factor_volatility = _oriented_gap(factor_row, "volatility_gap_a_minus_b_pct", long_is_a=long_is_a)
        factor_flags = []
        if factor_beta is not None and abs(factor_beta) > 0.25:
            factor_flags.append("beta_gap")
        if factor_momentum is not None and abs(factor_momentum) > 10.0:
            factor_flags.append("momentum_gap")
        if factor_volatility is not None and abs(factor_volatility) > 10.0:
            factor_flags.append("volatility_gap")
        risk_status = "borrow_unavailable" if not bool(pair.get("borrow_data_available_a")) or not bool(pair.get("borrow_data_available_b")) else "borrow_data_present"
        if factor_flags:
            risk_status += ";" + ";".join(f"material_{flag}" for flag in factor_flags)
        if direction_drawdown is None or direction_drawdown >= 0:
            risk_status += ";invalid_drawdown_input"
        for loss_budget in loss_budgets_pct:
            budget = float(loss_budget)
            drawdown_abs = abs(direction_drawdown) if direction_drawdown not in (None, 0) else None
            long_notional = budget / drawdown_abs * 100.0 if drawdown_abs else None
            short_notional = long_notional * beta if long_notional is not None else None
            gross_notional = long_notional + short_notional if long_notional is not None and short_notional is not None else None
            rows.append(
                {
                    "dataset_id": "airline_pair_risk_budget_sizing",
                    "pair_id": pair_id,
                    "selection_bucket": pair["selection_bucket"],
                    "direction_status": "provisional_mechanical_direction_requires_review",
                    "long_leg": base_trade.get("long_leg"),
                    "long_asset": long_asset,
                    "short_leg": base_trade.get("short_leg"),
                    "short_asset": short_asset,
                    "portfolio_loss_budget_pct": budget,
                    "mechanical_beta_hedge_ratio_long_to_short": beta,
                    "direction_aware_hedged_spread_volatility_pct": direction_volatility,
                    "direction_aware_hedged_spread_max_drawdown_pct": direction_drawdown,
                    "diagnostic_long_notional_pct_nav": long_notional,
                    "diagnostic_short_notional_pct_nav": short_notional,
                    "diagnostic_gross_notional_pct_nav": gross_notional,
                    "implied_loss_at_observed_drawdown_pct_nav": budget if long_notional is not None else None,
                    "factor_beta_long_minus_short": factor_beta,
                    "factor_size_log_gap_long_minus_short": factor_size,
                    "factor_momentum_1y_gap_long_minus_short_pct": factor_momentum,
                    "factor_volatility_gap_long_minus_short_pct": factor_volatility,
                    "factor_risk_flags": ";".join(factor_flags) if factor_flags else "none_on_available_proxies",
                    "risk_status": risk_status,
                    "illustrative_stop_rule": "Review at 50% of observed direction-aware drawdown; hard stop at portfolio risk limit, not a fixed price stop.",
                    "trade_construction_rule": "Use equal long-leg base notional with mechanical beta hedge only as a diagnostic; final sizing requires formal factor residuals, borrow/recall, liquidity and portfolio correlation review.",
                    "source_quality": "derived_direction_aware_risk_budget_diagnostic",
                    "source_paths": f"{WORKING_PATH};{TRADE_PATH};{RISK_PATH};{FACTOR_PATH}",
                    "retrieved_at": retrieved,
                }
            )
    result = pd.DataFrame(rows)
    return result


def fetch_airline_pair_risk_budget_sizing() -> pd.DataFrame:
    result = build_airline_pair_risk_budget_sizing()
    result.to_csv(OUTPUT_PATH, index=False)
    return result
