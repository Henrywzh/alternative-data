"""Reproducible SHKP project-universe and ownership-review runner.

The source module contains small fetch/parse/build contracts.  This module is
the orchestration layer that was missing from the checked-out CLI: it gives
those contracts one run id, persists every intermediate frame with lineage,
and keeps the ownership gate conservative.  A website match, vendor notice,
annual-report snapshot or grouped ``Group's Interest`` value can enrich the
review queue, but never sets ``ownership_attribution_ready`` by itself.
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .sources import land_planning, shkp, srpe
from .config import NORMALIZED_DIR
from .shkp_high_recall import (
    HIGH_RECALL_DATASET,
    HIGH_RECALL_OWNERSHIP_DATASET,
    build_shkp_high_recall_phase_candidates,
    enrich_indicative_ownership_with_high_recall,
    run_shkp_high_recall_phase_candidates,
)
from .storage import load_latest_normalized, save_normalized_dataset, save_raw_snapshot
from .sources.srpe_pdf import build_srpe_sales_signals


CORE_DATASETS = (
    "shkp_property_catalog",
    "srpe_development_index",
    "shkp_srpe_crosswalk",
    "shkp_pipeline_disclosures",
    "shkp_pipeline_srpe_crosswalk",
    "shkp_pipeline_project_registry",
    "shkp_annual_report_projects",
    "shkp_completed_properties",
    "shkp_annual_srpe_crosswalk",
    "shkp_annual_principal_subsidiaries",
    "shkp_annual_principal_subsidiary_crosswalk",
    "shkp_completion_schedule_projects",
    "shkp_completion_schedule_crosswalk",
    "shkp_completion_schedule_ownership_audit",
    "shkp_completion_schedule_ownership_evidence",
    "shkp_completion_schedule_reconciliation",
    "shkp_legal_ownership_observations",
    "shkp_ownership_coverage_audit",
    "shkp_phase_attribution_decisions",
    "shkp_phase_role_evidence",
    "shkp_ownership_evidence_timeline",
    "shkp_entity_ownership_crosswalk",
    "shkp_ownership_evidence_audit",
    "shkp_phase_evidence_quality_audit",
    "shkp_ownership_review_queue",
    "shkp_future_project_identity_evidence",
    "shkp_future_project_resolution_plan",
    "shkp_project_registry",
    "shkp_sales_ingestion_eligibility",
    "shkp_sales_ingestion_plan",
    "shkp_corporate_documents",
    "shkp_historical_annual_report_index",
    "shkp_project_site_vendor_facts",
    "shkp_project_site_vendor_crosswalk",
    "shkp_supporting_source_catalog",
    "shkp_land_planning_documents",
    "shkp_bd_crosswalk",
    "shkp_srpe_document_manifest",
)

CURRENT_MANIFEST_BACKFILL_DATASET = "shkp_current_srpe_document_manifest_backfill"
HISTORICAL_TRANSACTION_EVENT_DATASET = "shkp_historical_srpe_pilot_transaction_events"
HISTORICAL_MONTHLY_SIGNAL_DATASET = "shkp_historical_srpe_pilot_developer_monthly_signals"
HISTORICAL_DOCUMENT_AUDIT_DATASET = "shkp_historical_srpe_pilot_document_audit"
HISTORICAL_TRANSACTION_DATE_GAP_DATASET = "shkp_historical_srpe_transaction_date_gaps"

OPTIONAL_DATASETS = (
    "shkp_land_registry_evidence",
    # Derived from the full SRPE parent roster plus the latest available
    # evidence layers.  It is kept optional because a targeted lifecycle
    # refresh can legitimately use mixed source vintages while the core
    # ownership catalog remains gated on one coherent run.
    "shkp_historical_phase_roster",
    "shkp_historical_annual_report_projects",
    "shkp_historical_annual_srpe_crosswalk",
    "shkp_historical_srpe_document_manifest",
    "shkp_historical_phase_review_queue",
    "shkp_historical_transaction_quality_audit",
    "shkp_history_milestones",
    "shkp_history_milestone_identity_crosswalk",
    "shkp_historical_manifest_coverage_audit",
    "shkp_historical_phase_evidence_coverage",
    HISTORICAL_TRANSACTION_DATE_GAP_DATASET,
    "shkp_indicative_ownership_roster",
    HIGH_RECALL_DATASET,
    HIGH_RECALL_OWNERSHIP_DATASET,
    "shkp_bd_phase_permit_reconciliation",
    CURRENT_MANIFEST_BACKFILL_DATASET,
    # TPB/LandsD planning parsers are not wired into the live runner yet; the
    # current fetch is a source-document catalogue only. Keep this layer
    # visible as optional rather than letting an intentional empty frame make
    # an otherwise coherent catalog look current.
    "shkp_planning_evidence_crosswalk",
)

DERIVED_AUDIT_DATASETS = (
    "shkp_annual_srpe_crosswalk",
    "shkp_phase_attribution_decisions",
    "shkp_ownership_coverage_audit",
    "shkp_future_project_identity_evidence",
    "shkp_future_project_resolution_plan",
    "shkp_project_registry",
    "shkp_sales_ingestion_eligibility",
    "shkp_sales_ingestion_plan",
    "shkp_ownership_review_queue",
)

# These are intentionally refreshed outside the live SHKP catalog run.  The
# historical universe builder uses the latest non-empty SRPE index and annual
# report index as source inputs, so they may legitimately lack the catalog
# run id shared by the live derived layers.  Treat that condition as a visible
# warning, not as evidence that the ownership gate is usable.
ALLOWLISTED_UNSCOPED_CATALOG_INPUTS = frozenset({
    "srpe_development_index",
    "shkp_historical_annual_report_index",
})

# This is the bounded phase set used by the ownership audit.  It is not a
# claim that these are all SHKP phases; it is the explicit review boundary
# from the current pilot and makes accidental attribution promotion visible.
SHKP_PRIORITY_PHASE_IDS = (
    "9366", "11005", "9785", "10405", "11516", "11554", "11505",
    "11305", "11345", "9565", "10585", "7845", "8525",
)

# Manual IRIS acquisition is deliberately kept as a reviewed input plan.  It
# is not a scrape target: Land Registry's public search is ad-hoc/manual and
# the order plan records the package-level scope that must be checked before
# title evidence can be reconciled into a phase decision.
IRIS_ORDER_PLAN_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "asia-markets"
    / "REAL_ESTATE_SHKP_IRIS_ORDER_PLAN.csv"
)


def validate_shkp_iris_order_plan(
    path: Path = IRIS_ORDER_PLAN_PATH,
) -> dict[str, Any]:
    """Validate the manual IRIS package plan against the priority phase set.

    The validator is intentionally strict about coverage and duplicate package
    rows, but does not attempt to validate legal title facts.  The latter are
    supplied later through the optional manual IRIS import and a separately
    reviewed phase-attribution decision.
    """
    plan_path = Path(path)
    if not plan_path.is_file():
        raise FileNotFoundError(f"SHKP IRIS order plan not found: {plan_path}")
    frame = pd.read_csv(plan_path, dtype=str).fillna("")
    required = {
        "land_package",
        "srpe_development_ids",
        "base_full_search_fee_hkd",
        "document_copy_fee_hkd",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            "SHKP IRIS order plan is missing required columns: " + ", ".join(missing)
        )
    if frame.empty:
        raise ValueError("SHKP IRIS order plan contains no package rows")

    packages = frame["land_package"].astype(str).str.strip()
    if packages.eq("").any():
        raise ValueError("SHKP IRIS order plan contains a blank land_package")
    if packages.duplicated().any():
        duplicates = sorted(packages[packages.duplicated()].unique().tolist())
        raise ValueError(
            "SHKP IRIS order plan contains duplicate land_package rows: "
            + ", ".join(duplicates)
        )

    phase_ids: list[str] = []
    for package, raw_ids in zip(packages, frame["srpe_development_ids"].astype(str)):
        ids = [value.strip() for value in raw_ids.split("|") if value.strip()]
        if not ids:
            raise ValueError(f"IRIS order plan package {package!r} has no SRPE development ids")
        phase_ids.extend(ids)
    duplicates = sorted({value for value in phase_ids if phase_ids.count(value) > 1})
    if duplicates:
        raise ValueError(
            "SHKP IRIS order plan contains duplicate SRPE development ids: "
            + ", ".join(duplicates)
        )
    observed = set(phase_ids)
    expected = set(SHKP_PRIORITY_PHASE_IDS)
    missing_ids = sorted(expected - observed)
    unknown_ids = sorted(observed - expected)
    if missing_ids or unknown_ids:
        details = []
        if missing_ids:
            details.append("missing=" + ",".join(missing_ids))
        if unknown_ids:
            details.append("unknown=" + ",".join(unknown_ids))
        raise ValueError("SHKP IRIS order plan phase coverage mismatch (" + "; ".join(details) + ")")

    fees = pd.to_numeric(frame["base_full_search_fee_hkd"], errors="coerce")
    if fees.isna().any() or (fees <= 0).any():
        raise ValueError("SHKP IRIS order plan base_full_search_fee_hkd must be positive numeric values")
    document_fees = frame["document_copy_fee_hkd"].astype(str).str.strip()
    if document_fees.eq("").any():
        raise ValueError("SHKP IRIS order plan contains a blank document_copy_fee_hkd")
    return {
        "status": "valid",
        "path": str(plan_path),
        "rows": int(len(frame)),
        "phase_ids": sorted(observed),
        "priority_phase_count": len(expected),
        "covered_phase_count": len(observed),
        "coverage": "complete",
    }


def _load_or_build_phase_attribution_decisions(
    srpe_index: pd.DataFrame,
) -> pd.DataFrame:
    """Load reviewed decisions, or materialise explicit blocked placeholders.

    The decision layer is deliberately persisted even before the first IRIS
    or SPV/JV review.  An empty frame would make it unclear whether the layer
    was intentionally reviewed or simply omitted from a run.  Placeholders
    carry no ownership percentage or dates and therefore cannot satisfy the
    registry interval gate.
    """
    persisted = load_latest_normalized("shkp_phase_attribution_decisions")
    if not persisted.empty:
        try:
            # Re-run the importer contract on persisted rows.  A Parquet file
            # is an input boundary, not proof that an earlier writer supplied
            # valid provenance; failing closed here prevents a stale or
            # hand-edited approved row from bypassing the current gate rules.
            return shkp.build_shkp_phase_attribution_decisions(persisted)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "persisted SHKP phase-attribution decision layer failed validation; refusing refresh"
            ) from exc
    by_id = {
        str(row.get("development_id") or ""): row
        for row in srpe_index.to_dict("records")
        if str(row.get("development_id") or "").strip()
    }
    rows = []
    for development_id in SHKP_PRIORITY_PHASE_IDS:
        srpe_row = by_id.get(development_id, {})
        phase_label = " ".join(
            str(value).strip()
            for value in (srpe_row.get("development_name_en"), srpe_row.get("phase_name_en"), srpe_row.get("phase_no"))
            if value and str(value).strip()
        ) or None
        rows.append(
            {
                "decision_id": f"review:{development_id}:pending",
                "srpe_development_id": development_id,
                "phase_label": phase_label,
                "decision_status": "blocked_review",
                "phase_identity_status": "not_evaluated",
                "source_urls_json": "[]",
                "caveat": "No approved phase-specific ownership interval has been reviewed yet.",
            }
        )
    return shkp.build_shkp_phase_attribution_decisions(rows)


def _empty(columns: list[str] | tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def _load_all_non_empty_snapshots(dataset_name: str) -> pd.DataFrame:
    """Load every non-empty run for a backfill dataset during recovery/merge."""
    root = NORMALIZED_DIR / dataset_name
    frames: list[pd.DataFrame] = []
    parent_lineages: list[dict[str, Any]] = []
    if not root.is_dir():
        return pd.DataFrame()
    for path in sorted(root.glob(f"*/{dataset_name}.parquet")):
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        if not frame.empty:
            frames.append(frame)
            lineage_path = path.with_name("lineage.json")
            if lineage_path.exists():
                try:
                    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    lineage = None
                if isinstance(lineage, dict):
                    parent_lineages.append(lineage)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True).drop_duplicates().reset_index(drop=True)
    # DataFrame.attrs is not persisted in Parquet. Preserve a compact parent
    # lineage inventory on the merged input so the next append-only snapshot
    # can expose which immutable runs contributed its rows.  Keep the full
    # source/raw lists in the existing attrs contract; retain parent run ids and
    # created_at values as the audit anchor without duplicating whole rows.
    combined.attrs["source_lineages"] = [
        {
            "run_id": lineage.get("run_id"),
            "created_at": lineage.get("created_at"),
            "dataset_name": lineage.get("dataset_name", dataset_name),
        }
        for lineage in parent_lineages
        if lineage.get("run_id")
    ]
    combined.attrs["raw_snapshots"] = list(dict.fromkeys(
        str(value)
        for lineage in parent_lineages
        for value in (lineage.get("raw_snapshots") or ([lineage.get("raw_snapshot")] if lineage.get("raw_snapshot") else []))
        if value
    ))
    combined.attrs["source_urls"] = list(dict.fromkeys(
        str(value)
        for lineage in parent_lineages
        for value in (lineage.get("source_urls") or ([lineage.get("source_url")] if lineage.get("source_url") else []))
        if value
    ))
    combined.attrs["lineage_metadata"] = {
        "lineage_type": f"loaded_all_non_empty_{dataset_name}",
        "parent_lineage_count": len(parent_lineages),
        "parent_lineage_runs": [
            lineage.get("run_id") for lineage in parent_lineages if lineage.get("run_id")
        ],
    }
    return combined


def _read_snapshot_with_lineage(path: str | Path | None, lineage_path: str | Path | None = None) -> pd.DataFrame:
    """Read a run-scoped parquet and restore its sibling lineage attrs."""
    if not path:
        return pd.DataFrame()
    parquet_path = Path(path)
    try:
        frame = pd.read_parquet(parquet_path)
    except Exception:
        return pd.DataFrame()
    sidecar = Path(lineage_path) if lineage_path else parquet_path.with_name("lineage.json")
    if not sidecar.exists():
        return frame
    try:
        lineage = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return frame
    if not isinstance(lineage, dict):
        return frame
    frame.attrs["lineage_metadata"] = lineage
    frame.attrs["raw_snapshots"] = lineage.get("raw_snapshots") or (
        [lineage.get("raw_snapshot")] if lineage.get("raw_snapshot") else []
    )
    frame.attrs["source_urls"] = lineage.get("source_urls") or (
        [lineage.get("source_url")] if lineage.get("source_url") else []
    )
    frame.attrs["source_lineages"] = [{
        "run_id": lineage.get("run_id"),
        "created_at": lineage.get("created_at"),
        "dataset_name": lineage.get("dataset_name"),
    }]
    return frame


def _ordered_shkp_srpe_manifest_candidate_ids(
    *,
    shkp_crosswalk: pd.DataFrame,
    annual_srpe_crosswalk: pd.DataFrame,
    identity_evidence: pd.DataFrame,
    project_registry: pd.DataFrame,
) -> list[str]:
    """Return SRPE ids in evidence priority order for document discovery.

    The all-development index is a market universe, not an SHKP universe.
    The old runner took the first rows of ``project_registry`` and therefore
    queried arbitrary developments for the manifest.  Prefer direct SHKP
    listing candidates, then annual-report candidates and finally explicit
    future-identity evidence; use the full registry only as a last-resort
    fallback.  This controls discovery scope and never opens ownership
    attribution.
    """
    ranked: dict[str, tuple[int, int]] = {}
    sequence = 0

    def add(frame: pd.DataFrame | None, *, status_col: str, allowed: set[str], rank: int) -> None:
        nonlocal sequence
        if frame is None or frame.empty or "srpe_development_id" not in frame.columns:
            return
        for row in frame.to_dict("records"):
            phase_id = str(row.get("srpe_development_id") or "").strip()
            if not phase_id:
                continue
            status = str(row.get(status_col) or "").strip()
            if status not in allowed:
                continue
            current = ranked.get(phase_id)
            candidate = (rank, sequence)
            if current is None or candidate < current:
                ranked[phase_id] = candidate
            sequence += 1

    add(
        shkp_crosswalk,
        status_col="match_status",
        allowed={"matched"},
        rank=0,
    )
    add(
        shkp_crosswalk,
        status_col="match_status",
        allowed={"matched_needs_review"},
        rank=1,
    )
    add(
        annual_srpe_crosswalk,
        status_col="match_status",
        allowed={"matched_needs_review"},
        rank=2,
    )
    add(
        shkp_crosswalk,
        status_col="match_status",
        allowed={"ambiguous"},
        rank=3,
    )
    add(
        annual_srpe_crosswalk,
        status_col="match_status",
        allowed={"ambiguous"},
        rank=4,
    )
    # Future identity evidence already contains the official phase bridge;
    # its status is intentionally not used as a promotion decision here.
    if identity_evidence is not None and not identity_evidence.empty:
        for row in identity_evidence.to_dict("records"):
            phase_id = str(row.get("srpe_development_id") or "").strip()
            if not phase_id:
                continue
            current = ranked.get(phase_id)
            candidate = (5, sequence)
            if current is None or candidate < current:
                ranked[phase_id] = candidate
            sequence += 1

    if ranked:
        return [phase_id for phase_id, _ in sorted(ranked.items(), key=lambda item: item[1])]

    # A degraded/fallback path is still explicit and deterministic.  It is
    # better than silently returning no manifest, but callers should inspect
    # the candidate evidence before treating these rows as SHKP-related.
    if project_registry is not None and not project_registry.empty:
        return list(
            dict.fromkeys(
                str(value).strip()
                for value in project_registry.get("srpe_development_id", pd.Series(dtype="string")).dropna()
                if str(value).strip()
            )
        )
    return []


def _persist(
    frames: dict[str, pd.DataFrame],
    dataset_name: str,
    run_id: str,
    stored: dict[str, Any],
) -> None:
    frame = frames.get(dataset_name)
    if frame is None:
        frame = pd.DataFrame()
        frames[dataset_name] = frame
    # Empty frames are used for explicit ``--skip-*`` modes and can also be
    # returned by a degraded source.  Never publish them as the newest
    # normalized snapshot: doing so would make a skipped parser look like a
    # real zero-observation universe and erase the last usable data.
    if frame.empty:
        stored[dataset_name] = {
            "skipped": True,
            "records": 0,
            "reason": "empty frame not persisted; previous valid snapshot retained",
        }
        return
    attrs = dict(frame.attrs)
    lineage = attrs.get("lineage_metadata")
    if not isinstance(lineage, dict):
        lineage = {"lineage_type": "shkp_catalog_derived_frame"}
    lineage = {**lineage, "catalog_run_id": run_id}
    raw_snapshots = [str(value) for value in attrs.get("raw_snapshots", []) if value]
    source_urls = [str(value) for value in attrs.get("source_urls", []) if value]
    source_url = attrs.get("source_url")
    if source_url and not source_urls:
        source_urls = [str(source_url)]
    stored[dataset_name] = save_normalized_dataset(
        dataset_name,
        frame,
        run_id=run_id,
        raw_snapshot=str(attrs["raw_snapshot"]) if attrs.get("raw_snapshot") else None,
        raw_snapshots=raw_snapshots,
        source_url=str(source_url) if source_url else None,
        source_urls=source_urls,
        lineage_metadata=lineage,
    )


def _latest_lineage(dataset_name: str) -> dict[str, Any]:
    """Read lineage beside the same latest dataset directory as the loader."""
    dataset_dir = NORMALIZED_DIR / dataset_name
    if not dataset_dir.is_dir():
        return {}
    run_dirs = [directory for directory in dataset_dir.iterdir() if directory.is_dir()]
    if not run_dirs:
        return {}
    # Keep this resolver aligned with ``load_latest_normalized``: lineage
    # ``created_at`` is authoritative, with mtime/name as deterministic
    # fallbacks.  Sorting by mtime alone can audit a different immutable run
    # than the one the data loader actually returns.
    def _sort_key(directory: Path) -> tuple[float, float, str]:
        created_at = ""
        lineage_path = directory / "lineage.json"
        if lineage_path.exists():
            try:
                created_at = str(
                    json.loads(lineage_path.read_text(encoding="utf-8")).get("created_at") or ""
                )
            except (OSError, json.JSONDecodeError, TypeError):
                created_at = ""
        try:
            created_epoch = (
                datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
                if created_at
                else 0.0
            )
        except (TypeError, ValueError, OverflowError):
            created_epoch = 0.0
        return (created_epoch, directory.stat().st_mtime, directory.name)

    # Keep this resolver aligned with ``load_latest_normalized``: a newer
    # empty/parquet-less run must not contribute a lineage identity for an
    # older non-empty snapshot that the loader actually returns.
    for latest in sorted(run_dirs, key=_sort_key, reverse=True):
        parquet_path = latest / f"{dataset_name}.parquet"
        if not parquet_path.is_file():
            continue
        lineage_path = latest / "lineage.json"
        if not lineage_path.is_file():
            return {"run_id": latest.name, "lineage_file_missing": True}
        try:
            lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"run_id": latest.name, "lineage_file_invalid": True}
        records = lineage.get("records")
        try:
            if records is not None and int(records) <= 0:
                continue
        except (TypeError, ValueError):
            # If an older lineage has no usable record count, let the parquet
            # itself decide whether the snapshot is usable.
            pass
        if records is None:
            try:
                if len(pd.read_parquet(parquet_path, columns=[])) == 0:
                    continue
            except (OSError, ValueError, ImportError):
                return {"run_id": latest.name, "lineage_file_invalid": True}
        return lineage
    return {}


def _audit_derived_snapshot_consistency() -> dict[str, Any]:
    """Audit whether derived layers share one catalog run identity."""
    return _audit_snapshot_consistency(DERIVED_AUDIT_DATASETS, label="derived")


def _audit_snapshot_consistency(
    dataset_names: tuple[str, ...] | list[str],
    *,
    label: str = "catalog",
) -> dict[str, Any]:
    """Audit run identity for a set of normalized snapshots.

    ``load_latest_normalized`` resolves each dataset independently.  That is
    useful for source fallbacks, but it can silently assemble an offline
    catalog from unrelated refreshes.  Every live catalog write adds a
    ``catalog_run_id`` to lineage; missing values therefore remain visible as
    ``unscoped`` instead of being treated as coherent just because the
    directory names happen to match.
    """
    names = tuple(dict.fromkeys(str(name) for name in dataset_names))
    lineages = {name: _latest_lineage(name) for name in names}
    missing = [name for name, lineage in lineages.items() if not lineage]
    unscoped = [
        name
        for name, lineage in lineages.items()
        if lineage and not lineage.get("catalog_run_id")
    ]
    run_ids = sorted({
        str(lineage.get("catalog_run_id"))
        for lineage in lineages.values()
        if lineage.get("catalog_run_id")
    })
    if missing:
        status = "incomplete"
    elif len(run_ids) != 1:
        status = "mixed_catalog_runs"
    elif unscoped:
        status = f"unscoped_{label}_snapshots"
    else:
        status = "consistent"
    return {
        "status": status,
        "scope": label,
        "catalog_run_ids": run_ids,
        "missing_datasets": missing,
        "unscoped_datasets": unscoped,
        "dataset_lineage": {
            name: {
                "catalog_run_id": lineage.get("catalog_run_id"),
                "run_id": lineage.get("run_id"),
                "records": lineage.get("records"),
            }
            for name, lineage in lineages.items()
            if lineage
        },
    }


def _offline_summary() -> dict[str, Any]:
    iris_order_plan = validate_shkp_iris_order_plan()
    frames = {
        name: load_latest_normalized(name)
        for name in (*CORE_DATASETS, *OPTIONAL_DATASETS)
    }
    snapshot_consistency = _audit_snapshot_consistency(CORE_DATASETS, label="catalog")
    missing = [name for name in CORE_DATASETS if frames[name].empty]
    legal = frames.get("shkp_legal_ownership_observations", pd.DataFrame())
    ready = (
        legal.get("promotion_status", pd.Series(dtype="string"))
        .astype("string")
        .eq("approved")
        .sum()
        if not legal.empty
        else 0
    )
    registry = frames.get("shkp_project_registry", pd.DataFrame())
    coverage = frames.get("shkp_ownership_coverage_audit", pd.DataFrame())
    priority = registry.loc[
        registry.get("srpe_development_id", pd.Series(dtype="string")).astype("string").isin(SHKP_PRIORITY_PHASE_IDS)
    ] if not registry.empty else pd.DataFrame()
    diagnostic_gate = {
        "ownership_observation_rows": int(len(legal)),
        "ownership_ready_observation_rows": int(ready),
        "attribution_decision_rows": int(
            len(frames.get("shkp_phase_attribution_decisions", pd.DataFrame()))
        ),
        "approved_attribution_decision_rows": int(
            frames.get("shkp_phase_attribution_decisions", pd.DataFrame())
            .get("ownership_attribution_ready", pd.Series(dtype=bool))
            .fillna(False)
            .astype(bool)
            .sum()
        ),
        "priority_phase_count": int(len(priority)),
        "priority_phase_ready_count": int(
            priority.get("ownership_attribution_ready", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()
        ),
        "ownership_coverage_rows": int(len(coverage)),
        "ownership_coverage_status_counts": (
            coverage.get("coverage_status", pd.Series(dtype="string")).value_counts().to_dict()
            if not coverage.empty
            else {}
        ),
        "priority_phase_gate": {
            str(row.get("srpe_development_id")): {
                "ownership_status": row.get("ownership_status"),
                "ownership_attribution_ready": bool(row.get("ownership_attribution_ready")),
            }
            for row in priority.to_dict("records")
        },
    }
    unscoped_inputs_only = (
        snapshot_consistency["status"] == "unscoped_catalog_snapshots"
        and set(snapshot_consistency.get("unscoped_datasets", []))
        <= set(ALLOWLISTED_UNSCOPED_CATALOG_INPUTS)
    )
    gate_usable = snapshot_consistency["status"] == "consistent" or unscoped_inputs_only
    gate_status = (
        "usable"
        if snapshot_consistency["status"] == "consistent"
        else "usable_with_unscoped_source_inputs"
        if unscoped_inputs_only
        else "blocked_snapshot_incoherent"
    )
    return {
        "mode": "offline",
        "dataset_counts": {name: int(len(frame)) for name, frame in frames.items()},
        "missing_datasets": missing,
        "optional_missing_datasets": [
            name for name in OPTIONAL_DATASETS if frames[name].empty
        ],
        # The old derived-only check remains available for diagnostics, but
        # the public snapshot_consistency gate now covers every required
        # catalog layer.  Optional IRIS evidence is a separately acquired
        # manual input and is audited independently rather than mixed into the
        # live catalog run identity.
        "snapshot_consistency": snapshot_consistency,
        "derived_snapshot_consistency": _audit_derived_snapshot_consistency(),
        "optional_snapshot_consistency": _audit_snapshot_consistency(
            OPTIONAL_DATASETS,
            label="optional",
        ),
        "iris_order_plan": iris_order_plan,
        # Never present a cross-layer ownership gate as usable when the
        # offline loader assembled inputs from different catalog runs.  The
        # raw counts remain available under diagnostic_gate for reconciliation
        # and refresh planning, but callers must inspect gate_status first.
        "gate_status": gate_status,
        "ownership_observation_rows": int(len(legal)) if gate_usable else None,
        "ownership_ready_observation_rows": int(ready) if gate_usable else None,
        "attribution_decision_rows": diagnostic_gate["attribution_decision_rows"] if gate_usable else None,
        "approved_attribution_decision_rows": diagnostic_gate["approved_attribution_decision_rows"] if gate_usable else None,
        "priority_phase_count": diagnostic_gate["priority_phase_count"] if gate_usable else None,
        "priority_phase_ready_count": diagnostic_gate["priority_phase_ready_count"] if gate_usable else None,
        "ownership_coverage_rows": diagnostic_gate["ownership_coverage_rows"] if gate_usable else None,
        "ownership_coverage_status_counts": diagnostic_gate["ownership_coverage_status_counts"] if gate_usable else {},
        "priority_phase_gate": diagnostic_gate["priority_phase_gate"] if gate_usable else {},
        "diagnostic_gate": diagnostic_gate if not gate_usable else None,
        "attribution_policy": "phase-specific effective interval required; snapshots/JV/grouped interest do not promote",
    }


def build_shkp_historical_phase_roster(
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Persist a discovery-only roster from the full SRPE parent universe.

    This deliberately reuses ``build_shkp_project_registry`` so the existing
    ownership gate and evidence-layer semantics remain unchanged.  The
    result is a separate optional dataset because targeted SRPE lifecycle
    refreshes can be newer than the last coherent full catalog run.
    """
    run_id = run_id or f"shkp-historical-roster-{uuid.uuid4()}"
    frames = {
        "srpe_development_index": load_latest_normalized("srpe_development_index"),
        "shkp_srpe_crosswalk": load_latest_normalized("shkp_srpe_crosswalk"),
        # The current/live manifest is a separate source layer from the
        # historical inactive-phase backfill.  Pass it into the registry so
        # the parent roster exposes filing availability for current pilot
        # phases instead of reporting every row as ``not_loaded``.
        "shkp_srpe_document_manifest": load_latest_normalized("shkp_srpe_document_manifest"),
        CURRENT_MANIFEST_BACKFILL_DATASET: load_latest_normalized(CURRENT_MANIFEST_BACKFILL_DATASET),
        "shkp_annual_srpe_crosswalk": load_latest_normalized("shkp_annual_srpe_crosswalk"),
        "shkp_historical_annual_report_projects": load_latest_normalized("shkp_historical_annual_report_projects"),
        "shkp_pipeline_srpe_crosswalk": load_latest_normalized("shkp_pipeline_srpe_crosswalk"),
        "shkp_completion_schedule_crosswalk": load_latest_normalized("shkp_completion_schedule_crosswalk"),
        "shkp_project_site_vendor_crosswalk": load_latest_normalized("shkp_project_site_vendor_crosswalk"),
        "shkp_legal_ownership_observations": load_latest_normalized("shkp_legal_ownership_observations"),
        "shkp_phase_attribution_decisions": load_latest_normalized("shkp_phase_attribution_decisions"),
        "shkp_history_milestones": load_latest_normalized("shkp_history_milestones"),
    }


    index = frames["srpe_development_index"]
    if index.empty:
        raise RuntimeError("cannot build SHKP historical phase roster without SRPE development index")
    current_manifest_backfill = frames[CURRENT_MANIFEST_BACKFILL_DATASET]
    if not current_manifest_backfill.empty:
        current_manifest_frames = [
            frame for frame in (frames["shkp_srpe_document_manifest"], current_manifest_backfill)
            if not frame.empty
        ]
        merged_current_manifest = pd.concat(current_manifest_frames, ignore_index=True)
        merged_current_manifest = merged_current_manifest.drop_duplicates(
            subset=["srpe_development_id", "document_category", "document_id", "file_name"],
            keep="last",
        ).reset_index(drop=True)
        merged_current_manifest.attrs.update(
            source_urls=list(dict.fromkeys(
                str(value)
                for frame in (frames["shkp_srpe_document_manifest"], current_manifest_backfill)
                for value in frame.attrs.get("source_urls", [])
                if value
            )),
            raw_snapshots=list(dict.fromkeys(
                str(value)
                for frame in (frames["shkp_srpe_document_manifest"], current_manifest_backfill)
                for value in frame.attrs.get("raw_snapshots", [])
                if value
            )),
        )
        frames["shkp_srpe_document_manifest"] = merged_current_manifest
    history_milestones = frames["shkp_history_milestones"]
    history_crosswalk = shkp.build_shkp_history_milestone_crosswalk(
        history_milestones,
        index,
    )
    historical_annual = frames["shkp_historical_annual_report_projects"]
    if not historical_annual.empty:
        historical_crosswalk = shkp.build_shkp_annual_srpe_crosswalk(
            historical_annual,
            index,
        )
        existing_annual = frames["shkp_annual_srpe_crosswalk"]
        # Building from records avoids pandas' empty/all-NA concat dtype
        # warning while preserving the union of columns from old and
        # historical crosswalk vintages.
        annual_records = []
        for frame in (existing_annual, historical_crosswalk):
            if not frame.empty:
                annual_records.extend(frame.to_dict("records"))
        frames["shkp_annual_srpe_crosswalk"] = pd.DataFrame(annual_records)
        if not frames["shkp_annual_srpe_crosswalk"].empty:
            frames["shkp_annual_srpe_crosswalk"] = frames["shkp_annual_srpe_crosswalk"].drop_duplicates(
                subset=[
                    column
                    for column in ("report_id", "evidence_type", "project_label", "srpe_development_id")
                    if column in frames["shkp_annual_srpe_crosswalk"].columns
                ],
                keep="last",
            ).reset_index(drop=True)
    roster = shkp.build_shkp_project_registry(
        index,
        shkp_crosswalk=frames["shkp_srpe_crosswalk"],
        srpe_manifest=frames["shkp_srpe_document_manifest"],
        annual_srpe_crosswalk=frames["shkp_annual_srpe_crosswalk"],
        pipeline_crosswalk=frames["shkp_pipeline_srpe_crosswalk"],
        completion_schedule_crosswalk=frames["shkp_completion_schedule_crosswalk"],
        legal_ownership_observations=frames["shkp_legal_ownership_observations"],
        phase_attribution_decisions=frames["shkp_phase_attribution_decisions"],
        history_milestone_crosswalk=history_crosswalk,
    )
    # Materialise the historical manifest audit before saving the roster so
    # callers do not have to join a second dataset just to learn whether a
    # phase was probed.  Keep the generic live ``manifest_status`` untouched;
    # the helper writes explicit ``historical_*`` fields.
    historical_manifest = load_latest_normalized("shkp_historical_srpe_document_manifest")
    manifest_coverage_audit = shkp.build_shkp_historical_manifest_coverage_audit(
        roster,
        historical_manifest,
    )
    roster = shkp.enrich_shkp_historical_phase_roster_manifest_coverage(
        roster,
        manifest_coverage_audit,
    )
    source_urls = [
        str(value)
        for value in index.get("source_url", pd.Series(dtype="string")).dropna().unique()
        if str(value).strip()
    ]
    if not historical_annual.empty and "document_url" in historical_annual.columns:
        source_urls.extend(
            str(value)
            for value in historical_annual["document_url"].dropna().unique()
            if str(value).strip() and str(value) not in source_urls
        )
    current_manifest = frames["shkp_srpe_document_manifest"]
    if not current_manifest.empty:
        source_urls.extend(
            str(value)
            for value in current_manifest.attrs.get("source_urls", [])
            if str(value).strip() and str(value) not in source_urls
        )
        source_urls.extend(
            str(value)
            for value in current_manifest.get("source_url", pd.Series(dtype="string")).dropna().unique()
            if str(value).strip() and str(value) not in source_urls
        )
    normalized = save_normalized_dataset(
        "shkp_historical_phase_roster",
        roster,
        run_id=run_id,
        source_urls=source_urls,
        lineage_metadata={
            "lineage_type": "derived_shkp_historical_phase_roster",
            "parent_dataset": "srpe_development_index",
            "parent_rows": int(len(index)),
            "source_datasets": sorted(frames),
            "source_vintage_policy": "latest_non_empty_snapshot_per_input; may be mixed and remains discovery-only",
            "ownership_promotion": False,
        },
    )
    history_crosswalk_normalized = None
    if not history_crosswalk.empty:
        history_crosswalk_normalized = save_normalized_dataset(
            "shkp_history_milestone_identity_crosswalk",
            history_crosswalk,
            run_id=run_id,
            source_urls=list(history_crosswalk.attrs.get("source_urls", [])),
            lineage_metadata={
                **(history_crosswalk.attrs.get("lineage_metadata") or {}),
                "parent_datasets": ["shkp_history_milestones", "srpe_development_index"],
                "ownership_promotion": False,
                "sales_promotion": False,
            },
        )
    historical_crosswalk_normalized = None
    if not historical_annual.empty and not historical_crosswalk.empty:
        historical_crosswalk_normalized = save_normalized_dataset(
            "shkp_historical_annual_srpe_crosswalk",
            historical_crosswalk,
            run_id=run_id,
            source_urls=source_urls,
            lineage_metadata={
                "lineage_type": "derived_shkp_historical_annual_to_srpe_crosswalk",
                "parent_dataset": "shkp_historical_annual_report_projects",
                "historical_rows": int(len(historical_crosswalk)),
                "ownership_promotion": False,
            },
        )
    manifest_coverage_audit_normalized = None
    if not manifest_coverage_audit.empty:
        manifest_coverage_audit_normalized = save_normalized_dataset(
            "shkp_historical_manifest_coverage_audit",
            manifest_coverage_audit,
            run_id=run_id,
            source_urls=list(historical_manifest.attrs.get("source_urls", [])),
            lineage_metadata={
                **(manifest_coverage_audit.attrs.get("lineage_metadata") or {}),
                "parent_roster_run_id": run_id,
            },
        )
    phase_evidence_coverage = shkp.build_shkp_historical_phase_evidence_coverage(roster)
    phase_evidence_coverage_normalized = save_normalized_dataset(
        "shkp_historical_phase_evidence_coverage",
        phase_evidence_coverage,
        run_id=run_id,
        source_urls=source_urls,
        lineage_metadata={
            **(phase_evidence_coverage.attrs.get("lineage_metadata") or {}),
            "parent_roster_run_id": run_id,
        },
    )
    indicative_ownership = shkp.build_shkp_indicative_ownership_roster(roster)
    high_recall_candidates = build_shkp_high_recall_phase_candidates(
        index,
        property_catalog=load_latest_normalized("shkp_property_catalog"),
        current_crosswalk=frames["shkp_srpe_crosswalk"],
        annual_crosswalk=frames["shkp_annual_srpe_crosswalk"],
        historical_annual_crosswalk=historical_crosswalk,
        history_crosswalk=history_crosswalk,
        pipeline_crosswalk=frames["shkp_pipeline_srpe_crosswalk"],
        completion_crosswalk=frames["shkp_completion_schedule_crosswalk"],
        site_vendor_crosswalk=frames["shkp_project_site_vendor_crosswalk"],
        manifest=frames["shkp_srpe_document_manifest"],
    )
    indicative_ownership = enrich_indicative_ownership_with_high_recall(
        indicative_ownership,
        high_recall_candidates,
    )
    indicative_ownership_normalized = save_normalized_dataset(
        "shkp_indicative_ownership_roster",
        indicative_ownership,
        run_id=run_id,
        source_urls=source_urls,
        lineage_metadata={
            **(indicative_ownership.attrs.get("lineage_metadata") or {}),
            "parent_roster_run_id": run_id,
        },
    )
    high_recall_normalized = save_normalized_dataset(
        HIGH_RECALL_DATASET,
        high_recall_candidates,
        run_id=run_id,
        source_urls=[
            "https://www.shkp.com/en-US/our-business/hong-kong-properties",
            "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale",
            "https://www.srpe.gov.hk/opip/all_development",
        ],
        lineage_metadata={
            **(high_recall_candidates.attrs.get("lineage_metadata") or {}),
            "parent_roster_run_id": run_id,
        },
    )
    high_recall_ownership_normalized = save_normalized_dataset(
        HIGH_RECALL_OWNERSHIP_DATASET,
        indicative_ownership,
        run_id=run_id,
        source_urls=[
            "https://www.shkp.com/en-US/our-business/hong-kong-properties",
            "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale",
            "https://www.srpe.gov.hk/opip/all_development",
        ],
        lineage_metadata={
            "lineage_type": "derived_shkp_high_recall_ownership_review",
            "parent_datasets": ["shkp_indicative_ownership_roster", HIGH_RECALL_DATASET],
            "parent_roster_run_id": run_id,
            "ownership_promotion": False,
            "sales_promotion": False,
        },
    )
    historical_review_queue_normalized = None
    historical_review_queue = shkp.build_shkp_historical_phase_review_queue(
        historical_crosswalk if not historical_annual.empty else pd.DataFrame(),
        roster,
        historical_manifest,
    )
    if not historical_review_queue.empty:
        historical_review_queue_normalized = save_normalized_dataset(
            "shkp_historical_phase_review_queue",
            historical_review_queue,
            run_id=run_id,
            source_urls=source_urls,
            lineage_metadata={
                "lineage_type": "derived_shkp_historical_phase_identity_review_queue",
                "parent_datasets": [
                    "shkp_historical_annual_srpe_crosswalk",
                    "shkp_historical_phase_roster",
                    "shkp_historical_srpe_document_manifest",
                ],
                "ownership_promotion": False,
                "sales_promotion": False,
            },
        )
    return {
        "run_id": run_id,
        "normalized": normalized,
        "historical_crosswalk_normalized": historical_crosswalk_normalized,
        "history_milestone_crosswalk_normalized": history_crosswalk_normalized,
        "manifest_coverage_audit_normalized": manifest_coverage_audit_normalized,
        "phase_evidence_coverage_normalized": phase_evidence_coverage_normalized,
        "indicative_ownership_normalized": indicative_ownership_normalized,
        "high_recall_normalized": high_recall_normalized,
        "high_recall_ownership_normalized": high_recall_ownership_normalized,
        "historical_review_queue_normalized": historical_review_queue_normalized,
        "records": int(len(roster)),
        "high_recall_status_counts": high_recall_candidates["candidate_status"].value_counts().to_dict(),
        "high_recall_route_counts": high_recall_candidates["transaction_route_status"].value_counts().to_dict(),
        "historical_review_queue_rows": int(len(historical_review_queue)),
        "history_milestone_crosswalk_rows": int(len(history_crosswalk)),
        "history_milestone_match_status_counts": history_crosswalk.get("match_status", pd.Series(dtype="string")).value_counts().to_dict(),
        "manifest_coverage_status_counts": manifest_coverage_audit.get("manifest_status", pd.Series(dtype="string")).value_counts().to_dict(),
        "universe_status_counts": roster.get("universe_status", pd.Series(dtype="string")).value_counts().to_dict(),
        "ownership_ready_rows": int(roster.get("ownership_attribution_ready", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()),
        "source_vintage_policy": "latest_non_empty_snapshot_per_input; discovery-only",
    }


def run_shkp_historical_phase_manifest_backfill(
    *,
    max_developments: int = 25,
    timeout: float = 30,
    include_unobserved: bool = False,
) -> dict[str, Any]:
    """Fetch SRPE document manifests for inactive phases with SHKP evidence.

    The selection is discovery-only: an inactive SRPE phase is retained when
    the historical roster has annual-report evidence, and its official
    transaction/price/sales-arrangement manifest is fetched without asserting
    that SHKP owned the phase. PDF binaries are intentionally not downloaded
    here; the manifest is the stable hand-off for a later transaction parser.
    """
    if max_developments <= 0:
        raise ValueError("max_developments must be positive")
    roster = load_latest_normalized("shkp_historical_phase_roster")
    if roster.empty:
        raise RuntimeError("historical phase roster is missing; run build-shkp-historical-roster first")
    inactive = roster.get("active", pd.Series(dtype="string")).astype("string").str.upper().eq("N")
    historical_evidence = roster.get("evidence_count", pd.Series(dtype=float)).fillna(0).astype(float).gt(0)
    selected = roster.loc[inactive & (historical_evidence | include_unobserved)].copy()
    selected = selected.sort_values(
        ["srpe_date_complete_sales", "srpe_date_suspend_sales", "srpe_earliest_publication", "srpe_development_id"],
        na_position="first",
    )
    existing_manifest = load_latest_normalized("shkp_historical_srpe_document_manifest")
    existing_ids = (
        set(existing_manifest.get("srpe_development_id", pd.Series(dtype="string")).dropna().astype(str))
        if not existing_manifest.empty
        else set()
    )
    ids = [
        phase_id
        for phase_id in selected["srpe_development_id"].dropna().astype(str).drop_duplicates().tolist()
        if phase_id not in existing_ids
    ]
    ids = ids[:max_developments]
    if not ids:
        scope = "inactive SRPE phases" if include_unobserved else "inactive SRPE phases with historical SHKP evidence"
        raise RuntimeError(f"no new {scope} were found")
    new_manifest = shkp.fetch_shkp_srpe_document_manifest(ids, timeout=timeout, max_developments=len(ids))
    if existing_manifest.empty:
        manifest = new_manifest
    else:
        manifest = pd.concat([existing_manifest, new_manifest], ignore_index=True)
        manifest = manifest.drop_duplicates(subset=["srpe_development_id", "document_id"]).reset_index(drop=True)
        manifest.attrs.update(
            raw_snapshots=list(existing_manifest.attrs.get("raw_snapshots", [])) + list(new_manifest.attrs.get("raw_snapshots", [])),
            source_urls=list(dict.fromkeys(
                list(existing_manifest.attrs.get("source_urls", [])) + list(new_manifest.attrs.get("source_urls", []))
            )),
            lineage_metadata={
                **(new_manifest.attrs.get("lineage_metadata") or {}),
                "merged_prior_manifest": True,
                "prior_manifest_phase_count": len(existing_ids),
            },
        )
    run_id = f"shkp-historical-manifest-{uuid.uuid4()}"
    normalized = save_normalized_dataset(
        "shkp_historical_srpe_document_manifest",
        manifest,
        run_id=run_id,
        raw_snapshots=list(manifest.attrs.get("raw_snapshots", [])),
        source_urls=list(manifest.attrs.get("source_urls", [])),
        lineage_metadata={
            **(manifest.attrs.get("lineage_metadata") or {}),
            "lineage_type": "official_srpe_inactive_phase_manifest_backfill",
            "selected_inactive_phase_ids": ids,
            "manifest_phase_ids": sorted(set(manifest.get("srpe_development_id", pd.Series(dtype="string")).dropna().astype(str))),
            "selection_policy": "active=N and (historical roster evidence_count>0 or include_unobserved=True)",
            "include_unobserved": include_unobserved,
            "pdf_downloaded": False,
            "ownership_inference": False,
        },
    )
    coverage_audit = shkp.build_shkp_historical_manifest_coverage_audit(roster, manifest)
    coverage_audit_normalized = save_normalized_dataset(
        "shkp_historical_manifest_coverage_audit",
        coverage_audit,
        run_id=run_id,
        source_urls=list(manifest.attrs.get("source_urls", [])),
        lineage_metadata={
            **(coverage_audit.attrs.get("lineage_metadata") or {}),
            "manifest_run_id": run_id,
            "selected_inactive_phase_ids": ids,
        },
    )
    return {
        "run_id": run_id,
        "selected_developments": len(ids),
        "selected_phase_ids": ids,
        "manifest_rows": int(len(manifest)),
        "new_manifest_rows": int(len(new_manifest)),
        "manifest_category_counts": manifest.get("document_category", pd.Series(dtype="string")).value_counts().to_dict(),
        "skipped_items": manifest.attrs.get("skipped_documents", []),
        "normalized": normalized,
        "coverage_audit_normalized": coverage_audit_normalized,
        "coverage_status_counts": coverage_audit.get("manifest_status", pd.Series(dtype="string")).value_counts().to_dict(),
        "pdf_downloaded": False,
        "ownership_inference": False,
    }


def run_shkp_current_manifest_backfill(
    *,
    max_developments: int = 25,
    timeout: float = 30,
) -> dict[str, Any]:
    """Append official SRPE filing metadata for current SHKP directory candidates.

    The live catalog's ``shkp_srpe_document_manifest`` is intentionally tied
    to one coherent catalog run.  This targeted refresh therefore writes a
    separate append-only dataset instead of mutating that run or fabricating
    its ``catalog_run_id``.  The historical roster unions both layers when it
    is rebuilt.  Ambiguous current-directory crosswalks are retained as
    routing candidates only; no ownership or sales eligibility is inferred.
    """
    if max_developments <= 0:
        raise ValueError("max_developments must be positive")
    crosswalk = load_latest_normalized("shkp_srpe_crosswalk")
    if crosswalk.empty or "srpe_development_id" not in crosswalk.columns:
        raise RuntimeError("current SHKP/SRPE crosswalk is missing; run the SHKP catalog first")
    allowed_statuses = {"matched", "matched_needs_review", "ambiguous"}
    candidates = crosswalk.loc[
        crosswalk.get("match_status", pd.Series(dtype="string")).astype("string").isin(allowed_statuses)
    ]
    candidate_ids = [
        str(value).strip()
        for value in candidates["srpe_development_id"].dropna().astype(str).drop_duplicates()
        if str(value).strip()
    ]
    prior = _load_all_non_empty_snapshots(CURRENT_MANIFEST_BACKFILL_DATASET)
    base = load_latest_normalized("shkp_srpe_document_manifest")
    existing = set(prior.get("srpe_development_id", pd.Series(dtype="string")).dropna().astype(str))
    existing |= set(base.get("srpe_development_id", pd.Series(dtype="string")).dropna().astype(str))
    pending_ids = [value for value in candidate_ids if value not in existing]
    selected_ids = pending_ids[:max_developments]
    if not selected_ids:
        raise RuntimeError("no new current SHKP directory candidate phases require a manifest refresh")

    new_manifest = shkp.fetch_shkp_srpe_document_manifest(
        selected_ids,
        timeout=timeout,
        max_developments=len(selected_ids),
    )
    frames = [frame for frame in (prior, new_manifest) if frame is not None and not frame.empty]
    merged = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=shkp.SHKP_SRPE_MANIFEST_COLUMNS)
    if not merged.empty:
        merged = merged.drop_duplicates(
            subset=["srpe_development_id", "document_category", "document_id", "file_name"],
            keep="last",
        ).reset_index(drop=True)
    run_id = f"shkp-current-manifest-{uuid.uuid4()}"
    raw_snapshots = list(dict.fromkeys(
        str(value)
        for frame in (prior, new_manifest)
        for value in frame.attrs.get("raw_snapshots", [])
        if value
    ))
    source_urls = list(dict.fromkeys(
        str(value)
        for frame in (prior, new_manifest)
        for value in frame.attrs.get("source_urls", [])
        if value
    ))
    normalized = save_normalized_dataset(
        CURRENT_MANIFEST_BACKFILL_DATASET,
        merged,
        run_id=run_id,
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        lineage_metadata={
            "lineage_type": "official_srpe_current_directory_manifest_backfill",
            "candidate_source_dataset": "shkp_srpe_crosswalk",
            "selected_candidate_ids": selected_ids,
            "candidate_statuses": sorted(allowed_statuses),
            "merged_prior_snapshot": not prior.empty,
            "base_live_manifest_phase_count": len(existing - set(prior.get("srpe_development_id", pd.Series(dtype="string")).dropna().astype(str))),
            "pdf_downloaded": False,
            "ownership_inference": False,
            "sales_promotion": False,
        },
    )
    return {
        "run_id": run_id,
        "selected_phase_ids": selected_ids,
        "selected_development_count": len(selected_ids),
        "new_manifest_rows": int(len(new_manifest)),
        "merged_manifest_rows": int(len(merged)),
        "manifest_phase_count": int(merged.get("srpe_development_id", pd.Series(dtype="string")).nunique()),
        "manifest_category_counts": merged.get("document_category", pd.Series(dtype="string")).value_counts().to_dict(),
        "skipped_items": new_manifest.attrs.get("skipped_documents", []),
        "normalized": normalized,
        "ownership_inference": False,
        "sales_promotion": False,
    }


