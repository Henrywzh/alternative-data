from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.cathay_sector_trends import build_cathay_sector_trends


def _sample_frame() -> pd.DataFrame:
    rows = []
    for year, ask, rpk, passengers, aftk, rftk, cargo in (
        (2025, 1000, 800, 100000, 500, 250, 10000),
        (2026, 1200, 1020, 110000, 550, 302.5, 11000),
    ):
        for month in range(1, 7):
            rows.append({
                "month": f"{year}-{month:02d}",
                "cathay_ask_thousands": ask,
                "cathay_rpk_thousands": rpk,
                "cathay_passengers": passengers,
                "cathay_aftk_thousands": aftk,
                "cathay_rftk_thousands": rftk,
                "cathay_cargo_tonnes": cargo,
            })
    return pd.DataFrame(rows)


def test_build_cathay_sector_trends_normalizes_units_and_weights_load_factor():
    result = build_cathay_sector_trends(_sample_frame(), retrieved_at="2026-08-06T00:00:00+00:00")

    assert set(result["metric"]) == {
        "ask", "rpk", "passengers", "aftk", "rftk", "cargo_tonnes",
        "passenger_load_factor_pct", "freight_load_factor_pct",
    }
    ask = result.loc[result["metric"].eq("ask")].iloc[0]
    assert ask["prior_value"] == 6.0
    assert ask["current_value"] == 7.2
    assert ask["yoy_change_pct"] == pytest.approx(20.0)
    assert ask["unit"] == "million seat-km"

    passenger_lf = result.loc[result["metric"].eq("passenger_load_factor_pct")].iloc[0]
    assert passenger_lf["prior_value"] == pytest.approx(80.0)
    assert passenger_lf["current_value"] == pytest.approx(85.0)
    assert passenger_lf["quality_flag"] == "ok"
    assert result["source_note"].str.contains("kept separate").all()


def test_build_cathay_sector_trends_rejects_missing_core_fields():
    try:
        build_cathay_sector_trends(pd.DataFrame({"month": ["2026-01"]}))
    except ValueError as exc:
        assert "cathay_ask_thousands" in str(exc)
    else:
        raise AssertionError("missing core Cathay fields should fail loudly")
