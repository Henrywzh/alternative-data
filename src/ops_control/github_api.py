from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


GITHUB_API = "https://api.github.com"


class GitHubAPIError(RuntimeError):
    """Raised when a GitHub API call fails."""


def request_json(
    url: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "alternative-data-ops-control",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GitHubAPIError(f"GitHub API {method} {url} failed: {exc.code} {detail}") from exc
    except URLError as exc:
        raise GitHubAPIError(f"GitHub API {method} {url} failed: {exc.reason}") from exc
    if not raw:
        return None
    parsed = json.loads(raw.decode("utf-8"))
    return parsed


def _list_batch(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("items", "artifacts", "workflow_runs"):
        batch = payload.get(key)
        if isinstance(batch, list):
            return batch
    return []


def paginate(
    url: str,
    *,
    token: str,
    params: dict[str, Any] | None = None,
) -> list[Any]:
    query = dict(params or {})
    query.setdefault("per_page", 100)
    items: list[Any] = []
    page = 1
    while True:
        query["page"] = page
        separator = "&" if "?" in url else "?"
        joined = f"{url}{separator}{urlencode(query)}"
        payload = request_json(joined, token=token)
        batch = _list_batch(payload)
        if not isinstance(batch, list):
            raise GitHubAPIError(f"Unexpected GitHub list payload from {joined}")
        items.extend(batch)
        if len(batch) < int(query["per_page"]):
            return items
        page += 1


def quote_path(value: str) -> str:
    return quote(value, safe="")
