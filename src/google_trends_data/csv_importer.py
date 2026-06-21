from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .models import TrendsDataPoint


def parse_interest_over_time_csv(
    csv_path: str | Path,
    *,
    keyword: str,
    geo: str,
    fetched_at: str | None = None,
) -> list[TrendsDataPoint]:
    path = Path(csv_path)
    rows = list(csv.reader(path.open(encoding="utf-8")))
    header_index = _find_header_row(rows)
    header = rows[header_index]

    value_index = _find_value_column(header)
    partial_index = _find_partial_column(header)
    timestamp = fetched_at or datetime.now(timezone.utc).isoformat()

    records: list[TrendsDataPoint] = []
    for row in rows[header_index + 1:]:
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) <= value_index:
            continue

        raw_date = row[0].strip()
        if not raw_date:
            continue

        parsed_date = _normalize_date(raw_date)
        trend_value = _parse_trend_value(row[value_index])
        is_partial = _parse_partial(row[partial_index]) if partial_index is not None and len(row) > partial_index else False

        records.append(
            TrendsDataPoint(
                date=parsed_date,
                keyword=keyword,
                geo=geo,
                trend_value=trend_value,
                is_partial=is_partial,
                fetched_at=timestamp,
            )
        )

    if not records:
        raise ValueError(f"No trend rows found in {path}")
    return records


def _find_header_row(rows: list[list[str]]) -> int:
    for index, row in enumerate(rows):
        if row and row[0].strip().lower() in {"day", "week", "month"}:
            return index
    raise ValueError("Could not find Google Trends date header row")


def _find_value_column(header: list[str]) -> int:
    for index, column in enumerate(header[1:], start=1):
        normalized = column.strip().lower()
        if normalized and normalized != "ispartial":
            return index
    raise ValueError("Google Trends CSV is missing a value column")


def _find_partial_column(header: list[str]) -> int | None:
    for index, column in enumerate(header):
        if column.strip().lower() == "ispartial":
            return index
    return None


def _normalize_date(raw_date: str) -> str:
    first_token = raw_date.split(" - ", 1)[0].strip()
    parsed = pd.to_datetime(first_token, errors="raise")
    return parsed.strftime("%Y-%m-%d")


def _parse_trend_value(raw_value: str) -> int:
    normalized = raw_value.strip().replace(",", "")
    if normalized.startswith("<"):
        return 1
    return int(float(normalized))


def _parse_partial(raw_value: str) -> bool:
    return raw_value.strip().lower() in {"true", "1", "yes"}
