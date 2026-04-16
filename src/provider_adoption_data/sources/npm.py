from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from urllib.parse import quote

import requests

from provider_adoption_data.models import NpmDownloadPoint, ProviderConfig, Snapshot, sanitize_filename


class NpmDownloadsSource:
    BASE_URL = "https://api.npmjs.org/downloads/range"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "alternative-data-provider-adoption/0.1")

    def fetch_snapshots(self, providers: Iterable[ProviderConfig], start_date: date, end_date: date) -> list[Snapshot]:
        snapshots: list[Snapshot] = []
        for provider in providers:
            for package in provider.npm_packages:
                encoded_package = quote(package.package_name, safe="@")
                url = f"{self.BASE_URL}/{start_date.isoformat()}:{end_date.isoformat()}/{encoded_package}"
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                snapshots.append(
                    Snapshot(
                        name=sanitize_filename(f"npm_{provider.slug}_{package.package_name}"),
                        source_url=url,
                        body=response.text,
                    )
                )
        return snapshots

    def extract(self, snapshots: Iterable[Snapshot], providers: Iterable[ProviderConfig]) -> list[NpmDownloadPoint]:
        by_slug = {provider.slug: provider for provider in providers}
        points: list[NpmDownloadPoint] = []
        for snapshot in snapshots:
            payload = json.loads(snapshot.body)
            package_name = str(payload.get("package", ""))
            provider = next(
                (
                    provider
                    for provider in by_slug.values()
                    if any(package.package_name == package_name for package in provider.npm_packages)
                ),
                None,
            )
            if provider is None:
                continue
            package = next(package for package in provider.npm_packages if package.package_name == package_name)
            for row in payload.get("downloads", []):
                points.append(
                    NpmDownloadPoint(
                        provider=provider.slug,
                        provider_display_name=provider.display_name,
                        package_name=package_name,
                        package_type=package.package_type,
                        package_category=package.package_category,
                        download_date=str(row.get("day")),
                        downloads=int(row.get("downloads") or 0),
                        source_url=snapshot.source_url,
                    )
                )
        return points
