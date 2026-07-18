from __future__ import annotations

from pathlib import Path

from global_news_data.pipeline import NewsPipeline
from global_news_data.sources.gdelt import GdeltClient


class FakeGdeltResponse:
    def __init__(self, payload, content_type="application/json; charset=UTF-8", text=""):
        self.payload = payload
        self.headers = {"content-type": content_type}
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeGdeltSession:
    def __init__(self, response: FakeGdeltResponse) -> None:
        self.response = response
        self.last_params: dict | None = None

    def get(self, url: str, params=None, timeout=None):
        self.last_params = params
        return self.response


def test_gdelt_client_wraps_multi_word_query_in_quotes() -> None:
    client = GdeltClient()
    client.session = FakeGdeltSession(FakeGdeltResponse({"articles": []}))

    client.fetch_articles(query="chip shortage")

    assert client.session.last_params["query"] == '"chip shortage"'
    assert client.session.last_params["mode"] == "artlist"
    assert client.session.last_params["format"] == "json"


def test_gdelt_client_appends_country_and_language_filters() -> None:
    client = GdeltClient()
    client.session = FakeGdeltSession(FakeGdeltResponse({"articles": []}))

    client.fetch_articles(query="finance", source_country="HK", source_lang="chi")

    assert client.session.last_params["query"] == "finance sourcecountry:HK sourcelang:chi"


def test_gdelt_client_returns_empty_articles_on_non_json_response() -> None:
    client = GdeltClient()
    client.session = FakeGdeltSession(
        FakeGdeltResponse(payload={}, content_type="text/html; charset=UTF-8", text="invalid query")
    )

    result = client.fetch_articles(query="finance")

    assert result == {"articles": []}


class FakeGdeltClient:
    def __init__(self, articles) -> None:
        self.articles = articles

    def fetch_articles(self, query: str, max_records: int):
        return {"articles": self.articles}


def test_pipeline_maps_gdelt_articles_into_unified_schema(tmp_path: Path) -> None:
    articles = [
        {
            "url": "https://example.com/article-1",
            "title": "Chip shortage worsens in Asia",
            "seendate": "20260718T120000Z",
            "domain": "example.com",
            "language": "English",
            "sourcecountry": "Hong Kong",
        }
    ]
    pipeline = NewsPipeline(tmp_path, gdelt_client=FakeGdeltClient(articles))

    result = pipeline.run()

    assert result["fetched"]["gdelt"] == 1
    assert result["total_records_in_db"] == 1
    assert result["errors"] == {}


def test_pipeline_skips_gdelt_articles_missing_url(tmp_path: Path) -> None:
    articles = [{"title": "No url here"}]
    pipeline = NewsPipeline(tmp_path, gdelt_client=FakeGdeltClient(articles))

    result = pipeline.run()

    assert result["fetched"]["gdelt"] == 0
    assert result["total_records_in_db"] == 0


class FailingGdeltClient:
    def fetch_articles(self, query: str, max_records: int):
        raise RuntimeError("gdelt is down")


def test_pipeline_records_gdelt_error_without_crashing(tmp_path: Path) -> None:
    pipeline = NewsPipeline(tmp_path, gdelt_client=FailingGdeltClient())

    result = pipeline.run()

    assert result["errors"]["gdelt"] == "gdelt is down"
