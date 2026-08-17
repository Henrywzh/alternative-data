"""Fast, high-recall web check for SRPE phases still missing SHKP evidence.

This is deliberately a routing/audit layer, not an ownership resolver.  It
checks the public project website attached to each of the current
``identity_unknown_owner_evidence_missing`` SRPE rows, records statutory role
fields when visible, and keeps timeout/robots/no-keyword outcomes explicit.
The static pass is bounded and concurrent so dead domains do not hold up the
whole 334-row queue.  A later browser/Crawl4AI pass can enrich only the rows
marked short/error; it must not overwrite the raw static observation.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .config import DEFAULT_HEADERS
from .shkp_srpe_backfill import (
    SHKP_PHASE_SITE_EVIDENCE_COLUMNS,
    _SHKP_TERMS,
    _extract_role_fields,
    _extract_role_fields_from_html,
    _normalise_url,
    _text,
)
from .storage import load_latest_normalized, save_normalized_dataset, save_raw_snapshot


UNKNOWN_SITE_DATASET = "shkp_unknown_phase_site_evidence"
UNKNOWN_REVIEW_DATASET = "shkp_unknown_phase_identity_review"

UNKNOWN_REVIEW_COLUMNS = [
    "review_id",
    "srpe_development_id",
    "development_name_en",
    "phase_name_en",
    "official_website",
    "fetch_status",
    "robots_status",
    "http_status",
    "shkp_match_status",
    "vendor_name",
    "sales_agent",
    "holding_companies",
    "quick_check_result",
    "recommended_next_step",
    "review_caveat",
    "source_url",
    "last_checked_at",
]


def _robots_for_url(url: str, cache: dict[str, tuple[bool | None, str]], lock: threading.Lock, timeout: float) -> tuple[bool | None, str]:
    parsed = urlparse(url)
    key = parsed.netloc.casefold()
    with lock:
        if key in cache:
            return cache[key]
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    try:
        response = requests.get(
            robots_url,
            headers=DEFAULT_HEADERS,
            timeout=min(max(timeout, 1.0), 5.0),
        )
        if response.status_code == 404:
            result = (None, "unavailable")
        else:
            response.raise_for_status()
            parser.parse(response.text.splitlines())
            result = (parser.can_fetch("*", url), "checked")
    except requests.RequestException:
        result = (None, "unavailable")
    with lock:
        cache[key] = result
    return result


def _base_row(candidate: dict[str, Any], *, website: str | None, fetch_status: str) -> dict[str, Any]:
    phase_id = _text(candidate.get("srpe_development_id")) or ""
    evidence_id = hashlib.sha1(f"unknown-static|{phase_id}|{website}".encode("utf-8")).hexdigest()
    return {
        "evidence_id": evidence_id,
        "srpe_development_id": phase_id,
        "development_name_en": candidate.get("development_name_en"),
        "phase_name_en": candidate.get("phase_name_en"),
        "official_website": candidate.get("official_website"),
        "resolved_url": website,
        "http_status": None,
        "fetch_status": fetch_status,
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
            "Fast public project-site check only; absence of an SHKP keyword is not a negative ownership conclusion, "
            "and role evidence does not establish a listed-parent stake or JV percentage."
        ),
    }


def _fetch_one(candidate: dict[str, Any], *, timeout: float, robots_cache: dict[str, tuple[bool | None, str]], robots_lock: threading.Lock) -> dict[str, Any]:
    website = _normalise_url(candidate.get("official_website"))
    row = _base_row(candidate, website=website, fetch_status="no_official_website" if not website else "error")
    if not website:
        return row
    allowed, robots_status = _robots_for_url(website, robots_cache, robots_lock, timeout)
    row["robots_status"] = robots_status
    if allowed is False:
        row["fetch_status"] = "blocked_by_robots"
        return row
    try:
        # Keep the concurrent pass gentle on small project domains.  This is
        # a quick audit, not a crawl; the delay also gives redirects and
        # repeated phase URLs a little breathing room.
        time.sleep(0.15)
        response = requests.get(
            website,
            headers={**DEFAULT_HEADERS, "Accept": "text/html,application/xhtml+xml"},
            timeout=max(float(timeout), 1.0),
            allow_redirects=True,
        )
        response.raise_for_status()
        raw_path = save_raw_snapshot(
            "shkp_unknown_phase_site",
            response.content,
            file_ext="html",
            source_url=response.url,
        )
        visible = BeautifulSoup(response.content, "html.parser").get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", visible).strip()
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
        row.update(
            {
                "http_status": response.status_code,
                "fetch_status": "ok" if len(text) >= 120 else "ok_short_or_js",
                "resolved_url": response.url,
                "vendor_name": vendor,
                "sales_agent": sales_agent,
                "holding_companies": holding,
                "shkp_keyword_hits_json": json.dumps(list(dict.fromkeys(hits)), ensure_ascii=False),
                "shkp_match_status": "site_named_shkp" if role_hits else "page_named_shkp" if hits else "site_no_shkp_keyword",
                "evidence_context": " | ".join(value for value in (vendor, sales_agent, holding) if value)[:3000] or text[-1000:],
                "raw_snapshot_path": str(raw_path),
            }
        )
    except (requests.RequestException, ValueError) as exc:
        row["fetch_status"] = "error"
        row["evidence_context"] = str(exc)[:1000]
    return row


def fetch_unknown_phase_site_evidence(
    candidates: pd.DataFrame,
    *,
    timeout: float = 8.0,
    max_workers: int = 12,
) -> pd.DataFrame:
    """Fetch one bounded static observation for each unknown phase."""
    if candidates is None or candidates.empty:
        return pd.DataFrame(columns=SHKP_PHASE_SITE_EVIDENCE_COLUMNS)
    selected = candidates.loc[
        candidates.get("candidate_status", pd.Series(dtype="string")).astype(str).eq("identity_unknown_owner_evidence_missing")
    ].copy()
    if selected.empty:
        return pd.DataFrame(columns=SHKP_PHASE_SITE_EVIDENCE_COLUMNS)
    robots_cache: dict[str, tuple[bool | None, str]] = {}
    robots_lock = threading.Lock()
    rows: list[dict[str, Any]] = []
    workers = max(1, min(int(max_workers), 24))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _fetch_one,
                candidate,
                timeout=timeout,
                robots_cache=robots_cache,
                robots_lock=robots_lock,
            )
            for candidate in selected.to_dict("records")
        ]
        for future in as_completed(futures):
            rows.append(future.result())
    result = pd.DataFrame(rows, columns=SHKP_PHASE_SITE_EVIDENCE_COLUMNS)
    if not result.empty:
        order = {str(value): index for index, value in enumerate(selected["srpe_development_id"].astype(str).tolist())}
        result["_order"] = result["srpe_development_id"].astype(str).map(order).fillna(len(order))
        result = result.sort_values(["_order", "srpe_development_id"]).drop(columns=["_order"]).reset_index(drop=True)
    return result


def build_unknown_phase_identity_review(evidence: pd.DataFrame) -> pd.DataFrame:
    """Turn raw site outcomes into a quick-review queue without ownership promotion."""
    if evidence is None or evidence.empty:
        return pd.DataFrame(columns=UNKNOWN_REVIEW_COLUMNS)
    rows: list[dict[str, Any]] = []
    for record in evidence.to_dict("records"):
        fetch_status = _text(record.get("fetch_status")) or "unknown"
        match = _text(record.get("shkp_match_status")) or "not_evaluated"
        if match == "site_named_shkp":
            result = "quick_verified_role_shkp"
            next_step = "route to transaction-register download; keep stake/JV as unknown"
        elif match == "page_named_shkp":
            result = "page_keyword_only"
            next_step = "manual one-minute role check; keyword may be disclaimer or unrelated mention"
        elif match == "site_no_shkp_keyword":
            result = "checked_no_shkp_keyword"
            next_step = "do not reject; search vendor/agent and archived project material if needed"
        elif fetch_status in {"blocked_by_robots", "no_official_website"}:
            result = "not_fetchable_in_static_pass"
            next_step = "use SRPE documents or a permitted browser/manual check"
        elif fetch_status in {"ok_short_or_js", "error"}:
            result = "dynamic_or_fetch_gap"
            next_step = "bounded Crawl4AI/browser fallback, then manual review"
        else:
            result = "unclassified"
            next_step = "manual review"
        rows.append(
            {
                "review_id": hashlib.sha1(f"unknown-review|{record.get('srpe_development_id')}|{record.get('source_url')}".encode()).hexdigest(),
                "srpe_development_id": record.get("srpe_development_id"),
                "development_name_en": record.get("development_name_en"),
                "phase_name_en": record.get("phase_name_en"),
                "official_website": record.get("official_website"),
                "fetch_status": fetch_status,
                "robots_status": record.get("robots_status"),
                "http_status": record.get("http_status"),
                "shkp_match_status": match,
                "vendor_name": record.get("vendor_name"),
                "sales_agent": record.get("sales_agent"),
                "holding_companies": record.get("holding_companies"),
                "quick_check_result": result,
                "recommended_next_step": next_step,
                "review_caveat": "快速核查不是法律 ownership/JV attribution；site_no_shkp_keyword 不等于非 SHKP。",
                "source_url": record.get("source_url"),
                "last_checked_at": record.get("fetched_at"),
            }
        )
    return pd.DataFrame(rows, columns=UNKNOWN_REVIEW_COLUMNS)


def run_shkp_unknown_phase_probe(*, timeout: float = 8.0, max_workers: int = 12) -> dict[str, Any]:
    """Persist the 334-row unknown-phase static check and review queue."""
    run_id = f"shkp-unknown-phase-probe-{uuid.uuid4()}"
    candidates = load_latest_normalized("shkp_high_recall_phase_candidates")
    unknown = candidates.loc[
        candidates.get("candidate_status", pd.Series(dtype="string")).astype(str).eq("identity_unknown_owner_evidence_missing")
    ].copy()
    evidence = fetch_unknown_phase_site_evidence(unknown, timeout=timeout, max_workers=max_workers)
    review = build_unknown_phase_identity_review(evidence)
    source_urls = sorted({str(value).strip() for value in evidence.get("source_url", pd.Series(dtype="string")).dropna() if str(value).strip()})
    lineage = {
        "lineage_type": "shkp_unknown_phase_fast_site_check",
        "candidate_rows": int(len(unknown)),
        "evidence_rows": int(len(evidence)),
        "review_rows": int(len(review)),
        "max_workers": int(max_workers),
        "timeout_seconds": float(timeout),
        "ownership_inference": False,
        "strict_ownership_promotion_status": "blocked_quick_web_check_only",
        "caveat": "Static public-site quick check; negative/empty outcomes are not ownership negatives.",
    }
    normalized = {
        UNKNOWN_SITE_DATASET: save_normalized_dataset(
            UNKNOWN_SITE_DATASET,
            evidence,
            run_id=run_id,
            source_urls=source_urls,
            lineage_metadata=lineage,
        ),
        UNKNOWN_REVIEW_DATASET: save_normalized_dataset(
            UNKNOWN_REVIEW_DATASET,
            review,
            run_id=run_id,
            source_urls=source_urls,
            lineage_metadata=lineage,
        ),
    }
    return {
        "run_id": run_id,
        "candidate_rows": int(len(unknown)),
        "evidence_rows": int(len(evidence)),
        "fetch_status_counts": evidence.get("fetch_status", pd.Series(dtype="string")).value_counts().to_dict(),
        "match_status_counts": evidence.get("shkp_match_status", pd.Series(dtype="string")).value_counts().to_dict(),
        "quick_check_counts": review.get("quick_check_result", pd.Series(dtype="string")).value_counts().to_dict(),
        "normalized": normalized,
    }
