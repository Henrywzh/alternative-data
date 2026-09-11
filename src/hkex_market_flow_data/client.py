from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

import requests

from .config import HKEX_BASE_URL
from .models import HkexDailyFlowObservation


class HkexMarketFlowClient:
    DAILY_PATH = "/eng/csm/DailyStat/data_tab_daily_{date}e.js"
    SHORT_SELLING_PATH = "/eng/csm/shortsell/data_tab_short_selling_{date}e.js"

    def __init__(self, timeout_seconds: float = 30.0, session: requests.Session | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "text/javascript,*/*"})

    def fetch_dated_file(self, kind: str, trade_date: str) -> tuple[str, bytes]:
        date_token = trade_date.replace("-", "")
        path = self.DAILY_PATH if kind == "daily" else self.SHORT_SELLING_PATH
        url = f"{HKEX_BASE_URL}{path.format(date=date_token)}"
        response = self.session.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        if "tabData" not in response.text:
            raise ValueError(f"HKEX returned a non-data page for {trade_date}: {url}")
        return url, response.content

    @staticmethod
    def _parse_js_array(javascript: str | bytes) -> list[dict[str, Any]]:
        text = javascript.decode("utf-8-sig") if isinstance(javascript, bytes) else javascript.lstrip("\ufeff")
        if "=" not in text:
            raise ValueError("HKEX JavaScript payload does not contain an assignment")
        array_text = text.split("=", 1)[1].strip().rstrip(";")
        # Short-selling files contain a quoted time written with single
        # quotes; the rest of the payload is JSON-compatible.  Restrict the
        # replacement to that known literal rather than rewriting arbitrary
        # names or apostrophes in security names.
        array_text = array_text.replace("'15:15'", '"15:15"')
        array_text = re.sub(r",\s*([}\]])", r"\1", array_text)
        payload = json.loads(array_text)
        if not isinstance(payload, list):
            raise ValueError("HKEX tabData payload is not an array")
        return payload

    @staticmethod
    def _table_rows(item: dict[str, Any], classname: str) -> tuple[list[str], list[list[str]]]:
        for content in item.get("content", []):
            table = content.get("table", {})
            if table.get("classname") != classname:
                continue
            schema = table.get("schema") or []
            headers = list(schema[0]) if schema and isinstance(schema[0], list) else []
            rows: list[list[str]] = []
            for row in table.get("tr", []):
                cells = row.get("td", [])
                if cells and isinstance(cells[0], list):
                    rows.append([str(value) for value in cells[0]])
            return headers, rows
        return [], []

    @staticmethod
    def _number(value: object) -> float | None:
        text = str(value).strip().replace(",", "")
        if not text or text.lower() in {"available", "-", "nan", "none"}:
            return None
        try:
            return float(text.replace("%", ""))
        except ValueError:
            return None

    @classmethod
    def parse_daily_statistics(cls, javascript: str | bytes) -> dict[str, float | str | None]:
        result: dict[str, float | str | None] = {
            "trade_date": None,
            "southbound_buy_hkd_mln": None,
            "southbound_sell_hkd_mln": None,
            "northbound_total_turnover_rmb_mln": None,
        }
        southbound_buy = southbound_sell = northbound_total = 0.0
        southbound_seen = northbound_seen = False
        for item in cls._parse_js_array(javascript):
            market = str(item.get("market", ""))
            if item.get("date"):
                result["trade_date"] = str(item["date"])
            headers, rows = cls._table_rows(item, "tradingTable")
            if not headers or not rows:
                continue
            values = {header: cls._number(rows[idx][0]) for idx, header in enumerate(headers) if idx < len(rows)}
            if "Southbound" in market:
                southbound_seen = True
                southbound_buy += values.get("Buy Turnover") or 0.0
                southbound_sell += values.get("Sell Turnover") or 0.0
            elif "Northbound" in market:
                northbound_seen = True
                northbound_total += values.get("Total Turnover") or 0.0
        if southbound_seen:
            result["southbound_buy_hkd_mln"] = round(southbound_buy, 6)
            result["southbound_sell_hkd_mln"] = round(southbound_sell, 6)
        if northbound_seen:
            result["northbound_total_turnover_rmb_mln"] = round(northbound_total, 6)
        return result

    # The short-selling table carries a two-row header: the first row names the
    # column groups, the second names the sub-columns. HKEX dropped the
    # "Maximum" sub-column from the shares-available group during 2024, which
    # shifted every later column left by one:
    #
    #   2019-2023  [Suspension, Code, Name, Maximum, Remaining, Shares, Value, ...]
    #   2024-      [Suspension, Code, Name,          Remaining, Shares, Value, ...]
    #
    # Reading fixed offsets stored "Remaining" -- the lendable inventory -- as
    # short-selling turnover shares for every pre-2024 row, a different metric
    # at a plausible magnitude, which is the kind of error nothing downstream
    # would flag. Offsets are resolved from the header instead.
    _LEADING_COLUMNS = 3  # Suspension, Stock Code, Stock Name

    @classmethod
    def _short_selling_offsets(cls, table: dict[str, Any]) -> tuple[int, int, int | None] | None:
        """(shares, value, remaining) column indices for this table's layout."""
        sub_header: list[str] = []
        for row in table.get("tr", []):
            if not row.get("tableTitle"):
                continue
            cells = row.get("td", [])
            if not cells or not isinstance(cells[0], list):
                continue
            labels = [str(c) for c in cells[0]]
            if any(lbl.lower().startswith("shares") for lbl in labels):
                sub_header = labels
        if not sub_header:
            return None
        shares = value = remaining = None
        for position, label in enumerate(sub_header):
            normalized = label.lower().strip("* ")
            if normalized == "shares" and shares is None:
                shares = cls._LEADING_COLUMNS + position
            elif normalized.startswith("value") and value is None:
                value = cls._LEADING_COLUMNS + position
            elif normalized.startswith("remaining") and remaining is None:
                remaining = cls._LEADING_COLUMNS + position
        if shares is None or value is None:
            return None
        return shares, value, remaining

    @classmethod
    def parse_short_selling_metrics(cls, javascript: str | bytes) -> dict[str, float | int | str | None]:
        result: dict[str, float | int | str | None] = {
            "trade_date": None,
            "short_selling_turnover_rmb_mln": None,
            "short_selling_turnover_shares": None,
            "short_selling_security_count": 0,
            "short_selling_shares_available": None,
        }
        total_value = total_shares = total_remaining = 0.0
        count = 0
        for item in cls._parse_js_array(javascript):
            if item.get("date"):
                result["trade_date"] = str(item["date"])
            for content in item.get("content", []):
                table = content.get("table", {})
                if table.get("classname") != "shortSellingTable":
                    continue
                offsets = cls._short_selling_offsets(table)
                if offsets is None:
                    continue
                shares_index, value_index, remaining_index = offsets
                for row in table.get("tr", []):
                    if row.get("tableTitle"):
                        continue
                    cells = row.get("td", [])
                    if not cells or not isinstance(cells[0], list):
                        continue
                    values = cells[0]
                    if len(values) <= max(shares_index, value_index):
                        continue
                    shares = cls._number(values[shares_index])
                    value = cls._number(values[value_index])
                    if shares is not None:
                        total_shares += shares
                    if value is not None:
                        total_value += value
                    if remaining_index is not None and len(values) > remaining_index:
                        remaining = cls._number(values[remaining_index])
                        if remaining is not None:
                            total_remaining += remaining
                    count += 1
        result["short_selling_turnover_shares"] = round(total_shares, 6)
        # HKEX reports this column in RMB, not HKD; the name records that and
        # no conversion is applied here.
        result["short_selling_turnover_rmb_mln"] = round(total_value / 1_000_000, 6)
        result["short_selling_security_count"] = count
        result["short_selling_shares_available"] = round(total_remaining, 6)
        return result

    @staticmethod
    def derive_flow_metrics(
        trade_date: str,
        sb_buy_hkd: float | None,
        sb_sell_hkd: float | None,
        nb_buy_rmb: float | None,
        nb_sell_rmb: float | None,
        total_mkt_hkd: float | None,
        short_turnover_hkd: float | None,
        short_turnover_rmb: float | None = None,
        short_selling_security_count: int | None = None,
        short_turnover_shares: float | None = None,
        short_shares_available: float | None = None,
        northbound_total_rmb: float | None = None,
    ) -> HkexDailyFlowObservation:
        sb_net = (sb_buy_hkd - sb_sell_hkd) if (sb_buy_hkd is not None and sb_sell_hkd is not None) else None
        nb_net = (nb_buy_rmb - nb_sell_rmb) if (nb_buy_rmb is not None and nb_sell_rmb is not None) else None
        sb_total = (sb_buy_hkd + sb_sell_hkd) if (sb_buy_hkd is not None and sb_sell_hkd is not None) else None
        sb_share = round((sb_total / total_mkt_hkd) * 100, 4) if (sb_total is not None and total_mkt_hkd) else None
        short_ratio = round((short_turnover_hkd / total_mkt_hkd) * 100, 4) if (short_turnover_hkd is not None and total_mkt_hkd) else None
        return HkexDailyFlowObservation(
            trade_date=trade_date,
            southbound_buy_turnover_hkd_mln=sb_buy_hkd,
            southbound_sell_turnover_hkd_mln=sb_sell_hkd,
            southbound_net_inflow_hkd_mln=round(sb_net, 2) if sb_net is not None else None,
            northbound_buy_turnover_rmb_mln=nb_buy_rmb,
            northbound_sell_turnover_rmb_mln=nb_sell_rmb,
            northbound_net_inflow_rmb_mln=round(nb_net, 2) if nb_net is not None else None,
            total_market_turnover_hkd_mln=total_mkt_hkd,
            southbound_turnover_share_pct=sb_share,
            short_selling_turnover_hkd_mln=short_turnover_hkd,
            short_selling_ratio_pct=short_ratio,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            northbound_total_turnover_rmb_mln=northbound_total_rmb,
            short_selling_turnover_rmb_mln=short_turnover_rmb,
            short_selling_security_count=short_selling_security_count,
            short_selling_turnover_shares=short_turnover_shares,
            short_selling_shares_available=short_shares_available,
        )
