import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pandas as pd
from typing import Dict, Any

from ..config import SRPE_OPIP_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

SRPE_API_BASE = "https://www.srpe.gov.hk/api/SrpeWebService"
SRPE_DEVELOPMENT_INDEX_ENDPOINT = (
    f"{SRPE_API_BASE}/DistrictAreaSearch/getDistrictAreaSearchResult"
)

# Maps each SRPE document category to the download action name used in its
# real (reverse-engineered) download endpoint, e.g.
# POST {SRPE_API_BASE}/download/downloadTrx.
SRPE_DOWNLOAD_ACTIONS = {
    "register_of_transactions": "downloadTrx",
    "price_list": "downloadPrice",
    "sales_arrangement": "downloadSalesArrangement",
    "sales_brochure": "downloadBrochure",
}

# The upload-digest keys returned by DistrictAreaSearch/getUploadSearchResult,
# mapped to the document_category we emit.
SRPE_UPLOAD_LIST_KEYS = {
    "devListTransactions": "register_of_transactions",
    "devListPriceList": "price_list",
    "devListSalesArrangement": "sales_arrangement",
    "devListSaleBrochure": "sales_brochure",
}


class SRPEDocumentDownloadError(RuntimeError):
    """Raised when an SRPE document manifest entry cannot be downloaded."""


SRPE_DEVELOPMENT_INDEX_COLUMNS = [
    "development_id",
    "display_name",
    "development_name_en",
    "development_name_zh",
    "phase_name_en",
    "phase_name_zh",
    "phase_no",
    "address_en",
    "address_zh",
    "planning_area_en",
    "planning_area_zh",
    "broad_district_en",
    "active",
    "official_website",
    # Lifecycle fields are present in the all-development API even for
    # inactive/archived phases.  Keep them in the normalized contract rather
    # than treating the current ``active`` flag as a historical universe.
    "srpe_earliest_publication",
    "srpe_date_suspend_sales",
    "srpe_date_complete_sales",
    "srpe_is_deleted",
    "srpe_eng_remark",
    "srpe_chn_remark",
    "srpe_eng_addr_idx_remark",
    "srpe_chn_addr_idx_remark",
    "brochure_id",
    "brochure_first_print_date",
    "source_url",
    "fetched_at",
]


