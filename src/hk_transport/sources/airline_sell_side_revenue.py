"""Extract dated revenue forecasts from publicly linked sell-side PDFs."""

from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber
import requests

from ..config import AIRLINE_TICKER_ALIASES, DEFAULT_HEADERS, NORMALIZED_DIR, RAW_DIR


REPORT_INPUT_PATH = NORMALIZED_DIR / "airline_sell_side_reports_akshare_snapshot.csv"
PDF_CACHE_DIR = RAW_DIR / "airline_sell_side_pdfs"
PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

FORECAST_COLUMNS = [
    "dataset_id", "ticker", "company", "report_date", "institution", "report_title",
    "fiscal_year", "revenue_forecast_native_mn", "native_currency", "report_url",
    "source_quality", "source_page", "extraction_method", "source_note", "retrieved_at",
]
REVISION_COLUMNS = [
    "dataset_id", "ticker", "company", "institution", "fiscal_year", "report_date",
    "prior_report_date", "revenue_forecast_native_mn", "prior_revenue_forecast_native_mn",
    "revenue_change_native_mn", "revenue_change_pct", "report_title", "report_url",
    "source_quality", "source_note", "retrieved_at",
]


def _numeric_tokens(text: str) -> list[float]:
    return [float(token.replace(",", "")) for token in re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", text)]


def extract_revenue_forecast_from_text(text: str) -> list[dict[str, Any]]:
    """Extract 2026E+ revenue values from a normalized PDF text string.

    The parser requires a nearby year header and a ``营业收入(百万元)`` row;
    it returns no values when the table is ambiguous rather than guessing.
    """
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    rows: list[dict[str, Any]] = []
    seen_years: set[int] = set()
    for index, line in enumerate(lines):
        if "营业收入" not in line or "增长率" in line or "百万元" not in line:
            continue
        metric_match = re.search(r"营业收入\s*[（(]\s*百万元\s*[）)]", line)
        if not metric_match:
            continue
        header = ""
        for prior in reversed(lines[max(0, index - 4):index]):
            if re.search(r"20\d{2}E?", prior) and "2026" in prior:
                header = prior
                break
        if not header:
            # Some PDFs put the header and metric on one extracted line.
            header = line[:metric_match.start()]
        year_tokens = re.findall(r"(20\d{2})(?:E)?", header)
        forecast_years = [int(year) for year in year_tokens if int(year) >= 2026]
        if not forecast_years:
            continue
        values = _numeric_tokens(line[metric_match.end():])
        if len(values) < len(year_tokens):
            continue
        # The numeric columns follow the year columns in the same order.
        values = values[: len(year_tokens)]
        for year in forecast_years:
            if year in seen_years:
                continue
            year_position = year_tokens.index(str(year))
            if year_position >= len(values):
                continue
            seen_years.add(year)
            rows.append({"fiscal_year": year, "revenue_forecast_native_mn": values[year_position]})
        if rows:
            break
    return rows


def _cached_pdf(url: str, session: requests.Session) -> bytes | None:
    cache_path = PDF_CACHE_DIR / f"{hashlib.sha1(url.encode()).hexdigest()}.pdf"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path.read_bytes()
    try:
        response = session.get(url, headers=DEFAULT_HEADERS, timeout=30)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            return None
        cache_path.write_bytes(response.content)
        return response.content
    except requests.RequestException:
        return None


def _extract_pdf_revenue(content: bytes) -> tuple[list[dict[str, Any]], int | None]:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            rows = extract_revenue_forecast_from_text(page.extract_text() or "")
            if rows:
                return rows, page_number
    return [], None


def normalize_sell_side_revenue_forecasts(
    reports: pd.DataFrame,
    *,
    min_report_date: str = "2025-01-01",
    session: requests.Session | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Download and normalize report-linked revenue forecasts."""
    required = {"ticker", "company", "report_date", "institution", "report_title", "report_url"}
    missing = required.difference(reports.columns)
    if missing:
        raise ValueError(f"sell-side report feed is missing columns: {sorted(missing)}")
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    source = reports.copy()
    source["ticker"] = source["ticker"].replace(AIRLINE_TICKER_ALIASES)
    source["report_date"] = pd.to_datetime(source["report_date"], errors="coerce")
    source = source.loc[source["report_date"].ge(pd.Timestamp(min_report_date))].dropna(subset=["report_url"])
    source = source.drop_duplicates(subset=["report_url"])
    http = session or requests.Session()
    rows: list[dict[str, Any]] = []
    for _, report in source.sort_values("report_date").iterrows():
        content = _cached_pdf(str(report["report_url"]), http)
        if content is None:
            continue
        try:
            extracted, page_number = _extract_pdf_revenue(content)
        except Exception:
            continue
        for item in extracted:
            rows.append({
                "dataset_id": "airline_sell_side_revenue_forecasts",
                "ticker": report["ticker"],
                "company": report["company"],
                "report_date": report["report_date"].strftime("%Y-%m-%d"),
                "institution": report["institution"],
                "report_title": report["report_title"],
                "fiscal_year": item["fiscal_year"],
                "revenue_forecast_native_mn": item["revenue_forecast_native_mn"],
                "native_currency": "RMB",
                "report_url": report["report_url"],
                "source_quality": "sell_side_pdf_extracted",
                "source_page": page_number,
                "extraction_method": "pdf_text_revenue_table",
                "source_note": (
                    "Revenue forecast extracted from the report-linked public sell-side PDF. "
                    "Report date is the Eastmoney discovery-feed publication date; values are "
                    "not an institutional consensus aggregate."
                ),
                "retrieved_at": retrieved,
            })
    result = pd.DataFrame(rows, columns=FORECAST_COLUMNS)
    if result.empty:
        return result
    return result.drop_duplicates(
        subset=["ticker", "institution", "report_date", "fiscal_year", "report_url"]
    ).sort_values(["ticker", "institution", "fiscal_year", "report_date"]).reset_index(drop=True)


def build_sell_side_revenue_revisions(
    forecasts: pd.DataFrame,
    *,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Compare same-institution revenue forecasts across dated reports."""
    if forecasts.empty:
        return pd.DataFrame(columns=REVISION_COLUMNS)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    source = forecasts.copy()
    source["report_date"] = pd.to_datetime(source["report_date"], errors="coerce")
    source = source.sort_values(["ticker", "institution", "fiscal_year", "report_date"])
    rows: list[dict[str, Any]] = []
    previous: dict[tuple[str, str, int], tuple[str, float]] = {}
    for _, report in source.iterrows():
        key = (str(report["ticker"]), str(report["institution"]), int(report["fiscal_year"]))
        report_date = report["report_date"].strftime("%Y-%m-%d")
        prior_date, prior_value = previous.get(key, (None, None))
        value = float(report["revenue_forecast_native_mn"])
        change = value - prior_value if prior_value is not None else None
        change_pct = 100.0 * change / abs(prior_value) if prior_value not in (None, 0) else None
        rows.append({
            "dataset_id": "airline_sell_side_revenue_revisions",
            "ticker": report["ticker"],
            "company": report["company"],
            "institution": report["institution"],
            "fiscal_year": int(report["fiscal_year"]),
            "report_date": report_date,
            "prior_report_date": prior_date,
            "revenue_forecast_native_mn": value,
            "prior_revenue_forecast_native_mn": prior_value,
            "revenue_change_native_mn": change,
            "revenue_change_pct": change_pct,
            "report_title": report["report_title"],
            "report_url": report["report_url"],
            "source_quality": "sell_side_pdf_extracted",
            "source_note": "Same-institution/same-fiscal-year revenue change from public report-linked PDFs; not a complete consensus vintage history.",
            "retrieved_at": retrieved,
        })
        previous[key] = (report_date, value)
    return pd.DataFrame(rows, columns=REVISION_COLUMNS)


def fetch_sell_side_revenue_layers(*, min_report_date: str = "2025-01-01") -> dict[str, pd.DataFrame]:
    reports = pd.read_csv(REPORT_INPUT_PATH)
    retrieved = datetime.now(timezone.utc).isoformat()
    forecasts = normalize_sell_side_revenue_forecasts(
        reports, min_report_date=min_report_date, retrieved_at=retrieved
    )
    revisions = build_sell_side_revenue_revisions(forecasts, retrieved_at=retrieved)
    forecasts.to_csv(NORMALIZED_DIR / "airline_sell_side_revenue_forecasts.csv", index=False)
    revisions.to_csv(NORMALIZED_DIR / "airline_sell_side_revenue_revisions.csv", index=False)
    return {"forecasts": forecasts, "revisions": revisions}


def source_paths() -> dict[str, Path]:
    return {
        "forecasts": NORMALIZED_DIR / "airline_sell_side_revenue_forecasts.csv",
        "revisions": NORMALIZED_DIR / "airline_sell_side_revenue_revisions.csv",
    }
