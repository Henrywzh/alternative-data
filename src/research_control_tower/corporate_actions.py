"""Unified HKEX Next Day Disclosure / corporate-actions collection (T1).

Collector-side module only: nothing here is imported by the Streamlit app, and
the offline builder consumes only the standardized local parquet inputs this
module writes (corporate_actions_v1.parquet + state sidecar).  Values come
from the official HKEX disclosure layer, never from an aggregator.

Source
======
- HKEXnews title-search metadata (official exchange announcement feed).  The
  stock-code resolution and the non-negotiable STOCK_CODE guard follow the
  same adapter contract already proven in official_filings.
- For share-buyback Next Day Disclosure Returns (Forms FF304/FF305) the
  announcement body is downloaded and parsed for source-extractable repurchase
  fields: trading (execution) date, number of shares repurchased, method,
  highest/lowest per-share price, aggregate consideration, shares designated
  for cancellation / as treasury (FF305), and repurchase-mandate information
  (resolution date, authorised ceiling, cumulative repurchases).
- Dividend/distribution announcements are captured as title/metadata rows
  (published timestamp, action type, source URL); the per-share amount, record
  and ex dates live in announcement bodies whose parsing is deferred to a
  specialised dividend parser (T4+ backlog).  Numeric dividend fields are
  therefore null with an explicit coverage_reason, never inferred.

Issuer-agnostic: every row in the official-source identity crosswalk
(config/research_control_tower/official_source_identity.csv) with
source_kind == "hkex_code" is processed identically.  Tencent (0700.HK) is
the first collection target; the body parser accepts the current FF305 layout
("Repurchase report", verified on Tencent 2025/2026 filings) and the FF304
layout ("Purchase report", 2024 era) which share the same row structure.

Explicitly NOT captured in v1 (documented, never inferred):
- NDD Section I B "repurchased for cancellation but not yet cancelled"
  outstanding ledger: a rolling snapshot, not per-action records; completed
  cancellation is reported in subsequent Monthly Returns (out of scope).
- Director/chief-executive and other-interest NDD returns: not corporate
  actions; counted as skipped in the state sidecar.
- TCEHY_US (US OTC depositary receipt): no HKEX disclosure identity is
  registered until official depositary verification exists (gated per the
  Tencent T0-T3 design spec); the collector never fabricates one.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .build import SOURCE_STATE_COLUMNS
from .atomic_io import write_parquet_atomic
from .official_filings import load_source_identity  # reuse the shared crosswalk loader


logger = logging.getLogger(__name__)

HKEX_TIMEZONE = "Asia/Hong_Kong"
HKEXNEWS_PREFIX_URL = "https://www1.hkexnews.hk/search/prefix.do"
HKEXNEWS_TITLE_SEARCH_URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
HKEXNEWS_SEARCH_REFERER = "https://www1.hkexnews.hk/search/titlesearch.xhtml"
HKEXNEWS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": HKEXNEWS_SEARCH_REFERER,
}
HKEXNEWS_BODY_URL_PREFIX = "https://www1.hkexnews.hk"
HKEX_QUERY_INTERVAL_SECONDS = 0.4

PIT_CLASS = "snapshot_from_live_source"
LICENSE_CLASS = "official_public_metadata"
REGISTRY_VERSION = "v1"
SCHEMA_VERSION = "v1"
VERSION = 1

# Title-search queries; the servlet title parameter performs a substring
# match on announcement titles (verified against live HKEXnews for Tencent).
NDD_TITLE_QUERY = "Next Day Disclosure Return"
DIVIDEND_TITLE_QUERY = "Dividend"

# Action-type keywords applied to official HKEXnews titles only.
BUYBACK_KEYWORDS = ("SHARE BUYBACK", "SECURITIES BUYBACK", "OWN SHARES PURCHASE")
SKIP_NDD_KEYWORDS = (
    "DIRECTORS' INTERESTS",
    "DIRECTORS' DEALINGS",
    "CHIEF EXECUTIVE'S INTERESTS",
    "CHIEF EXECUTIVE'S DEALINGS",
    "OTHER INTERESTS",
)
DIVIDEND_KEYWORD = "DIVIDEND"
# Explicit negations only. A title that merely mentions a dividend is not a
# dividend declaration, and the mart must not infer one from a substring hit;
# anything outside this list is still classified on the keyword, never guessed.
NON_DIVIDEND_KEYWORDS = (
    "NO DIVIDEND",
    "NO FINAL DIVIDEND",
    "NO INTERIM DIVIDEND",
    "NOT DECLARE",
    "NOT TO DECLARE",
    "NOT RECOMMEND",
    "NOT TO RECOMMEND",
    "WITHOUT DIVIDEND",
)
DISTRIBUTION_IN_SPECIE_KEYWORD = "DISTRIBUTION IN SPECIE"

CORP_ACTIONS_COLUMNS = [
    "action_id",
    "version",
    "entity_id",
    "listing_id",
    "canonical_ticker",
    "action_type",
    "filing_date",
    "execution_date",
    "published_at",
    "shares_affected",
    "price_min",
    "price_max",
    "price_avg",
    "total_amount_paid",
    "currency",
    "shares_for_cancellation",
    "shares_for_treasury",
    "cancellation_status",
    "mandate_resolution_date",
    "mandate_authorised_shares",
    "mandate_cumulative_repurchased_shares",
    "coverage_reason",
    "source_url",
    "source_document_id",
    "document_format",
    "source_note",
    "retrieved_at_utc",
    "source_timezone",
    "date_precision",
    "source_quality",
    "pit_class",
    "source_license_class",
    "registry_version",
]

INT_COLUMNS = frozenset(
    {
        "version",
        "shares_affected",
        "shares_for_cancellation",
        "shares_for_treasury",
        "mandate_authorised_shares",
        "mandate_cumulative_repurchased_shares",
    }
)
FLOAT_COLUMNS = frozenset({"price_min", "price_max", "price_avg", "total_amount_paid"})
DATETIME_COLUMNS = frozenset({"published_at", "retrieved_at_utc"})
STRING_COLUMNS = tuple(
    column for column in CORP_ACTIONS_COLUMNS
    if column not in INT_COLUMNS and column not in FLOAT_COLUMNS and column not in DATETIME_COLUMNS
)


def _now_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _blank(value: object) -> bool:
    return value is None or value is pd.NaT or (not isinstance(value, (list, tuple, dict)) and pd.isna(value))


def _text(value: object) -> str:
    if _blank(value):
        return ""
    return str(value).strip()


def _normalize_hkex_code(code: object) -> str:
    bare = re.sub(r"\.HK$", "", _text(code), flags=re.IGNORECASE)
    return bare.lstrip("0") or "0"


def _resolve_hkex_stock_id(session: requests.Session, ticker: str, timeout: int) -> tuple[str, str] | None:
    """Resolve a bare stock code to HKEXnews internal stockId (prefix.do)."""

    bare = _normalize_hkex_code(ticker)
    padded = bare.zfill(5)
    response = session.get(
        HKEXNEWS_PREFIX_URL,
        params={"callback": "callback", "lang": "EN", "type": "A", "name": padded, "market": "SEHK"},
        headers=HKEXNEWS_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    match = re.search(r"\((\{.*})\)", response.text.strip(), flags=re.DOTALL)
    if not match:
        return None
    payload = json.loads(match.group(1))
    for suggestion in payload.get("stockInfo") or []:
        if _normalize_hkex_code(suggestion.get("code")) == bare:
            return str(suggestion.get("stockId")), bare
    return None


def _parse_hkex_datetime(value: object) -> pd.Timestamp | pd.NaT:
    """Parse HKEX title-search DATE_TIME (Asia/Hong_Kong local time)."""

    raw = _text(value)
    if not raw:
        return pd.NaT
    try:
        local = datetime.strptime(raw, "%d/%m/%Y %H:%M").replace(tzinfo=ZoneInfo(HKEX_TIMEZONE))
    except ValueError:
        return pd.NaT
    return pd.Timestamp(local).tz_convert("UTC")


def _action_id(
    listing_id: str,
    filing_date: str,
    execution_date: str,
    action_type: str,
    source_document_id: str = "",
    row_discriminator: str | int = "",
) -> str:
    """Deterministic primary key per the T1 design contract.

    Canonical key: hash of the 4-tuple plus source_document_id and
    row_discriminator, which guarantee collision-free IDs across multiple
    filings on the same day and multiple tranches/rows within one filing on
    the same execution date.  The two discriminators are always part of the
    key, blank or not: making them conditional would put the same 4-tuple in
    two different ID namespaces depending on how the caller was invoked.
    """

    parts = [
        listing_id,
        filing_date,
        execution_date,
        action_type,
        str(source_document_id),
        str(row_discriminator),
    ]
    key = "|".join(parts)
    return "ca:" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:24]


def _parse_number(value: object) -> float | None:
    raw = _text(value).replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_count(value: object) -> int | None:
    raw = _text(value).replace(",", "")
    if not raw or "." in raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


# Month lookup is explicit rather than ``%B``/``%b`` because strptime month
# names are locale-dependent: a CI container with a non-English LC_TIME would
# otherwise fail to parse every HKEX date.
_MONTH_NUMBERS = {
    name.upper(): number
    for number, names in enumerate(
        (
            ("January", "Jan"),
            ("February", "Feb"),
            ("March", "Mar"),
            ("April", "Apr"),
            ("May",),
            ("June", "Jun"),
            ("July", "Jul"),
            ("August", "Aug"),
            ("September", "Sep", "Sept"),
            ("October", "Oct"),
            ("November", "Nov"),
            ("December", "Dec"),
        ),
        start=1,
    )
    for name in names
}
_DAY_MONTH_YEAR_PATTERN = re.compile(
    r"^(\d{1,2})[\s\-/]+([A-Za-z]{3,9})\.?[\s\-/]+(\d{4})$"
)


def _parse_day_month_year(value: object) -> str | None:
    """Parse ``13 June 2025`` / ``13 Jun 2025`` / ``13-June-2025`` to ISO.

    Accepts every day-month-year spelling the row/summary regexes can capture
    (full and abbreviated month names, space or hyphen separated).  Returns
    ``None`` only when the text genuinely is not such a date.
    """

    raw = _text(value)
    if not raw:
        return None
    match = _DAY_MONTH_YEAR_PATTERN.match(raw)
    if match is None:
        return None
    month = _MONTH_NUMBERS.get(match.group(2).upper())
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1))).isoformat()
    except ValueError:
        return None


class _HtmlTextParser(HTMLParser):
    """Collects visible text nodes (tables included) into a plain-text body."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def html_to_text(payload: bytes) -> str:
    """Strip HTML/XHTML markup into whitespace-normalized plain text."""

    parser = _HtmlTextParser()
    try:
        parser.feed(payload.decode("utf-8", errors="replace"))
    except (AssertionError, ValueError) as exc:
        # HTMLParser raises on a handful of malformed constructs. Whatever it
        # managed to collect before that point is still real text, so keep it
        # and record why the rest is missing instead of silently returning "".
        logger.warning("HTML body parse stopped early (%s); using partial text", exc)
    return "\n\n".join(part.strip() for part in parser.parts if part.strip())


