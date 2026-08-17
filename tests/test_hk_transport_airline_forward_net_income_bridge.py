from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.hk_transport.config import NORMALIZED_DIR
from src.hk_transport.sources.airline_forward_net_income_bridge import (
    OUTPUT_COLUMNS,
    build_airline_forward_net_income_bridge,
)


@pytest.fixture(scope="module")
def bridge() -> pd.DataFrame:
    return build_airline_forward_net_income_bridge()


def test_bridge_columns_and_persistence(bridge: pd.DataFrame) -> None:
    assert not bridge.empty
    assert bridge.columns.tolist() == OUTPUT_COLUMNS
    assert (NORMALIZED_DIR / "airline_forward_net_income_bridge.csv").exists()


def test_core_pair_built_for_all_model_variants(bridge: pd.DataFrame) -> None:
    spring = bridge[bridge["company"].eq("Spring Airlines")]
    juneyao = bridge[bridge["company"].eq("Juneyao Airlines")]
    assert len(spring) == 5
    assert len(juneyao) == 5
    assert spring["bridge_status"].eq("available_h1_2025_interim_waterfall").all()
    assert juneyao["bridge_status"].eq("available_h1_2025_interim_waterfall").all()
    # Spring NCI ~ 0, Juneyao ~ 0 (both reconcile attributable ~ net income).
    assert (spring["h1_2025_nci_share_pct"].abs() < 0.1).all()
    assert (juneyao["h1_2025_nci_share_pct"].abs() < 0.1).all()


def test_pair_spread_direction_matches_long_spring_short_juneyao(
    bridge: pd.DataFrame,
) -> None:
    spring = bridge[bridge["company"].eq("Spring Airlines")].set_index("model_name")
    juneyao = bridge[bridge["company"].eq("Juneyao Airlines")].set_index("model_name")
    for model in spring.index:
        spread = (
            spring.loc[model, "forward_attributable_net_income_native_mn"]
            - juneyao.loc[model, "forward_attributable_net_income_native_mn"]
        )
        assert spread > 0


def test_eps_uses_implied_share_count(bridge: pd.DataFrame) -> None:
    spring = bridge[bridge["company"].eq("Spring Airlines")]
    row = spring[spring["model_name"].eq("flat_ask")].iloc[0]
    expected_eps = (
        row["forward_attributable_net_income_native_mn"]
        / row["implied_basic_shares_mn"]
    )
    assert row["forward_basic_eps_rmb_per_share"] == pytest.approx(expected_eps)


def test_tax_method_labelled_per_regime(bridge: pd.DataFrame) -> None:
    # Spring has a normal positive effective rate -> rate method on forward PBT.
    spring = bridge[bridge["company"].eq("Spring Airlines")]
    assert (
        spring["forward_income_tax_method"]
        .eq("h1_2025_effective_rate_on_forward_pbt")
        .all()
    )
    # Southern's loss-year 239.6% rate is outside the guard -> absolute carry.
    southern = bridge[bridge["company"].eq("China Southern Airlines")]
    assert southern["forward_income_tax_method"].eq("h1_2025_absolute_carry").all()


def test_missing_companies_carried_as_labelled_gaps(bridge: pd.DataFrame) -> None:
    # Air China's interim income statement is embedded as CID-font image
    # pages, so its bridge uses the annual-waterfall fallback with a clear
    # status label rather than a silent gap.
    air_china = bridge[bridge["company"].eq("Air China")]
    assert (
        air_china["bridge_status"]
        .eq("available_annual_waterfall_interim_pbt_calibrated")
        .all()
    )
    assert air_china["forward_attributable_net_income_native_mn"].notna().all()
    assert air_china["forward_basic_eps_rmb_per_share"].notna().all()
    # The fallback scales annual below-operating lines to the interim revenue
    # base, so finance cost must stay below the FY2025 annual level.
    row = air_china[air_china["model_name"].eq("flat_ask")].iloc[0]
    assert row["forward_finance_cost_native_mn"] < row["h1_2025_finance_cost_native_mn"]


def test_all_six_companies_build_with_five_model_variants(bridge: pd.DataFrame) -> None:
    companies = bridge["company"].unique()
    assert len(companies) == 6
    counts = bridge.groupby("company")["model_name"].count()
    assert (counts == 5).all()
    assert bridge["forward_attributable_net_income_native_mn"].notna().sum() == 30
