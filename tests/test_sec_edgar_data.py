from __future__ import annotations

from pathlib import Path

import pytest

from sec_edgar_data.client import EdgarFullTextSearchClient
from sec_edgar_data.config import DEFAULT_USER_AGENT, resolve_user_agent
from sec_edgar_data.models import EdgarFilingHit
from sec_edgar_data.pipeline import EdgarPipeline
from sec_edgar_data.storage import EdgarStorage


def _hit(query: str, accession_no: str, file_date: str, fetched_at: str = "t1") -> EdgarFilingHit:
    return EdgarFilingHit(
        query=query,
        accession_no=accession_no,
        cik="1832483",
        company_name="Example Corp",
        form="10-K",
        file_date=file_date,
        filing_url=f"https://www.sec.gov/Archives/edgar/data/1832483/{accession_no}/doc.htm",
        fetched_at=fetched_at,
    )


def test_upsert_filings_dedupes_by_query_and_accession(tmp_path: Path) -> None:
    storage = EdgarStorage(tmp_path)

    storage.upsert_filings([_hit("chip shortage", "0001", "2026-07-01", fetched_at="t1")])
    merged = storage.upsert_filings([_hit("chip shortage", "0001", "2026-07-01", fetched_at="t2")])

    assert len(merged) == 1
    assert merged.iloc[0]["fetched_at"] == "t2"


def test_upsert_filings_treats_same_filing_matched_by_different_query_as_distinct(tmp_path: Path) -> None:
    storage = EdgarStorage(tmp_path)

    merged = storage.upsert_filings([
        _hit("chip shortage", "0001", "2026-07-01"),
        _hit("export controls", "0001", "2026-07-01"),
    ])

    assert len(merged) == 2


def test_upsert_filings_sorts_newest_first(tmp_path: Path) -> None:
    storage = EdgarStorage(tmp_path)

    merged = storage.upsert_filings([
        _hit("chip shortage", "0001", "2026-07-01"),
        _hit("chip shortage", "0002", "2026-07-18"),
    ])

    assert list(merged["accession_no"]) == ["0002", "0001"]


def test_resolve_user_agent_falls_back_to_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)

    assert resolve_user_agent(tmp_path) == DEFAULT_USER_AGENT


def test_resolve_user_agent_prefers_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "my-app real@company.com")

    assert resolve_user_agent(tmp_path) == "my-app real@company.com"


def test_extract_builds_archive_url_and_strips_cik_leading_zeros() -> None:
    client = EdgarFullTextSearchClient(user_agent="test test@example.com")
    payload = {
        "hits": {
            "hits": [
                {
                    "_id": "0001832483-26-000010:patr-20251231.htm",
                    "_source": {
                        "adsh": "0001832483-26-000010",
                        "ciks": ["0001832483"],
                        "display_names": ["Example Corp (EXCO)"],
                        "form": "10-K",
                        "file_date": "2026-03-12",
                    },
                }
            ]
        }
    }

    records = client.extract(payload, query="chip shortage")

    assert len(records) == 1
    record = records[0]
    assert record.cik == "0001832483"
    assert record.filing_url == (
        "https://www.sec.gov/Archives/edgar/data/1832483/000183248326000010/patr-20251231.htm"
    )


def test_extract_skips_hits_missing_accession_number() -> None:
    client = EdgarFullTextSearchClient(user_agent="test test@example.com")
    payload = {"hits": {"hits": [{"_id": "bad", "_source": {}}]}}

    records = client.extract(payload, query="chip shortage")

    assert records == []


class FakeEdgarClient:
    def __init__(self, failing_queries: set[str]) -> None:
        self.failing_queries = failing_queries

    def search(self, query: str, forms=None, start_date=None, end_date=None, size=100):
        if query in self.failing_queries:
            raise RuntimeError(f"boom: {query}")
        return {"hits": {"hits": []}}

    def extract(self, payload, query: str) -> list[EdgarFilingHit]:
        if query in self.failing_queries:
            return []
        return [_hit(query, f"acc-{query}", "2026-07-01")]


def test_pipeline_run_records_per_query_errors_and_continues(tmp_path: Path) -> None:
    pipeline = EdgarPipeline(tmp_path, client=FakeEdgarClient(failing_queries={"export controls"}))

    result = pipeline.run(queries=["chip shortage", "export controls"])

    assert result["fetched"] == {"chip shortage": 1}
    assert result["filings_written"] == 1
    assert result["errors"] == {"export controls": "boom: export controls"}