def extract_pdf_text(payload: bytes) -> str:
    """Extract text from an HKEX NDD PDF via pdfplumber (footers preserved)."""

    import pdfplumber

    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n\n".join(pages)


def extract_document_text(payload: bytes, format_hint: str = "") -> str:
    """Route a downloaded announcement body to its text extractor.

    format_hint is the HKEX title-search FILE_TYPE (PDF/HTM); bytes sniffing
    is used when the hint is missing.
    """

    hint = _text(format_hint).upper()
    if hint == "PDF" or payload[:5] == b"%PDF-":
        return extract_pdf_text(payload)
    if hint == "HTM" or payload.lstrip()[:1] == b"<":
        return html_to_text(payload)
    return ""


def classify_action_type(*, title: str, long_text: str = "", short_text: str = "") -> tuple[str | None, str | None]:
    """Map an official HKEXnews title to a corporate-action type.

    Returns (action_type, note); action_type None means the row is
    deliberately skipped (not a corporate action of the T1 mart, or the NDD
    variant is unrecognizable and must not be guessed).  Note carries the
    classification rationale and is used for honest provenance.
    """

    title_upper = _text(title).upper()
    context_upper = " ".join(_text(part).upper() for part in (title, long_text, short_text))
    if NDD_TITLE_QUERY.upper() in title_upper:
        if any(keyword in context_upper for keyword in SKIP_NDD_KEYWORDS):
            return None, "NDD for directors'/chief executive's or other interests; not a corporate action"
        if any(keyword in context_upper for keyword in BUYBACK_KEYWORDS):
            return "buyback_execution", "HKEX Next Day Disclosure Return (share buyback)"
        return (
            None,
            "NDD title without recognizable buyback or interests classification; "
            "skipped to avoid misclassification",
        )
    if DISTRIBUTION_IN_SPECIE_KEYWORD in context_upper:
        return "distribution_in_specie", "HKEX announcement title carries distribution-in-specie"
    if DIVIDEND_KEYWORD in context_upper:
        negation = next(
            (keyword for keyword in NON_DIVIDEND_KEYWORDS if keyword in context_upper),
            None,
        )
        if negation is not None:
            return (
                None,
                f"announcement mentions a dividend but carries the explicit negation {negation!r}; "
                "skipped to avoid recording a declaration that was not made",
            )
        return "cash_dividend", "HKEX announcement title carries dividend"
    return None, "announcement title outside the corporate-action families tracked by the T1 mart"


