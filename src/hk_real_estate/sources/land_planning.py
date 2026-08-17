"""Conservative parsers for official LandsD and TPB project evidence.

These helpers extract the facts printed by the source.  They deliberately do
not resolve an application, lot, developer or parent-company mention to SHKP,
SRPE, or an ownership record.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urljoin, urlparse

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot


TPB_APPLICATION_COLUMNS = [
    "application_no",
    "application_type",
    "plan_area",
    "district",
    "application_received_date",
    "application_received_date_raw",
    "location_raw",
    "proposal_raw",
    "tentative_meeting_date",
    "tentative_meeting_date_raw",
    "public_inspection_until_date",
    "public_inspection_until_date_raw",
    "comment_expiry_date",
    "comment_expiry_date_raw",
    "comment_count",
    "remark",
    "further_information_json",
    "detail_url",
    "evidence_status",
]

LANDSD_CONSENT_COLUMNS = [
    "development_name_raw",
    "lot_no_raw",
    "parent_or_holding_company_or_developer_raw",
    "consent_type_raw",
    "solicitors_raw",
    "consent_or_approval_date",
    "consent_or_approval_date_raw",
    "district",
    "document_as_of_date",
    "document_url",
    "page_number",
    "extraction_method",
    "parser_confidence",
]

TPB_FETCH_COLUMNS = TPB_APPLICATION_COLUMNS + ["fetched_at", "raw_snapshot", "source_sha256"]
LANDSD_CONSENT_FETCH_COLUMNS = LANDSD_CONSENT_COLUMNS + ["fetched_at", "raw_snapshot", "source_sha256"]

# The monthly consent PDFs are a different table from the since-1994 district
# history.  They expose vendor, holding company, mortgagee, financier and (for
# issued consents) issue/effective dates in separate columns.  Keep this
# contract separate so the generic district parser cannot silently shift those
# fields into the wrong semantic columns.
LANDSD_MONTHLY_CONSENT_COLUMNS = [
    "lot_no_raw",
    "address_raw",
    "development_name_raw",
    "vendor_raw",
    "holding_company_raw",
    "solicitors_raw",
    "authorized_person_raw",
    "building_contractor_raw",
    "mortgagee_raw",
    "undertaking_bank_raw",
    "financier_raw",
    "issue_date",
    "consent_effective_date",
    "estimated_completion_date",
    "residential_units",
    "remarks_raw",
    "monthly_status",
    "document_as_of_date",
    "document_url",
    "page_number",
    "extraction_method",
    "parser_confidence",
]
LANDSD_MONTHLY_CONSENT_FETCH_COLUMNS = LANDSD_MONTHLY_CONSENT_COLUMNS + ["fetched_at", "raw_snapshot", "source_sha256"]


def _compact(value: str | None) -> str | None:
    if value is None:
        return None
    compact = re.sub(r"\s+", " ", value).strip()
    return compact or None


def _iso_dayfirst(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4})\b", value)
    if not match:
        return None
    try:
        raw = match.group(1)
        separator = "/" if "/" in raw else "-"
        return datetime.strptime(raw, f"%d{separator}%m{separator}%Y").date().isoformat()
    except ValueError:
        return None


def is_tpb_application_detail_url(url: str) -> bool:
    """Return whether ``url`` is a TPB application detail page, not navigation.

    TPB detail routes encode an application number as ``A_H6_97.html`` or
    ``Y_TM-LTYY_12.html``.  Attachment-index pages append ``_ac`` and the
    listing's ``Back`` link targets ``application_comment*.html``; neither is
    an application detail record.
    """
    path = urlparse(url).path
    return bool(re.search(r"/(?:[A-Z])_[A-Z0-9-]+_\d+\.html$", path, re.IGNORECASE))


def extract_tpb_application_detail_urls(html: str, source_url: str) -> list[str]:
    """Extract and de-duplicate TPB detail URLs from an applications listing."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        detail_url = urljoin(source_url, str(anchor["href"]).strip())
        if not is_tpb_application_detail_url(detail_url) or detail_url in seen:
            continue
        seen.add(detail_url)
        urls.append(detail_url)
    return urls


