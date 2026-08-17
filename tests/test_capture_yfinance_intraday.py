from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import duckdb
import pandas as pd
import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "capture_yfinance_intraday.py"
SPEC = importlib.util.spec_from_file_location("capture_yfinance_intraday", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _download_frame(start: str = "2026-08-07 01:30:00+00:00") -> pd.DataFrame:
    timestamps = pd.date_range(start, periods=3, freq="5min")
    columns = {}
    for ticker, base in (("0005.HK", 100.0), ("^HSI", 20000.0)):
        columns[(ticker, "Open")] = [base, base + 1, base + 2]
        columns[(ticker, "High")] = [base + 1, base + 2, base + 3]
        columns[(ticker, "Low")] = [base - 1, base, base + 1]
        columns[(ticker, "Close")] = [base + 0.5, base + 1.5, base + 2.5]
        columns[(ticker, "Adj Close")] = [base + 0.5, base + 1.5, base + 2.5]
        columns[(ticker, "Volume")] = [10, 11, 12]
    frame = pd.DataFrame(columns, index=timestamps)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    return frame


def test_normalize_yfinance_download_has_stable_primary_key():
    normalized = MODULE.normalize_yfinance_download(
        _download_frame(),
        ["0005.HK", "^HSI"],
        interval="5m",
        captured_at="2026-08-07T12:00:00Z",
    )
    assert len(normalized) == 6
    assert normalized[["ticker", "interval", "timestamp_utc"]].duplicated().sum() == 0
    assert str(normalized["timestamp_utc"].dt.tz) == "UTC"
    assert normalized["ticker"].nunique() == 2


def test_write_snapshot_is_append_only_and_records_manifest(tmp_path: Path):
    frame = MODULE.normalize_yfinance_download(
        _download_frame(),
        ["0005.HK", "^HSI"],
        interval="5m",
        captured_at="2026-08-07T12:00:00Z",
    )
    entry = MODULE.write_snapshot(
        frame,
        tmp_path,
        captured_at="2026-08-07T12:00:00Z",
        capture_id="20260807T120000Z-test",
    )
    assert entry["intervals"]["5m"]["rows"] == 6
    assert (tmp_path / "20260807T120000Z-test" / "bars_5m.parquet").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["version"] == MODULE.MANIFEST_VERSION
    assert len(manifest["captures"]) == 1
    assert len(entry["manifest_sha256"]) == 64
    with pytest.raises(FileExistsError):
        MODULE.write_snapshot(
            frame,
            tmp_path,
            captured_at="2026-08-07T12:00:00Z",
            capture_id="20260807T120000Z-test",
        )


def test_validate_snapshot_rejects_duplicate_primary_key():
    frame = MODULE.normalize_yfinance_download(
        _download_frame(),
        ["0005.HK", "^HSI"],
        interval="5m",
        captured_at="2026-08-07T12:00:00Z",
    )
    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="primary key"):
        MODULE.validate_snapshot_frame(duplicate)


def test_write_snapshot_rejects_empty_capture(tmp_path: Path):
    empty = pd.DataFrame(
        columns=[
            "ticker", "interval", "timestamp_utc", "open", "high", "low",
            "close", "adj_close", "volume", "captured_at",
        ]
    )
    with pytest.raises(ValueError, match="empty"):
        MODULE.write_snapshot(
            empty,
            tmp_path,
            captured_at="2026-08-07T12:00:00Z",
            capture_id="empty-capture",
        )


def test_validate_capture_coverage_requires_benchmark_and_threshold():
    frame = MODULE.normalize_yfinance_download(
        _download_frame(),
        ["0005.HK", "^HSI"],
        interval="5m",
        captured_at="2026-08-07T12:00:00Z",
    )
    coverage = MODULE.validate_capture_coverage(
        frame,
        ["0005.HK", "^HSI"],
        ["5m"],
        benchmark="^HSI",
        min_symbol_coverage=1.0,
    )
    assert coverage["5m"]["coverage_ratio"] == 1.0
    with pytest.raises(ValueError, match="benchmark"):
        MODULE.validate_capture_coverage(
            frame.loc[frame.ticker.ne("^HSI")],
            ["0005.HK", "^HSI"],
            ["5m"],
            benchmark="^HSI",
        )


