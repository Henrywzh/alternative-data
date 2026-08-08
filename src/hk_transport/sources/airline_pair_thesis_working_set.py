"""Working set for converting airline pair candidates into actual theses.

This is intentionally not a final trade recommendation.  It aligns the
company-level forward bridge with the actual market leg used in each pair,
then exposes valuation, catalyst, risk and evidence gates needed before a
direction can be approved.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

SCORECARD_PATH = NORMALIZED_DIR / "airline_pair_scorecard.csv"
BRIDGE_PATH = NORMALIZED_DIR / "airline_forward_earnings_bridge.csv"
EXPECTATION_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
GUIDANCE_PATH = NORMALIZED_DIR / "airline_guidance_coverage.csv"
PAIR_RISK_PATH = NORMALIZED_DIR / "airline_pair_risk_metrics.csv"
FACTOR_PATH = NORMALIZED_DIR / "airline_pair_factor_diagnostics.csv"
INVALIDATION_PATH = NORMALIZED_DIR / "airline_forward_invalidation_rules.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"


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


def _pair_row(frame: pd.DataFrame, company_a: str, company_b: str, asset_a: str, asset_b: str) -> pd.Series:
    if frame.empty or not {"company_a", "company_b"}.issubset(frame.columns):
        return pd.Series(dtype=object)
    rows = frame[
        frame["company_a"].eq(company_a)
        & frame["company_b"].eq(company_b)
        & (frame["asset_a"].eq(asset_a) if "asset_a" in frame.columns else True)
        & (frame["asset_b"].eq(asset_b) if "asset_b" in frame.columns else True)
    ]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _date_text(value: object) -> str:
    if pd.isna(value):
        return "pending"
    text = str(value)[:10]
    return text if len(text) == 10 and text[4] == "-" and text[7] == "-" else "pending"


def _market_leg(expectations: pd.DataFrame, company: str, asset: str) -> pd.Series:
    rows = expectations[
        expectations.get("company", pd.Series(dtype=object)).eq(company)
        & expectations.get("market_ticker", pd.Series(dtype=object)).eq(asset)
    ]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _bridge_leg(bridge: pd.DataFrame, company: str) -> pd.Series:
    rows = bridge[bridge.get("company", pd.Series(dtype=object)).eq(company) & bridge.get("scenario", pd.Series(dtype=object)).eq("base")]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _event_fields(guidance: pd.DataFrame, company: str) -> dict[str, object]:
    row = _row(guidance, company=company)
    return {
        "formal_report_scheduled_date": _date_text(row.get("formal_report_scheduled_date")) if not row.empty else "pending",
        "latest_warning_date": _date_text(row.get("latest_warning_date")) if not row.empty else "pending",
        "latest_warning_metric": row.get("latest_warning_metric", "") if not row.empty else "",
        "guidance_coverage_status": row.get("guidance_coverage_status", "pending") if not row.empty else "pending",
        "guidance_source_url": row.get("latest_warning_source_url", "") if not row.empty else "",
    }


def _leg_market_fields(expectations: pd.DataFrame, company: str, asset: str) -> dict[str, object]:
    row = _market_leg(expectations, company, asset)
    if row.empty:
        return {
            "current_price_native": None, "price_currency": "", "market_cap_usd_mn": None,
            "market_cap_to_consensus_revenue": None, "market_cap_to_consensus_profit": None,
            "target_price_avg_usd": None, "consensus_snapshot_date": "pending",
            "revenue_consensus_freshness": "missing", "profit_consensus_freshness": "missing",
        }
    return {
        "current_price_native": _num(row.get("latest_price_native")),
        "price_currency": row.get("price_currency", ""),
        "market_cap_usd_mn": _num(row.get("market_cap_usd_mn")),
        "market_cap_to_consensus_revenue": _num(row.get("market_cap_to_consensus_revenue_usd")),
        "market_cap_to_consensus_profit": _num(row.get("market_cap_to_consensus_net_profit_usd")),
        "target_price_avg_usd": _num(row.get("target_price_avg_usd")),
        "consensus_snapshot_date": str(row.get("snapshot_date", "pending"))[:10],
        "revenue_consensus_freshness": row.get("revenue_consensus_freshness_band", "missing"),
        "profit_consensus_freshness": row.get("profit_consensus_freshness_band", "missing"),
    }


def build_airline_pair_thesis_working_set(
    *,
    scorecard: pd.DataFrame | None = None,
    bridge: pd.DataFrame | None = None,
    expectations: pd.DataFrame | None = None,
    guidance: pd.DataFrame | None = None,
    pair_risk: pd.DataFrame | None = None,
    factors: pd.DataFrame | None = None,
    invalidations: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    scorecard = scorecard if scorecard is not None else pd.read_csv(SCORECARD_PATH)
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    expectations = expectations if expectations is not None else pd.read_csv(EXPECTATION_PATH)
    guidance = guidance if guidance is not None else pd.read_csv(GUIDANCE_PATH)
    pair_risk = pair_risk if pair_risk is not None else pd.read_csv(PAIR_RISK_PATH)
    factors = factors if factors is not None else pd.read_csv(FACTOR_PATH)
    invalidations = invalidations if invalidations is not None else pd.read_csv(INVALIDATION_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()

    priority = scorecard[
        scorecard.selection_bucket.ne("monitor")
        | scorecard.pair_id.eq("601021.SH__603885.SH")
    ].copy()
    priority = priority.sort_values("rank")
    rows: list[dict[str, object]] = []
    for _, pair in priority.iterrows():
        pair_id = str(pair["pair_id"])
        company_a, company_b = str(pair["company_a"]), str(pair["company_b"])
        asset_a, asset_b = str(pair["asset_a"]), str(pair["asset_b"])
        bridge_a, bridge_b = _bridge_leg(bridge, company_a), _bridge_leg(bridge, company_b)
        a_gap = _num(bridge_a.get("earnings_gap_to_consensus_pct"))
        b_gap = _num(bridge_b.get("earnings_gap_to_consensus_pct"))
        if a_gap is not None and b_gap is not None and a_gap > b_gap:
            direction_hint = "mechanical_long_a_short_b"
        elif a_gap is not None and b_gap is not None and a_gap < b_gap:
            direction_hint = "mechanical_long_b_short_a"
        else:
            direction_hint = "no_mechanical_direction"
        long_is_a = direction_hint == "mechanical_long_a_short_b"
        confidence = "low_requires_fundamental_validation"
        if not bridge_a.empty and not bridge_b.empty and bridge_a.get("assumption_status") == "existing_company_explicit_assumption" and bridge_b.get("assumption_status") == "existing_company_explicit_assumption":
            confidence = "medium_still_requires_valuation_and_catalyst_validation"
        risk = _pair_row(pair_risk, company_a, company_b, asset_a, asset_b)
        factor = _row(factors, pair_id=pair_id)
        events_a, events_b = _event_fields(guidance, company_a), _event_fields(guidance, company_b)
        market_a, market_b = _leg_market_fields(expectations, company_a, asset_a), _leg_market_fields(expectations, company_b, asset_b)
        inv_a = invalidations[invalidations.company.eq(company_a)]
        inv_b = invalidations[invalidations.company.eq(company_b)]
        rows.append({
            "dataset_id": "airline_pair_thesis_working_set", "pair_id": pair_id,
            "priority_rank": _num(pair.get("rank")), "selection_bucket": pair.get("selection_bucket"),
            "company_a": company_a, "asset_a": asset_a, "company_b": company_b, "asset_b": asset_b,
            "thesis_status": "direction_pending_review", "mechanical_direction_hint": direction_hint,
            "mechanical_direction_confidence": confidence,
            "variant_perception_a_gap_pct": a_gap, "variant_perception_b_gap_pct": b_gap,
            "variant_perception_gap_difference_pct": a_gap - b_gap if a_gap is not None and b_gap is not None else None,
            "base_revenue_gap_a_pct": _num(bridge_a.get("revenue_gap_to_consensus_pct")),
            "base_revenue_gap_b_pct": _num(bridge_b.get("revenue_gap_to_consensus_pct")),
            "current_price_a_native": market_a["current_price_native"], "current_price_b_native": market_b["current_price_native"],
            "price_currency_a": market_a["price_currency"], "price_currency_b": market_b["price_currency"],
            "market_cap_a_usd_mn": market_a["market_cap_usd_mn"], "market_cap_b_usd_mn": market_b["market_cap_usd_mn"],
            "ps_consensus_revenue_a": market_a["market_cap_to_consensus_revenue"], "ps_consensus_revenue_b": market_b["market_cap_to_consensus_revenue"],
            "pe_consensus_profit_a": market_a["market_cap_to_consensus_profit"], "pe_consensus_profit_b": market_b["market_cap_to_consensus_profit"],
            "valuation_status_a": "profit_multiple_unstable_or_missing" if market_a["market_cap_to_consensus_profit"] is None else "profit_multiple_available",
            "valuation_status_b": "profit_multiple_unstable_or_missing" if market_b["market_cap_to_consensus_profit"] is None else "profit_multiple_available",
            "consensus_snapshot_date_a": market_a["consensus_snapshot_date"], "consensus_snapshot_date_b": market_b["consensus_snapshot_date"],
            "revenue_consensus_freshness_a": market_a["revenue_consensus_freshness"], "revenue_consensus_freshness_b": market_b["revenue_consensus_freshness"],
            "profit_consensus_freshness_a": market_a["profit_consensus_freshness"], "profit_consensus_freshness_b": market_b["profit_consensus_freshness"],
            "report_date_a": events_a["formal_report_scheduled_date"], "report_date_b": events_b["formal_report_scheduled_date"],
            "warning_date_a": events_a["latest_warning_date"], "warning_date_b": events_b["latest_warning_date"],
            "guidance_status_a": events_a["guidance_coverage_status"], "guidance_status_b": events_b["guidance_coverage_status"],
            "correlation_a_b": _num(risk.get("correlation_a_b")), "beta_a_to_b": _num(risk.get("beta_a_to_b")),
            "beta_b_to_a": _num(risk.get("beta_b_to_a")),
            "hedged_spread_vol_pct": _num(risk.get("hedged_spread_vol_a_minus_beta_b_pct" if long_is_a else "hedged_spread_vol_b_minus_beta_a_pct")),
            "hedged_spread_max_drawdown_pct": _num(risk.get("hedged_spread_max_drawdown_a_minus_beta_b_pct" if long_is_a else "hedged_spread_max_drawdown_b_minus_beta_a_pct")),
            "hedged_spread_vol_a_minus_beta_b_pct": _num(risk.get("hedged_spread_vol_a_minus_beta_b_pct")),
            "hedged_spread_vol_b_minus_beta_a_pct": _num(risk.get("hedged_spread_vol_b_minus_beta_a_pct")),
            "hedged_spread_max_drawdown_a_minus_beta_b_pct": _num(risk.get("hedged_spread_max_drawdown_a_minus_beta_b_pct")),
            "hedged_spread_max_drawdown_b_minus_beta_a_pct": _num(risk.get("hedged_spread_max_drawdown_b_minus_beta_a_pct")),
            "turnover_a_usd_mn": _num(risk.get("median_turnover_a_usd_mn_60d")), "turnover_b_usd_mn": _num(risk.get("median_turnover_b_usd_mn_60d")),
            "borrow_data_available_a": risk.get("borrow_data_available_a"), "borrow_data_available_b": risk.get("borrow_data_available_b"),
            "factor_beta_gap_a_minus_b": _num(factor.get("beta_gap_a_minus_b")), "factor_size_gap_a_minus_b": _num(factor.get("log_size_gap_a_minus_b")),
            "factor_momentum_1y_gap_a_minus_b_pct": _num(factor.get("momentum_1y_gap_a_minus_b_pct")),
            "factor_volatility_gap_a_minus_b_pct": _num(factor.get("volatility_gap_a_minus_b_pct")),
            "invalidation_rule_count_a": len(inv_a), "invalidation_rule_count_b": len(inv_b),
            "next_evidence_gate": "route pricing/booking, 1H2026 actuals, consensus revisions, valuation target and catalyst confirmation",
            "source_quality": "derived_thesis_working_set",
            "source_paths": ";".join(str(path) for path in (SCORECARD_PATH, BRIDGE_PATH, EXPECTATION_PATH, GUIDANCE_PATH, PAIR_RISK_PATH, FACTOR_PATH, INVALIDATION_PATH)),
            "retrieved_at": retrieved,
        })
    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_pair_thesis_working_set() -> pd.DataFrame:
    return build_airline_pair_thesis_working_set()
