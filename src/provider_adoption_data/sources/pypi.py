from __future__ import annotations

import json
import logging
import time
from typing import Iterable

import requests

from provider_adoption_data.models import ProviderConfig, PypiDownloadPoint, Snapshot, sanitize_filename


class PypiStatsSource:
    BASE_URL = "https://pypistats.org/api/packages"
    MAX_RETRIES = 2
    BASE_RETRY_DELAY_SECONDS = 2.0
    MAX_RETRY_DELAY_SECONDS = 60.0
    RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "alternative-data-provider-adoption/0.1")

    def fetch_snapshots(self, providers: Iterable[ProviderConfig]) -> list[Snapshot]:
        snapshots: list[Snapshot] = []
        for provider in providers:
            for package in provider.pypi_packages:
                url = f"{self.BASE_URL}/{package.package_name}/overall"
                snapshot = self._fetch_snapshot(provider.slug, package.package_name, url)
                if snapshot is not None:
                    snapshots.append(snapshot)
        return snapshots

    def _fetch_snapshot(self, provider_slug: str, package_name: str, url: str) -> Snapshot | None:
        max_attempts = self.MAX_RETRIES + 1
        for attempt in range(1, max_attempts + 1):
            response = None
            try:
                response = self.session.get(url, timeout=30)
            except (requests.ConnectionError, requests.Timeout) as exc:
                reason = type(exc).__name__
            else:
                if response.status_code not in self.RETRYABLE_STATUS_CODES:
                    response.raise_for_status()
                    return Snapshot(
                        name=sanitize_filename(f"pypi_{provider_slug}_{package_name}"),
                        source_url=url,
                        body=response.text,
                    )
                reason = f"HTTP {response.status_code}"

            if attempt == max_attempts:
                logging.warning(
                    "PyPIStats unavailable provider=%s package=%s (%s) after %s attempts; skipping package",
                    provider_slug, package_name, reason, attempt,
                )
                return None
            delay_seconds = (
                self._retry_delay_seconds(response, attempt)
                if response is not None
                else self.BASE_RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
            )
            logging.warning(
                "PyPIStats unavailable provider=%s package=%s (%s); retrying in %.1fs (attempt %s/%s)",
                provider_slug, package_name, reason, delay_seconds, attempt, max_attempts,
            )
            time.sleep(delay_seconds)
        return None

    def _retry_delay_seconds(self, response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return min(max(float(retry_after), 0.0), self.MAX_RETRY_DELAY_SECONDS)
            except ValueError:
                pass
        return self.BASE_RETRY_DELAY_SECONDS * (2 ** (attempt - 1))

    def extract(self, snapshots: Iterable[Snapshot], providers: Iterable[ProviderConfig]) -> list[PypiDownloadPoint]:
        by_slug = {provider.slug: provider for provider in providers}
        points: list[PypiDownloadPoint] = []
        for snapshot in snapshots:
            payload = json.loads(snapshot.body)
            package_name = str(payload.get("package", ""))
            provider = next(
                (
                    provider
                    for provider in by_slug.values()
                    if any(package.package_name == package_name for package in provider.pypi_packages)
                ),
                None,
            )
            if provider is None:
                continue
            package = next(
                package for package in provider.pypi_packages if package.package_name == package_name
            )
            for row in payload.get("data", []):
                category = str(row.get("category", "without_mirrors")).strip().lower()
                points.append(
                    PypiDownloadPoint(
                        provider=provider.slug,
                        provider_display_name=provider.display_name,
                        package_name=package_name,
                        package_type=package.package_type,
                        package_category=package.package_category,
                        with_mirrors=category == "with_mirrors",
                        download_date=str(row.get("date")),
                        downloads=int(row.get("downloads") or 0),
                        source_url=snapshot.source_url,
                    )
                )
        return points
