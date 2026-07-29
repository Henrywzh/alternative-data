from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from provider_incident_data.extract import extract_snapshot
from provider_incident_data.models import Snapshot
from provider_incident_data.quality import validate_incidents
from provider_incident_data.storage import IncidentStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill")

# One-off manual backfill against public Statuspage.io-hosted pages shared by
# many unrelated companies. Stay a low-volume, identified, serial client -
# the same posture as ProviderIncidentSource - so this never looks like abuse
# to Statuspage's shared infrastructure or gets the daily scraper's IP range
# throttled as a side effect.
USER_AGENT = "alternative-data-backfill/1.0 (+https://github.com/Henrywzh/alternative-data)"
REQUEST_DELAY_SECONDS = 0.3

STATUSPAGE_PROVIDERS = [
    ("minimax", "MiniMax", "status.minimax.io"),
    ("anthropic", "Anthropic", "status.claude.com"),
    ("moonshot", "Moonshot AI (Kimi)", "status.moonshot.cn"),
]


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(
        total=1,
        connect=1,
        read=1,
        status=1,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _context() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return (
        "backfill-" + now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6],
        now.isoformat().replace("+00:00", "Z"),
    )


def fetch_statuspage_incident_ids(session: requests.Session, domain: str, max_pages: int = 15) -> list[str]:
    incident_ids: list[str] = []
    seen = set()

    for page in range(1, max_pages + 1):
        url = f"https://{domain}/history?page={page}"
        try:
            res = session.get(url, timeout=10)
            if res.status_code != 200:
                logger.info(f"Page {page} returned status {res.status_code} for {domain}. Stopping pagination.")
                break
            soup = BeautifulSoup(res.text, "html.parser")
            tag = soup.find(attrs={"data-react-class": "HistoryIndex"})
            if not tag:
                logger.info(f"No HistoryIndex tag on page {page} for {domain}.")
                break
            props = json.loads(html.unescape(tag.get("data-react-props") or "{}"))
            months = props.get("months", [])
            page_new_count = 0
            for m in months:
                for inc in m.get("incidents", []):
                    code = inc.get("code")
                    if code and code not in seen:
                        seen.add(code)
                        incident_ids.append(code)
                        page_new_count += 1
            logger.info(f"Fetched page {page} for {domain}: {page_new_count} new incident codes found.")
            if page_new_count == 0 and page > 1:
                break
        except requests.RequestException as exc:
            logger.warning(f"Error fetching page {page} for {domain}: {exc}")
            break
        finally:
            time.sleep(REQUEST_DELAY_SECONDS)
    return incident_ids


def fetch_openai_incident_ids(session: requests.Session) -> list[str]:
    url = "https://status.openai.com/history"
    seen = set()
    incident_ids: list[str] = []
    try:
        res = session.get(url, timeout=15)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            links = soup.find_all("a", href=re.compile(r"/incidents/"))
            for a in links:
                href = a["href"]
                code = href.split("/incidents/")[-1].strip()
                if code and code not in seen:
                    seen.add(code)
                    incident_ids.append(code)
            logger.info(f"Fetched OpenAI history page: found {len(incident_ids)} incident codes.")
        else:
            logger.warning(f"OpenAI history page returned status {res.status_code}.")
    except requests.RequestException as exc:
        logger.warning(f"Error fetching OpenAI history page: {exc}")
    finally:
        time.sleep(REQUEST_DELAY_SECONDS)
    return incident_ids


