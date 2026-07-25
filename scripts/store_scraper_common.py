"""Shared helpers for the HK retail/F&B store-count scrapers in this directory.

Every scrape_*_stores.py script here follows the same shape: fetch live data
from a public store-locator endpoint, count stores by region, and append a
deduplicated snapshot to a parquet file. This module factors out the two
pieces of that shape that were previously duplicated verbatim across all 8
scripts (and inconsistently implemented in some of them): the retrying HTTP
fetch and the snapshot-append logic.
"""

from __future__ import annotations

import time
import urllib.request
from pathlib import Path
from typing import Optional

import pandas as pd

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_url(
    url: str,
    *,
    headers: Optional[dict] = None,
    method: str = "GET",
    data: Optional[bytes] = None,
    timeout: int = 30,
    attempts: int = 3,
    backoff_seconds: float = 2.0,
) -> Optional[bytes]:
    """Fetch a URL with retries, returning the response body or None on failure.

    Never raises -- every scraper in this directory treats "couldn't fetch"
    as an honest empty result for that run (no data today, prior history
    untouched) rather than a crash. This matters concretely: a single
    company's transient network blip must not abort every scraper listed
    after it in a scheduled batch run. Real endpoints tested clean under
    normal certificate verification (no ssl._create_unverified_context()
    needed anywhere in this directory as of 2026-07), so this always
    verifies certs.
    """
    req_headers = dict(headers or {})
    req_headers.setdefault("User-Agent", DEFAULT_USER_AGENT)

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers=req_headers, method=method, data=data)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - deliberately broad; see docstring
            last_error = exc
            if attempt < attempts:
                time.sleep(backoff_seconds * attempt)
    print(f"  Fetch failed after {attempts} attempts: {url} ({last_error})")
    return None


def append_snapshot(df: pd.DataFrame, out_path: Path, key_column: str = "region") -> pd.DataFrame:
    """Append a snapshot to an existing parquet file, deduplicated on (date, key_column).

    `key_column` is "region" for most of these scrapers, but a few group by
    a differently-named column instead (e.g. Fairwood's "category") -- pass
    that column name explicitly in those cases.

    An empty `df` (fetch failed / no data extracted) leaves the existing
    file untouched rather than overwriting real history with nothing.
    """
    existing = pd.read_parquet(out_path) if out_path.exists() else None
    if df.empty:
        return existing if existing is not None else df
    combined = df if existing is None else pd.concat([existing, df], ignore_index=True)
    combined = (
        combined.drop_duplicates(subset=["date", key_column], keep="last")
        .sort_values(["date", key_column])
        .reset_index(drop=True)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(out_path, index=False)
    return combined
