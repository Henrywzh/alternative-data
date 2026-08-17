"""Historical Buildings Department monthly-digest and project detail data.

The module keeps the stable Section 1 summary-table backfill separate from the
more fragile Tables 5.2--5.6 project-level parser.  Both contracts preserve
the digest publication month and raw PDF lineage; neither invents an exact
permit day or promotes a developer/phase attribution.
"""

from __future__ import annotations

import io
import json
import logging
import re
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
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

# The annual archive PDFs retain the detailed Md52--Md56 tables as visual
# tables rather than historical XLS files.  These contracts deliberately keep
# the digest month separate from an event date: the monthly digest tells us
# that a row was published in that issue, but does not expose the exact day on
# which the consent/permit was issued.  The x-coordinate bands below are the
# stable landscape-page columns used by the English digest since at least 2005;
# the parser still records a medium confidence when the row shape is unusual.
_DETAIL_STAGE_NAMES = {
    "5.2": "Demolition Consents",
    "5.3": "Plans Approved",
    "5.4": "Consent to Commence",
    "5.5": "Notice of Commencement Received",
    "5.6": "Occupation Permits (OP) Issued",
}
_DETAIL_TITLE_RE = re.compile(r"TABLE\s+5\.(2|3|4|5|6)\b", re.IGNORECASE)
_DETAIL_PERMIT_RE = re.compile(
    r"\b[A-Z]{1,3}\s*\d+/\d{4}(?:\s*/\s*OP|\s*\(\s*OP\s*\))(?=$|[^A-Za-z0-9])",
    re.IGNORECASE,
)
_DETAIL_PLANNING_REF_RE = re.compile(r"^\d+(?:\.\d+)+/\(\d+\)")
_DETAIL_SUSPECT_ADDRESS_RE = re.compile(
    r"(?:TABLE\s+5\.|NOTE:|ADDRESS OF SITE|\b(?:\d+\s+){2,}\d+\b)",
    re.IGNORECASE,
)
_DETAIL_REGION_LABELS = {
    "hong kong island",
    "kowloon & new territories",
    "kowloon and new territories",
    "kowloon",
    "new territories",
}
_DETAIL_CATEGORY_LABELS = {"domestic", "non-domestic", "composite"}
_DETAIL_COLUMNS = {
    # (column name, left edge, right edge).  The first band is intentionally
    # wider than the text itself so wrapped addresses remain in one cell.
    "Demolition Consents": (
        ("address", 0, 160), ("building_type", 160, 270),
        ("authorized_person", 270, 380), ("applicant", 380, 842),
    ),
    "Plans Approved": (
        ("address", 0, 178), ("blocks", 178, 240), ("storeys", 240, 263),
        ("building_type", 263, 375), ("gfa_domestic", 375, 430),
        ("gfa_non_domestic", 430, 465), ("authorized_person", 465, 558),
        ("engineer", 558, 650), ("applicant", 650, 842),
    ),
    "Consent to Commence": (
        ("address", 0, 150), ("blocks", 150, 210), ("storeys", 210, 225),
        ("building_type", 225, 320), ("units", 320, 347),
        ("unit_size", 347, 390), ("gfa_domestic", 390, 430),
        ("gfa_non_domestic", 430, 475), ("ufa_domestic", 475, 520),
        ("ufa_non_domestic", 520, 542), ("authorized_person", 542, 610),
        ("engineer", 610, 677), ("applicant", 677, 842),
    ),
    "Notice of Commencement Received": (
        ("address", 0, 140), ("blocks", 140, 205), ("storeys", 205, 215),
        ("building_type", 215, 310), ("units", 310, 347),
        ("unit_size", 347, 390), ("gfa_domestic", 390, 420),
        ("gfa_non_domestic", 420, 480), ("ufa_domestic", 480, 510),
        ("ufa_non_domestic", 510, 536), ("authorized_person", 536, 605),
        ("engineer", 605, 675), ("applicant", 675, 842),
    ),
    "Occupation Permits (OP) Issued": (
        ("address", 0, 100), ("permit_number", 100, 178),
        ("blocks", 178, 225), ("storeys", 225, 247),
        ("building_type", 247, 330), ("units", 330, 365),
        ("unit_size", 365, 400), ("gfa_domestic", 400, 445),
        ("gfa_non_domestic", 445, 480), ("ufa_domestic", 480, 525),
        ("ufa_non_domestic", 525, 545), ("authorized_person", 545, 615),
        ("engineer", 615, 682), ("applicant", 682, 842),
    ),
}
_DETAIL_OP_COLUMNS_PRE_2009 = (
    ("address", 0, 110), ("permit_number", 110, 183),
    ("blocks", 183, 225), ("storeys", 225, 250),
    # 2005--2008 rows use three glyph positions for the domestic-unit
    # column (x=327.7, 331.0 and 334.2).  The previous 330px boundary read
    # the latter two as unit sizes and under-counted the 2008-12 digest by
    # 1,760 units against its official Table 1.3 total.
    ("building_type", 250, 305), ("units", 305, 350),
    ("unit_size", 350, 380), ("gfa_domestic", 300, 410),
    ("gfa_non_domestic", 410, 425), ("ufa_domestic", 425, 485),
    ("ufa_non_domestic", 485, 500), ("authorized_person", 545, 635),
    ("engineer", 635, 710), ("applicant", 710, 842),
)
_DETAIL_OP_COLUMNS_2009_2010 = (
    ("address", 0, 110), ("permit_number", 110, 183),
    ("blocks", 183, 225), ("storeys", 225, 250),
    # In the 2009--2010 landscape layout some wrapped unit-tier rows start
    # at x=327.7 while the first row starts at x=331.0.  A 330px boundary
    # silently drops those tiers (the 2010-12 digest then under-counts 467
    # units against Table 1.3).  Keep the building-type band separate and
    # include both PDF glyph positions.
    ("building_type", 250, 325), ("units", 325, 350),
    ("unit_size", 350, 380), ("gfa_domestic", 380, 430),
    ("gfa_non_domestic", 430, 455), ("ufa_domestic", 455, 515),
    ("ufa_non_domestic", 515, 545), ("authorized_person", 545, 635),
    ("engineer", 635, 710), ("applicant", 710, 842),
)
_DETAIL_OP_COLUMNS_2020 = (
    ("address", 0, 105), ("permit_number", 105, 150),
    ("blocks", 150, 225), ("storeys", 225, 232),
    # The 2020 digest moved the unit columns left by roughly 25px.  Unit
    # counts appear at x=303--309, while unit sizes begin at x=337--340.
    # Using the post-2021 bands here reads sizes as counts (e.g. 10.3 -> 10).
    ("building_type", 232, 300), ("units", 300, 335),
    ("unit_size", 335, 365), ("gfa_domestic", 365, 410),
    ("gfa_non_domestic", 410, 445), ("ufa_domestic", 445, 500),
    ("ufa_non_domestic", 500, 520), ("authorized_person", 520, 580),
    ("engineer", 580, 645), ("applicant", 645, 842),
)
_DETAIL_HISTORY_COLUMNS = [
    "digest_month",
    "observation_month",
    "event_date",
    "event_date_status",
    "permit_stage",
    "permit_number",
    "region",
    "property_category",
    "site_address",
    "num_blocks",
    "num_storeys",
    "building_type",
    "domestic_units_count",
    "usable_floor_area_sqm",
    "domestic_gfa_sqm",
    "non_domestic_gfa_sqm",
    "non_domestic_usable_floor_area_sqm",
    "authorized_person",
    "registered_structural_engineer",
    "applicant",
    "revision_status",
    "source_pdf_page",
    "parser_confidence",
    "parser_quality_flag",
    "source_agency",
    "source_url",
    "archive_year",
    "raw_snapshot",
    "parser_version",
]
_DETAIL_AUDIT_COLUMNS = [
    "observation_month",
    "permit_stage",
    "summary_permit_stage",
    "comparison_metric",
    "detail_row_count",
    "detail_compared_row_count",
    "detail_amendment_row_count",
    "detail_domestic_units",
    "detail_compared_domestic_units",
    "detail_amendment_domestic_units",
    "summary_row_count",
    "summary_total_projects_count",
    "summary_domestic_units",
    "comparison_detail_value",
    "comparison_summary_value",
    "comparison_difference",
    "comparison_ratio",
    "reconciliation_status",
    "detail_quality_flag_count",
    "detail_medium_confidence_count",
    "detail_source_url",
    "summary_source_url",
    "detail_parser_version",
    "summary_parser_version",
]
_DETAIL_SUMMARY_COMPARISONS = {
    "Plans Approved": ("Plans Approved", "project_count"),
    "Consent to Commence": ("Consent to Commence", "domestic_units"),
    "Notice of Commencement Received": ("Notice of Commencement Received", "domestic_units"),
    "Occupation Permits (OP) Issued": ("Occupation Permits (OP) Issued", "domestic_units"),
}


