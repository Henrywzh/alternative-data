"""Free Hong Kong commercial-property control series.

These feeds are market controls for the SHKP commercial asset master.  They
are deliberately not labelled as SHKP revenue, rent or occupancy: RVD is a
market-level source, C&SD is an economy-wide retail survey, and the tourism
files are Hong Kong hotel-industry aggregates.

The source contracts in this module keep the original observation grain and
retain an explicit ``source_url``/raw snapshot.  Rolling five-year tourism
files and annual RVD stock/vacancy tables must not be silently expanded into
longer histories.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot


# C&SD's web-table viewer is JavaScript-heavy, but the sibling local-consumer
# source already uses the stable underlying MDT CSV files.  Reuse that parser
# so the two sectors do not drift in their definition of the retail index.
from src.hk_local_consumer.sources.cnsd_retail import fetch_cnsd_retail_sales


RVD_OFFICE_VACANCY_URL = "https://www.rvd.gov.hk/datagovhk/Private_Offices-Vacancy.csv"
RVD_OFFICE_STOCK_VACANCY_DISTRICT_URL = (
    "https://www.rvd.gov.hk/datagovhk/Off_Stock_Completions_and_Vacancy_by_District_Eng.csv"
)
RVD_COMMERCIAL_STOCK_VACANCY_DISTRICT_URL = (
    "https://www.rvd.gov.hk/datagovhk/Com_Stock_Completions_and_Vacancy_by_District_Eng.csv"
)
RVD_COMMERCIAL_FORECAST_COMPLETIONS_URL = (
    "https://www.rvd.gov.hk/datagovhk/Com_Completions_and_Forecast_Completions_by_District_Eng.csv"
)

TOURISM_HOTEL_OCCUPANCY_CATEGORY_URL = (
    "https://www.tourism.gov.hk/datagovhk/hotelroomoccupancy/"
    "hotel_room_occupancy_rate_monthly_by_cat_en.csv"
)
TOURISM_HOTEL_ADR_CATEGORY_URL = (
    "https://www.tourism.gov.hk/datagovhk/hotelroomrate/"
    "average_achieved_hotel_room_rate_by_category_en.csv"
)
TOURISM_HOTEL_ROOMS_CATEGORY_URL = (
    "https://www.tourism.gov.hk/datagovhk/hotelrooms/"
    "Number_of_hotel_rooms_in_Hong_Kong_by_hotel_category_en.csv"
)


CNSD_RETAIL_COLUMNS = [
    "date",
    "category",
    "metric",
    "value",
    "unit",
    "is_provisional",
    "source_agency",
    "source_url",
]
TOURISM_COLUMNS = [
    "date",
    "category",
    "metric",
    "value",
    "unit",
    "is_provisional",
    "source_agency",
    "source_url",
]
RVD_CONTROL_COLUMNS = [
    "date",
    "geography",
    "district",
    "segment",
    "metric",
    "value",
    "unit",
    "frequency",
    "data_status",
    "source_agency",
    "source_url",
]


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _stamp_lineage(
    frame: pd.DataFrame,
    *,
    raw_snapshots: list[str],
    source_urls: list[str],
    lineage_type: str,
) -> pd.DataFrame:
    frame.attrs["raw_snapshots"] = [value for value in raw_snapshots if value]
    if frame.attrs["raw_snapshots"]:
        frame.attrs["raw_snapshot"] = frame.attrs["raw_snapshots"][0]
    frame.attrs["source_urls"] = list(dict.fromkeys(value for value in source_urls if value))
    if frame.attrs["source_urls"]:
        frame.attrs["source_url"] = frame.attrs["source_urls"][0]
    frame.attrs["lineage_metadata"] = {
        "lineage_type": lineage_type,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "market_context_only": True,
        "shkp_asset_attribution": False,
    }
    return frame


def _fetch_csv(source_name: str, url: str, *, timeout: float = 30) -> tuple[bytes, str]:
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    raw_path = save_raw_snapshot(source_name, response.content, file_ext="csv", source_url=url)
    return response.content, str(raw_path)


def _parse_monthly_columns(content: bytes, *, metric: str, unit: str) -> pd.DataFrame:
    raw = pd.read_csv(io.BytesIO(content), dtype=str, encoding="utf-8-sig")
    if raw.empty:
        return _empty(TOURISM_COLUMNS)
    date_column = next((column for column in raw.columns if "year-month" in str(column).lower()), raw.columns[0])
    rows: list[dict[str, Any]] = []
    for _, record in raw.iterrows():
        date = pd.to_datetime(str(record.get(date_column, "")), format="%Y%m", errors="coerce")
        if pd.isna(date):
            continue
        for column in raw.columns:
            if column == date_column:
                continue
            value = pd.to_numeric(
                str(record.get(column, "")).replace(",", "").replace(" ", "").replace("\u00a0", "").strip(),
                errors="coerce",
            )
            if pd.isna(value):
                continue
            label = re.sub(r"\s+", " ", str(column)).strip()
            label = re.sub(r"^(?:Hotel room occupancy rate|Average achieved hotel room rate|Number of)\s+", "", label, flags=re.I)
            label = re.sub(r"\s*\([^)]*\)\s*$", "", label).strip()
            label = label or "all"
            rows.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "category": label,
                    "metric": metric,
                    "value": float(value),
                    "unit": unit,
                    "is_provisional": False,
                    "source_agency": "Culture, Sports and Tourism Bureau / Hong Kong Tourism Board",
                }
            )
    return pd.DataFrame(rows, columns=TOURISM_COLUMNS[:-1])


def _fetch_tourism_series(source_name: str, url: str, *, metric: str, unit: str) -> pd.DataFrame:
    content, raw_path = _fetch_csv(source_name, url)
    result = _parse_monthly_columns(content, metric=metric, unit=unit)
    if result.empty:
        return _empty(TOURISM_COLUMNS)
    result["source_url"] = url
    result = result.reindex(columns=TOURISM_COLUMNS)
    return _stamp_lineage(
        result,
        raw_snapshots=[raw_path],
        source_urls=[url],
        lineage_type=f"official_tourism_{metric}_monthly",
    )


def fetch_tourism_hotel_occupancy_category() -> pd.DataFrame:
    return _fetch_tourism_series(
        "tourism_hotel_occupancy_category",
        TOURISM_HOTEL_OCCUPANCY_CATEGORY_URL,
        metric="hotel_occupancy",
        unit="percent",
    )


def fetch_tourism_hotel_adr_category() -> pd.DataFrame:
    return _fetch_tourism_series(
        "tourism_hotel_adr_category",
        TOURISM_HOTEL_ADR_CATEGORY_URL,
        metric="hotel_adr",
        unit="HKD_per_room",
    )


def fetch_tourism_hotel_rooms_category() -> pd.DataFrame:
    return _fetch_tourism_series(
        "tourism_hotel_rooms_category",
        TOURISM_HOTEL_ROOMS_CATEGORY_URL,
        metric="hotel_rooms",
        unit="rooms",
    )


def fetch_cnsd_retail_sales_control() -> pd.DataFrame:
    """Return C&SD retail value/volume indices in one long-form contract."""
    source = fetch_cnsd_retail_sales()
    if source is None or source.empty:
        return _empty(CNSD_RETAIL_COLUMNS)
    rows: list[dict[str, Any]] = []
    for record in source.to_dict("records"):
        for metric, field, unit in (
            ("retail_sales_value_index", "sales_value_index", "index"),
            ("retail_sales_volume_index", "sales_volume_index", "index"),
        ):
            value = pd.to_numeric(record.get(field), errors="coerce")
            if pd.isna(value):
                continue
            rows.append(
                {
                    "date": record.get("date"),
                    "category": record.get("category") or "all retail outlets",
                    "metric": metric,
                    "value": float(value),
                    "unit": unit,
                    "is_provisional": bool(record.get("is_provisional", False)),
                    "source_agency": "Census and Statistics Department",
                    "source_url": (
                        "https://www.censtatd.gov.hk/data/MDT_75_620-67002_"
                        "VAL_IDX_RS_Raw_1dp_idx_n.csv"
                    ),
                }
            )
    result = pd.DataFrame(rows, columns=CNSD_RETAIL_COLUMNS)
    if result.empty:
        return _empty(CNSD_RETAIL_COLUMNS)
    raw_snapshot = str(source.attrs.get("raw_snapshot") or "")
    return _stamp_lineage(
        result,
        raw_snapshots=[raw_snapshot] if raw_snapshot else [],
        source_urls=sorted(result["source_url"].dropna().astype(str).unique().tolist()),
        lineage_type="official_censtatd_retail_sales_control_long_form",
    )


def _numeric(value: Any) -> float | None:
    cleaned = str(value or "").replace(",", "").strip()
    if not cleaned or cleaned in {"-", "—", "N.A.", "N/A"}:
        return None
    parsed = pd.to_numeric(cleaned, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _parse_rvd_office_vacancy(content: bytes, url: str) -> pd.DataFrame:
    raw = pd.read_csv(io.BytesIO(content), skiprows=1, dtype=str, encoding="utf-8-sig")
    year_column = next((column for column in raw.columns if str(column).strip().lower() == "year"), raw.columns[0])
    rows: list[dict[str, Any]] = []
    for _, record in raw.iterrows():
        year = pd.to_numeric(record.get(year_column), errors="coerce")
        if pd.isna(year):
            continue
        for column in raw.columns:
            if column == year_column:
                continue
            name = str(column).strip()
            match = re.match(r"(.+?) \(Vacancy\) - (Area|%)$", name, flags=re.I)
            if not match:
                continue
            grade = re.sub(r"[^a-z0-9]+", "_", match.group(1).strip().lower()).strip("_")
            suffix = match.group(2).lower()
            value = _numeric(record.get(column))
            if value is None:
                continue
            rows.append(
                {
                    "date": f"{int(year)}-12-31",
                    "geography": "hong_kong",
                    "district": "all_hong_kong",
                    "segment": grade,
                    "metric": "vacancy_area_sqft" if suffix == "area" else "vacancy_pct",
                    "value": value,
                    "unit": "sqft" if suffix == "area" else "percent",
                    "frequency": "annual",
                    "data_status": "historical_year_end",
                    "source_agency": "Rating and Valuation Department",
                    "source_url": url,
                }
            )
    return pd.DataFrame(rows, columns=RVD_CONTROL_COLUMNS)


def _parse_rvd_district_snapshot(content: bytes, url: str, *, geography: str, table_kind: str) -> pd.DataFrame:
    raw = pd.read_csv(io.BytesIO(content), skiprows=1, dtype=str, encoding="utf-8-sig")
    if raw.empty:
        return _empty(RVD_CONTROL_COLUMNS)
    district_column = raw.columns[0]
    header_text = " | ".join(str(column) for column in raw.columns)
    years = [int(value) for value in re.findall(r"20\d{2}", header_text)]
    current_year = max(years) if years else datetime.now(timezone.utc).year
    rows: list[dict[str, Any]] = []
    for _, record in raw.iterrows():
        district = re.sub(r"\s+", " ", str(record.get(district_column, "")).strip())
        if not district or district.lower() == "nan":
            continue
        for column in raw.columns[1:]:
            name = re.sub(r"\s+", " ", str(column)).strip()
            value = _numeric(record.get(column))
            if value is None:
                continue
            year_match = re.search(r"20\d{2}", name)
            year = int(year_match.group(0)) if year_match else current_year
            lower = name.lower()
            if "stock at" in lower:
                metric, unit = "stock", "sqft"
            elif "amount vacant" in lower:
                metric, unit = "vacancy_area_sqft", "sqft"
            elif "% vacant" in lower:
                metric, unit = "vacancy_pct", "percent"
            elif "completions as a %" in lower:
                metric, unit = "completion_rate_pct", "percent"
            elif "completions" in lower:
                metric, unit = "completions", "sqft"
            else:
                continue
            rows.append(
                {
                    "date": f"{year}-12-31",
                    "geography": geography,
                    "district": district,
                    "segment": table_kind,
                    "metric": metric,
                    "value": value,
                    "unit": unit,
                    "frequency": "annual",
                    "data_status": "latest_annual_snapshot",
                    "source_agency": "Rating and Valuation Department",
                    "source_url": url,
                }
            )
    result = pd.DataFrame(rows, columns=RVD_CONTROL_COLUMNS)
    return result.drop_duplicates(subset=["date", "district", "segment", "metric"]).reset_index(drop=True)


def _parse_rvd_forecast(content: bytes, url: str) -> pd.DataFrame:
    raw = pd.read_csv(io.BytesIO(content), skiprows=1, dtype=str, encoding="utf-8-sig")
    if raw.empty:
        return _empty(RVD_CONTROL_COLUMNS)
    district_column = raw.columns[0]
    rows: list[dict[str, Any]] = []
    for _, record in raw.iterrows():
        district = re.sub(r"\s+", " ", str(record.get(district_column, "")).strip())
        if not district or district.lower() == "nan":
            continue
        for column in raw.columns[1:]:
            name = re.sub(r"\s+", " ", str(column)).strip()
            year_match = re.search(r"20\d{2}", name)
            if not year_match:
                continue
            value = _numeric(record.get(column))
            if value is None:
                continue
            metric = "forecast_completions" if "forecast" in name.lower() else "completions"
            rows.append(
                {
                    "date": f"{int(year_match.group(0))}-12-31",
                    "geography": "hong_kong",
                    "district": district,
                    "segment": "private_commercial",
                    "metric": metric,
                    "value": value,
                    "unit": "sqft",
                    "frequency": "annual",
                    "data_status": "forecast_or_latest_annual_snapshot",
                    "source_agency": "Rating and Valuation Department",
                    "source_url": url,
                }
            )
    return pd.DataFrame(rows, columns=RVD_CONTROL_COLUMNS)


def _fetch_rvd_control(source_name: str, url: str, parser, **kwargs: Any) -> pd.DataFrame:
    content, raw_path = _fetch_csv(source_name, url)
    result = parser(content, url, **kwargs)
    if result.empty:
        return _empty(RVD_CONTROL_COLUMNS)
    return _stamp_lineage(
        result,
        raw_snapshots=[raw_path],
        source_urls=[url],
        lineage_type=f"official_rvd_{source_name}",
    )


def fetch_rvd_office_vacancy_annual() -> pd.DataFrame:
    return _fetch_rvd_control(
        "rvd_private_offices_vacancy",
        RVD_OFFICE_VACANCY_URL,
        _parse_rvd_office_vacancy,
    )


def fetch_rvd_office_stock_vacancy_district() -> pd.DataFrame:
    return _fetch_rvd_control(
        "rvd_office_stock_vacancy_district",
        RVD_OFFICE_STOCK_VACANCY_DISTRICT_URL,
        _parse_rvd_district_snapshot,
        geography="hong_kong",
        table_kind="private_office",
    )


def fetch_rvd_commercial_stock_vacancy_district() -> pd.DataFrame:
    return _fetch_rvd_control(
        "rvd_commercial_stock_vacancy_district",
        RVD_COMMERCIAL_STOCK_VACANCY_DISTRICT_URL,
        _parse_rvd_district_snapshot,
        geography="hong_kong",
        table_kind="private_commercial",
    )


def fetch_rvd_commercial_forecast_completions() -> pd.DataFrame:
    return _fetch_rvd_control(
        "rvd_commercial_forecast_completions",
        RVD_COMMERCIAL_FORECAST_COMPLETIONS_URL,
        _parse_rvd_forecast,
    )
