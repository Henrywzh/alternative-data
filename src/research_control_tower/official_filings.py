"""Official filings/announcement metadata collection for Control Tower Batch 2.

Collector-side module only: nothing here is imported by the Streamlit app, and
the offline builder consumes only the standardized local parquet inputs this
module writes.  Sources are the issuer/exchange official metadata layers:

- SEC EDGAR ``data.sec.gov/submissions`` API (public, unauthenticated; a
  descriptive User-Agent is required and throttling is enforced).  The raw
  payloads are snapshotted through the existing ``sec_edgar_data`` storage
  pattern; the normalized rows keep accession, filing/accepted timestamps and
  report dates but never document bodies.
- HKEXnews title-search servlet (official exchange announcement feed).  The
  stock-code resolution and the non-negotiable ``STOCK_CODE`` guard follow the
  HKEXnews adapter already proven in ``hk_stablecoin_crypto`` (see its module
  docstring for the silent wrong-company gotcha).
- Issuer IR: an optional standardized snapshot may be supplied; otherwise the
  adapter reports an honest ``no_records``/``partial`` state instead of
  fabricating calendar rows from HTML.

ByteDance is private: the collector emits a ``not_applicable`` state row and
never fabricates a listed-issuer disclosure.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from ..sec_edgar_data.client import build_retrying_session
from ..sec_edgar_data.config import resolve_user_agent
from ..sec_edgar_data.storage import EdgarStorage
from .build import OFFICIAL_FILINGS_COLUMNS, OFFICIAL_FILINGS_SCHEMA_ID, SOURCE_STATE_COLUMNS


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

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_FORMS_OF_INTEREST = frozenset({"6-K", "6-K/A", "20-F", "20-F/A", "10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A"})
SEC_REQUEST_INTERVAL_SECONDS = 0.2

PIT_CLASS = "snapshot_from_live_source"
LICENSE_CLASS = "official_public_metadata"

# Every mart-facing ``source_id`` this collector emits (SEC submissions,
# HKEXnews, issuer-IR) is namespaced with a "filings:" prefix so it is
# byte-for-byte identical to the governing ``source_health``/source-state
# record for the same provider ("filings:hkexnews", "filings:issuer_ir", ...
# below). The two standardized outputs (``official_filings_v1.parquet`` and
# ``official_filings_state.parquet``) are written together by this module, so
# keeping their ``source_id`` spelling identical at the point of collection
# means the offline builder and the Control Tower coverage matrix never have
# to guess which health record governs a filing row.


def _now_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _utc(value: object) -> pd.Timestamp | pd.NaT:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return pd.NaT
    if pd.isna(parsed):
        return pd.NaT
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def _date_text(value: object) -> str:
    parsed = _utc(value)
    return "" if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _iso(value: object) -> str:
    parsed = _utc(value)
    return "" if pd.isna(parsed) else parsed.isoformat()


def _as_date(value: object) -> date | None:
    parsed = _utc(value)
    return None if pd.isna(parsed) else parsed.date()


def _blank(value: object) -> bool:
    return value is None or value is pd.NaT or (not isinstance(value, (list, tuple, dict)) and pd.isna(value))


def _text(value: object) -> str:
    if _blank(value):
        return ""
    return str(value).strip()


class SecSubmissionsClient:
    """Thin, source-specific client for the public SEC submissions JSON API.

    This is the filer-submission *public* data feed (no token); it is distinct
    from the authenticated filer-submission API.  It preserves source-native
    ``acceptanceDateTime``/``filingDate``/``reportDate`` values, which the
    full-text search endpoint does not expose.
    """

    def __init__(self, user_agent: str, timeout: int = 20) -> None:
        self.timeout = timeout
        self.session = build_retrying_session(user_agent)
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < SEC_REQUEST_INTERVAL_SECONDS:
            time.sleep(SEC_REQUEST_INTERVAL_SECONDS - elapsed)
        self._last_request_at = time.monotonic()

    def fetch_submissions(self, cik: int) -> dict[str, Any]:
        self._throttle()
        url = SEC_SUBMISSIONS_URL.format(cik=cik)
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.json()


def _sec_metadata_rows(
    payload: Mapping[str, Any],
    *,
    cik: int,
    entity_id: str,
    listing_id: str,
    canonical_ticker: str,
    as_of_utc: pd.Timestamp,
    lookback_days: int,
    fetched_at: pd.Timestamp,
    max_rows: int,
) -> list[dict[str, Any]]:
    """Map one submissions payload into standardized metadata rows."""

    recent = payload.get("filings", {}).get("recent", {})
    count = len(recent.get("form", []))
    company_name = _text(payload.get("name")) or f"CIK {cik}"
    cutoff = (as_of_utc - pd.Timedelta(days=lookback_days)).normalize()
    rows: list[dict[str, Any]] = []
    for index in range(count):
        form = _text(recent["form"][index]).upper()
        if form not in SEC_FORMS_OF_INTEREST:
            continue
        accession = _text(recent["accessionNumber"][index])
        filing_date = _utc(recent["filingDate"][index]).normalize()
        if pd.isna(filing_date) or filing_date > as_of_utc or filing_date < cutoff:
            continue
        accepted_text = (
            _text(recent["acceptanceDateTime"][index])
            if recent.get("acceptanceDateTime") and index < len(recent["acceptanceDateTime"])
            else ""
        )
        accepted = _utc(accepted_text)
        if pd.isna(accepted):
            accepted = filing_date
        report_date = (
            _utc(recent["reportDate"][index]).normalize()
            if recent.get("reportDate") and index < len(recent["reportDate"])
            else pd.NaT
        )
        primary_document = _text(recent["primaryDocument"][index]) if recent.get("primaryDocument") else ""
        description = (
            _text(recent["primaryDocDescription"][index])
            if recent.get("primaryDocDescription") and index < len(recent["primaryDocDescription"])
            else ""
        )
        accn_nodash = accession.replace("-", "")
        if primary_document:
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/{primary_document}"
        else:
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/"
        description = description or primary_document or "filing"
        is_annual = form in {"20-F", "20-F/A", "10-K", "10-K/A"}
        is_quarterly = form in {"10-Q", "10-Q/A"}
        period_label = ""
        period_end: object = pd.NaT
        if is_annual and not pd.isna(report_date):
            period_end = report_date
            period_label = f"FY{report_date.year}"
        elif is_quarterly and not pd.isna(report_date):
            period_end = report_date
            quarter = (report_date.month - 1) // 3 + 1
            period_label = f"Q{quarter}{report_date.year}"
        rows.append(
            {
                "document_id": f"sec:{accession}",
                "document_type": "filing",
                "event_class": "earnings_results" if (is_annual or is_quarterly) else "general",
                "source_id": "filings:sec_edgar_submissions",
                "headline": f"{company_name} — Form {form} — {description}",
                "publisher": "SEC EDGAR",
                "published_at": accepted,
                "accepted_at": accepted,
                "scheduled_date": pd.NaT,
                "retrieved_at_utc": fetched_at,
                "source_url": filing_url,
                "language": "en",
                "entity_id": entity_id,
                "listing_id": listing_id,
                "canonical_ticker": canonical_ticker,
                "reporting_period_label": period_label,
                "reporting_period_start": pd.NaT,
                "reporting_period_end": period_end,
                "date_precision": "minute" if accepted_text else "day",
                "source_timezone": "UTC",
                "event_status": "observed",
                "source_quality": "official_metadata",
                "pit_class": PIT_CLASS,
                "source_license_class": LICENSE_CLASS,
                "content_hash_if_permitted": "",
                "source_note": (
                    "SEC submissions metadata; accepted/filing times are the SEC acceptance "
                    "timestamp; annual 20-F/10-K rows carry the report period end date. "
                    "Document bodies are not collected."
                ),
                "registry_version": "v1",
            }
        )
        if len(rows) >= max_rows:
            break
    return rows


def _normalize_hkex_code(code: object) -> str:
    bare = re.sub(r"\.HK$", "", _text(code), flags=re.IGNORECASE)
    return bare.lstrip("0") or "0"


def _resolve_hkex_stock_id(session: requests.Session, ticker: str, timeout: int) -> tuple[str, str] | None:
    """Resolve a bare stock code to HKEXnews' internal stockId (prefix.do)."""

    bare = _normalize_hkex_code(ticker)
    padded = bare.zfill(5)
    response = session.get(
        HKEXNEWS_PREFIX_URL,
        params={"callback": "callback", "lang": "EN", "type": "A", "name": padded, "market": "SEHK"},
        headers=HKEXNEWS_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    match = re.search(r"\((\{.*\})\)", response.text.strip(), flags=re.DOTALL)
    if not match:
        return None
    payload = json.loads(match.group(1))
    for suggestion in payload.get("stockInfo") or []:
        if _normalize_hkex_code(suggestion.get("code")) == bare:
            return str(suggestion.get("stockId")), bare
    return None


def _hkex_title_period_end(title: str) -> tuple[date | None, str | None]:
    """Extract the reporting-period end date and granularity from a results title.

    Handles both HKEX title styles: "THREE AND SIX MONTHS ENDED 30 JUNE 2026"
    and "FOR THE YEAR ENDED DECEMBER 31, 2025".
    """

    text = title.upper()
    match = re.search(r"ENDED\s+(?:ON\s+)?(\d{1,2})\s+([A-Z]+)\s+(\d{4})", text)
    if not match:
        match = re.search(r"ENDED\s+([A-Z]+)\s+(\d{1,2}),?\s+(\d{4})", text)
    if not match:
        return None, None
    try:
        months = {
            "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
            "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11,
            "DECEMBER": 12,
        }
        if match.lastindex == 3 and match.group(1).isdigit():
            day, month_name, year = int(match.group(1)), match.group(2), int(match.group(3))
        else:
            month_name, day, year = match.group(1), int(match.group(2)), int(match.group(3))
        period_end = date(year, months[month_name], day)
    except (KeyError, ValueError, IndexError):
        return None, None
    if "SIX MONTH" in text or "INTERIM" in text:
        granularity = "interim"
    elif "ANNUAL" in text or "YEAR ENDED" in text or "FINAL" in text:
        granularity = "annual"
    elif "QUARTER" in text or "THREE MONTH" in text:
        granularity = "quarterly"
    else:
        granularity = None
    return period_end, granularity


def _hkex_period_metadata(period_end: date, granularity: str | None) -> dict[str, object]:
    if granularity == "annual":
        start = date(period_end.year, 1, 1)
        label = f"FY{period_end.year}"
    elif granularity == "interim":
        start = date(period_end.year, 1, 1)
        label = f"1H{period_end.year}"
    elif granularity == "quarterly":
        quarter = min((period_end.month - 1) // 3 + 1, 4)
        start = date(period_end.year, 3 * (quarter - 1) + 1, 1)
        label = f"Q{quarter}{period_end.year}"
    else:
        start = period_end - timedelta(days=91)
        label = f"period ended {period_end.isoformat()}"
    return {"reporting_period_label": label, "reporting_period_start": start, "reporting_period_end": period_end}


def _classify_hkex_title(title: str) -> dict[str, object]:
    text = title.upper()
    period_end, granularity = _hkex_title_period_end(text)
    if granularity is None:
        return {
            "event_class": "general",
            "reporting_period_label": "",
            "reporting_period_start": pd.NaT,
            "reporting_period_end": pd.NaT,
        }
    return {"event_class": "earnings_results", **_hkex_period_metadata(period_end, granularity)}  # type: ignore[arg-type]


def _hkex_announcement_rows(
    session: requests.Session,
    *,
    ticker: str,
    entity_id: str,
    listing_id: str,
    canonical_ticker: str,
    as_of_utc: pd.Timestamp,
    lookback_days: int,
    fetched_at: pd.Timestamp,
    timeout: int,
    max_rows: int,
) -> tuple[list[dict[str, Any]], str]:
    """Fetch HKEXnews announcements for one issuer across month windows.

    Returns (rows, state) where state is one of "available", "no_records" or
    "unavailable".  The servlet caps each query at ``rowRange`` rows and its
    ``page`` parameter is ignored, so the window is walked month by month.
    """

    resolved = _resolve_hkex_stock_id(session, ticker, timeout)
    if resolved is None:
        return [], "unavailable"
    stock_id, bare_code = resolved
    rows: list[dict[str, Any]] = []
    window = timedelta(days=31)
    cursor = as_of_utc.normalize()
    start_bound = cursor - pd.Timedelta(days=lookback_days)
    queried = 0
    while cursor > start_bound and len(rows) < max_rows:
        window_start = max(cursor - window, start_bound)
        params = {
            "sortDir": "0",
            "sortByOptions": "DateTime",
            "category": "0",
            "market": "SEHK",
            "stockId": stock_id,
            "documentType": "-1",
            "fromDate": window_start.strftime("%Y%m%d"),
            "toDate": cursor.strftime("%Y%m%d"),
            "title": "",
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
        payload = response.json()
        raw_rows = json.loads(payload.get("result") or "[]")
        queried += 1
        for row in raw_rows:
            raw_stock_code = _text(row.get("STOCK_CODE"))
            codes = [_normalize_hkex_code(part) for part in re.split(r"<br\s*/?>", raw_stock_code) if part.strip()]
            if bare_code not in codes:
                continue
            date_time = _text(row.get("DATE_TIME"))
            published = pd.NaT
            if date_time:
                try:
                    local = datetime.strptime(date_time, "%d/%m/%Y %H:%M").replace(
                        tzinfo=ZoneInfo(HKEX_TIMEZONE)
                    )
                    published = pd.Timestamp(local).tz_convert("UTC")
                except ValueError:
                    published = pd.NaT
            title = _text(row.get("TITLE"))
            file_link = _text(row.get("FILE_LINK"))
            source_url = (
                f"https://www1.hkexnews.hk{file_link}" if file_link.startswith("/") else file_link
            )
            classification = _classify_hkex_title(title)
            rows.append(
                {
                    "document_id": f"hkexnews:{_text(row.get('NEWS_ID'))}",
                    "document_type": "announcement",
                    "event_class": classification["event_class"],
                    "source_id": "filings:hkexnews",
                    "headline": title,
                    "publisher": "HKEXnews",
                    "published_at": published,
                    "accepted_at": published,
                    "scheduled_date": pd.NaT,
                    "retrieved_at_utc": fetched_at,
                    "source_url": source_url,
                    "language": "en",
                    "entity_id": entity_id,
                    "listing_id": listing_id,
                    "canonical_ticker": canonical_ticker,
                    "reporting_period_label": classification["reporting_period_label"],
                    "reporting_period_start": classification["reporting_period_start"],
                    "reporting_period_end": classification["reporting_period_end"],
                    "date_precision": "minute" if not pd.isna(published) else "day",
                    "source_timezone": HKEX_TIMEZONE,
                    "event_status": "observed",
                    "source_quality": "official_metadata",
                    "pit_class": PIT_CLASS,
                    "source_license_class": LICENSE_CLASS,
                    "content_hash_if_permitted": "",
                    "source_note": (
                        "HKEXnews title-search metadata; DATE_TIME is the exchange publication "
                        "timestamp (Asia/Hong_Kong). Titles/links only, no announcement bodies."
                    ),
                    "registry_version": "v1",
                }
            )
        cursor = window_start - timedelta(days=1)
        time.sleep(0.4)
    state = "available" if rows else ("no_records" if queried else "unavailable")
    return rows[:max_rows], state


def _state_row(
    *,
    source_id: str,
    source_kind: str,
    status: str,
    detail: str,
    row_count: int,
    as_of_utc: pd.Timestamp,
    source_url: str = "",
    cadence: str = "",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_kind": source_kind,
        "status": status,
        "detail": detail,
        "row_count": row_count,
        "first_observation_at": pd.NaT,
        "latest_observation_at": pd.NaT,
        "source_latest_at": pd.NaT,
        "retrieved_at_utc": as_of_utc,
        "source_url": source_url,
        "pit_class": PIT_CLASS,
        "source_license_class": LICENSE_CLASS,
        "cadence": cadence,
    }


def load_source_identity(path: Path) -> pd.DataFrame:
    """Load the official-source identity crosswalk for the Stage 1 listings."""

    frame = pd.read_csv(path, keep_default_na=False)
    required = {"entity_id", "listing_id", "canonical_ticker", "source_kind", "source_native_id"}
    if not required.issubset(set(frame.columns)):
        raise ValueError(f"official source identity is missing columns: {sorted(required - set(frame.columns))}")
    return frame


def collect_official_filings(
    identity: pd.DataFrame,
    *,
    as_of_utc: pd.Timestamp | None = None,
    lookback_days: int = 365,
    max_rows_per_issuer: int = 300,
    output_dir: Path | None = None,
    ir_snapshot_path: Path | None = None,
    raw_root: Path | None = None,
    user_agent: str | None = None,
    sec_client: SecSubmissionsClient | None = None,
    hkex_session: requests.Session | None = None,
    timeout: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Collect Batch 2 metadata and return (filings frame, state frame).

    When ``output_dir`` is given the two standardized local inputs are written
    there so the offline builder can consume them.  SEC raw payloads are
    snapshotted under ``raw_root`` using the existing sec_edgar_data storage.
    """

    fetched_at = _now_utc() if as_of_utc is None else pd.Timestamp(as_of_utc).tz_convert("UTC")
    agent = user_agent or resolve_user_agent(Path.cwd())
    client = sec_client or SecSubmissionsClient(agent, timeout=timeout)
    session = hkex_session or requests.Session()
    rows: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    storage = EdgarStorage(Path.cwd()) if raw_root is None else EdgarStorage(raw_root)

    sec_rows = 0
    hkex_rows = 0
    sec_errors: list[str] = []
    hkex_errors: list[str] = []
    hkex_no_records: list[str] = []
    for _, item in identity.iterrows():
        entity_id = _text(item.get("entity_id"))
        listing_id = _text(item.get("listing_id"))
        canonical_ticker = _text(item.get("canonical_ticker"))
        source_kind = _text(item.get("source_kind"))
        native_id = _text(item.get("source_native_id"))
        source_url = _text(item.get("source_url"))
        if source_kind == "sec_cik":
            try:
                cik = int(native_id)
            except (TypeError, ValueError):
                sec_errors.append(f"{entity_id}: invalid CIK {native_id!r}")
                continue
            try:
                payload = client.fetch_submissions(cik)
                storage.write_raw_payload(
                    fetched_at.strftime("%Y%m%dT%H%M%SZ"),
                    f"submissions_{cik}",
                    payload,
                )
                rows.extend(
                    _sec_metadata_rows(
                        payload,
                        cik=cik,
                        entity_id=entity_id,
                        listing_id=listing_id,
                        canonical_ticker=canonical_ticker,
                        as_of_utc=fetched_at,
                        lookback_days=lookback_days,
                        fetched_at=fetched_at,
                        max_rows=max_rows_per_issuer,
                    )
                )
            except Exception as exc:  # network/parse failures are recorded, never swallowed silently
                sec_errors.append(f"{entity_id}: {exc}")
        elif source_kind == "hkex_code":
            try:
                issuer_rows, state = _hkex_announcement_rows(
                    session,
                    ticker=native_id,
                    entity_id=entity_id,
                    listing_id=listing_id,
                    canonical_ticker=canonical_ticker,
                    as_of_utc=fetched_at,
                    lookback_days=lookback_days,
                    fetched_at=fetched_at,
                    timeout=timeout,
                    max_rows=max_rows_per_issuer,
                )
                rows.extend(issuer_rows)
                if state == "no_records":
                    hkex_no_records.append(entity_id)
                if state == "unavailable":
                    hkex_errors.append(f"{entity_id}: could not resolve or query HKEXnews")
            except Exception as exc:
                hkex_errors.append(f"{entity_id}: {exc}")

    sec_rows = sum(1 for row in rows if row["source_id"] == "filings:sec_edgar_submissions")
    hkex_rows = sum(1 for row in rows if row["source_id"] == "filings:hkexnews")

    if identity["source_kind"].eq("sec_cik").any():
        if sec_errors:
            states.append(
                _state_row(
                    source_id="filings:sec_edgar_submissions",
                    source_kind="official_filing",
                    status="unavailable",
                    detail="; ".join(sec_errors)[:500],
                    row_count=0,
                    as_of_utc=fetched_at,
                    source_url="https://data.sec.gov/submissions/",
                    cadence="daily",
                )
            )
        else:
            states.append(
                _state_row(
                    source_id="filings:sec_edgar_submissions",
                    source_kind="official_filing",
                    status="available",
                    detail=f"sec_submissions_metadata rows={sec_rows}",
                    row_count=sec_rows,
                    as_of_utc=fetched_at,
                    source_url="https://data.sec.gov/submissions/",
                    cadence="daily",
                )
            )

    if identity["source_kind"].eq("hkex_code").any():
        if hkex_errors:
            states.append(
                _state_row(
                    source_id="filings:hkexnews",
                    source_kind="official_filing",
                    status="partial" if hkex_rows else "unavailable",
                    detail="; ".join(hkex_errors)[:500],
                    row_count=hkex_rows,
                    as_of_utc=fetched_at,
                    source_url="https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en",
                    cadence="daily",
                )
            )
        else:
            states.append(
                _state_row(
                    source_id="filings:hkexnews",
                    source_kind="official_filing",
                    status="no_records" if not hkex_rows else "available",
                    detail=(
                        "hkexnews_title_search rows=0 within lookback"
                        if not hkex_rows
                        else f"hkexnews_title_search rows={hkex_rows}"
                    ),
                    row_count=hkex_rows,
                    as_of_utc=fetched_at,
                    source_url="https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en",
                    cadence="daily",
                )
            )

    ir_rows: list[dict[str, Any]] = []
    if ir_snapshot_path is not None and Path(ir_snapshot_path).is_file():
        snapshot = pd.read_parquet(ir_snapshot_path) if str(ir_snapshot_path).endswith(".parquet") else pd.read_csv(Path(ir_snapshot_path), keep_default_na=False)
        if set(OFFICIAL_FILINGS_COLUMNS).issubset(set(snapshot.columns)):
            ir_rows = [
                {**row, "source_id": "filings:issuer_ir", "retrieved_at_utc": fetched_at}
                for row in snapshot.to_dict("records")
            ]
            states.append(
                _state_row(
                    source_id="filings:issuer_ir",
                    source_kind="official_filing",
                    status="available",
                    detail=f"issuer_ir_snapshot rows={len(ir_rows)}",
                    row_count=len(ir_rows),
                    as_of_utc=fetched_at,
                    source_url=(
                        _text(next((value for value in snapshot["source_url"] if not _blank(value)), ""))
                        if "source_url" in snapshot.columns
                        else ""
                    ),
                    cadence="monthly",
                )
            )
        else:
            states.append(
                _state_row(
                    source_id="filings:issuer_ir",
                    source_kind="official_filing",
                    status="unavailable",
                    detail="issuer_ir_snapshot schema mismatch; expected official_filings_v1 columns",
                    row_count=0,
                    as_of_utc=fetched_at,
                    cadence="monthly",
                )
            )
    else:
        states.append(
            _state_row(
                source_id="filings:issuer_ir",
                source_kind="official_filing",
                status="no_records",
                detail=(
                    "no machine-readable issuer IR calendar snapshot configured; "
                    "official exchange metadata (SEC/HKEX) is used instead; HTML IR pages are not scraped"
                ),
                row_count=0,
                as_of_utc=fetched_at,
                cadence="monthly",
            )
        )

    states.append(
        _state_row(
            source_id="filings:bytedance",
            source_kind="official_filing",
            status="not_applicable",
            detail="private company with no public filings or earnings calendar; competitor research only",
            row_count=0,
            as_of_utc=fetched_at,
            cadence="",
        )
    )

    rows.extend(ir_rows)
    frame = pd.DataFrame(rows, columns=OFFICIAL_FILINGS_COLUMNS)
    state_frame = pd.DataFrame(states, columns=SOURCE_STATE_COLUMNS)
    # Normalize temporal columns so a mixed ``datetime.date``/``NaT``/tz-aware
    # object column is written as a consistent UTC parquet column instead of
    # failing pyarrow conversion on live data.  The offline builder applies
    # the same coercion when it publishes the date32 mart columns.
    for column in (
        "published_at", "accepted_at", "scheduled_date", "retrieved_at_utc",
        "reporting_period_start", "reporting_period_end",
    ):
        frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)
    for column in ("first_observation_at", "latest_observation_at", "source_latest_at", "retrieved_at_utc"):
        state_frame[column] = pd.to_datetime(state_frame[column], errors="coerce", utc=True)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(output_dir / "official_filings_v1.parquet", index=False)
        state_frame.to_parquet(output_dir / "official_filings_state.parquet", index=False)
    return frame, state_frame


__all__ = [
    "OFFICIAL_FILINGS_SCHEMA_ID",
    "SecSubmissionsClient",
    "collect_official_filings",
    "load_source_identity",
]
