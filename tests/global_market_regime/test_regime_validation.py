"""Historical replay and threshold-calibration tests."""

from __future__ import annotations

import pandas as pd
import pytest

from global_market_regime.validation import (
    build_event_forward_returns,
    build_signal_episodes,
    build_threshold_sensitivity,
    summarize_event_forward_returns,
)


def test_signal_episodes_collapse_contiguous_non_normal_states() -> None:
    states = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=8, freq="D"),
            "indicator_id": ["us10y"] * 8,
            "state": [
                "Normal",
                "Watch",
                "Confirmed",
                "Improving",
                "Normal",
                "Normal",
                "Watch",
                "Confirmed",
            ],
        }
    )

    episodes = build_signal_episodes(states)

    assert episodes[
        [
            "start_date",
            "end_date",
            "observation_count",
            "max_state",
            "open_episode",
        ]
    ].to_dict("records") == [
        {
            "start_date": pd.Timestamp("2026-01-02"),
            "end_date": pd.Timestamp("2026-01-04"),
            "observation_count": 3,
            "max_state": "Confirmed",
            "open_episode": False,
        },
        {
            "start_date": pd.Timestamp("2026-01-07"),
            "end_date": pd.Timestamp("2026-01-08"),
            "observation_count": 2,
            "max_state": "Confirmed",
            "open_episode": True,
        },
    ]


def test_threshold_sensitivity_counts_hits_and_distinct_episodes() -> None:
    states = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=6, freq="D"),
            "indicator_id": ["brent"] * 6,
            "value": [89.0, 101.0, 102.0, 95.0, 101.0, 80.0],
        }
    )

    sensitivity = build_threshold_sensitivity(
        states,
        candidates={"brent": (90.0, 100.0)},
    ).set_index("threshold")

    assert sensitivity.loc[100.0, "above_count"] == 3
    assert sensitivity.loc[100.0, "raw_hit_episode_count"] == 2
    assert bool(sensitivity.loc[100.0, "is_current_threshold"]) is True
    assert sensitivity.loc[90.0, "above_count"] == 4


def test_threshold_sensitivity_matches_strict_live_threshold() -> None:
    states = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "indicator_id": ["brent"] * 3,
            "value": [99.0, 100.0, 101.0],
        }
    )

    sensitivity = build_threshold_sensitivity(
        states,
        candidates={"brent": (100.0,)},
    ).iloc[0]

    assert sensitivity["above_count"] == 1


def test_long_data_gap_starts_a_new_signal_episode() -> None:
    states = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02", "2026-02-01"],
            "indicator_id": ["brent"] * 3,
            "state": ["Watch", "Confirmed", "Confirmed"],
        }
    )

    episodes = build_signal_episodes(states)

    assert len(episodes) == 2
    assert episodes["observation_count"].tolist() == [2, 1]


def test_signal_episode_deduplicates_same_indicator_date() -> None:
    states = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-01", "2026-01-02"],
            "indicator_id": ["brent", "brent", "brent"],
            "state": ["Watch", "Watch", "Confirmed"],
        }
    )

    episodes = build_signal_episodes(states)

    assert len(episodes) == 1
    assert episodes.iloc[0]["observation_count"] == 2


def test_event_forward_returns_use_each_exposures_trading_sessions() -> None:
    transitions = pd.DataFrame(
        [
            {
                "date": "2026-01-03",
                "indicator_id": "brent",
                "prior_state": "Watch",
                "state": "Confirmed",
            },
            {
                "date": "2026-01-05",
                "indicator_id": "us10y",
                "prior_state": "Normal",
                "state": "Watch",
            },
        ]
    )
    prices = pd.DataFrame(
        [
            {"date": date, "exposure_id": exposure, "close": base + index}
            for exposure, base in (("sp500", 100.0), ("hsi", 50.0))
            for index, date in enumerate(pd.date_range("2026-01-01", periods=12, freq="B"))
        ]
    )

    returns = build_event_forward_returns(transitions, prices, horizons=(5,))

    assert len(returns) == 2
    assert set(returns["indicator_id"]) == {"brent"}
    sp500 = returns[returns["exposure_id"].eq("sp500")].iloc[0]
    assert sp500["price_date"] == pd.Timestamp("2026-01-05")
    assert sp500["forward_date"] == pd.Timestamp("2026-01-12")
    assert round(sp500["forward_return_pct"], 6) == round((107 / 102 - 1) * 100, 6)


