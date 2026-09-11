from __future__ import annotations

from datetime import datetime, timezone
import io
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .models import MsciReviewEvent


class MsciIndexReviewClient:
    def __init__(self, timeout_seconds: float = 45.0, session: requests.Session | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html,application/pdf,application/xhtml+xml",
            }
        )

    def fetch_review_page(self, url: str = "https://www.msci.com/eqb/gimi/stdindex/index_review.html") -> tuple[str, bytes]:
        response = self.session.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.url, response.content

    def fetch_public_list(self, url: str) -> tuple[str, bytes]:
        response = self.session.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        if response.content[:4] != b"%PDF":
            raise ValueError(f"MSCI public-list URL did not return a PDF: {url}")
        return response.url, response.content

    @staticmethod
    def extract_public_list_links(html: str, page_url: str) -> list[str]:
        """Return MSCI's publicly listed additions/deletions PDFs.

        The review page also links historical constituent files and
        methodology documents.  ``PublicList`` is the source's stable marker
        for the review event artifact, so constituent snapshots are not mixed
        into the event table.
        """
        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            if not href:
                continue
            url = urljoin(page_url, href)
            parsed = urlparse(url)
            if parsed.netloc.lower() not in {"www.msci.com", "msci.com", "app2.msci.com"}:
                continue
            if "publiclist" not in parsed.path.lower():
                continue
            if url not in links:
                links.append(url)
        return links

    @staticmethod
    def _parse_date(value: str) -> str:
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                continue
        return ""

    @staticmethod
    def _size_segment(source_url: str) -> str:
        filename = urlparse(source_url).path.rsplit("/", 1)[-1].upper()
        if "NEW_FM" in filename:
            return "FRONTIER_NEW"
        if "FM_SC" in filename:
            return "FRONTIER_SMALL_CAP"
        if "FM_PUBLICLIST" in filename:
            return "FRONTIER_MARKETS"
        if "CHINAAPUBLICLIST" in filename:
            return "CHINA_A"
        if "SCPUBLICLIST" in filename:
            return "SMALL_CAP"
        if "MICROPUBLICLIST" in filename:
            return "MICRO"
        return "STANDARD"

    @staticmethod
    def _review_cycle(source_url: str, size_segment: str) -> str:
        filename = urlparse(source_url).path.rsplit("/", 1)[-1]
        match = re.search(r"MSCI[_-](Feb|May|Aug|Nov)(\d{2})", filename, re.IGNORECASE)
        if not match:
            return ""
        month = {"feb": 2, "may": 5, "aug": 8, "nov": 11}[match.group(1).lower()]
        year = 2000 + int(match.group(2))
        return f"{year:04d}-{month:02d}-{size_segment}"

    @staticmethod
    def _country_code(index_name: str) -> str:
        name = index_name.upper()
        mapping = {
            "AUSTRALIA": "AU", "JAPAN": "JP", "INDONESIA": "ID", "PHILIPPINES": "PH",
            "TAIWAN": "TW", "KOREA": "KR", "INDIA": "IN", "CHINA": "CN",
            "SINGAPORE": "SG", "HONG KONG": "HK", "MALAYSIA": "MY", "THAILAND": "TH",
            "NEW ZEALAND": "NZ", "UNITED KINGDOM": "GB", "UNITED STATES": "US", "USA": "US",
            "CANADA": "CA", "BRAZIL": "BR", "MEXICO": "MX", "FRANCE": "FR",
            "GERMANY": "DE", "ITALY": "IT", "SPAIN": "ES", "NETHERLANDS": "NL",
            "SWITZERLAND": "CH", "DENMARK": "DK", "SWEDEN": "SE", "NORWAY": "NO",
            "FINLAND": "FI", "GREECE": "GR", "TURKEY": "TR", "ISRAEL": "IL",
            "SOUTH AFRICA": "ZA", "SAUDI ARABIA": "SA", "UNITED ARAB EMIRATES": "AE",
            "QATAR": "QA", "KUWAIT": "KW", "POLAND": "PL", "RUSSIA": "RU",
            "MOROCCO": "MA", "COLOMBIA": "CO", "CHILE": "CL", "PERU": "PE",
        }
        for label, code in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
            if label in name:
                return code
        return "GLOBAL"

    @staticmethod
    def _section_name(line: str) -> str | None:
        cleaned = re.sub(r"\s+", " ", line).strip().upper()
        if not cleaned.startswith("MSCI ") or not re.search(r" INDEX(?:ES)?$", cleaned):
            return None
        # These are document-level headings, not a constituent table.
        if any(token in cleaned for token in ("GLOBAL STANDARD", "GLOBAL SMALL", "STANDARD INDEX SERIES", "INDEX SERIES")):
            return None
        return cleaned

    @staticmethod
    def _clean_security_name(value: str) -> str:
        value = re.sub(r"\s+", " ", value).strip(" .")
        value = re.sub(r"[\u2020\u2021*]+$", "", value).strip()
        return value

    @classmethod
    def _is_security_name(cls, value: str) -> bool:
        name = cls._clean_security_name(value)
        if not name or name.lower() in {
            "none", "additions", "deletions", "asia pacific", "europe, middle east and africa", "americas",
        }:
            return False
        if not re.search(r"[A-Za-z0-9]", name):
            return False
        if len(name) > 100 or re.match(r"^(page|notice|summary|region|country|index|the following)\b", name, re.I):
            return False
        if "©" in name or "disclaimer" in name.lower():
            return False
        return True

    @classmethod
    def parse_public_list_pdf(
        cls,
        payload: bytes,
        source_url: str,
        *,
        fetched_at: str | None = None,
    ) -> list[MsciReviewEvent]:
        """Parse additions/deletions while preserving name-only identity.

        MSCI's public PDFs deliberately do not provide exchange tickers for
        most rows.  ``ticker`` is kept blank rather than guessed from a
        different vendor; the raw PDF and source URL remain the authoritative
        lineage for later optional security-master resolution.
        """
        try:
            import pdfplumber
        except ImportError as exc:  # pragma: no cover - dependency is in pyproject
            raise RuntimeError("pdfplumber is required for MSCI public-list parsing") from exc

        pages: list[str] = []
        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text(layout=True) or "")
        text = "\n".join(pages)
        date_matches = re.findall(
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b",
            text,
            re.IGNORECASE,
        )
        announcement_date = cls._parse_date(date_matches[0]) if date_matches else ""
        effective_match = re.search(r"close of\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", text, re.IGNORECASE)
        effective_date = cls._parse_date(effective_match.group(1)) if effective_match else ""
        fetched = fetched_at or datetime.now(timezone.utc).isoformat()
        size_segment = cls._size_segment(source_url)
        review_cycle = cls._review_cycle(source_url, size_segment)
        events: list[MsciReviewEvent] = []
        current_index = ""
        action_header = False
        deletion_column_start: int | None = None
        for raw_line in text.splitlines():
            section = cls._section_name(raw_line)
            if section:
                current_index = section
                action_header = False
                deletion_column_start = None
                continue
            normalized_line = re.sub(r"\s+", " ", raw_line).strip()
            if not normalized_line:
                continue
            if re.match(
                r"^(Notice and Disclaimer|About MSCI|The information contained|The Information contained|Morgan Stanley Capital)\b",
                normalized_line,
                re.I,
            ):
                # A public-list PDF ends with a legal page.  Without this
                # guard its fixed-width prose can look like a one-sided
                # additions/deletions row for the last index.
                current_index = ""
                action_header = False
                deletion_column_start = None
                continue
            if re.search(r"\bAdditions\b", normalized_line, re.I) and re.search(r"\bDeletions\b", normalized_line, re.I):
                action_header = True
                deletion_column_start = normalized_line.lower().find("deletions")
                # ``normalized_line`` collapses indentation, while the raw
                # PDF text is fixed-width.  Recover the same column offset in
                # the raw line when possible.
                raw_deletion_start = raw_line.lower().find("deletions")
                if raw_deletion_start >= 0:
                    deletion_column_start = raw_deletion_start
                continue
            if not current_index or not action_header:
                continue
            if deletion_column_start is not None and deletion_column_start > 0:
                left = cls._clean_security_name(raw_line[:deletion_column_start])
                right = cls._clean_security_name(raw_line[deletion_column_start:])
            else:
                parts = re.split(r"\s{2,}", raw_line.strip())
                if len(parts) < 2:
                    continue
                left = cls._clean_security_name(parts[0])
                right = cls._clean_security_name(parts[-1])
            country = cls._country_code(current_index)
            if cls._is_security_name(left):
                events.append(
                    MsciReviewEvent(
                        review_cycle=review_cycle,
                        announcement_date=announcement_date,
                        effective_date=effective_date,
                        action="ADD",
                        index_name=current_index,
                        country=country,
                        ticker="",
                        security_name=left,
                        size_segment=size_segment,
                        fetched_at=fetched,
                        source_url=source_url,
                    )
                )
            if cls._is_security_name(right):
                events.append(
                    MsciReviewEvent(
                        review_cycle=review_cycle,
                        announcement_date=announcement_date,
                        effective_date=effective_date,
                        action="DELETE",
                        index_name=current_index,
                        country=country,
                        ticker="",
                        security_name=right,
                        size_segment=size_segment,
                        fetched_at=fetched,
                        source_url=source_url,
                    )
                )
        return events

    @staticmethod
    def create_sample_event(
        review_cycle: str,
        announcement_date: str,
        effective_date: str,
        action: str,
        index_name: str,
        country: str,
        ticker: str,
        name: str,
        size_segment: str = "STANDARD",
    ) -> MsciReviewEvent:
        return MsciReviewEvent(
            review_cycle=review_cycle,
            announcement_date=announcement_date,
            effective_date=effective_date,
            action=action.upper(),
            index_name=index_name,
            country=country,
            ticker=ticker,
            security_name=name,
            size_segment=size_segment,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
