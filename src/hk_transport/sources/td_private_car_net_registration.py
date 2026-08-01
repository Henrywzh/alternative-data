"""Transport Department Table 4.1(c) private-car net registration."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, TD_PRIVATE_CAR_NET_REGISTRATION_URL
from ..storage import save_raw_snapshot

SCHEMA_COLUMNS = [
    "date",
    "year",
    "month",
    "gross_first_registrations",
    "deregistrations",
    "net_first_registrations",
]


def _number(value: Any) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).replace(",", "").strip()
    if not text or text in {"-", "N.A.", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"TD Table 4.1(c) has an unparseable numeric value: {value!r}") from exc


def _integer(value: Any) -> int | None:
    if pd.isna(value):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else None


def _check_headers(frame: pd.DataFrame) -> None:
    header_text = " ".join(str(value) for value in frame.iloc[:8].to_numpy().flatten() if pd.notna(value))
    required = ("Gross First Registration", "Cumulative Deregistration", "Net First Registration")
    missing = [text for text in required if text not in header_text]
    if missing:
        raise ValueError("TD Table 4.1(c) header layout changed: " + ", ".join(missing))


def parse_private_car_net_registration_sheet(frame: pd.DataFrame) -> pd.DataFrame:
    """Parse monthly rows, excluding the workbook's annual summary rows."""
    _check_headers(frame)
    records: list[dict[str, Any]] = []
    current_year: int | None = None
    for _, row in frame.iterrows():
        first = _integer(row.iloc[0])
        second = _integer(row.iloc[1])
        if first is not None and len(str(first)) == 4:
            current_year = first
        month_number = second
        if current_year is None or month_number is None or not 1 <= month_number <= 12:
            continue
        month = month_number
        gross = _number(row.iloc[2]) if len(row) > 2 else None
        deregistered = _number(row.iloc[3]) if len(row) > 3 else None
        net = _number(row.iloc[4]) if len(row) > 4 else None
        if gross is None or deregistered is None or net is None:
            continue
        if abs(gross - deregistered - net) > 0.5:
            raise ValueError(
                f"TD Table 4.1(c) identity failed for {current_year}-{month:02d}: "
                f"gross={gross}, deregistered={deregistered}, net={net}"
            )
        records.append(
            {
                "date": f"{current_year}-{month:02d}",
                "year": current_year,
                "month": month,
                "gross_first_registrations": gross,
                "deregistrations": deregistered,
                "net_first_registrations": net,
            }
        )
    result = pd.DataFrame(records, columns=SCHEMA_COLUMNS).drop_duplicates("date")
    result = result.sort_values("date").reset_index(drop=True)
    if result.empty:
        raise ValueError("TD Table 4.1(c) contained no monthly private-car rows")
    return result


def parse_private_car_net_registration_workbook(payload: bytes) -> pd.DataFrame:
    workbook = pd.ExcelFile(io.BytesIO(payload))
    if len(workbook.sheet_names) != 1:
        raise ValueError(f"TD Table 4.1(c) expected one worksheet, found {workbook.sheet_names}")
    return parse_private_car_net_registration_sheet(workbook.parse(workbook.sheet_names[0], header=None))


def fetch_td_private_car_net_registration() -> pd.DataFrame:
    response = requests.get(
        TD_PRIVATE_CAR_NET_REGISTRATION_URL,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    response.raise_for_status()
    result = parse_private_car_net_registration_workbook(response.content)
    raw_path = save_raw_snapshot(
        "td_private_car_net_registration",
        response.content,
        file_ext="xls",
        source_url=TD_PRIVATE_CAR_NET_REGISTRATION_URL,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = TD_PRIVATE_CAR_NET_REGISTRATION_URL
    return result
