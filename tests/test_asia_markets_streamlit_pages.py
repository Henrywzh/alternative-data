"""Contracts for Asia Markets native pages and page-scoped artifact loading."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


APP_DIR = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "asia-markets-streamlit"
)
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def test_page_registry_has_unique_keys_paths_and_one_default() -> None:
    from am.page_registry import PAGE_DEFINITIONS

    keys = [page.key for page in PAGE_DEFINITIONS]
    paths = [page.url_path for page in PAGE_DEFINITIONS]
    defaults = [page.key for page in PAGE_DEFINITIONS if page.default]

    assert len(keys) == len(set(keys))
    assert len(paths) == len(set(paths))
    assert defaults == ["overview"]
    assert PAGE_DEFINITIONS[0].url_path is None
    assert {
        "overview",
        "market",
        "regime",
        "hong_kong_flows",
        "events",
        "heatmaps",
        "labour",
        "population",
        "real_estate",
        "transport",
        "aerospace",
        "crypto",
        "data",
        "health",
    } == set(keys)


@pytest.mark.parametrize(
    ("page_key", "sector_key"),
    [
        ("market", "market"),
        ("regime", "regime"),
        ("heatmaps", "market"),
        ("labour", "labour"),
        ("population", "population"),
        ("real_estate", "real_estate"),
        ("transport", "transport"),
        ("aerospace", "aerospace"),
        ("crypto", "crypto"),
    ],
)
def test_sector_pages_load_only_their_own_artifact(
    page_key: str,
    sector_key: str,
    monkeypatch,
) -> None:
    import am.page_registry as registry

    sector_calls: list[tuple[str, str]] = []
    all_calls: list[str] = []

    def fake_sector_loader(key: str, language: str):
        sector_calls.append((key, language))
        artifact = {"manifest": {}, "snapshot": {"datasets": {}}}
        return artifact, artifact, []

    monkeypatch.setattr(registry, "load_sector_artifact", fake_sector_loader)
    monkeypatch.setattr(
        registry,
        "load_all_sector_artifacts",
        lambda language: all_calls.append(language),
    )
    monkeypatch.setattr(registry, "_render_sector", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(registry, "_page_state", lambda: ("zh", "10 years"))

    registry.run_page(page_key)

    assert sector_calls == [(sector_key, "zh")]
    assert all_calls == []


@pytest.mark.parametrize("page_key", ["overview", "data", "health"])
def test_aggregate_pages_load_all_artifacts(
    page_key: str,
    monkeypatch,
) -> None:
    import am.page_registry as registry

    all_calls: list[str] = []
    sector_calls: list[tuple[str, str]] = []
    bundle = (
        {"market": {"manifest": {}, "snapshot": {"datasets": {}}}},
        {"market": {"manifest": {}, "snapshot": {"datasets": {}}}},
        [],
    )

    def fake_all_loader(language: str):
        all_calls.append(language)
        return bundle

    monkeypatch.setattr(registry, "load_all_sector_artifacts", fake_all_loader)
    monkeypatch.setattr(
        registry,
        "load_sector_artifact",
        lambda key, language: sector_calls.append((key, language)),
    )
    monkeypatch.setattr(registry, "_render_aggregate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(registry, "_page_state", lambda: ("en", "10 years"))

    registry.run_page(page_key)

    assert all_calls == ["en"]
    assert sector_calls == []


def test_events_page_is_standalone_and_loads_no_sector_artifacts(monkeypatch) -> None:
    import am.page_registry as registry

    rendered_languages: list[str] = []
    all_calls: list[str] = []
    sector_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        registry,
        "load_all_sector_artifacts",
        lambda language: all_calls.append(language),
    )
    monkeypatch.setattr(
        registry,
        "load_sector_artifact",
        lambda key, language: sector_calls.append((key, language)),
    )
    monkeypatch.setattr(
        registry,
        "_resolve_renderer",
        lambda _target: rendered_languages.append,
    )
    monkeypatch.setattr(registry, "_page_state", lambda: ("zh", "10 years"))

    registry.run_page("events")

    assert rendered_languages == ["zh"]
    assert all_calls == []
    assert sector_calls == []


def test_sidebar_groups_reference_every_registered_page_once() -> None:
    from am.page_registry import PAGE_DEFINITIONS
    from am.sidebar import SIDEBAR_GROUPS

    sidebar_keys = [
        page_key
        for _group_key, page_keys in SIDEBAR_GROUPS
        for page_key in page_keys
    ]
    registry_keys = [page.key for page in PAGE_DEFINITIONS]

    assert sorted(sidebar_keys) == sorted(registry_keys)
    assert len(sidebar_keys) == len(set(sidebar_keys))
    assert dict(SIDEBAR_GROUPS)["markets"] == (
        "market",
        "regime",
        "hong_kong_flows",
        "events",
        "heatmaps",
    )


def test_period_signal_requires_the_exact_prior_year_month() -> None:
    import pandas as pd

    from am.signals import latest_period_signal

    frame = pd.DataFrame(
        [
            {"date": "2024-06-01", "value": 80},
            {"date": "2025-07-01", "value": 100},
        ]
    )

    signal = latest_period_signal(frame, "date", "value")

    assert signal["value"] == 100
    assert signal["change"] is None


def test_period_signal_compares_the_exact_prior_year_month() -> None:
    import pandas as pd

    from am.signals import latest_period_signal

    frame = pd.DataFrame(
        [
            {"date": "2024-07-31", "value": 80},
            {"date": "2025-07-01", "value": 100},
        ]
    )

    signal = latest_period_signal(frame, "date", "value")

    assert signal["change"] == pytest.approx(25.0)


def test_heatmaps_is_a_lazy_market_page():
    from am.page_registry import DEFINITION_BY_KEY

    definition = DEFINITION_BY_KEY["heatmaps"]
    assert definition.group == "markets"
    assert definition.url_path == "heat-maps"
    assert definition.renderer == "am.heatmaps:render_heatmaps"


def test_events_is_a_standalone_market_page() -> None:
    from am.page_registry import DEFINITION_BY_KEY

    definition = DEFINITION_BY_KEY["events"]
    assert definition.group == "markets"
    assert definition.url_path == "events-consensus"
    assert definition.sector_key is None
    assert definition.renderer == "am.events_consensus:render_events_consensus"

def test_factset_helpers_split_snapshot_from_revision_and_keep_sector_dates() -> None:
    import pandas as pd

    from am.regime import (
        FACTSET_CORE_FIELDS,
        FACTSET_REVISION_FIELDS,
        _factset_latest_sector_board,
        _factset_latest_with_any,
        _factset_valuation_history,
    )

    frame = pd.DataFrame(
        [
            {
                "report_date": "2026-08-07",
                "article_type": "sector",
                "article_title": "Earnings Season Update",
                "blended_earnings_growth_yoy": 47.4,
                "eps_beat_rate": 86.0,
                "forward_12m_pe": 20.0,
                "forward_12m_pe_10y_avg": 19.0,
                "quarterly_eps_revision_pct": None,
                "annual_eps_revision_pct": None,
                "sector_revision_json": None,
            },
            {
                "report_date": "2026-09-04",
                "article_type": "revision",
                "article_title": "Analysts Increasing EPS Estimates",
                "blended_earnings_growth_yoy": None,
                "eps_beat_rate": None,
                "forward_12m_pe": None,
                "forward_12m_pe_10y_avg": 39.0,
                "quarterly_eps_revision_pct": 1.2,
                "annual_eps_revision_pct": 6.1,
                "sector_revision_json": '{"Energy": 11.8, "Materials": -9.1}',
            },
            {
                "report_date": "2026-07-10",
                "article_type": "revision",
                "article_title": "Earlier IT revision",
                "blended_earnings_growth_yoy": None,
                "eps_beat_rate": None,
                "forward_12m_pe": None,
                "forward_12m_pe_10y_avg": None,
                "quarterly_eps_revision_pct": None,
                "annual_eps_revision_pct": None,
                "sector_revision_json": '{"Information Technology": 3.4}',
            },
        ]
    )

    core = _factset_latest_with_any(frame, FACTSET_CORE_FIELDS)
    revision = _factset_latest_with_any(frame, FACTSET_REVISION_FIELDS)
    board = _factset_latest_sector_board(frame)
    history = _factset_valuation_history(frame)

    assert str(pd.to_datetime(core["report_date"]).date()) == "2026-08-07"
    assert core["forward_12m_pe"] == 20.0
    assert str(pd.to_datetime(revision["report_date"]).date()) == "2026-09-04"
    assert revision["quarterly_eps_revision_pct"] == 1.2
    assert list(board["sector"]) == ["Energy", "Information Technology", "Materials"]
    assert list(board["revision_pct"]) == [11.8, 3.4, -9.1]
    assert 39.0 not in set(history["forward_12m_pe_10y_avg"].dropna())
    assert 20.0 in set(history["forward_12m_pe"].dropna())
