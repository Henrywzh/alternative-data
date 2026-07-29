"""Historical Buildings Department monthly-digest aggregates.

This module intentionally parses the stable Section 1 summary tables in the
official monthly-digest PDFs.  It is a month/stage aggregate backfill, not a
project-level PDF parser or a replacement for the current Md52--Md56 XLS
snapshot source.
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests

from ..config import (
    BD_HISTORY_FIRST_YEAR,
    BD_MONTHLY_DIGEST_ARCHIVE_BASE,
    BD_MONTHLY_DIGESTS_URL,
    DEFAULT_HEADERS,
)
from ..storage import save_raw_snapshot


logger = logging.getLogger(__name__)

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONTH_NUMBER = {month: index for index, month in enumerate(_MONTHS, start=1)}
_MONTH_PATTERN = r"J\s*a\s*n(?:uary)?|F\s*e\s*b(?:ruary)?|M\s*a\s*r(?:ch)?|A\s*p\s*r(?:il)?|M\s*a\s*y|J\s*u\s*n(?:e)?|J\s*u\s*l(?:y)?|A\s*u\s*g(?:ust)?|S\s*e\s*p(?:tember)?|O\s*c\s*t(?:ober)?|N\s*o\s*v(?:ember)?|D\s*e\s*c(?:ember)?"
_STAGE_NAMES = {
    "1.2": "Demolition Consents",
    "1.4": "Plans Approved",
    "1.5": "Consent to Commence",
    "1.6": "Notice of Commencement Received",
    "1.3": "Occupation Permits (OP) Issued",
}
_SUMMARY_TABLE_TITLES = {
    "1.2": r"TABLE\s+1\.2\s+CONSENT\s+TO\s+COMMENCE\s+WORKS?\s+ISSUED\s+BY\s+THE\s+BUILDING\s+AUTHORITY",
    "1.3": r"TABLE\s+1\.3\s+OCCUPATION\s+PERMITS\s+ISSUED\s+BY\s+THE\s+BUILDING\s+AUTHORITY",
    "1.4": r"TABLE\s+1\.4\s+APPROVALS\s+OF\s+NEW\s+AND\s+MAJOR\s+REVISION\s+BUILDING\s+PLANS",
    "1.5": r"TABLE\s+1\.5\s+CONSENT\s+TO\s+COMMENCE\s+GENERAL\s+BUILDING\s+AND\s+SUPERSTRUCTURE\s+WORKS?",
    "1.6": r"TABLE\s+1\.6\s+NOTIFICATION\s+OF\s+COMMENCEMENT\s+OF\s+GENERAL\s+BUILDING",
    "1.7": r"TABLE\s+1\.7\s+COMPLETION\s+OF\s+NEW\s+BUILDINGS",
}
_HISTORY_COLUMNS = [
    "date",
    "observation_month",
    "permit_stage",
    "region",
    "property_category",
    "total_projects_count",
    "total_domestic_units",
    "total_domestic_gfa_sqm",
    "total_non_domestic_gfa_sqm",
    "total_domestic_ufa_sqm",
    "total_non_domestic_ufa_sqm",
    "revision_status",
    "parser_confidence",
    "source_agency",
    "source_url",
    "archive_year",
    "raw_snapshot",
    "parser_version",
]
_NUMBER_RE = re.compile(r"(?<![A-Za-z])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![A-Za-z])")


def _empty_history() -> pd.DataFrame:
    return pd.DataFrame(columns=_HISTORY_COLUMNS)


def discover_bd_digest_archives(index_html: str) -> dict[int, str]:
    """Return annual archive URLs linked from the official BD digest index."""
    years = {int(year) for year in re.findall(r"Md(20\d{2})e\.zip", index_html, flags=re.IGNORECASE)}
    return {
        year: f"{BD_MONTHLY_DIGEST_ARCHIVE_BASE}/Md{year}e.zip"
        for year in sorted(years)
    }


def discover_bd_digest_pdf_urls(index_html: str) -> dict[int, str]:
    """Select the latest direct monthly PDF per year from the official index."""
    candidates: dict[int, tuple[int, str]] = {}
    for href in re.findall(r'''href=["']([^"']*Md(20\d{2})(\d{2})e\.pdf[^"']*)["']''', index_html, flags=re.IGNORECASE):
        path, year_s, month_s = href
        year, month = int(year_s), int(month_s)
        if not 1 <= month <= 12:
            continue
        url = urljoin(BD_MONTHLY_DIGESTS_URL, path)
        if year not in candidates or month > candidates[year][0]:
            candidates[year] = (month, url)
    return {year: value[1] for year, value in candidates.items()}


def list_archive_pdf_members(zip_bytes: bytes, archive_year: int) -> list[str]:
    """Return one official PDF per archive month, accepting revised members.

    Some official archives replace the original PDF with a member such as
    ``Md201404e_revised.pdf``.  That is a BD revision, not a corrupted
    archive, so choose it for that month while continuing to reject a missing
    month altogether.
    """
    expected = [f"Md{archive_year}{month:02d}e.pdf" for month in range(1, 13)]
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        pdf_members = archive.namelist()
    selected: list[str] = []
    missing: list[str] = []
    for canonical in expected:
        revised = canonical.removesuffix(".pdf") + "_revised.pdf"
        if canonical in pdf_members:
            selected.append(canonical)
        elif revised in pdf_members:
            selected.append(revised)
        else:
            missing.append(canonical)
    if missing:
        raise ValueError(
            f"BD {archive_year} archive is missing monthly digest PDFs; "
            f"missing={missing!r}, found={[name for name in pdf_members if name.lower().endswith('.pdf')]!r}"
        )
    return selected


def _number_values(text: str) -> list[float]:
    return [float(value.replace(",", "")) for value in _NUMBER_RE.findall(text)]


def _table_text(full_text: str, table_id: str) -> str:
    title = _SUMMARY_TABLE_TITLES[table_id]
    match = re.search(title, full_text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    next_table = re.search(r"TABLE\s+1\.[1-7]\s+", full_text[match.end():], flags=re.IGNORECASE)
    end = match.end() + next_table.start() if next_table else len(full_text)
    return full_text[match.start():end]


def _month_rows(table_text: str, year: int) -> dict[str, list[list[float]]]:
    """Read text-layout rows for one year from a Section 1 table."""
    rows: dict[str, list[list[float]]] = defaultdict(list)
    current_year = False
    current_month: str | None = None
    for raw_line in table_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        first = re.match(rf"^{year}\s*:?\s*\*?\s*({_MONTH_PATTERN})\s+(.*)$", line, flags=re.IGNORECASE)
        continuation = re.match(rf"^\*?\s*({_MONTH_PATTERN})\s+(.*)$", line, flags=re.IGNORECASE)
        if first:
            current_year = True
            month, rest = first.groups()
        elif current_year and continuation:
            month, rest = continuation.groups()
        elif current_year and current_month and re.match(r"^(?:First Submission|Major Revision)\b", line, flags=re.IGNORECASE):
            month, rest = current_month, line
        else:
            if current_year and re.match(r"^\d{4}\s*:", line):
                break
            continue
        values = _number_values(rest)
        if values:
            month = re.sub(r"\s+", "", month)[:3].title()
            rows[month].append(values)
            current_month = month
    return rows


def _value(values: list[float], index: int) -> float | None:
    return values[index] if len(values) > index else None


def _sum_at(rows: list[list[float]], index: int) -> float | None:
    values = [_value(row, index) for row in rows]
    available = [value for value in values if value is not None]
    return float(sum(available)) if available else None


def _approval_total(row: list[float]) -> float | None:
    """Read Table 1.4's final approval-total column defensively.

    A small number of archived PDFs collapse the two preceding approval
    columns (for example ``4 4`` becomes ``44`` in extracted text).  The
    published total remains the final numeric value, but accept that compact
    form only when the merged digits add back to the stated total.
    """
    if len(row) >= 6:
        return _value(row, 5)
    if len(row) != 5 or not all(value.is_integer() for value in row[3:]):
        return None
    merged = str(int(row[3]))
    total = int(row[4])
    if len(merged) >= 2 and any(int(merged[:split]) + int(merged[split:]) == total for split in range(1, len(merged))):
        return float(total)
    return None


def _record(month: str, year: int, stage: str, source_url: str, archive_year: int, **metrics: Any) -> dict[str, Any]:
    observation_month = f"{year}-{_MONTH_NUMBER[month]:02d}-01"
    return {
        "date": observation_month,
        "observation_month": observation_month,
        "permit_stage": stage,
        "region": "All",
        "property_category": "All",
        "total_projects_count": None,
        "total_domestic_units": None,
        "total_domestic_gfa_sqm": None,
        "total_non_domestic_gfa_sqm": None,
        "total_domestic_ufa_sqm": None,
        "total_non_domestic_ufa_sqm": None,
        "revision_status": "as_published",
        "parser_confidence": "HIGH",
        "source_agency": "Hong Kong Buildings Department",
        "source_url": source_url,
        "archive_year": archive_year,
        "raw_snapshot": None,
        "parser_version": "bd-summary-history-v1",
        **metrics,
    }


def parse_bd_history_text(text: str, year: int, source_url: str, archive_year: int) -> pd.DataFrame:
    """Parse one digest's Section 1 monthly summary tables for ``year``.

    Md52 is proxied by Table 1.2's demolition-consent count, Md53 by Table
    1.4's approval count, Md54 by Table 1.2/1.5, Md55 by Table 1.6, and Md56
    by Tables 1.3/1.7.  This is the official monthly aggregate, not a sum of
    fragile project rows from the historical detailed tables.
    """
    tables = {table_id: _month_rows(_table_text(text, table_id), year) for table_id in ("1.2", "1.3", "1.4", "1.5", "1.6", "1.7")}
    records: list[dict[str, Any]] = []
    for month in _MONTHS:
        consent_rows = tables["1.2"].get(month, [])
        approval_rows = tables["1.4"].get(month, [])
        commence_rows = tables["1.5"].get(month, [])
        notice_rows = tables["1.6"].get(month, [])
        occupation_rows = tables["1.3"].get(month, [])
        completion_rows = tables["1.7"].get(month, [])

        if consent_rows and _value(consent_rows[0], 0) is not None:
            records.append(_record(month, year, _STAGE_NAMES["1.2"], source_url, archive_year, total_projects_count=_value(consent_rows[0], 0)))
        approval_total = _approval_total(approval_rows[0]) if approval_rows else None
        if approval_total is not None:
            records.append(_record(month, year, _STAGE_NAMES["1.4"], source_url, archive_year, total_projects_count=approval_total))
        if commence_rows:
            records.append(
                _record(
                    month,
                    year,
                    _STAGE_NAMES["1.5"],
                    source_url,
                    archive_year,
                    total_projects_count=_value(consent_rows[0], 3) if consent_rows else None,
                    total_domestic_units=_sum_at(commence_rows, 6),
                    total_domestic_gfa_sqm=_sum_at(commence_rows, 0),
                    total_non_domestic_gfa_sqm=_sum_at(commence_rows, 1),
                    total_domestic_ufa_sqm=_sum_at(commence_rows, 3),
                    total_non_domestic_ufa_sqm=_sum_at(commence_rows, 4),
                )
            )
        if notice_rows:
            records.append(
                _record(
                    month,
                    year,
                    _STAGE_NAMES["1.6"],
                    source_url,
                    archive_year,
                    total_domestic_units=_value(notice_rows[0], 6),
                    total_domestic_gfa_sqm=_value(notice_rows[0], 0),
                    total_non_domestic_gfa_sqm=_value(notice_rows[0], 1),
                    total_domestic_ufa_sqm=_value(notice_rows[0], 3),
                    total_non_domestic_ufa_sqm=_value(notice_rows[0], 4),
                )
            )
        if occupation_rows:
            completion = completion_rows[0] if completion_rows else []
            records.append(
                _record(
                    month,
                    year,
                    _STAGE_NAMES["1.3"],
                    source_url,
                    archive_year,
                    total_projects_count=_value(occupation_rows[0], 3),
                    total_domestic_units=_value(occupation_rows[0], 4),
                    total_domestic_gfa_sqm=_value(completion, 0),
                    total_non_domestic_gfa_sqm=_value(completion, 1),
                    total_domestic_ufa_sqm=_value(completion, 3),
                    total_non_domestic_ufa_sqm=_value(completion, 4),
                )
            )
    if not records:
        return _empty_history()
    return pd.DataFrame(records, columns=_HISTORY_COLUMNS)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n\f\n".join(page.extract_text(layout=True) or "" for page in pdf.pages)


def parse_bd_history_digest(pdf_bytes: bytes, year: int, source_url: str, archive_year: int) -> pd.DataFrame:
    return parse_bd_history_text(extract_pdf_text(pdf_bytes), year, source_url, archive_year)


def _archive_december_pdf(archive_bytes: bytes, year: int) -> tuple[str, bytes]:
    member = next(name for name in list_archive_pdf_members(archive_bytes, year) if name.startswith(f"Md{year}12e"))
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        return member, archive.read(member)


def fetch_bd_supply_pipeline_history(
    start_year: int = BD_HISTORY_FIRST_YEAR,
    end_year: int | None = None,
) -> pd.DataFrame:
    """Backfill annual BD digest snapshots into a monthly Md52--Md56 series.

    It intentionally downloads one December digest per archived year, because
    that digest contains the complete Jan--Dec Section 1 table for that year.
    For years still exposed as direct PDFs on the index, it uses the latest
    available month and consequently reports year-to-date coverage.
    """
    end_year = end_year or datetime.now(timezone.utc).year
    if start_year < BD_HISTORY_FIRST_YEAR or end_year < start_year:
        raise ValueError(f"supported BD history range starts at {BD_HISTORY_FIRST_YEAR}: {start_year=} {end_year=}")
    index_response = requests.get(BD_MONTHLY_DIGESTS_URL, headers=DEFAULT_HEADERS, timeout=30)
    index_response.raise_for_status()
    archives = discover_bd_digest_archives(index_response.text)
    direct_pdfs = discover_bd_digest_pdf_urls(index_response.text)
    frames: list[pd.DataFrame] = []
    raw_paths: list[str] = []
    source_urls: list[str] = []
    errors: list[str] = []
    for year in range(start_year, end_year + 1):
        try:
            logger.info("Backfilling Buildings Department monthly digest for %s", year)
            if year in archives:
                archive_url = archives[year]
                archive_response = requests.get(archive_url, headers=DEFAULT_HEADERS, timeout=60)
                archive_response.raise_for_status()
                member, pdf_bytes = _archive_december_pdf(archive_response.content, year)
                source_url = f"{archive_url}#{member}"
            elif year in direct_pdfs:
                source_url = direct_pdfs[year]
                pdf_response = requests.get(source_url, headers=DEFAULT_HEADERS, timeout=60)
                pdf_response.raise_for_status()
                pdf_bytes = pdf_response.content
            else:
                errors.append(f"{year}: no official archive or direct PDF link found")
                continue
            raw_path = save_raw_snapshot(
                "bd_monthly_digest_history",
                pdf_bytes,
                file_ext="pdf",
                source_url=source_url,
            )
            parsed = parse_bd_history_digest(pdf_bytes, year, source_url, year)
            if parsed.empty:
                errors.append(f"{year}: no parseable Section 1 Md52--Md56 aggregate rows")
                continue
            parsed["raw_snapshot"] = str(raw_path)
            frames.append(parsed)
            raw_paths.append(str(raw_path))
            source_urls.append(source_url)
        except Exception as exc:  # noqa: BLE001 -- retain year-level backfill coverage
            errors.append(f"{year}: {exc}")
    result = pd.concat(frames, ignore_index=True) if frames else _empty_history()
    if not result.empty:
        result = result.drop_duplicates(
            subset=["observation_month", "permit_stage", "region", "property_category", "revision_status"],
            keep="last",
        ).sort_values(["observation_month", "permit_stage"]).reset_index(drop=True)
    result.attrs.update(
        raw_snapshot=json.dumps(raw_paths),
        source_url=json.dumps(source_urls),
        backfill_errors=json.dumps(errors),
    )
    return result
