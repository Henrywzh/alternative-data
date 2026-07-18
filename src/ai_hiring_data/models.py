from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    source_kind: str
    source_url: str
    company_id: str | None = None
    company_name: str | None = None
    company_segment: str | None = None
    source_platform: str | None = None
    board_token: str | None = None
    careers_url: str | None = None


@dataclass(frozen=True)
class Snapshot:
    source_id: str
    source_kind: str
    source_url: str
    body: str | None
    content_type: str
    status_code: int
    response_ms: int
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


@dataclass(frozen=True)
class FetchFailure:
    source_id: str
    source_kind: str
    source_url: str
    error: str
    company_id: str | None = None
    company_name: str | None = None
    status_code: int | None = None