def _tpb_label_values(soup: BeautifulSoup) -> dict[str, str]:
    values: dict[str, str] = {}
    for label in soup.select("p.title"):
        key = _compact(label.get_text(" ", strip=True))
        if not key:
            continue
        value_tag = label.find_next_sibling("p")
        value = _compact(value_tag.get_text(" ", strip=True)) if value_tag else None
        if value:
            values[key] = value
    return values


def _tpb_value(values: Mapping[str, str], prefix: str) -> str | None:
    for label, value in values.items():
        if label.casefold().startswith(prefix.casefold()):
            return value
    return None


def _tpb_application_type(soup: BeautifulSoup) -> str | None:
    text = soup.get_text(" ", strip=True)
    match = re.search(r"\bSection\s+(12A|16|17)\s+(?:Application|Review)\b", text, re.IGNORECASE)
    return f"Section {match.group(1)}" if match else None


def _tpb_further_information(soup: BeautifulSoup) -> list[dict[str, str | None]]:
    records: list[dict[str, str | None]] = []
    for table in soup.select("table"):
        table_text = _compact(table.get_text(" ", strip=True)) or ""
        if "Further Information Received on" not in table_text:
            continue
        fields = {
            _compact(cell.get_text(" ", strip=True)) or "": _compact(cell.find_next_sibling("td").get_text(" ", strip=True))
            for cell in table.select("th")
            if cell.find_next_sibling("td")
        }
        received_raw = next((value for key, value in fields.items() if key.startswith("Further Information Received on")), None)
        records.append(
            {
                "received_date": _iso_dayfirst(received_raw),
                "received_date_raw": received_raw,
                "nature_raw": fields.get("Nature"),
                "decision_raw": fields.get("Decision"),
            }
        )
    return records


def parse_tpb_application_detail_html(html: str, detail_url: str) -> pd.DataFrame:
    """Parse one official TPB application detail HTML page into one evidence row."""
    if not is_tpb_application_detail_url(detail_url):
        return pd.DataFrame(columns=TPB_APPLICATION_COLUMNS)
    soup = BeautifulSoup(html, "html.parser")
    values = _tpb_label_values(soup)
    received_raw = _tpb_value(values, "Date of Application Received")
    tentative_raw = _tpb_value(values, "Tentative Date of Meeting")
    inspection_raw = _tpb_value(values, "Application Available for Public Inspection Until")
    comment_raw = _tpb_value(values, "Expiry Date for Making Comment")
    comment_match = re.search(r"\((\d+)\)", comment_raw or "")
    record = {
        "application_no": _tpb_value(values, "Application No."),
        "application_type": _tpb_application_type(soup),
        "plan_area": _tpb_value(values, "Plan Area"),
        "district": _tpb_value(values, "District"),
        "application_received_date": _iso_dayfirst(received_raw),
        "application_received_date_raw": received_raw,
        "location_raw": _tpb_value(values, "Location"),
        "proposal_raw": _tpb_value(values, "Proposal"),
        "tentative_meeting_date": _iso_dayfirst(tentative_raw),
        "tentative_meeting_date_raw": tentative_raw,
        "public_inspection_until_date": _iso_dayfirst(inspection_raw),
        "public_inspection_until_date_raw": inspection_raw,
        "comment_expiry_date": _iso_dayfirst(comment_raw),
        "comment_expiry_date_raw": comment_raw,
        "comment_count": int(comment_match.group(1)) if comment_match else None,
        "remark": _tpb_value(values, "Remark"),
        "further_information_json": json.dumps(_tpb_further_information(soup), ensure_ascii=False),
        "detail_url": detail_url,
        "evidence_status": "application_detail",
    }
    return pd.DataFrame([record], columns=TPB_APPLICATION_COLUMNS)


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(response, "content", b"")
    if isinstance(content, str):
        return content
    return bytes(content).decode("utf-8", errors="replace")


