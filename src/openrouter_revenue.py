from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from pricing_model_aliases import canonical_provider_slug, clean_slug, derive_provider_prefix, generate_candidate_aliases


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

# Historical OpenRouter activity predates the first complete pricing snapshots
# for many providers.  An exact route's first later paid price may therefore be
# used as an explicitly labelled historical proxy.  The fill is intentionally
# route-exact and never falls back to a provider/global median; routes with no
# later paid price remain unresolved.


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


_MODEL_STATS_COLUMNS = [
    "canonical_model_key",
    "provider_prefix",
    "pricing_snapshot_ts",
    "pricing_prompt",
    "pricing_completion",
    "pricing_blended",
]


def _empty_price_context() -> PriceContext:
    return PriceContext(
        model_stats=pd.DataFrame(columns=_MODEL_STATS_COLUMNS),
        alias_to_model_key={},
        provider_lookup={},
        global_stats=None,
        latest_snapshot_ts=None,
    )


def _prepare_price_rows(pricing: pd.DataFrame) -> pd.DataFrame:
    """Resolve per-row model identity and pricing fields.

    Every derived column here depends only on that row's own values, never on
    which other rows are present - so this can be computed once over any
    pricing frame (e.g. a whole history) and safely reused for any date
    subset of it afterward. Any extra columns on the input (e.g. a caller's
    ``_pricing_date`` cutoff marker) pass through untouched.
    """
    prepared = pricing.copy()
    prepared["model_id"] = _clean_model_id(prepared["model_id"])
    prepared["canonical_slug"] = _clean_model_id(_optional_series(prepared, "canonical_slug"))
    prepared["provider_prefix"] = _clean_model_id(_optional_series(prepared, "provider_prefix"))
    prepared["provider_prefix"] = prepared["provider_prefix"].fillna(
        prepared["canonical_slug"].map(derive_provider_prefix)
    ).fillna(prepared["model_id"].map(derive_provider_prefix))
    prepared["provider_prefix"] = prepared["provider_prefix"].map(canonical_provider_slug)
    prepared["snapshot_ts"] = _to_datetime(prepared["snapshot_ts"], utc=True)
    prepared["pricing_prompt"] = pd.to_numeric(prepared["pricing_prompt"], errors="coerce")
    prepared["pricing_completion"] = pd.to_numeric(prepared["pricing_completion"], errors="coerce")
    prepared = prepared.dropna(subset=["model_id", "snapshot_ts"]).copy()
    key_source = prepared["canonical_slug"].where(prepared["canonical_slug"].notna(), prepared["model_id"])
    preserve_free = prepared["model_id"].astype(str).str.endswith(":free")
    key_pairs = list(zip(key_source, preserve_free))
    resolved_keys = {
        pair: canonical_model_key(pair[0], preserve_free=pair[1]) for pair in set(key_pairs)
    }
    prepared["canonical_model_key"] = [resolved_keys[pair] for pair in key_pairs]
    prepared["pricing_blended"] = blended_unit_price_series(prepared["pricing_prompt"], prepared["pricing_completion"])
    prepared = prepared.dropna(subset=["canonical_model_key"]).copy()
    return prepared


def _alias_map_from_rows(prepared: pd.DataFrame) -> dict[str, str]:
    """Resolve the alias->canonical-key map from unique identity triples.

    Ties (the same alias string produced by two different models) are broken
    by each triple's own candidate-list position, and - among equal
    positions - by which triple appears first in ``prepared``'s row order.
    Callers that need this for many nested, chronologically-growing subsets
    of the same pricing frame (see ``_price_contexts_by_cutoff``) must feed
    rows in a chronological sweep to get an identical result to calling this
    fresh on each subset, since the tie-break is order-sensitive.
    """
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
    return alias_to_model_key


def _provider_and_global_stats(model_stats: pd.DataFrame) -> tuple[dict[str, dict[str, float]], dict[str, float] | None]:
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
    return provider_lookup, global_stats


