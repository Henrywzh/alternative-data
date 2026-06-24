from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from google_trends_data.automation import GoogleTrendsWatchlistRunner, load_watchlist
from google_trends_data.csv_importer import parse_interest_over_time_csv
from google_trends_data.exporter import GoogleTrendsCsvExporter
from google_trends_data.models import StockDataPoint, TrendsDataPoint


FIXTURES = Path(__file__).parent / "fixtures"


class _FakeExporter:
    def __init__(self, exports: dict[tuple[str, str], Path], *, fail_on: tuple[str, str] | None = None) -> None:
        self.exports = exports
        self.fail_on = fail_on
        self.calls: list[tuple[str, str]] = []

    def export_interest_over_time(
        self,
        *,
        keyword: str,
        geo: str,
        timeframe: str,
        hl: str,
        output_dir: Path,
        headless: bool,
    ) -> Path:
        key = (keyword, geo)
        self.calls.append(key)
        if self.fail_on == key:
            raise RuntimeError(f"export failed for {keyword}/{geo}")
        return self.exports[key]


class _FakeStockFetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def fetch(self, *, ticker: str, period: str, interval: str = "1d") -> list[StockDataPoint]:
        self.calls.append((ticker, period))
        return [
            StockDataPoint(
                date="2024-01-05",
                ticker=ticker,
                open=10.0,
                high=11.0,
                low=9.0,
                close=10.0,
                adj_close=10.0,
                volume=100,
                fetched_at="2026-06-21T00:00:00Z",
            ),
            StockDataPoint(
                date="2024-01-12",
                ticker=ticker,
                open=10.5,
                high=11.5,
                low=10.0,
                close=11.0,
                adj_close=11.0,
                volume=120,
                fetched_at="2026-06-21T00:00:00Z",
            ),
            StockDataPoint(
                date="2024-01-19",
                ticker=ticker,
                open=11.0,
                high=12.0,
                low=10.5,
                close=12.0,
                adj_close=12.0,
                volume=140,
                fetched_at="2026-06-21T00:00:00Z",
            ),
        ]


class _FakeTrendsFetcher:
    def __init__(self, *, fail_on: tuple[str, str] | None = None) -> None:
        self.fail_on = fail_on
        self.calls: list[tuple[str, str, str]] = []

    def fetch(self, *, keyword: str, geo: str = "", timeframe: str = "today 5-y") -> list[TrendsDataPoint]:
        self.calls.append((keyword, geo, timeframe))
        if self.fail_on == (keyword, geo):
            raise RuntimeError(f"fetch failed for {keyword}/{geo}")
        return [
            TrendsDataPoint(
                date="2024-01-07T00:00:00+00:00",
                keyword=keyword,
                geo=geo,
                trend_value=62,
                is_partial=False,
                fetched_at="2026-06-21T00:00:00Z",
            ),
            TrendsDataPoint(
                date="2024-01-14T00:00:00+00:00",
                keyword=keyword,
                geo=geo,
                trend_value=66,
                is_partial=False,
                fetched_at="2026-06-21T00:00:00Z",
            ),
            TrendsDataPoint(
                date="2024-01-21T00:00:00+00:00",
                keyword=keyword,
                geo=geo,
                trend_value=70,
                is_partial=True,
                fetched_at="2026-06-21T00:00:00Z",
            ),
        ]


