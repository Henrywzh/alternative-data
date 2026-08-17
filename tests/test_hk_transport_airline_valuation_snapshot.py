from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_valuation_snapshot import (
    build_airline_valuation_snapshot,
)


def test_valuation_snapshot_covers_all_carriers_with_pe() -> None:
    df = build_airline_valuation_snapshot()
    assert len(df) == 6
    assert df["market_cap_native_mn"].notna().all()
    assert df["pe_ttm"].notna().all()
    assert df["ps_ttm"].notna().all()
    assert df["pb_mrq"].notna().all()


def test_peer_zscore_is_relative_to_cross_section() -> None:
    df = build_airline_valuation_snapshot()
    # Spring's P/S is the highest in the group -> positive P/S z-score.
    spring = df[df["company"].eq("Spring Airlines")].iloc[0]
    assert spring["ps_peer_zscore"] > 0


def test_implied_expectations_compare_price_to_street_and_model() -> None:
    df = build_airline_valuation_snapshot()
    spring = df[df["company"].eq("Spring Airlines")].iloc[0]
    juneyao = df[df["company"].eq("Juneyao Airlines")].iloc[0]
    # Both carriers are priced above Street consensus EPS (positive implied
    # vs consensus), and Juneyao's implied premium is larger than Spring's.
    assert spring["implied_vs_consensus_eps_pct"] > 0
    assert juneyao["implied_vs_consensus_eps_pct"] > spring["implied_vs_consensus_eps_pct"]


def test_ev_ebitdar_is_labelled_when_components_missing() -> None:
    df = build_airline_valuation_snapshot()
    # Missing components must be labelled, not silently zero.
    assert df["ev_ebitdar_status"].isin(
        ["missing_components", "lease_addback_missing", "depreciation_from_official_drivers", "lease_addback_from_unit_aircraft_cask"]
    ).all()
