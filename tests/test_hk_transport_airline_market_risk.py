from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_market_risk import build_airline_market_risk_metrics


def test_market_risk_snapshot_covers_universe_and_explicitly_excludes_borrow_data() -> None:
    result = pd.read_csv("data/normalized/hk_transport/airline_market_risk_metrics.csv")
    result = result.loc[result["snapshot_date"].eq(result["snapshot_date"].max())].copy()

    assert len(result) == 7
    assert result["company"].nunique() == 7
    assert result["snapshot_date"].eq("2026-08-07").all()
    assert result["beta_to_benchmark"].notna().all()
    assert result["annualized_volatility_pct"].gt(0).all()
    assert result["max_drawdown_pct"].le(0).all()
    assert result["median_daily_turnover_usd_mn_60d"].gt(0).all()
    assert result["borrow_data_available"].eq(False).all()
    assert result["source_quality"].eq("yfinance_discovery").all()


def test_market_risk_builder_uses_explicit_benchmark_and_window() -> None:
    result = build_airline_market_risk_metrics()

    assert set(result["benchmark_ticker"]) == {"^HSI", "000300.SS"}
    assert result["window_label"].eq("1y_daily").all()
    assert result["source_url"].str.contains("finance.yahoo.com/quote").all()