def _detail_group_words_by_y(words: list[dict[str, Any]], tolerance: float = 1.5) -> list[list[dict[str, Any]]]:
    """Group pdfplumber words into visual lines without relying on glyph text."""
    rows: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (float(item.get("top", 0)), float(item.get("x0", 0)))):
        if not rows or abs(float(word.get("top", 0)) - float(rows[-1][0].get("top", 0))) > tolerance:
            rows.append([word])
        else:
            rows[-1].append(word)
    return rows


def _detail_detect_columns(
    words: list[dict[str, Any]],
    stage: str,
    archive_year: int | None = None,
) -> tuple[tuple[str, int, int], ...] | None:
    """Infer detail-table columns from the page's multi-row header.

    The Buildings Department shifted the landscape table by 20--40 points
    across PDF vintages.  Header-derived bands are safer than a year-only
    lookup and still fall back to the tested static contracts when a page
    does not expose a header (usually a continuation page).
    """
    if stage not in {
        "Plans Approved",
        "Consent to Commence",
        "Notice of Commencement Received",
        "Occupation Permits (OP) Issued",
    }:
        return None
    # The pre-2013 plans table uses a materially different compact layout;
    # its labels overlap the data bands and the tested static contract is more
    # reliable there.  Header-derived plans columns are needed for the later
    # shifted landscape layout (notably 2023), so only gate that stage.
    if stage == "Plans Approved" and archive_year is not None and archive_year < 2013:
        return None
    rows = _detail_group_words_by_y(words)
    address_row_index: int | None = None
    for index, row in enumerate(rows):
        text = " ".join(str(word.get("text", "")) for word in row)
        if re.search(r"address\s+of\s+site", text, re.IGNORECASE):
            address_row_index = index
            break
    if address_row_index is None:
        return None
    # The landscape digest header is not consistently two visual rows.  Older
    # issues put the ``Domestic / Non-domestic`` subheaders below the address
    # row, while newer issues may add a separate ``Size`` row.  Restrict the
    # window by vertical distance rather than a fixed row count so we capture
    # the complete header without pulling in the first project/category row.
    address_top = float(rows[address_row_index][0].get("top", 0))
    header_words = [
        word
        for row in rows
        if address_top - 15 <= float(row[0].get("top", 0)) <= address_top + 16
        for word in row
    ]

    def positions(*labels: str) -> list[float]:
        wanted = {label.casefold() for label in labels}
        return [
            float(word.get("x0", 0))
            for word in header_words
            if str(word.get("text", "")).strip().casefold() in wanted
        ]

    no_positions = positions("No.", "No")
    block_positions = positions("Blocks")
    storey_positions = positions("Storeys")
    building_positions = positions("Building")
    unit_positions = positions("Unit")
    permit_positions = positions("Permit")
    occupation_positions = positions("Occupation")
    domestic_positions = sorted(positions("Domestic"))
    non_domestic_positions = sorted(positions("Non-domestic"))
    authorized_positions = positions("Authorized")
    engineer_positions = positions("Engineer")
    applicant_positions = positions("Applicant")
    if stage == "Plans Approved":
        if not (
            block_positions
            and storey_positions
            and building_positions
            and domestic_positions
            and non_domestic_positions
            and authorized_positions
            and engineer_positions
            and applicant_positions
        ):
            return None
    elif not (
        no_positions
        and block_positions
        and storey_positions
        and building_positions
        and unit_positions
        and len(domestic_positions) >= 2
        and len(non_domestic_positions) >= 2
        and authorized_positions
        and engineer_positions
        and applicant_positions
    ):
        return None
    if stage == "Plans Approved":
        lefts = [
            ("address", 0),
            ("blocks", max(0, min(block_positions) - 5)),
            ("storeys", max(0, min(storey_positions) - 5)),
            (
                "building_type",
                max(0, min(building_positions) - 35, min(storey_positions)),
            ),
        ]
        gfa_domestic_left = max(0, min(domestic_positions) - 5)
        gfa_non_domestic_left = max(0, min(non_domestic_positions) - 5)
        # Text glyphs in the older plans table can begin well to the left of
        # their header labels.  Keep the numeric bands header-derived while
        # widening the free-text bands enough to retain the first name token.
        authorized_left = max(gfa_non_domestic_left + 1, min(authorized_positions) - 20)
        engineer_left = max(authorized_left + 1, min(engineer_positions) - 35)
        applicant_left = max(engineer_left + 1, min(applicant_positions) - 60)
        lefts.extend(
            [
                ("gfa_domestic", gfa_domestic_left),
                ("gfa_non_domestic", gfa_non_domestic_left),
                ("authorized_person", authorized_left),
                ("engineer", engineer_left),
                ("applicant", applicant_left),
            ]
        )
        if any(left >= right for (_, left), (_, right) in zip(lefts, lefts[1:])):
            return None
        return tuple(
            (name, int(left), int(right))
            for (name, left), (_, right) in zip(lefts, lefts[1:] + [("_end", 842)])
        )
    if stage == "Occupation Permits (OP) Issued" and not (permit_positions or occupation_positions):
        return None
    first_domestic_header = min(domestic_positions)
    units_header = max(no_positions)
    if units_header < first_domestic_header - 30:
        # Some 2012-era OP headers print ``Domestic units`` on the top row
        # without a third ``No.`` token on the second row.
        units_header = first_domestic_header
    unit_size_header = min(position for position in unit_positions if position > units_header - 2)
    gfa_domestic_header = min(position for position in domestic_positions if position > unit_size_header)
    gfa_non_domestic_header = min(position for position in non_domestic_positions if position > gfa_domestic_header)
    ufa_domestic_header = max(position for position in domestic_positions if position > gfa_non_domestic_header)
    ufa_non_domestic_header = max(position for position in non_domestic_positions if position > ufa_domestic_header)
    lefts = [("address", 0)]
    if stage == "Occupation Permits (OP) Issued":
        # A few legacy digests extract the permit prefix (``HK``/``NT``/``PR``)
        # as a separate word 8--12pt before the numeric portion.  Keep that
        # prefix in the permit cell so the normalizer sees the full identifier
        # (otherwise every OP row in those pages is silently rejected).
        lefts.append(("permit_number", max(0, min(permit_positions or occupation_positions) - 20)))
    engineer_left = max(0, min(engineer_positions) - 10)
    applicant_left = max(0, engineer_left + 1, min(applicant_positions) - 55)
    lefts.extend([
        ("blocks", max(0, min(block_positions) - 5)),
        ("storeys", max(0, min(storey_positions) - 5)),
        # PDF extraction often places the first building-type glyph well to
        # the left of the header label (for example ``Apartment/Commercial``
        # starts ~20--30pt before ``Building type``).  If this band is too
        # narrow, the first row is not recognised as a new project and all
        # of its continuation unit tiers disappear from the history.
        (
            "building_type",
            max(
                0,
                min(building_positions) - 35,
                min(storey_positions),
            ),
        ),
        # Data glyphs can sit a few points left of their header labels.
        ("units", max(0, units_header - 5)),
        ("unit_size", max(0, unit_size_header - 10)),
        ("gfa_domestic", max(0, gfa_domestic_header - 5)),
        ("gfa_non_domestic", max(0, gfa_non_domestic_header - 5)),
        ("ufa_domestic", max(0, ufa_domestic_header - 5)),
        ("ufa_non_domestic", max(0, ufa_non_domestic_header - 5)),
        ("authorized_person", max(0, min(authorized_positions) - 10)),
        ("engineer", engineer_left),
        # Applicant company names often begin 35–45 points to the left of
        # the printed ``Applicant`` header.  A narrow band captures only the
        # legal suffix (``Ltd``), which destroys the most useful entity key
        # for joining BD permits to project/SPV evidence.  Keep the band
        # after the engineer column while widening it leftward.
        ("applicant", applicant_left),
    ])
    # Header labels are ordered left-to-right; reject a malformed extraction
    # rather than constructing overlapping bands.
    if any(left >= right for (_, left), (_, right) in zip(lefts, lefts[1:])):
        return None
    return tuple(
        (name, int(left), int(right))
        for (name, left), (_, right) in zip(lefts, lefts[1:] + [("_end", 842)])
    )


