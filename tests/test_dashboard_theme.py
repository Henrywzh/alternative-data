from __future__ import annotations

import re

from dashboard.theme import _DASHBOARD_CSS


def test_streamlit_toolbar_remains_visible_for_sidebar_reopen_control() -> None:
    toolbar_rule = re.search(
        r'\[data-testid="stToolbar"\]\s*\{(?P<body>[^}]*)\}',
        _DASHBOARD_CSS,
    )

    assert toolbar_rule is not None
    body = toolbar_rule.group("body")
    assert "visibility: visible !important" in body
    assert "display: flex !important" in body


def test_streamlit_header_is_transparent_without_losing_controls() -> None:
    header_rule = re.search(
        r'\[data-testid="stHeader"\]\s*\{(?P<body>[^}]*)\}',
        _DASHBOARD_CSS,
    )

    assert header_rule is not None
    body = header_rule.group("body")
    assert "background-color: transparent !important" in body
    assert "box-shadow: none !important" in body

    global_rule = re.search(r'/\* Global overrides \*/(?P<body>.*?)/\* Sidebar styles \*/', _DASHBOARD_CSS, re.S)
    assert global_rule is not None
    assert '[data-testid="stHeader"]' not in global_rule.group("body")
