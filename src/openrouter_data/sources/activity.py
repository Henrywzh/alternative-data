from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import requests

from openrouter_data.exceptions import ExtractionError
from openrouter_data.models import DatasetRecord, RunContext, Snapshot
from openrouter_data.sources.provider_activity import PROVIDER_SLUGS
from openrouter_data.sources.base import SourceExtractor
from openrouter_data.utils import iter_next_f_objects, walk_json


class ActivitySource(SourceExtractor):
    name = "openrouter_activity"
    BROWSE_URL = "https://openrouter.ai/rankings"
    MODELS_API_URL = "https://openrouter.ai/api/v1/models"
    MODEL_BASE_URL = "https://openrouter.ai"
    ALLOWED_PROVIDER_PREFIXES = frozenset(PROVIDER_SLUGS.keys())

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
        )

    def fetch_popular_slugs(self, limit: int = 50) -> list[str]:
        """Discovery phase: get the most popular model slugs from the rankings page."""
        response = self.session.get(self.BROWSE_URL, timeout=self.timeout)
        response.raise_for_status()
        html = response.text

        slugs = []
        # Fallback to broad regex if next_f structure is too nested for easy walk
        # Look for maker/model patterns
        patterns = [
            r'"([a-z0-9-]+/[a-z0-9-.]+)"',
            r'/([a-z0-9-]+/[a-z0-9-.]+)/activity',
        ]
        excluded_prefixes = {"apps", "ai", "docs", "api", "static", "media", "font", "css", "image", "favicon", "manifest"}

        for pattern in patterns:
            found = re.findall(pattern, html)
            for s in found:
                if "/" in s:
                    prefix = s.split("/")[0]
                    if prefix not in excluded_prefixes:
                        slugs.append(s)

        # Also try structured parsing
        for obj in iter_next_f_objects(html):
            for node in walk_json(obj):
                if isinstance(node, dict) and node.get("slug") and "/" in node["slug"]:
                    prefix = node["slug"].split("/")[0]
                    if prefix not in excluded_prefixes:
                        slugs.append(node["slug"])

        # Deduplicate while preserving order
        seen = set()
        unique_slugs = []
        for s in slugs:
            if s not in seen:
                unique_slugs.append(s)
                seen.add(s)
        
        filtered_slugs = [slug for slug in unique_slugs if slug.split("/")[0] in self.ALLOWED_PROVIDER_PREFIXES]
        return filtered_slugs[:limit]

    def fetch_catalog_slugs(self, limit: int = 0) -> list[str]:
        """Discover current model slugs from OpenRouter's public Models API."""
        response = self.session.get(self.MODELS_API_URL, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("data", []) if isinstance(payload, dict) else []
        slugs: list[str] = []
        seen: set[str] = set()
        for item in models:
            if not isinstance(item, dict):
                continue
            slug = item.get("canonical_slug") or item.get("id")
            if not isinstance(slug, str) or "/" not in slug:
                continue
            if slug.split("/")[0] not in self.ALLOWED_PROVIDER_PREFIXES or slug in seen:
                continue
            seen.add(slug)
            slugs.append(slug)
        if limit and limit > 0:
            return slugs[:limit]
        return slugs

    def fetch_snapshots(self, slugs: list[str]) -> list[Snapshot]:
        """Fetch activity snapshots for the given slugs."""
        snapshots = []
        for slug in slugs:
            url = f"{self.MODEL_BASE_URL}/{slug}/activity"
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                snapshots.append(
                    Snapshot(
                        name=f"activity_{slug.replace('/', '_')}",
                        source_url=url,
                        body=response.text,
                    )
                )
            except Exception as e:
                # Log error but continue with other models
                print(f"Warning: Failed to fetch activity for {slug}: {e}")
        return snapshots

    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[DatasetRecord]]:
        records: list[DatasetRecord] = []
        dataset_id = "openrouter_model_activity"
        scraped_at = context.scraped_at_iso

        for snapshot in snapshots:
            # Reconstruct slug from name if needed, or better, look into body
            html = snapshot.body
            
            # Find the activity data in Next.js payload
            activity_data = []
            model_slug = None

            for obj in iter_next_f_objects(html):
                for node in walk_json(obj):
                    # Patterns found in research: categories array with tokens
                    if isinstance(node, dict) and "categories" in node and isinstance(node["categories"], list):
                        activity_data = node["categories"]
                    if isinstance(node, dict) and "slug" in node and "/" in node["slug"]:
                        model_slug = node["slug"]

            # Fallback for slug from URL if not in payload
            if not model_slug:
                model_slug = snapshot.source_url.replace(self.MODEL_BASE_URL + "/", "").replace("/activity", "")

            for item in activity_data:
                # expected fields: date, model, category, count, total_prompt_tokens, total_completion_tokens
                usage_date = item.get("date")
                category = item.get("category")
                reasoning_tokens = self._extract_reasoning_tokens(item)
                
                records.append(
                    DatasetRecord(
                        dataset_id=dataset_id,
                        source_url=snapshot.source_url,
                        source_run_id=context.run_id,
                        scraped_at=scraped_at,
                        usage_date=usage_date,
                        model_permaslug=item.get("model") or model_slug,
                        category_slug=category,
                        request_count=item.get("count"),
                        prompt_tokens=float(item.get("total_prompt_tokens", 0) or 0),
                        completion_tokens=float(item.get("total_completion_tokens", 0) or 0),
                        reasoning_tokens=reasoning_tokens,
                        total_tokens=float(item.get("total_prompt_tokens", 0) or 0) + float(item.get("total_completion_tokens", 0) or 0),
                        rank=item.get("rank"),
                    )
                )

        return {dataset_id: records}

    @staticmethod
    def _extract_reasoning_tokens(item: dict[str, Any]) -> float | None:
        for key in ("total_reasoning_tokens", "reasoning_tokens", "native_reasoning_tokens"):
            value = item.get(key)
            if value is not None:
                return float(value or 0)
        return None
