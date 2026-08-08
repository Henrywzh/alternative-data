"""Cross-market expectation dispersion for dual-listed mainland airlines."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


MARKET_EXPECTATIONS_PATH = NORMALIZED_DIR / "airline_market_expectations_snapshot.csv"
BRIDGE_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
EVENT_PATH = NORMALIZED_DIR / "airline_event_timeline.csv"
EPS_REVISION_PATH = NORMALIZED_DIR / "airline_sell_side_forecast_revisions.csv"
REVENUE_REVISION_PATH = NORMALIZED_DIR / "airline_sell_side_revenue_revisions.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_consensus_dispersion.csv"

DUAL_LISTED_UNIVERSE: tuple[dict[str, str], ...] = (
    {"company": "Air China", "hk_ticker": "0753.HK", "a_ticker": "601111.SH"},
    {"company": "China Southern Airlines", "hk_ticker": "01055.HK", "a_ticker": "600029.SH"},
    {"company": "China Eastern Airlines", "hk_ticker": "0670.HK", "a_ticker": "600115.SH"},
)

OUTPUT_COLUMNS = [
    "dataset_id", "pair_id", "company", "snapshot_date", "hk_ticker", "a_ticker",
    "hk_market_cap_usd_mn", "a_market_cap_usd_mn",
    "hk_profit_consensus_usd_mn", "a_profit_consensus_usd_mn",
    "profit_gap_a_minus_hk_usd_mn", "profit_sign_disagreement",
    "hk_profit_latest_observation_date", "a_profit_latest_observation_date",
    "hk_profit_age_days", "a_profit_age_days",
    "hk_profit_freshness_band", "a_profit_freshness_band",
    "hk_revenue_consensus_usd_mn", "a_revenue_consensus_usd_mn",
    "revenue_gap_a_minus_hk_usd_mn", "hk_revenue_age_days", "a_revenue_age_days",
    "hk_revenue_freshness_band", "a_revenue_freshness_band",
    "hk_consensus_source_quality", "a_consensus_source_quality",
    "eps_revision_count", "eps_positive_revision_count", "eps_negative_revision_count",
    "eps_latest_revision_date", "eps_latest_revision_pct",
    "revenue_revision_count", "revenue_positive_revision_count",
    "revenue_negative_revision_count", "revenue_latest_revision_date",
    "revenue_latest_revision_pct", "revision_source_quality",
    "latest_h1_warning_date", "hk_profit_forecast_pre_warning",
    "a_profit_forecast_pre_warning", "forecast_warning_alignment",
    "vintage_status", "source_quality", "source_note", "retrieved_at",
]


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value)


def _sign_disagreement(left: float | None, right: float | None) -> bool | None:
    if left is None or right is None:
        return None
    if left == 0 or right == 0:
        return False
    return (left > 0) != (right > 0)


def _market_row(frame: pd.DataFrame, ticker: str) -> dict[str, Any]:
    rows = frame.loc[frame["ticker"].eq(ticker)]
    return rows.iloc[0].to_dict() if not rows.empty else {}


def _bridge_row(frame: pd.DataFrame, ticker: str) -> dict[str, Any]:
    rows = frame.loc[frame["market_ticker"].eq(ticker)]
    return rows.iloc[0].to_dict() if not rows.empty else {}


def _warning_date(events: pd.DataFrame, company: str) -> str | None:
    if events.empty or "event_type" not in events.columns:
        return None
    rows = events.loc[
        events["company"].eq(company) & events["event_type"].eq("earnings_warning")
    ].copy()
    if rows.empty:
        return None
    dates = pd.to_datetime(rows["event_date"], errors="coerce").dropna()
    return dates.min().strftime("%Y-%m-%d") if not dates.empty else None


def _revision_summary(
    revisions: pd.DataFrame,
    *,
    company: str,
    change_column: str,
) -> dict[str, Any]:
    if revisions.empty or "company" not in revisions.columns:
        return {
            "count": 0,
            "positive_count": 0,
            "negative_count": 0,
            "latest_date": None,
            "latest_pct": None,
        }
    rows = revisions.loc[
        revisions["company"].eq(company)
        & pd.to_numeric(revisions.get("fiscal_year"), errors="coerce").eq(2026)
        & revisions["prior_report_date"].notna()
    ].copy()
    if rows.empty:
        return {
            "count": 0,
            "positive_count": 0,
            "negative_count": 0,
            "latest_date": None,
            "latest_pct": None,
        }
    changes = pd.to_numeric(rows[change_column], errors="coerce")
    rows["_report_date"] = pd.to_datetime(rows["report_date"], errors="coerce")
    rows = rows.sort_values("_report_date")
    latest = rows.iloc[-1]
    return {
        "count": int(len(rows)),
        "positive_count": int((changes > 0).sum()),
        "negative_count": int((changes < 0).sum()),
        "latest_date": latest["_report_date"].strftime("%Y-%m-%d") if pd.notna(latest["_report_date"]) else None,
        "latest_pct": _number(latest.get(change_column)),
    }


def build_airline_consensus_dispersion(
    *,
    market_expectations: pd.DataFrame | None = None,
    bridge: pd.DataFrame | None = None,
    events: pd.DataFrame | None = None,
    eps_revisions: pd.DataFrame | None = None,
    revenue_revisions: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build dual-listed USD expectation gaps with an explicit reconciliation flag."""
    market_expectations = (
        market_expectations
        if market_expectations is not None
        else pd.read_csv(MARKET_EXPECTATIONS_PATH)
    )
    bridge = bridge if bridge is not None else pd.read_csv(BRIDGE_PATH)
    events = events if events is not None else pd.read_csv(EVENT_PATH)
    eps_revisions = (
        eps_revisions
        if eps_revisions is not None
        else (pd.read_csv(EPS_REVISION_PATH) if EPS_REVISION_PATH.exists() else pd.DataFrame())
    )
    revenue_revisions = (
        revenue_revisions
        if revenue_revisions is not None
        else (pd.read_csv(REVENUE_REVISION_PATH) if REVENUE_REVISION_PATH.exists() else pd.DataFrame())
    )
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    for item in DUAL_LISTED_UNIVERSE:
        hk_market = _market_row(market_expectations, item["hk_ticker"])
        a_market = _market_row(market_expectations, item["a_ticker"])
        if not hk_market or not a_market:
            continue
        hk_bridge = _bridge_row(bridge, item["hk_ticker"])
        a_bridge = _bridge_row(bridge, item["a_ticker"])
        hk_profit = _number(hk_market.get("fy2026_net_profit_avg_usd_mn"))
        a_profit = _number(a_market.get("fy2026_net_profit_avg_usd_mn"))
        hk_revenue = _number(hk_market.get("fy2026_revenue_avg_usd_mn"))
        a_revenue = _number(a_market.get("fy2026_revenue_avg_usd_mn"))
        hk_profit_date = _text(hk_bridge.get("hk_broker_latest_report_date"))
        a_profit_date = _text(a_bridge.get("profit_consensus_latest_observation_date"))
        hk_profit_age = _number(hk_bridge.get("hk_broker_consensus_age_days"))
        a_profit_age = _number(a_bridge.get("profit_consensus_age_days"))
        hk_revenue_age = _number(hk_bridge.get("revenue_consensus_age_days"))
        a_revenue_age = _number(a_bridge.get("revenue_consensus_age_days"))
        hk_profit_band = _text(hk_bridge.get("hk_broker_consensus_freshness_band"))
        a_profit_band = _text(a_bridge.get("profit_consensus_freshness_band"))
        hk_revenue_band = _text(hk_bridge.get("revenue_consensus_freshness_band"))
        a_revenue_band = _text(a_bridge.get("revenue_consensus_freshness_band"))
        eps_revision = _revision_summary(
            eps_revisions, company=item["company"], change_column="eps_change_pct"
        )
        revenue_revision = _revision_summary(
            revenue_revisions, company=item["company"], change_column="revenue_change_pct"
        )
        warning_date = _warning_date(events, item["company"])
        hk_pre_warning = None
        a_pre_warning = None
        if warning_date and hk_profit_date:
            hk_pre_warning = hk_profit_date < warning_date
        if warning_date and a_profit_date:
            a_pre_warning = a_profit_date < warning_date

        statuses: list[str] = []
        if _sign_disagreement(hk_profit, a_profit):
            statuses.append("profit_sign_disagreement")
        if hk_profit_date and a_profit_date and hk_profit_date != a_profit_date:
            statuses.append("asynchronous_profit_observation_dates")
        if "stale" in {hk_profit_band, a_profit_band, hk_revenue_band, a_revenue_band}:
            statuses.append("stale_consensus_input")
        if not statuses:
            statuses.append("no_obvious_gap_flag")

        if hk_pre_warning is True and a_pre_warning is False:
            warning_alignment = "hk_pre_warning_a_post_warning"
        elif hk_pre_warning is False and a_pre_warning is True:
            warning_alignment = "hk_post_warning_a_pre_warning"
        elif hk_pre_warning is True and a_pre_warning is True:
            warning_alignment = "both_pre_warning"
        elif hk_pre_warning is False and a_pre_warning is False:
            warning_alignment = "both_post_warning"
        else:
            warning_alignment = "unknown"

        snapshot_dates = pd.to_datetime(
            [hk_market.get("snapshot_date"), a_market.get("snapshot_date")],
            errors="coerce",
        ).dropna()
        rows.append(
            {
                "dataset_id": "airline_consensus_dispersion",
                "pair_id": f"{item['company'].lower().replace(' ', '_')}_hk_a_consensus",
                "company": item["company"],
                "snapshot_date": snapshot_dates.max().strftime("%Y-%m-%d") if not snapshot_dates.empty else None,
                "hk_ticker": item["hk_ticker"],
                "a_ticker": item["a_ticker"],
                "hk_market_cap_usd_mn": _number(hk_market.get("market_cap_usd_mn")),
                "a_market_cap_usd_mn": _number(a_market.get("market_cap_usd_mn")),
                "hk_profit_consensus_usd_mn": hk_profit,
                "a_profit_consensus_usd_mn": a_profit,
                "profit_gap_a_minus_hk_usd_mn": a_profit - hk_profit if a_profit is not None and hk_profit is not None else None,
                "profit_sign_disagreement": _sign_disagreement(hk_profit, a_profit),
                "hk_profit_latest_observation_date": hk_profit_date,
                "a_profit_latest_observation_date": a_profit_date,
                "hk_profit_age_days": hk_profit_age,
                "a_profit_age_days": a_profit_age,
                "hk_profit_freshness_band": hk_profit_band,
                "a_profit_freshness_band": a_profit_band,
                "hk_revenue_consensus_usd_mn": hk_revenue,
                "a_revenue_consensus_usd_mn": a_revenue,
                "revenue_gap_a_minus_hk_usd_mn": a_revenue - hk_revenue if a_revenue is not None and hk_revenue is not None else None,
                "hk_revenue_age_days": hk_revenue_age,
                "a_revenue_age_days": a_revenue_age,
                "hk_revenue_freshness_band": hk_revenue_band,
                "a_revenue_freshness_band": a_revenue_band,
                "hk_consensus_source_quality": _text(hk_market.get("consensus_source_quality")),
                "a_consensus_source_quality": _text(a_market.get("consensus_source_quality")),
                "eps_revision_count": eps_revision["count"],
                "eps_positive_revision_count": eps_revision["positive_count"],
                "eps_negative_revision_count": eps_revision["negative_count"],
                "eps_latest_revision_date": eps_revision["latest_date"],
                "eps_latest_revision_pct": eps_revision["latest_pct"],
                "revenue_revision_count": revenue_revision["count"],
                "revenue_positive_revision_count": revenue_revision["positive_count"],
                "revenue_negative_revision_count": revenue_revision["negative_count"],
                "revenue_latest_revision_date": revenue_revision["latest_date"],
                "revenue_latest_revision_pct": revenue_revision["latest_pct"],
                "revision_source_quality": "public_sell_side_pdf_revision_proxy",
                "latest_h1_warning_date": warning_date,
                "hk_profit_forecast_pre_warning": hk_pre_warning,
                "a_profit_forecast_pre_warning": a_pre_warning,
                "forecast_warning_alignment": warning_alignment,
                "vintage_status": ";".join(statuses),
                "source_quality": "derived_cross_market_reconciliation",
                "source_note": (
                    "A/H FY2026 consensus comparison in USD. The gap is a reconciliation signal, not a trade signal: "
                    "HK and A-share providers can differ in broker coverage, forecast vintage and reporting scope. "
                    "Profit freshness uses the HK broker layer for H shares and A-share profit consensus for A shares; "
                    "revenue freshness uses the matched vendor/fallback layer in the expectation bridge."
                ),
                "retrieved_at": retrieved,
            }
        )

    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_consensus_dispersion() -> pd.DataFrame:
    result = build_airline_consensus_dispersion()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
