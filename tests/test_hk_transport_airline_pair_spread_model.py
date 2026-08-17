from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_pair_spread_model import (
    _fy_spread,
    build_airline_pair_spread_model,
)


def test_fy_spread_history_is_positive_in_recent_years() -> None:
    spread = _fy_spread()
    assert spread.index.min() <= 2016
    assert spread.loc[2021] > 0
    assert spread.loc[2025] > spread.loc[2016]


def test_pair_spread_model_has_historical_fit_and_forecast() -> None:
    df = build_airline_pair_spread_model()
    assert len(df) >= 10
    hist = df[df["model_status"].eq("historical_fit")]
    assert len(hist) >= 8
    assert hist["spread_direction_correct"].mean() >= 0.6
    cur = df[df["model_status"].eq("current_forecast")]
    assert len(cur) == 1
    assert cur["spread_predicted_native_mn"].iloc[0] > 0


def test_forecast_spread_is_positive_consistent_with_thesis() -> None:
    df = build_airline_pair_spread_model()
    cur = df[df["model_status"].eq("current_forecast")]
    assert cur["spread_predicted_native_mn"].iloc[0] > 0
    assert cur["cask_diff_native"].iloc[0] > 0  # Juneyao CASK > Spring
