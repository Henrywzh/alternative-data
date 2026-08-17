"""Bounded Crawl4AI fallback used for SHKP unknown-phase quick checks.

The project runtime intentionally does not depend on Crawl4AI.  Run this
script with the isolated ``.venv-crawl4ai`` interpreter and pipe one JSON
object per line on stdin.  It emits one JSON object per input URL and keeps
the browser lane separate from the requests/static evidence dataset.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig


TERMS = (
    "sun hung kai properties",
    "sun hung kai",
    "shkp",
    "新鴻基地產",
    "新鸿基地产",
    "新鴻基",
    "新鸿基",
)


def field(text: str, labels: tuple[str, ...]) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    stop_pattern = (
        r"Vendor|Sales\s+Agents?|Holding\s+Companies?(?:\s+of\s+the\s+Vendor)?|"
        r"Holding\s+Company(?:\s+of\s+the\s+Vendor)?|銷售代理(?:人)?|销售代理(?:人)?|控股公司|賣方|卖方|"
        r"Authorized\s+Person|Building\s+contractor|The\s+firm\s+of\s+solicitors|"
        r"Authorized\s+institution|Any\s+other\s+person|Last\s+updated|District|Name\s+of"
    )
    match = re.search(
        rf"(?:^|[|;\n]|\s)(?:{label_pattern})\s*[:：]\s*(?P<value>.*?)"
        rf"(?=\s*(?:{stop_pattern})\s*[:：]|\s*[|;\n]|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group("value")).strip(" |;\t\r\n")
    return value or None


def parse(markdown: str) -> dict[str, object]:
    visible = BeautifulSoup(markdown or "", "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", visible).strip()
    vendor = field(text, ("Vendor", "賣方", "卖方"))
    agent = field(text, ("Sales Agent", "Sales Agents", "銷售代理", "銷售代理人", "销售代理", "销售代理人"))
    holding = field(
        text,
        (
            "Holding Companies of the Vendor",
            "Holding Company of the Vendor",
            "Holding Companies",
            "Holding Company",
            "控股公司",
        ),
    )
    hits = [term for term in TERMS if term.casefold() in text.casefold()]
    role_text = " | ".join(value for value in (vendor, agent, holding) if value)
    role_hits = [term for term in TERMS if term.casefold() in role_text.casefold()]
    return {
        "vendor_name": vendor,
        "sales_agent": agent,
        "holding_companies": holding,
        "shkp_keyword_hits": list(dict.fromkeys(hits)),
        "shkp_match_status": "site_named_shkp" if role_hits else "page_named_shkp" if hits else "site_no_shkp_keyword",
        "evidence_context": role_text[:3000] or text[-1000:],
        "text_length": len(text),
    }


async def main() -> None:
    rows = [json.loads(line) for line in sys.stdin if line.strip()]
    browser = BrowserConfig(headless=True, verbose=False)
    page_timeout = int(os.getenv("C4A_PAGE_TIMEOUT_MS", "15000"))
    wait_timeout = int(os.getenv("C4A_WAIT_TIMEOUT_MS", "3500"))
    concurrency = max(1, min(int(os.getenv("C4A_CONCURRENCY", "8")), 12))
    run = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        wait_until="domcontentloaded",
        page_timeout=page_timeout,
        wait_for_timeout=wait_timeout,
        delay_before_return_html=0.4,
        verbose=False,
    )
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch(row: dict[str, object], crawler: AsyncWebCrawler) -> dict[str, object]:
        async with semaphore:
            url = str(row.get("url") or "")
            base = dict(row)
            base["crawl4ai_status"] = "error"
            if not url or url.rstrip("/").lower() in {"http:", "https:"}:
                base["crawl4ai_status"] = "no_url"
                return base
            try:
                result = await crawler.arun(url=url, config=run)
                base["crawl4ai_status"] = "ok" if result.success else "error"
                base["resolved_url"] = getattr(result, "url", None) or url
                if not result.success:
                    base["error"] = str(getattr(result, "error_message", None) or "crawl returned success=false")[:2000]
                parsed = parse(result.markdown or result.cleaned_html or "")
                base.update(parsed)
                base["http_status"] = getattr(result, "status_code", None)
            except Exception as exc:  # bounded fallback; preserve failure row
                base["error"] = str(exc)[:1000]
            return base

    async with AsyncWebCrawler(config=browser) as crawler:
        results = await asyncio.gather(*(fetch(row, crawler) for row in rows))
    for row in results:
        print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
