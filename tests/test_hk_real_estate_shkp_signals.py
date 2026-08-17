import pandas as pd

from src.hk_real_estate.shkp_signals import (
    build_shkp_all_history_project_month_signals,
    build_shkp_indicative_project_month_signals,
    build_shkp_project_month_signals,
    deduplicate_shkp_transactions,
    _normalise_transactions,
)


def _transactions():
    return pd.DataFrame(
        [
            {
                "srpe_development_id": "1",
                "development_id": "1",
                "development_name": "TEST DEVELOPMENT",
                "phase_name": "PHASE 1",
                "block_name": "Tower 1",
                "floor": "10",
                "unit": "A",
                "date_of_pasp": "2026-01-05",
                "date_of_asp": "2026-01-10",
                "date_of_asp_termination": None,
                "transaction_price_hkd": 100.0,
                "is_cancelled": False,
                "transaction_id": "event-a",
                "document_id": "doc-1",
            },
            {
                # Same unit/event repeated by a later register version.
                "srpe_development_id": "1",
                "development_id": "1",
                "development_name": "TEST DEVELOPMENT",
                "phase_name": "PHASE 1",
                "block_name": "Tower 1",
                "floor": "10",
                "unit": "A",
                "date_of_pasp": "2026-01-05",
                "date_of_asp": "2026-01-10",
                "date_of_asp_termination": None,
                "transaction_price_hkd": 100.0,
                "is_cancelled": False,
                "transaction_id": "event-a-replayed",
                "document_id": "doc-2",
            },
            {
                "srpe_development_id": "1",
                "development_id": "1",
                "development_name": "TEST DEVELOPMENT",
                "phase_name": "PHASE 1",
                "block_name": "Tower 1",
                "floor": "10",
                "unit": "B",
                "date_of_pasp": "2026-01-15",
                "date_of_asp": "2026-01-20",
                "date_of_asp_termination": "2026-03-15",
                "transaction_price_hkd": 200.0,
                "is_cancelled": True,
                "transaction_id": "event-b",
                "document_id": "doc-1",
            },
            {
                "srpe_development_id": "1",
                "development_id": "1",
                "development_name": "TEST DEVELOPMENT",
                "phase_name": "PHASE 1",
                "block_name": "Tower 1",
                "floor": "11",
                "unit": "A",
                "date_of_pasp": "2026-02-01",
                "date_of_asp": "2026-02-05",
                "date_of_asp_termination": None,
                "transaction_price_hkd": 300.0,
                "is_cancelled": False,
                "transaction_id": "event-c",
                "document_id": "doc-1",
            },
        ]
    )


def test_semantic_dedup_removes_register_replay_but_keeps_distinct_units():
    deduped, stats = deduplicate_shkp_transactions(_transactions())
    assert len(deduped) == 3
    assert stats == {"rows_input": 4, "rows_output": 3, "duplicate_rows": 1}


def test_normalise_transactions_repairs_compact_row_price_shift():
    result = _normalise_transactions(
        pd.DataFrame(
            [
                {
                    "srpe_development_id": "285",
                    "development_id": "285",
                    "block_name": "17G Shouson Hill Road",
                    "floor": "",
                    "unit": "$228,420,000",
                    "date_of_pasp": "2016-10-03",
                    "date_of_asp": "2016-10-06",
                    "transaction_price_hkd": 1.0,
                    "transaction_id": "compact-1",
                },
                {
                    "srpe_development_id": "3245",
                    "development_id": "3245",
                    "block_name": "309",
                    "floor": "1",
                    "unit": "16,638,278\nlegacy revision text",
                    "date_of_pasp": "2016-09-01",
                    "date_of_asp": "2016-09-08",
                    "transaction_price_hkd": 1.0,
                    "transaction_id": "compact-plain",
                },
                {
                    "srpe_development_id": "5685",
                    "development_id": "5685",
                    "block_name": "9",
                    "floor": "A",
                    "unit": "",
                    "car_parking_space": "HK$13,493,000",
                    "date_of_pasp": "2021-01-01",
                    "date_of_asp": "2021-01-08",
                    "transaction_price_hkd": 1.0,
                    "transaction_id": "compact-parking",
                },
                {
                    "srpe_development_id": "control",
                    "development_id": "control",
                    "block_name": "Tower 1",
                    "floor": "10",
                    "unit": "A",
                    "date_of_pasp": "2021-01-01",
                    "date_of_asp": "2021-01-08",
                    "transaction_price_hkd": 8_000_000.0,
                    "transaction_id": "ordinary",
                },
            ]
        )
    ).set_index("transaction_id")
    assert result.loc["compact-1", "transaction_price_hkd"] == 228420000
    assert result.loc["compact-plain", "transaction_price_hkd"] == 16638278
    assert result.loc["compact-parking", "transaction_price_hkd"] == 13493000
    assert result.loc["compact-1", "unit"] == ""
    assert result.loc["compact-plain", "unit"] == ""
    assert result.loc["compact-parking", "car_parking_space"] == ""
    assert result.loc["ordinary", "unit"] == "A"
    assert result.loc["ordinary", "parser_quality_status"] == "parsed_standard_row"
    assert result.loc["compact-1", "parser_quality_status"] == "compact_row_price_shift_repaired"