def test_event_forward_returns_reject_zero_and_deduplicate_sessions() -> None:
    transitions = pd.DataFrame(
        [
            {
                "date": "2026-01-05",
                "indicator_id": "brent",
                "prior_state": "Watch",
                "state": "Confirmed",
            }
        ]
    )
    dates = list(pd.date_range("2026-01-06", periods=8, freq="B"))
    prices = pd.DataFrame(
        [{"date": dates[0], "exposure_id": "sp500", "close": 0.0}]
        + [
            {"date": date, "exposure_id": "sp500", "close": 90.0 + index}
            for index, date in enumerate(dates[1:])
        ]
        + [{"date": dates[1], "exposure_id": "sp500", "close": 100.0}]
    )

    result = build_event_forward_returns(transitions, prices, horizons=(5,))

    assert len(result) == 1
    assert result.iloc[0]["price_date"] == dates[1]
    assert result.iloc[0]["forward_date"] == dates[6]
    assert result.iloc[0]["forward_return_pct"] == pytest.approx(
        (95.0 / 100.0 - 1.0) * 100.0
    )


def test_event_forward_returns_start_strictly_after_event_date() -> None:
    transitions = pd.DataFrame(
        [
            {
                "date": "2026-01-05",
                "indicator_id": "us10y",
                "prior_state": "Watch",
                "state": "Confirmed",
            }
        ]
    )
    prices = pd.DataFrame(
        [
            {
                "date": date,
                "exposure_id": "hsi",
                "close": 100.0 + index,
            }
            for index, date in enumerate(pd.date_range("2026-01-05", periods=8, freq="B"))
        ]
    )

    result = build_event_forward_returns(transitions, prices, horizons=(5,))

    assert result.iloc[0]["price_date"] == pd.Timestamp("2026-01-06")
    assert result.iloc[0]["forward_date"] == pd.Timestamp("2026-01-13")


def test_event_forward_returns_count_one_entry_per_non_normal_episode() -> None:
    transitions = pd.DataFrame(
        [
            {"date": "2026-01-02", "indicator_id": "brent", "prior_state": "Normal", "state": "Watch"},
            {"date": "2026-01-05", "indicator_id": "brent", "prior_state": "Watch", "state": "Confirmed"},
            {"date": "2026-01-06", "indicator_id": "brent", "prior_state": "Confirmed", "state": "Escalating"},
            {"date": "2026-01-07", "indicator_id": "brent", "prior_state": "Escalating", "state": "Confirmed"},
            {"date": "2026-01-08", "indicator_id": "brent", "prior_state": "Confirmed", "state": "Normal"},
            {"date": "2026-01-09", "indicator_id": "brent", "prior_state": "Normal", "state": "Watch"},
            {"date": "2026-01-12", "indicator_id": "brent", "prior_state": "Watch", "state": "Confirmed"},
        ]
    )
    prices = pd.DataFrame(
        [
            {"date": date, "exposure_id": "sp500", "close": 100.0 + index}
            for index, date in enumerate(pd.date_range("2026-01-01", periods=30, freq="B"))
        ]
    )

    result = build_event_forward_returns(transitions, prices, horizons=(5,))

    assert result["event_id"].nunique() == 2
    assert set(result["event_date"]) == {
        pd.Timestamp("2026-01-05"),
        pd.Timestamp("2026-01-12"),
    }


def test_event_forward_returns_restart_after_long_source_gap() -> None:
    states = pd.DataFrame(
        [
            {"date": "2026-01-02", "indicator_id": "brent", "state": "Watch"},
            {"date": "2026-01-05", "indicator_id": "brent", "state": "Confirmed"},
            {"date": "2026-01-20", "indicator_id": "brent", "state": "Confirmed"},
        ]
    )
    prices = pd.DataFrame(
        [
            {"date": date, "exposure_id": "sp500", "close": 100.0 + index}
            for index, date in enumerate(pd.date_range("2026-01-01", periods=60, freq="B"))
        ]
    )

    result = build_event_forward_returns(states, prices, horizons=(5,))

    assert result["event_id"].nunique() == 2
    assert set(result["event_date"]) == {
        pd.Timestamp("2026-01-05"),
        pd.Timestamp("2026-01-20"),
    }


def test_forward_return_summary_keeps_sample_size_visible() -> None:
    rows = pd.DataFrame(
        [
            {
                "event_id": event,
                "indicator_id": "brent",
                "domain_id": "inflation_supply",
                "state": "Confirmed",
                "exposure_id": "sp500",
                "horizon_sessions": 20,
                "forward_return_pct": value,
            }
            for event, value in (("a", -2.0), ("b", 4.0), ("c", 1.0))
        ]
    )

    summary = summarize_event_forward_returns(rows).iloc[0]

    assert summary["event_count"] == 3
    assert summary["median_forward_return_pct"] == 1.0
    assert summary["mean_forward_return_pct"] == 1.0
    assert round(summary["positive_share_pct"], 4) == round(200 / 3, 4)


def test_forward_return_summary_fails_closed_without_event_id() -> None:
    assert summarize_event_forward_returns(
        pd.DataFrame(
            [
                {
                    "indicator_id": "brent",
                    "domain_id": "inflation_supply",
                    "state": "Confirmed",
                    "exposure_id": "sp500",
                    "horizon_sessions": 20,
                    "forward_return_pct": 1.0,
                }
            ]
        )
    ).empty
