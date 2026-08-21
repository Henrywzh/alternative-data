"""Deterministic resolution of Artificial Analysis models to OpenRouter routes.

Every frontier release blanks part of the SOTA cohort until a human edits
``config/openrouter_capability_map.json`` by hand.  The curated map stays
authoritative -- it is the only layer allowed to make a judgement call -- but
a model absent from it no longer has to wait for that edit: this module
resolves it from the two committed inputs (the AA snapshot and the OpenRouter
catalog) by a fixed, auditable rule, or declines and says why.

The rules are deliberately conservative.  Matching is exact after
normalization, never fuzzy; an ambiguous stripped key resolves to nothing
rather than to a guess.  Declining is a coverage gap the guard reports, and a
coverage gap is always preferable to a wrong family assignment, which would
silently corrupt a published price index.

Design: docs/openrouter-capability-self-healing-design.md sections 5.1-5.3.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Mapping

import pandas as pd


DATE_SUFFIX = re.compile(r"[-_:]?\d{8}$")

# Reasoning-effort tiers are stripped only in tier B, and only from both sides
# at once.  One-sided stripping would match AA "qwen3-8-max" to an OpenRouter
# route that genuinely is a different, non-max model.
EFFORT_TIERS = frozenset({"high", "xhigh", "medium", "low", "max", "min"})

# Route qualifiers never distinguish one model from another, so they are
# dropped in both tiers.
ROUTE_VARIANTS = frozenset(
    {"free", "batch", "preview", "beta", "alpha", "latest", "stable", "exp", "experimental", "fast"}
)

# AA creator slugs and OpenRouter prefixes disagree for exactly the frontier
# labs. This table changes only when a NEW lab starts publishing frontier
# models -- rare, and precisely what the guard reports on day one with an
# actionable message rather than resolving to something wrong.
CREATOR_ALIASES: dict[str, str] = {
    "xai": "x-ai",
    "kimi": "moonshotai",
    "alibaba": "qwen",
    "zai": "z-ai",
    "zhipu": "z-ai",
    "meta": "meta-llama",
    "mistral": "mistralai",
    "bytedance": "bytedance-seed",
    "stepfun": "stepfun-ai",
}

RESOLVER_EXACT = "resolver_exact_match"
RESOLVER_STRIPPED = "resolver_stripped_match"
UNRESOLVED_AMBIGUOUS = "unresolved_ambiguous_stripped_key"
UNRESOLVED_NO_ROUTE = "unresolved_no_catalog_route"
UNRESOLVED_NO_PREFIX = "unresolved_unknown_creator_prefix"


def normalize_slug(slug: object, *, strip_tiers: bool = False) -> str:
    """Canonical key: lowercase, unify separators, drop dates and qualifiers.

    ``grok-4-6``, ``grok-4.6``, ``grok-4.6-20260810`` and ``grok-4.6:free``
    all collapse to ``grok-4-6``.
    """
    if slug is None or (isinstance(slug, float) and pd.isna(slug)):
        return ""
    text = DATE_SUFFIX.sub("", str(slug).strip().lower())
    for separator in (".", "_", ":"):
        text = text.replace(separator, "-")
    parts = [part for part in text.split("-") if part]
    parts = [part for part in parts if part not in ROUTE_VARIANTS]
    if strip_tiers:
        while parts and parts[-1] in EFFORT_TIERS:
            parts.pop()
    return "-".join(parts)


def route_slug(model_id: object) -> str:
    """``moonshotai/kimi-k3-20260715:free`` -> ``kimi-k3-20260715``."""
    if model_id is None:
        return ""
    return str(model_id).split(":", 1)[0].split("/", 1)[-1]


def openrouter_prefix(model_id: object) -> str:
    text = str(model_id or "")
    return text.split("/", 1)[0].lstrip("~").lower() if "/" in text else ""


def expand_routes(
    seeds: Iterable[str],
    canonical_of: Mapping[str, str],
    ids_of_canonical: Mapping[str, frozenset[str]],
) -> frozenset[str]:
    """Transitive closure over model_id <-> canonical_slug links.

    Usage flows on dated permaslugs (``moonshotai/kimi-k3-20260715``) while the
    catalog exposes undated aliases (``moonshotai/kimi-k3``). The catalog's
    ``canonical_slug`` is the bridge, and it has to be followed to a fixed
    point: a family resolved only to its alias would rank but carry no tokens.
    """
    routes = set(seeds)
    frontier = list(routes)
    while frontier:
        following = []
        for route in frontier:
            targets: set[str] = set()
            canonical = canonical_of.get(route)
            if canonical:
                targets.add(canonical)
            targets |= set(ids_of_canonical.get(route, frozenset()))
            for target in targets:
                if target and target not in routes:
                    routes.add(target)
                    following.append(target)
        frontier = following
    return frozenset(routes)


@dataclass(frozen=True)
class Resolution:
    """One AA model's resolution attempt, successful or not."""

    aa_model_id: str
    model_name: str
    model_slug: str
    creator_slug: str
    status: str
    family_id: str | None = None
    routes: frozenset[str] = frozenset()
    effective_from: pd.Timestamp | None = None
    detail: str = ""

    @property
    def resolved(self) -> bool:
        return self.family_id is not None