def test_audit_snapshot_archive_reports_missing_and_stale_symbols(tmp_path: Path):
    first = MODULE.normalize_yfinance_download(
        _download_frame(),
        ["0005.HK", "^HSI"],
        interval="5m",
        captured_at="2026-08-07T02:00:00Z",
    )
    second = MODULE.normalize_yfinance_download(
        _download_frame("2026-08-07 03:00:00+00:00"),
        ["^HSI"],
        interval="5m",
        captured_at="2026-08-07T03:30:00Z",
    )
    MODULE.write_snapshot(
        first,
        tmp_path,
        captured_at="2026-08-07T02:00:00Z",
        capture_id="capture-1",
        request={"symbols": ["0005.HK", "^HSI"]},
    )
    MODULE.write_snapshot(
        second,
        tmp_path,
        captured_at="2026-08-07T03:30:00Z",
        capture_id="capture-2",
        request={"symbols": ["^HSI"]},
    )

    audit = MODULE.audit_snapshot_archive(
        tmp_path,
        requested_symbols=["0005.HK", "0006.HK", "^HSI"],
        intervals=["5m"],
        as_of="2026-08-07T04:00:00Z",
        max_bar_lag_hours={"5m": 0.25},
    )
    report = audit["intervals"]["5m"]
    assert report["status"] == "degraded"
    assert report["capture_count"] == 2
    assert report["distinct_market_cutoff_count"] == 2
    assert report["capture_cutoff_status"] == "distinct_market_cutoffs_present"
    assert report["missing_symbols"] == ["0006.HK"]
    assert report["stale_symbols"] == ["0005.HK"]
    assert audit["integrity_error_count"] == 0


def test_audit_normalizes_same_cutoff_serializations(tmp_path: Path):
    frame = MODULE.normalize_yfinance_download(
        _download_frame(),
        ["0005.HK", "^HSI"],
        interval="5m",
        captured_at="2026-08-07T12:00:00Z",
    )
    MODULE.write_snapshot(
        frame,
        tmp_path,
        captured_at="2026-08-07T12:00:00Z",
        capture_id="capture-z",
    )
    MODULE.write_snapshot(
        frame,
        tmp_path,
        captured_at="2026-08-07T12:05:00+00:00",
        capture_id="capture-offset",
    )

    report = MODULE.audit_snapshot_archive(
        tmp_path,
        requested_symbols=["0005.HK", "^HSI"],
        intervals=["5m"],
        as_of="2026-08-07T12:10:00Z",
    )["intervals"]["5m"]

    assert report["capture_count"] == 2
    assert report["distinct_market_cutoff_count"] == 1
    assert report["capture_cutoff_status"] == "non_independent_same_market_cutoff"


def test_resolve_event_universe_reads_canonical_counts_without_writing(tmp_path: Path):
    database = tmp_path / "events.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE hkex_announcement_events (ticker VARCHAR, available_at TIMESTAMP)")
        connection.executemany(
            "INSERT INTO hkex_announcement_events VALUES (?, ?)",
            [("0005.HK", "2026-08-07 01:00:00"), ("0005.HK", "2026-08-07 02:00:00"), ("0700.HK", "2026-08-07 03:00:00")],
        )
    assert MODULE.resolve_event_universe(database, benchmark="^HSI") == ["0005.HK", "0700.HK", "^HSI"]
    assert MODULE.resolve_event_universe(database, top_tickers=1, benchmark="^HSI") == ["0005.HK", "^HSI"]
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "manifest.json").write_text(
        json.dumps({"version": MODULE.MANIFEST_VERSION, "captures": []})
    )
    readiness = MODULE.build_refresh_readiness(database, archive, intervals=["5m"])
    assert readiness["status"] == "needs_capture"
    assert "5m_missing_current_event_symbols" in readiness["reasons"]


def test_normalize_yfinance_download_supports_1d_interval():
    timestamps = pd.date_range("2026-08-05", periods=3, freq="D", tz="UTC")
    columns = {}
    for ticker, base in (("0005.HK", 100.0), ("^HSI", 20000.0)):
        columns[(ticker, "Open")] = [base, base + 1, base + 2]
        columns[(ticker, "High")] = [base + 1, base + 2, base + 3]
        columns[(ticker, "Low")] = [base - 1, base, base + 1]
        columns[(ticker, "Close")] = [base + 0.5, base + 1.5, base + 2.5]
        columns[(ticker, "Adj Close")] = [base + 0.5, base + 1.5, base + 2.5]
        columns[(ticker, "Volume")] = [1000, 1100, 1200]
    raw_frame = pd.DataFrame(columns, index=timestamps)
    raw_frame.columns = pd.MultiIndex.from_tuples(raw_frame.columns)

    normalized = MODULE.normalize_yfinance_download(
        raw_frame,
        ["0005.HK", "^HSI"],
        interval="1d",
        captured_at="2026-08-07T18:00:00Z",
    )

    assert len(normalized) == 6
    assert (normalized["interval"] == "1d").all()
    assert normalized[["ticker", "interval", "timestamp_utc"]].duplicated().sum() == 0
    assert str(normalized["timestamp_utc"].dt.tz) == "UTC"
    assert set(normalized["ticker"].unique()) == {"0005.HK", "^HSI"}


