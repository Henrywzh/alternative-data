from __future__ import annotations

from collections import defaultdict
from typing import Any

# As of 2026-08-06, opencode.ai's home page stopped nesting market/usage/
# users/leaderboard/country under {timeframe: [...]} (or {tier: {timeframe:
# [...]}}) and started returning a single flat list directly -- the
# per-item shape is unchanged, only the timeframe/tier grouping layer is
# gone. This is weekly-bucketed (confirmed against the live page's own
# JUN 12/JUN 19/... axis labels), not daily, so it's stored as a new "1W"
# timeframe rather than mislabeled as "1D". Tier is similarly collapsed to
# a single implicit "All Users" bucket, matching the dashboard's existing
# DEFAULT_TIER for the old shape's all-users tier.
_FLAT_SCHEMA_TIMEFRAME = "1W"
_FLAT_SCHEMA_TIER = "All Users"


def extract_market_share(stats_home: dict[str, Any], scraped_at: str) -> list[dict[str, Any]]:
    """Extract market share time series across all timeframes."""
    rows: list[dict[str, Any]] = []
    market_data = stats_home.get("market", {})
    if isinstance(market_data, list):
        market_data = {_FLAT_SCHEMA_TIMEFRAME: market_data}
    if not isinstance(market_data, dict):
        return rows

    for timeframe, item_list in market_data.items():
        if not isinstance(item_list, list):
            continue
        # Coarse timeframes (e.g. "ALL") can legitimately emit more than one
        # entry under the same "date" label (e.g. two distinct "APR" totals
        # with different author breakdowns). Track how many entries we've
        # already seen for this date so those rows get a stable, distinct key
        # instead of colliding and silently overwriting one another.
        date_occurrence: dict[Any, int] = defaultdict(int)
        for item in item_list:
            if not isinstance(item, dict):
                continue
            usage_date = item.get("date")
            occurrence_index = date_occurrence[usage_date]
            date_occurrence[usage_date] += 1
            total_tokens = item.get("total")
            authors = item.get("authors", [])
            if not isinstance(authors, list):
                continue

            for a in authors:
                if not isinstance(a, dict):
                    continue
                rows.append(
                    {
                        "timeframe": timeframe,
                        "usage_date": usage_date,
                        "date_occurrence": occurrence_index,
                        "author": a.get("author"),
                        "share_pct": a.get("share"),
                        "tokens_trillion": a.get("tokens"),
                        "total_tokens_trillion": total_tokens,
                        "scraped_at": scraped_at,
                    }
                )
    return rows


def extract_usage_daily(stats_home: dict[str, Any], scraped_at: str) -> list[dict[str, Any]]:
    """Extract model usage daily time series across user tiers."""
    rows: list[dict[str, Any]] = []
    usage_data = stats_home.get("usage", {})
    if isinstance(usage_data, list):
        usage_data = {_FLAT_SCHEMA_TIER: {_FLAT_SCHEMA_TIMEFRAME: usage_data}}
    if not isinstance(usage_data, dict):
        return rows

    for tier, timeframes in usage_data.items():
        if not isinstance(timeframes, dict):
            continue
        for tf, item_list in timeframes.items():
            if not isinstance(item_list, list):
                continue
            # See extract_market_share: coarse timeframes can repeat "date"
            # labels across genuinely distinct entries.
            date_occurrence: dict[Any, int] = defaultdict(int)
            for item in item_list:
                if not isinstance(item, dict):
                    continue
                usage_date = item.get("date")
                occurrence_index = date_occurrence[usage_date]
                date_occurrence[usage_date] += 1
                segments = item.get("segments", [])
                if not isinstance(segments, list):
                    continue
                for seg in segments:
                    if not isinstance(seg, dict):
                        continue
                    rows.append(
                        {
                            "user_tier": tier,
                            "timeframe": tf,
                            "usage_date": usage_date,
                            "date_occurrence": occurrence_index,
                            "model_slug": seg.get("model"),
                            "token_value": seg.get("value"),
                            "scraped_at": scraped_at,
                        }
                    )
    return rows


