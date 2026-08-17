"""High-recall SHKP/SRPE phase discovery.

The strict SHKP crosswalk is intentionally conservative, which is useful for
legal attribution but too narrow for the first pass of a Hong Kong project
universe.  This module provides a separate, reviewable candidate layer across
the full SRPE index.  It uses existing official SHKP directory, annual-report,
history, completion-schedule and pipeline evidence plus transparent name
matching.  It never infers a legal stake and never opens the sales gate.

The output is deliberately useful for routing transaction-register work:
``likely_shkp`` means an explicit official SHKP/role row is already linked to
the SRPE id; ``possible_shkp_high_recall`` means a high-recall name/official
evidence match that still needs a quick web check; and
``identity_unknown_owner_evidence_missing`` means only the SRPE parent row was
observed.  The last state is not a negative ownership conclusion.
"""

from __future__ import annotations

import json
import re
import uuid
from difflib import SequenceMatcher
from typing import Any, Iterable

import pandas as pd

from .sources.shkp import SHKP_CURATED_NON_SHKP_SRPE_PHASES
from .storage import load_latest_normalized, save_normalized_dataset


HIGH_RECALL_DATASET = "shkp_high_recall_phase_candidates"
HIGH_RECALL_OWNERSHIP_DATASET = "shkp_high_recall_ownership_review"

HIGH_RECALL_COLUMNS = [
    "candidate_id",
    "srpe_development_id",
    "development_name_en",
    "phase_name_en",
    "address_en",
    "planning_area_en",
    "active",
    "official_website",
    "candidate_status",
    "identity_evidence_status",
    "match_confidence",
    "match_score",
    "match_method",
    "evidence_source_types",
    "evidence_labels_json",
    "evidence_urls_json",
    "explicit_evidence_rows",
    "fuzzy_evidence_rows",
    "candidate_count_for_name",
    "transaction_route_status",
    "strict_ownership_promotion_status",
    "recommended_next_step",
    "source_vintage_policy",
    "last_verified_at",
]

HIGH_RECALL_OWNERSHIP_COLUMNS = [
    "registry_key",
    "srpe_development_id",
    "high_recall_status",
    "high_recall_identity_evidence_status",
    "high_recall_confidence",
    "high_recall_match_score",
    "high_recall_match_method",
    "high_recall_evidence_source_types",
    "high_recall_evidence_rows",
    "high_recall_evidence_urls_json",
    "high_recall_next_step",
    "strict_ownership_promotion_status",
    "last_verified_at",
]

_STOPWORDS = {
    "a",
    "and",
    "at",
    "development",
    "estate",
    "for",
    "land",
    "lot",
    "no",
    "of",
    "phase",
    "phases",
    "project",
    "the",
    "town",
    "road",
    "residential",
}


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _normalise(value: Any) -> str:
    text = _text(value).lower().replace("&", " and ")
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: Any) -> set[str]:
    text = _normalise(value)
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text)
        if token not in _STOPWORDS and (len(token) >= 3 or token.isdigit())
    }


def _label_candidates(frame: pd.DataFrame | None, source_type: str) -> Iterable[dict[str, Any]]:
    """Yield normalised evidence labels without assuming one schema."""
    if frame is None or frame.empty:
        return []
    label_columns = (
        "marketing_name",
        "project_label",
        "milestone_summary",
        "development_name_en",
        "srpe_development_name",
        "phase_name_en",
        "srpe_phase_name",
        "project_name",
    )
    id_columns = ("srpe_development_id", "development_id", "srpe_dev_id")
    status_columns = ("match_status", "candidate_status", "evidence_status", "status")
    url_columns = (
        "source_url",
        "shkp_source_url",
        "document_url",
        "annual_document_url",
        "phase_identity_source_url",
        "source_page_url",
    )
    rows: list[dict[str, Any]] = []
    for record in frame.to_dict("records"):
        phase_id = next((_text(record.get(column)) for column in id_columns if _text(record.get(column))), "")
        # Curated exclusions verified against official developer records
        # (2026-08-09).  These SRPE phases are owned by other developers
        # (Lohas Park Wheelock/Nan Fung/Sino phases, Henderson's One
        # Innovale); the ambiguous annual labels must not re-enter the
        # candidate queue through the raw crosswalk layer.
        if phase_id in SHKP_CURATED_NON_SHKP_SRPE_PHASES:
            continue
        labels = list(dict.fromkeys(_text(record.get(column)) for column in label_columns if _text(record.get(column))))
        if not labels:
            continue
        status = next((_text(record.get(column)) for column in status_columns if _text(record.get(column))), "")
        urls = list(dict.fromkeys(_text(record.get(column)) for column in url_columns if _text(record.get(column))))
        for label in labels:
            rows.append(
                {
                    "source_type": source_type,
                    "label": label,
                    "normalised_label": _normalise(label),
                    "tokens": _tokens(label),
                    "srpe_development_id": phase_id,
                    "status": status,
                    "urls": urls,
                }
            )
    return rows


