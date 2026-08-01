"""SFC News & Announcements Source.

Forward-looking regulatory news feed (rulemaking, consultations, enforcement
actions), complementing the static hkma_register.py / sfc_vatp_register.py
snapshots which only show "who's licensed right now" with no history.

Access: `POST https://apps.sfc.hk/edistributionWeb/api/news/search`. This is
a real JSON API confirmed live by loading the SFC's React SPA
(https://apps.sfc.hk/edistributionWeb/gateway/EN/news-and-announcements/news/)
in a real browser and inspecting the network request it fires. The exact
request body is a POST of the SPA's own client-side state object:

    {"lang": "EN", "category": "all", "year": "all", "month": "all",
     "pageNo": 0, "pageSize": 100, "isLoading": true, "errors": null,
     "items": null, "total": -1}

`pageNo` is 0-indexed; `year`/`month` accept "all" or a specific value
(e.g. "2026") to scope the query; `total` reflects the full matching count
(confirmed 5297 for year="all", i.e. the complete historical archive, not a
recent-items cache). No auth or special headers are required — a plain
Content-Type: application/json POST works.

The raw feed is ALL SFC news across all of finance (cybersecurity fines, IPO
fraud enforcement, asset-management surveys, etc.) — most of it is NOT
crypto-related. CRYPTO_NEWS_KEYWORDS (config.py) narrows this down to
stablecoin/virtual-asset/crypto relevance. Verified 2026-08-01: fetching the
last ~13 months (2025 + 2026 year-to-date, 329 raw items) found 24
crypto-relevant items after filtering — a real, non-trivial subset, not an
empty or unfiltered result.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from ..config import CRYPTO_NEWS_KEYWORDS, DEFAULT_TIMEOUT, SFC_NEWS_API_URL, SFC_NEWS_REFERER
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = ["news_ref_no", "issue_date", "title", "news_type", "source", "fetched_at"]

PAGE_SIZE = 100


def _is_crypto_relevant(title: str) -> bool:
    title_lower = title.lower()
    return any(kw in title_lower for kw in CRYPTO_NEWS_KEYWORDS)


def fetch_sfc_news(months_back: int = 13) -> pd.DataFrame:
    """Fetch SFC news/announcements for the trailing `months_back` months,
    filtered to stablecoin/virtual-asset/crypto relevance.

    Pages through the SFC news-search API scoped by year (the API accepts a
    year filter, which keeps each request's result set small rather than
    paging through the entire 5000+ item historical archive), then applies a
    client-side date cutoff and keyword filter.
    """
    now = datetime.now(timezone.utc)
    now_str = now.isoformat()
    cutoff = now - timedelta(days=months_back * 31)

    years_to_fetch = sorted({now.year, cutoff.year}, reverse=True)

    headers = {"Content-Type": "application/json", "Referer": SFC_NEWS_REFERER}

    all_items: list[dict] = []

    try:
        for year in years_to_fetch:
            page_no = 0
            while True:
                body = {
                    "lang": "EN",
                    "category": "all",
                    "year": str(year),
                    "month": "all",
                    "pageNo": page_no,
                    "pageSize": PAGE_SIZE,
                    "isLoading": True,
                    "errors": None,
                    "items": None,
                    "total": -1,
                }
                resp = requests.post(
                    SFC_NEWS_API_URL, json=body, headers=headers, timeout=DEFAULT_TIMEOUT
                )
                resp.raise_for_status()
                payload = resp.json()
                items = payload.get("items") or []
                total = payload.get("total", 0)

                all_items.extend(items)

                if not items or (page_no + 1) * PAGE_SIZE >= total:
                    break
                page_no += 1

        save_raw_snapshot(
            "sfc_news_raw",
            all_items,
            file_ext="json",
            source_url=SFC_NEWS_API_URL,
        )

        # Apply date cutoff
        recent_items = []
        for item in all_items:
            issue_date_raw = item.get("issueDate")
            if not issue_date_raw:
                continue
            try:
                issue_dt = datetime.fromisoformat(issue_date_raw).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if issue_dt >= cutoff:
                recent_items.append(item)

        # Apply crypto-relevance keyword filter
        relevant_items = [it for it in recent_items if _is_crypto_relevant(it.get("title", ""))]

        logger.info(
            "SFC news: fetched %d raw items (%d within last %d months), "
            "%d crypto-relevant after keyword filter.",
            len(all_items), len(recent_items), months_back, len(relevant_items),
        )

        if not relevant_items:
            return pd.DataFrame(columns=SCHEMA_COLUMNS)

        result = pd.DataFrame(
            {
                "news_ref_no": [it.get("newsRefNo") for it in relevant_items],
                "issue_date": [it.get("issueDate") for it in relevant_items],
                "title": [it.get("title", "").strip() for it in relevant_items],
                "news_type": [it.get("newsType") for it in relevant_items],
                "source": "sfc",
                "fetched_at": now_str,
            }
        )
        result = result.drop_duplicates(subset=["news_ref_no"]).reset_index(drop=True)

        save_raw_snapshot(
            "sfc_news_crypto_relevant",
            result.to_dict(orient="records"),
            file_ext="json",
            source_url=SFC_NEWS_API_URL,
        )

        return result[SCHEMA_COLUMNS]

    except Exception:
        logger.exception("Failed to fetch SFC news.")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
