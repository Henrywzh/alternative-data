from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

from .config import FACTSET_INSIGHT_URL
from .models import FactsetEarningsObservation


class FactsetEarningsClient:
    def __init__(self, timeout_seconds: float = 30.0, session: requests.Session | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"})

    def fetch(self, url: str) -> requests.Response:
        response = self.session.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response

    @staticmethod
    def extract_article_links(html: str, base_url: str = FACTSET_INSIGHT_URL) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            if href.startswith("/"):
                href = f"https://insight.factset.com{href}"
            if not href.startswith("https://insight.factset.com/"):
                continue
            if "/topic/" in href or "/search" in href or href.endswith("/sitemap.xml"):
                continue
            if href.rstrip("/") == base_url.rstrip("/"):
                continue
            if href not in links:
                links.append(href)
        return links

    @staticmethod
    def extract_article_metadata(html: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        heading = soup.find("h1")
        title = heading.get_text(" ", strip=True) if heading else ""
        for element in soup(["script", "style", "noscript", "svg"]):
            element.decompose()

        # FactSet's public article pages contain a long "related content"
        # footer.  Parsing the whole document makes old articles inherit
        # quarters from current footer links (for example, 2026Q2).  Prefer
        # the article-body wrapper and use the full page only as a fallback
        # for page variants that do not expose that wrapper.
        content_root = None
        for selector in (
            "#hs_cos_wrapper_post_body",
            "[id*='post_body']",
            "[class*='post_body']",
            "[itemprop='articleBody']",
            "article",
        ):
            candidate = soup.select_one(selector)
            if candidate and len(candidate.get_text(" ", strip=True)) >= 200:
                content_root = candidate
                break
        if content_root is None:
            content_root = soup
        text = content_root.get_text("\n", strip=True)
        page_text = soup.get_text("\n", strip=True)
        date_match = re.search(
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b",
            page_text,
            re.IGNORECASE,
        )
        report_date = ""
        if date_match:
            try:
                report_date = datetime.strptime(date_match.group(0), "%B %d, %Y").date().isoformat()
            except ValueError:
                pass
        images: list[str] = []
        for image in content_root.find_all("img", src=True):
            src = str(image["src"])
            if src.startswith("//"):
                src = f"https:{src}"
            elif src.startswith("/"):
                src = f"https://insight.factset.com{src}"
            if src.startswith("https://insight.factset.com/") and src not in images:
                images.append(src)
        return {"title": title, "text": text, "report_date": report_date, "image_urls": images}

    @staticmethod
    def parse_summary_metrics(
        text: str,
        report_date: str,
        ref_quarter: str,
        *,
        source_url: str = FACTSET_INSIGHT_URL,
    ) -> FactsetEarningsObservation:
        fetched_at = datetime.now(timezone.utc).isoformat()

        def find_float(pattern: str, value_text: str | None = None) -> float | None:
            match = re.search(pattern, text if value_text is None else value_text, re.IGNORECASE | re.DOTALL)
            if not match:
                return None
            try:
                return float(match.group(1).replace("%", "").replace(",", ""))
            except ValueError:
                return None

        def find_first(patterns: list[str]) -> float | None:
            for pattern in patterns:
                value = find_float(pattern)
                if value is not None:
                    return value
            return None

        def find_forward_pe_average() -> float | None:
            marker = re.compile(r"forward\s+(?:12-month\s+)?P/E\s+ratio", re.IGNORECASE)
            average_patterns = [
                r"(?:10-year|ten-year)\s+average(?:\s+of)?\s*\(?\s*([\d]+(?:\.[\d]+)?)",
                r"(?:10-year|ten-year)\s*\(\s*([\d]+(?:\.[\d]+)?)",
            ]
            for marker_match in marker.finditer(text):
                window = text[marker_match.start():marker_match.start() + 900]
                for pattern in average_patterns:
                    value = find_float(pattern, window)
                    if value is not None and 0 < value < 60:
                        return value
            return None

        return FactsetEarningsObservation(
            report_date=report_date,
            reference_quarter=ref_quarter,
            blended_earnings_growth_yoy=find_first([
                r"(?:blended\s+)?earnings growth rate of\s*([+-]?[\d.]+)%",
                r"blended earnings growth of\s*([+-]?[\d.]+)%",
            ]),
            blended_revenue_growth_yoy=find_first([
                r"(?:blended\s+)?revenue growth rate of\s*([+-]?[\d.]+)%",
                r"blended revenue growth of\s*([+-]?[\d.]+)%",
            ]),
            eps_beat_rate=find_first([
                r"([+-]?[\d.]+)% of S&P 500 companies have reported.*?above EPS estimates",
                r"([+-]?[\d.]+)% of S&P 500 companies.*?beating EPS estimates",
                r"([+-]?[\d.]+)% of S&P 500 companies reported actual EPS above\s+estimated EPS",
            ]),
            eps_surprise_pct=find_first([
                r"earnings (?:are )?reporting\s*([+-]?[\d.]+)% above estimates",
                r"reported earnings.*?([+-]?[\d.]+)% above estimates",
            ]),
            revenue_beat_rate=find_first([r"([+-]?[\d.]+)% of S&P 500 companies.*?above revenue estimates"]),
            revenue_surprise_pct=find_first([r"revenues? (?:are )?reporting\s*([+-]?[\d.]+)% above estimates"]),
            forward_12m_pe=find_first([
                r"forward\s+12-month\s+P/E\s+ratio\s+(?:is|was|of)\s*([\d]+(?:\.[\d]+)?)",
                r"forward\s+12-month\s+P/E\s+ratio\s+of\s+the\s+S&P\s+500\s+(?:is|was)\s*([\d]+(?:\.[\d]+)?)",
                r"forward\s+12-month\s+P/E\s+ratio\s+for\s+the\s+S&P\s+500\s+(?:is|was)\s*([\d]+(?:\.[\d]+)?)",
                r"forward\s+12-month\s+P/E\s+ratio\s+for\s+the\s+S&P\s+500\s+(?:has\s+)?(?:increased|decreased|rose|fell|declined|dropped|climbed|reduced)\s+to\s*([\d]+(?:\.[\d]+)?)",
                r"forward\s+12-month\s+P/E\s+ratio\s+(?:has\s+)?(?:increased|decreased|rose|fell|declined|dropped|climbed|reduced)\s+to\s*([\d]+(?:\.[\d]+)?)",
                r"forward\s+12-month\s+P/E\s+ratio\s+(?:has\s+increased\s+to|increased\s+to|stood\s+at|is\s+currently\s+at)\s*([\d]+(?:\.[\d]+)?)",
            ]),
            forward_12m_pe_10y_avg=find_forward_pe_average(),
            revision_breadth_score=None,
            sector_growth_json=None,
            fetched_at=fetched_at,
            source_url=source_url,
        )

    @staticmethod
    def infer_reference_quarter(text: str, title: str = "", report_date: str = "") -> str:
        def formatted(match: re.Match[str]) -> str:
            return f"{match.group(2)}Q{match.group(1)}"

        def seasonal_period(value: str) -> tuple[int, int] | None:
            try:
                parsed = datetime.strptime(value[:10], "%Y-%m-%d")
            except (TypeError, ValueError):
                return None
            if parsed.month in (1, 2, 3):
                return parsed.year - 1, 4
            if parsed.month in (4, 5, 6):
                return parsed.year, 1
            if parsed.month in (7, 8, 9):
                return parsed.year, 2
            if parsed.month in (10, 11):
                return parsed.year, 3
            return parsed.year, 4

        quarter_pattern = r"\bQ([1-4])\s*(20\d{2})\b"
        # Annual previews are not quarter-specific in the source text, but
        # Q4 is the least misleading representation in this quarterly schema.
        annual_match = re.search(r"\bCY\s*(20\d{2})\b", title, re.IGNORECASE)
        if annual_match:
            return f"{annual_match.group(1)}Q4"

        title_matches = list(re.finditer(quarter_pattern, title, re.IGNORECASE))
        for match in title_matches:
            prefix = title[max(0, match.start() - 24):match.start()].lower()
            if re.search(r"\b(?:since|from|over|past|last|prior|than)\s*$", prefix):
                continue
            return formatted(match)

        period = seasonal_period(report_date)
        # A title such as “... for Q2” omits the year; the publication date
        # supplies the year without looking at later forecast quarters.
        bare_title = re.search(r"\bQ([1-4])\b", title, re.IGNORECASE)
        if bare_title and period:
            title_year = period[0]
            try:
                publication = datetime.strptime(report_date[:10], "%Y-%m-%d")
                # A Q4 article published in Jan–Mar refers to the prior
                # calendar year; Q1/Q2/Q3 bare titles refer to the current
                # publication year.
                if int(bare_title.group(1)) != 4 and publication.month <= 3:
                    title_year = publication.year
            except (TypeError, ValueError):
                pass
            return f"{title_year}Q{bare_title.group(1)}"

        matches = list(re.finditer(quarter_pattern, text, re.IGNORECASE))
        if period:
            expected = f"{period[0]}Q{period[1]}"
            for match in matches:
                if formatted(match) == expected:
                    return expected
            ordinal_map = {"first": 1, "second": 2, "third": 3, "fourth": 4}
            ordinal = re.search(r"\b(first|second|third|fourth)\s+quarter\s+(?:earnings\s+)?season\b", text[:2500], re.IGNORECASE)
            if ordinal and ordinal_map[ordinal.group(1).lower()] == period[1]:
                return expected
            # Valuation-only Insight notes often contain no earnings-quarter
            # token.  Align their rolling forward P/E snapshot to the
            # publication-season quarter so it remains usable in the same
            # time-indexed regime table without inventing a forecast quarter.
            if re.search(r"forward\s+12-month\s+P/E", text, re.IGNORECASE):
                return expected
        if matches:
            return formatted(matches[0])
        return ""
