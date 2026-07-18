from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    provider_id: str
    provider_name: str
    source_kind: str
    source_url: str
    parser: str


@dataclass(frozen=True)
class Snapshot:
    provider_id: str
    provider_name: str
    source_kind: str
    source_url: str
    parser: str
    body: str
    content_type: str
    status_code: int
    response_ms: int
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class FetchFailure:
    provider_id: str
    provider_name: str
    source_kind: str
    source_url: str
    error: str
    status_code: int | None = None
