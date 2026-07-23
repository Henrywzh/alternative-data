from __future__ import annotations

import json
import time
from urllib.parse import quote

from ai_news_data.models import GenericRecord, RunContext, Snapshot
from ai_news_data.sources.base import SourceExtractor
from ai_news_data.sources.http import fetch_json

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"

# Overlapping keyword queries are fine: storage dedupes on story_id, so a
# story matched by two queries collapses into a single row anyway.
QUERIES = [
    "OpenAI", "DeepSeek", "Anthropic", "Claude", "Gemini", "Mistral",
    "model release", "vLLM", "open source model", "LLM",
]

# 2-day overlap so a missed/failed run never leaves a gap; re-fetched stories
# are deduped by story_id in storage rather than re-appended.
LOOKBACK_SECONDS = 60 * 60 * 24 * 2


class HackerNewsSource(SourceExtractor):
    name = "hackernews"

    def fetch_snapshots(self) -> list[Snapshot]:
        since = int(time.time()) - LOOKBACK_SECONDS
        snapshots = []
        for query in QUERIES:
            url = f"{ALGOLIA_URL}?query={quote(query)}&tags=story&numericFilters=created_at_i%3E{since}&hitsPerPage=50"
            snapshots.append(Snapshot(name=f"query__{query}", source_url=url, body=json.dumps(fetch_json(url))))
        return snapshots

    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[GenericRecord]]:
        scraped_at = context.scraped_at_iso
        seen_ids: set[str] = set()
        records: list[GenericRecord] = []

        for snapshot in snapshots:
            query = snapshot.name.split("__", 1)[1]
            for hit in json.loads(snapshot.body).get("hits", []):
                story_id = hit.get("objectID")
                if not story_id or story_id in seen_ids:
                    continue
                seen_ids.add(story_id)
                records.append(
                    GenericRecord(
                        dataset_id="ai_news_hn_stories",
                        source_url=snapshot.source_url,
                        source_run_id=context.run_id,
                        scraped_at=scraped_at,
                        payload={
                            "story_id": story_id,
                            "title": hit.get("title"),
                            "url": hit.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
                            "score": hit.get("points"),
                            "by": hit.get("author"),
                            "time": hit.get("created_at_i"),
                            "comments_count": hit.get("num_comments"),
                            "matched_query": query,
                        },
                    )
                )

        return {"ai_news_hn_stories": records}
