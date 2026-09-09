"""Decision-layer transforms for the Global Market Regime V2 page."""

from __future__ import annotations

import pandas as pd

from global_market_regime.presentation import (
    build_cross_asset_returns,
    build_domain_summary,
    build_regime_summary,
    build_state_transitions,
    build_threshold_monitor,
    rebase_price_history,
)


def _latest_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "indicator_id": "brent",
                "label_en": "Brent crude",
                "label_zh": "布伦特原油",
                "state": "Normal",
                "value": 96.02,
                "observation_date": "2026-09-01",
                "freshness": "Last session",
                "consecutive_breach": 0,
            },
            {
                "indicator_id": "us10y",
                "label_en": "US 10-year yield",
                "label_zh": "美国10年期国债收益率",
                "state": "Normal",
                "value": 4.79,
                "observation_date": "2026-09-02",
                "freshness": "Last session",
                "consecutive_breach": 0,
            },
            {
                "indicator_id": "fomc_hike",
                "label_en": "Next FOMC hike odds",
                "label_zh": "下次FOMC加息赔率",
                "state": "Watch",
                "value": 66.0,
                "observation_date": "2026-09-04",
                "freshness": "Current session",
                "consecutive_breach": 1,
            },
            {
                "indicator_id": "credit_vix",
                "label_en": "HY OAS + VIX sync stress",
                "label_zh": "高收益债利差与VIX同步压力",
                "state": "Normal",
                "value": 0.8,
                "hy_z": 0.8,
                "vix_z": 1.2,
                "observation_date": "2026-09-02",
                "freshness": "Last session",
                "consecutive_breach": 0,
            },
        ]
    )


def test_threshold_monitor_has_units_distances_and_confirmation_progress() -> None:
    states = pd.DataFrame(
        {
            "date": pd.date_range("2026-08-28", periods=5, freq="D"),
            "indicator_id": ["brent"] * 5,
            "value": [101, 102, 99, 101, 102],
            "breached": [True, True, False, True, True],
            "state": ["Watch", "Confirmed", "Improving", "Watch", "Confirmed"],
            "consecutive_breach": [1, 2, 0, 1, 2],
        }
    )

    monitor = build_threshold_monitor(_latest_rows(), states)
    by_id = monitor.set_index("indicator_id")

    assert by_id.loc["brent", "threshold"] == 100.0
    assert by_id.loc["brent", "distance"] == -3.98
    assert by_id.loc["brent", "distance_unit"] == "USD/bbl"
    assert by_id.loc["brent", "persistence_count"] == 4
    assert by_id.loc["brent", "persistence_required"] == 4
    assert by_id.loc["us10y", "distance"] == -3.0
    assert by_id.loc["us10y", "distance_unit"] == "bp"
    assert by_id.loc["fomc_hike", "distance"] == 1.0
    assert by_id.loc["fomc_hike", "distance_unit"] == "pp"
    assert by_id.loc["credit_vix", "distance"] == -0.2
    assert by_id.loc["credit_vix", "distance_unit"] == "z"


def test_polymarket_monitor_changes_use_previous_observation_and_calendar_week() -> None:
    latest = _latest_rows()
    history = pd.DataFrame(
        {
            "date": ["2026-08-27", "2026-09-03", "2026-09-04"],
            "hike_prob": [50.0, 43.0, 41.0],
        }
    )

    monitor = build_threshold_monitor(latest, fomc_history=history).set_index(
        "indicator_id"
    )

    assert monitor.loc["fomc_hike", "change_1obs_pp"] == -2.0
    assert monitor.loc["fomc_hike", "change_7d_pp"] == -9.0


def test_state_transitions_exclude_initial_and_unchanged_rows() -> None:
    states = pd.DataFrame(
        {
            "date": pd.date_range("2026-09-01", periods=4, freq="D"),
            "indicator_id": ["brent"] * 4,
            "value": [99, 101, 102, 98],
            "state": ["Normal", "Watch", "Watch", "Improving"],
        }
    )

    transitions = build_state_transitions(states)

    assert transitions[["prior_state", "state"]].to_dict("records") == [
        {"prior_state": "Normal", "state": "Watch"},
        {"prior_state": "Watch", "state": "Improving"},
    ]


