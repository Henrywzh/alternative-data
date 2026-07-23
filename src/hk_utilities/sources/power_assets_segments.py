"""Power Assets Holdings (0006.HK) Geographic Segment Reporting.

Power Assets is a pure holding company with no direct operational KPIs of
its own (its HK electricity business, HK Electric Investments, is a
separately listed equity-accounted associate). However its interim/annual
report discloses a real "Segment reporting" note breaking out revenue,
segment profit, and share of joint-venture/associate results by geography:
Investment in HKEI, United Kingdom, Australia, Others.

This is a semi-annual disclosure (H1 interim report + FY annual report),
not daily/monthly, so freshness handling in pipeline.py uses a much wider
max_age_days than the other HK Utilities sources.

No figures are hardcoded. The interim report PDF is fetched and the
"Segment reporting" note is located and parsed directly from the real PDF
text; periods that cannot be fetched or parsed are simply absent from the
result.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date

import pandas as pd
import pdfplumber
import requests

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "period",
    "date",
    "revenue_hkei_hkdm",
    "revenue_uk_hkdm",
    "revenue_australia_hkdm",
    "revenue_others_hkdm",
    "revenue_total_hkdm",
    "segment_profit_hkei_hkdm",
    "segment_profit_uk_hkdm",
    "segment_profit_australia_hkdm",
    "segment_profit_others_hkdm",
    "segment_profit_total_hkdm",
    "jv_associate_results_hkei_hkdm",
    "jv_associate_results_uk_hkdm",
    "jv_associate_results_australia_hkdm",
    "jv_associate_results_others_hkdm",
    "jv_associate_results_total_hkdm",
]

# Power Assets' interim report PDF is split into numbered "e<NN>" chapter
# files under a per-year folder. The "Segment reporting" note has been
# verified at chapter 13 for the 2025 Interim Report; nearby chapter
# numbers are also tried since the note's position can shift by a page or
# two between reporting periods as other notes are added/removed.
_INTERIM_URL_TEMPLATE = (
    "https://www.powerassets.com/documents/en/InvestorRelations/Documents/"
    "Interim%20Report%20{year}/PAHIR{year}_e{chapter:02d}.pdf"
)
_CANDIDATE_CHAPTERS = (13, 12, 14, 11, 15)

_YEAR_HEADER_RE = re.compile(r"^(\d{4})$", re.MULTILINE)
_NUM = r"(–|\(?[\d,]+\)?)"
_ROW = r"\s+".join([_NUM] * 7)

_ROW_PATTERNS = {
    "revenue": re.compile(r"Reportable segment revenue\s+" + _ROW),
    "segment_profit": re.compile(r"Reportable segment profit\s*/\s*\(loss\)\s+" + _ROW),
    "jv_associate_results": re.compile(
        r"Share of results of\s+joint ventures and associates\s+" + _ROW
    ),
}

# Column order within each matched row: HKEI, UK, Australia, Others,
# Sub-total, All other activities, Total. We keep HKEI/UK/Australia/Others
# and the reported Total (dropping Sub-total/All-other-activities, which
# are derivable and not needed for the geography breakdown).
_FIELD_ORDER = ["hkei", "uk", "australia", "others"]


def _parse_num(token: str) -> float:
    token = token.strip()
    if token == "–":
        return 0.0
    negative = token.startswith("(")
    value = float(token.replace("(", "").replace(")", "").replace(",", ""))
    return -value if negative else value


def _parse_segment_note(text: str, report_year: int) -> dict | None:
    """Parse the 'Segment reporting' note text for the current-period block.

    The note shows the current period's figures first, followed by a
    comparative prior-period block starting with the prior year label.
    We only take the first (current-period) block.
    """
    if "Segment reporting" not in text:
        return None

    year_matches = list(_YEAR_HEADER_RE.finditer(text))
    if not year_matches:
        return None

    # The first bare-year line should match the report's own year.
    first_year = int(year_matches[0].group(1))
    if first_year != report_year:
        logger.warning(
            "Segment note's first year block (%s) does not match report year (%s)",
            first_year,
            report_year,
        )
        return None

    # Restrict search to the text up to the second year header (i.e. only
    # the current-period block), if a second block exists.
    current_block = text[: year_matches[1].start()] if len(year_matches) > 1 else text

    parsed: dict[str, float] = {}
    for row_name, pattern in _ROW_PATTERNS.items():
        match = pattern.search(current_block)
        if not match:
            logger.warning("Could not find row '%s' in segment note", row_name)
            return None
        values = [_parse_num(g) for g in match.groups()]
        # values: [hkei, uk, australia, others, sub_total, all_other, total]
        for field, value in zip(_FIELD_ORDER, values[:4]):
            parsed[f"{row_name}_{field}_hkdm"] = value
        parsed[f"{row_name}_total_hkdm"] = values[6]

    return parsed


def fetch_power_assets_segments() -> pd.DataFrame:
    """Fetch and normalize Power Assets' semi-annual geographic segment note.

    Tries the current year's and prior year's H1 Interim Report across a
    small set of candidate chapter numbers (the note's exact chapter
    shifts slightly year to year). Periods that cannot be fetched or
    parsed are skipped -- never back-filled with guessed figures.
    """
    current_year = date.today().year
    records: list[dict] = []
    raw_snapshots: dict[str, str] = {}
    source_url = _INTERIM_URL_TEMPLATE.format(year=current_year, chapter=_CANDIDATE_CHAPTERS[0])

    for year in (current_year, current_year - 1):
        for chapter in _CANDIDATE_CHAPTERS:
            url = _INTERIM_URL_TEMPLATE.format(year=year, chapter=chapter)
            try:
                resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=20)
            except requests.RequestException as exc:
                logger.info("Power Assets interim chapter fetch failed (%s, e%02d): %s", year, chapter, exc)
                continue

            if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
                continue

            try:
                with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                    text = "\n".join((page.extract_text() or "") for page in pdf.pages)
            except Exception as exc:
                logger.warning("Power Assets interim chapter (%s, e%02d) failed to parse as PDF: %s", year, chapter, exc)
                continue

            if "Segment reporting" not in text:
                continue

            parsed = _parse_segment_note(text, year)
            if parsed is None:
                continue

            parsed["period"] = f"{year} H1"
            parsed["date"] = date(year, 6, 30).isoformat()
            records.append(parsed)
            raw_path = save_raw_snapshot(
                f"power_assets_segments_h1_{year}",
                resp.content,
                file_ext="pdf",
                source_url=url,
            )
            raw_snapshots[str(year)] = str(raw_path)
            source_url = url
            break  # found the right chapter for this year; move to next year

    if not records:
        result = pd.DataFrame(columns=SCHEMA_COLUMNS)
        result.attrs["raw_snapshot"] = None
        result.attrs["source_url"] = source_url
        return result

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])

    for col in SCHEMA_COLUMNS:
        if col not in df.columns:
            df[col] = None

    result = df[SCHEMA_COLUMNS].sort_values("date").reset_index(drop=True)
    result.attrs["raw_snapshot"] = raw_snapshots
    result.attrs["source_url"] = "https://www.powerassets.com/en/investor-relations/financial-reports"
    return result
