"""Offline tests for CNN Business US-equity Fear & Greed."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from global_market_regime.cnn_fear_greed import parse_cnn_fear_greed
from global_market_regime.pipeline import source_health_rows


def _payload() -> dict:
    return {
        "fear_and_greed": {
            "score": 31.0,
            "rating": "fear",
            "timestamp": "2026-09-14T23:59:50+00:00",
        },
        "fear_and_greed_historical": {
            "data": [
                {"x": 1757894400000.0, "y": 64.4, "rating": "greed"},
                {"x": 1789430390000.0, "y": 31.0, "rating": "fear"},
            ]
        },
        "market_momentum_sp500": {
            "score": 25.4,
            "rating": "fear",
            "timestamp": 1789418088000.0,
            "data": [
                {"x": 1757894400000.0, "y": 6615.28, "rating": "extreme greed"},
                {"x": 1789418088000.0, "y": 7619.98, "rating": "extreme greed"},
            ],
        },
        "stock_price_strength": {
            "score": 3.6,
            "rating": "extreme fear",
            "timestamp": 1789430390000.0,
            "data": [
                {"x": 1757894400000.0, "y": 3.8, "rating": "extreme fear"},
                {"x": 1789430390000.0, "y": -2.7, "rating": "extreme fear"},
            ],
        },
        "stock_price_breadth": {
            "score": 9.0,
            "rating": "extreme fear",
            "timestamp": 1789430390000.0,
            "data": [
                {"x": 1757894400000.0, "y": 1339.8, "rating": "extreme greed"},
                {"x": 1789430390000.0, "y": 770.8, "rating": "extreme greed"},
            ],
        },
        "put_call_options": {
            "score": 35.8,
            "rating": "fear",
            "timestamp": 1789419263000.0,
            "data": [
                {"x": 1757894400000.0, "y": 0.60, "rating": "extreme fear"},
                {"x": 1789419263000.0, "y": 0.76, "rating": "extreme fear"},
            ],
        },
        "market_volatility_vix": {
            "score": 50.0,
            "rating": "neutral",
            "timestamp": 1789416901000.0,
            "data": [
                {"x": 1757894400000.0, "y": 15.69, "rating": "extreme fear"},
                {"x": 1789416901000.0, "y": 17.10, "rating": "extreme fear"},
            ],
        },
        "junk_bond_demand": {
            "score": 64.6,
            "rating": "greed",
            "timestamp": 1789425000000.0,
            "data": [
                {"x": 1757894400000.0, "y": 1.27, "rating": "extreme fear"},
                {"x": 1789425000000.0, "y": 1.22, "rating": "extreme fear"},
            ],
        },
        "safe_haven_demand": {
            "score": 29.0,
            "rating": "fear",
            "timestamp": 1789415999000.0,
            "data": [
                {"x": 1757894400000.0, "y": 0.65, "rating": "extreme fear"},
                {"x": 1789415999000.0, "y": 0.50, "rating": "extreme fear"},
            ],
        },
    }


def test_parse_cnn_fear_greed_keeps_composite_history_and_latest_component_scores() -> None:
    frame = parse_cnn_fear_greed(_payload(), retrieved_at="2026-09-15T00:00:00Z")
    composite = frame[frame["component_id"].eq("composite")].sort_values("date")
    assert list(composite["score"].round(1)) == [64.4, 31.0]
    assert composite.iloc[-1]["rating"] == "fear"
    momentum = frame[frame["component_id"].eq("momentum")].sort_values("date")
    assert pd.isna(momentum.iloc[0]["score"])
    assert momentum.iloc[-1]["score"] == 25.4
    assert momentum.iloc[-1]["raw_value"] == 7619.98


def test_cnn_source_health_is_equity_index_not_crypto() -> None:
    frame = parse_cnn_fear_greed(_payload(), retrieved_at="2026-09-15T00:00:00Z")
    health = source_health_rows(
        fred=pd.DataFrame(),
        mpt=pd.DataFrame(),
        fred_errors={},
        mpt_error=None,
        cot=pd.DataFrame(),
        fomc=pd.DataFrame(),
        cross_asset=pd.DataFrame(),
        cnn_fear_greed=frame,
        now=datetime(2026, 9, 15, tzinfo=timezone.utc),
    )
    row = health[health["series_id"].eq("cnn_fear_greed")].iloc[0]
    assert row["status"] == "Healthy"
    assert "not Alternative.me" in row["notes"]
    assert int(row["records"]) == 2


def test_empty_cnn_payload_is_unavailable() -> None:
    health = source_health_rows(
        fred=pd.DataFrame(),
        mpt=pd.DataFrame(),
        fred_errors={},
        mpt_error=None,
        cot=pd.DataFrame(),
        fomc=pd.DataFrame(),
        cross_asset=pd.DataFrame(),
        cnn_fear_greed=pd.DataFrame(),
        now=datetime(2026, 9, 15, tzinfo=timezone.utc),
    )
    row = health[health["series_id"].eq("cnn_fear_greed")].iloc[0]
    assert row["status"] == "Unavailable"


def test_component_charts_keep_raw_history_and_latest_score_only() -> None:
    frame = parse_cnn_fear_greed(_payload(), retrieved_at="2026-09-15T00:00:00Z")
    momentum = frame[frame["component_id"].eq("momentum")].sort_values("date")
    assert list(momentum["raw_value"].round(2)) == [6615.28, 7619.98]
    assert momentum["score"].notna().sum() == 1
    assert float(momentum.dropna(subset=["score"]).iloc[-1]["score"]) == 25.4
    vix = frame[frame["component_id"].eq("vix")].sort_values("date")
    assert float(vix.iloc[-1]["raw_value"]) == 17.1
    assert float(vix.dropna(subset=["score"]).iloc[-1]["score"]) == 50.0
