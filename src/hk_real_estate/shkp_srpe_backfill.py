"""SHKP-wide SRPE discovery and transaction-register scratch contracts.

This module deliberately separates three operations that are easy to conflate:

* candidate discovery from the all-development index and SHKP evidence;
* first-party project-site evidence (Vendor / Sales Agent / Holding Companies);
* the SRPE document metadata used by the PDF runner.

No row in this module promotes a phase to SHKP attributable ownership.  The
site evidence is a routing signal and review queue only; the transaction
register remains an official SRPE document source.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .config import DEFAULT_HEADERS
from .storage import load_latest_normalized, save_normalized_dataset, save_raw_snapshot


SHKP_PHASE_CANDIDATE_COLUMNS = [
    "srpe_development_id",
    "development_name_en",
    "phase_name_en",
    "phase_no",
    "address_en",
    "active",
    "official_website",
    "candidate_status",
    "candidate_tier",
    "candidate_sources_json",
    "candidate_context",
    "last_verified_at",
]

SHKP_PHASE_SITE_EVIDENCE_COLUMNS = [
    "evidence_id",
    "srpe_development_id",
    "development_name_en",
    "phase_name_en",
    "official_website",
    "resolved_url",
    "http_status",
    "fetch_status",
    "robots_status",
    "vendor_name",
    "sales_agent",
    "holding_companies",
    "shkp_keyword_hits_json",
    "shkp_match_status",
    "evidence_context",
    "source_url",
    "raw_snapshot_path",
    "fetched_at",
    "caveat",
]

# Rendered evidence is kept in a separate dataset.  A browser-rendered page
# is a useful recovery path for a JS shell, but it must not silently replace
# the raw HTTP observation or be treated as stronger ownership evidence.
SHKP_PHASE_RENDERED_SITE_EVIDENCE_COLUMNS = SHKP_PHASE_SITE_EVIDENCE_COLUMNS.copy()

SHKP_SCRATCH_REGISTRY_COLUMNS = [
    "project_id",
    "stock_code",
    "ownership_pct",
    "srpe_dev_id",
    "srpe_development_id",
    "development_name",
    "phase_name",
    "phase_no",
    "development_address",
    "pilot_group",
    "source_document",
    "last_verified_date",
    "candidate_status",
    "official_website",
    "ownership_attribution_ready",
    "ownership_effective_from",
    "ownership_effective_to",
    "ownership_interval_evidence_type",
    "ownership_attribution_decision_id",
    "ownership_interval_promotion_status",
]


_SHKP_TERMS = (
    "sun hung kai properties",
    "sun hung kai",
    "shkp",
    "新鴻基地產",
    "新鸿基地产",
    "新鴻基",
    "新鸿基",
)

# The all-SRPE quick-review queue contains many phases sharing one project
# domain.  Cache the robots decision per origin so a batch probe does not
# refetch the same robots.txt hundreds of times.  The cache is process-local
# and deliberately not persisted as a permission assertion; every persisted
# evidence row still records the robots status observed during its run.
_ROBOTS_CACHE: dict[tuple[str, str], tuple[bool | None, str]] = {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _normalise_url(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    if not re.match(r"^https?://", text, flags=re.IGNORECASE):
        text = "https://" + text
    return text


def _json_list(values: Iterable[Any]) -> str:
    return json.dumps(
        list(dict.fromkeys(str(value).strip() for value in values if _text(value))),
        ensure_ascii=False,
    )


def build_shkp_phase_candidates(
    srpe_index: pd.DataFrame,
    shkp_crosswalk: pd.DataFrame | None = None,
    annual_srpe_crosswalk: pd.DataFrame | None = None,
    identity_evidence: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build an SHKP candidate queue from current official evidence layers.

    The current SHKP listing crosswalk is the strongest discovery source,
    followed by annual-report phase candidates and explicit future-project
    identity evidence.  Ambiguous/review rows are retained so coverage can be
    measured rather than silently dropped.
    """
    if srpe_index is None or srpe_index.empty:
        return pd.DataFrame(columns=SHKP_PHASE_CANDIDATE_COLUMNS)
    srpe_by_id = {
        str(row.get("development_id") or "").strip(): row
        for row in srpe_index.to_dict("records")
        if _text(row.get("development_id"))
    }
    evidence: dict[str, dict[str, Any]] = {}
    sequence = 0

    def add(frame: pd.DataFrame | None, source: str, *, rank_by_status: dict[str, int]) -> None:
        nonlocal sequence
        if frame is None or frame.empty or "srpe_development_id" not in frame.columns:
            return
        for row in frame.to_dict("records"):
            phase_id = _text(row.get("srpe_development_id"))
            if not phase_id or phase_id not in srpe_by_id:
                continue
            status = _text(row.get("match_status")) or "identity_evidence"
            rank = rank_by_status.get(status, 5)
            existing = evidence.get(phase_id)
            if existing is None or rank < existing["rank"]:
                evidence[phase_id] = {
                    "rank": rank,
                    "sequence": sequence,
                    "candidate_status": status,
                    "source": source,
                    "context": [],
                }
            target = evidence[phase_id]
            target["context"].extend(
                value
                for value in (
                    row.get("marketing_name"),
                    row.get("project_label"),
                    row.get("phase_label"),
                    row.get("evidence_summary"),
                )
                if _text(value)
            )
            if source not in target.get("sources", []):
                target.setdefault("sources", []).append(source)
            sequence += 1

    add(
        shkp_crosswalk,
        "shkp_website_crosswalk",
        rank_by_status={"matched": 0, "matched_needs_review": 1, "ambiguous": 3},
    )
    add(
        annual_srpe_crosswalk,
        "shkp_annual_report_crosswalk",
        rank_by_status={"matched_needs_review": 2, "ambiguous": 4, "unmatched": 5},
    )
    add(
        identity_evidence,
        "shkp_future_project_identity_evidence",
        rank_by_status={"phase_resolved_srpe": 2, "matched_needs_review": 3},
    )

    rows: list[dict[str, Any]] = []
    for phase_id, meta in sorted(evidence.items(), key=lambda item: (item[1]["rank"], item[1]["sequence"])):
        srpe = srpe_by_id[phase_id]
        rows.append(
            {
                "srpe_development_id": phase_id,
                "development_name_en": srpe.get("development_name_en") or srpe.get("display_name"),
                "phase_name_en": srpe.get("phase_name_en"),
                "phase_no": srpe.get("phase_no"),
                "address_en": srpe.get("address_en"),
                "active": srpe.get("active"),
                "official_website": srpe.get("official_website"),
                "candidate_status": meta["candidate_status"],
                "candidate_tier": f"tier_{meta['rank'] + 1}",
                "candidate_sources_json": _json_list(meta.get("sources", [meta["source"]])),
                "candidate_context": " | ".join(dict.fromkeys(_text(value) for value in meta["context"] if _text(value))) or None,
                "last_verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=SHKP_PHASE_CANDIDATE_COLUMNS)


def build_shkp_transaction_scratch_registry(
    candidates: pd.DataFrame,
    *,
    include_review: bool = False,
    max_phases: int | None = None,
    start_index: int = 0,
) -> pd.DataFrame:
    """Build a temporary routing registry for SHKP transaction ingestion.

    This registry is intentionally not an ownership registry.  It gives the
    existing PDF runner stable project IDs and detail-API IDs while setting
    the ownership percentage to zero and the interval gate to blocked.  The
    caller may therefore batch-download official registers without creating
    a false company-level sales series.
    """
    if candidates is None or candidates.empty:
        return pd.DataFrame(columns=SHKP_SCRATCH_REGISTRY_COLUMNS)
    allowed = {"matched", "matched_needs_review", "ambiguous"} if include_review else {"matched"}
    selected = candidates[candidates["candidate_status"].isin(allowed)].copy()
    selected = selected[selected["srpe_development_id"].notna()]
    selected = selected.drop_duplicates(subset=["srpe_development_id"], keep="first")
    selected = selected.iloc[max(int(start_index), 0):]
    if max_phases is not None and max_phases > 0:
        selected = selected.head(max_phases)
    verified = datetime.now(timezone.utc).date().isoformat()
    rows: list[dict[str, Any]] = []
    for row in selected.to_dict("records"):
        phase_id = _text(row.get("srpe_development_id"))
        if not phase_id:
            continue
        development = _text(row.get("development_name_en")) or f"SRPE {phase_id}"
        phase = _text(row.get("phase_name_en")) or development
        rows.append(
            {
                "project_id": f"shkp-srpe-{phase_id}",
                "stock_code": "0016",
                "ownership_pct": 0.0,
                "srpe_dev_id": phase_id,
                "srpe_development_id": phase_id,
                "development_name": development,
                "phase_name": phase,
                "phase_no": _text(row.get("phase_no")) or "",
                "development_address": _text(row.get("address_en")) or "",
                "pilot_group": "shkp_candidate_routing_only",
                "source_document": "SRPE index + SHKP candidate evidence; ownership review required",
                "last_verified_date": verified,
                "candidate_status": _text(row.get("candidate_status")),
                "official_website": _text(row.get("official_website")),
                "ownership_attribution_ready": False,
                "ownership_effective_from": None,
                "ownership_effective_to": None,
                "ownership_interval_evidence_type": None,
                "ownership_attribution_decision_id": None,
                "ownership_interval_promotion_status": "blocked_candidate_routing_only",
            }
        )
    return pd.DataFrame(rows, columns=SHKP_SCRATCH_REGISTRY_COLUMNS)


def _extract_field(text: str, labels: Iterable[str]) -> str | None:
    escaped = "|".join(re.escape(label) for label in labels)
    # Require a statutory-field boundary and a colon.  Searching for the
    # words ``Sales Agent`` anywhere in a page otherwise captures ordinary
    # prose such as ``details of the sales agent`` and produces false names
    # like ``of the``.
    all_labels = (
        r"Vendor|Sales\s+Agents?|Holding\s+Companies?(?:\s+of\s+the\s+Vendor)?|"
        r"Holding\s+Company(?:\s+of\s+the\s+Vendor)?|"
        r"銷售代理(?:人)?|销售代理(?:人)?|控股公司|賣方|卖方|"
        r"Authorized\s+Person(?:\s+(?:for|of)\s+the\s+(?:Development|Phase))?|"
        r"Building\s+contractor(?:\s+for\s+the\s+(?:Development|Phase))?|"
        r"The\s+firms?\s+of\s+solicitors|The\s+firm\s+of\s+solicitors|"
        r"Authorized\s+institution|Any\s+other\s+person|This\s+advertisement|Last\s+updated|"
        r"To\s+the\s+extent|District|Name\s+of(?:\s+the)?\s+(?:Development|Phase|Street)|"
        r"Website\s+address|Enquiry\s+Hotline|Information\s+on\s+the\s+Vendor|"
        r"承辦商"
    )
    plain_boundaries = r"To\s+the\s+extent|Information\s+on\s+the\s+Vendor"
    pattern = re.compile(
        rf"(?:^|[|;\n]|\s)(?:{escaped})\s*[:：]\s*(?P<value>.*?)"
        rf"(?=\s*(?:{all_labels})\s*[:：]|\s*(?:{plain_boundaries})\b|\s*[|;\n]|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group("value")).strip(" |;\t\r\n")
    return value or None


def _extract_role_fields(text: str) -> tuple[str | None, str | None, str | None]:
    """Extract the three statutory role fields from visible/serialized text.

    Project sites use several materially different renderings: a plain
    ``Holding companies of the Vendor:`` label, a full-width pipe delimiter,
    or a JSON/app-state key.  Keep one conservative extractor so the audit
    records the field value without treating a generic page mention of SHKP
    as role evidence.
    """
    normalised = html.unescape(text).replace("｜", "|").replace("¦", "|")
    normalised = re.sub(r"[ \t\r\f\v]+", " ", normalised)
    vendor = _extract_field(normalised, ("Vendor", "賣方", "卖方"))
    sales_agent = _extract_field(
        normalised,
        (
            "Sales Agent",
            "Sales Agents",
            "Sales Agent(s)",
            "銷售代理",
            "銷售代理人",
            "销售代理",
            "销售代理人",
        ),
    )
    holding = _extract_field(
        normalised,
        (
            "Holding Companies of the Vendor",
            "Holding Company of the Vendor",
            "Holding Companies",
            "Holding Company",
            "控股公司",
        ),
    )

    # Modern React sites can leave the statutory facts in serialized state
    # rather than visible text.  Only accept values that look like a company
    # value and never overwrite a stronger visible-field extraction.
    def json_value(keys: tuple[str, ...]) -> str | None:
        key_pattern = "|".join(re.escape(key) for key in keys)
        matches = re.findall(
            rf"(?:\\\"|\")(?P<key>{key_pattern})(?:\\\"|\")\s*:\s*(?:\\\"|\")(?P<value>.*?)(?:\\\"|\")",
            normalised,
            flags=re.IGNORECASE,
        )
        values = [
            html.unescape(re.sub(r"\\[\"\\/bfnrtu]", "", value)).strip()
            for _, value in matches
            if value and re.search(r"(?:limited|ltd|company|corporation|新鴻基|新鸿基)", value, re.I)
        ]
        return max(values, key=len) if values else None

    vendor = vendor or json_value(("vendor",))
    sales_agent = sales_agent or json_value(("salesAgent", "salesAgents", "sales_agent"))
    holding = holding or json_value(("holdingCompanies", "holdingCompany", "holding_companies"))
    return vendor, sales_agent, holding


def _extract_role_fields_from_html(raw_html: str) -> tuple[str | None, str | None, str | None]:
    """Extract role fields from serialized HTML without leaking markup into values.

    Some project sites render statutory fields as text nodes separated by
    ``<br>``/``<span>`` tags.  Passing serialized markup directly to the
    conservative field extractor can therefore retain a literal ``<br>`` in a
    holding-company value.  BeautifulSoup gives us a clean text pass while
    preserving script/app-state text for the JSON-key fallback.
    """
    if not _text(raw_html):
        return None, None, None
    visible = BeautifulSoup(raw_html, "html.parser").get_text(" ", strip=True)
    return _extract_role_fields(visible)


def _robots_allowed(url: str, *, user_agent: str = "*") -> tuple[bool | None, str]:
    parsed = urlparse(url)
    cache_key = (parsed.netloc.casefold(), user_agent)
    cached = _ROBOTS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
        result = (parser.can_fetch(user_agent, url), "checked")
        _ROBOTS_CACHE[cache_key] = result
        return result
    except Exception:
        # A missing/unreachable robots file is not evidence of permission, but
        # we keep the fetch bounded and visible rather than silently claiming
        # compliance.
        result = (None, "unavailable")
        _ROBOTS_CACHE[cache_key] = result
        return result


def fetch_shkp_phase_site_evidence(
    candidates: pd.DataFrame,
    *,
    session: requests.Session | None = None,
    max_phases: int | None = 25,
    timeout: float = 20,
    request_delay: float = 0.25,
) -> pd.DataFrame:
    """Fetch public SRPE project sites and extract role/evidence labels."""
    if candidates is None or candidates.empty:
        return pd.DataFrame(columns=SHKP_PHASE_SITE_EVIDENCE_COLUMNS)
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "text/html,application/xhtml+xml"})
    selected = candidates.head(max_phases) if max_phases is not None and max_phases > 0 else candidates
    rows: list[dict[str, Any]] = []
    for candidate in selected.to_dict("records"):
        phase_id = _text(candidate.get("srpe_development_id"))
        website = _normalise_url(candidate.get("official_website"))
        fetched_at = datetime.now(timezone.utc).isoformat()
        evidence_id = hashlib.sha1(f"{phase_id}|{website}".encode("utf-8")).hexdigest()
        base = {
            "evidence_id": evidence_id,
            "srpe_development_id": phase_id,
            "development_name_en": candidate.get("development_name_en"),
            "phase_name_en": candidate.get("phase_name_en"),
            "official_website": candidate.get("official_website"),
            "resolved_url": website,
            "http_status": None,
            "fetch_status": "no_official_website" if not website else "error",
            "robots_status": None,
            "vendor_name": None,
            "sales_agent": None,
            "holding_companies": None,
            "shkp_keyword_hits_json": "[]",
            "shkp_match_status": "not_evaluated",
            "evidence_context": None,
            "source_url": website,
            "raw_snapshot_path": None,
            "fetched_at": fetched_at,
            "caveat": "Project-site role evidence is discovery/review-only; it does not establish listed-parent ownership percentage.",
        }
        if not website:
            rows.append(base)
            continue
        allowed, robots_status = _robots_allowed(website)
        base["robots_status"] = robots_status
        if allowed is False:
            base["fetch_status"] = "blocked_by_robots"
            rows.append(base)
            continue
        try:
            response = client.get(website, timeout=timeout, allow_redirects=True)
            response.raise_for_status()
            raw_path = save_raw_snapshot(
                "shkp_srpe_project_site",
                response.content,
                file_ext="html",
                source_url=response.url,
            )
            visible_text = BeautifulSoup(response.content, "html.parser").get_text(" ", strip=True)
            text = re.sub(r"\s+", " ", visible_text)
            # Prefer rendered/visible text.  App-state HTML often contains a
            # second copy of the disclaimer and can make a field span across
            # the visible/raw boundary; only use serialized text as a
            # per-field fallback for JS-heavy sites.
            vendor, sales_agent, holding = _extract_role_fields(text)
            raw_vendor, raw_sales_agent, raw_holding = _extract_role_fields_from_html(response.text)
            vendor = vendor or raw_vendor
            sales_agent = sales_agent or raw_sales_agent
            holding = holding or raw_holding
            lower = text.casefold()
            hits = [term for term in _SHKP_TERMS if term.casefold() in lower]
            role_values = " | ".join(value for value in (vendor, sales_agent, holding) if value)
            role_lower = role_values.casefold()
            role_hits = [term for term in _SHKP_TERMS if term.casefold() in role_lower]
            match_status = "site_named_shkp" if role_hits else "page_named_shkp" if hits else "site_no_shkp_keyword"
            context_terms = [term for term in (vendor, sales_agent, holding) if term]
            base.update(
                {
                    "http_status": response.status_code,
                    "fetch_status": "ok" if len(text) >= 120 else "ok_short_or_js",
                    "resolved_url": response.url,
                    "vendor_name": vendor,
                    "sales_agent": sales_agent,
                    "holding_companies": holding,
                    "shkp_keyword_hits_json": json.dumps(list(dict.fromkeys(hits)), ensure_ascii=False),
                    "shkp_match_status": match_status,
                    "evidence_context": " | ".join(context_terms)[:3000] or text[-1000:],
                    "raw_snapshot_path": str(raw_path),
                }
            )
        except (requests.RequestException, ValueError) as exc:
            base["fetch_status"] = "error"
            base["evidence_context"] = str(exc)
        rows.append(base)
        if request_delay:
            time.sleep(request_delay)
    return pd.DataFrame(rows, columns=SHKP_PHASE_SITE_EVIDENCE_COLUMNS)


def fetch_shkp_phase_site_evidence_rendered(
    candidates: pd.DataFrame,
    *,
    max_phases: int | None = 8,
    timeout: float = 30,
    wait_ms: int = 2500,
    request_delay: float = 0.5,
) -> pd.DataFrame:
    """Fetch bounded JS-heavy project sites with a real Chromium page.

    This is deliberately separate from :func:`fetch_shkp_phase_site_evidence`.
    The ordinary requests path remains the cheap, reproducible first pass;
    this function is only for pages that return an app shell or timeout before
    exposing the statutory role fields.  The rendered HTML is archived and
    the result is labelled ``rendered_*`` so downstream joins can keep both
    observations.  It is discovery/review evidence, never an ownership claim.

    Playwright is imported lazily so the normal source pipeline does not need
    to launch a browser.  If the browser dependency or browser binary is not
    available, one bounded status row per selected candidate is returned
    instead of raising and dropping the audit trail.
    """
    if candidates is None or candidates.empty:
        return pd.DataFrame(columns=SHKP_PHASE_RENDERED_SITE_EVIDENCE_COLUMNS)
    selected = candidates.head(max_phases) if max_phases is not None and max_phases > 0 else candidates
    selected_rows = selected.to_dict("records")
    rows: list[dict[str, Any]] = []

    def base_row(candidate: dict[str, Any], *, website: str | None, status: str) -> dict[str, Any]:
        phase_id = _text(candidate.get("srpe_development_id"))
        evidence_id = hashlib.sha1(f"rendered|{phase_id}|{website}".encode("utf-8")).hexdigest()
        return {
            "evidence_id": evidence_id,
            "srpe_development_id": phase_id,
            "development_name_en": candidate.get("development_name_en"),
            "phase_name_en": candidate.get("phase_name_en"),
            "official_website": candidate.get("official_website"),
            "resolved_url": website,
            "http_status": None,
            "fetch_status": status,
            "robots_status": None,
            "vendor_name": None,
            "sales_agent": None,
            "holding_companies": None,
            "shkp_keyword_hits_json": "[]",
            "shkp_match_status": "not_evaluated",
            "evidence_context": None,
            "source_url": website,
            "raw_snapshot_path": None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "caveat": (
                "Browser-rendered statutory role evidence is discovery/review-only; "
                "it does not establish listed-parent ownership percentage or an effective interval."
            ),
        }

    for candidate in selected_rows:
        website = _normalise_url(candidate.get("official_website"))
        row = base_row(candidate, website=website, status="rendered_no_official_website" if not website else "rendered_pending")
        if not website:
            rows.append(row)

    if len(rows) == len(selected_rows):
        return pd.DataFrame(rows, columns=SHKP_PHASE_RENDERED_SITE_EVIDENCE_COLUMNS)

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        for candidate in selected_rows:
            website = _normalise_url(candidate.get("official_website"))
            if website:
                row = base_row(candidate, website=website, status="rendered_dependency_missing")
                row["evidence_context"] = str(exc)
                rows.append(row)
        return pd.DataFrame(rows, columns=SHKP_PHASE_RENDERED_SITE_EVIDENCE_COLUMNS)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1440, "height": 1200},
                user_agent=DEFAULT_HEADERS.get("User-Agent"),
            )
            for candidate in selected_rows:
                website = _normalise_url(candidate.get("official_website"))
                if not website:
                    continue
                row = base_row(candidate, website=website, status="rendered_error")
                allowed, robots_status = _robots_allowed(website)
                row["robots_status"] = robots_status
                if allowed is False:
                    row["fetch_status"] = "rendered_blocked_by_robots"
                    rows.append(row)
                    continue
                try:
                    response = page.goto(
                        website,
                        wait_until="domcontentloaded",
                        timeout=max(int(timeout * 1000), 1000),
                    )
                    if wait_ms > 0:
                        page.wait_for_timeout(min(int(wait_ms), 15000))
                    rendered_html = page.content()
                    visible_text = page.locator("body").inner_text(timeout=max(int(timeout * 1000), 1000))
                    text = re.sub(r"\s+", " ", visible_text or "").strip()
                    resolved_url = page.url or website
                    raw_path = save_raw_snapshot(
                        "shkp_srpe_project_site_rendered",
                        rendered_html,
                        file_ext="html",
                        source_url=resolved_url,
                    )
                    vendor, sales_agent, holding = _extract_role_fields(text)
                    raw_vendor, raw_sales_agent, raw_holding = _extract_role_fields_from_html(rendered_html)
                    vendor = vendor or raw_vendor
                    sales_agent = sales_agent or raw_sales_agent
                    holding = holding or raw_holding
                    lower = text.casefold()
                    hits = [term for term in _SHKP_TERMS if term.casefold() in lower]
                    role_values = " | ".join(value for value in (vendor, sales_agent, holding) if value)
                    role_lower = role_values.casefold()
                    role_hits = [term for term in _SHKP_TERMS if term.casefold() in role_lower]
                    row.update(
                        {
                            "http_status": response.status if response is not None else None,
                            "fetch_status": "rendered_ok" if len(text) >= 120 else "rendered_ok_short",
                            "resolved_url": resolved_url,
                            "vendor_name": vendor,
                            "sales_agent": sales_agent,
                            "holding_companies": holding,
                            "shkp_keyword_hits_json": json.dumps(list(dict.fromkeys(hits)), ensure_ascii=False),
                            "shkp_match_status": "site_named_shkp" if role_hits else "page_named_shkp" if hits else "site_no_shkp_keyword",
                            "evidence_context": " | ".join(value for value in (vendor, sales_agent, holding) if value)[:3000] or text[-1000:],
                            "source_url": resolved_url,
                            "raw_snapshot_path": str(raw_path),
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                except PlaywrightTimeoutError as exc:
                    row["fetch_status"] = "rendered_timeout"
                    row["evidence_context"] = str(exc)
                except Exception as exc:  # browser/network errors are row-scoped audit outcomes
                    row["fetch_status"] = "rendered_error"
                    row["evidence_context"] = f"{type(exc).__name__}: {exc}"
                rows.append(row)
                if request_delay:
                    time.sleep(request_delay)
            browser.close()
    except Exception as exc:
        # Launch failures (missing Chromium, sandbox restrictions, etc.) are
        # retained for every URL rather than turning a bounded probe into a
        # pipeline-wide failure.
        for candidate in selected_rows:
            website = _normalise_url(candidate.get("official_website"))
            if website and not any(item.get("srpe_development_id") == _text(candidate.get("srpe_development_id")) for item in rows):
                row = base_row(candidate, website=website, status="rendered_browser_unavailable")
                row["evidence_context"] = f"{type(exc).__name__}: {exc}"
                rows.append(row)
    return pd.DataFrame(rows, columns=SHKP_PHASE_RENDERED_SITE_EVIDENCE_COLUMNS)


def run_shkp_srpe_transaction_scratch(
    *,
    max_phases: int | None = 17,
    start_index: int = 0,
    include_review: bool = False,
    timeout: float = 30,
    request_delay: float = 0.25,
) -> dict[str, Any]:
    """Run a candidate-routed, transaction-register-only SHKP scratch batch."""
    from .srpe_pilot import run_srpe_pilot

    candidates = build_shkp_phase_candidates(
        load_latest_normalized("srpe_development_index"),
        load_latest_normalized("shkp_srpe_crosswalk"),
        load_latest_normalized("shkp_annual_srpe_crosswalk"),
        load_latest_normalized("shkp_future_project_identity_evidence"),
    )
    registry = build_shkp_transaction_scratch_registry(
        candidates,
        include_review=include_review,
        max_phases=max_phases,
        start_index=start_index,
    )
    if registry.empty:
        raise ValueError("SHKP transaction scratch registry is empty")
    run_id = f"shkp-srpe-transaction-scratch-{uuid.uuid4()}"
    registry_raw = save_raw_snapshot(
        "shkp_srpe_transaction_scratch_registry",
        registry.to_csv(index=False),
        file_ext="csv",
        source_url="https://www.srpe.gov.hk/opip/all_development",
        run_id=run_id,
    )
    result = run_srpe_pilot(
        run_id=run_id,
        registry_path=registry_raw,
        pilot_group="shkp_candidate_routing_only",
        all_transaction_documents=True,
        transactions_only=True,
        dataset_prefix="shkp_srpe_scratch",
        request_delay=request_delay,
        timeout=timeout,
    )
    result.update(
        {
            "scratch_registry_mode": "candidate_routing_only",
            "scratch_candidate_status_filter": ["matched", "matched_needs_review", "ambiguous"]
            if include_review
            else ["matched"],
            "scratch_candidate_rows": int(len(registry)),
            "scratch_candidate_start_index": int(start_index),
            "scratch_candidate_ids": registry["srpe_development_id"].astype(str).tolist(),
            "ownership_attribution": "blocked_phase_specific_interval",
        }
    )
    return result


def run_shkp_srpe_site_probe(
    *,
    max_phases: int | None = 25,
    timeout: float = 20,
    request_delay: float = 0.25,
) -> dict[str, Any]:
    """Persist a bounded SHKP candidate/site-evidence scratch run."""
    run_id = f"shkp-srpe-site-probe-{uuid.uuid4()}"
    candidates = build_shkp_phase_candidates(
        load_latest_normalized("srpe_development_index"),
        load_latest_normalized("shkp_srpe_crosswalk"),
        load_latest_normalized("shkp_annual_srpe_crosswalk"),
        load_latest_normalized("shkp_future_project_identity_evidence"),
    )
    site_evidence = fetch_shkp_phase_site_evidence(
        candidates,
        max_phases=max_phases,
        timeout=timeout,
        request_delay=request_delay,
    )
    source_urls = sorted(
        set(
            str(value).strip()
            for value in site_evidence.get("source_url", pd.Series(dtype="string")).dropna()
            if str(value).strip()
        )
    )
    lineage = {
        "lineage_type": "shkp_srpe_phase_site_evidence_scratch",
        "candidate_rows": int(len(candidates)),
        "site_rows": int(len(site_evidence)),
        "site_match_status_counts": site_evidence.get("shkp_match_status", pd.Series(dtype="string")).value_counts().to_dict(),
        "ownership_inference": False,
        "sales_attribution": False,
    }
    normalized = {
        "shkp_srpe_phase_candidates": save_normalized_dataset(
            "shkp_srpe_phase_candidates",
            candidates,
            run_id=run_id,
            source_urls=["https://www.srpe.gov.hk/api/SrpeWebService/DistrictAreaSearch/getDistrictAreaSearchResult"],
            lineage_metadata=lineage,
        ),
        "shkp_srpe_phase_site_evidence": save_normalized_dataset(
            "shkp_srpe_phase_site_evidence",
            site_evidence,
            run_id=run_id,
            source_urls=source_urls,
            lineage_metadata=lineage,
        ),
    }
    return {
        "run_id": run_id,
        "candidate_rows": int(len(candidates)),
        "site_rows": int(len(site_evidence)),
        "site_match_status_counts": site_evidence.get("shkp_match_status", pd.Series(dtype="string")).value_counts().to_dict(),
        "normalized": normalized,
    }


def run_shkp_srpe_rendered_site_probe(
    *,
    max_phases: int | None = 8,
    timeout: float = 30,
    wait_ms: int = 2500,
    request_delay: float = 0.5,
    only_js_candidates: bool = True,
) -> dict[str, Any]:
    """Persist a bounded Playwright fallback for JS-heavy candidate sites."""
    run_id = f"shkp-srpe-rendered-site-probe-{uuid.uuid4()}"
    candidates = build_shkp_phase_candidates(
        load_latest_normalized("srpe_development_index"),
        load_latest_normalized("shkp_srpe_crosswalk"),
        load_latest_normalized("shkp_annual_srpe_crosswalk"),
        load_latest_normalized("shkp_future_project_identity_evidence"),
    )
    baseline = load_latest_normalized("shkp_srpe_phase_site_evidence")
    if only_js_candidates and not baseline.empty:
        js_ids = set(
            baseline.loc[
                baseline["fetch_status"].isin(["ok_short_or_js", "error"])
                | baseline["shkp_match_status"].eq("not_evaluated"),
                "srpe_development_id",
            ].astype(str)
        )
        candidates = candidates[candidates["srpe_development_id"].astype(str).isin(js_ids)].copy()
    evidence = fetch_shkp_phase_site_evidence_rendered(
        candidates,
        max_phases=max_phases,
        timeout=timeout,
        wait_ms=wait_ms,
        request_delay=request_delay,
    )
    source_urls = sorted({str(value).strip() for value in evidence.get("source_url", pd.Series(dtype="string")).dropna() if str(value).strip()})
    lineage = {
        "lineage_type": "shkp_srpe_phase_site_rendered_evidence_scratch",
        "rendering_engine": "playwright_chromium",
        "candidate_rows": int(len(candidates)),
        "site_rows": int(len(evidence)),
        "only_js_candidates": bool(only_js_candidates),
        "bounded": True,
        "ownership_inference": False,
        "sales_attribution": False,
    }
    normalized = save_normalized_dataset(
        "shkp_srpe_phase_site_rendered_evidence",
        evidence,
        run_id=run_id,
        source_urls=source_urls,
        lineage_metadata=lineage,
    )
    return {
        "run_id": run_id,
        "candidate_rows": int(len(candidates)),
        "site_rows": int(len(evidence)),
        "fetch_status_counts": evidence.get("fetch_status", pd.Series(dtype="string")).value_counts().to_dict(),
        "site_match_status_counts": evidence.get("shkp_match_status", pd.Series(dtype="string")).value_counts().to_dict(),
        "normalized": {"shkp_srpe_phase_site_rendered_evidence": normalized},
    }
