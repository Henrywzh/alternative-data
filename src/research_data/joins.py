from __future__ import annotations

import numpy as np
import pandas as pd

from .clean import clean_model_id, to_datetime
from pricing_model_aliases import derive_provider_prefix, generate_candidate_aliases


def _prepare_pricing_catalog(models: pd.DataFrame) -> pd.DataFrame:
    pricing = models.copy()
    if pricing.empty:
        return pricing

    pricing["model_id"] = clean_model_id(pricing["model_id"])
    pricing["canonical_slug"] = clean_model_id(pricing.get("canonical_slug"))
    pricing["provider_prefix"] = clean_model_id(pricing.get("provider_prefix"))
    pricing["provider_prefix"] = pricing["provider_prefix"].fillna(
        pricing["canonical_slug"].map(derive_provider_prefix)
    ).fillna(pricing["model_id"].map(derive_provider_prefix))
    pricing["snapshot_ts"] = to_datetime(pricing["snapshot_ts"], utc=True)
    pricing["pricing_effective_date"] = pricing["snapshot_ts"].dt.tz_convert(None).dt.normalize()
    pricing = pricing.dropna(subset=["model_id", "pricing_effective_date"]).copy()

    alias_rows: list[dict[str, object]] = []
    for row in pricing.to_dict(orient="records"):
        exact_sources = [("canonical_slug", row.get("canonical_slug")), ("model_id", row.get("model_id"))]
        generated_sources = [("canonical_slug", row.get("canonical_slug")), ("model_id", row.get("model_id"))]

        for priority, (_, raw_value) in enumerate(exact_sources):
            if raw_value:
                alias_rows.append({**row, "pricing_lookup_key": raw_value, "lookup_priority": priority})

        generated_priority = len(exact_sources)
        for source_name, raw_value in generated_sources:
            aliases = generate_candidate_aliases(raw_value)
            for alias in aliases:
                alias_rows.append(
                    {
                        **row,
                        "pricing_lookup_key": alias,
                        "lookup_priority": generated_priority + (0 if source_name == "canonical_slug" else 1),
                    }
                )

    alias_df = pd.DataFrame(alias_rows)
    if alias_df.empty:
        return alias_df

    alias_df = alias_df.dropna(subset=["pricing_lookup_key"]).sort_values(
        ["pricing_lookup_key", "pricing_effective_date", "snapshot_ts", "lookup_priority", "model_id"]
    )
    alias_df = alias_df.drop_duplicates(subset=["pricing_lookup_key", "snapshot_ts"], keep="first")
    return alias_df.reset_index(drop=True)


def resolve_pricing_lookup_key(slug: object, pricing_lookup_keys: set[str], slug_strategy: str) -> str | None:
    cleaned = clean_model_id(pd.Series([slug])).iloc[0]
    if pd.isna(cleaned):
        return None
    text = str(cleaned)
    if slug_strategy == "strict":
        return text
    for alias in generate_candidate_aliases(text):
        if alias in pricing_lookup_keys:
            return alias
    return text


def _expand_usage_aliases(
    usage: pd.DataFrame,
    pricing_lookup_keys: set[str],
    slug_strategy: str,
) -> pd.DataFrame:
    expanded_rows: list[dict[str, object]] = []
    for row in usage.to_dict(orient="records"):
        model_permaslug = row.get("model_permaslug")
        cleaned = clean_model_id(pd.Series([model_permaslug])).iloc[0]
        aliases: list[str]
        if pd.isna(cleaned):
            aliases = []
        elif slug_strategy == "strict":
            aliases = [str(cleaned)]
        else:
            aliases = [alias for alias in generate_candidate_aliases(str(cleaned)) if alias in pricing_lookup_keys]
            if not aliases:
                aliases = [str(cleaned)]

        for alias_priority, alias in enumerate(aliases):
            expanded_rows.append(
                {
                    **row,
                    "pricing_lookup_key": alias,
                    "alias_priority": alias_priority,
                }
            )

    return pd.DataFrame(expanded_rows) if expanded_rows else usage.copy()


