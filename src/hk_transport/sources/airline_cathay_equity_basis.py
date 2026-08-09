"""Point-in-time Cathay Pacific equity and asset basis for P/B diagnostics.

The sibling ``financial-data`` repository contains provider-side Cathay
equity observations, but those observations do not carry the issuer's
announcement date.  This module keeps a small official-report layer for the
four balance-sheet anchors needed to backfill a dated P/B diagnostic without
using information before it was public.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber
import requests

from ..config import DEFAULT_HEADERS, NORMALIZED_DIR, RAW_DIR


@dataclass(frozen=True)
class CathayEquityReport:
    report_id: str
    statement_period: str
    period_end: str
    announced_at: str
    source_url: str
    cache_path: Path
    pdf_page: int
    anchors: tuple[str, ...]
    equity_attributable_hkd_mn: float
    total_equity_hkd_mn: float
    total_assets_hkd_mn: float
    total_assets_calculation: str


CATHAY_REPORTS: tuple[CathayEquityReport, ...] = (
    CathayEquityReport(
        report_id="0293_2024_fy_equity",
        statement_period="FY2024",
        period_end="2024-12-31",
        announced_at="2025-03-12",
        source_url=(
            "https://www.cathaypacific.com/content/dam/cx/about-us/"
            "investor-relations/interim-annual-reports/en/2024_cx_annual_report_en.pdf"
        ),
        cache_path=RAW_DIR / "cathay_2024_annual_report.pdf",
        pdf_page=79,
        anchors=(
            "CONSOLIDATED STATEMENT OF FINANCIAL POSITION",
            "Funds attributable to the shareholders of the Cathay Group",
            "Total equity",
        ),
        equity_attributable_hkd_mn=52_500.0,
        total_equity_hkd_mn=52_507.0,
        total_assets_hkd_mn=171_244.0,
        total_assets_calculation="derived_from_reported_non_current_and_current_assets",
    ),
    CathayEquityReport(
        report_id="0293_2025_h1_equity",
        statement_period="1H2025",
        period_end="2025-06-30",
        announced_at="2025-08-06",
        source_url=(
            "https://www.cathaypacific.com/content/dam/cx/about-us/"
            "investor-relations/announcements/en/2025_cx_interim_results_en.pdf"
        ),
        cache_path=RAW_DIR / "cathay_2025_interim_results.pdf",
        pdf_page=16,
        anchors=(
            "Consolidated Statement of Financial Position",
            "Funds attributable to the shareholders of the Cathay Group",
            "Total equity",
        ),
        equity_attributable_hkd_mn=51_654.0,
        total_equity_hkd_mn=51_661.0,
        total_assets_hkd_mn=170_302.0,
        total_assets_calculation="derived_from_reported_non_current_and_current_assets",
    ),
    CathayEquityReport(
        report_id="0293_2025_fy_equity",
        statement_period="FY2025",
        period_end="2025-12-31",
        announced_at="2026-03-11",
        source_url=(
            "https://www.cathaypacific.com/content/dam/cx/about-us/"
            "investor-relations/interim-annual-reports/en/2025_cx_annual_report_en.pdf"
        ),
        cache_path=RAW_DIR / "cathay_2025_annual_report.pdf",
        pdf_page=87,
        anchors=(
            "CONSOLIDATED STATEMENT OF FINANCIAL POSITION",
            "Funds attributable to the shareholders of the Cathay Group",
            "Total equity",
        ),
        equity_attributable_hkd_mn=60_110.0,
        total_equity_hkd_mn=60_117.0,
        total_assets_hkd_mn=177_051.0,
        total_assets_calculation="derived_from_reported_non_current_and_current_assets",
    ),
    CathayEquityReport(
        report_id="0293_2026_h1_equity",
        statement_period="1H2026",
        period_end="2026-06-30",
        announced_at="2026-08-05",
        source_url=(
            "https://www.cathaypacific.com/content/dam/cx/about-us/"
            "investor-relations/announcements/en/2026_cx_interim_results_en.pdf"
        ),
        cache_path=RAW_DIR / "cathay_2026_interim_results.pdf",
        pdf_page=16,
        anchors=(
            "Consolidated Statement of Financial Position",
            "Funds attributable to the shareholders of the Cathay Group",
            "Total equity",
        ),
        equity_attributable_hkd_mn=58_018.0,
        total_equity_hkd_mn=58_026.0,
        total_assets_hkd_mn=182_663.0,
        total_assets_calculation="derived_from_reported_non_current_and_current_assets",
    ),
)


OUTPUT_PATH = NORMALIZED_DIR / "airline_cathay_equity_basis.csv"

OUTPUT_COLUMNS = [
    "dataset_id",
    "report_id",
    "ticker",
    "company",
    "statement_period",
    "period_end",
    "announced_at",
    "metric",
    "value_native",
    "native_unit",
    "native_currency",
    "value_usd",
    "usd_unit",
    "fx_pair",
    "fx_observation_date",
    "fx_value",
    "calculation_method",
    "source_quality",
    "source_url",
    "source_page",
    "source_note",
    "retrieved_at",
]


def _fx_asof(period_end: str) -> tuple[str | None, float | None]:
    path = NORMALIZED_DIR / "airline_fx_rates.parquet"
    if not path.exists():
        return None, None
    frame = pd.read_parquet(path)
    required = {"pair", "observation_date", "value"}
    if not required.issubset(frame.columns):
        return None, None
    frame = frame.loc[frame["pair"].eq("USD_HKD")].copy()
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.loc[
        frame["observation_date"].le(pd.Timestamp(period_end))
    ].dropna(subset=["observation_date", "value"])
    if frame.empty:
        return None, None
    row = frame.sort_values("observation_date").iloc[-1]
    return row["observation_date"].strftime("%Y-%m-%d"), float(row["value"])


def _download_report(spec: CathayEquityReport, session: requests.Session | None = None) -> bytes:
    if spec.cache_path.exists() and spec.cache_path.stat().st_size > 0:
        return spec.cache_path.read_bytes()
    http = session or requests.Session()
    response = http.get(spec.source_url, headers=DEFAULT_HEADERS, timeout=60)
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise ValueError(f"Cathay report URL did not return a PDF: {spec.source_url}")
    spec.cache_path.parent.mkdir(parents=True, exist_ok=True)
    spec.cache_path.write_bytes(response.content)
    return response.content


def _assert_report_anchor(content: bytes, spec: CathayEquityReport) -> None:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        if spec.pdf_page > len(pdf.pages):
            raise ValueError(f"Cathay report is shorter than expected: {spec.report_id}")
        text = pdf.pages[spec.pdf_page - 1].extract_text() or ""
    if not all(anchor in text for anchor in spec.anchors):
        raise ValueError(f"Cathay equity-basis anchor missing on PDF page {spec.pdf_page}: {spec.report_id}")


def build_cathay_equity_basis(
    *,
    fx_rates: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build official equity/asset anchors with USD views and PIT dates."""

    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for spec in CATHAY_REPORTS:
        if fx_rates is None:
            fx_date, fx_value = _fx_asof(spec.period_end)
        else:
            rates = fx_rates.copy()
            rates = rates.loc[rates["pair"].eq("USD_HKD")].copy()
            rates["observation_date"] = pd.to_datetime(rates["observation_date"], errors="coerce")
            rates["value"] = pd.to_numeric(rates["value"], errors="coerce")
            rates = rates.loc[rates["observation_date"].le(pd.Timestamp(spec.period_end))].dropna(
                subset=["observation_date", "value"]
            )
            if rates.empty:
                fx_date, fx_value = None, None
            else:
                fx_row = rates.sort_values("observation_date").iloc[-1]
                fx_date, fx_value = fx_row["observation_date"].strftime("%Y-%m-%d"), float(fx_row["value"])

        raw_rows = (
            ("equity_attributable", spec.equity_attributable_hkd_mn, "issuer_reported"),
            ("total_equity", spec.total_equity_hkd_mn, "issuer_reported"),
            ("total_assets", spec.total_assets_hkd_mn, spec.total_assets_calculation),
        )
        for metric, value, calculation_method in raw_rows:
            rows.append(
                {
                    "dataset_id": "airline_cathay_equity_basis",
                    "report_id": spec.report_id,
                    "ticker": "0293.HK",
                    "company": "Cathay Pacific",
                    "statement_period": spec.statement_period,
                    "period_end": spec.period_end,
                    "announced_at": spec.announced_at,
                    "metric": metric,
                    "value_native": value,
                    "native_unit": "HKD million",
                    "native_currency": "HKD",
                    "value_usd": value / fx_value if fx_value else None,
                    "usd_unit": "USD million" if fx_value else None,
                    "fx_pair": "USD_HKD" if fx_value else None,
                    "fx_observation_date": fx_date if fx_value else None,
                    "fx_value": fx_value if fx_value else None,
                    "calculation_method": calculation_method,
                    "source_quality": "primary_issuer",
                    "source_url": spec.source_url,
                    "source_page": spec.pdf_page,
                    "source_note": (
                        "Cathay consolidated statement of financial position; "
                        f"official {spec.statement_period} report announced {spec.announced_at}. "
                        "Equity basis is funds attributable to shareholders; total equity is a check field."
                    ),
                    "retrieved_at": retrieved,
                }
            )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_cathay_equity_basis() -> pd.DataFrame:
    """Fetch/assert the four official reports and write the normalized basis."""

    session = requests.Session()
    for spec in CATHAY_REPORTS:
        _assert_report_anchor(_download_report(spec, session=session), spec)
    result = build_cathay_equity_basis()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