@dataclass
class ParsedNdd:
    """Structured result of parsing one Next Day Disclosure Return body."""

    form: str = ""
    issuer_name: str = ""
    date_submitted: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    aggregate_price_paid: float | None = None
    shares_for_cancellation: int | None = None
    shares_for_treasury: int | None = None
    mandate_resolution_date: str | None = None
    mandate_authorised_shares: int | None = None
    mandate_cumulative_shares: int | None = None
    coverage_reason: str = ""
    parse_errors: list[str] = field(default_factory=list)


_ROW_PATTERN = re.compile(
    r"(\d+)\)\.?\s*"
    r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s*"
    r"([\d,]+(?:\.[\d]+)?)\s*"
    r"(On the Exchange|another stock exchange(?:\s*\([^)]*\))?|by private arrangement|by general offer)"
    r"\s*HKD\s*([\d.,]+)\s*HKD\s*([\d.,]+)\s*HKD\s*([\d.,]+)"
)
_DATE_SUBMITTED_PATTERN = re.compile(r"Date Submitted:\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})")
_ISSUER_PATTERN = re.compile(r"Name of Issuer:\s*(.+?)(?:\n|$)")
_FORM_PATTERN = re.compile(r"\bFF30[45]\b")
_RESOLUTION_DATE_PATTERN = re.compile(
    r"Date of the resolution granting the repurchase mandate\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})"
)
_AUTHORISED_PATTERN = re.compile(
    r"Total number of shares which the issuer is authorised to repurchase under the repurchase mandate\s*([\d,]+)"
)
_CUMULATIVE_FF305_PATTERN = re.compile(
    r"Number of shares repurchased on the Exchange or another stock exchange under the repurchase mandate \(a\)\s*([\d,]+)"
)
_CUMULATIVE_FF304_PATTERN = re.compile(
    r"Number of such securities purchased on the Exchange in the year to date \(since ordinary resolution\) \(a\)\s*([\d,]+)"
)
_AGGREGATE_FF305_PATTERN = re.compile(r"Aggregate price paid\s*\$?\s*HKD\s*([\d.,]+)")
_AGGREGATE_FF304_PATTERN = re.compile(r"Total paid\s*\$?\s*HKD\s*([\d.,]+)")
_FOR_CANCELLATION_PATTERN = re.compile(
    r"Number of shares (?:repurchased|purchased) for\s*([\d,]+)\s*cancellation"
)
_FOR_TREASURY_PATTERN = re.compile(
    r"Number of shares (?:repurchased|purchased) for holding\s*([\d,]+)\s*as treasury shares"
)


