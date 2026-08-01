"""HKMA Press Releases News Source.

Forward-looking regulatory news feed (licensing decisions, sandbox updates,
Ordinance amendments), complementing the static hkma_register.py /
sfc_vatp_register.py snapshots which only show "who's licensed right now"
with no history.

Access: `GET https://api.hkma.gov.hk/public/press-releases?lang=en&offset=N`.
This is HKMA's own documented Open API (see the "Open API" link on the
press-releases listing page, apidocs.hkma.gov.hk/documentation/press-releases/),
found by loading the press-releases page with a real browser and inspecting
its bundled `pr-listing.js`, which pointed to an internal AJAX endpoint —
but the public Open API turned out to be the clean, documented, no-auth
alternative, so that's what this module uses instead. No headers/auth
required; returns clean JSON:

    {"header": {"success": true, ...},
     "result": {"datasize": 100,
                "records": [{"title": "...", "link": "...", "date": "YYYY-MM-DD"}, ...]}}

Paginated via `offset` (100 records per page, newest first). The underlying
press-releases HTML listing page IS server-rendered (matching hkma_register.py's
`requests.get()` + `pandas.read_html()` style used elsewhere in this sector),
but for this endpoint the Open API is strictly better: structured JSON,
clean pagination, no HTML parsing needed.

The raw feed is ALL HKMA press releases (monetary statistics, mortgage
surveys, scam alerts, bond tenders, etc.) — most of it is NOT
crypto-related. CRYPTO_NEWS_KEYWORDS (config.py) narrows this down to
stablecoin/virtual-asset/crypto relevance. Verified 2026-08-01: fetching the
last ~13 months (800 raw items) found 9 crypto-relevant items after
filtering, including "Granting of stablecoin issuer licences" (2026-04-10)
and "Implementation of regulatory regime for stablecoin issuers"
(2025-07-29) — real, non-trivial hits, not an empty or unfiltered result.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from ..config import CRYPTO_NEWS_KEYWORDS, DEFAULT_TIMEOUT, HKMA_NEWS_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = ["news_ref_no", "issue_date", "title", "news_type", "source", "fetched_at"]

PAGE_SIZE = 100


def _is_crypto_relevant(title: str) -> bool:
    title_lower = title.lower()
    return any(kw in title_lower for kw in CRYPTO_NEWS_KEYWORDS)


def fetch_hkma_news(months_back: int = 13) -> pd.DataFrame:
    """Fetch HKMA press releases for the trailing `months_back` months,
    filtered to stablecoin/virtual-asset/crypto relevance.

    Pages through HKMA's public Open API via `offset` (newest first, 100
    records/page) until the page's oldest record crosses the date cutoff,
    then applies the crypto-relevance keyword filter client-side.
    """
    now = datetime.now(timezone.utc)
    now_str = now.isoformat()
    cutoff = now - timedelta(days=months_back * 31)

    all_records: list[dict] = []

    try:
        offset = 0
        while True:
            resp = requests.get(
                HKMA_NEWS_URL, params={"lang": "en", "offset": offset}, timeout=DEFAULT_TIMEOUT
            )
            resp.raise_for_status()
            payload = resp.json()
            records = payload.get("result", {}).get("records") or []
            if not records:
                break

            all_records.extend(records)

            oldest_date_str = records[-1].get("date")
            if not oldest_date_str:
                break
            oldest_dt = datetime.strptime(oldest_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if oldest_dt < cutoff:
                break

            offset += PAGE_SIZE

        save_raw_snapshot(
            "hkma_news_raw",
            all_records,
            file_ext="json",
            source_url=HKMA_NEWS_URL,
        )

        # Apply date cutoff
        recent_records = []
        for rec in all_records:
            date_str = rec.get("date")
            if not date_str:
                continue
            try:
                rec_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if rec_dt >= cutoff:
                recent_records.append(rec)

        # Apply crypto-relevance keyword filter
        relevant_records = [r for r in recent_records if _is_crypto_relevant(r.get("title", ""))]

        logger.info(
            "HKMA news: fetched %d raw items (%d within last %d months), "
            "%d crypto-relevant after keyword filter.",
            len(all_records), len(recent_records), months_back, len(relevant_records),
        )

        if not relevant_records:
            return pd.DataFrame(columns=SCHEMA_COLUMNS)

        result = pd.DataFrame(
            {
                # HKMA's API has no ref-no field; the press-release link slug
                # (e.g. .../2026/04/20260410-3/) is the closest stable id.
                "news_ref_no": [
                    r.get("link", "").rstrip("/").rsplit("/", 1)[-1] for r in relevant_records
                ],
                "issue_date": [r.get("date") for r in relevant_records],
                "title": [r.get("title", "").strip() for r in relevant_records],
                "news_type": None,
                "source": "hkma",
                "fetched_at": now_str,
            }
        )
        result = result.drop_duplicates(subset=["news_ref_no"]).reset_index(drop=True)

        save_raw_snapshot(
            "hkma_news_crypto_relevant",
            result.to_dict(orient="records"),
            file_ext="json",
            source_url=HKMA_NEWS_URL,
        )

        return result[SCHEMA_COLUMNS]

    except Exception:
        logger.exception("Failed to fetch HKMA news.")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
