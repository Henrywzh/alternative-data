"""Derived company/share-class bridge for airline long/short research."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR, ROOT_DIR


MARKET_PATH = NORMALIZED_DIR / "airline_market_expectations_snapshot.csv"
OFFICIAL_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
CATHAY_FINANCIAL_PATH = NORMALIZED_DIR / "airline_financial_driver_snapshot.csv"
CATHAY_ANNUAL_FINANCIAL_PATH = NORMALIZED_DIR / "airline_cathay_annual_driver_snapshot.csv"
CATHAY_INTERIM_FINANCIAL_PATH = NORMALIZED_DIR / "airline_cathay_interim_driver_snapshot.csv"
TREND_PATH = NORMALIZED_DIR / "airline_sector_trend_snapshot.csv"
CATHAY_TREND_PATH = NORMALIZED_DIR / "airline_cathay_sector_trend_snapshot.csv"
EVENT_PATH = NORMALIZED_DIR / "airline_event_timeline.csv"
FILING_CALENDAR_PATH = NORMALIZED_DIR / "airline_filing_calendar.csv"
OFFICIAL_FILING_WATCH_PATH = NORMALIZED_DIR / "airline_official_filing_watch.csv"
SELL_SIDE_REVENUE_PATH = NORMALIZED_DIR / "airline_sell_side_revenue_forecasts.csv"
SELL_SIDE_REVENUE_REVISION_PATH = NORMALIZED_DIR / "airline_sell_side_revenue_revisions.csv"
HK_BROKER_FORECAST_PATH = NORMALIZED_DIR / "airline_hk_sell_side_forecasts.csv"
HK_BROKER_REVISION_PATH = NORMALIZED_DIR / "airline_hk_forecast_revisions.csv"
CONSENSUS_FRESHNESS_PATH = NORMALIZED_DIR / "airline_consensus_freshness.csv"
EM_CONSENSUS_PATH = NORMALIZED_DIR / "airline_consensus_em_snapshot.csv"
YAHOO_ANALYST_PATH = NORMALIZED_DIR / "airline_yahoo_analyst_snapshot.csv"
CNINFO_RATING_PATH = NORMALIZED_DIR / "airline_cninfo_rating_events.csv"
ASHARE_ACTUALS_PATH = NORMALIZED_DIR / "airline_financial_actuals_akshare_snapshot.csv"
ENERGY_PATH = NORMALIZED_DIR / "airline_energy_prices.parquet"

BRIDGE_COLUMNS = [
    "dataset_id", "company", "market_ticker", "market", "snapshot_date",
    "latest_price_native", "price_currency", "market_cap_usd_mn",
    "h1_ask_yoy_pct", "h1_rpk_yoy_pct", "h1_passengers_yoy_pct",
    "h1_passenger_lf_change_pp", "h1_cargo_tonnes_yoy_pct",
    "h1_freight_lf_change_pp", "latest_financial_period",
    "latest_financial_currency", "latest_report_announcement_date",
    "latest_report_revenue_native_mn", "latest_report_passenger_revenue_native_mn",
    "latest_report_cargo_revenue_native_mn", "latest_report_operating_cost_native_mn",
    "latest_report_fuel_cost_native_mn", "latest_report_fuel_cost_share_pct",
    "latest_report_fuel_hedge_native_mn", "latest_report_cask_native",
    "latest_report_cost_per_atk_native",
    "latest_report_ask_mn_seat_km", "latest_report_rpk_mn_passenger_km",
    "latest_report_passenger_load_factor_pct",
    "latest_report_rask_native", "latest_report_passenger_yield_native",
    "latest_report_attributable_profit_native_mn",
    "latest_report_operating_cash_flow_native_mn", "latest_report_cash_and_cash_equivalents_native_mn",
    "latest_report_total_liabilities_native_mn", "latest_report_liabilities_to_assets_pct",
    "latest_report_interest_bearing_debt_native_mn", "latest_report_capex_cash_paid_native_mn",
    "latest_report_net_borrowings_native_mn", "latest_report_available_unrestricted_liquidity_native_mn",
    "latest_discovery_debt_to_assets_pct",
    "latest_discovery_debt_to_assets_period_end", "latest_discovery_debt_to_assets_source_quality",
    "fy2026_revenue_avg_native_mn",
    "fy2026_revenue_low_native_mn", "fy2026_revenue_high_native_mn",
    "fy2026_revenue_avg_usd_mn", "fy2026_revenue_low_usd_mn",
    "fy2026_revenue_high_usd_mn",
    "fy2026_revenue_growth_pct", "fy2026_revenue_analyst_count",
    "revenue_consensus_source_quality", "revenue_consensus_source_layer",
    "revenue_consensus_scope",
    "revenue_consensus_as_of_date", "revenue_consensus_latest_observation_date",
    "revenue_consensus_age_days", "revenue_consensus_freshness_band",
    "revenue_consensus_revision_history_available",
    "latest_sell_side_revenue_native_mn", "latest_sell_side_revenue_report_date",
    "latest_sell_side_revenue_institution", "latest_sell_side_revenue_title",
    "latest_sell_side_revenue_revision_pct", "latest_sell_side_revenue_source_quality",
    "latest_sell_side_revenue_source_url",
    "sell_side_revenue_source_layer",
    "sell_side_revenue_as_of_date", "sell_side_revenue_age_days",
    "sell_side_revenue_freshness_band", "sell_side_revenue_revision_history_available",
    "hk_broker_observation_count", "hk_broker_latest_report_date",
    "hk_broker_latest_institution", "hk_broker_latest_rating",
    "hk_broker_latest_target_price_hkd", "hk_broker_forecast_currency",
    "hk_broker_target_price_currency", "hk_broker_latest_net_profit_usd_mn",
    "hk_broker_latest_eps_usd", "hk_broker_latest_target_price_usd",
    "hk_broker_forecast_fx_pair", "hk_broker_forecast_fx_observation_date",
    "hk_broker_target_price_fx_observation_date", "hk_broker_true_revision_count",
    "hk_broker_source_quality",
    "hk_broker_consensus_source_layer",
    "hk_broker_consensus_as_of_date", "hk_broker_consensus_age_days",
    "hk_broker_consensus_freshness_band", "hk_broker_consensus_revision_history_available",
    "a_share_consensus_em_snapshot_date", "a_share_eps_2026_native",
    "a_share_eps_2026_usd", "a_share_research_report_count_6m",
    "a_share_rating_buy_count", "a_share_rating_add_count",
    "a_share_rating_neutral_count", "a_share_rating_reduce_count",
    "a_share_rating_sell_count", "a_share_rating_total_count",
    "a_share_buy_add_pct", "a_share_consensus_em_source_quality",
    "cninfo_rating_event_count", "cninfo_latest_rating_event_date",
    "cninfo_latest_rating_change", "cninfo_latest_rating_direction",
    "cninfo_latest_target_price_low_native", "cninfo_latest_target_price_high_native",
    "cninfo_rating_source_quality", "cninfo_rating_history_scope",
    "profit_consensus_as_of_date", "profit_consensus_latest_observation_date",
    "profit_consensus_age_days", "profit_consensus_freshness_band",
    "profit_consensus_revision_history_available",
    "profit_consensus_source_layer",
    "yahoo_analyst_snapshot_date", "yahoo_eps_revision_signal_count",
    "yahoo_eps_revision_up_30d", "yahoo_eps_revision_down_30d",
    "yahoo_recommendation_period", "yahoo_recommendation_buy_add_pct",
    "yahoo_recommendation_rating_total", "yahoo_analyst_source_quality",
    "yahoo_analyst_source_url",
    "fy2026_net_profit_avg_native_mn", "fy2026_net_profit_low_native_mn",
    "fy2026_net_profit_high_native_mn", "consensus_forward_pe",
    "fy2026_net_profit_avg_usd_mn", "fy2026_net_profit_low_usd_mn",
    "fy2026_net_profit_high_usd_mn", "target_price_avg_usd",
    "market_cap_to_consensus_net_profit", "market_cap_to_consensus_net_profit_usd",
    "market_cap_to_consensus_revenue_usd", "fy2026_consensus_net_margin_pct",
    "fy2026_profit_range_crosses_zero", "consensus_valuation_quality",
    "latest_event_date", "latest_event_type",
    "latest_event_metric", "latest_event_value_min", "latest_event_value_max",
    "latest_event_native_unit", "latest_event_source_quality", "latest_event_source_url",
    "formal_report_status", "formal_report_scheduled_date",
    "formal_report_actual_disclosure_date", "formal_report_calendar_source_url",
    "formal_report_evidence_source_quality", "formal_report_evidence_source_url",
    "formal_report_announcement_id",
    "energy_observation_date", "jet_fuel_spot_usd_per_gallon",
    "brent_spot_usd_per_barrel", "energy_source_release_date",
    "source_quality", "source_note", "retrieved_at",
]


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _is_true(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        if str(value).strip().lower() in {"", "nan", "none"}:
            continue
        return value
    return None


def _first_metric(frame: pd.DataFrame, metric: str) -> float | None:
    rows = frame.loc[frame["metric"].eq(metric)]
    if rows.empty:
        return None
    return _number(rows.iloc[0].get("value_native"))


def _first_metric_any(frame: pd.DataFrame, *metrics: str) -> float | None:
    for metric in metrics:
        value = _first_metric(frame, metric)
        if value is not None:
            return value
    return None


def _trend_value(frame: pd.DataFrame, company: str, metric: str, field: str) -> float | None:
    rows = frame.loc[
        frame["company"].eq(company)
        & frame["scope_type"].eq("company")
        & frame["region"].eq("Total")
        & frame["metric"].eq(metric)
    ]
    if rows.empty:
        return None
    return _number(rows.iloc[0].get(field))


def _latest_energy(path: Path = ENERGY_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    frame = pd.read_parquet(path).copy()
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame = frame.loc[frame["frequency"].eq("weekly")].dropna(subset=["observation_date"])
    if frame.empty:
        return {}
    latest_date = frame["observation_date"].max()
    latest = frame.loc[frame["observation_date"].eq(latest_date)]
    result: dict[str, Any] = {"energy_observation_date": latest_date.strftime("%Y-%m-%d")}
    for series_id, field in (
        ("EER_EPJK_PF4_RGC_DPG", "jet_fuel_spot_usd_per_gallon"),
        ("RBRTE", "brent_spot_usd_per_barrel"),
    ):
        rows = latest.loc[latest["series_id"].eq(series_id)]
        if not rows.empty:
            result[field] = _number(rows.iloc[0].get("value"))
            result["energy_source_release_date"] = rows.iloc[0].get("source_release_date")
    return result


def _freshness_row(
    freshness: pd.DataFrame,
    *,
    company: str,
    ticker: str,
    source_layer: str,
) -> dict[str, Any]:
    """Return the freshness contract row for a bridge source.

    The bridge contains both HK and A-share share classes.  Freshness rows are
    matched by exact ticker first, then by company, because the A-share
    consensus layer is the underlying issuer-level source for both share
    classes.  A missing row stays explicit rather than being treated as fresh.
    """
    if freshness.empty:
        return {}
    candidates = freshness.loc[freshness["source_layer"].eq(source_layer)].copy()
    if candidates.empty:
        return {}
    exact = candidates.loc[candidates["ticker"].astype(str).eq(str(ticker))]
    if not exact.empty:
        return exact.iloc[0].to_dict()
    company_rows = candidates.loc[candidates["company"].astype(str).eq(str(company))]
    if company_rows.empty:
        return {}
    return company_rows.iloc[0].to_dict()


def _freshness_fields(
    freshness: pd.DataFrame,
    *,
    company: str,
    ticker: str,
) -> dict[str, Any]:
    """Map the consensus freshness contract into explicit bridge fields."""
    revenue = _freshness_row(
        freshness, company=company, ticker=ticker, source_layer="vendor_revenue_consensus"
    )
    if not revenue:
        # Hainan's revenue fallback comes from the A-share detailed-indicator
        # layer rather than Yahoo. Keep that fallback's freshness explicit.
        revenue = _freshness_row(
            freshness, company=company, ticker=ticker, source_layer="ashare_detailed_consensus"
        )
    profit = _freshness_row(
        freshness, company=company, ticker=ticker, source_layer="ashare_profit_consensus"
    )
    sell_side = _freshness_row(
        freshness, company=company, ticker=ticker, source_layer="mainland_revenue_sell_side_pdf"
    )
    hk_broker = _freshness_row(
        freshness, company=company, ticker=ticker, source_layer="hk_broker_profit_consensus"
    )

    def pick(row: dict[str, Any], key: str) -> Any:
        return row.get(key) if row else None

    return {
        "revenue_consensus_source_layer": pick(revenue, "source_layer"),
        "revenue_consensus_as_of_date": pick(revenue, "as_of_date"),
        "revenue_consensus_latest_observation_date": pick(revenue, "latest_observation_date"),
        "revenue_consensus_age_days": pick(revenue, "age_days"),
        "revenue_consensus_freshness_band": pick(revenue, "freshness_band"),
        "revenue_consensus_revision_history_available": pick(revenue, "revision_history_available"),
        "sell_side_revenue_as_of_date": pick(sell_side, "as_of_date"),
        "sell_side_revenue_age_days": pick(sell_side, "age_days"),
        "sell_side_revenue_freshness_band": pick(sell_side, "freshness_band"),
        "sell_side_revenue_revision_history_available": pick(sell_side, "revision_history_available"),
        "sell_side_revenue_source_layer": pick(sell_side, "source_layer"),
        "hk_broker_consensus_as_of_date": pick(hk_broker, "as_of_date"),
        "hk_broker_consensus_age_days": pick(hk_broker, "age_days"),
        "hk_broker_consensus_freshness_band": pick(hk_broker, "freshness_band"),
        "hk_broker_consensus_revision_history_available": pick(hk_broker, "revision_history_available"),
        "hk_broker_consensus_source_layer": pick(hk_broker, "source_layer"),
        "profit_consensus_as_of_date": pick(profit, "as_of_date"),
        "profit_consensus_latest_observation_date": pick(profit, "latest_observation_date"),
        "profit_consensus_age_days": pick(profit, "age_days"),
        "profit_consensus_freshness_band": pick(profit, "freshness_band"),
        "profit_consensus_revision_history_available": pick(profit, "revision_history_available"),
        "profit_consensus_source_layer": pick(profit, "source_layer"),
    }


def _em_consensus_row(frame: pd.DataFrame, company: str) -> dict[str, Any]:
    """Return the latest FY2026 Eastmoney EPS/rating row for an issuer."""
    if frame.empty or "company" not in frame.columns:
        return {}
    candidates = frame.loc[
        frame["company"].eq(company) & frame["fiscal_year"].eq(2026)
    ].copy()
    if candidates.empty:
        return {}
    candidates["_snapshot"] = pd.to_datetime(candidates["snapshot_date"], errors="coerce")
    return candidates.sort_values("_snapshot").iloc[-1].to_dict()


def _cninfo_rating_summary(frame: pd.DataFrame, company: str) -> dict[str, Any]:
    """Summarize dated Cninfo rating events without implying full coverage."""
    if frame.empty or "company" not in frame.columns:
        return {}
    candidates = frame.loc[frame["company"].eq(company)].copy()
    if candidates.empty:
        return {}
    candidates["_date"] = pd.to_datetime(candidates["report_date"], errors="coerce")
    latest = candidates.sort_values("_date").iloc[-1]
    return {
        "cninfo_rating_event_count": len(candidates),
        "cninfo_latest_rating_event_date": latest.get("report_date"),
        "cninfo_latest_rating_change": latest.get("rating_change"),
        "cninfo_latest_rating_direction": latest.get("rating_direction"),
        "cninfo_latest_target_price_low_native": latest.get("target_price_low_native"),
        "cninfo_latest_target_price_high_native": latest.get("target_price_high_native"),
        "cninfo_rating_source_quality": latest.get("source_quality"),
        "cninfo_rating_history_scope": latest.get("history_scope"),
    }


def _yahoo_analyst_summary(frame: pd.DataFrame, *, company: str, ticker: str) -> dict[str, Any]:
    """Map the exact share-class Yahoo snapshot into bridge fields."""
    if frame.empty or "ticker" not in frame.columns:
        return {}
    candidates = frame.loc[frame["ticker"].astype(str).eq(str(ticker))].copy()
    if candidates.empty:
        candidates = frame.loc[frame["company"].eq(company)].copy()
    if candidates.empty:
        return {}
    candidates["_snapshot"] = pd.to_datetime(candidates["snapshot_date"], errors="coerce")
    snapshot = candidates["_snapshot"].max()
    result: dict[str, Any] = {
        "yahoo_analyst_snapshot_date": snapshot.strftime("%Y-%m-%d") if not pd.isna(snapshot) else None,
        "yahoo_analyst_source_quality": candidates.iloc[-1].get("source_quality"),
        "yahoo_analyst_source_url": candidates.iloc[-1].get("source_url"),
    }
    revisions = candidates.loc[candidates["metric"].eq("eps_revision_signal")]
    if not revisions.empty:
        result.update({
            "yahoo_eps_revision_signal_count": len(revisions),
            "yahoo_eps_revision_up_30d": pd.to_numeric(revisions["up_last_30_days"], errors="coerce").sum(min_count=1),
            "yahoo_eps_revision_down_30d": pd.to_numeric(revisions["down_last_30_days"], errors="coerce").sum(min_count=1),
        })
    ratings = candidates.loc[
        candidates["metric"].eq("recommendation_trend")
        & candidates["period"].astype(str).eq("0m")
    ]
    if not ratings.empty:
        latest = ratings.sort_values("_snapshot").iloc[-1]
        result.update({
            "yahoo_recommendation_period": latest.get("period"),
            "yahoo_recommendation_buy_add_pct": latest.get("buy_add_pct"),
            "yahoo_recommendation_rating_total": latest.get("rating_total"),
        })
    return result


def _latest_discovery_debt_to_assets(frame: pd.DataFrame, company: str) -> dict[str, Any]:
    """Return the latest provider balance-sheet ratio with its PIT caveat."""
    if frame.empty or not {"company", "metric", "period_end", "value_native"}.issubset(frame.columns):
        return {}
    candidates = frame.loc[
        frame["company"].eq(company) & frame["metric"].eq("debt_to_assets")
    ].copy()
    if candidates.empty:
        return {}
    candidates["_period_end"] = pd.to_datetime(candidates["period_end"], errors="coerce")
    candidates = candidates.dropna(subset=["_period_end"]).sort_values("_period_end")
    if candidates.empty:
        return {}
    latest = candidates.iloc[-1]
    return {
        "latest_discovery_debt_to_assets_pct": _number(latest.get("value_native")),
        "latest_discovery_debt_to_assets_period_end": latest.get("period_end"),
        "latest_discovery_debt_to_assets_source_quality": latest.get("source_quality"),
    }


def _company_financials(company: str, official: pd.DataFrame, cathay: pd.DataFrame) -> dict[str, Any]:
    if company == "Cathay Pacific":
        available_periods = set(cathay.get("statement_period", pd.Series(dtype=str)).dropna().astype(str))
        period = next(
            (candidate for candidate in ("1H2026", "FY2025", "1H2025") if candidate in available_periods),
            "1H2025",
        )
        rows = cathay.loc[
            cathay["company"].eq("Cathay Pacific")
            & cathay["statement_period"].eq(period)
        ].copy()
        if rows.empty:
            return {"latest_financial_period": period}
        value = lambda metric: _first_metric(rows, metric)
        fuel_cost = value("fuel_cost")
        operating_cost = value("operating_cost")
        return {
            "latest_financial_period": period,
            "latest_financial_currency": "HKD",
            "latest_report_announcement_date": {
                "1H2026": "2026-08-05",
                "FY2025": "2026-03-11",
                "1H2025": None,
            }.get(period),
            "latest_report_revenue_native_mn": value("total_revenue"),
            "latest_report_passenger_revenue_native_mn": value("passenger_revenue"),
            "latest_report_cargo_revenue_native_mn": value("cargo_revenue"),
            "latest_report_operating_cost_native_mn": operating_cost,
            "latest_report_fuel_cost_native_mn": fuel_cost,
            "latest_report_fuel_cost_share_pct": 100.0 * fuel_cost / operating_cost if fuel_cost is not None and operating_cost else None,
            "latest_report_fuel_hedge_native_mn": _first_metric_any(
                rows, "fuel_hedging_loss_gain", "fuel_hedge_fair_value_change"
            ),
            "latest_report_cask_native": None,
            "latest_report_cost_per_atk_native": value("cost_per_atk_incl_fuel"),
            "latest_report_ask_mn_seat_km": value("ask"),
            "latest_report_rpk_mn_passenger_km": value("rpk"),
            "latest_report_passenger_load_factor_pct": value("passenger_load_factor"),
            "latest_report_rask_native": value("passenger_revenue_per_ask"),
            "latest_report_passenger_yield_native": value("passenger_yield"),
            "latest_report_attributable_profit_native_mn": value("group_attributable_profit"),
            "latest_report_operating_cash_flow_native_mn": value("operating_cash_flow"),
            "latest_report_cash_and_cash_equivalents_native_mn": value("cash_and_cash_equivalents"),
            "latest_report_total_liabilities_native_mn": value("total_liabilities"),
            "latest_report_liabilities_to_assets_pct": value("liabilities_to_assets_pct_derived"),
            "latest_report_interest_bearing_debt_native_mn": value("interest_bearing_debt"),
            "latest_report_capex_cash_paid_native_mn": value("capex_cash_paid"),
            "latest_report_net_borrowings_native_mn": value("net_borrowings"),
            "latest_report_available_unrestricted_liquidity_native_mn": value("available_unrestricted_liquidity"),
        }

    rows = official.loc[
        official["company"].eq(company)
        & official["report_type"].eq("annual")
        & official["statement_period"].eq("FY2025")
    ].copy()
    if rows.empty:
        return {"latest_financial_period": "FY2025"}
    value = lambda metric: _first_metric(rows, metric)
    report_date = rows["announced_at"].dropna().astype(str).iloc[0] if rows["announced_at"].notna().any() else None
    currency = rows["native_currency"].dropna().astype(str).iloc[0] if rows["native_currency"].notna().any() else "RMB"
    return {
        "latest_financial_period": "FY2025",
        "latest_financial_currency": currency,
        "latest_report_announcement_date": report_date,
        "latest_report_revenue_native_mn": value("total_revenue"),
        "latest_report_passenger_revenue_native_mn": value("passenger_revenue"),
        "latest_report_cargo_revenue_native_mn": value("cargo_revenue"),
        "latest_report_operating_cost_native_mn": value("operating_cost"),
        "latest_report_fuel_cost_native_mn": value("fuel_cost"),
        "latest_report_fuel_cost_share_pct": value("fuel_cost_share_pct_derived"),
        "latest_report_fuel_hedge_native_mn": value("fuel_hedge_fair_value_change"),
        "latest_report_cask_native": value("cask_derived"),
        "latest_report_cost_per_atk_native": None,
        "latest_report_ask_mn_seat_km": value("ask"),
        "latest_report_rpk_mn_passenger_km": value("rpk"),
        "latest_report_passenger_load_factor_pct": value("passenger_load_factor_pct"),
        "latest_report_rask_native": _first_metric_any(
            rows, "rask_derived", "rask_from_reported_yield_derived"
        ),
        "latest_report_passenger_yield_native": _first_metric_any(
            rows, "passenger_yield", "passenger_yield_derived"
        ),
        "latest_report_attributable_profit_native_mn": value("attributable_net_income"),
        "latest_report_operating_cash_flow_native_mn": value("operating_cash_flow"),
        "latest_report_cash_and_cash_equivalents_native_mn": value("cash_and_cash_equivalents"),
        "latest_report_total_liabilities_native_mn": value("total_liabilities"),
        "latest_report_liabilities_to_assets_pct": value("liabilities_to_assets_pct_derived"),
        "latest_report_interest_bearing_debt_native_mn": value("interest_bearing_debt"),
        "latest_report_capex_cash_paid_native_mn": value("capex_cash_paid"),
        "latest_report_net_borrowings_native_mn": value("net_borrowings"),
        "latest_report_available_unrestricted_liquidity_native_mn": value("available_unrestricted_liquidity"),
    }


def build_airline_expectation_bridge(
    *,
    market: pd.DataFrame | None = None,
    official: pd.DataFrame | None = None,
    cathay_financials: pd.DataFrame | None = None,
    trend: pd.DataFrame | None = None,
    cathay_trend: pd.DataFrame | None = None,
    events: pd.DataFrame | None = None,
    filing_calendar: pd.DataFrame | None = None,
    official_filing_watch: pd.DataFrame | None = None,
    sell_side_revenue: pd.DataFrame | None = None,
    sell_side_revenue_revisions: pd.DataFrame | None = None,
    hk_broker_forecasts: pd.DataFrame | None = None,
    hk_broker_revisions: pd.DataFrame | None = None,
    consensus_freshness: pd.DataFrame | None = None,
    a_share_consensus_em: pd.DataFrame | None = None,
    yahoo_analyst_snapshot: pd.DataFrame | None = None,
    cninfo_rating_events: pd.DataFrame | None = None,
    a_share_actuals: pd.DataFrame | None = None,
    energy: dict[str, Any] | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Join the current sector evidence into one auditable share-class view."""
    market = market if market is not None else pd.read_csv(MARKET_PATH)
    official = official if official is not None else pd.read_csv(OFFICIAL_PATH)
    if cathay_financials is None:
        cathay_frames = []
        if CATHAY_FINANCIAL_PATH.exists():
            cathay_frames.append(pd.read_csv(CATHAY_FINANCIAL_PATH))
        if CATHAY_ANNUAL_FINANCIAL_PATH.exists():
            cathay_frames.append(pd.read_csv(CATHAY_ANNUAL_FINANCIAL_PATH))
        if CATHAY_INTERIM_FINANCIAL_PATH.exists():
            cathay_frames.append(pd.read_csv(CATHAY_INTERIM_FINANCIAL_PATH))
        cathay_financials = pd.concat(cathay_frames, ignore_index=True) if cathay_frames else pd.DataFrame()
    trend_frames = []
    if trend is not None:
        trend_frames.append(trend)
    elif TREND_PATH.exists():
        trend_frames.append(pd.read_csv(TREND_PATH))
    if cathay_trend is not None:
        trend_frames.append(cathay_trend)
    elif CATHAY_TREND_PATH.exists():
        trend_frames.append(pd.read_csv(CATHAY_TREND_PATH))
    trend_all = pd.concat(trend_frames, ignore_index=True) if trend_frames else pd.DataFrame()
    events = events if events is not None else pd.read_csv(EVENT_PATH)
    filing_calendar = (
        filing_calendar
        if filing_calendar is not None
        else (pd.read_csv(FILING_CALENDAR_PATH) if FILING_CALENDAR_PATH.exists() else pd.DataFrame())
    )
    official_filing_watch = (
        official_filing_watch
        if official_filing_watch is not None
        else (pd.read_csv(OFFICIAL_FILING_WATCH_PATH) if OFFICIAL_FILING_WATCH_PATH.exists() else pd.DataFrame())
    )
    sell_side_revenue = (
        sell_side_revenue
        if sell_side_revenue is not None
        else (pd.read_csv(SELL_SIDE_REVENUE_PATH) if SELL_SIDE_REVENUE_PATH.exists() else pd.DataFrame())
    )
    sell_side_revenue_revisions = (
        sell_side_revenue_revisions
        if sell_side_revenue_revisions is not None
        else (pd.read_csv(SELL_SIDE_REVENUE_REVISION_PATH) if SELL_SIDE_REVENUE_REVISION_PATH.exists() else pd.DataFrame())
    )
    hk_broker_forecasts = (
        hk_broker_forecasts
        if hk_broker_forecasts is not None
        else (pd.read_csv(HK_BROKER_FORECAST_PATH) if HK_BROKER_FORECAST_PATH.exists() else pd.DataFrame())
    )
    hk_broker_revisions = (
        hk_broker_revisions
        if hk_broker_revisions is not None
        else (pd.read_csv(HK_BROKER_REVISION_PATH) if HK_BROKER_REVISION_PATH.exists() else pd.DataFrame())
    )
    consensus_freshness = (
        consensus_freshness
        if consensus_freshness is not None
        else (pd.read_csv(CONSENSUS_FRESHNESS_PATH) if CONSENSUS_FRESHNESS_PATH.exists() else pd.DataFrame())
    )
    a_share_consensus_em = (
        a_share_consensus_em
        if a_share_consensus_em is not None
        else (pd.read_csv(EM_CONSENSUS_PATH) if EM_CONSENSUS_PATH.exists() else pd.DataFrame())
    )
    yahoo_analyst_snapshot = (
        yahoo_analyst_snapshot
        if yahoo_analyst_snapshot is not None
        else (pd.read_csv(YAHOO_ANALYST_PATH) if YAHOO_ANALYST_PATH.exists() else pd.DataFrame())
    )
    cninfo_rating_events = (
        cninfo_rating_events
        if cninfo_rating_events is not None
        else (pd.read_csv(CNINFO_RATING_PATH) if CNINFO_RATING_PATH.exists() else pd.DataFrame())
    )
    a_share_actuals = (
        a_share_actuals
        if a_share_actuals is not None
        else (pd.read_csv(ASHARE_ACTUALS_PATH) if ASHARE_ACTUALS_PATH.exists() else pd.DataFrame())
    )
    energy = energy if energy is not None else _latest_energy()
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    for _, item in market.iterrows():
        company = str(item["company"])
        trend_company = "Cathay Pacific Group" if company == "Cathay Pacific" else company
        financial = _company_financials(company, official, cathay_financials)
        em_consensus = _em_consensus_row(a_share_consensus_em, company)
        yahoo_summary = _yahoo_analyst_summary(
            yahoo_analyst_snapshot,
            company=company,
            ticker=str(item["ticker"]),
        )
        cninfo_summary = _cninfo_rating_summary(cninfo_rating_events, company)
        discovery_leverage = _latest_discovery_debt_to_assets(a_share_actuals, company)
        latest_event = events.loc[events["company"].eq(company)].copy()
        if not latest_event.empty:
            priority = {
                "financial_results": 4,
                "earnings_warning": 3,
                "earnings_guidance": 3,
                "consensus_expectation_news": 2,
                "monthly_operating_update": 1,
            }
            latest_event["_event_priority"] = latest_event["event_type"].map(priority).fillna(0)
            latest_event = latest_event.sort_values(
                ["event_date", "_event_priority", "event_id"]
            ).iloc[-1]
        else:
            latest_event = {}
        formal_report = {}
        if company == "Cathay Pacific":
            formal_report = {
                "formal_report_status": "disclosed",
                "formal_report_scheduled_date": "2026-08-05",
                "formal_report_actual_disclosure_date": "2026-08-05",
                "formal_report_calendar_source_url": "https://www.cathaypacific.com/cx/en_HK/investor-relations/financial-calendar.html",
            }
        elif not filing_calendar.empty and "company" in filing_calendar.columns:
            candidates = filing_calendar.loc[filing_calendar["company"].eq(company)]
            if not candidates.empty:
                calendar_row = candidates.sort_values("snapshot_date").iloc[-1]
                formal_report = {
                    "formal_report_status": calendar_row.get("calendar_status"),
                    "formal_report_scheduled_date": calendar_row.get("first_scheduled_date"),
                    "formal_report_actual_disclosure_date": calendar_row.get("actual_disclosure_date"),
                    "formal_report_calendar_source_url": calendar_row.get("source_url"),
                }
        if not official_filing_watch.empty and "company" in official_filing_watch.columns:
            watch_candidates = official_filing_watch.loc[
                official_filing_watch["company"].eq(company)
            ].copy()
            if not watch_candidates.empty:
                watch_candidates["_snapshot"] = pd.to_datetime(
                    watch_candidates["snapshot_date"], errors="coerce"
                )
                watch_row = watch_candidates.sort_values("_snapshot").iloc[-1]
                formal_report["formal_report_scheduled_date"] = (
                    _first_present(
                        watch_row.get("scheduled_date"),
                        formal_report.get("formal_report_scheduled_date"),
                    )
                )
                formal_report["formal_report_evidence_source_quality"] = watch_row.get("source_quality")
                formal_report["formal_report_evidence_source_url"] = (
                    _first_present(watch_row.get("report_pdf_url"), watch_row.get("source_url"))
                )
                formal_report["formal_report_announcement_id"] = watch_row.get("announcement_id")
                if _is_true(watch_row.get("official_report_found")):
                    formal_report["formal_report_status"] = "disclosed"
                    formal_report["formal_report_actual_disclosure_date"] = watch_row.get(
                        "official_disclosure_date"
                    )
        latest_sell_side = {}
        latest_sell_side_revision = {}
        if not sell_side_revenue.empty:
            sell_side_candidates = sell_side_revenue.loc[
                sell_side_revenue["company"].eq(company)
                & sell_side_revenue["fiscal_year"].eq(2026)
            ].copy()
            if not sell_side_candidates.empty:
                latest_sell_side = sell_side_candidates.sort_values("report_date").iloc[-1]
        if not sell_side_revenue_revisions.empty:
            revision_candidates = sell_side_revenue_revisions.loc[
                sell_side_revenue_revisions["company"].eq(company)
                & sell_side_revenue_revisions["fiscal_year"].eq(2026)
                & sell_side_revenue_revisions["prior_report_date"].notna()
            ].copy()
            if not revision_candidates.empty:
                latest_sell_side_revision = revision_candidates.sort_values("report_date").iloc[-1]
        hk_broker_latest = {}
        hk_broker_count = 0
        hk_broker_true_revision_count = 0
        if not hk_broker_forecasts.empty:
            broker_candidates = hk_broker_forecasts.loc[
                hk_broker_forecasts["ticker"].eq(item["ticker"])
            ].copy()
            if not broker_candidates.empty:
                hk_broker_count = len(broker_candidates)
                hk_broker_latest = broker_candidates.sort_values("report_date").iloc[-1]
        if not hk_broker_revisions.empty:
            revision_candidates = hk_broker_revisions.loc[
                hk_broker_revisions["ticker"].eq(item["ticker"])
                & hk_broker_revisions["prior_report_date"].notna()
            ]
            hk_broker_true_revision_count = len(revision_candidates)
        row = {
            "dataset_id": "airline_expectation_bridge",
            "company": company,
            "market_ticker": item["ticker"],
            "market": item["market"],
            "snapshot_date": item.get("snapshot_date"),
            "latest_price_native": item.get("latest_price_native"),
            "price_currency": item.get("price_currency"),
            "market_cap_usd_mn": item.get("market_cap_usd_mn"),
            "h1_ask_yoy_pct": _trend_value(trend_all, trend_company, "ask", "yoy_change_pct"),
            "h1_rpk_yoy_pct": _trend_value(trend_all, trend_company, "rpk", "yoy_change_pct"),
            "h1_passengers_yoy_pct": _trend_value(trend_all, trend_company, "passengers", "yoy_change_pct"),
            "h1_passenger_lf_change_pp": _trend_value(trend_all, trend_company, "passenger_load_factor_pct", "yoy_change_abs"),
            "h1_cargo_tonnes_yoy_pct": _trend_value(trend_all, trend_company, "cargo_tonnes", "yoy_change_pct"),
            "h1_freight_lf_change_pp": _trend_value(trend_all, trend_company, "freight_load_factor_pct", "yoy_change_abs"),
            **financial,
            **discovery_leverage,
            "fy2026_revenue_avg_native_mn": item.get("fy2026_revenue_avg_native_mn"),
            "fy2026_revenue_low_native_mn": item.get("fy2026_revenue_low_native_mn"),
            "fy2026_revenue_high_native_mn": item.get("fy2026_revenue_high_native_mn"),
            "fy2026_revenue_avg_usd_mn": item.get("fy2026_revenue_avg_usd_mn"),
            "fy2026_revenue_low_usd_mn": item.get("fy2026_revenue_low_usd_mn"),
            "fy2026_revenue_high_usd_mn": item.get("fy2026_revenue_high_usd_mn"),
            "fy2026_revenue_growth_pct": item.get("fy2026_revenue_growth_pct"),
            "fy2026_revenue_analyst_count": item.get("fy2026_revenue_analyst_count"),
            "revenue_consensus_source_quality": item.get("revenue_consensus_source_quality"),
            "revenue_consensus_scope": item.get("revenue_consensus_scope"),
            **_freshness_fields(
                consensus_freshness,
                company=company,
                ticker=str(item["ticker"]),
            ),
            "latest_sell_side_revenue_native_mn": latest_sell_side.get("revenue_forecast_native_mn"),
            "latest_sell_side_revenue_report_date": latest_sell_side.get("report_date"),
            "latest_sell_side_revenue_institution": latest_sell_side.get("institution"),
            "latest_sell_side_revenue_title": latest_sell_side.get("report_title"),
            "latest_sell_side_revenue_revision_pct": latest_sell_side_revision.get("revenue_change_pct"),
            "latest_sell_side_revenue_source_quality": latest_sell_side.get("source_quality"),
            "latest_sell_side_revenue_source_url": latest_sell_side.get("report_url"),
            "hk_broker_observation_count": hk_broker_count or None,
            "hk_broker_latest_report_date": hk_broker_latest.get("report_date"),
            "hk_broker_latest_institution": hk_broker_latest.get("institution"),
            "hk_broker_latest_rating": hk_broker_latest.get("rating"),
            "hk_broker_latest_target_price_hkd": hk_broker_latest.get("target_price_hkd"),
            "hk_broker_forecast_currency": hk_broker_latest.get(
                "forecast_currency", "HKD" if company == "Cathay Pacific" else "RMB"
            ),
            "hk_broker_target_price_currency": hk_broker_latest.get("target_price_currency", "HKD"),
            "hk_broker_latest_net_profit_usd_mn": hk_broker_latest.get("net_profit_usd_mn_at_report"),
            "hk_broker_latest_eps_usd": hk_broker_latest.get("eps_usd_at_report"),
            "hk_broker_latest_target_price_usd": hk_broker_latest.get("target_price_usd_at_report"),
            "hk_broker_forecast_fx_pair": hk_broker_latest.get("forecast_fx_pair"),
            "hk_broker_forecast_fx_observation_date": hk_broker_latest.get("forecast_fx_observation_date"),
            "hk_broker_target_price_fx_observation_date": hk_broker_latest.get("target_price_fx_observation_date"),
            "hk_broker_true_revision_count": hk_broker_true_revision_count,
            "hk_broker_source_quality": hk_broker_latest.get("source_quality"),
            "a_share_consensus_em_snapshot_date": em_consensus.get("snapshot_date"),
            "a_share_eps_2026_native": em_consensus.get("eps_avg_native"),
            "a_share_eps_2026_usd": em_consensus.get("eps_avg_usd_at_snapshot"),
            "a_share_research_report_count_6m": em_consensus.get("research_report_count_6m"),
            "a_share_rating_buy_count": em_consensus.get("rating_buy_count"),
            "a_share_rating_add_count": em_consensus.get("rating_add_count"),
            "a_share_rating_neutral_count": em_consensus.get("rating_neutral_count"),
            "a_share_rating_reduce_count": em_consensus.get("rating_reduce_count"),
            "a_share_rating_sell_count": em_consensus.get("rating_sell_count"),
            "a_share_rating_total_count": em_consensus.get("rating_total_count"),
            "a_share_buy_add_pct": em_consensus.get("buy_add_pct"),
            "a_share_consensus_em_source_quality": em_consensus.get("source_quality"),
            **cninfo_summary,
            **yahoo_summary,
            "fy2026_net_profit_avg_native_mn": item.get("fy2026_net_profit_avg_native_mn"),
            "fy2026_net_profit_low_native_mn": item.get("fy2026_net_profit_low_native_mn"),
            "fy2026_net_profit_high_native_mn": item.get("fy2026_net_profit_high_native_mn"),
            "fy2026_net_profit_avg_usd_mn": item.get("fy2026_net_profit_avg_usd_mn"),
            "fy2026_net_profit_low_usd_mn": item.get("fy2026_net_profit_low_usd_mn"),
            "fy2026_net_profit_high_usd_mn": item.get("fy2026_net_profit_high_usd_mn"),
            "target_price_avg_usd": item.get("target_price_avg_usd"),
            "consensus_forward_pe": item.get("consensus_forward_pe"),
            "market_cap_to_consensus_net_profit": item.get("market_cap_to_consensus_net_profit"),
            "market_cap_to_consensus_net_profit_usd": item.get("market_cap_to_consensus_net_profit_usd"),
            "market_cap_to_consensus_revenue_usd": item.get("market_cap_to_consensus_revenue_usd"),
            "fy2026_consensus_net_margin_pct": item.get("fy2026_consensus_net_margin_pct"),
            "fy2026_profit_range_crosses_zero": item.get("fy2026_profit_range_crosses_zero"),
            "consensus_valuation_quality": item.get("consensus_valuation_quality"),
            "latest_event_date": latest_event.get("event_date") if isinstance(latest_event, dict) else latest_event.get("event_date"),
            "latest_event_type": latest_event.get("event_type") if isinstance(latest_event, dict) else latest_event.get("event_type"),
            "latest_event_metric": latest_event.get("metric") if isinstance(latest_event, dict) else latest_event.get("metric"),
            "latest_event_value_min": latest_event.get("value_min") if isinstance(latest_event, dict) else latest_event.get("value_min"),
            "latest_event_value_max": latest_event.get("value_max") if isinstance(latest_event, dict) else latest_event.get("value_max"),
            "latest_event_native_unit": latest_event.get("native_unit") if isinstance(latest_event, dict) else latest_event.get("native_unit"),
            "latest_event_source_quality": latest_event.get("source_quality") if isinstance(latest_event, dict) else latest_event.get("source_quality"),
            "latest_event_source_url": latest_event.get("source_url") if isinstance(latest_event, dict) else latest_event.get("source_url"),
            **formal_report,
            **energy,
            "source_quality": "derived_join_with_source_lineage",
            "source_note": (
                "Derived share-class bridge. H1 operating values are 2026H1 versus 2025H1; "
                "financial actuals retain their disclosed latest period (1H2026 for Cathay and "
                "FY2025 for the current mainland groups). Revenue/profit expectations are asynchronous "
                "discovery snapshots and are not a complete broker-vintage tape. A-share debt-to-assets "
                "is provider discovery context with period_end retained, not a formal announcement-date PIT fact."
                " Formal-report status keeps the scheduled calendar separate from direct CNINFO evidence."
            ),
            "retrieved_at": retrieved,
        }
        rows.append(row)
    return pd.DataFrame(rows, columns=BRIDGE_COLUMNS)


def fetch_airline_expectation_bridge() -> pd.DataFrame:
    result = build_airline_expectation_bridge()
    result.to_csv(NORMALIZED_DIR / "airline_expectation_bridge.csv", index=False)
    return result


def source_path() -> Path:
    return NORMALIZED_DIR / "airline_expectation_bridge.csv"
