"""Unified point-in-time revision evidence for airline expectations.

The output intentionally preserves two evidence classes:

* dated broker/rating events from the public revision/event tape; and
* Yahoo's current short-horizon EPS revision counts.

The second class is useful context but is not a broker-vintage event.  Keeping
it in the same schema with an explicit evidence type makes that boundary easy
to enforce in pair research and downstream dashboards.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import AIRLINE_TICKER_ALIASES, NORMALIZED_DIR


EVENT_PATH = NORMALIZED_DIR / "airline_consensus_events.csv"
YAHOO_PATH = NORMALIZED_DIR / "airline_yahoo_analyst_snapshot.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_revision_evidence.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "evidence_date",
    "evidence_type", "metric", "fiscal_year", "institution", "prior_evidence_date",
    "current_value_native", "prior_value_native", "change_native", "change_pct",
    "direction", "signal_window", "signal_up_count", "signal_down_count",
    "signal_total_count", "rating", "previous_rating", "source_quality",
    "source_url", "information_scope", "revision_history_available",
    "source_note", "retrieved_at",
]


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _date(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _direction_from_counts(up: float | None, down: float | None) -> str:
    up_value = up or 0.0
    down_value = down or 0.0
    if up_value == 0 and down_value == 0:
        return "no_signal"
    if up_value > down_value:
        return "up"
    if down_value > up_value:
        return "down"
    return "flat"


def _event_rows(events: pd.DataFrame, *, retrieved_at: str) -> list[dict[str, Any]]:
    if events.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, event in events.iterrows():
        evidence_type = (
            "dated_estimate_revision"
            if str(event.get("event_type")) == "estimate_revision"
            else "dated_rating_event"
        )
        rows.append({
            "dataset_id": "airline_revision_evidence",
            "company": event.get("company"),
            "ticker": str(event.get("ticker")).replace("00670.HK", "0670.HK"),
            "market": event.get("market"),
            "evidence_date": _date(event.get("event_date")),
            "evidence_type": evidence_type,
            "metric": event.get("estimate_metric"),
            "fiscal_year": _number(event.get("fiscal_year")),
            "institution": event.get("institution"),
            "prior_evidence_date": _date(event.get("prior_event_date")),
            "current_value_native": _number(event.get("current_value_native")),
            "prior_value_native": _number(event.get("prior_value_native")),
            "change_native": _number(event.get("change_native")),
            "change_pct": _number(event.get("change_pct")),
            "direction": event.get("direction"),
            "signal_window": None,
            "signal_up_count": None,
            "signal_down_count": None,
            "signal_total_count": None,
            "rating": event.get("rating"),
            "previous_rating": event.get("previous_rating"),
            "source_quality": event.get("source_quality"),
            "source_url": event.get("source_url"),
            "information_scope": event.get("information_scope") or "dated_public_event",
            "revision_history_available": evidence_type == "dated_estimate_revision",
            "source_note": (
                "Dated public estimate/rating evidence unified from the consensus event tape. "
                "Estimate rows have same-institution prior/current values where available; "
                "rating rows are separate events and are not estimate revisions."
            ),
            "retrieved_at": retrieved_at,
        })
    return rows


def _yahoo_rows(yahoo: pd.DataFrame, *, retrieved_at: str) -> list[dict[str, Any]]:
    if yahoo.empty:
        return []
    source = yahoo.loc[yahoo["metric"].eq("eps_revision_signal")].copy()
    if source.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, signal in source.iterrows():
        up_7 = _number(signal.get("up_last_7_days"))
        down_7 = _number(signal.get("down_last_7_days"))
        up_30 = _number(signal.get("up_last_30_days"))
        down_30 = _number(signal.get("down_last_30_days"))
        for window, up, down in (("7d", up_7, down_7), ("30d", up_30, down_30)):
            if up is None and down is None:
                continue
            up_value = up or 0.0
            down_value = down or 0.0
            rows.append({
                "dataset_id": "airline_revision_evidence",
                "company": signal.get("company"),
                "ticker": str(signal.get("ticker")).replace("00670.HK", "0670.HK"),
                "market": signal.get("market"),
                "evidence_date": _date(signal.get("snapshot_date")),
                "evidence_type": "vendor_revision_signal",
                "metric": "eps_revision_signal",
                "fiscal_year": _number(signal.get("forecast_year")),
                "institution": "Yahoo Finance analyst aggregate",
                "prior_evidence_date": None,
                "current_value_native": None,
                "prior_value_native": None,
                "change_native": None,
                "change_pct": None,
                "direction": _direction_from_counts(up, down),
                "signal_window": window,
                "signal_up_count": up_value,
                "signal_down_count": down_value,
                "signal_total_count": up_value + down_value,
                "rating": None,
                "previous_rating": None,
                "source_quality": signal.get("source_quality"),
                "source_url": signal.get("source_url"),
                "information_scope": "vendor_short_horizon_snapshot",
                "revision_history_available": False,
                "source_note": (
                    "Yahoo Finance/yfinance short-horizon EPS revision count. This is an "
                    "aggregate up/down signal as of the snapshot date, without broker identity "
                    "or exact update timestamps; it is not a dated broker-vintage revision."
                ),
                "retrieved_at": retrieved_at,
            })
    return rows


def build_airline_revision_evidence(
    *,
    events: pd.DataFrame | None = None,
    yahoo: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Combine dated public events and current vendor revision signals."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    if events is None:
        events = pd.read_csv(EVENT_PATH) if EVENT_PATH.exists() else pd.DataFrame()
    if yahoo is None:
        yahoo = pd.read_csv(YAHOO_PATH) if YAHOO_PATH.exists() else pd.DataFrame()
    rows = _event_rows(events, retrieved_at=retrieved) + _yahoo_rows(yahoo, retrieved_at=retrieved)
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if result.empty:
        return result
    result["ticker"] = result["ticker"].replace(AIRLINE_TICKER_ALIASES)
    result = result.drop_duplicates(
        subset=[
            "ticker", "evidence_date", "evidence_type", "metric", "fiscal_year",
            "institution", "prior_evidence_date", "signal_window", "source_url",
        ],
    )
    return result.sort_values(
        ["evidence_date", "company", "evidence_type", "metric", "signal_window"],
        na_position="last",
    ).reset_index(drop=True)


def fetch_airline_revision_evidence() -> pd.DataFrame:
    result = build_airline_revision_evidence()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
