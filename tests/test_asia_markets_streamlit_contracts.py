"""Smoke tests for Streamlit pages against published artifact contracts."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-streamlit" / "app.py"


def _dispatched_pages() -> list[str]:
    """Every page ``main()`` can route to, read out of the dispatch itself.

    A hand-maintained list is the thing that failed: the smoke test ran two
    pages in both languages while eight others -- including the ETF monitor,
    whose Chinese half raised KeyError in production -- had never been
    rendered by any test. Deriving the list means a page cannot be added
    without being covered.
    """
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    main = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    pages = {
        comparator.value
        for node in ast.walk(main)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "page"
        for comparator in node.comparators
        if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str)
    }
    # If the dispatch is ever refactored into a table this parse returns
    # nothing, and a test that silently covers zero pages is worse than no
    # test at all. Fail loudly instead, so whoever refactors updates this.
    assert len(pages) >= 10, f"page discovery found only {sorted(pages)}"
    return sorted(pages)


DISPATCHED_PAGES = _dispatched_pages()


@pytest.mark.parametrize("page", DISPATCHED_PAGES)
@pytest.mark.parametrize("language_choice", ["English", "中文"])
def test_every_page_renders_in_both_languages(page: str, language_choice: str) -> None:
    """Rendering must not raise, in either language, on the shipped artifacts.

    Both languages matter on their own: the ETF monitor crashed only in
    Chinese, because only the Chinese path renamed a column and then indexed
    with the pre-rename name.
    """
    app = AppTest.from_file(str(APP_PATH), default_timeout=120)
    app.session_state["page"] = page
    app.session_state["language_choice"] = language_choice
    app.run()

    assert not app.exception, [str(error) for error in app.exception]


def _app_module():
    """Import app.py as a module so its helpers can be tested directly."""
    import importlib.util
    import sys

    app_dir = str(APP_PATH.parent)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    spec = importlib.util.spec_from_file_location("_asia_markets_app", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_index_style_pills_have_one_entry_per_category() -> None:
    """The pills carried the raw config string as their identity.

    config.py spells one idea three ways -- "Tech / Growth", "Growth" and
    "Tech / Semis" -- while the Chinese label for all three is 科技成长, so the
    row rendered 科技成长 twice and 红利价值 twice.
    """
    from market_monitor.config import EXPOSURES

    app = _app_module()
    keys = {app.normalize_index_style(e.get("style", "Broad")) for e in EXPOSURES}
    labels_zh = {app.STYLE_CATEGORY_LABELS[k][1] for k in keys}
    labels_en = {app.STYLE_CATEGORY_LABELS[k][0] for k in keys}
    assert len(labels_zh) == len(keys), "two categories share a Chinese label"
    assert len(labels_en) == len(keys), "two categories share an English label"

    # The spellings that actually collided in config.
    assert app.normalize_index_style("Tech / Growth") == app.normalize_index_style("Growth")
    assert app.normalize_index_style("Tech / Semis") == app.normalize_index_style("Growth")
    assert app.normalize_index_style("Dividend / Value") == app.normalize_index_style("Value")


def test_index_style_pill_order_does_not_follow_the_data() -> None:
    """Pill order came from insertion order, so it reshuffled per section.

    Two sections of the same page rendered the row in different orders, and
    neither matched any declared order.
    """
    app = _app_module()

    def ordered(styles: list[str]) -> list[str]:
        present = {app.normalize_index_style(s) for s in styles}
        return [key for key, _en, _zh in app.STYLE_CATEGORIES if key in present]

    styles = ["Growth", "Broad", "Sector", "Value"]
    assert ordered(styles) == ordered(list(reversed(styles)))
    assert ordered(styles) == ["broad", "tech_growth", "value_dividend", "sector"]
