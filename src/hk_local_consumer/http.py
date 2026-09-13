"""Bounded-retry HTTP for this sector's public sources.

Two different transient failures reach these endpoints, and an adapter-level
``urllib3.Retry`` only covers one of them.

``Retry`` mounted on an ``HTTPAdapter`` retries inside ``urlopen`` -- connect
failures, read timeouts, and the retryable status codes. It does **not**
reliably cover a response that dies while its *body* is being read, which is
what happens to a large chunked download: requests raises
``ChunkedEncodingError: Response ended prematurely`` out of ``send()``, past
the point where the adapter can retry.

That is not hypothetical. FEHD's 4.8 MB licensed-premises XML failed exactly
that way on 2026-09-13, which under ``--strict`` failed the whole stage-1
ingest, degraded the Asia Markets dashboard refresh to
``DEGRADED_RETAINED``, and opened a NEEDS_HUMAN incident -- for one dropped
connection to one source.

So the retry wraps the whole request *and* the body read.
"""

from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import DEFAULT_HEADERS

logger = logging.getLogger(__name__)

RETRY_STATUS_CODES = (429, 500, 502, 503, 504)
DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 1.0


def _session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.5,
        status_forcelist=RETRY_STATUS_CODES,
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_with_retry(
    url: str,
    *,
    timeout: tuple[float, float] = (8.0, 30.0),
    attempts: int = DEFAULT_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    sleep = time.sleep,
) -> requests.Response:
    """GET ``url``, retrying transient transport failures and 5xx.

    Touching ``response.content`` here is deliberate: it forces the body to be
    read inside the retry loop, so a truncated download is retried rather than
    surfacing to the caller as a successful response that explodes later.
    """
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            response = _session().get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            response.raise_for_status()
            _ = response.content
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= attempts:
                break
            delay = backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                "GET %s failed on attempt %s/%s (%s); retrying in %.1fs",
                url, attempt, attempts, type(exc).__name__, delay,
            )
            sleep(delay)
    assert last_error is not None
    raise last_error
