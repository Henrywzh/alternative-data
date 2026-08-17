from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

import requests

from semiconductor_high_frequency_data.config import (
    DEFAULT_KOSIS_ORG_ID,
    DEFAULT_KOSIS_TABLE_ID,
    KOSIS_PARAMETER_URL,
    KOSIS_SOURCE_URL,
    MissingCredentialError,
    SourceResponseError,
)
from semiconductor_high_frequency_data.models import KosisIndustryIndexPoint, Snapshot


class KosisSemiconductorSource:
    """KOSIS production/shipment/inventory table adapter.

    KOSIS table dimensions differ across revisions, so the adapter accepts
    an optional industry code and otherwise filters dimension labels containing
    반도체/semiconductor. The raw row is retained in the snapshot for later
    table-dimension refinement.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        session: requests.Session | None = None,
        timeout: int = 60,
        org_id: str = DEFAULT_KOSIS_ORG_ID,
        table_id: str = DEFAULT_KOSIS_TABLE_ID,
        industry_code: str | None = None,
        industry_pattern: str = r"반도체|semiconductor",
    ) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "alternative-data-semiconductor/1.0"})
        self.timeout = timeout
        self.org_id = org_id
        self.table_id = table_id
        self.industry_code = industry_code
        self.industry_pattern = re.compile(industry_pattern, flags=re.IGNORECASE)

    def fetch_snapshots(self, *, start_month: str, end_month: str) -> list[Snapshot]:
        key = self._require_api_key()
        _validate_month(start_month)
        _validate_month(end_month)
        if end_month < start_month:
            raise ValueError("end_month must be greater than or equal to start_month")
        params = {
            "method": "getList",
            "apiKey": key,
            "format": "json",
            "jsonVD": "Y",
            "orgId": self.org_id,
            "tblId": self.table_id,
            "prdSe": "M",
            "startPrdDe": start_month.replace("-", ""),
            "endPrdDe": end_month.replace("-", ""),
        }
        response = self.session.get(KOSIS_PARAMETER_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        try:
            payload = response.json()
        except (ValueError, AttributeError) as exc:
            raise SourceResponseError("KOSIS returned a non-JSON response") from exc
        if isinstance(payload, dict) and payload.get("err"):
            raise SourceResponseError(f"KOSIS response {payload.get('err')}: {payload.get('errMsg', '')}")
        return [
            Snapshot(
                name=f"kosis_{self.table_id}_{start_month}_{end_month}",
                source_url=KOSIS_PARAMETER_URL,
                body=json.dumps(payload, ensure_ascii=False),
                metadata={
                    "kind": "kosis_industry_index",
                    "org_id": self.org_id,
                    "table_id": self.table_id,
                    "start_month": start_month,
                    "end_month": end_month,
                    "source_page": KOSIS_SOURCE_URL,
                },
            )
        ]

    def extract(
        self,
        snapshots: Iterable[Snapshot],
        *,
        run_id: str,
        scraped_at: str,
    ) -> list[KosisIndustryIndexPoint]:
        points: list[KosisIndustryIndexPoint] = []
        for snapshot in snapshots:
            if snapshot.metadata.get("kind") != "kosis_industry_index":
                continue
            payload = json.loads(snapshot.body)
            for row in _rows(payload):
                period = _normalize_month(_pick(row, "PRD_DE", "PRDDE", "period"))
                if not period:
                    continue
                dimension_text = _dimension_text(row)
                industry_code = _pick_text(row, "C1_OBJ_ID", "C2_OBJ_ID", "OBJ_ID", "industryCode")
                industry_name = _pick_text(row, "C1_OBJ_NM", "C2_OBJ_NM", "OBJ_NM", "industryName")
                if self.industry_code and self.industry_code not in {industry_code, _pick_text(row, "C1", "C2")}:
                    continue
                if not self.industry_code and not self.industry_pattern.search(dimension_text):
                    continue

                measure = _measure_name(dimension_text)
                if measure is None:
                    continue
                points.append(
                    KosisIndustryIndexPoint(
                        dataset_id="kosis_semiconductor_cycle_monthly",
                        period=period,
                        industry_code=industry_code,
                        industry_name=industry_name,
                        measure=measure,
                        value=_to_float(_pick(row, "DT", "DATA_VALUE", "VALUE", "value")),
                        unit=_pick_text(row, "UNIT_NM", "UNIT", "unit"),
                        seasonal_adjustment=_seasonal_adjustment(dimension_text),
                        item_code=_pick_text(row, "ITM_ID", "ITEM_CODE", "itemCode"),
                        item_name=_pick_text(row, "ITM_NM", "ITEM_NM", "itemName"),
                        object_code=_pick_text(row, "C1_OBJ_ID", "C2_OBJ_ID", "OBJ_ID", "objectCode"),
                        object_name=_pick_text(row, "C1_OBJ_NM", "C2_OBJ_NM", "OBJ_NM", "objectName"),
                        release_date=_pick_text(row, "RELEASE_DATE", "releaseDate"),
                        source_table_id=str(snapshot.metadata.get("table_id", self.table_id)),
                        source_org_id=str(snapshot.metadata.get("org_id", self.org_id)),
                        source_url=snapshot.source_url,
                        source_run_id=run_id,
                        scraped_at=scraped_at,
                        parser_version="kosis-semiconductor-v1",
                    )
                )
        return points

    def _require_api_key(self) -> str:
        if not self.api_key:
            raise MissingCredentialError(
                "KOSIS requires an API key. Pass api_key or set KOSIS_API_KEY/KOSIS_KEY."
            )
        return self.api_key


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "rows", "result"):
        value = payload.get(key)
        rows = _rows(value)
        if rows:
            return rows
    return []


def _dimension_text(row: dict[str, Any]) -> str:
    keys = (
        "ITM_NM", "ITEM_NM", "C1_OBJ_NM", "C2_OBJ_NM", "C3_OBJ_NM", "OBJ_NM",
        "UNIT_NM", "itemName", "industryName", "objectName",
    )
    return " ".join(str(row[key]) for key in keys if row.get(key) not in {None, ""})


def _measure_name(text: str) -> str | None:
    lowered = text.lower()
    if "출하" in text or "shipment" in lowered:
        return "shipment"
    if "재고" in text or "inventory" in lowered:
        return "inventory"
    if "생산" in text or "production" in lowered:
        return "production"
    return None


def _seasonal_adjustment(text: str) -> str:
    lowered = text.lower()
    return "seasonally_adjusted" if "계절조정" in text or "seasonally" in lowered or " sa" in lowered else "original"


def _normalize_month(value: Any) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) >= 6 and digits[:4].isdigit():
        return f"{digits[:4]}-{digits[4:6]}"
    return None


def _validate_month(value: str) -> None:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise ValueError(f"KOSIS months must use YYYY-MM, got {value!r}")


def _pick(row: dict[str, Any], *aliases: str) -> Any:
    for alias in aliases:
        if alias in row and row[alias] not in {None, ""}:
            return row[alias]
    return None


def _pick_text(row: dict[str, Any], *aliases: str) -> str | None:
    value = _pick(row, *aliases)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    raw = str(value).strip().replace(",", "")
    if not raw or raw in {"-", "--", "..", "N/A", "null"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
