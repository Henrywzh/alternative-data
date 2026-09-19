"""Unit tests for the CNN component percentile-proxy used in the regime page."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd


APP_DIR = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-streamlit"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from am.regime_evidence import (  # noqa: E402
    CNN_COMPONENT_DIRECTION,
    CNN_MOMENTUM_MA_WINDOW,
    CNN_SCORE_BANDS,
    _cnn_official_score_hovertemplate,
    cnn_component_proxy_percentile,
)


def _frame(component_id: str, values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=len(values), freq="D"),
            "component_id": component_id,
            "raw_value": values,
        }
    )


def test_vix_high_raw_values_map_to_fear_side() -> None:
    """VIX is direction=-1: a higher raw VIX must produce a lower 0-100 proxy."""
    frame = _frame("vix", [10.0, 15.0, 20.0, 25.0, 30.0])
    proxy = cnn_component_proxy_percentile(frame, "vix")
    assert not proxy.empty
    # Ascending raw VIX ranks [20,40,60,80,100], flipped for direction=-1.
    assert proxy["proxy"].tolist() == [80.0, 60.0, 40.0, 20.0, 0.0]


def test_momentum_uses_price_versus_125d_average_not_raw_level() -> None:
    """Raw momentum is an index level; the proxy must rank price/MA125 instead."""
    values = np.concatenate(
        [
            np.full(200, 100.0),
            np.linspace(100.0, 109.8, 50),
        ]
    )
    frame = _frame("momentum", values.tolist())
    proxy = cnn_component_proxy_percentile(frame, "momentum")
    assert CNN_MOMENTUM_MA_WINDOW == 125
    # 250 rows -> first valid MA ratio appears at row 125.
    assert len(proxy) == 126
    # Flat price equals its own average (proxy below 50 because of later uptrend),
    # and the final uptrend point is the most greedy observation in the window.
    assert proxy["proxy"].iloc[0] < 50
    assert proxy["proxy"].iloc[-1] == 100.0


def test_unknown_component_returns_empty_frame() -> None:
    frame = _frame("not_a_component", [1.0, 2.0, 3.0])
    proxy = cnn_component_proxy_percentile(frame, "not_a_component")
    assert proxy.empty
    assert list(proxy.columns) == ["date", "proxy"]


def test_component_direction_mapping_is_complete() -> None:
    """Every direction-adjusted component must have an explicit direction."""
    assert CNN_COMPONENT_DIRECTION == {
        "momentum": 1,
        "strength": 1,
        "breadth": 1,
        "safe_haven": 1,
        "put_call": -1,
        "vix": -1,
        "junk_bond": -1,
    }


def test_official_score_tooltip_contains_a_renderable_plotly_value_token() -> None:
    template = _cnn_official_score_hovertemplate("CNN官方分数")

    assert "%{y:.0f}" in template
    assert "%{{y:.0f}}" not in template


def test_cnn_score_bands_match_labelled_inclusive_buckets() -> None:
    """Integer CNN scores must sit inside the labelled 0-24 / 25-44 / 45-55 / 56-74 / 75-100 buckets."""
    bands = [(float(low), float(high)) for low, high, *_ in CNN_SCORE_BANDS]
    assert bands == [(0.0, 24.0), (25.0, 44.0), (45.0, 55.0), (56.0, 74.0), (75.0, 100.0)]

    def bucket(score: float) -> tuple[float, float]:
        matches = [band for band in bands if band[0] <= score <= band[1]]
        assert len(matches) == 1, score
        return matches[0]

    assert bucket(24) == (0.0, 24.0)
    assert bucket(25) == (25.0, 44.0)
    assert bucket(44) == (25.0, 44.0)
    assert bucket(45) == (45.0, 55.0)
    assert bucket(55) == (45.0, 55.0)
    assert bucket(56) == (56.0, 74.0)
    assert bucket(74) == (56.0, 74.0)
    assert bucket(75) == (75.0, 100.0)
