from __future__ import annotations

from time import monotonic

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from provider_incident_data.models import FetchFailure, Snapshot, SourceSpec


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec("openai", "OpenAI", "statuspage_json", "https://status.openai.com/api/v2/incidents.json", "statuspage"),
    SourceSpec("anthropic", "Anthropic", "statuspage_json", "https://status.claude.com/api/v2/incidents.json", "statuspage"),
    SourceSpec("google", "Google", "google_cloud_json", "https://status.cloud.google.com/incidents.json", "google"),
    SourceSpec("deepseek", "DeepSeek", "atom", "https://status.deepseek.com/feed.atom", "feed"),
    SourceSpec("xai", "xAI", "rss", "https://status.x.ai/feed.xml", "feed"),
    SourceSpec("mistral", "Mistral AI", "atom", "https://status.mistral.ai/feed.atom", "feed"),
    SourceSpec("cohere", "Cohere", "statuspage_json", "https://status.cohere.com/api/v2/incidents.json", "statuspage"),
    SourceSpec("openrouter", "OpenRouter", "rss", "https://status.openrouter.ai/incidents.rss", "feed"),
)


class ProviderIncidentSource:
    """Low-volume client for official, public provider status feeds."""

    def __init__(self, *, timeout: int = 30, specs: tuple[SourceSpec, ...] = SOURCE_SPECS) -> None:
        self.timeout = timeout
        self.specs = specs
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json, application/atom+xml, application/rss+xml, application/xml, text/xml;q=0.9",
                "User-Agent": "alternative-data-dashboard/0.2 (+https://github.com/Henrywzh/alternative-data)",
            }
        )
        retry = Retry(
            total=1,
            connect=1,
            read=1,
            status=1,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def fetch_all(self) -> tuple[list[Snapshot], list[FetchFailure]]:
        snapshots: list[Snapshot] = []
        failures: list[FetchFailure] = []
        for spec in self.specs:
            started = monotonic()
            try:
                response = self.session.get(spec.source_url, timeout=self.timeout)
                response.raise_for_status()
                snapshots.append(
                    Snapshot(
                        provider_id=spec.provider_id,
                        provider_name=spec.provider_name,
                        source_kind=spec.source_kind,
                        source_url=response.url,
                        parser=spec.parser,
                        body=response.text,
                        content_type=response.headers.get("Content-Type", ""),
                        status_code=response.status_code,
                        response_ms=round((monotonic() - started) * 1000),
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                    )
                )
            except requests.RequestException as exc:
                response = getattr(exc, "response", None)
                failures.append(
                    FetchFailure(
                        provider_id=spec.provider_id,
                        provider_name=spec.provider_name,
                        source_kind=spec.source_kind,
                        source_url=spec.source_url,
                        error=f"{type(exc).__name__}: {exc}",
                        status_code=getattr(response, "status_code", None),
                    )
                )
        return snapshots, failures
