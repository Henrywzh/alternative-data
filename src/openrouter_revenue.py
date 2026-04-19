from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from pricing_model_aliases import clean_slug, derive_provider_prefix, generate_candidate_aliases


NO_SPLIT_PROMPT_SHARE = 0.977
NO_SPLIT_COMPLETION_SHARE = 0.023


def _clean_model_id(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


def _to_datetime(series: pd.Series, *, utc: bool = False) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=utc)


@dataclass(frozen=True)
class PriceContext:
    model_stats: pd.DataFrame
    alias_to_model_key: dict[str, str]
    provider_lookup: dict[str, dict[str, float]]
    global_stats: dict[str, float] | None
    latest_snapshot_ts: pd.Timestamp | None


def canonical_model_key(value: object, *, preserve_free: bool = False) -> str | None:
    slug = clean_slug(value)
    if slug is None:
        return None
    if preserve_free and slug.endswith(":free"):
        return slug
    aliases = generate_candidate_aliases(slug)
    if not aliases:
        return slug
    return aliases[-1]


def blended_unit_price(prompt_price: object, completion_price: object) -> float:
    prompt = pd.to_numeric(pd.Series([prompt_price]), errors="coerce").iloc[0]
    completion = pd.to_numeric(pd.Series([completion_price]), errors="coerce").iloc[0]
    if pd.notna(prompt) and pd.notna(completion):
        return float((prompt * NO_SPLIT_PROMPT_SHARE) + (completion * NO_SPLIT_COMPLETION_SHARE))
    if pd.notna(prompt):
        return float(prompt)
    if pd.notna(completion):
        return float(completion)
    return np.nan


