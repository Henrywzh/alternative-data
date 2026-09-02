"""Sino Land (0083.HK) company adapter.

Sino Group's Hong Kong property pages are backed by a public Kontent Delivery
API proxy.  This adapter keeps that endpoint-specific work separate from the
developer-agnostic event/snapshot/queue contracts in
``hk_real_estate.developer_tracking``.

The adapter is intentionally conservative:

* the company catalog is a discovery/current-listing layer, not a legal
  ownership registry;
* project-site text can establish role/identity evidence, not an equity
  interval; and
* annual-report pipeline labels remain planned/under-development evidence
  until an SRPE phase is resolved.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Iterable
from urllib.parse import urlencode, urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import DEFAULT_HEADERS, REGISTRY_DIR
from ..developer_tracking import (
    DEVELOPER_IDENTITY_COLUMNS,
    DEVELOPER_PIPELINE_COLUMNS,
    DEVELOPER_PROPERTY_CATALOG_COLUMNS,
    DeveloperProfile,
    build_developer_identity_crosswalk,
    build_developer_project_events,
    build_developer_project_snapshot,
    build_developer_sales_queue,
    normalize_developer_catalog,
)
from ..storage import load_latest_normalized, save_normalized_dataset, save_raw_snapshot
from .srpe import (
    SRPE_API_BASE,
    SRPE_DETAIL_ENDPOINT,
    SRPE_DOWNLOAD_ACTIONS,
    download_srpe_document,
    fetch_srpe_project_detail,
)
from .srpe_pdf import (
    PRICE_LIST_COLUMNS,
    TRANSACTION_COLUMNS,
    build_srpe_sales_signals,
    parse_srpe_price_list_pdf,
    parse_srpe_transaction_pdf,
)


SINO_LAND_PROFILE = DeveloperProfile(
    developer_id="sino_land",
    ticker="0083.HK",
    names_en=("Sino Land", "Sino Land Company Limited", "Sino Group"),
    names_zh=("信和置業", "信和置业", "信和集團", "信和集团"),
    official_domains=("https://www.sino.com", "https://salescms2.sino.com"),
    adapter_version="sino_land_kontent_v1",
)

SINO_KONTENT_PROJECT_ID = "20a53f0a-15c8-0029-b8df-e495023b403f"
SINO_KONTENT_ITEMS_URL = f"https://web-cdn.sino.com/{SINO_KONTENT_PROJECT_ID}/items"
SINO_PROPERTY_TYPES = "property_a,property_b,property_advertisement,property_quote,property_mainland_china"

SINO_PROPERTY_QUERY_CONFIGS: tuple[dict[str, str], ...] = (
    {
        "asset_type": "residential_for_sale",
        "business_category": "residential",
        "property_type": "for_sale",
        "source_page_url": "https://www.sino.com/en/our-business/residential/hong-kong/residential-for-sale/",
    },
    {
        "asset_type": "residential_for_lease",
        "business_category": "residential",
        "property_type": "for_lease",
        "source_page_url": "https://www.sino.com/en/our-business/residential/hong-kong/residential-for-lease/",
    },
    {
        "asset_type": "office",
        "business_category": "offices",
        "property_type": "for_lease",
        "source_page_url": "https://www.sino.com/en/our-business/office/hong-kong/",
    },
    {
        "asset_type": "industrial",
        "business_category": "industrial",
        "property_type": "for_lease",
        "source_page_url": "https://www.sino.com/en/our-business/industrial/hong-kong/",
    },
    {
        "asset_type": "shopping_mall",
        "business_category": "retail",
        "property_type": "for_lease",
        "source_page_url": "https://www.sino.com/en/our-business/retail/hong-kong/",
    },
)

SINO_PIPELINE_DISCLOSURE_COLUMNS = [
    *DEVELOPER_PIPELINE_COLUMNS,
    "annual_report_id",
    "annual_report_page",
    "group_equity_interest_pct",
]

SINO_SITE_ROLE_COLUMNS = [
    "company_id",
    "ticker",
    "marketing_name",
    "external_project_url",
    "site_evidence_status",
    "vendor_name",
    "holding_company_hits_json",
    "role_hits_json",
    "evidence_context",
    "raw_snapshot",
    "source_url",
    "fetched_at",
]

SINO_SRPE_MANIFEST_COLUMNS = [
    "company_id",
    "ticker",
    "canonical_project_id",
    "project_label",
    "srpe_development_id",
    "srpe_phase_name",
    "queue_status",
    "document_category",
    "document_id",
    "document_serial_no",
    "file_name",
    "submission_time",
    "date_of_printing",
    "expected_file_size_bytes",
    "download_endpoint",
    "manifest_status",
    "error",
    "source_url",
    "observed_at",
    "missing_data_policy",
]

SINO_SRPE_TRANSACTION_AUDIT_COLUMNS = [
    "company_id",
    "ticker",
    "canonical_project_id",
    "project_label",
    "srpe_development_id",
    "document_id",
    "file_name",
    "submission_time",
    "expected_file_size_bytes",
    "actual_file_size_bytes",
    "download_status",
    "parse_status",
    "raw_snapshot_path",
    "raw_rows",
    "dedup_rows",
    "cross_document_duplicate_rows_removed",
    "error",
    "source_url",
    "observed_at",
    "missing_data_policy",
]

SINO_SRPE_TRANSACTION_COVERAGE_COLUMNS = [
    "company_id",
    "ticker",
    "canonical_project_id",
    "project_label",
    "srpe_development_id",
    "srpe_phase_name",
    "queue_status",
    "transaction_document_count",
    "transaction_document_ids_json",
    "coverage_status",
    "download_status",
    "parse_status",
    "parsed_event_rows",
    "last_document_submission_time",
    "observed_at",
    "missing_data_policy",
]

SINO_SRPE_PRICE_LIST_AUDIT_COLUMNS = [
    "company_id",
    "ticker",
    "canonical_project_id",
    "project_label",
    "srpe_development_id",
    "document_id",
    "file_name",
    "submission_time",
    "date_of_printing",
    "expected_file_size_bytes",
    "actual_file_size_bytes",
    "download_status",
    "parse_status",
    "raw_snapshot_path",
    "raw_rows",
    "dedup_rows",
    "total_residential_properties",
    "error",
    "source_url",
    "observed_at",
    "missing_data_policy",
]

SINO_SRPE_PRICE_LIST_COVERAGE_COLUMNS = [
    "company_id",
    "ticker",
    "canonical_project_id",
    "project_label",
    "srpe_development_id",
    "srpe_phase_name",
    "queue_status",
    "price_list_document_count",
    "price_list_document_ids_json",
    "coverage_status",
    "download_status",
    "parse_status",
    "parsed_unit_rows",
    "total_residential_properties",
    "inventory_status",
    "last_document_submission_time",
    "observed_at",
    "missing_data_policy",
]

# Official issuer-hosted copy of Annual Report 2025.  HKEX is kept as a
# secondary source in the fetch result for audit/recovery, not used as a
# substitute for issuer text when the issuer PDF is unavailable.
SINO_ANNUAL_REPORT_2025_URL = (
    "https://web-media.sino.com/20a53f0a-15c8-0029-b8df-e495023b403f/"
    "c468acfe-1a59-4c93-9131-6eeba511b501/E_SL_Annual%20Report%202025.pdf"
)
SINO_ANNUAL_REPORT_2025_HKEX_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0925/2025092501132.pdf"

# These are labels explicitly present in the 2025 annual-report pipeline
# paragraph.  They are adapter-level search anchors, not a claim that the
# list is a complete land bank.
SINO_PIPELINE_PROJECT_HINTS: tuple[tuple[str, str], ...] = (
    ("Yau Tong Ventilation Building Property Development", "planned_launch"),
    ("Grand Mayfair III", "planned_launch"),
    ("LOHAS Park Package Thirteen Property Development", "planned_launch"),
    ("Wing Kwong Street/Sung On Street Development Project", "under_development"),
)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _element(item: dict[str, Any], key: str, default: Any = None) -> Any:
    value = item.get("elements", {}).get(key, {})
    if isinstance(value, dict):
        return value.get("value", default)
    return default


def _taxonomy_name(item: dict[str, Any], key: str) -> str | None:
    value = _element(item, key, [])
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return _clean(first.get("name") or first.get("codename"))
    return _clean(value)


def _normalize_project_url(value: Any) -> str | None:
    url = _clean(value)
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("www."):
        return "https://" + url
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return urljoin("https://www.sino.com/", url)
    return url


def _extract_group_equity_interest(text: str) -> float | None:
    """Extract only an explicit ``% equity interest`` phrase from evidence."""
    matches = re.findall(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*%\s*(?:equity\s+interest|interest)\b",
        text or "",
        flags=re.IGNORECASE,
    )
    if not matches:
        return None
    try:
        return float(matches[0])
    except (TypeError, ValueError):
        return None


def fetch_sino_property_catalog(
    *,
    session: requests.Session | None = None,
    timeout: float = 60,
    page_size: int = 100,
    max_pages: int | None = None,
    tolerate_category_errors: bool = True,
) -> pd.DataFrame:
    """Fetch Sino Group's Hong Kong property catalog by business category."""
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "application/json, */*"})
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    summaries: list[dict[str, Any]] = []

    for config in SINO_PROPERTY_QUERY_CONFIGS:
        summary: dict[str, Any] = {
            "asset_type": config["asset_type"],
            "source_page_url": config["source_page_url"],
            "pages_fetched": 0,
            "rows_emitted": 0,
            "status": "failed",
            "error_type": None,
            "error": None,
        }
        try:
            skip = 0
            page_number = 0
            next_request_url: str | None = None
            seen_request_urls: set[str] = set()
            while True:
                params = {
                    "system.type[in]": SINO_PROPERTY_TYPES,
                    "language": "en",
                    "order": "elements.property_attribute__rank[asc]",
                    "skip": skip,
                    "limit": page_size,
                    "elements.property_attribute__business_category[contains]": config["business_category"],
                    "elements.property_attribute__property_region[any]": "hong_kong",
                    "elements.property_attribute__property_type[contains]": config["property_type"],
                }
                request_url = next_request_url or f"{SINO_KONTENT_ITEMS_URL}?{urlencode(params)}"
                if request_url in seen_request_urls:
                    raise ValueError(f"Sino property endpoint repeated pagination URL: {request_url}")
                seen_request_urls.add(request_url)
                response = client.get(request_url, timeout=timeout)
                raw_body = getattr(response, "content", getattr(response, "text", b""))
                if isinstance(raw_body, str):
                    raw_body = raw_body.encode("utf-8")
                raw_path = save_raw_snapshot(
                    f"sino_land_{config['asset_type']}_catalog_page_{page_number}",
                    raw_body or b"",
                    file_ext="json",
                    source_url=request_url,
                )
                raw_snapshots.append(str(raw_path))
                source_urls.append(request_url)
                response.raise_for_status()
                if not raw_body or not raw_body.strip():
                    raise ValueError("Sino property endpoint returned an empty body")
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                    raise ValueError("Sino property endpoint returned no item list")
                items = payload["items"]
                emitted_count = 0
                for item in items:
                    system = item.get("system", {}) if isinstance(item, dict) else {}
                    title = _clean(_element(item, "property__title") or system.get("name"))
                    if not title:
                        continue
                    location = _taxonomy_name(item, "property_attribute__property_location")
                    address = _clean(_element(item, "property__address"))
                    address_2 = _clean(_element(item, "property__address_2"))
                    if address_2:
                        address = f"{address}; {address_2}" if address else address_2
                    rank = _element(item, "property_attribute__rank")
                    rows.append(
                        {
                            "company_id": SINO_LAND_PROFILE.developer_id,
                            "ticker": SINO_LAND_PROFILE.normalized_ticker,
                            "asset_type": config["asset_type"],
                            "subtype": config["property_type"],
                            "marketing_name": title,
                            "district": location,
                            "address": address,
                            "external_project_url": _normalize_project_url(_element(item, "property__website_url")),
                            "source_record_id": _clean(system.get("id") or system.get("codename")),
                            "source_page_url": config["source_page_url"],
                            "source_url": request_url,
                            "listed_status": config["property_type"],
                            "raw_langcode": "en",
                            "page_number": page_number,
                            "display_order": rank,
                            "fetched_at": fetched_at,
                            "source_adapter": SINO_LAND_PROFILE.adapter_version,
                        }
                    )
                    emitted_count += 1
                page_number += 1
                summary["pages_fetched"] = page_number
                summary["rows_emitted"] = int(summary["rows_emitted"]) + emitted_count
                pagination = payload.get("pagination") or {}
                next_page = _clean(pagination.get("next_page"))
                count = int(pagination.get("count") or 0)
                if not items or (max_pages is not None and page_number >= max_pages):
                    break
                if next_page:
                    next_request_url = (
                        next_page if re.match(r"^https?://", next_page, re.IGNORECASE)
                        else urljoin(SINO_KONTENT_ITEMS_URL, next_page)
                    )
                    # The opaque next-page URL owns pagination state; do not
                    # append a stale skip/limit query to it.
                    continue
                next_request_url = None
                if count <= 0 or skip + len(items) >= count:
                    break
                skip += len(items)
            summary["status"] = "ok"
        except Exception as exc:
            summary["error_type"] = type(exc).__name__
            summary["error"] = str(exc)
            if not tolerate_category_errors:
                raise
        summaries.append(summary)

    frame = pd.DataFrame(rows, columns=DEVELOPER_PROPERTY_CATALOG_COLUMNS)
    if not frame.empty:
        frame = normalize_developer_catalog(SINO_LAND_PROFILE, frame, source_adapter=SINO_LAND_PROFILE.adapter_version)
    frame.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=list(dict.fromkeys(source_urls)),
        fetch_summary=summaries,
        lineage_metadata={
            "lineage_type": "official_sino_land_property_catalog",
            "company_id": SINO_LAND_PROFILE.developer_id,
            "ticker": SINO_LAND_PROFILE.normalized_ticker,
            "adapter_version": SINO_LAND_PROFILE.adapter_version,
            "category_error_policy": "continue_per_category" if tolerate_category_errors else "fail_fast",
            "failed_category_count": sum(item["status"] != "ok" for item in summaries),
        },
    )
    if frame.empty and summaries and all(item["status"] != "ok" for item in summaries):
        raise RuntimeError("All Sino Land property catalog categories failed")
    return frame


