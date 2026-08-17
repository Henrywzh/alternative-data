import pandas as pd
import pytest

from src.hk_real_estate.shkp_forecast_backtest import (
    build_shkp_forecast_scenarios,
    build_shkp_release_event_study,
)


def test_forecast_scenarios_keep_broker_and_consensus_layers_separate():
    broker = pd.DataFrame([
        {
            "forecast_id": "b1", "ticker": "0016.HK", "broker_name": "A",
            "forecast_date": "2026-01-01", "fiscal_year": 2026,
            "eps": 7.0, "target_price": 120.0, "net_profit": 20_000.0,
            "dividend": 3.0, "eps_currency": "HKD", "target_price_currency": "HKD",
            "net_profit_currency": "HKD", "dividend_currency": "HKD",
            "fetched_at": "2026-07-26T00:00:00Z",
        },
        {
            "forecast_id": "b2", "ticker": "0016.HK", "broker_name": "B",
            "forecast_date": "2026-02-01", "fiscal_year": 2026,
            "eps": 9.0, "target_price": 160.0, "net_profit": 24_000.0,
            "dividend": 4.0, "eps_currency": "HKD", "target_price_currency": "HKD",
            "net_profit_currency": "HKD", "dividend_currency": "HKD",
            "fetched_at": "2026-07-26T00:00:00Z",
        },
    ])
    consensus = pd.DataFrame([
        {
            "ticker": "0016.HK", "metric": "eps", "statistic": "mean",
            "value": 8.1, "unit": "currency_per_share", "currency": "HKD",
            "fiscal_year": 2026, "snapshot_date": "2026-07-26",
            "contributor_count": 2, "source": "test",
        },
    ])

    result = build_shkp_forecast_scenarios(broker, consensus)

    broker_eps = result[(result["source_layer"] == "broker_forecasts") & (result["metric"] == "eps")]
    assert broker_eps.set_index("scenario").loc["low", "value"] == pytest.approx(7.0)
    assert broker_eps.set_index("scenario").loc["base", "value"] == pytest.approx(8.0)
    assert broker_eps.set_index("scenario").loc["high", "value"] == pytest.approx(9.0)
    assert set(result["source_layer"]) == {"broker_forecasts", "consensus_statistics"}
    assert result.loc[result["metric"].eq("net_profit"), "unit"].eq("currency").all()
    assert result["research_only"].eq(True).all()
    assert result["model_use"].eq("current_snapshot_scenario_only").all()


def test_release_event_study_uses_next_session_after_after_close_release():
    documents = pd.DataFrame([
        {
            "title": "Results",
            "document_type": "financial_report",
            "document_semantics": "results_announcement",
            "reporting_period_end": "2025-06-30",
            "hkex_release_at": "2026-01-02T16:30:00+08:00",
            "release_source_url": "https://example.test/hkex.pdf",
        },
    ])
    prices = pd.DataFrame({
        "ticker": ["0016.HK"] * 5,
        "trading_date": pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]),
        "adj_close": [100.0, 110.0, 121.0, 121.0, 121.0],
        "source": ["test"] * 5,
        "source_url": ["https://example.test/prices"] * 5,
    })

    result = build_shkp_release_event_study(documents, prices)

    row = result.iloc[0]
    assert row["event_price_date"] == "2026-01-02"
    assert row["forward_price_date_1d"] == "2026-01-05"
    assert row["forward_return_1d"] == pytest.approx(0.1)
    assert row["forward_return_5d"] is None or pd.isna(row["forward_return_5d"])
    assert row["same_day_inclusion_policy"].startswith("after_close_release")
    assert bool(row["research_only"])