def _detail_cells(
    words: list[dict[str, Any]],
    stage: str,
    archive_year: int | None = None,
    columns: tuple[tuple[str, int, int], ...] | None = None,
) -> dict[str, str]:
    if columns is not None:
        selected_columns = columns
    elif stage == "Occupation Permits (OP) Issued" and archive_year and archive_year <= 2008:
        selected_columns = _DETAIL_OP_COLUMNS_PRE_2009
    elif stage == "Occupation Permits (OP) Issued" and archive_year == 2020:
        selected_columns = _DETAIL_OP_COLUMNS_2020
    elif stage == "Occupation Permits (OP) Issued" and archive_year and archive_year <= 2010:
        selected_columns = _DETAIL_OP_COLUMNS_2009_2010
    else:
        selected_columns = _DETAIL_COLUMNS[stage]
    cells: dict[str, list[str]] = {name: [] for name, _, _ in selected_columns}
    for word in sorted(words, key=lambda item: float(item.get("x0", 0))):
        x0 = float(word.get("x0", 0))
        for name, left, right in selected_columns:
            if left <= x0 < right:
                cells[name].append(str(word.get("text", "")))
                break
    return {name: " ".join(values).strip() for name, values in cells.items()}


def _detail_numeric(value: Any, *, integer: bool = False) -> float | None:
    # Keep whitespace between adjacent visual columns.  Older PDFs often
    # place ``unit count`` and ``unit size`` in the same extracted cell (for
    # example ``1 275.0``); deleting the space would turn that into 1275.0 and
    # create a false unit-count spike.
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or text in {"-", "--", "—"}:
        return None
    # Put the comma-grouped alternative first and require a digit boundary.
    # Without the boundary ``1580`` matched the first three digits (``158``),
    # which only surfaced in older PDFs with four-digit unit tiers.
    match = re.search(
        r"(?<![A-Za-z0-9])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\d)",
        text,
    )
    if not match:
        return None
    try:
        number = float(match.group(0).replace(",", ""))
        return float(int(number)) if integer else number
    except (TypeError, ValueError):
        return None


def _detail_has_blocks_value(value: Any) -> bool:
    """Return whether a project row publishes a block-count cell.

    Md53--Md55 legitimately use ``-`` for non-building works (cable trenches,
    footbridges, plant rooms, etc.).  Those rows still count as projects in
    Section 1 and must not be discarded merely because the block count is not
    numeric.
    """
    text = re.sub(r"\s+", "", str(value or ""))
    if _detail_numeric(value, integer=True) is not None:
        return True
    # Static legacy bands can concatenate the block/storey/building cells
    # (for example ``- -Team``).  The first token is still the published
    # block-count marker; accept a leading dash while rejecting arbitrary
    # continuation text.
    first_token = re.split(r"\s+", str(value or "").strip(), maxsplit=1)[0]
    return text in {"-", "--", "—"} or first_token in {"-", "--", "—"}


def _detail_normalize_permit(value: str) -> str | None:
    match = _DETAIL_PERMIT_RE.search(str(value or ""))
    if not match:
        return None
    normalized = re.sub(r"\s+", "", match.group(0)).upper()
    normalized = normalized.replace("(OP)", "/OP")
    return normalized


