from __future__ import annotations

import json

from ai_news_data.models import GenericRecord, RunContext, Snapshot
from ai_news_data.sources.base import SourceExtractor
from ai_news_data.sources.http import fetch_json

DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"
TRENDING_MODELS_URL = "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=50"
ORG_MODELS_URL = "https://huggingface.co/api/models?author={org}&sort=createdAt&direction=-1&limit=10"

# Labs whose new model uploads are worth tracking as a leading indicator.
WATCHED_ORGS = ["deepseek-ai", "Qwen", "meta-llama", "mistralai", "google", "openai", "anthropic"]


class HuggingFaceSource(SourceExtractor):
    name = "huggingface"

    def fetch_snapshots(self) -> list[Snapshot]:
        snapshots = [
            Snapshot(name="daily_papers", source_url=DAILY_PAPERS_URL, body=json.dumps(fetch_json(DAILY_PAPERS_URL))),
            Snapshot(
                name="trending_models",
                source_url=TRENDING_MODELS_URL,
                body=json.dumps(fetch_json(TRENDING_MODELS_URL)),
            ),
        ]
        for org in WATCHED_ORGS:
            url = ORG_MODELS_URL.format(org=org)
            snapshots.append(Snapshot(name=f"org_watch__{org}", source_url=url, body=json.dumps(fetch_json(url))))
        return snapshots

    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[GenericRecord]]:
        by_name = {s.name: s for s in snapshots}
        scraped_at = context.scraped_at_iso
        records: dict[str, list[GenericRecord]] = {
            "ai_news_hf_papers": [],
            "ai_news_hf_trending_models": [],
            "ai_news_hf_org_watch": [],
        }

        for item in json.loads(by_name["daily_papers"].body):
            p = item.get("paper", {})
            paper_id = p.get("id")
            if not paper_id:
                continue
            records["ai_news_hf_papers"].append(
                GenericRecord(
                    dataset_id="ai_news_hf_papers",
                    source_url=DAILY_PAPERS_URL,
                    source_run_id=context.run_id,
                    scraped_at=scraped_at,
                    payload={
                        "paper_id": paper_id,
                        "title": p.get("title"),
                        "authors": "; ".join(a.get("name", "") for a in p.get("authors", []) if a.get("name")),
                        "published_at": p.get("publishedAt"),
                        "upvotes": p.get("upvotes", 0),
                        "summary": p.get("summary"),
                        "url": f"https://huggingface.co/papers/{paper_id}",
                    },
                )
            )

        snapshot_date = context.scraped_at.strftime("%Y-%m-%d")
        for m in json.loads(by_name["trending_models"].body):
            model_id = m.get("id")
            if not model_id:
                continue
            records["ai_news_hf_trending_models"].append(
                GenericRecord(
                    dataset_id="ai_news_hf_trending_models",
                    source_url=TRENDING_MODELS_URL,
                    source_run_id=context.run_id,
                    scraped_at=scraped_at,
                    payload={
                        "snapshot_date": snapshot_date,
                        "model_id": model_id,
                        "author": m.get("author"),
                        "pipeline_tag": m.get("pipeline_tag"),
                        "likes": m.get("likes"),
                        "downloads": m.get("downloads"),
                        "trending_score": m.get("trendingScore"),
                        "tags": "; ".join(m.get("tags", [])),
                        "created_at": m.get("createdAt"),
                    },
                )
            )

        for org in WATCHED_ORGS:
            for m in json.loads(by_name[f"org_watch__{org}"].body):
                model_id = m.get("id")
                if not model_id:
                    continue
                records["ai_news_hf_org_watch"].append(
                    GenericRecord(
                        dataset_id="ai_news_hf_org_watch",
                        source_url=ORG_MODELS_URL.format(org=org),
                        source_run_id=context.run_id,
                        scraped_at=scraped_at,
                        payload={
                            "org": org,
                            "model_id": model_id,
                            "pipeline_tag": m.get("pipeline_tag"),
                            "likes": m.get("likes"),
                            "downloads": m.get("downloads"),
                            "created_at": m.get("createdAt"),
                        },
                    )
                )

        return records
