from __future__ import annotations

import time
from time import monotonic

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ai_hiring_data.config import SOURCE_SPECS
from ai_hiring_data.models import FetchFailure, Snapshot, SourceSpec


class AIHiringSource:
    """Low-frequency client for official public ATS and aggregate hiring data."""

    def __init__(
        self,
        *,
        timeout: int = 45,
        spacing_seconds: float = 1.0,
        specs: tuple[SourceSpec, ...] = SOURCE_SPECS,
    ) -> None:
        self.timeout = timeout
        self.spacing_seconds = spacing_seconds
        self.specs = specs
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json, text/csv;q=0.9, text/plain;q=0.8",
                "User-Agent": "alternative-data-dashboard/0.2 (+https://github.com/Henrywzh/alternative-data)",
            }
        )
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def fetch_all(
        self,
        validators: dict[str, dict[str, str | None]] | None = None,
    ) -> tuple[list[Snapshot], list[FetchFailure]]:
        validators = validators or {}
        snapshots: list[Snapshot] = []
        failures: list[FetchFailure] = []
        for index, spec in enumerate(self.specs):
            headers: dict[str, str] = {}
            validator = validators.get(spec.source_id, {})
            if validator.get("etag"):
                headers["If-None-Match"] = str(validator["etag"])
            if validator.get("last_modified"):
                headers["If-Modified-Since"] = str(validator["last_modified"])
            started = monotonic()
            try:
                response = self.session.get(spec.source_url, headers=headers, timeout=self.timeout)
                if response.status_code == 304:
                    snapshots.append(
                        Snapshot(
                            source_id=spec.source_id,
                            source_kind=spec.source_kind,
                            source_url=response.url,
                            body=None,
                            content_type=response.headers.get("Content-Type", ""),
                            status_code=304,
                            response_ms=round((monotonic() - started) * 1000),
                            etag=response.headers.get("ETag") or validator.get("etag"),
                            last_modified=response.headers.get("Last-Modified") or validator.get("last_modified"),
                            not_modified=True,
                        )
                    )
                else:
                    response.raise_for_status()
                    snapshots.append(
                        Snapshot(
                            source_id=spec.source_id,
                            source_kind=spec.source_kind,
                            source_url=response.url,
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
                        source_id=spec.source_id,
                        source_kind=spec.source_kind,
                        source_url=spec.source_url,
                        company_id=spec.company_id,
                        company_name=spec.company_name,
                        error=f"{type(exc).__name__}: {exc}",
                        status_code=getattr(response, "status_code", None),
                    )
                )
            if self.spacing_seconds > 0 and index < len(self.specs) - 1:
                time.sleep(self.spacing_seconds)
        return snapshots, failures