def _fetch_single_incident(
    session: requests.Session, domain: str, provider_id: str, provider_name: str, code: str, run_id: str, scraped_at: str
) -> dict[str, list[dict[str, Any]]] | None:
    """Fetch and extract one incident. Returns None on failure so callers can count it."""
    detail_url = f"https://{domain}/api/v2/incidents/{code}.json"
    try:
        res = session.get(detail_url, timeout=10)
        if res.status_code != 200:
            logger.warning(f"CTIA-style detail fetch for {code} on {domain} returned status {res.status_code}.")
            return None
        payload = res.json()
        incident = payload.get("incident")
        if not incident:
            logger.warning(f"No 'incident' payload for {code} on {domain}.")
            return None
        snapshot_body = json.dumps({"incidents": [incident]})
        snapshot = Snapshot(
            provider_id=provider_id,
            provider_name=provider_name,
            source_kind="statuspage_json",
            source_url=detail_url,
            parser="statuspage",
            body=snapshot_body,
            content_type="application/json",
            status_code=200,
            response_ms=100,
        )
        return extract_snapshot(snapshot, run_id=run_id, scraped_at=scraped_at)
    except (requests.RequestException, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        logger.warning(f"Failed fetching detail for {code} on {domain}: {exc}")
        return None
    finally:
        time.sleep(REQUEST_DELAY_SECONDS)


def _fetch_all_details(
    session: requests.Session,
    domain: str,
    provider_id: str,
    provider_name: str,
    codes: list[str],
    run_id: str,
    scraped_at: str,
    rows: dict[str, list[dict[str, Any]]],
) -> tuple[int, int]:
    """Serially fetch every incident's detail for one provider. Returns (succeeded, failed)."""
    succeeded = 0
    failed = 0
    for index, code in enumerate(codes, start=1):
        extracted = _fetch_single_incident(session, domain, provider_id, provider_name, code, run_id, scraped_at)
        if extracted is None:
            failed += 1
        else:
            succeeded += 1
            rows["provider_incidents"].extend(extracted.get("provider_incidents", []))
            rows["provider_incident_updates"].extend(extracted.get("provider_incident_updates", []))
            rows["provider_incident_components"].extend(extracted.get("provider_incident_components", []))
        if index % 50 == 0 or index == len(codes):
            logger.info(f"  Processed {index}/{len(codes)} incidents for {provider_name} ({failed} failed so far).")
    return succeeded, failed


def backfill_all(base_dir: Path) -> dict[str, int]:
    storage = IncidentStorage(base_dir)
    run_id, scraped_at = _context()
    session = _build_session()

    rows: dict[str, list[dict[str, Any]]] = {
        "provider_incidents": [],
        "provider_incident_updates": [],
        "provider_incident_components": [],
    }
    total_succeeded = 0
    total_failed = 0

    # 1. Process Statuspage providers (MiniMax, Anthropic, Moonshot)
    for provider_id, provider_name, domain in STATUSPAGE_PROVIDERS:
        logger.info(f"Starting backfill for {provider_name} ({domain})...")
        codes = fetch_statuspage_incident_ids(session, domain)
        logger.info(f"Found {len(codes)} incident codes for {provider_name}. Fetching details serially...")
        succeeded, failed = _fetch_all_details(session, domain, provider_id, provider_name, codes, run_id, scraped_at, rows)
        total_succeeded += succeeded
        total_failed += failed

    # 2. Process OpenAI
    logger.info("Starting backfill for OpenAI...")
    openai_codes = fetch_openai_incident_ids(session)
    logger.info(f"Found {len(openai_codes)} incident codes for OpenAI. Fetching details serially...")
    succeeded, failed = _fetch_all_details(
        session, "status.openai.com", "openai", "OpenAI", openai_codes, run_id, scraped_at, rows
    )
    total_succeeded += succeeded
    total_failed += failed

    attempted = total_succeeded + total_failed
    if attempted and total_failed / attempted > 0.1:
        logger.warning(
            f"High failure rate while fetching incident details: {total_failed}/{attempted} requests failed. "
            "The backfill likely hit a rate limit, block, or a page-layout change; results may be incomplete."
        )

    # 3. Validate before writing anything - the same guardrail the daily
    # pipeline enforces via provider_incident_data.pipeline.run_update().
    incidents_frame = pd.DataFrame(rows["provider_incidents"])
    validate_incidents(incidents_frame)

    # 4. Upsert to storage
    logger.info(f"Upserting {len(rows['provider_incidents'])} total backfilled incidents into storage...")
    written = {}
    if rows["provider_incidents"]:
        written["provider_incidents"] = len(storage.upsert("provider_incidents", rows["provider_incidents"]))
    if rows["provider_incident_updates"]:
        written["provider_incident_updates"] = len(storage.upsert("provider_incident_updates", rows["provider_incident_updates"]))
    if rows["provider_incident_components"]:
        written["provider_incident_components"] = len(storage.upsert("provider_incident_components", rows["provider_incident_components"]))
    logger.info(f"Backfill complete! Updated dataset counts: {written}")
    return written


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    backfill_all(project_root)
