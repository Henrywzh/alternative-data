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


class _RecordingStreamlit:
    """Captures what a render function hands to Streamlit.

    render_relative_regime and render_market_index_detail are ~200 and ~380
    lines that only a "did not raise" smoke test has ever run. Driving them
    with a recorder makes their data transforms assertable without pulling
    them apart while another session is editing the file.
    """

    def __init__(self, selections: dict | None = None) -> None:
        self.selections = selections or {}
        self.figures: list = []
        self.infos: list[str] = []
        self.captions: list[str] = []
        self.options: dict[str, list] = {}

    def _pick(self, label, options, key=None, **kwargs):
        options = list(options)
        self.options[str(key or label)] = options
        chosen = self.selections.get(str(key or label))
        return chosen if chosen is not None else (options[0] if options else None)

    segmented_control = _pick
    pills = _pick

    def radio(self, label, options, **kwargs):
        return self._pick(label, options, key=kwargs.get("key"))

    def selectbox(self, label, options, **kwargs):
        return self._pick(label, options, key=kwargs.get("key"))

    def plotly_chart(self, fig, **kwargs):
        self.figures.append(fig)

    def info(self, text, **kwargs):
        self.infos.append(str(text))

    def caption(self, text, **kwargs):
        self.captions.append(str(text))

    def columns(self, spec, **kwargs):
        count = spec if isinstance(spec, int) else len(list(spec))
        return [_RecordingStreamlit._Slot(self) for _ in range(max(count, 1))]

    def container(self, *args, **kwargs):
        return _RecordingStreamlit._Slot(self)

    expander = container
    empty = container

    def __getattr__(self, name):
        def _noop(*args, **kwargs):
            return None
        return _noop

    class _Slot:
        """Stands in for a column/container: a context manager that also
        forwards the recording calls made inside it."""

        def __init__(self, parent: "_RecordingStreamlit") -> None:
            self._parent = parent

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __getattr__(self, name):
            return getattr(self._parent, name)


def _regime_fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    summary = pd.DataFrame(
        [
            {"pair_id": "cross_pair", "region": "Cross", "numerator_id": "csi300",
             "denominator_id": "sp500", "ratio": 1.2, "zscore": 0.4},
            {"pair_id": "china_pair", "region": "China", "numerator_id": "csi500",
             "denominator_id": "csi300", "ratio": 0.9, "zscore": -1.1},
            {"pair_id": "hk_pair", "region": "HK", "numerator_id": "hstech",
             "denominator_id": "hsi", "ratio": 1.05, "zscore": 0.2},
        ]
    )
    dates = pd.date_range("2026-01-01", periods=40, freq="D")
    history = pd.concat(
        [
            pd.DataFrame({"pair_id": pair, "date": dates,
                          "ratio": [1.0 + i / 100 for i in range(len(dates))],
                          "ratio_ma": [1.0 for _ in range(len(dates))]})
            for pair in ("cross_pair", "china_pair", "hk_pair")
        ],
        ignore_index=True,
    )
    return summary, history


def test_relative_regime_orders_markets_china_first(monkeypatch) -> None:
    """Region order is fixed, not whatever order the summary arrives in.

    The fixture deliberately lists Cross first; a sorted() or first-seen
    ordering would put Cross or China at the front by accident.
    """
    app = _app_module()
    recorder = _RecordingStreamlit()
    monkeypatch.setattr(app, "st", recorder)
    summary, history = _regime_fixture()

    app.render_relative_regime(summary, history, "en", "1 year")

    # sorted() would give China, Cross, HK; first-seen would give Cross first.
    assert recorder.options["market_pair_region"] == ["China", "HK", "Cross"]


def test_relative_regime_charts_only_the_selected_pair(monkeypatch) -> None:
    """The cohort filter is what keeps one market's pair out of another's."""
    app = _app_module()
    recorder = _RecordingStreamlit(selections={"market_pair_region": "HK"})
    monkeypatch.setattr(app, "st", recorder)
    summary, history = _regime_fixture()

    app.render_relative_regime(summary, history, "en", "1 year")

    assert recorder.options["market_pair_select"] == ["hk_pair"]
    assert recorder.figures, "the selected pair should have produced a chart"


def test_relative_regime_says_so_when_a_pair_has_no_history(monkeypatch) -> None:
    """Empty history used to be indistinguishable from a flat line."""
    app = _app_module()
    recorder = _RecordingStreamlit()
    monkeypatch.setattr(app, "st", recorder)
    summary, _ = _regime_fixture()

    app.render_relative_regime(summary, pd.DataFrame(), "en", "1 year")

    assert any("history" in text.lower() for text in recorder.infos)
    assert not recorder.figures


