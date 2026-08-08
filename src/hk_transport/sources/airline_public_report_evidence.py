"""Structured public sell-side evidence from the 10jqka airline forecast pages.

The page exposes a useful current view of institution forecasts, but it is not
an official broker-vintage database.  EPS and net-profit rows have a visible
institution report date and can be used as dated public evidence.  The
institution-level revenue tooltips do not expose a row-level date, so revenue
rows are retained with an explicit ``page_snapshot_only`` scope and must not be
used as dated revisions.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import DEFAULT_HEADERS, NORMALIZED_DIR


OUTPUT_PATH = NORMALIZED_DIR / "airline_public_report_evidence.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "ticker", "company", "source_url", "snapshot_date",
    "report_date", "information_scope", "institution", "analyst",
    "fiscal_year", "metric", "forecast_value_native", "native_unit",
    "native_currency", "rating", "revision_flag", "source_quality",
    "source_note", "retrieved_at",
]


PUBLIC_REPORT_PAGES: tuple[dict[str, str], ...] = (
    {
        "symbol": "601111", "ticker": "0753.HK / 601111.SH",
        "company": "Air China",
        "source_url": "https://basic.10jqka.com.cn/601111/worth.html",
    },
    {
        "symbol": "600029", "ticker": "01055.HK / 600029.SH",
        "company": "China Southern Airlines",
        "source_url": "https://basic.10jqka.com.cn/600029/worth.html",
    },
    {
        "symbol": "600115", "ticker": "0670.HK / 600115.SH",
        "company": "China Eastern Airlines",
        "source_url": "https://basic.10jqka.com.cn/600115/worth.html",
    },
    {
        "symbol": "601021", "ticker": "601021.SH",
        "company": "Spring Airlines",
        "source_url": "https://basic.10jqka.com.cn/601021/worth.html",
    },
    {
        "symbol": "603885", "ticker": "603885.SH",
        "company": "Juneyao Airlines",
        "source_url": "https://basic.10jqka.com.cn/603885/worth.html",
    },
    {
        "symbol": "600221", "ticker": "600221.SH",
        "company": "Hainan Airlines Holdings",
        "source_url": "https://basic.10jqka.com.cn/600221/worth.html",
    },
)

_DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def _text(tag: Any) -> str:
    return " ".join(tag.stripped_strings).strip() if tag is not None else ""


def _clean_rating(value: str | None) -> str | None:
    text = (value or "").strip()
    return None if not text or text in {"-", "—", "--"} else text


def _numeric_value(value: str) -> float | None:
    text = str(value).replace(",", "").strip()
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    number = float(match.group(0))
    # Net-profit cells are normally RMB hundred-million, but some pages show
    # small values in ten-thousand RMB.  Convert to the same RMB 100m unit.
    if "万" in text and "亿" not in text:
        number /= 10_000.0
    return number


def _revision_flag(cell: Any) -> str:
    marker = cell.find("s") if cell is not None else None
    classes = set(marker.get("class", [])) if marker is not None else set()
    if "up" in classes:
        return "up"
    if "down" in classes:
        return "down"
    return "unchanged_or_not_shown"


def _table_rows(table: Any) -> list[Any]:
    body = table.find("tbody", recursive=False)
    if body is not None:
        return body.find_all("tr", recursive=False)
    return table.find_all("tr", recursive=False)


def _base_row(
    *,
    page: Mapping[str, str],
    snapshot_date: str,
    report_date: str | None,
    information_scope: str,
    institution: str,
    analyst: str,
    fiscal_year: int,
    metric: str,
    value: float,
    unit: str,
    rating: str | None,
    revision_flag: str,
    retrieved_at: str,
) -> dict[str, Any]:
    return {
        "dataset_id": "airline_public_report_evidence",
        "ticker": page["ticker"],
        "company": page["company"],
        "source_url": page["source_url"],
        "snapshot_date": snapshot_date,
        "report_date": report_date,
        "information_scope": information_scope,
        "institution": institution,
        "analyst": analyst,
        "fiscal_year": fiscal_year,
        "metric": metric,
        "forecast_value_native": value,
        "native_unit": unit,
        "native_currency": "RMB",
        "rating": rating,
        "revision_flag": revision_flag,
        "source_quality": "10jqka_structured_page",
        "source_note": (
            "Structured public 10jqka forecast page. EPS/net-profit rows use the visible "
            "institution report date; revenue rows have no institution-level date on the "
            "page and are explicitly page-snapshot-only, not a complete broker vintage."
        ),
        "retrieved_at": retrieved_at,
    }


def _parse_dated_eps_profit_rows(
    soup: BeautifulSoup,
    *,
    page: Mapping[str, str],
    snapshot_date: str,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    table = soup.find("table", class_=lambda value: value and "posi_table" in value)
    if table is None:
        return rows
    # Header rows have no ISO report date; filtering by the last cell keeps
    # this parser tolerant of small page-template changes.
    for tr in _table_rows(table):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) != 9:
            continue
        report_date = _text(cells[-1])
        if not _DATE_RE.fullmatch(report_date):
            continue
        institution = _text(cells[0])
        analyst = _text(cells[1])
        if not institution:
            continue
        for offset, fiscal_year in enumerate((2026, 2027, 2028), start=2):
            eps_value = _numeric_value(_text(cells[offset]))
            profit_value = _numeric_value(_text(cells[offset + 3]))
            if eps_value is not None:
                rows.append(_base_row(
                    page=page, snapshot_date=snapshot_date, report_date=report_date,
                    information_scope="institution_report_date", institution=institution,
                    analyst=analyst, fiscal_year=fiscal_year, metric="eps",
                    value=eps_value, unit="RMB/share", rating=None,
                    revision_flag=_revision_flag(cells[offset]), retrieved_at=retrieved_at,
                ))
            if profit_value is not None:
                rows.append(_base_row(
                    page=page, snapshot_date=snapshot_date, report_date=report_date,
                    information_scope="institution_report_date", institution=institution,
                    analyst=analyst, fiscal_year=fiscal_year, metric="net_profit",
                    value=profit_value, unit="RMB 100 million", rating=None,
                    revision_flag=_revision_flag(cells[offset + 3]), retrieved_at=retrieved_at,
                ))
    return rows


def _parse_revenue_page_snapshot_rows(
    soup: BeautifulSoup,
    *,
    page: Mapping[str, str],
    snapshot_date: str,
    retrieved_at: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    table = soup.find("table", class_=lambda value: value and "organData" in value)
    if table is None:
        return rows
    # The column header is in ``thead`` on this page; every body row is a
    # forecast metric row.
    for tr in _table_rows(table):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) != 7:
            continue
        metric_label = _text(cells[0])
        if "营业收入" not in metric_label or "增长率" in metric_label:
            continue
        for column, fiscal_year in zip((4, 5, 6), (2026, 2027, 2028)):
            nested = cells[column].find("table")
            if nested is None:
                continue
            for broker_row in nested.find_all("tr")[1:]:
                broker_cells = broker_row.find_all(["th", "td"], recursive=False)
                if len(broker_cells) != 4:
                    continue
                institution = _text(broker_cells[0])
                analyst = _text(broker_cells[1])
                value = _numeric_value(_text(broker_cells[2]))
                if not institution or value is None:
                    continue
                rows.append(_base_row(
                    page=page, snapshot_date=snapshot_date, report_date=None,
                    information_scope="page_snapshot_only", institution=institution,
                    analyst=analyst, fiscal_year=fiscal_year, metric="revenue",
                    value=value, unit="RMB 100 million",
                    rating=_clean_rating(_text(broker_cells[3])),
                    revision_flag="not_shown", retrieved_at=retrieved_at,
                ))
    return rows


def parse_10jqka_report_evidence(
    html: str | bytes,
    *,
    page: Mapping[str, str],
    snapshot_date: str,
    retrieved_at: str,
) -> pd.DataFrame:
    """Parse one GBK 10jqka ``worth.html`` page into normalized evidence."""
    if isinstance(html, bytes):
        html = html.decode("gbk", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    rows = _parse_dated_eps_profit_rows(
        soup, page=page, snapshot_date=snapshot_date, retrieved_at=retrieved_at
    )
    rows.extend(_parse_revenue_page_snapshot_rows(
        soup, page=page, snapshot_date=snapshot_date, retrieved_at=retrieved_at
    ))
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def build_airline_public_report_evidence(
    html_by_symbol: Mapping[str, str | bytes] | None = None,
    *,
    snapshot_date: str = "2026-08-07",
    retrieved_at: str = "2026-08-07T00:00:00+00:00",
) -> pd.DataFrame:
    """Build evidence from supplied HTML fixtures or cached page bodies."""
    frames: list[pd.DataFrame] = []
    for page in PUBLIC_REPORT_PAGES:
        html = (html_by_symbol or {}).get(page["symbol"])
        if html is None:
            continue
        parsed = parse_10jqka_report_evidence(
            html, page=page, snapshot_date=snapshot_date, retrieved_at=retrieved_at
        )
        if not parsed.empty:
            frames.append(parsed)
    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    result = pd.concat(frames, ignore_index=True)
    return result.drop_duplicates(
        subset=["ticker", "snapshot_date", "report_date", "institution", "fiscal_year", "metric", "forecast_value_native"]
    ).sort_values(["company", "metric", "fiscal_year", "institution"]).reset_index(drop=True)


def merge_public_report_evidence_history(
    prior: pd.DataFrame,
    current: pd.DataFrame,
) -> pd.DataFrame:
    """Append public snapshots while replacing only the same PIT observation key."""
    result = pd.concat([prior, current], ignore_index=True)
    if result.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    key = [
        "ticker", "snapshot_date", "report_date", "institution", "analyst",
        "fiscal_year", "metric",
    ]
    result = result.drop_duplicates(subset=key, keep="last")
    return result.sort_values(
        ["ticker", "snapshot_date", "metric", "fiscal_year", "institution", "analyst"]
    ).reset_index(drop=True)


def fetch_airline_public_report_evidence(
    *,
    snapshot_date: str | None = None,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch all six public pages and write the structured evidence layer."""
    retrieved = datetime.now(timezone.utc).isoformat()
    as_of = snapshot_date or datetime.now(timezone.utc).date().isoformat()
    http = session or requests.Session()
    html_by_symbol: dict[str, bytes] = {}
    for page in PUBLIC_REPORT_PAGES:
        response = http.get(page["source_url"], headers=DEFAULT_HEADERS, timeout=30)
        response.raise_for_status()
        html_by_symbol[page["symbol"]] = response.content
    result = build_airline_public_report_evidence(
        html_by_symbol, snapshot_date=as_of, retrieved_at=retrieved
    )
    if OUTPUT_PATH.exists():
        prior = pd.read_csv(OUTPUT_PATH)
        result = merge_public_report_evidence_history(prior, result)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
