"""Bounded numeric fact extraction from official SHKP Quarterly PDFs.

The issuer's Quarterly page is an article/PDF catalogue rather than a
structured operating-data feed.  This module therefore extracts only explicit
numbers that appear beside an interpretable unit (units, square feet, HKD,
percent, stores, lease years or completion year), and keeps the source sentence
and page number with every row.  It is an event-context layer, not a revenue or
ownership model.
"""

from __future__ import annotations

import hashlib
import re
from io import BytesIO
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot


SHKP_QUARTERLY_FACT_COLUMNS = [
    "fact_id",
    "event_id",
    "quarter_label",
    "quarter_end",
    "event_date",
    "event_type",
    "asset_class",
    "geography",
    "project_label",
    "title",
    "fact_type",
    "value",
    "unit",
    "currency",
    "reporting_period_start",
    "reporting_period_end",
    "reporting_period_type",
    "sales_scope",
    "page_number",
    "fact_text",
    "source_url",
    "source_page_url",
    "extraction_method",
    "confidence",
    "coverage_status",
    "model_use",
    "research_only",
    "caveat",
]


def _stable_key(*parts: Any) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _number(raw: str, scale: float = 1.0) -> float | None:
    compact = re.sub(r"[^0-9.]", "", str(raw).replace(",", ""))
    if not compact:
        return None
    try:
        return float(compact) * scale
    except ValueError:
        return None


def _sentence_texts(text: str) -> Iterable[str]:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return []
    # PDF text frequently has no reliable punctuation around bilingual
    # columns; retaining line-sized chunks is more useful than aggressive
    # sentence tokenisation for the evidence excerpt.
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\s{2,}", cleaned) if part.strip()]


def _append_fact(
    rows: list[dict[str, Any]],
    *,
    event: dict[str, Any],
    source_page_url: Any,
    source_url: str,
    page_number: int,
    fact_type: str,
    value: float,
    unit: str,
    sentence: str,
    confidence: str = "high",
    currency: str | None = None,
    model_use: str = "commercial_event_context_only",
    caveat: str | None = None,
    sales_scope: str | None = None,
) -> None:
    period_start, period_end, period_type = _infer_reporting_interval(event, sentence)
    rows.append(
        {
            "fact_id": _stable_key(event.get("event_id"), fact_type, value, unit, sentence),
            "event_id": event.get("event_id"),
            "quarter_label": event.get("quarter_label"),
            "quarter_end": event.get("quarter_end"),
            "event_date": event.get("event_date"),
            "event_type": event.get("event_type"),
            "asset_class": event.get("asset_class"),
            "geography": event.get("geography"),
            "project_label": event.get("project_label"),
            "title": event.get("title"),
            "fact_type": fact_type,
            "value": float(value),
            "unit": unit,
            "currency": currency,
            "reporting_period_start": period_start,
            "reporting_period_end": period_end,
            "reporting_period_type": period_type,
            "sales_scope": sales_scope,
            "page_number": int(page_number),
            "fact_text": sentence[:700],
            "source_url": source_url,
            "source_page_url": source_page_url,
            "extraction_method": "pdf_text_regex_sentence",
            "confidence": confidence,
            "coverage_status": "bounded_official_pdf_numeric_fact",
            "model_use": model_use,
            "research_only": True,
            "caveat": caveat or "Explicit number from issuer Quarterly PDF text; not recognized revenue, rent, NOI or legal ownership.",
        }
    )


def _infer_reporting_interval(event: dict[str, Any], text: str) -> tuple[str | None, str | None, str]:
    """Infer the issuer reporting interval without treating publication quarter as it."""
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    title = str(event.get("title") or "")
    combined = f"{title} {cleaned}"
    for pattern, period_type in (
        (r"(?:six|6)\s+months?\s+ended\s+(?P<date>\d{1,2}\s+[A-Za-z]+\s+20\d{2})", "interim"),
        (r"year\s+ended\s+(?P<date>\d{1,2}\s+[A-Za-z]+\s+20\d{2})", "annual"),
    ):
        match = re.search(pattern, combined, flags=re.IGNORECASE)
        if match:
            end = pd.to_datetime(match.group("date"), errors="coerce")
            if pd.notna(end):
                end = pd.Timestamp(end).normalize()
                months = 6 if period_type == "interim" else 12
                start = end - pd.DateOffset(months=months) + pd.Timedelta(days=1)
                return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), period_type

    # Some Quarterly PDFs omit the date in the extracted sentence but retain
    # the fiscal-year label in the article title (for example 2024/25 interim
    # results). Keep this fallback explicit and separate from a true date.
    fiscal = re.search(r"(?P<start>20\d{2})\s*/\s*(?P<end>\d{2})", title)
    if fiscal and re.search(r"interim|six\s+months", title, flags=re.IGNORECASE):
        year = int(fiscal.group("start"))
        end = pd.Timestamp(year=year, month=12, day=31)
        return f"{year}-07-01", end.strftime("%Y-%m-%d"), "interim_title_inferred"
    if fiscal and re.search(r"annual\s+results|year\s+results", title, flags=re.IGNORECASE):
        year = int(fiscal.group("start")) + 1
        end = pd.Timestamp(year=year, month=6, day=30)
        return f"{year - 1}-07-01", end.strftime("%Y-%m-%d"), "annual_title_inferred"
    return None, None, "unknown"


