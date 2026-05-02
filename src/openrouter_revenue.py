from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from pricing_model_aliases import clean_slug, derive_provider_prefix, generate_candidate_aliases


NO_SPLIT_PROMPT_SHARE = 0.977
NO_SPLIT_COMPLETION_SHARE = 0.023
CONSERVATIVE_ECONOMICS_COLUMNS = [
    "usage_date",
    "provider_slug",
    "provider_name",
    "model_permaslug",
    "total_tokens",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "estimated_revenue",
    "pricing_snapshot_ts",
    "pricing_prompt",
    "pricing_completion",
    "pricing_join_status",
    "revenue_method",
    "has_pricing",
    "has_split_tokens",
    "split_source",
]


def is_free_model_slug(value: object) -> bool:
    slug = clean_slug(value)
    return bool(slug and slug.endswith(":free"))


def _clean_model_id(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


def _to_datetime(series: pd.Series, *, utc: bool = False) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=utc)


def _optional_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    return pd.Series(pd.NA, index=frame.index, dtype="string")


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
    prepared["canonical_slug"] = _clean_model_id(_optional_series(prepared, "canonical_slug"))
    prepared["provider_prefix"] = _clean_model_id(_optional_series(prepared, "provider_prefix"))
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


def _estimate_with_context(
    estimated: pd.DataFrame,
    context: PriceContext,
    *,
    slug_strategy: str,
    pricing_strategy: str,
) -> pd.DataFrame:
    if estimated.empty:
        return estimated

    estimated = estimated.copy()
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
    free_mask = estimated["model_permaslug"].map(is_free_model_slug)
    estimated.loc[free_mask, "pricing_prompt"] = 0.0
    estimated.loc[free_mask, "pricing_completion"] = 0.0
    estimated.loc[free_mask, "pricing_blended"] = 0.0
    estimated.loc[free_mask, "estimated_revenue"] = 0.0
    estimated.loc[free_mask, "pricing_join_status"] = "free_model_zero_revenue"

    if pricing_strategy == "provider_fallback":
        unresolved_mask = estimated["pricing_join_status"].eq("unresolved_missing_pricing") & ~free_mask
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

    estimated["model_permaslug"] = _clean_model_id(estimated["model_permaslug"])
    provider_series = estimated["provider_slug"] if "provider_slug" in estimated.columns else pd.Series(pd.NA, index=estimated.index)
    estimated["provider_slug"] = _clean_model_id(provider_series).fillna(estimated["model_permaslug"].map(derive_provider_prefix))
    if "usage_date" not in estimated.columns or "snapshot_ts" not in pricing.columns:
        context = build_price_context(pricing)
        return _estimate_with_context(
            estimated,
            context,
            slug_strategy=slug_strategy,
            pricing_strategy=pricing_strategy,
        )

    usage_dates = pd.to_datetime(estimated["usage_date"], errors="coerce", utc=True).dt.normalize()
    pricing_dates = pd.to_datetime(pricing["snapshot_ts"], errors="coerce", utc=True).dt.normalize()
    pricing_with_dates = pricing.copy()
    pricing_with_dates["_pricing_date"] = pricing_dates
    estimated["_usage_date"] = usage_dates
    earliest_pricing_date = pricing_with_dates["_pricing_date"].dropna().min()

    resolved_frames: list[pd.DataFrame] = []
    for usage_date, group in estimated.groupby("_usage_date", dropna=False, sort=False):
        if pd.notna(usage_date):
            eligible_pricing = pricing_with_dates[pricing_with_dates["_pricing_date"] <= usage_date].drop(
                columns="_pricing_date"
            )
            if eligible_pricing.empty and pd.notna(earliest_pricing_date):
                eligible_pricing = pricing_with_dates[
                    pricing_with_dates["_pricing_date"] == earliest_pricing_date
                ].drop(columns="_pricing_date")
        else:
            eligible_pricing = pricing_with_dates.drop(columns="_pricing_date")
        group = group.drop(columns="_usage_date")
        context = build_price_context(eligible_pricing)
        resolved_frames.append(
            _estimate_with_context(
                group,
                context,
                slug_strategy=slug_strategy,
                pricing_strategy=pricing_strategy,
            )
        )

    return pd.concat(resolved_frames, ignore_index=True) if resolved_frames else estimated.drop(columns="_usage_date")


