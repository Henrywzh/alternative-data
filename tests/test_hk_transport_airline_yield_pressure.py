from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_yield_pressure import (
    PRIOR_WEIGHTS,
    _attach_validation,
    _zscore,
)


def test_prior_weights_follow_economic_direction() -> None:
    # Demand-capacity gap is the dominant positive driver; competitive
    # capacity is a negative modifier.
    assert PRIOR_WEIGHTS["rpk_ask_gap"] > PRIOR_WEIGHTS["lf_change"]
    assert PRIOR_WEIGHTS["lf_change"] > 0
    assert PRIOR_WEIGHTS["intl_mix"] > 0
    assert PRIOR_WEIGHTS["industry_ask"] < 0


def test_zscore_normalises_and_handles_constant_series() -> None:
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = _zscore(s)
    assert abs(z.mean()) < 1e-9
    assert abs(z.std(ddof=0) - 1.0) < 1e-9
    constant = pd.Series([3.0, 3.0, 3.0])
    assert (_zscore(constant) == 0.0).all()


def test_build_index_covers_all_carriers_and_recent_months() -> None:
    from src.hk_transport.sources.airline_yield_pressure import (
        build_airline_yield_pressure_index,
    )

    df = build_airline_yield_pressure_index()
    assert len(df) >= 600
    assert df["company"].nunique() == 6
    assert df["month"].max() >= "2026-06"
    assert df["yield_pressure_score"].notna().all()
    assert df["validation_status"].str.startswith("validation_limited").all()


def test_validation_summary_is_written_and_honest() -> None:
    from pathlib import Path

    from src.hk_transport.config import NORMALIZED_DIR

    p = NORMALIZED_DIR / "airline_yield_pressure_validation.csv"
    assert p.exists()
    v = pd.read_csv(p)
    assert "spearman_rank_corr" in v.columns
    assert "pearson_corr" in v.columns
    # The all-year mean should not be claimed as strong; the file carries the
    # per-year numbers so the reader can judge (including negative years).
    assert len(v) >= 5


def test_attach_validation_returns_summary_frame() -> None:
    index_df = pd.DataFrame(
        [
            {"company": "Spring Airlines", "month": "2025-01", "yield_pressure_score": 0.5},
            {"company": "Juneyao Airlines", "month": "2025-01", "yield_pressure_score": 0.2},
        ]
    )
    walk = pd.DataFrame(
        [
            {
                "company": "Spring Airlines",
                "target_year": 2025,
                "revenue_per_rpk_growth_actual_pct": -4.3,
            },
            {
                "company": "Juneyao Airlines",
                "target_year": 2025,
                "revenue_per_rpk_growth_actual_pct": -1.4,
            },
        ]
    )
    result, summary = _attach_validation(index_df, walk)
    assert result["validation_direction_consistent"].notna().any()
    assert isinstance(summary, pd.DataFrame)