def _score_name(srpe_name: str, evidence_label: str) -> tuple[float, str]:
    left = _normalise(srpe_name)
    right = _normalise(evidence_label)
    if not left or not right:
        return 0.0, "none"
    # Completion schedules and PDF tables sometimes expose row markers such
    # as ``(4)`` or short lot fragments.  They are not project names and can
    # otherwise look like high-ratio substrings of a long SRPE label.
    if right.isdigit() or len(right) < 5:
        return 0.0, "none"
    if left == right:
        return 1.0, "official_label_exact"
    if min(len(left), len(right)) >= 6 and (left in right or right in left):
        return 0.94, "official_label_substring"
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    shared = left_tokens & right_tokens
    if shared:
        strong_shared = {token for token in shared if len(token) >= 6}
        if strong_shared:
            coverage = len(strong_shared) / max(1, min(len(left_tokens), len(right_tokens)))
            if coverage >= 0.5:
                return 0.86, "official_label_strong_token_overlap"
            # One distinctive project name (for example, CULLINAN or NOVO)
            # is enough for a high-recall queue, but remains review-only.
            if len(strong_shared) == 1:
                return 0.78, "official_label_distinctive_token"
    ratio = SequenceMatcher(None, left, right).ratio()
    if min(len(left), len(right)) >= 5 and ratio >= 0.82:
        return ratio, "official_label_sequence_match"
    return ratio, "none"


def _phase_name(record: dict[str, Any]) -> str:
    return " / ".join(
        value
        for value in (_text(record.get("development_name_en")), _text(record.get("phase_name_en")))
        if value
    )


