from __future__ import annotations

import pandas as pd


# Static supplemental pricing for models absent from the OpenRouter API.
# Prices are in $/token (same units as raw_openrouter_models).
# Sources: openai.com/pricing, mistral.ai/pricing, Google AI pricing pages.
SUPPLEMENT_PRICING: list[dict] = [
    # OpenAI embeddings
    {"model_id": "openai/text-embedding-3-small",  "pricing_prompt": 2e-08,   "pricing_completion": 0.0},
    {"model_id": "openai/text-embedding-3-large",  "pricing_prompt": 1.3e-07, "pricing_completion": 0.0},
    {"model_id": "openai/text-embedding-ada-002",  "pricing_prompt": 1e-07,   "pricing_completion": 0.0},
    # Mistral embeddings & small completions
    {"model_id": "mistralai/mistral-embed-2312",   "pricing_prompt": 1e-07,   "pricing_completion": 0.0},
    {"model_id": "mistralai/codestral-embed-2505", "pricing_prompt": 1.5e-07, "pricing_completion": 0.0},
    {"model_id": "mistralai/mistral-tiny",         "pricing_prompt": 2.5e-07, "pricing_completion": 7.5e-07},
    # Google embeddings (free tier — zero price to reflect no per-token cost)
    {"model_id": "google/gemini-embedding-001",    "pricing_prompt": 0.0,     "pricing_completion": 0.0},
    # Qwen embeddings (no public price published — zero flags for review)
    {"model_id": "qwen/qwen3-embedding-8b",        "pricing_prompt": 0.0,     "pricing_completion": 0.0},
    {"model_id": "qwen/qwen3-embedding-4b",        "pricing_prompt": 0.0,     "pricing_completion": 0.0},
]

_SNAPSHOT_TS = "2026-01-01T00:00:00.000000Z"


def supplement_pricing_df() -> pd.DataFrame:
    """Return a DataFrame of supplemental pricing rows compatible with raw_openrouter_models schema."""
    rows = []
    for entry in SUPPLEMENT_PRICING:
        rows.append({
            "dataset_id": "supplement_pricing",
            "source_url": "manual",
            "source_run_id": "static",
            "scraped_at": _SNAPSHOT_TS,
            "snapshot_ts": _SNAPSHOT_TS,
            "model_id": entry["model_id"],
            "canonical_slug": entry["model_id"],
            "pricing_prompt": entry["pricing_prompt"],
            "pricing_completion": entry["pricing_completion"],
            "provider_prefix": entry["model_id"].split("/")[0],
        })
    return pd.DataFrame(rows)
