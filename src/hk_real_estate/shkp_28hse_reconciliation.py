"""Auditable 28Hse new-project versus SHKP/SRPE reconciliation.

28Hse's new-project cards expose portal unit states, while SRPE exposes
phase-level statutory registers and (sometimes) price-list inventory.  The
sources do not share a guaranteed project ID, so this module only promotes an
exact, unique name/alias match.  Everything else is retained as an explicit
coverage gap or review item rather than fuzzy-matched into a false comparison.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

import pandas as pd

from .storage import load_latest_normalized, save_normalized_dataset


RECON_DATASET = "shkp_28hse_reconciliation"
SUMMARY_DATASET = "shkp_28hse_reconciliation_summary"
PRIORITY_DATASET = "shkp_ownership_review_priority"


def _norm_name(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).upper()
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff]+", "", text)


def build_shkp_28hse_reconciliation(
    hse28_projects: pd.DataFrame,
    srpe_candidates: pd.DataFrame,
    crosswalk: pd.DataFrame | None = None,
    srpe_signals: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return row-level reconciliation and a compact coverage summary."""
    hse = hse28_projects.copy() if hse28_projects is not None else pd.DataFrame()
    candidates = srpe_candidates.copy() if srpe_candidates is not None else pd.DataFrame()
    if hse.empty:
        hse = pd.DataFrame(columns=["project_name"])
    if candidates.empty:
        candidates = pd.DataFrame(columns=["srpe_development_id", "development_name_en", "phase_name_en"])

    # Only unique aliases are eligible for automatic matching.  Shared
    # marketing names remain ambiguous even when one candidate happens to be
    # currently active.
    alias_to_ids: dict[str, set[str]] = {}
    if crosswalk is not None and not crosswalk.empty:
        for row in crosswalk.to_dict("records"):
            alias = _norm_name(row.get("marketing_name"))
            phase_id = str(row.get("srpe_development_id") or "").strip()
            if alias and phase_id:
                alias_to_ids.setdefault(alias, set()).add(phase_id)
    for row in candidates.to_dict("records"):
        phase_id = str(row.get("srpe_development_id") or "").strip()
        if not phase_id:
            continue
        for value in (row.get("phase_name_en"), row.get("development_name_en")):
            alias = _norm_name(value)
            if alias:
                alias_to_ids.setdefault(alias, set()).add(phase_id)

    candidate_by_id = {
        str(row.get("srpe_development_id")): row for row in candidates.to_dict("records")
    }
    latest_signal: dict[str, dict[str, Any]] = {}
    if srpe_signals is not None and not srpe_signals.empty:
        signal = srpe_signals.copy()
        signal["phase_id"] = signal.get("srpe_development_id", signal.get("phase_id", "")).fillna("").astype(str)
        signal["period_date"] = pd.to_datetime(signal.get("period"), errors="coerce")
        for phase_id, group in signal.sort_values("period_date").groupby("phase_id"):
            if phase_id:
                latest_signal[phase_id] = group.iloc[-1].to_dict()

    rows: list[dict[str, Any]] = []
    hse_matched_ids: set[str] = set()
    for _, project in hse.iterrows():
        project_name = project.get("project_name")
        alias = _norm_name(project_name)
        ids = alias_to_ids.get(alias, set())
        if len(ids) == 1:
            phase_id = next(iter(ids))
            match_status = "exact_unique_alias"
            hse_matched_ids.add(phase_id)
        elif len(ids) > 1:
            phase_id = None
            match_status = "ambiguous_alias"
        else:
            phase_id = None
            match_status = "not_matched_current_28hse_listing"
        candidate = candidate_by_id.get(phase_id, {}) if phase_id else {}
        latest = latest_signal.get(str(phase_id), {}) if phase_id else {}
        total_units = pd.to_numeric(pd.Series([project.get("estimated_total_units")]), errors="coerce").iloc[0]
        inventory = pd.to_numeric(pd.Series([latest.get("published_inventory_units")]), errors="coerce").iloc[0]
        rows.append(
            {
                "reconciliation_id": f"hse28|{_norm_name(project_name)}|{phase_id or 'unmatched'}",
                "row_side": "hse28_project",
                "hse28_project_name": project_name,
                "hse28_project_url": project.get("project_url"),
                "hse28_status": project.get("status"),
                "hse28_total_units": total_units,
                "hse28_remaining_units": project.get("remaining_units"),
                "hse28_on_sale_units": project.get("on_sale_units"),
                "hse28_sold_units": project.get("sold_units"),
                "srpe_development_id": phase_id,
                "srpe_development_name": candidate.get("development_name_en"),
                "srpe_phase_name": candidate.get("phase_name_en"),
                "srpe_latest_period": latest.get("period"),
                "srpe_active_units_eom": latest.get("active_units_eom"),
                "srpe_published_inventory_units": inventory,
                "srpe_candidate_status": candidate.get("candidate_status"),
                "match_status": match_status,
                "unit_total_delta_hse28_minus_srpe": float(total_units - inventory) if pd.notna(total_units) and pd.notna(inventory) else None,
                "status_comparison": "comparable_only_after_exact_match" if match_status == "exact_unique_alias" else "not_comparable",
                "coverage_note": "28Hse current new-project listing is not a complete SHKP project universe; unmatched rows are retained as coverage gaps.",
            }
        )

    # Add every SRPE candidate absent from the current 28Hse new-project page,
    # making one-sided coverage visible instead of silently dropping it.
    for phase_id, candidate in candidate_by_id.items():
        if phase_id in hse_matched_ids:
            continue
        latest = latest_signal.get(phase_id, {})
        rows.append(
            {
                "reconciliation_id": f"srpe|{phase_id}|hse28_unobserved",
                "row_side": "srpe_phase",
                "hse28_project_name": None,
                "hse28_project_url": None,
                "hse28_status": None,
                "hse28_total_units": None,
                "hse28_remaining_units": None,
                "hse28_on_sale_units": None,
                "hse28_sold_units": None,
                "srpe_development_id": phase_id,
                "srpe_development_name": candidate.get("development_name_en"),
                "srpe_phase_name": candidate.get("phase_name_en"),
                "srpe_latest_period": latest.get("period"),
                "srpe_active_units_eom": latest.get("active_units_eom"),
                "srpe_published_inventory_units": latest.get("published_inventory_units"),
                "srpe_candidate_status": candidate.get("candidate_status"),
                "match_status": "srpe_phase_not_in_current_28hse_listing",
                "unit_total_delta_hse28_minus_srpe": None,
                "status_comparison": "not_comparable",
                "coverage_note": "SRPE phase has transaction-register coverage but no exact current 28Hse new-project alias.",
            }
        )

    reconciliation = pd.DataFrame(rows)
    match_counts = reconciliation["match_status"].value_counts().to_dict() if not reconciliation.empty else {}
    summary = pd.DataFrame([
        {
            "hse28_project_rows": int(len(hse)),
            "srpe_candidate_phase_rows": int(len(candidates)),
            "reconciliation_rows": int(len(reconciliation)),
            "exact_unique_matches": int(match_counts.get("exact_unique_alias", 0)),
            "ambiguous_alias_rows": int(match_counts.get("ambiguous_alias", 0)),
            "hse28_unmatched_rows": int(match_counts.get("not_matched_current_28hse_listing", 0)),
            "srpe_not_in_current_hse28_rows": int(match_counts.get("srpe_phase_not_in_current_28hse_listing", 0)),
            "unit_comparable_rows": int(reconciliation["unit_total_delta_hse28_minus_srpe"].notna().sum()) if not reconciliation.empty else 0,
            "automatic_ownership_inference": False,
            "source_scope_note": "28Hse is a current portal new-project snapshot; SRPE is a statutory phase/register layer. Non-matches are coverage/identity gaps, not zero units.",
        }
    ])
    return reconciliation, summary