@dataclass(frozen=True)
class CatalogIndex:
    """Precomputed lookups over one OpenRouter catalog snapshot."""

    by_prefix: Mapping[str, tuple[str, ...]]
    canonical_of: Mapping[str, str]
    ids_of_canonical: Mapping[str, frozenset[str]]
    created_at: Mapping[str, pd.Timestamp]
    known_prefixes: frozenset[str]


def build_catalog_index(catalog: pd.DataFrame) -> CatalogIndex:
    if catalog.empty or "model_id" not in catalog.columns:
        return CatalogIndex({}, {}, {}, {}, frozenset())

    frame = catalog.drop_duplicates(subset="model_id", keep="last")
    by_prefix: dict[str, list[str]] = {}
    canonical_of: dict[str, str] = {}
    ids_of_canonical: dict[str, set[str]] = {}
    created_at: dict[str, pd.Timestamp] = {}

    created_series = (
        pd.to_datetime(frame["created_at"], errors="coerce", utc=True)
        if "created_at" in frame.columns
        else pd.Series(pd.NaT, index=frame.index)
    )
    for position, (_, row) in enumerate(frame.iterrows()):
        model_id = str(row["model_id"])
        by_prefix.setdefault(openrouter_prefix(model_id), []).append(model_id)
        canonical = row.get("canonical_slug")
        if canonical is not None and not pd.isna(canonical) and str(canonical) != model_id:
            canonical_of[model_id] = str(canonical)
            ids_of_canonical.setdefault(str(canonical), set()).add(model_id)
        stamp = created_series.iloc[position]
        if pd.notna(stamp):
            created_at[model_id] = pd.Timestamp(stamp).tz_convert(None).normalize()

    return CatalogIndex(
        by_prefix={key: tuple(value) for key, value in by_prefix.items()},
        canonical_of=canonical_of,
        ids_of_canonical={key: frozenset(value) for key, value in ids_of_canonical.items()},
        created_at=created_at,
        known_prefixes=frozenset(by_prefix),
    )


def _candidate_prefixes(creator_slug: str, index: CatalogIndex) -> list[str]:
    """Aliased prefix first, then the creator slug verbatim.

    Some creators match the OpenRouter prefix without an alias entry, so trying
    the raw slug avoids growing the table for no reason. An unknown creator
    yields nothing and lands in the unresolved path with a named cause.
    """
    candidates: list[str] = []
    aliased = CREATOR_ALIASES.get(creator_slug)
    for candidate in (aliased, creator_slug):
        if candidate and candidate in index.known_prefixes and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _effective_from(
    release_date: pd.Timestamp | None,
    routes: frozenset[str],
    index: CatalogIndex,
) -> pd.Timestamp | None:
    """The first day this family may carry usage.

    A route cannot carry usage before it exists in the catalog, and a family
    cannot enter the cohort before AA says it is released, so the later of the
    two bounds wins. This preserves the point-in-time contract the curated
    map's own effective_from provides.
    """
    bounds: list[pd.Timestamp] = []
    if release_date is not None and pd.notna(release_date):
        bounds.append(pd.Timestamp(release_date).normalize())
    catalog_dates = [index.created_at[route] for route in routes if route in index.created_at]
    if catalog_dates:
        bounds.append(min(catalog_dates))
    return max(bounds) if bounds else None


def resolve_model(
    *,
    aa_model_id: str,
    model_name: str,
    model_slug: str,
    creator_slug: str,
    release_date: pd.Timestamp | None,
    index: CatalogIndex,
) -> Resolution:
    """Resolve one AA model to an OpenRouter family, or decline with a reason."""
    base = dict(
        aa_model_id=aa_model_id,
        model_name=model_name,
        model_slug=model_slug,
        creator_slug=creator_slug,
    )
    prefixes = _candidate_prefixes(creator_slug, index)
    if not prefixes:
        return Resolution(
            **base,
            status=UNRESOLVED_NO_PREFIX,
            detail=(
                f"creator '{creator_slug}' matches no OpenRouter prefix; "
                f"add CREATOR_ALIASES['{creator_slug}'] = '<prefix>'"
            ),
        )

    for prefix in prefixes:
        catalog_ids = index.by_prefix.get(prefix, ())
        for strip_tiers in (False, True):
            target = normalize_slug(model_slug, strip_tiers=strip_tiers)
            if not target:
                continue
            matches = [
                model_id
                for model_id in catalog_ids
                if normalize_slug(route_slug(model_id), strip_tiers=strip_tiers) == target
            ]
            if not matches:
                continue
            # Tier B may have collapsed genuinely different models together
            # (o3-mini vs o3-mini-high). Distinct tier-A keys among the matches
            # is exactly that condition. Never guess between them.
            distinct_exact_keys = {normalize_slug(route_slug(model_id)) for model_id in matches}
            if strip_tiers and len(distinct_exact_keys) > 1:
                return Resolution(
                    **base,
                    status=UNRESOLVED_AMBIGUOUS,
                    detail=(
                        f"stripped key '{target}' matches {len(distinct_exact_keys)} distinct "
                        f"catalog families in '{prefix}': {sorted(distinct_exact_keys)}; "
                        "add a curated entry to disambiguate"
                    ),
                )
            routes = expand_routes(matches, index.canonical_of, index.ids_of_canonical)
            return Resolution(
                **base,
                status=RESOLVER_STRIPPED if strip_tiers else RESOLVER_EXACT,
                family_id=f"{prefix}/{target}",
                routes=routes,
                effective_from=_effective_from(release_date, routes, index),
                detail=f"matched {len(matches)} catalog route(s) under '{prefix}'",
            )

    return Resolution(
        **base,
        status=UNRESOLVED_NO_ROUTE,
        detail=(
            f"no catalog route under {prefixes} normalizes to "
            f"'{normalize_slug(model_slug)}'"
        ),
    )


