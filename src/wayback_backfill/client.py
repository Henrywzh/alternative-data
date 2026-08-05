"""Thin client for enumerating and fetching Wayback Machine captures.

Used to backfill OpenRouter datasets from before this repo started scraping.
Wayback has no published rate limit, but it does return 429s under load, so
every call here is polite by default: one request in flight, a fixed delay
between requests, and exponential backoff on failure.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

CDX_URL = "https://web.archive.org/cdx/search/cdx"
CAPTURE_URL_TEMPLATE = "https://web.archive.org/web/{timestamp}id_/{original}"


@dataclass(frozen=True)
class Capture:
    timestamp: str  # "20250403043148"
    original: str

    @property
    def capture_date(self) -> str:
        return f"{self.timestamp[0:4]}-{self.timestamp[4:6]}-{self.timestamp[6:8]}"


class WaybackClient:
    def __init__(
        self,
        *,
        request_delay_seconds: float = 1.5,
        timeout: int = 60,
        max_retries: int = 4,
        user_agent: str = "alternative-data-wayback-backfill/1.0 (research use)",
    ) -> None:
        self.request_delay_seconds = request_delay_seconds
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._last_request_at: float | None = None

    def list_snapshots(
        self,
        url: str,
        *,
        from_date: str,
        to_date: str,
        collapse_digits: int = 8,
    ) -> list[Capture]:
        """List distinct-day 200-status captures of `url` between from_date/to_date (YYYYMMDD)."""
        params = {
            "url": url,
            "output": "json",
            "from": from_date,
            "to": to_date,
            "filter": "statuscode:200",
            "collapse": f"timestamp:{collapse_digits}",
            "fl": "timestamp,original",
        }
        body = self._get(CDX_URL, params=params)
        rows = self._parse_cdx_json(body)
        return [Capture(timestamp=row[0], original=row[1]) for row in rows]

    def fetch_capture(self, capture: Capture) -> str:
        """Fetch the raw archived body for a capture (the `id_` modifier returns the
        unmodified original bytes, without Wayback's banner/link-rewriting)."""
        capture_url = CAPTURE_URL_TEMPLATE.format(
            timestamp=capture.timestamp, original=quote(capture.original, safe=":/?&=")
        )
        return self._get(capture_url)

    def _parse_cdx_json(self, body: str) -> list[list[str]]:
        import json

        if not body.strip():
            return []
        data = json.loads(body)
        if not data or len(data) < 2:
            return []
        return data[1:]  # first row is the header ["timestamp", "original"]

    def _get(self, url: str, *, params: dict | None = None) -> str:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code == 429:
                    wait = 5.0 * (attempt + 1)
                    logger.warning("Wayback rate-limited us; backing off %.1fs", wait)
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                return response.text
            except requests.RequestException as exc:
                last_exc = exc
                wait = 2.0 * (2**attempt)
                logger.warning("Wayback request failed (attempt %d/%d): %s; retrying in %.1fs", attempt + 1, self.max_retries, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"Wayback request to {url} failed after {self.max_retries} attempts") from last_exc

    def _throttle(self) -> None:
        if self._last_request_at is None:
            self._last_request_at = time.monotonic()
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.request_delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()