def _aggregate_price_context(prepared: pd.DataFrame) -> PriceContext:
    if prepared.empty:
        return _empty_price_context()

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
    alias_to_model_key = _alias_map_from_rows(prepared)
    provider_lookup, global_stats = _provider_and_global_stats(model_stats)
    latest_snapshot_ts = prepared["snapshot_ts"].max() if prepared["snapshot_ts"].notna().any() else None
    return PriceContext(
        model_stats=model_stats,
        alias_to_model_key=alias_to_model_key,
        provider_lookup=provider_lookup,
        global_stats=global_stats,
        latest_snapshot_ts=latest_snapshot_ts,
    )


def build_price_context(pricing: pd.DataFrame) -> PriceContext:
    if pricing.empty:
        return _empty_price_context()
    return _aggregate_price_context(_prepare_price_rows(pricing))


def _price_contexts_by_cutoff(pricing_with_dates: pd.DataFrame) -> dict[pd.Timestamp, PriceContext] | None:
    """Build a PriceContext for every distinct ``_pricing_date`` cutoff in one pass.

    ``build_price_context`` recomputed a full alias map and per-model median
    from scratch for every cutoff, over that cutoff's *entire* cumulative
    eligible-pricing set - cost that grows with both the number of cutoffs
    and the size of pricing history, i.e. roughly quadratically as more time
    passes. This computes the same PriceContext for every cutoff using each
    pricing row exactly once:

    - Per-model running median/max/first-provider via pandas' own expanding/
      cummax/groupby machinery (each row visited once, not once per cutoff
      it happens to be eligible for).
    - A single as-of reconstruction (``merge_asof``) turns "per-model stats
      as of cutoff C" into a lookup over a small models x cutoffs table
      instead of a fresh groupby over the full, ever-growing pricing rows.
    - provider_lookup/global_stats are still recomputed per cutoff, but over
      that small (one row per model) table, not the raw pricing rows.
    - The alias map is the one piece with no numeric pandas equivalent; it's
      swept forward once, snapshotting a dict copy at each cutoff boundary.

    Returns None if pricing rows aren't in chronological order (by
    ``_pricing_date``, in the frame's current row order) - the whole
    approach depends on "processing cutoffs in ascending order" matching
    "the row order build_price_context would see for any date subset",
    which only holds when the input is already date-ordered. The caller
    should fall back to calling build_price_context per cutoff in that case.
    """
    if not pricing_with_dates["_pricing_date"].is_monotonic_increasing:
        return None

    prepared = _prepare_price_rows(pricing_with_dates)
    prepared = prepared.dropna(subset=["_pricing_date"])
    if prepared.empty or not prepared["_pricing_date"].is_monotonic_increasing:
        # A row-prep drop (e.g. bad model_id) could theoretically disturb
        # ordering only if the input already wasn't safe; re-check defensively.
        return None if not prepared.empty else {}

    sorted_by_model = prepared.sort_values("canonical_model_key", kind="stable")
    grouped = sorted_by_model.groupby("canonical_model_key", sort=False)
    sorted_by_model = sorted_by_model.assign(
        _exp_prompt=grouped["pricing_prompt"].expanding().median().reset_index(level=0, drop=True),
        _exp_completion=grouped["pricing_completion"].expanding().median().reset_index(level=0, drop=True),
        _exp_blended=grouped["pricing_blended"].expanding().median().reset_index(level=0, drop=True),
        _cummax_ts=grouped["snapshot_ts"].cummax(),
        _first_provider=grouped["provider_prefix"].transform("first"),
    )
    per_model_cols = ["_exp_prompt", "_exp_completion", "_exp_blended", "_cummax_ts", "_first_provider"]
    enriched = prepared.join(sorted_by_model[per_model_cols]).sort_values("_pricing_date", kind="stable")

    distinct_dates = sorted(prepared["_pricing_date"].unique())
    model_keys = prepared["canonical_model_key"].unique()
    left = pd.MultiIndex.from_product(
        [model_keys, distinct_dates], names=["canonical_model_key", "_pricing_date"]
    ).to_frame(index=False).sort_values("_pricing_date", kind="stable")
    merged = pd.merge_asof(
        left,
        enriched[["_pricing_date", "canonical_model_key", *per_model_cols]],
        on="_pricing_date",
        by="canonical_model_key",
        direction="backward",
    )

    # Alias map: a single forward sweep over cutoffs, snapshotting a dict
    # copy after each cutoff's rows are folded in (see _alias_map_from_rows
    # docstring for why row order must stay chronological here).
    alias_to_model_key: dict[str, str] = {}
    alias_priority: dict[str, int] = {}
    seen_triples: set[tuple[object, object, object]] = set()
    alias_by_cutoff: dict[pd.Timestamp, dict[str, str]] = {}
    for pricing_date, group in prepared.groupby("_pricing_date", sort=False):
        for row in group[["model_id", "canonical_slug", "canonical_model_key"]].drop_duplicates().itertuples(index=False):
            triple = (row.model_id, row.canonical_slug, row.canonical_model_key)
            if triple in seen_triples:
                continue
            seen_triples.add(triple)
            model_id, canonical_slug, model_key = triple
            if pd.isna(model_id) or pd.isna(model_key):
                continue
            if str(model_id).endswith(":free"):
                aliases = [str(model_id)]
            else:
                aliases = []
                for raw in (model_id, canonical_slug, model_key):
                    for alias in generate_candidate_aliases(raw):
                        if alias not in aliases:
                            aliases.append(alias)
            for priority, alias in enumerate(aliases):
                if alias not in alias_to_model_key or priority < alias_priority[alias]:
                    alias_to_model_key[alias] = str(model_key)
                    alias_priority[alias] = priority
        alias_by_cutoff[pricing_date] = dict(alias_to_model_key)

    # provider_lookup/global_stats ("median of qualifying models' own medians",
    # per cutoff) is itself just a groupby/median - the same shape of problem
    # as model_stats above, just one level up. Compute it for every cutoff at
    # once instead of once per cutoff: filter to the same "qualifies as a
    # fallback price" rows _provider_and_global_stats would use
    # (pricing_blended > 0), then group by (cutoff, provider) and by cutoff.
    qualifying = merged[merged["_cummax_ts"].notna() & (merged["_exp_blended"] > 0)]
    provider_medians = (
        qualifying.groupby(["_pricing_date", "_first_provider"], as_index=False)
        .agg(
            pricing_prompt=("_exp_prompt", "median"),
            pricing_completion=("_exp_completion", "median"),
            pricing_blended=("_exp_blended", "median"),
        )
        .dropna(subset=["pricing_blended"])
    )
    provider_lookup_by_cutoff: dict[pd.Timestamp, dict[str, dict[str, float]]] = {d: {} for d in distinct_dates}
    for row in provider_medians.itertuples(index=False):
        provider_lookup_by_cutoff[row[0]][row[1]] = {
            "pricing_prompt": float(row.pricing_prompt) if pd.notna(row.pricing_prompt) else np.nan,
            "pricing_completion": float(row.pricing_completion) if pd.notna(row.pricing_completion) else np.nan,
            "pricing_blended": float(row.pricing_blended),
        }
    global_medians = qualifying.groupby("_pricing_date", as_index=False).agg(
        pricing_prompt=("_exp_prompt", "median"),
        pricing_completion=("_exp_completion", "median"),
        pricing_blended=("_exp_blended", "median"),
    )
    global_stats_by_cutoff: dict[pd.Timestamp, dict[str, float] | None] = {d: None for d in distinct_dates}
    for row in global_medians.itertuples(index=False):
        global_stats_by_cutoff[row[0]] = {
            "pricing_prompt": float(row.pricing_prompt) if pd.notna(row.pricing_prompt) else np.nan,
            "pricing_completion": float(row.pricing_completion) if pd.notna(row.pricing_completion) else np.nan,
            "pricing_blended": float(row.pricing_blended),
        }

    contexts: dict[pd.Timestamp, PriceContext] = {}
    for cutoff in distinct_dates:
        sub = merged[(merged["_pricing_date"] == cutoff) & merged["_cummax_ts"].notna()]
        model_stats = sub.rename(
            columns={
                "_first_provider": "provider_prefix",
                "_cummax_ts": "pricing_snapshot_ts",
                "_exp_prompt": "pricing_prompt",
                "_exp_completion": "pricing_completion",
                "_exp_blended": "pricing_blended",
            }
        )[_MODEL_STATS_COLUMNS].sort_values(["provider_prefix", "canonical_model_key"], na_position="last").reset_index(drop=True)
        latest_snapshot_ts = model_stats["pricing_snapshot_ts"].max() if not model_stats.empty else None
        contexts[cutoff] = PriceContext(
            model_stats=model_stats,
            alias_to_model_key=alias_by_cutoff[cutoff],
            provider_lookup=provider_lookup_by_cutoff[cutoff],
            global_stats=global_stats_by_cutoff[cutoff],
            latest_snapshot_ts=latest_snapshot_ts,
        )
    return contexts


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
    unique_slugs = estimated["model_permaslug"].dropna().unique()
    resolved_lookup = {
        slug: resolve_model_key(slug, context.alias_to_model_key, slug_strategy=slug_strategy)
        for slug in unique_slugs
    }
    estimated["matched_model_key"] = estimated["model_permaslug"].map(resolved_lookup)

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
    estimated["provider_slug"] = estimated["provider_slug"].map(canonical_provider_slug)
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
    # As-of pricing only actually changes on the (typically much sparser) set of
    # dates a new snapshot was published, not on every usage date. Bucket usage
    # dates by that cutoff so the price context - which does real work (alias
    # generation, groupby/median stats) - is resolved once per distinct pricing
    # state instead of once per usage date.
    distinct_pricing_dates = pd.DatetimeIndex(sorted(pricing_with_dates["_pricing_date"].dropna().unique()))

    def _cutoff_for(usage_date: pd.Timestamp) -> object:
        if pd.isna(usage_date):
            return None
        position = distinct_pricing_dates.searchsorted(usage_date, side="right") - 1
        if position < 0:
            return "__earliest__" if pd.notna(earliest_pricing_date) else "__empty__"
        return distinct_pricing_dates[position]

    # Try building every cutoff's PriceContext in one linear-ish pass (see
    # _price_contexts_by_cutoff). This only holds when pricing rows are
    # already date-ordered; fall back to resolving each cutoff independently
    # (slower, but always correct) otherwise.
    batch_contexts = _price_contexts_by_cutoff(pricing_with_dates)
    context_cache: dict[object, PriceContext] = {}
    if batch_contexts is not None and len(distinct_pricing_dates):
        context_cache["__earliest__"] = batch_contexts[distinct_pricing_dates[0]]
        context_cache[None] = batch_contexts[distinct_pricing_dates[-1]]
        for cutoff_date in distinct_pricing_dates:
            context_cache[cutoff_date] = batch_contexts[cutoff_date]
    if "__empty__" not in context_cache:
        context_cache["__empty__"] = _empty_price_context()
    if None not in context_cache:
        # No usable pricing rows at all (or the batch path was unavailable and
        # there are no distinct dates to seed it): every cutoff is empty.
        context_cache[None] = build_price_context(pricing_with_dates.drop(columns="_pricing_date"))

    def _context_for_cutoff(cutoff: object) -> PriceContext:
        if cutoff in context_cache:
            return context_cache[cutoff]
        if cutoff == "__earliest__":
            eligible_pricing = pricing_with_dates[
                pricing_with_dates["_pricing_date"] == earliest_pricing_date
            ].drop(columns="_pricing_date")
        else:
            eligible_pricing = pricing_with_dates[pricing_with_dates["_pricing_date"] <= cutoff].drop(
                columns="_pricing_date"
            )
        context = build_price_context(eligible_pricing)
        context_cache[cutoff] = context
        return context

    # Many usage dates share the same as-of cutoff (that's the entire point of
    # the bucketing above), so grouping by the cutoff itself - rather than by
    # the raw usage date - collapses those into one _estimate_with_context
    # call instead of redundantly repeating it once per usage date that maps
    # to the same context.
    # _cutoff_for's `None` result (missing usage_date) must not travel through
    # Series.map() as a bare None: pandas' result-dtype inference can coerce a
    # lone/uniform None into float NaN, which then fails `is/== None` lookups
    # against context_cache. Use an explicit string sentinel instead, the same
    # way "__earliest__"/"__empty__" already sidestep this.
    _NO_USAGE_DATE_KEY = "__no_usage_date__"
    estimated["_cutoff_key"] = estimated["_usage_date"].map(
        lambda usage_date: _NO_USAGE_DATE_KEY if pd.isna(usage_date) else _cutoff_for(usage_date)
    )
    resolved_frames: list[pd.DataFrame] = []
    for cutoff_key, group in estimated.groupby("_cutoff_key", dropna=False, sort=False):
        context = _context_for_cutoff(None if cutoff_key == _NO_USAGE_DATE_KEY else cutoff_key)
        group = group.drop(columns=["_usage_date", "_cutoff_key"])
        resolved_frames.append(
            _estimate_with_context(
                group,
                context,
                slug_strategy=slug_strategy,
                pricing_strategy=pricing_strategy,
            )
        )

    return (
        pd.concat(resolved_frames, ignore_index=True)
        if resolved_frames
        else estimated.drop(columns=["_usage_date", "_cutoff_key"])
    )