def test_normalise_transactions_parses_string_cancellation_flags():
    rows = []
    for transaction_id, raw_flag in (
        ("cancelled-false", "False"),
        ("cancelled-true", "True"),
    ):
        rows.append(
            {
                "srpe_development_id": "1",
                "development_id": "1",
                "block_name": "Tower 1",
                "floor": "10",
                "unit": transaction_id,
                "date_of_pasp": "2026-01-05",
                "date_of_asp": "2026-01-10",
                "date_of_asp_termination": None,
                "transaction_price_hkd": 100.0,
                "is_cancelled": raw_flag,
                "transaction_id": transaction_id,
            }
        )

    result = _normalise_transactions(pd.DataFrame(rows)).set_index("transaction_id")

    assert bool(result.loc["cancelled-false", "is_cancelled"]) is False
    assert bool(result.loc["cancelled-true", "is_cancelled"]) is True


def test_pasp_missing_asp_present_is_explicitly_quarantined():
    transactions = pd.DataFrame([{
        "srpe_development_id": "gap-1",
        "development_id": "gap-1",
        "development_name": "DATE GAP",
        "phase_name": "PHASE 1",
        "block_name": "Tower 1",
        "floor": "10",
        "unit": "A",
        "date_of_pasp": None,
        "date_of_asp": "2026-01-10",
        "date_of_asp_termination": None,
        "transaction_price_hkd": 1000000.0,
        "is_cancelled": False,
        "transaction_id": "gap-event",
    }])
    normalised = _normalise_transactions(transactions)
    assert normalised.loc[0, "date_gap_status"] == "pasp_missing_asp_observed"
    assert pd.isna(normalised.loc[0, "event_period"])

    signals, statuses, coverage = build_shkp_project_month_signals(transactions)
    assert signals.empty
    assert statuses.empty
    row = coverage.loc[coverage["srpe_development_id"].eq("gap-1")].iloc[0]
    assert row["date_gap_event_rows"] == 1
    assert row["date_gap_status"] == "pasp_missing_asp_observed"
    assert row["signal_exclusion_reason"] == "pasp_missing_not_in_month_grid"


def test_project_month_signals_track_month_end_active_state_and_parser_status():
    candidates = pd.DataFrame(
        [{"srpe_development_id": "1", "candidate_status": "matched", "candidate_tier": "tier_1"}]
    )
    audits = pd.DataFrame([{"srpe_dev_id": "1", "document_id": "doc-1", "parse_status": "success"}])
    signals, statuses, coverage = build_shkp_project_month_signals(
        _transactions(), candidates=candidates, audits=audits
    )

    jan = signals.loc[signals["period"].eq("2026-01-01")].iloc[0]
    feb = signals.loc[signals["period"].eq("2026-02-01")].iloc[0]
    mar = signals.loc[signals["period"].eq("2026-03-01")].iloc[0]
    assert jan["sales_units_gross"] == 2
    assert jan["active_units_eom"] == 2
    assert feb["active_units_eom"] == 3
    assert mar["active_units_eom"] == 2
    assert mar["cancelled_units"] == 1
    assert mar["cancellation_rate"] == 1.0
    assert mar["month_status"] == "observed_zero_transactions"
    assert signals["ownership_attribution_ready"].eq(False).all()
    assert set(statuses["month_status"]) == {"observed_transactions", "observed_zero_transactions"}
    assert coverage.loc[0, "audit_status"] == "success"
    assert bool(coverage.loc[0, "parser_gap"]) is False


