from __future__ import annotations

import math

import pandas as pd

from signal_layer.aggregation import build_asset_signals, build_theme_signals
from signal_layer.models import ASSET_SIGNAL_COLUMNS, THEME_SIGNAL_COLUMNS


def test_build_asset_signals_combines_only_valid_rows_and_carries_quality_issues() -> None:
    metric_signals = pd.DataFrame(
        [
            {
                "metric_id": "metric_positive",
                "as_of_date": "2026-06-30",
                "signed_stat": 2.0,
                "signal_state": "bullish",
                "quality_state": "valid",
                "quality_issues": "",
                "confidence": "high",
            },
            {
                "metric_id": "metric_negative",
                "as_of_date": "2026-06-30",
                "signed_stat": 1.0,
                "signal_state": "watch",
                "quality_state": "valid",
                "quality_issues": "",
                "confidence": "medium",
            },
            {
                "metric_id": "metric_invalid",
                "as_of_date": "2026-06-30",
                "signed_stat": 5.0,
                "signal_state": "watch",
                "quality_state": "stale",
                "quality_issues": "freshness_lag_days=12 above max_freshness_lag_days=7",
                "confidence": "low",
            },
        ]
    )
    asset_mapping = pd.DataFrame(
        [
            {
                "metric_id": "metric_positive",
                "ticker": "MSFT",
                "company_name": "Microsoft",
                "asset_type": "equity",
                "theme": "ai_platforms",
                "expected_direction": "positive",
                "exposure_weight": 4.0,
                "confidence": "high",
            },
            {
                "metric_id": "metric_negative",
                "ticker": "MSFT",
                "company_name": "Microsoft",
                "asset_type": "equity",
                "theme": "ai_platforms",
                "expected_direction": "negative",
                "exposure_weight": 1.0,
                "confidence": "medium",
            },
            {
                "metric_id": "metric_invalid",
                "ticker": "MSFT",
                "company_name": "Microsoft",
                "asset_type": "equity",
                "theme": "ai_platforms",
                "expected_direction": "positive",
                "exposure_weight": 9.0,
                "confidence": "low",
            },
        ]
    )
    metric_registry = pd.DataFrame(
        [
            {"metric_id": "metric_positive", "description": "Positive demand metric"},
            {"metric_id": "metric_negative", "description": "Cost pressure metric"},
            {"metric_id": "metric_invalid", "description": "Stale survey metric"},
        ]
    )

    result = build_asset_signals(metric_signals, asset_mapping, metric_registry)

    assert result.columns.tolist() == ASSET_SIGNAL_COLUMNS
    assert len(result) == 1
    row = result.loc[0]
    expected_stat = (math.sqrt(4.0) * 2.0 + math.sqrt(1.0) * -1.0) / math.sqrt(5.0)

    assert row["ticker"] == "MSFT"
    assert row["combined_signed_stat"] == expected_stat
    assert row["driver_count"] == 3
    assert row["valid_driver_count"] == 2
    assert row["non_valid_driver_count"] == 1
    assert row["positive_evidence_count"] == 1
    assert row["negative_evidence_count"] == 1
    assert row["bullish_metric_count"] == 1
    assert row["bearish_metric_count"] == 0
    assert row["neutral_metric_count"] == 2
    assert row["top_metric_id"] == "metric_positive"
    assert row["top_metric_description"] == "Positive demand metric"
    assert "metric_invalid" in row["quality_issues"]
    assert "freshness_lag_days=12 above max_freshness_lag_days=7" in row["quality_issues"]
    assert row["signal_state"] == "watch"


def test_build_theme_signals_rolls_up_assets_and_identifies_top_ticker() -> None:
    asset_signals = pd.DataFrame(
        [
            {
                "ticker": "MSFT",
                "company_name": "Microsoft",
                "asset_type": "equity",
                "as_of_date": "2026-06-30",
                "theme": "ai_platforms",
                "combined_signed_stat": 2.4,
                "combined_tail_probability": 0.016,
                "median_signed_stat": 2.2,
                "positive_evidence_count": 2,
                "negative_evidence_count": 0,
                "bullish_metric_count": 1,
                "bearish_metric_count": 0,
                "neutral_metric_count": 1,
                "top_metric_id": "metric_positive",
                "top_metric_description": "Positive demand metric",
                "driver_count": 2,
                "valid_driver_count": 2,
                "non_valid_driver_count": 0,
                "quality_issues": "",
                "signal_state": "bullish",
                "confidence": "high",
                "summary": "",
            },
            {
                "ticker": "AMZN",
                "company_name": "Amazon",
                "asset_type": "equity",
                "as_of_date": "2026-06-30",
                "theme": "ai_platforms",
                "combined_signed_stat": 0.8,
                "combined_tail_probability": 0.21,
                "median_signed_stat": 0.8,
                "positive_evidence_count": 1,
                "negative_evidence_count": 0,
                "bullish_metric_count": 0,
                "bearish_metric_count": 0,
                "neutral_metric_count": 1,
                "top_metric_id": "metric_secondary",
                "top_metric_description": "Secondary metric",
                "driver_count": 1,
                "valid_driver_count": 1,
                "non_valid_driver_count": 0,
                "quality_issues": "",
                "signal_state": "neutral",
                "confidence": "medium",
                "summary": "",
            },
        ]
    )

    result = build_theme_signals(asset_signals)

    assert result.columns.tolist() == THEME_SIGNAL_COLUMNS
    assert len(result) == 1
    row = result.loc[0]

    assert row["theme"] == "ai_platforms"
    assert row["active_asset_count"] == 2
    assert row["active_metric_count"] == 2
    assert row["top_ticker"] == "MSFT"
    assert row["top_metric_id"] == "metric_positive"
    assert row["positive_evidence_count"] == 3
    assert row["negative_evidence_count"] == 0
    assert row["signal_state"] == "bullish"
