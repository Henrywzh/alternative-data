# SHKP / SRPE transaction-register data-health monitor.
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import pandas as pd
from .storage import load_latest_normalized, save_normalized_dataset
HEALTH_DATASET = "shkp_srpe_transaction_data_health"
SITUATION_PARSED = "situation_1_parsed"
SITUATION_NO_UPDATE = "situation_2_no_deals_or_no_update"
SITUATION_READY = "situation_3_ready"

def _phase_id(row: pd.Series, *columns: str) -> str:
    for column in columns:
        value = str(row.get(column) or "").strip()
        if value and value.lower() not in {"nan", "none"}:
            return value
    return ""

def build_shkp_srpe_transaction_data_health(*, quality_audit: pd.DataFrame | None = None, document_audit: pd.DataFrame | None = None, historical_events: pd.DataFrame | None = None, signal_coverage: pd.DataFrame | None = None, eligibility: pd.DataFrame | None = None, high_recall: pd.DataFrame | None = None, now: datetime | None = None) -> pd.DataFrame:
    now = now or datetime.now(timezone.utc)
    quality_audit = quality_audit if quality_audit is not None else load_latest_normalized("shkp_historical_transaction_quality_audit")
    document_audit = document_audit if document_audit is not None else load_latest_normalized("shkp_historical_srpe_pilot_document_audit")
    historical_events = historical_events if historical_events is not None else load_latest_normalized("shkp_historical_srpe_pilot_transaction_events")
    signal_coverage = signal_coverage if signal_coverage is not None else load_latest_normalized("shkp_srpe_signal_coverage")
    eligibility = eligibility if eligibility is not None else load_latest_normalized("shkp_sales_ingestion_eligibility")
    high_recall = high_recall if high_recall is not None else load_latest_normalized("shkp_high_recall_phase_candidates")
    names = {}
    for frame, id_col, name_col, phase_col in ((eligibility, "srpe_development_id", "development_name_en", "phase_name_en"), (high_recall, "srpe_development_id", "development_name_en", "phase_name_en"), (signal_coverage, "srpe_development_id", "development_name", "phase_name")):
        if frame is None or frame.empty:
            continue
        for _, row in frame.iterrows():
            phase_id = _phase_id(row, id_col, "development_id", "srpe_dev_id")
            if not phase_id:
                continue
            names.setdefault(phase_id, {"development_name": None, "phase_name": None})
            names[phase_id]["development_name"] = names[phase_id]["development_name"] or row.get(name_col)
            names[phase_id]["phase_name"] = names[phase_id]["phase_name"] or row.get(phase_col)
    event_counts = {}
    if historical_events is not None and not historical_events.empty:
        phase_column = next((c for c in ("development_id", "srpe_development_id", "srpe_dev_id") if c in historical_events.columns), None)
        if phase_column:
            event_counts = historical_events.groupby(historical_events[phase_column].astype(str)).size().to_dict()
    coverage_map = {}
    if signal_coverage is not None and not signal_coverage.empty:
        for _, row in signal_coverage.iterrows():
            phase_id = _phase_id(row, "srpe_development_id", "phase_id", "development_id")
            if phase_id:
                coverage_map[phase_id] = row
    quality_map = {}
    if quality_audit is not None and not quality_audit.empty:
        for _, row in quality_audit.iterrows():
            phase_id = _phase_id(row, "srpe_development_id")
            if phase_id:
                quality_map[phase_id] = row
    rows = []
    seen = set()
    if document_audit is not None and not document_audit.empty:
        for _, row in document_audit.iterrows():
            phase_id = _phase_id(row, "srpe_dev_id", "srpe_development_id", "development_id")
            if not phase_id or phase_id in seen:
                continue
            seen.add(phase_id)
            emitted = int(pd.to_numeric(row.get("rows_emitted"), errors="coerce") or 0)
            parse_status = str(row.get("parse_status") or "")
            current_rows = int(event_counts.get(phase_id, 0))
            quality = quality_map.get(phase_id, pd.Series(dtype=object))
            coverage = coverage_map.get(phase_id, pd.Series(dtype=object))
            if current_rows > 0:
                situation = SITUATION_READY
                note = "register parsed and transaction rows are available"
            elif parse_status in {"empty", "success"}:
                situation = SITUATION_NO_UPDATE
                note = "register observed after parse; no extractable deals or no update"
            else:
                situation = SITUATION_PARSED
                note = "situation 1 pending: register file exists but has not been parsed yet"
            rows.append({"srpe_development_id": phase_id, "development_name": names.get(phase_id, {}).get("development_name"), "phase_name": names.get(phase_id, {}).get("phase_name"), "situation": situation, "parse_status": parse_status or None, "file_name": row.get("file_name"), "raw_snapshot_path": row.get("raw_snapshot_path"), "audit_rows_emitted": emitted, "current_event_rows": current_rows, "quality_status": quality.get("quality_status"), "coverage_audit_status": coverage.get("audit_status"), "note": note, "last_verified_at": now.isoformat()})
    for phase_id, coverage in coverage_map.items():
        if phase_id in seen:
            continue
        raw_rows = int(pd.to_numeric(coverage.get("raw_event_rows"), errors="coerce") or 0)
        situation = SITUATION_READY if raw_rows > 0 else SITUATION_NO_UPDATE
        rows.append({"srpe_development_id": phase_id, "development_name": names.get(phase_id, {}).get("development_name") or coverage.get("development_name"), "phase_name": names.get(phase_id, {}).get("phase_name") or coverage.get("phase_name"), "situation": situation, "parse_status": "success" if raw_rows else None, "file_name": None, "raw_snapshot_path": None, "audit_rows_emitted": raw_rows, "current_event_rows": int(event_counts.get(phase_id, raw_rows)), "quality_status": None, "coverage_audit_status": coverage.get("audit_status"), "note": "current candidate register is ready" if raw_rows else "no transaction register rows observed", "last_verified_at": now.isoformat()})
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(["situation", "srpe_development_id"]).reset_index(drop=True)

def run_shkp_srpe_transaction_data_health() -> dict[str, Any]:
    frame = build_shkp_srpe_transaction_data_health()
    normalized = save_normalized_dataset(HEALTH_DATASET, frame, source_urls=["https://www.srpe.gov.hk/opip/all_development"], lineage_metadata={"lineage_type": "derived_shkp_srpe_transaction_data_health", "situation_1": SITUATION_PARSED, "situation_2": SITUATION_NO_UPDATE, "situation_3": SITUATION_READY})
    counts = frame["situation"].value_counts().to_dict() if not frame.empty else {}
    return {"normalized": {HEALTH_DATASET: normalized}, "situation_counts": counts, "rows": int(len(frame))}
