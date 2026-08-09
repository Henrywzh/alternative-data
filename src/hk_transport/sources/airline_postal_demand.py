"""State Post Bureau postal/express demand context for airline research.

The State Post Bureau publishes official national operating-statistics articles
with postal/express revenue, parcel volume and intra-city/inter-city/
international split.  This is not airline cargo revenue: it is a broad
e-commerce and time-sensitive-logistics proxy.  The source is useful because
the articles expose an official publication date, unlike the current MOFCOM
latest-snapshot endpoint.

Only the three explicit article URLs below are fetched in this first version.
Rows remain at cumulative or latest-month article grain; no monthly history is
invented from cumulative figures.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    NORMALIZED_DIR,
    SPB_2025_H1_URL,
    SPB_2026_H1_URL,
    SPB_2026_JAN_APR_URL,
    SPB_STATS_INDEX_URL,
)
from ..storage import save_raw_snapshot


OUTPUT_PATH = NORMALIZED_DIR / "airline_postal_demand_proxies.csv"
DATASET_ID = "airline_postal_demand_proxies"

OUTPUT_COLUMNS = [
    "dataset_id",
    "source_organization",
    "source_document_type",
    "source_url",
    "observation_period",
    "period_type",
    "observation_month",
    "period_end",
    "metric",
    "value",
    "unit",
    "yoy_pct",
    "source_release_date",
    "source_release_date_status",
    "point_in_time_status",
    "source_quality",
    "source_note",
    "retrieved_at",
]

_NUMBER = r"(?P<value>\d[\d,]*(?:\.\d+)?)"
_UNIT = r"(?P<unit>亿元|亿件|万件)"
_YOY = r"同比(?P<direction>增长|下降)(?P<yoy>\d[\d,]*(?:\.\d+)?)%"


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(str(value).replace(",", ""), errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _to_normalized_value(value: float, unit: str) -> tuple[float, str]:
    if unit == "亿元":
        return value * 100.0, "RMB million"
    if unit == "亿件":
        return value * 100.0, "million parcels"
    if unit == "万件":
        return value / 100.0, "million parcels"
    raise ValueError(f"Unsupported SPB unit: {unit}")


def _yoy(direction: str, value: str) -> float:
    parsed = _number(value)
    if parsed is None:
        raise ValueError(f"Invalid SPB YoY value: {value!r}")
    return -parsed if direction == "下降" else parsed


def _compact_html_text(html: str | bytes) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return re.sub(r"\s+", "", soup.get_text(" ", strip=True))


def _find_metric(
    text: str,
    prefix: str,
    *,
    cumulative: bool,
    monthly_label: str | None = None,
    expected_units: tuple[str, ...] | None = None,
) -> tuple[float, str, float] | None:
    prefix_pattern = re.escape(prefix)
    unit_pattern = (
        rf"(?P<unit>{'|'.join(re.escape(unit) for unit in expected_units)})"
        if expected_units
        else _UNIT
    )
    if cumulative:
        # Bound the match after the metric label. This avoids the navigation
        # keyword ``快递业务量`` consuming the first unrelated cumulative row.
        suffix = rf"(?:(?!累计完成).){{0,80}}?累计完成\s*{_NUMBER}\s*{unit_pattern}.*?{_YOY}"
        for prefix_match in re.finditer(prefix_pattern, text):
            match = re.match(prefix_pattern + suffix, text[prefix_match.start():])
            if match:
                break
        else:
            return None
    else:
        label = re.escape(monthly_label or "6月份")
        # Segment rows such as 同城/异地 are only cumulative in the national
        # articles; prohibit an intervening ``累计`` so they are not copied
        # into the monthly observation.
        pattern = rf"{label}.{{0,120}}?{prefix_pattern}(?:(?!累计).){{0,60}}?完成\s*{_NUMBER}\s*{unit_pattern}.*?{_YOY}"
        match = re.search(pattern, text)
        if not match:
            return None
    value, unit = _to_normalized_value(float(_number(match.group("value"))), match.group("unit"))
    return value, unit, _yoy(match.group("direction"), match.group("yoy"))


METRIC_PREFIXES = (
    ("postal_business_revenue", "邮政行业业务收入"),
    ("express_business_revenue", "快递业务收入"),
    ("postal_delivery_volume", "邮政行业寄递业务量"),
    ("express_delivery_volume", "快递业务量"),
    ("express_intra_city_volume", "同城快递业务量"),
    ("express_inter_city_volume", "异地快递业务量"),
    ("express_international_hk_macao_taiwan_volume", "国际/港澳台快递业务量"),
)

METRIC_EXPECTED_UNITS = {
    "postal_business_revenue": ("亿元",),
    "express_business_revenue": ("亿元",),
    "postal_delivery_volume": ("亿件", "万件"),
    "express_delivery_volume": ("亿件", "万件"),
    "express_intra_city_volume": ("亿件", "万件"),
    "express_inter_city_volume": ("亿件", "万件"),
    "express_international_hk_macao_taiwan_volume": ("亿件", "万件"),
}


def parse_spb_postal_html(
    html: str | bytes,
    *,
    observation_period: str,
    observation_month: str,
    period_end: str,
    source_release_date: str,
    source_url: str,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse one official SPB article into cumulative and latest-month rows."""
    text = _compact_html_text(html)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []

    for metric, prefix in METRIC_PREFIXES:
        for period_type, cumulative in (("cumulative", True), ("monthly", False)):
            found = _find_metric(
                text,
                prefix,
                cumulative=cumulative,
                monthly_label=f"{int(observation_month[-2:])}月份",
                expected_units=METRIC_EXPECTED_UNITS[metric],
            )
            if found is None:
                continue
            value, unit, yoy = found
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "source_organization": "State Post Bureau",
                    "source_document_type": "national_postal_operating_statistics",
                    "source_url": source_url,
                    "observation_period": observation_period,
                    "period_type": period_type,
                    "observation_month": observation_month,
                    "period_end": period_end,
                    "metric": metric,
                    "value": value,
                    "unit": unit,
                    "yoy_pct": yoy,
                    "source_release_date": source_release_date,
                    "source_release_date_status": "official_article_date",
                    "point_in_time_status": "official_release_date_available",
                    "source_quality": "spb_primary_official_html",
                    "source_note": (
                        "Broad postal/express demand proxy; not airline cargo revenue. "
                        "Cumulative and latest-month observations are parsed from the same official article."
                    ),
                    "retrieved_at": retrieved,
                }
            )

    core = {"postal_business_revenue", "express_business_revenue", "postal_delivery_volume", "express_delivery_volume"}
    if not core.issubset(set(row["metric"] for row in rows if row["period_type"] == "cumulative")):
        raise ValueError(
            f"SPB article did not expose all core cumulative metrics for {observation_period}: "
            f"{sorted(set(row['metric'] for row in rows if row['period_type'] == 'cumulative'))}"
        )
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    return result.sort_values(["period_type", "metric"]).reset_index(drop=True)