def xiaomi_mimo_backpricing_hazard(frame: pd.DataFrame) -> pd.Series:
    """Flag Xiaomi rows whose later model identity must not be priced backward."""
    if frame.empty:
        return pd.Series(dtype=bool, index=frame.index)
    usage_date = pd.to_datetime(frame.get("usage_date"), errors="coerce").dt.strftime("%Y-%m-%d")
    provider = frame.get(
        "entity_id",
        frame.get("provider_slug", pd.Series("", index=frame.index)),
    ).astype("string").str.lower()
    model = frame.get("model_permaslug", pd.Series("", index=frame.index)).astype("string").str.lower()
    return (
        provider.eq("xiaomi")
        & usage_date.between("2026-03-19", "2026-04-05")
        & model.str.startswith("xiaomi/mimo-v2-", na=False)
    )


def build_provider_revenue_estimates(provider_activity: pd.DataFrame, pricing: pd.DataFrame) -> pd.DataFrame:
    """Build the dashboard estimate, including documented historical price backcasts."""
    if provider_activity.empty:
        return provider_activity.copy()
    activity = provider_activity[~xiaomi_mimo_backpricing_hazard(provider_activity)].copy()
    return estimate_usage_revenue(
        activity,
        pricing,
        slug_strategy="canonical",
        pricing_strategy="provider_fallback",
    )


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
    usage["provider_slug"] = usage["provider_slug"].map(canonical_provider_slug)
    usage["provider_name"] = entity_name.astype("string").fillna(usage["provider_slug"])
    usage.loc[usage["provider_slug"].eq("meta"), "provider_name"] = "Meta"
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
    prepared["provider_prefix"] = prepared["provider_prefix"].map(canonical_provider_slug)
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
    unique_usage_slugs = usage["model_permaslug"].dropna().unique()
    candidates_lookup = {
        slug: [alias for alias in generate_candidate_aliases(slug) if alias in pricing_keys]
        for slug in unique_usage_slugs
    }

    def _candidates_or_fallback(slug: object) -> list[str]:
        candidates = candidates_lookup.get(slug) or []
        return candidates if candidates else [str(slug)]

    # A row with no model_permaslug has no candidates at all (matching the
    # historical behavior: such rows never appeared in `expanded` below).
    usage_with_slug = usage[usage["model_permaslug"].notna()].copy()
    if usage_with_slug.empty:
        for column in ["pricing_snapshot_ts", "pricing_prompt", "pricing_completion", "matched_model_id"]:
            usage[column] = pd.NA
        return usage.drop(columns=["_usage_row_id", "_usage_date"])

    usage_with_slug["pricing_lookup_key"] = usage_with_slug["model_permaslug"].map(_candidates_or_fallback)
    expanded = usage_with_slug.explode("pricing_lookup_key", ignore_index=True)
    expanded["usage_alias_priority"] = expanded.groupby("_usage_row_id").cumcount()

    price_frame = aliases[
        ["pricing_lookup_key", "snapshot_ts", "pricing_prompt", "pricing_completion", "model_id", "alias_priority"]
    ].rename(columns={"snapshot_ts": "pricing_snapshot_ts", "model_id": "matched_model_id"})

    # Two different pricing model_ids can alias to the same pricing_lookup_key
    # at the exact same snapshot_ts with different prices (e.g. a plain slug
    # like "provider/model" and a dated variant "provider/model-20260101" both
    # stripping down to the same lookup key). merge_asof(direction="backward")
    # resolves an exact tie on the `on` value by picking the LAST matching row
    # in `right`'s current order, so sort alias_priority descending within
    # each timestamp: the lowest (most exact) priority ends up last and wins -
    # the same "lowest alias_priority wins" rule build_price_context and
    # _forward_fill_target_route_pricing already apply for this exact kind of
    # ambiguity.
    expanded_sorted = expanded.sort_values("_usage_date", kind="stable")
    price_frame_sorted = price_frame.sort_values(
        ["pricing_snapshot_ts", "alias_priority"], ascending=[True, False], kind="stable"
    ).drop(columns="alias_priority")
    joined = pd.merge_asof(
        expanded_sorted,
        price_frame_sorted,
        left_on="_usage_date",
        right_on="pricing_snapshot_ts",
        by="pricing_lookup_key",
        direction="backward",
    )

    joined["_price_rank"] = np.where(joined["pricing_snapshot_ts"].notna(), 0, 1)
    joined = joined.sort_values(["_usage_row_id", "_price_rank", "usage_alias_priority"]).drop_duplicates(
        "_usage_row_id", keep="first"
    )
    return joined.drop(
        columns=["_usage_row_id", "_usage_date", "usage_alias_priority", "pricing_lookup_key"], errors="ignore"
    )


