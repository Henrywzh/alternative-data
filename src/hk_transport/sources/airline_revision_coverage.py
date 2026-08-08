"""Coverage summary for airline consensus and sell-side revision evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


OUTPUT_PATH = NORMALIZED_DIR / "airline_revision_coverage.csv"

COMPANIES = [
    "Cathay Pacific", "Air China", "China Southern Airlines",
    "China Eastern Airlines", "Spring Airlines", "Juneyao Airlines",
    "Hainan Airlines Holdings",
]

OUTPUT_COLUMNS = [
    "dataset_id", "company", "snapshot_date", "hk_broker_observation_count",
    "hk_broker_true_revision_count", "hk_broker_latest_observation_date",
    "ashare_eps_revision_proxy_count", "ashare_eps_positive_revision_count",
    "ashare_eps_negative_revision_count", "ashare_eps_latest_revision_date",
    "mainland_revenue_revision_proxy_count", "mainland_revenue_positive_revision_count",
    "mainland_revenue_negative_revision_count", "mainland_revenue_latest_revision_date",
    "public_report_evidence_row_count", "public_report_dated_row_count",
    "public_report_eps_up_marker_count", "public_report_eps_down_marker_count",
    "public_report_net_profit_up_marker_count", "public_report_net_profit_down_marker_count",
    "public_report_latest_date", "public_report_evidence_scope",
    "cninfo_rating_event_count", "cninfo_rating_upgrade_count",
    "cninfo_rating_downgrade_count", "cninfo_rating_latest_event_date",
    "unified_consensus_event_count", "unified_estimate_revision_count",
    "unified_rating_event_count", "unified_up_revision_count",
    "unified_down_revision_count", "unified_latest_event_date",
    "unified_latest_estimate_revision_date",
    "em_consensus_snapshot_date", "em_rating_total_count_2026", "em_buy_add_pct_2026",
    "yahoo_snapshot_date", "yahoo_share_class_count",
    "yahoo_eps_revision_signal_count", "yahoo_eps_revision_up_30d",
    "yahoo_eps_revision_down_30d", "yahoo_recommendation_share_class_count",
    "yahoo_recommendation_buy_add_pct_min", "yahoo_recommendation_buy_add_pct_max",
    "yahoo_recommendation_rating_total_sum", "yahoo_coverage_status",
    "yahoo_source_quality",
    "provider_revision_history_available", "revision_evidence_band", "source_quality",
    "source_note", "retrieved_at",
]


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _subset(frame: pd.DataFrame | None, company: str) -> pd.DataFrame:
    if frame is None or frame.empty or "company" not in frame.columns:
        return pd.DataFrame()
    return frame.loc[frame["company"].eq(company)].copy()


def _count_direction(frame: pd.DataFrame, column: str, direction: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    values = pd.to_numeric(frame[column], errors="coerce")
    if direction == "positive":
        return int(values.gt(0).sum())
    return int(values.lt(0).sum())


def _latest_date(frame: pd.DataFrame, column: str) -> str | None:
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_datetime(frame[column], errors="coerce").dropna()
    return values.max().strftime("%Y-%m-%d") if not values.empty else None


def build_airline_revision_coverage(
    *,
    hk_forecasts: pd.DataFrame | None = None,
    hk_revisions: pd.DataFrame | None = None,
    ashare_revisions: pd.DataFrame | None = None,
    revenue_revisions: pd.DataFrame | None = None,
    cninfo_events: pd.DataFrame | None = None,
    consensus_events: pd.DataFrame | None = None,
    em_consensus: pd.DataFrame | None = None,
    snapshot_date: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Summarize evidence availability without turning proxies into consensus."""
    def read(name: str, provided: pd.DataFrame | None) -> pd.DataFrame:
        if provided is not None:
            return provided
        path = NORMALIZED_DIR / name
        return pd.read_csv(path) if path.exists() else pd.DataFrame()

    hk_forecasts = read("airline_hk_sell_side_forecasts.csv", hk_forecasts)
    hk_revisions = read("airline_hk_forecast_revisions.csv", hk_revisions)
    ashare_revisions = read("airline_sell_side_forecast_revisions.csv", ashare_revisions)
    revenue_revisions = read("airline_sell_side_revenue_revisions.csv", revenue_revisions)
    cninfo_events = read("airline_cninfo_rating_events.csv", cninfo_events)
    consensus_events = read("airline_consensus_events.csv", consensus_events)
    em_consensus = read("airline_consensus_em_snapshot.csv", em_consensus)
    public_report_evidence = read("airline_public_report_evidence.csv", None)
    yahoo_analyst = read("airline_yahoo_analyst_snapshot.csv", None)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    snap = snapshot_date or pd.Timestamp(retrieved).strftime("%Y-%m-%d")
    rows: list[dict[str, Any]] = []
    for company in COMPANIES:
        hk = _subset(hk_forecasts, company)
        hk_rev = _subset(hk_revisions, company)
        eps_rev = _subset(ashare_revisions, company)
        rev_rev = _subset(revenue_revisions, company)
        public_reports = _subset(public_report_evidence, company)
        public_dated = public_reports.loc[public_reports["report_date"].notna()] if not public_reports.empty else pd.DataFrame()
        public_eps = public_dated.loc[public_dated["metric"].eq("eps")] if not public_dated.empty else pd.DataFrame()
        public_profit = public_dated.loc[public_dated["metric"].eq("net_profit")] if not public_dated.empty else pd.DataFrame()
        ratings = _subset(cninfo_events, company)
        em = _subset(em_consensus, company)
        yahoo = _subset(yahoo_analyst, company)
        em_2026 = em.loc[em["fiscal_year"].eq(2026)] if not em.empty else pd.DataFrame()
        hk_true = hk_rev.loc[hk_rev["prior_report_date"].notna()] if not hk_rev.empty and "prior_report_date" in hk_rev else pd.DataFrame()
        eps_true = eps_rev.loc[eps_rev["prior_report_date"].notna()] if not eps_rev.empty and "prior_report_date" in eps_rev else pd.DataFrame()
        revenue_true = rev_rev.loc[rev_rev["prior_report_date"].notna()] if not rev_rev.empty and "prior_report_date" in rev_rev else pd.DataFrame()
        dated_estimate_proxy_count = len(eps_true) + len(revenue_true) + len(hk_true)
        rating_count = len(ratings)
        unified = _subset(consensus_events, company)
        unified_estimates = unified.loc[unified["event_type"].eq("estimate_revision")] if not unified.empty and "event_type" in unified else pd.DataFrame()
        unified_ratings = unified.loc[unified["event_type"].eq("rating_event")] if not unified.empty and "event_type" in unified else pd.DataFrame()
        yahoo_revisions = yahoo.loc[yahoo["metric"].eq("eps_revision_signal")] if not yahoo.empty else pd.DataFrame()
        yahoo_ratings = yahoo.loc[
            yahoo["metric"].eq("recommendation_trend")
            & yahoo["period"].astype(str).eq("0m")
        ] if not yahoo.empty else pd.DataFrame()
        yahoo_snapshot = _latest_date(yahoo, "snapshot_date")
        yahoo_buy_add = pd.to_numeric(yahoo_ratings.get("buy_add_pct", pd.Series(dtype=float)), errors="coerce").dropna()
        yahoo_rating_total = pd.to_numeric(yahoo_ratings.get("rating_total", pd.Series(dtype=float)), errors="coerce").dropna()
        if yahoo.empty:
            yahoo_status = "no_vendor_coverage"
        elif yahoo_revisions.empty:
            yahoo_status = "available_no_eps_revision"
        else:
            yahoo_status = "available_with_revision_signal"
        if dated_estimate_proxy_count > 0:
            evidence_band = "dated_estimate_revision_proxy"
        elif not public_dated.empty:
            evidence_band = "dated_public_report_markers"
        elif rating_count > 0:
            evidence_band = "dated_rating_events_only"
        else:
            evidence_band = "current_snapshot_only"
        rows.append({
            "dataset_id": "airline_revision_coverage",
            "company": company,
            "snapshot_date": snap,
            "hk_broker_observation_count": len(hk),
            "hk_broker_true_revision_count": len(hk_true),
            "hk_broker_latest_observation_date": _latest_date(hk, "report_date"),
            "ashare_eps_revision_proxy_count": len(eps_true),
            "ashare_eps_positive_revision_count": _count_direction(eps_true, "eps_change_native", "positive"),
            "ashare_eps_negative_revision_count": _count_direction(eps_true, "eps_change_native", "negative"),
            "ashare_eps_latest_revision_date": _latest_date(eps_true, "report_date"),
            "mainland_revenue_revision_proxy_count": len(revenue_true),
            "mainland_revenue_positive_revision_count": _count_direction(revenue_true, "revenue_change_native_mn", "positive"),
            "mainland_revenue_negative_revision_count": _count_direction(revenue_true, "revenue_change_native_mn", "negative"),
            "mainland_revenue_latest_revision_date": _latest_date(revenue_true, "report_date"),
            "public_report_evidence_row_count": len(public_reports),
            "public_report_dated_row_count": len(public_dated),
            "public_report_eps_up_marker_count": int(public_eps.get("revision_flag", pd.Series(dtype=str)).eq("up").sum()) if not public_eps.empty else 0,
            "public_report_eps_down_marker_count": int(public_eps.get("revision_flag", pd.Series(dtype=str)).eq("down").sum()) if not public_eps.empty else 0,
            "public_report_net_profit_up_marker_count": int(public_profit.get("revision_flag", pd.Series(dtype=str)).eq("up").sum()) if not public_profit.empty else 0,
            "public_report_net_profit_down_marker_count": int(public_profit.get("revision_flag", pd.Series(dtype=str)).eq("down").sum()) if not public_profit.empty else 0,
            "public_report_latest_date": _latest_date(public_reports, "report_date",),
            "public_report_evidence_scope": (
                "dated_eps_profit_plus_page_snapshot_revenue" if not public_reports.empty else "not_available"
            ),
            "cninfo_rating_event_count": rating_count,
            "cninfo_rating_upgrade_count": int(ratings.get("rating_direction", pd.Series(dtype=str)).eq("upgrade").sum()) if not ratings.empty else 0,
            "cninfo_rating_downgrade_count": int(ratings.get("rating_direction", pd.Series(dtype=str)).eq("downgrade").sum()) if not ratings.empty else 0,
            "cninfo_rating_latest_event_date": _latest_date(ratings, "report_date"),
            "unified_consensus_event_count": len(unified),
            "unified_estimate_revision_count": len(unified_estimates),
            "unified_rating_event_count": len(unified_ratings),
            "unified_up_revision_count": int(unified_estimates.get("direction", pd.Series(dtype=str)).eq("up").sum()) if not unified_estimates.empty else 0,
            "unified_down_revision_count": int(unified_estimates.get("direction", pd.Series(dtype=str)).eq("down").sum()) if not unified_estimates.empty else 0,
            "unified_latest_event_date": _latest_date(unified, "event_date"),
            "unified_latest_estimate_revision_date": _latest_date(unified_estimates, "event_date"),
            "em_consensus_snapshot_date": _latest_date(em_2026, "snapshot_date"),
            "em_rating_total_count_2026": _number(em_2026.iloc[-1].get("rating_total_count")) if not em_2026.empty else None,
            "em_buy_add_pct_2026": _number(em_2026.iloc[-1].get("buy_add_pct")) if not em_2026.empty else None,
            "yahoo_snapshot_date": yahoo_snapshot,
            "yahoo_share_class_count": int(yahoo["ticker"].nunique()) if not yahoo.empty and "ticker" in yahoo.columns else 0,
            "yahoo_eps_revision_signal_count": len(yahoo_revisions),
            "yahoo_eps_revision_up_30d": pd.to_numeric(yahoo_revisions.get("up_last_30_days", pd.Series(dtype=float)), errors="coerce").sum(min_count=1) if not yahoo_revisions.empty else None,
            "yahoo_eps_revision_down_30d": pd.to_numeric(yahoo_revisions.get("down_last_30_days", pd.Series(dtype=float)), errors="coerce").sum(min_count=1) if not yahoo_revisions.empty else None,
            "yahoo_recommendation_share_class_count": len(yahoo_ratings),
            "yahoo_recommendation_buy_add_pct_min": yahoo_buy_add.min() if not yahoo_buy_add.empty else None,
            "yahoo_recommendation_buy_add_pct_max": yahoo_buy_add.max() if not yahoo_buy_add.empty else None,
            "yahoo_recommendation_rating_total_sum": yahoo_rating_total.sum(min_count=1) if not yahoo_rating_total.empty else None,
            "yahoo_coverage_status": yahoo_status,
            "yahoo_source_quality": _subset(yahoo, company).iloc[0].get("source_quality") if not yahoo.empty else None,
            "provider_revision_history_available": False,
            "revision_evidence_band": evidence_band,
            "source_quality": "derived_coverage_summary",
            "source_note": (
                "Counts are evidence coverage, not a consensus signal. HK and public sell-side rows are sparse; "
                "Cninfo is queried-date rating history; the unified event/pulse layers remain sparse public evidence. "
                "Yahoo fields are share-class vendor snapshots and are not a complete revision history. "
                "10jqka public-report markers show page-level up/down flags without a prior numeric estimate and "
                "therefore do not establish a complete revision history."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_revision_coverage() -> pd.DataFrame:
    result = build_airline_revision_coverage()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
