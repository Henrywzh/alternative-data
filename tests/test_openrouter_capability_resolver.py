"""Tests for deterministic capability resolution and the drift guard."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from openrouter_derived_data.guard import report_exit_code, run_guard
from openrouter_derived_data.identity import (
    CapabilityEntry,
    CapabilityMap,
    CapabilityRoute,
    load_capability_map,
    rank_capability_families,
)
from openrouter_derived_data.resolver import (
    RESOLVER_EXACT,
    RESOLVER_STRIPPED,
    UNRESOLVED_AMBIGUOUS,
    UNRESOLVED_NO_PREFIX,
    build_catalog_index,
    expand_routes,
    normalize_slug,
    resolve_capability_map,
    resolve_model,
    route_slug,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("grok-4-6", "grok-4-6"),
        ("grok-4.6", "grok-4-6"),
        ("grok-4.6-20260810", "grok-4-6"),
        ("grok-4.6:free", "grok-4-6"),
        ("Kimi_K3", "kimi-k3"),
        ("gpt-5.6-sol-preview", "gpt-5-6-sol"),
    ],
)
def test_normalize_slug_collapses_dates_separators_and_route_qualifiers(raw, expected):
    assert normalize_slug(raw) == expected


def test_effort_tiers_survive_tier_a_and_collapse_in_tier_b():
    """Stripping is tier B only, so tier A cannot confuse two real variants."""
    assert normalize_slug("claude-opus-5-xhigh") == "claude-opus-5-xhigh"
    assert normalize_slug("claude-opus-5-xhigh", strip_tiers=True) == "claude-opus-5"
    # 'max' is an effort tier, but qwen3-8-max is a distinct product. Symmetric
    # stripping is what keeps that safe: both sides lose it or neither does.
    assert normalize_slug("qwen3-8-max") == "qwen3-8-max"


def test_route_slug_drops_prefix_and_variant():
    assert route_slug("moonshotai/kimi-k3-20260715:free") == "kimi-k3-20260715"


def test_expand_routes_follows_canonical_slug_to_a_fixed_point():
    """A family resolved only to its undated alias would carry no tokens."""
    routes = expand_routes(
        {"moonshotai/kimi-k3"},
        canonical_of={"moonshotai/kimi-k3": "moonshotai/kimi-k3-20260715"},
        ids_of_canonical={"moonshotai/kimi-k3-20260715": frozenset({"moonshotai/kimi-k3"})},
    )
    assert routes == frozenset({"moonshotai/kimi-k3", "moonshotai/kimi-k3-20260715"})


def _catalog(rows: list[tuple[str, str | None]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model_id": model_id,
                "canonical_slug": canonical,
                "created_at": "2026-07-01T00:00:00Z",
                "provider_prefix": model_id.split("/", 1)[0],
            }
            for model_id, canonical in rows
        ]
    )


def _resolve(model_slug: str, creator_slug: str, catalog: pd.DataFrame):
    return resolve_model(
        aa_model_id="uuid-1",
        model_name="Test Model",
        model_slug=model_slug,
        creator_slug=creator_slug,
        release_date=pd.Timestamp("2026-07-01"),
        index=build_catalog_index(catalog),
    )


def test_resolver_matches_a_dated_permaslug_through_the_creator_alias():
    catalog = _catalog([("x-ai/grok-4.6-20260810", None)])
    resolution = _resolve("grok-4.6", "xai", catalog)
    assert resolution.status == RESOLVER_EXACT
    assert resolution.family_id == "x-ai/grok-4-6"
    assert "x-ai/grok-4.6-20260810" in resolution.routes


def test_resolver_falls_back_to_stripping_effort_tiers():
    catalog = _catalog([("anthropic/claude-opus-5", None)])
    resolution = _resolve("claude-opus-5-xhigh", "anthropic", catalog)
    assert resolution.status == RESOLVER_STRIPPED
    assert resolution.family_id == "anthropic/claude-opus-5"


def test_resolver_declines_an_ambiguous_stripped_key_rather_than_guessing():
    """o3-mini and o3-mini-high both exist; a guess would corrupt the index."""
    catalog = _catalog([("openai/o3-mini", None), ("openai/o3-mini-high", None)])
    resolution = _resolve("o3-mini-medium", "openai", catalog)
    assert resolution.status == UNRESOLVED_AMBIGUOUS
    assert resolution.family_id is None
    assert "o3-mini" in resolution.detail


def test_resolver_names_an_unknown_creator_instead_of_matching_anything():
    catalog = _catalog([("x-ai/grok-4.6", None)])
    resolution = _resolve("brand-new-1", "neverheardof", catalog)
    assert resolution.status == UNRESOLVED_NO_PREFIX
    assert "CREATOR_ALIASES" in resolution.detail


def _aa_frame(rows: list[tuple[str, str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "as_of_date": "2026-08-19",
                "model_id": aa_id,
                "model_slug": slug,
                "model_name": name,
                "creator_slug": creator,
                "release_date": "2026-07-01",
                "intelligence_index": 60.0 - index,
            }
            for index, (aa_id, slug, name, creator) in enumerate(rows)
        ]
    )


def _curated(family_id: str, aa_model_id: str, route: str) -> CapabilityMap:
    return CapabilityMap(
        methodology_version="test-v1",
        entries=(
            CapabilityEntry(
                aa_model_id=aa_model_id,
                family_id=family_id,
                effective_from=pd.Timestamp("2026-07-01"),
                openrouter_routes=(CapabilityRoute(route, pd.Timestamp("2026-07-01")),),
            ),
        ),
    )


def test_curated_entries_are_never_overridden_by_the_resolver():
    """A human assignment is the one thing the resolver must not touch."""
    curated = _curated("anthropic/hand-picked", "uuid-claude", "anthropic/claude-opus-5")
    aa = _aa_frame([("uuid-claude", "claude-opus-5", "Claude Opus 5", "anthropic")])
    catalog = _catalog([("anthropic/claude-opus-5", None)])

    augmented, resolutions = resolve_capability_map(curated, aa, catalog)

    assert augmented.by_aa_model_id["uuid-claude"].family_id == "anthropic/hand-picked"
    assert len(augmented.entries) == 1
    # The attempt is still recorded so the guard can report it.
    assert resolutions[0].aa_model_id == "uuid-claude"


def test_resolver_adds_only_families_the_curated_map_is_silent_about():
    curated = _curated("moonshotai/kimi-k3", "uuid-kimi", "moonshotai/kimi-k3")
    aa = _aa_frame(
        [
            ("uuid-kimi", "kimi-k3", "Kimi K3", "kimi"),
            ("uuid-gemini", "gemini-3.7-flash", "Gemini 3.7 Flash", "google"),
        ]
    )
    catalog = _catalog(
        [("moonshotai/kimi-k3", None), ("google/gemini-3.7-flash", None)]
    )

    augmented, _ = resolve_capability_map(curated, aa, catalog)

    assert augmented.by_aa_model_id["uuid-gemini"].family_id == "google/gemini-3-7-flash"
    assert "resolver1" in augmented.methodology_version


def test_a_route_curated_to_one_family_is_never_reassigned():
    """load_capability_map rejects a route in two families; so must the augment."""
    curated = _curated("uuid-a", "vendor/shared-route", "vendor/shared-route")
    aa = _aa_frame([("uuid-b", "shared-route", "Shared Route", "vendor")])
    catalog = _catalog([("vendor/shared-route", None)])

    augmented, resolutions = resolve_capability_map(curated, aa, catalog)

    assignments: dict[str, str] = {}
    for entry in augmented.entries:
        for route in entry.openrouter_routes:
            assert assignments.setdefault(route.model_id, entry.family_id) == entry.family_id
    assert not [item for item in resolutions if item.aa_model_id == "uuid-b" and item.resolved]


def test_rankings_distinguish_a_resolved_family_from_a_curated_one():
    aa = _aa_frame([("uuid-gemini", "gemini-3.7-flash", "Gemini 3.7 Flash", "google")])
    ranked = rank_capability_families(
        aa,
        pd.Series([pd.Timestamp("2026-08-19")]),
        CapabilityMap(
            methodology_version="test-v1",
            entries=(
                CapabilityEntry(
                    aa_model_id="uuid-gemini",
                    family_id="google/gemini-3-7-flash",
                    effective_from=pd.Timestamp("2026-07-01"),
                    openrouter_routes=(
                        CapabilityRoute("google/gemini-3.7-flash", pd.Timestamp("2026-07-01")),
                    ),
                ),
            ),
        ),
        backfill_latest_snapshot=True,
        resolution_status={"uuid-gemini": RESOLVER_EXACT},
    )
    assert ranked["model_match_status"].tolist() == [RESOLVER_EXACT]


def _guard_base(tmp_path: Path, aa: pd.DataFrame, catalog: pd.DataFrame, curated_models: list[dict]) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "openrouter_capability_map.json").write_text(
        json.dumps({"methodology_version": "test-v1", "models": curated_models})
    )
    aa_dir = tmp_path / "data" / "normalized" / "artificial_analysis"
    catalog_dir = tmp_path / "data" / "normalized" / "compute_availability"
    aa_dir.mkdir(parents=True)
    catalog_dir.mkdir(parents=True)
    aa.to_parquet(aa_dir / "artificial_analysis_models_daily.parquet", index=False)
    catalog.to_parquet(catalog_dir / "raw_openrouter_models.parquet", index=False)
    return tmp_path


_CURATED_KIMI = [
    {
        "aa_model_id": "uuid-kimi",
        "family_id": "moonshotai/kimi-k3",
        "effective_from": "2026-07-01",
        "openrouter_routes": [{"model_id": "moonshotai/kimi-k3", "effective_from": "2026-07-01"}],
    }
]


def test_guard_is_quiet_when_every_top_model_is_curated(tmp_path: Path):
    base = _guard_base(
        tmp_path,
        _aa_frame([("uuid-kimi", "kimi-k3", "Kimi K3", "kimi")]),
        _catalog([("moonshotai/kimi-k3", None)]),
        _CURATED_KIMI,
    )
    report = run_guard(base, top_n=10)
    assert report.findings == []
    assert report_exit_code(report) == 0


def test_guard_fails_on_a_top_model_that_resolves_to_nothing(tmp_path: Path):
    """The frontier-release case: a new lab nobody has aliased yet."""
    base = _guard_base(
        tmp_path,
        _aa_frame(
            [
                ("uuid-new", "brand-new-1", "Brand New 1", "neverheardof"),
                ("uuid-kimi", "kimi-k3", "Kimi K3", "kimi"),
            ]
        ),
        _catalog([("moonshotai/kimi-k3", None)]),
        _CURATED_KIMI,
    )
    report = run_guard(base, top_n=10)
    drift = [item for item in report.findings if item.check == "drift"]
    assert len(drift) == 1
    assert "Brand New 1" in drift[0].message
    assert report_exit_code(report) == 1


def test_guard_flags_an_automatic_match_without_failing_by_default(tmp_path: Path):
    """A resolved family publishes; it just should not stay unreviewed."""
    base = _guard_base(
        tmp_path,
        _aa_frame(
            [
                ("uuid-kimi", "kimi-k3", "Kimi K3", "kimi"),
                ("uuid-gemini", "gemini-3.7-flash", "Gemini 3.7 Flash", "google"),
            ]
        ),
        _catalog([("moonshotai/kimi-k3", None), ("google/gemini-3.7-flash", None)]),
        _CURATED_KIMI,
    )
    report = run_guard(base, top_n=10)
    fuzzy = [item for item in report.findings if item.check == "fuzzy"]
    assert len(fuzzy) == 1
    assert report_exit_code(report) == 0
    assert report_exit_code(report, fail_on="fuzzy") == 1


def test_guard_fails_on_a_run_of_partially_covered_days(tmp_path: Path):
    """Catches degradation the resolution checks cannot see."""
    base = _guard_base(
        tmp_path,
        _aa_frame([("uuid-kimi", "kimi-k3", "Kimi K3", "kimi")]),
        _catalog([("moonshotai/kimi-k3", None)]),
        _CURATED_KIMI,
    )
    mart_dir = base / "data" / "normalized" / "marts"
    mart_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "usage_date": pd.date_range("2026-08-15", periods=4, freq="D"),
            "metric_id": "sota_volume_weighted_atp",
            "pricing_join_status": "partial_true_sota_route_coverage",
            "observed_family_count": 3.0,
            "expected_family_count": 5.0,
        }
    ).to_parquet(mart_dir / "openrouter_usage_economics_daily.parquet", index=False)

    report = run_guard(base, top_n=10)
    coverage = [item for item in report.findings if item.check == "coverage"]
    assert len(coverage) == 1
    assert coverage[0].detail["consecutive_days"] == 4
    assert report_exit_code(report) == 1
