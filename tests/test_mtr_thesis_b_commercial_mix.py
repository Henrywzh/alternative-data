"""Regression checks for the MTR Thesis B audit layer."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mtr_thesis_b_commercial_mix.py"
SPEC = importlib.util.spec_from_file_location("mtr_thesis_b_commercial_mix", MODULE_PATH)
assert SPEC and SPEC.loader
mtr_b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mtr_b)


def test_flow_uses_mainland_land_control_points_not_all_departures():
    flow = mtr_b.build_immd_flow_yearly()

    assert "hk_resident_mainland_land_departures" in flow.columns
    assert "hk_northbound" not in flow.columns
    assert "net_outflow_wan" not in flow.columns

    # 2025 is a complete year in the current raw ImmD archive.  The exact
    # value is a stable historical regression guard against reverting to the
    # all-control-point resident-departure field.
    assert flow.loc[2025, "hk_resident_mainland_land_departures"] == pytest.approx(93_069_112)
    assert flow.loc[2025, "hk_resident_departures_all_points"] == pytest.approx(117_547_210)
    assert flow.loc[2025, "hk_resident_mainland_land_departures"] < flow.loc[2025, "hk_resident_departures_all_points"]
    assert flow.loc[2025, "mainland_visitor_arrivals_mainland_land"] == pytest.approx(30_752_792)
    assert flow.loc[2025, "mainland_land_departure_to_matching_land_visitor_ratio"] == pytest.approx(3.026363, rel=1e-5)
    assert flow.loc[2025, "mainland_visitor_arrivals_all_points"] == pytest.approx(37_817_789)
    assert flow.attrs["source_date_max"] >= "2026-08-10"


def test_commercial_intensity_is_explicitly_a_proxy_and_reconciles():
    commercial = mtr_b.build_commercial_yearly()

    assert commercial.loc["2017", "station_rental_source_scope"] == "merged_station_plus_rental_disclosure"
    assert commercial.loc["2025", "station_rental_source_scope"] == "sum_of_separate_disclosures"
    assert commercial.loc["2025", "station_plus_rental"] == pytest.approx(10_412)
    assert commercial.loc["2025", "station_rental_intensity_hkd_per_mtr_journey"] == pytest.approx(5.312, rel=1e-3)
    assert commercial.loc["2025", "transport_intensity_hkd_per_mtr_journey"] == pytest.approx(12.046, rel=1e-3)
    assert commercial.loc["2025", "station_rental_intensity_hkd_per_mtr_journey"] == pytest.approx(
        commercial.loc["2025", "station_plus_rental"] / commercial.loc["2025", "pax_m"]
    )
