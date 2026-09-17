"""Finnhub free quote adapter used by explicit and scheduled refreshes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd
import requests

from ..domain import enrich_quote_row, payload_checksum
from .http import retrying_session

QUOTE_URL = "https://finnhub.io/api/v1/quote"


def fetch_quotes(
    instruments: Iterable[dict[str, str]],
    *,
    api_key: str,
    trigger_type: str,
    session: requests.Session | None = None,
    now_utc: datetime | None = None,
    timeout: int = 12,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    retrieved = now_utc or datetime.now(timezone.utc)
    instrument_rows = tuple(instruments)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    client = session or retrying_session()
    if not api_key:
        return pd.DataFrame(), {
            "source_id": "finnhub_quotes",
            "status": "Unavailable",
            "retrieved_at_utc": retrieved.isoformat(),
            "records": 0,
            "notes": "FINNHUB_API_KEY is not configured.",
        }

    for instrument in instrument_rows:
        symbol = str(instrument["symbol"])
        try:
            response = client.get(
                QUOTE_URL,
                params={"symbol": symbol, "token": api_key},
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            current = payload.get("c") if isinstance(payload, dict) else None
            timestamp = payload.get("t") if isinstance(payload, dict) else None
            if current in (None, 0) or not timestamp:
                errors.append(f"{symbol}: empty quote")
                continue
            observed = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
            rows.append(
                enrich_quote_row(
                    {
                        "symbol": symbol,
                        "label": instrument.get("label", symbol),
                        "asset_class": instrument.get("asset_class", ""),
                        "current": float(current),
                        "change": payload.get("d"),
                        "percent_change": payload.get("dp"),
                        "high": payload.get("h"),
                        "low": payload.get("l"),
                        "open": payload.get("o"),
                        "previous_close": payload.get("pc"),
                        "market_timestamp_utc": observed.isoformat(),
                        "retrieved_at_utc": retrieved.isoformat(),
                        "trigger_type": trigger_type,
                        "provider": "finnhub",
                        "status": "available",
                        "source_url": QUOTE_URL,
                        "payload_checksum": payload_checksum(payload),
                    }
                )
            )
        except Exception as exc:
            errors.append(f"{symbol}: {type(exc).__name__}")

    frame = pd.DataFrame(rows)
    status = "Healthy" if len(frame) == len(instrument_rows) else "Partial" if not frame.empty else "Unavailable"
    health = {
        "source_id": "finnhub_quotes",
        "status": status,
        "retrieved_at_utc": retrieved.isoformat(),
        "records": int(len(frame)),
        "notes": (
            f"US quote coverage {len(frame)}/{len(instrument_rows)}."
            + (f" Failures: {', '.join(errors[:5])}." if errors else "")
        ),
    }
    return frame, health
