"""Offline contracts for the bounded SHKP refresh orchestrator."""

from __future__ import annotations

import pandas as pd
import pytest

from src.hk_real_estate import shkp_refresh
from src.hk_real_estate.shkp_catalog import _reuse_latest_non_empty_snapshot


def _fake_result(run_id: str, **values):
    return {"run_id": run_id, **values}


def test_skip_source_reuses_last_non_empty_snapshot(monkeypatch):
    source = pd.DataFrame([{"value": 1}])
    monkeypatch.setattr(
        "src.hk_real_estate.shkp_catalog.load_latest_normalized",
        lambda name: source.copy(),
    )
    monkeypatch.setattr(
        "src.hk_real_estate.shkp_catalog._latest_lineage",
        lambda name: {"run_id": "prior-run", "records": 1},
    )

    reused = _reuse_latest_non_empty_snapshot(
        "deep_source",
        ["value"],
        reason="test_skip",
    )

    assert reused["value"].tolist() == [1]
    assert reused.attrs["lineage_metadata"]["source_refresh_status"] == "skipped_reused_last_valid"
    assert reused.attrs["lineage_metadata"]["source_refresh_prior_run_id"] == "prior-run"


def test_bounded_refresh_records_steps_and_official_only_mode(monkeypatch):
    saved = {}

    monkeypatch.setattr(
        shkp_refresh,
        "run_shkp_catalog",
        lambda **kwargs: _fake_result("catalog-run", dataset_counts={"shkp_property_catalog": 1}),
    )
    monkeypatch.setattr(
        shkp_refresh,
        "run_shkp_current_manifest_backfill",
        lambda **kwargs: _fake_result("manifest-noop", mode="no_op", selected_development_count=0),
    )
    monkeypatch.setattr(
        shkp_refresh,
        "run_shkp_srpe_transaction_scratch",
        lambda **kwargs: _fake_result("scratch-run", records={"transaction_events": 2}),
    )
    monkeypatch.setattr(
        shkp_refresh,
        "run_shkp_srpe_signal_contract",
        lambda: _fake_result("signals-run", signal_rows=3, phase_rows=1),
    )
    monkeypatch.setattr(
        shkp_refresh,
        "run_shkp_indicative_signal_contract",
        lambda: _fake_result("indicative-run", rows=3),
    )
    monkeypatch.setattr(
        shkp_refresh,
        "run_shkp_all_history_signal_contract",
        lambda: _fake_result("history-run", merged_rows=3, merged_phases=1),
    )
    monkeypatch.setattr(
        shkp_refresh,
        "run_shkp_indicative_sales_model",
        lambda: _fake_result("model-run", rows=3),
    )
    monkeypatch.setattr(
        shkp_refresh,
        "run_shkp_financial_model",
        lambda **kwargs: _fake_result("financial-run", validation={"status": "valid"}),
    )
    monkeypatch.setattr(
        shkp_refresh,
        "load_latest_normalized",
        lambda name: pd.DataFrame([{"period": "2026-01-01"}])
        if name == "shkp_historical_srpe_pilot_developer_monthly_signals"
        else pd.DataFrame(),
    )

    def fake_save(dataset_name, frame, **kwargs):
        saved[dataset_name] = frame.copy()
        return {"dataset_name": dataset_name, "records": len(frame)}

    monkeypatch.setattr(shkp_refresh, "save_normalized_dataset", fake_save)

    result = shkp_refresh.run_shkp_refresh(
        load_financial_data=False,
        strict=True,
    )

    assert result["status"] == "success"
    assert result["financial_data_mode"] == "official_only_no_sibling_financial_data"
    assert "shkp_developer_tracking_refresh_status" in saved
    status = saved["shkp_developer_tracking_refresh_status"]
    assert set(status.loc[status["step"] != "summary", "status"]) >= {"success", "no_op"}
    scratch_row = status.loc[status["step"].eq("transaction_scratch")].iloc[0]
    assert int(scratch_row["records"]) == 2
    summary = status.loc[status["step"].eq("summary")].iloc[0]
    assert summary["status"] == "success"


def test_bounded_refresh_persists_failure_then_fails_strictly(monkeypatch):
    saved = {}

    def fail_catalog(**kwargs):
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(shkp_refresh, "run_shkp_catalog", fail_catalog)
    monkeypatch.setattr(
        shkp_refresh,
        "run_shkp_financial_model",
        lambda **kwargs: _fake_result("financial-run", validation={"status": "valid"}),
    )
    def fake_save(dataset_name, frame, **kwargs):
        saved[dataset_name] = frame.copy()
        return {"dataset_name": dataset_name}

    monkeypatch.setattr(shkp_refresh, "save_normalized_dataset", fake_save)

    with pytest.raises(RuntimeError, match="catalog"):
        shkp_refresh.run_shkp_refresh(load_financial_data=False, strict=True)

    status = saved["shkp_developer_tracking_refresh_status"]
    summary = status.loc[status["step"].eq("summary")].iloc[0]
    assert summary["status"] == "failed"
    assert "index unavailable" in str(summary["error"])
