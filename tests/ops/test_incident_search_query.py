"""The incident search query GitHub will actually accept.

Every Ops Reconciliation run failed -- the scheduled one and all three manual
retries -- on:

    GitHub API GET https://api.github.com/search/issues?q=... failed: 422
    {"message": "Query must include 'is:issue' or 'is:pull-request'"}

The search/issues endpoint rejects a query that does not say which of the two
it wants. Nothing caught it because the query is built as a bare f-string and
the only coverage of this path mocked the transport, so the string itself was
never asserted on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ops_control.store import IncidentStore


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "ops" / "incident.schema.json"


def _captured_query(monkeypatch) -> str:
    seen: dict[str, str] = {}

    def fake_paginate(url, *, token=None, params=None, **kwargs):
        seen["url"] = url
        seen["q"] = (params or {}).get("q", "")
        return []

    monkeypatch.setattr("ops_control.store.paginate", fake_paginate)
    store = IncidentStore(
        repository="owner/ops", token="t", schema_path=SCHEMA
    )
    store.find_by_fingerprint("abc123")
    assert seen["url"] == "https://api.github.com/search/issues"
    return seen["q"]


def test_the_query_names_the_item_type_github_requires(monkeypatch) -> None:
    # Without this GitHub answers 422 and the whole reconciliation dies.
    query = _captured_query(monkeypatch)

    assert "is:issue" in query or "is:pull-request" in query


def test_the_query_still_scopes_to_the_repo_label_and_fingerprint(monkeypatch) -> None:
    # The 422 fix must not widen the search: a query that dropped the label or
    # the repository would start matching other people's issues.
    query = _captured_query(monkeypatch)

    assert "repo:owner/ops" in query
    assert "label:ops-incident" in query
    assert '"fingerprint: abc123"' in query
    assert "in:body" in query
