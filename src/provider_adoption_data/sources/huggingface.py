from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from provider_adoption_data.models import HuggingFaceModelPoint, ProviderConfig, Snapshot


class HuggingFaceSource:
    BASE_URL = "https://huggingface.co/api/models"
    EXPAND_FIELDS = ("author", "downloads", "downloadsAllTime", "likes", "lastModified")

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "alternative-data-provider-adoption/0.1")
        token = os.getenv("HF_TOKEN")
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def fetch_snapshots(self, providers: Iterable[ProviderConfig]) -> list[Snapshot]:
        snapshots: list[Snapshot] = []
        for provider in providers:
            for org in provider.huggingface_orgs:
                source_url = self._build_source_url(org)
                payload: list[dict] = []
                next_url: str | None = source_url

                while next_url:
                    response = self.session.get(next_url, timeout=30)
                    response.raise_for_status()
                    page = response.json()
                    if not isinstance(page, list):
                        break
                    payload.extend(page)
                    next_url = response.links.get("next", {}).get("url")

                snapshots.append(
                    Snapshot(
                        name=f"huggingface_{provider.slug}_{org.replace('-', '_')}",
                        source_url=source_url,
                        body=json.dumps(payload),
                    )
                )
        return snapshots

    def extract(self, snapshots: Iterable[Snapshot], providers: Iterable[ProviderConfig]) -> list[HuggingFaceModelPoint]:
        by_org = {org: provider for provider in providers for org in provider.huggingface_orgs}
        points: list[HuggingFaceModelPoint] = []
        scraped_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        for snapshot in snapshots:
            org = self._extract_org_from_source_url(snapshot.source_url)
            provider = by_org.get(org)
            if not provider:
                continue

            try:
                models = json.loads(snapshot.body)
            except json.JSONDecodeError:
                continue

            if not isinstance(models, list):
                continue

            for model in models:
                model_id = model.get("id")
                if not model_id:
                    continue

                author = model.get("author") or self._extract_author_from_model_id(model_id) or org
                downloads_30d = model.get("downloads", 0)
                downloads_all_time = model.get("downloadsAllTime", 0)
                likes = model.get("likes", 0)
                last_modified = model.get("lastModified", "")

                points.append(
                    HuggingFaceModelPoint(
                        provider=provider.slug,
                        author=author,
                        model_id=model_id,
                        downloads_30d=int(downloads_30d),
                        downloads_all_time=int(downloads_all_time),
                        likes=int(likes),
                        last_modified=last_modified,
                        scraped_at=scraped_at,
                        source_url=snapshot.source_url,
                    )
                )

        return points

    def _build_source_url(self, org: str) -> str:
        params: list[tuple[str, str]] = [("author", org)]
        params.extend(("expand", field) for field in self.EXPAND_FIELDS)
        return f"{self.BASE_URL}?{urlencode(params)}"

    @staticmethod
    def _extract_org_from_source_url(source_url: str) -> str | None:
        parsed = urlparse(source_url)
        params = parse_qs(parsed.query)
        authors = params.get("author")
        return authors[0] if authors else None

    @staticmethod
    def _extract_author_from_model_id(model_id: str) -> str | None:
        if "/" not in model_id:
            return None
        author, _ = model_id.split("/", 1)
        return author or None
