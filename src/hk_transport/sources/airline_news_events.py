"""Current public airline news discovery layer with point-in-time metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import AIRLINE_TICKER_ALIASES, NORMALIZED_DIR


OUTPUT_PATH = NORMALIZED_DIR / "airline_news_events.csv"
SOURCE_URL = "https://so.eastmoney.com/news/s"

NEWS_UNIVERSE = (
    ("0293.HK", "Cathay Pacific", "HK", "00293"),
    ("0753.HK / 601111.SH", "Air China", "CN_A/HK", "601111"),
    ("01055.HK / 600029.SH", "China Southern Airlines", "CN_A/HK", "600029"),
    ("0670.HK / 600115.SH", "China Eastern Airlines", "CN_A/HK", "600115"),
    ("601021.SH", "Spring Airlines", "CN_A", "601021"),
    ("603885.SH", "Juneyao Airlines", "CN_A", "603885"),
    ("600221.SH", "Hainan Airlines Holdings", "CN_A", "600221"),
)

CHINESE_NAMES = {
    "Cathay Pacific": ("国泰航空", "国泰"),
    "Air China": ("中国国航", "国航"),
    "China Southern Airlines": ("南方航空", "南航"),
    "China Eastern Airlines": ("中国东航", "东航"),
    "Spring Airlines": ("春秋航空", "春秋"),
    "Juneyao Airlines": ("吉祥航空", "吉祥"),
    "Hainan Airlines Holdings": ("海南航空", "海航"),
}

OUTPUT_COLUMNS = [
    "dataset_id", "ticker", "company", "market", "query_symbol", "published_at",
    "news_title", "news_content", "news_source", "news_url", "event_category",
    "relevance_scope", "history_scope", "source_quality", "source_url", "source_note", "retrieved_at",
]


def _category(title: Any, content: Any) -> str:
    text = f"{title or ''} {content or ''}"
    if any(token in text for token in ("业绩", "净利", "溢利", "盈利", "亏损", "财报", "结果")):
        return "financial_results_or_guidance"
    if any(token in text for token in ("运力", "客座率", "客运", "货运", "旅客", "航班", "ASK", "RPK")):
        return "operating_update"
    if any(token in text for token in ("空客", "飞机", "购入", "购买", "机队", "航材")):
        return "fleet_or_capex"
    if any(token in text for token in ("回购", "辞职", "股息", "分红", "增持", "出售")):
        return "capital_or_management"
    if any(token in text for token in ("航油", "油价", "燃油", "机场", "航空股")):
        return "sector_or_cost_context"
    return "other_news"


def _relevance_scope(company: str, title: Any, content: Any) -> str:
    headline = str(title or "")
    body = str(content or "")
    names = CHINESE_NAMES.get(company, ())
    if any(name in headline for name in names):
        return "direct_headline"
    if any(name in body for name in names):
        return "mentioned_in_body"
    return "broad_market_or_noise"


def normalize_news_frames(
    frames: list[tuple[str, str, str, str, pd.DataFrame]],
    *,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Normalize ``(ticker, company, market, query_symbol, frame)`` records."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for ticker, company, market, query_symbol, frame in frames:
        if frame is None or frame.empty:
            continue
        for _, source in frame.iterrows():
            published = pd.to_datetime(source.get("发布时间"), errors="coerce")
            if pd.isna(published):
                continue
            title = source.get("新闻标题")
            content = source.get("新闻内容")
            url = source.get("新闻链接")
            rows.append({
                "dataset_id": "airline_news_events",
                "ticker": ticker,
                "company": company,
                "market": market,
                "query_symbol": query_symbol,
                "published_at": published.strftime("%Y-%m-%d %H:%M:%S"),
                "news_title": title,
                "news_content": content,
                "news_source": source.get("文章来源"),
                "news_url": url,
                "event_category": _category(title, content),
                "relevance_scope": _relevance_scope(company, title, content),
                "history_scope": "latest_public_news_window",
                "source_quality": "eastmoney_news_discovery",
                "source_url": SOURCE_URL,
                "source_note": (
                    "Latest public Eastmoney news window retrieved through AkShare. "
                    "Category is keyword-based discovery metadata, not sentiment or a trade signal."
                ),
                "retrieved_at": retrieved,
            })
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if result.empty:
        return result
    return result.drop_duplicates(subset=["company", "published_at", "news_title", "news_url"]).sort_values(
        ["published_at", "company"], ascending=[False, True]
    ).reset_index(drop=True)


def merge_news_history(prior: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    """Append news snapshots while replacing only the same article key."""
    result = pd.concat([prior, current], ignore_index=True)
    if result.empty:
        return result
    result["ticker"] = result["ticker"].replace(AIRLINE_TICKER_ALIASES)
    key = ["company", "published_at", "news_title", "news_url"]
    return result.drop_duplicates(key, keep="last").sort_values(
        ["published_at", "company"], ascending=[False, True]
    ).reset_index(drop=True)


def fetch_airline_news_events() -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("akshare is required for the airline news layer") from exc
    retrieved = datetime.now(timezone.utc).isoformat()
    frames: list[tuple[str, str, str, str, pd.DataFrame]] = []
    for ticker, company, market, query_symbol in NEWS_UNIVERSE:
        try:
            frame = ak.stock_news_em(symbol=query_symbol)
        except Exception:
            frame = pd.DataFrame()
        frames.append((ticker, company, market, query_symbol, frame))
    result = normalize_news_frames(frames, retrieved_at=retrieved)
    if OUTPUT_PATH.exists():
        result = merge_news_history(pd.read_csv(OUTPUT_PATH), result)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
