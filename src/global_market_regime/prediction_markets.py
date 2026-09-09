"""Polymarket FOMC odds. This is a prediction-market price, not CME FedWatch."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from .config import FOMC_HIKE_ENTER, FOMC_HIKE_ESCALATE, FOMC_HIKE_EXIT, POLYMARKET_CLOB_HISTORY_URL, POLYMARKET_SEARCH_URL
from .signals import classify_level_states
from .storage import utc_now

FOMC_BUCKETS = ("hold", "hike_25", "hike_50", "cut_25", "cut_50")


def _json_list(value: Any) -> list[Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return list(value) if isinstance(value, (list, tuple)) else None


def _yes_index(market: dict[str, Any]) -> int | None:
    outcomes = _json_list(market.get("outcomes"))
    if not outcomes:
        return None
    try:
        return [str(item).lower() for item in outcomes].index("yes")
    except ValueError:
        return None


def _yes_price(market: dict[str, Any]) -> float | None:
    outcomes = _json_list(market.get("outcomes"))
    prices = _json_list(market.get("outcomePrices"))
    if not outcomes or not prices or len(outcomes) != len(prices):
        return None
    try:
        yes_idx = _yes_index(market)
        if yes_idx is None:
            return None
        price = float(prices[yes_idx])
        return price * 100.0 if math.isfinite(price) and 0.0 <= price <= 1.0 else None
    except (ValueError, TypeError, IndexError):
        return None


def _token_id(market: dict[str, Any]) -> str | None:
    tokens = _json_list(market.get("clobTokenIds"))
    yes_idx = _yes_index(market)
    if not tokens or yes_idx is None or yes_idx >= len(tokens):
        return None
    token = str(tokens[yes_idx]).strip()
    return token or None


def classify_fomc_question(question: str) -> str | None:
    text = question.lower()
    if "no change" in text:
        return "hold"
    if "decrease" in text and "50" in text:
        return "cut_50"
    if "decrease" in text and "25" in text:
        return "cut_25"
    if "increase" in text and "50" in text:
        return "hike_50"
    if "increase" in text and "25" in text:
        return "hike_25"
    return None


def select_next_fomc_event(events: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any] | None:
    now = now or datetime.now(timezone.utc)
    today = now.date()
    candidates: list[dict[str, Any]] = []
    for event in events:
        slug = str(event.get("slug") or "")
        title = str(event.get("title") or "")
        if "fed-decision" not in slug and "fed decision" not in title.lower():
            continue
        if event.get("closed") is True:
            continue
        end_raw = str(event.get("endDate") or "")[:10]
        try:
            end_date = datetime.strptime(end_raw, "%Y-%m-%d").date()
        except ValueError:
            continue
        if end_date < today:
            continue
        event = dict(event)
        event["_end_date"] = end_date
        candidates.append(event)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item["_end_date"])[0]


def parse_fomc_snapshot(event: dict[str, Any], *, retrieved_at: str | None = None) -> dict[str, Any]:
    retrieved_at = retrieved_at or utc_now()
    buckets: dict[str, float] = {}
    token_by_bucket: dict[str, str] = {}
    for market in event.get("markets") or []:
        bucket = classify_fomc_question(str(market.get("question") or ""))
        price = _yes_price(market)
        token = _token_id(market)
        if bucket is None or price is None:
            continue
        buckets[bucket] = price
        if token:
            token_by_bucket[bucket] = token
    distribution_complete = all(bucket in buckets for bucket in FOMC_BUCKETS)
    hike = (
        float(buckets["hike_25"] + buckets["hike_50"])
        if distribution_complete
        else None
    )
    cut = (
        float(buckets["cut_25"] + buckets["cut_50"])
        if distribution_complete
        else None
    )
    hold = float(buckets["hold"]) if "hold" in buckets else None
    return {
        "event_id": str(event.get("id") or ""),
        "slug": str(event.get("slug") or ""),
        "title": str(event.get("title") or ""),
        "meeting_date": str(event.get("endDate") or "")[:10],
        "hike_prob": hike,
        "hold_prob": hold,
        "cut_prob": cut,
        "distribution_complete": distribution_complete,
        "observed_buckets": sorted(buckets),
        "hike_25": buckets.get("hike_25"),
        "hike_50": buckets.get("hike_50"),
        "cut_25": buckets.get("cut_25"),
        "cut_50": buckets.get("cut_50"),
        "token_hike_25": token_by_bucket.get("hike_25"),
        "token_hike_50": token_by_bucket.get("hike_50"),
        "token_cut_25": token_by_bucket.get("cut_25"),
        "token_cut_50": token_by_bucket.get("cut_50"),
        "token_hold": token_by_bucket.get("hold"),
        "retrieved_at": retrieved_at,
        "source": "polymarket",
        "caveat": "Prediction-market price, not CME FedWatch or Atlanta Fed SOFR odds.",
    }


def fetch_fomc_event(*, query: str = "Fed Decision") -> dict[str, Any] | None:
    response = requests.get(POLYMARKET_SEARCH_URL, params={"q": query}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    events = payload.get("events") or []
    return select_next_fomc_event(events)


def fetch_token_history(token_id: str) -> pd.DataFrame:
    response = requests.get(
        POLYMARKET_CLOB_HISTORY_URL,
        params={"market": token_id, "interval": "max"},
        timeout=30,
    )
    response.raise_for_status()
    history = response.json().get("history") or []
    if not history:
        return pd.DataFrame(columns=["date", "value"])
    frame = pd.DataFrame(history)
    if not {"t", "p"}.issubset(frame.columns):
        return pd.DataFrame(columns=["date", "value"])
    frame["_timestamp"] = pd.to_datetime(
        pd.to_numeric(frame["t"], errors="coerce"),
        unit="s",
        utc=True,
        errors="coerce",
    )
    frame["value"] = pd.to_numeric(frame["p"], errors="coerce") * 100.0
    frame = frame[
        frame["_timestamp"].notna()
        & frame["value"].between(0.0, 100.0, inclusive="both")
    ].copy()
    if frame.empty:
        return pd.DataFrame(columns=["date", "value"])
    frame["date"] = frame["_timestamp"].dt.strftime("%Y-%m-%d")
    daily = (
        frame.sort_values("_timestamp", kind="mergesort")
        .groupby("date", as_index=False)
        .last()
    )
    return daily[["date", "value"]]


def fomc_probability_history(
    snapshot: dict[str, Any],
    hold_history: pd.DataFrame,
    hike25_history: pd.DataFrame,
    *,
    hike50_history: pd.DataFrame | None = None,
    cut25_history: pd.DataFrame | None = None,
    cut50_history: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build bucket history from each outcome token's own observed prices.

    Outcome tokens trade independently and may not print on the same dates.
    The outer calendar is therefore forward-filled per token after that
    token's first observation. Current snapshot prices are never projected
    backwards into historical rows.
    """
    histories = {
        "hold_prob": hold_history,
        "hike_25": hike25_history,
        "hike_50": hike50_history,
        "cut_25": cut25_history,
        "cut_50": cut50_history,
    }
    # The five contracts are intended to form one exhaustive distribution.
    # If one token is absent or its history fetch failed, treating that bucket
    # as zero would manufacture a policy signal.
    if any(history is None or history.empty for history in histories.values()):
        return pd.DataFrame()
    parts: list[pd.DataFrame] = []
    for field, history in histories.items():
        part = history[["date", "value"]].rename(columns={"value": field}).copy()
        parts.append(part)
    if not parts:
        return pd.DataFrame()
    merged = parts[0]
    for part in parts[1:]:
        merged = pd.merge(merged, part, on="date", how="outer")
    merged = merged.sort_values("date").reset_index(drop=True)
    if merged.empty:
        return pd.DataFrame()
    probability_fields = [field for field in histories if field in merged.columns]
    merged[probability_fields] = merged[probability_fields].ffill()
    complete = merged[probability_fields].notna().all(axis=1)
    bounded = merged[probability_fields].apply(
        lambda series: pd.to_numeric(series, errors="coerce").between(
            0.0, 100.0, inclusive="both"
        )
    ).all(axis=1)
    merged = merged[complete & bounded].copy()
    if merged.empty:
        return pd.DataFrame()
    hike_fields = [field for field in ("hike_25", "hike_50") if field in merged.columns]
    cut_fields = [field for field in ("cut_25", "cut_50") if field in merged.columns]
    merged["hike_prob"] = (
        merged[hike_fields].sum(axis=1, min_count=1) if hike_fields else pd.NA
    )
    merged["cut_prob"] = (
        merged[cut_fields].sum(axis=1, min_count=1) if cut_fields else pd.NA
    )
    if "hold_prob" not in merged.columns:
        merged["hold_prob"] = pd.NA
    merged["event_id"] = snapshot.get("event_id")
    merged["meeting_date"] = snapshot.get("meeting_date")
    merged["slug"] = snapshot.get("slug")
    merged["source"] = "polymarket"
    merged["distribution_complete"] = True
    return merged.reset_index(drop=True)


def classify_fomc_states(history: pd.DataFrame) -> pd.DataFrame:
    if history is None or history.empty:
        return pd.DataFrame()
    source = history.copy()
    source["date"] = pd.to_datetime(source["date"], errors="coerce")
    frame = source.rename(columns={"hike_prob": "value"})[["date", "value", "meeting_date"]].copy()
    classified = classify_level_states(
        frame,
        enter=FOMC_HIKE_ENTER,
        exit=FOMC_HIKE_EXIT,
        escalate=FOMC_HIKE_ESCALATE,
        reset_on="meeting_date",
    )
    classified["date"] = pd.to_datetime(classified["date"], errors="coerce")
    return classified.merge(source, on="date", how="left", suffixes=("", "_src"))