def _detail_clean_address(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or text.lower() in _DETAIL_REGION_LABELS:
        return ""
    if re.match(r"^\(?\d+(?:\.\d+)+/\(\d+\)", text):
        return ""
    if text.lower().startswith(("note:", "* in terms", "the figure in parentheses")):
        return ""
    return text


def _detail_has_project_address(value: str) -> bool:
    """Reject numeric spillover from the PDF's adjacent columns as an address."""
    cleaned = _detail_clean_address(value)
    return bool(cleaned and re.search(r"[A-Za-z]", cleaned) and len(cleaned) >= 3)


def _detail_address_quality(address: str) -> tuple[str, str]:
    """Return a conservative parser quality flag for column spillover."""
    if _DETAIL_SUSPECT_ADDRESS_RE.search(address):
        return "MEDIUM", "address_column_spillover_or_note_text"
    return "HIGH", "ok"


def _detail_category(row_text: str, current: str) -> str:
    normalized = re.sub(r"\s+", " ", row_text).strip().lower()
    if normalized in _DETAIL_CATEGORY_LABELS:
        return normalized.title() if normalized != "non-domestic" else "Non-domestic"
    return current


def _detail_region(row_text: str, current: str) -> str:
    normalized = re.sub(r"\s+", " ", row_text).strip().lower()
    if normalized in _DETAIL_REGION_LABELS:
        if normalized == "kowloon and new territories":
            return "Kowloon & New Territories"
        return normalized.title()
    return current


def _detail_header_stage(text: str) -> str | None:
    match = _DETAIL_TITLE_RE.search(text)
    return _DETAIL_STAGE_NAMES.get(f"5.{match.group(1)}") if match else None


def _detail_is_table_header(row_text: str) -> bool:
    lowered = row_text.lower()
    return (
        "table 5." in lowered
        or "detailed information" in lowered
        or "address of site" in lowered
        or "occupation permit no." in lowered
        or "no. of blocks" in lowered
    )


def parse_bd_detail_pdf(
    pdf_bytes: bytes,
    digest_month: str,
    source_url: str,
    archive_year: int | None = None,
) -> pd.DataFrame:
    """Parse project rows from one official monthly digest's Tables 5.2--5.6.

    The source PDF is a visual table and does not publish a precise event day.
    ``digest_month`` is therefore the observation/publication month, while
    ``event_date`` remains null with an explicit ``event_date_status``.  This
    is intentionally a history layer, not a replacement for the current XLS
    snapshot parser.
    """
    records: list[dict[str, Any]] = []
    digest_month = str(pd.to_datetime(digest_month).strftime("%Y-%m-01"))
    current_stage: str | None = None
    detected_columns: dict[str, tuple[tuple[str, int, int], ...]] = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text(layout=True) or ""
            title_stage = _detail_header_stage(page_text)
            if title_stage:
                current_stage = title_stage
            # Annual/monthly digests often append corrigenda for an earlier
            # issue after the current detailed tables.  Those pages repeat a
            # 5.3--5.6 heading but must not be attributed to this digest's
            # observation month; Section 1's current-month summary excludes
            # them.  Keep the official PDF in raw lineage, but omit the
            # historical correction rows from this month-level detail parse.
            if re.search(r"\bCORRIGENDUM\b", page_text, re.IGNORECASE):
                continue
            if not current_stage or not re.search(r"address\s+of\s+site", page_text, re.IGNORECASE):
                continue
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
            if not words:
                continue
            page_columns = _detail_detect_columns(words, current_stage, archive_year)
            if page_columns is not None:
                detected_columns[current_stage] = page_columns
            revision_status = "amendment" if re.search(r"\bAMENDMENT\b", page_text, re.IGNORECASE) else "as_published"
            current_region = "Unknown"
            current_category = "Domestic" if current_stage != "Demolition Consents" else "Unknown"
            current: dict[str, Any] | None = None
            previous_row_top: float | None = None

            def flush() -> None:
                nonlocal current
                if not current:
                    return
                address = re.sub(r"\s+", " ", " ".join(current.pop("address_lines", []))).strip()
                current.pop("_after_reference", None)
                if address:
                    confidence, quality_flag = _detail_address_quality(address)
                    if confidence == "MEDIUM":
                        current["parser_confidence"] = "MEDIUM"
                    current["parser_quality_flag"] = quality_flag
                    current["site_address"] = address
                    records.append(current)
                current = None

            def merge_continuation(cells: dict[str, str]) -> None:
                """Merge wrapped address/unit rows, including planning-ref rows."""
                if current is None:
                    return
                cleaned = _detail_clean_address(cells.get("address", ""))
                if cleaned:
                    current["address_lines"].append(cleaned)
                units = _detail_numeric(cells.get("units"), integer=True)
                if units is not None:
                    current["domestic_units_count"] = (current.get("domestic_units_count") or 0) + units
                for field, cell_name in (
                    ("usable_floor_area_sqm", "ufa_domestic"),
                    ("domestic_gfa_sqm", "gfa_domestic"),
                    ("non_domestic_gfa_sqm", "gfa_non_domestic"),
                    ("non_domestic_usable_floor_area_sqm", "ufa_non_domestic"),
                ):
                    if pd.isna(current.get(field)):
                        value = _detail_numeric(cells.get(cell_name))
                        if value is not None:
                            current[field] = value

            for row_words in _detail_group_words_by_y(words):
                row_top = float(row_words[0].get("top", 0))
                row_gap = row_top - previous_row_top if previous_row_top is not None else 0.0
                previous_row_top = row_top
                cells = _detail_cells(
                    row_words,
                    current_stage,
                    archive_year,
                    columns=detected_columns.get(current_stage),
                )
                row_text = " ".join(value for value in cells.values() if value).strip()
                if not row_text or _detail_is_table_header(row_text):
                    continue
                address_cell = cells.get("address", "")
                normalized_address_cell = re.sub(r"\s+", " ", address_cell).strip().lower()
                current_region = _detail_region(address_cell or row_text, current_region)
                current_category = _detail_category(row_text, current_category)
                if normalized_address_cell in _DETAIL_REGION_LABELS:
                    if current is not None:
                        current["region"] = current_region
                        merge_continuation(cells)
                    continue
                if row_text.lower() in _DETAIL_CATEGORY_LABELS:
                    continue

                # Planning-area references terminate a project block.  They
                # are useful for deciding whether the next row with repeated
                # block/type cells is a new project, but are not part of the
                # human-readable site address.
                if _DETAIL_PLANNING_REF_RE.match(address_cell.strip()):
                    if current is not None:
                        merge_continuation(cells)
                        current["_after_reference"] = True
                    continue

                permit_match = _DETAIL_PERMIT_RE.search(cells.get("permit_number", ""))
                normalized_permit = _detail_normalize_permit(cells.get("permit_number", ""))
                if current_stage == "Occupation Permits (OP) Issued":
                    is_new = bool(permit_match)
                elif current_stage == "Demolition Consents":
                    is_new = bool(
                        _detail_has_project_address(address_cell)
                        and cells.get("building_type")
                        and (current is None or current.get("_after_reference") or row_gap > 12)
                    )
                else:
                    is_new = bool(
                        _detail_has_project_address(address_cell)
                        and cells.get("building_type")
                        and _detail_has_blocks_value(cells.get("blocks"))
                        and (current is None or current.get("_after_reference") or row_gap > 12)
                    )

                if is_new:
                    flush()
                    current = {
                        "digest_month": digest_month,
                        "observation_month": digest_month,
                        "event_date": pd.NA,
                        "event_date_status": "not_published_in_monthly_digest",
                        "permit_stage": current_stage,
                        "permit_number": normalized_permit if normalized_permit else pd.NA,
                        "region": current_region,
                        "property_category": current_category,
                        "address_lines": [],
                        "num_blocks": _detail_numeric(cells.get("blocks"), integer=True),
                        "num_storeys": _detail_numeric(cells.get("storeys"), integer=True),
                        "building_type": cells.get("building_type") or pd.NA,
                        "domestic_units_count": _detail_numeric(cells.get("units"), integer=True),
                        "usable_floor_area_sqm": (
                            _detail_numeric(cells.get("ufa_domestic"))
                            or _detail_numeric(cells.get("ufa_non_domestic"))
                        ),
                        "domestic_gfa_sqm": _detail_numeric(cells.get("gfa_domestic")),
                        "non_domestic_gfa_sqm": _detail_numeric(cells.get("gfa_non_domestic")),
                        "non_domestic_usable_floor_area_sqm": _detail_numeric(cells.get("ufa_non_domestic")),
                        "authorized_person": cells.get("authorized_person") or pd.NA,
                        "registered_structural_engineer": cells.get("engineer") or pd.NA,
                        "applicant": cells.get("applicant") or pd.NA,
                        "revision_status": revision_status,
                        "source_pdf_page": page_number,
                        "parser_confidence": "HIGH" if (permit_match or current_stage in {"Demolition Consents", "Plans Approved"}) else "MEDIUM",
                        "parser_quality_flag": "pending_address_audit",
                        "source_agency": "Hong Kong Buildings Department",
                        "source_url": source_url,
                        "archive_year": archive_year,
                        "raw_snapshot": pd.NA,
                        "parser_version": "bd-detail-history-v6",
                        "_after_reference": False,
                    }
                    cleaned = _detail_clean_address(address_cell)
                    if cleaned:
                        current["address_lines"].append(cleaned)
                    continue

                if current is None:
                    continue
                merge_continuation(cells)
            flush()

    if not records:
        return pd.DataFrame(columns=_DETAIL_HISTORY_COLUMNS)
    result = pd.DataFrame(records)
    for column in _DETAIL_HISTORY_COLUMNS:
        if column not in result.columns:
            result[column] = pd.NA
    result = result[_DETAIL_HISTORY_COLUMNS]
    # A project can span pages, but identical page rows are still a parser
    # duplicate.  Keep amendment rows separate because they are explicit BD
    # revisions rather than accidental duplicates.  Md53--Md55 do not carry
    # a permit number, and a single address can legitimately have multiple
    # approvals (for example two utility structures at one site); include the
    # row's published type/measure fingerprint so those records survive.
    result = result.drop_duplicates(
        subset=[
            "digest_month",
            "permit_stage",
            "site_address",
            "permit_number",
            "revision_status",
            "building_type",
            "num_blocks",
            "num_storeys",
            "domestic_units_count",
            "domestic_gfa_sqm",
            "non_domestic_gfa_sqm",
            "usable_floor_area_sqm",
            "authorized_person",
            "registered_structural_engineer",
            "applicant",
        ],
        keep="first",
    ).reset_index(drop=True)
    return result


def build_bd_project_lifecycle_history_audit(
    detail_history: pd.DataFrame,
    summary_history: pd.DataFrame,
) -> pd.DataFrame:
    """Reconcile detailed Md52--Md56 rows against Section 1 aggregates.

    The audit is deliberately separate from the project history contract.  A
    mismatch is evidence that a parser/layout or source-scope question needs
    review; it never overwrites either input with the other.  Unit totals are
    compared for Md54--Md56, while Md53 is compared only on project-row count.
    Md52 has no like-for-like Section 1 aggregate in the current summary
    contract and is therefore reported as ``not_comparable``.
    """
    detail = detail_history.copy() if detail_history is not None else pd.DataFrame()
    summary = summary_history.copy() if summary_history is not None else pd.DataFrame()
    if not detail.empty:
        detail["observation_month"] = pd.to_datetime(
            detail.get("digest_month", detail.get("observation_month")), errors="coerce"
        ).dt.strftime("%Y-%m-01")
    if not summary.empty:
        summary["observation_month"] = pd.to_datetime(summary["observation_month"], errors="coerce").dt.strftime("%Y-%m-01")

    detail_keys = set()
    if not detail.empty and {"observation_month", "permit_stage"}.issubset(detail.columns):
        detail_keys = set(zip(detail["observation_month"], detail["permit_stage"]))
    summary_keys = set()
    if not summary.empty and {"observation_month", "permit_stage"}.issubset(summary.columns):
        summary_keys = set(zip(summary["observation_month"], summary["permit_stage"]))
    rows: list[dict[str, Any]] = []
    for month, stage in sorted(
        detail_keys | summary_keys,
        key=lambda item: (str(item[0]), str(item[1])),
    ):
        detail_rows = detail[(detail["observation_month"] == month) & (detail["permit_stage"] == stage)] if not detail.empty else pd.DataFrame()
        summary_stage, metric = _DETAIL_SUMMARY_COMPARISONS.get(stage, (None, None))
        summary_rows = (
            summary[(summary["observation_month"] == month) & (summary["permit_stage"] == summary_stage)]
            if summary_stage and not summary.empty
            else pd.DataFrame()
        )

        # Section 1 is the as-published monthly total.  Tables 5.2--5.6 may
        # append explicitly labelled amendment pages for earlier issues; the
        # amendment rows are real source records but are not part of the
        # current month's Section 1 denominator.  Keep them in the detail
        # contract and expose their counts in the audit, while comparing only
        # the as-published slice to avoid treating an official correction as a
        # parser gap.
        if not detail_rows.empty and "revision_status" in detail_rows.columns:
            revision_status = detail_rows["revision_status"].astype("string").str.strip().str.casefold()
            amendment_mask = revision_status.eq("amendment")
            compared_detail_rows = detail_rows.loc[~amendment_mask]
            amendment_detail_rows = detail_rows.loc[amendment_mask]
        else:
            compared_detail_rows = detail_rows
            amendment_detail_rows = detail_rows.iloc[0:0]

        def _sum_numeric(frame: pd.DataFrame, column: str) -> float | None:
            if frame.empty or column not in frame.columns:
                return None
            values = pd.to_numeric(frame[column], errors="coerce")
            return float(values.sum()) if values.notna().any() else None

        detail_units = _sum_numeric(detail_rows, "domestic_units_count")
        compared_detail_units = _sum_numeric(compared_detail_rows, "domestic_units_count")
        amendment_detail_units = _sum_numeric(amendment_detail_rows, "domestic_units_count")
        summary_units = _sum_numeric(summary_rows, "total_domestic_units")
        summary_projects = _sum_numeric(summary_rows, "total_projects_count")
        if metric == "domestic_units":
            comparison_detail = compared_detail_units
            comparison_summary = summary_units
        elif metric == "project_count":
            comparison_detail = float(len(compared_detail_rows)) if not compared_detail_rows.empty else None
            comparison_summary = summary_projects
        else:
            comparison_detail = None
            comparison_summary = None

        difference: float | None = None
        ratio: float | None = None
        if comparison_detail is not None and comparison_summary is not None:
            difference = float(comparison_detail - comparison_summary)
            ratio = float(comparison_detail / comparison_summary) if comparison_summary else (1.0 if difference == 0 else None)
            status = "matched" if abs(difference) <= 0.5 else "gap"
        elif metric is None:
            status = "not_comparable"
        elif metric == "domestic_units" and comparison_detail is None and comparison_summary == 0:
            # A detail table can contain only non-domestic works (no numeric
            # domestic-unit cell) while Section 1 explicitly reports zero.
            # This is a reconciled zero, not a parser failure or a zero-filled
            # missing month.
            status = "matched_zero"
        elif comparison_detail is None:
            status = "detail_metric_missing"
        elif comparison_summary is None:
            status = "summary_metric_missing"
        else:
            status = "not_comparable"

        quality_count = int(
            compared_detail_rows.get("parser_quality_flag", pd.Series(dtype="object")).astype("string").ne("ok").sum()
        ) if not compared_detail_rows.empty else 0
        medium_count = int(
            compared_detail_rows.get("parser_confidence", pd.Series(dtype="object")).astype("string").eq("MEDIUM").sum()
        ) if not compared_detail_rows.empty else 0

        def _first_value(frame: pd.DataFrame, column: str) -> str | None:
            if frame.empty or column not in frame.columns:
                return None
            values = [str(value) for value in frame[column].dropna().tolist() if str(value).strip()]
            return values[0] if values else None

        rows.append(
            {
                "observation_month": month,
                "permit_stage": stage,
                "summary_permit_stage": summary_stage,
                "comparison_metric": metric,
                "detail_row_count": int(len(detail_rows)),
                "detail_compared_row_count": int(len(compared_detail_rows)),
                "detail_amendment_row_count": int(len(amendment_detail_rows)),
                "detail_domestic_units": detail_units,
                "detail_compared_domestic_units": compared_detail_units,
                "detail_amendment_domestic_units": amendment_detail_units,
                "summary_row_count": int(len(summary_rows)),
                "summary_total_projects_count": summary_projects,
                "summary_domestic_units": summary_units,
                "comparison_detail_value": comparison_detail,
                "comparison_summary_value": comparison_summary,
                "comparison_difference": difference,
                "comparison_ratio": ratio,
                "reconciliation_status": status,
                "detail_quality_flag_count": quality_count,
                "detail_medium_confidence_count": medium_count,
                "detail_source_url": _first_value(detail_rows, "source_url"),
                "summary_source_url": _first_value(summary_rows, "source_url"),
                "detail_parser_version": _first_value(detail_rows, "parser_version"),
                "summary_parser_version": _first_value(summary_rows, "parser_version"),
            }
        )

    result = pd.DataFrame(rows, columns=_DETAIL_AUDIT_COLUMNS)
    if not result.empty:
        result = result.sort_values(["observation_month", "permit_stage"]).reset_index(drop=True)
    raw_snapshots = list(dict.fromkeys(
        [str(value) for frame in (detail, summary) for value in frame.attrs.get("raw_snapshots", []) if value]
    ))
    source_urls = list(dict.fromkeys(
        [str(value) for frame in (detail, summary) for value in frame.attrs.get("source_urls", []) if value]
    ))
    result.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        lineage_metadata={
            "lineage_type": "bd_detail_to_section_1_reconciliation_audit",
            "comparison_contract": _DETAIL_SUMMARY_COMPARISONS,
            "detail_records": int(len(detail)),
            "summary_records": int(len(summary)),
        },
    )
    return result


