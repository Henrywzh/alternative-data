from __future__ import annotations

import numpy as np
import pandas as pd

from src.hk_transport.sources.airline_pair_factor_residual_test import (
    YF_SYMBOLS,
    build_airline_pair_factor_residual_test,
)


def test_factor_residual_test_runs_on_dated_synthetic_bars() -> None:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=240, freq="B")
    rows: list[dict[str, object]] = []
    for asset, symbol in YF_SYMBOLS.items():
        prices = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, len(dates))))
        rows.extend(
            {
                "ticker": symbol,
                "observation_date": date.date().isoformat(),
                "adj_close": float(price),
            }
            for date, price in zip(dates, prices)
        )
    bars = pd.DataFrame(rows)
    pair_risk = pd.DataFrame(
        [
            {
                "pair_id": "601021.SH__603885.SH",
                "asset_a": "601021.SH",
                "company_a": "Spring Airlines",
                "asset_b": "603885.SH",
                "company_b": "Juneyao Airlines",
                "same_market": True,
                "beta_a_to_b": 1.0,
            }
        ]
    )
    market_snapshot = pd.DataFrame(
        [
            {"ticker": asset, "market_cap_usd_mn": float(index + 1) * 1000.0}
            for index, asset in enumerate(YF_SYMBOLS)
        ]
    )
    pb_valuation = pd.DataFrame(
        [{"asset": asset, "current_pb": 1.0 + index / 10.0} for index, asset in enumerate(YF_SYMBOLS)]
    )

    result, factors = build_airline_pair_factor_residual_test(
        bars=bars,
        pair_risk=pair_risk,
        market_snapshot=market_snapshot,
        pb_valuation=pb_valuation,
        retrieved_at="2026-08-08T00:00:00+00:00",
    )

    assert len(result) == 1
    assert result.iloc[0].regression_status == "estimated"
    assert result.iloc[0].observations >= 60
    assert result.iloc[0].point_in_time_status.startswith("price_history_dated")
    assert len(factors) > 0
    assert factors.market_factor_return.notna().any()