def _frame_lineage(
    frame: pd.DataFrame,
    *,
    raw_snapshots: list[str],
    source_urls: list[str],
    skipped_documents: list[dict[str, str]],
    fetch_kind: str,
) -> pd.DataFrame:
    frame.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        skipped_documents=skipped_documents,
        lineage_metadata={
            "lineage_type": fetch_kind,
            "fetched_documents": len(source_urls),
            "parsed_rows": int(len(frame)),
            "skipped_documents": len(skipped_documents),
        },
    )
    return frame


def fetch_tpb_application_details(
    detail_urls: Iterable[str],
    *,
    session: requests.Session | None = None,
    max_records: int = 10,
    timeout: float = 60,
) -> pd.DataFrame:
    """Fetch a bounded set of official TPB application detail pages.

    This helper is intentionally not wired into ``run-shkp-catalog``: the
    existing catalog remains a discovery snapshot, while callers can opt into
    a small, auditable expansion with an explicit cap.
    """
    if max_records < 0:
        raise ValueError("max_records must be non-negative")
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "text/html, */*"})
    frames: list[pd.DataFrame] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for detail_url in detail_urls:
        if len(source_urls) >= max_records:
            break
        if detail_url in seen:
            continue
        seen.add(detail_url)
        if not is_tpb_application_detail_url(detail_url):
            skipped.append({"document_url": detail_url, "reason": "not_tpb_application_detail_url"})
            continue
        response = client.get(detail_url, timeout=timeout)
        response.raise_for_status()
        content = getattr(response, "content", _response_text(response).encode("utf-8"))
        if isinstance(content, str):
            content = content.encode("utf-8")
        raw_snapshot = save_raw_snapshot(
            "tpb_application_detail",
            content,
            file_ext="html",
            source_url=detail_url,
        )
        raw_snapshots.append(str(raw_snapshot))
        source_urls.append(detail_url)
        parsed = parse_tpb_application_detail_html(_response_text(response), detail_url)
        if parsed.empty:
            skipped.append({"document_url": detail_url, "reason": "no_parseable_application_detail"})
            continue
        parsed["fetched_at"] = datetime.now(timezone.utc).isoformat()
        parsed["raw_snapshot"] = str(raw_snapshot)
        parsed["source_sha256"] = hashlib.sha256(bytes(content)).hexdigest()
        frames.append(parsed.reindex(columns=TPB_FETCH_COLUMNS))
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=TPB_FETCH_COLUMNS)
    return _frame_lineage(
        result,
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        skipped_documents=skipped,
        fetch_kind="official_tpb_application_detail_fetch",
    )


def _words_to_text(words: Iterable[Mapping[str, Any]]) -> str:
    return _compact(" ".join(str(word.get("text", "")) for word in words)) or ""


def _landsd_as_of_date(page_text: str) -> str | None:
    # Monthly PDFs append a footnote marker directly to the year
    # (``31/01/20261``), so a trailing word boundary would reject the valid
    # date.  Capture the date itself and let the source footnote remain out of
    # the normalized value.
    match = re.search(r"\bAs\s+at\s+(\d{1,2}/\d{1,2}/\d{4})", page_text, re.IGNORECASE)
    return _iso_dayfirst(match.group(1)) if match else None


def _landsd_monthly_document_as_of_date(page_text: str) -> str | None:
    """Return the end date printed in a monthly LandsD consent heading."""
    as_at = _landsd_as_of_date(page_text)
    if as_at:
        return as_at
    period = re.search(
        r"period\s+from\s+\d{1,2}[/-]\d{1,2}[/-]\d{4}\s+to\s+(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
        page_text,
        re.IGNORECASE,
    )
    return _iso_dayfirst(period.group(1)) if period else None


