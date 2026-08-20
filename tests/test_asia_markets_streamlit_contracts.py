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
