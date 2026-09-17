"""Optional local Futu OpenD fast lane.

The adapter is intentionally optional. It imports futu-api lazily and reports
an explicit source-health state when the SDK or local OpenD service is absent.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

import pandas as pd

from ..domain import enrich_quote_row, payload_checksum

FUTU_SYMBOLS: tuple[dict[str, str], ...] = (
    {"code": "US.SPY", "symbol": "SPY", "label": "S&P 500", "asset_class": "US equity"},
    {"code": "US.QQQ", "symbol": "QQQ", "label": "Nasdaq 100", "asset_class": "US equity"},
    {"code": "US.SOXX", "symbol": "SOXX", "label": "Semiconductors", "asset_class": "US equity"},
    {"code": "US.IGV", "symbol": "IGV", "label": "Software", "asset_class": "US equity"},
    {"code": "US.TLT", "symbol": "TLT", "label": "Long Treasuries", "asset_class": "rates"},
    {"code": "US.HYG", "symbol": "HYG", "label": "High yield credit", "asset_class": "credit"},
    {"code": "US.GLD", "symbol": "GLD", "label": "Gold", "asset_class": "commodity"},
    {"code": "US.USO", "symbol": "USO", "label": "Oil", "asset_class": "commodity"},
    {"code": "US.UUP", "symbol": "UUP", "label": "US dollar", "asset_class": "FX"},
    {"code": "HK.07709", "symbol": "7709.HK", "label": "SK Hynix HK", "asset_class": "HK equity"},
)


def fetch_futu_quotes(
    *,
    trigger_type: str,
    now_utc: datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    retrieved = now_utc or datetime.now(timezone.utc)
    try:
        from futu import OpenQuoteContext, RET_OK
    except ImportError:
        return pd.DataFrame(), {
            "source_id": "futu_opend",
            "status": "Not configured",
            "retrieved_at_utc": retrieved.isoformat(),
            "records": 0,
            "notes": "Optional futu-api SDK is not installed; Finnhub remains the quote fallback.",
        }

    host = os.environ.get("FUTU_OPEND_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("FUTU_OPEND_PORT", "11111"))
    except ValueError:
        port = 11111
    context = None
    try:
        context = OpenQuoteContext(host=host, port=port)
        status, payload = context.get_market_snapshot(
            [row["code"] for row in FUTU_SYMBOLS]
        )
        if status != RET_OK or not isinstance(payload, pd.DataFrame):
            detail = str(payload)[:160]
            return pd.DataFrame(), {
                "source_id": "futu_opend",
                "status": "Unavailable",
                "retrieved_at_utc": retrieved.isoformat(),
                "records": 0,
                "notes": f"OpenD snapshot request failed: {detail}",
            }
        by_code = {row["code"]: row for row in FUTU_SYMBOLS}
        rows: list[dict[str, Any]] = []
        for raw in payload.to_dict("records"):
            spec = by_code.get(str(raw.get("code")))
            if spec is None:
                continue
            current = pd.to_numeric(raw.get("last_price"), errors="coerce")
            previous = pd.to_numeric(raw.get("last_close"), errors="coerce")
            if pd.isna(current) or float(current) <= 0:
                continue
            percent_change = (
                None
                if pd.isna(previous) or float(previous) == 0
                else (float(current) / float(previous) - 1) * 100
            )
            update_time = pd.to_datetime(raw.get("update_time"), errors="coerce")
            if pd.isna(update_time):
                observed = retrieved.isoformat()
            elif update_time.tzinfo is None:
                observed = update_time.tz_localize("Asia/Hong_Kong").tz_convert("UTC").isoformat()
            else:
                observed = update_time.tz_convert("UTC").isoformat()
            rows.append(
                enrich_quote_row(
                    {
                        "symbol": spec["symbol"],
                        "label": spec["label"],
                        "asset_class": spec["asset_class"],
                        "current": float(current),
                        "change": None if pd.isna(previous) else float(current) - float(previous),
                        "percent_change": percent_change,
                        "high": raw.get("high_price"),
                        "low": raw.get("low_price"),
                        "open": raw.get("open_price"),
                        "previous_close": None if pd.isna(previous) else float(previous),
                        "market_timestamp_utc": observed,
                        "retrieved_at_utc": retrieved.isoformat(),
                        "trigger_type": trigger_type,
                        "provider": "futu_opend",
                        "status": "available",
                        "source_url": "futu://opend/get_market_snapshot",
                        "payload_checksum": payload_checksum(raw),
                    }
                )
            )
        frame = pd.DataFrame(rows)
        return frame, {
            "source_id": "futu_opend",
            "status": "Healthy" if not frame.empty else "Unavailable",
            "retrieved_at_utc": retrieved.isoformat(),
            "records": int(len(frame)),
            "notes": (
                f"Local OpenD quote coverage {len(frame)}/{len(FUTU_SYMBOLS)}. "
                "Korean cash equities are outside Futu's supported market set."
            ),
        }
    except Exception as exc:
        return pd.DataFrame(), {
            "source_id": "futu_opend",
            "status": "Unavailable",
            "retrieved_at_utc": retrieved.isoformat(),
            "records": 0,
            "notes": f"{type(exc).__name__}: OpenD is not reachable at {host}:{port}.",
        }
    finally:
        if context is not None:
            context.close()