def run_shkp_28hse_reconciliation() -> dict[str, Any]:
    """Persist the current 28Hse↔SRPE reconciliation contract."""
    run_id = f"shkp-28hse-reconciliation-{uuid.uuid4()}"
    hse = load_latest_normalized("hse28_new_projects_catalog")
    candidates = load_latest_normalized("shkp_srpe_phase_candidates")
    crosswalk = load_latest_normalized("shkp_srpe_crosswalk")
    signals = load_latest_normalized("shkp_srpe_project_month_signals")
    reconciliation, summary = build_shkp_28hse_reconciliation(hse, candidates, crosswalk, signals)
    lineage = {
        "lineage_type": "shkp_28hse_srpe_reconciliation",
        "source_datasets": ["hse28_new_projects_catalog", "shkp_srpe_phase_candidates", "shkp_srpe_crosswalk", "shkp_srpe_project_month_signals"],
        "automatic_ownership_inference": False,
        "match_policy": "exact_unique_alias_only",
    }
    stored = {
        RECON_DATASET: save_normalized_dataset(RECON_DATASET, reconciliation, run_id=run_id, lineage_metadata=lineage),
        SUMMARY_DATASET: save_normalized_dataset(SUMMARY_DATASET, summary, run_id=run_id, lineage_metadata=lineage),
    }
    return {"run_id": run_id, "rows": int(len(reconciliation)), "summary": summary.iloc[0].to_dict(), "normalized": stored}


