"""Local labelled news overlay for Control Tower company pages.

Reads collector outputs under data/normalized/marts/news_*.parquet and resolves
headlines through the registry alias table. This is not the published
news_filings.parquet generation artifact.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .registries import load_news_entity_aliases, load_registry_bundle, resolve_news_entities

NEWS_MART_FILES = ("news_marketaux.parquet", "news_finnhub.parquet")


def default_news_mart_dir(repo_root: Path | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    return root / "data" / "normalized" / "marts"


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "published_at",
            "headline",
            "publisher",
            "source_id",
            "source_url",
            "related_entity_ids",
            "related_listing_ids",
        ]
    )


def load_local_news_overlay(
    *,
    entity_id: str,
    listing_id: str | None = None,
    repo_root: Path | None = None,
) -> pd.DataFrame:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    mart_dir = default_news_mart_dir(root)
    frames: list[pd.DataFrame] = []
    for name in NEWS_MART_FILES:
        path = mart_dir / name
        if path.is_file():
            raw = pd.read_parquet(path)
            if not raw.empty:
                raw = raw.copy()
                raw["source_id"] = path.stem
                frames.append(raw)
    if not frames:
        return _empty()
    news = pd.concat(frames, ignore_index=True)
    registries = load_registry_bundle(root / "config" / "research_control_tower")
    aliases = load_news_entity_aliases(root / "config" / "research_control_tower" / "news_entity_aliases.csv")
    rows: list[dict] = []
    wanted_entity = str(entity_id or "").strip()
    wanted_listing = str(listing_id or "").strip()
    for _, item in news.iterrows():
        headline = str(item.get("title") or "").strip()
        entity_ids, listing_ids = resolve_news_entities(
            headline,
            entities=registries.entities,
            listings=registries.listings,
            aliases=aliases,
        )
        if wanted_entity and wanted_entity not in set(entity_ids):
            if wanted_listing and wanted_listing not in set(listing_ids):
                continue
            if not wanted_listing:
                continue
        rows.append(
            {
                "published_at": item.get("pub_date"),
                "headline": headline,
                "publisher": item.get("source_name") or item.get("source_id"),
                "source_id": item.get("source_id"),
                "source_url": item.get("link") or item.get("source_url"),
                "related_entity_ids": ",".join(entity_ids),
                "related_listing_ids": ",".join(listing_ids),
            }
        )
    if not rows:
        return _empty()
    out = pd.DataFrame(rows)
    out["published_at"] = pd.to_datetime(out["published_at"], errors="coerce", utc=True)
    return out.sort_values("published_at", ascending=False, na_position="last").reset_index(drop=True)
