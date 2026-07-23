from __future__ import annotations

import time

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _get_with_retries(url: str, *, headers: dict | None = None, retries: int, timeout: int) -> requests.Response:
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=hdrs, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_exc}") from last_exc


def fetch_json(url: str, *, headers: dict | None = None, retries: int = 3, timeout: int = 20):
    return _get_with_retries(url, headers=headers, retries=retries, timeout=timeout).json()


def fetch_text(url: str, *, headers: dict | None = None, retries: int = 3, timeout: int = 20) -> str:
    return _get_with_retries(url, headers=headers, retries=retries, timeout=timeout).text