def _monthly_row_groups(
    words: list[Mapping[str, Any]],
    *,
    issued: bool,
) -> list[tuple[float, float, list[Mapping[str, Any]]]]:
    """Group monthly-table words into one row band per development."""
    # Pending/issued monthly layouts both place completion dates near the right
    # edge.  Issued rows contain three dates (a/b/c) separated by ~20 points;
    # pending rows contain one estimated-completion date.  A gap of 45 points
    # separates adjacent development rows in the observed official layouts.
    date_words = [
        word for word in words
        if 630 <= float(word.get("x0", 0)) <= 735 and _iso_dayfirst(str(word.get("text")))
    ]
    if not date_words:
        return []
    tops = sorted(float(word["top"]) for word in date_words)
    starts: list[float] = []
    for top in tops:
        if not starts or top - starts[-1] > (45 if issued else 35):
            starts.append(top)
    groups: list[tuple[float, float, list[Mapping[str, Any]]]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else float("inf")
        row_words = [
            word for word in words
            if start - 0.5 <= float(word.get("top", -1)) < end - 0.5
        ]
        groups.append((start, end, row_words))
    return groups


def parse_landsd_monthly_consent_page_words(
    words: Iterable[Mapping[str, Any]],
    *,
    document_url: str,
    page_number: int,
    document_as_of_date: str | None = None,
    monthly_status: str = "issued",
) -> pd.DataFrame:
    """Parse one monthly LandsD consent table without shifting vendor fields.

    ``monthly_status`` is ``issued`` for ``t1_YYMM.pdf`` and
    ``pending_approval`` for ``t2_YYMM.pdf``.  The parser keeps the source's
    vendor/holding labels verbatim; it does not infer SHKP ownership.
    """
    materialized = [word for word in words if word.get("text")]
    if not materialized:
        return pd.DataFrame(columns=LANDSD_MONTHLY_CONSENT_COLUMNS)
    issued = monthly_status == "issued"
    # Header positions differ by a few points between the two monthly table
    # families.  These boundaries are taken from the printed column anchors.
    bounds = (
        [0, 71, 127, 184, 241, 298, 354, 418, 473, 524, 579, 634, 698, 747, 792, 10_000]
        if issued
        else [0, 76, 138, 199, 261, 329, 384, 457, 514, 564, 620, 677, 734, 783, 10_000]
    )
    field_names = [
        "lot_no_raw", "address_raw", "development_name_raw", "vendor_raw",
        "holding_company_raw", "solicitors_raw", "authorized_person_raw",
        "building_contractor_raw", "mortgagee_raw", "undertaking_bank_raw",
        "financier_raw", "dates", "residential_units", "remarks_raw",
    ]
    records: list[dict[str, Any]] = []
    for start, _, row_words in _monthly_row_groups(materialized, issued=issued):
        columns: dict[str, list[Mapping[str, Any]]] = {name: [] for name in field_names}
        for word in row_words:
            x0 = float(word.get("x0", 0))
            for index, name in enumerate(field_names):
                if bounds[index] <= x0 < bounds[index + 1]:
                    columns[name].append(word)
                    break
        dates = sorted(
            (word for word in columns["dates"] if _iso_dayfirst(str(word.get("text")))),
            key=lambda word: float(word.get("top", 0)),
        )
        if not dates:
            continue
        date_values = [_iso_dayfirst(str(word.get("text"))) for word in dates]
        date_values = [value for value in date_values if value]
        units_text = _words_to_text(columns["residential_units"])
        units_match = re.search(r"\d[\d,]*", units_text)
        records.append(
            {
                "lot_no_raw": _words_to_text(columns["lot_no_raw"]) or None,
                "address_raw": _words_to_text(columns["address_raw"]) or None,
                "development_name_raw": _words_to_text(columns["development_name_raw"]) or None,
                "vendor_raw": _words_to_text(columns["vendor_raw"]) or None,
                "holding_company_raw": _words_to_text(columns["holding_company_raw"]) or None,
                "solicitors_raw": _words_to_text(columns["solicitors_raw"]) or None,
                "authorized_person_raw": _words_to_text(columns["authorized_person_raw"]) or None,
                "building_contractor_raw": _words_to_text(columns["building_contractor_raw"]) or None,
                "mortgagee_raw": _words_to_text(columns["mortgagee_raw"]) or None,
                "undertaking_bank_raw": _words_to_text(columns["undertaking_bank_raw"]) or None,
                "financier_raw": _words_to_text(columns["financier_raw"]) or None,
                "issue_date": date_values[0] if issued and date_values else None,
                "consent_effective_date": date_values[1] if issued and len(date_values) > 1 else None,
                "estimated_completion_date": date_values[2] if issued and len(date_values) > 2 else (date_values[0] if not issued else None),
                "residential_units": int(units_match.group(0).replace(",", "")) if units_match else None,
                "remarks_raw": _words_to_text(columns["remarks_raw"]) or None,
                "monthly_status": monthly_status,
                "document_as_of_date": document_as_of_date,
                "document_url": document_url,
                "page_number": page_number,
                "extraction_method": "pdfplumber_words_monthly_fixed_columns",
                "parser_confidence": "high",
            }
        )
    return pd.DataFrame(records, columns=LANDSD_MONTHLY_CONSENT_COLUMNS)


def parse_landsd_monthly_consent_pdf(
    pdf_bytes: bytes,
    *,
    document_url: str,
) -> pd.DataFrame:
    """Parse a monthly LandsD ``t1``/``t2`` consent PDF into source facts."""
    rows: list[pd.DataFrame] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            lowered = page_text.casefold()
            monthly_status = "pending_approval" if "pending approval" in lowered else "issued"
            rows.append(
                parse_landsd_monthly_consent_page_words(
                    page.extract_words(use_text_flow=True, keep_blank_chars=False),
                    document_url=document_url,
                    page_number=page_number,
                    document_as_of_date=_landsd_monthly_document_as_of_date(page_text),
                    monthly_status=monthly_status,
                )
            )
    nonempty = [frame for frame in rows if not frame.empty]
    result = pd.concat(nonempty, ignore_index=True) if nonempty else pd.DataFrame(columns=LANDSD_MONTHLY_CONSENT_COLUMNS)
    if not result.empty:
        result.attrs["source_sha256"] = hashlib.sha256(pdf_bytes).hexdigest()
    result.attrs["parser_scope"] = "text_native_landsd_monthly_consent_table_only"
    return result


def fetch_landsd_monthly_consent_facts(
    document_urls: Iterable[str],
    *,
    lot_patterns: Iterable[str] | None = None,
    session: requests.Session | None = None,
    max_documents: int = 12,
    timeout: float = 60,
) -> pd.DataFrame:
    """Fetch monthly LandsD consent tables and optionally keep target lots.

    ``lot_patterns`` is a review filter only (for example ``1071`` or
    ``TWTL 160``); it never converts a vendor/holding label into SHKP
    ownership.  Each monthly PDF remains a separate raw parent in lineage.
    """
    if max_documents < 0:
        raise ValueError("max_documents must be non-negative")
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "application/pdf,*/*"})
    patterns = [str(value).casefold().replace(" ", "") for value in (lot_patterns or []) if str(value).strip()]
    frames: list[pd.DataFrame] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for document_url in document_urls:
        if len(source_urls) >= max_documents:
            break
        document_url = str(document_url).strip()
        if not document_url or document_url in seen:
            continue
        seen.add(document_url)
        if "/consent/monthly/" not in document_url.casefold() or not document_url.casefold().endswith(".pdf"):
            skipped.append({"document_url": document_url, "reason": "not_monthly_consent_pdf"})
            continue
        response = client.get(document_url, timeout=timeout)
        response.raise_for_status()
        content = getattr(response, "content", b"")
        if isinstance(content, str):
            content = content.encode("utf-8")
        raw_snapshot = save_raw_snapshot(
            "landsd_monthly_consent_pdf",
            content,
            file_ext="pdf",
            source_url=document_url,
        )
        raw_snapshots.append(str(raw_snapshot))
        source_urls.append(document_url)
        parsed = parse_landsd_monthly_consent_pdf(bytes(content), document_url=document_url)
        if parsed.empty:
            skipped.append({"document_url": document_url, "reason": "image_only_or_unparseable_pdf"})
            continue
        if patterns:
            normalized_lots = parsed["lot_no_raw"].astype("string").str.casefold().str.replace(" ", "", regex=False)
            mask = normalized_lots.apply(lambda value: any(pattern in str(value) for pattern in patterns))
            parsed = parsed.loc[mask].copy()
        if parsed.empty:
            skipped.append({"document_url": document_url, "reason": "no_requested_lot_match"})
            continue
        parsed["fetched_at"] = datetime.now(timezone.utc).isoformat()
        parsed["raw_snapshot"] = str(raw_snapshot)
        parsed["source_sha256"] = hashlib.sha256(bytes(content)).hexdigest()
        frames.append(parsed.reindex(columns=LANDSD_MONTHLY_CONSENT_FETCH_COLUMNS))
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=LANDSD_MONTHLY_CONSENT_FETCH_COLUMNS)
    if not result.empty:
        result = result.drop_duplicates(
            subset=["lot_no_raw", "document_url", "page_number", "monthly_status", "estimated_completion_date"]
        ).reset_index(drop=True)
    return _frame_lineage(
        result,
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        skipped_documents=skipped,
        fetch_kind="official_landsd_monthly_consent_fetch",
    )


