"""Free third-party economic calendar and consensus adapter."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Iterable

import pandas as pd
import requests

from ..domain import enrich_event_row, optional_iso_utc, payload_checksum, stable_event_id
from .http import retrying_session


CALENDAR_URL = "https://economic-calendar.tradingview.com/events"


def fetch_calendar(
    from_date: date,
    to_date: date,
    *,
    countries: Iterable[str],
    trigger_type: str,
    session: requests.Session | None = None,
    now_utc: datetime | None = None,
    timeout: int = 20,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch and normalize one calendar window.

    TradingView is a third-party expectation source. Its actual values remain
    unverified until a separate official collector confirms them.
    """
    client = session or retrying_session()
    retrieved = now_utc or datetime.now(timezone.utc)
    params = {
        "from": datetime.combine(from_date, time.min, tzinfo=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "to": datetime.combine(to_date, time.max, tzinfo=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "countries": ",".join(sorted({str(value).upper() for value in countries})),
    }
    response = client.get(
        CALENDAR_URL,
        params=params,
        headers={
            "Origin": "https://www.tradingview.com",
            "User-Agent": "AsiaMarketsEventConsensus/1.0",
            "Accept": "application/json",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    raw_rows = payload.get("result", []) if isinstance(payload, dict) else []
    if not isinstance(raw_rows, list):
        raise ValueError("TradingView calendar result is not a row array")

    rows: list[dict[str, Any]] = []
    allowed = {str(value).upper() for value in countries}
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        country = str(raw.get("country") or "").upper()
        if country not in allowed:
            continue
        scheduled = raw.get("date")
        title = str(raw.get("title") or raw.get("indicator") or "").strip()
        if not title or not scheduled:
            continue
        event_id = stable_event_id("tradingview", raw.get("id"), title, scheduled)
        row = {
            "event_id": event_id,
            "provider_event_id": str(raw.get("id") or ""),
            "country": country,
            "currency": raw.get("currency"),
            "title": title,
            "indicator": raw.get("indicator"),
            "category": raw.get("category"),
            "scheduled_at_utc": scheduled,
            "reference_period": raw.get("period") or raw.get("referenceDate"),
            "importance": raw.get("importance"),
            "forecast": raw.get("forecastRaw", raw.get("forecast")),
            "forecast_raw": raw.get("forecast"),
            "previous": raw.get("previousRaw", raw.get("previous")),
            "previous_raw": raw.get("previous"),
            "revised_previous": raw.get("revisedPrevious") or raw.get("previousRevision"),
            "actual": raw.get("actualRaw", raw.get("actual")),
            "actual_raw": raw.get("actual"),
            "unit": raw.get("unit"),
            "provider": "tradingview",
            "source_name": raw.get("source") or "TradingView Economic Calendar",
            "source_url": raw.get("source_url") or CALENDAR_URL,
            "source_timezone": raw.get("timezone") or raw.get("timeZone"),
            "provider_published_at": optional_iso_utc(
                raw.get("publishedAt") or raw.get("updatedAt")
            ),
            "payload_checksum": payload_checksum(raw),
            "first_observed_at_utc": retrieved.isoformat(),
            "retrieved_at_utc": retrieved,
            "trigger_type": trigger_type,
            "verification_status": (
                "third_party_actual_unverified"
                if raw.get("actual") is not None or raw.get("actualRaw") is not None
                else "third_party_consensus"
            ),
        }
        rows.append(enrich_event_row(row, now_utc=retrieved))

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(
            ["scheduled_at_utc", "risk_score", "country"],
            ascending=[True, False, True],
        ).reset_index(drop=True)
    health = {
        "source_id": "tradingview_calendar",
        "status": "Healthy" if not frame.empty else "Unavailable",
        "retrieved_at_utc": retrieved.isoformat(),
        "records": int(len(frame)),
        "notes": (
            "Third-party calendar/consensus; actuals require official verification."
            if not frame.empty
            else "Calendar returned no usable events."
        ),
    }
    return frame, health
