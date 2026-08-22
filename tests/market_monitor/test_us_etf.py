"""US sector/sub-industry ETF universe, metrics and storage contracts.

What these protect is the honesty of the board: a partial provider answer, a
short history, or an unconfigured bucket must all be visible as themselves
rather than as a plausible-looking number.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from market_monitor.us_etf.fetch import (
    _common_rebase_window,
    build_us_sector_artifact,
    compute_rsi,
)
from market_monitor.us_etf.universe import ALL_US_ETFS, US_SECTOR_ETFS


def _history(spec: dict[str, list[float]], start: str = "2026-05-01") -> pd.DataFrame:
    rows = []
    for ticker, closes in spec.items():
        dates = pd.bdate_range(start, periods=len(closes)).strftime("%Y-%m-%d")
        rows += [
            {"date": d, "ticker": ticker, "close": float(c),
             "open": 0.0, "high": 0.0, "low": 0.0, "volume": 0.0}
            for d, c in zip(dates, closes)
        ]
    return pd.DataFrame(rows)


def _tail_aligned(spec: dict[str, list[float]]) -> pd.DataFrame:
    """Series of different lengths that all end on the same date."""
    longest = max(len(v) for v in spec.values())
    dates = pd.bdate_range("2026-05-01", periods=longest).strftime("%Y-%m-%d")
    rows = []
    for ticker, closes in spec.items():
        for d, c in zip(dates[longest - len(closes):], closes):
            rows.append({"date": d, "ticker": ticker, "close": float(c),
                         "open": 0.0, "high": 0.0, "low": 0.0, "volume": 0.0})
    return pd.DataFrame(rows)


# --- universe ---------------------------------------------------------------


def test_the_universe_has_the_eleven_gics_sectors_and_no_duplicates():
    assert len(US_SECTOR_ETFS) == 11
    tickers = [item["ticker"] for item in ALL_US_ETFS]
    assert len(tickers) == len(set(tickers))
    sectors = {item["sector"] for item in US_SECTOR_ETFS}
    assert len(sectors) == 11


def test_every_universe_entry_states_its_own_fee():
    """No entry may rely on a default: an unstated fee is an unknown cost.

    The CN registry learned this the hard way -- 16 of 23 hand-typed fees were
    wrong, and three wrappers sharing one placeholder hid it.
    """
    missing = [i["ticker"] for i in ALL_US_ETFS if i.get("expense_ratio") is None]
    assert missing == []


def test_sub_industry_entries_point_at_a_real_parent_sector():
    parents = {item["sector"] for item in US_SECTOR_ETFS}
    for item in ALL_US_ETFS:
        if "sector" in item:
            continue
        assert item["parent_sector"] in parents, item["ticker"]


# --- RSI --------------------------------------------------------------------


def test_a_flat_series_has_no_rsi_rather_than_a_perfect_one():
    """avg_loss == 0 returned 100.0, i.e. "maximally overbought", for a series
    that never moved."""
    assert compute_rsi(pd.Series([100.0] * 40)) is None


def test_a_monotonic_advance_is_a_hundred():
    assert compute_rsi(pd.Series([100.0 + i for i in range(40)])) == 100.0


def test_rsi_needs_enough_history():
    assert compute_rsi(pd.Series([100.0, 101.0])) is None


# --- missing metrics stay missing -------------------------------------------


def test_short_history_reports_null_returns_not_zero():
    """0.0 reads as "flat", which is a claim the data does not support."""
    frame = _history({"XLK": [100.0 + i for i in range(30)]})
    sector = build_us_sector_artifact(frame)["sectors"][0]

    assert sector["ret_20d_pct"] is not None      # 30 sessions: measurable
    assert sector["ret_60d_pct"] is None          # 60 sessions: not
    assert sector["ma60_pct"] is None


def test_a_fund_without_twenty_sessions_has_no_ma20():
    frame = _history({"XLK": [100.0 + i for i in range(10)]})
    sector = build_us_sector_artifact(frame)["sectors"][0]

    assert sector["ma20_pct"] is None
    assert sector["ret_20d_pct"] is None


def test_a_missing_expense_ratio_is_not_filled_in_at_nine_basis_points():
    frame = _history({"XLK": [100.0 + i for i in range(70)]})
    artifact = build_us_sector_artifact(frame)
    sector = artifact["sectors"][0]
    assert sector["expense_ratio"] == 0.0009  # XLK really does state it

    # An entry with no stated fee must surface as unknown.
    from market_monitor.us_etf import fetch as fetch_module

    original = list(fetch_module.ALL_US_ETFS)
    try:
        stripped = dict(original[0])
        stripped.pop("expense_ratio", None)
        fetch_module.ALL_US_ETFS = [stripped]
        sector = fetch_module.build_us_sector_artifact(frame)["sectors"][0]
        assert sector["expense_ratio"] is None
        assert sector["expense_ratio_str"] is None
    finally:
        fetch_module.ALL_US_ETFS = original


# --- the relative-performance chart -----------------------------------------


def test_every_plotted_series_shares_one_base_date():
    """Rebasing each line against its own first row compares cumulative
    returns measured over different windows, on one axis, against one y=100."""
    frame = _tail_aligned({
        "XLK": [100.0 + i for i in range(80)],
        "XLF": [100.0] * 40,
    })
    artifact = build_us_sector_artifact(frame)

    bases = {
        s["ticker"]: s["sparkline_60d"][0]["d"]
        for s in artifact["sectors"] if s["sparkline_60d"]
    }
    assert len(set(bases.values())) == 1
    assert artifact["coverage"]["rebase_base_date"] in set(bases.values())
    for s in artifact["sectors"]:
        if s["sparkline_60d"]:
            assert s["sparkline_60d"][0]["rebased"] == 100.0


def test_a_series_that_misses_the_base_date_is_not_drawn():
    frame = _tail_aligned({
        "XLK": [100.0 + i for i in range(80)],
        "XLF": [100.0 + i for i in range(80)],
        "XLE": [100.0] * 5,      # far too short to reach the common base
    })
    artifact = build_us_sector_artifact(frame)
    by_ticker = {s["ticker"]: s for s in artifact["sectors"]}

    assert by_ticker["XLE"]["sparkline_60d"] == []
    assert by_ticker["XLE"]["rebase_base_date"] is None
    assert by_ticker["XLK"]["sparkline_60d"]


def test_the_common_window_is_empty_when_nothing_overlaps():
    base, excluded = _common_rebase_window(pd.DataFrame(), ["XLK"], 60)
    assert base is None
    assert excluded == ["XLK"]


# --- coverage ---------------------------------------------------------------


def test_a_partial_answer_reports_what_is_missing():
    """Four sectors must not render as though four were all there is."""
    frame = _history({"XLK": [100.0 + i for i in range(70)]})
    coverage = build_us_sector_artifact(frame)["coverage"]

    assert coverage["sectors_expected"] == 11
    assert coverage["sectors_delivered"] == 1
    assert "XLF" in coverage["sectors_missing"]


def test_unmeasured_momentum_sorts_last_rather_than_as_zero():
    frame = _tail_aligned({
        "XLK": [100.0 + i for i in range(70)],     # strong
        "XLF": [100.0 - i * 0.1 for i in range(70)],  # weak but measured
        "XLE": [100.0] * 8,                        # too short to measure 20D
    })
    order = [s["ticker"] for s in build_us_sector_artifact(frame)["sectors"]]
    assert order[0] == "XLK"
    assert order[-1] == "XLE"


# --- storage ----------------------------------------------------------------


def test_the_config_reader_returns_r2_keys_only(tmp_path, monkeypatch):
    """.config also holds FRED, Groq and Gmail credentials."""
    from market_monitor.us_etf import storage_r2

    config = tmp_path / ".config"
    config.write_text(
        "R2_BUCKET=bucket\nR2_ACCESS_KEY_ID=ak\n"
        "FRED_API_KEY=secret-fred\nGROQ_API_KEY=secret-groq\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(storage_r2, "REPO_ROOT", tmp_path)
    for leaked in ("FRED_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(leaked, raising=False)

    values = storage_r2.get_r2_config()
    assert values["R2_BUCKET"] == "bucket"
    assert set(values) <= set(storage_r2.R2_CONFIG_KEYS)
    assert "FRED_API_KEY" not in values
    assert "secret-fred" not in json.dumps(values)


def test_an_unconfigured_bucket_is_distinguishable_from_a_failed_upload(
    tmp_path, monkeypatch
):
    """R2-first: an upload that silently never happens is the failure that
    matters, and a bare False cannot say which one it was."""
    from market_monitor.us_etf import storage_r2

    monkeypatch.setattr(storage_r2, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(storage_r2, "LOCAL_CACHE_DIR", tmp_path / "cache")
    for key in storage_r2.R2_CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)

    assert storage_r2.upload_json_to_r2("x.json", {"a": 1}) == "not_configured"
    # The local cache is still written, so the run is not lost.
    assert storage_r2.load_local_cache_json("x.json") == {"a": 1}
    assert storage_r2.local_cache_age_hours("x.json") is not None
    assert storage_r2.local_cache_age_hours("missing.json") is None
