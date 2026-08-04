import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path

import pandas as pd
import requests

from ..config import (
    DEFAULT_HEADERS,
    MPFA_QUARTERLY_DIGEST_BASE_URL,
    MPFA_QUARTERLY_DIGEST_LISTING_URL,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

# Modern (2020-present) MPFA Statistical Digest filename scheme:
# .../mpf-schemes/{month}_{year}_issue.pdf
_PDF_LINK_RE = re.compile(
    r"/en/-/media/files/information-centre/research-and-statistics/"
    r"quarterly-reports/mpf-schemes/(march|june|september|december)_(\d{4})_issue\.pdf",
    re.IGNORECASE,
)

_MONTH_TO_QUARTER = {
    "march": "Q1",
    "june": "Q2",
    "september": "Q3",
    "december": "Q4",
}

# Table II.2.2 "Number of Claims of MPF Benefits by Grounds of Withdrawal" and
# Table II.2.3 "Amount of MPF Benefits Paid by Grounds of Withdrawal" both
# have 9 numeric columns per quarter row, in this fixed order:
# Retirement, Early Retirement, Permanent Departure from HK, Terminal
# Incapacity, Terminal Illness, Death, Small Balance Account, Offsetting
# Severance Payment, Offsetting Long Service Payment. Column mapping verified
# against the MPFA press release for Q3 2023
# (https://www.mpfa.org.hk/en/info-centre/press-releases/20231129, PD claims
# = 8,700) and independently re-confirmed for Q1 2026 (~5,000 claims,
# HK$1.188bn) via MPFA's own quarterly digest coverage note.
_PERMANENT_DEPARTURE_COLUMN_INDEX = 2  # 0-based, within the 9 data columns

_QUARTER_ROW_RE = re.compile(r"^(Q[1-4])\s+(\d{4})\b")

# _discover_pdf_urls() finds every quarter since 2020-Q2 (20+ PDFs), each
# fetched sequentially at up to 60s. Under normal conditions this finishes in
# well under a minute total; when MPFA's site is degraded, per-PDF downloads
# have been observed to take 20s+ each, which without a cap turns a routine
# call into a 15-20+ minute one and once stalled CI past its job timeout.
# Stopping once the budget is spent and returning whatever quarters were
# already parsed keeps this an honest partial result, not a fabricated one.
_FETCH_TIME_BUDGET_SECONDS = 90

_TABLE_II_2_2_MARKER_RE = re.compile(r"Table\s+II\.2\.2", re.IGNORECASE)
_TABLE_II_2_3_MARKER_RE = re.compile(r"Table\s+II\.2\.3", re.IGNORECASE)
_NEXT_TABLE_MARKER_RE = re.compile(r"^\s*Table\s+II\.", re.IGNORECASE | re.MULTILINE)


def _discover_pdf_urls() -> list[tuple[str, str]]:
    """Return [(quarter_label, pdf_url), ...] sorted chronologically, discovered
    from the live MPFA listing page rather than a hardcoded date range."""
    response = requests.get(MPFA_QUARTERLY_DIGEST_LISTING_URL, headers=DEFAULT_HEADERS, timeout=30)
    response.raise_for_status()
    save_raw_snapshot("mpfa_quarterly_digest_listing", response.content, file_ext="html", source_url=MPFA_QUARTERLY_DIGEST_LISTING_URL)

    html = response.text
    found: dict[str, str] = {}
    for match in _PDF_LINK_RE.finditer(html):
        month, year = match.group(1).lower(), match.group(2)
        quarter = f"{year}-{_MONTH_TO_QUARTER[month]}"
        url = MPFA_QUARTERLY_DIGEST_BASE_URL + match.group(0)
        found[quarter] = url

    return sorted(found.items())


def _parse_number(token: str) -> float | None:
    token = token.strip()
    if token in ("§", "§§", "-", ""):
        # "§" = fewer than 50 claims, "§§" = less than HK$0.5 million: both
        # are negligible-but-nonzero disclosures, not missing data, but MPFA
        # does not publish an exact figure for them.
        return None
    cleaned = token.replace(",", "").replace(" ", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_table_section(text: str, start_marker_re: re.Pattern) -> str:
    start_match = start_marker_re.search(text)
    if not start_match:
        return ""
    remainder = text[start_match.end():]
    # Stop at the next "Table II.x" heading (covers both the II.2.3 marker
    # after II.2.2, and any following table after II.2.3, e.g. II.2.4). The
    # marker regex is anchored with MULTILINE so "^" matches the start of
    # each line in `remainder`, not just the very start of the string.
    next_match = _NEXT_TABLE_MARKER_RE.search(remainder)
    return remainder[: next_match.start()] if next_match else remainder


def _parse_quarter_rows(section_text: str) -> dict[str, list[float | None]]:
    rows: dict[str, list[float | None]] = {}
    for line in section_text.splitlines():
        stripped = line.strip()
        match = _QUARTER_ROW_RE.match(stripped)
        if not match:
            continue
        quarter_label = f"{match.group(2)}-{match.group(1)}"
        columns = re.split(r"\s{2,}", stripped)[1:]
        if len(columns) != 9:
            logger.warning("Unexpected column count (%d) for %s row: %r", len(columns), quarter_label, stripped)
            continue
        rows[quarter_label] = [_parse_number(c) for c in columns]
    return rows


def _parse_pdf(pdf_bytes: bytes, source_url: str) -> dict[str, dict[str, float | None]]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = Path(tmp_dir) / "digest.pdf"
        pdf_path.write_bytes(pdf_bytes)
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning("pdftotext failed for %s: %s", source_url, result.stderr)
            return {}
        text = result.stdout

    claims_section = _extract_table_section(text, _TABLE_II_2_2_MARKER_RE)
    amount_section = _extract_table_section(text, _TABLE_II_2_3_MARKER_RE)

    claims_rows = _parse_quarter_rows(claims_section)
    amount_rows = _parse_quarter_rows(amount_section)

    combined: dict[str, dict[str, float | None]] = {}
    for quarter, columns in claims_rows.items():
        combined.setdefault(quarter, {})["claims_count"] = columns[_PERMANENT_DEPARTURE_COLUMN_INDEX]
    for quarter, columns in amount_rows.items():
        combined.setdefault(quarter, {})["amount_mhkd"] = columns[_PERMANENT_DEPARTURE_COLUMN_INDEX]

    return combined


def fetch_mpfa_permanent_departure_claims() -> pd.DataFrame:
    """
    Fetch MPFA quarterly statistics on MPF claims for permanent departure from
    Hong Kong, parsed from the official quarterly "Statistical Digest" PDFs
    (Table II.2.2 claim counts, Table II.2.3 amounts paid, HK$ million).

    Coverage is limited to issues published under the current (2020-present)
    filename scheme discovered from the MPFA quarterly reports listing page;
    older issues use an inconsistent legacy filename scheme and are not
    parsed here, so history starts at 2020-Q2 rather than 2014.
    """
    quarter_urls = _discover_pdf_urls()

    merged: dict[str, dict[str, float | None]] = {}
    deadline = time.monotonic() + _FETCH_TIME_BUDGET_SECONDS
    for quarter, pdf_url in quarter_urls:
        if time.monotonic() >= deadline:
            logger.warning(
                "MPFA digest fetch exceeded its %ss time budget with %d/%d quarters remaining; "
                "returning the quarters already fetched instead of blocking further.",
                _FETCH_TIME_BUDGET_SECONDS,
                len(quarter_urls) - len(merged),
                len(quarter_urls),
            )
            break
        try:
            response = requests.get(pdf_url, headers=DEFAULT_HEADERS, timeout=60)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Failed to download MPFA digest for %s (%s): %s", quarter, pdf_url, exc)
            continue

        save_raw_snapshot(f"mpfa_digest_{quarter}", response.content, file_ext="pdf", source_url=pdf_url)

        try:
            parsed = _parse_pdf(response.content, pdf_url)
        except Exception as exc:
            logger.warning("Failed to parse MPFA digest for %s (%s): %s", quarter, pdf_url, exc)
            continue

        for parsed_quarter, values in parsed.items():
            merged.setdefault(parsed_quarter, {}).update(values)

    records = [
        {
            "quarter": quarter,
            "claims_count": values.get("claims_count"),
            "amount_mhkd": values.get("amount_mhkd"),
        }
        for quarter, values in sorted(merged.items())
        if values.get("claims_count") is not None
    ]

    df = pd.DataFrame(records, columns=["quarter", "claims_count", "amount_mhkd"])
    df["source_agency"] = "Mandatory Provident Fund Schemes Authority (MPFA)"
    df.attrs.update(source_url=MPFA_QUARTERLY_DIGEST_LISTING_URL)
    return df