def test_cli_default_intervals_remain_intraday(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["capture_yfinance_intraday.py", "--tickers", "0005.HK"])
    args = MODULE.parse_args()
    assert args.intervals == ["5m", "1h"]


def test_write_snapshot_and_audit_supports_1d_bars(tmp_path: Path):
    timestamps = pd.date_range("2026-08-05", periods=3, freq="D", tz="UTC")
    columns = {}
    for ticker, base in (("0005.HK", 100.0), ("^HSI", 20000.0)):
        columns[(ticker, "Open")] = [base, base + 1, base + 2]
        columns[(ticker, "High")] = [base + 1, base + 2, base + 3]
        columns[(ticker, "Low")] = [base - 1, base, base + 1]
        columns[(ticker, "Close")] = [base + 0.5, base + 1.5, base + 2.5]
        columns[(ticker, "Adj Close")] = [base + 0.5, base + 1.5, base + 2.5]
        columns[(ticker, "Volume")] = [1000, 1100, 1200]
    raw_frame = pd.DataFrame(columns, index=timestamps)
    raw_frame.columns = pd.MultiIndex.from_tuples(raw_frame.columns)

    normalized = MODULE.normalize_yfinance_download(
        raw_frame,
        ["0005.HK", "^HSI"],
        interval="1d",
        captured_at="2026-08-07T18:00:00Z",
    )
    entry = MODULE.write_snapshot(
        normalized,
        tmp_path,
        captured_at="2026-08-07T18:00:00Z",
        capture_id="20260807T180000Z-1d-test",
    )

    assert (tmp_path / "20260807T180000Z-1d-test" / "bars_1d.parquet").exists()
    assert entry["intervals"]["1d"]["rows"] == 6

    audit = MODULE.audit_snapshot_archive(
        tmp_path,
        requested_symbols=["0005.HK", "^HSI"],
        intervals=["1d"],
        as_of="2026-08-07T20:00:00Z",
    )
    report = audit["intervals"]["1d"]
    assert report["status"] == "ok"
    assert report["bar_lag_threshold_hours"] == 120.0
    assert report["missing_symbols"] == []
    assert report["stale_symbols"] == []


def test_fetch_and_write_snapshot_1d_manifest_period_provenance(tmp_path: Path, monkeypatch):
    timestamps = pd.date_range("2026-08-05", periods=3, freq="D", tz="UTC")
    columns = {}
    for ticker, base in (("0005.HK", 100.0), ("^HSI", 20000.0)):
        columns[(ticker, "Open")] = [base, base + 1, base + 2]
        columns[(ticker, "High")] = [base + 1, base + 2, base + 3]
        columns[(ticker, "Low")] = [base - 1, base, base + 1]
        columns[(ticker, "Close")] = [base + 0.5, base + 1.5, base + 2.5]
        columns[(ticker, "Adj Close")] = [base + 0.5, base + 1.5, base + 2.5]
        columns[(ticker, "Volume")] = [1000, 1100, 1200]
    raw_frame = pd.DataFrame(columns, index=timestamps)
    raw_frame.columns = pd.MultiIndex.from_tuples(raw_frame.columns)

    download_calls = []

    def mock_download(*args, **kwargs):
        download_calls.append(kwargs)
        return raw_frame

    import yfinance as yf
    monkeypatch.setattr(yf, "download", mock_download)

    result = MODULE.fetch_and_write_snapshot(
        ["0005.HK", "^HSI"],
        intervals=["1d"],
        period_1d="3y",
        output_root=tmp_path,
        captured_at="2026-08-07T18:00:00Z",
    )

    assert download_calls[0]["period"] == "3y"
    assert download_calls[0]["interval"] == "1d"
    assert result["request"]["period_1d"] == "3y"

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["captures"][0]["request"]["period_1d"] == "3y"
