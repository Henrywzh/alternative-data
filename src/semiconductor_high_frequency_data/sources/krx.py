from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date
from typing import Any

import requests

from semiconductor_high_frequency_data.config import KRX_JSON_URL, KRX_SOURCE_URL, SourceResponseError
from semiconductor_high_frequency_data.models import KrxPositioningPoint, Snapshot


class KrxAuthenticationRequired(SourceResponseError):
    """Raised when the Data Marketplace session is not authenticated."""


class KrxPositioningSource:
    """KRX Data Marketplace adapter for issue-level investor and short data.

    The Data Marketplace UI endpoint is session-gated. Callers can pass an
    authenticated requests.Session; the parser remains independently testable
    with raw response fixtures.
    """

    INVESTOR_BLD = "dbms/MDC/STAT/standard/MDCSTAT02303"
    SHORT_POSITION_BLD = "dbms/MDC_OUT/STAT/srt/MDCSTAT30001_OUT"

    DEFAULT_ISINS = {
        "000660": "KR7000660001",
        "005930": "KR7005930003",
    }

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: int = 60,
        investor_bld: str | None = None,
        short_position_bld: str | None = None,
        auth_key: str | None = None,
        cookie_header: str | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "alternative-data-semiconductor/1.0",
            "Referer": KRX_SOURCE_URL,
            "X-Requested-With": "XMLHttpRequest",
        })
        self.timeout = timeout
        self.investor_bld = investor_bld or self.INVESTOR_BLD
        self.short_position_bld = short_position_bld or self.SHORT_POSITION_BLD
        self.auth_key = auth_key
        if cookie_header:
            self.session.headers["Cookie"] = cookie_header

    def fetch_snapshots(
        self,
        *,
        start_date: str,
        end_date: str,
        instrument_codes: Iterable[str],
        instrument_isins: dict[str, str] | None = None,
        include_investor_flow: bool = True,
        include_short_position: bool = True,
    ) -> list[Snapshot]:
        _validate_date(start_date)
        _validate_date(end_date)
        if end_date < start_date:
            raise ValueError("end_date must be greater than or equal to start_date")

        isins = dict(self.DEFAULT_ISINS)
        isins.update(instrument_isins or {})
        snapshots: list[Snapshot] = []
        for raw_code in sorted(set(instrument_codes)):
            code = _normalize_instrument_code(raw_code)
            isin = isins.get(code, code)
            if include_investor_flow:
                data = {
                    "bld": self.investor_bld,
                    "locale": "ko_KR",
                    "isuCd": isin,
                    "isuCd2": code,
                    "strtDd": start_date,
                    "endDd": end_date,
                    "share": "1",
                    "money": "1",
                    "csvxls_isNo": "false",
                }
                payload = self._post(data)
                snapshots.append(
                    Snapshot(
                        name=f"krx_investor_flow_{code}_{start_date}_{end_date}",
                        source_url=KRX_JSON_URL,
                        body=json.dumps(payload, ensure_ascii=False),
                        metadata={
                            "kind": "investor_flow",
                            "instrument_code": code,
                            "instrument_isin": isin,
                            "start_date": start_date,
                            "end_date": end_date,
                            "bld": self.investor_bld,
                        },
                    )
                )
            if include_short_position:
                data = {
                    "bld": self.short_position_bld,
                    "locale": "ko_KR",
                    "isuCd": code,
                    "strtDd": start_date,
                    "endDd": end_date,
                    "share": "1",
                    "money": "1",
                    "csvxls_isNo": "false",
                }
                payload = self._post(data)
                snapshots.append(
                    Snapshot(
                        name=f"krx_short_position_{code}_{start_date}_{end_date}",
                        source_url=KRX_JSON_URL,
                        body=json.dumps(payload, ensure_ascii=False),
                        metadata={
                            "kind": "short_position",
                            "instrument_code": code,
                            "instrument_isin": isin,
                            "start_date": start_date,
                            "end_date": end_date,
                            "bld": self.short_position_bld,
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
    ) -> list[KrxPositioningPoint]:
        points: list[KrxPositioningPoint] = []
        for snapshot in snapshots:
            kind = str(snapshot.metadata.get("kind", ""))
            if kind not in {"investor_flow", "short_position"}:
                continue
            payload = json.loads(snapshot.body)
            rows = _rows(payload)
            code = str(snapshot.metadata.get("instrument_code", ""))
            for row in rows:
                trade_date = _normalize_date(_pick(row, "TRD_DD", "TRD_DD1", "date", "tradeDate"))
                if not trade_date:
                    continue
                instrument_name = _pick_text(row, "ISU_NM", "isuNm", "instrumentName")
                if kind == "short_position":
                    points.extend(
                        self._extract_short_row(
                            row,
                            trade_date=trade_date,
                            instrument_code=code,
                            instrument_name=instrument_name,
                            snapshot=snapshot,
                            run_id=run_id,
                            scraped_at=scraped_at,
                        )
                    )
                else:
                    points.extend(
                        self._extract_investor_row(
                            row,
                            trade_date=trade_date,
                            instrument_code=code,
                            instrument_name=instrument_name,
                            snapshot=snapshot,
                            run_id=run_id,
                            scraped_at=scraped_at,
                        )
                    )
        return points

    def _extract_short_row(
        self,
        row: dict[str, Any],
        *,
        trade_date: str,
        instrument_code: str,
        instrument_name: str | None,
        snapshot: Snapshot,
        run_id: str,
        scraped_at: str,
    ) -> list[KrxPositioningPoint]:
        fields = {
            "short_volume": ("CVSRTSELL_TRDVOL", "SRTSELL_TRDVOL", "shortVolume"),
            "short_value": ("CVSRTSELL_TRDVAL", "SRTSELL_TRDVAL", "shortValue"),
            "net_short_balance_volume": ("STR_CONST_VAL1", "NET_SRTSELL_TRDVOL", "netShortBalanceVolume"),
            "net_short_balance_value": ("STR_CONST_VAL2", "NET_SRTSELL_TRDVAL", "netShortBalanceValue"),
        }
        points: list[KrxPositioningPoint] = []
        for measure, aliases in fields.items():
            value = _to_float(_pick(row, *aliases))
            if value is None:
                continue
            is_balance = measure.startswith("net_short_balance")
            points.append(
                KrxPositioningPoint(
                    dataset_id="krx_positioning_daily",
                    trade_date=trade_date,
                    instrument_code=instrument_code,
                    instrument_name=instrument_name,
                    market=_pick_text(row, "MKT_NM", "market", "marketName"),
                    data_family="issue_short_position",
                    investor_type=None,
                    measure=measure,
                    value=value,
                    unit="KRW" if measure.endswith("value") else "shares",
                    currency="KRW" if measure.endswith("value") else None,
                    availability_lag_days=2 if is_balance else 0,
                    source_url=snapshot.source_url,
                    source_run_id=run_id,
                    scraped_at=scraped_at,
                    parser_version="krx-short-position-v1",
                )
            )
        return points

    def _extract_investor_row(
        self,
        row: dict[str, Any],
        *,
        trade_date: str,
        instrument_code: str,
        instrument_name: str | None,
        snapshot: Snapshot,
        run_id: str,
        scraped_at: str,
    ) -> list[KrxPositioningPoint]:
        investor_type = _normalize_investor_type(
            _pick_text(row, "INVST_TP_NM", "INVESTOR_TYPE", "investorType", "INVST_TP")
        )
        aliases_by_measure = {
            "buy_shares": ("FOR_BUY_QTY", "FRGN_BUY_QTY", "FOREIGN_BUY_QTY", "BUY_QTY", "buyShares"),
            "sell_shares": ("FOR_SELL_QTY", "FRGN_SELL_QTY", "FOREIGN_SELL_QTY", "SELL_QTY", "sellShares"),
            "net_buy_shares": ("FOR_NETBUY_QTY", "FRGN_NETBUY_QTY", "FOREIGN_NETBUY_QTY", "NETBUY_QTY", "netBuyShares"),
            "buy_value": ("FOR_BUY_AMT", "FRGN_BUY_AMT", "FOREIGN_BUY_AMT", "BUY_AMT", "buyValue"),
            "sell_value": ("FOR_SELL_AMT", "FRGN_SELL_AMT", "FOREIGN_SELL_AMT", "SELL_AMT", "sellValue"),
            "net_buy_value": ("FOR_NETBUY_AMT", "FRGN_NETBUY_AMT", "FOREIGN_NETBUY_AMT", "NETBUY_AMT", "netBuyValue"),
        }
        points: list[KrxPositioningPoint] = []
        for measure, aliases in aliases_by_measure.items():
            value = _to_float(_pick(row, *aliases))
            if value is None:
                continue
            points.append(
                KrxPositioningPoint(
                    dataset_id="krx_positioning_daily",
                    trade_date=trade_date,
                    instrument_code=instrument_code,
                    instrument_name=instrument_name,
                    market=_pick_text(row, "MKT_NM", "market", "marketName"),
                    data_family="investor_flow",
                    investor_type=investor_type or "foreigner",
                    measure=measure,
                    value=value,
                    unit="KRW" if measure.endswith("value") else "shares",
                    currency="KRW" if measure.endswith("value") else None,
                    availability_lag_days=0,
                    source_url=snapshot.source_url,
                    source_run_id=run_id,
                    scraped_at=scraped_at,
                    parser_version="krx-investor-flow-v1",
                )
            )
        return points

    def _post(self, data: dict[str, str]) -> dict[str, Any]:
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        if self.auth_key:
            headers["AUTH_KEY"] = self.auth_key
        response = self.session.post(
            KRX_JSON_URL,
            data=data,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        text = getattr(response, "text", "")
        if "LOGOUT" in text or "로그인 또는 회원가입" in text:
            raise KrxAuthenticationRequired(
                "KRX Data Marketplace requires an authenticated session for this endpoint"
            )
        try:
            payload = response.json()
        except (ValueError, AttributeError) as exc:
            raise SourceResponseError("KRX returned a non-JSON response") from exc
        if not isinstance(payload, dict):
            raise SourceResponseError("KRX returned an unexpected JSON payload")
        return payload


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("OutBlock_1", "outBlock_1", "rows", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    for value in payload.values():
        if isinstance(value, dict):
            rows = _rows(value)
            if rows:
                return rows
        elif isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
            return value
    return []


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


def _normalize_instrument_code(value: str) -> str:
    code = str(value).strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError(f"KRX instrument code must be six digits, got {value!r}")
    return code


def _validate_date(value: str) -> None:
    try:
        date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}")
    except (ValueError, IndexError):
        raise ValueError(f"KRX dates must use YYYYMMDD, got {value!r}") from None


def _normalize_date(value: Any) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    raw = str(value).strip().replace(",", "")
    if not raw or raw in {"-", "--", "N/A", "null"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _normalize_investor_type(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if "외국" in normalized or "foreign" in normalized:
        return "foreigner"
    if "기관" in normalized or "institution" in normalized:
        return "institution"
    if "개인" in normalized or "retail" in normalized or "individual" in normalized:
        return "retail"
    if "기타" in normalized or "other" in normalized:
        return "other"
    return normalized
