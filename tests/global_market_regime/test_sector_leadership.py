"""US sector-ETF leadership versus SPY."""

from __future__ import annotations

import pandas as pd

from global_market_regime.sector_leadership import build_sector_leadership


def _prices() -> pd.DataFrame:
    dates = pd.date_range("2026-01-02", periods=260, freq="B")
    rows = []
    for i, date in enumerate(dates):
        rows.append({"date": date, "exposure_id": "us_broad", "close": 100 + i * 0.02})
        rows.append({"date": date, "exposure_id": "us_tech", "close": 100 + i * 0.08})
        rows.append({"date": date, "exposure_id": "us_utilities", "close": 100 + i * 0.01})
    return pd.DataFrame(rows)


def test_sector_leadership_ranks_relative_20d_return() -> None:
    table = build_sector_leadership(
        _prices(),
        sector_ids=("us_tech", "us_utilities"),
        benchmark_id="us_broad",
    )
    assert list(table["exposure_id"]) == ["us_tech", "us_utilities"]
    tech = table.set_index("exposure_id").loc["us_tech"]
    util = table.set_index("exposure_id").loc["us_utilities"]
    assert tech["rel_20d_pct"] > 0
    assert util["rel_20d_pct"] < 0
    assert tech["rank_20d"] == 1
    assert pd.notna(tech["sma200_slope_ann_pct"])


def test_sector_leadership_without_benchmark_is_empty() -> None:
    prices = _prices()
    prices = prices[prices["exposure_id"].ne("us_broad")]
    assert build_sector_leadership(prices).empty
