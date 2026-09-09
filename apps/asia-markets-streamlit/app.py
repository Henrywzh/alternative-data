"""Asia Markets private Streamlit research terminal.

The entrypoint owns only application bootstrap and navigation.  Page
renderers and artifact reads stay lazy so opening one sector does not parse
every dashboard artifact or import every renderer.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
import sys
from typing import Any

import streamlit as st


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
APP_DIR = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import am
from am.artifacts import load_all_sector_artifacts
from am.core import style_app
from am.page_registry import (
    PAGE_DEFINITIONS,
    build_streamlit_pages,
    selected_page_key,
)
from am.sidebar import render_sidebar


# Compatibility for tests and small scripts that historically imported the
# monolithic app.py.  Values are resolved only when requested, preserving the
# lazy startup contract of the page architecture.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "CHINA_AIRLINE_SERIES_LABELS": ("am.config", "CHINA_AIRLINE_SERIES_LABELS"),
    "CHINA_AIRLINE_SERIES_LABELS_ZH": (
        "am.config",
        "CHINA_AIRLINE_SERIES_LABELS_ZH",
    ),
    "ETF_ACTIVITY_CNY_PER_YI": ("am.config", "ETF_ACTIVITY_CNY_PER_YI"),
    "OVERVIEW_FEATURED_CHARTS": ("am.config", "OVERVIEW_FEATURED_CHARTS"),
    "OVERVIEW_PULSE_CONFIG": ("am.config", "OVERVIEW_PULSE_CONFIG"),
    "SECTORS": ("am.config", "SECTORS"),
    "STYLE_CATEGORIES": ("am.market_us", "STYLE_CATEGORIES"),
    "STYLE_CATEGORY_LABELS": ("am.market_us", "STYLE_CATEGORY_LABELS"),
    "_compute_rsi_series": ("am.market", "_compute_rsi_series"),
    "_market_etf_activity_frame": ("am.market", "_market_etf_activity_frame"),
    "_market_label": ("am.market", "_market_label"),
    "_market_pair_history_frame": ("am.market", "_market_pair_history_frame"),
    "_market_price_frame": ("am.market", "_market_price_frame"),
    "build_cross_asset_return_heatmap_figure": (
        "am.regime_evidence",
        "build_cross_asset_return_heatmap_figure",
    ),
    "combined_dataset_index": ("am.explorer", "combined_dataset_index"),
    "cross_asset_return_heatmap_frame": (
        "am.regime_evidence",
        "cross_asset_return_heatmap_frame",
    ),
    "index_style_key": ("am.market_page", "index_style_key"),
    "latest_metric_reading": ("am.core", "latest_metric_reading"),
    "latest_series_reading": ("am.core", "latest_series_reading"),
    "line_view_frame": ("am.core", "line_view_frame"),
    "localize_coverage": ("am.core", "localize_coverage"),
    "localized_source_health_frame": (
        "am.core",
        "localized_source_health_frame",
    ),
    "normalize_index_style": ("am.market_page", "normalize_index_style"),
    "observation_date_label": ("am.core", "observation_date_label"),
    "regime_alert_decision_view": ("am.regime", "regime_alert_decision_view"),
    "regime_daily_brief_items": ("am.regime", "regime_daily_brief_items"),
    "regime_data_warnings": ("am.regime", "regime_data_warnings"),
    "regime_visual_state": ("am.regime", "regime_visual_state"),
    "render_market_index_detail": ("am.market", "render_market_index_detail"),
    "render_market_leadership_chart": (
        "am.market",
        "render_market_leadership_chart",
    ),
    "render_relative_regime": ("am.market", "render_relative_regime"),
    "render_southbound_market_flow": (
        "am.market_us",
        "render_southbound_market_flow",
    ),
    "sparkline_context": ("am.core", "sparkline_context"),
    "view_label": ("am.core", "view_label"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def load_sector_artifacts(
    language: str,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    list[str],
]:
    """Compatibility alias for aggregate callers from the monolithic app."""
    return load_all_sector_artifacts(language)


def main() -> None:
    st.set_page_config(
        page_title="Asia Markets",
        page_icon="🌏",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    style_app()

    pages = build_streamlit_pages()
    selected = st.navigation(list(pages.values()), position="hidden")
    current_page_key = selected_page_key(selected, pages)

    # Migrate the former session-state router once.  This preserves existing
    # bookmarked test/session state while URL-backed pages become canonical.
    legacy_page_key = st.session_state.pop("page", None)
    if (
        isinstance(legacy_page_key, str)
        and legacy_page_key in pages
        and legacy_page_key != current_page_key
    ):
        st.switch_page(pages[legacy_page_key])

    language_hint = st.session_state.get("language_choice", "中文")
    initial_language = "zh" if language_hint == "中文" else "en"
    render_sidebar(
        initial_language,
        current_page_key,
        pages,
        PAGE_DEFINITIONS,
    )
    selected.run()


if __name__ == "__main__":
    main()