def test_month_end_state_later_termination_supersedes_open_register_row():
    open_row = {
        "srpe_development_id": "1",
        "development_id": "1",
        "development_name": "TEST DEVELOPMENT",
        "phase_name": "PHASE 1",
        "block_name": "Tower 1",
        "floor": "10",
        "unit": "A",
        "date_of_pasp": "2026-01-05",
        "date_of_asp": "2026-01-10",
        "date_of_asp_termination": None,
        "transaction_price_hkd": 100.0,
        "is_cancelled": False,
        "transaction_id": "open-version",
    }
    terminated_row = {
        **open_row,
        "date_of_asp_termination": "2026-03-15",
        "is_cancelled": True,
        "transaction_id": "terminated-version",
    }
    signals, _, _ = build_shkp_project_month_signals(
        pd.DataFrame([open_row, terminated_row])
    )
    assert signals.set_index("period").loc["2026-02-01", "active_units_eom"] == 1
    assert signals.set_index("period").loc["2026-03-01", "active_units_eom"] == 0


def test_project_month_signals_reuse_strict_gate_and_canonical_ownership_pct():
    second_phase = {
        **_transactions().iloc[0].to_dict(),
        "srpe_development_id": "2",
        "development_id": "2",
        "transaction_id": "phase-2-event",
    }
    transactions = pd.concat(
        [_transactions().iloc[[0]], pd.DataFrame([second_phase])],
        ignore_index=True,
    )
    ownership_registry = pd.DataFrame(
        [
            {
                "srpe_development_id": "1",
                "ownership_status": "consistent_numeric",
                "ownership_attribution_ready": True,
                "ownership_observed_pct": 60.0,
                "ownership_effective_from": "2025-01-01",
                "ownership_effective_to": "2027-12-31",
                "ownership_interval_evidence_type": "approved_phase_attribution_decision",
                "ownership_attribution_decision_id": "decision-1",
                "ownership_interval_promotion_status": "approved_phase_attribution",
            },
            {
                "srpe_development_id": "2",
                "ownership_status": "consistent_numeric",
                "ownership_attribution_ready": True,
                "curated_registry_ownership_pct": 50.0,
                "ownership_effective_from": "2025-01-01",
                "ownership_effective_to": "2027-12-31",
                # A legacy ready flag plus dates is not an approved decision.
                "ownership_interval_evidence_type": "annual_report_snapshot",
                "ownership_attribution_decision_id": None,
                "ownership_interval_promotion_status": "blocked_effective_interval",
            },
        ]
    )
    signals, _, _ = build_shkp_project_month_signals(
        transactions,
        ownership_registry=ownership_registry,
    )
    approved = signals.loc[signals["srpe_development_id"].eq("1")].iloc[0]
    blocked = signals.loc[signals["srpe_development_id"].eq("2")].iloc[0]
    assert bool(approved["ownership_attribution_ready"]) is True
    assert approved["ownership_pct"] == 60.0
    assert approved["sales_value_attributable_hkd"] == 60.0
    assert bool(blocked["ownership_attribution_ready"]) is False
    assert pd.isna(blocked["sales_value_attributable_hkd"])


def test_project_month_signals_treat_string_false_ready_flag_as_blocked():
    ownership_registry = pd.DataFrame(
        [
            {
                "srpe_development_id": "1",
                "ownership_status": "consistent_numeric",
                "ownership_attribution_ready": "False",
                "ownership_observed_pct": 60.0,
                "ownership_effective_from": "2025-01-01",
                "ownership_effective_to": "2027-12-31",
                "ownership_interval_evidence_type": "approved_phase_attribution_decision",
                "ownership_attribution_decision_id": "decision-1",
                "ownership_interval_promotion_status": "approved_phase_attribution",
            }
        ]
    )
    signals, _, _ = build_shkp_project_month_signals(
        _transactions().iloc[[0]],
        ownership_registry=ownership_registry,
    )
    row = signals.iloc[0]
    assert bool(row["ownership_attribution_ready"]) is False
    assert pd.isna(row["sales_value_attributable_hkd"])


