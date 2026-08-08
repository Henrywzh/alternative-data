from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_market_snapshot import build_market_snapshot, merge_market_expectations


def test_build_market_snapshot_keeps_quote_and_market_cap_timestamps_separate(monkeypatch) -> None:
    universe = (
        {
            "ticker": "601111.SH",
            "symbol": "601111",
            "market": "CN_A",
            "company": "Air China",
            "currency": "RMB",
            "valuation_function": "stock_zh_valuation_baidu",
            "valuation_symbol": "601111",
        },
    )

    monkeypatch.setattr(
        "hk_transport.sources.airline_market_snapshot._tencent_quotes",
        lambda universe, session: {"601111.SH": (pd.Timestamp("2026-08-06T10:00:00+08:00"), 6.5)},
    )
    monkeypatch.setattr(
        "hk_transport.sources.airline_market_snapshot._latest_baidu_market_cap",
        lambda symbol, function_name: ("2026-08-05", 1250.0),
    )
    fx = pd.DataFrame(
        {"pair": ["USD_CNY"], "observation_date": ["2026-08-05"], "value": [7.0]}
    )

    result = build_market_snapshot(universe=universe, fx_rates=fx, retrieved_at="2026-08-06T00:00:00+00:00")
    row = result.iloc[0]
    assert row["snapshot_date"] == "2026-08-05"
    assert row["quote_timestamp"].startswith("2026-08-06T10:00:00")
    assert row["latest_price_native"] == 6.5
    assert row["market_cap_native_mn"] == 125000.0
    assert row["market_cap_usd_mn"] == 125000.0 / 7.0
    assert row["source_quality"] == "market_snapshot_discovery"


def test_merge_market_expectations_keeps_native_units_and_calculates_forward_pe() -> None:
    market = pd.DataFrame(
        {
            "ticker": ["601111.SH"], "company": ["Air China"], "market": ["CN_A"],
            "snapshot_date": ["2026-08-06"], "latest_price_native": [6.0],
            "price_currency": ["RMB"], "market_cap_usd_mn": [18000.0],
            "retrieved_at": ["2026-08-06T00:00:00+00:00"],
            "market_cap_native_mn": [126000.0],
        }
    )
    consensus = pd.DataFrame(
        {
            "ticker": ["0753.HK / 601111.SH", "0753.HK / 601111.SH"],
            "fiscal_year": [2026, 2026], "metric": ["eps", "net_profit"],
            "value_avg_native": [0.30, 50.0], "value_low_native": [0.10, 20.0],
            "value_high_native": [0.50, 80.0], "source_quality": ["akshare_discovery"] * 2,
            "snapshot_date": ["2026-08-06"] * 2, "forecast_count": [7, 7],
        }
    )
    detailed = pd.DataFrame(
        {
            "ticker": ["0753.HK / 601111.SH", "0753.HK / 601111.SH"],
            "fiscal_year": [2026, 2026],
            "metric": ["revenue", "revenue_growth"],
            "value_avg_native": [1939.37, 13.09],
            "snapshot_date": ["2026-08-06", "2026-08-06"],
            "source_quality": ["akshare_discovery", "akshare_discovery"],
        }
    )
    result = merge_market_expectations(
        market,
        ashare_consensus=consensus,
        ashare_detailed_consensus=detailed,
        revenue_consensus=pd.DataFrame(),
    )
    row = result.iloc[0]
    assert row["fy2026_eps_avg_native"] == 0.30
    assert row["fy2026_net_profit_avg_native_mn"] == 5000.0
    assert row["consensus_forward_pe"] == 20.0
    assert row["market_cap_to_consensus_net_profit"] == 25.2
    assert row["fy2026_revenue_avg_native_mn"] == 193937.0
    assert row["fy2026_revenue_growth_pct"] == 13.09
    assert row["fy2026_revenue_avg_usd_mn"] > 0
    assert row["market_cap_to_consensus_revenue_usd"] > 0


def test_current_market_snapshot_covers_all_airline_share_classes() -> None:
    market = pd.read_csv("data/normalized/hk_transport/airline_market_snapshot.csv")
    bridge = pd.read_csv("data/normalized/hk_transport/airline_market_expectations_snapshot.csv")

    assert len(market) == 10
    assert market["latest_price_native"].notna().all()
    assert market["market_cap_usd_mn"].notna().all()
    assert market["quote_timestamp"].notna().all()
    assert market["market_cap_observation_date"].notna().all()
    assert len(bridge) == len(market)
    assert bridge.loc[bridge["ticker"].eq("0670.HK"), "fy2026_eps_avg_native"].notna().all()
    assert bridge["fy2026_net_profit_avg_usd_mn"].notna().all()
    assert bridge["fy2026_revenue_avg_usd_mn"].notna().all()
    assert bridge["market_cap_to_consensus_revenue_usd"].notna().all()
    assert bridge["consensus_valuation_quality"].notna().all()
