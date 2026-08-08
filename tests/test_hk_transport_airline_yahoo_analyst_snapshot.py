from __future__ import annotations

from pathlib import Path

import pandas as pd

from hk_transport.sources.airline_yahoo_analyst_snapshot import (
    merge_yahoo_analyst_history,
    normalize_yahoo_analyst_frames,
)


ITEM = {
    "ticker": "0293.HK",
    "source_ticker": "0293.HK",
    "company": "Cathay Pacific",
    "market": "HK",
    "currency": "HKD",
}


def test_normalize_yahoo_analyst_frames_keeps_estimates_revisions_and_ratings_separate() -> None:
    earnings = pd.DataFrame(
        {
            "avg": [1.2, 1.5], "low": [1.0, 1.3], "high": [1.4, 1.7],
            "yearAgoEps": [1.1, 1.2], "numberOfAnalysts": [5, 5], "growth": [0.1, 0.2],
        }, index=["0y", "+1y"]
    )
    revenue = pd.DataFrame(
        {
            "avg": [10_000_000, 11_000_000], "low": [9_000_000, 10_000_000],
            "high": [12_000_000, 13_000_000], "yearAgoRevenue": [9_000_000, 10_000_000],
            "numberOfAnalysts": [5, 5], "growth": [0.1, 0.1],
        }, index=["0y", "+1y"]
    )
    revisions = pd.DataFrame(
        {
            "upLast7days": [1, 2], "upLast30days": [2, 3],
            "downLast30days": [0, 1], "downLast7Days": [0, 1],
        }, index=["0y", "+1y"]
    )
    recommendations = pd.DataFrame(
        {"strongBuy": [2, 1], "buy": [3, 3], "hold": [1, 2], "sell": [0, 1], "strongSell": [0, 0]},
        index=["0m", "-1m"]
    )
    growth = pd.DataFrame({"stockTrend": [0.2], "indexTrend": [0.1]}, index=["0y"])

    result = normalize_yahoo_analyst_frames(
        item=ITEM,
        earnings_estimate=earnings,
        revenue_estimate=revenue,
        eps_revisions=revisions,
        recommendations=recommendations,
        growth_estimates=growth,
        snapshot_date="2026-08-07",
        retrieved_at="2026-08-07T00:00:00+00:00",
    )

    assert set(result["metric"]) == {
        "revenue_estimate", "eps_estimate", "eps_revision_signal",
        "recommendation_trend", "growth_estimate",
    }
    revenue_row = result.loc[(result["metric"] == "revenue_estimate") & (result["period"] == "0y")].iloc[0]
    assert revenue_row["value_avg_native"] == 10.0
    revision_row = result.loc[(result["metric"] == "eps_revision_signal") & (result["period"] == "0y")].iloc[0]
    assert bool(revision_row["revision_signal_available"]) is True
    rating_row = result.loc[(result["metric"] == "recommendation_trend") & (result["period"] == "0m")].iloc[0]
    assert rating_row["rating_total"] == 6.0
    assert rating_row["buy_add_pct"] == 83.33333333333333
    assert result["revision_history_available"].eq(False).all()


def test_yahoo_analyst_history_replaces_only_same_snapshot_key() -> None:
    prior = pd.DataFrame(
        [{"ticker": "0293.HK", "snapshot_date": "2026-08-07", "metric": "eps_estimate", "period": "0y", "value_avg_native": 1.0}]
    )
    current = prior.copy()
    current.loc[0, "value_avg_native"] = 1.2
    result = merge_yahoo_analyst_history(prior, current)
    assert len(result) == 1
    assert result.iloc[0]["value_avg_native"] == 1.2


def test_current_yahoo_analyst_snapshot_has_multiple_evidence_types() -> None:
    path = Path("data/normalized/hk_transport/airline_yahoo_analyst_snapshot.csv")
    frame = pd.read_csv(path)
    latest = frame.loc[frame["snapshot_date"].eq(frame["snapshot_date"].max())]
    assert len(latest) > 20
    assert latest["company"].nunique() >= 7
    assert {"revenue_estimate", "eps_estimate", "recommendation_trend"}.issubset(set(latest["metric"]))
    assert not latest.loc[latest["metric"].eq("recommendation_trend"), "period"].astype(str).isin({"0", "1", "2", "3"}).any()
    assert latest["source_quality"].eq("yfinance_discovery").all()
    assert latest["source_url"].notna().all()
