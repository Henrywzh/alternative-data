"""CAAC seasonal route-licence events for forward airline supply context.

The CAAC summer/autumn 2026 table is a free primary PDF with new domestic
route licences, re-issued cargo licences and cancellations.  It describes
planned/approved supply events; it does not prove that a flight operated or
that the stated initial frequency became realized ASK.  Rows therefore remain
an event layer and are not merged into the issuer monthly ASK history.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import pypdf
import requests

from ..config import (
    CAAC_2026_SUMMER_ROUTE_LICENCE_URL,
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    NORMALIZED_DIR,
)
from ..storage import save_raw_snapshot


OUTPUT_PATH = NORMALIZED_DIR / "airline_caac_route_licence_events.csv"
DATASET_ID = "airline_caac_route_licence_events"
SOURCE_RELEASE_DATE = "2026-03-23"
SCHEDULE_SEASON = "2026_summer_autumn"

OUTPUT_COLUMNS = [
    "dataset_id",
    "source_organization",
    "source_document_type",
    "source_url",
    "source_release_date",
    "schedule_season",
    "table_type",
    "row_number",
    "event_type",
    "licence_type",
    "airline_short_name",
    "airline_normalized_name",
    "route_text",
    "origin_city",
    "intermediate_stops",
    "destination_city",
    "route_leg_count",
    "planned_start_date",
    "initial_frequency_per_week",
    "frequency_status",
    "cancellation_date",
    "note",
    "page_number",
    "point_in_time_status",
    "source_quality",
    "source_note",
    "retrieved_at",
]

AIRLINE_NAME_MAP = {
    "春秋航": "Spring Airlines",
    "吉祥航": "Juneyao Airlines",
    "九元航": "9 Air",
    "南航": "China Southern Airlines",
    "东航": "China Eastern Airlines",
    "国航": "Air China",
    "海航": "Hainan Airlines Holdings",
}

_DATE = r"(?P<date>\d{4}[./-]\d{2}[./-]\d{2})"


def _normalise_date(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"[./]", "-", value)


def _route_parts(route_text: str) -> tuple[str | None, str | None, str | None, int | None]:
    route = re.sub(r"\s+", "", route_text)
    cities = [city for city in re.split(r"[-—－至]", route) if city]
    if len(cities) < 2:
        return None, None, None, None
    return cities[0], "-".join(cities[1:-1]) or None, cities[-1], len(cities) - 1


def _base_row(
    *,
    table_type: str,
    row_number: int,
    event_type: str,
    licence_type: str,
    airline_short_name: str,
    route_text: str | None,
    planned_start_date: str | None = None,
    initial_frequency_per_week: float | None = None,
    frequency_status: str,
    cancellation_date: str | None = None,
    note: str | None = None,
    page_number: int | None = None,
    retrieved_at: str,
) -> dict[str, object]:
    origin, stops, destination, legs = _route_parts(route_text or "")
    return {
        "dataset_id": DATASET_ID,
        "source_organization": "Civil Aviation Administration of China",
        "source_document_type": "seasonal_route_licence_table",
        "source_url": CAAC_2026_SUMMER_ROUTE_LICENCE_URL,
        "source_release_date": SOURCE_RELEASE_DATE,
        "schedule_season": SCHEDULE_SEASON,
        "table_type": table_type,
        "row_number": row_number,
        "event_type": event_type,
        "licence_type": licence_type,
        "airline_short_name": airline_short_name,
        "airline_normalized_name": AIRLINE_NAME_MAP.get(airline_short_name),
        "route_text": route_text,
        "origin_city": origin,
        "intermediate_stops": stops,
        "destination_city": destination,
        "route_leg_count": legs,
        "planned_start_date": planned_start_date,
        "initial_frequency_per_week": initial_frequency_per_week,
        "frequency_status": frequency_status,
        "cancellation_date": cancellation_date,
        "note": note,
        "page_number": page_number,
        "point_in_time_status": "official_release_date_available_planned_supply",
        "source_quality": "caac_primary_route_licence_pdf",
        "source_note": (
            "CAAC route-licence event; planned/approved frequency is not realized flight activity or company ASK. "
            "The table states route, carrier and initial frequency but does not provide operated-flight confirmation."
        ),
        "retrieved_at": retrieved_at,
    }


def parse_caac_route_licence_text(
    text: str,
    *,
    page_number: int = 1,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse text extracted from one or more pages of the CAAC route table."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or not re.match(r"^\d+\s+", line):
            continue
        fields = line.split(" ")
        try:
            row_number = int(fields[0])
        except (ValueError, IndexError):
            continue
        if len(fields) < 5:
            continue

        # New/re-issued licence rows with a planned date and initial frequency.
        addition = re.match(
            rf"^(?P<row>\d+)\s+(?P<event>新增许可)\s+(?P<licence>\S+)\s+(?P<airline>\S+)\s+(?P<route>.+?)\s+{_DATE}\s+(?P<frequency>\d+(?:\.\d+)?)$",
            line,
        )
        if addition:
            rows.append(
                _base_row(
                    table_type="new_domestic_route",
                    row_number=row_number,
                    event_type=addition.group("event"),
                    licence_type=addition.group("licence"),
                    airline_short_name=addition.group("airline"),
                    route_text=addition.group("route"),
                    planned_start_date=_normalise_date(addition.group("date")),
                    initial_frequency_per_week=float(addition.group("frequency")),
                    frequency_status="stated_initial_frequency",
                    page_number=page_number,
                    retrieved_at=retrieved,
                )
            )
            continue

        # Cargo licence renewals have no city pair or frequency; preserve the
        # broad route scope and the table's note instead of fabricating one.
        renewal = re.match(
            r"^(?P<row>\d+)\s+(?P<event>新增许可)\s+(?P<licence>\S+)\s+(?P<airline>\S+)\s+(?P<route>.+?)\s+(?P<note>换发|不限)$",
            line,
        )
        if renewal:
            rows.append(
                _base_row(
                    table_type="renewed_domestic_cargo_licence",
                    row_number=row_number,
                    event_type=renewal.group("event"),
                    licence_type=renewal.group("licence"),
                    airline_short_name=renewal.group("airline"),
                    route_text=renewal.group("route"),
                    frequency_status="not_stated",
                    note=renewal.group("note"),
                    page_number=page_number,
                    retrieved_at=retrieved,
                )
            )
            continue

        cancellation = re.match(
            rf"^(?P<row>\d+)\s+(?P<event>注销)\s+(?P<licence>\S+)\s+(?P<airline>\S+)\s+(?P<route>.+?)\s+{_DATE}$",
            line,
        )
        if cancellation:
            rows.append(
                _base_row(
                    table_type="cancelled_route_licence",
                    row_number=row_number,
                    event_type=cancellation.group("event"),
                    licence_type=cancellation.group("licence"),
                    airline_short_name=cancellation.group("airline"),
                    route_text=cancellation.group("route"),
                    frequency_status="not_stated",
                    cancellation_date=_normalise_date(cancellation.group("date")),
                    page_number=page_number,
                    retrieved_at=retrieved,
                )
            )

    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if result.empty:
        raise ValueError("CAAC route licence PDF text produced no event rows")
    return result


def _extract_pdf_pages(payload: bytes) -> Iterable[tuple[int, str]]:
    reader = pypdf.PdfReader(io.BytesIO(payload))
    for index, page in enumerate(reader.pages, start=1):
        yield index, page.extract_text() or ""


def parse_caac_route_licence_pdf(
    payload: bytes,
    *,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    frames = [
        parse_caac_route_licence_text(text, page_number=page, retrieved_at=retrieved_at)
        for page, text in _extract_pdf_pages(payload)
        if text.strip()
    ]
    if not frames:
        raise ValueError("CAAC route licence PDF has no extractable text")
    records: list[dict[str, object]] = []
    for frame in frames:
        records.extend(frame.to_dict("records"))
    result = pd.DataFrame.from_records(records, columns=OUTPUT_COLUMNS)
    if result.duplicated(["table_type", "row_number", "airline_short_name", "route_text"]).any():
        result = result.drop_duplicates(
            ["table_type", "row_number", "airline_short_name", "route_text"],
            keep="first",
        )
    return result.reindex(columns=OUTPUT_COLUMNS)


def fetch_caac_route_licence_events() -> pd.DataFrame:
    """Fetch and persist the dated CAAC summer/autumn 2026 route event layer."""
    retrieved = datetime.now(timezone.utc).isoformat()
    response = requests.get(
        CAAC_2026_SUMMER_ROUTE_LICENCE_URL,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    response.raise_for_status()
    save_raw_snapshot(
        "caac_summer_route_licences_2026",
        response.content,
        file_ext="pdf",
        source_url=CAAC_2026_SUMMER_ROUTE_LICENCE_URL,
    )
    result = parse_caac_route_licence_pdf(response.content, retrieved_at=retrieved)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_COLUMNS",
    "OUTPUT_PATH",
    "fetch_caac_route_licence_events",
    "parse_caac_route_licence_pdf",
    "parse_caac_route_licence_text",
]
