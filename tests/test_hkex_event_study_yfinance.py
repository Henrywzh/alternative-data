from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "run_hkex_event_study_yfinance.py"
SPEC = importlib.util.spec_from_file_location("hkex_event_study_yfinance", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _bars(tickers: list[str], timestamps: list[str]) -> pd.DataFrame:
    index = pd.DatetimeIndex(timestamps, tz="UTC")
    columns: dict[tuple[str, str], list[float]] = {}
    for ticker in tickers:
        base = 100.0 if ticker == "0005.HK" else 200.0
        values = [base + index_position for index_position in range(len(index))]
        columns[(ticker, "Open")] = values
        columns[(ticker, "Close")] = [value + 0.5 for value in values]
    frame = pd.DataFrame(columns, index=index)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    return frame


def _events(rows: list[tuple[str, str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": event_id,
                "ticker": ticker,
                "event_type": event_type,
                "available_at": pd.Timestamp(available_at, tz="UTC"),
            }
            for event_id, ticker, event_type, available_at in rows
        ]
    )


def test_event_study_skips_lunch_and_keeps_event_types_in_same_cluster():
    timestamps = [
        "2026-08-04 01:30:00",
        "2026-08-04 01:35:00",
        "2026-08-04 04:05:00",
        "2026-08-04 05:00:00",
        "2026-08-04 05:05:00",
        "2026-08-04 05:10:00",
        "2026-08-04 05:15:00",
        "2026-08-04 05:20:00",
        "2026-08-04 05:25:00",
        "2026-08-04 05:30:00",
        "2026-08-04 05:35:00",
        "2026-08-04 05:40:00",
        "2026-08-04 05:45:00",
        "2026-08-04 05:50:00",
        "2026-08-04 05:55:00",
        "2026-08-04 06:00:00",
    ]
    bars = _bars(["0005.HK", "^HSI"], timestamps)
    events = _events(
        [
            ("event-1", "0005.HK", "BUSINESS_UPDATE", "2026-08-04 01:32:00"),
            ("event-2", "0005.HK", "INTERIM_RESULTS", "2026-08-04 04:10:00"),
        ]
    )

    result = MODULE.calculate_event_returns(events, bars, bars)

    intraday = result.loc[result["event_id"].eq("event-1")].iloc[0]
    lunch = result.loc[result["event_id"].eq("event-2")].iloc[0]
    assert intraday["market_data_status"] == "covered"
    assert intraday["entry_bar_at_hkt"].startswith("2026-08-04T09:35")
    assert pd.isna(intraday["gap_return"])
    assert lunch["entry_bar_at_hkt"].startswith("2026-08-04T13:00")
    assert lunch["session"] == "LUNCH_BREAK"
    assert pd.notna(lunch["gap_return"])
    assert pd.isna(intraday["1h_return"])
    assert "1h" in intraday["bar_hole_horizons"]
    assert pd.notna(lunch["1h_return"])
    assert result["cluster_size"].eq(1).all()


def test_same_bar_different_event_types_are_not_lost_from_summary():
    timestamps = [
        "2026-08-04 01:30:00",
        "2026-08-04 01:35:00",
        "2026-08-04 01:40:00",
        "2026-08-04 01:45:00",
        "2026-08-04 01:50:00",
        "2026-08-04 01:55:00",
        "2026-08-04 02:00:00",
        "2026-08-04 02:05:00",
        "2026-08-04 02:10:00",
        "2026-08-04 02:15:00",
        "2026-08-04 02:20:00",
        "2026-08-04 02:25:00",
        "2026-08-04 02:30:00",
    ]
    bars = _bars(["0005.HK", "^HSI"], timestamps)
    events = _events(
        [
            ("event-1", "0005.HK", "BUSINESS_UPDATE", "2026-08-04 01:31:00"),
            ("event-2", "0005.HK", "TRADING_UPDATE", "2026-08-04 01:32:00"),
        ]
    )

    result = MODULE.calculate_event_returns(events, bars, bars)
    summary = MODULE.summarize(result)

    assert result["cluster_key"].nunique() == 1
    assert result["cluster_size"].eq(2).all()
    assert result["cluster_document_count"].eq(2).all()
    assert result["is_multi_document_cluster"].all()
    assert not result["is_pure_event_type"].any()
    assert result["cluster_co_occurring_types"].eq("BUSINESS_UPDATE,TRADING_UPDATE").all()
    assert set(summary["primary_event_type"]) == {"BUSINESS_UPDATE", "TRADING_UPDATE"}


def test_native_1h_sensitivity_keeps_session_grain():
    result = pd.DataFrame(
        [
            {
                "session": "LUNCH_BREAK",
                "primary_event_type": "BUSINESS_UPDATE",
                "derived_impact_direction": "neutral_unknown",
                "is_type_cluster_representative": True,
                "native_1h_abnormal_return": 0.01,
                "1h_abnormal_return": 0.02,
            },
            {
                "session": "OVERNIGHT_POST",
                "primary_event_type": "BUSINESS_UPDATE",
                "derived_impact_direction": "neutral_unknown",
                "is_type_cluster_representative": True,
                "native_1h_abnormal_return": -0.01,
                "1h_abnormal_return": -0.02,
            },
        ]
    )

    sensitivity = MODULE.native_1h_sensitivity(result)

    assert len(sensitivity) == 2
    assert set(sensitivity["session"]) == {"LUNCH_BREAK", "OVERNIGHT_POST"}


def test_long_missing_market_data_is_not_treated_as_event_coverage():
    bars = _bars(
        ["0005.HK", "^HSI"],
        [
            "2026-07-10 01:30:00",
            "2026-07-10 01:35:00",
            "2026-07-10 01:40:00",
        ],
    )
    events = _events(
        [("event-1", "0005.HK", "BOARD_MEETING_DATE", "2026-07-01 08:00:00")]
    )

    result = MODULE.calculate_event_returns(events, bars, bars)

    assert result.loc[0, "market_data_status"] == "missing"
    assert result.loc[0, "1h_return"] is None


def test_pending_market_cutoff_is_distinguished_from_history_missing():
    result = pd.DataFrame(
        [
            {
                "market_data_status": "missing",
                "available_at": pd.Timestamp("2026-08-07 19:00", tz="UTC"),
                "data_gap_reason": "no eligible 5m bar in downloaded window",
            },
            {
                "market_data_status": "missing",
                "available_at": pd.Timestamp("2026-08-04 10:00", tz="UTC"),
                "data_gap_reason": "no eligible 5m bar in downloaded window",
            },
        ]
    )
    marked, count = MODULE.mark_pending_market_cutoff_events(
        result, "2026-08-07 08:05:00+00:00"
    )
    assert count == 1
    assert marked.loc[0, "data_gap_reason"] == "awaiting_next_market_cutoff"
    assert marked.loc[1, "data_gap_reason"] != "awaiting_next_market_cutoff"


def test_exact_session_boundaries_use_a_strictly_later_bar():
    bars = pd.Series(
        [100.0, 101.0, 102.0],
        index=pd.DatetimeIndex(
            [
                "2026-08-04 01:30:00+00:00",  # 09:30 HKT
                "2026-08-04 01:35:00+00:00",  # 09:35 HKT
                "2026-08-05 01:30:00+00:00",  # next session open
            ]
        ),
    )
    exact_open = MODULE._eligible_bar_index(
        bars, pd.Timestamp("2026-08-04 01:30:00+00:00")
    )
    exact_close_boundary = MODULE._eligible_bar_index(
        bars, pd.Timestamp("2026-08-04 07:55:00+00:00")
    )
    assert exact_open == 1
    assert exact_close_boundary == 2


def test_evidence_layer_corrects_direction_and_primary_type():
    assert MODULE.derive_impact_direction(
        "INSIDE INFORMATION - POSITIVE PROFIT ALERT", ""
    ) == "positive"
    assert MODULE.derive_impact_direction("NEGATIVE PROFIT ALERT", "") == "negative"
    assert MODULE.derive_impact_direction("Interim Results", "中期业绩") == "neutral_unknown"
    assert MODULE._impact_direction_match(
        "INSIDE INFORMATION -\nPOSITIVE PROFIT ALERT", ""
    )[1] == "title_high_precision_positive_match"
    assert MODULE._impact_direction_match(
        "Estimated Profit Increase and Profit Warning", ""
    ) == ("mixed", "title_conflicting_high_precision_matches")

    events = pd.DataFrame(
        [
            {
                "event_id": "a",
                "ticker": "0005.HK",
                "event_type": "BOARD_MEETING_DATE",
                "title_en": "INTERIM RESULTS FOR 2026",
                "title_zh": "",
                "announcement_at": pd.Timestamp("2026-08-01", tz="UTC"),
                "available_at": pd.Timestamp("2026-08-01 00:10", tz="UTC"),
                "content_hash": "same-document",
                "source_url": "https://example.test/a.pdf",
            },
            {
                "event_id": "b",
                "ticker": "0005.HK",
                "event_type": "INTERIM_RESULTS",
                "title_en": "INTERIM RESULTS FOR 2026",
                "title_zh": "",
                "announcement_at": pd.Timestamp("2026-08-01", tz="UTC"),
                "available_at": pd.Timestamp("2026-08-01 00:10", tz="UTC"),
                "content_hash": "same-document",
                "source_url": "https://example.test/a.pdf",
            },
        ]
    )
    enriched = MODULE.derive_evidence_fields(events)
    assert set(enriched["primary_event_type"]) == {"INTERIM_RESULTS"}
    assert enriched["is_document_representative"].tolist() == [True, False]
    assert enriched["impact_direction_basis"].eq("no_high_precision_title_match").all()
    assert enriched["impact_direction"].eq("unknown").all()


def test_generic_earnings_warning_uses_high_precision_title_override_with_provenance():
    events = pd.DataFrame(
        [
            {
                "event_id": "warning-1",
                "ticker": "3993.HK",
                "event_type": "EARNINGS_WARNING",
                "title_en": "INSIDE INFORMATION - POSITIVE PROFIT ALERT",
                "title_zh": "",
                "impact_direction": "negative",
                "announcement_at": pd.Timestamp("2026-08-01", tz="UTC"),
                "available_at": pd.Timestamp("2026-08-01 00:10", tz="UTC"),
            }
        ]
    )
    enriched = MODULE.derive_evidence_fields(events)
    assert enriched.loc[0, "impact_direction"] == "negative"
    assert enriched.loc[0, "impact_direction_reconciled"] == "positive"
    assert enriched.loc[0, "impact_direction_reconciliation_basis"] == "category_generic_title_override"
    assert enriched.loc[0, "resolved_impact_direction"] == "positive"
    assert enriched.loc[0, "resolved_impact_direction_basis"] == "category_generic_title_override"
    assert MODULE.direction_conflict_frame(enriched).empty


def test_candidate_loader_keeps_only_named_pit_complete_non_composite_rows(tmp_path):
    inventory = pd.DataFrame(
        [
            {
                "filing_id": "safe-1",
                "ticker": "0005.HK",
                "announcement_at": "2026-08-01T01:00:00Z",
                "available_at": "2026-08-01T01:10:00Z",
                "availability_basis": "source_timestamp_proxy",
                "title_en": "Dividend announcement",
                "title_zh": "",
                "category": "Dividend",
                "document_url": "https://example.test/safe.pdf",
                "candidate_family": "dividend",
                "category_is_composite": False,
                "candidate_status": "discovery_candidate",
                "event_study_eligible": True,
            },
            {
                "filing_id": "unsafe-1",
                "ticker": "0005.HK",
                "announcement_at": "2026-08-01T01:00:00Z",
                "available_at": "2026-08-01T01:10:00Z",
                "availability_basis": "source_timestamp_proxy",
                "title_en": "Other notice",
                "title_zh": "",
                "category": "Other",
                "document_url": "https://example.test/unsafe.pdf",
                "candidate_family": "other",
                "category_is_composite": False,
                "candidate_status": "discovery_candidate",
                "event_study_eligible": True,
            },
            {
                "filing_id": "sidecar-1",
                "ticker": "0005.HK",
                "announcement_at": "2026-08-01T01:00:00Z",
                "available_at": "2026-08-01T01:10:00Z",
                "availability_basis": "source_timestamp_proxy",
                "title_en": "Dividend announcement",
                "title_zh": "",
                "category": "Dividend",
                "document_url": "https://example.test/sidecar.pdf",
                "candidate_family": "dividend",
                "category_is_composite": False,
                "candidate_status": "discovery_candidate",
                "event_study_eligible": False,
            },
        ]
    )
    path = tmp_path / "inventory.csv"
    inventory.to_csv(path, index=False)

    loaded = MODULE.load_candidate_events(path)

    assert loaded["event_id"].tolist() == ["filing:safe-1"]
    assert loaded["primary_event_type"].tolist() == ["DIVIDEND"]
    assert loaded["availability_basis"].tolist() == ["source_timestamp_proxy"]


def test_archive_manifest_symbols_support_candidate_archive_expansion(tmp_path: Path):
    root = tmp_path / "archive"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "version": "yfinance_snapshot_archive.v1",
                "captures": [
                    {
                        "capture_id": "capture-1",
                        "intervals": {
                            "5m": {"symbols": ["0005.HK", "candidate.HK"]},
                            "1h": {"symbol_coverage": {"0005.HK": {}, "candidate.HK": {}}},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert MODULE.archive_manifest_symbols(root, "5m") == {"0005.HK", "candidate.HK"}
    assert MODULE.archive_manifest_symbols(root, "1h") == {"0005.HK", "candidate.HK"}


def test_robustness_summary_uses_type_clusters_and_announcement_dates():
    timestamps = [
        timestamp.isoformat()
        for timestamp in pd.date_range(
            "2026-08-04 01:30:00+00:00", periods=14, freq="5min"
        )
    ]
    bars = _bars(["0005.HK", "^HSI"], timestamps)
    events = _events(
        [
            ("event-1", "0005.HK", "INTERIM_RESULTS", "2026-08-04 01:31:00"),
            ("event-2", "0005.HK", "INTERIM_RESULTS", "2026-08-04 01:32:00"),
        ]
    )
    result = MODULE.calculate_event_returns(events, bars, bars)
    robustness = MODULE.robustness_summary(result)

    assert len(robustness) == 3
    assert robustness["n_type_clusters"].eq(1).all()
    assert robustness["n_announcement_dates"].eq(1).all()
    assert robustness["resolved_impact_direction"].eq("unknown").all()


def test_signal_registry_is_explicitly_non_trading_until_gates_pass():
    robustness = pd.DataFrame(
        [
            {
                "primary_event_type": "INTERIM_RESULTS",
                "derived_impact_direction": "neutral_unknown",
                "horizon": "1h",
                "n_type_clusters": 14,
                "n_announcement_dates": 10,
                "pit_observed_share": 0.1,
                "mean_abnormal_return": 0.022,
                "median_abnormal_return": 0.0028,
                "winsorized_1pct_mean": 0.021,
                "mean_after_30bps_scenario": 0.019,
                "event_level_t_stat": 1.5,
                "announcement_date_cluster_t_stat": 1.2,
            }
        ]
    )
    registry = MODULE.build_signal_registry(robustness)
    row = registry.iloc[0]
    assert row["status"] == "blocked"
    assert bool(row["statistical_gates_passed"]) is False
    assert row["sample_tier"] == "insufficient_sample"
    assert row["registration_state"] == "not_registered"
    assert bool(row["registered_for_trading_signal"]) is False
    assert bool(row["trading_execution_eligible"]) is False
    assert bool(row["sample_gate"]) is False


def test_signal_registration_gate_surfaces_pit_conflicts_and_bar_holes():
    audit = {
        "intervals": {
            "5m": {"status": "ok", "distinct_market_cutoff_count": 2},
            "1h": {"status": "ok", "distinct_market_cutoff_count": 2},
        }
    }
    gate = MODULE.build_signal_registration_gate(
        audit,
        {
            "covered_event_rows": 20,
            "covered_observed_event_rows": 0,
            "covered_proxy_event_rows": 20,
            "direction_conflict_rows": 2,
            "bar_hole_event_rows": 1,
        },
    )

    assert gate["status"] == "blocked"
    assert set(gate["reasons"]) == {
        "covered_sample_proxy_only",
        "direction_conflicts_require_review",
        "bar_holes_require_review",
    }


def test_stratified_summary_preserves_pit_and_liquidity_buckets():
    timestamps = [
        timestamp.isoformat()
        for timestamp in pd.date_range(
            "2026-08-04 01:30:00+00:00", periods=14, freq="5min"
        )
    ]
    bars = _bars(["0005.HK", "^HSI"], timestamps)
    events = _events(
        [("event-1", "0005.HK", "INTERIM_RESULTS", "2026-08-04 01:31:00")]
    )
    result = MODULE.calculate_event_returns(events, bars, bars)
    stratified = MODULE.stratified_event_summary(result)
    assert stratified["liquidity_bucket"].eq("volume_missing").all()
    assert stratified["availability_basis"].eq("unknown").all()
    assert stratified["return_rows"].eq(1).all()


def test_gap_drift_summary_keeps_intraday_gap_missing_and_drift_present():
    timestamps = [
        timestamp.isoformat()
        for timestamp in pd.date_range(
            "2026-08-04 01:30:00+00:00", periods=14, freq="5min"
        )
    ]
    bars = _bars(["0005.HK", "^HSI"], timestamps)
    events = _events(
        [("event-1", "0005.HK", "INTERIM_RESULTS", "2026-08-04 01:31:00")]
    )
    result = MODULE.calculate_event_returns(events, bars, bars)
    summary = MODULE.gap_drift_summary(result)
    assert len(summary) == 3
    assert summary["n_gap_observations"].eq(0).all()
    assert summary["n_drift_observations"].eq(1).all()
    assert summary["resolved_impact_direction"].eq("unknown").all()


def test_total_return_decomposition_and_signed_direction_are_explicit():
    timestamps = [
        "2026-08-04 07:45:00",
        "2026-08-04 07:50:00",
        "2026-08-05 01:30:00",
        "2026-08-05 01:35:00",
        "2026-08-05 01:40:00",
        "2026-08-05 01:45:00",
        "2026-08-05 01:50:00",
        "2026-08-05 01:55:00",
    ]
    bars = _bars(["0005.HK", "^HSI"], timestamps)
    events = _events(
        [("event-1", "0005.HK", "INTERIM_RESULTS", "2026-08-04 08:00:00")]
    )
    events["impact_direction"] = "positive"
    events = MODULE.derive_evidence_fields(events)
    result = MODULE.calculate_event_returns(events, bars, bars)
    row = result.iloc[0]

    assert row["session"] == "OVERNIGHT_POST"
    assert pd.notna(row["opening_gap_return"])
    assert pd.notna(row["total_5m_return"])
    expected_total = (1 + row["opening_gap_return"]) * (1 + row["5m_drift_return"]) - 1
    assert row["total_5m_return"] == pytest.approx(expected_total)
    assert row["resolved_impact_direction"] == "positive"
    assert row["signed_total_5m_abnormal_return"] == pytest.approx(
        row["total_5m_abnormal_return"]
    )


def test_direction_conflict_frame_is_a_manual_audit_queue():
    result = pd.DataFrame(
        [
            {
                "event_id": "conflict",
                "ticker": "3993.HK",
                "event_type": "EARNINGS_WARNING",
                "primary_event_type": "EARNINGS_WARNING",
                "title_en": "POSITIVE PROFIT ALERT",
                "title_zh": "",
                "announcement_at": pd.Timestamp("2026-08-07", tz="UTC"),
                "available_at": pd.Timestamp("2026-08-07 01:00", tz="UTC"),
                "availability_basis": "observed_collection",
                "source_url": "https://example.test/3993.pdf",
                "impact_direction": "negative",
                "impact_confidence": "high",
                "review_status": "auto_parsed",
                "parser_version": "test",
                "derived_impact_direction": "positive",
                "impact_direction_basis": "title_high_precision_positive_match",
            }
        ]
    )
    conflicts = MODULE.direction_conflict_frame(result)
    assert len(conflicts) == 1
    assert conflicts.loc[0, "raw_impact_direction_normalized"] == "negative"
    assert conflicts.loc[0, "derived_impact_direction"] == "positive"
    neutral_title = result.assign(
        event_id="raw-only",
        impact_direction="positive",
        derived_impact_direction="neutral_unknown",
    )
    assert MODULE.direction_conflict_frame(neutral_title).empty


@pytest.mark.parametrize(
    ("raw", "derived", "expected_direction", "expected_basis"),
    [
        ("positive", "neutral_unknown", "positive", "raw_only_title_neutral"),
        ("positive", "positive", "positive", "raw_and_title_agree"),
        ("negative", "positive", "review_required", "raw_derived_conflict"),
        ("unknown", "positive", "positive", "title_only"),
        ("unknown", "neutral_unknown", "unknown", "insufficient_direction_evidence"),
    ],
)
def test_resolve_impact_direction_is_conservative_without_overflagging_neutral_titles(
    raw: str,
    derived: str,
    expected_direction: str,
    expected_basis: str,
):
    assert MODULE.resolve_impact_direction(raw, derived) == (expected_direction, expected_basis)


def test_load_archived_bars_requires_all_requested_symbols(tmp_path: Path):
    capture = tmp_path / "capture-1"
    capture.mkdir()
    rows = []
    for ticker, base in (("0005.HK", 100.0), ("^HSI", 20000.0)):
        rows.append(
            {
                "ticker": ticker,
                "interval": "5m",
                "timestamp_utc": pd.Timestamp("2026-08-07 01:30:00+00:00"),
                "open": base,
                "high": base + 1,
                "low": base - 1,
                "close": base + 0.5,
                "adj_close": base + 0.5,
                "volume": 10,
                "captured_at": pd.Timestamp("2026-08-07 12:00:00+00:00"),
            }
        )
    pd.DataFrame(rows).to_parquet(capture / "bars_5m.parquet", index=False)
    parquet_path = capture / "bars_5m.parquet"
    digest = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    rows_count = len(rows)
    manifest = {
        "version": "yfinance_snapshot_archive.v1",
        "captures": [
            {
                "capture_id": "capture-1",
                "intervals": {
                    "5m": {
                        "path": "capture-1/bars_5m.parquet",
                        "rows": rows_count,
                        "sha256": digest,
                    }
                },
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest) + "\n")

    loaded = MODULE.load_archived_bars(tmp_path, interval="5m", symbols=["0005.HK", "^HSI"])
    assert set(loaded.columns.get_level_values(0)) == {"0005.HK", "^HSI"}
    selected = MODULE.load_archived_bars(
        tmp_path, interval="5m", symbols=["0005.HK", "^HSI"], capture_id="capture-1"
    )
    assert selected.attrs["archive_capture_id"] == "capture-1"
    with pytest.raises(ValueError, match="capture_id not found"):
        MODULE.load_archived_bars(
            tmp_path, interval="5m", symbols=["0005.HK", "^HSI"], capture_id="missing"
        )
    with pytest.raises(ValueError, match="missing requested symbols"):
        MODULE.load_archived_bars(tmp_path, interval="5m", symbols=["0005.HK", "0700.HK"])
    parquet_path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="sha256 mismatch"):
        MODULE.load_archived_bars(tmp_path, interval="5m", symbols=["0005.HK", "^HSI"])


def test_archive_audit_fingerprint_rejects_changed_manifest(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": "yfinance_snapshot_archive.v1", "captures": []}))
    (tmp_path / "archive_audit.json").write_text(
        json.dumps({"version": "yfinance_snapshot_archive_audit.v1", "manifest_sha256": "stale"})
    )
    with pytest.raises(ValueError, match="archive audit is stale"):
        MODULE.load_archive_audit(tmp_path)


def test_merge_bar_frames_preserves_archive_precedence_and_new_symbols():
    index = pd.DatetimeIndex(["2026-08-07 01:30:00+00:00", "2026-08-07 01:35:00+00:00"])
    archive = pd.DataFrame(
        {
            ("0005.HK", "Open"): [100.0, None],
            ("0005.HK", "Close"): [100.5, None],
        },
        index=index,
    )
    archive.columns = pd.MultiIndex.from_tuples(archive.columns)
    live = pd.DataFrame(
        {
            ("0005.HK", "Open"): [999.0, 101.0],
            ("0005.HK", "Close"): [999.5, 101.5],
            ("0700.HK", "Open"): [300.0, 301.0],
            ("0700.HK", "Close"): [300.5, 301.5],
        },
        index=index,
    )
    live.columns = pd.MultiIndex.from_tuples(live.columns)
    merged = MODULE.merge_bar_frames(archive, live)
    assert merged.loc[index[0], ("0005.HK", "Open")] == 100.0
    assert merged.loc[index[1], ("0005.HK", "Open")] == 101.0
    assert merged.loc[index[0], ("0700.HK", "Close")] == 300.5
