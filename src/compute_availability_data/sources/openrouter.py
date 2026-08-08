from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import requests

from compute_availability_data.models import DatasetRecord, Snapshot
from compute_availability_data.storage import MINIMUM_PRODUCTION_CATALOG_MODELS
from pricing_model_aliases import derive_provider_prefix

logger = logging.getLogger(__name__)


class OpenRouterSource:
    URL = "https://openrouter.ai/api/v1/models"
    # Every genuinely healthy fetch on record has returned 336-524 models. In
    # production this endpoint has intermittently -- reproducibly only in CI,
    # not from a developer machine with the same real API key -- returned a
    # 200 with a well-formed but badly truncated `data` array (as few as 1
    # model), which sailed straight past the old, much lower validation floor
    # for months. A short retry gives a likely-transient degraded response
    # (CDN/network, not auth) a chance to recover before the caller has to
    # treat it as a hard failure.
    _MAX_FETCH_ATTEMPTS = 3
    _RETRY_DELAY_SECONDS = 5.0

    def fetch_snapshot(self) -> Snapshot:
        headers = {"Accept": "application/json", "User-Agent": "alternative-data-dashboard/1.0"}
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        for attempt in range(1, self._MAX_FETCH_ATTEMPTS + 1):
            response = requests.get(
                self.URL,
                params={"output_modalities": "all"},
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            body = response.text
            try:
                model_count = len(json.loads(body).get("data", []))
            except (json.JSONDecodeError, AttributeError):
                model_count = 0
            if model_count >= MINIMUM_PRODUCTION_CATALOG_MODELS:
                return Snapshot(name="openrouter_models", source_url=self.URL, body=body)
            logger.warning(
                "OpenRouter models fetch attempt %d/%d returned only %d models (expected >= %d); retrying",
                attempt, self._MAX_FETCH_ATTEMPTS, model_count, MINIMUM_PRODUCTION_CATALOG_MODELS,
            )
            if attempt < self._MAX_FETCH_ATTEMPTS:
                time.sleep(self._RETRY_DELAY_SECONDS)

        # All attempts came back degraded -- return the last one anyway and
        # let validate_current_catalog() reject it with a clear error rather
        # than raising a different exception here for the same condition.
        return Snapshot(name="openrouter_models", source_url=self.URL, body=body)

    def extract(self, snapshot: Snapshot, run_id: str, scraped_at: str) -> list[DatasetRecord]:
        data = json.loads(snapshot.body)
        models = data.get("data", [])
        snapshot_ts = scraped_at  # Use scraped_at as snapshot_ts for consistency

        records = []
        for model in models:
            pricing = model.get("pricing", {})
            architecture = model.get("architecture", {})
            top_provider = model.get("top_provider", {})

            records.append(
                DatasetRecord(
                    dataset_id="raw_openrouter_models",
                    source_url=self.URL,
                    source_run_id=run_id,
                    scraped_at=scraped_at,
                    snapshot_ts=snapshot_ts,
                    model_id=model.get("id"),
                    canonical_slug=model.get("canonical_slug"),
                    model_name=model.get("name"),
                    created_at=float(model.get("created")) if model.get("created") else None,
                    context_length=float(model.get("context_length")) if model.get("context_length") else None,
                    architecture=architecture.get("modality") or architecture.get("tokenizer"),
                    description=model.get("description"),
                    hugging_face_id=model.get("hugging_face_id"),
                    architecture_modality=architecture.get("modality"),
                    input_modalities_json=self._json_value(architecture.get("input_modalities")),
                    output_modalities_json=self._json_value(architecture.get("output_modalities")),
                    tokenizer=architecture.get("tokenizer"),
                    instruct_type=architecture.get("instruct_type"),
                    supported_parameters_json=self._json_value(model.get("supported_parameters")),
                    default_parameters_json=self._json_value(model.get("default_parameters")),
                    per_request_limits_json=self._json_value(model.get("per_request_limits")),
                    pricing_prompt=self._float_value(pricing.get("prompt")),
                    pricing_completion=self._float_value(pricing.get("completion")),
                    pricing_request=self._float_value(pricing.get("request")),
                    pricing_image=self._float_value(pricing.get("image")),
                    pricing_web_search=self._float_value(pricing.get("web_search")),
                    pricing_internal_reasoning=self._float_value(pricing.get("internal_reasoning")),
                    pricing_input_cache_read=self._float_value(pricing.get("input_cache_read")),
                    pricing_input_cache_write=self._float_value(pricing.get("input_cache_write")),
                    top_provider_id=top_provider.get("id"),
                    top_provider_context_length=self._float_value(top_provider.get("context_length")),
                    top_provider_max_completion_tokens=self._float_value(top_provider.get("max_completion_tokens")),
                    top_provider_is_moderated=top_provider.get("is_moderated"),
                    provider_prefix=derive_provider_prefix(model.get("canonical_slug") or model.get("id")),
                    expiration_date=model.get("expiration_date"),
                    knowledge_cutoff=model.get("knowledge_cutoff"),
                    benchmarks_json=self._json_value(model.get("benchmarks")),
                    links_json=self._json_value(model.get("links")),
                    reasoning_json=self._json_value(model.get("reasoning")),
                    supported_voices_json=self._json_value(model.get("supported_voices")),
                )
            )
        return records

    @staticmethod
    def _float_value(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _json_value(value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