def test_project_month_signals_block_sales_outside_approved_interval():
    ownership_registry = pd.DataFrame(
        [
            {
                "srpe_development_id": "1",
                "ownership_status": "consistent_numeric",
                "ownership_attribution_ready": True,
                "ownership_observed_pct": 60.0,
                "ownership_effective_from": "2027-01-01",
                "ownership_effective_to": "2027-12-31",
                "ownership_interval_evidence_type": "approved_phase_attribution_decision",
                "ownership_attribution_decision_id": "decision-1",
                "ownership_interval_promotion_status": "approved_phase_attribution",
            }
        ]
    )
    signals, _, _ = build_shkp_project_month_signals(
        _transactions().iloc[[0]],
        ownership_registry=ownership_registry,
    )
    row = signals.iloc[0]
    assert bool(row["ownership_attribution_ready"]) is False
    assert pd.isna(row["sales_value_attributable_hkd"])


def test_project_month_signals_block_ambiguous_multiple_ownership_intervals():
    registry_row = {
        "srpe_development_id": "1",
        "ownership_status": "consistent_numeric",
        "ownership_attribution_ready": True,
        "ownership_observed_pct": 60.0,
        "ownership_interval_evidence_type": "approved_phase_attribution_decision",
        "ownership_interval_promotion_status": "approved_phase_attribution",
    }
    ownership_registry = pd.DataFrame(
        [
            {
                **registry_row,
                "ownership_effective_from": "2025-01-01",
                "ownership_effective_to": "2026-12-31",
                "ownership_attribution_decision_id": "decision-1",
            },
            {
                **registry_row,
                "ownership_effective_from": "2026-01-01",
                "ownership_effective_to": "2027-12-31",
                "ownership_attribution_decision_id": "decision-2",
            },
        ]
    )
    signals, _, _ = build_shkp_project_month_signals(
        _transactions().iloc[[0]],
        ownership_registry=ownership_registry,
    )
    assert signals["ownership_attribution_ready"].eq(False).all()
    assert signals["sales_value_attributable_hkd"].isna().all()


def test_project_month_signals_reject_invalid_ownership_percentage():
    ownership_registry = pd.DataFrame(
        [
            {
                "srpe_development_id": "1",
                "ownership_status": "consistent_numeric",
                "ownership_attribution_ready": True,
                "ownership_observed_pct": 150.0,
                "ownership_effective_from": "2025-01-01",
                "ownership_effective_to": "2027-12-31",
                "ownership_interval_evidence_type": "approved_phase_attribution_decision",
                "ownership_attribution_decision_id": "decision-1",
                "ownership_interval_promotion_status": "approved_phase_attribution",
            }
        ]
    )
    signals, _, _ = build_shkp_project_month_signals(
        _transactions().iloc[[0]],
        ownership_registry=ownership_registry,
    )
    assert signals["ownership_attribution_ready"].eq(False).all()
    assert signals["sales_value_attributable_hkd"].isna().all()


def test_project_month_signals_marks_phase_tail_not_covered():
    transactions = pd.concat(
        [
            _transactions(),
            pd.DataFrame([{
                "srpe_development_id": "2",
                "development_id": "2",
                "development_name": "OTHER",
                "phase_name": "PHASE 1",
                "block_name": "A",
                "floor": "1",
                "unit": "1",
                "date_of_pasp": "2026-04-05",
                "date_of_asp": "2026-04-06",
                "date_of_asp_termination": None,
                "transaction_price_hkd": 400.0,
                "is_cancelled": False,
                "transaction_id": "event-other",
                "document_id": "doc-2",
            }]),
        ],
        ignore_index=True,
    )
    candidates = pd.DataFrame([
        {"srpe_development_id": "1", "candidate_status": "matched", "candidate_tier": "tier_1"},
        {"srpe_development_id": "2", "candidate_status": "matched", "candidate_tier": "tier_1"},
    ])
    audits = pd.DataFrame([
        {"srpe_dev_id": "1", "document_id": "doc-1", "parse_status": "success"},
        {"srpe_dev_id": "2", "document_id": "doc-2", "parse_status": "success"},
    ])
    signals, statuses, coverage = build_shkp_project_month_signals(
        transactions, candidates=candidates, audits=audits
    )
    tail = signals[(signals["srpe_development_id"] == "1") & (signals["period"] == "2026-04-01")].iloc[0]
    assert tail["month_status"] == "not_covered"
    assert pd.isna(tail["active_units_eom"])
    assert pd.isna(tail["sales_units_gross"])
    assert coverage.loc[coverage["srpe_development_id"] == "1", "not_covered_months"].iloc[0] == 1
    assert "not_covered" in set(statuses["month_status"])


