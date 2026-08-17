"""Peer-comparability and valuation-evidence gate for priority airline pairs."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

FUNDAMENTALS_PATH = NORMALIZED_DIR / "airline_company_fundamentals.csv"
HISTORY_PATH = NORMALIZED_DIR / "airline_financial_history_trend.csv"
WORKING_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"
PB_PATH = NORMALIZED_DIR / "airline_historical_pb_valuation.csv"
FREE_HISTORY_PATH = NORMALIZED_DIR / "airline_free_valuation_history.csv"
FREE_CURRENT_PATH = NORMALIZED_DIR / "airline_free_current_valuation.csv"
BANDS_PATH = NORMALIZED_DIR / "airline_historical_valuation_bands.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_valuation_peer_comparability.csv"


PEER_CLASS = {
    "Cathay Pacific": "international_hub_carrier",
    "Air China": "network_carrier",
    "China Southern Airlines": "network_carrier",
    "China Eastern Airlines": "network_carrier",
    "Spring Airlines": "low_cost_carrier",
    "Hainan Airlines Holdings": "multi_carrier_network_group",
    "Juneyao Airlines": "mixed_high_value_network_with_9air",
}


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _latest_date(*frames: pd.DataFrame | None) -> str:
    candidates: list[str] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for column in ("as_of_date", "snapshot_date", "screen_snapshot_date", "retrieved_at"):
            if column not in frame.columns:
                continue
            for raw in frame[column].dropna().astype(str):
                candidate = raw[:10]
                if len(candidate) == 10 and candidate[4] == "-" and candidate[7] == "-":
                    candidates.append(candidate)
    return max(candidates) if candidates else "pending_date_derivation"


def _fundamental_row(fundamentals: pd.DataFrame, company: str) -> pd.Series:
    matched = fundamentals[fundamentals["company"].astype(str).eq(company)]
    return matched.iloc[0] if not matched.empty else pd.Series(dtype=object)


def _scope_class(company: str, row: pd.Series) -> str:
    if company == "Juneyao Airlines":
        return "listed_group_consolidated_including_9air"
    if company == "Hainan Airlines Holdings":
        return "listed_multi_carrier_group_consolidated"
    if not row.empty and "scope" in _text(row.get("operating_scope_warning")).lower():
        return "listed_group_consolidated_scope_warning"
    return "listed_carrier_consolidated"


def _model_match(class_a: str, class_b: str) -> str:
    if class_a == class_b:
        return "same_peer_class"
    if {class_a, class_b} == {"network_carrier", "low_cost_carrier"}:
        return "network_vs_low_cost_not_like_for_like"
    return "different_business_model_or_group_scope"


def _historical_market_multiple_status(history: pd.DataFrame, company: str) -> tuple[str, str, str, str]:
    subset = history[history["company"].astype(str).eq(company)] if not history.empty else pd.DataFrame()
    if subset.empty:
        return (
            "no_historical_financial_rows",
            "pending",
            "pending",
            "no_historical_rows",
        )
    period_end = pd.to_datetime(subset.get("period_end"), errors="coerce")
    min_period = period_end.min().date().isoformat() if period_end.notna().any() else "pending"
    max_period = period_end.max().date().isoformat() if period_end.notna().any() else "pending"
    has_market_series = subset["metric"].astype(str).str.lower().isin({"price", "market_cap", "market_capitalization"}).any()
    pit = ";".join(sorted(set(subset.get("point_in_time_status", pd.Series(dtype=str)).dropna().astype(str))))
    if has_market_series:
        return ("historical_market_series_present_check_multiple_construction", min_period, max_period, pit)
    return ("missing_historical_price_market_cap_series", min_period, max_period, pit or "financial_period_end_only")


def _free_valuation_status(
    free_history: pd.DataFrame,
    bands: pd.DataFrame,
    asset: str,
) -> tuple[str, str, str, str, dict[str, float | None]]:
    subset = free_history.loc[free_history["asset"].eq(asset)].copy() if not free_history.empty else pd.DataFrame()
    if subset.empty:
        return "missing_free_valuation_history", "pending", "pending", "free_layer_missing", {}
    dates = pd.to_datetime(subset.get("observation_date"), errors="coerce")
    min_period = dates.min().date().isoformat() if dates.notna().any() else "pending"
    max_period = dates.max().date().isoformat() if dates.notna().any() else "pending"
    pit = ";".join(sorted(set(subset.get("point_in_time_status", pd.Series(dtype=str)).dropna().astype(str))))
    stats: dict[str, float | None] = {}
    if not bands.empty:
        rows = bands.loc[bands["asset"].eq(asset) & bands["window"].eq("3y")]
        for metric in ("pe_ttm", "pb", "ps_annual_period_end"):
            row = rows.loc[rows["metric"].eq(metric)]
            if not row.empty:
                stats[f"{metric}_median_3y"] = _num(row.iloc[0].get("median_value"))
                stats[f"{metric}_current_percentile_3y"] = _num(row.iloc[0].get("current_percentile_positive"))
    return "free_dated_pe_pb_market_cap_plus_constructed_ps", min_period, max_period, pit or "free_vendor_dated", stats


def build_airline_valuation_peer_comparability(
    *,
    fundamentals: pd.DataFrame | None = None,
    history: pd.DataFrame | None = None,
    working: pd.DataFrame | None = None,
    pb: pd.DataFrame | None = None,
    free_history: pd.DataFrame | None = None,
    free_current: pd.DataFrame | None = None,
    valuation_bands: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build the valuation evidence gate for the five priority pair rows."""

    fundamentals = fundamentals if fundamentals is not None else pd.read_csv(FUNDAMENTALS_PATH)
    history = history if history is not None else pd.read_csv(HISTORY_PATH)
    working = working if working is not None else pd.read_csv(WORKING_PATH)
    pb = pb if pb is not None else (pd.read_csv(PB_PATH) if PB_PATH.exists() else pd.DataFrame())
    free_history = free_history if free_history is not None else (pd.read_csv(FREE_HISTORY_PATH) if FREE_HISTORY_PATH.exists() else pd.DataFrame())
    free_current = free_current if free_current is not None else (pd.read_csv(FREE_CURRENT_PATH) if FREE_CURRENT_PATH.exists() else pd.DataFrame())
    valuation_bands = valuation_bands if valuation_bands is not None else (pd.read_csv(BANDS_PATH) if BANDS_PATH.exists() else pd.DataFrame())
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    free_layer_available = not free_history.empty
    rows: list[dict[str, object]] = []

    for _, pair in working.iterrows():
        company_a = _text(pair.get("company_a"))
        company_b = _text(pair.get("company_b"))
        fund_a = _fundamental_row(fundamentals, company_a)
        fund_b = _fundamental_row(fundamentals, company_b)
        class_a = PEER_CLASS.get(company_a, "unclassified")
        class_b = PEER_CLASS.get(company_b, "unclassified")
        free_a, min_a, max_a, pit_a, stats_a = _free_valuation_status(free_history, valuation_bands, _text(pair.get("asset_a")))
        free_b, min_b, max_b, pit_b, stats_b = _free_valuation_status(free_history, valuation_bands, _text(pair.get("asset_b")))
        hist_a, hist_b = free_a, free_b
        if free_history.empty:
            hist_a, min_a, max_a, pit_a = _historical_market_multiple_status(history, company_a)
            hist_b, min_b, max_b, pit_b = _historical_market_multiple_status(history, company_b)
            stats_a, stats_b = {}, {}
        ps_a = _num(pair.get("ps_consensus_revenue_a"))
        ps_b = _num(pair.get("ps_consensus_revenue_b"))
        pe_a = _num(pair.get("pe_consensus_profit_a"))
        pe_b = _num(pair.get("pe_consensus_profit_b"))
        market_a = _text(pair.get("market_a"))
        market_b = _text(pair.get("market_b"))
        same_market = market_a == market_b and bool(market_a)
        warnings = [x for x in (_text(fund_a.get("operating_scope_warning")), _text(fund_b.get("operating_scope_warning"))) if x]
        historical_missing = hist_a.startswith("missing_") or hist_b.startswith("missing_")
        comparable_class = class_a == class_b
        current_ps_available = ps_a is not None and ps_b is not None and ps_a > 0 and ps_b > 0
        current_pe_available = pe_a is not None and pe_b is not None and pe_a > 0 and pe_b > 0
        pb_a = pb[pb["asset"].eq(_text(pair.get("asset_a")))] if not pb.empty and "asset" in pb.columns else pd.DataFrame()
        pb_b = pb[pb["asset"].eq(_text(pair.get("asset_b")))] if not pb.empty and "asset" in pb.columns else pd.DataFrame()
        pb_row_a = pb_a.iloc[0] if not pb_a.empty else pd.Series(dtype=object)
        pb_row_b = pb_b.iloc[0] if not pb_b.empty else pd.Series(dtype=object)

        if current_ps_available and historical_missing:
            method_status = "current_relative_ps_only_no_historical_multiple"
        elif current_ps_available and not historical_missing and free_layer_available:
            method_status = "current_relative_ps_plus_free_historical_valuation_bands"
        elif current_ps_available and not historical_missing:
            method_status = "current_relative_ps_with_historical_market_series_check_pending"
        else:
            method_status = "no_comparable_current_revenue_multiple"

        if comparable_class and not warnings:
            scope_status = "same_business_model_and_no_scope_warning"
        elif comparable_class:
            scope_status = "same_peer_class_but_consolidated_scope_warning"
        else:
            scope_status = "different_business_model_or_consolidated_scope"

        if historical_missing:
            readiness = "not_ready_missing_historical_multiple_evidence"
        elif not comparable_class:
            readiness = "not_ready_business_model_not_like_for_like"
        elif not same_market:
            readiness = "not_ready_market_scope_mismatch"
        elif not current_pe_available:
            readiness = "not_ready_profit_multiple_unstable_or_missing"
        else:
            readiness = "candidate_for_historical_peer_valuation_review"

        rows.append(
            {
                "dataset_id": "airline_valuation_peer_comparability",
                "as_of_date": _latest_date(fundamentals, history, working),
                "pair_id": _text(pair.get("pair_id")),
                "selection_bucket": _text(pair.get("selection_bucket")),
                "company_a": company_a,
                "asset_a": _text(pair.get("asset_a")),
                "company_b": company_b,
                "asset_b": _text(pair.get("asset_b")),
                "peer_class_a": class_a,
                "peer_class_b": class_b,
                "business_model_match_status": _model_match(class_a, class_b),
                "market_scope_a": market_a,
                "market_scope_b": market_b,
                "same_market_scope": same_market,
                "consolidated_scope_a": _scope_class(company_a, fund_a),
                "consolidated_scope_b": _scope_class(company_b, fund_b),
                "scope_comparability_status": scope_status,
                "operating_scope_warning_present": bool(warnings),
                "current_ps_a": ps_a,
                "current_ps_b": ps_b,
                "current_pe_a": pe_a,
                "current_pe_b": pe_b,
                "current_revenue_multiple_status": "available_current_relative_ps" if current_ps_available else "missing_current_relative_ps",
                "current_profit_multiple_status": "available_current_forward_pe" if current_pe_available else "one_or_both_profit_multiples_unstable_or_missing",
                "historical_pb_status_a": "dated_1y_pb_history_available" if _num(pb_row_a.get("pb_observation_count")) else "missing_dated_pb_history",
                "historical_pb_status_b": "dated_1y_pb_history_available" if _num(pb_row_b.get("pb_observation_count")) else "missing_dated_pb_history",
                "current_pb_a": _num(pb_row_a.get("current_pb")),
                "current_pb_b": _num(pb_row_b.get("current_pb")),
                "pb_median_1y_a": _num(pb_row_a.get("pb_median_1y")),
                "pb_median_1y_b": _num(pb_row_b.get("pb_median_1y")),
                "current_pb_percentile_1y_a": _num(pb_row_a.get("current_pb_percentile_1y")),
                "current_pb_percentile_1y_b": _num(pb_row_b.get("current_pb_percentile_1y")),
                "historical_market_multiple_status_a": hist_a,
                "historical_market_multiple_status_b": hist_b,
                "historical_period_min_a": min_a,
                "historical_period_max_a": max_a,
                "historical_period_min_b": min_b,
                "historical_period_max_b": max_b,
                "historical_pit_status_a": pit_a,
                "historical_pit_status_b": pit_b,
                "historical_pe_ttm_median_3y_a": stats_a.get("pe_ttm_median_3y"),
                "historical_pe_ttm_median_3y_b": stats_b.get("pe_ttm_median_3y"),
                "historical_pb_median_3y_a": stats_a.get("pb_median_3y"),
                "historical_pb_median_3y_b": stats_b.get("pb_median_3y"),
                "historical_ps_annual_median_3y_a": stats_a.get("ps_annual_period_end_median_3y"),
                "historical_ps_annual_median_3y_b": stats_b.get("ps_annual_period_end_median_3y"),
                "current_ps_percentile_3y_a": stats_a.get("ps_annual_period_end_current_percentile_3y"),
                "current_ps_percentile_3y_b": stats_b.get("ps_annual_period_end_current_percentile_3y"),
                "valuation_method_status": method_status,
                "valuation_target_readiness": readiness,
                "required_next_evidence": "Reconcile free-provider denominator semantics to announcement-aligned revenue/profit; use historical PE/PB bands and constructed annual-revenue PS as valuation diagnostics; separate LCC, network-carrier and multi-carrier scope; refresh 1H2026 actuals and consensus revisions before approving a target.",
                "source_quality": "derived_peer_comparability_valuation_gate",
                "source_paths": f"{FUNDAMENTALS_PATH};{HISTORY_PATH};{WORKING_PATH};{PB_PATH};{FREE_HISTORY_PATH};{FREE_CURRENT_PATH};{BANDS_PATH}",
                "retrieved_at": retrieved,
            }
        )

    result = pd.DataFrame(rows)
    return result


def fetch_airline_valuation_peer_comparability() -> pd.DataFrame:
    result = build_airline_valuation_peer_comparability()
    result.to_csv(OUTPUT_PATH, index=False)
    return result
