from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_cathay_equity_basis import build_cathay_equity_basis
from src.hk_transport.sources.airline_historical_pb_valuation import (
    _annotate_pb_history,
    _equity_frame,
)


def test_cathay_equity_basis_has_four_pit_report_anchors_and_check_fields() -> None:
    fx = pd.DataFrame(
        [
            {"pair": "USD_HKD", "observation_date": "2024-12-31", "value": 7.8},
            {"pair": "USD_HKD", "observation_date": "2025-06-30", "value": 7.8},
            {"pair": "USD_HKD", "observation_date": "2025-12-31", "value": 7.8},
            {"pair": "USD_HKD", "observation_date": "2026-06-30", "value": 7.8},
        ]
    )
    frame = build_cathay_equity_basis(fx_rates=fx, retrieved_at="2026-08-08T00:00:00+00:00")

    assert len(frame) == 12
    assert set(frame["statement_period"]) == {"FY2024", "1H2025", "FY2025", "1H2026"}
    assert set(frame["metric"]) == {"equity_attributable", "total_equity", "total_assets"}
    assert frame[["report_id", "statement_period", "metric"]].duplicated().sum() == 0
    assert frame.loc[
        (frame["statement_period"] == "FY2025") & (frame["metric"] == "equity_attributable"),
        "value_usd",
    ].item() == 60110.0 / 7.8
    assert frame.loc[frame["metric"] == "total_assets", "calculation_method"].eq(
        "derived_from_reported_non_current_and_current_assets"
    ).all()
    assert frame["source_quality"].eq("primary_issuer").all()
    assert frame["announced_at"].notna().all()


def test_cathay_daily_pb_basis_changes_only_after_report_announcement() -> None:
    basis = pd.DataFrame(
        [
            {"company": "Cathay Pacific", "metric": "equity_attributable", "statement_period": "1H2025", "period_end": "2025-06-30", "announced_at": "2025-08-06", "value_usd": 100.0},
            {"company": "Cathay Pacific", "metric": "equity_attributable", "statement_period": "FY2025", "period_end": "2025-12-31", "announced_at": "2026-03-11", "value_usd": 200.0},
            {"company": "Cathay Pacific", "metric": "equity_attributable", "statement_period": "1H2026", "period_end": "2026-06-30", "announced_at": "2026-08-05", "value_usd": 300.0},
        ]
    )
    equity = _equity_frame(pd.DataFrame(), basis)
    history = pd.DataFrame(
        [
            {"asset": "0293.HK", "company": "Cathay Pacific", "observation_date": "2025-08-05", "pb": 1.0},
            {"asset": "0293.HK", "company": "Cathay Pacific", "observation_date": "2025-08-06", "pb": 1.0},
            {"asset": "0293.HK", "company": "Cathay Pacific", "observation_date": "2026-03-10", "pb": 1.0},
            {"asset": "0293.HK", "company": "Cathay Pacific", "observation_date": "2026-03-11", "pb": 1.0},
            {"asset": "0293.HK", "company": "Cathay Pacific", "observation_date": "2026-08-04", "pb": 1.0},
            {"asset": "0293.HK", "company": "Cathay Pacific", "observation_date": "2026-08-05", "pb": 1.0},
        ]
    )
    annotated = _annotate_pb_history(history, equity)

    assert pd.isna(annotated.loc[annotated["observation_date"] == "2025-08-05", "equity_basis_usd_mn"].item())
    assert annotated.loc[annotated["observation_date"] == "2025-08-06", "equity_basis_period"].item() == "1H2025"
    assert annotated.loc[annotated["observation_date"] == "2026-03-10", "equity_basis_period"].item() == "1H2025"
    assert annotated.loc[annotated["observation_date"] == "2026-03-11", "equity_basis_period"].item() == "FY2025"
    assert annotated.loc[annotated["observation_date"] == "2026-08-04", "equity_basis_period"].item() == "FY2025"
    assert annotated.loc[annotated["observation_date"] == "2026-08-05", "equity_basis_period"].item() == "1H2026"
