"""Official holiday travel-demand controls for the airline v3 model.

The Ministry of Transport (MOT) and Ministry of Culture and Tourism (MCT)
publish free event-level travel statistics.  They measure broad travel
activity rather than a specific airline's RPK or revenue, so this module keeps
them in an explicit event panel and never interpolates them into monthly
airline traffic.

The panel preserves the article publication date, event duration, raw metric,
per-day normalization and the distinction between a source-reported YoY rate
and a rate derived from the article's prior-period increase.  This makes the
data useful as a sector demand regime control without hiding holiday-length
effects or look-ahead risk.
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
    MCT_2025_MAY_TOURISM_URL,
    MCT_2026_DRAGON_BOAT_TOURISM_URL,
    MCT_2026_MAY_TOURISM_URL,
    MCT_2026_SPRING_TOURISM_URL,
    MOT_2026_SPRING_TRANSPORT_URL,
    NORMALIZED_DIR,
)
from ..storage import save_raw_snapshot


OUTPUT_PATH = NORMALIZED_DIR / "airline_travel_demand_events.csv"
DATASET_ID = "airline_travel_demand_events"

OUTPUT_COLUMNS = [
    "dataset_id",
    "event_id",
    "source_organization",
    "event_family",
    "event_name",
    "event_year",
    "source_url",
    "event_duration_days",
    "event_duration_status",
    "metric",
    "value",
    "unit",
    "value_per_day",
    "prior_value",
    "prior_unit",
    "prior_duration_days",
    "yoy_pct",
    "daily_yoy_pct",
    "yoy_method",
    "source_release_date",
    "source_release_date_status",
    "point_in_time_status",
    "source_quality",
    "source_note",
    "raw_snapshot_path",
    "retrieved_at",
]

_NUM = r"(?P<value>\d[\d,]*(?:\.\d+)?)"
_PERSON_UNIT = r"(?P<unit>亿人次|万人次)"
_SPEND_UNIT = r"(?P<unit>亿元)"


SOURCE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "event_id": "mot_2026_spring_transport",
        "source_organization": "Ministry of Transport",
        "event_family": "spring_festival_transport",
        "event_name": "2026 Spring Festival 40-day transport",
        "event_year": 2026,
        "source_url": MOT_2026_SPRING_TRANSPORT_URL,
        "release_date": "2026-03-16",
        "duration_days": 40,
        "duration_status": "official_event_window",
        "parser": "mot_spring_transport",
    },
    {
        "event_id": "mct_2026_spring_tourism",
        "source_organization": "Ministry of Culture and Tourism",
        "event_family": "holiday_tourism",
        "event_name": "2026 Spring Festival domestic tourism",
        "event_year": 2026,
        "source_url": MCT_2026_SPRING_TOURISM_URL,
        "release_date": "2026-02-24",
        "duration_days": 9,
        "duration_status": "parsed_from_official_article",
        "parser": "mct_tourism",
    },
    {
        "event_id": "mct_2026_may_tourism",
        "source_organization": "Ministry of Culture and Tourism",
        "event_family": "holiday_tourism",
        "event_name": "2026 May Day domestic tourism",
        "event_year": 2026,
        "source_url": MCT_2026_MAY_TOURISM_URL,
        "release_date": "2026-05-07",
        "duration_days": 5,
        "duration_status": "official_holiday_calendar_context",
        "parser": "mct_tourism",
    },
    {
        "event_id": "mct_2026_dragon_boat_tourism",
        "source_organization": "Ministry of Culture and Tourism",
        "event_family": "holiday_tourism",
        "event_name": "2026 Dragon Boat domestic tourism",
        "event_year": 2026,
        "source_url": MCT_2026_DRAGON_BOAT_TOURISM_URL,
        "release_date": "2026-06-22",
        "duration_days": 3,
        "duration_status": "parsed_from_official_article",
        "parser": "mct_tourism",
    },
    {
        "event_id": "mct_2025_may_tourism",
        "source_organization": "Ministry of Culture and Tourism",
        "event_family": "holiday_tourism",
        "event_name": "2025 May Day domestic tourism",
        "event_year": 2025,
        "source_url": MCT_2025_MAY_TOURISM_URL,
        "release_date": "2025-05-06",
        "duration_days": 5,
        "duration_status": "official_holiday_calendar_context",
        "parser": "mct_tourism",
    },
)


def _number(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(str(value).replace(",", ""), errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _compact_html_text(payload: str | bytes) -> str:
    soup = BeautifulSoup(payload, "html.parser")
    return (
        re.sub(r"\s+", "", soup.get_text(" ", strip=True))
        .replace("，", ",")
        .replace("：", ":")
        .replace("％", "%")
        .replace("；", ";")
    )


def _to_normalized(value: float, unit: str) -> tuple[float, str]:
    if unit == "亿人次":
        return value * 100.0, "million persons"
    if unit == "万人次":
        return value / 100.0, "million persons"
    if unit == "亿元":
        return value * 100.0, "RMB million"
    raise ValueError(f"Unsupported travel-demand unit: {unit}")


def _row(
    spec: dict[str, Any],
    *,
    metric: str,
    value: float,
    unit: str,
    yoy_pct: float | None,
    yoy_method: str,
    prior_value: float | None = None,
    prior_unit: str | None = None,
    prior_duration_days: int | None = None,
    daily_yoy_pct: float | None = None,
    raw_snapshot_path: str | None = None,
    retrieved_at: str | None = None,
    source_note: str,
) -> dict[str, Any]:
    duration = int(spec["duration_days"]) if spec.get("duration_days") else None
    return {
        "dataset_id": DATASET_ID,
        "event_id": spec["event_id"],
        "source_organization": spec["source_organization"],
        "event_family": spec["event_family"],
        "event_name": spec["event_name"],
        "event_year": spec["event_year"],
        "source_url": spec["source_url"],
        "event_duration_days": duration,
        "event_duration_status": spec["duration_status"],
        "metric": metric,
        "value": value,
        "unit": unit,
        "value_per_day": value / duration if duration else None,
        "prior_value": prior_value,
        "prior_unit": prior_unit,
        "prior_duration_days": prior_duration_days,
        "yoy_pct": yoy_pct,
        "daily_yoy_pct": daily_yoy_pct,
        "yoy_method": yoy_method,
        "source_release_date": spec["release_date"],
        "source_release_date_status": "official_article_publication_date",
        "point_in_time_status": "release_date_safe_event_observation",
        "source_quality": "government_primary_official_html",
        "source_note": source_note,
        "raw_snapshot_path": raw_snapshot_path,
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat(),
    }


def _mct_current_value(text: str, metric: str) -> tuple[float, str] | None:
    if metric == "domestic_travelers":
        match = re.search(r"全国国内出游" + _NUM + _PERSON_UNIT, text)
    elif metric == "domestic_tourism_spend":
        match = re.search(r"(?:国内出游|国内游客出游)总花费" + _NUM + _SPEND_UNIT, text)
    else:
        raise ValueError(f"Unsupported MCT metric: {metric}")
    if not match:
        return None
    value = _number(match.group("value"))
    if value is None:
        return None
    return _to_normalized(value, match.group("unit"))


def _mct_source_yoy(text: str, metric: str) -> float | None:
    if metric == "domestic_travelers":
        pattern = (
            r"全国国内出游(?P<current>\d[\d,]*(?:\.\d+)?)(?:亿人次|万人次)"
            r".*?(?:同比增长|同比上升)(?P<yoy>\d[\d,]*(?:\.\d+)?)%"
        )
    else:
        pattern = (
            r"(?:国内出游|国内游客出游)总花费(?P<current>\d[\d,]*(?:\.\d+)?)(?:亿元)"
            r".*?(?:同比增长|同比上升)(?P<yoy>\d[\d,]*(?:\.\d+)?)%"
        )
    match = re.search(pattern, text)
    return _number(match.group("yoy")) if match else None


def _mct_spring_prior(text: str, metric: str) -> tuple[float, str, int] | None:
    if metric == "domestic_travelers":
        pattern = (
            r"全国国内出游(?P<current>\d[\d,]*(?:\.\d+)?)(?P<current_unit>亿人次|万人次)"
            + r".*?较2025年春节假日(?P<prior_days>\d+)天增加"
            + r"(?P<increase>\d[\d,]*(?:\.\d+)?)(?P<increase_unit>亿人次|万人次)"
        )
    else:
        pattern = (
            r"(?:国内出游|国内游客出游)总花费(?P<current>\d[\d,]*(?:\.\d+)?)(?P<current_unit>亿元)"
            + r".*?较2025年春节假日(?P<prior_days>\d+)天增加"
            + r"(?P<increase>\d[\d,]*(?:\.\d+)?)(?P<increase_unit>亿元)"
        )
    match = re.search(pattern, text)
    if not match:
        return None
    current = _number(match.group("current"))
    increase = _number(match.group("increase"))
    prior_days = int(match.group("prior_days"))
    if current is None or increase is None:
        return None
    normalized_current, normalized_unit = _to_normalized(current, match.group("current_unit"))
    normalized_increase, _ = _to_normalized(increase, match.group("increase_unit"))
    return normalized_current - normalized_increase, normalized_unit, prior_days


def parse_mct_tourism_article(
    payload: str | bytes,
    *,
    spec: dict[str, Any],
    raw_snapshot_path: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse official MCT holiday travel and tourism-spend rows."""
    text = _compact_html_text(payload)
    rows: list[dict[str, Any]] = []
    for metric in ("domestic_travelers", "domestic_tourism_spend"):
        current = _mct_current_value(text, metric)
        if current is None:
            continue
        value, unit = current
        source_yoy = _mct_source_yoy(text, metric)
        prior_value = None
        prior_unit = None
        prior_days = None
        daily_yoy = None
        yoy_method = "source_reported_yoy" if source_yoy is not None else "not_reported"
        if source_yoy is None and spec["event_id"] == "mct_2026_spring_tourism":
            prior = _mct_spring_prior(text, metric)
            if prior is not None:
                prior_value, prior_unit, prior_days = prior
                source_yoy = 100.0 * value / prior_value - 100.0 if prior_value else None
                current_days = int(spec["duration_days"])
                daily_yoy = (
                    100.0 * (value / current_days) / (prior_value / prior_days) - 100.0
                    if prior_value and prior_days and current_days
                    else None
                )
                yoy_method = "derived_from_source_reported_prior_period_increase_and_duration"
        rows.append(
            _row(
                spec,
                metric=metric,
                value=value,
                unit=unit,
                yoy_pct=source_yoy,
                daily_yoy_pct=daily_yoy,
                yoy_method=yoy_method,
                prior_value=prior_value,
                prior_unit=prior_unit,
                prior_duration_days=prior_days,
                raw_snapshot_path=raw_snapshot_path,
                retrieved_at=retrieved_at,
                source_note=(
                    "MCT official holiday tourism estimate; broad leisure-demand control, not airline RPK. "
                    "Per-day normalization is derived from the event duration."
                ),
            )
        )
    if not rows:
        raise ValueError(f"MCT article did not expose domestic travel metrics: {spec['event_id']}")
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def parse_mot_spring_transport_article(
    payload: str | bytes,
    *,
    spec: dict[str, Any],
    raw_snapshot_path: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse official MOT Spring Festival transport totals and modes."""
    text = _compact_html_text(payload)
    rows: list[dict[str, Any]] = []
    mode_patterns = (
        ("cross_regional_person_flow", r"全社会跨区域人员流动量" + _NUM + _PERSON_UNIT, True),
        ("rail_passengers", r"铁路客运量累计" + _NUM + _PERSON_UNIT, False),
        ("road_person_flow", r"公路人员流动量累计" + _NUM + _PERSON_UNIT, False),
    )
    # The waterway value is adjacent to civil aviation in the article and is
    # not a separate labelled phrase, so extract it from the combined clause.
    water_match = re.search(
        r"水路、民航客运量累计"
        r"(?P<water>\d[\d,]*(?:\.\d+)?)(?P<water_unit>亿人次|万人次)、"
        r"(?P<civil>\d[\d,]*(?:\.\d+)?)(?P<civil_unit>亿人次|万人次)",
        text,
    )
    for metric, pattern, has_yoy in mode_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        else:
            raw_value = match.group("value")
            raw_unit = match.group("unit")
        value = _number(raw_value)
        if value is None:
            continue
        normalized_value, unit = _to_normalized(value, raw_unit)
        yoy = None
        if has_yoy:
            yoy_match = re.search(
                r"全社会跨区域人员流动量\d[\d,]*(?:\.\d+)?(?:亿人次|万人次)"
                r".*?(?:比2025年同期增长|同比增长)(?P<yoy>\d[\d,]*(?:\.\d+)?)%",
                text,
            )
            yoy = _number(yoy_match.group("yoy")) if yoy_match else None
        rows.append(
            _row(
                spec,
                metric=metric,
                value=normalized_value,
                unit=unit,
                yoy_pct=yoy,
                yoy_method="source_reported_yoy" if yoy is not None else "not_reported_for_submode",
                raw_snapshot_path=raw_snapshot_path,
                retrieved_at=retrieved_at,
                source_note=(
                    "MOT official Spring Festival transport summary; broad travel/HSR control, not airline company revenue. "
                    "Sub-mode YoY is left blank when the article reports only the total-flow YoY."
                ),
            )
        )
    if water_match:
        for metric, value_group, unit_group in (
            ("waterway_passengers", "water", "water_unit"),
            ("civil_aviation_passengers", "civil", "civil_unit"),
        ):
            value = _number(water_match.group(value_group))
            if value is None:
                continue
            normalized_value, unit = _to_normalized(value, water_match.group(unit_group))
            rows.append(
                _row(
                    spec,
                    metric=metric,
                    value=normalized_value,
                    unit=unit,
                    yoy_pct=None,
                    yoy_method="not_reported_for_submode",
                    raw_snapshot_path=raw_snapshot_path,
                    retrieved_at=retrieved_at,
                    source_note=(
                        "MOT official Spring Festival transport summary; broad travel/HSR control, not airline company revenue. "
                        "Sub-mode YoY is left blank when the article reports only the total-flow YoY."
                    ),
                )
            )
    if not rows:
        raise ValueError(f"MOT article did not expose transport metrics: {spec['event_id']}")
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def parse_travel_demand_article(
    payload: str | bytes,
    *,
    spec: dict[str, Any],
    raw_snapshot_path: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    if spec["parser"] == "mct_tourism":
        return parse_mct_tourism_article(
            payload,
            spec=spec,
            raw_snapshot_path=raw_snapshot_path,
            retrieved_at=retrieved_at,
        )
    if spec["parser"] == "mot_spring_transport":
        return parse_mot_spring_transport_article(
            payload,
            spec=spec,
            raw_snapshot_path=raw_snapshot_path,
            retrieved_at=retrieved_at,
        )
    raise ValueError(f"Unknown travel-demand parser: {spec['parser']}")


def fetch_airline_travel_demand_events() -> pd.DataFrame:
    """Fetch the curated official MOT/MCT event sources and persist the panel."""
    retrieved = datetime.now(timezone.utc).isoformat()
    frames: list[pd.DataFrame] = []
    for spec in SOURCE_SPECS:
        response = requests.get(
            spec["source_url"],
            headers=DEFAULT_HEADERS,
            timeout=max(DEFAULT_TIMEOUT, 30),
        )
        response.raise_for_status()
        raw_path = save_raw_snapshot(
            f"airline_travel_demand_{spec['event_id']}",
            response.content,
            file_ext="html",
            source_url=spec["source_url"],
        )
        frames.append(
            parse_travel_demand_article(
                response.content,
                spec=spec,
                raw_snapshot_path=str(raw_path),
                retrieved_at=retrieved,
            )
        )
    # Build from records rather than concatenating partially sparse metric
    # frames; this avoids pandas' all-NA-column dtype warning while preserving
    # the explicit output schema.
    result = pd.DataFrame(
        [record for frame in frames for record in frame.to_dict("records")],
        columns=OUTPUT_COLUMNS,
    )
    if OUTPUT_PATH.exists():
        prior = pd.read_csv(OUTPUT_PATH)
        result = pd.DataFrame(
            [*prior.to_dict("records"), *result.to_dict("records")],
            columns=OUTPUT_COLUMNS,
        )
    result = result.drop_duplicates(
        subset=["event_id", "metric", "source_url"],
        keep="last",
    ).reindex(columns=OUTPUT_COLUMNS)
    result.to_csv(OUTPUT_PATH, index=False)
    return result.sort_values(["event_year", "source_release_date", "event_id", "metric"]).reset_index(drop=True)


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "SOURCE_SPECS",
    "fetch_airline_travel_demand_events",
    "parse_mct_tourism_article",
    "parse_mot_spring_transport_article",
    "parse_travel_demand_article",
    "source_path",
]
