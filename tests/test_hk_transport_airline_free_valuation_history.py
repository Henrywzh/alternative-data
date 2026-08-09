from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_free_valuation_history import (
    AIRLINE_CONFIG,
    build_airline_valuation_source_matrix,
)


def test_cathay_is_registered_as_a_free_hk_valuation_leg() -> None:
    config = AIRLINE_CONFIG["0293.HK"]
    assert config["company"] == "Cathay Pacific"
    assert config["market"] == "HK"
    assert config["baidu_symbol"] == "00293"
    assert config["eastmoney_symbol"] == "00293"


def test_source_matrix_distinguishes_direct_history_from_current_ps() -> None:
    history = pd.DataFrame(
        [
            {
                "asset": "601021.SH",
                "company": "Spring Airlines",
                "market": "CN_A",
                "observation_date": "2024-01-02",
                "metric": "pb",
                "value": 3.0,
            },
            {
                "asset": "601021.SH",
                "company": "Spring Airlines",
                "market": "CN_A",
                "observation_date": "2026-08-07",
                "metric": "pb",
                "value": 2.0,
            },
        ]
    )
    current = pd.DataFrame(
        [
            {
                "asset": "601021.SH",
                "metric": "ps_ttm",
                "value": 2.1,
            }
        ]
    )
    matrix = build_airline_valuation_source_matrix(
        history=history,
        current=current,
        retrieved_at="2026-08-08T00:00:00+00:00",
    )
    pb = matrix.loc[matrix.asset.eq("601021.SH") & matrix.metric.eq("pb")].iloc[0]
    ps = matrix.loc[matrix.asset.eq("601021.SH") & matrix.metric.eq("ps_ttm")].iloc[0]
    assert pb.coverage_status == "dated_history"
    assert pb.observation_count == 2
    assert pb.observation_start_date == "2024-01-02"
    assert pb.observation_end_date == "2026-08-07"
    assert ps.coverage_status == "current_only"
    assert not ps.direct_history_available
    assert ps.current_snapshot_available
    assert "construct" in ps.next_action


def test_missing_free_metric_is_explicit() -> None:
    matrix = build_airline_valuation_source_matrix(
        history=pd.DataFrame(),
        current=pd.DataFrame(),
    )
    row = matrix.loc[matrix.asset.eq("01055.HK") & matrix.metric.eq("pe_ttm")].iloc[0]
    assert row.coverage_status == "missing"
    assert row.observation_count == 0
    assert row.point_in_time_status == "vendor_dated_ratio_denominator_semantics_unverified"
