"""On-demand company refresh: incremental merge, HKEX overlay, vendor skip rules."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.research_control_tower.live_refresh import (
    load_local_hkex_overlay,
    merge_hkex_frames,
    merge_news_frames,
    refresh_company_news,
)
from src.research_control_tower.news_collector import FetchResult, NEWS_INPUT_COLUMNS
from tests.test_research_control_tower_official_filings import _FakeHkexSession, _hkex_row


REPO = Path(__file__).resolve().parents[1]
NOW = pd.Timestamp("2026-08-25T08:00:00Z")


def _news_row(*, title: str, link: str, first_seen: str, last_seen: str, content_hash: str) -> dict:
    return {
        "dataset_id": "ai_news_blog_posts",
        "source_url": "https://example.test/feed",
        "source_run_id": "run-1",
        "scraped_at": last_seen,
        "first_seen_at": first_seen,
        "last_seen_at": last_seen,
        "source_name": "Marketaux",
        "title": title,
        "link": link,
        "pub_date": "2026-08-24T12:00:00Z",
        "description": "",
        "body_text": "",
        "content_hash": content_hash,
    }


def test_merge_news_frames_keeps_first_seen_and_updates_last_seen() -> None:
    existing = pd.DataFrame(
        [
            _news_row(
                title="Tencent results",
                link="https://example.test/tencent",
                first_seen="2026-08-20T00:00:00Z",
                last_seen="2026-08-20T00:00:00Z",
                content_hash="abc",
            )
        ]
    )
    incoming = pd.DataFrame(
        [
            _news_row(
                title="Tencent results",
                link="https://example.test/tencent",
                first_seen="2026-08-25T08:00:00Z",
                last_seen="2026-08-25T08:00:00Z",
                content_hash="abc",
            ),
            _news_row(
                title="New Tencent headline",
                link="https://example.test/tencent-new",
                first_seen="2026-08-25T08:00:00Z",
                last_seen="2026-08-25T08:00:00Z",
                content_hash="def",
            ),
        ]
    )
    merged = merge_news_frames(existing, incoming, now_utc=NOW)
    by_hash = merged.set_index("content_hash")
    first_seen = pd.Timestamp(by_hash.loc["abc", "first_seen_at"])
    last_seen = pd.Timestamp(by_hash.loc["abc", "last_seen_at"])
    if first_seen.tzinfo is None:
        first_seen = first_seen.tz_localize("UTC")
    else:
        first_seen = first_seen.tz_convert("UTC")
    if last_seen.tzinfo is None:
        last_seen = last_seen.tz_localize("UTC")
    else:
        last_seen = last_seen.tz_convert("UTC")
    assert first_seen == pd.Timestamp("2026-08-20T00:00:00Z")
    assert last_seen == NOW
    assert "def" in set(merged["content_hash"])
    assert set(merged.columns) == set(NEWS_INPUT_COLUMNS)


def test_merge_hkex_frames_is_sticky_on_document_id() -> None:
    existing = pd.DataFrame(
        [{"document_id": "hkexnews:1", "headline": "old", "retrieved_at_utc": "2026-08-20T00:00:00Z"}]
    )
    incoming = pd.DataFrame(
        [
            {"document_id": "hkexnews:1", "headline": "new title same id", "retrieved_at_utc": "2026-08-25T08:00:00Z"},
            {"document_id": "hkexnews:2", "headline": "fresh", "retrieved_at_utc": "2026-08-25T08:00:00Z"},
        ]
    )
    merged = merge_hkex_frames(existing, incoming)
    assert list(merged["document_id"]) == ["hkexnews:1", "hkexnews:2"] or set(merged["document_id"]) == {"hkexnews:1", "hkexnews:2"}
    row = merged.loc[merged["document_id"].eq("hkexnews:1")].iloc[0]
    assert row["headline"] == "new title same id"


def test_tencent_refresh_writes_hkex_and_marketaux_skips_finnhub(tmp_path: Path) -> None:
    session = _FakeHkexSession(rows=[_hkex_row()])
    queried: list[tuple[str, dict]] = []

    def fake_fetch(url: str, *, params=None, **_kwargs) -> FetchResult:
        params = dict(params or {})
        queried.append((url, params))
        if "marketaux" in url:
            payload = {
                "data": [
                    {
                        "title": "Tencent: The Market Is Underestimating This AI Giant",
                        "url": "https://example.test/tencent-sa",
                        "published_at": "2026-08-25T01:00:00Z",
                    }
                ]
            }
            return FetchResult(url=url, status_code=200, content_type="application/json", text=json.dumps(payload), ok=True)
        if "finnhub" in url:
            return FetchResult(url=url, status_code=403, content_type="application/json", text="[]", ok=False)
        return FetchResult(url=url, status_code=404, content_type="text/plain", text="", ok=False)

    mart_dir = tmp_path / "marts"
    result = refresh_company_news(
        "TENCENT",
        repo_root=REPO,
        listing_id="0700_HK",
        api_keys={"marketaux": "test-marketaux", "finnhub": "test-finnhub"},
        now_utc=NOW,
        hkex_lookback_days=14,
        hkex_max_rows=10,
        hkex_session=session,
        download_fn=fake_fetch,
        mart_dir=mart_dir,
    )
    by_source = {item.source_id: item for item in result.sources}
    assert by_source["hkexnews"].status == "available"
    assert by_source["hkexnews"].new_rows >= 1
    assert by_source["news_marketaux"].status in {"available", "partial"}
    assert by_source["news_finnhub"].skipped is True
    assert "403s" in by_source["news_finnhub"].detail or "US ADR" in by_source["news_finnhub"].detail
    live = load_local_hkex_overlay(entity_id="TENCENT", listing_id="0700_HK", mart_dir=mart_dir)
    assert not live.empty
    assert live["document_id"].astype("string").str.startswith("hkexnews:").all()
    news = pd.read_parquet(mart_dir / "news_marketaux.parquet")
    assert news["title"].str.contains("Tencent", case=False).any()
    finnhub_calls = [item for item in queried if "finnhub" in item[0]]
    assert finnhub_calls == []
    marketaux_calls = [item for item in queried if "marketaux" in item[0]]
    assert len(marketaux_calls) == 1
    assert marketaux_calls[0][1].get("symbols") == "0700.HK"
    assert (mart_dir / "hkexnews_live.parquet").is_file()
    assert not (REPO / "data" / "normalized" / "marts" / "hkexnews_live.parquet").exists()


def test_alibaba_refresh_queries_finnhub_us_adr(tmp_path: Path) -> None:
    queried_symbols: list[str] = []

    def fake_fetch(url: str, *, params=None, **_kwargs) -> FetchResult:
        params = dict(params or {})
        if "finnhub" in url:
            queried_symbols.append(str(params.get("symbol", "")))
            payload = [
                {
                    "headline": "Alibaba: The Market Got This One Wrong",
                    "url": "https://example.test/baba",
                    "datetime": 1787097600,
                }
            ]
            return FetchResult(url=url, status_code=200, content_type="application/json", text=json.dumps(payload), ok=True)
        if "marketaux" in url:
            return FetchResult(
                url=url,
                status_code=200,
                content_type="application/json",
                text=json.dumps({"data": []}),
                ok=True,
            )
        return FetchResult(url=url, status_code=404, content_type="text/plain", text="", ok=False)

    session = _FakeHkexSession(
        rows=[
            {
                **_hkex_row(),
                "STOCK_CODE": "09988",
                "STOCK_NAME": "BABA-W",
                "NEWS_ID": "2026082000001",
            }
        ],
        stock_id="9988",
    )
    # prefix.do in the fake session always returns TENCENT 00700. For Alibaba we
    # only care that Finnhub is pointed at BABA, so skip a live HKEX match by
    # letting the adapter return no exact code and recording not_applicable/unavailable.
    result = refresh_company_news(
        "ALIBABA",
        repo_root=REPO,
        listing_id="9988_HK",
        api_keys={"marketaux": "test-marketaux", "finnhub": "test-finnhub"},
        now_utc=NOW,
        hkex_session=session,
        download_fn=fake_fetch,
        mart_dir=tmp_path / "marts",
    )
    by_source = {item.source_id: item for item in result.sources}
    assert by_source["news_finnhub"].skipped is False
    assert "BABA" in queried_symbols


def test_company_page_exposes_refresh_button() -> None:
    source = (REPO / "apps/research-control-tower/control_tower/pages/company.py").read_text()
    assert "Refresh news & filings" in source
    assert "On-demand HKEXnews overlay" in source
    assert "refresh_company_news" in source