def latest_pricing_snapshot(models: pd.DataFrame) -> pd.DataFrame:
    if models.empty:
        return pd.DataFrame(
            columns=[
                "model_id",
                "canonical_slug",
                "provider_prefix",
                "pricing_snapshot_ts",
                "pricing_prompt",
                "pricing_completion",
                "context_length",
            ]
        )

    pricing = _prepare_pricing_catalog(models)
    pricing = pricing.sort_values(["model_id", "snapshot_ts", "lookup_priority"])
    latest = pricing.groupby("model_id", as_index=False).tail(1).copy()
    latest = latest.rename(columns={"snapshot_ts": "pricing_snapshot_ts"})
    latest = latest.rename(columns={"context_length": "openrouter_context_length"})
    return latest[
        [
            "model_id",
            "canonical_slug",
            "provider_prefix",
            "pricing_snapshot_ts",
            "pricing_prompt",
            "pricing_completion",
            "openrouter_context_length",
        ]
    ].reset_index(drop=True)


def latest_huggingface_snapshot(models: pd.DataFrame) -> pd.DataFrame:
    if models.empty:
        return pd.DataFrame(
            columns=[
                "model_id",
                "hf_download_date",
                "hf_downloads_daily_est_latest",
                "hf_downloads_all_time_latest",
            ]
        )

    enriched = models.copy()
    enriched["model_id"] = clean_model_id(enriched["model_id"])
    enriched["download_date"] = to_datetime(enriched["download_date"])
    enriched = enriched.dropna(subset=["model_id", "download_date"]).sort_values(["model_id", "download_date"])
    latest = enriched.groupby("model_id", as_index=False).tail(1).copy()
    latest = latest.rename(
        columns={
            "download_date": "hf_download_date",
            "hf_downloads_daily_est": "hf_downloads_daily_est_latest",
            "hf_downloads_all_time": "hf_downloads_all_time_latest",
        }
    )
    return latest[
        [
            "model_id",
            "hf_download_date",
            "hf_downloads_daily_est_latest",
            "hf_downloads_all_time_latest",
        ]
    ].reset_index(drop=True)


def attach_asof_pricing(activity: pd.DataFrame, pricing: pd.DataFrame, *, slug_strategy: str = "canonical") -> pd.DataFrame:
    if activity.empty:
        return pd.DataFrame()

    usage = activity.copy()
    usage["model_permaslug"] = clean_model_id(usage["model_permaslug"])
    usage["usage_date_dt"] = to_datetime(usage["usage_date"])
    pricing_df = _prepare_pricing_catalog(pricing)
    pricing_lookup_keys = set(pricing_df["pricing_lookup_key"].dropna().astype(str)) if not pricing_df.empty else set()
    usage = usage.reset_index(drop=True)
    usage["_usage_row_id"] = usage.index
    usage_expanded = _expand_usage_aliases(usage, pricing_lookup_keys, slug_strategy)
    usage_expanded = usage_expanded.sort_values(["pricing_lookup_key", "usage_date_dt", "alias_priority"]).reset_index(drop=True)

    pricing_df = pricing_df[
        [
            "pricing_lookup_key",
            "model_id",
            "canonical_slug",
            "provider_prefix",
            "snapshot_ts",
            "pricing_effective_date",
            "pricing_prompt",
            "pricing_completion",
            "context_length",
        ]
    ].copy()

    merged_groups: list[pd.DataFrame] = []
    empty_price_columns = [
        "pricing_effective_date",
        "pricing_snapshot_ts",
        "pricing_prompt",
        "pricing_completion",
        "pricing_context_length",
        "matched_model_id",
        "matched_canonical_slug",
        "matched_provider_prefix",
    ]
    for lookup_key, usage_group in usage_expanded.groupby("pricing_lookup_key", dropna=False):
        model_prices = pricing_df[pricing_df["pricing_lookup_key"] == lookup_key].copy()
        if model_prices.empty:
            missing = usage_group.copy()
            for column in empty_price_columns:
                missing[column] = pd.NA
            merged_groups.append(missing)
            continue

        joined = pd.merge_asof(
            usage_group.sort_values("usage_date_dt"),
            model_prices.rename(
                columns={
                    "snapshot_ts": "pricing_snapshot_ts",
                    "context_length": "openrouter_context_length",
                    "model_id": "matched_model_id",
                    "canonical_slug": "matched_canonical_slug",
                    "provider_prefix": "matched_provider_prefix",
                }
            ).sort_values("pricing_effective_date"),
            left_on="usage_date_dt",
            right_on="pricing_effective_date",
            direction="backward",
        )
        merged_groups.append(joined)

    merged = pd.concat(merged_groups, ignore_index=True) if merged_groups else usage_expanded
    merged["_match_rank"] = np.where(merged["pricing_snapshot_ts"].notna(), 0, 1)
    merged = merged.sort_values(["_usage_row_id", "_match_rank", "alias_priority"]).drop_duplicates(
        subset=["_usage_row_id"], keep="first"
    )
    merged = merged.drop(columns=["_match_rank", "_usage_row_id", "alias_priority"], errors="ignore")
    merged["pricing_join_status"] = "matched"
    merged.loc[merged["model_permaslug"] == "Others", "pricing_join_status"] = "synthetic_unpriced"
    merged.loc[
        (merged["pricing_join_status"] == "matched") & merged["pricing_snapshot_ts"].isna(),
        "pricing_join_status",
    ] = "unresolved_missing_pricing"
    merged.loc[
        (merged["pricing_join_status"] == "matched")
        & merged[["pricing_prompt", "pricing_completion"]].isna().all(axis=1),
        "pricing_join_status",
    ] = "unresolved_missing_pricing"
    return merged


