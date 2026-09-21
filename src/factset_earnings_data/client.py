from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import re
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .config import FACTSET_INSIGHT_URL, GICS_SECTORS
from .models import FACTSET_PAYLOAD_FIELDS, FactsetEarningsObservation


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
    def is_candidate_article_url(url: str) -> bool:
        """Return whether a URL looks like a FactSet Insight article.

        Topic pagination and author/search pages are navigation artifacts, not
        article records.  Keeping this predicate in the client lets the live
        collector and the offline raw-snapshot replay use the same boundary.
        """
        path = urlparse(url).path.strip("/").lower()
        if not path or path.startswith(("author/", "topic/", "search")):
            return False
        return any(
            token in path
            for token in (
                "earnings",
                "eps",
                "sp-500",
                "revenue",
                "profit",
                "margin",
                "estimate",
            )
        )

    @staticmethod
    def is_relevant_article(title: str, text: str, url: str) -> bool:
        """Keep only relevant public earnings/valuation Insight articles."""
        path = urlparse(url).path.strip("/").lower()
        if not path or path.startswith("author/"):
            return False
        blob = f"{title} {text} {url}".lower()
        return bool(
            (
                "earnings" in blob
                and ("insight" in blob or "s&p 500" in blob or "eps" in blob)
            )
            or ("eps" in blob and ("s&p 500" in blob or "estimate" in blob))
            or "forward 12-month p/e" in blob
            or "forward p/e" in blob
        )

    @staticmethod
    def classify_article(title: str, text: str, url: str = "") -> str:
        """Classify an article for discovery and dashboard filtering.

        This is intentionally descriptive rather than a trading label.  The
        classifier is based on public article language and has a stable
        fallback so new FactSet article formats remain catalogued.
        """
        blob = f"{title} {text} {url}".lower()
        if "podcast" in blob:
            return "podcast"
        if "infographic" in blob:
            return "infographic"
        if any(
            token in blob
            for token in (
                "eps estimate",
                "eps estimates",
                "estimate revision",
                "analysts increasing",
                "analysts lowering",
                "issued positive eps guidance",
                "issued negative eps guidance",
            )
        ):
            return "revision"
        if "earnings call" in blob or "earnings calls" in blob:
            return "earnings_calls"
        if "preview" in blob or "ahead of earnings" in blob:
            return "preview"
        if "sector" in blob and any(sector.lower() in blob for sector in GICS_SECTORS):
            return "sector"
        if "earnings season" in blob or "earnings insight" in blob:
            return "earnings_update"
        if any(token in blob for token in ("thematic", "theme", "tariff", "esg", "ukraine")):
            return "theme"
        return "earnings_article"

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
        report_date = ""

        def parse_date_text(value: str) -> str:
            match = re.search(
                r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+"
                r"\d{1,2}(?:st|nd|rd|th)?(?:,)?\s+\d{4}\b",
                value,
                re.IGNORECASE,
            )
            if not match:
                return ""
            cleaned = re.sub(r"(\d{1,2})(?:st|nd|rd|th)", r"\1", match.group(0), flags=re.IGNORECASE)
            for date_format in ("%B %d, %Y", "%B %d %Y"):
                try:
                    return datetime.strptime(cleaned, date_format).date().isoformat()
                except ValueError:
                    continue
            return ""

        # The publication stamp sits outside the article-body wrapper.  It is
        # the authoritative HTML date; scanning the body first can mistake a
        # historical comparison (e.g. "since April 10, 2002") for the article
        # publication date.
        for selector in (
            ".fs--blog--single--meta",
            "[class*='blog--single--meta']",
            "[class*='post--meta']",
            "time[datetime]",
        ):
            candidate = soup.select_one(selector)
            if candidate:
                candidate_text = (
                    candidate.get("datetime", "")
                    if candidate.name == "time"
                    else candidate.get_text(" ", strip=True)
                )
                report_date = parse_date_text(candidate_text)
                if report_date:
                    break
        if not report_date:
            report_date = parse_date_text(title)
        if not report_date:
            report_date = parse_date_text(text)
        if not report_date:
            report_date = parse_date_text(page_text)
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

    _URL_DATE_RE = re.compile(
        r"(january|february|march|april|may|june|july|august|september|october|november|december)"
        r"-(\d{1,2})-(20\d{2})",
        re.IGNORECASE,
    )
    _LEGACY_URL_DATE_RE = re.compile(
        r"/(20\d{2})/\d{1,2}/[^/]*?(\d{1,2})[.-](\d{1,2})[.-](\d{2,4})(?:$|[_.-])",
        re.IGNORECASE,
    )

    @classmethod
    def report_date_from_url(cls, url: str) -> str:
        """Publication date taken from the article slug, when it carries one.

        The page parser prefers FactSet's publication stamp, but historical
        slugs are more deterministic and the collector/replay uses this value
        whenever it exists. This avoids dates from sidebar teasers or article
        body references being mistaken for the publication date.
        """
        match = cls._URL_DATE_RE.search(url or "")
        if match:
            try:
                return datetime.strptime(
                    f"{match.group(1)} {match.group(2)} {match.group(3)}", "%B %d %Y"
                ).date().isoformat()
            except ValueError:
                return ""
        legacy = cls._LEGACY_URL_DATE_RE.search(url or "")
        if not legacy:
            return ""
        year_text = legacy.group(4)
        year = int(year_text)
        if len(year_text) == 2:
            year += 2000 if year < 70 else 1900
        try:
            return datetime(year, int(legacy.group(2)), int(legacy.group(3))).date().isoformat()
        except ValueError:
            return ""

    @staticmethod
    def parse_summary_metrics(
        text: str,
        report_date: str,
        ref_quarter: str,
        *,
        source_url: str = FACTSET_INSIGHT_URL,
        fetched_at: str | None = None,
    ) -> FactsetEarningsObservation:
        fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()

        def find_float(pattern: str, value_text: str | None = None) -> float | None:
            match = re.search(pattern, text if value_text is None else value_text, re.IGNORECASE | re.DOTALL)
            if not match:
                return None
            try:
                return float(match.group(1).replace("%", "").replace(",", ""))
            except ValueError:
                return None

        def find_first(patterns: list[str], bounds: tuple[float, float] | None = None) -> float | None:
            for pattern in patterns:
                value = find_float(pattern)
                if value is None:
                    continue
                # A value outside the plausible range means the pattern bound
                # to the wrong number, not that the index reached it. Keep
                # looking rather than storing it.
                if bounds and not (bounds[0] <= value <= bounds[1]):
                    continue
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

        def find_signed_change(patterns: list[str]) -> float | None:
            negative = {"decreased", "declined", "fell", "dropped", "cut", "reduced", "lowered"}
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if not match:
                    continue
                try:
                    value = abs(float(match.group(2).replace(",", "")))
                except (TypeError, ValueError):
                    continue
                direction = match.group(1).lower()
                return -value if direction in negative else value
            return None

        def find_surprise_pct(patterns: list[str]) -> float | None:
            """Parse a surprise magnitude while preserving above/below direction."""
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if not match:
                    continue
                try:
                    value = float(match.group(1).replace(",", ""))
                except (TypeError, ValueError):
                    continue
                direction = str(match.group(2) or "").lower()
                if direction == "below":
                    return -abs(value)
                if direction == "above":
                    return abs(value)
                return value
            return None

        def find_count(patterns: list[str]) -> float | None:
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if not match:
                    continue
                try:
                    return float(match.group(1).replace(",", ""))
                except (TypeError, ValueError):
                    continue
            return None

        revision_verbs = (
            "increased|rose|climbed|grew|advanced|gained|raised|"
            "decreased|declined|fell|dropped|cut|reduced|lowered"
        )
        revision_value = r"([+-]?\d+(?:\.\d+)?)%"
        quarterly_eps_revision_pct = find_signed_change([
            rf"\bQ[1-4](?:\s+20\d{{2}})?\s+bottom-up\s+EPS\s+estimate\b"
            rf"[^.]{{0,260}}?\b({revision_verbs})\s+by\s+{revision_value}",
            rf"\bbottom-up\s+EPS\s+estimate\b[^.]{{0,120}}?\bfor\s+Q[1-4]"
            rf"(?:\s+20\d{{2}})?[^.]{{0,180}}?\b({revision_verbs})\s+by\s+{revision_value}",
        ])
        annual_eps_revision_pct = find_signed_change([
            rf"\bCY\s*20\d{{2}}\s+bottom-up\s+EPS\s+estimate\b"
            rf"[^.]{{0,260}}?\b({revision_verbs})\s+by\s+{revision_value}",
            rf"\bbottom-up\s+EPS\s+estimate\b[^.]{{0,120}}?\bfor\s+CY\s*20\d{{2}}"
            rf"[^.]{{0,180}}?\b({revision_verbs})\s+by\s+{revision_value}",
        ])
        positive_guidance = find_count([r"(\d[\d,]*)\s+have issued positive EPS\s+guidance"])
        negative_guidance = find_count([r"(\d[\d,]*)\s+have issued negative EPS\s+guidance"])
        guidance_total = find_count([
            r"(\d[\d,]*)\s+(?:S&P\s+500\s+)?companies have issued (?:quarterly\s+)?EPS\s+guidance",
        ])
        if guidance_total is None and positive_guidance is not None and negative_guidance is not None:
            guidance_total = positive_guidance + negative_guidance

        sector_revisions: dict[str, float] = {}
        for sector in GICS_SECTORS:
            sector_pattern = (
                rf"\b{re.escape(sector)}\s*\(\s*([+-]?\d+(?:\.\d+)?)%\s*\)\s*sector\b"
            )
            match = re.search(sector_pattern, text, re.IGNORECASE)
            if match:
                try:
                    sector_revisions[sector] = float(match.group(1))
                except ValueError:
                    continue
        sector_revision_json = (
            json.dumps(sector_revisions, sort_keys=True, separators=(",", ":"))
            if sector_revisions
            else None
        )

        # Patterns are anchored on FactSet's actual sentence structure, verified
        # against the 3,274 retained articles. The originals assumed the figure
        # came before the subject ("X% of S&P 500 companies have reported ...
        # above EPS estimates") while the report writes "Of these companies,
        # 86% have reported actual EPS above estimates" -- so eps_beat_rate
        # filled on 6 of 218 rows and the two revenue fields on none at all.
        # Several also used re.DOTALL with .*?, letting a capture span the
        # whole article and pick up an unrelated number.
        return FactsetEarningsObservation(
            report_date=report_date,
            reference_quarter=ref_quarter,
            blended_earnings_growth_yoy=find_first([
                r"(?:blended\s+)?earnings growth rate (?:of|for the index (?:of|is))\s*([+-]?\d+(?:\.\d+)?)%",
                r"blended earnings growth (?:rate )?of\s*([+-]?\d+(?:\.\d+)?)%",
            ]),
            blended_revenue_growth_yoy=find_first([
                r"(?:blended\s+)?revenue growth rate (?:of|for the index (?:of|is))\s*([+-]?\d+(?:\.\d+)?)%",
                r"blended revenue growth (?:rate )?of\s*([+-]?\d+(?:\.\d+)?)%",
            ]),
            eps_beat_rate=find_first([
                r"[Oo]f these companies,?\s*(\d+(?:\.\d+)?)%\s*have reported actual EPS above estimates",
                r"(\d+(?:\.\d+)?)%\s*of S&P 500 companies have reported actual EPS above (?:EPS )?estimates",
                r"(\d+(?:\.\d+)?)%\s*of S&P 500 companies have reported a positive EPS surprise",
            ]),
            eps_surprise_pct=find_surprise_pct([
                r"companies are reporting earnings that are\s*([+-]?\d+(?:\.\d+)?)%\s*(?:(above|below)\s+estimates)?",
                r"reporting earnings that are\s*([+-]?\d+(?:\.\d+)?)%\s*(?:(above|below)\s+estimates)?",
                r"earnings are reporting\s*([+-]?\d+(?:\.\d+)?)%\s*(?:(above|below)\s+estimates)?",
            ]),
            revenue_beat_rate=find_first([
                r"[Oo]f these companies,?\s*(\d+(?:\.\d+)?)%\s*have reported actual revenues? above estimates",
                r"(\d+(?:\.\d+)?)%\s*of S&P 500 companies have reported actual revenues? above estimates",
            ]),
            revenue_surprise_pct=find_surprise_pct([
                r"companies are reporting revenues? that are\s*([+-]?\d+(?:\.\d+)?)%\s*(?:(above|below)\s+estimates)?",
                r"reporting revenues? that are\s*([+-]?\d+(?:\.\d+)?)%\s*(?:(above|below)\s+estimates)?",
            ]),
            forward_12m_pe=find_first([
                # The verb is required. Without it the optional "for the S&P
                # 500" lets the capture land on the constituent count.
                r"forward 12-month P/E ratio (?:for the S&P 500 )?"
                r"(?:is|was|of|at|stands at|declined to|dropped to|fell to|rose to|increased to|climbed to)"
                r"\s*(\d+(?:\.\d+)?)",
                # No loose "[^\d]{0,40}" fallback here: the only thing it
                # reliably caught was the 500 in "S&P 500", which stored a
                # forward P/E of 500.0.
                r"forward 12-month P/E (?:ratio )?(?:is|of|at)\s*(\d+(?:\.\d+)?)",
            ], bounds=(5.0, 40.0)),
            forward_12m_pe_10y_avg=find_first([
                r"10-year average\s*\(\s*(\d+(?:\.\d+)?)\s*\)",
                r"10-year average (?:P/E ratio )?(?:of|is)\s*(\d+(?:\.\d+)?)",
            ], bounds=(5.0, 40.0)),
            revision_breadth_score=None,
            sector_growth_json=None,
            fetched_at=fetched_at,
            source_url=source_url,
            quarterly_eps_revision_pct=quarterly_eps_revision_pct,
            annual_eps_revision_pct=annual_eps_revision_pct,
            positive_eps_guidance_count=positive_guidance,
            negative_eps_guidance_count=negative_guidance,
            eps_guidance_total_count=guidance_total,
            sector_revision_json=sector_revision_json,
        )

    @staticmethod
    def supported_field_count(observation: FactsetEarningsObservation) -> int:
        """Count non-empty fields that form a publishable FactSet payload."""
        count = 0
        for field in FACTSET_PAYLOAD_FIELDS:
            value = getattr(observation, field, None)
            if value is None:
                continue
            if isinstance(value, float) and math.isnan(value):
                continue
            if isinstance(value, str) and not value.strip():
                continue
            count += 1
        return count


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
            # A historical comparison such as "the largest decline since Q1
            # 2009" should not move the observation twelve years into the
            # past.  If all explicit quarter tokens are historical-context
            # references, the publication season is the honest fallback.
            contextual_matches = []
            for match in matches:
                prefix = text[max(0, match.start() - 80):match.start()].lower()
                if re.search(r"\b(?:since|from|over|past|last|prior|than|historical|recorded)\s*$", prefix):
                    continue
                contextual_matches.append(match)
            if contextual_matches:
                return formatted(contextual_matches[0])
            if matches:
                return expected
            # Many older Insight articles say "The Q1 bottom-up EPS
            # estimate" without repeating the year.  Use the publication
            # year for those bare quarter tokens, while ignoring any token
            # that is part of a historical full-year comparison above.
            for bare_match in re.finditer(r"\bQ([1-4])\b", text, re.IGNORECASE):
                if any(full.start() <= bare_match.start() < full.end() for full in matches):
                    continue
                prefix = text[max(0, bare_match.start() - 80):bare_match.start()].lower()
                if re.search(r"\b(?:since|from|over|past|last|prior|than|historical|recorded)\s*$", prefix):
                    continue
                quarter = int(bare_match.group(1))
                quarter_year = period[0]
                try:
                    publication = datetime.strptime(report_date[:10], "%Y-%m-%d")
                    if quarter != 4 and publication.month <= 3:
                        quarter_year = publication.year
                except (TypeError, ValueError):
                    pass
                return f"{quarter_year}Q{quarter}"
        if matches:
            return formatted(matches[0])
        return ""
