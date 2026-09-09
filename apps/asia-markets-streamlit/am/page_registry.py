"""Native Streamlit page registry with lazy renderer imports."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from importlib import import_module
from typing import Any, Mapping, Sequence

import streamlit as st

from .artifacts import load_all_sector_artifacts, load_sector_artifact
from .config import HISTORY_WINDOWS, SECTORS
from .core import tr


@dataclass(frozen=True)
class PageDefinition:
    key: str
    group: str
    title_en: str
    title_zh: str
    url_path: str | None
    icon: str
    default: bool = False
    sector_key: str | None = None
    renderer: str | None = None

    def label(self, language: str) -> str:
        return self.title_zh if language == "zh" else self.title_en


PAGE_DEFINITIONS: tuple[PageDefinition, ...] = (
    PageDefinition("overview", "workspace", "Overview", "总览", None, "🌏", True),
    PageDefinition(
        "market",
        "markets",
        "ETF Monitor",
        "ETF监控",
        "etf-monitor",
        "📈",
        sector_key="market",
        renderer="am.market_page:render_market",
    ),
    PageDefinition(
        "regime",
        "markets",
        "Market Regime",
        "市场状态",
        "market-regime",
        "🧭",
        sector_key="regime",
        renderer="am.regime:render_regime",
    ),
    PageDefinition(
        "labour",
        "hong_kong",
        "Labour Market",
        "劳动力市场",
        "hk-labour-market",
        "💼",
        sector_key="labour",
        renderer="am.labour:render_labour",
    ),
    PageDefinition(
        "population",
        "hong_kong",
        "Population & Migration",
        "人口与迁移",
        "hk-population-migration",
        "👥",
        sector_key="population",
        renderer="am.population:render_population",
    ),
    PageDefinition(
        "real_estate",
        "hong_kong",
        "Hong Kong Real Estate",
        "地产",
        "hk-real-estate",
        "🏙️",
        sector_key="real_estate",
        renderer="am.realestate:render_real_estate_tabs",
    ),
    PageDefinition(
        "transport",
        "hong_kong",
        "Transport & Aviation",
        "交通与航空",
        "hk-transport",
        "✈️",
        sector_key="transport",
        renderer="am.transport:render_transport_tabs",
    ),
    PageDefinition(
        "aerospace",
        "hong_kong",
        "Commercial Aerospace",
        "商业航天",
        "hk-commercial-aerospace",
        "🚀",
        sector_key="aerospace",
        renderer="am.aerospace:render_aerospace",
    ),
    PageDefinition(
        "crypto",
        "hong_kong",
        "Stablecoin & Crypto",
        "稳定币与加密资产",
        "hk-stablecoin-crypto",
        "🪙",
        sector_key="crypto",
        renderer="am.crypto:render_crypto",
    ),
    PageDefinition("data", "data", "Data Explorer", "数据探索器", "data-explorer", "🔎"),
    PageDefinition("health", "data", "Source Health", "来源健康度", "source-health", "🩺"),
)

DEFINITION_BY_KEY = {definition.key: definition for definition in PAGE_DEFINITIONS}


def _page_state() -> tuple[str, str]:
    language = (
        "zh"
        if st.session_state.get("language_choice", "中文") == "中文"
        else "en"
    )
    history_window = st.session_state.get(
        "history_window",
        next(iter(HISTORY_WINDOWS)),
    )
    if history_window not in HISTORY_WINDOWS:
        history_window = next(iter(HISTORY_WINDOWS))
    return language, str(history_window)


def _show_errors(errors: Sequence[str]) -> None:
    if errors:
        st.warning(" ".join(errors))


def _resolve_renderer(target: str):
    module_name, attribute = target.split(":", 1)
    return getattr(import_module(module_name), attribute)


def _render_sector(
    definition: PageDefinition,
    artifact: dict[str, Any],
    labels: dict[str, Any],
    language: str,
    history_window: str,
) -> None:
    if definition.renderer is None:
        raise ValueError(f"Page {definition.key} has no renderer")
    renderer = _resolve_renderer(definition.renderer)
    renderer(artifact, labels, language, history_window)


def _render_aggregate(
    page_key: str,
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
    history_window: str,
) -> None:
    if page_key == "overview":
        from .overview import render_overview

        render_overview(artifacts, labels, language, history_window)
        return
    if page_key == "data":
        from .explorer import render_data_explorer

        render_data_explorer(artifacts, language)
        return
    if page_key == "health":
        from .explorer import render_source_coverage

        st.markdown(
            f'<div class="am-page-title">'
            f'{tr(language, "Source Health", "来源健康度")}</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            tr(
                language,
                f"Freshness and coverage for {len(SECTORS)} connected research sections.",
                f"{len(SECTORS)} 个已接入研究板块的更新时间和覆盖情况。",
            )
        )
        render_source_coverage(artifacts, labels, language)
        return
    raise KeyError(f"Unknown aggregate page: {page_key}")


def run_page(page_key: str) -> None:
    """Load only the data required by one registered page and render it."""
    definition = DEFINITION_BY_KEY.get(page_key)
    if definition is None:
        raise KeyError(f"Unknown Asia Markets page: {page_key}")

    language, history_window = _page_state()
    if definition.sector_key is not None:
        artifact, labels, errors = load_sector_artifact(
            definition.sector_key,
            language,
        )
        _show_errors(errors)
        _render_sector(
            definition,
            artifact,
            labels,
            language,
            history_window,
        )
        return

    artifacts, labels, errors = load_all_sector_artifacts(language)
    _show_errors(errors)
    _render_aggregate(
        page_key,
        artifacts,
        labels,
        language,
        history_window,
    )


def build_streamlit_pages() -> dict[str, Any]:
    pages: dict[str, Any] = {}
    for definition in PAGE_DEFINITIONS:
        runner = partial(run_page, definition.key)
        pages[definition.key] = st.Page(
            runner,
            title=definition.title_en,
            icon=definition.icon,
            url_path=definition.url_path,
            default=definition.default,
        )
    return pages


def selected_page_key(
    selected_page: Any,
    pages: Mapping[str, Any],
) -> str:
    for page_key, page in pages.items():
        if page is selected_page:
            return page_key
    selected_path = getattr(selected_page, "url_path", None)
    for page_key, page in pages.items():
        if getattr(page, "url_path", None) == selected_path:
            return page_key
    return "overview"
