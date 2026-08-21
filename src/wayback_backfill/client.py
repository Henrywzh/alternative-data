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
from datetime import date, timedelta
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


@dataclass(frozen=True)
class CaptureCoveragePlan:
    """Minimal archived captures and any target ranges they cannot cover."""

    selected: tuple[Capture, ...]
    uncovered_ranges: tuple[tuple[str, str], ...]


def plan_rolling_window_captures(
    captures: list[Capture],
    *,
    start_date: date,
    end_date: date,
    window_days: int = 91,
) -> CaptureCoveragePlan:
    """Greedily choose the fewest captures that cover a rolling chart history.

    Each archived page is treated as an interval ending on its capture date and
    spanning ``window_days`` calendar days.  The returned gap ranges make
    incomplete Wayback coverage explicit instead of silently presenting a
    discontinuous backfill as complete.
    """
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    if window_days < 1:
        raise ValueError("window_days must be positive")

    intervals: list[tuple[date, date, Capture]] = []
    for capture in captures:
        try:
            captured_on = date.fromisoformat(capture.capture_date)
        except ValueError:
            continue
        intervals.append(
            (
                captured_on - timedelta(days=window_days - 1),
                captured_on,
                capture,
            )
        )
    intervals.sort(key=lambda item: (item[0], item[1], item[2].timestamp))

    selected: list[Capture] = []
    gaps: list[tuple[str, str]] = []
    cursor = start_date
    while cursor <= end_date:
        covering = [
            interval
            for interval in intervals
            if interval[0] <= cursor <= interval[1]
        ]
        if covering:
            best = max(covering, key=lambda item: (item[1], item[2].timestamp))
            if not selected or selected[-1].timestamp != best[2].timestamp:
                selected.append(best[2])
            cursor = best[1] + timedelta(days=1)
            continue

        future_starts = [interval[0] for interval in intervals if interval[0] > cursor]
        if not future_starts:
            gaps.append((cursor.isoformat(), end_date.isoformat()))
            break
        next_start = min(future_starts)
        gap_end = min(end_date, next_start - timedelta(days=1))
        gaps.append((cursor.isoformat(), gap_end.isoformat()))
        cursor = next_start

    return CaptureCoveragePlan(
        selected=tuple(sorted(selected, key=lambda capture: capture.timestamp)),
        uncovered_ranges=tuple(gaps),
    )


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
