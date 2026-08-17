from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from typing import Any

import requests

from us_census_trade_data.config import (
    CENSUS_IMPORTS_HS_URL,
    CENSUS_IMPORTS_PORTHS_URL,
    DEFAULT_HS_CODE,
    DEFAULT_SOUTH_KOREA_CODE,
    SourceResponseError,
    require_credential,
)
from us_census_trade_data.models import MonthlyImportPoint, PortMonthlyImportPoint, Snapshot


USER_AGENT = "alternative-data-us-census-trade/0.1"
SOURCE_NAME = "U.S. Census Bureau International Trade API"
PORT_SOURCE_NAME = "U.S. Census Bureau Port HS International Trade API"


class CensusInternationalTradeSource:
    """Fetch U.S. monthly HS imports from a selected partner country.

    The Census API returns a header row followed by value rows. The request is
    scoped to one partner country and one import HS code so the normalized
    dataset is directly usable as a Korean memory-import signal.
    """

    RESPONSE_FIELDS = (
        "CTY_CODE",
        "CTY_NAME",
        "I_COMMODITY",
        "I_COMMODITY_SDESC",
        "GEN_VAL_MO",
        "GEN_QY1_MO",
        "UNIT_QY1",
        "GEN_QY2_MO",
        "UNIT_QY2",
        "AIR_VAL_MO",
        "AIR_WGT_MO",
        "CNT_VAL_MO",
        "CNT_WGT_MO",
        "VES_VAL_MO",
        "VES_WGT_MO",
        "CON_VAL_MO",
        "CON_QY1_MO",
        "CON_QY2_MO",
        "YEAR",
        "MONTH",
        "LAST_UPDATE",
        "SUMMARY_LVL",
    )

    def __init__(
        self,
        *,
        api_key: str | None = None,
        session: requests.Session | None = None,
        timeout: int = 60,
    ) -> None:
        self.api_key = (
            api_key
            or os.environ.get("CENSUS_DATA_API_KEY")
            or os.environ.get("CENSUS_API_KEY")
            or os.environ.get("US_CENSUS_API_KEY")
        )
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.timeout = timeout

    def fetch_snapshots(
        self,
        months: Iterable[str],
        *,
        partner_country_code: str = DEFAULT_SOUTH_KOREA_CODE,
        partner_country_codes: Iterable[str] | None = None,
        hs_code: str = DEFAULT_HS_CODE,
    ) -> list[Snapshot]:
        ordered_months = sorted({_validate_month(month) for month in months})
        if not ordered_months:
            return []

        partner_codes = _normalize_partner_codes(partner_country_code, partner_country_codes)
        target_hs = _validate_hs_code(hs_code)
        api_key = require_credential(self.api_key)
        start_month, end_month = ordered_months[0], ordered_months[-1]
        snapshots: list[Snapshot] = []
        for partner_code in partner_codes:
            params = {
                "get": ",".join(self.RESPONSE_FIELDS),
                "time": f"from {start_month} to {end_month}",
                "CTY_CODE": partner_code,
                "I_COMMODITY": target_hs,
                "SUMMARY_LVL": "DET",
                "key": api_key,
            }
            snapshots.append(
                _fetch_snapshot(
                    session=self.session,
                    url=CENSUS_IMPORTS_HS_URL,
                    params=params,
                    timeout=self.timeout,
                    name=f"census_imports_hs_{partner_code}_{target_hs}_{start_month}_{end_month}",
                    source_url=_safe_source_url(CENSUS_IMPORTS_HS_URL, partner_code, target_hs, start_month, end_month),
                    metadata={
                        "partner_country_code": partner_code,
                        "hs_code": target_hs,
                        "start_month": start_month,
                        "end_month": end_month,
                    },
                )
            )
        return snapshots

    def extract(
        self,
        snapshots: Iterable[Snapshot],
        *,
        run_id: str,
        scraped_at: str,
    ) -> list[MonthlyImportPoint]:
        points: list[MonthlyImportPoint] = []
        for snapshot in snapshots:
            payload = _parse_payload(snapshot.body)
            partner_code = str(snapshot.metadata.get("partner_country_code", DEFAULT_SOUTH_KOREA_CODE))
            hs_code = str(snapshot.metadata.get("hs_code", DEFAULT_HS_CODE))
            for row in _rows(payload):
                row_partner_code = _clean_text(_pick(row, "CTY_CODE"))
                row_hs_code = _clean_text(_pick(row, "I_COMMODITY"))
                if row_partner_code not in {partner_code, ""} or row_hs_code not in {hs_code, ""}:
                    continue

                period = _normalize_period(
                    _pick(row, "time"),
                    year=_pick(row, "YEAR"),
                    month=_pick(row, "MONTH"),
                )
                if period is None:
                    continue

                general_value = _to_float(_pick(row, "GEN_VAL_MO"))
                quantity_1_unit = _normalize_unit(_pick(row, "UNIT_QY1"))
                quantity_2_unit = _normalize_unit(_pick(row, "UNIT_QY2"))
                general_quantity = _to_quantity(_pick(row, "GEN_QY1_MO"), quantity_1_unit)
                points.append(
                    MonthlyImportPoint(
                        dataset_id="us_census_memory_imports_monthly",
                        period=period,
                        reporter_country_code="US",
                        reporter_country_name="United States",
                        partner_country_code=row_partner_code or partner_code,
                        partner_country_name=_clean_text(_pick(row, "CTY_NAME")) or "South Korea",
                        hs_code=row_hs_code or hs_code,
                        item_name=_clean_text(_pick(row, "I_COMMODITY_SDESC", "I_COMMODITY_LDESC")),
                        general_import_value_usd=general_value,
                        general_import_quantity=general_quantity,
                        general_import_quantity_unit=quantity_1_unit,
                        general_import_quantity_2=_to_quantity(_pick(row, "GEN_QY2_MO"), quantity_2_unit),
                        general_import_quantity_2_unit=quantity_2_unit,
                        air_import_value_usd=_to_float(_pick(row, "AIR_VAL_MO")),
                        air_shipping_weight=_to_float(_pick(row, "AIR_WGT_MO")),
                        containerized_vessel_import_value_usd=_to_float(_pick(row, "CNT_VAL_MO")),
                        containerized_vessel_shipping_weight=_to_float(_pick(row, "CNT_WGT_MO")),
                        vessel_import_value_usd=_to_float(_pick(row, "VES_VAL_MO")),
                        vessel_shipping_weight=_to_float(_pick(row, "VES_WGT_MO")),
                        consumption_import_value_usd=_to_float(_pick(row, "CON_VAL_MO")),
                        consumption_import_quantity=_to_quantity(_pick(row, "CON_QY1_MO"), quantity_1_unit),
                        consumption_import_quantity_unit=quantity_1_unit,
                        consumption_import_quantity_2=_to_quantity(_pick(row, "CON_QY2_MO"), quantity_2_unit),
                        consumption_import_quantity_2_unit=quantity_2_unit,
                        general_value_per_quantity_unit_usd=(
                            general_value / general_quantity
                            if general_value is not None and general_quantity not in {None, 0}
                            else None
                        ),
                        last_update=_normalize_last_update(_pick(row, "LAST_UPDATE")),
                        source_name=SOURCE_NAME,
                        source_url=snapshot.source_url,
                        source_run_id=run_id,
                        scraped_at=scraped_at,
                        parser_version="census-imports-hs-v1",
                    )
                )
        return points


