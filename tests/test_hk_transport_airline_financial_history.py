from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_financial_history import build_airline_financial_history


def test_historical_financial_layer_keeps_provider_history_separate_from_pit_primary() -> None:
    actuals = pd.DataFrame(
        [
            {
                "ticker": "601021.SH", "company": "Spring Airlines",
                "statement_period": "2019-12", "period_end": "2019-12-31",
                "metric": "total_revenue", "provider_metric": "营业总收入",
                "value_native": 100.0, "native_unit": "RMB million",
                "native_currency": "RMB", "value_usd": 14.0,
                "usd_unit": "USD million", "fx_pair": "USD_CNY",
                "fx_observation_date": "2019-12-31", "fx_value": 7.1,
                "source_quality": "akshare_discovery",
                "announcement_date_available": False,
                "source_url": "https://example.test", "source_note": "provider",
                "retrieved_at": "2026-08-07T00:00:00+00:00",
            },
            {
                "ticker": "601021.SH", "company": "Spring Airlines",
                "statement_period": "2018-12", "period_end": "2018-12-31",
                "metric": "total_revenue", "provider_metric": "营业总收入",
                "value_native": 90.0, "native_unit": "RMB million",
                "native_currency": "RMB", "value_usd": 13.0,
                "usd_unit": "USD million", "fx_pair": "USD_CNY",
                "fx_observation_date": "2018-12-31", "fx_value": 6.9,
                "source_quality": "akshare_discovery",
                "announcement_date_available": False,
                "source_url": "https://example.test", "source_note": "provider",
                "retrieved_at": "2026-08-07T00:00:00+00:00",
            },
        ]
    )
    result = build_airline_financial_history(
        actuals, start_date="2019-01-01", retrieved_at="2026-08-07T00:00:00+00:00"
    )
    assert len(result) == 1
    assert result.iloc[0]["period_type"] == "FY"
    assert result.iloc[0]["source_quality"] == "akshare_discovery_historical"
    assert result.iloc[0]["announcement_date_available"] == False
    assert result.iloc[0]["point_in_time_status"] == "period_end_only_no_announcement_date"
    assert result.iloc[0]["as_of_date"] == "2019-12-31"


def test_current_history_layer_has_multiple_periods_and_all_required_metrics() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_financial_history_trend.csv")
    assert frame["company"].nunique() == 6
    assert frame["period_end"].min() >= "2016-01-01"
    assert frame["period_end"].max() >= "2026-03-31"
    assert frame["period_type"].isin({"FY", "H1_or_2Q", "Q1_or_1Q", "Q3_or_9M"}).all()
    assert frame["source_quality"].eq("akshare_discovery_historical").all()
    assert frame["announcement_date_available"].eq(False).all()
    assert frame["point_in_time_status"].eq("period_end_only_no_announcement_date").all()
    assert frame[["source_url", "as_of_date", "retrieved_at"]].notna().all().all()
    assert {"total_revenue", "operating_cost", "attributable_net_income", "operating_cash_flow"}.issubset(
        set(frame["metric"])
    )
