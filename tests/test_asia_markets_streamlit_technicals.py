"""MACD and ratio-default helpers for the ETF Monitor technicals view."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "apps" / "asia-markets-streamlit" / "am" / "technicals.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("asia_markets_technicals", HELPER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_macd_zero_line_and_signal_relationship() -> None:
    helper = _load_helper()
    values = pd.Series(
        [100 + i for i in range(80)] + [180 - i for i in range(40)],
        index=pd.date_range("2024-01-02", periods=120, freq="B"),
    )
    frame = helper.macd_frame(values)
    assert {"macd", "signal", "histogram"}.issubset(frame.columns)
    assert len(frame) == 120
    gap = (frame["macd"] - frame["signal"] - frame["histogram"]).abs().max()
    assert float(gap) < 1e-10
    rising = helper.macd_frame(pd.Series(range(1, 60), dtype=float))
    assert float(rising["macd"].iloc[-1]) > 0


def test_ratio_defaults_prefer_region_pairs() -> None:
    helper = _load_helper()
    china = ["csi300", "csi500", "csi1000"]
    assert china[helper.ratio_default_index(china, "csi1000", 0)] == "csi1000"
    assert china[helper.ratio_default_index(china, "csi300", 1)] == "csi300"
    unknown = ["aaa", "bbb"]
    assert unknown[helper.ratio_default_index(unknown, "missing", 1)] == "bbb"
    assert helper.RATIO_DEFAULTS["us"] == ("us_small", "us_broad")