def parse_landsd_consent_page_words(
    words: Iterable[Mapping[str, Any]],
    *,
    district: str | None,
    document_url: str,
    page_number: int,
    document_as_of_date: str | None = None,
) -> pd.DataFrame:
    """Parse one text-native LandsD consent table page using its stable columns.

    The published table labels the third column ``Parent Co. or Holding
    Co./Developer``.  Its content is retained as one raw field, rather than
    split into an inferred owner and vendor/developer.
    """
    materialized = [word for word in words if word.get("text")]
    # District PDFs use slightly different page layouts: the consent-date
    # column appears around x=512–523.  Header as-of dates sit around
    # x=410–475, so x>=500 accepts the observed date-column variants without
    # treating the title date as a consent row.
    date_words = [
        word for word in materialized
        if float(word.get("x0", 0)) >= 500 and _iso_dayfirst(str(word.get("text")))
    ]
    if not date_words:
        return pd.DataFrame(columns=LANDSD_CONSENT_COLUMNS)
    starts = sorted(float(word["top"]) for word in date_words)
    records: list[dict[str, Any]] = []
    for index, top in enumerate(starts):
        next_top = starts[index + 1] if index + 1 < len(starts) else float("inf")
        row_words = [
            word for word in materialized
            if top - 0.5 <= float(word.get("top", -1)) < next_top - 0.5
        ]
        date_word = next((word for word in row_words if float(word.get("x0", 0)) >= 500 and _iso_dayfirst(str(word.get("text")))), None)
        if not date_word:
            continue
        columns = {
            # Across the official district layouts the observed starts are
            # approximately 30 / 135 / 221 / 325 / 429 / 512.  Leave a
            # small margin at each boundary: otherwise a word beginning at
            # x=134.8 (TPTL) or x=221.4 (the entity label) shifts into the
            # preceding column and corrupts the lot/project fields.
            "development": [word for word in row_words if float(word.get("x0", 0)) < 130],
            "lot": [word for word in row_words if 130 <= float(word.get("x0", 0)) < 220],
            "entity": [word for word in row_words if 220 <= float(word.get("x0", 0)) < 325],
            "consent": [word for word in row_words if 325 <= float(word.get("x0", 0)) < 425],
            "solicitors": [word for word in row_words if 425 <= float(word.get("x0", 0)) < 500],
        }
        development = re.sub(r"^\d+\s+", "", _words_to_text(columns["development"]))
        records.append(
            {
                "development_name_raw": development or None,
                "lot_no_raw": _words_to_text(columns["lot"]) or None,
                "parent_or_holding_company_or_developer_raw": _words_to_text(columns["entity"]) or None,
                "consent_type_raw": _words_to_text(columns["consent"]) or None,
                "solicitors_raw": _words_to_text(columns["solicitors"]) or None,
                "consent_or_approval_date": _iso_dayfirst(str(date_word.get("text"))),
                "consent_or_approval_date_raw": str(date_word.get("text")),
                "district": district,
                "document_as_of_date": document_as_of_date,
                "document_url": document_url,
                "page_number": page_number,
                "extraction_method": "pdfplumber_words_fixed_columns",
                "parser_confidence": "medium",
            }
        )
    return pd.DataFrame(records, columns=LANDSD_CONSENT_COLUMNS)


