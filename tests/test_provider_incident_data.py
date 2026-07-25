from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd

from provider_incident_data.extract import extract_snapshot
from provider_incident_data.models import Snapshot, SourceSpec
from provider_incident_data.pipeline import ProviderIncidentPipeline
from provider_incident_data.quality import validate_incidents
from provider_incident_data.source import SOURCE_SPECS
from provider_incident_data.storage import IncidentStorage
from dashboard.sections.provider_incidents import _prepare_incidents


def _snapshot(provider_id: str, parser: str, body: str) -> Snapshot:
    return Snapshot(
        provider_id=provider_id,
        provider_name=provider_id.title(),
        source_kind="json" if parser != "feed" else "atom",
        source_url=f"https://status.{provider_id}.example/feed",
        parser=parser,
        body=body,
        content_type="application/json" if parser != "feed" else "application/atom+xml",
        status_code=200,
        response_ms=20,
    )


def test_verified_moonshot_and_minimax_sources_use_statuspage_api() -> None:
    specs = {spec.provider_id: spec for spec in SOURCE_SPECS}

    assert specs["moonshot"].provider_name == "Moonshot AI (Kimi)"
    assert specs["moonshot"].source_url == "https://status.moonshot.cn/api/v2/incidents.json"
    assert specs["moonshot"].parser == "statuspage"
    assert specs["minimax"].provider_name == "MiniMax"
    assert specs["minimax"].source_url == "https://status.minimax.io/api/v2/incidents.json"
    assert specs["minimax"].parser == "statuspage"


def test_verified_statuspage_sources_extract_incidents_and_updates() -> None:
    for provider_id in ("moonshot", "minimax"):
        body = json.dumps(
            {
                "incidents": [
                    {
                        "id": f"{provider_id}-incident-1",
                        "name": "Elevated API errors",
                        "status": "resolved",
                        "impact": "minor",
                        "created_at": "2026-07-25T10:00:00Z",
                        "resolved_at": "2026-07-25T10:30:00Z",
                        "components": [{"id": "api", "name": "API"}],
                        "incident_updates": [
                            {
                                "id": f"{provider_id}-update-1",
                                "status": "resolved",
                                "body": "Recovered",
                                "created_at": "2026-07-25T10:30:00Z",
                            }
                        ],
                    }
                ]
            }
        )
        extracted = extract_snapshot(
            _snapshot(provider_id, "statuspage", body),
            run_id="run",
            scraped_at="2026-07-25T11:00:00Z",
        )

        assert len(extracted["provider_incidents"]) == 1
        assert len(extracted["provider_incident_updates"]) == 1
        assert extracted["provider_incidents"][0]["normalized_status"] == "resolved"


def test_statuspage_extracts_incident_updates_and_components() -> None:
    body = json.dumps(
        {
            "incidents": [
                {
                    "id": "inc-1",
                    "name": "Elevated API errors",
                    "status": "resolved",
                    "impact": "major",
                    "created_at": "2026-07-17T10:00:00Z",
                    "resolved_at": "2026-07-17T11:30:00Z",
                    "components": [{"id": "api", "name": "API"}],
                    "incident_updates": [
                        {"id": "up-1", "status": "investigating", "body": "Investigating", "created_at": "2026-07-17T10:00:00Z"},
                        {"id": "up-2", "status": "resolved", "body": "Recovered", "created_at": "2026-07-17T11:30:00Z"},
                    ],
                }
            ]
        }
    )
    extracted = extract_snapshot(_snapshot("openai", "statuspage", body), run_id="run", scraped_at="2026-07-18T00:00:00Z")

    incident = extracted["provider_incidents"][0]
    assert incident["normalized_status"] == "resolved"
    assert incident["severity_level"] == 2
    assert incident["duration_minutes"] == 90.0
    assert incident["latest_message"] == "Recovered"
    assert len(extracted["provider_incident_updates"]) == 2
    assert extracted["provider_incident_components"][0]["component_name"] == "API"


def test_google_extracts_only_vertex_and_gemini_incidents() -> None:
    body = json.dumps(
        [
            {
                "id": "storage",
                "begin": "2026-07-01T10:00:00Z",
                "end": "2026-07-01T11:00:00Z",
                "external_desc": "Cloud Storage errors",
                "affected_products": [{"id": "storage", "title": "Cloud Storage"}],
                "updates": [],
            },
            {
                "id": "gemini",
                "begin": "2026-07-02T10:00:00Z",
                "end": "2026-07-02T11:00:00Z",
                "created": "2026-07-02T10:05:00Z",
                "severity": "low",
                "status_impact": "SERVICE_DISRUPTION",
                "external_desc": "Vertex AI Gemini API customers experienced elevated errors.",
                "affected_products": [{"id": "vertex", "title": "Vertex Gemini API"}],
                "updates": [{"when": "2026-07-02T11:00:00Z", "status": "AVAILABLE", "text": "Resolved"}],
            },
        ]
    )
    extracted = extract_snapshot(_snapshot("google", "google", body), run_id="run", scraped_at="2026-07-18T00:00:00Z")

    assert [row["source_incident_id"] for row in extracted["provider_incidents"]] == ["gemini"]
    assert extracted["provider_incidents"][0]["affected_components_json"] == '["Vertex Gemini API"]'


