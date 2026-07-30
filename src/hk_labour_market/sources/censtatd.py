"""Adapter for C&SD Web Table full-series JSON API responses."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from ..config import CENSTATD_API_URL, DEFAULT_HEADERS
from ..source_registry import CenstatdTableSpec


class CenstatdFetchError(RuntimeError):
    """Raised when C&SD does not return a successful complete table response."""

    def __init__(self, message: str, *, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.payload = payload


def _period_end(period: str) -> str | None:
    """Return a calendar period end without changing C&SD's original period."""
    text = str(period).strip()
    if len(text) == 4 and text.isdigit():
        return f"{text}-12-31"
    if len(text) == 6 and text.isdigit():
        return (pd.Period(f"{text[:4]}-{text[4:]}", freq="M")).end_time.date().isoformat()
    return None


def _frequency_label(code: str) -> str:
    return {
        "M3M": "rolling_three_months",
        "Q": "quarterly",
        "Y": "annual",
        # Several employment/vacancy tables are period-end observations
        # reported for March/June/September/December despite this API code.
        "M": "month_end_observation",
    }.get(code, "source_defined")


def _as_text(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def normalize_censtatd_table(payload: dict[str, Any], spec: CenstatdTableSpec) -> pd.DataFrame:
    """Flatten C&SD records while preserving source codes, descriptions and flags."""
    header = payload.get("header") if isinstance(payload, dict) else None
    status = header.get("status", {}) if isinstance(header, dict) else {}
    if status.get("name") != "Success":
        raise CenstatdFetchError(f"{spec.table_id}: API status was not Success: {status}")
    records = payload.get("dataSet")
    if not isinstance(records, list) or not records:
        raise CenstatdFetchError(f"{spec.table_id}: API returned no dataSet records")

    title = str(header.get("title") or spec.title)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    normalized: list[dict[str, Any]] = []
    measure_keys = {"freq", "period", "sv", "svDesc", "figure", "sd_value"}
    for record in records:
        if not isinstance(record, dict):
            continue
        # C&SD tables have different classification dimensions (e.g. MPS,
        # SECTOR, END_USE). Preserve every source dimension rather than
        # hardcoding a finite list and accidentally collapsing the grain.
        dimension_codes = {
            key: _as_text(record.get(key))
            for key in sorted(record)
            if key not in measure_keys and not key.endswith("Desc")
        }
        source_dimensions = {
            key: _as_text(record.get(key))
            for key in sorted(record)
            if key not in measure_keys
        }
        figure = pd.to_numeric(pd.Series([record.get("figure")]), errors="coerce").iloc[0]
        frequency_code = _as_text(record.get("freq")) or ""
        row = {
            "source_table_id": spec.table_id,
            "source_title": title,
            "source_url": spec.source_url,
            "period": _as_text(record.get("period")),
            "period_end": _period_end(_as_text(record.get("period")) or ""),
            "frequency_code": frequency_code,
            "frequency_label": _frequency_label(frequency_code),
            "metric_code": _as_text(record.get("sv")),
            "metric_label": _as_text(record.get("svDesc")),
            "dimension_key": json.dumps(dimension_codes, ensure_ascii=False, sort_keys=True),
            "source_dimensions_json": json.dumps(source_dimensions, ensure_ascii=False, sort_keys=True),
            "value": None if pd.isna(figure) else float(figure),
            "status_flag": _as_text(record.get("sd_value")),
            # A few official tables use MIND/MOCC as the primary
            # classification key rather than IND/OCC.  Expose both the
            # generic alias and the source-specific main_* fields so
            # downstream consumers do not mistake a populated table for an
            # unclassified one.
            "industry_code": _as_text(record.get("IND")) or _as_text(record.get("MIND")),
            "industry": _as_text(record.get("INDDesc")) or _as_text(record.get("MINDDesc")),
            "main_industry_code": _as_text(record.get("MIND")),
            "main_industry": _as_text(record.get("MINDDesc")),
            "occupation_code": _as_text(record.get("OCC")) or _as_text(record.get("MOCC")),
            "occupation": _as_text(record.get("OCCDesc")) or _as_text(record.get("MOCCDesc")),
            "main_occupation_code": _as_text(record.get("MOCC")),
            "main_occupation": _as_text(record.get("MOCCDesc")),
            "establishment_size_code": _as_text(record.get("MPS")),
            "establishment_size": _as_text(record.get("MPSDesc")),
            "construction_sector_code": _as_text(record.get("SECTOR")),
            "construction_sector": _as_text(record.get("SECTORDesc")),
            "construction_site_type_code": _as_text(record.get("TYPE_CON")),
            "construction_site_type": _as_text(record.get("TYPE_CONDesc")),
            "construction_end_use_code": _as_text(record.get("END_USE")),
            "construction_end_use": _as_text(record.get("END_USEDesc")),
            "construction_site_size_code": _as_text(record.get("EMP_SIZE")),
            "construction_site_size": _as_text(record.get("EMP_SIZEDesc")),
            "employment_nature_code": _as_text(record.get("EMP_NATURE")),
            "employment_nature": _as_text(record.get("EMP_NATUREDesc")),
            "age_group_code": _as_text(record.get("AGE")),
            "age_group": _as_text(record.get("AGEDesc")),
            "education_code": _as_text(record.get("EDU")),
            "education": _as_text(record.get("EDUDesc")),
            "hourly_wage_group_code": _as_text(record.get("HWGP")),
            "hourly_wage_group": _as_text(record.get("HWGPDesc")),
            "weekly_hours_group_code": _as_text(record.get("WWHGP")),
            "weekly_hours_group": _as_text(record.get("WWHGPDesc")),
            "sex_code": _as_text(record.get("SEX")),
            "sex": _as_text(record.get("SEXDesc")),
            "household_size_code": _as_text(record.get("HHSIZE")),
            "household_size": _as_text(record.get("HHSIZEDesc")),
            "retrieved_at": retrieved_at,
            "data_source": "official_censtatd_api",
        }
        normalized.append(row)
    frame = pd.DataFrame(normalized)
    if frame.empty:
        raise CenstatdFetchError(f"{spec.table_id}: no usable record objects")
    return frame


def fetch_censtatd_table(
    spec: CenstatdTableSpec,
    *,
    session: requests.Session | None = None,
    timeout: int = 90,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Fetch one full history table and return both raw response and normalized frame."""
    client = session or requests.Session()
    response = client.get(
        CENSTATD_API_URL,
        params={"id": spec.table_id, "lang": "en", "full_series": "1"},
        headers=DEFAULT_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    try:
        frame = normalize_censtatd_table(payload, spec)
    except CenstatdFetchError as exc:
        raise CenstatdFetchError(str(exc), payload=payload) from exc
    return payload, frame