RESOLVER_VERSION_SUFFIX = "resolver1"


def resolve_capability_map(
    capability_map: "CapabilityMap",
    aa_models: pd.DataFrame,
    catalog: pd.DataFrame,
) -> tuple["CapabilityMap", list[Resolution]]:
    """Extend a curated map with deterministically resolved families.

    The curated map is never overridden: an AA model it names keeps its human
    assignment, and a route it claims can never be reassigned by the resolver.
    Only models the curated map is silent about are resolved, which is exactly
    the frontier-release gap this exists to close.

    Returns the augmented map and every resolution attempt, resolved or not --
    the declines are what the drift guard reports.
    """
    from .identity import CapabilityEntry, CapabilityMap, CapabilityRoute

    if aa_models.empty:
        return capability_map, []

    curated_ids = set(capability_map.by_aa_model_id)
    # A route already spoken for by a human keeps that family. load_capability_map
    # rejects a route in two families, and the augmented map has to hold the
    # same invariant or downstream joins would double-count a route's usage.
    claimed_routes: dict[str, str] = {
        route.model_id: entry.family_id
        for entry in capability_map.entries
        for route in entry.openrouter_routes
    }

    index = build_catalog_index(catalog)
    latest = aa_models
    if "as_of_date" in latest.columns:
        as_of = pd.to_datetime(latest["as_of_date"], errors="coerce")
        latest = latest.loc[as_of == as_of.max()]
    latest = latest.drop_duplicates(subset="model_id", keep="last")

    resolutions: list[Resolution] = []
    new_entries: list[CapabilityEntry] = []
    for _, model in latest.iterrows():
        aa_model_id = str(model["model_id"])
        release_date = pd.to_datetime(model.get("release_date"), errors="coerce")
        resolution = resolve_model(
            aa_model_id=aa_model_id,
            model_name=str(model.get("model_name") or ""),
            model_slug=str(model.get("model_slug") or ""),
            creator_slug=str(model.get("creator_slug") or ""),
            release_date=release_date,
            index=index,
        )
        if aa_model_id in curated_ids:
            # Recorded for the guard's benefit (it reports which top-N models
            # still depend on a hand-written entry) but never applied.
            resolutions.append(resolution)
            continue

        if resolution.resolved:
            free_routes = frozenset(
                route
                for route in resolution.routes
                if claimed_routes.get(route, resolution.family_id) == resolution.family_id
            )
            if not free_routes:
                resolution = Resolution(
                    aa_model_id=resolution.aa_model_id,
                    model_name=resolution.model_name,
                    model_slug=resolution.model_slug,
                    creator_slug=resolution.creator_slug,
                    status=UNRESOLVED_NO_ROUTE,
                    detail="every matched route is already curated to another family",
                )
            else:
                resolution = Resolution(
                    aa_model_id=resolution.aa_model_id,
                    model_name=resolution.model_name,
                    model_slug=resolution.model_slug,
                    creator_slug=resolution.creator_slug,
                    status=resolution.status,
                    family_id=resolution.family_id,
                    routes=free_routes,
                    effective_from=resolution.effective_from,
                    detail=resolution.detail,
                )
        resolutions.append(resolution)
        if not resolution.resolved or resolution.effective_from is None:
            continue

        entry_from = pd.Timestamp(resolution.effective_from).normalize()
        routes = tuple(
            CapabilityRoute(
                model_id=route,
                effective_from=max(entry_from, index.created_at.get(route, entry_from)),
            )
            for route in sorted(resolution.routes)
        )
        new_entries.append(
            CapabilityEntry(
                aa_model_id=resolution.aa_model_id,
                family_id=resolution.family_id,
                effective_from=entry_from,
                openrouter_routes=routes,
            )
        )
        for route in resolution.routes:
            claimed_routes.setdefault(route, resolution.family_id)

    if not new_entries:
        return capability_map, resolutions

    version = capability_map.methodology_version
    if RESOLVER_VERSION_SUFFIX not in version:
        version = f"{version}+{RESOLVER_VERSION_SUFFIX}"
    return (
        CapabilityMap(
            methodology_version=version,
            entries=capability_map.entries + tuple(new_entries),
        ),
        resolutions,
    )
