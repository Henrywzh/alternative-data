"""Compact thesis-input layer for the pre-1H2026 airline research bet.

This module does not scrape new sources and does not choose a long/short
direction.  It joins the V2 operating forecast to the existing public
consensus, revision, guidance/calendar and historical valuation artifacts,
while retaining explicit data-quality states such as ``thin_consensus`` and
``revision_not_confirmed``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR


WALK_FORWARD_PATH = NORMALIZED_DIR / "airline_walk_forward_model_v2.csv"
WALK_FORWARD_SUMMARY_PATH = NORMALIZED_DIR / "airline_walk_forward_model_v2_summary.csv"
CURRENT_FORECAST_PATH = NORMALIZED_DIR / "airline_walk_forward_model_v2_current_forecast.csv"
EXPECTATION_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
REVISION_PULSE_PATH = NORMALIZED_DIR / "airline_consensus_revision_pulse.csv"
REVISION_EVIDENCE_PATH = NORMALIZED_DIR / "airline_revision_evidence.csv"
GUIDANCE_PATH = NORMALIZED_DIR / "airline_guidance_coverage.csv"
VALUATION_PATH = NORMALIZED_DIR / "airline_historical_valuation_bands.csv"

OUTPUT_PATH = NORMALIZED_DIR / "airline_thesis_v2_input_coverage.csv"
FORECAST_OUTPUT_PATH = NORMALIZED_DIR / "airline_thesis_v2_pre_h1_forecast.csv"
PAIR_OUTPUT_PATH = NORMALIZED_DIR / "airline_thesis_v2_pair_readiness.csv"

COMPANIES = (
    "Cathay Pacific",
    "Air China",
    "China Southern Airlines",
    "China Eastern Airlines",
    "Hainan Airlines Holdings",
    "Spring Airlines",
    "Juneyao Airlines",
)
SELECTED_MARKET = {
    "Cathay Pacific": ("HK", "0293.HK"),
    "Air China": ("CN_A", "601111.SH"),
    "China Southern Airlines": ("CN_A", "600029.SH"),
    "China Eastern Airlines": ("CN_A", "600115.SH"),
    "Hainan Airlines Holdings": ("CN_A", "600221.SH"),
    "Spring Airlines": ("CN_A", "601021.SH"),
    "Juneyao Airlines": ("CN_A", "603885.SH"),
}

# These are research-monitor pairs.  The fields are intentionally leg_a and
# leg_b rather than long and short; the module must not pre-commit direction.
PAIR_DEFINITIONS = (
    ("Spring__Juneyao", "Spring Airlines", "Juneyao Airlines"),
    ("Spring__Southern", "Spring Airlines", "China Southern Airlines"),
    ("Spring__Eastern", "Spring Airlines", "China Eastern Airlines"),
    ("Spring__AirChina", "Spring Airlines", "Air China"),
    ("Spring__Hainan", "Spring Airlines", "Hainan Airlines Holdings"),
    ("Southern__Eastern", "China Southern Airlines", "China Eastern Airlines"),
)


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _date(value: object) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else pd.Timestamp(parsed).normalize()


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _select_expectation(expectation: pd.DataFrame, company: str) -> pd.Series:
    if expectation.empty or "company" not in expectation.columns:
        return pd.Series(dtype=object)
    market, ticker = SELECTED_MARKET[company]
    rows = expectation.loc[
        expectation["company"].eq(company)
        & expectation.get("market", pd.Series(index=expectation.index, dtype=object)).eq(market)
    ].copy()
    if rows.empty:
        rows = expectation.loc[expectation["company"].eq(company)].copy()
    if rows.empty:
        return pd.Series(dtype=object)
    if "market_ticker" in rows.columns:
        exact = rows.loc[rows["market_ticker"].astype(str).eq(ticker)]
        if not exact.empty:
            rows = exact
    sort_cols = [c for c in ("snapshot_date", "retrieved_at") if c in rows.columns]
    if sort_cols:
        rows = rows.sort_values(sort_cols, ascending=False, kind="stable")
    return rows.iloc[0]


def _revision_snapshot(
    evidence: pd.DataFrame,
    pulse: pd.DataFrame,
    company: str,
    as_of: pd.Timestamp,
) -> dict[str, object]:
    result: dict[str, object] = {
        "revision_evidence_count_180d": 0,
        "revision_up_count_180d": 0,
        "revision_down_count_180d": 0,
        "revision_net_direction_180d": "no_signal",
        "revision_latest_date": None,
        "revision_latest_metric": None,
        "revision_latest_direction": None,
        "revision_latest_evidence_type": None,
        "revision_history_status": "missing_public_revision_evidence",
        "revision_pulse_count_365d": 0,
        "revision_pulse_up_count_365d": 0,
        "revision_pulse_down_count_365d": 0,
        "revision_pulse_latest_date": None,
        "revision_pulse_latest_metric": None,
        "revision_pulse_latest_median_change_pct": None,
        "revision_confirmation_status": "revision_not_confirmed",
    }
    if not evidence.empty and "company" in evidence.columns:
        rows = evidence.loc[evidence["company"].eq(company)].copy()
        rows["date_parsed"] = pd.to_datetime(rows.get("evidence_date"), errors="coerce")
        # Rating events are evidence for sentiment, not estimate revisions.
        rows = rows.loc[~rows.get("evidence_type", pd.Series(index=rows.index, dtype=object)).astype(str).str.contains("rating", case=False, na=False)]
        recent = rows.loc[rows["date_parsed"].between(as_of - pd.Timedelta(days=180), as_of)].copy()
        if not recent.empty:
            result["revision_evidence_count_180d"] = int(len(recent))
            dated = recent.loc[~recent.get("evidence_type", pd.Series(index=recent.index, dtype=object)).astype(str).str.contains("vendor_revision_signal")]
            vendor = recent.loc[recent.get("evidence_type", pd.Series(index=recent.index, dtype=object)).astype(str).str.contains("vendor_revision_signal")]
            up = int(dated.get("direction", pd.Series(dtype=object)).astype(str).eq("up").sum())
            down = int(dated.get("direction", pd.Series(dtype=object)).astype(str).eq("down").sum())
            up += int(pd.to_numeric(vendor.get("signal_up_count", 0), errors="coerce").fillna(0).sum())
            down += int(pd.to_numeric(vendor.get("signal_down_count", 0), errors="coerce").fillna(0).sum())
            result["revision_up_count_180d"] = up
            result["revision_down_count_180d"] = down
            result["revision_net_direction_180d"] = "up" if up > down else "down" if down > up else "mixed_or_flat"
            latest = recent.sort_values("date_parsed", ascending=False).iloc[0]
            result["revision_latest_date"] = latest["date_parsed"].strftime("%Y-%m-%d")
            result["revision_latest_metric"] = latest.get("metric")
            result["revision_latest_direction"] = latest.get("direction")
            result["revision_latest_evidence_type"] = latest.get("evidence_type")
            result["revision_history_status"] = "dated_subset_not_complete"
    if not pulse.empty and "company" in pulse.columns:
        rows = pulse.loc[pulse["company"].eq(company)].copy()
        rows["date_parsed"] = pd.to_datetime(rows.get("event_date"), errors="coerce")
        recent = rows.loc[rows["date_parsed"].between(as_of - pd.Timedelta(days=365), as_of)].copy()
        if not recent.empty:
            result["revision_pulse_count_365d"] = int(len(recent))
            result["revision_pulse_up_count_365d"] = int(pd.to_numeric(recent.get("up_revision_count", 0), errors="coerce").fillna(0).sum())
            result["revision_pulse_down_count_365d"] = int(pd.to_numeric(recent.get("down_revision_count", 0), errors="coerce").fillna(0).sum())
            latest = recent.sort_values("date_parsed", ascending=False).iloc[0]
            result["revision_pulse_latest_date"] = latest["date_parsed"].strftime("%Y-%m-%d")
            result["revision_pulse_latest_metric"] = latest.get("estimate_metric")
            result["revision_pulse_latest_median_change_pct"] = _num(latest.get("median_change_pct"))
    if result["revision_evidence_count_180d"] or result["revision_pulse_count_365d"]:
        result["revision_confirmation_status"] = "partial_public_revision_signal"
    return result


def _guidance_snapshot(guidance: pd.DataFrame, company: str) -> dict[str, object]:
    if guidance.empty or "company" not in guidance.columns:
        return {"guidance_coverage_status": "missing_guidance_artifact"}
    rows = guidance.loc[guidance["company"].eq(company)].copy()
    if rows.empty:
        return {"guidance_coverage_status": "missing_company_guidance_row"}
    row = rows.sort_values("snapshot_date", ascending=False).iloc[0]
    fields = [
        "guidance_event_count", "warning_event_count", "formal_result_event_count",
        "latest_guidance_date", "latest_guidance_metric", "latest_guidance_value_min",
        "latest_guidance_value_max", "latest_guidance_native_unit", "latest_warning_date",
        "latest_warning_metric", "latest_warning_value_min", "latest_warning_value_max",
        "formal_report_status", "formal_report_scheduled_date", "formal_report_actual_disclosure_date",
        "guidance_coverage_status",
    ]
    return {
        (field if field.startswith("guidance_") else f"guidance_{field}"): row.get(field)
        for field in fields
    }


def _valuation_snapshot(valuation: pd.DataFrame, company: str) -> dict[str, object]:
    result: dict[str, object] = {"valuation_band_window": "3y"}
    if valuation.empty or "company" not in valuation.columns:
        result["valuation_band_status"] = "missing_historical_valuation_band"
        return result
    rows = valuation.loc[valuation["company"].eq(company) & valuation["window"].eq("3y")].copy()
    if rows.empty:
        result["valuation_band_status"] = "missing_3y_historical_valuation_band"
        return result
    for metric, prefix in (("pe_ttm", "pe"), ("ps_annual_period_end", "ps"), ("pb", "pb")):
        row = rows.loc[rows["metric"].eq(metric)]
        if row.empty:
            continue
        item = row.iloc[0]
        current = _num(item.get("current_value"))
        median = _num(item.get("median_value"))
        result[f"{prefix}_current"] = current
        result[f"{prefix}_median_3y"] = median
        result[f"{prefix}_p25_3y"] = _num(item.get("p25_value"))
        result[f"{prefix}_p75_3y"] = _num(item.get("p75_value"))
        result[f"{prefix}_current_percentile"] = _num(item.get("current_percentile_positive"))
        result[f"{prefix}_relative_to_median_pct"] = 100.0 * current / median - 100.0 if current is not None and median else None
        result[f"{prefix}_point_in_time_status"] = item.get("point_in_time_status")
        result[f"{prefix}_current_basis"] = item.get("current_basis")
    result["valuation_band_status"] = "available_with_denominator_caveat" if "historical" in str(rows.iloc[0].get("point_in_time_status", "")) else "available"
    return result


def _model_snapshot(current: pd.DataFrame, summary: pd.DataFrame, company: str) -> dict[str, object]:
    result: dict[str, object] = {
        "v2_current_forecast_status": "not_available_pre_h1_model" if company != "Cathay Pacific" else "benchmark_actual_reported_not_pre_h1_forecast",
        "v2_base_case_name": "walk_forward_fuel_nonfuel",
        "v2_base_case_status": "research_base_case_pending_review",
    }
    rows = current.loc[current["company"].eq(company) & current["period"].eq("H1")].copy() if not current.empty else pd.DataFrame()
    if rows.empty:
        return result
    result["v2_current_forecast_status"] = "available_pre_1H2026"
    for model in ("flat_ask", "flat_rpk", "walk_forward_yield_mix", "walk_forward_fuel_nonfuel", "walk_forward_integrated"):
        row = rows.loc[rows["model_name"].eq(model)]
        if row.empty:
            continue
        item = row.iloc[0]
        prefix = f"v2_{model}"
        for source, target in (
            ("predicted_revenue_native_mn", "revenue_native_mn"),
            ("predicted_operating_cost_native_mn", "operating_cost_native_mn"),
            ("predicted_operating_profit_proxy_native_mn", "operating_profit_proxy_native_mn"),
            ("ask_growth_pct", "ask_growth_pct"),
            ("rpk_growth_pct", "rpk_growth_pct"),
            ("fuel_growth_pct", "fuel_growth_pct"),
            ("predicted_revenue_per_rpk_growth_pct", "predicted_revenue_per_rpk_growth_pct"),
            ("predicted_fuel_contribution_pct", "predicted_fuel_contribution_pct"),
            ("predicted_nonfuel_ask_contribution_pct", "predicted_nonfuel_ask_contribution_pct"),
        ):
            result[f"{prefix}_{target}"] = item.get(source)
        if model == "walk_forward_fuel_nonfuel":
            result["v2_base_case_revenue_native_mn"] = item.get("predicted_revenue_native_mn")
            result["v2_base_case_operating_cost_native_mn"] = item.get("predicted_operating_cost_native_mn")
            result["v2_base_case_operating_profit_proxy_native_mn"] = item.get("predicted_operating_profit_proxy_native_mn")
            result["v2_base_case_prior_revenue_native_mn"] = item.get("prior_revenue_native_mn")
            result["v2_base_case_prior_operating_cost_native_mn"] = item.get("prior_operating_cost_native_mn")
            result["v2_base_case_forecast_cutoff_date"] = item.get("forecast_cutoff_date")
            result["v2_base_case_yield_model_fallback"] = item.get("yield_model_fallback")
            result["v2_base_case_cost_model_fallback"] = item.get("cost_model_fallback")
    h1_summary = summary.loc[summary["company"].eq(company) & summary["period"].eq("H1")].copy() if not summary.empty else pd.DataFrame()
    for model in ("flat_ask", "flat_rpk", "walk_forward_yield_mix", "walk_forward_fuel_nonfuel", "walk_forward_integrated"):
        row = h1_summary.loc[h1_summary["model_name"].eq(model)]
        if row.empty:
            continue
        item = row.iloc[0]
        prefix = f"v2_h1_{model}"
        result[f"{prefix}_revenue_mae_pct"] = item.get("revenue_mae_pct")
        result[f"{prefix}_operating_cost_mae_pct"] = item.get("operating_cost_mae_pct")
        result[f"{prefix}_operating_profit_proxy_mae_pct_of_prior_revenue"] = item.get("operating_profit_proxy_mae_pct_of_prior_revenue")
        result[f"{prefix}_historical_rows"] = item.get("historical_evaluated_rows")
    return result


def _consensus_snapshot(expectation: pd.DataFrame, company: str, model: dict[str, object]) -> dict[str, object]:
    row = _select_expectation(expectation, company)
    if row.empty:
        return {"consensus_status": "missing_consensus_row"}
    analyst_count = _num(row.get("fy2026_revenue_analyst_count"))
    source_quality = str(row.get("revenue_consensus_source_quality", ""))
    status = "thin_consensus" if analyst_count is None or analyst_count < 3 else "discovery_consensus_snapshot"
    if "fallback" in source_quality.lower() or "unstable" in str(row.get("consensus_valuation_quality", "")).lower():
        status = f"{status}_with_scope_or_profit_caveat"
    result = {
        "consensus_market": row.get("market"),
        "consensus_ticker": row.get("market_ticker"),
        "consensus_snapshot_date": row.get("snapshot_date"),
        "consensus_status": status,
        "consensus_revenue_avg_usd_mn": row.get("fy2026_revenue_avg_usd_mn"),
        "consensus_revenue_low_usd_mn": row.get("fy2026_revenue_low_usd_mn"),
        "consensus_revenue_high_usd_mn": row.get("fy2026_revenue_high_usd_mn"),
        "consensus_revenue_growth_pct": row.get("fy2026_revenue_growth_pct"),
        "consensus_revenue_analyst_count": analyst_count,
        "consensus_revenue_source_quality": row.get("revenue_consensus_source_quality"),
        "consensus_revenue_scope": row.get("revenue_consensus_scope"),
        "consensus_profit_avg_usd_mn": row.get("fy2026_net_profit_avg_usd_mn"),
        "consensus_profit_low_usd_mn": row.get("fy2026_net_profit_low_usd_mn"),
        "consensus_profit_high_usd_mn": row.get("fy2026_net_profit_high_usd_mn"),
        "consensus_profit_range_crosses_zero": row.get("fy2026_profit_range_crosses_zero"),
        "consensus_valuation_quality": row.get("consensus_valuation_quality"),
        "consensus_forward_pe": row.get("consensus_forward_pe"),
        "consensus_target_price_upside_pct": row.get("target_price_upside_pct"),
        "consensus_note": row.get("source_note"),
    }
    prior_h1 = _num(model.get("v2_base_case_prior_revenue_native_mn"))
    growth = _num(row.get("fy2026_revenue_growth_pct"))
    # This is a clearly labelled annual-growth-scaled H1 proxy, not an H1
    # broker estimate. It is useful only as a rough market-expectation anchor.
    result["h1_consensus_revenue_annual_growth_scaled_proxy_native_mn"] = prior_h1 * (1.0 + growth / 100.0) if prior_h1 is not None and growth is not None else None
    base_h1 = _num(model.get("v2_base_case_revenue_native_mn"))
    proxy = _num(result["h1_consensus_revenue_annual_growth_scaled_proxy_native_mn"])
    result["h1_base_case_revenue_vs_annual_consensus_scaled_proxy_pct"] = 100.0 * base_h1 / proxy - 100.0 if base_h1 is not None and proxy else None
    result["h1_consensus_proxy_method"] = "prior_H1_revenue_scaled_by_FY2026_consensus_revenue_growth_not_direct_H1_consensus"
    return result


def _company_row(
    company: str,
    *,
    expectation: pd.DataFrame,
    revisions: pd.DataFrame,
    pulse: pd.DataFrame,
    guidance: pd.DataFrame,
    valuation: pd.DataFrame,
    current: pd.DataFrame,
    summary: pd.DataFrame,
    as_of: pd.Timestamp,
    retrieved_at: str,
) -> dict[str, object]:
    model = _model_snapshot(current, summary, company)
    result: dict[str, object] = {
        "dataset_id": "airline_thesis_v2_input_coverage",
        "company": company,
        "market_ticker": SELECTED_MARKET[company][1],
        "market": SELECTED_MARKET[company][0],
        "as_of_date": as_of.strftime("%Y-%m-%d"),
        "source_quality": "joined_existing_free_layers_no_new_scrape",
        "source_note": "Non-directional pre-1H2026 thesis input layer. Consensus is a discovery snapshot; public revisions are not a complete broker vintage; historical valuation bands retain denominator/PIT caveats.",
        "retrieved_at": retrieved_at,
    }
    result.update(model)
    result.update(_consensus_snapshot(expectation, company, model))
    result.update(_revision_snapshot(revisions, pulse, company, as_of))
    result.update(_guidance_snapshot(guidance, company))
    result.update(_valuation_snapshot(valuation, company))
    return result


def _pair_readiness(coverage: pd.DataFrame, retrieved_at: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    indexed = coverage.set_index("company") if not coverage.empty else pd.DataFrame()
    for pair_id, leg_a, leg_b in PAIR_DEFINITIONS:
        a = indexed.loc[leg_a] if leg_a in indexed.index else pd.Series(dtype=object)
        b = indexed.loc[leg_b] if leg_b in indexed.index else pd.Series(dtype=object)
        blockers: list[str] = []
        for leg, item in ((leg_a, a), (leg_b, b)):
            if item.empty or item.get("v2_current_forecast_status") not in {"available_pre_1H2026", "benchmark_actual_reported_not_pre_h1_forecast"}:
                blockers.append(f"{leg}:missing_v2_forecast")
            if str(item.get("consensus_status", "")).startswith("thin"):
                blockers.append(f"{leg}:thin_consensus")
            if item.empty or item.get("revision_confirmation_status") == "revision_not_confirmed":
                blockers.append(f"{leg}:revision_not_confirmed")
            if item.empty or str(item.get("valuation_band_status", "")).startswith("missing"):
                blockers.append(f"{leg}:valuation_band_missing")
            if item.empty or pd.isna(item.get("guidance_formal_report_scheduled_date")):
                blockers.append(f"{leg}:report_date_missing")
        a_rev = _num(a.get("v2_base_case_revenue_native_mn"))
        b_rev = _num(b.get("v2_base_case_revenue_native_mn"))
        a_profit = _num(a.get("v2_base_case_operating_profit_proxy_native_mn"))
        b_profit = _num(b.get("v2_base_case_operating_profit_proxy_native_mn"))
        a_prior = _num(a.get("v2_base_case_prior_revenue_native_mn"))
        b_prior = _num(b.get("v2_base_case_prior_revenue_native_mn"))
        a_growth = 100.0 * a_rev / a_prior - 100.0 if a_rev is not None and a_prior else None
        b_growth = 100.0 * b_rev / b_prior - 100.0 if b_rev is not None and b_prior else None
        a_margin = 100.0 * a_profit / a_rev if a_profit is not None and a_rev else None
        b_margin = 100.0 * b_profit / b_rev if b_profit is not None and b_rev else None
        rows.append(
            {
                "dataset_id": "airline_thesis_v2_pair_readiness",
                "pair_id": pair_id,
                "leg_a": leg_a,
                "leg_b": leg_b,
                "direction_status": "not_selected_by_v2",
                "leg_a_v2_base_case_revenue_growth_pct": a_growth,
                "leg_b_v2_base_case_revenue_growth_pct": b_growth,
                "v2_base_case_revenue_growth_spread_a_minus_b_pp": a_growth - b_growth if a_growth is not None and b_growth is not None else None,
                "leg_a_v2_base_case_operating_margin_pct": a_margin,
                "leg_b_v2_base_case_operating_margin_pct": b_margin,
                "v2_base_case_operating_margin_spread_a_minus_b_pp": a_margin - b_margin if a_margin is not None and b_margin is not None else None,
                "leg_a_consensus_revenue_growth_pct": _num(a.get("consensus_revenue_growth_pct")),
                "leg_b_consensus_revenue_growth_pct": _num(b.get("consensus_revenue_growth_pct")),
                "consensus_revenue_growth_spread_a_minus_b_pp": _num(a.get("consensus_revenue_growth_pct")) - _num(b.get("consensus_revenue_growth_pct")) if _num(a.get("consensus_revenue_growth_pct")) is not None and _num(b.get("consensus_revenue_growth_pct")) is not None else None,
                "leg_a_revision_status": a.get("revision_confirmation_status"),
                "leg_b_revision_status": b.get("revision_confirmation_status"),
                "leg_a_revision_net_direction": a.get("revision_net_direction_180d"),
                "leg_b_revision_net_direction": b.get("revision_net_direction_180d"),
                "leg_a_ps_current_percentile": _num(a.get("ps_current_percentile")),
                "leg_b_ps_current_percentile": _num(b.get("ps_current_percentile")),
                "ps_percentile_gap_a_minus_b": _num(a.get("ps_current_percentile")) - _num(b.get("ps_current_percentile")) if _num(a.get("ps_current_percentile")) is not None and _num(b.get("ps_current_percentile")) is not None else None,
                "pair_data_readiness_status": "partial_monitor" if blockers else "research_ready_pending_direction",
                "blocking_items": ";".join(blockers) if blockers else "none",
                "source_quality": "non_directional_joined_pair_gate",
                "source_note": "A/B legs are symmetric research labels, not long/short assignments. Direction still requires variant perception, valuation reconciliation, factor residual test and risk review.",
                "retrieved_at": retrieved_at,
            }
        )
    return pd.DataFrame(rows)


def build_airline_thesis_v2_inputs(*, as_of_date: object | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    as_of = _date(as_of_date) or pd.Timestamp(datetime.now(timezone.utc).date())
    retrieved_at = datetime.now(timezone.utc).isoformat()
    expectation = _read(EXPECTATION_PATH)
    revisions = _read(REVISION_EVIDENCE_PATH)
    pulse = _read(REVISION_PULSE_PATH)
    guidance = _read(GUIDANCE_PATH)
    valuation = _read(VALUATION_PATH)
    current = _read(CURRENT_FORECAST_PATH)
    summary = _read(WALK_FORWARD_SUMMARY_PATH)
    coverage = pd.DataFrame(
        [
            _company_row(
                company,
                expectation=expectation,
                revisions=revisions,
                pulse=pulse,
                guidance=guidance,
                valuation=valuation,
                current=current,
                summary=summary,
                as_of=as_of,
                retrieved_at=retrieved_at,
            )
            for company in COMPANIES
        ]
    )
    forecast = current.copy()
    if not forecast.empty:
        forecast = forecast.merge(coverage, on="company", how="left", suffixes=("", "_coverage"))
        forecast["dataset_id"] = "airline_thesis_v2_pre_h1_forecast"
        forecast["source_quality"] = "v2_forecast_plus_existing_market_layers"
        forecast["source_note"] = "H1 2026 pre-interim forecast alternatives; annual consensus fields are context, not direct H1 consensus. No direction selected."
    pairs = _pair_readiness(coverage, retrieved_at)
    coverage.to_csv(OUTPUT_PATH, index=False)
    forecast.to_csv(FORECAST_OUTPUT_PATH, index=False)
    pairs.to_csv(PAIR_OUTPUT_PATH, index=False)
    return coverage, forecast, pairs


def fetch_airline_thesis_v2_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return build_airline_thesis_v2_inputs()


if __name__ == "__main__":
    coverage, forecast, pairs = fetch_airline_thesis_v2_inputs()
    print(f"Built airline thesis v2 inputs: coverage={len(coverage)}, forecast={len(forecast)}, pairs={len(pairs)}")