def _extract_quarterly_facts_from_text(
    text: str,
    *,
    event: dict[str, Any],
    source_url: str,
    source_page_url: Any,
    page_number: int,
) -> list[dict[str, Any]]:
    """Extract explicit unit/area/percent/lease/year facts from one PDF page."""
    rows: list[dict[str, Any]] = []
    _extract_attributable_contract_sales(
        rows,
        text=text,
        event=event,
        source_url=source_url,
        source_page_url=source_page_url,
        page_number=page_number,
    )
    property_words = re.compile(
        r"property|development|project|residential|unit|office|mall|retail|hotel|tenant|lease|completion|opening|handover|sales|square feet|sq\.?\s*ft",
        re.IGNORECASE,
    )
    for sentence in _sentence_texts(text):
        if not property_words.search(sentence):
            continue
        # ``2.6 million square feet`` and ``37,000 square feet``.
        for match in re.finditer(
            r"(?P<num>\d[\d,\.\s]*?)\s*(?P<scale>million|mn|billion)?\s*(?:square\s+feet|sq\.?\s*ft\.?|sqft)",
            sentence,
            flags=re.IGNORECASE,
        ):
            scale_name = str(match.group("scale") or "").casefold()
            scale = 1_000_000 if scale_name in {"million", "mn"} else 1_000_000_000 if scale_name == "billion" else 1
            value = _number(match.group("num"), scale)
            # PDF page/footnote artefacts occasionally produce fragments such
            # as ``18 square feet`` or ``10.764 square feet`` immediately
            # before a real area.  A genuine Hong Kong unit/clubhouse/office
            # area in this source family is at least 100 sqft; keep smaller
            # numbers out rather than publishing obvious extraction noise.
            if value is not None and value >= 100:
                _append_fact(
                    rows,
                    event=event,
                    source_page_url=source_page_url,
                    source_url=source_url,
                    page_number=page_number,
                    fact_type="area_sqft",
                    value=value,
                    unit="sqft",
                    sentence=sentence,
                )
        for match in re.finditer(
            r"(?P<num>\d[\d,\s]*)\s*(?:residential\s+)?units?\b",
            sentence,
            flags=re.IGNORECASE,
        ):
            value = _number(match.group("num"))
            if value is not None:
                _append_fact(
                    rows,
                    event=event,
                    source_page_url=source_page_url,
                    source_url=source_url,
                    page_number=page_number,
                    fact_type="unit_count",
                    value=value,
                    unit="units",
                    sentence=sentence,
                )
        if re.search(r"turnover|occupancy|take[- ]up|leased|lease-up|sold", sentence, re.IGNORECASE):
            for match in re.finditer(r"(?P<num>\d+(?:\.\d+)?)\s*%", sentence):
                value = _number(match.group("num"))
                if value is not None:
                    _append_fact(
                        rows,
                        event=event,
                        source_page_url=source_page_url,
                        source_url=source_url,
                        page_number=page_number,
                        fact_type="property_rate_pct",
                        value=value,
                        unit="percent",
                        sentence=sentence,
                        confidence="medium",
                    )
        for match in re.finditer(r"(?P<num>\d[\d,\s]*)\s+(?:stores|shops|retailers|brands)\b", sentence, re.IGNORECASE):
            value = _number(match.group("num"))
            if value is not None:
                _append_fact(
                    rows,
                    event=event,
                    source_page_url=source_page_url,
                    source_url=source_url,
                    page_number=page_number,
                    fact_type="retail_store_count",
                    value=value,
                    unit="stores",
                    sentence=sentence,
                    confidence="medium",
                )
        for match in re.finditer(r"(?P<num>\d+(?:\.\d+)?)\s*[- ]?year\s+lease", sentence, re.IGNORECASE):
            value = _number(match.group("num"))
            if value is not None:
                _append_fact(
                    rows,
                    event=event,
                    source_page_url=source_page_url,
                    source_url=source_url,
                    page_number=page_number,
                    fact_type="lease_term_years",
                    value=value,
                    unit="years",
                    sentence=sentence,
                    confidence="medium",
                )
        for match in re.finditer(r"(?:scheduled|expected|planned)\s+(?:for\s+)?(?:completion|opening|handover)[^\d]{0,35}(?P<year>20\d{2})", sentence, re.IGNORECASE):
            value = _number(match.group("year"))
            if value is not None:
                _append_fact(
                    rows,
                    event=event,
                    source_page_url=source_page_url,
                    source_url=source_url,
                    page_number=page_number,
                    fact_type="milestone_year",
                    value=value,
                    unit="year",
                    sentence=sentence,
                    confidence="medium",
                )
        for match in re.finditer(r"HK\$\s*(?P<num>\d[\d,\.\s]*)\s*(?P<scale>million|billion)?", sentence, re.IGNORECASE):
            scale_name = str(match.group("scale") or "").casefold()
            scale = 1_000_000 if scale_name == "million" else 1_000_000_000 if scale_name == "billion" else 1
            value = _number(match.group("num"), scale)
            if value is not None:
                _append_fact(
                    rows,
                    event=event,
                    source_page_url=source_page_url,
                    source_url=source_url,
                    page_number=page_number,
                    fact_type="amount_hkd",
                    value=value,
                    unit="HKD",
                    currency="HKD",
                    sentence=sentence,
                    confidence="medium",
                )
    return rows