def test_atom_entries_consolidate_into_one_incident() -> None:
    body = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>API Degraded</title><id>incident-1</id><link href="https://status.example/incidents/1"/><updated>2026-07-17T10:00:00Z</updated><summary><![CDATA[Status: Investigating<br/><ul><li>Chat API</li></ul>]]></summary></entry>
      <entry><title>API Degraded</title><id>incident-1</id><link href="https://status.example/incidents/1"/><updated>2026-07-17T11:00:00Z</updated><summary><![CDATA[Status: Resolved<br/><ul><li>Chat API</li></ul>]]></summary></entry>
    </feed>"""
    extracted = extract_snapshot(_snapshot("mistral", "feed", body), run_id="run", scraped_at="2026-07-18T00:00:00Z")

    assert len(extracted["provider_incidents"]) == 1
    incident = extracted["provider_incidents"][0]
    assert incident["normalized_status"] == "resolved"
    assert incident["duration_minutes"] == 60.0
    assert len(extracted["provider_incident_updates"]) == 2
    assert extracted["provider_incident_components"][0]["component_name"] == "Chat API"


def test_resolved_feed_item_uses_explicit_timeline_without_inventing_start() -> None:
    body = """<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel><item>
      <title>[API] Model unavailable</title>
      <guid>incident-2</guid>
      <link>status.example/incidents/2</link>
      <pubDate>Tue, 07 Jul 2026 15:40:26 GMT</pubDate>
      <description><![CDATA[
        <h3>Status: RESOLVED</h3>
        <div><p><strong>Tue, 07 Jul 2026 16:37:02 GMT</strong></p><h3>Resolved</h3><p>Recovered.</p></div>
        <div><p><strong>Tue, 07 Jul 2026 15:40:26 GMT</strong></p><h3>Investigating</h3><p>Investigating.</p></div>
      ]]></description>
    </item></channel></rss>"""
    extracted = extract_snapshot(_snapshot("xai", "feed", body), run_id="run", scraped_at="2026-07-18T00:00:00Z")

    incident = extracted["provider_incidents"][0]
    assert incident["incident_url"] == "https://status.example/incidents/2"
    assert incident["started_at"] == "2026-07-07T15:40:26Z"
    assert incident["resolved_at"] == "2026-07-07T16:37:02Z"
    assert incident["duration_minutes"] == 56.6


def test_single_resolved_atom_update_leaves_start_unknown_and_extracts_components() -> None:
    body = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>API Degraded</title><id>incident-3</id><updated>2026-07-02T17:56:22+08:00</updated>
      <link href="https://status.example/incidents/3"/>
      <summary><![CDATA[<p><strong>Status:</strong> resolved</p><p><strong>Affected components:</strong> API Service, Web Chat Service</p>]]></summary>
    </entry></feed>"""
    extracted = extract_snapshot(_snapshot("deepseek", "feed", body), run_id="run", scraped_at="2026-07-18T00:00:00Z")

    incident = extracted["provider_incidents"][0]
    assert incident["started_at"] is None
    assert incident["published_at"] == "2026-07-02T09:56:22Z"
    assert incident["resolved_at"] == "2026-07-02T09:56:22Z"
    assert incident["duration_minutes"] is None
    assert json.loads(incident["affected_components_json"]) == ["API Service", "Web Chat Service"]


def test_dashboard_keeps_mixed_fractional_timestamps() -> None:
    frame = pd.DataFrame(
        {
            "provider_id": ["openai", "anthropic"],
            "provider_name": ["OpenAI", "Anthropic"],
            "started_at": ["2026-07-17T10:00:00Z", "2026-07-17T10:00:00.123000Z"],
            "published_at": ["2026-07-17T10:00:00Z", "2026-07-17T10:00:00.123000Z"],
            "resolved_at": ["2026-07-17T11:00:00Z", "2026-07-17T11:00:00.123000Z"],
            "duration_minutes": [60.0, 60.0],
            "severity_level": [1, 1],
            "normalized_status": ["resolved", "resolved"],
        }
    )

    prepared = _prepare_incidents(SimpleNamespace(frame=frame))

    assert len(prepared) == 2
    assert prepared["activity_at"].notna().all()


def test_quality_rejects_reversed_mixed_fractional_timestamps() -> None:
    frame = pd.DataFrame(
        {
            "provider_id": ["openai", "anthropic"],
            "source_incident_id": ["normal", "reversed"],
            "normalized_status": ["resolved", "resolved"],
            "severity_level": [1, 1],
            "started_at": ["2026-07-17T10:00:00Z", "2026-07-17T12:00:00.123000Z"],
            "resolved_at": ["2026-07-17T11:00:00Z", "2026-07-17T11:00:00.123000Z"],
        }
    )

    try:
        validate_incidents(frame)
    except ValueError as exc:
        assert "resolution before the start" in str(exc)
    else:
        raise AssertionError("Expected mixed-format reversed timestamps to fail validation")


