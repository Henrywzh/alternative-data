"""Bounded, repeatable SHKP refresh orchestration.

The repository has many SHKP research contracts, but previously no single
entry point connected the official project index, current SRPE filing queue,
recent transaction batches, signal consolidation and the financial-input
model.  This module is that operational boundary.

The runner is deliberately conservative:

* the catalog refresh is index/website bounded and reuses the last valid deep
  source snapshots when those sources are intentionally skipped;
* an up-to-date SRPE filing queue is recorded as ``no_op`` rather than an
  error;
* project activity remains a leading indicator until the existing
  phase-specific ownership interval gate is approved; and
* a private sibling ``financial-data`` checkout is optional.  If it is not
  available, the official-only financial lane is run with explicit warnings,
  never with fabricated actuals or consensus.

Every step is recorded in ``shkp_developer_tracking_refresh_status`` so a
scheduled run can be inspected without inferring success from a process exit
code alone.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .shkp_catalog import run_shkp_catalog, run_shkp_current_manifest_backfill
from .shkp_financial_model import (
    FINANCIAL_DATA_DB_PATH,
    run_shkp_financial_model,
)
from .shkp_indicative_sales_model import run_shkp_indicative_sales_model
from .shkp_signals import (
    run_shkp_all_history_signal_contract,
    run_shkp_indicative_signal_contract,
    run_shkp_srpe_signal_contract,
)
from .shkp_srpe_backfill import run_shkp_srpe_transaction_scratch
from .storage import load_latest_normalized, save_normalized_dataset


SHKP_REFRESH_STATUS_DATASET = "shkp_developer_tracking_refresh_status"
SHKP_REFRESH_STATUS_COLUMNS = [
    "refresh_run_id",
    "ticker",
    "step",
    "status",
    "required",
    "started_at",
    "finished_at",
    "child_run_id",
    "records",
    "phases",
    "warning",
    "error",
    "details_json",
    "source_refresh_mode",
    "research_only",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def _result_count(result: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = result.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, dict):
            # A few source runners return a compact per-output count mapping
            # (for example ``records: {transaction_events: ..., ...}``).
            # Surface its total in the status contract instead of silently
            # recording ``null``.  Prefer an explicit total when present; do
            # not count nested mappings or booleans as rows.
            for total_key in ("total", "total_rows", "rows"):
                total = value.get(total_key)
                if isinstance(total, (int, float)) and not isinstance(total, bool):
                    return int(total)
            numeric = [
                item
                for item in value.values()
                if isinstance(item, (int, float)) and not isinstance(item, bool)
            ]
            if numeric:
                return int(sum(numeric))
            continue
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _step_row(
    *,
    refresh_run_id: str,
    step: str,
    status: str,
    required: bool,
    started_at: str,
    finished_at: str,
    result: dict[str, Any] | None = None,
    warning: str | None = None,
    error: str | None = None,
    source_refresh_mode: str = "live",
) -> dict[str, Any]:
    payload = result or {}
    warnings = payload.get("warnings") or []
    if isinstance(warnings, str):
        warnings = [warnings]
    warning_text = warning or " | ".join(str(item) for item in warnings if item)
    return {
        "refresh_run_id": refresh_run_id,
        "ticker": "0016.HK",
        "step": step,
        "status": status,
        "required": bool(required),
        "started_at": started_at,
        "finished_at": finished_at,
        "child_run_id": payload.get("run_id"),
        "records": _result_count(
            payload,
            (
                "records",
                "rows",
                "signal_rows",
                "merged_rows",
                "disclosed_rows",
                "new_manifest_rows",
                "raw_transaction_rows",
            ),
        ),
        "phases": _result_count(
            payload,
            (
                "phases",
                "merged_phases",
                "manifest_phase_count",
                "phase_rows",
                "scratch_eligible_recent_phase_count",
            ),
        ),
        "warning": warning_text or None,
        "error": error,
        "details_json": _json(payload),
        "source_refresh_mode": source_refresh_mode,
        "research_only": bool(payload.get("research_only", True)),
    }


def _save_status(
    frame: pd.DataFrame,
    *,
    refresh_run_id: str,
    source_urls: list[str],
) -> dict[str, Any]:
    return save_normalized_dataset(
        SHKP_REFRESH_STATUS_DATASET,
        frame.reindex(columns=SHKP_REFRESH_STATUS_COLUMNS),
        run_id=refresh_run_id,
        source_urls=source_urls,
        lineage_metadata={
            "lineage_type": "shkp_bounded_refresh_status",
            "refresh_run_id": refresh_run_id,
            "ticker": "0016.HK",
            "step_status_contract": "one_row_per_step_plus_summary",
            "ownership_policy": "phase_specific_effective_interval_required",
            "missing_data_policy": "unknown_is_not_zero; no_srpe_is_not_no_sales",
        },
    )


def run_shkp_refresh(
    *,
    timeout: float = 45,
    max_pages: int | None = None,
    catalog_site_project_limit: int = 0,
    catalog_max_manifest_developments: int = 0,
    current_manifest_max_developments: int = 25,
    recent_days: int = 90,
    recent_years: int = 2,
    refresh_after_days: int = 7,
    include_older_active: bool = False,
    transaction_max_phases: int = 8,
    transaction_start_index: int = 0,
    include_review: bool = False,
    transaction_request_delay: float = 0.25,
    financial_db: Path | None = None,
    load_financial_data: bool | None = None,
    include_price_history: bool = False,
    strict: bool = True,
) -> dict[str, Any]:
    """Refresh the SHKP developer-tracking and model-input minimum viable set.

    The default is bounded for a scheduled job.  It fetches the official
    issuer directory, SRPE index and pipeline, refreshes only recent/current
    filing metadata, parses a small recent transaction batch, consolidates
    signals, then builds official financial-model inputs.  ``strict`` fails
    the command only when a required step fails; expected no-op/coverage gaps
    are retained as warnings in the status dataset.
    """
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if current_manifest_max_developments <= 0:
        raise ValueError("current_manifest_max_developments must be positive")
    if transaction_max_phases <= 0:
        raise ValueError("transaction_max_phases must be positive")
    if transaction_start_index < 0:
        raise ValueError("transaction_start_index must be non-negative")
    if recent_days < 0 or recent_years < 0:
        raise ValueError("recent_days and recent_years must be non-negative")

    refresh_run_id = f"shkp-refresh-{uuid.uuid4()}"
    rows: list[dict[str, Any]] = []
    results: dict[str, Any] = {}
    required_failures: list[str] = []
    warnings: list[str] = []

    def execute(
        step: str,
        fn: Callable[[], dict[str, Any]],
        *,
        required: bool,
        source_refresh_mode: str = "live",
        empty_warning: str | None = None,
    ) -> dict[str, Any] | None:
        started = _utc_now()
        try:
            result = fn()
            if not isinstance(result, dict):
                result = {"result": result}
            status = "no_op" if result.get("mode") == "no_op" else "success"
            nested_validation = result.get("validation")
            nested_warnings = (
                nested_validation.get("warnings")
                if isinstance(nested_validation, dict)
                else []
            ) or []
            if nested_warnings:
                warnings.extend(f"{step}: {item}" for item in nested_warnings)
                if status == "success":
                    status = "warning"
            if empty_warning:
                record_count = _result_count(
                    result,
                    ("records", "rows", "signal_rows", "merged_rows", "disclosed_rows"),
                )
                if record_count == 0:
                    status = "warning"
                    warnings.append(f"{step}: {empty_warning}")
            rows.append(
                _step_row(
                    refresh_run_id=refresh_run_id,
                    step=step,
                    status=status,
                    required=required,
                    started_at=started,
                    finished_at=_utc_now(),
                    result=result,
                    warning=(
                        " | ".join(str(item) for item in nested_warnings)
                        if nested_warnings
                        else empty_warning
                        if status == "warning"
                        else None
                    ),
                    source_refresh_mode=source_refresh_mode,
                )
            )
            results[step] = result
            return result
        except Exception as exc:  # retain the failure in the status contract
            message = f"{type(exc).__name__}: {exc}"
            rows.append(
                _step_row(
                    refresh_run_id=refresh_run_id,
                    step=step,
                    status="failed",
                    required=required,
                    started_at=started,
                    finished_at=_utc_now(),
                    error=message,
                    source_refresh_mode=source_refresh_mode,
                )
            )
            results[step] = {"status": "failed", "error": message}
            if required:
                required_failures.append(f"{step}: {message}")
            else:
                warnings.append(f"{step}: {message}")
            return None

    catalog = execute(
        "catalog",
        lambda: run_shkp_catalog(
            timeout=timeout,
            max_pages=max_pages,
            max_manifest_developments=catalog_max_manifest_developments,
            site_project_limit=catalog_site_project_limit,
            skip_site_facts=catalog_site_project_limit == 0,
            skip_deep_documents=True,
        ),
        required=True,
        source_refresh_mode="bounded_index_pipeline_reusing_skipped_deep_snapshots",
    )

    if catalog is not None:
        execute(
            "current_manifest",
            lambda: run_shkp_current_manifest_backfill(
                max_developments=current_manifest_max_developments,
                timeout=min(timeout, 30),
                recent_days=recent_days,
                recent_years=recent_years,
                refresh_after_days=refresh_after_days,
                include_older_active=include_older_active,
                allow_noop=True,
            ),
            required=False,
            source_refresh_mode="recent_active_current_directory_queue",
        )
        execute(
            "transaction_scratch",
            lambda: run_shkp_srpe_transaction_scratch(
                max_phases=transaction_max_phases,
                start_index=transaction_start_index,
                include_review=include_review,
                recent_days=recent_days,
                recent_years=recent_years,
                include_older_active=include_older_active,
                timeout=min(timeout, 30),
                request_delay=transaction_request_delay,
            ),
            required=False,
            source_refresh_mode="recent_active_candidate_transaction_registers",
            empty_warning="no recent routed transaction rows were produced; this is a coverage warning, not zero sales",
        )
        signals = execute(
            "signals",
            run_shkp_srpe_signal_contract,
            required=True,
            source_refresh_mode="all_persisted_scratch_batches_deduplicated",
            empty_warning="strict signal layer is empty; inspect scratch routing and parser audit",
        )
        if signals is not None:
            execute(
                "indicative_signals",
                run_shkp_indicative_signal_contract,
                required=False,
                source_refresh_mode="indicative_ownership_only",
            )
            historical = load_latest_normalized(
                "shkp_historical_srpe_pilot_developer_monthly_signals"
            )
            if historical.empty:
                rows.append(
                    _step_row(
                        refresh_run_id=refresh_run_id,
                        step="all_history_signals",
                        status="skipped",
                        required=False,
                        started_at=_utc_now(),
                        finished_at=_utc_now(),
                        warning="historical SRPE backfill is not present; current signals remain usable but all-history coverage is not refreshed",
                        source_refresh_mode="historical_backfill_not_available",
                    )
                )
                warnings.append("all_history_signals: historical backfill not available")
            else:
                execute(
                    "all_history_signals",
                    run_shkp_all_history_signal_contract,
                    required=False,
                    source_refresh_mode="current_plus_sparse_historical_registers",
                )
            execute(
                "indicative_sales_model",
                run_shkp_indicative_sales_model,
                required=False,
                source_refresh_mode="indicative_project_activity_proxy",
            )
    else:
        for step in ("current_manifest", "transaction_scratch", "signals", "indicative_signals", "all_history_signals", "indicative_sales_model"):
            rows.append(
                _step_row(
                    refresh_run_id=refresh_run_id,
                    step=step,
                    status="skipped",
                    required=step == "signals",
                    started_at=_utc_now(),
                    finished_at=_utc_now(),
                    warning="catalog failed; dependent step was not attempted",
                    source_refresh_mode="dependency_failed",
                )
            )

    db_path = Path(financial_db or FINANCIAL_DATA_DB_PATH)
    financial_available = db_path.is_file()
    if load_financial_data is None:
        load_financial_data = financial_available
    if load_financial_data and not financial_available:
        warning = f"financial-data requested but DuckDB is missing at {db_path}; switching to explicit official-only lane"
        warnings.append(warning)
        load_financial_data = False
    financial_mode = "sibling_financial_data_plus_official" if load_financial_data else "official_only_no_sibling_financial_data"
    execute(
        "financial_model",
        lambda: run_shkp_financial_model(
            db_path=db_path,
            include_price_history=include_price_history,
            load_financial_data=bool(load_financial_data),
        ),
        required=True,
        source_refresh_mode=financial_mode,
    )

    overall_status = "failed" if required_failures else "warning" if warnings else "success"
    summary_warning = " | ".join(warnings) if warnings else None
    summary = _step_row(
        refresh_run_id=refresh_run_id,
        step="summary",
        status=overall_status,
        required=True,
        started_at=rows[0]["started_at"] if rows else _utc_now(),
        finished_at=_utc_now(),
        result={
            "run_id": refresh_run_id,
            "status": overall_status,
            "financial_data_mode": financial_mode,
            "required_failures": required_failures,
            "warnings": warnings,
            "step_count": len(rows),
        },
        warning=summary_warning,
        error=" | ".join(required_failures) if required_failures else None,
        source_refresh_mode="shkp_bounded_refresh_summary",
    )
    rows.append(summary)
    status_frame = pd.DataFrame(rows, columns=SHKP_REFRESH_STATUS_COLUMNS)
    status_normalized = _save_status(
        status_frame,
        refresh_run_id=refresh_run_id,
        source_urls=[
            "https://www.shkp.com/en-US/our-business/hong-kong-properties",
            "https://www.srpe.gov.hk/opip/all_development",
            "https://www.shkp.com/en-US/investor-relations/financial-summary",
        ],
    )

    output = {
        "mode": "shkp_bounded_refresh",
        "run_id": refresh_run_id,
        "status": overall_status,
        "financial_data_mode": financial_mode,
        "financial_data_db_path": str(db_path),
        "required_failures": required_failures,
        "warnings": warnings,
        "steps": rows,
        "normalized": {SHKP_REFRESH_STATUS_DATASET: status_normalized},
        "ownership_policy": "project activity remains non-attributable until an approved phase-specific effective interval exists",
    }
    if strict and required_failures:
        raise RuntimeError("SHKP refresh failed required steps: " + " | ".join(required_failures))
    return output


__all__ = [
    "SHKP_REFRESH_STATUS_COLUMNS",
    "SHKP_REFRESH_STATUS_DATASET",
    "run_shkp_refresh",
]