def build_price_context(pricing: pd.DataFrame) -> PriceContext:
    if pricing.empty:
        return PriceContext(
            model_stats=pd.DataFrame(
                columns=[
                    "canonical_model_key",
                    "provider_prefix",
                    "pricing_snapshot_ts",
                    "pricing_prompt",
                    "pricing_completion",
                    "pricing_blended",
                ]
            ),
            alias_to_model_key={},
            provider_lookup={},
            global_stats=None,
            latest_snapshot_ts=None,
        )

    prepared = pricing.copy()
    prepared["model_id"] = _clean_model_id(prepared["model_id"])
    prepared["canonical_slug"] = _clean_model_id(prepared.get("canonical_slug"))
    prepared["provider_prefix"] = _clean_model_id(prepared.get("provider_prefix"))
    prepared["provider_prefix"] = prepared["provider_prefix"].fillna(
        prepared["canonical_slug"].map(derive_provider_prefix)
    ).fillna(prepared["model_id"].map(derive_provider_prefix))
    prepared["snapshot_ts"] = _to_datetime(prepared["snapshot_ts"], utc=True)
    prepared["pricing_prompt"] = pd.to_numeric(prepared["pricing_prompt"], errors="coerce")
    prepared["pricing_completion"] = pd.to_numeric(prepared["pricing_completion"], errors="coerce")
    prepared = prepared.dropna(subset=["model_id", "snapshot_ts"]).copy()
    prepared["canonical_model_key"] = prepared.apply(
        lambda row: canonical_model_key(
            row["canonical_slug"] if pd.notna(row.get("canonical_slug")) else row["model_id"],
            preserve_free=str(row["model_id"]).endswith(":free"),
        ),
        axis=1,
    )
    prepared["pricing_blended"] = prepared.apply(
        lambda row: blended_unit_price(row["pricing_prompt"], row["pricing_completion"]),
        axis=1,
    )
    prepared = prepared.dropna(subset=["canonical_model_key"]).copy()

    model_stats = (
        prepared.groupby("canonical_model_key", as_index=False)
        .agg(
            provider_prefix=("provider_prefix", "first"),
            pricing_snapshot_ts=("snapshot_ts", "max"),
            pricing_prompt=("pricing_prompt", "median"),
            pricing_completion=("pricing_completion", "median"),
            pricing_blended=("pricing_blended", "median"),
        )
        .sort_values(["provider_prefix", "canonical_model_key"], na_position="last")
        .reset_index(drop=True)
    )

    alias_to_model_key: dict[str, str] = {}
    alias_priority: dict[str, int] = {}
    for row in prepared[["model_id", "canonical_slug", "canonical_model_key"]].drop_duplicates().to_dict(orient="records"):
        model_id = row["model_id"]
        model_key = row["canonical_model_key"]
        if pd.isna(model_id) or pd.isna(model_key):
            continue

        if str(model_id).endswith(":free"):
            aliases = [str(model_id)]
        else:
            aliases: list[str] = []
            for raw in [row.get("model_id"), row.get("canonical_slug"), row.get("canonical_model_key")]:
                for alias in generate_candidate_aliases(raw):
                    if alias not in aliases:
                        aliases.append(alias)

        for priority, alias in enumerate(aliases):
            if alias not in alias_to_model_key or priority < alias_priority[alias]:
                alias_to_model_key[alias] = str(model_key)
                alias_priority[alias] = priority

    fallback_source = model_stats[pd.to_numeric(model_stats["pricing_blended"], errors="coerce") > 0].copy()
    provider_lookup = {
        row["provider_prefix"]: {
            "pricing_prompt": float(row["pricing_prompt"]) if pd.notna(row["pricing_prompt"]) else np.nan,
            "pricing_completion": float(row["pricing_completion"]) if pd.notna(row["pricing_completion"]) else np.nan,
            "pricing_blended": float(row["pricing_blended"]),
        }
        for _, row in (
            fallback_source.groupby("provider_prefix", as_index=False)
            .agg(
                pricing_prompt=("pricing_prompt", "median"),
                pricing_completion=("pricing_completion", "median"),
                pricing_blended=("pricing_blended", "median"),
            )
            .dropna(subset=["pricing_blended"])
            .iterrows()
        )
    }
    global_stats = None
    if not fallback_source.empty:
        global_stats = {
            "pricing_prompt": float(fallback_source["pricing_prompt"].median())
            if fallback_source["pricing_prompt"].notna().any()
            else np.nan,
            "pricing_completion": float(fallback_source["pricing_completion"].median())
            if fallback_source["pricing_completion"].notna().any()
            else np.nan,
            "pricing_blended": float(fallback_source["pricing_blended"].median()),
        }

    latest_snapshot_ts = prepared["snapshot_ts"].max() if prepared["snapshot_ts"].notna().any() else None
    return PriceContext(
        model_stats=model_stats,
        alias_to_model_key=alias_to_model_key,
        provider_lookup=provider_lookup,
        global_stats=global_stats,
        latest_snapshot_ts=latest_snapshot_ts,
    )


def resolve_model_key(value: object, alias_to_model_key: dict[str, str], slug_strategy: str = "canonical") -> str | None:
    slug = clean_slug(value)
    if slug is None:
        return None
    if slug_strategy == "strict":
        return alias_to_model_key.get(slug)
    for alias in generate_candidate_aliases(slug):
        if alias in alias_to_model_key:
            return alias_to_model_key[alias]
    return None