def build_shkp_ownership_review_priority(
    review_queue: pd.DataFrame,
    coverage: pd.DataFrame | None = None,
    signals: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Rank ownership review rows using existing evidence and sales coverage.

    The ranking is a work queue, not an ownership decision.  Signal volume is
    only used to choose where a human review creates the most analytical value;
    it never changes ``ownership_attribution_ready``.
    """
    if review_queue is None or review_queue.empty:
        return pd.DataFrame()
    queue = review_queue.copy()
    queue["srpe_development_id"] = queue["srpe_development_id"].fillna("").astype(str)
    if coverage is not None and not coverage.empty:
        cov = coverage.copy()
        cov["srpe_development_id"] = cov["srpe_development_id"].fillna("").astype(str)
        cov = cov[[c for c in ["srpe_development_id", "dedup_event_rows", "covered_months", "observed_transaction_months", "candidate_status"] if c in cov.columns]].drop_duplicates("srpe_development_id")
        queue = queue.merge(cov, on="srpe_development_id", how="left", suffixes=("", "_signal"))
    if signals is not None and not signals.empty:
        sig = signals.copy()
        sig["srpe_development_id"] = sig["srpe_development_id"].fillna("").astype(str)
        sig["period_date"] = pd.to_datetime(sig.get("period"), errors="coerce")
        latest = sig.sort_values("period_date").groupby("srpe_development_id", as_index=False).tail(1)
        latest = latest[[c for c in ["srpe_development_id", "period", "active_units_eom", "published_inventory_units", "sales_units_gross", "candidate_status"] if c in latest.columns]].rename(columns={"candidate_status": "signal_candidate_status"})
        queue = queue.merge(latest, on="srpe_development_id", how="left")
    priority = queue.get("review_priority", pd.Series("P2", index=queue.index)).fillna("P2").astype(str)
    priority_rank = priority.map({"P0": 0, "P1": 1, "P2": 2}).fillna(9)
    queue["priority_rank"] = priority_rank
    for column in ("evidence_count", "dedup_event_rows", "covered_months", "observed_transaction_months"):
        if column not in queue.columns:
            queue[column] = 0
        queue[column] = pd.to_numeric(queue[column], errors="coerce").fillna(0)
    queue["ownership_review_status"] = queue.get("ownership_attribution_ready", False).map(
        lambda value: "approved_interval" if bool(value) else "blocked_interval_missing"
    )
    queue = queue.sort_values(
        ["priority_rank", "dedup_event_rows", "evidence_count", "srpe_development_id"],
        ascending=[True, False, False, True],
    ).reset_index(drop=True)
    queue["review_queue_rank"] = range(1, len(queue) + 1)
    return queue


def run_shkp_ownership_review_priority() -> dict[str, Any]:
    run_id = f"shkp-ownership-priority-{uuid.uuid4()}"
    queue = load_latest_normalized("shkp_ownership_review_queue")
    coverage = load_latest_normalized("shkp_srpe_signal_coverage")
    signals = load_latest_normalized("shkp_srpe_project_month_signals")
    result = build_shkp_ownership_review_priority(queue, coverage, signals)
    lineage = {
        "lineage_type": "shkp_ownership_review_priority_queue",
        "source_datasets": ["shkp_ownership_review_queue", "shkp_srpe_signal_coverage", "shkp_srpe_project_month_signals"],
        "ownership_inference": False,
        "ranking_use": "human_review_prioritization_only",
    }
    stored = save_normalized_dataset(PRIORITY_DATASET, result, run_id=run_id, lineage_metadata=lineage)
    return {"run_id": run_id, "rows": int(len(result)), "top_phase_ids": result["srpe_development_id"].head(10).tolist() if not result.empty else [], "normalized": stored}
