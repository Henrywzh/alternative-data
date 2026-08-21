"""Batch 5 news collector + label regression tests.

Covers the design-review acceptance matrix for the news metadata layer:
source-quality/event-class mapping (discovery never official), registry-backed
entity resolution with negative exclusions, no-body storage policy, sidecar
state semantics, and the 45-day freshness window.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.research_control_tower.build import (
    NEWS_EVENT_CLASS_DISCOVERY,
    NEWS_EVENT_CLASS_OFFICIAL,
    NEWS_EVENT_CLASS_SECONDARY_PROBE,
    _classify_source_quality,
    _news_event_class,
)
from src.research_control_tower.news_collector import (
    FetchResult,
    NEWS_INPUT_COLUMNS,
    NEWS_STATUS_SCHEMA,
    FINNHUB_SPEC,
    NewsCollectionResult,
    NewsProbeEvidence,
    collect_news,
    collect_official_ir_allowlist,
    _row,
    _utc,
    news_status_path,
    write_news_input,
)
from src.research_control_tower.registries import resolve_news_entities


def _entities() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entity_id": "TENCENT",
                "legal_name": "Tencent Holdings Limited",
                "display_name": "Tencent",
            },
            {
                "entity_id": "ALIBABA",
                "legal_name": "Alibaba Group Holding Limited",
                "display_name": "Alibaba",
            },
            {
                "entity_id": "BYTEDANCE",
                "legal_name": "ByteDance Ltd",
                "display_name": "ByteDance",
            },
        ]
    )


def _listings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "listing_id": "0700_HK",
                "entity_id": "TENCENT",
                "canonical_ticker": "0700.HK",
                "financial_data_security_id": "sec-0700",
                "mapping_status": "verified",
                "collection_eligible": True,
                "listing_status": "active",
                "active_from": "2026-01-01",
                "active_to": "",
            },
            {
                "listing_id": "9988_HK",
                "entity_id": "ALIBABA",
                "canonical_ticker": "9988.HK",
                "financial_data_security_id": "sec-9988",
                "mapping_status": "verified",
                "collection_eligible": True,
                "listing_status": "active",
                "active_from": "2026-01-01",
                "active_to": "",
            },
            {
                "listing_id": "BABA_US",
                "entity_id": "ALIBABA",
                "canonical_ticker": "BABA.US",
                "financial_data_security_id": "sec-baba",
                "mapping_status": "verified",
                "collection_eligible": True,
                "listing_status": "active",
                "active_from": "2026-01-01",
                "active_to": "",
            },
            {
                "listing_id": "TCEHY_US",
                "entity_id": "TENCENT",
                "canonical_ticker": "TCEHY.US",
                "financial_data_security_id": "sec-tcehy",
                "mapping_status": "unresolved",
                "collection_eligible": False,
                "listing_status": "active",
                "active_from": "2026-01-01",
                "active_to": "",
            },
        ]
    )


def _aliases() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entity_id": "TENCENT",
                "alias_kind": "negative",
                "match_token": "Tencent Music",
                "match_mode": "substring",
                "registry_version": "v1",
                "source_or_research_note": "TME is a separate issuer",
            },
            {
                "entity_id": "TENCENT",
                "alias_kind": "negative",
                "match_token": "腾讯音乐",
                "match_mode": "substring",
                "registry_version": "v1",
                "source_or_research_note": "TME is a separate issuer (Chinese)",
            },
            {
                "entity_id": "ALIBABA",
                "alias_kind": "negative",
                "match_token": "Alibaba Pictures",
                "match_mode": "substring",
                "registry_version": "v1",
                "source_or_research_note": "film arm is a separate issuer",
            },
            {
                "entity_id": "TENCENT",
                "alias_kind": "positive",
                "match_token": "腾讯",
                "match_mode": "substring",
                "registry_version": "v1",
                "source_or_research_note": "Chinese name variant",
            },
        ]
    )


def _probe(provider: str, status: str = "entitled") -> NewsProbeEvidence:
    return NewsProbeEvidence(
        provider=provider,
        endpoint=f"https://example.test/{provider}",
        fields=("headline", "url", "published_at"),
        free_limits="60 calls/min",
        geography="US",
        license_class="free_tier_metadata_only",
        probe_date=pd.Timestamp("2026-08-19T00:00:00Z"),
        status=status,  # type: ignore[arg-type]
        detail="probe passed",
    )


def test_bare_rss_source_is_discovery_never_official() -> None:
    assert _classify_source_quality("google_news_rss", "public", "news") == "discovery"
    assert _classify_source_quality("gdetl_discovery", "public", "news") == "discovery"
    assert _news_event_class("google_news_rss", "public") == NEWS_EVENT_CLASS_DISCOVERY


def test_explicit_official_marker_keeps_official_class() -> None:
    assert (
        _classify_source_quality("news_official_ir_allowlist", "official_public_metadata", "news")
        == "official"
    )
    assert (
        _classify_source_quality("official_ai_rss", "public_metadata", "news")
        == "official"
    )
    assert _news_event_class("news_official_ir_allowlist", "official_public_metadata") == NEWS_EVENT_CLASS_OFFICIAL


def test_probed_provider_is_secondary_probe() -> None:
    assert _news_event_class("news_finnhub", "free_tier_metadata_only") == NEWS_EVENT_CLASS_SECONDARY_PROBE
    assert _news_event_class("news_marketaux", "free_tier_metadata_only") == NEWS_EVENT_CLASS_SECONDARY_PROBE
    assert _news_event_class("news_fmp", "free_tier_metadata_only") == NEWS_EVENT_CLASS_SECONDARY_PROBE


def test_probed_provider_entitled_even_with_cli_default_license() -> None:
    """CLI 4-field descriptors default license to public_metadata; the three
    structured provider source_ids must still classify as entitled, not
    official (the Blocker-2 regression)."""
    assert _classify_source_quality("news_finnhub", "public_metadata", "news") == "entitled"
    assert _classify_source_quality("news_marketaux", "public_metadata", "news") == "entitled"
    assert _classify_source_quality("news_fmp", "public_metadata", "news") == "entitled"
    assert _news_event_class("news_finnhub", "public_metadata") == NEWS_EVENT_CLASS_SECONDARY_PROBE


def test_finnhub_epoch_seconds_parsed_correctly() -> None:
    """Finnhub datetime is Unix epoch SECONDS; must not be misread as
    nanoseconds yielding 1970 dates (the Blocker-1 regression)."""
    epoch_seconds = 1755648000  # 2025-08-20 00:00:00 UTC
    row = _row(
        provider="Finnhub",
        endpoint="https://finnhub.io/api/v1/company-news",
        run_id="run-test",
        now_utc=pd.Timestamp("2026-08-19T00:00:00Z"),
        title="Test headline",
        link="https://example.test/a",
        published=epoch_seconds,
        license_class="free_tier_metadata_only",
    )
    assert row["pub_date"] == pd.Timestamp("2025-08-20T00:00:00Z")


def test_entity_resolution_positive_and_negative_exclusions() -> None:
    entities = _entities()
    listings = _listings()
    aliases = _aliases()

    entity_ids, listing_ids = resolve_news_entities(
        "Tencent Holdings posts record quarterly revenue",
        entities=entities,
        listings=listings,
        aliases=aliases,
    )
    assert entity_ids == ["TENCENT"]
    assert listing_ids == ["0700_HK"]

    entity_ids, listing_ids = resolve_news_entities(
        "腾讯发布新游戏",
        entities=entities,
        listings=listings,
        aliases=aliases,
    )
    assert entity_ids == ["TENCENT"]

    # Negative exclusion: Tencent Music is NOT Tencent Holdings.
    entity_ids, _ = resolve_news_entities(
        "Tencent Music reports quarterly results",
        entities=entities,
        listings=listings,
        aliases=aliases,
    )
    assert entity_ids == []

    # Chinese negative exclusion: 腾讯音乐 is NOT 腾讯控股.
    entity_ids, _ = resolve_news_entities(
        "腾讯音乐发布第二季度财报",
        entities=entities,
        listings=listings,
        aliases=aliases,
    )
    assert entity_ids == []

    # Negative exclusion: Alibaba Pictures is NOT Alibaba Group.
    entity_ids, _ = resolve_news_entities(
        "Alibaba Pictures announces film slate",
        entities=entities,
        listings=listings,
        aliases=aliases,
    )
    assert entity_ids == []


def test_unmatchable_headline_resolves_to_empty_ids() -> None:
    entity_ids, listing_ids = resolve_news_entities(
        "Unrelated industry note on an unlisted vendor",
        entities=_entities(),
        listings=_listings(),
        aliases=_aliases(),
    )
    assert entity_ids == []
    assert listing_ids == []


def test_write_news_input_metadata_only_and_sidecar(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        [
            {
                "dataset_id": "ai_news_blog_posts",
                "source_url": "https://example.test/feed",
                "source_run_id": "run-1",
                "scraped_at": "2026-08-19T00:00:00Z",
                "first_seen_at": "2026-08-19T00:00:00Z",
                "last_seen_at": "2026-08-19T00:00:00Z",
                "source_name": "example",
                "title": "Example headline",
                "link": "https://example.test/a",
                "pub_date": "2026-08-18T12:00:00Z",
                "description": "",
                "body_text": "",
                "content_hash": "abc123",
            }
        ]
    )
    result = NewsCollectionResult(
        source_id="news_finnhub",
        provider="finnhub",
        frame=frame,
        aggregate_status="available",
        probe=_probe("finnhub"),
        diagnostics=(),
    )
    output = write_news_input(frame, tmp_path / "news_finnhub.parquet", result=result)

    written = pd.read_parquet(output)
    assert set(written.columns) == set(NEWS_INPUT_COLUMNS)
    # No-body policy: description/body_text stay empty.
    assert written["body_text"].isna().all() or (written["body_text"] == "").all()
    assert written["content_hash"].iloc[0] == "abc123"

    sidecar = json.loads(news_status_path(output).read_text(encoding="utf-8"))
    assert sidecar["schema"] == NEWS_STATUS_SCHEMA
    assert sidecar["aggregate_status"] == "available"
    assert sidecar["probe"]["status"] == "entitled"


def test_collect_news_unavailable_without_key(tmp_path: Path) -> None:
    written, results = collect_news(
        tmp_path,
        providers=("finnhub",),
        api_keys=None,
        listings=_listings(),
        entities=_entities(),
        as_of_utc=pd.Timestamp("2026-08-19T00:00:00Z"),
    )
    assert "news_finnhub.parquet" in {path.name for path in written.values()}
    result = results[0]
    assert result.aggregate_status == "unavailable"
    assert result.probe.status == "failed"
    assert "no API key" in result.probe.detail
    assert result.frame.empty
    sidecar = json.loads(news_status_path(written["news_finnhub"]).read_text(encoding="utf-8"))
    assert sidecar["aggregate_status"] == "unavailable"


@pytest.mark.parametrize("provider", ["finnhub", "marketaux", "fmp"])
def test_provider_news_gate_rejects_tcehy_but_queries_0700(
    tmp_path: Path,
    provider: str,
) -> None:
    queried_symbols: list[str] = []
    calls = 0

    def fake_fetch(url: str, *, params=None, **_kwargs) -> FetchResult:
        nonlocal calls
        calls += 1
        params = dict(params or {})
        if provider == "finnhub":
            symbol = str(params.get("symbol", ""))
            payload = [{
                "headline": "Tencent update",
                "url": "https://example.test/tencent",
                "datetime": 1787097600,
            }]
        elif provider == "marketaux":
            symbol = str(params.get("symbols", ""))
            payload = {"data": [{
                "title": "Tencent update",
                "url": "https://example.test/tencent",
                "published_at": "2026-08-18T00:00:00Z",
            }]}
        else:
            symbol = str(params.get("tickers", ""))
            payload = [{
                "title": "Tencent update",
                "url": "https://example.test/tencent",
                "date": "2026-08-18T00:00:00Z",
            }]
        if symbol:
            queried_symbols.append(symbol)
        is_probe = calls == 1
        body = "{}" if is_probe and provider == "marketaux" else "[]" if is_probe else json.dumps(payload)
        return FetchResult(
            url=url,
            status_code=200,
            content_type="application/json",
            text=body,
            ok=True,
        )

    written, results = collect_news(
        tmp_path,
        providers=(provider,),
        api_keys={provider: "test-key"},
        download_fn=fake_fetch,
        listings=_listings(),
        entities=_entities(),
        aliases=_aliases(),
        as_of_utc=pd.Timestamp("2026-08-19T00:00:00Z"),
        now_utc=pd.Timestamp("2026-08-19T00:00:00Z"),
    )

    assert written
    result = results[0]
    assert result.frame.shape[0] == 1
    assert "0700.HK" in queried_symbols
    assert all("TCEHY" not in symbol for symbol in queried_symbols)
    tcehy_diagnostics = [item for item in result.diagnostics if item.listing_id == "TCEHY_US"]
    assert tcehy_diagnostics
    assert tcehy_diagnostics[0].status == "not_verified"
    assert "mapping_status=unresolved" in tcehy_diagnostics[0].reason
    sidecar = json.loads(news_status_path(next(iter(written.values()))).read_text(encoding="utf-8"))
    assert any(item["listing_id"] == "TCEHY_US" for item in sidecar["diagnostics"])


def test_official_ir_gate_rejects_tcehy_but_retains_0700() -> None:
    allowlist = pd.DataFrame(
        [
            {
                "entity_id": "TENCENT",
                "listing_id": "0700_HK",
                "canonical_ticker": "0700.HK",
                "feed_url": "https://example.test/0700.xml",
            },
            {
                "entity_id": "TENCENT",
                "listing_id": "TCEHY_US",
                "canonical_ticker": "TCEHY.US",
                "feed_url": "https://example.test/tcehy.xml",
            },
        ]
    )
    fetched: list[str] = []

    def fake_fetch(url: str, **_kwargs) -> FetchResult:
        fetched.append(url)
        return FetchResult(
            url=url,
            status_code=200,
            content_type="application/rss+xml",
            text=(
                "<?xml version='1.0'?><rss><channel><item>"
                "<title>Tencent update</title><link>https://example.test/tencent</link>"
                "<pubDate>Tue, 18 Aug 2026 00:00:00 GMT</pubDate>"
                "</item></channel></rss>"
            ),
            ok=True,
        )

    result = collect_official_ir_allowlist(
        allowlist,
        fetch=fake_fetch,
        listings=_listings(),
        as_of_utc=pd.Timestamp("2026-08-19T00:00:00Z"),
        lookback_days=45,
        timeout=1.0,
    )

    assert result.frame.shape[0] == 1
    assert fetched == ["https://example.test/0700.xml"]
    tcehy_diagnostics = [item for item in result.diagnostics if item.listing_id == "TCEHY_US"]
    assert tcehy_diagnostics
    assert tcehy_diagnostics[0].status == "not_verified"
    assert "mapping_status=unresolved" in tcehy_diagnostics[0].reason
