"""HKEXnews Company Announcements/Disclosures Source.

Covers the ~22 tickers in the HK Stablecoin & Crypto watchlist (config.WATCHLIST).
This sector's price action is driven almost entirely by same-day company
announcements (MOUs, treasury purchases, placements) for these small/mid-cap
names -- not by any of the point-in-time register/supply/AUM snapshots the
other sources in this package provide. See docs/asia-markets/asia-markets-hk-stablecoin-crypto.md.

CRITICAL GOTCHA (confirmed live, 2026-08-01): titleSearchServlet.do's `stockId`
query parameter does NOT filter by the plain numeric stock code you'd naively
pass in. Calling it with stockId="700" (Tencent) returns HTTP 200 with a
plausible-looking result set, but every row's STOCK_CODE is "00362" ("C ZENITH
CHEM") -- a completely unrelated company. The servlet silently ignores an
unrecognized stockId and falls back to some other feed rather than erroring.

This is the same bug class as the HK Transport Department scrapers fixed
earlier in this repo (see tests/test_hk_transport_scrapers.py): a 200 response
with real-looking data that is actually attributed to the wrong entity.

Fix: the real search UI resolves the stock code/name you type into an
*internal* numeric stockId via a companion autocomplete endpoint
(prefix.do) before it ever calls the search servlet. We replicate that:
  1. Call HKEXNEWS_PREFIX_URL with the bare stock code to get candidate
     {stockId, code, name} suggestions.
  2. Pick the suggestion whose own `code` field matches the requested ticker
     (normalized to bare digits) -- there can be multiple prefix matches
     (e.g. "00005" also prefix-matches "00050", "00051", ...).
  3. Call HKEXNEWS_TITLE_SEARCH_URL with that resolved internal stockId.
  4. Non-negotiable final guard: every row returned must have its own
     STOCK_CODE (normalized to bare digits) match the ticker that was
     requested. Any row that doesn't match is dropped and logged -- never
     silently kept. This is verified positively and negatively in
     tests/test_hkexnews_announcements.py.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    HKEXNEWS_PREFIX_URL,
    HKEXNEWS_SEARCH_REFERER,
    HKEXNEWS_TITLE_SEARCH_URL,
    WATCHLIST,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "ticker",
    "stock_code",
    "stock_name",
    "news_id",
    "title",
    "short_text",
    "date_time",
    "file_link",
    "file_type",
    "fetched_at",
]

LOOKBACK_DAYS = 90
_SEARCH_HEADERS = {**DEFAULT_HEADERS, "Referer": HKEXNEWS_SEARCH_REFERER}


def _normalize_code(code: str) -> str:
    """Strip a leading '.HK'/'HK' suffix and leading zeros -- e.g. '00863.HK' -> '863'."""
    bare = re.sub(r"\.HK$", "", str(code).strip(), flags=re.IGNORECASE)
    bare = bare.lstrip("0")
    return bare or "0"


def all_watchlist_tickers() -> list[str]:
    """Flatten config.WATCHLIST (TIER_1..TIER_4) into a plain list of ticker strings."""
    tickers: list[str] = []
    for entries in WATCHLIST.values():
        for entry in entries:
            ticker = entry.get("ticker")
            if ticker:
                tickers.append(ticker)
    return tickers


def _resolve_stock_id(ticker: str) -> tuple[str, str] | None:
    """Resolve a ticker's plain code to the internal numeric stockId the search
    servlet actually filters on, via the prefix.do autocomplete endpoint.

    Returns (stock_id, resolved_code) or None if no exact code match was found
    among the autocomplete suggestions.
    """
    bare_code = _normalize_code(ticker)
    padded_code = bare_code.zfill(5)

    resp = requests.get(
        HKEXNEWS_PREFIX_URL,
        params={"callback": "callback", "lang": "EN", "type": "A", "name": padded_code, "market": "SEHK"},
        headers=_SEARCH_HEADERS,
        timeout=DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    text = resp.text.strip()

    # Response is JSONP: callback({...});  -- unwrap it.
    match = re.search(r"\((\{.*\})\)", text, flags=re.DOTALL)
    if not match:
        logger.warning("hkexnews prefix.do: unexpected response shape for ticker %s: %r", ticker, text[:200])
        return None

    payload = json.loads(match.group(1))
    suggestions = payload.get("stockInfo") or []

    for suggestion in suggestions:
        suggestion_code = _normalize_code(str(suggestion.get("code", "")))
        if suggestion_code == bare_code:
            return str(suggestion.get("stockId")), suggestion_code

    logger.warning(
        "hkexnews prefix.do: no exact code match for ticker %s (bare_code=%s) among suggestions %s",
        ticker, bare_code, suggestions,
    )
    return None


def fetch_ticker_announcements(ticker: str, *, lookback_days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """Fetch recent HKEXnews announcements for a single watchlist ticker.

    Resolves `ticker` to HKEXnews' internal stockId first (see module
    docstring for why this is required), then queries the title search
    servlet and drops any row whose own STOCK_CODE does not match the
    requested ticker.
    """
    now = datetime.now(timezone.utc)
    now_str = now.isoformat()
    bare_code = _normalize_code(ticker)

    try:
        resolved = _resolve_stock_id(ticker)
        if resolved is None:
            logger.warning("Could not resolve stockId for ticker %s; skipping.", ticker)
            return pd.DataFrame(columns=SCHEMA_COLUMNS)

        stock_id, _resolved_code = resolved

        params = {
            "sortDir": "0",
            "sortByOptions": "DateTime",
            "category": "0",
            "market": "SEHK",
            "stockId": stock_id,
            "documentType": "-1",
            "fromDate": (now - timedelta(days=lookback_days)).strftime("%Y%m%d"),
            "toDate": now.strftime("%Y%m%d"),
            "title": "",
            "searchType": "1",
            "t1code": "-2",
            "t2Gcode": "-2",
            "t2code": "-2",
            "rowRange": "100",
            "lang": "E",
        }

        resp = requests.get(
            HKEXNEWS_TITLE_SEARCH_URL,
            params=params,
            headers=_SEARCH_HEADERS,
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        outer = resp.json()

        save_raw_snapshot(
            f"hkexnews_announcements_{bare_code}",
            outer,
            file_ext="json",
            source_url=resp.url,
        )

        raw_rows = json.loads(outer.get("result") or "[]")

        kept_rows = []
        dropped = 0
        for row in raw_rows:
            # STOCK_CODE can be a "<br/>"-joined multi-listing string, e.g.
            # "00700<br/>80700" for a stock with both an ordinary and a
            # secondary/ADR-style listing code. Compare against every code in it.
            raw_stock_code = str(row.get("STOCK_CODE", ""))
            codes_in_row = [_normalize_code(c) for c in re.split(r"<br\s*/?>", raw_stock_code) if c.strip()]

            if bare_code not in codes_in_row:
                dropped += 1
                logger.warning(
                    "Dropping HKEXnews row for ticker %s: STOCK_CODE=%r does not match requested code %s (news_id=%s)",
                    ticker, raw_stock_code, bare_code, row.get("NEWS_ID"),
                )
                continue

            kept_rows.append({
                "ticker": ticker,
                "stock_code": raw_stock_code.split("<br")[0].strip(),
                "stock_name": row.get("STOCK_NAME", ""),
                "news_id": str(row.get("NEWS_ID", "")),
                "title": row.get("TITLE", ""),
                "short_text": row.get("SHORT_TEXT", ""),
                "date_time": row.get("DATE_TIME", ""),
                "file_link": row.get("FILE_LINK", ""),
                "file_type": row.get("FILE_TYPE", ""),
                "fetched_at": now_str,
            })

        if dropped:
            logger.warning(
                "hkexnews_announcements: dropped %d/%d mismatched rows for ticker %s",
                dropped, len(raw_rows), ticker,
            )

        if not kept_rows:
            return pd.DataFrame(columns=SCHEMA_COLUMNS)

        return pd.DataFrame(kept_rows)[SCHEMA_COLUMNS]

    except Exception:
        logger.exception("Failed to fetch HKEXnews announcements for ticker %s.", ticker)
        return pd.DataFrame(columns=SCHEMA_COLUMNS)


def fetch_hkexnews_announcements(
    tickers: list[str] | None = None,
    *,
    lookback_days: int = LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Fetch recent HKEXnews announcements for every ticker in `tickers`
    (defaults to the full HK Stablecoin & Crypto watchlist), tag each row
    with its ticker, and return one combined DataFrame.
    """
    if tickers is None:
        tickers = all_watchlist_tickers()

    frames = []
    for ticker in tickers:
        df = fetch_ticker_announcements(ticker, lookback_days=lookback_days)
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["ticker", "news_id"]).reset_index(drop=True)

    save_raw_snapshot(
        "hkexnews_announcements_combined",
        combined.to_dict(orient="records"),
        file_ext="json",
        source_url=HKEXNEWS_TITLE_SEARCH_URL,
    )

    return combined
