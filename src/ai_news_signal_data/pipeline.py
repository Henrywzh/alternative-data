from __future__ import annotations

from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path

import pandas as pd

from ai_news_signal_data.config import groq_api_keys, load_config
from ai_news_signal_data.engine import CloudflareEngine
from ai_news_signal_data.guard import GroqGuard
from ai_news_signal_data.report import build_email_body, send_email
from ai_news_signal_data.rules import flag_trending_models
from ai_news_signal_data.storage import SignalStorage

AI_NEWS_ROOT = "ai_news"


def _s(value) -> str:
    """NA-safe string coercion — pd.NA/NaN/None fail truthiness checks (`or ""`),
    so this must use pd.isna rather than a plain `or` fallback."""
    return "" if pd.isna(value) else str(value)


def _n(value, default: int = 0):
    return default if pd.isna(value) else value


# dataset_id -> how to build the guard's lightweight candidate (title + one
# key stat) and, only for survivors, the engine's full-text payload.
NARRATIVE_DATASETS: dict[str, dict] = {
    "ai_news_hf_papers": {
        "id_col": "paper_id",
        "title": lambda r: _s(r.get("title")),
        "key_stat": lambda r: f"{_n(r.get('upvotes'))} upvotes",
        "text": lambda r: _s(r.get("summary")),
    },
    "ai_news_hf_org_watch": {
        "id_col": "model_id",
        "title": lambda r: _s(r.get("model_id")),
        "key_stat": lambda r: f"{_n(r.get('likes'))} likes / {_n(r.get('downloads'))} downloads",
        "text": lambda r: f"New model from {_s(r.get('org'))}: {_s(r.get('model_id'))} ({_s(r.get('pipeline_tag'))})",
    },
    "ai_news_hn_stories": {
        "id_col": "story_id",
        "title": lambda r: _s(r.get("title")),
        "key_stat": lambda r: f"{_n(r.get('score'))} points / {_n(r.get('comments_count'))} comments",
        "text": lambda r: f"{_s(r.get('title'))} — {_s(r.get('url'))}",
    },
    "ai_news_reddit_posts": {
        "id_col": "post_id",
        "title": lambda r: _s(r.get("title")),
        "key_stat": lambda r: f"r/{_s(r.get('subreddit'))}",
        "text": lambda r: _s(r.get("content_text")),
    },
    "ai_news_blog_posts": {
        "id_col": "link",
        "title": lambda r: _s(r.get("title")),
        "key_stat": lambda r: _s(r.get("source_name")),
        "text": lambda r: _s(r.get("description")),
    },
}


@dataclass
class SignalResult:
    candidates: int
    guard_tagged: int
    high_importance: int
    trending_flagged: int
    brief: dict


