from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from ai_news_data.models import GenericRecord, RunContext, Snapshot
from ai_news_data.sources.base import SourceExtractor
from ai_news_data.sources.http import fetch_text

SUBREDDITS = ["LocalLLaMA", "MachineLearning"]
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
POST_ID_RE = re.compile(r"/comments/([a-z0-9]+)/")


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)


class RedditSource(SourceExtractor):
    name = "reddit"

    def fetch_snapshots(self) -> list[Snapshot]:
        snapshots = []
        for sub in SUBREDDITS:
            url = f"https://www.reddit.com/r/{sub}/new.rss"
            snapshots.append(Snapshot(name=f"sub__{sub}", source_url=url, body=fetch_text(url)))
        return snapshots

    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[GenericRecord]]:
        scraped_at = context.scraped_at_iso
        records: list[GenericRecord] = []

        for snapshot in snapshots:
            sub = snapshot.name.split("__", 1)[1]
            root = ET.fromstring(snapshot.body)
            for entry in root.findall("atom:entry", ATOM_NS):
                link_el = entry.find("atom:link", ATOM_NS)
                link = link_el.attrib.get("href", "") if link_el is not None else ""
                match = POST_ID_RE.search(link)
                if not match:
                    continue
                title_el = entry.find("atom:title", ATOM_NS)
                author_el = entry.find("atom:author/atom:name", ATOM_NS)
                updated_el = entry.find("atom:updated", ATOM_NS)
                content_el = entry.find("atom:content", ATOM_NS)
                content = content_el.text if content_el is not None else ""
                records.append(
                    GenericRecord(
                        dataset_id="ai_news_reddit_posts",
                        source_url=snapshot.source_url,
                        source_run_id=context.run_id,
                        scraped_at=scraped_at,
                        payload={
                            "post_id": match.group(1),
                            "subreddit": sub,
                            "title": title_el.text if title_el is not None else "",
                            "author": author_el.text if author_el is not None else "",
                            "updated": updated_el.text if updated_el is not None else "",
                            "link": link,
                            "content": content,
                            "content_text": _strip_html(content),
                        },
                    )
                )

        return {"ai_news_reddit_posts": records}