def _empty_conservative_economics() -> pd.DataFrame:
    return pd.DataFrame(columns=CONSERVATIVE_ECONOMICS_COLUMNS)


def _prepare_usage_for_economics(provider_activity: pd.DataFrame) -> pd.DataFrame:
    if provider_activity.empty:
        return pd.DataFrame()

    usage = provider_activity.copy()
    usage["usage_date"] = pd.to_datetime(usage["usage_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    usage = usage.dropna(subset=["usage_date", "model_permaslug"]).copy()
    usage["model_permaslug"] = _clean_model_id(usage["model_permaslug"])
    entity_id = usage["entity_id"] if "entity_id" in usage.columns else pd.Series(pd.NA, index=usage.index)
    entity_name = usage["entity_name"] if "entity_name" in usage.columns else pd.Series(pd.NA, index=usage.index)
    usage["provider_slug"] = _clean_model_id(entity_id).fillna(usage["model_permaslug"].map(derive_provider_prefix))
    usage["provider_name"] = entity_name.astype("string").fillna(usage["provider_slug"])
    usage["total_tokens"] = pd.to_numeric(usage["total_tokens"], errors="coerce")
    for column in ["prompt_tokens", "completion_tokens", "reasoning_tokens"]:
        if column not in usage.columns:
            usage[column] = np.nan
        usage[column] = pd.to_numeric(usage[column], errors="coerce").astype(float)
    return usage


def _activity_split_ratios(model_activity: pd.DataFrame | None) -> pd.DataFrame:
    if model_activity is None or model_activity.empty:
        return pd.DataFrame(columns=["usage_date", "model_permaslug", "prompt_ratio", "completion_ratio", "reasoning_ratio"])

    activity = model_activity.copy()
    activity["usage_date"] = pd.to_datetime(activity["usage_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    activity["model_permaslug"] = _clean_model_id(activity["model_permaslug"])
    for column in ["prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens"]:
        if column not in activity.columns:
            activity[column] = np.nan
        activity[column] = pd.to_numeric(activity[column], errors="coerce")
    grouped = (
        activity.groupby(["usage_date", "model_permaslug"], as_index=False)
        .agg(
            activity_prompt_tokens=("prompt_tokens", "sum"),
            activity_completion_tokens=("completion_tokens", "sum"),
            activity_reasoning_tokens=("reasoning_tokens", "sum"),
            activity_total_tokens=("total_tokens", "sum"),
        )
    )
    denominator = grouped["activity_prompt_tokens"] + grouped["activity_completion_tokens"]
    denominator = denominator.where(denominator > 0, grouped["activity_total_tokens"])
    grouped["prompt_ratio"] = grouped["activity_prompt_tokens"] / denominator.replace(0, np.nan)
    grouped["completion_ratio"] = grouped["activity_completion_tokens"] / denominator.replace(0, np.nan)
    grouped["reasoning_ratio"] = grouped["activity_reasoning_tokens"] / denominator.replace(0, np.nan)
    return grouped[["usage_date", "model_permaslug", "prompt_ratio", "completion_ratio", "reasoning_ratio"]]


def _prepare_pricing_aliases(pricing: pd.DataFrame) -> pd.DataFrame:
    if pricing.empty:
        return pd.DataFrame()

    prepared = pricing.copy()
    prepared["model_id"] = _clean_model_id(prepared["model_id"])
    prepared["canonical_slug"] = _clean_model_id(_optional_series(prepared, "canonical_slug"))
    prepared["provider_prefix"] = _clean_model_id(_optional_series(prepared, "provider_prefix"))
    prepared["provider_prefix"] = prepared["provider_prefix"].fillna(
        prepared["canonical_slug"].map(derive_provider_prefix)
    ).fillna(prepared["model_id"].map(derive_provider_prefix))
    prepared["snapshot_ts"] = _to_datetime(prepared["snapshot_ts"], utc=True)
    prepared["pricing_prompt"] = pd.to_numeric(prepared["pricing_prompt"], errors="coerce")
    prepared["pricing_completion"] = pd.to_numeric(prepared["pricing_completion"], errors="coerce")
    prepared = prepared.dropna(subset=["model_id", "snapshot_ts"]).copy()

    rows: list[dict[str, object]] = []
    for row in prepared.to_dict(orient="records"):
        aliases: list[str] = []
        for value in [row.get("canonical_slug"), row.get("model_id")]:
            if pd.isna(value):
                continue
            for alias in generate_candidate_aliases(value):
                if alias not in aliases:
                    aliases.append(alias)
        for priority, alias in enumerate(aliases):
            rows.append({**row, "pricing_lookup_key": alias, "alias_priority": priority})

    aliases = pd.DataFrame(rows)
    if aliases.empty:
        return aliases
    return aliases.sort_values(["pricing_lookup_key", "snapshot_ts", "alias_priority"]).reset_index(drop=True)


def _attach_latest_prior_pricing(usage: pd.DataFrame, pricing: pd.DataFrame) -> pd.DataFrame:
    usage = usage.copy().drop(
        columns=["pricing_snapshot_ts", "pricing_prompt", "pricing_completion", "matched_model_id"],
        errors="ignore",
    ).reset_index(drop=True)
    usage["_usage_row_id"] = usage.index
    usage["_usage_date"] = pd.to_datetime(usage["usage_date"], errors="coerce", utc=True).dt.normalize()
    aliases = _prepare_pricing_aliases(pricing)
    if aliases.empty:
        for column in ["pricing_snapshot_ts", "pricing_prompt", "pricing_completion", "matched_model_id"]:
            usage[column] = pd.NA
        return usage.drop(columns=["_usage_row_id", "_usage_date"])

    pricing_keys = set(aliases["pricing_lookup_key"].dropna().astype(str))
    expanded_rows: list[dict[str, object]] = []
    for row in usage.to_dict(orient="records"):
        slug = row.get("model_permaslug")
        candidates = [alias for alias in generate_candidate_aliases(slug) if alias in pricing_keys]
        if not candidates:
            candidates = [str(slug)] if pd.notna(slug) else []
        for priority, candidate in enumerate(candidates):
            expanded_rows.append({**row, "pricing_lookup_key": candidate, "usage_alias_priority": priority})

    expanded = pd.DataFrame(expanded_rows)
    if expanded.empty:
        for column in ["pricing_snapshot_ts", "pricing_prompt", "pricing_completion", "matched_model_id"]:
            usage[column] = pd.NA
        return usage.drop(columns=["_usage_row_id", "_usage_date"])

    price_frame = aliases[
        ["pricing_lookup_key", "snapshot_ts", "pricing_prompt", "pricing_completion", "model_id"]
    ].rename(columns={"snapshot_ts": "pricing_snapshot_ts", "model_id": "matched_model_id"})

    joined_groups: list[pd.DataFrame] = []
    for key, usage_group in expanded.groupby("pricing_lookup_key", dropna=False):
        price_group = price_frame[price_frame["pricing_lookup_key"] == key].sort_values("pricing_snapshot_ts")
        if price_group.empty:
            missing = usage_group.copy()
            missing["pricing_snapshot_ts"] = pd.NaT
            missing["pricing_prompt"] = np.nan
            missing["pricing_completion"] = np.nan
            missing["matched_model_id"] = pd.Series(pd.NA, index=missing.index, dtype="string")
            joined_groups.append(missing)
            continue
        joined_groups.append(
            pd.merge_asof(
                usage_group.sort_values("_usage_date"),
                price_group,
                left_on="_usage_date",
                right_on="pricing_snapshot_ts",
                direction="backward",
            )
        )

    joined = pd.concat(joined_groups, ignore_index=True)
    joined["_price_rank"] = np.where(joined["pricing_snapshot_ts"].notna(), 0, 1)
    joined = joined.sort_values(["_usage_row_id", "_price_rank", "usage_alias_priority"]).drop_duplicates(
        "_usage_row_id", keep="first"
    )
    return joined.drop(columns=["_usage_row_id", "_usage_date", "usage_alias_priority"], errors="ignore")


def build_conservative_provider_economics(
    provider_activity: pd.DataFrame,
    pricing: pd.DataFrame,
    *,
    model_activity: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build auditable provider economics without provider/global price fallbacks."""
    usage = _prepare_usage_for_economics(provider_activity)
    if usage.empty:
        return _empty_conservative_economics()

    split_ratios = _activity_split_ratios(model_activity)
    usage = usage.merge(split_ratios, on=["usage_date", "model_permaslug"], how="left")
    for column in ["total_tokens", "prompt_tokens", "completion_tokens", "reasoning_tokens"]:
        usage[column] = pd.to_numeric(usage[column], errors="coerce").astype(float)

    native_split = usage["prompt_tokens"].fillna(0) + usage["completion_tokens"].fillna(0)
    inferred_split = usage["prompt_ratio"].notna() & usage["completion_ratio"].notna() & (native_split <= 0)
    if inferred_split.any():
        usage.loc[inferred_split, "prompt_tokens"] = (
            usage.loc[inferred_split, "total_tokens"] * usage.loc[inferred_split, "prompt_ratio"]
        )
        usage.loc[inferred_split, "completion_tokens"] = (
            usage.loc[inferred_split, "total_tokens"] * usage.loc[inferred_split, "completion_ratio"]
        )
        reasoning_inferred = inferred_split & usage["reasoning_ratio"].notna()
        if reasoning_inferred.any():
            usage.loc[reasoning_inferred, "reasoning_tokens"] = (
                usage.loc[reasoning_inferred, "total_tokens"] * usage.loc[reasoning_inferred, "reasoning_ratio"]
            )
    usage["split_source"] = np.where(native_split > 0, "source", np.where(inferred_split, "model_activity", "none"))

    priced = _attach_latest_prior_pricing(usage, pricing)
    priced["pricing_prompt"] = pd.to_numeric(priced["pricing_prompt"], errors="coerce")
    priced["pricing_completion"] = pd.to_numeric(priced["pricing_completion"], errors="coerce")
    priced["total_tokens"] = pd.to_numeric(priced["total_tokens"], errors="coerce")
    priced["prompt_tokens"] = pd.to_numeric(priced["prompt_tokens"], errors="coerce")
    priced["completion_tokens"] = pd.to_numeric(priced["completion_tokens"], errors="coerce")
    priced["reasoning_tokens"] = pd.to_numeric(priced["reasoning_tokens"], errors="coerce")

    has_pricing = priced["pricing_snapshot_ts"].notna() & (
        priced["pricing_prompt"].notna() | priced["pricing_completion"].notna()
    )
    has_split = (priced["prompt_tokens"].fillna(0) + priced["completion_tokens"].fillna(0)) > 0
    blended = blended_unit_price_series(priced["pricing_prompt"], priced["pricing_completion"])
    free_mask = priced["model_permaslug"].map(is_free_model_slug)

    priced["estimated_revenue"] = np.nan
    split_priced = has_pricing & has_split
    priced.loc[split_priced, "estimated_revenue"] = (
        priced.loc[split_priced, "prompt_tokens"].fillna(0) * priced.loc[split_priced, "pricing_prompt"].fillna(0)
        + priced.loc[split_priced, "completion_tokens"].fillna(0)
        * priced.loc[split_priced, "pricing_completion"].fillna(0)
    )
    blended_priced = has_pricing & ~has_split & priced["total_tokens"].notna()
    priced.loc[blended_priced, "estimated_revenue"] = priced.loc[blended_priced, "total_tokens"] * blended.loc[blended_priced]

    priced["has_pricing"] = has_pricing
    priced["has_split_tokens"] = has_split
    priced["pricing_join_status"] = np.where(has_pricing, "matched_asof", "unresolved_missing_pricing")
    priced.loc[priced["model_permaslug"].eq("Others"), "pricing_join_status"] = "synthetic_unpriced"
    priced.loc[priced["model_permaslug"].eq("Others"), "estimated_revenue"] = np.nan
    priced["revenue_method"] = "unpriced"
    priced.loc[has_pricing & has_split & priced["split_source"].eq("source"), "revenue_method"] = "exact_split_priced"
    priced.loc[has_pricing & has_split & priced["split_source"].eq("model_activity"), "revenue_method"] = "model_split_inferred"
    priced.loc[blended_priced, "revenue_method"] = "model_blended_no_split"
    priced.loc[priced["model_permaslug"].eq("Others"), "revenue_method"] = "unpriced"
    priced.loc[free_mask, "pricing_prompt"] = 0.0
    priced.loc[free_mask, "pricing_completion"] = 0.0
    priced.loc[free_mask, "estimated_revenue"] = 0.0
    priced.loc[free_mask, "has_pricing"] = True
    priced.loc[free_mask, "pricing_join_status"] = "free_model_zero_revenue"
    priced.loc[free_mask, "revenue_method"] = "free_model"

    output = priced.copy()
    output["pricing_snapshot_ts"] = pd.to_datetime(output["pricing_snapshot_ts"], errors="coerce", utc=True).dt.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return output[CONSERVATIVE_ECONOMICS_COLUMNS].sort_values(
        ["usage_date", "provider_slug", "model_permaslug"]
    ).reset_index(drop=True)


def blended_unit_price_series(prompt_prices: pd.Series, completion_prices: pd.Series) -> pd.Series:
    prompt = pd.to_numeric(prompt_prices, errors="coerce")
    completion = pd.to_numeric(completion_prices, errors="coerce")
    blended = (prompt * NO_SPLIT_PROMPT_SHARE) + (completion * NO_SPLIT_COMPLETION_SHARE)
    blended = blended.where(prompt.notna() & completion.notna(), prompt.where(prompt.notna(), completion))
    return blended


def summarize_economics_coverage(economics: pd.DataFrame) -> dict[str, object]:
    if economics.empty:
        return {
            "latest_data_date": None,
            "total_tokens": 0.0,
            "priced_tokens": 0.0,
            "split_tokens": 0.0,
            "unpriced_tokens": 0.0,
            "priced_token_coverage": 0.0,
            "split_token_coverage": 0.0,
            "unpriced_model_count": 0,
            "revenue_method_mix": {},
        }

    total_tokens = pd.to_numeric(economics["total_tokens"], errors="coerce").fillna(0)
    has_pricing = economics["has_pricing"].fillna(False).astype(bool)
    has_split = economics["has_split_tokens"].fillna(False).astype(bool)
    priced_tokens = float(total_tokens[has_pricing].sum())
    split_tokens = float(total_tokens[has_split].sum())
    total = float(total_tokens.sum())
    return {
        "latest_data_date": economics["usage_date"].dropna().astype(str).max() if economics["usage_date"].notna().any() else None,
        "total_tokens": total,
        "priced_tokens": priced_tokens,
        "split_tokens": split_tokens,
        "unpriced_tokens": float(total_tokens[~has_pricing].sum()),
        "priced_token_coverage": priced_tokens / total if total else 0.0,
        "split_token_coverage": split_tokens / total if total else 0.0,
        "unpriced_model_count": int(economics.loc[~has_pricing, "model_permaslug"].nunique()),
        "revenue_method_mix": economics["revenue_method"].value_counts(dropna=False).to_dict(),
    }
