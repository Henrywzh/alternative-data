from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_historical_pb_valuation import (
    build_airline_historical_pb_valuation,
)


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pb = pd.DataFrame(
        [
            {"asset": "601021.SH", "observation_date": "2025-08-08", "pb": 3.0},
            {"asset": "601021.SH", "observation_date": "2026-08-07", "pb": 2.0},
            {"asset": "603885.SH", "observation_date": "2025-08-08", "pb": 1.5},
            {"asset": "603885.SH", "observation_date": "2026-08-07", "pb": 2.5},
        ]
    )
    drivers = pd.DataFrame(
        [
            {"company": "Spring Airlines", "metric": "equity_attributable", "value_usd": 1000.0, "statement_period": "FY2025", "period_end": "2025-12-31", "announced_at": "2026-04-11"},
            {"company": "Juneyao Airlines", "metric": "equity_attributable", "value_usd": 800.0, "statement_period": "FY2025", "period_end": "2025-12-31", "announced_at": "2026-04-30"},
        ]
    )
    working = pd.DataFrame(
        [
            {"asset_a": "601021.SH", "current_price_a_native": 100.0, "asset_b": "603885.SH", "current_price_b_native": 20.0}
        ]
    )
    return pb, drivers, working


def test_pb_history_creates_percentile_and_target_diagnostics() -> None:
    pb, drivers, working = _inputs()
    frame = build_airline_historical_pb_valuation(pb_history=pb, drivers=drivers, working=working, retrieved_at="2026-08-08T00:00:00+00:00")
    spring = frame[frame.asset.eq("601021.SH")].iloc[0]
    assert spring.pb_observation_count == 2
    assert spring.current_pb == 2.0
    assert spring.pb_median_1y == 2.5
    assert spring.pb_target_return_median_pct == 25.0
    assert spring.equity_basis_usd_mn == 1000.0
    assert "pending_1H2026_refresh" in spring.valuation_status


def test_missing_asset_history_remains_explicitly_missing() -> None:
    pb, drivers, working = _inputs()
    frame = build_airline_historical_pb_valuation(pb_history=pb.iloc[0:0], drivers=drivers, working=working)
    spring = frame[frame.asset.eq("601021.SH")].iloc[0]
    assert spring.pb_observation_count == 0
    assert pd.isna(spring.current_pb)
    assert spring.valuation_status == "missing_pb_or_equity_basis"


def test_cathay_pb_history_is_retained_but_equity_basis_gap_is_explicit() -> None:
    pb = pd.DataFrame(
        [{"asset": "0293.HK", "observation_date": "2026-08-07", "pb": 1.5}]
    )
    market_snapshot = pd.DataFrame(
        [{"ticker": "0293.HK", "latest_price_native": 14.91}]
    )
    frame = build_airline_historical_pb_valuation(
        pb_history=pb,
        drivers=pd.DataFrame(),
        cathay_basis=pd.DataFrame(),
        working=pd.DataFrame(),
        market_snapshot=market_snapshot,
    )
    cathay = frame.loc[frame.asset.eq("0293.HK")].iloc[0]
    assert cathay.pb_observation_count == 1
    assert cathay.current_price_native == 14.91
    assert cathay.current_price_source == "airline_market_snapshot"
    assert cathay.valuation_status == "missing_pb_or_equity_basis"