def estimate_usage_revenue(
    usage: pd.DataFrame,
    pricing: pd.DataFrame,
    *,
    slug_strategy: str = "canonical",
    pricing_strategy: str = "provider_fallback",
) -> pd.DataFrame:
    estimated = usage.copy()
    if estimated.empty:
        return estimated

    estimated = estimated.drop(
        columns=[
            "matched_model_key",
            "provider_prefix",
            "pricing_snapshot_ts",
            "pricing_prompt",
            "pricing_completion",
            "pricing_blended",
        ],
        errors="ignore",
    )

    context = build_price_context(pricing)
    estimated["model_permaslug"] = _clean_model_id(estimated["model_permaslug"])
    provider_series = estimated["provider_slug"] if "provider_slug" in estimated.columns else pd.Series(pd.NA, index=estimated.index)
    estimated["provider_slug"] = _clean_model_id(provider_series).fillna(estimated["model_permaslug"].map(derive_provider_prefix))
    estimated["matched_model_key"] = estimated["model_permaslug"].map(
        lambda slug: resolve_model_key(slug, context.alias_to_model_key, slug_strategy=slug_strategy)
    )

    model_stats = context.model_stats.rename(columns={"canonical_model_key": "matched_model_key"})
    estimated = estimated.merge(model_stats, on="matched_model_key", how="left")

    total_tokens = pd.to_numeric(estimated["total_tokens"], errors="coerce")
    prompt_tokens = pd.to_numeric(estimated["prompt_tokens"], errors="coerce").fillna(0.0)
    completion_tokens = pd.to_numeric(estimated["completion_tokens"], errors="coerce").fillna(0.0)
    pricing_prompt = pd.to_numeric(estimated["pricing_prompt"], errors="coerce")
    pricing_completion = pd.to_numeric(estimated["pricing_completion"], errors="coerce")
    pricing_blended = pd.to_numeric(estimated["pricing_blended"], errors="coerce")
    has_split = (prompt_tokens + completion_tokens) > 0

    estimated["estimated_revenue"] = np.where(
        has_split & (pricing_prompt.notna() | pricing_completion.notna()),
        (prompt_tokens * pricing_prompt.fillna(0.0)) + (completion_tokens * pricing_completion.fillna(0.0)),
        total_tokens * pricing_blended,
    )
    estimated["pricing_join_status"] = np.where(
        estimated["model_permaslug"] == "Others",
        "synthetic_unpriced",
        np.where(
            pricing_blended.notna() | pricing_prompt.notna() | pricing_completion.notna(),
            np.where(has_split, "matched_model_split_median", "matched_model_median"),
            "unresolved_missing_pricing",
        ),
    )
    estimated.loc[estimated["pricing_join_status"] == "synthetic_unpriced", "estimated_revenue"] = np.nan

    if pricing_strategy == "provider_fallback":
        unresolved_mask = estimated["pricing_join_status"].eq("unresolved_missing_pricing")
        for index in estimated[unresolved_mask].index:
            provider = estimated.at[index, "provider_slug"]
            provider_stats = context.provider_lookup.get(str(provider)) if pd.notna(provider) else None
            if provider_stats is not None:
                prompt_value = provider_stats["pricing_prompt"]
                completion_value = provider_stats["pricing_completion"]
                blended_value = provider_stats["pricing_blended"]
                status = "fallback_provider_median"
            elif context.global_stats is not None and pd.notna(context.global_stats["pricing_blended"]):
                prompt_value = context.global_stats["pricing_prompt"]
                completion_value = context.global_stats["pricing_completion"]
                blended_value = context.global_stats["pricing_blended"]
                status = "fallback_global_median"
            else:
                continue

            if has_split.loc[index] and (pd.notna(prompt_value) or pd.notna(completion_value)):
                revenue = (prompt_tokens.loc[index] * (prompt_value if pd.notna(prompt_value) else 0.0)) + (
                    completion_tokens.loc[index] * (completion_value if pd.notna(completion_value) else 0.0)
                )
            else:
                revenue = total_tokens.loc[index] * blended_value

            estimated.at[index, "pricing_prompt"] = prompt_value
            estimated.at[index, "pricing_completion"] = completion_value
            estimated.at[index, "pricing_blended"] = blended_value
            estimated.at[index, "estimated_revenue"] = revenue
            estimated.at[index, "pricing_snapshot_ts"] = context.latest_snapshot_ts
            estimated.at[index, "pricing_join_status"] = status
    elif pricing_strategy != "observed_only":
        raise ValueError("pricing_strategy must be 'provider_fallback' or 'observed_only'")

    return estimated
