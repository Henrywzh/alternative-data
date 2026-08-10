"""Post-earnings tracking ledger for the airline research stack (priority 8).

Captures the full earnings event loop for each carrier / report period:

    pre-event model & consensus
        -> actual reported result
        -> market reaction (T0 / T+1 / T+5 returns)
        -> analyst revision signal
        -> validation status

The ledger is designed to be filled in two passes:

1. Pre-event pass (now): every row carries the model forecast (v3 base),
   the consensus profit and the scheduled filing date.  For the six
   mainland carriers the status is ``awaiting_report``.
2. Post-event pass (after each 1H2026 / FY2026 print): fill the actual
   columns, market-reaction returns and analyst-revision signal, and flip
   the status to ``filled``.

Cathay Pacific already reported 1H2026 (announced 2026-08-05), so its row
is the first fully filled example - it also doubles as a live backtest of
the market-reaction machinery on a known result.  Mainland A-share price
history is not yet in the yfinance layer, so their T0/T+1/T+5 returns are
left blank until price data is ingested (or filled manually from any
terminal).

Honesty rule: the H1 actual is compared against the FY2026 consensus/model
only through explicit share-of-FY ratios, never as a direct beat/miss -
that is the seasonal-adjustment trap.  The revision signal is a snapshot
of the 30d window ending at the expectation-bridge snapshot date, which
may straddle the announcement; it is labelled accordingly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_post_earnings_tracker.csv"
DATASET_ID = "airline_post_earnings_tracker"

PLAYBOOK_PATH = NORMALIZED_DIR / "airline_h1_2026_validation_playbook.csv"
EXPECTATION_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
FILING_CALENDAR_PATH = NORMALIZED_DIR / "airline_filing_calendar.csv"
YFINANCE_BARS_PATH = (
    Path(NORMALIZED_DIR).parent.parent.parent
    / "data/raw/market_data/yfinance/20260808T-stage3-daily-5y/bars_1d.parquet"
)

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "ticker",
    "report_period",
    "filing_scheduled_date",
    "announcement_date",
    "pre_event_model_fy2026_net_profit_usd_mn",
    "pre_event_consensus_fy2026_net_profit_usd_mn",
    "model_vs_consensus_pct",
    "net_income_leg",
    "actual_h1_net_profit_native_mn",
    "actual_h1_net_profit_currency",
    "actual_h1_net_profit_usd_mn",
    "actual_h1_revenue_native_mn",
    "h1_share_of_model_fy_pct",
    "h1_share_of_consensus_fy_pct",
    "return_day0_pct",
    "t1_return_pct",
    "t5_return_pct",
    "market_reaction_status",
    "analyst_revision_up_30d",
    "analyst_revision_down_30d",
    "revision_snapshot_date",
    "validation_status",
    "source_note",
    "retrieved_at",
]


def _num(value: object) -> float | None:
    if value is None:
        return None
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


def _returns_for_ticker(ticker: str, announcement_date: str) -> dict[str, Any]:
    """Compute T0 / T+1 / T+5 close-to-close returns around an announcement.

    T0 is the announcement-day close versus the previous trading day;
    T+1 / T+5 are the close N trading days after the announcement versus
    the announcement-day close.  Returns ``None`` values when the price
    history is unavailable or the horizon has not elapsed yet.
    """
    if not YFINANCE_BARS_PATH.exists():
        return {"day0": None, "t1": None, "t5": None, "status": "no_price_history"}
    try:
        bars = pd.read_parquet(YFINANCE_BARS_PATH)
    except Exception as exc:  # pragma: no cover - defensive
        return {"day0": None, "t1": None, "t5": None, "status": f"price_read_error:{exc}"}
    tick = bars[bars.ticker.eq(ticker)].copy()
    if tick.empty:
        return {"day0": None, "t1": None, "t5": None, "status": "ticker_not_in_yfinance_layer"}
    tick["dt"] = pd.to_datetime(tick["timestamp_utc"], errors="coerce")
    tick = tick.dropna(subset=["dt"]).sort_values("dt")
    anchor = pd.Timestamp(announcement_date, tz="UTC")
    after = tick[tick.dt >= anchor]
    if after.empty:
        return {"day0": None, "t1": None, "t5": None, "status": "announcement_beyond_price_history"}
    day0_close = after.iloc[0]["close"]
    day0_date = after.iloc[0]["dt"]
    before = tick[tick.dt < day0_date]
    prev_close = before.iloc[-1]["close"] if not before.empty else None
    day0 = (day0_close / prev_close - 1.0) * 100.0 if prev_close else None

    def _horizon(offset: int) -> float | None:
        idx = after.index.get_loc(after.index[0])
        if len(after) <= offset:
            return None
        return (after.iloc[offset]["close"] / day0_close - 1.0) * 100.0

    t1 = _horizon(1)
    t5 = _horizon(5)
    if t5 is None:
        status = "t5_pending" if t1 is not None else "returns_pending"
    else:
        status = "complete"
    return {"day0": day0, "t1": t1, "t5": t5, "status": status}


def _mainland_rows(playbook: pd.DataFrame, calendar: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, r in playbook.iterrows():
        company = r["company"]
        if company == "9 Air":
            continue  # no consensus / filing line; keep the playbook-only row out of the ledger
        cal = _row(calendar, company=company, statement_period="1H2026")
        model = _num(r.get("fy2026_v3_base_net_profit_usd_mn"))
        consensus = _num(r.get("consensus_fy2026_profit_usd_mn"))
        model_vs_consensus = (
            (model / consensus - 1.0) * 100.0 if (model is not None and consensus) else None
        )
        rows.append(
            {
                "company": company,
                "ticker": str(cal.get("ticker", "")) if not cal.empty else "",
                "report_period": "1H2026",
                "filing_scheduled_date": str(cal.get("first_scheduled_date", "")) if not cal.empty else "",
                "announcement_date": "",
                "pre_event_model_fy2026_net_profit_usd_mn": model,
                "pre_event_consensus_fy2026_net_profit_usd_mn": consensus,
                "model_vs_consensus_pct": model_vs_consensus,
                "net_income_leg": str(r.get("net_income_leg", "")),
                "actual_h1_net_profit_native_mn": None,
                "actual_h1_net_profit_currency": "",
                "actual_h1_net_profit_usd_mn": None,
                "actual_h1_revenue_native_mn": None,
                "h1_share_of_model_fy_pct": None,
                "h1_share_of_consensus_fy_pct": None,
                "return_day0_pct": None,
                "t1_return_pct": None,
                "t5_return_pct": None,
                "market_reaction_status": "awaiting_report",
                "analyst_revision_up_30d": None,
                "analyst_revision_down_30d": None,
                "revision_snapshot_date": "",
                "validation_status": "awaiting_report",
                "source_note": (
                    "Pre-event ledger row. Actuals, market reaction and "
                    "post-print revision signal to be filled after the 1H2026 "
                    "report. H1 actual is compared to FY consensus/model only "
                    "via share-of-FY ratios, not as a direct beat/miss. "
                    "model_vs_consensus_pct inherits the v3 net_income_leg "
                    "choice; for NCI-forward legs (e.g. Southern) the model "
                    "line is not attributable-net-income and must not be read "
                    "as a consensus beat/miss."
                ),
            }
        )
    return rows


def _cathay_row(expectation: pd.DataFrame) -> dict[str, Any]:
    cx = _row(expectation, company="Cathay Pacific")
    if cx.empty:
        return {}
    native = _num(cx.get("latest_report_attributable_profit_native_mn"))
    revenue = _num(cx.get("latest_report_revenue_native_mn"))
    consensus_native = _num(cx.get("fy2026_net_profit_avg_native_mn"))
    consensus_usd = _num(cx.get("fy2026_net_profit_avg_usd_mn"))
    # Implied FX from the consensus pair (native avg / usd avg), used to
    # translate the H1 actual into USD without introducing a separate rate.
    implied_fx = consensus_native / consensus_usd if (consensus_native and consensus_usd) else None
    actual_usd = native / implied_fx if (native is not None and implied_fx) else None
    announcement = str(cx.get("formal_report_actual_disclosure_date", ""))
    returns = _returns_for_ticker(str(cx.get("market_ticker", "")), announcement) if announcement else {
        "day0": None, "t1": None, "t5": None, "status": "no_announcement_date",
    }
    model = _num(cx.get("fy2026_v3_base_net_profit_usd_mn"))
    model_vs_consensus = (
        (model / consensus_usd - 1.0) * 100.0 if (model is not None and consensus_usd) else None
    )
    share_of_consensus = (
        (native / consensus_native) * 100.0 if (native is not None and consensus_native) else None
    )
    return {
        "company": "Cathay Pacific",
        "ticker": str(cx.get("market_ticker", "")),
        "report_period": str(cx.get("latest_financial_period", "1H2026")),
        "filing_scheduled_date": str(cx.get("formal_report_scheduled_date", "")) if not pd.isna(cx.get("formal_report_scheduled_date")) else "",
        "announcement_date": announcement,
        "pre_event_model_fy2026_net_profit_usd_mn": model,
        "pre_event_consensus_fy2026_net_profit_usd_mn": consensus_usd,
        "model_vs_consensus_pct": model_vs_consensus,
        "net_income_leg": "n_a_cathay_not_in_v3",
        "actual_h1_net_profit_native_mn": native,
        "actual_h1_net_profit_currency": str(cx.get("latest_financial_currency", "")),
        "actual_h1_net_profit_usd_mn": actual_usd,
        "actual_h1_revenue_native_mn": revenue,
        "h1_share_of_model_fy_pct": None,  # no v3 model for Cathay yet
        "h1_share_of_consensus_fy_pct": share_of_consensus,
        "return_day0_pct": returns["day0"],
        "t1_return_pct": returns["t1"],
        "t5_return_pct": returns["t5"],
        "market_reaction_status": returns["status"],
        "analyst_revision_up_30d": _num(cx.get("yahoo_eps_revision_up_30d")),
        "analyst_revision_down_30d": _num(cx.get("yahoo_eps_revision_down_30d")),
        "revision_snapshot_date": str(cx.get("yahoo_analyst_snapshot_date", "")) if not pd.isna(cx.get("yahoo_analyst_snapshot_date")) else "",
        "validation_status": "filled",
        "source_note": (
            "First filled ledger row (1H2026 announced 2026-08-05). H1 actual "
            "profit is HKD mn as reported; USD via implied FX from the "
            "consensus pair. H1 share of FY consensus shown, not a beat/miss. "
            "Returns: T0 announcement-day close vs prior close; T+1/T+5 vs "
            "announcement close. Revision signal is the 30d snapshot ending "
            "at the expectation-bridge snapshot date, may straddle the print."
        ),
    }


def build_airline_post_earnings_tracker() -> pd.DataFrame:
    """Build (or refresh) the post-earnings tracking ledger."""
    retrieved = datetime.now(timezone.utc).isoformat()
    playbook = pd.read_csv(PLAYBOOK_PATH)
    calendar = pd.read_csv(FILING_CALENDAR_PATH)
    expectation = pd.read_csv(EXPECTATION_PATH)

    rows: list[dict[str, Any]] = _mainland_rows(playbook, calendar)
    cathay = _cathay_row(expectation)
    if cathay:
        rows.append(cathay)

    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    result["dataset_id"] = DATASET_ID
    result["retrieved_at"] = retrieved
    result = result.sort_values(["validation_status", "company"]).reset_index(drop=True)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "build_airline_post_earnings_tracker",
    "source_path",
]