class CensusPortInternationalTradeSource(CensusInternationalTradeSource):
    """Fetch monthly U.S. imports by port, partner country and HS code."""

    PORT_RESPONSE_FIELDS = (
        "CTY_CODE",
        "CTY_NAME",
        "I_COMMODITY",
        "I_COMMODITY_SDESC",
        "GEN_VAL_MO",
        "AIR_VAL_MO",
        "AIR_WGT_MO",
        "CNT_VAL_MO",
        "CNT_WGT_MO",
        "VES_VAL_MO",
        "VES_WGT_MO",
        "PORT",
        "PORT_NAME",
        "YEAR",
        "MONTH",
        "LAST_UPDATE",
        "SUMMARY_LVL",
    )

    def fetch_port_snapshots(
        self,
        months: Iterable[str],
        *,
        partner_country_code: str = DEFAULT_SOUTH_KOREA_CODE,
        partner_country_codes: Iterable[str] | None = None,
        hs_code: str = DEFAULT_HS_CODE,
    ) -> list[Snapshot]:
        ordered_months = sorted({_validate_month(month) for month in months})
        if not ordered_months:
            return []

        partner_codes = _normalize_partner_codes(partner_country_code, partner_country_codes)
        target_hs = _validate_hs_code(hs_code)
        api_key = require_credential(self.api_key)
        start_month, end_month = ordered_months[0], ordered_months[-1]
        snapshots: list[Snapshot] = []
        for partner_code in partner_codes:
            params = {
                "get": ",".join(self.PORT_RESPONSE_FIELDS),
                "time": f"from {start_month} to {end_month}",
                "CTY_CODE": partner_code,
                "I_COMMODITY": target_hs,
                "SUMMARY_LVL": "DET",
                "key": api_key,
            }
            snapshots.append(
                _fetch_snapshot(
                    session=self.session,
                    url=CENSUS_IMPORTS_PORTHS_URL,
                    params=params,
                    timeout=self.timeout,
                    name=f"census_imports_porths_{partner_code}_{target_hs}_{start_month}_{end_month}",
                    source_url=_safe_source_url(CENSUS_IMPORTS_PORTHS_URL, partner_code, target_hs, start_month, end_month),
                    metadata={
                        "kind": "port_hs",
                        "partner_country_code": partner_code,
                        "hs_code": target_hs,
                        "start_month": start_month,
                        "end_month": end_month,
                    },
                )
            )
        return snapshots

    def extract_port_snapshots(
        self,
        snapshots: Iterable[Snapshot],
        *,
        run_id: str,
        scraped_at: str,
    ) -> list[PortMonthlyImportPoint]:
        points: list[PortMonthlyImportPoint] = []
        for snapshot in snapshots:
            payload = _parse_payload(snapshot.body)
            partner_code = str(snapshot.metadata.get("partner_country_code", DEFAULT_SOUTH_KOREA_CODE))
            hs_code = str(snapshot.metadata.get("hs_code", DEFAULT_HS_CODE))
            for row in _rows(payload):
                row_partner_code = _clean_text(_pick(row, "CTY_CODE"))
                row_hs_code = _clean_text(_pick(row, "I_COMMODITY"))
                port_code = _clean_text(_pick(row, "PORT"))
                if row_partner_code not in {partner_code, ""} or row_hs_code not in {hs_code, ""}:
                    continue
                if not port_code or port_code == "-":
                    continue

                period = _normalize_period(
                    _pick(row, "time"),
                    year=_pick(row, "YEAR"),
                    month=_pick(row, "MONTH"),
                )
                if period is None:
                    continue
                points.append(
                    PortMonthlyImportPoint(
                        dataset_id="us_census_memory_imports_port_monthly",
                        period=period,
                        reporter_country_code="US",
                        reporter_country_name="United States",
                        partner_country_code=row_partner_code or partner_code,
                        partner_country_name=_clean_text(_pick(row, "CTY_NAME")) or "South Korea",
                        hs_code=row_hs_code or hs_code,
                        item_name=_clean_text(_pick(row, "I_COMMODITY_SDESC", "I_COMMODITY_LDESC")),
                        port_code=port_code,
                        port_name=_clean_text(_pick(row, "PORT_NAME")),
                        general_import_value_usd=_to_float(_pick(row, "GEN_VAL_MO")),
                        air_import_value_usd=_to_float(_pick(row, "AIR_VAL_MO")),
                        air_shipping_weight=_to_float(_pick(row, "AIR_WGT_MO")),
                        containerized_vessel_import_value_usd=_to_float(_pick(row, "CNT_VAL_MO")),
                        containerized_vessel_shipping_weight=_to_float(_pick(row, "CNT_WGT_MO")),
                        vessel_import_value_usd=_to_float(_pick(row, "VES_VAL_MO")),
                        vessel_shipping_weight=_to_float(_pick(row, "VES_WGT_MO")),
                        last_update=_normalize_last_update(_pick(row, "LAST_UPDATE")),
                        source_name=PORT_SOURCE_NAME,
                        source_url=snapshot.source_url,
                        source_run_id=run_id,
                        scraped_at=scraped_at,
                        parser_version="census-imports-porths-v1",
                    )
                )
        return points


