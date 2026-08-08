"""Free, exchange-published short-side proxies for the airline universe.

These observations improve trade-implementation context but are deliberately
not labelled as borrow availability.  HKEX supplies daily regulated
short-selling turnover; SSE supplies margin-short balance and turnover fields
for eligible securities.  Neither source provides locatable shares, borrow
fee, recall risk or a broker-specific execution guarantee.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, NORMALIZED_DIR


OUTPUT_PATH = NORMALIZED_DIR / "airline_short_side_proxies.csv"
HKEX_SHORT_URL_TEMPLATE = "https://www.hkex.com.hk/eng/stat/smstat/dayquot/d{date}e.htm"
HKEX_SOURCE_URL = "https://www.hkex.com.hk/eng/stat/smstat/dayquot/"
SSE_SOURCE_URL = "https://www.sse.com.cn/market/othersdata/margin/detail/"

HK_UNIVERSE: dict[str, dict[str, str]] = {
    "293": {"ticker": "0293.HK", "company": "Cathay Pacific"},
    "753": {"ticker": "0753.HK", "company": "Air China"},
    "1055": {"ticker": "01055.HK", "company": "China Southern Airlines"},
    "670": {"ticker": "0670.HK", "company": "China Eastern Airlines"},
}

A_UNIVERSE: dict[str, dict[str, str]] = {
    "601111": {"ticker": "601111.SH", "company": "Air China"},
    "600029": {"ticker": "600029.SH", "company": "China Southern Airlines"},
    "600115": {"ticker": "600115.SH", "company": "China Eastern Airlines"},
    "601021": {"ticker": "601021.SH", "company": "Spring Airlines"},
    "600221": {"ticker": "600221.SH", "company": "Hainan Airlines Holdings"},
    "603885": {"ticker": "603885.SH", "company": "Juneyao Airlines"},
}

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "security_code", "observation_date",
    "short_proxy_type", "short_proxy_status", "short_turnover_shares",
    "short_turnover_native", "total_turnover_shares", "total_turnover_native",
    "short_turnover_pct", "margin_short_balance_shares", "margin_short_sell_volume",
    "margin_short_repay_volume", "margin_security_present", "native_currency",
    "borrow_data_available", "source_quality", "source_url", "source_note", "retrieved_at",
]


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(str(value).replace(",", ""), errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _date_text(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _hkex_report_block(html: str) -> str:
    text = BeautifulSoup(html, "html.parser").get_text("\n")
    marker = "SHORT SELLING TURNOVER - DAILY REPORT"
    start = text.rfind(marker)
    return text[start:] if start >= 0 else ""


def parse_hkex_short_turnover(
    html: str,
    *,
    observation_date: str,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse the current short-turnover table from an HKEX daily report."""
    retrieved = retrieved_at or _retrieved_at()
    block = _hkex_report_block(html)
    rows: list[dict[str, Any]] = []
    for line in block.splitlines():
        parts = line.split()
        if not parts or parts[0] not in HK_UNIVERSE or len(parts) < 6:
            continue
        # Current rows have four numeric columns after the stock name.  The
        # later adjusted-turnover section has only two and is intentionally
        # excluded by this fixed tail shape.
        values = [_number(value) for value in parts[-4:]]
        if any(value is None for value in values):
            continue
        code = parts[0]
        metadata = HK_UNIVERSE[code]
        short_shares, short_value, total_shares, total_value = values
        rows.append({
            "dataset_id": "airline_short_side_proxies",
            "company": metadata["company"],
            "ticker": metadata["ticker"],
            "market": "HK",
            "security_code": code,
            "observation_date": observation_date,
            "short_proxy_type": "hkex_regulated_short_turnover",
            "short_proxy_status": "observed",
            "short_turnover_shares": short_shares,
            "short_turnover_native": short_value,
            "total_turnover_shares": total_shares,
            "total_turnover_native": total_value,
            "short_turnover_pct": 100.0 * short_value / total_value if total_value else None,
            "margin_short_balance_shares": None,
            "margin_short_sell_volume": None,
            "margin_short_repay_volume": None,
            "margin_security_present": None,
            "native_currency": "HKD",
            "borrow_data_available": False,
            "source_quality": "hkex_public_daily_short_turnover",
            "source_url": HKEX_SHORT_URL_TEMPLATE.format(date=pd.Timestamp(observation_date).strftime("%y%m%d")),
            "source_note": (
                "HKEX public daily regulated short-selling turnover. This is executed short-turnover activity, "
                "not outstanding short interest, locatable borrow, borrow fee or recall risk."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def normalize_sse_margin_detail(
    frame: pd.DataFrame,
    *,
    observation_date: str,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Normalize SSE margin-short detail for the six A-share airline names."""
    retrieved = retrieved_at or _retrieved_at()
    rows: list[dict[str, Any]] = []
    if frame is None or frame.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    code_column = "标的证券代码"
    for code, metadata in A_UNIVERSE.items():
        source = frame.loc[frame[code_column].astype(str).str.zfill(6).eq(code)] if code_column in frame else pd.DataFrame()
        if source.empty:
            continue
        item = source.iloc[0]
        rows.append({
            "dataset_id": "airline_short_side_proxies",
            "company": metadata["company"],
            "ticker": metadata["ticker"],
            "market": "CN_A",
            "security_code": code,
            "observation_date": observation_date,
            "short_proxy_type": "sse_margin_short_balance",
            "short_proxy_status": "observed",
            "short_turnover_shares": None,
            "short_turnover_native": None,
            "total_turnover_shares": None,
            "total_turnover_native": None,
            "short_turnover_pct": None,
            "margin_short_balance_shares": _number(item.get("融券余量")),
            "margin_short_sell_volume": _number(item.get("融券卖出量")),
            "margin_short_repay_volume": _number(item.get("融券偿还量")),
            "margin_security_present": True,
            "native_currency": "RMB",
            "borrow_data_available": False,
            "source_quality": "sse_public_margin_detail_via_akshare",
            "source_url": SSE_SOURCE_URL,
            "source_note": (
                "SSE margin-detail snapshot for an eligible margin security. The securities-lending balance/volume "
                "is a public short-side proxy, not broker-locatable borrow, borrow fee or execution guarantee."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def _candidate_dates(end_date: str, lookback: int = 7) -> list[str]:
    end = pd.Timestamp(end_date).date()
    return [(end - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(lookback)]


def fetch_airline_short_side_proxies(
    *,
    observation_date: str | None = None,
) -> pd.DataFrame:
    """Fetch the latest available public HKEX and SSE short-side proxies."""
    requested = _date_text(observation_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if requested is None:
        raise ValueError("observation_date must be parseable")
    retrieved = _retrieved_at()
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    hk = pd.DataFrame(columns=OUTPUT_COLUMNS)
    for date in _candidate_dates(requested):
        url = HKEX_SHORT_URL_TEMPLATE.format(date=pd.Timestamp(date).strftime("%y%m%d"))
        response = session.get(url, timeout=max(DEFAULT_TIMEOUT, 30))
        if response.status_code != 200 or "SHORT SELLING TURNOVER - DAILY REPORT" not in response.text:
            continue
        hk = parse_hkex_short_turnover(response.text, observation_date=date, retrieved_at=retrieved)
        if not hk.empty:
            break

    try:
        import akshare as ak
    except ImportError:  # pragma: no cover
        ak = None
    sse = pd.DataFrame(columns=OUTPUT_COLUMNS)
    if ak is not None:
        for date in _candidate_dates(requested):
            try:
                raw = ak.stock_margin_detail_sse(pd.Timestamp(date).strftime("%Y%m%d"))
            except Exception:
                continue
            sse = normalize_sse_margin_detail(raw, observation_date=date, retrieved_at=retrieved)
            if not sse.empty:
                break

    frames = [frame for frame in (hk, sse) if not frame.empty]
    result = (
        pd.DataFrame(
            [record for frame in frames for record in frame.to_dict("records")],
            columns=OUTPUT_COLUMNS,
        )
        if frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    )
    for column in OUTPUT_COLUMNS:
        if column not in result:
            result[column] = None
    result = result[OUTPUT_COLUMNS].sort_values(["market", "company"]).reset_index(drop=True)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
