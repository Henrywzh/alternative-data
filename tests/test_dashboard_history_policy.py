"""Regression tests for the Cloudflare dashboard history-window contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "apps" / "asia-markets-dashboard" / "scripts"


def _load_history_policy():
    spec = importlib.util.spec_from_file_location("history_policy_test", SCRIPTS / "history_policy.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_history_window_uses_calendar_years_not_row_counts():
    policy = _load_history_policy()
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2010-01-01", "2026-01-01", freq="MS"),
            "value": range(193),
        }
    )

    window = policy.history_window(frame, "date", years=10)

    assert window["date"].min() == pd.Timestamp("2016-01-01")
    assert window["date"].max() == pd.Timestamp("2026-01-01")
    assert len(window) == 121


def test_history_window_keeps_all_available_history_when_shorter_than_ten_years():
    policy = _load_history_policy()
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2022-01-01", "2023-01-01", "2024-01-01"]),
            "value": [1, 2, 3],
        }
    )

    window = policy.history_window(frame, "date", years=10)

    assert window["date"].tolist() == frame["date"].tolist()


def test_history_window_does_not_change_daily_grain():
    policy = _load_history_policy()
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2016-01-01", "2026-01-01", freq="D"),
            "value": 1.0,
        }
    )

    window = policy.history_window(frame, "date", years=10)

    assert window["date"].min() == pd.Timestamp("2016-01-01")
    assert window["date"].is_unique
    assert len(window) > 3_600


def test_history_coverage_reports_actual_source_dates():
    policy = _load_history_policy()
    frame = pd.DataFrame({"date": ["2019-04-01", "2026-05-01"], "value": [1, 2]})

    assert policy.history_coverage(frame, "date") == {
        "available_from": "2019-04-01",
        "available_to": "2026-05-01",
        "records": 2,
    }
