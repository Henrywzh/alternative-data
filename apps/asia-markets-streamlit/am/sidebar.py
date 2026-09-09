"""Custom bilingual sidebar for hidden Streamlit page navigation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import streamlit as st

from .config import HISTORY_WINDOWS, SECTORS
from .core import tr


SIDEBAR_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("workspace", ("overview",)),
    ("markets", ("market", "regime")),
    (
        "hong_kong",
        (
            "labour",
            "population",
            "real_estate",
            "transport",
            "aerospace",
            "crypto",
        ),
    ),
    ("data", ("data", "health")),
)

GROUP_LABELS = {
    "workspace": ("Workspace", "工作台"),
    "markets": ("Markets", "市场"),
    "hong_kong": ("Hong Kong", "香港"),
    "data": ("Data", "数据"),
}


def active_language() -> str:
    return "zh" if st.session_state.get("language_choice", "中文") == "中文" else "en"


def render_sidebar(
    initial_language: str,
    current_page_key: str,
    pages: Mapping[str, Any],
    page_definitions: Sequence[Any],
) -> tuple[str, str]:
    """Render full-width navigation and return language/history state."""
    definition_by_key = {definition.key: definition for definition in page_definitions}
    with st.sidebar:
        st.markdown(
            '<div class="am-brand"><div class="am-brand-mark">AM</div>'
            '<div><div class="am-brand-name">Asia Markets</div>'
            '<div class="am-brand-sub">Private research terminal</div></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="am-sidebar-group-label">'
            f'{tr(initial_language, "Preferences", "偏好设置")}</div>',
            unsafe_allow_html=True,
        )
        language_choice = st.selectbox(
            "Language / 语言",
            ["English", "中文"],
            index=1 if initial_language == "zh" else 0,
            key="language_choice",
        )
        language = "zh" if language_choice == "中文" else "en"

        for group_key, page_keys in SIDEBAR_GROUPS:
            group_en, group_zh = GROUP_LABELS[group_key]
            st.markdown(
                f'<div class="am-sidebar-group-label">'
                f"{tr(language, group_en, group_zh)}</div>",
                unsafe_allow_html=True,
            )
            for page_key in page_keys:
                definition = definition_by_key[page_key]
                clicked = st.button(
                    definition.label(language),
                    key=f"sidebar_nav_{page_key}",
                    type="primary" if current_page_key == page_key else "secondary",
                    width="stretch",
                )
                if clicked:
                    st.switch_page(pages[page_key])

        st.divider()
        history_window = st.selectbox(
            tr(language, "Default history window", "默认历史范围"),
            list(HISTORY_WINDOWS),
            index=0,
            key="history_window",
            help=tr(
                language,
                "The source grain is preserved; shorter source histories show all available rows.",
                "保留来源粒度；来源历史较短时显示全部可用数据。",
            ),
        )
        st.divider()
        st.caption(tr(language, "V1 scope", "V1 范围"))
        st.caption(
            tr(
                language,
                f"{len(SECTORS)} connected research sections",
                f"{len(SECTORS)} 个已接入研究板块",
            )
        )
    return language, history_window
