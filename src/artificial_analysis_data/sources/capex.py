from __future__ import annotations

import ast
import re
from urllib.parse import urljoin

import requests

from artificial_analysis_data.models import CapexQuarterPoint, Snapshot


class ArtificialAnalysisCapexSource:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.page_url = "https://artificialanalysis.ai/trends"

    def fetch_snapshots(self) -> list[Snapshot]:
        page_response = self.session.get(self.page_url, timeout=30)
        page_response.raise_for_status()
        bundle_url = self.resolve_bundle_url(page_response.text)
        bundle_response = self.session.get(bundle_url, timeout=30)
        bundle_response.raise_for_status()
        snapshots = [
            Snapshot(name="trends_page", source_url=self.page_url, body=page_response.text),
            Snapshot(name="trends_bundle", source_url=bundle_url, body=bundle_response.text),
        ]
        if not self._contains_capex_payload(bundle_response.text):
            for capex_bundle_url in self.resolve_capex_data_bundle_urls(page_response.text):
                if capex_bundle_url == bundle_url:
                    continue
                capex_response = self.session.get(capex_bundle_url, timeout=30)
                capex_response.raise_for_status()
                snapshots.append(
                    Snapshot(name="capex_data_bundle", source_url=capex_bundle_url, body=capex_response.text)
                )
                if self._contains_capex_payload(capex_response.text):
                    break
        return snapshots

    def resolve_bundle_url(self, html: str) -> str:
        match = re.search(
            r'(/_next/static/chunks/app/(?:%5Blocale%5D|\(pages\))/trends/page-[^"]+\.js)',
            html,
        )
        if match is None:
            raise ValueError("Could not resolve trends page bundle URL")
        return urljoin(self.page_url, match.group(1))

    def resolve_capex_data_bundle_urls(self, html: str) -> list[str]:
        match = re.search(r'I\[\d+,\[(?P<chunks>.*?)\],\\"CapexQuarterContextProvider\\"', html, re.DOTALL)
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
        match = re.search(r'\[\{id:"20\d{2}-q[1-4]"', bundle_text)
        if match is None:
            raise ValueError("Could not locate capex array in trends bundle")

        object_literal = self._extract_balanced_array(bundle_text, match.start())
        normalized = re.sub(r'([{,])([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', object_literal)
        normalized = re.sub(r'([:\[,])\.(\d)', r"\g<1>0.\2", normalized)
        normalized = re.sub(r"\btrue\b", "True", normalized)
        normalized = re.sub(r"\bfalse\b", "False", normalized)
        normalized = re.sub(r"\bnull\b", "None", normalized)
        parsed = ast.literal_eval(normalized)
        return parsed

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