def fetch_bd_project_lifecycle_history_audit(
    start_year: int = BD_HISTORY_FIRST_YEAR,
    end_year: int | None = None,
) -> pd.DataFrame:
    """Build a bounded annual December cross-check for detailed BD history.

    Archived years use the December PDF from the official annual ZIP.  Years
    still published as direct PDFs use the latest available month, so the
    resulting dataset makes the historical/partial-current coverage explicit.
    """
    end_year = end_year or datetime.now(timezone.utc).year
    if start_year < BD_HISTORY_FIRST_YEAR or end_year < start_year:
        raise ValueError(f"supported BD history range starts at {BD_HISTORY_FIRST_YEAR}: {start_year=} {end_year=}")
    index_response = requests.get(BD_MONTHLY_DIGESTS_URL, headers=DEFAULT_HEADERS, timeout=30)
    index_response.raise_for_status()
    archives = discover_bd_digest_archives(index_response.text)
    direct_pdfs = discover_bd_digest_monthly_pdf_urls(index_response.text)
    detail_frames: list[pd.DataFrame] = []
    summary_frames: list[pd.DataFrame] = []
    raw_paths: list[str] = []
    source_urls: list[str] = []
    errors: list[str] = []

    def _download(url: str, timeout: int) -> bytes:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
                response.raise_for_status()
                return response.content
            except Exception as exc:  # noqa: BLE001 -- retry transient archive truncation
                last_error = exc
                if attempt < 2:
                    time.sleep(1.0)
        assert last_error is not None
        raise last_error

    for year in range(start_year, end_year + 1):
        try:
            if year in archives:
                archive_url = archives[year]
                member, pdf_bytes = _archive_december_pdf(_download(archive_url, 90), year)
                source_url = f"{archive_url}#{member}"
                digest_month = f"{year}-12-01"
            else:
                candidates = sorted((key, url) for key, url in direct_pdfs.items() if key[0] == year)
                if not candidates:
                    raise ValueError("no official annual archive or direct monthly PDF link found")
                (selected_year, selected_month), source_url = candidates[-1]
                if selected_year == datetime.now(timezone.utc).year and selected_month > datetime.now(timezone.utc).month:
                    raise ValueError("latest direct PDF is dated in the future")
                pdf_bytes = _download(source_url, 90)
                digest_month = f"{year}-{selected_month:02d}-01"

            raw_path = save_raw_snapshot(
                "bd_project_lifecycle_history_audit",
                pdf_bytes,
                file_ext="pdf",
                source_url=source_url,
            )
            raw_paths.append(str(raw_path))
            source_urls.append(source_url)
            detail = parse_bd_detail_pdf(pdf_bytes, digest_month, source_url, year)
            summary = parse_bd_history_digest(pdf_bytes, year, source_url, year)
            # Annual December PDFs contain the entire year's Section 1 table;
            # the audit compares only the same digest month as the detailed
            # Tables 5.2--5.6 sample.  Keeping Jan--Nov here would correctly
            # report ``detail_metric_missing`` but would make a December QA
            # audit look like a 12-month backfill.
            summary = summary[summary["observation_month"].eq(digest_month)].copy()
            if not detail.empty:
                detail["raw_snapshot"] = str(raw_path)
                detail_frames.append(detail)
            if not summary.empty:
                summary["raw_snapshot"] = str(raw_path)
                summary_frames.append(summary)
        except Exception as exc:  # noqa: BLE001 -- retain year-level coverage
            errors.append(f"{year}: {exc}")

    if detail_frames:
        prepared_detail: list[pd.DataFrame] = []
        for frame in detail_frames:
            frame = frame.copy()
            for column in _DETAIL_HISTORY_COLUMNS:
                # Explicitly align all columns before concatenation.  The
                # visual parser intentionally has all-null event_date fields;
                # casting the aligned frames avoids pandas' all-NA inference
                # warning without changing the persisted values.
                if column not in frame.columns:
                    frame[column] = pd.NA
                frame[column] = frame[column].astype(object)
            frame = frame[_DETAIL_HISTORY_COLUMNS]
            prepared_detail.append(frame)
        detail_history = pd.concat(prepared_detail, ignore_index=True)
    else:
        detail_history = pd.DataFrame(columns=_DETAIL_HISTORY_COLUMNS)
    if summary_frames:
        prepared_summary: list[pd.DataFrame] = []
        for frame in summary_frames:
            frame = frame.copy()
            for column in _HISTORY_COLUMNS:
                if column not in frame.columns:
                    frame[column] = pd.NA
                frame[column] = frame[column].astype(object)
            frame = frame[_HISTORY_COLUMNS]
            prepared_summary.append(frame)
        summary_history = pd.concat(prepared_summary, ignore_index=True)
    else:
        summary_history = pd.DataFrame(columns=_HISTORY_COLUMNS)
    detail_history.attrs.update(raw_snapshots=raw_paths, source_urls=source_urls)
    summary_history.attrs.update(raw_snapshots=raw_paths, source_urls=source_urls)
    result = build_bd_project_lifecycle_history_audit(detail_history, summary_history)
    result.attrs.update(
        raw_snapshots=raw_paths,
        source_urls=source_urls,
        backfill_errors=json.dumps(errors),
        lineage_metadata={
            **result.attrs.get("lineage_metadata", {}),
            "start_year": start_year,
            "end_year": end_year,
            "backfill_errors": errors,
        },
    )
    return result


