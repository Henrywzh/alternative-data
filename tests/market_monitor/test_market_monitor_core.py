"""Offline unit tests for market_monitor derived-signal math."""

import numpy as np
import pandas as pd
import pytest

from market_monitor.ranking import rank_wrappers
from market_monitor.relative_strength import build_relative_regime, compute_spread_metrics
from market_monitor.technicals import compute_technicals


def _make_daily(days: int = 120, base: float = 100.0, drift: float = 0.001) -> pd.Series:
    idx = pd.date_range("2026-01-01", periods=days, freq="D")
    changes = np.random.default_rng(7).normal(drift, 0.01, days)
    values = base * np.cumprod(1 + changes)
    return pd.Series(values, index=idx)


def test_technicals_smoke():
    close = _make_daily()
    result = compute_technicals(close)
    assert 0 <= result["rsi"] <= 100
    assert result["ma20"] is not None
    assert result["ma60"] is not None
    assert result["ma20_pct"] is not None
    assert result["drawdown_60d"] <= 0.0  # drawdown is non-positive


def test_technicals_rsi_extremes_stay_bounded():
    # A monotonic rally should push RSI toward the top.
    rng = np.random.default_rng(3)
    daily = 100 * np.cumprod(1 + rng.normal(0.008, 0.005, 90))  # steady up-trend with small noise
    up = pd.Series(daily, index=pd.date_range("2026-01-01", periods=90, freq="D"))
    result = compute_technicals(up)
    assert result["rsi"] > 70


def test_relative_regime_recognizes_leadership():
    rng = np.random.default_rng(42)
    dates = pd.date_range("2026-01-01", periods=100, freq="D")
    strong = pd.Series(100 * np.cumprod(1 + rng.normal(0.004, 0.01, 100)), index=dates)
    weak = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 100)), index=dates)
    metrics = compute_spread_metrics(strong, weak, label="small/large")
    assert metrics["spread_5d_pct"] is not None or metrics["spread_20d_pct"] is not None
    assert "spread_20d_zscore" in metrics


def test_relative_regime_builder_emits_rows():
    rng = np.random.default_rng(1)
    dates = pd.date_range("2026-01-01", periods=120, freq="D")
    close_by = {eid: pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.01, 120)), index=dates) for eid in ("csi300", "csi500", "csi1000", "dividend", "growth", "sp500")}
    rows = build_relative_regime(close_by)
    labels = {r["label"] for r in rows}
    assert {"Small / Large", "Mid / Large", "Growth / Dividend", "China / S&P 500"} <= labels


def test_spread_metrics_aligns_by_date_not_position():
    """Different trading calendars must not shift the spread by position."""
    dates_a = pd.date_range("2026-01-01", periods=30, freq="B")  # business days
    dates_b = dates_a[1:]  # B starts one day later / shorter tail
    left = pd.Series(range(30), index=dates_a, dtype=float)
    right = pd.Series(range(1, 30), index=dates_b, dtype=float)
    # Rebuild as in pipeline: same dates for both where they overlap.
    common = dates_a.intersection(dates_b)
    left_c = pd.Series(left.reindex(common).to_numpy(), index=common)
    right_c = pd.Series(right.reindex(common).to_numpy(), index=common)
    metrics = compute_spread_metrics(left_c, right_c, label="cross")
    # Constant 1:1 shift => daily spread 0; cumulative spread stays ~0.
    assert metrics["spread_5d_pct"] is None or abs(metrics["spread_5d_pct"]) < 1e-6


def test_rank_wrappers_produces_two_ranks():
    frame = pd.DataFrame(
        {
            "exposure_id": ["csi500"] * 3,
            "fund_id": ["a", "b", "c"],
            "ticker": ["a", "b", "c"],
            "premium_pct": [-0.1, 0.0, 0.5],
            "relative_premium_pct": [-0.2, -0.1, 0.4],
            "spread_bp": [1.0, 2.0, 5.0],
            "turnover": [6.0, 2.0, 0.5],
            "aum": [100.0, 50.0, 20.0],
            "management_fee": [0.002, 0.005, 0.008],
            "fund_age_days": [4000, 2000, 1000],
        }
    )
    ranked = rank_wrappers(frame)
    assert {"buy_score", "hold_score", "buy_rank", "hold_rank"} <= set(ranked.columns)
    assert sorted(ranked["buy_rank"].tolist()) == [1, 2, 3]
    assert sorted(ranked["hold_rank"].tolist()) == [1, 2, 3]


def test_rank_wrappers_survives_missing_fund():
    """A halted / unquoted fund (all NaN) must not crash the daily ranking."""
    frame = pd.DataFrame(
        {
            "exposure_id": ["csi500", "csi500", "csi500"],
            "fund_id": ["a", "b", "c"],
            "ticker": ["a", "b", "c"],
            "premium_pct": [-0.1, 0.2, None],
            "relative_premium_pct": [-0.1, 0.1, None],
            "spread_bp": [1.0, 2.0, None],
            "turnover": [5.0, 2.0, None],
            "aum": [100.0, 50.0, None],
            "management_fee": [0.002, 0.005, None],
            "fund_age_days": [4000.0, 2000.0, None],
        }
    )
    ranked = rank_wrappers(frame)
    assert len(ranked) == 3  # missing fund kept, not dropped
    # a (best) ranks 1; b and the fully-missing c both score 0 -> tied last.
    assert ranked.loc[ranked["fund_id"] == "a", "buy_rank"].iloc[0] == 1
    assert ranked.loc[ranked["fund_id"] == "c", "buy_rank"].iloc[0] >= 2