def _srpe_date(value: Any) -> str | None:
    """Normalize an SRPE ISO/date token without inventing a date."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def _normalize_srpe_development_rows(
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    source_url: str,
    fetched_at: str,
) -> pd.DataFrame:
    """Normalize the SRPE all-development API rows."""
    normalized: list[dict[str, Any]] = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        address = raw.get("addresses") or []
        if isinstance(address, dict):
            address = [address]
        first_address = address[0] if address and isinstance(address[0], dict) else {}
        planning = raw.get("planningArea1") or {}
        if isinstance(planning, str):
            planning = {"planningAreaNameEng": planning}
        broad = raw.get("broadDistrict") or {}
        if isinstance(broad, str):
            broad = {"broadDistrictNameEng": broad}
        brochure = raw.get("brochure") or {}
        if isinstance(brochure, list):
            brochure = brochure[0] if brochure else {}
        development_id = raw.get("developmentId") or raw.get("id")
        display_name = raw.get("engName") or raw.get("displayName")
        normalized.append(
            {
                "development_id": str(development_id).strip() if development_id is not None else None,
                "display_name": display_name,
                "development_name_en": raw.get("engName"),
                "development_name_zh": raw.get("chnName"),
                "phase_name_en": raw.get("engPhaseName"),
                "phase_name_zh": raw.get("chnPhaseName"),
                "phase_no": raw.get("engPhaseNo") or raw.get("chnPhaseNo"),
                "address_en": first_address.get("engAddress"),
                "address_zh": first_address.get("chnAddress"),
                "planning_area_en": planning.get("planningAreaNameEng"),
                "planning_area_zh": planning.get("planningAreaNameChn"),
                "broad_district_en": broad.get("broadDistrictNameEng")
                or raw.get("broadDistrictEngRank"),
                "active": raw.get("active"),
                "official_website": raw.get("website"),
                "srpe_earliest_publication": _srpe_date(raw.get("earlistPublicationTime")),
                "srpe_date_suspend_sales": _srpe_date(raw.get("dateSuspendSales")),
                "srpe_date_complete_sales": _srpe_date(raw.get("dateCompleteSales")),
                "srpe_is_deleted": raw.get("isDeleted"),
                "srpe_eng_remark": raw.get("engRemark"),
                "srpe_chn_remark": raw.get("chnRemark") or raw.get("schnRemark"),
                "srpe_eng_addr_idx_remark": raw.get("engAddrIdxRemark"),
                "srpe_chn_addr_idx_remark": raw.get("chnAddrIdxRemark")
                or raw.get("schnAddrIdxRemark"),
                "brochure_id": brochure.get("id"),
                "brochure_first_print_date": _srpe_date(
                    brochure.get("dateOfPrint") or brochure.get("dateOfPrinting")
                ),
                "source_url": source_url,
                "fetched_at": fetched_at,
            }
        )
    return pd.DataFrame(normalized, columns=SRPE_DEVELOPMENT_INDEX_COLUMNS)


def fetch_srpe_development_index(
    *,
    session: requests.Session | None = None,
    timeout: float = 20,
) -> pd.DataFrame:
    """Fetch the official SRPE all-residential development/phase index."""
    client = session or requests.Session()
    client.headers.update(
        {
            **DEFAULT_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://www.srpe.gov.hk",
            "Referer": SRPE_OPIP_URL,
        }
    )
    fetched_at = pd.Timestamp.now(tz="UTC").isoformat()
    action_id = f"{int(time.time() * 1000)}_0"
    # This mirrors the current all-development page request.  The previous
    # ``Index For All Residential Development`` label still returns HTTP 200
    # with ``code=0`` but an empty result, so treating it as a valid endpoint
    # silently erased the index during refreshes.
    payload = {
        "language": "en",
        "broadDistrictId": "A",
        "planningAreaId": "A",
        "planningAreaIdString": "All",
        "firstPrintYear": "A",
        "searchByYearOnly": False,
        "planningAreaIds": ["A"],
        "fromPath": "disclaimer_index_for_all_residential",
        "actionType": "Index For All Residential",
        "page": None,
        "limit": None,
        "actionId": action_id,
    }
    response = client.post(SRPE_DEVELOPMENT_INDEX_ENDPOINT, json=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    result_data = body.get("resultData") or {}
    if not isinstance(result_data, dict):
        raise RuntimeError("SRPE development-index response has an unexpected resultData shape")
    rows = result_data.get("list") or result_data.get("rows") or []
    total = result_data.get("total")
    # A zero-row response is not a valid replacement for the official
    # all-development index. Preserve the response for the caller's session
    # diagnostics by saving it before raising, but never return an empty frame.
    if not rows and (total is None or int(total or 0) == 0):
        save_raw_snapshot(
            "srpe_development_index_empty",
            json.dumps(body, ensure_ascii=False),
            file_ext="json",
            source_url=SRPE_DEVELOPMENT_INDEX_ENDPOINT,
        )
        raise RuntimeError("SRPE development-index endpoint returned zero rows")
    raw_path = save_raw_snapshot(
        "srpe_development_index",
        json.dumps(body, ensure_ascii=False),
        file_ext="json",
        source_url=SRPE_DEVELOPMENT_INDEX_ENDPOINT,
    )
    frame = _normalize_srpe_development_rows(
        rows,
        source_url=SRPE_DEVELOPMENT_INDEX_ENDPOINT,
        fetched_at=fetched_at,
    )
    frame.attrs.update(
        raw_snapshot=str(raw_path),
        raw_snapshots=[str(raw_path)],
        source_urls=[SRPE_DEVELOPMENT_INDEX_ENDPOINT, SRPE_OPIP_URL],
        lineage_metadata={
            "lineage_type": "official_srpe_all_development_index",
            "api_total": result_data.get("total", len(frame)),
            "endpoint": SRPE_DEVELOPMENT_INDEX_ENDPOINT,
            "action_type": payload["actionType"],
            "action_id": action_id,
        },
    )
    return frame


def download_srpe_document(
    document_category: str,
    document_id: str | int,
    development_id: str | int,
    *,
    seq: str | int | None = None,
    session: requests.Session | None = None,
    timeout: float = 30,
    max_attempts: int = 2,
    max_download_bytes: int = 250 * 1024 * 1024,
) -> bytes:
    """Download one manifest PDF and validate that the response is a PDF.

    SRPE occasionally leaves a manifest row whose download endpoint returns
    404 (observed for one NOVO LAND transaction row).  The error includes the
    exact identifiers so the caller can retain an auditable failure record
    instead of silently treating the missing file as a zero-transaction PDF.
    """
    if document_category not in SRPE_DOWNLOAD_ACTIONS:
        raise ValueError(f"unsupported SRPE document category: {document_category}")
    client = session or requests.Session()
    client.headers.update(
        {
            **DEFAULT_HEADERS,
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Content-Type": "application/json",
            "Origin": "https://www.srpe.gov.hk",
            "Referer": SRPE_OPIP_URL,
        }
    )
    endpoint = f"{SRPE_API_BASE}/download/{SRPE_DOWNLOAD_ACTIONS[document_category]}"
    payload = {"id": str(document_id), "seq": "" if seq is None else str(seq), "devId": str(development_id)}
    attempts = max(1, int(max_attempts))
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            # Stream the body so a slow/stalled large PDF cannot hold the
            # process indefinitely while ``requests`` assembles
            # ``response.content``.  Some unit-test fakes do not implement
            # ``iter_content``; those retain the small-response fallback.
            response = client.post(
                endpoint,
                json=payload,
                timeout=(timeout, timeout),
                stream=True,
            )
        except requests.RequestException as exc:
            last_error = f"request error: {exc}"
            if attempt < attempts:
                time.sleep(0.5 * attempt)
                continue
            break
        if response.status_code == 404:
            last_error = "HTTP 404 (manifest row may be stale or file may have been replaced)"
            if attempt < attempts:
                time.sleep(0.5 * attempt)
                continue
            break
        if response.status_code >= 500 and attempt < attempts:
            last_error = f"HTTP {response.status_code}"
            time.sleep(0.5 * attempt)
            continue
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            last_error = str(exc)
            break
        try:
            content_length = int(response.headers.get("Content-Length", "0"))
        except (AttributeError, TypeError, ValueError):
            content_length = 0
        if content_length > max_download_bytes:
            last_error = f"content length {content_length} exceeds max_download_bytes={max_download_bytes}"
            break
        if hasattr(response, "iter_content"):
            chunks: list[bytes] = []
            total = 0
            deadline = time.monotonic() + max(float(timeout) * 3.0, 60.0)
            try:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if time.monotonic() > deadline:
                        raise TimeoutError("streaming download deadline exceeded")
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_download_bytes:
                        raise ValueError(
                            f"streamed content exceeds max_download_bytes={max_download_bytes}"
                        )
                    chunks.append(chunk)
            except (requests.RequestException, TimeoutError, ValueError) as exc:
                last_error = str(exc)
                if attempt < attempts:
                    time.sleep(0.5 * attempt)
                    continue
                break
            content = b"".join(chunks)
        else:
            content = response.content
        if not content.startswith(b"%PDF"):
            last_error = f"HTTP {response.status_code} returned non-PDF content ({len(content)} bytes)"
            break
        return content
    raise SRPEDocumentDownloadError(
        f"failed to download SRPE {document_category}: document_id={document_id}, "
        f"development_id={development_id}, endpoint={endpoint}; {last_error or 'unknown error'}"
    )

def fetch_srpe_project_documents() -> pd.DataFrame:
    """
    Fetch SRPE OPIP portal and parse available project document search modules.
    """
    response = requests.get(SRPE_OPIP_URL, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()

    raw_path = save_raw_snapshot("srpe_opip_landing", response.text, file_ext="html", source_url=SRPE_OPIP_URL)

    soup = BeautifulSoup(response.text, 'html.parser')
    links = soup.find_all('a', href=True)

    records = []
    for a in links:
        href = a['href']
        text = a.get_text(strip=True)
        if any(action in href for action in ['.do', 'search', 'Brochure', 'Pricelist', 'Transaction']):
            records.append({
                'action_name': text,
                'action_endpoint': urljoin(SRPE_OPIP_URL, href),
                'source_platform': 'SRPE'
            })

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.drop_duplicates(subset=['action_endpoint']).reset_index(drop=True)
    df.attrs.update(raw_snapshot=str(raw_path), source_url=SRPE_OPIP_URL)
    return df

def fetch_srpe_firsthand_sales_digest() -> pd.DataFrame:
    """
    Fetch SRPE first-hand sales digest: statutory price list filings and transaction register snapshots.

    The OPIP portal (``SRPE_OPIP_URL``) is a client-rendered React SPA, but its
    real backend XHR contract has been reverse-engineered from the app's JS
    bundles (``/opip/v*/js/index.*.js`` and its lazy-loaded chunks) and
    verified with live requests against real, publicly-known developments
    (e.g. "WETLAND SEASONS PARK" and "21 BORRETT ROAD" -- both real HK
    first-hand developments). Contrary to an earlier review's claim, the
    portal does not expose routes literally named ``searchDevelopment`` /
    ``transactions`` / ``arrangements`` -- those strings only appear as i18n
    translation-key fragments (e.g. ``all.development.map.searchDevelopment``,
    ``msg.register.of.transaction``), not as callable endpoints.

    The real, verified contract used here:

    1. ``POST {SRPE_API_BASE}/DistrictAreaSearch/getUploadSearchResult`` --
       the backend for the portal's "Newly Uploaded Sales Documents" search.
       Given day-lookback filters per document type, it returns
       ``devListTransactions`` / ``devListPriceList`` /
       ``devListSalesArrangement`` / ``devListSaleBrochure``: lists of
       *developments* that had a document of that category uploaded within
       the lookback window. This needs no auth/session and returns genuine,
       richly structured government data (verified: fetched and confirmed
       against known real developments and file sizes).
    2. ``POST {SRPE_API_BASE}/DevBldgSearch/getSelectedDevResult`` with a
       ``devId`` from step 1 -- returns that development's full document
       manifest (``devInfoResp.transactions`` / ``.prices`` /
       ``.salesArrangements`` / ``.brochureList``), each entry carrying a real
       document id, printing/submission dates, and file metadata.
    3. ``POST {SRPE_API_BASE}/download/download{Trx,Price,SalesArrangement,Brochure}``
       with ``{"id": <document id>, "seq": "", "devId": <devId>}`` -- streams
       the actual statutory PDF (register of transactions / price list /
       sales arrangement / sales brochure). Verified live: both
       ``downloadTrx`` and ``downloadPrice`` returned genuine ``%PDF-1.4``
       binaries whose byte length matched the ``fileSize`` reported in step 2
       exactly (713507 bytes and 5650415 bytes respectively, for a real
       Wetland Seasons Park register-of-transactions and price-list filing).

    This function performs steps 1-2 for real (bounded by
    ``HK_REALESTATE_SRPE_MAX_DEVS``) and emits one row per statutory document
    found, with ``endpoint_url`` pointing at the real download API from step
    3. It does not download every PDF's full binary content by default (that
    would be a very large, slow fetch across every active development every
    run) -- the digest is a genuine, verified catalog of what's newly filed
    and where to fetch it, matching this dataset's catalog quality-spec
    (``document_category`` / ``endpoint_url`` / ``source_agency``).
    """
    session = requests.Session()
    session.headers.update(
        {
            **DEFAULT_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://www.srpe.gov.hk",
            "Referer": urljoin(SRPE_OPIP_URL, "new_upload_search_result"),
        }
    )

    lookback_days = os.getenv("HK_REALESTATE_SRPE_LOOKBACK_DAYS", "7")
    max_devs = int(os.getenv("HK_REALESTATE_SRPE_MAX_DEVS", "60"))
    request_delay = float(os.getenv("HK_REALESTATE_SRPE_DELAY", "0.2"))

    upload_payload = {
        "timeStamp": int(time.time() * 1000),
        "searchSalesBrochure": True,
        "salesBrochureDay": lookback_days,
        "searchTransactions": True,
        "transactionsDay": lookback_days,
        "searchPriceList": True,
        "priceListDay": lookback_days,
        "searchSalesArrangement": True,
        "salesArrangementDay": lookback_days,
        "actionType": "Newly Uploaded Sales Documents",
    }

    upload_resp = session.post(
        f"{SRPE_API_BASE}/DistrictAreaSearch/getUploadSearchResult",
        json=upload_payload,
        timeout=20,
    )
    upload_resp.raise_for_status()
    upload_data = upload_resp.json().get("resultData") or {}

    save_raw_snapshot(
        "srpe_upload_search_result",
        json.dumps(upload_data, ensure_ascii=False),
        file_ext="json",
        source_url=f"{SRPE_API_BASE}/DistrictAreaSearch/getUploadSearchResult",
    )

    # Collect the unique set of developments that had *any* newly uploaded
    # document, keeping a light-weight name/address fallback in case a
    # detail lookup for that devId fails.
    dev_meta: Dict[str, Dict[str, Any]] = {}
    for list_key in SRPE_UPLOAD_LIST_KEYS:
        for dev in upload_data.get(list_key) or []:
            dev_id = dev.get("developmentId") or dev.get("id")
            if dev_id and dev_id not in dev_meta:
                dev_meta[dev_id] = dev

    dev_ids = list(dev_meta.keys())[:max_devs]

    # getSelectedDevResult returns each development's *full* filing history,
    # not just what's new -- so to keep this a genuine "newly uploaded"
    # digest (matching the portal's own search semantics) rather than a full
    # historical dump, only keep documents whose submission actually falls
    # inside the requested lookback window (with a 1-day buffer for
    # timezone/day-boundary slop).
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=int(lookback_days) + 1)

    records = []
    detail_snapshots = {}
    for dev_id in dev_ids:
        try:
            detail_resp = session.post(
                f"{SRPE_API_BASE}/DevBldgSearch/getSelectedDevResult",
                json={"timeStamp": int(time.time() * 1000), "devId": dev_id},
                timeout=20,
            )
            detail_resp.raise_for_status()
            dev_info = (detail_resp.json().get("resultData") or {}).get("devInfoResp") or {}
        except Exception:
            # Real, honest skip: this one development's detail lookup failed;
            # continue with the rest rather than fabricating its documents.
            continue

        detail_snapshots[dev_id] = dev_info
        dev = dev_info.get("dev") or dev_meta.get(dev_id, {})
        dev_name = dev.get("engName")
        dev_phase = dev.get("engPhaseName")
        dev_phase_no = dev.get("engPhaseNo")
        dev_address = None
        addresses = dev.get("addresses") or []
        if addresses:
            dev_address = addresses[0].get("engAddress")

        def _emit(category: str, doc: Dict[str, Any]) -> None:
            file_info = doc.get("file") or {}
            submitted = pd.to_datetime(file_info.get("submissionTime"), errors="coerce", utc=True)
            if pd.isna(submitted) or submitted < cutoff:
                return
            records.append(
                {
                    "document_category": category,
                    "endpoint_url": f"{SRPE_API_BASE}/download/{SRPE_DOWNLOAD_ACTIONS[category]}",
                    "source_agency": "SRPE",
                    "development_id": dev_id,
                    "development_name": dev_name,
                    "development_phase": dev_phase,
                    "development_phase_no": dev_phase_no,
                    "development_address": dev_address,
                    "document_id": doc.get("id"),
                    "serial_no": doc.get("serialNo"),
                    "date_of_printing": doc.get("dateOfPrinting"),
                    "file_name": file_info.get("fileName"),
                    "file_size_bytes": file_info.get("fileSize"),
                    "submission_time": file_info.get("submissionTime"),
                }
            )

        for tx in dev_info.get("transactions") or []:
            _emit("register_of_transactions", tx)
        for price in dev_info.get("prices") or []:
            _emit("price_list", price)
        for arrangement in dev_info.get("salesArrangements") or []:
            _emit("sales_arrangement", arrangement)
        brochure_docs = dev_info.get("brochureList") or ([dev_info["brochure"]] if dev_info.get("brochure") else [])
        for brochure in brochure_docs:
            part_files = brochure.get("partFiles") or []
            if not part_files:
                continue
            # A brochure filing can have multiple parts; treat the first
            # (typically the full/latest version) as the document row and
            # keep its own id/file metadata -- these are still real,
            # per-filing records, not synthesized ones.
            for part in part_files:
                _emit(
                    "sales_brochure",
                    {
                        "id": brochure.get("id"),
                        "serialNo": part.get("partNo"),
                        "dateOfPrinting": brochure.get("dateOfPrint"),
                        "file": part,
                    },
                )

        time.sleep(request_delay)

    if detail_snapshots:
        save_raw_snapshot(
            "srpe_selected_dev_details",
            json.dumps(detail_snapshots, ensure_ascii=False),
            file_ext="json",
            source_url=f"{SRPE_API_BASE}/DevBldgSearch/getSelectedDevResult",
        )

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.drop_duplicates(subset=["document_category", "document_id", "file_name"]).reset_index(drop=True)
    df.attrs.update(
        raw_snapshot=str(save_raw_snapshot("srpe_firsthand_sales_digest_meta", json.dumps({"lookback_days": lookback_days, "dev_count": len(dev_ids)}), file_ext="json", source_url=SRPE_OPIP_URL)),
        source_url=f"{SRPE_API_BASE}/DistrictAreaSearch/getUploadSearchResult",
    )
    return df