def _extract_attributable_contract_sales(
    rows: list[dict[str, Any]],
    *,
    text: str,
    event: dict[str, Any],
    source_url: str,
    source_page_url: Any,
    page_number: int,
) -> None:
    """Extract only sales amounts tied to explicit attributable wording.

    PDF text from bilingual columns can interleave profit and sales sentences.
    Requiring ``attributable terms`` (or the Chinese equivalent) avoids
    misclassifying nearby HK$ profit/rental figures as contracted sales.
    """
    page_text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not page_text:
        return
    caveat = (
        "Issuer-disclosed contracted sales in attributable terms; this is a sales-period anchor, "
        "not recognized revenue and not a phase-level transaction reconstruction."
    )
    english_pattern = re.compile(
        r"contracted\s+sales(?:(?!contracted\s+sales).){0,160}?"
        r"HK\$\s*(?P<num>\d[\d,\.\s]*)\s*(?P<scale>million|billion|mn|bn)"
        r"(?:(?!contracted\s+sales).){0,90}?attributable\s+terms",
        flags=re.IGNORECASE,
    )
    for match in english_pattern.finditer(page_text):
        value = _number(match.group("num"))
        if value is None:
            continue
        scale = str(match.group("scale") or "").casefold()
        value_m = value * (1000.0 if scale in {"billion", "bn"} else 1.0)
        nearby = page_text[max(0, match.start() - 30): match.end() + 80]
        scope = "hong_kong" if re.search(r"Hong\s+Kong|香港", nearby, flags=re.IGNORECASE) else "group_total_or_scope_unspecified"
        _append_fact(
            rows,
            event=event,
            source_page_url=source_page_url,
            source_url=source_url,
            page_number=page_number,
            fact_type="contracted_sales_attributable_hkd_m",
            value=value_m,
            unit="HKD_m",
            currency="HKD",
            sentence=match.group(0),
            confidence="high",
            model_use="sales_model_calibration",
            caveat=caveat,
            sales_scope=scope,
        )

    chinese_patterns = (
        re.compile(
            r"按所佔權益計算.{0,100}?合約銷售(?:總額|額)?[^0-9]{0,20}"
            r"(?P<num>\d+(?:\.\d+)?)\s*億港元",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"合約銷售(?:總額|額)?[^0-9]{0,20}(?P<num>\d+(?:\.\d+)?)\s*億港元"
            r".{0,100}?按所佔權益計算",
            flags=re.IGNORECASE,
        ),
    )
    for pattern in chinese_patterns:
        for match in pattern.finditer(page_text):
            value = _number(match.group("num"))
            if value is None:
                continue
            _append_fact(
                rows,
                event=event,
                source_page_url=source_page_url,
                source_url=source_url,
                page_number=page_number,
                fact_type="contracted_sales_attributable_hkd_m",
                value=value * 100.0,
                unit="HKD_m",
                currency="HKD",
                sentence=match.group(0),
                confidence="high",
                model_use="sales_model_calibration",
                caveat=caveat,
                sales_scope="hong_kong" if re.search(r"香港", match.group(0)) else "group_total_or_scope_unspecified",
            )