def test_indicative_project_month_signals_applies_snapshot_pct_without_opening_strict_gate():
    signals = pd.DataFrame([
        {
            "srpe_development_id": "1",
            "period": "2026-01-01",
            "sales_value_gross_hkd": 1000.0,
            "sales_units_gross": 4.0,
            "ownership_attribution_ready": False,
        },
        {
            "srpe_development_id": "2",
            "period": "2026-01-01",
            "sales_value_gross_hkd": 500.0,
            "sales_units_gross": 2.0,
            "ownership_attribution_ready": False,
        },
    ])
    ownership = pd.DataFrame([
        {
            "srpe_development_id": "1",
            "indicative_owner_status": "likely_shkp_numeric_snapshot",
            "indicative_ownership_pct": 50.0,
            "indicative_ownership_pct_low": 49.8,
            "indicative_ownership_pct_high": 50.2,
            "indicative_numeric_consistency_status": "rounded_consistent_snapshots",
            "indicative_confidence": "medium",
            "indicative_evidence_basis": "annual_report_group_interest_snapshot",
            "indicative_sales_use_status": "indicative_numeric_only",
            "strict_ownership_attribution_ready": False,
        },
        {
            "srpe_development_id": "2",
            "indicative_owner_status": "likely_shkp_jv_unquantified",
            "indicative_ownership_pct": None,
            "indicative_confidence": "medium",
            "indicative_evidence_basis": "jv_wording",
            "indicative_sales_use_status": "indicative_unquantified_jv",
            "strict_ownership_attribution_ready": False,
        },
    ])
    result = build_shkp_indicative_project_month_signals(signals, ownership)
    numeric = result.loc[result["srpe_development_id"].eq("1")].iloc[0]
    jv = result.loc[result["srpe_development_id"].eq("2")].iloc[0]
    assert numeric["indicative_sales_value_hkd"] == 500.0
    assert numeric["indicative_sales_units"] == 2.0
    assert numeric["indicative_attribution_status"] == "indicative_numeric_snapshot"
    assert numeric["indicative_ownership_pct_low"] == 49.8
    assert numeric["indicative_ownership_pct_high"] == 50.2
    assert numeric["indicative_numeric_consistency_status"] == "rounded_consistent_snapshots"
    assert pd.isna(jv["indicative_sales_value_hkd"])
    assert jv["indicative_attribution_status"] == "indicative_jv_unquantified"
    assert result["ownership_attribution_ready"].eq(False).all()


def test_all_history_signal_merge_prefers_current_duplicate_and_keeps_sparse_history():
    current = pd.DataFrame([
        {
            "phase_id": "1",
            "project_id": "current-1",
            "srpe_development_id": "1",
            "development_id": "1",
            "development_name": "CURRENT",
            "phase_name": "P1",
            "period": "2020-01-01",
            "sales_units_gross": 2.0,
            "sales_value_gross_hkd": 200.0,
            "cancelled_units": 0.0,
            "month_status": "observed_transactions",
            "ownership_attribution_ready": False,
        },
    ])
    historical = pd.DataFrame([
        {
            "development_id": "1",
            "development_name": "HISTORICAL",
            "phase_name": "P1",
            "period": "2020-01-01",
            "sales_units_gross": 1.0,
            "sales_value_gross_hkd": 100.0,
            "cancelled_units": 0.0,
            "cumulative_unique_active_units": 1.0,
            "srpe_development_id": "1",
            "project_id": "historical-1",
        },
        {
            "development_id": "2",
            "development_name": "HISTORICAL ONLY",
            "phase_name": "P1",
            "period": "2019-03-01",
            "sales_units_gross": 0.0,
            "sales_value_gross_hkd": 0.0,
            "cancelled_units": 0.0,
            "cumulative_unique_active_units": 3.0,
            "srpe_development_id": "2",
            "project_id": "historical-2",
        },
    ])
    merged, coverage = build_shkp_all_history_project_month_signals(current, historical)
    duplicate = merged.loc[(merged["srpe_development_id"] == "1") & (merged["period"] == "2020-01-01")].iloc[0]
    assert duplicate["sales_value_gross_hkd"] == 200.0
    assert duplicate["signal_scope"] == "current_candidate_signal"
    assert len(merged) == 2
    assert set(coverage["signal_scope"]) == {"current_candidate_signal", "historical_inactive_backfill"}
    historical_only = merged.loc[merged["srpe_development_id"].eq("2")].iloc[0]
    assert historical_only["month_status"] == "observed_zero_transactions"
    assert historical_only["coverage_semantics"] == "sparse_historical_register_months"
