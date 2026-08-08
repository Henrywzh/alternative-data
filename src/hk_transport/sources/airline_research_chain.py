"""Auditable revenue-to-expectations chain for airline thesis preparation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


BRIDGE_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
READINESS_PATH = NORMALIZED_DIR / "airline_pair_readiness.csv"
RISK_PATH = NORMALIZED_DIR / "airline_market_risk_metrics.csv"
REVISION_PATH = NORMALIZED_DIR / "airline_revision_coverage.csv"
CONSENSUS_DISPERSION_PATH = NORMALIZED_DIR / "airline_consensus_dispersion.csv"
CONSENSUS_DISPERSION_ALL_PATH = NORMALIZED_DIR / "airline_consensus_dispersion_all.csv"
FUEL_PATH = NORMALIZED_DIR / "airline_fuel_sensitivity_scenarios.csv"
NEWS_PATH = NORMALIZED_DIR / "airline_news_events.csv"
EVENT_PATH = NORMALIZED_DIR / "airline_event_timeline.csv"
DRIVERS_PATH = NORMALIZED_DIR / "airline_earnings_driver_comparability.csv"
ELIGIBILITY_PATH = NORMALIZED_DIR / "airline_short_eligibility.csv"
FORECAST_PATH = NORMALIZED_DIR / "airline_company_financial_forecast_bridge.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_research_chain.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "snapshot_date",
    "financial_period", "chain_stage", "canonical_metric", "value_numeric",
    "value_text", "unit", "native_currency", "as_of_date", "source_field",
    "source_quality", "source_note", "retrieved_at",
]


METRICS = (
    ("supply", "ask_yoy_pct", "h1_ask_yoy_pct", "ASK YoY", "percentage", "numeric"),
    ("supply", "latest_report_ask_mn_seat_km", "latest_report_ask_mn_seat_km", "latest reported ASK", "million seat-km", "numeric"),
    ("supply", "passenger_capacity_lf_change_pp", "h1_passenger_lf_change_pp", "passenger LF change", "percentage points", "numeric"),
    ("demand", "rpk_yoy_pct", "h1_rpk_yoy_pct", "RPK YoY", "percentage", "numeric"),
    ("demand", "latest_report_rpk_mn_passenger_km", "latest_report_rpk_mn_passenger_km", "latest reported RPK", "million passenger-km", "numeric"),
    ("demand", "latest_report_passenger_load_factor_pct", "latest_report_passenger_load_factor_pct", "latest reported passenger load factor", "percentage", "numeric"),
    ("demand", "passengers_yoy_pct", "h1_passengers_yoy_pct", "passengers YoY", "percentage", "numeric"),
    ("demand", "cargo_tonnes_yoy_pct", "h1_cargo_tonnes_yoy_pct", "cargo tonnes YoY", "percentage", "numeric"),
    ("revenue", "latest_report_revenue_native_mn", "latest_report_revenue_native_mn", "latest reported revenue", "native million", "numeric"),
    ("revenue", "latest_report_passenger_revenue_native_mn", "latest_report_passenger_revenue_native_mn", "latest reported passenger-related revenue", "native million", "numeric"),
    ("revenue", "latest_report_passenger_yield_native", "latest_report_passenger_yield_native", "latest reported passenger yield", "native currency/RPK", "numeric"),
    ("revenue", "latest_report_rask_native", "latest_report_rask_native", "latest reported/derived RASK proxy", "native currency/ASK", "numeric"),
    ("revenue", "fy2026_revenue_consensus_avg_usd_mn", "fy2026_revenue_avg_usd_mn", "FY2026 revenue consensus", "USD million", "numeric"),
    ("revenue", "fy2026_revenue_growth_vs_latest_actual_pct", "fy2026_revenue_growth_pct", "FY2026 revenue growth", "percentage", "numeric"),
    ("cost", "latest_report_operating_cost_native_mn", "latest_report_operating_cost_native_mn", "latest reported operating cost", "native million", "numeric"),
    ("cost", "latest_report_fuel_cost_native_mn", "latest_report_fuel_cost_native_mn", "latest reported fuel cost", "native million", "numeric"),
    ("cost", "latest_report_fuel_hedge_native_mn", "latest_report_fuel_hedge_native_mn", "latest reported fuel-hedge gain/loss or fair-value change", "native million", "numeric"),
    ("cost", "latest_report_cask_native", "latest_report_cask_native", "latest reported/derived CASK", "native currency/ASK", "numeric"),
    ("cost", "fuel_cost_share_pct", "latest_report_fuel_cost_share_pct", "fuel cost share", "percentage", "numeric"),
    ("cost", "jet_fuel_spot_usd_per_gallon", "jet_fuel_spot_usd_per_gallon", "EIA jet-fuel benchmark", "USD/gallon", "numeric"),
    ("cost", "brent_spot_usd_per_barrel", "brent_spot_usd_per_barrel", "EIA Brent benchmark", "USD/barrel", "numeric"),
    ("earnings", "latest_report_profit_native_mn", "latest_report_attributable_profit_native_mn", "latest reported attributable profit", "native million", "numeric"),
    ("risk", "latest_report_cash_and_cash_equivalents_native_mn", "latest_report_cash_and_cash_equivalents_native_mn", "latest reported cash and cash equivalents", "native million", "numeric"),
    ("risk", "latest_report_total_liabilities_native_mn", "latest_report_total_liabilities_native_mn", "latest reported total liabilities", "native million", "numeric"),
    ("risk", "latest_report_liabilities_to_assets_pct", "latest_report_liabilities_to_assets_pct", "latest reported/derived liabilities to assets", "percentage", "numeric"),
    ("risk", "latest_report_interest_bearing_debt_native_mn", "latest_report_interest_bearing_debt_native_mn", "latest reported interest-bearing debt", "native million", "numeric"),
    ("risk", "latest_report_capex_cash_paid_native_mn", "latest_report_capex_cash_paid_native_mn", "latest reported cash capex", "native million", "numeric"),
    ("risk", "latest_report_net_borrowings_native_mn", "latest_report_net_borrowings_native_mn", "latest reported net borrowings", "native million", "numeric"),
    ("risk", "latest_report_available_unrestricted_liquidity_native_mn", "latest_report_available_unrestricted_liquidity_native_mn", "latest reported available unrestricted liquidity", "native million", "numeric"),
    ("earnings", "fy2026_profit_consensus_avg_usd_mn", "fy2026_net_profit_avg_usd_mn", "FY2026 profit consensus", "USD million", "numeric"),
    ("earnings", "fy2026_consensus_net_margin_pct", "fy2026_consensus_net_margin_pct", "FY2026 consensus net margin", "percentage", "numeric"),
    ("expectations", "market_cap_usd_mn", "market_cap_usd_mn", "market capitalization", "USD million", "numeric"),
    ("expectations", "market_cap_to_consensus_revenue_usd", "market_cap_to_consensus_revenue_usd", "market cap / consensus revenue", "multiple", "numeric"),
    ("expectations", "consensus_valuation_quality", "consensus_valuation_quality", "valuation quality guard", None, "text"),
    ("expectations", "revision_evidence_band", None, "revision evidence band", None, "readiness"),
    ("expectations", "unified_estimate_revision_count", None, "dated estimate revision count", "events", "numeric"),
    ("expectations", "unified_up_revision_count", None, "dated upward revision count", "events", "numeric"),
    ("expectations", "unified_down_revision_count", None, "dated downward revision count", "events", "numeric"),
    ("expectations", "unified_latest_estimate_revision_date", None, "latest dated estimate revision", None, "readiness"),
    ("expectations", "yahoo_eps_revision_up_30d", "yahoo_eps_revision_up_30d", "Yahoo EPS upward-revision signal (30d)", "analyst-count signal", "numeric"),
    ("expectations", "yahoo_eps_revision_down_30d", "yahoo_eps_revision_down_30d", "Yahoo EPS downward-revision signal (30d)", "analyst-count signal", "numeric"),
    ("risk", "latest_discovery_debt_to_assets_pct", "latest_discovery_debt_to_assets_pct", "latest provider debt-to-assets ratio", "percentage", "numeric"),
    ("catalyst", "formal_report_status", "formal_report_status", "formal report status", None, "text"),
    ("catalyst", "formal_report_scheduled_date", "formal_report_scheduled_date", "formal report scheduled date", None, "text"),
    ("catalyst", "latest_event_type", "latest_event_type", "latest event type", None, "text"),
    ("catalyst", "latest_event_date", "latest_event_date", "latest event date", None, "text"),
    ("catalyst", "latest_event_metric", "latest_event_metric", "latest event metric", None, "text"),
    ("catalyst", "latest_event_value_min", "latest_event_value_min", "latest event lower bound", "native unit", "numeric"),
    ("catalyst", "latest_event_value_max", "latest_event_value_max", "latest event upper bound", "native unit", "numeric"),
    ("catalyst", "latest_event_native_unit", "latest_event_native_unit", "latest event unit", None, "text"),
    ("catalyst", "latest_event_source_url", "latest_event_source_url", "latest event source", None, "text"),
)

RISK_METRICS = (
    ("beta_to_benchmark", "beta to benchmark", "multiple", "numeric"),
    ("annualized_volatility_pct", "annualized volatility", "percentage", "numeric"),
    ("max_drawdown_pct", "maximum drawdown", "percentage", "numeric"),
    ("median_daily_turnover_usd_mn_60d", "median 60-day USD turnover", "USD million/day", "numeric"),
    ("borrow_data_available", "borrow data available", None, "text"),
)

# Supplemental issuer-period drivers that are already present in the
# comparability layer but are not represented by the expectation bridge's
# passenger-led latest-report fields.  These are joined at each company's
# latest comparable financial period; missing issuer disclosures stay missing.
LATEST_DRIVER_METRICS = (
    ("cargo_tonnes", "demand", "latest_report_cargo_tonnes"),
    ("cargo_load_factor_pct", "demand", "latest_report_cargo_load_factor_pct"),
    ("cargo_revenue", "revenue", "latest_report_cargo_revenue_native_mn"),
    ("cargo_yield", "revenue", "latest_report_cargo_yield_native"),
    ("operating_cash_flow", "earnings", "latest_report_operating_cash_flow_native_mn"),
    ("fuel_cost_per_ask", "cost", "latest_report_fuel_cost_per_ask_native"),
    ("cost_per_atk_ex_fuel", "cost", "latest_report_cost_per_atk_ex_fuel_native"),
    ("fuel_intensity", "cost", "latest_report_fuel_intensity_native"),
    ("fuel_hedging_loss_gain", "cost", "latest_report_fuel_hedging_loss_gain_native_mn"),
    ("fuel_hedge_fair_value_change", "cost", "latest_report_fuel_hedge_fair_value_change_native_mn"),
    ("fuel_sensitivity_5pct_cost_abs", "cost", "latest_report_fuel_sensitivity_5pct_cost_abs_native_mn"),
    ("fuel_sensitivity_5pct_profit_up", "earnings", "latest_report_fuel_sensitivity_5pct_profit_up_native_mn"),
    ("fuel_sensitivity_5pct_profit_down", "earnings", "latest_report_fuel_sensitivity_5pct_profit_down_native_mn"),
    ("fleet_total", "supply", "latest_report_fleet_total"),
    ("daily_utilization", "supply", "latest_report_daily_utilization"),
)

EXPECTATION_ALIGNMENT_METRICS = (
    ("hk_profit_consensus_usd_mn", "hk_profit_avg_usd_mn", "USD million", "numeric"),
    ("a_profit_consensus_usd_mn", "a_profit_avg_usd_mn", "USD million", "numeric"),
    ("profit_gap_a_minus_hk_usd_mn", "profit_gap_a_minus_hk_usd_mn", "USD million", "numeric"),
    ("profit_sign_disagreement_hk_vs_a", "profit_sign_disagreement_hk_vs_a", None, "text"),
    ("hk_profit_range_crosses_zero", "hk_profit_range_crosses_zero", None, "text"),
    ("a_profit_range_crosses_zero", "a_profit_range_crosses_zero", None, "text"),
    ("hk_profit_latest_observation_date", "hk_profit_latest_observation_date", None, "text"),
    ("a_profit_latest_observation_date", "a_profit_latest_observation_date", None, "text"),
    ("latest_h1_warning_date", "latest_h1_warning_date", None, "text"),
    ("hk_profit_forecast_pre_warning", "hk_profit_forecast_pre_warning", None, "text"),
    ("a_profit_forecast_pre_warning", "a_profit_forecast_pre_warning", None, "text"),
    ("forecast_warning_alignment", "forecast_warning_alignment", None, "text"),
)


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def build_airline_research_chain(
    *,
    bridge: pd.DataFrame | None = None,
    readiness: pd.DataFrame | None = None,
    risk_metrics: pd.DataFrame | None = None,
    fuel_sensitivity: pd.DataFrame | None = None,
    news_events: pd.DataFrame | None = None,
    event_timeline: pd.DataFrame | None = None,
    earnings_drivers: pd.DataFrame | None = None,
    revision_coverage: pd.DataFrame | None = None,
    short_eligibility: pd.DataFrame | None = None,
    consensus_dispersion: pd.DataFrame | None = None,
    consensus_dispersion_all: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
    financial_forecast: pd.DataFrame | None = None,
) -> pd.DataFrame:
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    readiness = readiness if readiness is not None else pd.read_csv(READINESS_PATH)
    risk_metrics = risk_metrics if risk_metrics is not None else pd.read_csv(RISK_PATH)
    fuel_sensitivity = fuel_sensitivity if fuel_sensitivity is not None else pd.read_csv(FUEL_PATH)
    news_events = news_events if news_events is not None else pd.read_csv(NEWS_PATH)
    event_timeline = event_timeline if event_timeline is not None else pd.read_csv(EVENT_PATH)
    earnings_drivers = earnings_drivers if earnings_drivers is not None else pd.read_csv(DRIVERS_PATH)
    revision_coverage = revision_coverage if revision_coverage is not None else pd.read_csv(REVISION_PATH)
    consensus_dispersion = consensus_dispersion if consensus_dispersion is not None else (
        pd.read_csv(CONSENSUS_DISPERSION_PATH) if CONSENSUS_DISPERSION_PATH.exists() else pd.DataFrame()
    )
    consensus_dispersion_all = consensus_dispersion_all if consensus_dispersion_all is not None else (
        pd.read_csv(CONSENSUS_DISPERSION_ALL_PATH) if CONSENSUS_DISPERSION_ALL_PATH.exists() else pd.DataFrame()
    )
    short_eligibility = short_eligibility if short_eligibility is not None else (
        pd.read_csv(ELIGIBILITY_PATH) if ELIGIBILITY_PATH.exists() else pd.DataFrame()
    )
    financial_forecast = financial_forecast if financial_forecast is not None else (
        pd.read_csv(FORECAST_PATH) if FORECAST_PATH.exists() else pd.DataFrame()
    )
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    selected = pd.concat(
        [bridge.loc[bridge["company"].eq("Cathay Pacific")], bridge.loc[bridge["market"].eq("CN_A")]],
        ignore_index=True,
    ).drop_duplicates("company")
    rows: list[dict[str, Any]] = []
    for _, company_row in selected.iterrows():
        company = str(company_row["company"])
        readiness_row = readiness.loc[readiness["company"].eq(company)]
        readiness_row = readiness_row.iloc[0] if not readiness_row.empty else pd.Series(dtype=object)
        revision_row = revision_coverage.loc[revision_coverage["company"].eq(company)]
        revision_row = revision_row.iloc[0] if not revision_row.empty else pd.Series(dtype=object)
        warning_rows = event_timeline.loc[
            event_timeline["company"].eq(company)
            & event_timeline["event_type"].eq("earnings_warning")
            & event_timeline["metric"].isin({
                "net_loss_attributable_to_shareholders",
                "profit_attributable_to_shareholders",
            })
        ].copy()
        if not warning_rows.empty:
            warning_rows["_event_date"] = pd.to_datetime(warning_rows["event_date"], errors="coerce")
            warning_row = warning_rows.sort_values("_event_date").iloc[-1]
        else:
            warning_row = pd.Series(dtype=object)
        dispersion_row = consensus_dispersion_all.loc[
            consensus_dispersion_all["company"].eq(company)
        ] if not consensus_dispersion_all.empty and "company" in consensus_dispersion_all.columns else pd.DataFrame()
        dispersion_row = dispersion_row.iloc[0] if not dispersion_row.empty else pd.Series(dtype=object)
        paired_dispersion_row = consensus_dispersion.loc[
            consensus_dispersion["company"].eq(company)
        ] if not consensus_dispersion.empty and "company" in consensus_dispersion.columns else pd.DataFrame()
        paired_dispersion_row = paired_dispersion_row.iloc[0] if not paired_dispersion_row.empty else pd.Series(dtype=object)
        risk_row = risk_metrics.loc[risk_metrics["company"].eq(company)]
        risk_row = risk_row.iloc[0] if not risk_row.empty else pd.Series(dtype=object)
        eligibility_row = (
            short_eligibility.loc[
                short_eligibility["company"].eq(company)
                & short_eligibility["market"].eq(company_row["market"])
            ].sort_values("eligibility_effective_date").iloc[-1]
            if not short_eligibility.empty
            and {"company", "market"}.issubset(short_eligibility.columns)
            and not short_eligibility.loc[
                short_eligibility["company"].eq(company)
                & short_eligibility["market"].eq(company_row["market"])
            ].empty
            else pd.Series(dtype=object)
        )
        for stage, canonical, field, label, unit, value_kind in METRICS:
            if field is None:
                value = readiness_row.get(canonical)
                source_field = f"airline_pair_readiness.{canonical}"
            else:
                value = company_row.get(field)
                source_field = f"airline_expectation_bridge.{field}"
            if value_kind == "numeric":
                numeric = _number(value)
                text_value = None
            else:
                numeric = None
                text_value = None if pd.isna(value) else str(value)
            if numeric is None and text_value is None:
                continue
            if field in {
                "latest_report_revenue_native_mn", "latest_report_passenger_revenue_native_mn",
                "latest_report_operating_cost_native_mn", "latest_report_fuel_cost_native_mn",
                "latest_report_attributable_profit_native_mn", "latest_report_ask_mn_seat_km",
                "latest_report_rpk_mn_passenger_km", "latest_report_passenger_load_factor_pct",
                "latest_report_passenger_yield_native", "latest_report_rask_native",
                "latest_report_cask_native", "latest_report_cash_and_cash_equivalents_native_mn",
                "latest_report_total_liabilities_native_mn", "latest_report_liabilities_to_assets_pct",
                "latest_report_interest_bearing_debt_native_mn", "latest_report_capex_cash_paid_native_mn",
                "latest_report_net_borrowings_native_mn", "latest_report_available_unrestricted_liquidity_native_mn",
            }:
                as_of = company_row.get("latest_report_announcement_date")
            elif field in {"jet_fuel_spot_usd_per_gallon", "brent_spot_usd_per_barrel"}:
                as_of = company_row.get("energy_observation_date")
            elif canonical == "unified_latest_estimate_revision_date":
                as_of = text_value
            elif canonical in {
                "latest_event_metric", "latest_event_value_min", "latest_event_value_max",
                "latest_event_native_unit", "latest_event_source_url",
            }:
                as_of = company_row.get("latest_event_date")
            elif canonical == "latest_discovery_debt_to_assets_pct":
                as_of = company_row.get("latest_discovery_debt_to_assets_period_end")
            elif field is None:
                as_of = readiness_row.get("snapshot_date")
            else:
                as_of = company_row.get("snapshot_date")
            bridge_note = (
                "Yahoo Finance 30-day EPS revision count from a current vendor snapshot; "
                "it is not a dated broker-vintage revision."
                if canonical in {"yahoo_eps_revision_up_30d", "yahoo_eps_revision_down_30d"}
                else (
                    "A-share provider debt-to-assets ratio retained as leverage context with its "
                    "period_end; the source lacks a complete issuer announcement-date PIT field."
                    if canonical == "latest_discovery_debt_to_assets_pct"
                    else (
                        "Derived chain row from the expectation bridge/readiness gate. "
                        "Retains source field and as-of date; this layer adds no new estimate."
                    )
                )
            )
            rows.append({
                "dataset_id": "airline_research_chain",
                "company": company,
                "ticker": company_row["market_ticker"],
                "market": company_row["market"],
                "snapshot_date": company_row["snapshot_date"],
                "financial_period": company_row["latest_financial_period"],
                "chain_stage": stage,
                "canonical_metric": canonical,
                "value_numeric": numeric,
                "value_text": text_value,
                "unit": unit,
                "native_currency": company_row.get("latest_financial_currency") if unit and unit.startswith("native") else None,
                "as_of_date": as_of,
                "source_field": source_field,
                "source_quality": "derived_join_with_source_lineage",
                "source_note": bridge_note,
                "retrieved_at": retrieved,
            })
        latest_driver_rows = earnings_drivers.loc[
            earnings_drivers["company"].eq(company)
            & earnings_drivers["statement_period"].eq(company_row["latest_financial_period"])
        ].copy()
        for source_metric, stage, canonical in LATEST_DRIVER_METRICS:
            driver_match = latest_driver_rows.loc[
                latest_driver_rows["canonical_metric"].eq(source_metric)
                & latest_driver_rows["value_native"].notna()
            ]
            if driver_match.empty:
                continue
            driver_row = driver_match.iloc[-1]
            value = _number(driver_row.get("value_native"))
            if value is None:
                continue
            information_date = driver_row.get("information_date")
            if pd.isna(information_date):
                information_date = driver_row.get("period_end")
            native_unit = driver_row.get("native_unit")
            native_unit = None if pd.isna(native_unit) else str(native_unit)
            native_currency = driver_row.get("native_currency")
            native_currency = None if pd.isna(native_currency) else str(native_currency)
            reported_or_derived = driver_row.get("reported_or_derived")
            source_page = driver_row.get("source_page")
            source_note = (
                "Latest comparable issuer-period driver joined from "
                f"airline_earnings_driver_comparability; statement_period="
                f"{driver_row.get('statement_period')}, reported_or_derived={reported_or_derived}. "
                f"Source page={source_page}; this chain row does not add a new estimate."
            )
            rows.append({
                "dataset_id": "airline_research_chain",
                "company": company,
                "ticker": company_row["market_ticker"],
                "market": company_row["market"],
                "snapshot_date": company_row["snapshot_date"],
                "financial_period": company_row["latest_financial_period"],
                "chain_stage": stage,
                "canonical_metric": canonical,
                "value_numeric": value,
                "value_text": None,
                "unit": native_unit,
                "native_currency": native_currency,
                "as_of_date": information_date,
                "source_field": f"airline_earnings_driver_comparability.{source_metric}",
                "source_quality": "derived_join_with_source_lineage",
                "source_note": source_note,
                "retrieved_at": retrieved,
            })
        ask_growth = _number(company_row.get("h1_ask_yoy_pct"))
        rpk_growth = _number(company_row.get("h1_rpk_yoy_pct"))
        if ask_growth is not None and rpk_growth is not None:
            rows.append({
                "dataset_id": "airline_research_chain",
                "company": company,
                "ticker": company_row["market_ticker"],
                "market": company_row["market"],
                "snapshot_date": company_row["snapshot_date"],
                "financial_period": company_row["latest_financial_period"],
                "chain_stage": "demand",
                "canonical_metric": "rpk_minus_ask_growth_gap_pp",
                "value_numeric": rpk_growth - ask_growth,
                "value_text": None,
                "unit": "percentage points",
                "native_currency": None,
                "as_of_date": company_row.get("snapshot_date"),
                "source_field": "airline_expectation_bridge.h1_rpk_yoy_pct - h1_ask_yoy_pct",
                "source_quality": "derived_join_with_source_lineage",
                "source_note": (
                    "Demand-versus-capacity growth gap: H1 RPK YoY minus H1 ASK YoY. "
                    "Positive values indicate traffic demand grew faster than capacity; "
                    "this is a diagnostic, not a fare/yield estimate."
                ),
                "retrieved_at": retrieved,
            })
        forecast_rows = financial_forecast.loc[
            financial_forecast["company"].eq(company)
        ] if not financial_forecast.empty and "company" in financial_forecast.columns else pd.DataFrame()
        if not forecast_rows.empty:
            forecast_metrics = (
                ("forecast_ask_mn_seat_km", "forecast_ask_mn_seat_km", "million seat-km", "numeric", None),
                ("forecast_rpk_mn_passenger_km", "forecast_rpk_mn_passenger_km", "million passenger-km", "numeric", None),
                ("forecast_load_factor_pct", "forecast_load_factor_pct", "percentage", "numeric", None),
                ("forecast_rask_proxy_rmb_per_ask", "forecast_rask_proxy_rmb_per_ask", "RMB/ASK", "numeric", "CNY"),
                ("forecast_cask_rmb_per_ask", "forecast_cask_rmb_per_ask", "RMB/ASK", "numeric", "CNY"),
                ("forecast_revenue_usd_mn", "forecast_revenue_usd_mn", "USD million", "numeric", None),
                ("forecast_operating_cost_usd_mn", "forecast_operating_cost_usd_mn", "USD million", "numeric", None),
                ("forecast_earnings_proxy_after_fuel_usd_mn", "earnings_proxy_after_fuel_usd_mn", "USD million", "numeric", None),
                ("forecast_revenue_gap_to_consensus_pct", "revenue_gap_to_consensus_pct", "percentage", "numeric", None),
                ("forecast_earnings_gap_to_consensus_pct", "earnings_gap_to_consensus_pct", "percentage", "numeric", None),
            )
            for _, forecast_row in forecast_rows.iterrows():
                scenario = str(forecast_row.get("scenario", "unknown"))
                for canonical_base, field, unit, value_kind, native_currency in forecast_metrics:
                    value = forecast_row.get(field)
                    numeric = _number(value) if value_kind == "numeric" else None
                    if numeric is None:
                        continue
                    rows.append({
                        "dataset_id": "airline_research_chain",
                        "company": company,
                        "ticker": company_row["market_ticker"],
                        "market": company_row["market"],
                        "snapshot_date": company_row["snapshot_date"],
                        "financial_period": company_row["latest_financial_period"],
                        "chain_stage": "forecast",
                        "canonical_metric": f"{scenario}_{canonical_base}",
                        "value_numeric": numeric,
                        "value_text": None,
                        "unit": unit,
                        "native_currency": native_currency,
                        "as_of_date": forecast_row.get("as_of_date"),
                        "source_field": f"airline_company_financial_forecast_bridge.{field}",
                        "source_quality": "derived_join_with_source_lineage",
                        "source_note": (
                            f"{scenario} case from the FY2026 pre-interim company financial forecast bridge. "
                            "Mechanical driver output, not issuer guidance, broker consensus or a trade recommendation. "
                            f"Forecast status={forecast_row.get('forecast_status')}; scope={forecast_row.get('entity_scope')}."
                        ),
                        "retrieved_at": retrieved,
                    })
        public_report_metrics = (
            ("public_report_evidence_row_count", "rows"),
            ("public_report_dated_row_count", "rows"),
            ("public_report_eps_up_marker_count", "markers"),
            ("public_report_eps_down_marker_count", "markers"),
            ("public_report_net_profit_up_marker_count", "markers"),
            ("public_report_net_profit_down_marker_count", "markers"),
        )
        for canonical, unit in public_report_metrics:
            value = revision_row.get(canonical)
            numeric = _number(value)
            if numeric is None:
                continue
            rows.append({
                "dataset_id": "airline_research_chain",
                "company": company,
                "ticker": company_row["market_ticker"],
                "market": company_row["market"],
                "snapshot_date": company_row["snapshot_date"],
                "financial_period": company_row["latest_financial_period"],
                "chain_stage": "expectations",
                "canonical_metric": canonical,
                "value_numeric": numeric,
                "value_text": None,
                "unit": unit,
                "native_currency": None,
                "as_of_date": revision_row.get("snapshot_date"),
                "source_field": f"airline_revision_coverage.{canonical}",
                "source_quality": "derived_join_with_source_lineage",
                "source_note": (
                    "10jqka public-report coverage metadata joined into the expectations chain. "
                    "Counts and up/down markers do not establish a complete prior numeric revision."
                ),
                "retrieved_at": retrieved,
            })
        if company_row.get("market") == "CN_A" and not warning_row.empty:
            annual_consensus = _number(company_row.get("fy2026_net_profit_avg_native_mn"))
            warning_low = _number(warning_row.get("value_min"))
            warning_high = _number(warning_row.get("value_max"))
            warning_mid = (
                (warning_low + warning_high) / 2.0
                if warning_low is not None and warning_high is not None
                else None
            )
            warning_date = warning_row.get("event_date")
            consensus_date = company_row.get("profit_consensus_as_of_date")
            if annual_consensus is not None and warning_low is not None and warning_high is not None:
                implied_h2 = {
                    "h1_warning_profit_low_native_mn": warning_low,
                    "h1_warning_profit_high_native_mn": warning_high,
                    "h1_warning_profit_mid_native_mn": warning_mid,
                    "fy2026_profit_consensus_avg_native_mn": annual_consensus,
                    "implied_h2_profit_at_h1_warning_low_native_mn": annual_consensus - warning_low,
                    "implied_h2_profit_at_h1_warning_high_native_mn": annual_consensus - warning_high,
                    "implied_h2_profit_at_h1_warning_mid_native_mn": annual_consensus - warning_mid,
                }
                for canonical, value in implied_h2.items():
                    rows.append({
                        "dataset_id": "airline_research_chain",
                        "company": company,
                        "ticker": company_row["market_ticker"],
                        "market": company_row["market"],
                        "snapshot_date": company_row["snapshot_date"],
                        "financial_period": company_row["latest_financial_period"],
                        "chain_stage": "expectations" if canonical.startswith("implied") or canonical.startswith("fy2026") else "earnings",
                        "canonical_metric": canonical,
                        "value_numeric": value,
                        "value_text": None,
                        "unit": "RMB million",
                        "native_currency": "CNY",
                        "as_of_date": consensus_date if canonical.startswith("implied") or canonical.startswith("fy2026") else warning_date,
                        "source_field": (
                            "airline_expectation_bridge.fy2026_net_profit_avg_native_mn"
                            if canonical.startswith("implied") or canonical.startswith("fy2026")
                            else "airline_event_timeline.value_min/value_max"
                        ),
                        "source_quality": "derived_join_with_source_lineage",
                        "source_note": (
                            "Mechanical expectations bridge: FY2026 A-share consensus minus the issuer's H1 "
                            "preliminary profit range. The implied H2 amount is not a forecast and excludes "
                            "seasonality, later estimate revisions, tax/one-offs and accounting changes; "
                            f"warning date={warning_date}, consensus as-of={consensus_date}."
                        ),
                        "retrieved_at": retrieved,
                    })
                driver_rows = earnings_drivers.loc[
                    earnings_drivers["company"].eq(company)
                    & earnings_drivers["canonical_metric"].eq("attributable_profit")
                    & earnings_drivers["statement_period"].isin({"FY2025", "1H2025"})
                ].copy()
                driver_values = {
                    str(row["statement_period"]): _number(row.get("value_native"))
                    for _, row in driver_rows.iterrows()
                }
                fy2025_profit = driver_values.get("FY2025")
                h1_2025_profit = driver_values.get("1H2025")
                if fy2025_profit is not None and h1_2025_profit is not None:
                    historical_h2 = fy2025_profit - h1_2025_profit
                    implied_mid = implied_h2["implied_h2_profit_at_h1_warning_mid_native_mn"]
                    for canonical, value, as_of_date, source_field in (
                        (
                            "historical_2h2025_profit_native_mn",
                            historical_h2,
                            driver_rows["information_date"].max(),
                            "airline_earnings_driver_comparability.attributable_profit",
                        ),
                        (
                            "implied_h2_mid_minus_historical_2h2025_native_mn",
                            implied_mid - historical_h2,
                            consensus_date,
                            "airline_expectation_bridge.implied_h2_profit_at_h1_warning_mid_native_mn",
                        ),
                    ):
                        rows.append({
                            "dataset_id": "airline_research_chain",
                            "company": company,
                            "ticker": company_row["market_ticker"],
                            "market": company_row["market"],
                            "snapshot_date": company_row["snapshot_date"],
                            "financial_period": company_row["latest_financial_period"],
                            "chain_stage": "expectations",
                            "canonical_metric": canonical,
                            "value_numeric": value,
                            "value_text": None,
                            "unit": "RMB million",
                            "native_currency": "CNY",
                            "as_of_date": as_of_date,
                            "source_field": source_field,
                            "source_quality": "derived_join_with_source_lineage",
                            "source_note": (
                                "Historical 2H2025 profit is derived as FY2025 attributable profit minus "
                                "1H2025 attributable profit from issuer-report driver rows. The difference "
                                "against warning-implied 2H consensus is a recovery-base diagnostic, not a forecast."
                            ),
                            "retrieved_at": retrieved,
                        })
        # A/H consensus alignment is only emitted for the three paired
        # share-class names.  It keeps the provider/vintage mismatch visible
        # instead of flattening it into a single "consensus" number.
        if not dispersion_row.empty and not paired_dispersion_row.empty:
            for canonical, field, unit, value_kind in EXPECTATION_ALIGNMENT_METRICS:
                source = paired_dispersion_row if field in paired_dispersion_row.index else dispersion_row
                value = source.get(field)
                if pd.isna(value):
                    continue
                if value_kind == "numeric":
                    numeric = _number(value)
                    text_value = None
                else:
                    numeric = None
                    text_value = str(value)
                if numeric is None and text_value is None:
                    continue
                metric_as_of = (
                    value if canonical in {"hk_profit_latest_observation_date", "a_profit_latest_observation_date", "latest_h1_warning_date"}
                    else source.get("snapshot_date")
                )
                source_dataset = (
                    "airline_consensus_dispersion"
                    if field in paired_dispersion_row.index
                    else "airline_consensus_dispersion_all"
                )
                rows.append({
                    "dataset_id": "airline_research_chain",
                    "company": company,
                    "ticker": company_row["market_ticker"],
                    "market": company_row["market"],
                    "snapshot_date": company_row["snapshot_date"],
                    "financial_period": company_row["latest_financial_period"],
                    "chain_stage": "expectations",
                    "canonical_metric": canonical,
                    "value_numeric": numeric,
                    "value_text": text_value,
                    "unit": unit,
                    "native_currency": None,
                    "as_of_date": metric_as_of,
                    "source_field": f"{source_dataset}.{field}",
                    "source_quality": "derived_join_with_source_lineage",
                    "source_note": (
                        "A/H FY2026 profit-consensus alignment joined into the research chain. "
                        "The two market estimates can differ by provider coverage, share class and vintage; "
                        "sign disagreement or warning alignment is a review flag, not a directional signal."
                    ),
                    "retrieved_at": retrieved,
                })
        for canonical in ("public_report_latest_date", "public_report_evidence_scope"):
            value = revision_row.get(canonical)
            if pd.isna(value):
                continue
            rows.append({
                "dataset_id": "airline_research_chain",
                "company": company,
                "ticker": company_row["market_ticker"],
                "market": company_row["market"],
                "snapshot_date": company_row["snapshot_date"],
                "financial_period": company_row["latest_financial_period"],
                "chain_stage": "expectations",
                "canonical_metric": canonical,
                "value_numeric": None,
                "value_text": str(value),
                "unit": None,
                "native_currency": None,
                "as_of_date": (
                    revision_row.get("public_report_latest_date")
                    if canonical == "public_report_latest_date"
                    else revision_row.get("snapshot_date")
                ),
                "source_field": f"airline_revision_coverage.{canonical}",
                "source_quality": "derived_join_with_source_lineage",
                "source_note": (
                    "Public-report date/scope metadata retained separately from numeric estimates; "
                    "revenue evidence remains page-snapshot-only."
                ),
                "retrieved_at": retrieved,
            })
        fuel_rows = fuel_sensitivity.loc[fuel_sensitivity["company"].eq(company)] if not fuel_sensitivity.empty else pd.DataFrame()
        for shock, label in ((5.0, "plus_5pct"), (-5.0, "minus_5pct")):
            scenario = fuel_rows.loc[fuel_rows["scenario_fuel_price_change_pct"].eq(shock)] if not fuel_rows.empty else pd.DataFrame()
            if scenario.empty:
                continue
            scenario = scenario.iloc[0]
            impact = _number(scenario.get("pre_tax_profit_impact_usd_mn"))
            if impact is not None:
                rows.append({
                    "dataset_id": "airline_research_chain",
                    "company": company,
                    "ticker": company_row["market_ticker"],
                    "market": company_row["market"],
                    "snapshot_date": company_row["snapshot_date"],
                    "financial_period": company_row["latest_financial_period"],
                    "chain_stage": "cost",
                    "canonical_metric": f"fuel_{label}_profit_impact_usd_mn",
                    "value_numeric": impact,
                    "value_text": None,
                    "unit": "USD million",
                    "native_currency": None,
                    "as_of_date": scenario.get("jet_fuel_observation_date"),
                    "source_field": "airline_fuel_sensitivity_scenarios.pre_tax_profit_impact_usd_mn",
                    "source_quality": "derived_join_with_source_lineage",
                    "source_note": (
                        f"Fuel-price scenario at {shock:g}% using {scenario.get('scenario_method')}; "
                        f"FX observation date {scenario.get('fx_observation_date')} and EIA observation date "
                        f"{scenario.get('jet_fuel_observation_date')}."
                    ),
                    "retrieved_at": retrieved,
                })
            for canonical, value, source_field in (
                (f"fuel_{label}_scenario_method", scenario.get("scenario_method"), "scenario_method"),
                (
                    f"fuel_{label}_issuer_sensitivity_available",
                    scenario.get("issuer_sensitivity_available"),
                    "issuer_sensitivity_available",
                ),
            ):
                if pd.isna(value):
                    continue
                rows.append({
                    "dataset_id": "airline_research_chain",
                    "company": company,
                    "ticker": company_row["market_ticker"],
                    "market": company_row["market"],
                    "snapshot_date": company_row["snapshot_date"],
                    "financial_period": company_row["latest_financial_period"],
                    "chain_stage": "cost",
                    "canonical_metric": canonical,
                    "value_numeric": None,
                    "value_text": str(value),
                    "unit": None,
                    "native_currency": None,
                    "as_of_date": scenario.get("jet_fuel_observation_date"),
                    "source_field": f"airline_fuel_sensitivity_scenarios.{source_field}",
                    "source_quality": "derived_join_with_source_lineage",
                    "source_note": (
                        "Fuel scenario metadata retained separately from the numeric impact; "
                        "mechanical cases exclude hedging, contracts, mix, pass-through and demand response."
                    ),
                    "retrieved_at": retrieved,
                })
        if not fuel_rows.empty:
            scenario = fuel_rows.iloc[0]
            fx_date = scenario.get("fx_observation_date")
            if not pd.isna(fx_date):
                rows.append({
                    "dataset_id": "airline_research_chain",
                    "company": company,
                    "ticker": company_row["market_ticker"],
                    "market": company_row["market"],
                    "snapshot_date": company_row["snapshot_date"],
                    "financial_period": company_row["latest_financial_period"],
                    "chain_stage": "cost",
                    "canonical_metric": "fuel_scenario_fx_observation_date",
                    "value_numeric": None,
                    "value_text": str(fx_date),
                    "unit": None,
                    "native_currency": None,
                    "as_of_date": str(fx_date),
                    "source_field": "airline_fuel_sensitivity_scenarios.fx_observation_date",
                    "source_quality": "derived_join_with_source_lineage",
                    "source_note": "Latest ECB FX observation used for the USD scenario translation; not a forward-FX assumption.",
                    "retrieved_at": retrieved,
                })
            surcharge_reference = scenario.get("surcharge_reference")
            surcharge_date = scenario.get("surcharge_effective_from")
            surcharge_url = scenario.get("surcharge_source_url")
            if not pd.isna(surcharge_reference):
                rows.append({
                    "dataset_id": "airline_research_chain",
                    "company": company,
                    "ticker": company_row["market_ticker"],
                    "market": company_row["market"],
                    "snapshot_date": company_row["snapshot_date"],
                    "financial_period": company_row["latest_financial_period"],
                    "chain_stage": "cost",
                    "canonical_metric": "fuel_surcharge_context",
                    "value_numeric": None,
                    "value_text": str(surcharge_reference),
                    "unit": None,
                    "native_currency": None,
                    "as_of_date": surcharge_date,
                    "source_field": "airline_fuel_sensitivity_scenarios.surcharge_reference",
                    "source_quality": "derived_join_with_source_lineage",
                    "source_note": (
                        "Official fuel-surcharge schedule context retained from the scenario layer; "
                        "route/policy-specific and not realized fuel-cost recovery. "
                        f"Source URL: {surcharge_url}."
                    ),
                    "retrieved_at": retrieved,
                })
        company_news = news_events.loc[news_events["company"].eq(company)] if not news_events.empty else pd.DataFrame()
        if not company_news.empty:
            company_news = company_news.copy()
            company_news["_published"] = pd.to_datetime(company_news["published_at"], errors="coerce")
            company_news = company_news.dropna(subset=["_published"]).sort_values("_published")
            if not company_news.empty:
                latest_news = company_news.iloc[-1]
                news_rows = (
                    ("news_event_count_in_window", float(len(company_news)), "published_at", "news article count in public window", "numeric"),
                    (
                        "news_direct_headline_count_in_window",
                        float(company_news["relevance_scope"].eq("direct_headline").sum()),
                        "news_events.relevance_scope",
                        "direct-headline count in public window",
                        "numeric",
                    ),
                    ("news_latest_published_at", latest_news.get("published_at"), "news_events.published_at", "latest news publication time", "text"),
                    ("news_latest_title", latest_news.get("news_title"), "news_events.news_title", "latest news title", "text"),
                    ("news_latest_source_url", latest_news.get("news_url"), "news_events.news_url", "latest news source URL", "text"),
                )
                for canonical, value, source_field, label, value_kind in news_rows:
                    if pd.isna(value):
                        continue
                    rows.append({
                        "dataset_id": "airline_research_chain",
                        "company": company,
                        "ticker": company_row["market_ticker"],
                        "market": company_row["market"],
                        "snapshot_date": company_row["snapshot_date"],
                        "financial_period": company_row["latest_financial_period"],
                        "chain_stage": "catalyst",
                        "canonical_metric": canonical,
                        "value_numeric": float(value) if value_kind == "numeric" else None,
                        "value_text": str(value) if value_kind == "text" else None,
                        "unit": "articles" if value_kind == "numeric" else None,
                        "native_currency": None,
                        "as_of_date": latest_news.get("published_at"),
                        "source_field": f"airline_news_events.{source_field.split('.', 1)[-1]}",
                        "source_quality": "derived_join_with_source_lineage",
                        "source_note": (
                            "Public Eastmoney/AkShare news-window metadata for catalyst discovery. "
                            "Keyword categories and relevance scope are not sentiment or alpha signals."
                        ),
                        "retrieved_at": retrieved,
                    })
        for canonical, label, unit, value_kind in RISK_METRICS:
            value = risk_row.get(canonical)
            if value_kind == "numeric":
                numeric = _number(value)
                text_value = None
            else:
                numeric = None
                text_value = None if pd.isna(value) else str(value)
            if numeric is None and text_value is None:
                continue
            rows.append({
                "dataset_id": "airline_research_chain",
                "company": company,
                "ticker": company_row["market_ticker"],
                "market": company_row["market"],
                "snapshot_date": company_row["snapshot_date"],
                "financial_period": company_row["latest_financial_period"],
                "chain_stage": "risk",
                "canonical_metric": canonical,
                "value_numeric": numeric,
                "value_text": text_value,
                "unit": unit,
                "native_currency": None,
                "as_of_date": risk_row.get("snapshot_date"),
                "source_field": f"airline_market_risk_metrics.{canonical}",
                "source_quality": "derived_join_with_source_lineage",
                "source_note": (
                    "Derived market-risk row from the free historical risk snapshot. Borrow availability remains explicit."
                ),
                "retrieved_at": retrieved,
            })
        if not eligibility_row.empty and pd.notna(eligibility_row.get("eligibility_status")):
            rows.append({
                "dataset_id": "airline_research_chain",
                "company": company,
                "ticker": company_row["market_ticker"],
                "market": company_row["market"],
                "snapshot_date": company_row["snapshot_date"],
                "financial_period": company_row["latest_financial_period"],
                "chain_stage": "risk",
                "canonical_metric": "short_eligibility_status",
                "value_numeric": None,
                "value_text": str(eligibility_row.get("eligibility_status")),
                "unit": None,
                "native_currency": None,
                "as_of_date": eligibility_row.get("eligibility_effective_date"),
                "source_field": "airline_short_eligibility.eligibility_status",
                "source_quality": "derived_join_with_source_lineage",
                "source_note": (
                    "Exchange eligibility evidence only: HKEX designated-list or SSE margin-detail presence. "
                    "It does not establish locatable borrow, borrow fee, recall risk or execution availability; "
                    "borrow_data_available remains false."
                ),
                "retrieved_at": retrieved,
            })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_research_chain() -> pd.DataFrame:
    result = build_airline_research_chain()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
