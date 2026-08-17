from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "compare_hkex_event_study_captures.py"
SPEC = importlib.util.spec_from_file_location("hkex_capture_comparison", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _events(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": ["a", "b"],
            "5m_return": values,
            "30m_return": values,
            "1h_return": values,
            "5m_abnormal_return": values,
            "30m_abnormal_return": values,
            "1h_abnormal_return": values,
            "native_1h_return": values,
            "native_1h_abnormal_return": values,
            "market_data_status": ["covered", "missing"],
            "native_1h_status": ["covered", "missing"],
            "bar_hole_horizons": ["", "1h"],
        }
    )


def test_compare_event_frames_reports_exact_replay_consistency():
    result = MODULE.compare_event_frames(_events([0.01, -0.02]), _events([0.01, -0.02]))
    assert result["common_event_rows"] == 2
    assert result["exact_replay_consistent"] is True
    assert result["return_max_abs_differences"]["1h_return"] == 0.0
    assert result["return_equal_rows"]["native_1h_abnormal_return"] == 2
    assert result["coverage_equal_rows"]["bar_hole_horizons"] == 2


def test_compare_event_frames_reports_partial_overlap_and_difference():
    left = _events([0.01, -0.02])
    right = _events([0.01, -0.03]).replace({"a": "a", "b": "c"})
    result = MODULE.compare_event_frames(left, right)
    assert result["common_event_rows"] == 1
    assert result["exact_replay_consistent"] is False


def test_cutoff_key_normalizes_utc_serialization():
    assert MODULE._cutoff_key("2026-08-07T08:05:00Z") == MODULE._cutoff_key(
        "2026-08-07T08:05:00+00:00"
    )
