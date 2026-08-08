from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources.airline_revenue_consensus import normalize_revenue_estimate_frame
from hk_transport.sources.airline_revenue_consensus import merge_revenue_consensus_history


def test_normalize_revenue_estimates_keeps_range_and_analyst_count() -> None:
    raw = pd.DataFrame(
        {
            "avg": [130_859_069_970, 133_067_928_359],
            "low": [121_818_000_000, 119_757_000_000],
            "high": [139_047_423_970, 140_557_515_530],
            "numberOfAnalysts": [14, 14],
            "yearAgoRevenue": [116_766_000_000, 130_859_069_970],
            "growth": [0.1207, 0.0169],
        },
        index=["0y", "+1y"],
    )
    result = normalize_revenue_estimate_frame(
        raw,
        ticker="0293.HK",
        source_ticker="0293.HK",
        company="Cathay Pacific",
        market="HK",
        currency="HKD",
        snapshot_date="2026-08-06",
        retrieved_at="2026-08-06T00:00:00+00:00",
    )

    current = result.loc[result["forecast_period"].eq("0y")].iloc[0]
    assert current["fiscal_year"] == 2026
    assert current["revenue_avg_native_mn"] == pytest.approx(130859.06997)
    assert current["revenue_low_native_mn"] == pytest.approx(121818.0)
    assert current["revenue_high_native_mn"] == pytest.approx(139047.42397)
    assert current["analyst_count"] == 14
    assert current["growth_pct"] == pytest.approx(12.07)
    assert current["revision_history_available"] == False


def test_normalize_revenue_estimates_skips_zero_provider_rows() -> None:
    raw = pd.DataFrame(
        {
            "avg": [0, 100], "low": [0, 90], "high": [0, 110],
            "numberOfAnalysts": [0, 1], "yearAgoRevenue": [None, 80],
            "growth": [None, 0.25],
        },
        index=["0y", "+1y"],
    )
    result = normalize_revenue_estimate_frame(
        raw,
        ticker="600221.SH",
        source_ticker="600221.SS",
        company="Hainan Airlines Holdings",
        market="CN_A",
        currency="RMB",
        snapshot_date="2026-08-06",
    )
    assert result["forecast_period"].tolist() == ["+1y"]


def test_revenue_consensus_history_appends_point_in_time_snapshots() -> None:
    base = pd.DataFrame(
        {
            "ticker": ["0293.HK", "0293.HK"],
            "snapshot_date": ["2026-08-06", "2026-08-06"],
            "forecast_period": ["0y", "+1y"],
            "fiscal_year": [2026, 2027],
            "revenue_avg_native_mn": [100.0, 110.0],
        }
    )
    current = pd.DataFrame(
        {
            "ticker": ["0293.HK", "0293.HK"],
            "snapshot_date": ["2026-08-07", "2026-08-06"],
            "forecast_period": ["0y", "+1y"],
            "fiscal_year": [2026, 2027],
            "revenue_avg_native_mn": [102.0, 111.0],
        }
    )
    result = merge_revenue_consensus_history(base, current)
    assert len(result) == 3
    assert result.loc[
        (result["snapshot_date"] == "2026-08-07") & result["forecast_period"].eq("0y"),
        "revenue_avg_native_mn",
    ].iloc[0] == 102.0
    assert result.loc[
        (result["snapshot_date"] == "2026-08-06") & result["forecast_period"].eq("+1y"),
        "revenue_avg_native_mn",
    ].iloc[0] == 111.0
