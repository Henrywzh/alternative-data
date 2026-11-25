from __future__ import annotations

import ast
import math
import re
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from artificial_analysis_data.models import CapexQuarterPoint, Snapshot


CAPEX_COMPANIES = {"microsoft", "google", "meta", "amazon", "oracle", "apple"}
MAX_SCRIPT_CANDIDATES = 64


class ArtificialAnalysisCapexSource:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.page_url = "https://artificialanalysis.ai/trends"

    def fetch_snapshots(self) -> list[Snapshot]:
        page_response = self.session.get(self.page_url, timeout=30)
        page_response.raise_for_status()
        html = page_response.text
        snapshots = [Snapshot(name="trends_page", source_url=self.page_url, body=html)]
        try:
            legacy_url = self.resolve_bundle_url(html)
        except ValueError:
            legacy_url = None

        candidates = dict.fromkeys([
            *([legacy_url] if legacy_url else []),
            *self.resolve_capex_data_bundle_urls(html),
            *self._page_script_urls(html),
        ])
        attempted = 0
        fetch_failures = 0
        for url in list(candidates)[:MAX_SCRIPT_CANDIDATES]:
            attempted += 1
            try:
                response = self.session.get(url, timeout=10)
                response.raise_for_status()
            except requests.RequestException:
                fetch_failures += 1
                continue
            contains_capex = self._contains_capex_payload(response.text)
            if contains_capex or url == legacy_url:
                name = "trends_bundle" if url == legacy_url else "capex_data_bundle"
                snapshots.append(Snapshot(name=name, source_url=url, body=response.text))
            if contains_capex:
                return snapshots
        raise ValueError(
            f"Could not locate valid capex data in Trends scripts "
            f"({attempted} checked, {fetch_failures} fetch failures)"
        )

    def _page_script_urls(self, html: str) -> list[str]:
        scripts = BeautifulSoup(html, "html.parser").select("script[src]")
        origin = urlsplit(self.page_url)
        urls = []
        # Next lists the route's scripts after its shared runtime scripts.
        for script in reversed(scripts):
            url = urljoin(self.page_url, script["src"])
            parts = urlsplit(url)
            if (
                (parts.scheme, parts.netloc) == (origin.scheme, origin.netloc)
                and parts.path.startswith("/_next/static/")
                and parts.path.endswith(".js")
            ):
                urls.append(url)
        return urls

    def resolve_bundle_url(self, html: str) -> str:
        match = re.search(
            r'(/_next/static/chunks/app/(?:%5Blocale%5D|\(pages\))/trends/page-[^"]+\.js)',
            html,
        )
        if match is None:
            raise ValueError("Could not resolve trends page bundle URL")
        return urljoin(self.page_url, match.group(1))

    def resolve_capex_data_bundle_urls(self, html: str) -> list[str]:
        # Match any component name ending in "CapexQuarterContextProvider" -
        # the site has renamed this (e.g. to "TrendsCapexQuarterContextProvider")
        # without changing the surrounding RSC payload shape.
        match = re.search(r'I\[\d+,\[(?P<chunks>.*?)\],\\"[A-Za-z]*CapexQuarterContextProvider\\"', html, re.DOTALL)
        if match is None:
            return []
        chunk_paths = re.findall(r'static/chunks/[^"\\]+\.js', match.group("chunks"))
        urls = [urljoin(self.page_url, f"/_next/{path}") for path in chunk_paths]
        return list(dict.fromkeys(reversed(urls)))

    def extract(
        self,
        snapshots: list[Snapshot],
        *,
        run_id: str,
        scraped_at: str,
    ) -> list[CapexQuarterPoint]:
        page_snapshot = next(snapshot for snapshot in snapshots if snapshot.name == "trends_page")
        bundle_snapshots = [snapshot for snapshot in snapshots if snapshot.name in {"trends_bundle", "capex_data_bundle"}]
        payload: list[dict] | None = None
        bundle_snapshot: Snapshot | None = None
        for candidate in bundle_snapshots:
            try:
                payload = self._extract_capex_payload(candidate.body)
            except ValueError:
                continue
            bundle_snapshot = candidate
            break
        if payload is None or bundle_snapshot is None:
            raise ValueError("Could not locate capex array in trends bundle")
        return [
            CapexQuarterPoint(
                quarter_id=str(item["id"]),
                quarter_label=str(item["label"]),
                microsoft=_to_float(item.get("microsoft")),
                google=_to_float(item.get("google")),
                meta=_to_float(item.get("meta")),
                amazon=_to_float(item.get("amazon")),
                oracle=_to_float(item.get("oracle")),
                apple=_to_float(item.get("apple")),
                source_url=page_snapshot.source_url,
                page_url=page_snapshot.source_url,
                bundle_url=bundle_snapshot.source_url,
                source_run_id=run_id,
                scraped_at=scraped_at,
            )
            for item in payload
        ]

    def _extract_capex_payload(self, bundle_text: str) -> list[dict]:
        for match in re.finditer(r'\[\{id:"20\d{2}-q[1-4]"', bundle_text):
            try:
                object_literal = self._extract_balanced_array(bundle_text, match.start())
                normalized = re.sub(r'([{,])([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', object_literal)
                normalized = re.sub(r'([:\[,])\.(\d)', r"\g<1>0.\2", normalized)
                normalized = re.sub(r"\btrue\b", "True", normalized)
                normalized = re.sub(r"\bfalse\b", "False", normalized)
                normalized = re.sub(r"\bnull\b", "None", normalized)
                parsed = ast.literal_eval(normalized)
            except (SyntaxError, ValueError):
                continue
            if self._is_capex_payload(parsed):
                return parsed
        raise ValueError("Could not locate capex array in trends bundle")

    @staticmethod
    def _is_capex_payload(rows: list[dict]) -> bool:
        quarters = set()
        companies = set()
        for row in rows:
            if not isinstance(row, dict):
                return False
            quarter = row.get("id")
            label = row.get("label")
            if (
                not isinstance(quarter, str) or not re.fullmatch(r"20\d{2}-q[1-4]", quarter)
                or quarter in quarters or not isinstance(label, str) or not label.strip()
            ):
                return False
            quarters.add(quarter)
            for company in CAPEX_COMPANIES & row.keys():
                value = row[company]
                if value is None:
                    continue
                if type(value) not in (int, float) or not math.isfinite(value):
                    return False
                companies.add(company)
        return {"microsoft", "google", "meta", "amazon", "oracle"} <= companies

    @staticmethod
    def _extract_balanced_array(text: str, start: int) -> str:
        """Return one JavaScript array literal without relying on minified variable names."""
        depth = 0
        quote: str | None = None
        escaped = False

        for index in range(start, len(text)):
            char = text[index]
            if quote is not None:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue

            if char in {"'", '"', "`"}:
                quote = char
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]

        raise ValueError("Could not read complete capex array from trends bundle")

    def _contains_capex_payload(self, bundle_text: str) -> bool:
        try:
            self._extract_capex_payload(bundle_text)
        except ValueError:
            return False
        return True


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)
