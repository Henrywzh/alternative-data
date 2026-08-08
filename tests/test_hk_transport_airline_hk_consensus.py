from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources.airline_hk_consensus import (
    normalize_hk_forecast_revisions,
    normalize_hk_profit_forecast,
)


def test_normalize_hk_profit_forecast_converts_eps_cents_and_keeps_dates() -> None:
    raw = pd.DataFrame(
        {
            "财政年度": [2026], "纯利/亏损": [1000], "每股盈利": [230],
            "每股派息": [99], "证券商": ["Test Securities"], "评级": ["买入"],
            "目标价": [19.4], "更新日期": ["2026-08-05"],
        }
    )
    result = normalize_hk_profit_forecast(raw, code="0293", retrieved_at="2026-08-06")
    row = result.iloc[0]
    assert row["ticker"] == "0293.HK"
    assert row["eps_native"] == 2.30
    assert row["net_profit_native_mn"] == 1000
    assert row["forecast_currency"] == "HKD"
    assert row["target_price_currency"] == "HKD"
    assert row["report_date"] == "2026-08-05"
    assert row["source_quality"] == "akshare_discovery"


def test_normalize_hk_profit_forecast_adds_point_in_time_usd_views() -> None:
    raw = pd.DataFrame(
        {
            "财政年度": [2026], "纯利/亏损": [1000], "每股盈利": [230],
            "每股派息": [99], "证券商": ["Test Securities"], "评级": ["买入"],
            "目标价": [19.4], "更新日期": ["2026-08-05"],
        }
    )
    fx = pd.DataFrame(
        {
            "pair": ["USD_HKD"],
            "observation_date": ["2026-08-05"],
            "value": [8.0],
        }
    )
    row = normalize_hk_profit_forecast(
        raw, code="0293", fx_rates=fx, retrieved_at="2026-08-06"
    ).iloc[0]
    assert row["forecast_fx_pair"] == "USD_HKD"
    assert row["forecast_fx_observation_date"] == "2026-08-05"
    assert row["net_profit_usd_mn_at_report"] == pytest.approx(125.0)
    assert row["eps_usd_at_report"] == pytest.approx(0.2875)
    assert row["target_price_usd_at_report"] == pytest.approx(2.425)


def test_normalize_hk_forecast_revisions_compares_prior_broker_row() -> None:
    rows = pd.DataFrame(
        {
            "ticker": ["0293.HK", "0293.HK"], "company": ["Cathay Pacific"] * 2,
            "fiscal_year": [2026, 2026], "report_date": ["2026-07-01", "2026-08-01"],
            "institution": ["Test Securities"] * 2, "net_profit_native_mn": [1000, 1200],
            "eps_native": [1.0, 1.2], "target_price_hkd": [15, 18],
            "rating": ["增持", "买入"], "source_quality": ["akshare_discovery"] * 2,
            "source_url": ["https://example.com"] * 2,
        }
    )
    result = normalize_hk_forecast_revisions(rows, retrieved_at="2026-08-06")
    latest = result.iloc[-1]
    assert latest["prior_report_date"] == "2026-07-01"
    assert latest["net_profit_change_native_mn"] == 200
    assert latest["eps_change_native"] == pytest.approx(0.2)
    assert latest["target_price_change_pct"] == pytest.approx(20.0)


def test_current_hk_broker_layer_is_a_dated_observation_snapshot() -> None:
    forecasts = pd.read_csv("data/normalized/hk_transport/airline_hk_sell_side_forecasts.csv")
    revisions = pd.read_csv("data/normalized/hk_transport/airline_hk_forecast_revisions.csv")

    assert len(forecasts) >= 82
    assert forecasts["report_date"].notna().all()
    assert forecasts["source_quality"].eq("akshare_discovery").all()
    assert forecasts.loc[forecasts["company"].eq("Cathay Pacific"), "forecast_currency"].eq("HKD").all()
    assert forecasts.loc[~forecasts["company"].eq("Cathay Pacific"), "forecast_currency"].eq("RMB").all()
    assert forecasts["target_price_currency"].eq("HKD").all()
    assert forecasts.duplicated(["ticker", "fiscal_year", "institution", "report_date"]).sum() == 0
    assert set(revisions.columns) >= {"prior_report_date", "eps_change_native", "net_profit_change_native_mn"}
