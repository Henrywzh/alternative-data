from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_earnings_sensitivity import (
    _fx_sensitivity_share,
    build_airline_earnings_sensitivity,
)


def test_fx_sensitivity_share_ranks_by_international_exposure() -> None:
    assert _fx_sensitivity_share("Air China") > _fx_sensitivity_share("Spring Airlines")
    assert _fx_sensitivity_share("China Southern Airlines") > _fx_sensitivity_share("Juneyao Airlines")


def test_surface_covers_27_combinations_per_carrier() -> None:
    df = build_airline_earnings_sensitivity()
    assert df["company"].nunique() >= 5
    per_company = df.groupby("company").size()
    assert (per_company == 27).all()
    assert df["shocked_eps_rmb"].notna().all()


def test_spring_eps_stays_positive_in_worst_case_and_pair_spread_is_robust() -> None:
    df = build_airline_earnings_sensitivity()
    spring = df[df["company"].eq("Spring Airlines")]
    juneyao = df[df["company"].eq("Juneyao Airlines")]
    # Worst case: yield -3, fuel +5, fx +3
    worst = spring[
        spring["yield_shock_pct"].eq(-3)
        & spring["fuel_shock_pct"].eq(5)
        & spring["fx_shock_pct"].eq(3)
    ]
    assert worst["shocked_eps_rmb"].iloc[0] > 0.5
    # Pair spread positive across ALL 27 combinations
    sp = spring.set_index(["yield_shock_pct", "fuel_shock_pct", "fx_shock_pct"])
    jy = juneyao.set_index(["yield_shock_pct", "fuel_shock_pct", "fx_shock_pct"])
    spread = sp["shocked_eps_rmb"] - jy["shocked_eps_rmb"]
    assert (spread > 0).all()
    assert spread.min() > 1.0
