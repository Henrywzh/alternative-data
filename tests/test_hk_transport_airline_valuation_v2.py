"""Tests for valuation v2 (Street vs Own multiples)."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources import airline_valuation_v2 as val


@pytest.fixture(scope="module")
def outputs() -> dict[str, pd.DataFrame]:
    return val.build_airline_valuation_v2()


def test_valuation_covers_all_carriers(outputs: dict[str, pd.DataFrame]) -> None:
    v = outputs["valuation"]
    assert set(v.company) == set(val.COMPANIES)


def test_pair_carriers_have_both_pe_sets(outputs: dict[str, pd.DataFrame]) -> None:
    v = outputs["valuation"].set_index("company")
    for company in ["Spring Airlines", "Juneyao Airlines"]:
        assert v.loc[company, "pe_street"] is not None
        assert v.loc[company, "pe_own"] is not None
        assert v.loc[company, "v4_fy_eps_season_adj_rmb"] is not None


def test_spring_cheaper_than_juneyao_both_sets(outputs: dict[str, pd.DataFrame]) -> None:
    p = outputs["pair"].set_index("metric")
    assert p.loc["pe_street", "spring"] < p.loc["pe_street", "juneyao"]
    assert p.loc["pe_own", "spring"] < p.loc["pe_own", "juneyao"]


def test_own_pe_lower_than_street_pe(outputs: dict[str, pd.DataFrame]) -> None:
    """If our EPS is right, the stock de-rates to a lower P/E (price fixed)."""
    p = outputs["pair"].set_index("metric")
    assert p.loc["pe_own", "spring"] < p.loc["pe_street", "spring"]
    assert p.loc["pe_own", "juneyao"] < p.loc["pe_street", "juneyao"]


def test_near_zero_eps_carriers_have_no_pe(outputs: dict[str, pd.DataFrame]) -> None:
    """Air China consensus EPS 0.006 -> 955x PE is suppressed as artifact."""
    v = outputs["valuation"].set_index("company")
    for company in ["Air China", "China Eastern Airlines", "China Southern Airlines"]:
        assert pd.isna(v.loc[company, "pe_street"])


def test_pb_position_reported(outputs: dict[str, pd.DataFrame]) -> None:
    v = outputs["valuation"]
    assert v.pb_1y_percentile.notna().all()
    assert (v.pb_1y_percentile >= 0).all() and (v.pb_1y_percentile <= 100).all()