def test_storage_preserves_provenance_for_unchanged_incident(tmp_path) -> None:
    storage = IncidentStorage(tmp_path)
    columns = storage.load("provider_incidents").columns
    row = {column: None for column in columns}
    row.update(
        {
            "dataset_id": "provider_incidents",
            "source_url": "https://status.example",
            "source_run_id": "first",
            "scraped_at": "2026-07-17T00:00:00Z",
            "provider_id": "openai",
            "provider_name": "OpenAI",
            "source_incident_id": "inc-1",
            "title": "API errors",
            "normalized_status": "resolved",
        }
    )
    storage.upsert("provider_incidents", [row])
    second = {**row, "source_run_id": "second", "scraped_at": "2026-07-18T00:00:00Z"}
    stored = storage.upsert("provider_incidents", [second])

    assert len(stored) == 1
    assert stored.iloc[0]["source_run_id"] == "first"


class _FakeSource:
    def __init__(self, snapshots: list[Snapshot]) -> None:
        self._snapshots = snapshots
        self.specs = tuple(
            SourceSpec(row.provider_id, row.provider_name, row.source_kind, row.source_url, row.parser)
            for row in snapshots
        )

    def fetch_all(self):
        return self._snapshots, []


def test_pipeline_isolates_malformed_optional_provider_feed(tmp_path) -> None:
    good = _snapshot("openai", "statuspage", '{"incidents": []}')
    malformed = _snapshot("mistral", "feed", "<not-closed>")
    pipeline = ProviderIncidentPipeline(tmp_path, source=_FakeSource([good, malformed]))

    written = pipeline.run_update()
    health = pd.read_parquet(tmp_path / "data/normalized/provider_incidents/provider_incident_source_health.parquet")

    assert written["provider_incident_source_health"] == 2
    assert health.set_index("provider_id").loc["openai", "status"] == "ok"
    assert health.set_index("provider_id").loc["mistral", "status"] == "warning"


def test_pipeline_rejects_a_run_when_most_sources_fail(tmp_path) -> None:
    malformed = _snapshot("mistral", "feed", "<not-closed>")
    source = _FakeSource([malformed])
    source.specs = (
        *source.specs,
        SourceSpec("openai", "OpenAI", "json", "https://status.openai.example", "statuspage"),
        SourceSpec("google", "Google", "json", "https://status.google.example", "google"),
    )
    pipeline = ProviderIncidentPipeline(tmp_path, source=source)

    try:
        pipeline.run_update()
    except RuntimeError as exc:
        assert "Only 0/3 provider sources succeeded" in str(exc)
    else:
        raise AssertionError("Expected a majority-source failure to reject the run")

    assert not (tmp_path / "data/normalized/provider_incidents/provider_incidents.parquet").exists()


def test_pipeline_warns_on_unexplained_source_count_collapse(tmp_path) -> None:
    pipeline = ProviderIncidentPipeline(
        tmp_path,
        source=_FakeSource(
            [
                _snapshot("openai", "statuspage", '{"incidents": []}'),
                _snapshot(
                    "cohere",
                    "statuspage",
                    json.dumps(
                        {
                            "incidents": [
                                {
                                    "id": "inc-1",
                                    "name": "API errors",
                                    "status": "resolved",
                                    "impact": "minor",
                                    "created_at": "2026-07-17T10:00:00Z",
                                    "resolved_at": "2026-07-17T11:00:00Z",
                                    "incident_updates": [],
                                }
                            ]
                        }
                    ),
                ),
            ]
        ),
    )
    health_columns = pipeline.storage.load("provider_incident_source_health").columns
    previous = {column: None for column in health_columns}
    previous.update(
        {
            "dataset_id": "provider_incident_source_health",
            "source_url": "https://status.openai.example",
            "source_run_id": "prior",
            "scraped_at": "2026-07-17T00:00:00Z",
            "provider_id": "openai",
            "provider_name": "OpenAI",
            "source_system": "json",
            "status": "ok",
            "status_code": 200,
            "incident_rows": 25,
            "last_good_incident_rows": 25,
        }
    )
    pipeline.storage.upsert("provider_incident_source_health", [previous])

    pipeline.run_update()
    health = pipeline.storage.load("provider_incident_source_health").set_index("provider_id")

    assert health.loc["openai", "status"] == "warning"
    assert "CountCollapse" in health.loc["openai", "detail"]
    assert health.loc["openai", "last_good_incident_rows"] == 25
    assert health.loc["cohere", "status"] == "ok"

    pipeline.run_update()
    repeated = pipeline.storage.load("provider_incident_source_health").set_index("provider_id")
    assert repeated.loc["openai", "status"] == "warning"
    assert repeated.loc["openai", "last_good_incident_rows"] == 25
