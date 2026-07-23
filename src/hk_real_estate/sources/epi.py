"""Scratch ingestion for 28Hse's weekly EPI and ERI indices.

28Hse exposes the historical query through a first-party form endpoint.  The
response is a JSON envelope whose ``results`` member is an HTML table, so this
module intentionally stores the response before doing the small HTML parse.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import (
    DEFAULT_HEADERS,
    HSE28_EPI_HISTORY_ACTION_URL,
    HSE28_EPI_HISTORY_URL,
    HSE28_EPI_URL,
)
from ..storage import save_raw_snapshot


def _parse_period(value: str) -> tuple[str | None, str | None]:
    """Return the start/end ISO dates from ``YYYY/MM/DD - YYYY/MM/DD``."""
    dates = re.findall(r"\d{4}/\d{1,2}/\d{1,2}", value or "")
    if len(dates) != 2:
        return None, None
    parsed = [pd.to_datetime(item, format="%Y/%m/%d", errors="coerce") for item in dates]
    if any(pd.isna(item) for item in parsed):
        return None, None
    return parsed[0].strftime("%Y-%m-%d"), parsed[1].strftime("%Y-%m-%d")


def parse_epi_history_html(html: str, index_type: str) -> pd.DataFrame:
    soup = BeautifulSoup(html or "", "html.parser")
    records: list[dict[str, Any]] = []
    for row in soup.select("tr.epi_historical_row"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
        if len(cells) < 2:
            continue
        period_start, period_end = _parse_period(cells[0])
        value = pd.to_numeric(cells[1].replace(",", ""), errors="coerce")
        if not period_start or pd.isna(value):
            continue
        records.append(
            {
                "date": period_start,
                "period_start": period_start,
                "period_end": period_end,
                "index_type": index_type,
                "index_value": float(value),
                "source_platform": "28Hse",
            }
        )
    columns = [
        "date",
        "period_start",
        "period_end",
        "index_type",
        "index_value",
        "source_platform",
    ]
    return pd.DataFrame(records, columns=columns).drop_duplicates(
        subset=["index_type", "period_start"], keep="last"
    ).sort_values(["index_type", "period_start"]).reset_index(drop=True)


def fetch_28hse_epi_eri(*, start_date: str = "2016-01-01", end_date: str | None = None) -> pd.DataFrame:
    """Fetch all-HK weekly EPI and ERI history as one normalized frame."""
    end_date = end_date or date.today().isoformat()
    landing = requests.get(HSE28_EPI_URL, headers=DEFAULT_HEADERS, timeout=30)
    landing.raise_for_status()

    payloads: dict[str, Any] = {"landing_html": landing.text}
    frames = []
    for code, label in (("BUY", "EPI"), ("RENT", "ERI")):
        response = requests.post(
            HSE28_EPI_HISTORY_ACTION_URL,
            headers={**DEFAULT_HEADERS, "Referer": HSE28_EPI_HISTORY_URL},
            data={
                "action": "showHistoricalData",
                "buy_rent": code,
                "district": "ALL_HK",
                "start_date": start_date,
                "end_date": end_date,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        html = ((payload.get("data") or {}).get("results") or "")
        payloads[code.lower()] = payload
        frames.append(parse_epi_history_html(html, label))

    raw_path = save_raw_snapshot(
        "hse28_epi_eri",
        json.dumps(payloads, ensure_ascii=False),
        file_ext="json",
        source_url=HSE28_EPI_HISTORY_ACTION_URL,
    )
    result = pd.concat(frames, ignore_index=True)
    result.attrs.update(raw_snapshot=str(raw_path), source_url=HSE28_EPI_HISTORY_ACTION_URL)
    return result
