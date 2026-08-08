from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources.airline_financials import (
    _call_akshare_with_timeout,
    merge_airline_consensus_history,
    normalize_financial_abstract,
    normalize_detailed_indicator_forecast,
    normalize_profit_forecast,
    normalize_sell_side_forecast_revisions,
)


def test_akshare_call_timeout_is_bounded() -> None:
    def slow_call() -> None:
        import time

        time.sleep(0.05)

    with pytest.raises(TimeoutError):
        _call_akshare_with_timeout(slow_call, timeout_seconds=0.01)


def test_merge_airline_consensus_history_preserves_prior_snapshots() -> None:
    prior = pd.DataFrame(
        {
            "ticker": ["601111.SH"], "snapshot_date": ["2026-08-06"],
            "fiscal_year": [2026], "metric": ["net_profit"], "value_avg_native": [1.0],
        }
    )
    current = pd.DataFrame(
        {
            "ticker": ["601111.SH", "601111.SH"],
            "snapshot_date": ["2026-08-07", "2026-08-06"],
            "fiscal_year": [2026, 2026], "metric": ["net_profit", "net_profit"],
            "value_avg_native": [2.0, 1.5],
        }
    )
    result = merge_airline_consensus_history(
        prior, current,
        key_columns=["ticker", "snapshot_date", "fiscal_year", "metric"],
    )
    assert len(result) == 2
    assert result.loc[result["snapshot_date"].eq("2026-08-06"), "value_avg_native"].iloc[0] == 1.5
    assert result.loc[result["snapshot_date"].eq("2026-08-07"), "value_avg_native"].iloc[0] == 2.0


def test_normalize_financial_abstract_keeps_money_units_and_point_in_time_caveat() -> None:
    frame = pd.DataFrame(
        {
            "指标": ["归母净利润", "营业总收入", "毛利率", "资产负债率"],
            "20250630": [1_000_000_000, 10_000_000_000, 12.5, 82.0],
        }
    )
    fx = pd.DataFrame(
        {
            "pair": ["USD_CNY"],
            "observation_date": ["2025-06-30"],
            "value": [7.2],
        }
    )

    result = normalize_financial_abstract(
        frame,
        symbol="600029",
        company="China Southern Airlines",
        fx_rates=fx,
        retrieved_at="2026-08-06T00:00:00+00:00",
    )

    profit = result.loc[result["metric"].eq("attributable_net_income")].iloc[0]
    assert profit["value_native"] == 1000
    assert profit["native_unit"] == "RMB million"
    assert profit["value_usd"] == 1000 / 7.2
    assert profit["fx_observation_date"] == "2025-06-30"
    assert result["announcement_date_available"].eq(False).all()
    assert result["source_quality"].eq("akshare_discovery").all()
    assert result.loc[result["metric"].eq("gross_margin"), "value_usd"].isna().all()


def test_normalize_profit_forecast_translates_only_net_profit_at_snapshot_fx() -> None:
    frame = pd.DataFrame(
        {
            "年度": [2026, 2027],
            "预测机构数": [10, 9],
            "最小值": [-1.0, 2.0],
            "均值": [4.0, 6.0],
            "最大值": [8.0, 10.0],
            "行业平均数": [5.0, 7.0],
        }
    )
    fx = pd.DataFrame(
        {
            "pair": ["USD_CNY"],
            "observation_date": ["2026-08-06"],
            "value": [7.0],
        }
    )

    net_profit = normalize_profit_forecast(
        frame,
        symbol="600029",
        company="China Southern Airlines",
        metric="net_profit",
        fx_rates=fx,
        snapshot_date="2026-08-06",
        forecast_date_min="2026-05-01",
        forecast_date_max="2026-08-05",
        retrieved_at="2026-08-06T00:00:00+00:00",
    )
    eps = normalize_profit_forecast(
        frame,
        symbol="600029",
        company="China Southern Airlines",
        metric="eps",
        fx_rates=fx,
        snapshot_date="2026-08-06",
        retrieved_at="2026-08-06T00:00:00+00:00",
    )

    assert len(net_profit) == 2
    assert net_profit.iloc[0]["value_avg_usd_at_snapshot"] == 4 / 7
    assert net_profit.iloc[0]["native_unit"] == "RMB 100 million"
    assert net_profit.iloc[0]["forecast_date_max"] == "2026-08-05"
    assert eps["value_avg_usd_at_snapshot"].isna().all()
    assert eps["native_unit"].eq("RMB/share").all()


def test_normalize_detailed_indicator_forecast_adds_revenue_expectations() -> None:
    frame = pd.DataFrame(
        {
            "预测指标": ["营业收入(元)", "营业收入增长率", "净资产收益率"],
            "2025-实际值": ["1822.56亿", "4.61%", "1.20%"],
            "预测2026-平均": ["2031.23亿", "11.45%", "5.50%"],
            "预测2027-平均": ["2149.21亿", "5.82%", "8.10%"],
        }
    )
    fx = pd.DataFrame(
        {"pair": ["USD_CNY"], "observation_date": ["2026-08-06"], "value": [7.0]}
    )
    result = normalize_detailed_indicator_forecast(
        frame,
        symbol="600029",
        company="China Southern Airlines",
        fx_rates=fx,
        snapshot_date="2026-08-06",
        forecast_date_min="2026-05-01",
        forecast_date_max="2026-08-05",
        retrieved_at="2026-08-06T00:00:00+00:00",
    )

    revenue = result.loc[
        (result["metric"] == "revenue") & (result["fiscal_year"] == 2026)
    ].iloc[0]
    growth = result.loc[
        (result["metric"] == "revenue_growth") & (result["fiscal_year"] == 2026)
    ].iloc[0]
    assert revenue["value_avg_native"] == pytest.approx(2031.23)
    assert revenue["value_avg_usd_at_snapshot"] == pytest.approx(2031.23 / 7.0)
    assert revenue["native_unit"] == "RMB 100 million"
    assert growth["value_avg_native"] == pytest.approx(11.45)
    assert result["revision_history_available"].eq(False).all()


def test_normalize_sell_side_forecast_revisions_compares_same_broker_and_year() -> None:
    frame = pd.DataFrame(
        {
            "ticker": ["01055.HK / 600029.SH"] * 2,
            "company": ["China Southern Airlines"] * 2,
            "report_date": ["2026-01-01", "2026-02-01"],
            "institution": ["Test Securities"] * 2,
            "rating": ["增持", "买入"],
            "report_title": ["old", "new"],
            "eps_2026_native": [0.20, 0.30],
            "eps_2027_native": [None, None],
            "eps_2028_native": [None, None],
            "report_url": ["https://example.com/old", "https://example.com/new"],
        }
    )
    result = normalize_sell_side_forecast_revisions(frame, retrieved_at="2026-08-06")

    assert len(result) == 2
    latest = result.iloc[-1]
    assert latest["prior_report_date"] == "2026-01-01"
    assert latest["eps_change_native"] == pytest.approx(0.10)
    assert latest["eps_change_pct"] == pytest.approx(50.0)
    assert latest["source_quality"] == "akshare_discovery"