def extract_users_daily(stats_home: dict[str, Any], scraped_at: str) -> list[dict[str, Any]]:
    """Extract model daily active users time series across user tiers."""
    rows: list[dict[str, Any]] = []
    users_data = stats_home.get("users", {})
    if isinstance(users_data, list):
        users_data = {_FLAT_SCHEMA_TIER: {_FLAT_SCHEMA_TIMEFRAME: users_data}}
    if not isinstance(users_data, dict):
        return rows

    for tier, timeframes in users_data.items():
        if not isinstance(timeframes, dict):
            continue
        for tf, item_list in timeframes.items():
            if not isinstance(item_list, list):
                continue
            # See extract_market_share: coarse timeframes can repeat "date"
            # labels across genuinely distinct entries.
            date_occurrence: dict[Any, int] = defaultdict(int)
            for item in item_list:
                if not isinstance(item, dict):
                    continue
                usage_date = item.get("date")
                occurrence_index = date_occurrence[usage_date]
                date_occurrence[usage_date] += 1
                segments = item.get("segments", [])
                if not isinstance(segments, list):
                    continue
                for seg in segments:
                    if not isinstance(seg, dict):
                        continue
                    rows.append(
                        {
                            "user_tier": tier,
                            "timeframe": tf,
                            "usage_date": usage_date,
                            "date_occurrence": occurrence_index,
                            "model_slug": seg.get("model"),
                            "active_users": seg.get("value"),
                            "scraped_at": scraped_at,
                        }
                    )
    return rows


def extract_leaderboard(stats_home: dict[str, Any], scraped_at: str) -> list[dict[str, Any]]:
    """Extract model leaderboard ranks and token volume across user tiers."""
    rows: list[dict[str, Any]] = []
    lb_data = stats_home.get("leaderboard", {})
    if isinstance(lb_data, list):
        lb_data = {_FLAT_SCHEMA_TIER: {_FLAT_SCHEMA_TIMEFRAME: lb_data}}
    if not isinstance(lb_data, dict):
        return rows

    snapshot_date = scraped_at.split("T", 1)[0]
    for tier, timeframes in lb_data.items():
        if not isinstance(timeframes, dict):
            continue
        for tf, item_list in timeframes.items():
            if not isinstance(item_list, list):
                continue
            for item in item_list:
                if not isinstance(item, dict):
                    continue
                rows.append(
                    {
                        "snapshot_date": snapshot_date,
                        "user_tier": tier,
                        "timeframe": tf,
                        "rank": item.get("rank"),
                        "model_slug": item.get("model"),
                        "provider": item.get("provider"),
                        "author": item.get("author"),
                        "tokens": item.get("tokens"),
                        "rank_change": item.get("change"),
                        "scraped_at": scraped_at,
                    }
                )
    return rows


def extract_country_usage(stats_home: dict[str, Any], scraped_at: str) -> list[dict[str, Any]]:
    """Extract country-level usage breakdown."""
    rows: list[dict[str, Any]] = []
    country_data = stats_home.get("country", {})
    if isinstance(country_data, list):
        country_data = {_FLAT_SCHEMA_TIMEFRAME: country_data}
    if not isinstance(country_data, dict):
        return rows

    snapshot_date = scraped_at.split("T", 1)[0]
    for tf, item_list in country_data.items():
        if not isinstance(item_list, list):
            continue
        for item in item_list:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "snapshot_date": snapshot_date,
                    "timeframe": tf,
                    "country_code": item.get("country"),
                    "continent": item.get("continent"),
                    "tokens_trillion": item.get("tokens"),
                    "share_pct": item.get("share"),
                    "rank": item.get("rank"),
                    "scraped_at": scraped_at,
                }
            )
    return rows