def discover_bd_digest_monthly_pdf_urls(index_html: str) -> dict[tuple[int, int], str]:
    """Return every direct monthly PDF link currently exposed by the BD index."""
    urls: dict[tuple[int, int], str] = {}
    for href, year_s, month_s in re.findall(
        r'''href=["']([^"']*Md(20\d{2})(\d{2})e(?:_revised)?\.pdf[^"']*)["']''',
        index_html,
        flags=re.IGNORECASE,
    ):
        year, month = int(year_s), int(month_s)
        if 1 <= month <= 12:
            urls[(year, month)] = urljoin(BD_MONTHLY_DIGESTS_URL, href)
    return urls


def _archive_month_pdf(archive_bytes: bytes, year: int, month: int) -> tuple[str, bytes]:
    members = list_archive_pdf_members(archive_bytes, year)
    prefix = f"Md{year}{month:02d}e"
    member = next(name for name in members if name.startswith(prefix))
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        return member, archive.read(member)


def fetch_bd_project_lifecycle_history(
    start_year: int = BD_HISTORY_FIRST_YEAR,
    end_year: int | None = None,
    *,
    months: list[int] | tuple[int, ...] | None = None,
) -> pd.DataFrame:
    """Backfill detailed Md52--Md56 project rows from official monthly PDFs.

    This is intentionally explicit and separate from routine ingestion.  A
    20-year run downloads 240 PDFs (or 20 annual ZIP archives), so callers can
    begin with a bounded year or month sample and expand after QA.
    """
    end_year = end_year or datetime.now(timezone.utc).year
    if start_year < BD_HISTORY_FIRST_YEAR or end_year < start_year:
        raise ValueError(f"supported BD history range starts at {BD_HISTORY_FIRST_YEAR}: {start_year=} {end_year=}")
    selected_months = tuple(sorted(set(months or range(1, 13))))
    if not selected_months or any(month < 1 or month > 12 for month in selected_months):
        raise ValueError("months must contain values from 1 through 12")

    index_response = requests.get(BD_MONTHLY_DIGESTS_URL, headers=DEFAULT_HEADERS, timeout=30)
    index_response.raise_for_status()
    archives = discover_bd_digest_archives(index_response.text)
    direct_pdfs = discover_bd_digest_monthly_pdf_urls(index_response.text)
    frames: list[pd.DataFrame] = []
    raw_paths: list[str] = []
    source_urls: list[str] = []
    errors: list[str] = []
    empty_months: list[str] = []
    for year in range(start_year, end_year + 1):
        archive_bytes: bytes | None = None
        if year in archives:
            try:
                response = requests.get(archives[year], headers=DEFAULT_HEADERS, timeout=90)
                response.raise_for_status()
                archive_bytes = response.content
            except Exception as exc:  # noqa: BLE001 -- retain year-level coverage
                errors.append(f"{year}: archive download failed: {exc}")
                continue
        for month in selected_months:
            if year == end_year and month > datetime.now(timezone.utc).month and year == datetime.now(timezone.utc).year:
                continue
            try:
                if archive_bytes is not None:
                    member, pdf_bytes = _archive_month_pdf(archive_bytes, year, month)
                    source_url = f"{archives[year]}#{member}"
                elif (year, month) in direct_pdfs:
                    source_url = direct_pdfs[(year, month)]
                    pdf_response = requests.get(source_url, headers=DEFAULT_HEADERS, timeout=90)
                    pdf_response.raise_for_status()
                    pdf_bytes = pdf_response.content
                else:
                    errors.append(f"{year}-{month:02d}: no official monthly PDF link found")
                    continue
                raw_path = save_raw_snapshot(
                    "bd_project_lifecycle_history",
                    pdf_bytes,
                    file_ext="pdf",
                    source_url=source_url,
                )
                raw_paths.append(str(raw_path))
                source_urls.append(source_url)
                parsed = parse_bd_detail_pdf(
                    pdf_bytes,
                    f"{year}-{month:02d}-01",
                    source_url,
                    year,
                )
                if parsed.empty:
                    empty_months.append(f"{year}-{month:02d}")
                    continue
                parsed["raw_snapshot"] = str(raw_path)
                frames.append(parsed)
            except Exception as exc:  # noqa: BLE001 -- retain month-level coverage
                errors.append(f"{year}-{month:02d}: {exc}")

    if frames:
        prepared_frames: list[pd.DataFrame] = []
        for frame in frames:
            prepared = frame.copy()
            # Keep explicitly all-null semantic columns (notably event_date)
            # as object before concatenation; this avoids pandas silently
            # changing the inferred dtype when a later year gains a value.
            for column in _DETAIL_HISTORY_COLUMNS:
                if column in prepared.columns and prepared[column].isna().all():
                    prepared[column] = prepared[column].astype(object)
            prepared_frames.append(prepared)
        result = pd.concat(prepared_frames, ignore_index=True)
    else:
        result = pd.DataFrame(columns=_DETAIL_HISTORY_COLUMNS)
    if not result.empty:
        result = result.sort_values(["digest_month", "permit_stage", "site_address"]).reset_index(drop=True)
    result.attrs.update(
        raw_snapshot=json.dumps(raw_paths),
        raw_snapshots=raw_paths,
        source_url=json.dumps(source_urls),
        source_urls=source_urls,
        backfill_errors=json.dumps(errors),
        empty_months=json.dumps(empty_months),
        lineage_metadata={
            "parser_version": "bd-detail-history-v6",
            "start_year": start_year,
            "end_year": end_year,
            "months": list(selected_months),
            "empty_months": empty_months,
            "backfill_errors": errors,
        },
    )
    return result