def _detail_fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2026-01-01", periods=90, freq="D")
    prices = pd.concat(
        [
            pd.DataFrame({"exposure_id": exposure, "date": dates.strftime("%Y-%m-%d"),
                          "close": [base + i * 0.5 for i in range(len(dates))]})
            for exposure, base in (("csi300", 3800.0), ("csi500", 6000.0))
        ],
        ignore_index=True,
    )
    prices["_date"] = pd.to_datetime(prices["date"])
    technicals = pd.DataFrame(
        [
            {"exposure_id": "csi300", "rsi14": 58.0, "ma20_pct": 1.4,
             "avg_premium_30d": 0.35, "avg_premium_days": 30, "drawdown_60d": -4.2},
            {"exposure_id": "csi500", "rsi14": 71.0, "ma20_pct": 3.1,
             "avg_premium_30d": -0.10, "avg_premium_days": 5, "drawdown_60d": -1.0},
        ]
    )
    wrappers = pd.DataFrame(
        [
            {"exposure_id": "csi300", "fund_id": "510300", "ticker": "510300",
             "fund_name": "Big CSI300 ETF", "premium_pct": 0.2, "peer_rank": 1},
            {"exposure_id": "csi500", "fund_id": "510500", "ticker": "510500",
             "fund_name": "Other ETF", "premium_pct": -0.4, "peer_rank": 1},
        ]
    )
    return prices, technicals, wrappers


def test_index_detail_plots_only_the_requested_exposure(monkeypatch) -> None:
    """Every frame it receives holds all exposures; the filter is the contract.

    380 lines had never been run by anything but a "did not raise" smoke
    test, so nothing checked that asking for csi300 does not chart csi500.
    """
    app = _app_module()
    recorder = _RecordingStreamlit()
    monkeypatch.setattr(app, "st", recorder)
    prices, technicals, wrappers = _detail_fixture()

    app.render_market_index_detail(
        "csi300", "CSI 300", prices, technicals, wrappers, "en", "1 year"
    )

    assert recorder.figures, "the index chart should have been drawn"
    plotted = [
        float(value)
        for figure in recorder.figures
        for trace in figure.data
        for value in (list(trace.y) if getattr(trace, "y", None) is not None else [])
        if value is not None and value == value
    ]
    price_points = [value for value in plotted if value > 1000]
    assert price_points, "no price series was plotted"
    # csi300 runs 3800..3844.5; csi500 starts at 6000, so any value that high
    # means the other exposure's rows were charted too.
    assert max(price_points) < 4000, f"charted a foreign exposure: max {max(price_points)}"


def test_index_detail_names_the_window_its_premium_average_covers(monkeypatch) -> None:
    """A five-day mean labelled "30D" is the failure this guards.

    The card reads its own avg_premium_days rather than assuming the column
    name is the truth.
    """
    app = _app_module()
    prices, technicals, wrappers = _detail_fixture()

    labels = {}
    for exposure in ("csi300", "csi500"):
        recorder = _RecordingStreamlit()
        monkeypatch.setattr(app, "st", recorder)
        captured: list[str] = []
        recorder.metric = lambda label, *a, **k: captured.append(str(label))
        app.render_market_index_detail(
            exposure, exposure, prices, technicals, wrappers, "en", "1 year"
        )
        labels[exposure] = captured

    assert any("30D" in text for text in labels["csi300"])
    assert any("5D" in text for text in labels["csi500"])
    assert not any("30D" in text for text in labels["csi500"])


def test_index_detail_survives_an_exposure_with_no_technicals(monkeypatch) -> None:
    app = _app_module()
    recorder = _RecordingStreamlit()
    monkeypatch.setattr(app, "st", recorder)
    prices, _, wrappers = _detail_fixture()

    app.render_market_index_detail(
        "csi300", "CSI 300", prices, pd.DataFrame(columns=["exposure_id"]), wrappers, "en", "1 year"
    )

    assert recorder.figures


def test_the_deployed_app_imports_domain_packages_by_their_real_name() -> None:
    """`src.` only resolves by accident, and it stopped resolving in production.

    src has no __init__.py, so `src.market_monitor` is a PEP 420 namespace
    package: any installed distribution shipping a top-level `src` wins over
    the repo directory and the import raises. That is what took the deployed
    Streamlit app down -- render_market's very first statement was
    `from src.market_monitor.config import market_tab_exposures`.

    pyproject maps these to the top level already (package-dir = {"" = "src"}),
    so market_monitor is the name that does not depend on path luck.
    """
    source = APP_PATH.read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("from src.", "import src."))
    ]

    assert not offenders, "import these as top-level packages instead:\n" + "\n".join(offenders)


def test_the_app_puts_src_on_sys_path_so_those_imports_resolve() -> None:
    source = APP_PATH.read_text(encoding="utf-8")

    assert 'SRC_ROOT = REPO_ROOT / "src"' in source
    assert "sys.path.insert(0, str(SRC_ROOT))" in source