def parse_landsd_consent_pdf(
    pdf_bytes: bytes,
    *,
    district: str | None,
    document_url: str,
) -> pd.DataFrame:
    """Parse a text-native official LandsD consent/deed PDF into raw evidence rows.

    Image-only or materially redesigned PDFs produce an empty frame rather than
    fabricated values.  Callers should archive the original bytes and hash as
    part of their source-document lineage before using this helper.
    """
    rows: list[pd.DataFrame] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
            page_text = page.extract_text() or ""
            rows.append(
                parse_landsd_consent_page_words(
                    words,
                    district=district,
                    document_url=document_url,
                    page_number=page_number,
                    document_as_of_date=_landsd_as_of_date(page_text),
                )
            )
    nonempty = [frame for frame in rows if not frame.empty]
    if not nonempty:
        return pd.DataFrame(columns=LANDSD_CONSENT_COLUMNS)
    result = pd.concat(nonempty, ignore_index=True)
    result.attrs["source_sha256"] = hashlib.sha256(pdf_bytes).hexdigest()
    result.attrs["parser_scope"] = "text_native_landsd_consent_table_only"
    return result


def _landsd_district_from_url(document_url: str) -> str | None:
    """Best-effort district label from LandsD's district PDF filenames."""
    filename = unquote(urlparse(document_url).path.rsplit("/", 1)[-1])
    label = re.sub(r"\[from\s*\d{4}\].*$", "", filename, flags=re.IGNORECASE)
    label = re.sub(r"\(pre\s*\d{4}\).*$", "", label, flags=re.IGNORECASE)
    label = re.sub(r"wac_e\.pdf$|\.pdf$", "", label, flags=re.IGNORECASE)
    return _compact(label.replace("_", " "))


