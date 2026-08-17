"""Tests for consensus reverse engineering v2 (sanity checks + surface)."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources import airline_consensus_reverse_v2 as crv2


@pytest.fixture(scope="module")
def outputs() -> dict[str, pd.DataFrame]:
    return crv2.build_airline_consensus_reverse_v2()


def test_sanity_covers_all_carriers(outputs: dict[str, pd.DataFrame]) -> None:
    s = outputs["sanity"]
    assert set(s.company) == set(crv2.COMPANIES)


def test_spring_annualisation_valid_and_roughly_x2(outputs: dict[str, pd.DataFrame]) -> None:
    s = outputs["sanity"].set_index("company")
    spring = s.loc["Spring Airlines"]
    assert bool(spring.h1_annualisation_valid)
    assert spring.seasonality_fy_multiplier == pytest.approx(2.03, abs=0.05)
    assert not bool(spring.annualisation_mismatch_flagged)


def test_juneyao_annualisation_mismatch_flagged(outputs: dict[str, pd.DataFrame]) -> None:
    """The x2 convention understates Juneyao's FY surprise (H1 share ~37%)."""
    s = outputs["sanity"].set_index("company")
    juneyao = s.loc["Juneyao Airlines"]
    assert bool(juneyao.h1_annualisation_valid)
    assert bool(juneyao.annualisation_mismatch_flagged)
    assert juneyao.seasonality_fy_multiplier > 2.4
    assert juneyao.surprise_vs_consensus_season_adj_pct > juneyao.surprise_vs_consensus_x2_pct


def test_loss_year_carriers_not_annualised(outputs: dict[str, pd.DataFrame]) -> None:
    s = outputs["sanity"].set_index("company")
    for company in ["Air China", "China Eastern Airlines", "China Southern Airlines", "Hainan Airlines Holdings"]:
        assert not bool(s.loc[company, "h1_annualisation_valid"])
        assert pd.isna(s.loc[company, "surprise_vs_consensus_season_adj_pct"])


def test_share_count_checks(outputs: dict[str, pd.DataFrame]) -> None:
    s = outputs["sanity"].set_index("company")
    assert bool(s.loc["Spring Airlines", "share_count_sane"])
    assert bool(s.loc["Juneyao Airlines", "share_count_sane"])


def test_one_off_flags(outputs: dict[str, pd.DataFrame]) -> None:
    s = outputs["sanity"].set_index("company")
    # Spring's 1H2025 other income is 32% of H1 PBT - must be flagged.
    assert bool(s.loc["Spring Airlines", "one_off_flagged"])


def test_surface_built(outputs: dict[str, pd.DataFrame]) -> None:
    sf = outputs["surface"]
    assert len(sf) >= 6
    assert {"consensus_implied_rask_native", "implied_rask_gap_vs_model_pct"}.issubset(sf.columns)
    assert sf.implied_rask_gap_vs_model_pct.notna().all()


def test_surface_spring_gap_small(outputs: dict[str, pd.DataFrame]) -> None:
    """Spring's consensus implies only a ~2.6% RASK gap vs our model - the
    +65% EPS gap is NOT a yield disagreement, it is a cost/profit-level one."""
    sf = outputs["surface"].set_index("company")
    spring = sf.loc["Spring Airlines"]
    assert abs(spring.implied_rask_gap_vs_model_pct) < 6.0
