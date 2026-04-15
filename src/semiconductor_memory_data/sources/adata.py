from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from semiconductor_memory_data.models import (
    AdataImagePoint,
    AdataMonthlyPoint,
    AdataRawPoint,
    Snapshot,
)
from semiconductor_memory_data.sources.config import (
    ADATA_LIST_BASE_URL,
    ADATA_MAX_PAGES,
    ADATA_REPORT_BASE_URL,
    DRAM_SECTION_KEYWORDS,
    KEYWORD_PATTERNS,
    NAND_SECTION_KEYWORDS,
    USER_AGENT,
)


class AdataEDMSource:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_report_urls(self, max_pages: int = ADATA_MAX_PAGES) -> list[str]:
        """
        Iterate list pages and collect all Market Watch report URLs.
        Stops early if a page yields no matching links.
        Returns deduplicated list in discovery order (newest first).
        """
        seen: dict[str, None] = {}
        for page in range(1, max_pages + 1):
            url = f"{ADATA_LIST_BASE_URL}?page={page}"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            # Stop when the page has no EDM links at all (truly past end of archive)
            all_edm_links = soup.select('a[href*="/edm/"]')
            if not all_edm_links:
                break
            # Collect MarketWatch report links — match both encodings:
            #   newer:  /edm/MarketWatch_YYYYMM
            #   older:  /edm/Market%20Watch_YYYYMM  (space URL-encoded)
            for tag in all_edm_links:
                href = tag.get("href", "")
                if not href:
                    continue
                decoded = unquote(href)
                if not re.search(r"/edm/Market\s*Watch_\d{6}", decoded, re.IGNORECASE):
                    continue
                # Build absolute URL using the original href (preserve %20 encoding)
                abs_url = href if href.startswith("http") else urljoin("https://industrial.adata.com", href)
                # Deduplicate by month key (handles both URL forms for the same month)
                month_key = self._month_from_url(decoded)
                if month_key and month_key not in seen:
                    seen[month_key] = abs_url
            time.sleep(0.5)
        # Return URLs sorted newest-first (month keys sort lexicographically)
        return [seen[k] for k in sorted(seen.keys(), reverse=True)]

    def fetch_snapshots(
        self,
        *,
        month: str | None = None,
        start_month: str | None = None,
        end_month: str | None = None,
        _rate_limit: bool = True,
        _latest_only: bool = False,
    ) -> list[Snapshot]:
        """
        month="YYYY-MM"       → fetch exactly that one report
        _latest_only=True     → fetch only the most recent (used by adata-update default)
        start_month/end_month → discover all URLs, filter to range
        no args               → fetch ALL discovered URLs (used by adata-backfill)
        """
        if month is not None:
            yyyymm = month.replace("-", "")
            url = ADATA_REPORT_BASE_URL + yyyymm
            return [self._fetch_single(url)]

        all_urls = self.list_report_urls()
        if not all_urls:
            return []

        if _latest_only:
            return [self._fetch_single(all_urls[0])]

        # Filter to range (decode URL before month extraction to handle %20 variants)
        filtered: list[str] = []
        for url in all_urls:
            m = self._month_from_url(unquote(url))
            if m is None:
                continue
            if start_month and m < start_month:
                continue
            if end_month and m > end_month:
                continue
            filtered.append(url)

        snapshots: list[Snapshot] = []
        for i, url in enumerate(filtered):
            try:
                snapshots.append(self._fetch_single(url))
            except Exception as exc:
                print(f"[adata] skipping {url}: {exc}")
            if _rate_limit and i < len(filtered) - 1:
                time.sleep(1.0)
        return snapshots

    def extract(
        self,
        snapshots: list[Snapshot],
    ) -> tuple[list[AdataRawPoint], list[AdataImagePoint], list[AdataMonthlyPoint]]:
        """Parse all snapshots; returns three parallel lists."""
        raw_points: list[AdataRawPoint] = []
        image_points: list[AdataImagePoint] = []
        monthly_points: list[AdataMonthlyPoint] = []
        for snapshot in snapshots:
            try:
                raw_pt, img_pts, monthly_pt = self._parse_report(snapshot)
            except Exception as exc:
                print(f"[adata] parse error for {snapshot.source_url}: {exc}")
                continue
            raw_points.append(raw_pt)
            image_points.extend(img_pts)
            monthly_points.append(monthly_pt)
        return raw_points, image_points, monthly_points

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_single(self, url: str) -> Snapshot:
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        slug = urlparse(url).path.rstrip("/").split("/")[-1].lower()
        return Snapshot(name=slug, source_url=url, body=response.text)

    def _parse_report(
        self,
        snapshot: Snapshot,
    ) -> tuple[AdataRawPoint, list[AdataImagePoint], AdataMonthlyPoint]:
        soup = BeautifulSoup(snapshot.body, "html.parser")

        # Title and month
        h1_tag = soup.find("h1")
        title = h1_tag.get_text(strip=True) if h1_tag else "Monthly Memory & Flash Market Watch"

        h2_tag = soup.find("h2")
        month_label = h2_tag.get_text(strip=True) if h2_tag else ""
        month = self._parse_month_label(month_label) or self._month_from_url(snapshot.source_url) or "unknown"

        raw_text = soup.get_text(separator=" ", strip=True)
        fetch_time = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Images — only from content CDN (storage/edms/)
        image_points: list[AdataImagePoint] = []
        for a_tag in soup.select('a[href*="/storage/edms/"]'):
            img_tag = a_tag.find("img")
            if img_tag is None:
                continue
            img_href = a_tag.get("href", "")
            if not img_href:
                continue
            image_url = img_href if img_href.startswith("http") else urljoin("https://industrial-ad.adata.com", img_href)
            image_points.append(
                AdataImagePoint(
                    month=month,
                    page_url=snapshot.source_url,
                    image_url=image_url,
                    local_path="",  # filled by pipeline after download
                    image_type=self._infer_image_type(image_url),
                )
            )

        # Section map for scoped regime derivation
        section_map = self._extract_sections(soup)

        # Full-text keyword extraction
        mentions = self._extract_keywords(raw_text)

        # Regime labels (section-scoped)
        nand_regime = self._derive_regime(section_map, NAND_SECTION_KEYWORDS)
        dram_regime = self._derive_regime(section_map, DRAM_SECTION_KEYWORDS)

        # Narrative excerpts — longest paragraph text from the relevant section
        narrative_nand_supply = self._extract_narrative(section_map, NAND_SECTION_KEYWORDS)
        narrative_nand_price = self._extract_narrative(section_map, ("NAND Price", "Flash Price"))
        narrative_dram_supply = self._extract_narrative(section_map, DRAM_SECTION_KEYWORDS)
        narrative_dram_price = self._extract_narrative(section_map, ("DRAM Price", "DDR"))

        raw_pt = AdataRawPoint(
            month=month,
            url=snapshot.source_url,
            fetch_time=fetch_time,
            title=title,
            raw_text=raw_text,
            raw_html_path="",  # filled by pipeline after saving
        )

        monthly_pt = AdataMonthlyPoint(
            month=month,
            title=title,
            narrative_nand_supply=narrative_nand_supply,
            narrative_nand_price=narrative_nand_price,
            narrative_dram_supply=narrative_dram_supply,
            narrative_dram_price=narrative_dram_price,
            mentions_hbm=mentions["mentions_hbm"],
            mentions_csp=mentions["mentions_csp"],
            mentions_server=mentions["mentions_server"],
            mentions_ddr4=mentions["mentions_ddr4"],
            mentions_reallocate_capacity=mentions["mentions_reallocate_capacity"],
            mentions_shortage=mentions["mentions_shortage"],
            mentions_oversupply=mentions["mentions_oversupply"],
            nand_regime_label=nand_regime,
            dram_regime_label=dram_regime,
            source_url=snapshot.source_url,
        )

        return raw_pt, image_points, monthly_pt

    def _parse_month_label(self, label: str) -> str | None:
        """'April 2026' -> '2026-04'. Returns None if unparseable."""
        label = label.strip()
        for fmt in ("%B %Y", "%b %Y", "%B, %Y"):
            try:
                return datetime.strptime(label, fmt).strftime("%Y-%m")
            except ValueError:
                continue
        return None

    def _month_from_url(self, url: str) -> str | None:
        """'/en/edm/MarketWatch_202604' -> '2026-04'. Returns None if not parseable."""
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        match = re.search(r"(\d{6})$", slug)
        if match:
            yyyymm = match.group(1)
            return f"{yyyymm[:4]}-{yyyymm[4:]}"
        return None

    def _extract_sections(self, soup: BeautifulSoup) -> dict[str, str]:
        """
        Walk tags in document order.
        h3/h4 headings set the current section key;
        <p> text accumulates under both the current h3 and h4 keys.
        Returns a mapping of heading text -> accumulated paragraph text.
        """
        sections: dict[str, list[str]] = {}
        current_h3: str | None = None
        current_h4: str | None = None

        for tag in soup.find_all(["h3", "h4", "p"]):
            if not isinstance(tag, Tag):
                continue
            name = tag.name
            text = tag.get_text(separator=" ", strip=True)
            if not text:
                continue
            if name == "h3":
                current_h3 = text
                current_h4 = None
                sections.setdefault(current_h3, [])
            elif name == "h4":
                current_h4 = text
                sections.setdefault(current_h4, [])
            elif name == "p":
                if current_h3:
                    sections.setdefault(current_h3, []).append(text)
                if current_h4:
                    sections.setdefault(current_h4, []).append(text)

        return {k: " ".join(v) for k, v in sections.items()}

    def _extract_keywords(self, text: str) -> dict[str, bool]:
        return {
            field_name: bool(re.search(pattern, text, re.IGNORECASE))
            for field_name, pattern in KEYWORD_PATTERNS.items()
        }

    def _derive_regime(self, section_map: dict[str, str], section_keywords: tuple[str, ...]) -> str:
        """
        Concat text from sections whose heading contains any of the section_keywords.
        "shortage" takes precedence over "oversupply" if both match.
        Falls back to "balanced".
        """
        relevant: list[str] = []
        for heading, text in section_map.items():
            if any(kw.lower() in heading.lower() for kw in section_keywords):
                relevant.append(text)
        combined = " ".join(relevant)
        if not combined.strip():
            return "balanced"
        if re.search(KEYWORD_PATTERNS["mentions_shortage"], combined, re.IGNORECASE):
            return "shortage"
        if re.search(KEYWORD_PATTERNS["mentions_oversupply"], combined, re.IGNORECASE):
            return "oversupply"
        return "balanced"

    def _extract_narrative(self, section_map: dict[str, str], section_keywords: tuple[str, ...]) -> str:
        """Return concatenated text from all sections matching any keyword."""
        parts: list[str] = []
        for heading, text in section_map.items():
            if any(kw.lower() in heading.lower() for kw in section_keywords):
                parts.append(text)
        return " ".join(parts)[:2000]  # cap at 2000 chars for storage

    @staticmethod
    def _infer_image_type(image_url: str) -> str:
        """
        'https://.../202504_nand_price_01.JPG' -> 'nand_price'
        Strips leading YYYYMM segment and trailing NN.EXT segment.
        """
        filename = Path(urlparse(image_url).path).stem  # no extension
        parts = filename.split("_")
        # Drop leading date segment (6 digits) and trailing sequence number
        if parts and re.match(r"^\d{6}$", parts[0]):
            parts = parts[1:]
        if parts and re.match(r"^\d+$", parts[-1]):
            parts = parts[:-1]
        return "_".join(parts) if parts else "unknown"
