from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from global_news_data.models import UnifiedNewsRecord
from global_news_data.pipeline import NewsPipeline, load_config
from global_news_data.sources.marketaux import MarketauxClient
from global_news_data.storage import NewsStorage


def _record(article_id: str, source: str, published_at: str, fetched_at: str = "t1") -> UnifiedNewsRecord:
    return UnifiedNewsRecord(
        article_id=article_id,
        source=source,
        published_at=published_at,
        title=f"title-{article_id}",
        summary="",
        body_text=None,
        url=f"https://example.com/{article_id}",
        entities=json.dumps([]),
        sentiment_score=None,
        language="en",
        fetched_at=fetched_at,
    )


def test_upsert_records_dedupes_by_source_and_article_id_keeping_latest(tmp_path: Path) -> None:
    storage = NewsStorage(tmp_path)

    storage.upsert_records([_record("1", "guardian", "2026-07-17T00:00:00+00:00", fetched_at="t1")])
    merged = storage.upsert_records([_record("1", "guardian", "2026-07-17T00:00:00+00:00", fetched_at="t2")])

    assert len(merged) == 1
    assert merged.iloc[0]["fetched_at"] == "t2"


def test_upsert_records_treats_same_id_from_different_sources_as_distinct(tmp_path: Path) -> None:
    storage = NewsStorage(tmp_path)

    merged = storage.upsert_records(
        [
            _record("1", "guardian", "2026-07-17T00:00:00+00:00"),
            _record("1", "marketaux", "2026-07-17T00:00:00+00:00"),
        ]
    )

    assert len(merged) == 2


def test_upsert_records_sorts_newest_first(tmp_path: Path) -> None:
    storage = NewsStorage(tmp_path)

    merged = storage.upsert_records(
        [
            _record("1", "guardian", "2026-07-01T00:00:00+00:00"),
            _record("2", "guardian", "2026-07-18T00:00:00+00:00"),
        ]
    )

    assert list(merged["article_id"]) == ["2", "1"]


def test_load_config_strips_quotes_and_comments(tmp_path: Path) -> None:
    config_path = tmp_path / ".config"
    config_path.write_text(
        '\n'.join(
            [
                "# a comment",
                'GUARDIAN_API_KEY="abc123"',
                "MARKETAUX_API_KEY='def456'",
                "CURRENTS_API_KEY=ghi789",
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config == {
        "GUARDIAN_API_KEY": "abc123",
        "MARKETAUX_API_KEY": "def456",
        "CURRENTS_API_KEY": "ghi789",
    }


class FakeSession:
    def __init__(self) -> None:
        self.last_params: dict | None = None

    def get(self, url: str, params=None, timeout=None):
        self.last_params = params

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": []}

        return FakeResponse()


def test_marketaux_client_caps_limit_to_free_tier_default() -> None:
    client = MarketauxClient(api_key="key")
    client.session = FakeSession()

    client.fetch_news(limit=10)

    assert client.session.last_params["limit"] == 3


def test_marketaux_client_honors_configurable_max_limit() -> None:
    client = MarketauxClient(api_key="key", max_limit=25)
    client.session = FakeSession()

    client.fetch_news(limit=10)

    assert client.session.last_params["limit"] == 10


class FakeGuardianClient:
    def __init__(self, payload) -> None:
        self.payload = payload

    def fetch_articles(self, query: str, page_size: int):
        return self.payload


class FailingClient:
    def fetch_articles(self, *args, **kwargs):
        raise RuntimeError("guardian is down")

    def fetch_news(self, *args, **kwargs):
        raise RuntimeError("marketaux is down")

    def fetch_latest(self, *args, **kwargs):
        raise RuntimeError("currents is down")


class NullGdeltClient:
    """Stub used to keep unrelated tests hermetic; GDELT has no API key gate
    so NewsPipeline always constructs a real client unless one is injected."""

    def fetch_articles(self, *args, **kwargs):
        return {"articles": []}


def test_pipeline_skips_articles_missing_id_without_crashing(tmp_path: Path) -> None:
    payload = {
        "response": {
            "results": [
                {"id": "", "webTitle": "no id"},
                {"id": "good-1", "webTitle": "has id", "webPublicationDate": "2026-07-18T00:00:00Z"},
            ]
        }
    }
    pipeline = NewsPipeline(tmp_path, guardian_client=FakeGuardianClient(payload), gdelt_client=NullGdeltClient())

    result = pipeline.run()

    assert result["fetched"]["guardian"] == 1
    assert result["total_records_in_db"] == 1


def test_pipeline_records_errors_per_source_when_all_configured_sources_fail(tmp_path: Path) -> None:
    failing = FailingClient()
    pipeline = NewsPipeline(
        tmp_path,
        guardian_client=failing,
        marketaux_client=failing,
        currents_client=failing,
        gdelt_client=NullGdeltClient(),
    )

    result = pipeline.run()

    assert set(result["errors"]) == {"guardian", "marketaux", "currents"}
    assert result["total_records_in_db"] == 0
