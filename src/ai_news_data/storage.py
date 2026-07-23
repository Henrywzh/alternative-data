from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from ai_news_data.models import GenericRecord

# Trending-models is a genuine daily time series (score legitimately changes
# day to day), so each (model_id, snapshot_date) is its own row. Everything
# else is a "sighting" feed: the same story/paper/post reappearing on a later
# run must collapse into the original row, not duplicate it.
SNAPSHOT_DATASETS = {"ai_news_hf_trending_models"}

NATURAL_KEYS: dict[str, list[str]] = {
    "ai_news_hf_papers": ["paper_id"],
    "ai_news_hf_trending_models": ["model_id", "snapshot_date"],
    "ai_news_hf_org_watch": ["model_id"],
    "ai_news_hn_stories": ["story_id"],
    "ai_news_reddit_posts": ["post_id"],
    "ai_news_blog_posts": ["link"],
}

# Fields that legitimately change on a re-sighting (score climbing, likes
# accruing) and should be refreshed in place rather than frozen at first-seen.
VOLATILE_COLUMNS: dict[str, list[str]] = {
    "ai_news_hf_papers": ["upvotes"],
    "ai_news_hf_org_watch": ["likes", "downloads"],
    "ai_news_hn_stories": ["score", "comments_count"],
    "ai_news_reddit_posts": [],
    "ai_news_blog_posts": [],
}

_SIGHTING_META = ["first_seen_at", "last_seen_at"]

DATASET_COLUMNS: dict[str, list[str]] = {
    "ai_news_hf_papers": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", *_SIGHTING_META,
        "paper_id", "title", "authors", "published_at", "upvotes", "summary", "url",
    ],
    "ai_news_hf_trending_models": [
        "dataset_id", "source_url", "source_run_id", "scraped_at",
        "snapshot_date", "model_id", "author", "pipeline_tag",
        "likes", "downloads", "trending_score", "tags", "created_at",
    ],
    "ai_news_hf_org_watch": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", *_SIGHTING_META,
        "org", "model_id", "pipeline_tag", "likes", "downloads", "created_at",
    ],
    "ai_news_hn_stories": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", *_SIGHTING_META,
        "story_id", "title", "url", "score", "by", "time", "comments_count", "matched_query",
    ],
    "ai_news_reddit_posts": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", *_SIGHTING_META,
        "post_id", "subreddit", "title", "author", "updated", "link", "content", "content_text",
    ],
    "ai_news_blog_posts": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", *_SIGHTING_META,
        "source_name", "title", "link", "pub_date", "description",
    ],
}

NUMERIC_COLUMNS = ["upvotes", "likes", "downloads", "trending_score", "score", "comments_count", "time"]


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "ai_news"
        self.normalized_root = base_dir / "data" / "normalized" / "ai_news"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_run(self, run_id: str, snapshots, manifest: dict[str, Any]) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            safe_name = "".join(c for c in snapshot.name if c.isalnum() or c in "._-")
            (run_dir / f"{safe_name}.json").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir

    def load_dataset(self, dataset_id: str) -> pd.DataFrame:
        cols = DATASET_COLUMNS[dataset_id]
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        if not parquet_path.exists():
            return pd.DataFrame(columns=cols)
        df = pd.read_parquet(parquet_path)
        for col in cols:
            if col not in df.columns:
                df[col] = pd.NA
        return df[cols]

    def upsert_dataset(self, dataset_id: str, records: Iterable[GenericRecord]) -> pd.DataFrame:
        cols = DATASET_COLUMNS[dataset_id]
        keys = NATURAL_KEYS[dataset_id]
        incoming = pd.DataFrame([r.to_dict() for r in records])
        if incoming.empty:
            return self.load_dataset(dataset_id)

        incoming = incoming.reindex(columns=cols)
        if dataset_id not in SNAPSHOT_DATASETS:
            incoming["first_seen_at"] = incoming["scraped_at"]
            incoming["last_seen_at"] = incoming["scraped_at"]
        incoming = self._coerce_types(incoming).drop_duplicates(subset=keys, keep="last")

        existing = self._coerce_types(self.load_dataset(dataset_id))

        if dataset_id in SNAPSHOT_DATASETS:
            merged = pd.concat([existing, incoming]).drop_duplicates(subset=keys, keep="last")
        else:
            merged = self._merge_sightings(dataset_id, existing, incoming, keys)

        merged = merged.reset_index(drop=True)[cols]
        merged.to_parquet(self.normalized_root / f"{dataset_id}.parquet", index=False)
        return merged

    def _merge_sightings(
        self, dataset_id: str, existing: pd.DataFrame, incoming: pd.DataFrame, keys: list[str]
    ) -> pd.DataFrame:
        if existing.empty:
            return incoming

        volatile = VOLATILE_COLUMNS.get(dataset_id, [])
        ex = existing.set_index(keys)
        inc = incoming.set_index(keys)

        seen_before = ex.index.intersection(inc.index)
        new_rows = inc.index.difference(ex.index)
        untouched = ex.index.difference(inc.index)  # not re-fetched this run; keep as-is

        parts = [ex.loc[untouched]]
        if len(seen_before):
            # Re-sighted rows: keep the ORIGINAL first_seen_at, refresh
            # last_seen_at plus any volatile metrics; everything else stays as
            # first captured. This is what stops a story/post/paper that
            # already appeared yesterday from turning into a duplicate row.
            refreshed = ex.loc[seen_before].copy()
            refreshed["last_seen_at"] = inc.loc[seen_before, "last_seen_at"]
            for col in volatile:
                refreshed[col] = inc.loc[seen_before, col]
            parts.append(refreshed)
        parts.append(inc.loc[new_rows])

        merged = pd.concat([p for p in parts if len(p)]).reset_index()
        return merged[DATASET_COLUMNS[dataset_id]]

    @staticmethod
    def _coerce_types(df: pd.DataFrame) -> pd.DataFrame:
        for col in df.columns:
            if col in NUMERIC_COLUMNS:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                df[col] = df[col].astype("string")
        return df