def _fetch_snapshot(
    *,
    session: requests.Session,
    url: str,
    params: dict[str, str],
    timeout: int,
    name: str,
    source_url: str,
    metadata: dict[str, Any],
) -> Snapshot:
    response = session.get(url, params=params, timeout=timeout)
    status_code = int(getattr(response, "status_code", 200))
    if status_code == 204:
        body = "[]"
    else:
        response.raise_for_status()
        body = response.text
    return Snapshot(name=name, source_url=source_url, body=body, metadata=metadata)


def _safe_source_url(url: str, partner_code: str, hs_code: str, start_month: str, end_month: str) -> str:
    return f"{url}?CTY_CODE={partner_code}&I_COMMODITY={hs_code}&time=from+{start_month}+to+{end_month}"


def _parse_payload(body: str) -> Any:
    if not body.strip():
        return []
    payload = json.loads(body)
    if isinstance(payload, dict) and payload.get("error"):
        message = payload.get("error")
        if isinstance(message, dict):
            message = message.get("message") or message
        raise SourceResponseError(f"Census API error: {message}")
    return payload


def _normalize_partner_codes(
    partner_country_code: str | None,
    partner_country_codes: Iterable[str] | None,
) -> list[str]:
    values = list(partner_country_codes or [])
    if not values:
        values = [partner_country_code or DEFAULT_SOUTH_KOREA_CODE]
    normalized: list[str] = []
    for value in values:
        code = _validate_code(value, "partner_country_code")
        if code not in normalized:
            normalized.append(code)
    return normalized


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        value = payload.get("data") or payload.get("rows") or payload.get("result")
        return _rows(value)
    if not isinstance(payload, list) or not payload:
        return []
    if isinstance(payload[0], dict):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload[0], list):
        return []
    headers = [str(value) for value in payload[0]]
    return [
        _row_from_values(headers, row)
        for row in payload[1:]
        if isinstance(row, list)
    ]


