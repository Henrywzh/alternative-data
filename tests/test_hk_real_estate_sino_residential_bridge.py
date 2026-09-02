import pandas as pd
import pytest

from src.hk_real_estate.sino_residential_bridge import build_sino_residential_bridge


def test_sino_bridge_separates_observed_handover_and_stake_scenarios():
    signals = pd.DataFrame(
        [
            {
                "development_id": "1001",
                "development_name": "One Soho",
                "phase_name": "ONE SOHO",
                "period": "2025-01-01",
                "sales_units_gross": 10,
                "sales_value_gross_hkd": 100_000_000,
                "cumulative_unique_active_units": 10,
                "source_url": "https://srpe.test/signals",
            }
        ]
    )
    events = pd.DataFrame(
        [
            {
                "development_id": "1001",
                "development_address": "32B Shantung Street",
                "date_of_pasp": "2025-01-10",
                "transaction_price_hkd": 100_000_000,
                "is_cancelled": "False",
                "source_url": "https://srpe.test/register",
            }
        ]
    )
    queue = pd.DataFrame(
        [
            {
                "canonical_project_id": "sino_land:srpe:1001",
                "project_label": "One Soho",
                "srpe_development_id": "1001",
                "srpe_phase_name": "ONE SOHO",
                "queue_status": "eligible_for_recent_srpe_queue",
            },
            {
                "canonical_project_id": "sino_land:srpe:1002",
                "project_label": "No Register Project",
                "srpe_development_id": "1002",
                "srpe_phase_name": None,
                "queue_status": "eligible_for_recent_srpe_queue",
            },
        ]
    )
    identity = pd.DataFrame(
        [
            {
                "srpe_development_id": "1001",
                "ownership_pct_snapshot": 33.33,
                "ownership_scenario_status": "observed_snapshot_not_interval",
                "source_dataset": "annual_report",
            }
        ]
    )
    bd = pd.DataFrame(
        [
            {
                "permit_stage": "Occupation Permits (OP) Issued",
                "observation_month": "2026-01-01",
                "site_address": "32B Shantung Street",
                "domestic_units_count": 322,
                "source_url": "https://bd.test/op",
            }
        ]
    )

    layers = build_sino_residential_bridge(signals, events, queue, identity=identity, bd_history=bd, bridge_id="test-bridge")
    phase = layers["phase"].set_index("srpe_development_id")
    assert phase.loc["1001", "bd_occupation_match_status"] == "observed_bd_occupation_match"
    assert phase.loc["1001", "handover_lag_months_base"] == 12
    assert phase.loc["1001", "stake_low_pct"] == pytest.approx(33.33)
    assert phase.loc["1001", "stake_base_pct"] == pytest.approx(33.33)
    assert phase.loc["1001", "stake_high_pct"] == pytest.approx(33.33)
    assert phase.loc["1002", "sales_observation_status"] == "no_transaction_register_observed"
    assert phase.loc["1002", "stake_status"] == "unknown_assumed_50_75_100_scenario"
    schedule = layers["schedule"]
    assert len(schedule) == 1
    assert schedule.iloc[0]["attributable_contract_value_base_hkd"] == pytest.approx(33_330_000)
    assert layers["coverage"].iloc[0]["bd_occupation_observed_phase_count"] == 1
    assert layers["coverage"].iloc[0]["schedule_missing_recognition_period_rows"] == 0
    assert layers["coverage"].iloc[0]["schedule_negative_value_rows"] == 0
    assert layers["coverage"].iloc[0]["schedule_invalid_lag_order_rows"] == 0


def test_sino_bridge_marks_shared_bd_address_ambiguous():
    signals = pd.DataFrame(
        [
            {
                "development_id": "1001",
                "period": "2025-01-01",
                "sales_units_gross": 1,
                "sales_value_gross_hkd": 10_000_000,
            },
            {
                "development_id": "1002",
                "period": "2025-01-01",
                "sales_units_gross": 1,
                "sales_value_gross_hkd": 10_000_000,
            },
        ]
    )
    events = pd.DataFrame(
        [
            {"development_id": "1001", "development_address": "29 Kam Ho Road", "date_of_pasp": "2025-01-01", "transaction_price_hkd": 10_000_000, "is_cancelled": False},
            {"development_id": "1002", "development_address": "29 Kam Ho Road", "date_of_pasp": "2025-01-01", "transaction_price_hkd": 10_000_000, "is_cancelled": False},
        ]
    )
    queue = pd.DataFrame(
        [
            {"canonical_project_id": "p1", "project_label": "Phase 1", "srpe_development_id": "1001", "queue_status": "eligible_for_recent_srpe_queue"},
            {"canonical_project_id": "p2", "project_label": "Phase 2", "srpe_development_id": "1002", "queue_status": "eligible_for_recent_srpe_queue"},
        ]
    )
    bd = pd.DataFrame(
        [{"permit_stage": "Occupation Permits (OP) Issued", "observation_month": "2026-01-01", "site_address": "29 Kam Ho Road, Yuen Long", "domestic_units_count": 715}]
    )
    layers = build_sino_residential_bridge(signals, events, queue, bd_history=bd, bridge_id="test-ambiguous")
    assert set(layers["phase"]["bd_occupation_match_status"]) == {"ambiguous_address_match"}
    assert layers["coverage"].iloc[0]["bd_match_ambiguous_phase_count"] == 2


def test_sino_bridge_prefers_bd_house_number_anchor_over_shared_street_words():
    signals = pd.DataFrame(
        [
            {
                "development_id": "6685",
                "development_name": "St. George's Mansions",
                "phase_name": "ST. GEORGE'S MANSIONS",
                "period": "2025-01-01",
                "sales_units_gross": 2,
                "sales_value_gross_hkd": 40_000_000,
            }
        ]
    )
    events = pd.DataFrame(
        [
            {
                "development_id": "6685",
                "development_address": "24A Kadoorie Avenue, Ho Man Tin",
                "date_of_pasp": "2025-01-10",
                "transaction_price_hkd": 40_000_000,
                "is_cancelled": False,
            }
        ]
    )
    queue = pd.DataFrame(
        [
            {
                "canonical_project_id": "sino_land:srpe:6685",
                "project_label": "St. George's Mansions",
                "srpe_development_id": "6685",
                "queue_status": "eligible_for_recent_srpe_queue",
            }
        ]
    )
    bd = pd.DataFrame(
        [
            {
                "permit_stage": "Occupation Permits (OP) Issued",
                "observation_month": "2025-03-01",
                "site_address": "13 Ho Man Tin Street",
                "domestic_units_count": 6,
                "source_url": "https://bd.test/wrong-address",
            },
            {
                "permit_stage": "Occupation Permits (OP) Issued",
                "observation_month": "2026-01-01",
                "site_address": "24A Kadoorie Avenue,",
                "domestic_units_count": 175,
                "source_url": "https://bd.test/correct-address",
            },
        ]
    )

    layers = build_sino_residential_bridge(signals, events, queue, bd_history=bd, bridge_id="test-number-anchor")
    phase = layers["phase"].iloc[0]
    assert phase["bd_occupation_match_status"] == "observed_bd_occupation_match"
    assert phase["bd_occupation_observed_month"] == "2026-01-01"
    assert phase["bd_occupation_units"] == pytest.approx(175)
