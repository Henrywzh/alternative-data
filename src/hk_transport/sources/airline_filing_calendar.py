"""Point-in-time discovery calendar for mainland airline interim reports.

The 10jqka calendar is used only to discover scheduled disclosure dates.  It
is not treated as the issuer filing itself: an actual disclosure date and the
official Cninfo/SSE document must supersede the scheduled row when available.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, NORMALIZED_DIR


FILING_UNIVERSE: dict[str, dict[str, str]] = {
    "601111": {"ticker": "0753.HK / 601111.SH", "company": "Air China"},
    "600029": {"ticker": "01055.HK / 600029.SH", "company": "China Southern Airlines"},
    "600115": {"ticker": "0670.HK / 600115.SH", "company": "China Eastern Airlines"},
    "601021": {"ticker": "601021.SH", "company": "Spring Airlines"},
    "603885": {"ticker": "603885.SH", "company": "Juneyao Airlines"},
    "600221": {"ticker": "600221.SH", "company": "Hainan Airlines Holdings"},
}

FILING_CALENDAR_COLUMNS = [
    "dataset_id",
    "ticker",
    "company",
    "symbol",
    "statement_period",
    "snapshot_date",
    "first_scheduled_date",
    "changed_scheduled_date",
    "actual_disclosure_date",
    "calendar_status",
    "source_quality",
    "source_url",
    "source_note",
    "retrieved_at",
]


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_date(value: Any) -> str | None:
    text = str(value).strip()
    if not text or text in {"-", "--", "nan", "NaT"}:
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def parse_filing_calendar_html(
    payload: bytes,
    *,
    symbol: str,
    company: str,
    snapshot_date: str | None = None,
    source_url: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse the current 2026 interim-report schedule from a 10jqka page."""
    text = payload.decode("gb18030", errors="replace")
    tables = pd.read_html(StringIO(text))
    required = {"首次预约时间", "变更时间", "实际披露时间"}
    table = next(
        (frame for frame in tables if required.issubset(set(frame.columns))),
        None,
    )
    if table is None:
        raise ValueError("filing calendar page did not contain the expected schedule table")

    current = table.loc[
        table["首次预约时间"].astype(str).str.startswith("2026-")
    ].copy()
    if current.empty:
        raise ValueError("filing calendar page did not contain a 2026 scheduled row")
    row = current.iloc[0]
    first_date = _clean_date(row["首次预约时间"])
    changed_date = _clean_date(row["变更时间"])
    actual_date = _clean_date(row["实际披露时间"])
    snap = snapshot_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    retrieved = retrieved_at or _retrieved_at()
    status = "released" if actual_date else "scheduled"
    result = pd.DataFrame(
        [
            {
                "dataset_id": "airline_filing_calendar",
                "ticker": FILING_UNIVERSE.get(symbol, {}).get("ticker", symbol),
                "company": company,
                "symbol": symbol,
                "statement_period": "1H2026",
                "snapshot_date": snap,
                "first_scheduled_date": first_date,
                "changed_scheduled_date": changed_date,
                "actual_disclosure_date": actual_date,
                "calendar_status": status,
                "source_quality": "public_discovery",
                "source_url": source_url or f"https://data.10jqka.com.cn/financial/yypl/op/code/code/{symbol}/",
                "source_note": (
                    "10jqka public disclosure-calendar discovery row for 1H2026. "
                    "Scheduled date is not the actual issuer filing date; confirm against SSE/Cninfo."
                ),
                "retrieved_at": retrieved,
            }
        ],
        columns=FILING_CALENDAR_COLUMNS,
    )
    return result


def fetch_airline_filing_calendar(
    *,
    symbols: dict[str, dict[str, str]] | None = None,
    snapshot_date: str | None = None,
) -> pd.DataFrame:
    """Fetch and persist the six-name 1H2026 disclosure calendar."""
    universe = symbols or FILING_UNIVERSE
    retrieved = _retrieved_at()
    session = requests.Session()
    frames: list[pd.DataFrame] = []
    for symbol, metadata in universe.items():
        url = f"https://data.10jqka.com.cn/financial/yypl/op/code/code/{symbol}/"
        response = session.get(url, headers=DEFAULT_HEADERS, timeout=max(DEFAULT_TIMEOUT, 30))
        response.raise_for_status()
        frames.append(
            parse_filing_calendar_html(
                response.content,
                symbol=symbol,
                company=metadata["company"],
                snapshot_date=snapshot_date,
                source_url=url,
                retrieved_at=retrieved,
            )
        )
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=FILING_CALENDAR_COLUMNS)
    result.to_csv(NORMALIZED_DIR / "airline_filing_calendar.csv", index=False)
    return result


def source_path() -> Path:
    return NORMALIZED_DIR / "airline_filing_calendar.csv"
