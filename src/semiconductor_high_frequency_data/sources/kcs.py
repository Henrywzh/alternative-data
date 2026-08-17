from __future__ import annotations

import calendar
import json
import re
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any
from xml.etree import ElementTree

import requests

from semiconductor_high_frequency_data.config import (
    DEFAULT_KCS_HS_CODE,
    DEFAULT_KCS_TAIWAN_COUNTRY_CODE,
    DEFAULT_KCS_WORLD_COUNTRY_CODE,
    KCS_ITEM_COUNTRY_SOURCE_URL,
    KCS_ITEM_COUNTRY_URL,
    KCS_SOURCE_URL,
    KCS_TEN_DAY_URL,
    MissingCredentialError,
    SourceResponseError,
)
from semiconductor_high_frequency_data.models import (
    KcsMemoryMonthlyPoint,
    KcsTenDayPoint,
    Snapshot,
)


class KoreaCustomsHighFrequencySource:
    """KCS 10-day major-product and monthly HS/country trade adapter."""

    TEN_DAY_PARSER_VERSION = "kcs-10day-v1"
    MONTHLY_PARSER_VERSION = "kcs-item-country-v1"

    def __init__(
        self,
        *,
        service_key: str | None = None,
        session: requests.Session | None = None,
        timeout: int = 60,
        hs_code: str = DEFAULT_KCS_HS_CODE,
        world_country_code: str = DEFAULT_KCS_WORLD_COUNTRY_CODE,
        taiwan_country_code: str = DEFAULT_KCS_TAIWAN_COUNTRY_CODE,
    ) -> None:
        self.service_key = service_key
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "alternative-data-semiconductor/1.0"})
        self.timeout = timeout
        self.hs_code = hs_code
        self.world_country_code = world_country_code
        self.taiwan_country_code = taiwan_country_code

    def fetch_ten_day_snapshots(self, months: Iterable[str]) -> list[Snapshot]:
        key = self._require_service_key()
        snapshots: list[Snapshot] = []
        for month in sorted(set(months)):
            params = {
                "serviceKey": key,
                "strtYymm": _month_code(month),
                "endYymm": _month_code(month),
                "type": "json",
            }
            payload = self._get_json(KCS_TEN_DAY_URL, params=params)
            snapshots.append(
                Snapshot(
                    name=f"kcs_10day_{month}",
                    source_url=KCS_TEN_DAY_URL,
                    body=json.dumps(payload, ensure_ascii=False),
                    metadata={"kind": "ten_day", "month": month, "source_page": KCS_SOURCE_URL},
                )
            )
        return snapshots

    def fetch_monthly_memory_snapshots(
        self,
        months: Iterable[str],
        *,
        country_scopes: dict[str, str] | None = None,
    ) -> list[Snapshot]:
        key = self._require_service_key()
        scopes = country_scopes or {
            "world": self.world_country_code,
            "taiwan": self.taiwan_country_code,
        }
        snapshots: list[Snapshot] = []
        for month in sorted(set(months)):
            for scope, country_code in scopes.items():
                params = {
                    "serviceKey": key,
                    "strtYymm": _month_code(month),
                    "endYymm": _month_code(month),
                    "hsSgn": self.hs_code,
                    "cntyCd": country_code,
                    "type": "json",
                }
                payload = self._get_json(KCS_ITEM_COUNTRY_URL, params=params)
                snapshots.append(
                    Snapshot(
                        name=f"kcs_memory_monthly_{scope}_{month}",
                        source_url=KCS_ITEM_COUNTRY_URL,
                        body=json.dumps(payload, ensure_ascii=False),
                        metadata={
                            "kind": "memory_monthly",
                            "month": month,
                            "country_scope": scope,
                            "country_code": country_code,
                            "source_page": KCS_ITEM_COUNTRY_SOURCE_URL,
                        },
                    )
                )
        return snapshots

    def extract_ten_day(
        self,
        snapshots: Iterable[Snapshot],
        *,
        run_id: str,
        scraped_at: str,
    ) -> list[KcsTenDayPoint]:
        points: list[KcsTenDayPoint] = []
        for snapshot in snapshots:
            if snapshot.metadata.get("kind") != "ten_day":
                continue
            payload = json.loads(snapshot.body)
            item = _first_item(payload)
            if item is None:
                continue

            period_month = _normalize_month(item.get("priodMon")) or snapshot.metadata.get("month")
            raw_period_date = _normalize_date(item.get("priodDt"))
            period_start, period_end, release_date = _ten_day_window(raw_period_date, period_month)
            period = _period_key(period_start, period_end, period_month)
            revised = _to_bool(item.get("isRevised") or item.get("revised"))

            metrics = {
                "total_exports": item.get("itemUsdAmt00"),
                "semiconductor_exports": item.get("itemUsdAmt01"),
            }
            for metric, raw_value in metrics.items():
                value = _to_float(raw_value)
                if value is None:
                    continue
                points.append(
                    KcsTenDayPoint(
                        dataset_id="kcs_10day_exports",
                        period=period,
                        period_start=period_start,
                        period_end=period_end,
                        period_month=period_month,
                        release_date=release_date,
                        release_date_inferred=release_date is not None,
                        metric=metric,
                        value=value,
                        unit="usd_thousand",
                        currency="USD",
                        is_preliminary=True,
                        is_revised=revised,
                        source_url=snapshot.source_url,
                        source_run_id=run_id,
                        scraped_at=scraped_at,
                        parser_version=self.TEN_DAY_PARSER_VERSION,
                        raw_period_date=raw_period_date,
                    )
                )
        return points

    def extract_monthly_memory(
        self,
        snapshots: Iterable[Snapshot],
        *,
        run_id: str,
        scraped_at: str,
    ) -> list[KcsMemoryMonthlyPoint]:
        points: list[KcsMemoryMonthlyPoint] = []
        for snapshot in snapshots:
            if snapshot.metadata.get("kind") != "memory_monthly":
                continue
            payload = json.loads(snapshot.body)
            scope = str(snapshot.metadata.get("country_scope", "other"))
            code = str(snapshot.metadata.get("country_code", ""))
            for item in _items(payload):
                period = _normalize_month(item.get("year")) or str(snapshot.metadata.get("month", ""))
                hs_code = _clean_text(item.get("hsCd")) or self.hs_code
                export_value = _to_float(item.get("expDlr"))
                export_weight = _to_float(item.get("expWgt"))
                value_per_kg = None
                if export_value is not None and export_weight is not None and export_weight > 0:
                    value_per_kg = export_value / export_weight
                points.append(
                    KcsMemoryMonthlyPoint(
                        dataset_id="kcs_memory_monthly_country",
                        period=period,
                        country_scope=scope,
                        country_code=_clean_text(item.get("statCd")) or code,
                        country_name=_clean_text(item.get("statCdCntnKor1")),
                        hs_code=hs_code,
                        item_name=_clean_text(item.get("statKor")),
                        export_value_usd=export_value,
                        export_weight_kg=export_weight,
                        import_value_usd=_to_float(item.get("impDlr")),
                        import_weight_kg=_to_float(item.get("impWgt")),
                        trade_balance_usd=_to_float(item.get("balPayments")),
                        export_value_per_kg_usd=value_per_kg,
                        release_date=None,
                        is_preliminary=None,
                        is_revised=None,
                        source_url=snapshot.source_url,
                        source_run_id=run_id,
                        scraped_at=scraped_at,
                        parser_version=self.MONTHLY_PARSER_VERSION,
                    )
                )
        return points

    def _require_service_key(self) -> str:
        if not self.service_key:
            raise MissingCredentialError(
                "KCS requires a public data portal service key. "
                "Pass service_key or set KCS_SERVICE_KEY/KOREA_CUSTOMS_SERVICE_KEY."
            )
        return self.service_key

    def _get_json(self, url: str, *, params: dict[str, str]) -> dict[str, Any]:
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = _decode_response(response)
        result_code, result_message = _find_result(payload)
        if result_code and result_code not in {"00", "0", "200"}:
            raise SourceResponseError(f"KCS response {result_code}: {result_message or 'unknown error'}")
        return payload


