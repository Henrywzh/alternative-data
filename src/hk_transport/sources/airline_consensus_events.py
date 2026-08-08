"""Unified point-in-time consensus, estimate-revision and rating events."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..config import AIRLINE_TICKER_ALIASES, NORMALIZED_DIR


OUTPUT_PATH = NORMALIZED_DIR / "airline_consensus_events.csv"

INPUT_PATHS = {
    "hk_profit": NORMALIZED_DIR / "airline_hk_forecast_revisions.csv",
    "ashare_eps": NORMALIZED_DIR / "airline_sell_side_forecast_revisions.csv",
    "ashare_revenue": NORMALIZED_DIR / "airline_sell_side_revenue_revisions.csv",
    "ratings": NORMALIZED_DIR / "airline_cninfo_rating_events.csv",
}

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "event_date", "event_type",
    "estimate_metric", "fiscal_year", "institution", "prior_event_date",
    "current_value_native", "prior_value_native", "change_native", "change_pct",
    "direction", "rating", "previous_rating", "target_price_low_native",
    "target_price_high_native", "source_quality", "source_url", "information_scope",
    "source_note", "retrieved_at",
]


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _date(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _direction(change: Any) -> str:
    value = _number(change)
    if value is None:
        return "unknown"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def _estimate_event(
    row: pd.Series,
    *,
    metric: str,
    market: str,
    current_column: str,
    prior_column: str,
    change_column: str,
    change_pct_column: str,
    retrieved_at: str,
) -> dict[str, Any] | None:
    event_date = _date(row.get("report_date"))
    prior_date = _date(row.get("prior_report_date"))
    current = _number(row.get(current_column))
    prior = _number(row.get(prior_column))
    change = _number(row.get(change_column))
    change_pct = _number(row.get(change_pct_column))
    if not event_date or not prior_date or current is None or prior is None:
        return None
    return {
        "dataset_id": "airline_consensus_events",
        "company": row.get("company"),
        "ticker": str(row.get("ticker")).replace("00670.HK", "0670.HK"),
        "market": market,
        "event_date": event_date,
        "event_type": "estimate_revision",
        "estimate_metric": metric,
        "fiscal_year": _number(row.get("fiscal_year")),
        "institution": row.get("institution"),
        "prior_event_date": prior_date,
        "current_value_native": current,
        "prior_value_native": prior,
        "change_native": change,
        "change_pct": change_pct,
        "direction": _direction(change),
        "rating": None,
        "previous_rating": None,
        "target_price_low_native": None,
        "target_price_high_native": None,
        "source_quality": row.get("source_quality"),
        "source_url": row.get("report_url") or row.get("source_url"),
        "information_scope": "broker_report_vintage",
        "source_note": (
            "Unified dated same-institution/same-fiscal-year estimate revision. "
            "The source feed is sparse and is not a complete consensus-vintage tape."
        ),
        "retrieved_at": retrieved_at,
    }


def _revision_events(
    frame: pd.DataFrame,
    *,
    market: str,
    metric_columns: tuple[tuple[str, str, str, str], ...],
    retrieved_at: str,
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        for metric, current, prior, change, change_pct in metric_columns:
            event = _estimate_event(
                row,
                metric=metric,
                market=market,
                current_column=current,
                prior_column=prior,
                change_column=change,
                change_pct_column=change_pct,
                retrieved_at=retrieved_at,
            )
            if event is not None:
                rows.append(event)
    return rows


def _rating_events(frame: pd.DataFrame, *, retrieved_at: str) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        event_date = _date(row.get("report_date"))
        if not event_date:
            continue
        direction = row.get("rating_direction")
        direction = direction if direction in {"upgrade", "downgrade", "maintain_or_new"} else "unknown"
        rows.append({
            "dataset_id": "airline_consensus_events",
            "company": row.get("company"),
            "ticker": str(row.get("ticker")).replace("00670.HK", "0670.HK"),
            "market": "CN_A",
            "event_date": event_date,
            "event_type": "rating_event",
            "estimate_metric": "rating",
            "fiscal_year": None,
            "institution": row.get("institution"),
            "prior_event_date": None,
            "current_value_native": None,
            "prior_value_native": None,
            "change_native": None,
            "change_pct": None,
            "direction": direction,
            "rating": row.get("rating"),
            "previous_rating": row.get("previous_rating"),
            "target_price_low_native": _number(row.get("target_price_low_native")),
            "target_price_high_native": _number(row.get("target_price_high_native")),
            "source_quality": row.get("source_quality"),
            "source_url": row.get("source_url"),
            "information_scope": row.get("history_scope") or "queried_public_report_dates",
            "source_note": (
                "Unified dated Cninfo investment-rating event. This is queried-date "
                "coverage and does not imply a complete daily rating or estimate history."
            ),
            "retrieved_at": retrieved_at,
        })
    return rows


def build_airline_consensus_events(
    *,
    inputs: dict[str, pd.DataFrame] | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build the unified dated event timeline from existing public layers."""
    retrieved = retrieved_at or pd.Timestamp.utcnow().isoformat()
    frames = inputs or {
        key: (pd.read_csv(path) if path.exists() else pd.DataFrame())
        for key, path in INPUT_PATHS.items()
    }
    rows: list[dict[str, Any]] = []
    rows.extend(_revision_events(
        frames.get("hk_profit", pd.DataFrame()),
        market="HK",
        metric_columns=(
            ("net_profit", "net_profit_native_mn", "prior_net_profit_native_mn", "net_profit_change_native_mn", "net_profit_change_pct"),
            ("eps", "eps_native", "prior_eps_native", "eps_change_native", "eps_change_pct"),
        ),
        retrieved_at=retrieved,
    ))
    rows.extend(_revision_events(
        frames.get("ashare_eps", pd.DataFrame()),
        market="CN_A",
        metric_columns=(("eps", "eps_native", "prior_eps_native", "eps_change_native", "eps_change_pct"),),
        retrieved_at=retrieved,
    ))
    rows.extend(_revision_events(
        frames.get("ashare_revenue", pd.DataFrame()),
        market="CN_A",
        metric_columns=(("revenue", "revenue_forecast_native_mn", "prior_revenue_forecast_native_mn", "revenue_change_native_mn", "revenue_change_pct"),),
        retrieved_at=retrieved,
    ))
    rows.extend(_rating_events(frames.get("ratings", pd.DataFrame()), retrieved_at=retrieved))
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if result.empty:
        return _empty()
    result["ticker"] = result["ticker"].replace(AIRLINE_TICKER_ALIASES)
    result["event_date"] = pd.to_datetime(result["event_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result["prior_event_date"] = pd.to_datetime(result["prior_event_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result = result.drop_duplicates(
        subset=["ticker", "event_date", "event_type", "estimate_metric", "fiscal_year", "institution", "source_url", "rating"]
    )
    return result.sort_values(["event_date", "company", "event_type", "institution"], na_position="last").reset_index(drop=True)


def fetch_airline_consensus_events() -> pd.DataFrame:
    result = build_airline_consensus_events()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