def _row_from_values(headers: list[str], values: list[Any]) -> dict[str, Any]:
    """Keep the first requested value when Census repeats predicate columns."""
    row: dict[str, Any] = {}
    for header, value in zip(headers, values, strict=False):
        row.setdefault(header, value)
    return row


def _pick(row: dict[str, Any], *aliases: str) -> Any:
    for alias in aliases:
        if alias in row and row[alias] not in {None, ""}:
            return row[alias]
    return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", ".", "N/A", "null", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_unit(value: Any) -> str | None:
    text = _clean_text(value)
    if text in {None, "-", ".", "N/A", "null", "None"}:
        return None
    return text


def _normalize_last_update(value: Any) -> str | None:
    """Census currently returns non-date sentinels for LAST_UPDATE."""
    text = _clean_text(value)
    if text in {None, "0", "127", "-", ".", "N/A", "null", "None"}:
        return None
    return text


def _to_quantity(value: Any, unit: str | None) -> float | None:
    """Treat Census's zero/'-' pair as unavailable, not as a measured zero."""
    if unit is None:
        return None
    return _to_float(value)


def _normalize_period(value: Any, *, year: Any = None, month: Any = None) -> str | None:
    if value not in {None, ""}:
        text = str(value).strip()
        match = re.search(r"(\d{4})[-/]?(\d{2})", text)
        if match:
            return f"{match.group(1)}-{match.group(2)}"
    if year not in {None, ""} and month not in {None, ""}:
        try:
            return f"{int(str(year)):04d}-{int(str(month)):02d}"
        except (TypeError, ValueError):
            return None
    return None


def _validate_month(value: str) -> str:
    text = str(value).strip()
    if not re.fullmatch(r"\d{4}-\d{2}", text):
        raise ValueError(f"Months must use YYYY-MM, got {value!r}")
    year, month = (int(part) for part in text.split("-"))
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid month: {value!r}")
    if year < 2010:
        raise ValueError(f"Census monthly trade data starts in 2010, got {value!r}")
    return text


def _validate_code(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not re.fullmatch(r"\d{4}", text):
        raise ValueError(f"{field_name} must be a four-digit Census country code, got {value!r}")
    return text


def _validate_hs_code(value: str) -> str:
    text = str(value).strip()
    if not re.fullmatch(r"\d{2,10}", text):
        raise ValueError(f"hs_code must contain 2-10 digits, got {value!r}")
    return text