def _decode_response(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return payload
    except (ValueError, AttributeError):
        pass
    text = getattr(response, "text", "")
    if not text:
        return {}
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise SourceResponseError(f"KCS returned neither JSON nor XML: {exc}") from exc
    return _xml_to_payload(root)


def _xml_to_payload(root: ElementTree.Element) -> dict[str, Any]:
    header: dict[str, str] = {}
    for element in root.iter():
        tag = _local_name(element.tag)
        if tag in {"resultCode", "resultMsg"} and element.text:
            header[tag] = element.text.strip()
    rows: list[dict[str, Any]] = []
    for item in root.iter():
        if _local_name(item.tag) != "item":
            continue
        row = {
            _local_name(child.tag): (child.text or "").strip()
            for child in list(item)
        }
        if row:
            rows.append(row)
    return {"response": {"header": header, "body": {"items": {"item": rows}}}}


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = payload.get("response", payload)
    if not isinstance(body, dict):
        return []
    body = body.get("body", body)
    if not isinstance(body, dict):
        return []
    items = body.get("items", body.get("item", []))
    if isinstance(items, dict):
        items = items.get("item", items.get("items", []))
    if isinstance(items, dict):
        return [items]
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _first_item(payload: dict[str, Any]) -> dict[str, Any] | None:
    items = _items(payload)
    return items[0] if items else None


def _find_result(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    response = payload.get("response", payload)
    if not isinstance(response, dict):
        return None, None
    header = response.get("header", {})
    if not isinstance(header, dict):
        return None, None
    return _clean_text(header.get("resultCode")), _clean_text(header.get("resultMsg"))


def _month_code(value: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2})", value.strip())
    if not match:
        raise ValueError(f"Expected YYYY-MM, got {value!r}")
    return "".join(match.groups())


def _normalize_month(value: object) -> str | None:
    raw = _clean_text(value)
    if not raw:
        return None
    match = re.search(r"(\d{4})[.\-/]?(\d{2})", raw)
    return f"{match.group(1)}-{match.group(2)}" if match else None


def _normalize_date(value: object) -> str | None:
    raw = _clean_text(value)
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return None


def _ten_day_window(raw_period_date: str | None, period_month: str | None) -> tuple[str | None, str | None, str | None]:
    if raw_period_date:
        end_date = date.fromisoformat(raw_period_date)
        if end_date.day <= 10:
            start_date = end_date.replace(day=1)
            release = end_date + timedelta(days=1)
        elif end_date.day <= 20:
            start_date = end_date.replace(day=11)
            release = end_date + timedelta(days=1)
        else:
            start_date = end_date.replace(day=21)
            next_month = end_date.replace(day=28) + timedelta(days=4)
            release = next_month.replace(day=1)
        return start_date.isoformat(), end_date.isoformat(), release.isoformat()
    if period_month:
        year, month = (int(part) for part in period_month.split("-"))
        end_day = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{end_day:02d}", None
    return None, None, None


def _period_key(period_start: str | None, period_end: str | None, period_month: str | None) -> str:
    if period_start and period_end:
        return f"{period_start}_{period_end}"
    return period_month or "unknown"


def _to_float(value: object) -> float | None:
    raw = _clean_text(value)
    if not raw or raw in {"-", "--", "N/A", "null"}:
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _to_bool(value: object) -> bool | None:
    raw = _clean_text(value).lower()
    if not raw:
        return None
    if raw in {"true", "1", "y", "yes", "예", "수정"}:
        return True
    if raw in {"false", "0", "n", "no", "아니오"}:
        return False
    return None


def _clean_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]