def _build_historical_transaction_merge(
    prior_events: pd.DataFrame,
    current_events: pd.DataFrame,
    *,
    routed_phase_ids: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Repair and re-aggregate the append-only historical transaction union.

    Historical batches replace the routed phases while retaining every other
    phase from the prior union.  Normalization is deliberately applied after
    that merge so compact legacy rows already present in retained snapshots
    receive the same shifted-price repair as newly parsed rows.

    Monthly signals remain PASP-anchored.  Rows without PASP are retained in
    the event contract and copied to an explicit quarantine dataset; ASP is
    never substituted as the event month.
    """
    prior = prior_events.copy() if prior_events is not None else pd.DataFrame()
    current = current_events.copy() if current_events is not None else pd.DataFrame()
    routed = {str(value).strip() for value in routed_phase_ids if str(value).strip()}

    if not prior.empty and routed:
        phase_column = next(
            (
                column
                for column in ("srpe_development_id", "development_id", "srpe_dev_id")
                if column in prior.columns
            ),
            None,
        )
        if phase_column:
            prior = prior.loc[~prior[phase_column].fillna("").astype(str).isin(routed)].copy()
    merged = pd.concat([prior, current], ignore_index=True) if not prior.empty else current.copy()
    if merged.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # Import locally to keep the catalog orchestration boundary independent of
    # the scratch runner while reusing its narrow source-shaped normalization.
    from .shkp_signals import _normalise_transactions

    events = _normalise_transactions(merged)
    if "transaction_id" in events.columns:
        events = events.drop_duplicates(subset=["transaction_id"], keep="last")
    events = events.reset_index(drop=True)
    events["historical_month_inclusion"] = events["event_period"].notna()
    events["historical_date_handling_status"] = "included_pasp_month"
    pasp_missing = ~events["historical_month_inclusion"]
    events.loc[pasp_missing, "historical_date_handling_status"] = (
        events.loc[pasp_missing, "date_gap_status"].map(
            {
                "pasp_missing_asp_observed": "quarantined_pasp_missing_asp_observed",
                "pasp_and_asp_missing": "quarantined_pasp_and_asp_missing",
            }
        ).fillna("quarantined_pasp_missing")
    )

    date_gaps = events.loc[pasp_missing].copy()
    date_gaps["date_gap_dataset_status"] = date_gaps["historical_date_handling_status"]
    date_gaps["strict_signal_inclusion"] = False
    date_gaps["indicative_sales_model_inclusion"] = False
    date_gaps["asp_used_as_pasp"] = False

    eligible_events = events.loc[events["historical_month_inclusion"]].copy()
    monthly = build_srpe_sales_signals(eligible_events)
    mapping_columns = [
        "development_id",
        "project_id",
        "stock_code",
        "ownership_pct",
        "srpe_development_id",
        "ownership_attribution_ready",
        "sales_attribution_status",
    ]
    if not monthly.empty:
        mapping = events[[column for column in mapping_columns if column in events.columns]].copy()
        mapping = mapping.drop_duplicates(subset=["development_id"], keep="last")
        extra_columns = [column for column in mapping_columns if column != "development_id"]
        monthly = monthly.merge(mapping[["development_id", *extra_columns]], on="development_id", how="left")
        monthly["sales_value_attributable_hkd"] = float("nan")
    else:
        for column in mapping_columns[1:]:
            monthly[column] = pd.Series(dtype="object")
        monthly["sales_value_attributable_hkd"] = pd.Series(dtype="float64")
    return events, monthly, date_gaps


def run_shkp_historical_transaction_backfill(
    *,
    max_phases: int = 8,
    timeout: float = 30,
    request_delay: float = 0.25,
    phase_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Parse all available SRPE transaction-register versions for old phases.

    The generated registry is explicitly routing-only: it carries a zero
    ownership percentage and a blocked interval, so the resulting gross
    transaction events cannot enter SHKP attributable sales. Outputs use a
    separate ``shkp_historical_*`` dataset prefix.

    ``phase_ids`` optionally routes an explicit SRPE phase list (e.g. roster
    phases that carry numeric/JV evidence but never had a document manifest
    backfill because they are still active).  The same routing-only registry,
    merge, date-gap quarantine and quality-audit logic is reused verbatim so
    a targeted batch is indistinguishable from a manifest-driven one.
    """
    if max_phases <= 0:
        raise ValueError("max_phases must be positive")
    from .srpe_pilot import run_srpe_pilot

    manifest = load_latest_normalized("shkp_historical_srpe_document_manifest")
    roster = load_latest_normalized("shkp_historical_phase_roster")
    if manifest.empty and phase_ids is None:
        raise RuntimeError("historical manifest and roster are required; run both backfill commands first")
    if phase_ids is None:
        if roster.empty:
            raise RuntimeError("historical roster is required; run build-shkp-historical-roster first")
        register_ids = (
            manifest.loc[
                manifest.get("document_category", pd.Series(dtype="string")).astype("string").eq("register_of_transactions"),
                "srpe_development_id",
            ]
            .dropna()
            .astype(str)
            .drop_duplicates()
            .tolist()
        )
    else:
        if roster.empty:
            raise RuntimeError("historical roster is required for explicit phase routing")
        requested = {str(value).strip() for value in phase_ids if str(value).strip()}
        roster_ids = set(roster.get("srpe_development_id", pd.Series(dtype="string")).dropna().astype(str))
        missing = sorted(requested - roster_ids)
        if missing:
            raise ValueError(f"phase_ids not present in historical roster: {missing}")
        register_ids = sorted(requested)
    prior_quality = _load_all_non_empty_snapshots("shkp_historical_transaction_quality_audit")
    # Only skip phases that produced non-empty, date-complete events.  A
    # parser-zero result, a missing-PASP quarantine, or a review-required row
    # must remain retryable after a parser/source refresh; otherwise a transient
    # network failure becomes a permanent coverage hole.
    completed_ids: set[str] = set()
    if not prior_quality.empty and "srpe_development_id" in prior_quality.columns:
        ready = prior_quality.copy()
        ready_status = ready.get("quality_status", pd.Series("", index=ready.index)).astype(str)
        event_rows = pd.to_numeric(ready.get("event_rows", pd.Series(0, index=ready.index)), errors="coerce").fillna(0)
        missing_pasp = pd.to_numeric(ready.get("missing_pasp_rows", pd.Series(0, index=ready.index)), errors="coerce").fillna(0)
        missing_asp = pd.to_numeric(ready.get("missing_asp_rows", pd.Series(0, index=ready.index)), errors="coerce").fillna(0)
        eligible = ready_status.eq("gross_event_ready") & event_rows.gt(0) & missing_pasp.eq(0) & missing_asp.eq(0)
        completed_ids = {
            str(value).strip()
            for value in ready.loc[eligible, "srpe_development_id"].dropna()
            if str(value).strip()
        }
    pending_ids = [phase_id for phase_id in register_ids if phase_id not in completed_ids]
    if pending_ids:
        register_ids = pending_ids[:max_phases]
    else:
        register_ids = register_ids[:max_phases]
    if not register_ids:
        raise RuntimeError("historical manifest contains no transaction-register phase ids")
    roster_rows = {
        str(row.get("srpe_development_id")): row
        for row in roster.to_dict("records")
        if str(row.get("srpe_development_id") or "").strip()
    }
    rows: list[dict[str, Any]] = []
    for phase_id in register_ids:
        record = roster_rows.get(phase_id, {})
        rows.append(
            {
                "project_id": f"shkp-historical-srpe-{phase_id}",
                "stock_code": "0016",
                "ownership_pct": 0.0,
                "srpe_dev_id": phase_id,
                "srpe_development_id": phase_id,
                "development_name": record.get("development_name_en") or f"SRPE {phase_id}",
                "phase_name": record.get("phase_name_en") or record.get("development_name_en") or f"SRPE {phase_id}",
                "phase_no": record.get("phase_no") or "",
                "development_address": record.get("address_en") or "",
                "pilot_group": "shkp_historical_manifest_routing_only",
                "source_document": "historical SRPE manifest; ownership review required",
                "last_verified_date": datetime.now(timezone.utc).date().isoformat(),
                "candidate_status": "historical_manifest_routing",
                "official_website": record.get("official_website"),
                "ownership_attribution_ready": False,
                "ownership_effective_from": None,
                "ownership_effective_to": None,
                "ownership_interval_evidence_type": None,
                "ownership_attribution_decision_id": None,
                "ownership_interval_promotion_status": "blocked_historical_manifest_routing",
            }
        )
    registry = pd.DataFrame(rows)
    routed_phase_ids = [str(value) for value in register_ids]
    prior_transaction_frames = {
        name: _load_all_non_empty_snapshots(name)
        for name in (
            HISTORICAL_TRANSACTION_EVENT_DATASET,
            HISTORICAL_DOCUMENT_AUDIT_DATASET,
        )
    }
    registry_raw = save_raw_snapshot(
        "shkp_historical_transaction_registry",
        registry.to_csv(index=False),
        file_ext="csv",
        source_url="https://www.srpe.gov.hk/opip/all_development",
    )
    run_id = f"shkp-historical-transaction-{uuid.uuid4()}"
    result = run_srpe_pilot(
        run_id=run_id,
        registry_path=registry_raw,
        pilot_group="shkp_historical_manifest_routing_only",
        all_transaction_documents=True,
        transactions_only=True,
        dataset_prefix="shkp_historical",
        request_delay=request_delay,
        timeout=timeout,
    )
    # Backfill runs are append/refresh operations.  The pilot writer is
    # intentionally run-scoped, so merge the new phase batch with the latest
    # historical snapshot before publishing; otherwise a second batch would
    # make the first batch disappear from ``load_latest_normalized``.
    current_event_info = result.get("normalized", {}).get(HISTORICAL_TRANSACTION_EVENT_DATASET, {})
    current_event_path = current_event_info.get("parquet") if isinstance(current_event_info, dict) else None
    current_events = _read_snapshot_with_lineage(
        current_event_path,
        current_event_info.get("lineage") if isinstance(current_event_info, dict) else None,
    )
    merged_events, rebuilt_monthly, historical_date_gaps = _build_historical_transaction_merge(
        prior_transaction_frames.get(HISTORICAL_TRANSACTION_EVENT_DATASET, pd.DataFrame()),
        current_events,
        routed_phase_ids=routed_phase_ids,
    )
    rebuilt_frames = {
        HISTORICAL_TRANSACTION_EVENT_DATASET: merged_events,
        HISTORICAL_MONTHLY_SIGNAL_DATASET: rebuilt_monthly,
    }
    for dataset_name in (
        HISTORICAL_TRANSACTION_EVENT_DATASET,
        HISTORICAL_MONTHLY_SIGNAL_DATASET,
        HISTORICAL_DOCUMENT_AUDIT_DATASET,
    ):
        current_info = result.get("normalized", {}).get(dataset_name, {})
        current_path = current_info.get("parquet") if isinstance(current_info, dict) else None
        current = _read_snapshot_with_lineage(
            current_path,
            current_info.get("lineage") if isinstance(current_info, dict) else None,
        )
        prior = prior_transaction_frames.get(dataset_name, pd.DataFrame())
        if dataset_name in rebuilt_frames:
            merged = rebuilt_frames[dataset_name]
        elif not prior.empty:
            phase_column = next(
                (column for column in ("development_id", "srpe_development_id", "project_id") if column in prior.columns),
                None,
            )
            prior_keep = prior
            if phase_column:
                prior_keep = prior.loc[
                    ~prior[phase_column].fillna("").astype(str).isin(set(routed_phase_ids))
                ].copy()
            merged = pd.concat([prior_keep, current], ignore_index=True) if not current.empty else prior_keep.copy()
        else:
            merged = current
        if merged.empty:
            continue
        if dataset_name == HISTORICAL_TRANSACTION_EVENT_DATASET and "transaction_id" in merged.columns:
            merged = merged.drop_duplicates(subset=["transaction_id"], keep="last")
        elif dataset_name == HISTORICAL_MONTHLY_SIGNAL_DATASET:
            monthly_keys = [column for column in ("development_id", "period") if column in merged.columns]
            merged = merged.drop_duplicates(subset=monthly_keys, keep="last") if monthly_keys else merged.drop_duplicates()
        elif dataset_name == HISTORICAL_DOCUMENT_AUDIT_DATASET:
            audit_keys = [column for column in ("srpe_dev_id", "document_id", "document_hash") if column in merged.columns]
            merged = merged.drop_duplicates(subset=audit_keys, keep="last") if audit_keys else merged.drop_duplicates()
        else:
            merged = merged.drop_duplicates()
        merged = merged.reset_index(drop=True)
        attrs = dict(current.attrs)
        parent_lineages = [
            *prior.attrs.get("source_lineages", []),
            *current.attrs.get("source_lineages", []),
        ]
        if parent_lineages:
            attrs["source_lineages"] = list({
                str(item.get("run_id")): item
                for item in parent_lineages
                if isinstance(item, dict) and item.get("run_id")
            }.values())
        attrs["lineage_metadata"] = {
            **(attrs.get("lineage_metadata") or {}),
            "lineage_type": f"merged_{dataset_name}",
            "append_refresh": True,
            "merged_prior_snapshot": not prior.empty,
            "routed_phase_ids": routed_phase_ids,
            "ownership_attribution": False,
            "parent_lineage_runs": [
                item.get("run_id") for item in attrs.get("source_lineages", []) if item.get("run_id")
            ],
        }
        raw_snapshots = list(dict.fromkeys(
            str(value)
            for frame in (prior, current)
            for value in frame.attrs.get("raw_snapshots", [])
            if value
        ))
        source_urls = list(dict.fromkeys(
            str(value)
            for frame in (prior, current)
            for value in frame.attrs.get("source_urls", [])
            if value
        ))
        result.setdefault("normalized", {})[dataset_name] = save_normalized_dataset(
            dataset_name,
            merged,
            run_id=f"{run_id}-merged",
            raw_snapshots=raw_snapshots,
            source_urls=source_urls,
            lineage_metadata=attrs["lineage_metadata"],
        )
    result.setdefault("normalized", {})[HISTORICAL_TRANSACTION_DATE_GAP_DATASET] = (
        save_normalized_dataset(
            HISTORICAL_TRANSACTION_DATE_GAP_DATASET,
            historical_date_gaps,
            run_id=f"{run_id}-merged",
            source_urls=[
                "https://www.srpe.gov.hk/api/SrpeWebService/DevBldgSearch/getSelectedDevResult",
                "https://www.srpe.gov.hk/api/SrpeWebService/download/downloadTrx",
            ],
            lineage_metadata={
                "lineage_type": "derived_shkp_historical_transaction_date_gap_quarantine",
                "parent_dataset": HISTORICAL_TRANSACTION_EVENT_DATASET,
                "date_policy": "PASP_required_for_monthly_signal; ASP_is_never_substituted",
                "strict_signal_inclusion": False,
                "indicative_sales_model_inclusion": False,
            },
        )
    )
    transaction_quality_audit_normalized = None
    transaction_path = result.get("normalized", {}).get(HISTORICAL_TRANSACTION_EVENT_DATASET, {}).get("parquet")
    if transaction_path:
        transaction_events = pd.read_parquet(transaction_path)
        audit_rows: list[dict[str, Any]] = []
        key_columns = [
            "development_id", "block_name", "floor", "unit",
            "date_of_pasp", "date_of_asp", "date_of_asp_termination",
        ]
        for phase_id, group in transaction_events.groupby("development_id", dropna=False):
            phase_id = str(phase_id)
            exact_duplicates = int(group.duplicated().sum())
            available_keys = [column for column in key_columns if column in group.columns]
            composite_duplicates = int(group.duplicated(available_keys, keep=False).sum()) if available_keys else 0
            pasp = pd.to_datetime(group.get("date_of_pasp"), errors="coerce")
            asp = pd.to_datetime(group.get("date_of_asp"), errors="coerce")
            termination = pd.to_datetime(group.get("date_of_asp_termination"), errors="coerce")
            unit_columns = [column for column in ("block_name", "floor", "unit") if column in group.columns]
            unit_signatures = int(group[unit_columns].drop_duplicates().shape[0]) if unit_columns else 0
            notes: list[str] = []
            if exact_duplicates or composite_duplicates:
                notes.append("duplicate_event_key")
            if int(pasp.isna().sum()):
                notes.append("missing_pasp_date")
            if int(asp.isna().sum()):
                notes.append("missing_asp_date")
            if int(termination.notna().sum()):
                notes.append("termination_rows_present")
            audit_rows.append(
                {
                    "srpe_development_id": phase_id,
                    "event_rows": int(len(group)),
                    "exact_duplicate_rows": exact_duplicates,
                    "composite_duplicate_rows": composite_duplicates,
                    "missing_pasp_rows": int(pasp.isna().sum()),
                    "missing_asp_rows": int(asp.isna().sum()),
                    "termination_rows": int(termination.notna().sum()),
                    "first_pasp_date": pasp.min().date().isoformat() if pasp.notna().any() else None,
                    "last_asp_date": asp.max().date().isoformat() if asp.notna().any() else None,
                    "unique_unit_signatures": unit_signatures,
                    "quality_status": (
                        "review_required"
                        if (exact_duplicates or composite_duplicates)
                        else "gross_event_ready_with_date_gaps"
                        if (pasp.isna().any() or asp.isna().any())
                        else "gross_event_ready"
                    ),
                    "quality_notes": " | ".join(notes) or None,
                    "last_verified_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        observed_phase_ids = {str(row.get("srpe_development_id") or "") for row in audit_rows}
        for phase_id in routed_phase_ids:
            if phase_id in observed_phase_ids:
                continue
            audit_rows.append(
                {
                    "srpe_development_id": phase_id,
                    "event_rows": 0,
                    "exact_duplicate_rows": 0,
                    "composite_duplicate_rows": 0,
                    "missing_pasp_rows": 0,
                    "missing_asp_rows": 0,
                    "termination_rows": 0,
                    "first_pasp_date": None,
                    "last_asp_date": None,
                    "unique_unit_signatures": 0,
                    "quality_status": "register_parsed_zero_rows",
                    "quality_notes": "transaction register was observed and parsed, but emitted no transaction rows",
                    "last_verified_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        quality_audit = pd.DataFrame(audit_rows)
        if not prior_quality.empty:
            prior_keep = prior_quality.loc[
                ~prior_quality["srpe_development_id"].astype(str).isin(routed_phase_ids)
            ].copy()
            quality_audit = pd.concat([prior_keep, quality_audit], ignore_index=True)
        quality_audit = quality_audit.drop_duplicates(subset=["srpe_development_id"], keep="last").reset_index(drop=True)
        transaction_quality_audit_normalized = save_normalized_dataset(
            "shkp_historical_transaction_quality_audit",
            quality_audit,
            run_id=run_id,
            source_urls=[
                "https://www.srpe.gov.hk/api/SrpeWebService/DevBldgSearch/getSelectedDevResult",
                "https://www.srpe.gov.hk/api/SrpeWebService/download/downloadTrx",
            ],
            lineage_metadata={
                "lineage_type": "derived_shkp_historical_transaction_quality_audit",
                "parent_dataset": "shkp_historical_srpe_pilot_transaction_events",
                "composite_key": key_columns,
                "ownership_inference": False,
                "sales_attribution": False,
                "merged_prior_snapshot": not prior_quality.empty,
                "routed_phase_ids": routed_phase_ids,
            },
        )
    result.update(
        {
            "historical_manifest_phase_ids": register_ids,
            "routing_only": True,
            "ownership_attribution": "blocked_phase_specific_interval",
            "historical_date_gap_rows": int(len(historical_date_gaps)),
            "transaction_quality_audit_normalized": transaction_quality_audit_normalized,
        }
    )
    return result


def run_shkp_historical_annual_backfill(
    *,
    max_reports: int = 3,
    report_ids: list[str] | None = None,
    timeout: float = 120,
) -> dict[str, Any]:
    """Download/parse a bounded set of historical SHKP annual reports.

    The report index is the selection authority.  Full PDFs are preferred
    over text-only variants, and the default is intentionally small so a
    layout change or large historical file cannot silently trigger a full
    2001-onward download.  Output remains evidence-only until phase aliases
    and ownership are reconciled.
    """
    if max_reports <= 0:
        raise ValueError("max_reports must be positive")
    index = load_latest_normalized("shkp_historical_annual_report_index")
    if index.empty:
        raise RuntimeError("historical annual-report index is missing; run SHKP catalog/document discovery first")
    selected = index.loc[index.get("document_variant", pd.Series(dtype="string")).eq("full_pdf")].copy()
    if report_ids:
        requested = {str(value).strip() for value in report_ids if str(value).strip()}
        selected = selected.loc[selected["report_id"].astype(str).isin(requested)]
    else:
        selected = selected.sort_values(["report_period_end", "report_id"], na_position="last").head(max_reports)
    if selected.empty:
        raise ValueError("no matching full-PDF annual reports found in historical index")
    configs = [
        {
            "report_id": str(row["report_id"]),
            "report_period_end": row.get("report_period_end"),
            "url": str(row["document_url"]),
            "include_pipeline_anchors": False,
        }
        for row in selected.to_dict("records")
    ]
    projects = shkp.fetch_shkp_annual_report_pipeline(timeout=timeout, reports=configs)
    run_id = f"shkp-historical-annual-{uuid.uuid4()}"
    raw_snapshots = list(projects.attrs.get("raw_snapshots", []))
    source_urls = list(projects.attrs.get("source_urls", []))
    # Historical backfills are append/refresh operations.  A run-scoped
    # snapshot must not hide earlier report vintages just because one newer
    # report was parsed most recently.
    historical_root = NORMALIZED_DIR / "shkp_historical_annual_report_projects"
    prior_report_snapshots: dict[str, tuple[str, pd.DataFrame]] = {}
    if historical_root.is_dir():
        for parquet_path in historical_root.glob("*/shkp_historical_annual_report_projects.parquet"):
            try:
                frame = pd.read_parquet(parquet_path)
                if frame.empty or "report_id" not in frame.columns:
                    continue
                lineage_path = parquet_path.parent / "lineage.json"
                lineage = {}
                if lineage_path.exists():
                    try:
                        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError, TypeError):
                        lineage = {}
                selected_vintages = {
                    str(value).strip()
                    for value in lineage.get("selected_report_ids", [])
                    if str(value).strip()
                }
                # Before selected_report_ids was introduced, fall back to
                # every report in that snapshot. New snapshots always carry
                # the explicit selection list, so merged rows from another
                # vintage are not accidentally treated as refreshed.
                if not selected_vintages:
                    selected_vintages = set(frame["report_id"].dropna().astype(str))
                created_at = str(lineage.get("created_at") or "")
                for report_id in selected_vintages:
                    report_rows = frame.loc[frame["report_id"].astype(str).eq(report_id)].copy()
                    if report_rows.empty:
                        continue
                    prior = prior_report_snapshots.get(report_id)
                    if prior is None or created_at > prior[0]:
                        prior_report_snapshots[report_id] = (created_at, report_rows)
            except Exception:
                continue
    prior_frames = [frame for _, frame in sorted(prior_report_snapshots.values(), key=lambda item: item[0])]
    prior_rows = sum(len(frame) for frame in prior_frames)
    prior_records = []
    for frame in prior_frames:
        prior_records.extend(frame.to_dict("records"))
    prior_merged = pd.DataFrame(prior_records) if prior_records else pd.DataFrame(columns=projects.columns)
    selected_ids = {config["report_id"] for config in configs}
    if not prior_merged.empty and "report_id" in prior_merged.columns:
        # Replacing the selected report vintages prevents an earlier parser
        # configuration (for example stale future-pipeline anchors) from
        # surviving beside the corrected parse.
        prior_merged = prior_merged.loc[~prior_merged["report_id"].astype(str).isin(selected_ids)].copy()
    merged_records = []
    for frame in (prior_merged, projects):
        if not frame.empty:
            merged_records.extend(frame.to_dict("records"))
    merged_projects = pd.DataFrame(merged_records) if merged_records else projects.copy()
    dedup_keys = ["report_id", "evidence_type", "project_label", "page_number", "document_url"]
    available_keys = [key for key in dedup_keys if key in merged_projects.columns]
    if available_keys:
        merged_projects = merged_projects.drop_duplicates(subset=available_keys, keep="last").reset_index(drop=True)
    merged_projects.attrs.update(projects.attrs)
    normalized = save_normalized_dataset(
        "shkp_historical_annual_report_projects",
        merged_projects,
        run_id=run_id,
        raw_snapshots=raw_snapshots,
        source_urls=source_urls,
        lineage_metadata={
            **(projects.attrs.get("lineage_metadata") or {}),
            "lineage_type": "official_shkp_historical_annual_report_project_evidence",
            "selected_report_ids": [config["report_id"] for config in configs],
            "selection_policy": "full_pdf_only; bounded explicit report selection",
            "prior_snapshot_rows": int(prior_rows),
            "new_rows_before_dedup": int(len(projects)),
            "merged_rows": int(len(merged_projects)),
            "append_refresh_policy": "deduplicate by report/evidence/project/page/document and keep newest parse",
            "ownership_promotion": False,
        },
    )
    return {
        "run_id": run_id,
        "selected_report_ids": [config["report_id"] for config in configs],
        "report_count": len(configs),
        "project_evidence_rows": int(len(merged_projects)),
        "new_project_evidence_rows": int(len(projects)),
        "normalized": normalized,
        "parse_summary": projects.attrs.get("lineage_metadata", {}).get("parse_summary", []),
        "ownership_promotion": False,
    }


def import_shkp_land_registry_csv(
    csv_path: Path,
    *,
    run_id: str | None = None,
    last_verified_at: str | None = None,
) -> dict[str, Any]:
    """Validate and persist a manual IRIS/Land Registry CSV import.

    The title layer is intentionally not included in ``CORE_DATASETS`` and is
    never passed into the legal-ownership or sales gate.  It is an optional
    evidence table that an analyst can reconcile into a separately reviewed
    phase-attribution decision later.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Land Registry CSV not found: {path}")
    run_id = run_id or str(uuid.uuid4())
    raw_path = save_raw_snapshot(
        "shkp_land_registry_import",
        path.read_bytes(),
        file_ext="csv",
        source_url=str(path),
        run_id=run_id,
    )
    records = pd.read_csv(path, dtype=str)
    frame = shkp.build_shkp_land_registry_evidence(
        records,
        last_verified_at=last_verified_at,
    )
    if frame.empty:
        raise ValueError("Land Registry CSV contains no evidence rows")
    normalized = save_normalized_dataset(
        "shkp_land_registry_evidence",
        frame,
        run_id=run_id,
        raw_snapshot=str(raw_path),
        raw_snapshots=[str(raw_path)],
        source_url=str(path),
        source_urls=[str(path)],
        lineage_metadata={
            **(frame.attrs.get("lineage_metadata") or {}),
            "import_mode": "manual_csv",
            "sales_promotion": False,
        },
    )
    return {
        "mode": "manual_csv_import",
        "run_id": run_id,
        "records": int(len(frame)),
        "normalized": normalized,
        "raw_snapshot": str(raw_path),
        "promotion_policy": "registered title never promotes SHKP attribution without separate approved SPV/JV evidence",
    }


def import_shkp_phase_attribution_decisions_csv(
    csv_path: Path,
    *,
    run_id: str | None = None,
    last_verified_at: str | None = None,
) -> dict[str, Any]:
    """Validate and persist manually reviewed phase-attribution decisions.

    The CSV is merged onto the existing 13-phase decision layer rather than
    replacing it wholesale.  This lets an analyst review one phase at a time
    while preserving explicit blocked placeholders for every other priority
    phase.  The importer never builds a project registry or sales dataset;
    the next catalog refresh must re-run the decision gate before anything can
    become attributable sales.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"phase attribution decision CSV not found: {path}")
    incoming = pd.read_csv(path, dtype=str)
    if incoming.empty:
        raise ValueError("phase attribution decision CSV contains no rows")
    if "srpe_development_id" not in incoming.columns:
        raise ValueError("phase attribution decision CSV requires srpe_development_id")
    incoming_ids = incoming["srpe_development_id"].astype("string").str.strip()
    if incoming_ids.eq("").any() or incoming_ids.isna().any():
        raise ValueError("phase attribution decision CSV contains a blank srpe_development_id")
    if incoming_ids.duplicated().any():
        duplicates = sorted(incoming_ids[incoming_ids.duplicated()].unique().tolist())
        raise ValueError(f"phase attribution decision CSV contains duplicate phase ids: {', '.join(duplicates)}")
    unknown = sorted(set(incoming_ids) - set(SHKP_PRIORITY_PHASE_IDS))
    if unknown:
        raise ValueError(
            "phase attribution decision CSV contains non-priority phase ids: "
            + ", ".join(unknown)
        )

    run_id = run_id or str(uuid.uuid4())
    raw_path = save_raw_snapshot(
        "shkp_phase_attribution_decision_import",
        path.read_bytes(),
        file_ext="csv",
        source_url=str(path),
        run_id=run_id,
    )
    validated_incoming = shkp.build_shkp_phase_attribution_decisions(
        incoming,
        last_verified_at=last_verified_at,
    )
    srpe_index = load_latest_normalized("srpe_development_index")
    existing = _load_or_build_phase_attribution_decisions(srpe_index)
    merged_by_id = {
        str(row.get("srpe_development_id")): row
        for row in existing.to_dict("records")
        if str(row.get("srpe_development_id") or "").strip()
    }
    for row in validated_incoming.to_dict("records"):
        merged_by_id[str(row["srpe_development_id"])] = row
    merged = shkp.build_shkp_phase_attribution_decisions(
        list(merged_by_id.values()),
        last_verified_at=last_verified_at,
    )
    missing = sorted(set(SHKP_PRIORITY_PHASE_IDS) - set(merged["srpe_development_id"].astype(str)))
    if missing:
        raise RuntimeError(
            "merged phase-attribution decision layer is missing priority phases: "
            + ", ".join(missing)
        )
    normalized = save_normalized_dataset(
        "shkp_phase_attribution_decisions",
        merged,
        run_id=run_id,
        raw_snapshot=str(raw_path),
        raw_snapshots=[str(raw_path)],
        source_url=str(path),
        source_urls=[str(path)],
        lineage_metadata={
            **(merged.attrs.get("lineage_metadata") or {}),
            "import_mode": "manual_reviewed_decision_csv",
            "updated_phase_ids": sorted(set(incoming_ids)),
            "requires_catalog_refresh": True,
            "sales_promotion": False,
        },
    )
    return {
        "mode": "manual_phase_attribution_decision_import",
        "run_id": run_id,
        "updated_phase_ids": sorted(set(incoming_ids)),
        "records": int(len(merged)),
        "approved_records": int(merged["ownership_attribution_ready"].fillna(False).astype(bool).sum()),
        "normalized": normalized,
        "raw_snapshot": str(raw_path),
        "requires_catalog_refresh": True,
        "promotion_policy": "only approved phase-specific decisions with bounded dates and evidence can open the sales gate on the next catalog refresh",
    }


def run_shkp_catalog(
    *,
    timeout: float = 60,
    max_pages: int | None = None,
    max_manifest_developments: int = 10,
    site_project_limit: int | None = 50,
    skip_site_facts: bool = False,
    skip_deep_documents: bool = False,
    offline: bool = False,
) -> dict[str, Any]:
    """Run the bounded SHKP/SRPE catalog and ownership-review pipeline.

    ``skip_deep_documents`` is useful for a quick website/index refresh.  It
    still emits explicit empty frames for deep layers, so a skipped parser is
    distinguishable from an omitted dataset.  ``offline`` only audits the
    latest normalized snapshots and never claims that a live source was read.
    """
    if offline:
        return _offline_summary()
    if max_manifest_developments < 0:
        raise ValueError("max_manifest_developments must be non-negative")
    if site_project_limit is not None and site_project_limit < 0:
        raise ValueError("site_project_limit must be non-negative or None")

    run_id = str(uuid.uuid4())
    client = requests.Session()
    frames: dict[str, pd.DataFrame] = {}
    stored: dict[str, Any] = {}

    frames["shkp_property_catalog"] = shkp.fetch_shkp_property_catalog(
        session=client, timeout=timeout, max_pages=max_pages
    )
    if frames["shkp_property_catalog"].empty:
        raise RuntimeError("SHKP property catalog returned zero rows; refusing to publish an empty refresh")
    frames["srpe_development_index"] = srpe.fetch_srpe_development_index(
        session=client, timeout=min(timeout, 30)
    )
    if frames["srpe_development_index"].empty:
        raise RuntimeError("SRPE development index returned zero rows; refusing to publish an empty refresh")
    frames["shkp_srpe_crosswalk"] = shkp.build_shkp_srpe_crosswalk(
        frames["shkp_property_catalog"], frames["srpe_development_index"]
    )

    frames["shkp_pipeline_disclosures"] = shkp.fetch_shkp_pipeline_disclosures(
        session=client, timeout=timeout
    )
    frames["shkp_pipeline_srpe_crosswalk"] = shkp.build_shkp_pipeline_srpe_crosswalk(
        frames["shkp_pipeline_disclosures"], frames["srpe_development_index"]
    )
    frames["shkp_pipeline_project_registry"] = shkp.build_shkp_pipeline_project_registry(
        frames["shkp_pipeline_srpe_crosswalk"]
    )

    if skip_site_facts:
        frames["shkp_project_site_vendor_facts"] = _empty(shkp.SHKP_PROJECT_SITE_VENDOR_FACT_COLUMNS)
    elif site_project_limit == 0:
        frames["shkp_project_site_vendor_facts"] = _empty(shkp.SHKP_PROJECT_SITE_VENDOR_FACT_COLUMNS)
    else:
        residential = frames["shkp_property_catalog"].loc[
            frames["shkp_property_catalog"].get("asset_type", pd.Series(dtype="string")).eq("residential_for_sale")
        ]
        names = residential["marketing_name"].tolist() if site_project_limit is None else residential["marketing_name"].head(site_project_limit).tolist()
        frames["shkp_project_site_vendor_facts"] = shkp.fetch_shkp_project_site_vendor_facts(
            frames["shkp_property_catalog"], project_names=names, session=client, timeout=timeout, run_id=run_id
        )
    frames["shkp_project_site_vendor_crosswalk"] = shkp.build_shkp_project_site_vendor_crosswalk(
        frames["shkp_project_site_vendor_facts"], frames["shkp_srpe_crosswalk"]
    )

    if skip_deep_documents:
        frames["shkp_annual_report_projects"] = _empty(shkp.ANNUAL_REPORT_PROJECT_COLUMNS)
        frames["shkp_completed_properties"] = _empty(shkp.SHKP_COMPLETED_PROPERTY_COLUMNS)
        frames["shkp_annual_principal_subsidiaries"] = _empty(shkp.SHKP_ANNUAL_PRINCIPAL_SUBSIDIARY_COLUMNS)
        frames["shkp_completion_schedule_projects"] = _empty(shkp.SHKP_COMPLETION_SCHEDULE_COLUMNS)
    else:
        annual = shkp.fetch_shkp_annual_report_pipeline(session=client, timeout=max(timeout, 90))
        frames["shkp_annual_report_projects"] = annual
        completed_properties = annual.attrs.get("completed_properties_records")
        frames["shkp_completed_properties"] = (
            pd.DataFrame(completed_properties, columns=shkp.SHKP_COMPLETED_PROPERTY_COLUMNS)
            if isinstance(completed_properties, list)
            else _empty(shkp.SHKP_COMPLETED_PROPERTY_COLUMNS)
        )
        frames["shkp_completed_properties"].attrs.update(
            raw_snapshots=list(annual.attrs.get("raw_snapshots", [])),
            source_urls=list(annual.attrs.get("source_urls", [])),
            lineage_metadata={
                "lineage_type": "derived_shkp_completed_property_exposure",
                "source_dataset": "shkp_annual_report_projects",
                "report_parse_summary": annual.attrs.get("lineage_metadata", {}).get("parse_summary", []),
                "ownership_interval_promotion": False,
                "income_inference": False,
            },
        )
        frames["shkp_annual_principal_subsidiaries"] = shkp.parse_shkp_annual_principal_subsidiaries(
            annual.attrs.get("raw_snapshots", []), fetched_at=datetime.now(timezone.utc).isoformat()
        )
        frames["shkp_completion_schedule_projects"] = shkp.fetch_shkp_completion_schedule_projects(
            session=client, timeout=max(timeout, 90)
        )
    frames["shkp_annual_srpe_crosswalk"] = shkp.build_shkp_annual_srpe_crosswalk(
        frames["shkp_annual_report_projects"], frames["srpe_development_index"]
    )
    frames["shkp_legal_ownership_observations"] = shkp.build_shkp_legal_ownership_observations(
        frames["srpe_development_index"]
    )
    frames["shkp_phase_attribution_decisions"] = _load_or_build_phase_attribution_decisions(
        frames["srpe_development_index"]
    )
    frames["shkp_phase_role_evidence"] = shkp.build_shkp_phase_role_evidence()
    frames["shkp_annual_principal_subsidiary_crosswalk"] = shkp.build_shkp_annual_principal_subsidiary_crosswalk(
        frames["shkp_annual_principal_subsidiaries"],
        legal_ownership_observations=frames["shkp_legal_ownership_observations"],
        site_vendor_crosswalk=frames["shkp_project_site_vendor_crosswalk"],
        srpe_index=frames["srpe_development_index"],
    )
    frames["shkp_completion_schedule_crosswalk"] = shkp.build_shkp_completion_schedule_crosswalk(
        frames["shkp_completion_schedule_projects"], frames["srpe_development_index"]
    )
    frames["shkp_completion_schedule_ownership_evidence"] = shkp.build_shkp_completion_schedule_ownership_evidence(
        frames["shkp_completion_schedule_crosswalk"]
    )

    frames["shkp_supporting_source_catalog"] = shkp.fetch_shkp_supporting_source_catalog()
    if skip_deep_documents:
        frames["shkp_land_planning_documents"] = _empty(shkp.LAND_PLANNING_DOCUMENT_COLUMNS)
    else:
        frames["shkp_land_planning_documents"] = shkp.fetch_shkp_land_planning_documents(
            session=client, timeout=timeout
        )
    frames["shkp_planning_evidence_crosswalk"] = shkp.build_shkp_planning_evidence_crosswalk(
        _empty(land_planning.TPB_APPLICATION_COLUMNS),
        _empty(land_planning.LANDSD_CONSENT_COLUMNS),
        frames["srpe_development_index"],
    )
    bd_events = load_latest_normalized("bd_project_lifecycle_events")
    frames["shkp_bd_crosswalk"] = shkp.build_shkp_bd_crosswalk(
        frames["shkp_srpe_crosswalk"], frames["srpe_development_index"], bd_events
    )
    # Build identity evidence before manifest discovery so the candidate
    # ordering can include explicit SHKP future/phase bridges.
    frames["shkp_future_project_identity_evidence"] = shkp.build_shkp_future_project_identity_evidence()

    # Build the preliminary registry before asking SRPE for a bounded manifest.
    frames["shkp_project_registry"] = shkp.build_shkp_project_registry(
        frames["srpe_development_index"],
        shkp_crosswalk=frames["shkp_srpe_crosswalk"],
        annual_srpe_crosswalk=frames["shkp_annual_srpe_crosswalk"],
        planning_crosswalk=frames["shkp_planning_evidence_crosswalk"],
        pipeline_crosswalk=frames["shkp_pipeline_srpe_crosswalk"],
        bd_crosswalk=frames["shkp_bd_crosswalk"],
        completion_schedule_crosswalk=frames["shkp_completion_schedule_crosswalk"],
        legal_ownership_observations=frames["shkp_legal_ownership_observations"],
        phase_attribution_decisions=frames["shkp_phase_attribution_decisions"],
    )
    ids = _ordered_shkp_srpe_manifest_candidate_ids(
        shkp_crosswalk=frames["shkp_srpe_crosswalk"],
        annual_srpe_crosswalk=frames["shkp_annual_srpe_crosswalk"],
        identity_evidence=frames["shkp_future_project_identity_evidence"],
        project_registry=frames["shkp_project_registry"],
    )
    if skip_deep_documents or max_manifest_developments == 0:
        frames["shkp_srpe_document_manifest"] = _empty(shkp.SHKP_SRPE_MANIFEST_COLUMNS)
    else:
        frames["shkp_srpe_document_manifest"] = shkp.fetch_shkp_srpe_document_manifest(
            ids, session=client, max_developments=max_manifest_developments, timeout=min(timeout, 30)
        )
    frames["shkp_sales_ingestion_eligibility"] = shkp.build_shkp_sales_ingestion_eligibility(
        frames["shkp_project_registry"], frames["shkp_srpe_document_manifest"]
    )
    frames["shkp_sales_ingestion_plan"] = shkp.build_shkp_sales_ingestion_plan(
        frames["shkp_project_registry"], frames["shkp_sales_ingestion_eligibility"]
    )
    frames["shkp_completion_schedule_ownership_audit"] = shkp.build_shkp_completion_schedule_ownership_audit(
        frames["shkp_project_registry"], frames["shkp_completion_schedule_crosswalk"]
    )
    frames["shkp_completion_schedule_reconciliation"] = shkp.build_shkp_completion_schedule_reconciliation(
        frames["shkp_completion_schedule_crosswalk"],
        frames["shkp_annual_srpe_crosswalk"],
        frames["shkp_project_site_vendor_crosswalk"],
    )
    frames["shkp_ownership_evidence_audit"] = shkp.build_shkp_ownership_evidence_audit(
        frames["shkp_project_registry"], frames["shkp_annual_report_projects"]
    )
    frames["shkp_phase_evidence_quality_audit"] = shkp.build_shkp_phase_evidence_quality_audit(
        frames["shkp_annual_report_projects"], frames["srpe_development_index"], _empty(land_planning.TPB_APPLICATION_COLUMNS)
    )
    frames["shkp_ownership_evidence_timeline"] = shkp.build_shkp_ownership_evidence_timeline(
        legal_ownership_observations=frames["shkp_legal_ownership_observations"],
        annual_principal_subsidiary_crosswalk=frames["shkp_annual_principal_subsidiary_crosswalk"],
        annual_srpe_crosswalk=frames["shkp_annual_srpe_crosswalk"],
        completion_schedule_crosswalk=frames["shkp_completion_schedule_crosswalk"],
        planning_evidence_crosswalk=frames["shkp_planning_evidence_crosswalk"],
        pipeline_crosswalk=frames["shkp_pipeline_srpe_crosswalk"],
        site_vendor_crosswalk=frames["shkp_project_site_vendor_crosswalk"],
    )
    frames["shkp_entity_ownership_crosswalk"] = shkp.build_shkp_entity_ownership_crosswalk(
        legal_ownership_observations=frames["shkp_legal_ownership_observations"],
        planning_evidence_crosswalk=frames["shkp_planning_evidence_crosswalk"],
        site_vendor_crosswalk=frames["shkp_project_site_vendor_crosswalk"],
    )
    frames["shkp_ownership_coverage_audit"] = shkp.build_shkp_ownership_coverage_audit(
        frames["srpe_development_index"],
        phase_role_evidence=frames["shkp_phase_role_evidence"],
        legal_ownership_observations=frames["shkp_legal_ownership_observations"],
        phase_attribution_decisions=frames["shkp_phase_attribution_decisions"],
        identity_evidence=frames["shkp_future_project_identity_evidence"],
        priority_phase_ids=SHKP_PRIORITY_PHASE_IDS,
    )
    frames["shkp_future_project_resolution_plan"] = shkp.build_shkp_future_project_resolution_plan(
        frames["shkp_pipeline_project_registry"],
        frames["shkp_sales_ingestion_plan"],
        identity_evidence=frames["shkp_future_project_identity_evidence"],
    )
    frames["shkp_ownership_review_queue"] = shkp.build_shkp_ownership_review_queue(
        frames["shkp_project_registry"], frames["shkp_sales_ingestion_eligibility"]
    )
    if "shkp_corporate_documents" not in frames:
        frames["shkp_corporate_documents"] = shkp.fetch_shkp_corporate_documents(session=client, timeout=timeout)
    frames["shkp_history_milestones"] = shkp.fetch_shkp_history_milestones(
        session=client, timeout=timeout
    )
    frames["shkp_historical_annual_report_index"] = shkp.build_shkp_historical_annual_report_index(
        frames["shkp_corporate_documents"]
    )

    for dataset_name in CORE_DATASETS:
        _persist(frames, dataset_name, run_id, stored)
    # Some evidence layers are intentionally optional so an older catalog
    # snapshot remains usable when a non-essential source is unavailable.  If
    # this live run did fetch one, persist it with the same catalog lineage.
    for dataset_name in OPTIONAL_DATASETS:
        if dataset_name in frames:
            _persist(frames, dataset_name, run_id, stored)

    legal = frames["shkp_legal_ownership_observations"]
    registry = frames["shkp_project_registry"]
    priority = registry.loc[
        registry.get("srpe_development_id", pd.Series(dtype="string")).astype("string").isin(SHKP_PRIORITY_PHASE_IDS)
    ]
    return {
        "mode": "live",
        "run_id": run_id,
        "dataset_counts": {name: int(len(frame)) for name, frame in frames.items()},
        "normalized": stored,
        "ownership_observation_rows": int(len(legal)),
        "attribution_decision_rows": int(len(frames["shkp_phase_attribution_decisions"])),
        "approved_attribution_decision_rows": int(
            frames["shkp_phase_attribution_decisions"]
            .get("ownership_attribution_ready", pd.Series(dtype=bool))
            .fillna(False)
            .astype(bool)
            .sum()
        ),
        "ownership_ready_phase_count": int(
            registry.get("ownership_attribution_ready", pd.Series(dtype=bool)).astype(bool).sum()
        ),
        "priority_phase_count": int(len(priority)),
        "priority_phase_ready_count": int(
            priority.get("ownership_attribution_ready", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()
        ),
        "priority_phase_gate": {
            str(row.get("srpe_development_id")): {
                "ownership_status": row.get("ownership_status"),
                "ownership_attribution_ready": bool(row.get("ownership_attribution_ready")),
            }
            for row in priority.to_dict("records")
        },
        "attribution_policy": "phase-specific effective interval required; snapshots/JV/grouped interest do not promote",
    }


def run_shkp_history_milestones(*, timeout: float = 60) -> dict[str, Any]:
    """Fetch and persist the official SHKP History and Milestones evidence layer."""
    run_id = str(uuid.uuid4())
    frame = shkp.fetch_shkp_history_milestones(timeout=timeout)
    stored: dict[str, Any] = {}
    _persist({"shkp_history_milestones": frame}, "shkp_history_milestones", run_id, stored)
    srpe_index = load_latest_normalized("srpe_development_index")
    crosswalk = shkp.build_shkp_history_milestone_crosswalk(frame, srpe_index)
    _persist({"shkp_history_milestone_identity_crosswalk": crosswalk}, "shkp_history_milestone_identity_crosswalk", run_id, stored)
    return {
        "mode": "shkp_history_milestones",
        "run_id": run_id,
        "records": int(len(frame)),
        "year_min": int(frame["milestone_year"].min()),
        "year_max": int(frame["milestone_year"].max()),
        "normalized": stored.get("shkp_history_milestones"),
        "crosswalk_normalized": stored.get("shkp_history_milestone_identity_crosswalk"),
        "crosswalk_rows": int(len(crosswalk)),
        "crosswalk_match_status_counts": crosswalk.get("match_status", pd.Series(dtype="string")).value_counts().to_dict(),
        "source_url": shkp.SHKP_HISTORY_MILESTONES_URL,
        "phase_level_ownership_ready": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the bounded SHKP/SRPE project-universe catalog")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("catalog", "import-shkp-land-registry", "import-shkp-phase-decisions"),
        default="catalog",
    )
    parser.add_argument("csv_path", nargs="?", type=Path)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--max-manifest-developments", type=int, default=10)
    parser.add_argument("--site-project-limit", type=int, default=50)
    parser.add_argument("--skip-site-facts", action="store_true")
    parser.add_argument("--skip-deep-documents", action="store_true")
    parser.add_argument("--offline", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "import-shkp-land-registry":
        if args.csv_path is None:
            raise SystemExit("import-shkp-land-registry requires a CSV path")
        result = import_shkp_land_registry_csv(args.csv_path)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.command == "import-shkp-phase-decisions":
        if args.csv_path is None:
            raise SystemExit("import-shkp-phase-decisions requires a CSV path")
        result = import_shkp_phase_attribution_decisions_csv(args.csv_path)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    result = run_shkp_catalog(
        timeout=args.timeout,
        max_pages=args.max_pages,
        max_manifest_developments=args.max_manifest_developments,
        site_project_limit=args.site_project_limit,
        skip_site_facts=args.skip_site_facts,
        skip_deep_documents=args.skip_deep_documents,
        offline=args.offline,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
