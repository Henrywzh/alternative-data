from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


API_BASE = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class Snapshot:
    name: str
    source_url: str
    body: str
    query: dict[str, str | int]


class OpenRouterOfficialSource:
    """Small authenticated client for OpenRouter's documented public datasets."""

    def __init__(self, api_key: str, timeout: int = 45) -> None:
        if not api_key.strip():
            raise ValueError("OPENROUTER_API_KEY is required for official OpenRouter datasets")
        self.timeout = timeout
        self.last_failures: list[dict[str, str]] = []
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "alternative-data-dashboard/0.2 (+https://github.com/Henrywzh/alternative-data)",
                "HTTP-Referer": "https://github.com/Henrywzh/alternative-data",
                "X-OpenRouter-Title": "Alternative Data Dashboard",
            }
        )
        retry = Retry(
            total=4,
            connect=3,
            read=3,
            status=4,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _fetch(self, name: str, path: str, **params: str | int) -> Snapshot:
        url = f"{API_BASE}{path}"
        response = self.session.get(url, params=params or None, timeout=self.timeout)
        response.raise_for_status()
        return Snapshot(name=name, source_url=response.url, body=response.text, query=dict(params))

    def _fetch_optional(self, name: str, path: str, **params: str | int) -> Snapshot | None:
        try:
            return self._fetch(name, path, **params)
        except requests.RequestException as exc:
            self.last_failures.append(
                {"name": name, "path": path, "error": f"{type(exc).__name__}: {exc}"}
            )
            return None

    def fetch_daily_snapshots(self, *, target_date: date | None = None, lookback_days: int = 35) -> list[Snapshot]:
        self.last_failures = []
        end_date = target_date or (date.today() - timedelta(days=1))
        start_date = end_date - timedelta(days=lookback_days - 1)
        common_dates = {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}

        # Market totals are the core dataset and fail the run loudly. Auxiliary
        # sources are isolated so one endpoint outage cannot block fresh totals.
        snapshots = [self._fetch("rankings_daily", "/datasets/rankings-daily", period="day", **common_dates)]
        for optional in (
            self._fetch_optional("task_classifications", "/classifications/task", window="7d"),
            self._fetch_optional("providers", "/providers"),
            self._fetch_optional("benchmarks", "/benchmarks"),
        ):
            if optional is not None:
                snapshots.append(optional)
        for ranking_type in ("popular", "trending"):
            for offset in (0, 100):
                optional = self._fetch_optional(
                    f"app_rankings_{ranking_type}_{offset}",
                    "/datasets/app-rankings",
                    sort=ranking_type,
                    limit=100,
                    offset=offset,
                    **common_dates,
                )
                if optional is not None:
                    snapshots.append(optional)
        return snapshots

    def fetch_rankings_backfill(self, *, start_date: date, end_date: date) -> list[Snapshot]:
        self.last_failures = []
        return [
            self._fetch(
                "rankings_daily_backfill",
                "/datasets/rankings-daily",
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                period="day",
            )
        ]


def parse_json(snapshot: Snapshot) -> dict[str, Any]:
    payload = json.loads(snapshot.body)
    if not isinstance(payload, dict):
        raise ValueError(f"{snapshot.name} returned a non-object payload")
    return payload