def _forward_fill_target_route_pricing(priced: pd.DataFrame, pricing: pd.DataFrame) -> pd.DataFrame:
    """Fill unresolved model routes from their first later paid price.

    This is deliberately route-exact across all providers.  It does not use a
    provider or global median, and it leaves routes with no positive future
    price unresolved.  The future snapshot is retained in the output so the
    resulting revenue estimate is auditable as a historical proxy.
    """
    if priced.empty or pricing.empty:
        return priced
    aliases = _prepare_pricing_aliases(pricing)
    if aliases.empty:
        return priced
    aliases["pricing_prompt"] = pd.to_numeric(aliases["pricing_prompt"], errors="coerce")
    aliases["pricing_completion"] = pd.to_numeric(aliases["pricing_completion"], errors="coerce")
    aliases = aliases.loc[
        aliases["pricing_prompt"].gt(0) & aliases["pricing_completion"].gt(0)
    ].copy()
    if aliases.empty:
        return priced

    by_alias = {
        key: group.sort_values("snapshot_ts", kind="stable")
        for key, group in aliases.groupby("pricing_lookup_key", sort=False)
    }
    usage_dates = pd.to_datetime(priced["usage_date"], errors="coerce", utc=True).dt.normalize()
    model_ids = priced["model_permaslug"].astype("string")
    identity_hazard = xiaomi_mimo_backpricing_hazard(priced)
    needs_fill = (
        usage_dates.notna()
        & priced["pricing_snapshot_ts"].isna()
        & ~model_ids.str.endswith(":free", na=False)
        & ~identity_hazard
    )
    if not needs_fill.any():
        return priced

    result = priced.copy()
    # Candidate-alias generation and the future-price concat/sort only depend
    # on model_id, not on the individual row's usage_date - and many rows
    # needing a fill share the same model_id. Build each model's combined,
    # priority-sorted candidate table once, then resolve every row for that
    # model with a single vectorized as-of lookup instead of one concat+sort
    # per row.
    candidate_tables: dict[str, pd.DataFrame | None] = {}

    def _candidates_for_model(model_id: str) -> pd.DataFrame | None:
        if model_id in candidate_tables:
            return candidate_tables[model_id]
        pieces = []
        for priority, alias in enumerate(generate_candidate_aliases(model_id)):
            group = by_alias.get(alias)
            if group is None:
                continue
            tagged = group.copy()
            tagged["_alias_priority"] = priority
            pieces.append(tagged)
        table = None
        if pieces:
            table = pd.concat(pieces, ignore_index=True).sort_values(
                ["snapshot_ts", "_alias_priority"], kind="stable"
            ).reset_index(drop=True)
        candidate_tables[model_id] = table
        return table

    fill_frame = pd.DataFrame(
        {"model_id": model_ids, "usage_date": usage_dates}, index=priced.index
    ).loc[needs_fill]
    for model_id, group in fill_frame.groupby("model_id", sort=False):
        table = _candidates_for_model(model_id)
        if table is None or table.empty:
            continue
        # First candidate strictly after usage_date, in the same
        # [snapshot_ts, alias_priority] order the row-by-row version selected
        # its iloc[0] from - side="right" on ties lands on the first row past
        # every equal-or-earlier snapshot_ts, i.e. strictly greater.
        positions = table["snapshot_ts"].searchsorted(group["usage_date"], side="right")
        valid = positions < len(table)
        if not valid.any():
            continue
        matched_index = group.index[valid]
        selected = table.iloc[positions[valid]]
        result.loc[matched_index, "pricing_snapshot_ts"] = selected["snapshot_ts"].to_numpy()
        result.loc[matched_index, "pricing_prompt"] = selected["pricing_prompt"].to_numpy()
        result.loc[matched_index, "pricing_completion"] = selected["pricing_completion"].to_numpy()
        result.loc[matched_index, "pricing_join_status"] = "historical_route_price_fill"
    return result


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

    priced["pricing_join_status"] = "unresolved_missing_pricing"
    priced = _forward_fill_target_route_pricing(priced, pricing)
    historical_fill = priced["pricing_join_status"].astype("string").eq(
        "historical_route_price_fill"
    )

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
    priced.loc[historical_fill & has_pricing, "pricing_join_status"] = "historical_route_price_fill"
    priced.loc[priced["model_permaslug"].eq("Others"), "pricing_join_status"] = "synthetic_unpriced"
    priced.loc[priced["model_permaslug"].eq("Others"), "estimated_revenue"] = np.nan
    priced["revenue_method"] = "unpriced"
    priced.loc[has_pricing & has_split & priced["split_source"].eq("source"), "revenue_method"] = "exact_split_priced"
    priced.loc[has_pricing & has_split & priced["split_source"].eq("model_activity"), "revenue_method"] = "model_split_inferred"
    priced.loc[blended_priced, "revenue_method"] = "model_blended_no_split"
    priced.loc[historical_fill & has_pricing & has_split & priced["split_source"].eq("source"), "revenue_method"] = "historical_exact_split_priced"
    priced.loc[historical_fill & has_pricing & has_split & priced["split_source"].eq("model_activity"), "revenue_method"] = "historical_model_split_inferred"
    priced.loc[historical_fill & blended_priced, "revenue_method"] = "historical_model_blended_no_split"
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