def attach_latest_pricing(activity: pd.DataFrame, pricing: pd.DataFrame, *, slug_strategy: str = "canonical") -> pd.DataFrame:
    if activity.empty:
        return pd.DataFrame()

    latest = latest_pricing_snapshot(pricing)
    merged = activity.copy()
    merged["model_permaslug"] = clean_model_id(merged["model_permaslug"])
    latest_alias = _prepare_pricing_catalog(latest.rename(columns={"pricing_snapshot_ts": "snapshot_ts"}))
    pricing_lookup_keys = set(latest_alias["pricing_lookup_key"].dropna().astype(str)) if not latest_alias.empty else set()
    merged = merged.reset_index(drop=True)
    merged["_usage_row_id"] = merged.index
    expanded = _expand_usage_aliases(merged, pricing_lookup_keys, slug_strategy)
    merged = expanded.merge(
        latest_alias.rename(
            columns={
                "snapshot_ts": "pricing_snapshot_ts",
                "model_id": "matched_model_id",
                "canonical_slug": "matched_canonical_slug",
                "provider_prefix": "matched_provider_prefix",
                "context_length": "openrouter_context_length",
            }
        )[
            [
                "pricing_lookup_key",
                "matched_model_id",
                "matched_canonical_slug",
                "matched_provider_prefix",
                "pricing_snapshot_ts",
                "pricing_prompt",
                "pricing_completion",
                "openrouter_context_length",
            ]
        ],
        on="pricing_lookup_key",
        how="left",
    )
    merged["_match_rank"] = np.where(merged["pricing_snapshot_ts"].notna(), 0, 1)
    merged = merged.sort_values(["_usage_row_id", "_match_rank", "alias_priority"]).drop_duplicates(
        subset=["_usage_row_id"], keep="first"
    )
    merged = merged.drop(columns=["_match_rank", "_usage_row_id", "alias_priority"], errors="ignore")
    merged["pricing_join_status"] = "matched"
    merged.loc[merged["model_permaslug"] == "Others", "pricing_join_status"] = "synthetic_unpriced"
    merged.loc[
        (merged["pricing_join_status"] == "matched") & merged["pricing_snapshot_ts"].isna(),
        "pricing_join_status",
    ] = "unresolved_missing_pricing"
    merged.loc[
        (merged["pricing_join_status"] == "matched")
        & merged[["pricing_prompt", "pricing_completion"]].isna().all(axis=1),
        "pricing_join_status",
    ] = "unresolved_missing_pricing"
    return merged
