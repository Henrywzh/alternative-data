from __future__ import annotations

from datetime import datetime, timezone
import calendar
import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .models import SpPmiObservation


class SpPmiClient:
    HOME_URL = "https://pmi.spglobal.com/Public/Home/Index?language=en"
    RELEASES_URL = "https://pmi.spglobal.com/Public/Release/PressReleases?language=en"

    def __init__(self, timeout_seconds: float = 30.0, session: requests.Session | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            }
        )

    def fetch(self, url: str) -> tuple[str, bytes]:
        response = self.session.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.url, response.content

    @staticmethod
    def _region_code(value: str) -> str:
        normalized = re.sub(r"\s+", " ", value).strip().upper()
        mapping = {
            "UNITED STATES": "US",
            "EUROZONE": "EUROZONE",
            "UNITED KINGDOM": "UK",
            "GLOBAL": "GLOBAL",
            "CHINA": "CN",
            "JAPAN": "JP",
            "ASIA": "ASIA",
            "AUSTRALIA": "AU",
            "INDIA": "IN",
            "SOUTH KOREA": "KR",
            "KOREA": "KR",
            "TAIWAN": "TW",
            "CANADA": "CA",
            "BRAZIL": "BR",
            "MEXICO": "MX",
        }
        return mapping.get(normalized, normalized)

    @staticmethod
    def _sector_code(value: str) -> str:
        normalized = value.upper()
        if "COMPOSITE" in normalized:
            return "COMPOSITE"
        if "SERVICES" in normalized or "SERVICE" in normalized:
            return "SERVICES"
        if "MANUFACTURING" in normalized or "MANUFACT" in normalized:
            return "MANUFACTURING"
        return normalized.strip() or "UNKNOWN"

    @staticmethod
    def _period_from_month(month_text: str, reference_year: int | None = None) -> str:
        month = next((idx for idx in range(1, 13) if month_text.lower() in (calendar.month_name[idx].lower(), calendar.month_abbr[idx].lower())), None)
        if month is None:
            return ""
        year = reference_year or datetime.now(timezone.utc).year
        current_month = datetime.now(timezone.utc).month
        # The homepage usually displays the latest completed month.  If the
        # displayed month is ahead of today's month, it belongs to the prior
        # calendar year.
        if reference_year is None and month > current_month:
            year -= 1
        return f"{year:04d}-{month:02d}"

    @staticmethod
    def _date_from_text(text: str) -> str:
        match = re.search(
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b",
            text,
            re.IGNORECASE,
        )
        if not match:
            return ""
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(match.group(0), fmt).date().isoformat()
            except ValueError:
                continue
        return ""

    @classmethod
    def extract_release_links(cls, html: str, page_url: str = RELEASES_URL) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            url = urljoin(page_url, str(anchor["href"]).strip())
            if "/Public/Home/PressRelease/" not in url:
                continue
            if url not in links:
                links.append(url)
        return links

    @classmethod
    def extract_index_cards(
        cls,
        html: str,
        *,
        fetched_at: str | None = None,
        source_url: str = HOME_URL,
    ) -> list[SpPmiObservation]:
        soup = BeautifulSoup(html, "html.parser")
        fetched = fetched_at or datetime.now(timezone.utc).isoformat()
        observations: list[SpPmiObservation] = []
        for card in soup.select(".indexItem"):
            name_node = card.select_one(".indexName")
            type_node = card.select_one(".instrumentTypeDescription")
            figure_node = card.select_one(".indexFigure")
            if not name_node or not type_node or not figure_node:
                continue
            region = cls._region_code(name_node.get("title") or name_node.get_text(" ", strip=True))
            sector_text = type_node.get_text(" ", strip=True)
            figure = figure_node.get_text(" ", strip=True)
            match = re.search(r"\b([A-Za-z]{3,9})\s*:\s*([+-]?\d+(?:\.\d+)?)", figure)
            if not match:
                continue
            period = cls._period_from_month(match.group(1))
            if not period:
                continue
            headline = float(match.group(2))
            observations.append(
                cls.derive_subindex_signals(
                    period=period,
                    region=region,
                    sector=cls._sector_code(sector_text),
                    headline=headline,
                    new_orders=None,
                    inventory=None,
                    output=None,
                    input_prices=None,
                    output_prices=None,
                    employment=None,
                    is_flash="flash" in f"{sector_text} {figure}".lower(),
                    release_date="",
                    fetched_at=fetched,
                    source_url=source_url,
                )
            )
        return observations

    # Sponsor branding in a PMI headline is not a region. "S&P Global US
    # Services PMI" must resolve to US: an earliest-position scan otherwise
    # matches the GLOBAL in the vendor's own name first.
    _VENDOR_TOKENS = ("S&P GLOBAL", "S&P/", "HCOB", "CAIXIN", "AU JIBUN BANK", "JIBUN BANK", "JUDO BANK")

    @classmethod
    def _strip_vendor(cls, text: str) -> str:
        upper = text.upper()
        for token in cls._VENDOR_TOKENS:
            upper = upper.replace(token, " ")
        return upper

    @classmethod
    def _first_in_text(cls, text: str, candidates: list[tuple[str, str]]) -> str | None:
        """Region code for the candidate appearing earliest in ``text``.

        Earliest by position, not by order in the candidate list: the list is
        ordered by specificity, so a list-order scan let a passing "U.S."
        mention outrank the actual subject of the release.
        """
        best: tuple[int, str] | None = None
        for pattern, candidate in candidates:
            match = re.search(pattern, text)
            if match and (best is None or match.start() < best[0]):
                best = (match.start(), candidate)
        return cls._region_code(best[1]) if best else None

    @classmethod
    def parse_release_html(
        cls,
        html: str,
        source_url: str,
        *,
        fetched_at: str | None = None,
    ) -> SpPmiObservation | None:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "noscript", "svg"]):
            element.decompose()
        heading = soup.find("h1") or soup.find("title")
        title = heading.get_text(" ", strip=True) if heading else ""
        text = soup.get_text("\n", strip=True)
        combined = f"{title}\n{text}"
        upper = combined.upper()
        if "PMI" not in upper:
            return None
        # Scope both region and sector to the headline, not the whole page.
        # Scanning the full text matched navigation ("Composite PMI | Services
        # PMI") and passing references ("by comparison, the U.S. ..."), so a
        # Eurozone manufacturing release was stored as region=US,
        # sector=COMPOSITE -- wrong, and silently so.
        headline = cls._strip_vendor(title or combined.split("\n", 1)[0])
        region_candidates = [
            (r"\bUNITED STATES\b", "UNITED STATES"), (r"(?<![A-Z])U\.S\.(?![A-Z])", "UNITED STATES"), (r"\bUS\b", "UNITED STATES"),
            (r"\bEUROZONE\b", "EUROZONE"), (r"\bUNITED KINGDOM\b", "UNITED KINGDOM"),
            (r"\bCHINA\b", "CHINA"), (r"\bJAPAN\b", "JAPAN"), (r"\bTAIWAN\b", "TAIWAN"),
            (r"\bAUSTRALIA\b", "AUSTRALIA"), (r"\bINDIA\b", "INDIA"), (r"\bSOUTH KOREA\b", "SOUTH KOREA"),
            (r"\bKOREA\b", "KOREA"), (r"\bCANADA\b", "CANADA"), (r"\bBRAZIL\b", "BRAZIL"),
            (r"\bMEXICO\b", "MEXICO"), (r"\bGLOBAL\b", "GLOBAL"),
        ]
        region = cls._first_in_text(headline, region_candidates) or cls._first_in_text(upper, region_candidates) or "GLOBAL"
        sector = cls._sector_code(headline)
        month_match = re.search(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
            combined,
            re.IGNORECASE,
        )
        period = cls._period_from_month(month_match.group(1), int(month_match.group(2))) if month_match else ""
        release_date = cls._date_from_text(combined)
        is_flash = "FLASH" in upper

        def first_metric(labels: list[str]) -> float | None:
            """First number attached to one of ``labels``.

            The gap is deliberately short. A 100-character window that merely
            excluded digits let a label bind to a number from a different
            sentence, and because the labels overlap ("output" is a prefix of
            "output prices") an index could silently take its neighbour's
            value -- output_index was reading the Output Prices figure.
            """
            for label in labels:
                pattern = rf"\b{label}\b(?:\s+index)?[^\d\n+-]{{0,24}}([+-]?\d+(?:\.\d+)?)"
                match = re.search(pattern, combined, re.IGNORECASE)
                if match:
                    try:
                        return float(match.group(1))
                    except ValueError:
                        pass
            return None

        headline = first_metric([r"(?:headline\s+)?PMI", r"composite\s+output\s+index", r"manufacturing\s+PMI", r"services\s+PMI"])
        if headline is None:
            headline = first_metric([r"PMI\s+(?:rose|fell|increased|decreased|posted|was|at)"])
        if not period or headline is None:
            return None
        fetched = fetched_at or datetime.now(timezone.utc).isoformat()
        return cls.derive_subindex_signals(
            period=period,
            region=region,
            sector=sector,
            headline=headline,
            new_orders=first_metric([r"new\s+orders(?:\s+index)?", r"new\s+business(?:\s+index)?"]),
            inventory=first_metric([r"finished\s+goods\s+inventor(?:y|ies)", r"stocks\s+of\s+finished\s+goods", r"inventor(?:y|ies)"]),
            output=first_metric([r"output(?!\s+pric)(?:\s+index)?", r"business\s+activity(?:\s+index)?"]),
            input_prices=first_metric([r"input\s+prices?(?:\s+index)?", r"input\s+costs?(?:\s+index)?"]),
            output_prices=first_metric([r"output\s+prices?(?:\s+index)?", r"charges(?:\s+index)?"]),
            employment=first_metric([r"employment(?:\s+index)?"]),
            is_flash=is_flash,
            release_date=release_date,
            fetched_at=fetched,
            source_url=source_url,
        )

    @staticmethod
    def derive_subindex_signals(
        period: str,
        region: str,
        sector: str,
        headline: float | None,
        new_orders: float | None,
        inventory: float | None,
        output: float | None,
        input_prices: float | None,
        output_prices: float | None,
        employment: float | None,
        is_flash: bool,
        release_date: str,
        fetched_at: str | None = None,
        source_url: str | None = None,
    ) -> SpPmiObservation:
        ratio = (new_orders / inventory) if (new_orders is not None and inventory not in (None, 0)) else None
        spread = (output_prices - input_prices) if (output_prices is not None and input_prices is not None) else None
        return SpPmiObservation(
            period=period,
            region=region,
            sector=sector,
            is_flash=is_flash,
            headline_pmi=headline,
            new_orders_index=new_orders,
            output_index=output,
            finished_goods_inventory_index=inventory,
            input_prices_index=input_prices,
            output_prices_index=output_prices,
            employment_index=employment,
            orders_to_inventory_ratio=round(ratio, 4) if ratio is not None else None,
            price_pass_through_spread=round(spread, 4) if spread is not None else None,
            release_date=release_date,
            fetched_at=fetched_at or datetime.now(timezone.utc).isoformat(),
            source_url=source_url,
        )
