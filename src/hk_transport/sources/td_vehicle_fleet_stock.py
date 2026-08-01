"""Transport Department Table 4.1(a) private-car fleet stock.

The workbook contains one sheet per vehicle class.  The parser locates the
sheet by its own ``Private Cars`` label and validates the expected fuel/metric
headers before reading values, because TD is free to reorder sheets or alter
the surrounding presentation markup.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, TD_VEHICLE_FLEET_STOCK_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "date",
    "year",
    "month",
    "petrol_first_reg",
    "petrol_total_registered",
    "petrol_total_licensed",
    "electric_first_reg",
    "electric_total_registered",
    "electric_total_licensed",
    "diesel_first_reg",
    "diesel_total_registered",
    "diesel_total_licensed",
    "other_first_reg",
    "other_total_registered",
    "other_total_licensed",
    "all_fuel_first_reg",
    "all_fuel_total_registered",
    "all_fuel_total_licensed",
]

SHEET_LABEL_KEYWORDS = ("Private Cars", "私家車")

# The official Private Cars sheet currently uses these positions.  Header
# validation below ensures a shifted workbook fails rather than silently
# producing a differently-labelled series.
COLUMNS: dict[int, tuple[str, str]] = {
    2: ("petrol_first_reg", "Petrol"),
    3: ("petrol_total_registered", "Total Registration"),
    4: ("petrol_total_licensed", "Total Licensed"),
    5: ("electric_first_reg", "Electric"),
    6: ("electric_total_registered", "Total Registration"),
    7: ("electric_total_licensed", "Total Licensed"),
    8: ("diesel_first_reg", "Diesel"),
    9: ("diesel_total_registered", "Total Registration"),
    10: ("diesel_total_licensed", "Total Licensed"),
    11: ("other_first_reg", "Other"),
    12: ("other_total_registered", "Total Registration"),
    13: ("other_total_licensed", "Total Licensed"),
    14: ("all_fuel_first_reg", "Sub-total"),
    15: ("all_fuel_total_registered", "Total Registration"),
    16: ("all_fuel_total_licensed", "Total Licensed"),
}

TOLERANCE = 0.5


def _header_text(frame: pd.DataFrame, col: int, nrows: int = 12) -> str:
    if col >= frame.shape[1]:
        return ""
    return " ".join(
        str(value).replace("\n", " ")
        for value in frame.iloc[:nrows, col]
        if pd.notna(value)
    )


def _find_private_car_sheet(workbook: pd.ExcelFile) -> str:
    matches = [
        name
        for name in workbook.sheet_names
        if any(keyword in _header_text(workbook.parse(name, header=None), 2) for keyword in SHEET_LABEL_KEYWORDS)
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one private-car sheet, found {matches}")
    return matches[0]


def _validate_headers(frame: pd.DataFrame) -> None:
    missing = [
        f"column {col} (expected {keyword!r})"
        for col, (_field, keyword) in COLUMNS.items()
        if keyword not in _header_text(frame, col)
    ]
    if missing:
        raise ValueError("TD Table 4.1(a) header layout changed: " + "; ".join(missing))


def _number(value: Any) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).replace(",", "").strip()
    if not text or text in {"-", "N.A.", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"TD Table 4.1(a) has an unparseable numeric value: {value!r}") from exc


def _integer(value: Any) -> int | None:
    if pd.isna(value):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else None


def _check_identity(frame: pd.DataFrame, parts: list[str], total: str, label: str) -> None:
    computed = frame[parts].fillna(0).sum(axis=1)
    reported = frame[total]
    bad = frame[reported.notna() & ((computed - reported).abs() > TOLERANCE)]
    if not bad.empty:
        raise ValueError(
            f"{label} does not reconcile on {len(bad)} row(s): "
            f"{bad[['date', total] + parts].to_dict(orient='records')}"
        )


def parse_private_car_fleet_sheet(frame: pd.DataFrame) -> pd.DataFrame:
    """Parse the raw Private Cars worksheet into monthly stock rows."""
    _validate_headers(frame)
    records: list[dict[str, Any]] = []
    current_year: int | None = None
    for _, row in frame.iterrows():
        first = _integer(row.iloc[0])
        second = _integer(row.iloc[1])
        if first is not None and len(str(first)) == 4:
            current_year = first
            month_number = second
        elif current_year and (first is not None or second is not None):
            month_number = second if second is not None else first
        else:
            continue
        if month_number is None or not 1 <= month_number <= 12:
            continue
        month = month_number
        record: dict[str, Any] = {
            "date": f"{current_year}-{month:02d}",
            "year": current_year,
            "month": month,
        }
        for column, (field, _keyword) in COLUMNS.items():
            record[field] = _number(row.iloc[column]) if column < len(row) else None
        records.append(record)

    result = pd.DataFrame(records, columns=SCHEMA_COLUMNS).drop_duplicates("date")
    result = result.sort_values("date").reset_index(drop=True)
    if result.empty:
        raise ValueError("TD Table 4.1(a) contained no monthly private-car rows")
    _check_identity(
        result,
        ["petrol_total_registered", "electric_total_registered", "diesel_total_registered", "other_total_registered"],
        "all_fuel_total_registered",
        "Total registered private-car fleet",
    )
    _check_identity(
        result,
        ["petrol_total_licensed", "electric_total_licensed", "diesel_total_licensed", "other_total_licensed"],
        "all_fuel_total_licensed",
        "Total licensed private-car fleet",
    )
    return result


def parse_private_car_fleet_workbook(payload: bytes) -> pd.DataFrame:
    workbook = pd.ExcelFile(io.BytesIO(payload))
    sheet_name = _find_private_car_sheet(workbook)
    return parse_private_car_fleet_sheet(workbook.parse(sheet_name, header=None))


def fetch_td_vehicle_fleet_stock() -> pd.DataFrame:
    response = requests.get(
        TD_VEHICLE_FLEET_STOCK_URL,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    response.raise_for_status()
    result = parse_private_car_fleet_workbook(response.content)
    raw_path = save_raw_snapshot(
        "td_vehicle_fleet_stock",
        response.content,
        file_ext="xls",
        source_url=TD_VEHICLE_FLEET_STOCK_URL,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = TD_VEHICLE_FLEET_STOCK_URL
    return result
