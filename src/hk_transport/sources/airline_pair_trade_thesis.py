"""Provisional long/short trade-thesis scenarios for priority airline pairs."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

WORKING_SET_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"
BRIDGE_PATH = NORMALIZED_DIR / "airline_forward_earnings_bridge.csv"
BANDS_PATH = NORMALIZED_DIR / "airline_historical_valuation_bands.csv"
FREE_CURRENT_PATH = NORMALIZED_DIR / "airline_free_current_valuation.csv"
INDEPENDENT_FORECAST_PATH = NORMALIZED_DIR / "airline_independent_forecast_view.csv"
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


def _valuation_row(bands: pd.DataFrame, asset: str) -> pd.Series:
    if bands.empty:
        return pd.Series(dtype=object)
    rows = bands.loc[
        bands["asset"].eq(asset)
        & bands["metric"].eq("ps_annual_period_end")
        & bands["window"].eq("3y")
    ]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _current_ps_row(current: pd.DataFrame, asset: str) -> pd.Series:
    if current.empty:
        return pd.Series(dtype=object)
    rows = current.loc[current["asset"].eq(asset) & current["metric"].eq("ps_ttm")]
    return rows.iloc[-1] if not rows.empty else pd.Series(dtype=object)


def _valuation_reversion_return(current_ps: float | None, historical_median: float | None) -> float | None:
    if current_ps is None or historical_median is None or current_ps <= 0:
        return None
    return (historical_median / current_ps - 1.0) * 100.0


def build_airline_pair_trade_thesis_scenarios(
    *,
    working_set: pd.DataFrame | None = None,
    bridge: pd.DataFrame | None = None,
    valuation_bands: pd.DataFrame | None = None,
    free_current: pd.DataFrame | None = None,
    independent_forecast: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    working_set = working_set if working_set is not None else pd.read_csv(WORKING_SET_PATH)
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    valuation_bands = valuation_bands if valuation_bands is not None else (pd.read_csv(BANDS_PATH) if BANDS_PATH.exists() else pd.DataFrame())
    free_current = free_current if free_current is not None else (pd.read_csv(FREE_CURRENT_PATH) if FREE_CURRENT_PATH.exists() else pd.DataFrame())
    independent_forecast = independent_forecast if independent_forecast is not None else (
        pd.read_csv(INDEPENDENT_FORECAST_PATH) if INDEPENDENT_FORECAST_PATH.exists() else pd.DataFrame()
    )
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
        valuation_a = _valuation_row(valuation_bands, asset_a)
        valuation_b = _valuation_row(valuation_bands, asset_b)
        current_ps_row_a = _current_ps_row(free_current, asset_a)
        current_ps_row_b = _current_ps_row(free_current, asset_b)
        current_ps_ttm_a = _num(current_ps_row_a.get("value"))
        current_ps_ttm_b = _num(current_ps_row_b.get("value"))
        historical_ps_median_a = _num(valuation_a.get("median_value"))
        historical_ps_median_b = _num(valuation_b.get("median_value"))
        historical_ps_p25_a = _num(valuation_a.get("p25_value"))
        historical_ps_p25_b = _num(valuation_b.get("p25_value"))
        historical_ps_p75_a = _num(valuation_a.get("p75_value"))
        historical_ps_p75_b = _num(valuation_b.get("p75_value"))
        valuation_reversion_a = _valuation_reversion_return(current_ps_ttm_a, historical_ps_median_a)
        valuation_reversion_b = _valuation_reversion_return(current_ps_ttm_b, historical_ps_median_b)
        independent_a = _row(independent_forecast, company=company_a, scenario="base")
        independent_b = _row(independent_forecast, company=company_b, scenario="base")
        independent_view_defined = not independent_a.empty and not independent_b.empty
        independent_a_revenue_gap = _num(independent_a.get("revenue_gap_vs_consensus_pct")) if independent_view_defined else None
        independent_b_revenue_gap = _num(independent_b.get("revenue_gap_vs_consensus_pct")) if independent_view_defined else None
        independent_a_profit_gap = _num(independent_a.get("profit_gap_vs_consensus_pct")) if independent_view_defined else None
        independent_b_profit_gap = _num(independent_b.get("profit_gap_vs_consensus_pct")) if independent_view_defined else None
        independent_profit_gap_spread = (
            independent_a_profit_gap - independent_b_profit_gap
            if independent_a_profit_gap is not None and independent_b_profit_gap is not None
            else None
        )
        independent_revenue_gap_spread = (
            independent_a_revenue_gap - independent_b_revenue_gap
            if independent_a_revenue_gap is not None and independent_b_revenue_gap is not None
            else None
        )
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
            total_return_a = (
                (1.0 + gap_a / 100.0) * (1.0 + valuation_reversion_a / 100.0) - 1.0
            ) * 100.0 if gap_a is not None and valuation_reversion_a is not None else gap_a
            total_return_b = (
                (1.0 + gap_b / 100.0) * (1.0 + valuation_reversion_b / 100.0) - 1.0
            ) * 100.0 if gap_b is not None and valuation_reversion_b is not None else gap_b
            target_a = price_a * (1.0 + total_return_a / 100.0) if price_a is not None and total_return_a is not None else None
            target_b = price_b * (1.0 + total_return_b / 100.0) if price_b is not None and total_return_b is not None else None
            return_a, return_b = total_return_a, total_return_b
            long_return = return_a if long_leg == "a" else return_b
            short_return = return_b if short_leg == "b" else return_a
            gross_payoff = long_return - short_return if long_return is not None and short_return is not None else None
            beta_payoff = long_return - beta_hedge * short_return if long_return is not None and short_return is not None else None
            model_long_return = gap_a if long_leg == "a" else gap_b
            model_short_return = gap_b if short_leg == "b" else gap_a
            model_gross_payoff = model_long_return - model_short_return if model_long_return is not None and model_short_return is not None else None
            model_beta_payoff = model_long_return - beta_hedge * model_short_return if model_long_return is not None and model_short_return is not None else None
            independent_total_return_a = (
                (1.0 + independent_a_revenue_gap / 100.0) * (1.0 + valuation_reversion_a / 100.0) - 1.0
            ) * 100.0 if independent_a_revenue_gap is not None and valuation_reversion_a is not None else None
            independent_total_return_b = (
                (1.0 + independent_b_revenue_gap / 100.0) * (1.0 + valuation_reversion_b / 100.0) - 1.0
            ) * 100.0 if independent_b_revenue_gap is not None and valuation_reversion_b is not None else None
            independent_long_return = independent_total_return_a if long_leg == "a" else independent_total_return_b
            independent_short_return = independent_total_return_b if short_leg == "b" else independent_total_return_a
            independent_model_long_return = independent_a_revenue_gap if long_leg == "a" else independent_b_revenue_gap
            independent_model_short_return = independent_b_revenue_gap if short_leg == "b" else independent_a_revenue_gap
            independent_model_beta_payoff = (
                independent_model_long_return - beta_hedge * independent_model_short_return
                if independent_model_long_return is not None and independent_model_short_return is not None
                else None
            )
            independent_valuation_beta_payoff = (
                independent_long_return - beta_hedge * independent_short_return
                if independent_long_return is not None and independent_short_return is not None
                else None
            )
            independent_target_a = (
                price_a * (1.0 + independent_total_return_a / 100.0)
                if price_a is not None and independent_total_return_a is not None
                else None
            )
            independent_target_b = (
                price_b * (1.0 + independent_total_return_b / 100.0)
                if price_b is not None and independent_total_return_b is not None
                else None
            )
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
                "pre_event_view_status": "pre_event_view_defined" if independent_view_defined else "not_available_for_pair",
                "pre_event_view_direction": (
                    f"long {independent_a.get('company')} / short {independent_b.get('company')}"
                    if independent_view_defined and independent_a.get("view_direction") == "long_candidate" and independent_b.get("view_direction") == "short_candidate"
                    else "no_pre_event_independent_view"
                ),
                "pre_event_base_revenue_gap_a_pct": independent_a_revenue_gap,
                "pre_event_base_revenue_gap_b_pct": independent_b_revenue_gap,
                "pre_event_base_profit_gap_a_pct": independent_a_profit_gap,
                "pre_event_base_profit_gap_b_pct": independent_b_profit_gap,
                "pre_event_revenue_gap_spread_a_minus_b_pct": independent_revenue_gap_spread,
                "pre_event_profit_gap_spread_a_minus_b_pct": independent_profit_gap_spread,
                "pre_event_variant_perception": independent_a.get("variant_perception", "") if independent_view_defined else "",
                "pre_event_invalidation_rule": independent_a.get("invalidation_rule", "") if independent_view_defined else "",
                "pre_event_forecast_method": independent_a.get("forecast_method", "") if independent_view_defined else "",
                "current_price_a_native": price_a, "current_price_b_native": price_b,
                "current_ps_a": ps_a, "current_ps_b": ps_b,
                "current_ps_ttm_a": current_ps_ttm_a, "current_ps_ttm_b": current_ps_ttm_b,
                "historical_ps_p25_3y_a": historical_ps_p25_a, "historical_ps_p25_3y_b": historical_ps_p25_b,
                "historical_ps_median_3y_a": historical_ps_median_a, "historical_ps_median_3y_b": historical_ps_median_b,
                "historical_ps_p75_3y_a": historical_ps_p75_a, "historical_ps_p75_3y_b": historical_ps_p75_b,
                "valuation_reversion_return_a_pct": valuation_reversion_a,
                "valuation_reversion_return_b_pct": valuation_reversion_b,
                "target_price_a_native": target_a, "target_price_b_native": target_b,
                "target_price_method": "3y_median_annual_P/S_reversion_plus_model_revenue_gap_if_available",
                "model_revenue_gap_a_pct": gap_a, "model_revenue_gap_b_pct": gap_b,
                "valuation_adjusted_return_a_pct": return_a, "valuation_adjusted_return_b_pct": return_b,
                "equal_notional_gross_pair_payoff_pct": gross_payoff,
                "beta_hedge_ratio_long_to_short": beta_hedge,
                "beta_hedged_pair_payoff_pct": beta_payoff,
                "model_only_equal_notional_gross_pair_payoff_pct": model_gross_payoff,
                "model_only_beta_hedged_pair_payoff_pct": model_beta_payoff,
                "pre_event_independent_valuation_adjusted_return_a_pct": independent_total_return_a,
                "pre_event_independent_valuation_adjusted_return_b_pct": independent_total_return_b,
                "pre_event_independent_target_price_a_native": independent_target_a,
                "pre_event_independent_target_price_b_native": independent_target_b,
                "pre_event_independent_model_only_beta_hedged_revenue_payoff_pct": independent_model_beta_payoff,
                "pre_event_independent_beta_hedged_pair_payoff_pct": independent_valuation_beta_payoff,
                "pre_event_independent_target_method": (
                    "3y_median_annual_P/S_reversion_plus_independent_pre_event_revenue_gap_diagnostic"
                    if independent_view_defined
                    else "not_available_for_pair"
                ),
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
                "source_paths": f"{WORKING_SET_PATH};{BRIDGE_PATH};{BANDS_PATH};{FREE_CURRENT_PATH};{INDEPENDENT_FORECAST_PATH}",
                "retrieved_at": retrieved,
            })
    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_pair_trade_thesis_scenarios() -> pd.DataFrame:
    return build_airline_pair_trade_thesis_scenarios()
