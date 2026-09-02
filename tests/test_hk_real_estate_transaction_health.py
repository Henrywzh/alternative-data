import pandas as pd
from datetime import datetime, timezone
from src.hk_real_estate.shkp_transaction_health import build_shkp_srpe_transaction_data_health, SITUATION_PARSED, SITUATION_NO_UPDATE, SITUATION_READY

def test_health_classifies_situation_1_2_3():
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)
    quality = pd.DataFrame([{ "srpe_development_id": "8225", "quality_status": "register_parsed_zero_rows", "event_rows": 0 }])
    audit = pd.DataFrame([
        {"srpe_dev_id": "8225", "parse_status": "empty", "rows_emitted": 0, "file_name": "a.pdf", "raw_snapshot_path": "/tmp/a.pdf"},
        {"srpe_dev_id": "2445", "parse_status": "empty", "rows_emitted": 0, "file_name": "b.pdf", "raw_snapshot_path": "/tmp/b.pdf"},
        {"srpe_dev_id": "9999", "parse_status": None, "rows_emitted": 0, "file_name": "c.pdf", "raw_snapshot_path": "/tmp/c.pdf"},
    ])
    events = pd.DataFrame([{ "development_id": "8225", "transaction_id": "1" }, { "development_id": "8225", "transaction_id": "2" }])
    coverage = pd.DataFrame([{ "srpe_development_id": "11554", "development_name": "GARDEN REGENCY", "phase_name": "", "raw_event_rows": 367, "audit_status": "success" }])
    names = pd.DataFrame([{ "srpe_development_id": "8225", "development_name_en": "TWENTY PEAK ROAD BY V", "phase_name_en": None }])
    result = build_shkp_srpe_transaction_data_health(quality_audit=quality, document_audit=audit, historical_events=events, signal_coverage=coverage, eligibility=names, high_recall=names, now=now)
    by_id = result.set_index("srpe_development_id")
    assert by_id.loc["8225", "situation"] == SITUATION_READY
    assert by_id.loc["2445", "situation"] == SITUATION_NO_UPDATE
    assert by_id.loc["9999", "situation"] == SITUATION_PARSED
    assert by_id.loc["11554", "situation"] == SITUATION_READY