def parse_next_day_disclosure(text: str) -> ParsedNdd:
    """Parse a FF304/FF305 Next Day Disclosure Return body into structured rows.

    Text-based and tolerant of pdfplumber/pypdf cell-join artifacts (e.g.
    982,000On the Exchange HKD 515HKD 506.5HKD 500,382,813.6).  The two price
    values are the highest and lowest per-share repurchase prices;
    price_min/price_max are assigned by value so extraction-order noise cannot
    flip them.  Anything not found stays null with a reason in
    coverage_reason/parse_errors.
    """

    result = ParsedNdd()
    if not text or not text.strip():
        result.parse_errors.append("empty body text")
        result.coverage_reason = "empty NDD body text; metadata only"
        return result
    form_match = _FORM_PATTERN.search(text)
    if form_match:
        result.form = form_match.group(0)
    issuer_match = _ISSUER_PATTERN.search(text)
    if issuer_match:
        result.issuer_name = issuer_match.group(1).strip()
    submitted_match = _DATE_SUBMITTED_PATTERN.search(text)
    if submitted_match:
        result.date_submitted = _parse_day_month_year(submitted_match.group(1))

    # Part A (repurchase/purchase report rows + summary block) sits between
    # the A. heading and the B. additional-information heading in Section II;
    # the mandate block lives in Part B.
    part_a_start = re.search(r"\bA\.\s+(?:Repurchase|Purchase) report\b", text, flags=re.IGNORECASE)
    part_b_start = re.search(r"\bB\.\s+Additional information\b", text, flags=re.IGNORECASE)
    if part_a_start is None:
        result.parse_errors.append("no A. Repurchase/Purchase report section found")
        result.coverage_reason = "NDD layout unsupported in v1 (Section II Part A missing); metadata only"
        return result
    part_a = text[part_a_start.end() : part_b_start.start() if part_b_start else None]
    part_b = text[part_b_start.end() :] if part_b_start else ""

    normalized = re.sub(r"\s+", " ", part_a)
    for row_match in _ROW_PATTERN.finditer(normalized):
        price_first = _parse_number(row_match.group(5))
        price_second = _parse_number(row_match.group(6))
        result.rows.append(
            {
                "row_no": int(row_match.group(1)),
                "trading_date": _parse_day_month_year(row_match.group(2)),
                "shares": _parse_count(row_match.group(3)),
                "method": row_match.group(4).strip(),
                "price_first": price_first,
                "price_second": price_second,
                "total_paid": _parse_number(row_match.group(7)),
            }
        )
    if not result.rows:
        result.parse_errors.append("no repurchase/purchase row matched in Section II Part A")

    summary_region = " ".join((normalized, " ".join(part_b.split())))
    aggregate = _AGGREGATE_FF305_PATTERN.search(summary_region)
    if aggregate is None:
        aggregate = _AGGREGATE_FF304_PATTERN.search(summary_region)
    if aggregate:
        result.aggregate_price_paid = _parse_number(aggregate.group(1))
    cancellation = _FOR_CANCELLATION_PATTERN.search(summary_region)
    if cancellation:
        result.shares_for_cancellation = _parse_count(cancellation.group(1))
    treasury = _FOR_TREASURY_PATTERN.search(summary_region)
    if treasury:
        result.shares_for_treasury = _parse_count(treasury.group(1))
    resolution = _RESOLUTION_DATE_PATTERN.search(summary_region)
    if resolution:
        result.mandate_resolution_date = _parse_day_month_year(resolution.group(1))
    authorised = _AUTHORISED_PATTERN.search(summary_region)
    if authorised:
        result.mandate_authorised_shares = _parse_count(authorised.group(1))
    cumulative = _CUMULATIVE_FF305_PATTERN.search(summary_region) or _CUMULATIVE_FF304_PATTERN.search(summary_region)
    if cumulative:
        result.mandate_cumulative_shares = _parse_count(cumulative.group(1))

    notes: list[str] = []
    if result.rows and result.rows[0]["trading_date"] is None:
        notes.append("trading date unparseable in repurchase row")
    if result.shares_for_cancellation is None and result.shares_for_treasury is None and result.form == "FF305":
        notes.append("FF305 cancellation/treasury designation fields not found")
    if result.mandate_resolution_date is None and result.form == "FF304":
        notes.append("FF304 discloses no repurchase-mandate resolution date")
    notes.append(
        "cancellation_status null by design: the NDD discloses designation only; "
        "completed cancellation dates are reported in later Monthly Returns (out of scope)"
    )
    result.coverage_reason = "; ".join(notes)
    return result