def extract_model_catalog(catalog: dict[str, Any], scraped_at: str) -> list[dict[str, Any]]:
    """Extract model catalog records."""
    rows: list[dict[str, Any]] = []
    models = catalog.get("models", [])
    if not isinstance(models, list):
        return rows

    snapshot_date = scraped_at.split("T", 1)[0]
    for m in models:
        if not isinstance(m, dict):
            continue
        limit = m.get("limit", {}) if isinstance(m.get("limit"), dict) else {}
        cost = m.get("cost", {}) if isinstance(m.get("cost"), dict) else {}
        modalities = m.get("modalities", {}) if isinstance(m.get("modalities"), dict) else {}

        rows.append(
            {
                "snapshot_date": snapshot_date,
                "model_id": m.get("id"),
                "lab": m.get("lab"),
                "slug": m.get("slug"),
                "name": m.get("name"),
                "description": m.get("description"),
                "family": m.get("family"),
                "release_date": m.get("releaseDate"),
                "last_updated": m.get("lastUpdated"),
                "context_limit": limit.get("context"),
                "output_limit": limit.get("output"),
                "input_modalities": ",".join(modalities.get("input", [])) if isinstance(modalities.get("input"), list) else "",
                "output_modalities": ",".join(modalities.get("output", [])) if isinstance(modalities.get("output"), list) else "",
                "open_weights": bool(m.get("openWeights")),
                "reasoning": bool(m.get("reasoning")),
                "tool_call": bool(m.get("toolCall")),
                "attachment": bool(m.get("attachment")),
                "temperature": bool(m.get("temperature")),
                "input_cost_per_m": cost.get("input"),
                "output_cost_per_m": cost.get("output"),
                "cache_read_cost_per_m": cost.get("cacheRead"),
                "cache_write_cost_per_m": cost.get("cacheWrite"),
                "scraped_at": scraped_at,
            }
        )
    return rows


def extract_benchmarks(catalog: dict[str, Any], scraped_at: str) -> list[dict[str, Any]]:
    """Extract model benchmark evaluation scores."""
    rows: list[dict[str, Any]] = []
    models = catalog.get("models", [])
    if not isinstance(models, list):
        return rows

    snapshot_date = scraped_at.split("T", 1)[0]
    for m in models:
        if not isinstance(m, dict):
            continue
        model_id = m.get("id")
        model_slug = m.get("slug")
        benchmarks = m.get("benchmarks", [])
        if not isinstance(benchmarks, list):
            continue
        for b in benchmarks:
            if not isinstance(b, dict):
                continue
            rows.append(
                {
                    "snapshot_date": snapshot_date,
                    "model_id": model_id,
                    "model_slug": model_slug,
                    "benchmark_name": b.get("name"),
                    "score": b.get("score"),
                    "metric": b.get("metric"),
                    "harness": b.get("harness"),
                    "variant": b.get("variant"),
                    "dataset": b.get("dataset"),
                    "version": b.get("version"),
                    "source_url": b.get("source"),
                    "scraped_at": scraped_at,
                }
            )
    return rows


def extract_model_deepdive(model_payload: dict[str, Any], scraped_at: str) -> dict[str, Any]:
    """Extract summary metrics and token mix for a single model deepdive."""
    totals = model_payload.get("totals", {}) if isinstance(model_payload.get("totals"), dict) else {}
    token_mix = model_payload.get("tokenMix", []) if isinstance(model_payload.get("tokenMix"), list) else []

    mix_map = {}
    for item in token_mix:
        if isinstance(item, dict) and item.get("label"):
            mix_map[item["label"].lower()] = item.get("tokens")

    snapshot_date = scraped_at.split("T", 1)[0]
    return {
        "snapshot_date": snapshot_date,
        "model_slug": model_payload.get("slug"),
        "provider": model_payload.get("provider"),
        "author": model_payload.get("author"),
        "rank": model_payload.get("rank"),
        "previous_rank": model_payload.get("previousRank"),
        "total_models": model_payload.get("totalModels"),
        "token_share_pct": model_payload.get("tokenShare"),
        "token_change": model_payload.get("tokenChange"),
        "sessions": totals.get("sessions"),
        "unique_users": totals.get("uniqueUsers"),
        "tokens_total": totals.get("tokens"),
        "cost_total_usd": totals.get("cost"),
        "tokens_per_session": totals.get("tokensPerSession"),
        "cost_per_session_usd": totals.get("costPerSession"),
        "cost_per_million_usd": totals.get("costPerMillion"),
        "cache_ratio_pct": totals.get("cacheRatio"),
        "input_tokens": mix_map.get("input"),
        "output_tokens": mix_map.get("output"),
        "reasoning_tokens": mix_map.get("reasoning"),
        "cached_tokens": mix_map.get("cached"),
        "scraped_at": scraped_at,
    }
