"""Official airline fuel-surcharge snapshots.

Fuel surcharges are not the same as passenger yield.  They are retained as a
separate pass-through signal: a change in the surcharge tells us when an
airline or regulator is attempting to recover fuel-cost pressure from the
customer, while the financial model still needs actual yield and volume.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, NORMALIZED_DIR
from ..storage import save_raw_snapshot

CATHAY_FUEL_SURCHARGE_URL = (
    "https://www.cathaypacific.com/cx/en_IE/latest-news/other-news/"
    "fuel-surcharge-updates.html"
)
CHINA_DOMESTIC_FUEL_SURCHARGE_URL = (
    "https://english.www.gov.cn/news/202607/03/"
    "content_WS6a47b8a4c6d00ca5f9a0c052.html"
)

FUEL_SURCHARGE_COLUMNS = [
    "dataset_id",
    "carrier_scope",
    "charge_type",
    "origin_market",
    "destination_market",
    "route_band",
    "currency",
    "previous_value",
    "current_value",
    "previous_effective_to",
    "effective_from",
    "previous_value_inferred",
    "announced_at",
    "review_frequency",
    "source_name",
    "source_url",
    "retrieved_at",
]


def _text(html: bytes | str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())


def _parse_date(value: str) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=False)
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _money(text: str, currency: str) -> float | None:
    match = re.search(rf"{re.escape(currency)}\s*([\d,]+(?:\.\d+)?)", text, re.IGNORECASE)
    return None if not match else float(match.group(1).replace(",", ""))


def _append_row(rows: list[dict[str, Any]], **values: Any) -> None:
    rows.append({column: values.get(column) for column in FUEL_SURCHARGE_COLUMNS})


def parse_cathay_fuel_surcharge_html(
    html: bytes | str,
    *,
    source_url: str = CATHAY_FUEL_SURCHARGE_URL,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse the current Cathay passenger surcharge table into tidy rows."""
    text = _text(html)
    effective_match = re.search(
        r"effective\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        text,
        re.IGNORECASE,
    )
    effective_from = _parse_date(effective_match.group(1)) if effective_match else None
    if not effective_from:
        raise ValueError("Cathay surcharge page has no effective date")
    announced_match = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})\)?", text)
    announced_at = _parse_date(announced_match.group(1)) if announced_match else None
    previous_effective_to = (pd.Timestamp(effective_from) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    patterns = [
        (
            "Hong Kong to Chinese Mainland",
            "Hong Kong",
            "Chinese Mainland",
            "HKD",
            r"Flights from Hong Kong to Chinese Mainland:.*?Until\s+\d{2}\w{3}\d{4}\s+HKD\s+[\d,]+\s+From\s+\d{2}\w{3}\d{4}\s+HKD\s+[\d,]+",
        ),
        (
            "Chinese Mainland to Hong Kong",
            "Chinese Mainland",
            "Hong Kong",
            "CNY",
            r"Flights from Chinese Mainland to Hong Kong:.*?Until\s+\d{2}\w{3}\d{4}\s+CNY\s+[\d,]+\s+From\s+\d{2}\w{3}\d{4}\s+CNY\s+[\d,]+",
        ),
        (
            "Long-haul from Hong Kong",
            "Hong Kong",
            "South West Pacific / North America / Europe / Middle East / Africa",
            "HKD",
            r"Flights between Hong Kong and South West Pacific.*?Until\s+\d{2}\w{3}\d{4}\s+HKD\s+[\d,]+.*?From\s+\d{2}\w{3}\d{4}\s+HKD\s+[\d,]+",
        ),
        (
            "South Asian Sub-Continent from Hong Kong",
            "Hong Kong",
            "South Asian Sub-Continent",
            "HKD",
            r"Flights between Hong Kong and South Asian Sub-Continent:.*?Until\s+\d{2}\w{3}\d{4}\s+HKD\s+[\d,]+.*?From\s+\d{2}\w{3}\d{4}\s+HKD\s+[\d,]+",
        ),
        (
            "Other flights from Hong Kong",
            "Hong Kong",
            "Other flights",
            "HKD",
            r"Other flights:.*?Until\s+\d{2}\w{3}\d{4}\s+HKD\s+[\d,]+.*?From\s+\d{2}\w{3}\d{4}\s+HKD\s+[\d,]+",
        ),
    ]
    for route_band, origin, destination, currency, pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        block = match.group(0)
        values = re.findall(
            rf"(?:Until|From)\s+\d{{2}}\w{{3}}\d{{4}}\s+{re.escape(currency)}\s+([\d,]+(?:\.\d+)?)",
            block,
            re.IGNORECASE,
        )
        if len(values) < 2:
            continue
        _append_row(
            rows,
            dataset_id="airline_fuel_surcharges",
            carrier_scope="Cathay Pacific",
            charge_type="passenger_fuel_surcharge",
            origin_market=origin,
            destination_market=destination,
            route_band=route_band,
            currency=currency,
            previous_value=float(values[-2].replace(",", "")),
            current_value=float(values[-1].replace(",", "")),
            previous_effective_to=previous_effective_to,
            effective_from=effective_from,
            previous_value_inferred=False,
            announced_at=announced_at,
            review_frequency="biweekly",
            source_name="Cathay Pacific official fuel surcharge update",
            source_url=source_url,
            retrieved_at=retrieved,
        )

    result = pd.DataFrame(rows, columns=FUEL_SURCHARGE_COLUMNS)
    if result.empty:
        raise ValueError("Cathay surcharge page yielded no route-band rows")
    return result


def parse_china_domestic_fuel_surcharge_html(
    html: bytes | str,
    *,
    source_url: str = CHINA_DOMESTIC_FUEL_SURCHARGE_URL,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse the official mainland distance-band surcharge announcement."""
    text = _text(html)
    effective_match = re.search(r"tickets sold from\s+([A-Za-z]+\s+\d{1,2})", text, re.IGNORECASE)
    effective_from = _parse_date(effective_match.group(1) + " 2026") if effective_match else None
    values = re.search(
        r"pay a fuel surcharge of\s+(\d+) yuan.*?and\s+(\d+) yuan",
        text,
        re.IGNORECASE,
    )
    reductions = re.search(r"reduced by\s+(\d+) yuan.*?and by\s+(\d+) yuan", text, re.IGNORECASE)
    if not effective_from or not values:
        raise ValueError("China domestic surcharge announcement could not be parsed")
    current_values = [float(values.group(1)), float(values.group(2))]
    previous_values = [
        current_values[0] + float(reductions.group(1)) if reductions else None,
        current_values[1] + float(reductions.group(2)) if reductions else None,
    ]
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for route_band, previous, current in zip(
        ("up to 800 km", ">800 km"), previous_values, current_values
    ):
        _append_row(
            rows,
            dataset_id="airline_fuel_surcharges",
            carrier_scope="Mainland China passenger airlines",
            charge_type="passenger_fuel_surcharge",
            origin_market="Mainland China",
            destination_market="Mainland China",
            route_band=route_band,
            currency="CNY",
            previous_value=previous,
            current_value=current,
            previous_effective_to=(pd.Timestamp(effective_from) - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            effective_from=effective_from,
            previous_value_inferred=bool(reductions),
            announced_at=None,
            review_frequency="policy-linked",
            source_name="China government official announcement / Xinhua",
            source_url=source_url,
            retrieved_at=retrieved,
        )
    return pd.DataFrame(rows, columns=FUEL_SURCHARGE_COLUMNS)


def fetch_fuel_surcharge_snapshots(
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch official Cathay and mainland-China surcharge snapshots."""
    client = session or requests.Session()
    client.headers.update(DEFAULT_HEADERS)
    frames: list[pd.DataFrame] = []
    for name, url, parser in (
        ("cathay_fuel_surcharge", CATHAY_FUEL_SURCHARGE_URL, parse_cathay_fuel_surcharge_html),
        (
            "china_domestic_fuel_surcharge",
            CHINA_DOMESTIC_FUEL_SURCHARGE_URL,
            parse_china_domestic_fuel_surcharge_html,
        ),
    ):
        response = client.get(url, timeout=max(DEFAULT_TIMEOUT, 30))
        response.raise_for_status()
        save_raw_snapshot(name, response.content, file_ext="html", source_url=url)
        frames.append(parser(response.content, source_url=url))

    result = pd.concat(frames, ignore_index=True)
    path = NORMALIZED_DIR / "airline_fuel_surcharges.parquet"
    existing = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=FUEL_SURCHARGE_COLUMNS)
    merged = result.copy() if existing.empty else pd.concat([existing, result], ignore_index=True)
    merged = merged.drop_duplicates(
        subset=["carrier_scope", "route_band", "currency", "effective_from"],
        keep="last",
    ).sort_values(["effective_from", "carrier_scope", "route_band", "currency"])
    merged.to_parquet(path, index=False)
    return merged.reset_index(drop=True)