def fetch_sino_project_site_role_evidence(
    property_catalog: pd.DataFrame,
    *,
    session: requests.Session | None = None,
    timeout: float = 30,
    max_projects: int = 10,
    project_names: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Capture role/holding-company text from Sino project websites."""
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "text/html, */*"})
    requested = {_clean(value).casefold() for value in (project_names or []) if _clean(value)}
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    for record in property_catalog.to_dict("records"):
        if record.get("asset_type") != "residential_for_sale":
            continue
        name = _clean(record.get("marketing_name")) or ""
        if requested and name.casefold() not in requested:
            continue
        if len(rows) >= max(0, max_projects):
            break
        url = _normalize_project_url(record.get("external_project_url"))
        base = {
            "company_id": SINO_LAND_PROFILE.developer_id,
            "ticker": SINO_LAND_PROFILE.normalized_ticker,
            "marketing_name": name or None,
            "external_project_url": url,
            "site_evidence_status": "not_evaluated" if not url else "error",
            "vendor_name": None,
            "holding_company_hits_json": "[]",
            "role_hits_json": "[]",
            "evidence_context": None,
            "raw_snapshot": None,
            "source_url": url,
            "fetched_at": fetched_at,
        }
        if not url:
            rows.append(base)
            continue
        try:
            response = client.get(url, timeout=timeout)
            raw_body = getattr(response, "content", getattr(response, "text", b""))
            if isinstance(raw_body, str):
                raw_body = raw_body.encode("utf-8")
            raw_path = save_raw_snapshot("sino_land_project_site_role_page", raw_body or b"", file_ext="html", source_url=url)
            raw_snapshots.append(str(raw_path))
            source_urls.append(url)
            response.raise_for_status()
            text = re.sub(r"\s+", " ", BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)).strip()
            lower = text.casefold()
            company_terms = [
                "sino land company limited",
                "tsim sha tsui properties limited",
                "信和置業",
                "信和置业",
            ]
            role_terms = ["holding company", "holding companies", "vendor", "person so engaged", "owner", "發展商", "發展商人"]
            company_hits = [term for term in company_terms if term.casefold() in lower]
            role_hits = [term for term in role_terms if term.casefold() in lower]
            status = "site_named_company_role" if company_hits and role_hits else "site_named_company" if company_hits else "site_no_company_keyword"
            context = None
            if company_hits:
                position = min(lower.find(term.casefold()) for term in company_hits if term.casefold() in lower)
                context = text[max(0, position - 180): position + 500]
            base.update(
                site_evidence_status=status,
                vendor_name=company_hits[0] if company_hits else None,
                holding_company_hits_json=json.dumps(company_hits, ensure_ascii=False),
                role_hits_json=json.dumps(role_hits, ensure_ascii=False),
                evidence_context=context,
            )
            base["raw_snapshot"] = str(raw_path)
        except Exception as exc:
            base["site_evidence_status"] = "error"
            base["evidence_context"] = f"{type(exc).__name__}: {exc}"
        rows.append(base)
    frame = pd.DataFrame(rows, columns=SINO_SITE_ROLE_COLUMNS)
    frame.attrs["lineage_metadata"] = {
        "lineage_type": "official_sino_project_site_role_evidence",
        "company_id": SINO_LAND_PROFILE.developer_id,
        "ticker": SINO_LAND_PROFILE.normalized_ticker,
        "ownership_inference": False,
    }
    frame.attrs["raw_snapshots"] = raw_snapshots
    frame.attrs["source_urls"] = list(dict.fromkeys(source_urls))
    return frame


def fetch_sino_srpe_document_manifest(
    sales_queue: pd.DataFrame,
    *,
    session: requests.Session | None = None,
    timeout: float = 30,
    max_projects: int = 8,
    request_delay: float = 0.2,
) -> pd.DataFrame:
    """Fetch SRPE document metadata for a bounded recent Sino sales queue.

    The result is a routing/coverage layer, not a sales result.  A successful
    manifest with no transaction rows is recorded as ``manifest_ok_no_documents``
    and remains distinct from a failed request or a missing SRPE identity.
    PDFs are intentionally not downloaded here; the document IDs and download
    endpoints are the hand-off for the later parser/download lane.
    """
    client = session or requests.Session()
    fetched_at = datetime.now(timezone.utc).isoformat()
    client.headers.update(
        {
            **DEFAULT_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://www.srpe.gov.hk",
            "Referer": "https://www.srpe.gov.hk/opip/",
        }
    )
    eligible = sales_queue.copy() if sales_queue is not None else pd.DataFrame()
    if not eligible.empty:
        queue_status = eligible.get("queue_status", pd.Series(index=eligible.index, dtype="string"))
        development_ids = eligible.get("srpe_development_id", pd.Series(index=eligible.index, dtype="string"))
        eligible = eligible.loc[
            queue_status.eq("eligible_for_recent_srpe_queue")
            & development_ids.map(_clean).notna()
        ].drop_duplicates(subset=["canonical_project_id"], keep="last")
        eligible = eligible.head(max(0, int(max_projects)))

    rows: list[dict[str, Any]] = []
    raw_snapshots: list[str] = []
    source_urls = [SRPE_DETAIL_ENDPOINT]
    for record in eligible.to_dict("records"):
        project_id = _clean(record.get("canonical_project_id"))
        project_label = _clean(record.get("project_label"))
        development_id = _clean(record.get("srpe_development_id"))
        base = {
            "company_id": SINO_LAND_PROFILE.developer_id,
            "ticker": SINO_LAND_PROFILE.normalized_ticker,
            "canonical_project_id": project_id,
            "project_label": project_label,
            "srpe_development_id": development_id,
            "srpe_phase_name": _clean(record.get("srpe_phase_name")),
            "queue_status": _clean(record.get("queue_status")),
            "document_category": None,
            "document_id": None,
            "document_serial_no": None,
            "file_name": None,
            "submission_time": None,
            "date_of_printing": None,
            "expected_file_size_bytes": None,
            "download_endpoint": None,
            "manifest_status": "manifest_fetch_error",
            "error": None,
            "source_url": SRPE_DETAIL_ENDPOINT,
            "observed_at": fetched_at,
            "missing_data_policy": "unknown_is_not_zero; no_srpe_is_not_no_sales",
        }
        try:
            if not development_id:
                raise ValueError("missing srpe_development_id")
            detail = fetch_srpe_project_detail(development_id, session=client, timeout=timeout)
            raw_body = json.dumps(detail, ensure_ascii=False).encode("utf-8")
            raw_path = save_raw_snapshot(
                f"sino_land_srpe_manifest_{development_id}",
                raw_body,
                file_ext="json",
                source_url=SRPE_DETAIL_ENDPOINT,
            )
            raw_snapshots.append(str(raw_path))

            document_groups = (
                ("register_of_transactions", detail.get("transactions") or []),
                ("price_list", detail.get("prices") or []),
                ("sales_arrangement", detail.get("salesArrangements") or []),
                ("sales_brochure", detail.get("brochureList") or []),
            )
            emitted = 0
            for category, documents in document_groups:
                for document in documents:
                    if not isinstance(document, dict):
                        continue
                    file_info = document.get("file") or {}
                    document_id = _clean(document.get("id") or file_info.get("id"))
                    if not document_id:
                        continue
                    endpoint = f"{SRPE_API_BASE}/download/{SRPE_DOWNLOAD_ACTIONS[category]}"
                    row = dict(base)
                    row.update(
                        {
                            "document_category": category,
                            "document_id": document_id,
                            "document_serial_no": _clean(document.get("serialNo")),
                            "file_name": _clean(file_info.get("fileName") or document.get("fileName")),
                            "submission_time": _clean(file_info.get("submissionTime") or document.get("submissionTime")),
                            "date_of_printing": _clean(document.get("dateOfPrinting") or document.get("dateOfPrint")),
                            "expected_file_size_bytes": file_info.get("fileSize") or document.get("fileSize"),
                            "download_endpoint": endpoint,
                            "manifest_status": "manifest_document",
                        }
                    )
                    rows.append(row)
                    source_urls.append(endpoint)
                    emitted += 1
            if emitted == 0:
                row = dict(base)
                row["manifest_status"] = "manifest_ok_no_documents"
                rows.append(row)
        except Exception as exc:
            base["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(base)
        if request_delay:
            time.sleep(max(0.0, float(request_delay)))

    frame = pd.DataFrame(rows, columns=SINO_SRPE_MANIFEST_COLUMNS)
    frame.attrs.update(
        raw_snapshots=raw_snapshots,
        source_urls=list(dict.fromkeys(source_urls)),
        lineage_metadata={
            "lineage_type": "official_srpe_sino_land_document_manifest",
            "company_id": SINO_LAND_PROFILE.developer_id,
            "ticker": SINO_LAND_PROFILE.normalized_ticker,
            "max_projects": int(max_projects),
            "pdf_downloaded": False,
            "missing_data_policy": "unknown_is_not_zero; no_srpe_is_not_no_sales",
        },
    )
    return frame


def fetch_sino_srpe_transaction_events(
    manifest: pd.DataFrame,
    sales_queue: pd.DataFrame | None = None,
    *,
    price_lists: pd.DataFrame | None = None,
    session: requests.Session | None = None,
    timeout: float = 60,
    max_documents: int = 8,
    request_delay: float = 0.2,
) -> dict[str, pd.DataFrame]:
    """Download and parse the latest transaction register per eligible phase.

    This is deliberately a transaction-fact lane, not an ownership or revenue
    attribution lane.  The latest register is normally a cumulative project
    history; repeated identical ``transaction_id`` values across register
    versions are removed, while distinct price revisions, re-sales and
    cancellations remain separate events.  Missing/failed registers are
    represented in the coverage and audit frames rather than converted to
    zero sales.
    """
    client = session or requests.Session()
    fetched_at = datetime.now(timezone.utc).isoformat()
    client.headers.update(
        {
            **DEFAULT_HEADERS,
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Content-Type": "application/json",
            "Origin": "https://www.srpe.gov.hk",
            "Referer": "https://www.srpe.gov.hk/opip/",
        }
    )
    manifest_frame = manifest.copy() if manifest is not None else pd.DataFrame()
    all_transaction_docs = (
        manifest_frame.loc[
            manifest_frame.get("manifest_status", pd.Series(index=manifest_frame.index, dtype="string")).eq(
                "manifest_document"
            )
            & manifest_frame.get("document_category", pd.Series(index=manifest_frame.index, dtype="string")).eq(
                "register_of_transactions"
            )
        ].copy()
        if not manifest_frame.empty
        else pd.DataFrame(columns=SINO_SRPE_MANIFEST_COLUMNS)
    )
    transaction_docs = all_transaction_docs.copy()
    if not transaction_docs.empty:
        transaction_docs["_submission_sort"] = pd.to_datetime(
            transaction_docs.get("submission_time"), errors="coerce", utc=True
        )
        # A later register is normally cumulative.  Keep one latest document
        # per phase to avoid re-downloading every historical register on each
        # scheduled refresh; event-level dedupe remains a second safety net.
        transaction_docs = (
            transaction_docs.sort_values(
                ["srpe_development_id", "_submission_sort", "document_id"],
                na_position="first",
            )
            .drop_duplicates(subset=["srpe_development_id"], keep="last")
            .sort_values("_submission_sort", na_position="first")
            .head(max(0, int(max_documents)))
            .drop(columns=["_submission_sort"], errors="ignore")
        )

    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    event_frames: list[pd.DataFrame] = []
    audit_rows: list[dict[str, Any]] = []
    doc_state: dict[str, dict[str, Any]] = {}

    for record in transaction_docs.to_dict("records"):
        project_id = _clean(record.get("canonical_project_id"))
        project_label = _clean(record.get("project_label"))
        development_id = _clean(record.get("srpe_development_id"))
        document_id = _clean(record.get("document_id"))
        source_url = _clean(record.get("download_endpoint")) or f"{SRPE_API_BASE}/download/{SRPE_DOWNLOAD_ACTIONS['register_of_transactions']}"
        state = doc_state.setdefault(
            development_id or project_id or document_id or "unknown",
            {
                "download_status": "not_attempted",
                "parse_status": "not_attempted",
                "parsed_event_rows": 0,
                "document_id": document_id,
                "submission_time": _clean(record.get("submission_time")),
                "error": None,
            },
        )
        audit = {
            "company_id": SINO_LAND_PROFILE.developer_id,
            "ticker": SINO_LAND_PROFILE.normalized_ticker,
            "canonical_project_id": project_id,
            "project_label": project_label,
            "srpe_development_id": development_id,
            "document_id": document_id,
            "file_name": _clean(record.get("file_name")),
            "submission_time": _clean(record.get("submission_time")),
            "expected_file_size_bytes": record.get("expected_file_size_bytes"),
            "actual_file_size_bytes": None,
            "download_status": "error",
            "parse_status": "not_attempted",
            "raw_snapshot_path": None,
            "raw_rows": 0,
            "dedup_rows": 0,
            "cross_document_duplicate_rows_removed": 0,
            "error": None,
            "source_url": source_url,
            "observed_at": fetched_at,
            "missing_data_policy": "unknown_is_not_zero; no_srpe_is_not_no_sales",
        }
        try:
            if not development_id or not document_id:
                raise ValueError("transaction register is missing development or document id")
            content = download_srpe_document(
                "register_of_transactions",
                document_id,
                development_id,
                session=client,
                timeout=timeout,
            )
            raw_path = save_raw_snapshot(
                f"sino_land_srpe_transaction_{development_id}_{document_id}",
                content,
                file_ext="pdf",
                source_url=source_url,
            )
            raw_snapshots.append(str(raw_path))
            source_urls.append(source_url)
            audit["download_status"] = "downloaded"
            audit["actual_file_size_bytes"] = len(content)
            audit["raw_snapshot_path"] = str(raw_path)
            parsed = parse_srpe_transaction_pdf(
                content,
                development_id=development_id,
                development_name=project_label,
                phase_name=_clean(record.get("srpe_phase_name")),
                document_id=document_id,
                document_serial_no=_clean(record.get("document_serial_no")),
                source_document=_clean(record.get("file_name")),
            )
            audit["raw_rows"] = int(len(parsed))
            if parsed.empty:
                audit["parse_status"] = "parsed_empty"
                state.update(download_status="downloaded", parse_status="parsed_empty", parsed_event_rows=0)
            else:
                parsed = parsed.copy()
                parsed["company_id"] = SINO_LAND_PROFILE.developer_id
                parsed["ticker"] = SINO_LAND_PROFILE.normalized_ticker
                parsed["canonical_project_id"] = project_id
                parsed["project_label"] = project_label
                parsed["srpe_phase_name"] = _clean(record.get("srpe_phase_name"))
                parsed["source_url"] = source_url
                parsed["raw_snapshot_path"] = str(raw_path)
                parsed["observed_at"] = fetched_at
                parsed["missing_data_policy"] = "unknown_is_not_zero; no_srpe_is_not_no_sales"
                event_frames.append(parsed)
                audit["parse_status"] = "parsed"
                state.update(download_status="downloaded", parse_status="parsed", parsed_event_rows=int(len(parsed)))
            audit["dedup_rows"] = int(audit["raw_rows"])
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            audit["error"] = message
            state.update(download_status="error", parse_status="not_attempted", error=message)
        audit_rows.append(audit)
        if request_delay:
            time.sleep(max(0.0, float(request_delay)))

    if event_frames:
        event_frame = pd.concat(event_frames, ignore_index=True, sort=False)
        duplicate_mask = event_frame["transaction_id"].duplicated(keep="last")
        duplicate_count = int(duplicate_mask.sum())
        event_frame = event_frame.loc[~duplicate_mask].reset_index(drop=True)
    else:
        event_frame = pd.DataFrame(columns=[*TRANSACTION_COLUMNS, "company_id", "ticker", "canonical_project_id", "project_label", "srpe_phase_name", "source_url", "raw_snapshot_path", "observed_at", "missing_data_policy"])
        duplicate_count = 0
    if audit_rows and duplicate_count:
        # The raw parser count remains visible per document; record the
        # cross-document collapse separately rather than misattributing it to
        # the first register.
        audit_rows[0]["cross_document_duplicate_rows_removed"] = duplicate_count
    audit_frame = pd.DataFrame(audit_rows, columns=SINO_SRPE_TRANSACTION_AUDIT_COLUMNS)

    aligned_price_lists = price_lists
    if price_lists is not None and not price_lists.empty and not event_frame.empty:
        # SRPE sometimes omits the phase in the manifest and the two PDF
        # parsers then recover different statutory placeholders (for example
        # ``-`` versus ``--``).  Development ID is the stable phase-level key;
        # align the optional phase label to the transaction register before
        # joining inventory, otherwise a valid denominator would disappear.
        aligned_price_lists = price_lists.copy()
        if "development_id" in aligned_price_lists.columns and "development_id" in event_frame.columns:
            phase_map = (
                event_frame.loc[event_frame["development_id"].notna(), ["development_id", "phase_name"]]
                .drop_duplicates("development_id")
                .set_index("development_id")["phase_name"]
                .to_dict()
            )
            aligned_price_lists["phase_name"] = aligned_price_lists.apply(
                lambda row: phase_map.get(row.get("development_id"), row.get("phase_name")),
                axis=1,
            )
    monthly = build_srpe_sales_signals(event_frame, price_lists=aligned_price_lists)
    if not monthly.empty:
        labels = (
            event_frame[["development_id", "canonical_project_id", "project_label"]]
            .drop_duplicates("development_id")
        )
        monthly = monthly.merge(labels, on="development_id", how="left")
        monthly["company_id"] = SINO_LAND_PROFILE.developer_id
        monthly["ticker"] = SINO_LAND_PROFILE.normalized_ticker
        monthly["coverage_status"] = "observed_transactions"
        monthly["missing_data_policy"] = "unknown_is_not_zero; no_srpe_is_not_no_sales"
        monthly["observed_at"] = fetched_at

    eligible_queue = sales_queue.copy() if sales_queue is not None else pd.DataFrame()
    if not eligible_queue.empty:
        eligible_queue = eligible_queue.loc[
            eligible_queue.get("queue_status", pd.Series(index=eligible_queue.index, dtype="string")).eq(
                "eligible_for_recent_srpe_queue"
            )
        ].drop_duplicates(subset=["canonical_project_id"], keep="last")
    coverage_rows: list[dict[str, Any]] = []
    for record in eligible_queue.to_dict("records"):
        project_id = _clean(record.get("canonical_project_id"))
        development_id = _clean(record.get("srpe_development_id"))
        state = doc_state.get(development_id or project_id, {})
        project_docs = all_transaction_docs.loc[
            all_transaction_docs.get("canonical_project_id", pd.Series(index=all_transaction_docs.index, dtype="string")).eq(project_id)
        ] if not all_transaction_docs.empty else pd.DataFrame()
        doc_ids = [_clean(value) for value in project_docs.get("document_id", pd.Series(dtype="string")).tolist() if _clean(value)]
        if not doc_ids:
            coverage_status = "manifest_no_transaction_register"
            download_status = "not_observed"
            parse_status = "not_observed"
        elif development_id not in doc_state and project_id not in doc_state:
            coverage_status = "transaction_document_not_selected"
            download_status = "not_attempted"
            parse_status = "not_attempted"
        elif state.get("download_status") == "error":
            coverage_status = "transaction_download_error"
            download_status = "error"
            parse_status = "not_attempted"
        elif state.get("parse_status") == "parsed_empty":
            coverage_status = "transaction_parse_empty"
            download_status = "downloaded"
            parse_status = "parsed_empty"
        else:
            coverage_status = "observed_transaction_register"
            download_status = state.get("download_status", "not_attempted")
            parse_status = state.get("parse_status", "not_attempted")
        coverage_rows.append(
            {
                "company_id": SINO_LAND_PROFILE.developer_id,
                "ticker": SINO_LAND_PROFILE.normalized_ticker,
                "canonical_project_id": project_id,
                "project_label": _clean(record.get("project_label")),
                "srpe_development_id": development_id,
                "srpe_phase_name": _clean(record.get("srpe_phase_name")),
                "queue_status": _clean(record.get("queue_status")),
                "transaction_document_count": len(doc_ids),
                "transaction_document_ids_json": json.dumps(doc_ids, ensure_ascii=False),
                "coverage_status": coverage_status,
                "download_status": download_status,
                "parse_status": parse_status,
                "parsed_event_rows": int(state.get("parsed_event_rows", 0)),
                "last_document_submission_time": (
                    project_docs.get("submission_time", pd.Series(dtype="string")).dropna().astype(str).max()
                    if not project_docs.empty
                    else None
                ),
                "observed_at": fetched_at,
                "missing_data_policy": "unknown_is_not_zero; no_srpe_is_not_no_sales",
            }
        )
    coverage_frame = pd.DataFrame(coverage_rows, columns=SINO_SRPE_TRANSACTION_COVERAGE_COLUMNS)
    for frame in (event_frame, monthly, audit_frame, coverage_frame):
        frame.attrs.update(
            raw_snapshots=raw_snapshots,
            source_urls=list(dict.fromkeys(source_urls)),
            lineage_metadata={
                "lineage_type": "official_srpe_sino_land_transaction_facts",
                "company_id": SINO_LAND_PROFILE.developer_id,
                "ticker": SINO_LAND_PROFILE.normalized_ticker,
                "latest_register_per_phase": True,
                "cross_document_duplicate_rows_removed": duplicate_count,
                "pdf_downloaded": True,
                "missing_data_policy": "unknown_is_not_zero; no_srpe_is_not_no_sales",
            },
        )
    return {
        "transaction_events": event_frame,
        "monthly_signals": monthly,
        "document_audit": audit_frame,
        "coverage": coverage_frame,
    }


def fetch_sino_srpe_price_list_inventory(
    manifest: pd.DataFrame,
    sales_queue: pd.DataFrame | None = None,
    *,
    session: requests.Session | None = None,
    timeout: float = 60,
    max_documents: int = 8,
    request_delay: float = 0.2,
) -> dict[str, pd.DataFrame]:
    """Download the latest price list per eligible phase and parse inventory.

    A statutory price list is a snapshot of the units and prices offered in a
    particular filing, not a complete unsold-inventory feed.  The parser keeps
    unit rows and the document's ``total_residential_properties`` separately;
    sell-through denominators are populated only when that total is explicitly
    present in the PDF.  A parsed list with no explicit total is therefore
    useful evidence, but is not silently promoted to a full inventory count.
    """
    client = session or requests.Session()
    fetched_at = datetime.now(timezone.utc).isoformat()
    client.headers.update(
        {
            **DEFAULT_HEADERS,
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Content-Type": "application/json",
            "Origin": "https://www.srpe.gov.hk",
            "Referer": "https://www.srpe.gov.hk/opip/",
        }
    )
    policy = "unknown_is_not_zero; no_srpe_is_not_no_sales"
    manifest_frame = manifest.copy() if manifest is not None else pd.DataFrame()
    all_price_docs = (
        manifest_frame.loc[
            manifest_frame.get("manifest_status", pd.Series(index=manifest_frame.index, dtype="string")).eq(
                "manifest_document"
            )
            & manifest_frame.get("document_category", pd.Series(index=manifest_frame.index, dtype="string")).eq(
                "price_list"
            )
        ].copy()
        if not manifest_frame.empty
        else pd.DataFrame(columns=SINO_SRPE_MANIFEST_COLUMNS)
    )
    price_docs = all_price_docs.copy()
    if not price_docs.empty:
        price_docs["_submission_sort"] = pd.to_datetime(
            price_docs.get("submission_time"), errors="coerce", utc=True
        )
        price_docs = (
            price_docs.sort_values(
                ["srpe_development_id", "_submission_sort", "document_id"],
                na_position="first",
            )
            .drop_duplicates(subset=["srpe_development_id"], keep="last")
            .sort_values("_submission_sort", na_position="first")
            .head(max(0, int(max_documents)))
            .drop(columns=["_submission_sort"], errors="ignore")
        )

    raw_snapshots: list[str] = []
    source_urls: list[str] = []
    unit_frames: list[pd.DataFrame] = []
    audit_rows: list[dict[str, Any]] = []
    doc_state: dict[str, dict[str, Any]] = {}
    for record in price_docs.to_dict("records"):
        project_id = _clean(record.get("canonical_project_id"))
        project_label = _clean(record.get("project_label"))
        development_id = _clean(record.get("srpe_development_id"))
        document_id = _clean(record.get("document_id"))
        source_url = _clean(record.get("download_endpoint")) or (
            f"{SRPE_API_BASE}/download/{SRPE_DOWNLOAD_ACTIONS['price_list']}"
        )
        state = doc_state.setdefault(
            development_id or project_id or document_id or "unknown",
            {
                "download_status": "not_attempted",
                "parse_status": "not_attempted",
                "parsed_unit_rows": 0,
                "total_residential_properties": None,
                "error": None,
            },
        )
        audit = {
            "company_id": SINO_LAND_PROFILE.developer_id,
            "ticker": SINO_LAND_PROFILE.normalized_ticker,
            "canonical_project_id": project_id,
            "project_label": project_label,
            "srpe_development_id": development_id,
            "document_id": document_id,
            "file_name": _clean(record.get("file_name")),
            "submission_time": _clean(record.get("submission_time")),
            "date_of_printing": _clean(record.get("date_of_printing")),
            "expected_file_size_bytes": record.get("expected_file_size_bytes"),
            "actual_file_size_bytes": None,
            "download_status": "error",
            "parse_status": "not_attempted",
            "raw_snapshot_path": None,
            "raw_rows": 0,
            "dedup_rows": 0,
            "total_residential_properties": None,
            "error": None,
            "source_url": source_url,
            "observed_at": fetched_at,
            "missing_data_policy": policy,
        }
        try:
            if not development_id or not document_id:
                raise ValueError("price list is missing development or document id")
            content = download_srpe_document(
                "price_list",
                document_id,
                development_id,
                session=client,
                timeout=timeout,
            )
            raw_path = save_raw_snapshot(
                f"sino_land_srpe_price_list_{development_id}_{document_id}",
                content,
                file_ext="pdf",
                source_url=source_url,
            )
            raw_snapshots.append(str(raw_path))
            source_urls.append(source_url)
            audit["download_status"] = "downloaded"
            audit["actual_file_size_bytes"] = len(content)
            audit["raw_snapshot_path"] = str(raw_path)
            parsed = parse_srpe_price_list_pdf(
                content,
                development_id=development_id,
                development_name=project_label,
                phase_name=_clean(record.get("srpe_phase_name")),
                document_id=document_id,
                document_serial_no=_clean(record.get("document_serial_no")),
                source_document=_clean(record.get("file_name")),
            )
            audit["raw_rows"] = int(len(parsed))
            if parsed.empty:
                audit["parse_status"] = "parsed_empty"
                state.update(download_status="downloaded", parse_status="parsed_empty", parsed_unit_rows=0)
            else:
                parsed = parsed.copy()
                # Keep the manifest identity as the join key used by the
                # transaction layer, even if a bilingual PDF header differs.
                parsed["development_id"] = development_id
                parsed["development_name"] = project_label
                parsed["phase_name"] = _clean(record.get("srpe_phase_name")) or parsed["phase_name"]
                parsed["company_id"] = SINO_LAND_PROFILE.developer_id
                parsed["ticker"] = SINO_LAND_PROFILE.normalized_ticker
                parsed["canonical_project_id"] = project_id
                parsed["project_label"] = project_label
                parsed["source_url"] = source_url
                parsed["raw_snapshot_path"] = str(raw_path)
                parsed["observed_at"] = fetched_at
                parsed["missing_data_policy"] = policy
                parsed["inventory_unit_key"] = parsed["unit_key"].astype(str).str.strip()
                parsed = parsed.drop_duplicates(
                    subset=["development_id", "inventory_unit_key"], keep="last"
                ).reset_index(drop=True)
                numeric_total = pd.to_numeric(
                    parsed.get("total_residential_properties"), errors="coerce"
                ).dropna()
                total = float(numeric_total.max()) if not numeric_total.empty else None
                if total is not None and total.is_integer():
                    total = int(total)
                parsed["total_residential_properties"] = total
                audit["parse_status"] = "parsed"
                audit["dedup_rows"] = int(len(parsed))
                audit["total_residential_properties"] = total
                state.update(
                    download_status="downloaded",
                    parse_status="parsed",
                    parsed_unit_rows=int(len(parsed)),
                    total_residential_properties=total,
                )
                unit_frames.append(parsed)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            audit["error"] = message
            state.update(download_status="error", parse_status="not_attempted", error=message)
        audit_rows.append(audit)
        if request_delay:
            time.sleep(max(0.0, float(request_delay)))

    unit_columns = [
        *PRICE_LIST_COLUMNS,
        "company_id",
        "ticker",
        "canonical_project_id",
        "project_label",
        "source_url",
        "raw_snapshot_path",
        "observed_at",
        "missing_data_policy",
        "inventory_unit_key",
    ]
    if unit_frames:
        unit_frame = pd.concat(unit_frames, ignore_index=True, sort=False).reindex(columns=unit_columns)
    else:
        unit_frame = pd.DataFrame(columns=unit_columns)
    audit_frame = pd.DataFrame(audit_rows, columns=SINO_SRPE_PRICE_LIST_AUDIT_COLUMNS)

    eligible_queue = sales_queue.copy() if sales_queue is not None else pd.DataFrame()
    if not eligible_queue.empty:
        eligible_queue = eligible_queue.loc[
            eligible_queue.get("queue_status", pd.Series(index=eligible_queue.index, dtype="string")).eq(
                "eligible_for_recent_srpe_queue"
            )
        ].drop_duplicates(subset=["canonical_project_id"], keep="last")
    coverage_rows: list[dict[str, Any]] = []
    for record in eligible_queue.to_dict("records"):
        project_id = _clean(record.get("canonical_project_id"))
        development_id = _clean(record.get("srpe_development_id"))
        state = doc_state.get(development_id or project_id, {})
        project_docs = (
            all_price_docs.loc[
                all_price_docs.get("canonical_project_id", pd.Series(index=all_price_docs.index, dtype="string")).eq(project_id)
            ]
            if not all_price_docs.empty
            else pd.DataFrame()
        )
        doc_ids = [
            _clean(value)
            for value in project_docs.get("document_id", pd.Series(dtype="string")).tolist()
            if _clean(value)
        ]
        if not doc_ids:
            coverage_status = "manifest_no_price_list"
            download_status = "not_observed"
            parse_status = "not_observed"
        elif development_id not in doc_state and project_id not in doc_state:
            coverage_status = "price_list_document_not_selected"
            download_status = "not_attempted"
            parse_status = "not_attempted"
        elif state.get("download_status") == "error":
            coverage_status = "price_list_download_error"
            download_status = "error"
            parse_status = "not_attempted"
        elif state.get("parse_status") == "parsed_empty":
            coverage_status = "price_list_parse_empty"
            download_status = "downloaded"
            parse_status = "parsed_empty"
        else:
            coverage_status = "observed_price_list"
            download_status = state.get("download_status", "not_attempted")
            parse_status = state.get("parse_status", "not_attempted")
        total = state.get("total_residential_properties")
        inventory_status = (
            "total_units_observed" if total is not None else
            "unit_rows_observed_total_unknown" if state.get("parsed_unit_rows", 0) else
            "not_observed"
        )
        coverage_rows.append(
            {
                "company_id": SINO_LAND_PROFILE.developer_id,
                "ticker": SINO_LAND_PROFILE.normalized_ticker,
                "canonical_project_id": project_id,
                "project_label": _clean(record.get("project_label")),
                "srpe_development_id": development_id,
                "srpe_phase_name": _clean(record.get("srpe_phase_name")),
                "queue_status": _clean(record.get("queue_status")),
                "price_list_document_count": len(doc_ids),
                "price_list_document_ids_json": json.dumps(doc_ids, ensure_ascii=False),
                "coverage_status": coverage_status,
                "download_status": download_status,
                "parse_status": parse_status,
                "parsed_unit_rows": int(state.get("parsed_unit_rows", 0)),
                "total_residential_properties": total,
                "inventory_status": inventory_status,
                "last_document_submission_time": (
                    project_docs.get("submission_time", pd.Series(dtype="string")).dropna().astype(str).max()
                    if not project_docs.empty
                    else None
                ),
                "observed_at": fetched_at,
                "missing_data_policy": policy,
            }
        )
    coverage_frame = pd.DataFrame(coverage_rows, columns=SINO_SRPE_PRICE_LIST_COVERAGE_COLUMNS)

    for frame in (unit_frame, audit_frame, coverage_frame):
        frame.attrs.update(
            raw_snapshots=raw_snapshots,
            source_urls=list(dict.fromkeys(source_urls)),
            lineage_metadata={
                "lineage_type": "official_srpe_sino_land_price_list_inventory",
                "company_id": SINO_LAND_PROFILE.developer_id,
                "ticker": SINO_LAND_PROFILE.normalized_ticker,
                "latest_price_list_per_phase": True,
                "pdf_downloaded": True,
                "sell_through_denominator_policy": "explicit_total_residential_properties_only",
                "missing_data_policy": policy,
            },
        )
    return {
        "price_list_units": unit_frame,
        "document_audit": audit_frame,
        "coverage": coverage_frame,
    }


def fetch_sino_pipeline_disclosures(
    *,
    session: requests.Session | None = None,
    timeout: float = 60,
    annual_report_url: str = SINO_ANNUAL_REPORT_2025_URL,
    report_id: str = "sino_ar_2025",
) -> pd.DataFrame:
    """Extract the issuer's explicitly named Hong Kong launch pipeline."""
    client = session or requests.Session()
    client.headers.update({**DEFAULT_HEADERS, "Accept": "application/pdf, */*"})
    fetched_at = datetime.now(timezone.utc).isoformat()
    response = client.get(annual_report_url, timeout=timeout)
    raw_body = getattr(response, "content", b"")
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")
    raw_path = save_raw_snapshot("sino_land_annual_report_2025", raw_body or b"", file_ext="pdf", source_url=annual_report_url)
    response.raise_for_status()
    if not raw_body or not raw_body.strip():
        raise ValueError("Sino annual report returned an empty body")
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is in pyproject
        raise RuntimeError("pypdf is required for Sino annual-report pipeline extraction") from exc
    reader = PdfReader(BytesIO(raw_body))
    page_texts = [(index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages)]
    full_text = "\n".join(text for _, text in page_texts)
    page_offsets: list[tuple[int, int, int]] = []
    cursor = 0
    for page, text in page_texts:
        page_offsets.append((page, cursor, cursor + len(text)))
        cursor += len(text) + 1
    rows: list[dict[str, Any]] = []
    for label, state in SINO_PIPELINE_PROJECT_HINTS:
        label_pattern = re.sub(r"\\ ", r"\\s+", re.escape(label)).replace("/", r"\s*/\s*")
        matches = list(re.finditer(label_pattern, full_text, flags=re.IGNORECASE))
        if matches:
            # A launch-summary occurrence can precede the detailed project
            # description. Prefer the occurrence that carries explicit JV /
            # equity evidence, while retaining the first occurrence as a
            # deterministic fallback.
            candidates: list[tuple[int, int, str]] = []
            for match in matches:
                start = max(0, match.start() - 240)
                candidate_context = re.sub(r"\s+", " ", full_text[start: match.end() + 500]).strip()
                score = (
                    4 * int("equity interest" in candidate_context.casefold())
                    + 2 * int("joint venture" in candidate_context.casefold())
                    + int("development" in candidate_context.casefold())
                )
                candidates.append((score, -match.start(), candidate_context))
            _, negative_offset, context = max(candidates, key=lambda item: (item[0], item[1]))
            chosen_offset = -negative_offset
            page_number = next((page for page, start, end in page_offsets if start <= chosen_offset < end), None)
            if page_number is None:
                page_number = next((page for page, text in page_texts if label.casefold() in text.casefold()), None)
            evidence_status = "found"
        else:
            context = ""
            page_number = None
            evidence_status = "not_found"
        group_equity_interest_pct = _extract_group_equity_interest(context)
        rows.append(
            {
                "pipeline_registry_key": f"{SINO_LAND_PROFILE.developer_id}:{report_id}:{re.sub(r'[^a-z0-9]+', '', label.casefold())}",
                "company_id": SINO_LAND_PROFILE.developer_id,
                "ticker": SINO_LAND_PROFILE.normalized_ticker,
                "project_label": label,
                "project_state": state,
                "asset_scope": "residential_first_hand",
                "geography": "Hong Kong",
                "publication_date": "2025-09-25",
                "expected_launch_window": "issuer pipeline; timing subject to pre-sale consent and market conditions",
                "expected_completion_window": None,
                "srpe_candidate_ids": None,
                "linked_srpe_development_id": None,
                "srpe_match_status": "not_evaluated",
                "evidence_status": evidence_status,
                "evidence_context": context,
                "source_url": annual_report_url,
                "source_urls_json": json.dumps([annual_report_url, SINO_ANNUAL_REPORT_2025_HKEX_URL], ensure_ascii=False),
                "source_dataset": "sino_land_annual_report_pipeline",
                "observed_at": fetched_at,
                "missing_data_policy": "unknown_is_not_zero; no_srpe_is_not_no_sales",
                "annual_report_id": report_id,
                "annual_report_page": page_number,
                "group_equity_interest_pct": group_equity_interest_pct,
            }
        )
    frame = pd.DataFrame(rows, columns=SINO_PIPELINE_DISCLOSURE_COLUMNS)
    frame.attrs.update(
        raw_snapshots=[str(raw_path)],
        source_urls=[annual_report_url, SINO_ANNUAL_REPORT_2025_HKEX_URL],
        lineage_metadata={
            "lineage_type": "official_sino_land_annual_report_pipeline",
            "company_id": SINO_LAND_PROFILE.developer_id,
            "ticker": SINO_LAND_PROFILE.normalized_ticker,
            "report_id": report_id,
            "parser_policy": "explicit_project_anchor_search_only",
            "ownership_inference": False,
        },
    )
    return frame


def run_sino_land_tracking(
    *,
    session: requests.Session | None = None,
    timeout: float = 60,
    max_pages: int | None = None,
    max_site_projects: int = 0,
    max_srpe_manifest_projects: int = 8,
    max_srpe_transaction_documents: int = 8,
    max_srpe_price_list_documents: int = 8,
    srpe_request_delay: float = 0.2,
    persist: bool = True,
) -> dict[str, Any]:
    """Run and optionally persist the Sino Land minimum viable tracking set."""
    client = session or requests.Session()
    run_id = datetime.now(timezone.utc).strftime("sino-%Y%m%dT%H%M%S%fZ")
    catalog = fetch_sino_property_catalog(session=client, timeout=timeout, max_pages=max_pages)
    srpe = load_latest_normalized("srpe_development_index")
    registry_path = REGISTRY_DIR / "hk_developer_project_registry.csv"
    registry = pd.read_csv(registry_path, dtype=str).fillna("") if registry_path.exists() else pd.DataFrame()
    identity = build_developer_identity_crosswalk(
        SINO_LAND_PROFILE,
        catalog,
        srpe,
        registry=registry,
        source_dataset="sino_land_property_catalog",
    )
    pipeline = fetch_sino_pipeline_disclosures(session=client, timeout=timeout)
    pipeline_lineage = {
        "raw_snapshots": list(pipeline.attrs.get("raw_snapshots") or []),
        "source_urls": list(pipeline.attrs.get("source_urls") or []),
        "lineage_metadata": dict(pipeline.attrs.get("lineage_metadata") or {}),
    }
    pipeline_identity = build_developer_identity_crosswalk(
        SINO_LAND_PROFILE,
        pipeline,
        srpe,
        registry=registry,
        source_dataset="sino_land_annual_report_pipeline",
    )
    if not pipeline_identity.empty and "group_equity_interest_pct" in pipeline.columns:
        pipeline_ownership = pipeline.set_index("project_label")["group_equity_interest_pct"].to_dict()
        report_ownership = pd.to_numeric(
            pipeline_identity["project_label"].map(pipeline_ownership), errors="coerce"
        )
        existing_ownership = pd.to_numeric(pipeline_identity["ownership_pct_snapshot"], errors="coerce")
        resolved_ownership = existing_ownership.where(existing_ownership.notna(), report_ownership)
        pipeline_identity["ownership_pct_snapshot"] = resolved_ownership
        pipeline_identity.loc[resolved_ownership.notna(), "ownership_scenario_status"] = "observed_snapshot_not_interval"
    # Attach a unique exact SRPE link from the crosswalk to pipeline rows.  An
    # ambiguous row remains null and therefore stays out of the sales queue.
    if not pipeline.empty and not pipeline_identity.empty:
        links = pipeline_identity[["project_label", "srpe_development_id", "match_status"]].copy()
        links = links.rename(columns={"srpe_development_id": "linked_srpe_development_id", "match_status": "srpe_match_status"})
        pipeline = pipeline.drop(columns=["linked_srpe_development_id", "srpe_match_status"], errors="ignore").merge(
            links, on="project_label", how="left"
        )
        # pandas merge drops DataFrame.attrs; restore the official annual
        # report lineage before the frame is persisted.
        pipeline.attrs.update(pipeline_lineage)
    # Build from records rather than pandas concat: several identity fields
    # are legitimately all-NA for a pipeline row, and concat's dtype
    # inference currently emits a noisy FutureWarning for that case.
    combined_identity = pd.DataFrame(
        identity.to_dict("records") + pipeline_identity.to_dict("records"),
        columns=DEVELOPER_IDENTITY_COLUMNS,
    )
    combined_identity.attrs.update(
        raw_snapshots=(list(catalog.attrs.get("raw_snapshots") or []) + pipeline_lineage["raw_snapshots"]),
        source_urls=(list(catalog.attrs.get("source_urls") or []) + pipeline_lineage["source_urls"]),
        lineage_metadata={
            "lineage_type": "sino_land_identity_crosswalk",
            "company_id": SINO_LAND_PROFILE.developer_id,
            "ticker": SINO_LAND_PROFILE.normalized_ticker,
            "catalog_match_policy": "exact_normalized_name_or_explicit_registry_alias_only",
            "ownership_inference": False,
        },
    )
    ownership = combined_identity.loc[
        combined_identity["srpe_development_id"].notna() & combined_identity["ownership_pct_snapshot"].notna(),
        ["srpe_development_id", "ownership_pct_snapshot"],
    ].rename(columns={"ownership_pct_snapshot": "ownership_pct"})
    events = build_developer_project_events(
        SINO_LAND_PROFILE,
        pipeline=pipeline,
        identity=combined_identity,
        srpe_index=srpe,
        property_catalog=catalog,
        ownership_observations=ownership,
    )
    prior = load_latest_normalized("sino_land_project_events")
    if not prior.empty:
        events = build_developer_project_events(
            SINO_LAND_PROFILE,
            pipeline=pipeline,
            identity=combined_identity,
            srpe_index=srpe,
            property_catalog=catalog,
            prior_events=prior,
            ownership_observations=ownership,
        )
    snapshot = build_developer_project_snapshot(SINO_LAND_PROFILE, events)
    queue = build_developer_sales_queue(SINO_LAND_PROFILE, snapshot, srpe)
    srpe_manifest = fetch_sino_srpe_document_manifest(
        queue,
        session=client,
        timeout=min(timeout, 30),
        max_projects=max_srpe_manifest_projects,
        request_delay=srpe_request_delay,
    )
    price_list_layers = fetch_sino_srpe_price_list_inventory(
        srpe_manifest,
        queue,
        session=client,
        timeout=min(timeout, 60),
        max_documents=max_srpe_price_list_documents,
        request_delay=srpe_request_delay,
    )
    transaction_layers = fetch_sino_srpe_transaction_events(
        srpe_manifest,
        queue,
        price_lists=price_list_layers["price_list_units"],
        session=client,
        timeout=min(timeout, 60),
        max_documents=max_srpe_transaction_documents,
        request_delay=srpe_request_delay,
    )
    site_evidence = (
        fetch_sino_project_site_role_evidence(catalog, session=client, timeout=timeout, max_projects=max_site_projects)
        if max_site_projects > 0 else pd.DataFrame(columns=SINO_SITE_ROLE_COLUMNS)
    )
    lineage_raw_snapshots = list(catalog.attrs.get("raw_snapshots") or []) + pipeline_lineage["raw_snapshots"]
    lineage_source_urls = list(catalog.attrs.get("source_urls") or []) + pipeline_lineage["source_urls"]
    for frame in (events, snapshot, queue):
        frame.attrs.setdefault("raw_snapshots", lineage_raw_snapshots)
        frame.attrs.setdefault("source_urls", lineage_source_urls)
    srpe_manifest.attrs.setdefault("raw_snapshots", lineage_raw_snapshots + list(srpe_manifest.attrs.get("raw_snapshots") or []))
    srpe_manifest.attrs.setdefault("source_urls", lineage_source_urls + list(srpe_manifest.attrs.get("source_urls") or []))
    frames = {
        "sino_land_property_catalog": catalog,
        "sino_land_project_identity_evidence": combined_identity,
        "sino_land_pipeline_disclosures": pipeline,
        "sino_land_project_events": events,
        "sino_land_project_snapshot": snapshot,
        "sino_land_sales_ingestion_queue": queue,
        "sino_land_srpe_document_manifest": srpe_manifest,
        "sino_land_srpe_price_list_units": price_list_layers["price_list_units"],
        "sino_land_srpe_price_list_document_audit": price_list_layers["document_audit"],
        "sino_land_srpe_price_list_coverage": price_list_layers["coverage"],
        "sino_land_srpe_transaction_events": transaction_layers["transaction_events"],
        "sino_land_srpe_monthly_signals": transaction_layers["monthly_signals"],
        "sino_land_srpe_transaction_document_audit": transaction_layers["document_audit"],
        "sino_land_srpe_transaction_coverage": transaction_layers["coverage"],
        "sino_land_project_site_role_evidence": site_evidence,
    }
    normalized: dict[str, Any] = {}
    if persist:
        for dataset_name, frame in frames.items():
            if frame.empty:
                normalized[dataset_name] = {"skipped": True, "records": 0, "reason": "empty frame not persisted"}
                continue
            normalized[dataset_name] = save_normalized_dataset(
                dataset_name,
                frame,
                run_id=run_id,
                raw_snapshots=frame.attrs.get("raw_snapshots"),
                source_urls=frame.attrs.get("source_urls"),
                lineage_metadata=frame.attrs.get("lineage_metadata"),
            )
    return {
        "run_id": run_id,
        "company_id": SINO_LAND_PROFILE.developer_id,
        "ticker": SINO_LAND_PROFILE.normalized_ticker,
        "dataset_counts": {name: int(len(frame)) for name, frame in frames.items()},
        "normalized": normalized,
        "fetch_summary": catalog.attrs.get("fetch_summary", []),
        "site_evidence_rows": int(len(site_evidence)),
        "active_queue_rows": int(queue["queue_status"].eq("eligible_for_recent_srpe_queue").sum()) if not queue.empty else 0,
        "srpe_manifest_rows": int(len(srpe_manifest)),
        "srpe_manifest_document_rows": int(srpe_manifest["manifest_status"].eq("manifest_document").sum()) if not srpe_manifest.empty else 0,
        "srpe_manifest_project_count": int(srpe_manifest["canonical_project_id"].nunique()) if not srpe_manifest.empty else 0,
        "srpe_transaction_manifest_project_count": (
            int(
                srpe_manifest.loc[
                    srpe_manifest["document_category"].eq("register_of_transactions"),
                    "canonical_project_id",
                ].nunique()
            )
            if not srpe_manifest.empty
            else 0
        ),
        "srpe_transaction_event_rows": int(len(transaction_layers["transaction_events"])),
        "srpe_transaction_monthly_signal_rows": int(len(transaction_layers["monthly_signals"])),
        "srpe_transaction_coverage_rows": int(len(transaction_layers["coverage"])),
        "srpe_price_list_unit_rows": int(len(price_list_layers["price_list_units"])),
        "srpe_price_list_coverage_rows": int(len(price_list_layers["coverage"])),
    }