def test_regime_summary_ignores_stale_escalating_driver() -> None:
    monitor = _latest_rows()
    monitor.loc[monitor["indicator_id"].eq("brent"), ["state", "freshness"]] = [
        "Escalating",
        "Stale",
    ]

    summary = build_regime_summary(monitor, alert_state={"last_sent_at": None})

    assert summary["overall_state"] == "Watch"
    assert summary["primary_driver_ids"] == ["fomc_hike"]
    assert summary["active_driver_count"] == 1
    assert summary["breadth_id"] == "narrow"
    assert summary["active_domain_ids"] == ["rates_policy"]
    assert summary["defensive_alert_eligible"] is False
    assert "Next FOMC hike odds" in summary["explanation_en"]
    assert "0 other" not in summary["explanation_en"]
    assert "另有0个" not in summary["explanation_zh"]
    assert summary["alert_eligible"] is False


def test_regime_summary_is_unavailable_when_every_input_is_stale() -> None:
    monitor = _latest_rows()
    monitor["freshness"] = "Stale"

    summary = build_regime_summary(monitor)

    assert summary["overall_state"] == "Unavailable"
    assert summary["fresh_indicator_count"] == 0
    assert summary["alert_eligible"] is False
    assert summary["explanation_en"].startswith("No fresh regime inputs")


def test_regime_summary_fails_closed_on_malformed_monitor() -> None:
    summary = build_regime_summary(pd.DataFrame([{"indicator_id": "brent"}]))

    assert summary["overall_state"] == "Unavailable"
    assert summary["alert_eligible"] is False
    assert summary["observation_start"] is None


def test_domain_summary_uses_highest_fresh_state_per_domain() -> None:
    monitor = _latest_rows()
    monitor.loc[monitor["indicator_id"].eq("us10y"), "state"] = "Confirmed"

    domains = build_domain_summary(monitor).set_index("domain_id")

    assert domains.loc["rates_policy", "state"] == "Confirmed"
    assert domains.loc["rates_policy", "available_indicator_count"] == 2
    assert domains.loc["rates_policy", "active_indicator_count"] == 2
    assert domains.loc["financial_stress", "state"] == "Normal"


def test_defensive_alert_requires_two_confirmed_domains() -> None:
    monitor = _latest_rows()
    monitor.loc[monitor["indicator_id"].eq("brent"), "state"] = "Confirmed"
    monitor.loc[monitor["indicator_id"].eq("us10y"), "state"] = "Confirmed"

    summary = build_regime_summary(monitor)

    assert summary["breadth_id"] == "broadening"
    assert summary["confirmed_domain_count"] == 2
    assert summary["defensive_alert_eligible"] is True


def test_confirmed_financial_stress_is_defensive_alert_exception() -> None:
    monitor = _latest_rows()
    monitor["state"] = "Normal"
    monitor.loc[monitor["indicator_id"].eq("credit_vix"), "state"] = "Confirmed"

    summary = build_regime_summary(monitor)

    assert summary["breadth_id"] == "narrow"
    assert summary["confirmed_domain_count"] == 1
    assert summary["active_domain_ids"] == ["financial_stress"]
    assert summary["defensive_alert_eligible"] is True


def test_cross_asset_reindexing_and_returns_use_price_ratios() -> None:
    dates = pd.date_range("2026-01-01", periods=70, freq="D")
    prices = pd.DataFrame(
        [
            {"date": date, "exposure_id": exposure, "close": base + index}
            for exposure, base in (("sp500", 100.0), ("hstech", 50.0))
            for index, date in enumerate(dates)
        ]
    )

    rebased = rebase_price_history(prices, exposure_ids=["sp500", "hstech"])
    starts = rebased.groupby("exposure_id", sort=False)["rebased"].first()
    assert starts.to_dict() == {"sp500": 100.0, "hstech": 100.0}

    returns = build_cross_asset_returns(prices).set_index("exposure_id")
    assert round(returns.loc["sp500", "return_1d_pct"], 6) == round(
        (169.0 / 168.0 - 1.0) * 100.0,
        6,
    )
    assert round(returns.loc["sp500", "return_5d_pct"], 6) == round(
        (169.0 / 164.0 - 1.0) * 100.0,
        6,
    )
    assert round(returns.loc["sp500", "return_20d_pct"], 6) == round(
        (169.0 / 149.0 - 1.0) * 100.0,
        6,
    )
    assert round(returns.loc["hstech", "return_60d_pct"], 6) == round(
        (119.0 / 59.0 - 1.0) * 100.0,
        6,
    )