def _row_urls(record: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ("source_urls_json", "evidence_urls_json"):
        raw = record.get(key)
        if isinstance(raw, list):
            urls.extend(_text(value) for value in raw)
        elif _text(raw).startswith("["):
            try:
                parsed = json.loads(_text(raw))
                if isinstance(parsed, list):
                    urls.extend(_text(value) for value in parsed)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
    return list(dict.fromkeys(value for value in urls if value))


def _route_status(
    phase_id: str,
    manifest: pd.DataFrame | None,
) -> str:
    if manifest is None or manifest.empty or "srpe_development_id" not in manifest.columns:
        return "manifest_not_observed"
    rows = manifest.loc[manifest["srpe_development_id"].astype(str).eq(phase_id)]
    if rows.empty:
        return "manifest_not_observed"
    categories = set(rows.get("document_category", pd.Series(dtype="string")).astype(str))
    if "register_of_transactions" in categories:
        return "transaction_register_available"
    return "manifest_available_no_transaction_register"


def build_shkp_high_recall_phase_candidates(
    srpe_index: pd.DataFrame,
    *,
    property_catalog: pd.DataFrame | None = None,
    current_crosswalk: pd.DataFrame | None = None,
    annual_crosswalk: pd.DataFrame | None = None,
    historical_annual_crosswalk: pd.DataFrame | None = None,
    history_crosswalk: pd.DataFrame | None = None,
    pipeline_crosswalk: pd.DataFrame | None = None,
    completion_crosswalk: pd.DataFrame | None = None,
    site_vendor_crosswalk: pd.DataFrame | None = None,
    manifest: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a broad one-row-per-SRPE-phase SHKP candidate queue.

    The function is intentionally deterministic and network-free.  Official
    source URLs already captured by the ingestion layers are carried into the
    output, while name matching is marked as quick-review evidence rather than
    ownership proof.
    """
    if srpe_index is None or srpe_index.empty:
        return pd.DataFrame(columns=HIGH_RECALL_COLUMNS)

    evidence_frames = [
        ("current_shkp_directory", property_catalog),
        ("current_shkp_crosswalk", current_crosswalk),
        ("annual_report", annual_crosswalk),
        ("historical_annual_report", historical_annual_crosswalk),
        ("history_milestones", history_crosswalk),
        ("pipeline_disclosure", pipeline_crosswalk),
        ("completion_schedule", completion_crosswalk),
        ("project_site_vendor", site_vendor_crosswalk),
    ]
    labels: list[dict[str, Any]] = []
    for source_type, frame in evidence_frames:
        labels.extend(_label_candidates(frame, source_type))

    # De-duplicate repeated report rows while retaining the strongest URL and
    # source-type evidence in the audit columns.
    deduped_labels: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in labels:
        key = (row["source_type"], row["normalised_label"], row["srpe_development_id"])
        previous = deduped_labels.get(key)
        if previous is None:
            deduped_labels[key] = row
        else:
            previous["urls"] = list(dict.fromkeys(previous["urls"] + row["urls"]))
            if not previous["status"]:
                previous["status"] = row["status"]
    labels = list(deduped_labels.values())

    rows: list[dict[str, Any]] = []
    for raw in srpe_index.to_dict("records"):
        phase_id = _text(raw.get("development_id"))
        if not phase_id:
            continue
        # Curated exclusions are verified non-SHKP phases (2026-08-09).
        # They must not re-enter the queue through name-substring fuzzy
        # matching (e.g. "LOHAS PARK" matching an unrelated SHKP label), so
        # both explicit and fuzzy evidence are suppressed.
        if phase_id in SHKP_CURATED_NON_SHKP_SRPE_PHASES:
            rows.append(
                {
                    "candidate_id": f"shkp-high-recall:{phase_id}",
                    "srpe_development_id": phase_id,
                    "development_name_en": raw.get("development_name_en") or raw.get("display_name"),
                    "phase_name_en": raw.get("phase_name_en"),
                    "address_en": raw.get("address_en"),
                    "planning_area_en": raw.get("planning_area_en"),
                    "active": raw.get("active"),
                    "official_website": raw.get("official_website"),
                    "candidate_status": "identity_unknown_owner_evidence_missing",
                    "identity_evidence_status": "curated_non_shkp_exclusion",
                    "match_confidence": "none",
                    "match_score": 0.0,
                    "match_method": "curated_exclusion",
                    "evidence_source_types": "curated_non_shkp_reason",
                    "evidence_labels_json": "[]",
                    "evidence_urls_json": "[]",
                    "explicit_evidence_rows": 0,
                    "fuzzy_evidence_rows": 0,
                    "candidate_count_for_name": 0,
                    "transaction_route_status": _route_status(phase_id, manifest),
                    "strict_ownership_promotion_status": "blocked_high_recall_identity_only",
                    "recommended_next_step": "excluded; owned by another developer per official records",
                    "source_vintage_policy": "latest_non_empty_local_official_snapshots; quick-review layer",
                    "last_verified_at": pd.Timestamp.now(tz="UTC").isoformat(),
                }
            )
            continue
        phase_name = _phase_name(raw)
        explicit: list[dict[str, Any]] = [
            row for row in labels if row["srpe_development_id"] == phase_id
        ]
        fuzzy: list[dict[str, Any]] = []
        for row in labels:
            score, method = _score_name(phase_name, row["label"])
            if score >= 0.78 and method != "none":
                match = dict(row)
                match["score"] = score
                match["method"] = method
                fuzzy.append(match)
        # A fuzzy match is only one piece of evidence; repeated labels are
        # collapsed and the max score is retained for routing.
        fuzzy = sorted(fuzzy, key=lambda row: (-float(row["score"]), row["source_type"], row["label"]))
        best_fuzzy_score = float(fuzzy[0]["score"]) if fuzzy else 0.0
        best_fuzzy = fuzzy[0] if fuzzy else None
        evidence = explicit + fuzzy[:8]
        source_types = list(dict.fromkeys(row["source_type"] for row in evidence))
        evidence_labels = list(dict.fromkeys(row["label"] for row in evidence))
        urls = list(dict.fromkeys(url for row in evidence for url in row.get("urls", []) if url))
        statuses = {row["status"] for row in explicit if row["status"]}
        current_exact = any(
            row["source_type"] == "current_shkp_crosswalk" and row["status"] == "matched"
            for row in explicit
        )
        current_review = any(
            row["source_type"] in {"current_shkp_crosswalk", "current_shkp_directory"}
            and row["status"] in {"ambiguous", "matched_needs_review"}
            for row in explicit
        )
        explicit_nonnegative = bool(explicit) and not statuses.intersection({"unmatched", "not_observed"})
        if current_exact or (explicit_nonnegative and len(explicit) == 1):
            candidate_status = "likely_shkp"
            identity_status = "official_shkp_evidence_linked"
            confidence = "high" if current_exact else "medium"
            method = "official_current_directory_id" if current_exact else "official_crosswalk_id"
            score = 1.0 if current_exact else 0.9
            next_step = "route transaction register; keep ownership interval blocked"
        elif explicit_nonnegative or current_review or best_fuzzy_score >= 0.86:
            candidate_status = "possible_shkp_high_recall"
            identity_status = "official_evidence_or_name_match_review"
            confidence = "medium" if explicit_nonnegative or best_fuzzy_score >= 0.94 else "low"
            method = "+".join(
                dict.fromkeys(
                    [
                        *(["official_crosswalk_review"] if explicit_nonnegative else []),
                        *([best_fuzzy["method"]] if best_fuzzy else []),
                    ]
                )
            ) or "official_name_review"
            score = max(0.75, best_fuzzy_score, 0.9 if explicit_nonnegative else 0.0)
            next_step = "quick-check SHKP sales-agent/project page, then route register if confirmed"
        else:
            candidate_status = "identity_unknown_owner_evidence_missing"
            identity_status = "srpe_parent_only_no_shkp_evidence"
            confidence = "none"
            method = "srpe_parent_only"
            score = 0.0
            next_step = "search SHKP directory/annual report/project site before treating as non-SHKP"

        rows.append(
            {
                "candidate_id": f"shkp-high-recall:{phase_id}",
                "srpe_development_id": phase_id,
                "development_name_en": raw.get("development_name_en") or raw.get("display_name"),
                "phase_name_en": raw.get("phase_name_en"),
                "address_en": raw.get("address_en"),
                "planning_area_en": raw.get("planning_area_en"),
                "active": raw.get("active"),
                "official_website": raw.get("official_website"),
                "candidate_status": candidate_status,
                "identity_evidence_status": identity_status,
                "match_confidence": confidence,
                "match_score": score,
                "match_method": method,
                "evidence_source_types": "|".join(source_types) or None,
                "evidence_labels_json": json.dumps(evidence_labels, ensure_ascii=False),
                "evidence_urls_json": json.dumps(urls, ensure_ascii=False),
                "explicit_evidence_rows": int(len(explicit)),
                "fuzzy_evidence_rows": int(len(fuzzy)),
                "candidate_count_for_name": int(len(fuzzy)),
                "transaction_route_status": _route_status(phase_id, manifest),
                "strict_ownership_promotion_status": "blocked_high_recall_identity_only",
                "recommended_next_step": next_step,
                "source_vintage_policy": "latest_non_empty_local_official_snapshots; quick-review layer",
                "last_verified_at": pd.Timestamp.now(tz="UTC").isoformat(),
            }
        )
    frame = pd.DataFrame(rows, columns=HIGH_RECALL_COLUMNS)
    frame.attrs["lineage_metadata"] = {
        "lineage_type": "derived_shkp_high_recall_srpe_phase_candidates",
        "source_datasets": [name for name, data in evidence_frames if data is not None and not data.empty]
        + ["srpe_development_index"],
        "identity_policy": "high_recall_candidate_discovery_not_legal_ownership",
        "ownership_promotion": False,
        "sales_promotion": False,
    }
    return frame


def enrich_indicative_ownership_with_high_recall(
    indicative_ownership: pd.DataFrame,
    high_recall_candidates: pd.DataFrame,
) -> pd.DataFrame:
    """Attach high-recall identity status without changing numeric stakes.

    Existing numeric/JV snapshots always win.  Only rows previously labelled
    ``not_observed`` receive the new high-recall identity labels, so no rough
    name match can overwrite a sourced numeric percentage or JV state.
    """
    if indicative_ownership is None or indicative_ownership.empty:
        return indicative_ownership if indicative_ownership is not None else pd.DataFrame()
    out = indicative_ownership.copy()
    if high_recall_candidates is None or high_recall_candidates.empty:
        return out
    if "srpe_development_id" not in out.columns or "srpe_development_id" not in high_recall_candidates.columns:
        raise ValueError("indicative ownership and high-recall candidates require srpe_development_id")
    candidates = high_recall_candidates.drop_duplicates("srpe_development_id", keep="last").copy()
    candidate_columns = [
        "srpe_development_id",
        "candidate_status",
        "identity_evidence_status",
        "match_confidence",
        "match_score",
        "match_method",
        "evidence_source_types",
        "evidence_urls_json",
        "explicit_evidence_rows",
        "recommended_next_step",
    ]
    candidates = candidates[[column for column in candidate_columns if column in candidates.columns]]
    out["srpe_development_id"] = out["srpe_development_id"].astype(str)
    candidates["srpe_development_id"] = candidates["srpe_development_id"].astype(str)
    out = out.merge(candidates, on="srpe_development_id", how="left", suffixes=("", "_high_recall"))
    rename = {
        "candidate_status": "high_recall_status",
        "identity_evidence_status": "high_recall_identity_evidence_status",
        "match_confidence": "high_recall_confidence",
        "match_score": "high_recall_match_score",
        "match_method": "high_recall_match_method",
        "evidence_source_types": "high_recall_evidence_source_types",
        "evidence_urls_json": "high_recall_evidence_urls_json",
        "explicit_evidence_rows": "high_recall_evidence_rows",
        "recommended_next_step": "high_recall_next_step",
    }
    for source, target in rename.items():
        if source in out.columns:
            out = out.rename(columns={source: target})
        elif f"{source}_high_recall" in out.columns:
            out = out.rename(columns={f"{source}_high_recall": target})
        elif target not in out.columns:
            out[target] = pd.NA
    out["strict_ownership_promotion_status"] = "blocked_high_recall_identity_only"
    out["last_verified_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    base_status = out.get("indicative_owner_status", pd.Series("not_observed", index=out.index)).astype(str)
    candidate_status = out.get("high_recall_status", pd.Series("", index=out.index)).astype(str)
    eligible = base_status.eq("not_observed")
    likely = eligible & candidate_status.eq("likely_shkp")
    possible = eligible & candidate_status.eq("possible_shkp_high_recall")
    out.loc[likely, "indicative_owner_status"] = "likely_shkp_high_recall_unquantified"
    out.loc[likely, "indicative_confidence"] = out.loc[likely, "high_recall_confidence"]
    out.loc[likely, "indicative_evidence_basis"] = "official_high_recall_identity"
    out.loc[likely, "indicative_sales_use_status"] = "review_only_high_recall_identity"
    out.loc[possible, "indicative_owner_status"] = "possible_shkp_high_recall"
    out.loc[possible, "indicative_confidence"] = out.loc[possible, "high_recall_confidence"]
    out.loc[possible, "indicative_evidence_basis"] = "official_high_recall_name_or_crosswalk_review"
    out.loc[possible, "indicative_sales_use_status"] = "review_only_high_recall_identity"
    out["identity_evidence_status"] = candidate_status.map(
        {
            "likely_shkp": "official_shkp_evidence_linked",
            "possible_shkp_high_recall": "official_evidence_or_name_match_review",
            "identity_unknown_owner_evidence_missing": "srpe_parent_only_no_shkp_evidence",
        }
    ).fillna("not_evaluated")
    return out


def run_shkp_high_recall_phase_candidates() -> dict[str, Any]:
    """Build/persist the high-recall layer from latest local snapshots."""
    index = load_latest_normalized("srpe_development_index")
    if index.empty:
        raise RuntimeError("SRPE development index is missing")
    high_recall = build_shkp_high_recall_phase_candidates(
        index,
        property_catalog=load_latest_normalized("shkp_property_catalog"),
        current_crosswalk=load_latest_normalized("shkp_srpe_crosswalk"),
        annual_crosswalk=load_latest_normalized("shkp_annual_srpe_crosswalk"),
        historical_annual_crosswalk=load_latest_normalized("shkp_historical_annual_srpe_crosswalk"),
        history_crosswalk=load_latest_normalized("shkp_history_milestone_identity_crosswalk"),
        pipeline_crosswalk=load_latest_normalized("shkp_pipeline_srpe_crosswalk"),
        completion_crosswalk=load_latest_normalized("shkp_completion_schedule_crosswalk"),
        site_vendor_crosswalk=load_latest_normalized("shkp_project_site_vendor_crosswalk"),
        manifest=load_latest_normalized("shkp_current_srpe_document_manifest_backfill"),
    )
    existing_ownership = load_latest_normalized("shkp_indicative_ownership_roster")
    ownership = enrich_indicative_ownership_with_high_recall(existing_ownership, high_recall)
    run_id = f"shkp-high-recall-{uuid.uuid4()}"
    lineage = high_recall.attrs.get("lineage_metadata") or {}
    normalized = {
        HIGH_RECALL_DATASET: save_normalized_dataset(
            HIGH_RECALL_DATASET,
            high_recall,
            run_id=run_id,
            source_urls=[
                "https://www.shkp.com/en-US/our-business/hong-kong-properties",
                "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale",
                "https://www.srpe.gov.hk/opip/all_development",
            ],
            lineage_metadata=lineage,
        ),
        HIGH_RECALL_OWNERSHIP_DATASET: save_normalized_dataset(
            HIGH_RECALL_OWNERSHIP_DATASET,
            ownership,
            run_id=run_id,
            source_urls=[
                "https://www.shkp.com/en-US/our-business/hong-kong-properties",
                "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale",
                "https://www.srpe.gov.hk/opip/all_development",
            ],
            lineage_metadata={
                "lineage_type": "derived_shkp_high_recall_ownership_review",
                "parent_datasets": ["shkp_indicative_ownership_roster", HIGH_RECALL_DATASET],
                "ownership_promotion": False,
                "sales_promotion": False,
            },
        ),
        # Keep the canonical indicative roster in sync with the high-recall
        # identity labels. Numeric stake/JV fields are unchanged; this only
        # lets downstream signal builders distinguish review evidence from a
        # genuinely unobserved ownership row.
        "shkp_indicative_ownership_roster": save_normalized_dataset(
            "shkp_indicative_ownership_roster",
            ownership,
            run_id=run_id,
            source_urls=[
                "https://www.shkp.com/en-US/our-business/hong-kong-properties",
                "https://www.shkp.com/en-US/our-business/hong-kong-properties/residential-for-sale",
                "https://www.srpe.gov.hk/opip/all_development",
            ],
            lineage_metadata={
                "lineage_type": "derived_shkp_indicative_ownership_roster_with_high_recall",
                "parent_datasets": ["shkp_indicative_ownership_roster", HIGH_RECALL_DATASET],
                "ownership_promotion": False,
                "sales_promotion": False,
            },
        ),
    }
    return {
        "run_id": run_id,
        "phase_rows": int(len(high_recall)),
        "status_counts": high_recall["candidate_status"].value_counts().to_dict(),
        "route_counts": high_recall["transaction_route_status"].value_counts().to_dict(),
        "ownership_rows": int(len(ownership)),
        "ownership_status_counts": ownership.get("indicative_owner_status", pd.Series(dtype="string")).value_counts().to_dict(),
        "normalized": normalized,
        "strict_ownership_promotion": False,
    }
