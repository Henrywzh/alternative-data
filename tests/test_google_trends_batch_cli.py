from __future__ import annotations

from pathlib import Path

from google_trends_data import batch_cli


class _FakeRunner:
    last_instance: "_FakeRunner | None" = None

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.calls: list[tuple[str, dict]] = []
        _FakeRunner.last_instance = self

    def refresh_enabled(self, **kwargs):
        self.calls.append(("refresh-enabled", kwargs))
        return {"tickers": 1, "keyword_pairs": 2}

    def refresh_enabled_with_fetcher(self, **kwargs):
        self.calls.append(("refresh-enabled-library", kwargs))
        return {"tickers": 1, "keyword_pairs": 2}

    def refresh_ticker(self, ticker: str, **kwargs):
        self.calls.append(("refresh-ticker", {"ticker": ticker, **kwargs}))
        return {"tickers": 1, "keyword_pairs": 1}

    def validate(self, **kwargs):
        self.calls.append(("validate", kwargs))
        return {"keyword": "Tesla", "geo": "", "rows": 3}


def test_batch_cli_refresh_enabled_dispatches_runner(monkeypatch, capsys) -> None:
    monkeypatch.setattr(batch_cli, "GoogleTrendsWatchlistRunner", _FakeRunner)

    exit_code = batch_cli.main(
        [
            "refresh-enabled",
            "--base-dir",
            "/tmp/repo",
            "--watchlist",
            "/tmp/repo/watchlist.json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "keyword_pairs=2" in captured.out
    assert _FakeRunner.last_instance is not None
    assert _FakeRunner.last_instance.calls == [
        (
            "refresh-enabled",
            {
                "timeframe": "today 5-y",
                "stock_period": "5y",
                "hl": "en-US",
                "headless": True,
                "download_dir": None,
            },
        )
    ]


def test_batch_cli_refresh_ticker_dispatches_runner(monkeypatch, capsys) -> None:
    monkeypatch.setattr(batch_cli, "GoogleTrendsWatchlistRunner", _FakeRunner)

    exit_code = batch_cli.main(
        [
            "refresh-ticker",
            "--ticker",
            "TSLA",
            "--headful",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "keyword_pairs=1" in captured.out
    assert _FakeRunner.last_instance is not None
    assert _FakeRunner.last_instance.calls == [
        (
            "refresh-ticker",
            {
                "ticker": "TSLA",
                "timeframe": "today 5-y",
                "stock_period": "5y",
                "hl": "en-US",
                "headless": False,
                "download_dir": None,
            },
        )
    ]


def test_batch_cli_refresh_enabled_library_dispatches_runner(monkeypatch, capsys) -> None:
    monkeypatch.setattr(batch_cli, "GoogleTrendsWatchlistRunner", _FakeRunner)

    exit_code = batch_cli.main(
        [
            "refresh-enabled-library",
            "--base-dir",
            "/tmp/repo",
            "--watchlist",
            "/tmp/repo/watchlist.json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "keyword_pairs=2" in captured.out
    assert _FakeRunner.last_instance is not None
    assert _FakeRunner.last_instance.calls == [
        (
            "refresh-enabled-library",
            {
                "timeframe": "today 5-y",
                "stock_period": "5y",
            },
        )
    ]


def test_batch_cli_validate_dispatches_runner(monkeypatch, capsys) -> None:
    monkeypatch.setattr(batch_cli, "GoogleTrendsWatchlistRunner", _FakeRunner)

    exit_code = batch_cli.main(["validate", "--download-dir", str(Path("/tmp/downloads"))])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "rows=3" in captured.out
    assert _FakeRunner.last_instance is not None
    assert _FakeRunner.last_instance.calls == [
        (
            "validate",
            {
                "timeframe": "today 5-y",
                "hl": "en-US",
                "headless": True,
                "download_dir": Path("/tmp/downloads"),
            },
        )
    ]
