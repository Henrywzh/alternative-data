from __future__ import annotations

from pathlib import Path

from ops_control.store import IncidentStore


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "ops" / "incident.schema.json"


def test_fingerprint_search_query_includes_is_issue(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_paginate(url: str, *, token: str, params=None):
        captured["url"] = url
        captured["params"] = params
        return []

    monkeypatch.setattr("ops_control.store.paginate", fake_paginate)
    store = IncidentStore(
        repository="Henrywzh/alternative-data-ops",
        token="ghs_test",
        schema_path=SCHEMA,
    )

    assert store.find_by_fingerprint("asia-markets-dashboard-refresh:x:y:abc") is None
    assert captured["url"] == "https://api.github.com/search/issues"
    query = str((captured["params"] or {}).get("q"))
    assert "is:issue" in query
    assert "repo:Henrywzh/alternative-data-ops" in query
    assert "label:ops-incident" in query
    assert '"fingerprint: asia-markets-dashboard-refresh:x:y:abc"' in query