def _write_watchlist(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "ticker": "TSLA",
                    "name": "Tesla",
                    "enabled": True,
                    "keywords": [
                        {"term": "Tesla", "geo": ""},
                        {"term": "Tesla Model Y", "geo": "US"},
                    ],
                },
                {
                    "ticker": "ABNB",
                    "name": "Airbnb",
                    "enabled": False,
                    "keywords": [
                        {"term": "Airbnb", "geo": ""},
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )


def test_parse_interest_over_time_csv_reads_standard_export() -> None:
    records = parse_interest_over_time_csv(
        FIXTURES / "google_trends_interest_over_time_standard.csv",
        keyword="Tesla",
        geo="",
        fetched_at="2026-06-21T00:00:00Z",
    )

    assert [record.date for record in records] == ["2024-01-07", "2024-01-14", "2024-01-21"]
    assert [record.trend_value for record in records] == [62, 66, 70]
    assert [record.is_partial for record in records] == [False, False, True]


def test_parse_interest_over_time_csv_accepts_metadata_rows_and_geo_label() -> None:
    records = parse_interest_over_time_csv(
        FIXTURES / "google_trends_interest_over_time_geo.csv",
        keyword="Nike",
        geo="US",
        fetched_at="2026-06-21T00:00:00Z",
    )

    assert len(records) == 2
    assert records[0].keyword == "Nike"
    assert records[0].geo == "US"
    assert records[1].trend_value == 58


def test_parse_interest_over_time_csv_rejects_missing_value_column() -> None:
    with pytest.raises(ValueError, match="value column"):
        parse_interest_over_time_csv(
            FIXTURES / "google_trends_interest_over_time_missing_value.csv",
            keyword="Tesla",
            geo="",
            fetched_at="2026-06-21T00:00:00Z",
        )


def test_load_watchlist_returns_enabled_entries_only(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.json"
    _write_watchlist(watchlist_path)

    enabled_only = load_watchlist(watchlist_path)

    assert [item["ticker"] for item in enabled_only] == ["TSLA"]


def test_watchlist_runner_refresh_ticker_writes_expected_outputs(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.json"
    _write_watchlist(watchlist_path)
    exporter = _FakeExporter(
        {
            ("Tesla", ""): FIXTURES / "google_trends_interest_over_time_standard.csv",
            ("Tesla Model Y", "US"): FIXTURES / "google_trends_interest_over_time_standard.csv",
        }
    )
    stock_fetcher = _FakeStockFetcher()

    runner = GoogleTrendsWatchlistRunner(
        base_dir=tmp_path,
        watchlist_path=watchlist_path,
        exporter=exporter,
        stock_fetcher=stock_fetcher,
    )

    result = runner.refresh_ticker("TSLA")

    assert result["tickers"] == 1
    assert result["keyword_pairs"] == 2
    assert stock_fetcher.calls == [("TSLA", "5y")]
    assert exporter.calls == [("Tesla", ""), ("Tesla Model Y", "US")]

    raw_dir = tmp_path / "data" / "raw" / "google_trends"
    processed_dir = tmp_path / "data" / "processed" / "google_trends"
    assert (raw_dir / "tesla_worldwide_trends.parquet").exists()
    assert (raw_dir / "tesla_model_y_us_trends.parquet").exists()
    assert (raw_dir / "tsla_stock_daily.parquet").exists()
    assert (processed_dir / "tesla_worldwide_tsla_combined.parquet").exists()
    assert (processed_dir / "tesla_model_y_us_tsla_combined.parquet").exists()

    combined = pd.read_parquet(processed_dir / "tesla_worldwide_tsla_combined.parquet")
    assert list(combined["trend_value"]) == [62, 66, 70]


def test_watchlist_runner_raises_without_writing_partial_outputs(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.json"
    _write_watchlist(watchlist_path)
    exporter = _FakeExporter(
        {
            ("Tesla", ""): FIXTURES / "google_trends_interest_over_time_standard.csv",
            ("Tesla Model Y", "US"): FIXTURES / "google_trends_interest_over_time_standard.csv",
        },
        fail_on=("Tesla Model Y", "US"),
    )

    runner = GoogleTrendsWatchlistRunner(
        base_dir=tmp_path,
        watchlist_path=watchlist_path,
        exporter=exporter,
        stock_fetcher=_FakeStockFetcher(),
    )

    with pytest.raises(RuntimeError, match="export failed"):
        runner.refresh_ticker("TSLA")

    assert not (tmp_path / "data" / "raw" / "google_trends").exists()
    assert not (tmp_path / "data" / "processed" / "google_trends").exists()


def test_watchlist_runner_validate_parses_first_enabled_keyword_without_writing(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.json"
    _write_watchlist(watchlist_path)
    exporter = _FakeExporter({("Tesla", ""): FIXTURES / "google_trends_interest_over_time_standard.csv"})

    runner = GoogleTrendsWatchlistRunner(
        base_dir=tmp_path,
        watchlist_path=watchlist_path,
        exporter=exporter,
        stock_fetcher=_FakeStockFetcher(),
    )

    result = runner.validate()

    assert result["keyword"] == "Tesla"
    assert result["geo"] == ""
    assert result["rows"] == 3
    assert exporter.calls == [("Tesla", "")]
    assert not (tmp_path / "data").exists()


def test_watchlist_runner_refresh_enabled_with_fetcher_writes_expected_outputs(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.json"
    _write_watchlist(watchlist_path)
    trends_fetcher = _FakeTrendsFetcher()
    stock_fetcher = _FakeStockFetcher()

    runner = GoogleTrendsWatchlistRunner(
        base_dir=tmp_path,
        watchlist_path=watchlist_path,
        exporter=_FakeExporter({}),
        stock_fetcher=stock_fetcher,
        trends_fetcher=trends_fetcher,
    )

    result = runner.refresh_enabled_with_fetcher()

    assert result["tickers"] == 1
    assert result["keyword_pairs"] == 2
    assert stock_fetcher.calls == [("TSLA", "5y")]
    assert trends_fetcher.calls == [("Tesla", "", "today 5-y"), ("Tesla Model Y", "US", "today 5-y")]

    raw_dir = tmp_path / "data" / "raw" / "google_trends"
    processed_dir = tmp_path / "data" / "processed" / "google_trends"
    assert (raw_dir / "tesla_worldwide_trends.parquet").exists()
    assert (raw_dir / "tesla_model_y_us_trends.parquet").exists()
    assert (raw_dir / "tsla_stock_daily.parquet").exists()
    assert (processed_dir / "tesla_worldwide_tsla_combined.parquet").exists()
    assert (processed_dir / "tesla_model_y_us_tsla_combined.parquet").exists()


def test_watchlist_runner_refresh_enabled_with_fetcher_raises_without_writing_partial_outputs(tmp_path: Path) -> None:
    watchlist_path = tmp_path / "watchlist.json"
    _write_watchlist(watchlist_path)
    trends_fetcher = _FakeTrendsFetcher(fail_on=("Tesla Model Y", "US"))

    runner = GoogleTrendsWatchlistRunner(
        base_dir=tmp_path,
        watchlist_path=watchlist_path,
        exporter=_FakeExporter({}),
        stock_fetcher=_FakeStockFetcher(),
        trends_fetcher=trends_fetcher,
    )

    with pytest.raises(RuntimeError, match="fetch failed"):
        runner.refresh_enabled_with_fetcher()

    assert not (tmp_path / "data" / "raw" / "google_trends").exists()
    assert not (tmp_path / "data" / "processed" / "google_trends").exists()


def test_csv_exporter_builds_explore_url() -> None:
    exporter = GoogleTrendsCsvExporter(profile_dir=Path("/tmp/profile"))

    url = exporter.build_explore_url(keyword="Tesla Model Y", geo="US", timeframe="today 5-y", hl="en-US")

    assert url.startswith("https://trends.google.com/trends/explore?")
    assert "q=Tesla+Model+Y" in url
    assert "geo=US" in url
    assert "date=today+5-y" in url
    assert "hl=en-US" in url


def test_csv_exporter_waits_for_download_button_until_toolbar_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = GoogleTrendsCsvExporter(profile_dir=Path("/tmp/profile"), timeout_ms=3500)
    page = _FakePage()
    target = object()
    attempts = {"count": 0}

    def fake_locate(_page):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ValueError("not yet")
        return target

    dismiss_calls = {"count": 0}

    def fake_dismiss(_page):
        dismiss_calls["count"] += 1

    monkeypatch.setattr(exporter, "_locate_download_button", fake_locate)
    monkeypatch.setattr(exporter, "_dismiss_common_dialogs", fake_dismiss)

    assert exporter._wait_for_download_button(page) is target
    assert page.wait_calls == [1000, 1000]
    assert dismiss_calls["count"] == 3


def test_csv_exporter_wait_for_download_button_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    import google_trends_data.exporter as exporter_module

    exporter = GoogleTrendsCsvExporter(profile_dir=Path("/tmp/profile"), timeout_ms=2200)
    page = _FakePage()
    ticks = iter([0.0, 0.5, 1.5, 2.5])

    monkeypatch.setattr(exporter, "_locate_download_button", lambda _page: (_ for _ in ()).throw(ValueError("missing")))
    monkeypatch.setattr(exporter, "_dismiss_common_dialogs", lambda _page: None)
    monkeypatch.setattr(exporter_module, "monotonic", lambda: next(ticks))

    with pytest.raises(ValueError, match="missing"):
        exporter._wait_for_download_button(page)

    assert page.wait_calls == [1000, 1000]


def test_csv_exporter_prefers_topmost_csv_button() -> None:
    exporter = GoogleTrendsCsvExporter(profile_dir=Path("/tmp/profile"))
    lower = _FakeButton(y=900)
    topmost = _FakeButton(y=200)
    locator = _FakeLocatorCollection([lower, topmost])

    assert exporter._pick_topmost_button(locator) is topmost


def test_csv_exporter_prefers_interest_over_time_widget_button() -> None:
    exporter = GoogleTrendsCsvExporter(profile_dir=Path("/tmp/profile"))
    good = _FakeButton(y=500)
    wrong = _FakeButton(y=100)
    page = _FakeExportPage(
        {
            ("widget", "Interest over time", "button[title='CSV']"): _FakeLocatorCollection([good]),
            ("locator", None, "button[title='CSV']"): _FakeLocatorCollection([wrong, good]),
        }
    )

    assert exporter._locate_download_button(page) is good


def test_csv_exporter_collects_candidate_buttons_in_priority_order() -> None:
    exporter = GoogleTrendsCsvExporter(profile_dir=Path("/tmp/profile"))
    good = _FakeButton(y=500, x=10)
    wrong = _FakeButton(y=100, x=20)
    page = _FakeExportPage(
        {
            ("widget", "Interest over time", "button[title='CSV']"): _FakeLocatorCollection([good]),
            ("locator", None, "button[title='CSV']"): _FakeLocatorCollection([wrong, good]),
        }
    )

    assert exporter._candidate_download_buttons(page) == [good, wrong]


def test_csv_exporter_does_not_fallback_without_interest_over_time_widget() -> None:
    exporter = GoogleTrendsCsvExporter(profile_dir=Path("/tmp/profile"))
    wrong = _FakeButton(y=100, x=20)
    page = _FakeExportPage(
        {
            ("locator", None, "button[title='CSV']"): _FakeLocatorCollection([wrong]),
        }
    )

    assert exporter._candidate_download_buttons(page) == []


def test_csv_exporter_detects_timeseries_csv_shape() -> None:
    exporter = GoogleTrendsCsvExporter(profile_dir=Path("/tmp/profile"))

    assert exporter._download_contains_timeseries_header(FIXTURES / "google_trends_interest_over_time_standard.csv")
    assert not exporter._download_contains_timeseries_header(
        FIXTURES / "google_trends_interest_over_time_title_only.csv"
    )


class _FakePage:
    def __init__(self) -> None:
        self.wait_calls: list[int] = []

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.wait_calls.append(milliseconds)


class _FakeButton:
    def __init__(self, *, y: float, x: float = 0.0) -> None:
        self._box = {"x": x, "y": y, "width": 40.0, "height": 24.0}

    def bounding_box(self) -> dict[str, float]:
        return self._box


class _FakeLocatorCollection:
    def __init__(self, buttons: list[_FakeButton]) -> None:
        self._buttons = buttons

    def count(self) -> int:
        return len(self._buttons)

    def nth(self, index: int) -> _FakeButton:
        return self._buttons[index]

    @property
    def first(self) -> _FakeButton:
        return self._buttons[0]


class _FakeExportPage:
    def __init__(self, mapping) -> None:
        self._mapping = mapping

    def locator(self, selector: str):
        if selector == "widget":
            return _FakeWidgetLocator(self._mapping)
        return self._mapping.get(("locator", None, selector), _FakeLocatorCollection([]))

    def get_by_role(self, *args, **kwargs):
        return _FakeLocatorCollection([])

    def get_by_label(self, *args, **kwargs):
        return _FakeLocatorCollection([])


class _FakeWidgetLocator:
    def __init__(self, mapping) -> None:
        self._mapping = mapping
        self._has_text = None

    def filter(self, *, has_text: str):
        self._has_text = has_text
        return self

    def locator(self, selector: str):
        return self._mapping.get(("widget", self._has_text, selector), _FakeLocatorCollection([]))
