from __future__ import annotations

import json
from typing import Iterable

import requests

from provider_adoption_data.models import ProviderConfig, PypiDownloadPoint, Snapshot, sanitize_filename


class PypiStatsSource:
    BASE_URL = "https://pypistats.org/api/packages"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "alternative-data-provider-adoption/0.1")

    def fetch_snapshots(self, providers: Iterable[ProviderConfig]) -> list[Snapshot]:
        snapshots: list[Snapshot] = []
        for provider in providers:
            for package in provider.pypi_packages:
                url = f"{self.BASE_URL}/{package.package_name}/overall"
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                snapshots.append(
                    Snapshot(
                        name=sanitize_filename(f"pypi_{provider.slug}_{package.package_name}"),
                        source_url=url,
                        body=response.text,
                    )
                )
        return snapshots

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
            package_type = next(
                package.package_type for package in provider.pypi_packages if package.package_name == package_name
            )
            for row in payload.get("data", []):
                category = str(row.get("category", "without_mirrors")).strip().lower()
                points.append(
                    PypiDownloadPoint(
                        provider=provider.slug,
                        provider_display_name=provider.display_name,
                        package_name=package_name,
                        package_type=package_type,
                        with_mirrors=category == "with_mirrors",
                        download_date=str(row.get("date")),
                        downloads=int(row.get("downloads") or 0),
                        source_url=snapshot.source_url,
                    )
                )
        return points