def fetch_shkp_quarterly_numeric_facts(
    corporate_documents: pd.DataFrame,
    quarterly_events: pd.DataFrame,
    *,
    max_documents: int = 24,
    timeout: float = 60,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Download a bounded HK-only Quarterly subset and extract numeric facts."""
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pdfplumber is required for SHKP Quarterly fact extraction") from exc

    events = quarterly_events.copy()
    if events.empty:
        return pd.DataFrame(columns=SHKP_QUARTERLY_FACT_COLUMNS)
    title = events.get("title", pd.Series(dtype="string")).fillna("").astype(str)
    property_events = (
        events.get("property_relevance", pd.Series(dtype="string")).eq("property")
        & events.get("geography", pd.Series(dtype="string")).eq("hong_kong")
    )
    # Results articles are indexed as generic corporate updates rather than
    # property events. Include only the issuer's own SHKP/Group results rows;
    # exclude SUNeVision/SmarTone subsidiary results from this sales anchor.
    issuer_results = title.str.contains(
        r"(?:SHKP|the group|group) announces .*results",
        case=False,
        regex=True,
    ) & ~title.str.contains(r"SUNeVision|SmarTone", case=False, regex=True)
    events = events.loc[(property_events | issuer_results) & ~title.eq("PDF")].copy()
    events = events.sort_values(["event_date", "event_id"], ascending=[False, True], na_position="last").head(max_documents)
    documents = corporate_documents.copy()
    documents = documents.loc[documents.get("document_type", pd.Series(dtype="string")).eq("quarterly_article")]
    documents = documents.drop_duplicates(subset=["document_url"])
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "application/pdf,*/*"})
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    parse_summary: list[dict[str, Any]] = []
    for event in events.to_dict("records"):
        # The event contract stores the PDF link in document_url; the generic
        # source_url field points to the Quarterly landing page.
        document_url = str(event.get("document_url") or "")
        if not document_url.lower().endswith(".pdf"):
            continue
        try:
            response = client.get(document_url, timeout=timeout)
            response.raise_for_status()
            if not response.content.lstrip().startswith(b"%PDF"):
                continue
            raw_path = save_raw_snapshot(
                "shkp_quarterly_numeric_pdf",
                response.content,
                file_ext="pdf",
                source_url=document_url,
            )
            raw_snapshots.append(str(raw_path))
            source_urls.append(document_url)
            fact_count = 0
            with pdfplumber.open(BytesIO(response.content)) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    page_rows = _extract_quarterly_facts_from_text(
                        page.extract_text() or "",
                        event=event,
                        source_url=document_url,
                        source_page_url=event.get("source_page_url"),
                        page_number=page_number,
                    )
                    rows.extend(page_rows)
                    fact_count += len(page_rows)
            parse_summary.append({"event_id": event.get("event_id"), "document_url": document_url, "fact_rows": fact_count})
        except Exception as exc:  # noqa: BLE001 - one unavailable PDF must not erase prior facts
            parse_summary.append({"event_id": event.get("event_id"), "document_url": document_url, "fact_rows": 0, "error": str(exc)})

    frame = pd.DataFrame(rows, columns=SHKP_QUARTERLY_FACT_COLUMNS)
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["event_id", "fact_type", "value", "unit"]).reset_index(drop=True)
    frame.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=list(dict.fromkeys(source_urls + ["https://www.shkp.com/en-US/investor-relations/shkp-quarterly"])),
        lineage_metadata={
            "lineage_type": "derived_shkp_quarterly_numeric_facts",
            "documents_requested": int(len(events)),
            "documents_parsed": int(sum(1 for item in parse_summary if item.get("fact_rows", 0) > 0)),
            "parse_summary": parse_summary,
            "scope": "hong_kong_property_relevant_quarterly_articles_only",
            "ownership_or_revenue_inference": False,
            "fetched_at": fetched_at,
        },
    )
    return frame
