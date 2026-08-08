from __future__ import annotations

import pandas as pd


def test_eastmoney_consensus_snapshot_covers_six_airline_names() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_consensus_em_snapshot.csv")

    assert len(frame) == 24
    assert frame["company"].nunique() == 6
    assert set(frame["fiscal_year"]) == {2025, 2026, 2027, 2028}
    current = frame.loc[frame["fiscal_year"].eq(2026)]
    assert current["eps_avg_native"].notna().all()
    assert current["rating_total_count"].gt(0).all()
    assert current["buy_add_pct"].between(0, 100).all()
    assert current["source_quality"].eq("akshare_discovery").all()
    assert current["revision_history_available"].eq(False).all()
    assert current["source_url"].str.contains("eastmoney.com").all()


def test_normalize_eastmoney_forecast_keeps_rating_counts_and_usd_eps() -> None:
    from hk_transport.sources.airline_consensus_em import normalize_em_profit_forecast

    source = pd.DataFrame(
        {
            "代码": ["601111"], "名称": ["中国国航"], "研报数": [11],
            "机构投资评级(近六个月)-买入": [6], "机构投资评级(近六个月)-增持": [5],
            "机构投资评级(近六个月)-中性": [0], "机构投资评级(近六个月)-减持": [0],
            "机构投资评级(近六个月)-卖出": [0], "2025预测每股收益": [-0.08],
            "2026预测每股收益": [0.01], "2027预测每股收益": [0.30],
            "2028预测每股收益": [0.56],
        }
    )
    fx = pd.DataFrame({"pair": ["USD_CNY"], "observation_date": ["2026-08-07"], "value": [7.0]})
    result = normalize_em_profit_forecast(
        source, fx_rates=fx, snapshot_date="2026-08-07", retrieved_at="2026-08-07T00:00:00+00:00"
    )
    row = result.loc[result["fiscal_year"].eq(2026)].iloc[0]
    assert row["rating_total_count"] == 11
    assert row["buy_add_pct"] == 100.0
    assert row["eps_avg_usd_at_snapshot"] == 0.01 / 7.0


def test_eastmoney_history_is_append_only_by_snapshot_key() -> None:
    from hk_transport.sources.airline_consensus_em import merge_em_consensus_history

    prior = pd.DataFrame(
        {"ticker": ["601021.SH"], "snapshot_date": ["2026-08-06"], "fiscal_year": [2026], "eps_avg_native": [2.0]}
    )
    current = pd.DataFrame(
        {"ticker": ["601021.SH", "601021.SH"], "snapshot_date": ["2026-08-06", "2026-08-07"], "fiscal_year": [2026, 2026], "eps_avg_native": [2.1, 2.2]}
    )
    result = merge_em_consensus_history(prior, current)
    assert len(result) == 2
    assert result.loc[result["snapshot_date"].eq("2026-08-06"), "eps_avg_native"].item() == 2.1
    assert result.loc[result["snapshot_date"].eq("2026-08-07"), "eps_avg_native"].item() == 2.2
