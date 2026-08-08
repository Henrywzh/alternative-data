from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_news_events import normalize_news_frames


def test_news_normalization_keeps_point_in_time_lineage_and_relevance_scope() -> None:
    source = pd.DataFrame(
        {
            "新闻标题": ["中国国航：6月客运运力投入同比增长", "市场午间新闻"],
            "新闻内容": ["中国国航发布月度经营数据", "宏观市场动态"],
            "发布时间": ["2026-08-07 09:00:00", "2026-08-07 10:00:00"],
            "文章来源": ["source-a", "source-b"],
            "新闻链接": ["https://example.com/a", "https://example.com/b"],
        }
    )
    result = normalize_news_frames(
        [("0753.HK / 601111.SH", "Air China", "CN_A/HK", "601111", source)],
        retrieved_at="2026-08-07T00:00:00+00:00",
    )
    assert len(result) == 2
    assert result["published_at"].notna().all()
    assert result["source_quality"].eq("eastmoney_news_discovery").all()
    assert result.loc[result["news_title"].str.contains("中国国航"), "relevance_scope"].item() == "direct_headline"
    assert result.loc[result["news_title"].eq("市场午间新闻"), "relevance_scope"].item() == "broad_market_or_noise"


def test_current_news_layer_covers_universe_and_deduplicates_articles() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_news_events.csv")

    assert len(frame) >= 70
    assert frame["company"].nunique() == 7
    assert frame.duplicated(["company", "published_at", "news_title", "news_url"]).sum() == 0
    assert frame[["published_at", "news_title", "news_url", "event_category", "relevance_scope"]].notna().all().all()
    assert frame["history_scope"].eq("latest_public_news_window").all()
