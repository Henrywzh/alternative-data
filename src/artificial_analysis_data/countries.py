from __future__ import annotations

from typing import Any

import pandas as pd


ARTIFICIAL_ANALYSIS_PROVIDER_COUNTRIES = {
    "ai2": "United States",
    "anthropic": "United States",
    "arcee": "United States",
    "aws": "United States",
    "azure": "United States",
    "databricks": "United States",
    "google": "United States",
    "ibm": "United States",
    "liquidai": "United States",
    "meta": "United States",
    "nvidia": "United States",
    "openai": "United States",
    "perplexity": "United States",
    "reka-ai": "United States",
    "servicenow": "United States",
    "snowflake": "United States",
    "xai": "United States",
    "alibaba": "China",
    "baidu": "China",
    "bytedance_seed": "China",
    "china-mobile": "China",
    "deepseek": "China",
    "inclusionai": "China",
    "kimi": "China",
    "kwaikat": "China",
    "longcat": "China",
    "minimax": "China",
    "nanbeige": "China",
    "stepfun": "China",
    "xiaomi": "China",
    "zai": "China",
}


def artificial_analysis_country_label(*, creator_country: Any, creator_slug: Any) -> str | None:
    """Normalize Artificial Analysis creator metadata to the tracked US/China comparison."""
    if pd.notna(creator_country):
        normalized = str(creator_country).strip().lower()
        if normalized in {"us", "usa", "united states", "united states of america"}:
            return "United States"
        if normalized in {"cn", "china", "prc", "people's republic of china"}:
            return "China"
    if pd.isna(creator_slug):
        return None
    return ARTIFICIAL_ANALYSIS_PROVIDER_COUNTRIES.get(str(creator_slug).strip().lower())