def reparse_bd_project_lifecycle_history_from_local_snapshots(
    history: pd.DataFrame,
    *,
    strict: bool = True,
) -> pd.DataFrame:
    """Reparse an existing detail-history snapshot without another network fetch.

    The historical backfill stores one raw PDF path on every parsed row.  This
    helper reuses those immutable local PDFs after a parser fix, preserving the
    original digest month and source URL while making the reparse explicit in
    lineage.  It is intentionally strict by default: a missing or unreadable
    raw PDF must not produce a seemingly complete partial replacement.  Set
    ``strict=False`` only for a bounded diagnostic run.
    """
    source = history.copy() if history is not None else pd.DataFrame()
    if source.empty:
        result = pd.DataFrame(columns=_DETAIL_HISTORY_COLUMNS)
        result.attrs.update(
            raw_snapshots=[],
            source_urls=[],
            reparse_errors=[],
            lineage_metadata={
                "lineage_type": "local_raw_reparse_after_detail_parser_fix",
                "parser_version": "bd-detail-history-v6",
                "input_rows": 0,
                "output_rows": 0,
                "raw_pdf_count": 0,
            },
        )
        return result
    required = {"raw_snapshot", "digest_month", "source_url", "archive_year"}
    missing = sorted(required.difference(source.columns))
    if missing:
        raise ValueError(f"bd detail history is missing reparse columns: {missing}")

    jobs: list[tuple[str, str, str, int]] = []
    for raw_snapshot, group in source.groupby("raw_snapshot", dropna=True, sort=True):
        raw_path = str(raw_snapshot).strip()
        if not raw_path:
            continue
        first = group.iloc[0]

        def _first_text(*values: Any) -> str:
            for value in values:
                if value is None:
                    continue
                try:
                    if bool(pd.isna(value)):
                        continue
                except (TypeError, ValueError):
                    pass
                text = str(value).strip()
                if text and text.casefold() not in {"<na>", "nan", "nat"}:
                    return text
            return ""

        digest_month = _first_text(first.get("digest_month"), first.get("observation_month"))
        source_url = _first_text(first.get("source_url")) or BD_MONTHLY_DIGESTS_URL
        try:
            archive_year = int(float(first.get("archive_year")))
        except (TypeError, ValueError):
            parsed_month = pd.to_datetime(digest_month, errors="coerce")
            if pd.isna(parsed_month):
                raise ValueError(f"cannot infer archive year for raw snapshot {raw_path}")
            archive_year = int(parsed_month.year)
        jobs.append((raw_path, digest_month, source_url, archive_year))

    frames: list[pd.DataFrame] = []
    errors: list[dict[str, str]] = []
    raw_paths: list[str] = []
    source_urls: list[str] = []
    for raw_path, digest_month, source_url, archive_year in jobs:
        try:
            pdf_path = Path(raw_path)
            if not pdf_path.exists():
                raise FileNotFoundError(raw_path)
            parsed = parse_bd_detail_pdf(pdf_path.read_bytes(), digest_month, source_url, archive_year)
            if not parsed.empty:
                parsed = parsed.copy()
                parsed["raw_snapshot"] = raw_path
                frames.append(parsed)
            raw_paths.append(raw_path)
            source_urls.append(source_url)
        except Exception as exc:  # noqa: BLE001 -- collect file-level QA context
            errors.append(
                {
                    "raw_snapshot": raw_path,
                    "digest_month": digest_month,
                    "error": repr(exc),
                }
            )

    if errors and strict:
        raise RuntimeError(
            f"local BD detail reparse failed for {len(errors)} of {len(jobs)} raw PDFs; "
            "set strict=False only for diagnostics"
        )
    if frames:
        result = pd.concat(frames, ignore_index=True)
        for column in _DETAIL_HISTORY_COLUMNS:
            if column not in result.columns:
                result[column] = pd.NA
        result = result[_DETAIL_HISTORY_COLUMNS]
        result = result.sort_values(["digest_month", "permit_stage", "site_address"]).reset_index(drop=True)
    else:
        result = pd.DataFrame(columns=_DETAIL_HISTORY_COLUMNS)
    result.attrs.update(
        raw_snapshots=raw_paths,
        source_urls=list(dict.fromkeys(source_urls)),
        reparse_errors=errors,
        lineage_metadata={
            "lineage_type": "local_raw_reparse_after_detail_parser_fix",
            "parser_version": "bd-detail-history-v6",
            "input_rows": int(len(source)),
            "output_rows": int(len(result)),
            "raw_pdf_count": int(len(jobs)),
            "reparse_errors": errors,
            "source_scope": "existing local raw snapshots; no network fetch",
        },
    )
    return result


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
