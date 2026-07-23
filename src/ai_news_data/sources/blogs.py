from __future__ import annotations

import xml.etree.ElementTree as ET

from ai_news_data.models import GenericRecord, RunContext, Snapshot
from ai_news_data.sources.base import SourceExtractor
from ai_news_data.sources.http import fetch_text

FEEDS = {
    "OpenAI": "https://openai.com/news/rss.xml",
    "GoogleDeepMind": "https://deepmind.google/blog/rss.xml",
}


class BlogsSource(SourceExtractor):
    name = "blogs"

    def fetch_snapshots(self) -> list[Snapshot]:
        return [Snapshot(name=f"blog__{name}", source_url=url, body=fetch_text(url)) for name, url in FEEDS.items()]

    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[GenericRecord]]:
        scraped_at = context.scraped_at_iso
        records: list[GenericRecord] = []

        for snapshot in snapshots:
            source_name = snapshot.name.split("__", 1)[1]
            root = ET.fromstring(snapshot.body)
            for item in root.findall(".//item"):
                link_el = item.find("link")
                link = link_el.text if link_el is not None else ""
                if not link:
                    continue
                title_el = item.find("title")
                pub_el = item.find("pubDate")
                desc_el = item.find("description")
                records.append(
                    GenericRecord(
                        dataset_id="ai_news_blog_posts",
                        source_url=snapshot.source_url,
                        source_run_id=context.run_id,
                        scraped_at=scraped_at,
                        payload={
                            "source_name": source_name,
                            "title": title_el.text if title_el is not None else "",
                            "link": link,
                            "pub_date": pub_el.text if pub_el is not None else "",
                            "description": desc_el.text if desc_el is not None else "",
                        },
                    )
                )

        return {"ai_news_blog_posts": records}
