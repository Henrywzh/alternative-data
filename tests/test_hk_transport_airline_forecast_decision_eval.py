from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_forecast_decision_eval import (
    _ensemble_weights,
    build_airline_forecast_decision_eval,
)


def test_ensemble_weights_prefer_flat_ask_revenue_and_fuel_nonfuel_cost() -> None:
    w = _ensemble_weights()
    assert w["revenue"]["flat_ask"] > w["revenue"]["yield_mix"]
    assert w["cost"]["fuel_nonfuel"] > w["cost"]["flat_ask"]
    assert abs(w["revenue"]["flat_ask"] + w["revenue"]["yield_mix"] - 1.0) < 1e-9


def test_decision_eval_covers_all_carriers_with_beat_probability() -> None:
    eval_df, ens, unc = build_airline_forecast_decision_eval()
    assert len(eval_df) == 6
    assert eval_df["beat_probability_pct"].notna().all()
    assert eval_df["beat_probability_pct"].between(0, 100).all()


def test_spring_beat_probability_exceeds_juneyao() -> None:
    eval_df, _, _ = build_airline_forecast_decision_eval()
    spring = eval_df[eval_df["company"].eq("Spring Airlines")].iloc[0]
    juneyao = eval_df[eval_df["company"].eq("Juneyao Airlines")].iloc[0]
    assert spring["beat_probability_pct"] > juneyao["beat_probability_pct"]
    assert spring["beat_probability_pct"] > 60.0


def test_uncertainty_interval_spans_the_point_estimate() -> None:
    _, _, unc = build_airline_forecast_decision_eval()
    spring = unc[unc["company"].eq("Spring Airlines")].iloc[0]
    assert spring["p5_net_profit_native_mn"] < spring["p50_net_profit_native_mn"] < spring["p95_net_profit_native_mn"]
