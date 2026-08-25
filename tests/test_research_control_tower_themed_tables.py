"""ct_dataframe: the themed table that replaced st.dataframe."""

from __future__ import annotations

import re

import pandas as pd
import pytest

from control_tower import components


@pytest.fixture
def rendered(monkeypatch):
    def _render(frame, **kwargs):
        captured: dict[str, str] = {}
        monkeypatch.setattr(components.st, "markdown", lambda html, **k: captured.setdefault("html", html))
        monkeypatch.setattr(components.st, "caption", lambda text, **k: captured.setdefault("caption", str(text)))
        components.ct_dataframe(frame, **kwargs)
        return captured

    return _render


def test_tables_render_as_dom_so_the_theme_reaches_them(rendered) -> None:
    """st.dataframe paints to a canvas from Streamlit's own theme.

    The --gdg-* variables were reaching the element and the grid ignored
    them, so every table stayed white on a dark page. A real table element
    picks up --ct-* like the rest of the app.
    """
    html = rendered(pd.DataFrame({"Source": ["Akshare"], "Rows": [21]}))["html"]

    assert 'class="ct-table-scroll"' in html
    assert "ct-table" in html
    assert "<table" in html


def test_a_missing_value_never_reads_as_a_value(rendered) -> None:
    """to_html's na_rep misses a literal None, which prints as "None"."""
    frame = pd.DataFrame(
        {
            "Nullable": pd.array([1.5, None], dtype="Float64"),
            "Object": ["ok", None],
            "Float": [1.0, float("nan")],
        }
    )
    html = rendered(frame)["html"]

    assert "None" not in re.sub(r"<[^>]+>", "", html)
    assert html.count("—") == 3


def test_a_nullable_integer_column_keeps_whole_numbers(rendered) -> None:
    """Formatting is decided per column dtype, not per value.

    .map() over a nullable integer column with a missing entry yields Python
    floats, so a per-value check saw a float and rendered a row count of
    44,686 as 44,686.0000.
    """
    frame = pd.DataFrame({"Rows": pd.array([44686, None], dtype="Int64")})
    html = rendered(frame)["html"]

    assert "44686" in html
    assert "44,686.0000" not in html


def test_floats_keep_the_precision_the_grid_showed(rendered) -> None:
    """astype(object) hands rendering to str(): 2.253025 instead of 2.2530."""
    frame = pd.DataFrame(
        {
            "WithGap": pd.array([2.253025, None], dtype="Float64"),
            "Clean": [0.00451234, 10.89821],
        }
    )
    html = rendered(frame)["html"]

    assert "2.2530" in html and "2.253025" not in html
    assert "0.0045" in html and "0.00451234" not in html


def test_cell_content_is_escaped(rendered) -> None:
    """The frames carry vendor-supplied text and this renders raw HTML."""
    html = rendered(pd.DataFrame({"Title": ["<script>alert(1)</script>"]}))["html"]

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_an_empty_frame_says_so_rather_than_drawing_a_bare_header(rendered) -> None:
    assert rendered(pd.DataFrame())["caption"] == "No rows."


def test_the_index_is_hidden_by_default_as_every_call_site_asked(rendered) -> None:
    frame = pd.DataFrame({"Value": [10, 20]}, index=["alpha", "beta"])

    assert "alpha" not in rendered(frame)["html"]
    assert "alpha" in rendered(frame, hide_index=False)["html"]


def test_no_call_site_still_reaches_for_st_dataframe() -> None:
    """The grid ignores this app's CSS, so one leftover is one white table."""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "apps" / "research-control-tower"
    hits = subprocess.run(
        ["grep", "-rn", r"\bst\.dataframe(", str(root)],
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert not hits, f"st.dataframe still called:\n{hits}"
