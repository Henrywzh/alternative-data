"""Identity and quality helpers for OpenRouter serving-provider routes.

OpenRouter model activity identifies the model owner in the route prefix while
provider pages identify the serving endpoint in the page slug.  Those are
different dimensions: an independent inference provider can serve a model
owned by any lab, and a first-party lab can also expose a route for another
lab's model.  Keep the distinction explicit in every normalized row.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pandas as pd


# These are intentionally conservative, stable classifications.  Providers
# not in the first-party or hyperscaler sets are known serving providers, so
# they are classified as independent inference rather than silently treated as
# first-party labs.  A missing provider remains ``unknown``.
FIRST_PARTY_PROVIDER_SLUGS = frozenset(
    {
        "ai21",
        "aion-labs",
        "openai",
        "anthropic",
        "meta",
        "meta-llama",
        "mistral",
        "mistralai",
        "deepseek",
        "xai",
        "x-ai",
        "z-ai",
        "moonshotai",
        "minimax",
        "xiaomi",
        "tencent",
        "stepfun",
        "cohere",
        "perplexity",
        "upstage",
        "reka",
        "rekaai",
        "liquid",
        "arcee-ai",
        "black-forest-labs",
        "fish-audio",
        "recraft",
        "sakana",
        "seed",
        "voyageai",
    }
)

HYPERSCALER_PROVIDER_SLUGS = frozenset(
    {
        "azure",
        "azure-ai",
        "microsoft-azure",
        "amazon-bedrock",
        "aws-bedrock",
        "alibaba",
        "baidu",
        "claude-on-aws",
        "digitalocean",
        "google-vertex",
        "google-ai-studio",
        "vertex-ai",
        "google-cloud",
        "cloudflare",
        "cloudflare-workers-ai",
        "oracle",
        "oracle-cloud",
        "ibm",
        "nvidia",
    }
)

INDEPENDENT_INFERENCE_PROVIDER_SLUGS = frozenset(
    {
        "akashml",
        "ambient",
        "atlas-cloud",
        "baseten",
        "cerebras",
        "chutes",
        "clarifai",
        "coreweave",
        "crucible",
        "crusoe",
        "darkbloom",
        "decart",
        "deepgram",
        "deepinfra",
        "dekallm",
        "fireworks",
        "friendli",
        "gmicloud",
        "groq",
        "inception",
        "inceptron",
        "infermatic",
        "inflection",
        "io-net",
        "ionstream",
        "krea",
        "mancer",
        "mara",
        "modal",
        "modelrun",
        "morph",
        "nebius",
        "nex-agi",
        "nextbit",
        "novita",
        "open-inference",
        "parasail",
        "perceptron",
        "phala",
        "poolside",
        "relace",
        "sail-research",
        "sambanova",
        "siliconflow",
        "sourceful",
        "stealth",
        "streamlake",
        "switchpoint",
        "together",
        "venice",
        "wafer",
    }
)

SERVING_PROVIDER_ORIGIN_ALIASES: dict[str, str] = {
    "alibaba": "qwen",
    "google-ai-studio": "google",
    "google-vertex": "google",
    "meta-llama": "meta",
    "mistral": "mistralai",
    "reka": "rekaai",
    "seed": "bytedance-seed",
    "xai": "x-ai",
}

MODEL_ORIGIN_COMPANIES: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "meta": "Meta",
    "meta-llama": "Meta",
    "mistralai": "Mistral AI",
    "deepseek": "DeepSeek",
    "x-ai": "xAI (Grok)",
    "z-ai": "智谱AI (Z.ai)",
    "moonshotai": "Moonshot AI",
    "qwen": "Alibaba (Qwen)",
    "minimax": "MiniMax",
    "xiaomi": "Xiaomi",
    "tencent": "Tencent",
    "stepfun": "StepFun",
    "cohere": "Cohere",
    "perplexity": "Perplexity",
    "01-ai": "01.AI (Yi)",
    "upstage": "Upstage",
    "rekaai": "Reka AI",
    "liquid": "Liquid AI",
    "arcee-ai": "Arcee AI",
    "nvidia": "NVIDIA",
    "databricks": "Databricks",
    "bytedance-seed": "ByteDance (Seed)",
}


def _clean_slug(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().casefold()
    if not text or text in {"nan", "none", "null", "<na>", "others"}:
        return None
    return text


def model_origin_prefix(model_permaslug: object) -> str | None:
    """Return the model-owner prefix, preserving unknown prefixes."""

    slug = _clean_slug(model_permaslug)
    if not slug or "/" not in slug:
        return None
    prefix = slug.split("/", 1)[0].strip()
    return prefix or None


def model_origin_company(model_permaslug: object) -> str | None:
    """Map a model route to its owner company without inventing bucket owners."""

    prefix = model_origin_prefix(model_permaslug)
    if prefix is None:
        return None
    return MODEL_ORIGIN_COMPANIES.get(prefix, prefix.replace("-", " ").title())


def classify_serving_provider(provider_slug: object) -> str:
    """Classify a serving endpoint as first-party, hyperscaler, independent, or unknown."""

    slug = _clean_slug(provider_slug)
    if slug is None:
        return "unknown"
    if slug in HYPERSCALER_PROVIDER_SLUGS:
        return "hyperscaler"
    if slug in FIRST_PARTY_PROVIDER_SLUGS:
        return "first_party_lab"
    if slug in INDEPENDENT_INFERENCE_PROVIDER_SLUGS:
        return "independent_inference"
    return "unknown"


def is_first_party_route(model_permaslug: object, serving_provider: object) -> bool:
    """Return whether this specific model route is served by its owner lab."""

    origin = model_origin_prefix(model_permaslug)
    serving = _clean_slug(serving_provider)
    if origin is None or serving is None:
        return False
    normalized_origin = "meta" if origin == "meta-llama" else origin
    normalized_serving = SERVING_PROVIDER_ORIGIN_ALIASES.get(serving, serving)
    return normalized_origin == normalized_serving


def flag_latest_likely_incomplete_day(
    frame: pd.DataFrame,
    *,
    scraped_at: datetime | date | str | None = None,
    usage_column: str = "usage_date",
    group_columns: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Mark the newest current-day observation and exclude it from default KPIs.

    Provider charts commonly include the in-progress UTC day.  Rows are kept
    for auditability, but the current day is labelled and excluded.  A chart
    whose newest date is yesterday is treated as complete.  The helper is
    intentionally idempotent and works with legacy frames that do not yet
    carry the quality columns.
    """

    result = frame.copy()
    for column, default in (
        ("observation_status", "complete"),
        ("is_complete_day", True),
        ("include_in_default_kpis", True),
    ):
        if column not in result.columns:
            result[column] = default
    result["observation_status"] = (
        result["observation_status"].astype("string").fillna("complete")
    )
    result["is_complete_day"] = (
        result["is_complete_day"].astype("boolean").fillna(True)
    )
    result["include_in_default_kpis"] = (
        result["include_in_default_kpis"].astype("boolean").fillna(True)
    )

    if result.empty or usage_column not in result.columns:
        return result
    if group_columns:
        missing_groups = [column for column in group_columns if column not in result]
        if missing_groups:
            raise KeyError(f"incomplete-day grouping columns are missing: {missing_groups}")
        quality_columns = [
            "observation_status",
            "is_complete_day",
            "include_in_default_kpis",
        ]
        grouped = result.groupby(list(group_columns), dropna=False, sort=False)
        for indices in grouped.groups.values():
            flagged = flag_latest_likely_incomplete_day(
                result.loc[indices],
                scraped_at=scraped_at,
                usage_column=usage_column,
            )
            result.loc[indices, quality_columns] = flagged[quality_columns]
        # Also retain the aggregate guard. A globally partial latest day must
        # not leave a handful of stable small providers visible as though the
        # market-wide day were complete.
        aggregate_flagged = flag_latest_likely_incomplete_day(
            result,
            scraped_at=scraped_at,
            usage_column=usage_column,
        )
        aggregate_incomplete = ~aggregate_flagged[
            "include_in_default_kpis"
        ].astype(bool)
        result.loc[aggregate_incomplete, quality_columns] = aggregate_flagged.loc[
            aggregate_incomplete, quality_columns
        ]
        return result

    usage_dates = (
        pd.to_datetime(result[usage_column], errors="coerce", utc=True)
        .dt.tz_convert(None)
        .dt.normalize()
    )
    valid_dates = usage_dates.dropna()
    if valid_dates.empty:
        return result

    latest_date = valid_dates.max()
    if scraped_at is None:
        as_of_date = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    else:
        as_of = pd.Timestamp(scraped_at)
        if as_of.tzinfo is None:
            as_of = as_of.tz_localize("UTC")
        as_of_date = as_of.tz_convert("UTC").tz_localize(None).normalize()

    latest_rows = usage_dates.eq(latest_date)
    current_utc_day = latest_date >= as_of_date
    volume_incomplete = False
    if "total_tokens" in result.columns:
        totals = (
            pd.DataFrame(
                {
                    "usage_date": usage_dates,
                    "total_tokens": pd.to_numeric(
                        result["total_tokens"], errors="coerce"
                    ).fillna(0.0),
                }
            )
            .dropna(subset=["usage_date"])
            .groupby("usage_date")["total_tokens"]
            .sum()
            .sort_index()
        )
        prior = totals.loc[totals.index < latest_date].tail(7)
        baseline = prior.median() if len(prior) >= 3 else pd.NA
        latest_total = totals.get(latest_date, pd.NA)
        volume_incomplete = bool(
            pd.notna(baseline)
            and baseline > 0
            and pd.notna(latest_total)
            and latest_total < baseline * 0.70
        )
    incomplete = latest_rows & (current_utc_day or volume_incomplete)
    status = (
        "latest_likely_incomplete_volume"
        if volume_incomplete and not current_utc_day
        else "latest_likely_incomplete"
    )
    result.loc[incomplete, "observation_status"] = status
    result.loc[incomplete, "is_complete_day"] = False
    result.loc[incomplete, "include_in_default_kpis"] = False
    result.loc[~incomplete & usage_dates.notna(), "observation_status"] = "complete"
    result.loc[~incomplete & usage_dates.notna(), "is_complete_day"] = True
    result.loc[~incomplete & usage_dates.notna(), "include_in_default_kpis"] = True
    return result


def route_metadata(
    model_permaslug: object,
    serving_provider: object,
) -> dict[str, Any]:
    """Build the row-level identity fields shared by extractors and marts."""

    provider_type = classify_serving_provider(serving_provider)
    return {
        "model_origin_company": model_origin_company(model_permaslug),
        "serving_provider": _clean_slug(serving_provider),
        "serving_provider_type": provider_type,
        "is_first_party_route": is_first_party_route(model_permaslug, serving_provider),
    }