class AiNewsSignalPipeline:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.storage = SignalStorage(base_dir)
        self.config = load_config(base_dir)
        self.guard = GroqGuard(groq_api_keys(self.config))
        self.engine = CloudflareEngine(
            self.config.get("CLOUDFLARE_ACCOUNT_ID", ""), self.config.get("CLOUDFLARE_API_KEY", "")
        )

    def _load_today(self, dataset_id: str, run_date: str) -> pd.DataFrame:
        path = self.base_dir / "data" / "normalized" / AI_NEWS_ROOT / f"{dataset_id}.parquet"
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_parquet(path)
        if "first_seen_at" not in df.columns:
            return pd.DataFrame()
        return df[df["first_seen_at"].astype(str).str.startswith(run_date)]

    def run(self, *, run_date: str | None = None, send: bool = False, limit: int | None = None) -> SignalResult:
        run_date = run_date or pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")

        # 1. Rule-based flag for the numeric leaderboard — no LLM call.
        trending_path = self.base_dir / "data" / "normalized" / AI_NEWS_ROOT / "ai_news_hf_trending_models.parquet"
        trending_df = pd.read_parquet(trending_path) if trending_path.exists() else pd.DataFrame()
        trending_today = (
            trending_df[trending_df.get("snapshot_date") == run_date] if not trending_df.empty else trending_df
        )
        flagged_trending = flag_trending_models(trending_today) if not trending_today.empty else pd.DataFrame()
        trending_high = (
            flagged_trending[flagged_trending["importance"] == "high"] if not flagged_trending.empty else pd.DataFrame()
        )

        # 2. Build lightweight candidates (title + one key stat only) for the guard.
        # Collected per-dataset first and round-robin merged so an optional
        # `limit` (preview runs) samples across all sources instead of being
        # dominated by whichever dataset happens to have the most rows.
        per_dataset: list[list[dict]] = []
        candidate_meta: dict[str, dict] = {}
        for dataset_id, spec in NARRATIVE_DATASETS.items():
            today_df = self._load_today(dataset_id, run_date)
            bucket: list[dict] = []
            for _, row in today_df.iterrows():
                item_id = f"{dataset_id}:{row[spec['id_col']]}"
                title = spec["title"](row)
                bucket.append({"item_id": item_id, "title": title, "key_stat": spec["key_stat"](row)})
                candidate_meta[item_id] = {"dataset_id": dataset_id, "row": row, "spec": spec, "title": title}
            per_dataset.append(bucket)

        candidates: list[dict] = []
        for group in zip_longest(*per_dataset):
            candidates.extend(c for c in group if c is not None)
        if limit is not None:
            candidates = candidates[:limit]
        # Restrict meta to the actually-sampled candidates so a `limit`
        # preview run doesn't default every unsampled item to "medium" below.
        sampled_ids = {c["item_id"] for c in candidates}
        candidate_meta = {item_id: meta for item_id, meta in candidate_meta.items() if item_id in sampled_ids}

        # 3. Guard: cheap triage on titles/key-stats only. A chunk response
        # occasionally omits an item_id (truncated JSON on a large batch) —
        # default those to "medium" rather than silently dropping them, so a
        # real launch can never vanish just because the guard's reply got cut.
        tags = self.guard.tag(candidates)
        for item_id in candidate_meta:
            tags.setdefault(item_id, {"importance": "medium", "reason": "no guard response"})
        guard_log = [
            {
                "run_date": run_date,
                "item_id": item_id,
                "dataset_id": candidate_meta[item_id]["dataset_id"],
                "title": candidate_meta[item_id]["title"],
                "importance": tag["importance"],
                "reason": tag["reason"],
            }
            for item_id, tag in tags.items()
            if item_id in candidate_meta
        ]
        self.storage.append_guard_log(guard_log)

        # 4. Pull full text ONLY for guard survivors + rule-flagged trending models.
        high_items = [item_id for item_id, tag in tags.items() if tag["importance"] == "high"]
        engine_input: list[dict] = []
        for item_id in high_items:
            meta = candidate_meta.get(item_id)
            if meta is None:
                continue
            engine_input.append({"item_id": item_id, "title": meta["title"], "text": meta["spec"]["text"](meta["row"])})
        for _, row in trending_high.iterrows():
            item_id = f"ai_news_hf_trending_models:{row['model_id']}"
            engine_input.append(
                {
                    "item_id": item_id,
                    "title": row["model_id"],
                    "text": (
                        f"Trending on HuggingFace: {row['model_id']} ({row.get('pipeline_tag')}), "
                        f"trending_score={row.get('trending_score')}, likes={row.get('likes')}"
                    ),
                }
            )

        # 5. Engine: deep analysis on survivors only.
        brief = self.engine.analyze(engine_input)
        brief_rows = [
            {
                "run_date": run_date,
                "item_id": item.get("item_id", ""),
                "headline": item.get("headline", ""),
                "analysis": item.get("analysis", ""),
            }
            for item in brief.get("items", [])
        ]
        self.storage.append_brief(brief_rows)

        if send:
            body = build_email_body(run_date, brief)
            send_email(self.config, run_date=run_date, body=body)

        return SignalResult(
            candidates=len(candidates),
            guard_tagged=len(tags),
            high_importance=len(high_items),
            trending_flagged=len(trending_high),
            brief=brief,
        )