def fetch_landsd_consent_facts(
    document_urls: Iterable[str],
    *,
    session: requests.Session | None = None,
    max_documents: int = 5,
    timeout: float = 60,
) -> pd.DataFrame:
    """Fetch a bounded set of text-native LandsD consent/deed PDFs.

    Every downloaded PDF is archived.  PDFs with no recoverable table rows
    are deliberately omitted from facts and reported in ``skipped_documents``
    as ``image_only_or_unparseable_pdf`` rather than being represented by
    invented values.
    """
    if max_documents < 0:
        raise ValueError("max_documents must be non-negative")
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "application/pdf,*/*"})
    frames: list[pd.DataFrame] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for document_url in document_urls:
        if len(source_urls) >= max_documents:
            break
        if document_url in seen:
            continue
        seen.add(document_url)
        if not urlparse(document_url).path.lower().endswith(".pdf"):
            skipped.append({"document_url": document_url, "reason": "not_pdf"})
            continue
        response = client.get(document_url, timeout=timeout)
        response.raise_for_status()
        content = getattr(response, "content", b"")
        if isinstance(content, str):
            content = content.encode("utf-8")
        raw_snapshot = save_raw_snapshot(
            "landsd_consent_pdf",
            content,
            file_ext="pdf",
            source_url=document_url,
        )
        raw_snapshots.append(str(raw_snapshot))
        source_urls.append(document_url)
        parsed = parse_landsd_consent_pdf(
            bytes(content),
            district=_landsd_district_from_url(document_url),
            document_url=document_url,
        )
        if parsed.empty:
            skipped.append({"document_url": document_url, "reason": "image_only_or_unparseable_pdf"})
            continue
        # The district is source-document metadata determined at this fetch
        # boundary.  Stamp it here as well as in the parser so partial parser
        # output cannot lose that lineage field.
        parsed["district"] = _landsd_district_from_url(document_url)
        parsed["fetched_at"] = datetime.now(timezone.utc).isoformat()
        parsed["raw_snapshot"] = str(raw_snapshot)
        parsed["source_sha256"] = hashlib.sha256(bytes(content)).hexdigest()
        frames.append(parsed.reindex(columns=LANDSD_CONSENT_FETCH_COLUMNS))
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=LANDSD_CONSENT_FETCH_COLUMNS)
    return _frame_lineage(
        result,
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        skipped_documents=skipped,
        fetch_kind="official_landsd_consent_pdf_fetch",
    )
