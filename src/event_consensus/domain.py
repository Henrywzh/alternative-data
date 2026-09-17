"""Pure normalization, checkpoint and scoring logic."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any

import pandas as pd

from .config import EVENT_FAMILY_RULES


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: Any) -> str | None:
    if value in (None, ""):
        return None
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp.isoformat()


def optional_iso_utc(value: Any) -> str | None:
    """Best-effort timestamp normalization for optional provider metadata."""
    try:
        return iso_utc(value)
    except (TypeError, ValueError, OverflowError):
        return None


def numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if math.isnan(number) else number
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "—", "N/A", "n/a", "null"}:
        return None
    text = re.sub(r"[%$€£¥]", "", text)
    multiplier = 1.0
    if text[-1:].upper() in {"K", "M", "B", "T"}:
        multiplier = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[text[-1].upper()]
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def classify_event_family(title: str) -> str:
    lowered = str(title or "").casefold()
    for family, needles in EVENT_FAMILY_RULES:
        if any(needle in lowered for needle in needles):
            return family
    return "other"


def checkpoint_stage(
    scheduled_at_utc: Any,
    *,
    now_utc: datetime | pd.Timestamp | str | None = None,
) -> str:
    scheduled = pd.Timestamp(scheduled_at_utc)
    if pd.isna(scheduled):
        return "unknown"
    if scheduled.tzinfo is None:
        scheduled = scheduled.tz_localize("UTC")
    else:
        scheduled = scheduled.tz_convert("UTC")
    now = pd.Timestamp(now_utc or utc_now())
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    else:
        now = now.tz_convert("UTC")
    minutes = (scheduled - now).total_seconds() / 60
    if minutes > 5 * 24 * 60:
        return "watch"
    if minutes > 24 * 60:
        return "t_minus_5d"
    if minutes > 60:
        return "t_minus_1d"
    if minutes > 0:
        return "t_minus_60m"
    elapsed = -minutes
    if elapsed <= 2:
        return "t_plus_2m"
    if elapsed <= 30:
        return "t_plus_30m"
    if elapsed <= 18 * 60:
        return "end_of_day"
    return "t_plus_1d"


def stable_event_id(provider: str, provider_event_id: Any, title: str, scheduled: Any) -> str:
    provider_id = str(provider_event_id or "").strip()
    if provider_id:
        return f"{provider}:{provider_id}"
    payload = "|".join(
        (
            provider,
            str(title or "").strip().casefold(),
            iso_utc(scheduled) or "",
        )
    )
    return f"{provider}:{hashlib.sha256(payload.encode()).hexdigest()[:20]}"


def payload_checksum(payload: Any) -> str:
    """Return a deterministic checksum without persisting the raw payload."""
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def quote_observation_signature(row: dict[str, Any]) -> str:
    """Hash quote content while excluding transport timestamps and trigger."""
    fields = (
        "provider",
        "symbol",
        "current",
        "change",
        "percent_change",
        "high",
        "low",
        "open",
        "previous_close",
        "market_timestamp_utc",
    )
    return payload_checksum({field: row.get(field) for field in fields})


def quote_snapshot_id(row: dict[str, Any]) -> str:
    payload = {
        "provider": row.get("provider"),
        "symbol": row.get("symbol"),
        "retrieved_at_utc": row.get("retrieved_at_utc"),
        "trigger_type": row.get("trigger_type"),
        "signature": row.get("observation_signature") or quote_observation_signature(row),
    }
    return payload_checksum(payload)[:24]


def enrich_quote_row(row: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    enriched["retrieved_at_utc"] = iso_utc(enriched.get("retrieved_at_utc") or utc_now())
    enriched["market_timestamp_utc"] = iso_utc(
        enriched.get("market_timestamp_utc") or enriched["retrieved_at_utc"]
    )
    enriched["observation_signature"] = quote_observation_signature(enriched)
    enriched["snapshot_id"] = quote_snapshot_id(enriched)
    return enriched


def component_observation_signature(row: dict[str, Any]) -> str:
    fields = (
        "source_id",
        "series_id",
        "event_family",
        "component_id",
        "reference_period",
        "latest_value",
        "previous_value",
        "mom_change",
        "mom_pct",
        "yoy_change",
        "yoy_pct",
        "payroll_change",
        "mom_change_pp",
        "yoy_change_pp",
    )
    return payload_checksum({field: row.get(field) for field in fields})


def component_snapshot_id(row: dict[str, Any]) -> str:
    payload = {
        "source_id": row.get("source_id"),
        "series_id": row.get("series_id"),
        "retrieved_at_utc": row.get("retrieved_at_utc"),
        "trigger_type": row.get("trigger_type"),
        "signature": row.get("observation_signature") or component_observation_signature(row),
    }
    return payload_checksum(payload)[:24]


def observation_signature(row: dict[str, Any]) -> str:
    """Hash event content without retrieval time for scheduled deduplication."""
    fields = (
        "event_id",
        "snapshot_stage",
        "forecast",
        "forecast_raw",
        "previous",
        "previous_raw",
        "revised_previous",
        "actual",
        "actual_raw",
        "unit",
        "scheduled_at_utc",
    )
    payload = {field: row.get(field) for field in fields}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def snapshot_id(row: dict[str, Any]) -> str:
    payload = {
        "event_id": row.get("event_id"),
        "retrieved_at_utc": row.get("retrieved_at_utc"),
        "trigger_type": row.get("trigger_type"),
        "signature": observation_signature(row),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:24]


def _gap_score(forecast: float | None, previous: float | None) -> float:
    if forecast is None or previous is None:
        return 0.0
    scale = max(abs(previous), abs(forecast), 1.0)
    return min(10.0, abs(forecast - previous) / scale * 40.0)


def _surprise_score(actual: float | None, forecast: float | None) -> float:
    if actual is None or forecast is None:
        return 0.0
    scale = max(abs(forecast), 1.0)
    return min(15.0, abs(actual - forecast) / scale * 50.0)


def risk_score_parts(row: dict[str, Any], *, now_utc: Any = None) -> dict[str, float]:
    """Explainable provisional event score; unavailable factors stay absent."""
    raw_importance = numeric(row.get("importance"))
    # TradingView currently exposes -1/0/1. Unknown providers are clamped into
    # the same three-level scale instead of being allowed to inflate the score.
    level = 2 if raw_importance is None else max(1, min(3, int(raw_importance) + 2))
    importance = {1: 15.0, 2: 30.0, 3: 45.0}[level]

    scheduled = pd.Timestamp(row.get("scheduled_at_utc"))
    now = pd.Timestamp(now_utc or utc_now())
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    else:
        now = now.tz_convert("UTC")
    if pd.isna(scheduled):
        proximity = 0.0
    else:
        scheduled = scheduled.tz_localize("UTC") if scheduled.tzinfo is None else scheduled.tz_convert("UTC")
        hours = abs((scheduled - now).total_seconds()) / 3600
        proximity = 20.0 if hours <= 1 else 16.0 if hours <= 24 else 10.0 if hours <= 5 * 24 else 4.0

    forecast = numeric(row.get("forecast"))
    previous = numeric(row.get("previous"))
    actual = numeric(row.get("actual"))
    family = str(row.get("event_family") or "other")
    watchlist = 10.0 if family in {"cpi", "ppi", "pce", "payrolls", "fomc"} else 6.0 if family in {"gdp", "retail_sales", "pmi", "china_activity", "trade"} else 2.0
    return {
        "risk_importance": importance,
        "risk_proximity": proximity,
        "risk_consensus": 10.0 if forecast is not None else 0.0,
        "risk_forecast_gap": round(_gap_score(forecast, previous), 2),
        "risk_actual_surprise": round(_surprise_score(actual, forecast), 2),
        "risk_watchlist": watchlist,
    }


def enrich_event_row(row: dict[str, Any], *, now_utc: Any = None) -> dict[str, Any]:
    enriched = dict(row)
    enriched["event_family"] = str(
        enriched.get("event_family") or classify_event_family(str(enriched.get("title") or ""))
    )
    enriched["scheduled_at_utc"] = iso_utc(enriched.get("scheduled_at_utc"))
    enriched["retrieved_at_utc"] = iso_utc(enriched.get("retrieved_at_utc") or utc_now())
    enriched["snapshot_stage"] = checkpoint_stage(
        enriched.get("scheduled_at_utc"),
        now_utc=now_utc,
    )
    enriched["forecast"] = numeric(enriched.get("forecast"))
    enriched["previous"] = numeric(enriched.get("previous"))
    enriched["actual"] = numeric(enriched.get("actual"))
    parts = risk_score_parts(enriched, now_utc=now_utc)
    enriched.update(parts)
    enriched["risk_score"] = round(min(100.0, sum(parts.values())), 1)
    if enriched["actual"] is not None and enriched["forecast"] is not None:
        enriched["surprise"] = enriched["actual"] - enriched["forecast"]
    else:
        enriched["surprise"] = None
    enriched["observation_signature"] = observation_signature(enriched)
    enriched["snapshot_id"] = snapshot_id(enriched)
    return enriched
