"""Smoke tests for Streamlit pages against published artifact contracts."""

from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
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


def test_every_config_style_maps_explicitly() -> None:
    """An unknown style renders under 宽基大盘 with nothing to notice.

    normalize_index_style falls back to "broad" so a page never fails to
    render, which means a new style spelling in config.py -- "Commodity",
    "Bond" -- would silently join the Broad Benchmark pill. This is the signal
    that fallback otherwise swallows: add a rule to _STYLE_RULES.
    """
    from market_monitor.config import EXPOSURES

    app = _app_module()
    unmatched = sorted(
        {
            str(e.get("style"))
            for e in EXPOSURES
            if app.index_style_key(e.get("style", "")) is None
        }
    )
    assert not unmatched, f"styles matching no rule in _STYLE_RULES: {unmatched}"


def test_us_sector_funds_are_not_filed_as_broad_benchmarks() -> None:
    """XLK/XLU/XLV and friends sat under the Broad Benchmark pill.

    Their config style was "Broad", so clicking 宽基大盘 listed six sector
    funds alongside CSI 300 and the Hang Seng Index.
    """
    from market_monitor.config import EXPOSURES

    app = _app_module()
    by_id = {e["exposure_id"]: e for e in EXPOSURES}
    for eid in (
        "us_tech",
        "us_discretionary",
        "us_communication",
        "us_staples",
        "us_utilities",
        "us_healthcare",
    ):
        assert app.normalize_index_style(by_id[eid]["style"]) == "sector", eid

    # The Dow is price-weighted blue chips; it was filed as Dividend / Value
    # only because its style string contained the word "Value".
    assert app.normalize_index_style(by_id["dow"]["style"]) == "broad"


def test_exposure_labels_are_unique_in_both_languages() -> None:
    """Two exposures sharing a label put the same name in the picker twice.

    russell2000 (the ^RUT index) and us_small (the IWM fund) were both
    labelled "Russell 2000"; both are in the US scope, so the index picker
    listed it twice with no way to tell them apart.
    """
    from market_monitor.config import EXPOSURES

    for field in ("label", "label_zh"):
        seen: dict[str, str] = {}
        for exposure in EXPOSURES:
            value = str(exposure.get(field, ""))
            assert value, f"{exposure['exposure_id']} has no {field}"
            assert value not in seen, (
                f"{field} {value!r} is shared by {seen[value]} and {exposure['exposure_id']}"
            )
            seen[value] = exposure["exposure_id"]


def test_every_region_tab_can_show_the_ratio_view_at_once() -> None:
    """Two tabs in Ratio mode crashed the whole ETF Monitor page.

    render_market_ratio_chart hardcoded key="market_ratio_num"/"..._den"
    while every region tab calls it, and st.tabs evaluates all five tab bodies
    on every run -- so the second tab switched to Ratio raised
    StreamlitDuplicateElementKey and took the page down.

    test_every_page_renders_in_both_languages cannot catch this: it renders
    with default widget state and never switches a view.
    """
    app = AppTest.from_file(str(APP_PATH), default_timeout=120)
    app.session_state["page"] = "market"
    app.session_state["language_choice"] = "English"
    for tab_key in ("china", "us", "apac", "emea", "global"):
        app.session_state[f"market_leadership_mode_{tab_key}"] = "Ratio (A/B)"
    app.run()

    assert not app.exception, [str(error) for error in app.exception]


# --- render-layer data transforms -------------------------------------
# These four turn raw artifact records into the frames every ETF Monitor chart
# reads. They had no tests: the only coverage over the render layer was
# test_every_page_renders_in_both_languages, which asserts that rendering does
# not raise and nothing about what it produces. Every defect found in this
# area so far -- duplicate pills, labels reduced to exposure ids, column names
# leaking into legends -- rendered without raising.


def test_market_price_frame_types_sorts_and_drops_unusable_rows() -> None:
    app = _app_module()
    frame = app._market_price_frame(
        {
            "index_price_daily_tail": [
                {"exposure_id": "csi300", "date": "2026-08-21", "close": "4100.5"},
                {"exposure_id": "csi300", "date": "2026-08-19", "close": "4000"},
                {"exposure_id": "csi300", "date": "not-a-date", "close": "4050"},
                {"exposure_id": "csi300", "date": "2026-08-20", "close": "n/a"},
            ]
        }
    )
    # The unparseable date and the unparseable close are dropped, not carried
    # as NaT/NaN into a chart.
    assert len(frame) == 2
    assert list(frame["_date"]) == [pd.Timestamp("2026-08-19"), pd.Timestamp("2026-08-21")]
    assert list(frame["close"]) == [4000.0, 4100.5]
    assert pd.api.types.is_numeric_dtype(frame["close"])


def test_market_price_frame_is_empty_when_the_dataset_lacks_its_columns() -> None:
    """A shape change upstream must not raise inside a chart."""
    app = _app_module()
    assert app._market_price_frame({}).empty
    assert app._market_price_frame({"index_price_daily_tail": []}).empty
    assert app._market_price_frame(
        {"index_price_daily_tail": [{"exposure_id": "csi300", "date": "2026-08-21"}]}
    ).empty


def test_market_pair_history_frame_coerces_every_numeric_column() -> None:
    """ratio_ma and zscore are optional; when present they must be numeric.

    A string zscore plots as a category axis rather than raising, which is the
    failure mode this whole area keeps producing.
    """
    app = _app_module()
    frame = app._market_pair_history_frame(
        {
            "relative_pair_history": [
                {"pair_id": "cn_small_large", "date": "2026-08-21", "ratio": "1.05",
                 "ratio_ma": "1.02", "zscore": "0.51"},
                {"pair_id": "cn_small_large", "date": "2026-08-20", "ratio": "1.04",
                 "ratio_ma": "", "zscore": None},
                {"pair_id": "cn_small_large", "date": "2026-08-19", "ratio": "bad",
                 "ratio_ma": "1.00", "zscore": "0.4"},
            ]
        }
    )
    assert len(frame) == 2
    assert list(frame["_date"]) == [pd.Timestamp("2026-08-20"), pd.Timestamp("2026-08-21")]
    for column in ("ratio", "ratio_ma", "zscore"):
        assert pd.api.types.is_numeric_dtype(frame[column]), column


def test_market_label_falls_back_to_english_when_no_chinese_label_exists() -> None:
    app = _app_module()
    row = pd.Series({"exposure_id": "csi300", "label": "CSI 300", "label_zh": "沪深300"})
    assert app._market_label(row, "zh") == "沪深300"
    assert app._market_label(row, "en") == "CSI 300"

    blank = pd.Series({"exposure_id": "csi300", "label": "CSI 300", "label_zh": "  "})
    assert app._market_label(blank, "zh") == "CSI 300"

    missing = pd.Series({"exposure_id": "csi300", "label": "CSI 300"})
    assert app._market_label(missing, "zh") == "CSI 300"