BodyFetcher = Callable[[str], bytes | None]
TextExtractor = Callable[[bytes, str], str]


def _validate_lookback_days(lookback_days: object) -> int:
    if isinstance(lookback_days, bool) or not isinstance(lookback_days, int):
        raise ValueError("lookback_days must be a non-negative integer")
    if lookback_days < 0:
        raise ValueError("lookback_days must be a non-negative integer")
    return lookback_days


def _default_body_fetcher(session: requests.Session, timeout: int) -> BodyFetcher:
    def fetch(url: str) -> bytes | None:
        try:
            response = session.get(url, headers=HKEXNEWS_HEADERS, timeout=timeout)
            response.raise_for_status()
            return response.content
        except requests.RequestException:
            return None

    return fetch


def _corporate_action_rows(
    session: requests.Session,
    *,
    ticker: str,
    entity_id: str,
    listing_id: str,
    canonical_ticker: str,
    as_of_utc: pd.Timestamp,
    lookback_days: int,
    retrieved_at_utc: pd.Timestamp,
    timeout: int,
    max_rows_per_query: int | None,
    body_fetcher: BodyFetcher | None = None,
    text_extractor: TextExtractor | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch corporate-action announcements for one HKEX issuer.

    Returns (rows, counts) where counts carries collected, parsed, unparsed,
    skipped, exceptions, query counts, and explicit truncation state so the
    source sidecar stays honest about coverage.
    """

    _validate_lookback_days(lookback_days)
    if max_rows_per_query is not None and (
        isinstance(max_rows_per_query, bool) or max_rows_per_query <= 0
    ):
        raise ValueError("max_rows_per_query must be a positive integer or None")

    resolved = _resolve_hkex_stock_id(session, ticker, timeout)
    if resolved is None:
        return [], {
            "collected": 0,
            "parsed": 0,
            "unparsed": 0,
            "skipped": 0,
            "exceptions": 1,
            "raw_rows": 0,
            "returned_rows": 0,
            "query_count": 0,
            "truncated": False,
        }
    stock_id, bare_code = resolved
    fetch_body = body_fetcher or _default_body_fetcher(session, timeout)
    as_of_hk = as_of_utc.tz_convert(HKEX_TIMEZONE)

    def query_title(title: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
        raw_rows: list[dict[str, str]] = []
        query_count = 0
        api_truncated = False
        cap_truncated = False
        window = pd.Timedelta(days=31)
        cursor = as_of_hk.normalize()
        start_bound = (as_of_hk - pd.Timedelta(days=lookback_days)).normalize()

        def request_window(
            window_start: pd.Timestamp,
            window_end: pd.Timestamp,
        ) -> tuple[list[dict[str, str]], int, bool]:
            nonlocal query_count
            params = {
                "sortDir": "0",
                "sortByOptions": "DateTime",
                "category": "0",
                "market": "SEHK",
                "stockId": stock_id,
                "documentType": "-1",
                "fromDate": window_start.strftime("%Y%m%d"),
                "toDate": window_end.strftime("%Y%m%d"),
                "title": title,
                "searchType": "1",
                "t1code": "-2",
                "t2Gcode": "-2",
                "t2code": "-2",
                "rowRange": "100",
                "lang": "E",
            }
            response = session.get(
                HKEXNEWS_TITLE_SEARCH_URL, params=params, headers=HKEXNEWS_HEADERS, timeout=timeout
            )
            response.raise_for_status()
            query_count += 1
            payload = response.json()
            raw = json.loads(payload.get("result") or "[]")
            filtered_rows: list[dict[str, str]] = []
            for row in raw:
                raw_stock_code = _text(row.get("STOCK_CODE"))
                codes = [
                    _normalize_hkex_code(part)
                    for part in re.split(r"<br\s*/?>", raw_stock_code)
                    if part.strip()
                ]
                if bare_code not in codes:
                    continue  # silent wrong-company guard, same adapter as official_filings
                filtered_rows.append(
                    {
                        key: _text(row.get(key))
                        for key in ("NEWS_ID", "TITLE", "LONG_TEXT", "SHORT_TEXT", "DATE_TIME", "FILE_LINK", "FILE_TYPE")
                    }
                )
            time.sleep(HKEX_QUERY_INTERVAL_SECONDS)

            # HKEX title search honors rowRange but ignores page. If a date
            # window fills the server cap, split the window until each query
            # is below the cap. A single calendar day that still fills the
            # cap is explicitly reported as truncated.
            if len(filtered_rows) >= 100 and window_start < window_end:
                midpoint = window_start + pd.Timedelta(
                    days=(window_end - window_start).days // 2
                )
                left, left_queries, left_truncated = request_window(
                    window_start, midpoint
                )
                right, right_queries, right_truncated = request_window(
                    midpoint + pd.Timedelta(days=1), window_end
                )
                return (
                    left + right,
                    left_queries + right_queries,
                    left_truncated or right_truncated,
                )
            return filtered_rows, 1, len(filtered_rows) >= 100

        while cursor >= start_bound:
            window_start = max(cursor - window, start_bound)
            window_rows, _window_queries, window_truncated = request_window(
                window_start, cursor
            )
            raw_rows.extend(window_rows)
            api_truncated = api_truncated or window_truncated
            has_more_windows = window_start > start_bound
            if max_rows_per_query is not None and len(raw_rows) >= max_rows_per_query:
                # Reaching a caller-supplied cap is itself an incomplete
                # coverage signal: even an exact-boundary count cannot prove
                # that the provider had no additional rows.
                cap_truncated = True
                break
            cursor = window_start - pd.Timedelta(days=1)
        returned_rows = (
            raw_rows[:max_rows_per_query]
            if max_rows_per_query is not None
            else raw_rows
        )
        return returned_rows, {
            "raw_rows": len(raw_rows),
            "returned_rows": len(returned_rows),
            "query_count": query_count,
            "truncated": api_truncated or cap_truncated,
        }

    ndd_rows, ndd_counts = query_title(NDD_TITLE_QUERY)
    dividend_rows, dividend_counts = query_title(DIVIDEND_TITLE_QUERY)
    seen: set[str] = set()
    counts: dict[str, Any] = {
        "collected": 0,
        "parsed": 0,
        "unparsed": 0,
        "skipped": 0,
        "exceptions": 0,
        "raw_rows": ndd_counts["raw_rows"] + dividend_counts["raw_rows"],
        "returned_rows": ndd_counts["returned_rows"] + dividend_counts["returned_rows"],
        "query_count": ndd_counts["query_count"] + dividend_counts["query_count"],
        "truncated": bool(ndd_counts["truncated"] or dividend_counts["truncated"]),
    }
    out: list[dict[str, Any]] = []
    for meta in ndd_rows + dividend_rows:
        news_id = meta["NEWS_ID"]
        if news_id in seen:
            continue
        published = _parse_hkex_datetime(meta["DATE_TIME"])
        # Point-in-time guard: explicitly discard rows published after as_of_utc
        # (including intraday same-calendar-day publications).
        if not pd.isna(published) and published > as_of_utc:
            continue
        seen.add(news_id)
        counts["collected"] += 1
        action_type, note = classify_action_type(
            title=meta["TITLE"], long_text=meta["LONG_TEXT"], short_text=meta["SHORT_TEXT"]
        )
        filing_date = "" if pd.isna(published) else published.strftime("%Y-%m-%d")
        file_link = meta["FILE_LINK"]
        source_url = f"{HKEXNEWS_BODY_URL_PREFIX}{file_link}" if file_link.startswith("/") else file_link
        source_doc_id = news_id if news_id else file_link
        base = {
            "version": VERSION,
            "entity_id": entity_id,
            "listing_id": listing_id,
            "canonical_ticker": canonical_ticker,
            "action_type": "",
            "filing_date": filing_date,
            "execution_date": "",
            "published_at": published,
            "shares_affected": None,
            "price_min": None,
            "price_max": None,
            "price_avg": None,
            "total_amount_paid": None,
            "currency": "HKD",
            "shares_for_cancellation": None,
            "shares_for_treasury": None,
            "cancellation_status": None,
            "mandate_resolution_date": None,
            "mandate_authorised_shares": None,
            "mandate_cumulative_repurchased_shares": None,
            "coverage_reason": "",
            "source_url": source_url,
            "source_document_id": source_doc_id,
            "document_format": meta["FILE_TYPE"].lower() if meta["FILE_TYPE"] else "unknown",
            "source_note": note or "",
            "retrieved_at_utc": retrieved_at_utc,
            "source_timezone": HKEX_TIMEZONE,
            "date_precision": "minute" if not pd.isna(published) else "day",
            "source_quality": "official_metadata",
            "pit_class": PIT_CLASS,
            "source_license_class": LICENSE_CLASS,
            "registry_version": REGISTRY_VERSION,
        }
        if action_type is None:
            counts["skipped"] += 1
            continue
        base["action_type"] = action_type
        if action_type != "buyback_execution":
            # Dividend/distribution rows: title metadata only; amounts, record
            # and ex dates need the announcement body (specialised parser,
            # T4+).  Nulls are provenance, never inference.
            base["coverage_reason"] = (
                "dividend/distribution amount, shares and dates are not extractable from the "
                "announcement title; body parsing is deferred to a specialised dividend parser (T4+)"
            )
            base["action_id"] = _action_id(listing_id, filing_date, "", action_type, source_doc_id, 1)
            out.append(base)
            continue

        payload = fetch_body(source_url)
        if payload is None:
            counts["unparsed"] += 1
            base["coverage_reason"] = "NDD body fetch failed; metadata only (numeric fields null)"
            base["action_id"] = _action_id(listing_id, filing_date, "", action_type, source_doc_id, 1)
            out.append(base)
            continue
        text = (text_extractor or extract_document_text)(payload, base["document_format"])
        parsed = parse_next_day_disclosure(text)
        if not parsed.rows:
            counts["unparsed"] += 1
            base["coverage_reason"] = "; ".join(parsed.parse_errors) or "NDD body parsing failed; metadata only"
            base["action_id"] = _action_id(listing_id, filing_date, "", action_type, source_doc_id, 1)
            out.append(base)
            continue
        counts["parsed"] += 1
        multiple_rows = len(parsed.rows) > 1
        for idx, row in enumerate(parsed.rows):
            action = dict(base)
            execution_date = row["trading_date"] or ""
            action["execution_date"] = execution_date
            action["filing_date"] = filing_date or (parsed.date_submitted or "")
            action["shares_affected"] = row["shares"]
            if row["price_first"] is not None and row["price_second"] is not None:
                action["price_min"] = min(row["price_first"], row["price_second"])
                action["price_max"] = max(row["price_first"], row["price_second"])
            action["total_amount_paid"] = row["total_paid"]
            coverage = [parsed.coverage_reason]
            if multiple_rows:
                coverage.append(
                    "filing-level summary/designation/mandate fields not attached to multi-row filings"
                )
            else:
                action["shares_for_cancellation"] = parsed.shares_for_cancellation
                action["shares_for_treasury"] = parsed.shares_for_treasury
                action["mandate_resolution_date"] = parsed.mandate_resolution_date
                action["mandate_authorised_shares"] = parsed.mandate_authorised_shares
                action["mandate_cumulative_repurchased_shares"] = parsed.mandate_cumulative_shares
            action["coverage_reason"] = "; ".join(coverage)
            action["source_quality"] = "official_body"
            action["source_note"] = (
                f"NDD form {parsed.form}; {len(parsed.rows)} repurchase row(s); "
                f"submitted {parsed.date_submitted or 'unknown'}"
            )
            row_discriminator = row.get("row_no") if row.get("row_no") is not None else (idx + 1)
            action["action_id"] = _action_id(
                listing_id,
                action["filing_date"],
                execution_date,
                action_type,
                source_doc_id,
                row_discriminator,
            )
            out.append(action)
    return out, counts


def _atomic_write_parquet(frame: pd.DataFrame, target_path: Path) -> None:
    """Write DataFrame to parquet atomically via temporary file and rename."""
    write_parquet_atomic(frame, target_path)


def collect_corporate_actions(
    identity: pd.DataFrame,
    *,
    as_of_utc: pd.Timestamp | None = None,
    retrieved_at_utc: pd.Timestamp | None = None,
    collection_clock: Callable[[], pd.Timestamp] | None = None,
    lookback_days: int = 365,
    max_rows_per_query: int | None = None,
    output_dir: Path | None = None,
    hkex_session: requests.Session | None = None,
    body_fetcher: BodyFetcher | None = None,
    text_extractor: TextExtractor | None = None,
    timeout: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Collect corporate-action announcements for every HKEX identity row.

    Returns (corporate_actions frame, state frame); with output_dir the two
    standardized local inputs are written (corporate_actions_v1.parquet and
    corporate_actions_state.parquet).  Any source failure is recorded in the
    state sidecar; a failed or unsupported body never fabricates numeric
    fields.
    """

    if retrieved_at_utc is not None:
        retrieval_time = (
            pd.Timestamp(retrieved_at_utc).tz_convert("UTC")
            if pd.Timestamp(retrieved_at_utc).tzinfo is not None
            else pd.Timestamp(retrieved_at_utc).tz_localize("UTC")
        )
    elif collection_clock is not None:
        clock_val = collection_clock()
        retrieval_time = (
            pd.Timestamp(clock_val).tz_convert("UTC")
            if pd.Timestamp(clock_val).tzinfo is not None
            else pd.Timestamp(clock_val).tz_localize("UTC")
        )
    else:
        retrieval_time = _now_utc()

    if as_of_utc is not None:
        query_as_of = (
            pd.Timestamp(as_of_utc).tz_convert("UTC")
            if pd.Timestamp(as_of_utc).tzinfo is not None
            else pd.Timestamp(as_of_utc).tz_localize("UTC")
        )
    else:
        query_as_of = retrieval_time

    _validate_lookback_days(lookback_days)

    if retrieval_time < query_as_of:
        raise ValueError(
            f"causal clock violation: retrieved_at_utc ({retrieval_time.isoformat()}) "
            f"cannot precede as_of_utc ({query_as_of.isoformat()})"
        )

    if max_rows_per_query is not None and (
        isinstance(max_rows_per_query, bool) or max_rows_per_query <= 0
    ):
        raise ValueError("max_rows_per_query must be a positive integer or None")

    session = hkex_session or requests.Session()
    hkex_identity = identity[identity["source_kind"].eq("hkex_code")].copy()
    rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []

    if hkex_identity.empty:
        state_rows.append(
            {
                "source_id": "corporate_actions:hkexnews",
                "source_kind": "corporate_action",
                "status": "no_records",
                "detail": "no hkex_code identity rows configured for corporate-action collection",
                "row_count": 0,
                "first_observation_at": pd.NaT,
                "latest_observation_at": pd.NaT,
                "source_latest_at": pd.NaT,
                "retrieved_at_utc": retrieval_time,
                "source_url": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en",
                "pit_class": PIT_CLASS,
                "source_license_class": LICENSE_CLASS,
                "cadence": "daily",
            }
        )
    else:
        totals: dict[str, Any] = {
            "collected": 0,
            "parsed": 0,
            "unparsed": 0,
            "skipped": 0,
            "exceptions": 0,
            "raw_rows": 0,
            "returned_rows": 0,
            "query_count": 0,
            "truncated": False,
        }
        issuers = 0
        for _, item in hkex_identity.iterrows():
            try:
                issuer_rows, counts = _corporate_action_rows(
                    session,
                    ticker=_text(item.get("source_native_id")),
                    entity_id=_text(item.get("entity_id")),
                    listing_id=_text(item.get("listing_id")),
                    canonical_ticker=_text(item.get("canonical_ticker")),
                    as_of_utc=query_as_of,
                    lookback_days=lookback_days,
                    retrieved_at_utc=retrieval_time,
                    timeout=timeout,
                    max_rows_per_query=max_rows_per_query,
                    body_fetcher=body_fetcher,
                    text_extractor=text_extractor,
                )
            except Exception as exc:
                totals["exceptions"] += 1
                logger.warning("corporate-action collection failed for %s: %s", item.get("entity_id"), exc)
                continue
            issuers += 1
            for key in ("collected", "parsed", "unparsed", "skipped", "exceptions", "raw_rows", "returned_rows", "query_count"):
                totals[key] += counts.get(key, 0)
            totals["truncated"] = bool(totals["truncated"] or counts.get("truncated", False))
            rows.extend(issuer_rows)
        detail = (
            f"hkexnews corporate-action title-search rows: collected={totals['collected']} "
            f"parsed={totals['parsed']} unparsed={totals['unparsed']} skipped={totals['skipped']} "
            f"exceptions={totals['exceptions']} raw_rows={totals['raw_rows']} "
            f"returned_rows={totals['returned_rows']} queries={totals['query_count']} "
            f"truncated={'true' if totals['truncated'] else 'false'} issuers={issuers}"
        )
        if totals["truncated"]:
            status = "partial"
        elif totals["parsed"] > 0:
            status = "partial" if (totals["unparsed"] > 0 or totals["exceptions"] > 0) else "available"
        elif totals["unparsed"] > 0:
            status = "partial"
        elif totals["exceptions"] > 0:
            status = "unavailable"
        else:
            status = "no_records"
        parsed_published = [
            r["published_at"]
            for r in rows
            if "published_at" in r and not pd.isna(r["published_at"])
        ]
        first_obs = min(parsed_published) if parsed_published else pd.NaT
        latest_obs = max(parsed_published) if parsed_published else pd.NaT
        source_latest = max(parsed_published) if parsed_published else pd.NaT

        state_rows.append(
            {
                "source_id": "corporate_actions:hkexnews",
                "source_kind": "corporate_action",
                "status": status,
                "detail": detail,
                "row_count": len(rows),
                "first_observation_at": first_obs,
                "latest_observation_at": latest_obs,
                "source_latest_at": source_latest,
                "retrieved_at_utc": retrieval_time,
                "source_url": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en",
                "pit_class": PIT_CLASS,
                "source_license_class": LICENSE_CLASS,
                "cadence": "daily",
            }
        )

    frame = pd.DataFrame(rows, columns=CORP_ACTIONS_COLUMNS)
    state_frame = pd.DataFrame(state_rows, columns=SOURCE_STATE_COLUMNS)
    for column in INT_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    for column in FLOAT_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
    for column in DATETIME_COLUMNS:
        frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)
    for column in STRING_COLUMNS:
        frame[column] = frame[column].fillna("").astype("string")
    for column in ("first_observation_at", "latest_observation_at", "source_latest_at", "retrieved_at_utc"):
        state_frame[column] = pd.to_datetime(state_frame[column], errors="coerce", utc=True)

    # Fail closed on duplicate primary keys before write
    if not frame.empty and not frame["version"].eq(VERSION).all():
        raise ValueError("corporate action version must be integer 1")
    if not frame.empty and not frame["registry_version"].eq(REGISTRY_VERSION).all():
        raise ValueError("corporate action registry_version must be 'v1'")
    if not frame["action_id"].is_unique:
        duplicates = frame[frame["action_id"].duplicated(keep=False)]["action_id"].tolist()
        raise ValueError(
            f"duplicate action_id detected in corporate actions ({len(duplicates)} occurrences): {duplicates[:10]}"
        )
    if not state_frame["source_id"].is_unique:
        duplicates = state_frame[state_frame["source_id"].duplicated(keep=False)]["source_id"].tolist()
        raise ValueError(
            f"duplicate source_id detected in corporate_actions_state ({len(duplicates)} occurrences): {duplicates[:10]}"
        )

    if output_dir is not None:
        _atomic_write_parquet(frame, output_dir / "corporate_actions_v1.parquet")
        _atomic_write_parquet(state_frame, output_dir / "corporate_actions_state.parquet")
    return frame, state_frame


__all__ = [
    "CORP_ACTIONS_COLUMNS",
    "REGISTRY_VERSION",
    "VERSION",
    "BodyFetcher",
    "TextExtractor",
    "classify_action_type",
    "collect_corporate_actions",
    "extract_document_text",
    "load_source_identity",
    "parse_next_day_disclosure",
]
