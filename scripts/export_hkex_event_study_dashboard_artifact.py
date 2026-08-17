"""Export a research-only HKEX event-study bundle as a dashboard artifact.

The event-study generator intentionally writes auditable CSV/JSON evidence
files.  This adapter adds the repository's unified ``manifest`` +
``snapshot.datasets`` contract without wiring the research bundle into the
production sector roster or making the Streamlit app fetch raw CSVs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from audit_hkex_event_study_outputs import audit_output
except ModuleNotFoundError:  # pragma: no cover - needed for file-based imports in tests
    _AUDITOR_SPEC = importlib.util.spec_from_file_location(
        "audit_hkex_event_study_outputs",
        Path(__file__).with_name("audit_hkex_event_study_outputs.py"),
    )
    if _AUDITOR_SPEC is None or _AUDITOR_SPEC.loader is None:
        raise
    _AUDITOR_MODULE = importlib.util.module_from_spec(_AUDITOR_SPEC)
    _AUDITOR_SPEC.loader.exec_module(_AUDITOR_MODULE)
    audit_output = _AUDITOR_MODULE.audit_output


SCOPE_LABELS = {
    "hkex_event_study_yfinance": "full_universe",
    "hkex_event_study_top30": "top30",
    "hkex_event_study_candidates": "candidate_exploratory",
    "hkex_event_study_candidates_pit_recovered": "candidate_pit_recovered",
}
REPO_ROOT = Path(__file__).resolve().parents[1]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    clean = frame.astype(object).where(pd.notna(frame), None)
    return [_json_safe(row) for row in clean.to_dict(orient="records")]


def _bool_series(values: pd.Series) -> pd.Series:
    return values.astype(str).str.lower().isin({"true", "1", "yes"})


def _weighted_mean(group: pd.DataFrame, value: str, weight: str) -> float | None:
    values = pd.to_numeric(group[value], errors="coerce")
    weights = pd.to_numeric(group[weight], errors="coerce")
    valid = values.notna() & weights.notna() & weights.gt(0)
    if not valid.any():
        return None
    return float((values.loc[valid] * weights.loc[valid]).sum() / weights.loc[valid].sum())


def _scope_for(input_dir: Path) -> str:
    return SCOPE_LABELS.get(input_dir.name, input_dir.name)


def _archive_provenance(coverage: dict[str, Any]) -> dict[str, Any]:
    """Return the immutable capture IDs and cutoffs used by a replay.

    A replay with ``archive_capture_id`` reads one capture.  Candidate replays
    omit that field and intentionally merge all manifest-backed captures, so
    their provenance must say so explicitly rather than looking canonical.
    """
    audit = coverage.get("archive_audit") or {}
    selected_id = coverage.get("archive_capture_id")
    records: dict[str, dict[str, Any]] = {}
    for interval, info in (audit.get("intervals") or {}).items():
        for record in info.get("capture_records") or []:
            capture_id = record.get("capture_id")
            if capture_id:
                records.setdefault(str(capture_id), {})[str(interval)] = record
    capture_ids = [str(selected_id)] if selected_id else sorted(records)
    cutoffs: dict[str, list[str]] = {}
    for interval in ("5m", "1h"):
        values = []
        for capture_id in capture_ids:
            record = records.get(capture_id, {}).get(interval) or {}
            if record.get("latest_bar_utc"):
                values.append(str(record["latest_bar_utc"]))
        cutoffs[interval] = sorted(set(values))
    return {
        "archive_capture_ids": capture_ids,
        "archive_capture_scope": "single_capture" if selected_id else "merged_manifest_archive",
        "archive_market_cutoffs_by_interval": cutoffs,
        "distinct_market_cutoffs_5m": cutoffs["5m"],
        "distinct_market_cutoffs_1h": cutoffs["1h"],
        "distinct_market_cutoff_count_5m": len(cutoffs["5m"]),
        "distinct_market_cutoff_count_1h": len(cutoffs["1h"]),
        "canonical_symbol_count": int(audit.get("requested_symbol_count", 0)),
    }


def _load_csv(input_dir: Path, name: str) -> pd.DataFrame:
    path = input_dir / name
    if not path.exists():
        raise FileNotFoundError(f"missing event-study artifact: {path}")
    return pd.read_csv(path)


def _build_stock_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    events = events.copy()
    events["is_covered"] = events["market_data_status"].eq("covered")
    events["is_type_rep"] = _bool_series(events["is_type_cluster_representative"])
    events["is_pure"] = _bool_series(events["is_pure_event_type"])
    events["is_multi_document"] = _bool_series(events["is_multi_document_cluster"])
    for ticker, group in events.groupby("ticker", sort=True):
        representative = group.loc[group["is_type_rep"] & group["is_covered"]].copy()
        signed = pd.to_numeric(
            representative["signed_total_1h_abnormal_return"], errors="coerce"
        ).dropna()
        total = pd.to_numeric(
            representative["total_1h_abnormal_return"], errors="coerce"
        ).dropna()
        available = pd.to_datetime(group["available_at"], errors="coerce", utc=True).dropna()
        rows.append(
            {
                "ticker": ticker,
                "event_rows": int(len(group)),
                "covered_event_rows": int(group["is_covered"].sum()),
                "type_cluster_rows": int(group["is_type_rep"].sum()),
                "covered_type_cluster_rows": int(len(representative)),
                "pure_event_rows": int(group["is_pure"].sum()),
                "multi_document_rows": int(group["is_multi_document"].sum()),
                "observed_collection_rows": int(group["availability_basis"].eq("observed_collection").sum()),
                "source_timestamp_proxy_rows": int(group["availability_basis"].eq("source_timestamp_proxy").sum()),
                "positive_direction_rows": int(group["resolved_impact_direction"].eq("positive").sum()),
                "negative_direction_rows": int(group["resolved_impact_direction"].eq("negative").sum()),
                "review_direction_rows": int(group["resolved_impact_direction"].eq("review_required").sum()),
                "mean_total_1h_abnormal_return": None if total.empty else float(total.mean()),
                "directional_1h_win_rate": None if signed.empty else float((signed > 0).mean()),
                "directional_1h_mean_signed_abnormal_return": None if signed.empty else float(signed.mean()),
                "latest_available_at": None if available.empty else available.max().isoformat(),
                "coverage_status": "covered" if group["is_covered"].any() else "missing",
            }
        )
    return pd.DataFrame(rows)


def _build_direction_summary(coverage: dict[str, Any], events: pd.DataFrame) -> pd.DataFrame:
    counts = coverage.get("resolved_impact_direction_counts", {})
    rows = []
    for direction in ("positive", "negative", "mixed", "review_required", "unknown"):
        rows.append(
            {
                "resolved_impact_direction": direction,
                "event_rows": int(counts.get(direction, 0)),
                "share_of_event_rows": (
                    None
                    if not len(events)
                    else float(counts.get(direction, 0) / len(events))
                ),
                "dashboard_eligibility": (
                    "directional_efficacy_view"
                    if direction in {"positive", "negative"}
                    else "context_or_review_only"
                ),
            }
        )
    return pd.DataFrame(rows)


def _build_pit_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for basis, group in events.groupby("availability_basis", dropna=False, sort=True):
        basis = "unknown" if pd.isna(basis) else str(basis)
        covered = group["market_data_status"].eq("covered")
        delays = pd.to_numeric(group["source_delay_minutes"], errors="coerce").dropna()
        rows.append(
            {
                "availability_basis": basis,
                "event_rows": int(len(group)),
                "covered_event_rows": int(covered.sum()),
                "missing_event_rows": int((~covered).sum()),
                "median_source_delay_minutes": None if delays.empty else float(delays.median()),
                "pit_quality": (
                    "observed_collection"
                    if basis == "observed_collection"
                    else "historical_timing_proxy"
                    if basis == "source_timestamp_proxy"
                    else "unknown"
                ),
                "dashboard_default": basis == "observed_collection",
            }
        )
    return pd.DataFrame(rows)


def _build_pit_recovery_summary(
    sidecar_dir: Path,
    active_event_ids: set[str] | None = None,
) -> pd.DataFrame:
    """Expose PIT recovery proof without treating it as event-study input."""
    columns = [
        "sidecar_version", "sidecar_status", "recovered_legacy_rows",
        "official_datetime_verified_rows", "url_continuity_verified_rows",
        "official_timestamp_verified_rows", "availability_delta_verified_rows",
        "retrospective_collection_verified_rows", "median_availability_delta_minutes",
        "event_study_eligible_rows", "event_study_eligible", "active_event_overlap_rows",
        "isolation_status",
        "exclusion_reason", "production_database_modified",
    ]
    manifest_path = sidecar_dir / "pit_recovery_manifest.json"
    if not manifest_path.exists():
        return pd.DataFrame(
            [{
                "sidecar_version": None,
                "sidecar_status": "not_available",
                "recovered_legacy_rows": 0,
                "official_datetime_verified_rows": 0,
                "url_continuity_verified_rows": 0,
                "official_timestamp_verified_rows": 0,
                "availability_delta_verified_rows": 0,
                "retrospective_collection_verified_rows": 0,
                "median_availability_delta_minutes": None,
                "event_study_eligible_rows": 0,
                "event_study_eligible": False,
                "active_event_overlap_rows": 0,
                "isolation_status": "isolated_audit_sidecar_not_available",
                "exclusion_reason": "PIT recovery sidecar has not been generated",
                "production_database_modified": False,
            }],
            columns=columns,
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows_path = sidecar_dir / "pit_recovered_filings.parquet"
    rows = pd.read_parquet(rows_path) if rows_path.exists() else pd.DataFrame()
    sidecar_ids = set(rows["filing_id"].astype(str)) if "filing_id" in rows else set()
    # Candidate event studies represent non-canonical filings as ``filing:<id>``.
    # Check both raw and prefixed forms so the dashboard artifact cannot certify
    # a sidecar as isolated while an exploratory candidate run has imported it.
    sidecar_event_ids = sidecar_ids | {f"filing:{filing_id}" for filing_id in sidecar_ids}
    active_overlap = 0 if active_event_ids is None else len(sidecar_event_ids & active_event_ids)
    def verified_count(field: str) -> int:
        return 0 if rows.empty or field not in rows else int(_bool_series(rows[field]).sum())
    deltas = pd.to_numeric(rows.get("availability_delta_minutes"), errors="coerce").dropna() if not rows.empty else pd.Series(dtype=float)
    return pd.DataFrame(
        [{
            "sidecar_version": manifest.get("version"),
            "sidecar_status": manifest.get("status", "unknown"),
            "recovered_legacy_rows": int(manifest.get("recovered_legacy_rows", 0)),
            "official_datetime_verified_rows": int(manifest.get("official_datetime_verified_rows", 0)),
            "url_continuity_verified_rows": verified_count("url_continuity_ok"),
            "official_timestamp_verified_rows": verified_count("official_timestamp_ok"),
            "availability_delta_verified_rows": verified_count("availability_delta_ok"),
            "retrospective_collection_verified_rows": verified_count("retrospective_collection_ok"),
            "median_availability_delta_minutes": None if deltas.empty else float(deltas.median()),
            "event_study_eligible_rows": int(manifest.get("event_study_eligible_rows", 0)),
            "event_study_eligible": False,
            "active_event_overlap_rows": active_overlap,
            "isolation_status": "isolated_audit_sidecar",
            "exclusion_reason": "PIT recovery audit only; promotion requires candidate taxonomy, market coverage, cluster and signal gates",
            "production_database_modified": manifest.get("production_database_modified") is True,
        }],
        columns=columns,
    )


def _build_stale_symbol_summary(coverage: dict[str, Any]) -> pd.DataFrame:
    stale = coverage.get("archive_stale_event_tickers", []) or []
    latest_by_interval = coverage.get("archive_symbol_latest_by_interval", {}) or {}
    reference_5m = (latest_by_interval.get("5m", {}) or {}).get("^HSI")
    reference_1h = (latest_by_interval.get("1h", {}) or {}).get("^HSI")
    rows: list[dict[str, Any]] = []
    for ticker in stale:
        for interval, reference in (("5m", reference_5m), ("1h", reference_1h)):
            latest = (latest_by_interval.get(interval, {}) or {}).get(str(ticker))
            latest_ts = pd.to_datetime(latest, errors="coerce", utc=True)
            reference_ts = pd.to_datetime(reference, errors="coerce", utc=True)
            lag_hours = None
            if pd.notna(latest_ts) and pd.notna(reference_ts):
                lag_hours = float((reference_ts - latest_ts).total_seconds() / 3600.0)
            rows.append(
                {
                    "ticker": ticker,
                    "interval": interval,
                    "latest_bar_at": None if pd.isna(latest_ts) else latest_ts.isoformat(),
                    "reference_cutoff_at": None if pd.isna(reference_ts) else reference_ts.isoformat(),
                    "bar_lag_hours": lag_hours,
                    "status": "stale_yfinance_history_unresolved",
                    "interpretation": "No newer yfinance bar was returned; do not infer suspension or fill prices without independent evidence.",
                }
            )
    return pd.DataFrame(rows)


def _build_horizon_summary(robustness: pd.DataFrame) -> pd.DataFrame:
    if robustness.empty:
        return pd.DataFrame(
            columns=[
                "horizon", "resolved_impact_direction", "type_cluster_rows",
                "mean_abnormal_return", "mean_total_abnormal_return",
                "directional_win_rate", "total_directional_win_rate",
            ]
        )
    rows: list[dict[str, Any]] = []
    for (horizon, direction), group in robustness.groupby(
        ["horizon", "resolved_impact_direction"], sort=True, dropna=False
    ):
        rows.append(
            {
                "horizon": horizon,
                "resolved_impact_direction": direction,
                "type_cluster_rows": int(
                    pd.to_numeric(group["n_type_clusters"], errors="coerce").fillna(0).sum()
                ),
                "mean_abnormal_return": _weighted_mean(group, "mean_abnormal_return", "n_type_clusters"),
                "mean_total_abnormal_return": _weighted_mean(
                    group, "mean_total_abnormal_return", "total_return_rows"
                ),
                "directional_win_rate": _weighted_mean(
                    group, "directional_win_rate", "directional_return_rows"
                ),
                "total_directional_win_rate": _weighted_mean(
                    group, "total_directional_win_rate", "total_directional_return_rows"
                ),
            }
        )
    return pd.DataFrame(rows)


def _build_coverage_summary(coverage: dict[str, Any], events: pd.DataFrame, scope: str) -> pd.DataFrame:
    status_counts = coverage.get("market_data_status_counts", {})
    representative = events.loc[
        _bool_series(events["is_type_cluster_representative"])
        & events["market_data_status"].eq("covered")
    ]
    signed = pd.to_numeric(representative["signed_total_1h_abnormal_return"], errors="coerce").dropna()
    latest_5m = (coverage.get("archive_symbol_latest_by_interval", {}).get("5m", {}) or {}).get("^HSI")
    latest_1h = (coverage.get("archive_symbol_latest_by_interval", {}).get("1h", {}) or {}).get("^HSI")
    gate = coverage.get("signal_registration_gate", {})
    event_return_coverage = coverage.get("event_row_return_coverage", {}) or {}
    cluster_return_coverage = coverage.get("cluster_return_coverage", {}) or {}
    return pd.DataFrame(
        [
            {
                "evaluation_scope": scope,
                "event_rows": int(coverage.get("event_rows", len(events))),
                "covered_event_rows": int(status_counts.get("covered", 0)),
                "missing_event_rows": int(status_counts.get("missing", 0)),
                "pending_market_cutoff_event_rows": int(coverage.get("pending_market_cutoff_event_rows", 0)),
                "candidate_archive_expansion_ticker_count": int(
                    coverage.get("candidate_archive_expansion_ticker_count", 0)
                ),
                "candidate_archive_unavailable_ticker_count": int(
                    coverage.get("candidate_archive_unavailable_ticker_count", 0)
                ),
                "bar_hole_event_rows": int(coverage.get("bar_hole_event_rows", 0)),
                "event_return_coverage_5m": int(event_return_coverage.get("5m", 0)),
                "event_return_coverage_30m": int(event_return_coverage.get("30m", 0)),
                "event_return_coverage_1h": int(event_return_coverage.get("1h", 0)),
                "cluster_return_coverage_5m": int(cluster_return_coverage.get("5m", 0)),
                "cluster_return_coverage_30m": int(cluster_return_coverage.get("30m", 0)),
                "cluster_return_coverage_1h": int(cluster_return_coverage.get("1h", 0)),
                "native_1h_return_coverage": int(coverage.get("native_1h_return_coverage", 0)),
                "native_1h_global_directional_agreement_rate": coverage.get(
                    "native_1h_global_directional_agreement_rate"
                ),
                "native_1h_mean_absolute_difference": coverage.get("native_1h_mean_absolute_difference"),
                "directional_1h_rows": int(len(signed)),
                "directional_1h_win_rate": None if signed.empty else float((signed > 0).mean()),
                "directional_1h_mean_signed_abnormal_return": None if signed.empty else float(signed.mean()),
                "raw_direction_conflict_rows": int(coverage.get("raw_direction_conflict_rows", 0)),
                "direction_override_rows": int(coverage.get("direction_override_rows", 0)),
                "event_clusters": int(coverage.get("event_clusters", 0)),
                "multi_document_cluster_count": int(coverage.get("multi_document_cluster_count", 0)),
                "pure_event_cluster_count": int(coverage.get("pure_event_cluster_count", 0)),
                "contaminated_type_cluster_rows": int(coverage.get("contaminated_type_cluster_rows", 0)),
                "latest_market_cutoff_5m": latest_5m,
                "latest_market_cutoff_1h": latest_1h,
                "signal_gate_status": gate.get("status", "blocked"),
                "signal_gate_reasons": "; ".join(str(reason) for reason in gate.get("reasons", [])),
                "production_database_modified": coverage.get("production_database_modified") is True,
            }
        ]
    )


def validate_artifact(artifact: dict[str, Any]) -> None:
    """Validate the adapter contract before persisting a dashboard artifact."""
    required_datasets = {
        "coverage_summary", "direction_summary", "pit_summary", "pit_recovery_summary", "cluster_summary", "stock_summary",
        "stale_symbol_summary",
        "directional_horizon_summary", "event_returns", "event_robustness_summary",
        "event_stratified_summary", "event_gap_drift_summary", "event_native_1h_sensitivity",
        "event_direction_conflicts", "signal_registry", "source_health",
    }
    if artifact.get("surface") != "dashboard":
        raise ValueError("artifact surface must be dashboard")
    manifest = artifact.get("manifest", {})
    if manifest.get("version") != "hkex_event_study_artifact.v1":
        raise ValueError("unsupported HKEX event-study artifact version")
    snapshot = artifact.get("snapshot", {})
    datasets = snapshot.get("datasets", {})
    missing = sorted(required_datasets.difference(datasets))
    if missing or snapshot.get("status") != "ready":
        raise ValueError(f"artifact datasets/status invalid: missing={missing}")
    coverage_rows = datasets["coverage_summary"]
    if len(coverage_rows) != 1 or coverage_rows[0].get("signal_gate_status") != "blocked":
        raise ValueError("research artifact must expose a blocked signal gate")
    registry = datasets["signal_registry"]
    if any(bool(row.get("registered_for_trading_signal")) for row in registry):
        raise ValueError("research artifact cannot contain registered trading signals")
    recovery_rows = datasets["pit_recovery_summary"]
    for row in recovery_rows:
        if (
            row.get("event_study_eligible_rows") != 0
            or row.get("event_study_eligible") is not False
            or row.get("active_event_overlap_rows") != 0
        ):
            raise ValueError("pit_recovery_summary must remain event-study ineligible")
    event_keys = [
        (row.get("evaluation_scope"), row.get("event_id"))
        for row in datasets["event_returns"]
    ]
    if len(event_keys) != len(set(event_keys)):
        raise ValueError("event_returns evaluation_scope/event_id must be unique")
    for chart in manifest.get("charts", []):
        encodings = chart.get("encodings", {})
        if not encodings.get("x", {}).get("field") or not encodings.get("y", {}).get("field"):
            raise ValueError(f"chart is missing x/y encoding: {chart.get('id')}")
    for table in manifest.get("tables", []):
        if table.get("dataset") not in datasets:
            raise ValueError(f"table references missing dataset: {table.get('id')}")
    if artifact.get("package_info", {}).get("researchOnly") is not True:
        raise ValueError("artifact must be marked researchOnly")
    if artifact.get("package_info", {}).get("productionDatabaseModified") is not False:
        raise ValueError("artifact must confirm production database was unmodified")


def build_artifact(input_dir: Path, output_path: Path, comparison_path: Path | None = None) -> dict[str, Any]:
    input_dir = input_dir.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit = audit_output(input_dir, comparison_path)
    if audit.get("status") != "ok":
        raise ValueError(f"input bundle failed post-write audit: {audit.get('errors')}")
    coverage = json.loads((input_dir / "coverage.json").read_text(encoding="utf-8"))
    events = _load_csv(input_dir, "event_returns.csv")
    robustness = _load_csv(input_dir, "event_robustness_summary.csv")
    stratified = _load_csv(input_dir, "event_stratified_summary.csv")
    gap_drift = _load_csv(input_dir, "event_gap_drift_summary.csv")
    native = _load_csv(input_dir, "event_native_1h_sensitivity.csv")
    conflicts = _load_csv(input_dir, "event_direction_conflicts.csv")
    registry = _load_csv(input_dir, "signal_registry.csv")
    scope = _scope_for(input_dir)
    coverage_summary = _build_coverage_summary(coverage, events, scope)
    direction_summary = _build_direction_summary(coverage, events)
    pit_summary = _build_pit_summary(events)
    pit_recovery_summary = _build_pit_recovery_summary(
        REPO_ROOT / "outputs/hkex_pit_recovery_sidecar",
        active_event_ids=set(events["event_id"].astype(str)),
    )
    stale_symbol_summary = _build_stale_symbol_summary(coverage)
    horizon_summary = _build_horizon_summary(robustness)
    stock_summary = _build_stock_summary(events)
    cluster_summary = pd.DataFrame(
        [
            {
                "evaluation_scope": scope,
                "event_clusters": coverage.get("event_clusters", 0),
                "multi_document_cluster_count": coverage.get("multi_document_cluster_count", 0),
                "pure_event_cluster_count": coverage.get("pure_event_cluster_count", 0),
                "contaminated_type_cluster_rows": coverage.get("contaminated_type_cluster_rows", 0),
                "cluster_policy": "same eligible entry bar; no interpolation; mixed-type clusters remain reviewable",
            }
        ]
    )
    source_health = pd.DataFrame(
        [
            {
                "source_id": "hkex_announcement_events",
                "status": "available",
                "grain": "one row per source announcement event_id",
                "path": str(Path("/Users/henrywzh/Desktop/Quant/financial-data/data/databases/hk_financials.duckdb")),
                "caveat": "PIT completeness is carried per event; source_timestamp_proxy rows are not observed live availability.",
            },
            {
                "source_id": "yfinance_intraday_archive",
                "status": "available_with_gate_caveats",
                "grain": "normalized 5m and 1h bars in append-only captures",
                "path": str(REPO_ROOT / "data/raw/market_data/yfinance"),
                "caveat": "yfinance is rolling intraday history; current archive has stale-symbol and single-cutoff limitations.",
            },
            {
                "source_id": "hsi_benchmark",
                "status": "available",
                "grain": "synchronous ^HSI 5m/1h bars",
                "path": str(REPO_ROOT / "data/raw/market_data/yfinance"),
                "caveat": "abnormal returns are simple stock-minus-HSI returns, not a fitted market model.",
            },
            {
                "source_id": "hkex_pit_recovery_sidecar",
                "status": "available_with_isolation_contract",
                "grain": "one row per recovered legacy filing, summarized here",
                "path": str(REPO_ROOT / "outputs/hkex_pit_recovery_sidecar"),
                "caveat": "timestamp recovery proof only; recovered rows remain event-study ineligible until explicit downstream gates pass.",
            },
        ]
    )
    for frame in (events, robustness, stratified, gap_drift, native, conflicts, registry):
        frame.insert(0, "evaluation_scope", scope)
    datasets = {
        "coverage_summary": _records(coverage_summary),
        "direction_summary": _records(direction_summary),
        "pit_summary": _records(pit_summary),
        "pit_recovery_summary": _records(pit_recovery_summary),
        "cluster_summary": _records(cluster_summary),
        "stock_summary": _records(stock_summary),
        "stale_symbol_summary": _records(stale_symbol_summary),
        "directional_horizon_summary": _records(horizon_summary),
        "event_returns": _records(events),
        "event_robustness_summary": _records(robustness),
        "event_stratified_summary": _records(stratified),
        "event_gap_drift_summary": _records(gap_drift),
        "event_native_1h_sensitivity": _records(native),
        "event_direction_conflicts": _records(conflicts),
        "signal_registry": _records(registry),
        "source_health": _records(source_health),
    }
    generated_at = pd.Timestamp.now(tz="UTC").isoformat().replace("+00:00", "Z")
    candidate_scope = scope in {"candidate_exploratory", "candidate_pit_recovered"}
    archive_provenance = _archive_provenance(coverage)
    source_description = (
        "HKEX exploratory filing candidates joined to yfinance 5m/1h snapshot bars and synchronous ^HSI abnormal returns."
        if candidate_scope
        else "Canonical HKEX announcement events joined to yfinance 5m/1h bars and synchronous ^HSI abnormal returns."
    )
    sources = [
        {
            "id": "hkex_event_study",
            "label": "HKEX announcement event-study evidence",
            "path": str(input_dir),
            "query": {
                "engine": "read-only persisted event-study bundle",
                "description": source_description,
            },
        },
        {
            "id": "yfinance_intraday_archive",
            "label": "yfinance 5m/1h snapshot archive",
            "path": str(REPO_ROOT / "data/raw/market_data/yfinance"),
            "query": {
                "engine": "yfinance snapshot archive",
                "description": "Append-only normalized bars; archive audit and capture comparison remain the authority for freshness and independence.",
            },
        },
    ]
    manifest = {
        "version": "hkex_event_study_artifact.v1",
        "surface": "dashboard",
        "title": "HKEX Announcement Event Study — Research Evidence",
        "description": "Research-only event evidence for stock decision pages. It exposes PIT timing, cluster contamination, opening-gap/drift/total reaction, HSI abnormal returns and signal-gate limitations; it is not a registered trading signal.",
        "sector": "hk-equities-event-study-research",
        "generatedAt": generated_at,
        "metadata": {
            "evaluation_scope": scope,
            "input_bundle": str(input_dir),
            "archive_capture_id": coverage.get("archive_capture_id"),
            **archive_provenance,
            "archive_manifest_sha256": (coverage.get("archive_audit") or {}).get("manifest_sha256"),
            "data_source_mode": coverage.get("data_source_mode"),
            "candidate_archive_expansion_tickers": coverage.get("candidate_archive_expansion_tickers", []),
            "candidate_expansion_symbol_count": int(coverage.get("candidate_archive_expansion_ticker_count", 0)),
            "candidate_archive_unavailable_tickers": coverage.get("candidate_archive_unavailable_tickers", []),
        },
        "cards": [
            {
                "id": "event_coverage_card",
                "description": "Event and market-data coverage with the global registration gate shown explicitly.",
                "dataset": "coverage_summary",
                "sourceId": "hkex_event_study",
                "metrics": [
                    {"label": "Events", "field": "event_rows", "format": "number"},
                    {"label": "Covered events", "field": "covered_event_rows", "format": "number"},
                    {"label": "Pending next cutoff", "field": "pending_market_cutoff_event_rows", "format": "number"},
                    {"label": "Expanded candidate tickers", "field": "candidate_archive_expansion_ticker_count", "format": "number"},
                    {"label": "Candidate bars unavailable", "field": "candidate_archive_unavailable_ticker_count", "format": "number"},
                    {"label": "Bar-hole rows", "field": "bar_hole_event_rows", "format": "number"},
                    {"label": "5m return rows", "field": "event_return_coverage_5m", "format": "number"},
                    {"label": "30m return rows", "field": "event_return_coverage_30m", "format": "number"},
                    {"label": "1h return rows", "field": "event_return_coverage_1h", "format": "number"},
                    {"label": "Native 1h coverage", "field": "native_1h_return_coverage", "format": "number"},
                    {"label": "Signal gate", "field": "signal_gate_status", "format": "text"},
                ],
            },
            {
                "id": "directional_efficacy_card",
                "description": "Direction-signed 1h total abnormal-return efficacy; review and unknown rows are excluded.",
                "dataset": "coverage_summary",
                "sourceId": "hkex_event_study",
                "metrics": [
                    {"label": "Directional rows", "field": "directional_1h_rows", "format": "number"},
                    {"label": "Directional win rate", "field": "directional_1h_win_rate", "format": "percent"},
                    {"label": "Mean signed abnormal return", "field": "directional_1h_mean_signed_abnormal_return", "format": "percent"},
                    {"label": "Raw conflicts", "field": "raw_direction_conflict_rows", "format": "number"},
                    {"label": "Title overrides", "field": "direction_override_rows", "format": "number"},
                ],
            },
            {
                "id": "cluster_quality_card",
                "description": "Cluster contamination context for interpreting event reactions.",
                "dataset": "cluster_summary",
                "sourceId": "hkex_event_study",
                "metrics": [
                    {"label": "Clusters", "field": "event_clusters", "format": "number"},
                    {"label": "Multi-document clusters", "field": "multi_document_cluster_count", "format": "number"},
                    {"label": "Mixed-type rows", "field": "contaminated_type_cluster_rows", "format": "number"},
                ],
            },
        ],
        "charts": [
            {
                "id": "total_abnormal_return_by_horizon",
                "title": "Mean Total Abnormal Return by Horizon and Resolved Direction",
                "subtitle": "Descriptive, cluster-aware evidence; signal registration remains gated.",
                "type": "line",
                "dataset": "directional_horizon_summary",
                "sourceId": "hkex_event_study",
                "encodings": {
                    "x": {"field": "horizon", "type": "nominal", "label": "Horizon"},
                    "y": {"field": "mean_total_abnormal_return", "type": "quantitative", "label": "Mean total abnormal return"},
                    "color": {"field": "resolved_impact_direction", "type": "nominal", "label": "Resolved direction"},
                },
                "valueFormat": "percent",
                "layout": "full",
            },
            {
                "id": "directional_win_rate_by_horizon",
                "title": "Direction-Signed Win Rate by Horizon",
                "subtitle": "Only positive/negative resolved rows with valid HSI abnormal returns are included.",
                "type": "line",
                "dataset": "directional_horizon_summary",
                "sourceId": "hkex_event_study",
                "encodings": {
                    "x": {"field": "horizon", "type": "nominal", "label": "Horizon"},
                    "y": {"field": "total_directional_win_rate", "type": "quantitative", "label": "Direction-signed win rate"},
                    "color": {"field": "resolved_impact_direction", "type": "nominal", "label": "Resolved direction"},
                },
                "valueFormat": "percent",
                "layout": "full",
            },
        ],
        "tables": [
            {
                "id": "stock_summary_table",
                "title": "Per-Ticker Event Evidence Summary",
                "subtitle": "Use covered type-cluster rows for reaction comparisons; proxy timing and cluster contamination remain visible.",
                "dataset": "stock_summary",
                "sourceId": "hkex_event_study",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "ticker", "label": "Ticker", "type": "text"},
                    {"field": "event_rows", "label": "Events", "format": "number"},
                    {"field": "covered_event_rows", "label": "Covered", "format": "number"},
                    {"field": "pure_event_rows", "label": "Pure-event rows", "format": "number"},
                    {"field": "multi_document_rows", "label": "Multi-document rows", "format": "number"},
                    {"field": "directional_1h_win_rate", "label": "1h signed win rate", "format": "percent"},
                    {"field": "coverage_status", "label": "Coverage", "type": "text"},
                ],
            },
            {
                "id": "event_returns_table",
                "title": "Event-Level Return Decomposition",
                "subtitle": "PIT timestamps, resolved direction, cluster flags, opening gap, drift and total abnormal returns.",
                "dataset": "event_returns",
                "sourceId": "hkex_event_study",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "ticker", "label": "Ticker", "type": "text"},
                    {"field": "event_id", "label": "Event ID", "type": "text"},
                    {"field": "available_at", "label": "Available at", "type": "text"},
                    {"field": "availability_basis", "label": "PIT basis", "type": "text"},
                    {"field": "market_data_status", "label": "Market data", "type": "text"},
                    {"field": "data_gap_reason", "label": "Data-gap reason", "type": "text"},
                    {"field": "resolved_impact_direction", "label": "Resolved direction", "type": "text"},
                    {"field": "resolved_impact_direction_basis", "label": "Direction basis", "type": "text"},
                    {"field": "impact_direction_reconciled", "label": "Reconciled direction", "type": "text"},
                    {"field": "impact_direction_reconciliation_basis", "label": "Reconciliation basis", "type": "text"},
                    {"field": "cluster_co_occurring_types", "label": "Cluster types", "type": "text"},
                    {"field": "opening_gap_return", "label": "Opening gap", "format": "percent"},
                    {"field": "total_5m_abnormal_return", "label": "Total 5m abnormal", "format": "percent"},
                    {"field": "total_30m_abnormal_return", "label": "Total 30m abnormal", "format": "percent"},
                    {"field": "total_1h_abnormal_return", "label": "Total 1h abnormal", "format": "percent"},
                    {"field": "native_1h_abnormal_return", "label": "Native 1h sensitivity", "format": "percent"},
                    {"field": "bar_hole_horizons", "label": "Bar-hole horizons", "type": "text"},
                    {"field": "native_1h_status", "label": "Native 1h", "type": "text"},
                ],
            },
            {
                "id": "signal_registry_table",
                "title": "Research Signal Registry",
                "subtitle": "Readiness evidence only; registered_for_trading_signal is intentionally false.",
                "dataset": "signal_registry",
                "sourceId": "hkex_event_study",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "primary_event_type", "label": "Event type", "type": "text"},
                    {"field": "resolved_impact_direction", "label": "Resolved direction", "type": "text"},
                    {"field": "horizon", "label": "Horizon", "type": "text"},
                    {"field": "status", "label": "Status", "type": "text"},
                    {"field": "statistical_gates_passed", "label": "Statistical gates", "type": "text"},
                    {"field": "sample_tier", "label": "Sample tier", "type": "text"},
                    {"field": "pit_quality", "label": "PIT quality", "type": "text"},
                    {"field": "registered_for_trading_signal", "label": "Registered", "type": "text"},
                    {"field": "trading_execution_eligible", "label": "Execution eligible", "type": "text"},
                ],
            },
            {
                "id": "direction_conflicts_table",
                "title": "Direction Review Queue",
                "subtitle": "Active raw-versus-title contradictions only.",
                "dataset": "event_direction_conflicts",
                "sourceId": "hkex_event_study",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "ticker", "label": "Ticker", "type": "text"},
                    {"field": "event_id", "label": "Event ID", "type": "text"},
                    {"field": "impact_direction", "label": "Raw direction", "type": "text"},
                    {"field": "derived_impact_direction", "label": "Title direction", "type": "text"},
                    {"field": "resolved_impact_direction_basis", "label": "Review basis", "type": "text"},
                ],
            },
            {
                "id": "pit_summary_table",
                "title": "Point-in-Time Availability Summary",
                "subtitle": "Observed collection and source-timestamp proxy rows are deliberately separated.",
                "dataset": "pit_summary",
                "sourceId": "hkex_event_study",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "availability_basis", "label": "PIT basis", "type": "text"},
                    {"field": "event_rows", "label": "Events", "format": "number"},
                    {"field": "covered_event_rows", "label": "Covered", "format": "number"},
                    {"field": "median_source_delay_minutes", "label": "Median delay (min)", "format": "number"},
                    {"field": "pit_quality", "label": "Quality", "type": "text"},
                ],
            },
            {
                "id": "pit_recovery_table",
                "title": "PIT Timestamp Recovery Provenance",
                "subtitle": "Recovery proof only; these legacy rows remain event-study ineligible and are not trading signals.",
                "dataset": "pit_recovery_summary",
                "sourceId": "hkex_pit_recovery_sidecar",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "sidecar_status", "label": "Sidecar status", "type": "text"},
                    {"field": "recovered_legacy_rows", "label": "Recovered legacy rows", "format": "number"},
                    {"field": "official_datetime_verified_rows", "label": "Official time verified", "format": "number"},
                    {"field": "median_availability_delta_minutes", "label": "Proxy delta (min)", "format": "number"},
                    {"field": "event_study_eligible_rows", "label": "Event-study eligible", "format": "number"},
                    {"field": "isolation_status", "label": "Isolation", "type": "text"},
                ],
            },
            {
                "id": "stale_symbol_table",
                "title": "Stale yfinance Symbol Boundary",
                "subtitle": "Stale history remains visible and is never silently filled or treated as a trading signal.",
                "dataset": "stale_symbol_summary",
                "sourceId": "yfinance_intraday_archive",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "ticker", "label": "Ticker", "type": "text"},
                    {"field": "interval", "label": "Interval", "type": "text"},
                    {"field": "latest_bar_at", "label": "Latest bar", "type": "text"},
                    {"field": "reference_cutoff_at", "label": "Reference cutoff", "type": "text"},
                    {"field": "bar_lag_hours", "label": "Lag (hours)", "format": "number"},
                    {"field": "status", "label": "Status", "type": "text"},
                ],
            },
        ],
        "sources": sources,
        "blocks": [
            {"id": "kpi_grid", "type": "metric-strip", "cardIds": ["event_coverage_card", "directional_efficacy_card", "cluster_quality_card"]},
            {"id": "total_return_chart", "type": "chart", "chartId": "total_abnormal_return_by_horizon"},
            {"id": "directional_win_chart", "type": "chart", "chartId": "directional_win_rate_by_horizon"},
            {"id": "stock_summary", "type": "table", "tableId": "stock_summary_table"},
            {"id": "event_detail", "type": "table", "tableId": "event_returns_table"},
            {"id": "signal_registry", "type": "table", "tableId": "signal_registry_table"},
            {"id": "direction_review", "type": "table", "tableId": "direction_conflicts_table"},
            {"id": "pit_summary", "type": "table", "tableId": "pit_summary_table"},
            {"id": "pit_recovery", "type": "table", "tableId": "pit_recovery_table"},
            {"id": "stale_symbols", "type": "table", "tableId": "stale_symbol_table"},
        ],
    }
    artifact = {
        "surface": "dashboard",
        "manifest": manifest,
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": datasets,
        },
        "sources": sources,
        "package_info": {
            "snapshotId": f"hkex-event-study-{scope}",
            "dataAsOf": coverage_summary.iloc[0]["latest_market_cutoff_5m"],
            "researchOnly": True,
            "productionDatabaseModified": False,
            "postWriteAudit": audit,
        },
    }
    validate_artifact(artifact)
    output_path.write_text(json.dumps(_json_safe(artifact), ensure_ascii=False, indent=2), encoding="utf-8")
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a research-only HKEX event-study dashboard artifact")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--comparison-json", type=Path)
    args = parser.parse_args()
    artifact = build_artifact(args.input_dir, args.output, args.comparison_json)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "scope": artifact["snapshot"]["datasets"]["coverage_summary"][0]["evaluation_scope"],
                "dataset_count": len(artifact["snapshot"]["datasets"]),
                "status": artifact["snapshot"]["status"],
                "signal_gate_status": artifact["snapshot"]["datasets"]["coverage_summary"][0]["signal_gate_status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