SOURCE_SPECS = (
    (SPB_2026_JAN_APR_URL, "2026-01_to_04", "2026-04", "2026-04-30", "2026-05-20"),
    (SPB_2026_H1_URL, "2026-H1", "2026-06", "2026-06-30", "2026-07-17"),
    (SPB_2025_H1_URL, "2025-H1", "2025-06", "2025-06-30", "2025-07-16"),
)


def fetch_airline_postal_demand_proxies() -> pd.DataFrame:
    """Fetch the curated official SPB articles and persist an append-safe panel."""
    retrieved = datetime.now(timezone.utc).isoformat()
    frames: list[pd.DataFrame] = []
    for source_url, period, observation_month, period_end, release_date in SOURCE_SPECS:
        response = requests.get(source_url, headers=DEFAULT_HEADERS, timeout=max(DEFAULT_TIMEOUT, 30))
        response.raise_for_status()
        save_raw_snapshot(
            f"spb_postal_{period}",
            response.content,
            file_ext="html",
            source_url=source_url,
        )
        frames.append(
            parse_spb_postal_html(
                response.content,
                observation_period=period,
                observation_month=observation_month,
                period_end=period_end,
                source_release_date=release_date,
                source_url=source_url,
                retrieved_at=retrieved,
            )
        )
    result = pd.concat(frames, ignore_index=True)
    if OUTPUT_PATH.exists():
        prior = pd.read_csv(OUTPUT_PATH)
        result = pd.concat([prior, result], ignore_index=True)
    result = result.drop_duplicates(
        subset=["observation_period", "period_type", "metric", "source_url"],
        keep="last",
    ).reindex(columns=OUTPUT_COLUMNS)
    result.to_csv(OUTPUT_PATH, index=False)
    result.attrs["source_page"] = SPB_STATS_INDEX_URL
    return result.sort_values(["observation_period", "period_type", "metric"]).reset_index(drop=True)


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_COLUMNS",
    "OUTPUT_PATH",
    "parse_spb_postal_html",
    "fetch_airline_postal_demand_proxies",
]
