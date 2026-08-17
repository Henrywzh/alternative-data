"""Tests for the v4 decomposition revenue model."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources import airline_earnings_model_v4 as v4


@pytest.fixture(scope="module")
def model() -> pd.DataFrame:
    return v4.build_airline_earnings_model_v4()


@pytest.fixture(scope="module")
def ablation() -> pd.DataFrame:
    return pd.read_csv(v4.ABLATION_OUTPUT_PATH)


def test_covers_all_carriers_periods(model: pd.DataFrame) -> None:
    assert set(model.company) == set(v4.COMPANIES)
    assert set(model.period) == set(v4.PERIODS)
    assert len(model) == 108  # 6 carriers x 3 periods x 6 evaluated years


def test_base_decomposition_equals_flat_ask(model: pd.DataFrame) -> None:
    """The decomposition baseline must be algebraically identical to flat-ASK."""
    back = pd.read_csv(v4.BACKTEST_PATH)
    merged = model.merge(
        back[["company", "period", "target_year", "revenue_error_flat_ask_pct"]],
        on=["company", "period", "target_year"],
        how="left",
    )
    diff = (merged.error_base_decomposition_pct - merged.revenue_error_flat_ask_pct).abs()
    assert diff.max() < 1e-9


def test_shrinkage_improves_overall_mae(ablation: pd.DataFrame) -> None:
    base = ablation[ablation.stage.eq("base_decomposition")].iloc[0]
    shrink = ablation[ablation.stage.eq("dynamic_shrinkage")].iloc[0]
    assert shrink["mae_pct"] < base["mae_pct"]
    assert base["mae_regime_years_pct"] > shrink["mae_regime_years_pct"]


def test_full_stack_best_mae(ablation: pd.DataFrame) -> None:
    final = ablation[ablation.stage.eq("recovery_overlay")].iloc[0]
    assert final["mae_pct"] < 8.0
    assert final["mae_pct"] < ablation[ablation.stage.eq("base_decomposition")].iloc[0]["mae_pct"]


def test_recovery_overlay_only_spring_and_labelled(model: pd.DataFrame) -> None:
    active = model[model.recovery_overlay_active.eq(True)]
    assert len(active) > 0
    assert (active.company == "Spring Airlines").all()


def test_walk_forward_no_lookahead(model: pd.DataFrame) -> None:
    """Normal levels must be computable from strictly earlier rows only."""
    # lf_normal for year t equals the median of lf over years < t (verified by
    # construction in _build_series); spot-check one cell against history.
    spring = model[
        (model.company.eq("Spring Airlines"))
        & (model.period.eq("FY"))
        & (model.target_year.eq(2023))
    ].iloc[0]
    back = pd.read_csv(v4.BACKTEST_PATH)
    hist = back[
        (back.company.eq("Spring Airlines"))
        & (back.period.eq("FY"))
        & (back.target_year < 2023)
    ]
    lf_hist = hist.current_fy_rpk_mn / hist.current_fy_ask_mn
    assert spring.lf_normal == pytest.approx(float(lf_hist.median()), rel=1e-9)


def test_yield_modifier_bounded(model: pd.DataFrame) -> None:
    deltas = model.yield_modifier_delta_pct.dropna()
    assert (deltas.abs() <= 3.0).all()


def test_rank_ic_output_written() -> None:
    ic = pd.read_csv(v4.RANK_IC_OUTPUT_PATH)
    assert len(ic) > 0
    assert "rank_ic_recovery_overlay" in ic.columns
