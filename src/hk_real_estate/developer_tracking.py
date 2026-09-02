"""Developer-agnostic project tracking contracts.

The SHKP implementation predates a multi-developer workflow and therefore
contains several issuer-specific parsers and registries.  This module holds
the stable part of the workflow: company identity, conservative SRPE
crosswalks, append-only project events, current snapshots and sales-queue
routing.  Website/API extraction remains in a per-company adapter.

The contract is deliberately evidence-first.  A missing SRPE match or a
failed page fetch is retained as an unresolved state; neither is interpreted
as a zero-sales month or a cancelled project.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

import pandas as pd


MISSING_DATA_POLICY = "unknown_is_not_zero; no_srpe_is_not_no_sales"


@dataclass(frozen=True)
class DeveloperProfile:
    """Issuer-level configuration shared by all source adapters."""

    developer_id: str
    ticker: str
    names_en: tuple[str, ...] = ()
    names_zh: tuple[str, ...] = ()
    official_domains: tuple[str, ...] = ()
    commercial_asset_scopes: tuple[str, ...] = (
        "commercial",
        "commercial_investment",
        "commercial_investment_or_bot",
        "commercial_under_development",
        "data_centre",
        "industrial",
        "office",
        "shopping_mall",
    )
    adapter_version: str = "v1"

    @property
    def normalized_ticker(self) -> str:
        return str(self.ticker).strip().upper()

    def is_commercial_scope(self, value: Any) -> bool:
        text = _clean_text(value) or ""
        return text in set(self.commercial_asset_scopes) or text.startswith("commercial")


DEVELOPER_PROPERTY_CATALOG_COLUMNS = [
    "company_id",
    "ticker",
    "asset_type",
    "subtype",
    "marketing_name",
    "district",
    "address",
    "external_project_url",
    "source_record_id",
    "source_page_url",
    "source_url",
    "listed_status",
    "raw_langcode",
    "page_number",
    "display_order",
    "fetched_at",
    "source_adapter",
]

DEVELOPER_IDENTITY_COLUMNS = [
    "identity_evidence_id",
    "company_id",
    "ticker",
    "project_label",
    "aliases_json",
    "asset_scope",
    "srpe_development_id",
    "srpe_phase_name",
    "match_status",
    "match_confidence",
    "candidate_count",
    "lot_no",
    "address",
    "ownership_pct_snapshot",
    "ownership_scenario_status",
    "source_url",
    "source_urls_json",
    "source_dataset",
    "evidence_status",
    "observed_at",
    "missing_data_policy",
]

DEVELOPER_PIPELINE_COLUMNS = [
    "pipeline_registry_key",
    "company_id",
    "ticker",
    "project_label",
    "project_state",
    "asset_scope",
    "geography",
    "publication_date",
    "expected_launch_window",
    "expected_completion_window",
    "srpe_candidate_ids",
    "linked_srpe_development_id",
    "srpe_match_status",
    "evidence_status",
    "evidence_context",
    "source_url",
    "source_urls_json",
    "source_dataset",
    "observed_at",
    "missing_data_policy",
]

DEVELOPER_EVENT_COLUMNS = [
    "company_id",
    "ticker",
    "event_id",
    "event_key",
    "canonical_project_id",
    "project_label",
    "aliases_json",
    "asset_scope",
    "event_type",
    "event_date",
    "event_date_semantics",
    "state_before",
    "state_after",
    "lot_no",
    "address",
    "srpe_development_id",
    "srpe_phase_name",
    "units",
    "gfa_sqft",
    "expected_launch_window",
    "expected_completion_window",
    "ownership_low_pct",
    "ownership_base_pct",
    "ownership_high_pct",
    "ownership_scenario_status",
    "source_url",
    "source_urls_json",
    "source_dataset",
    "evidence_status",
    "evidence_key",
    "sales_queue_status",
    "observed_at",
    "missing_data_policy",
]

DEVELOPER_SNAPSHOT_COLUMNS = [
    "company_id",
    "ticker",
    "canonical_project_id",
    "project_label",
    "aliases_json",
    "asset_scope",
    "current_state",
    "state_event_date",
    "state_event_type",
    "lot_no",
    "address",
    "srpe_development_id",
    "srpe_phase_name",
    "units",
    "gfa_sqft",
    "expected_launch_window",
    "expected_completion_window",
    "ownership_low_pct",
    "ownership_base_pct",
    "ownership_high_pct",
    "ownership_scenario_status",
    "sales_queue_status",
    "coverage_status",
    "last_event_id",
    "last_observed_at",
    "source_urls_json",
    "missing_data_policy",
]

DEVELOPER_SALES_QUEUE_COLUMNS = [
    "company_id",
    "ticker",
    "canonical_project_id",
    "project_label",
    "asset_scope",
    "srpe_development_id",
    "srpe_phase_name",
    "eligibility_status",
    "queue_status",
    "eligibility_reason",
    "coverage_status",
    "source_urls_json",
    "last_verified_at",
    "missing_data_policy",
]


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    result = str(value).strip()
    return result or None


def _normalized_name(value: Any) -> str:
    text = (_clean_text(value) or "").casefold()
    text = re.sub(r"[\u2018\u2019'`\"]", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
    return text


def _is_generic_phase_label(value: Any) -> bool:
    """Return True for phase labels that are not project identity evidence."""
    text = (_clean_text(value) or "").casefold().strip()
    if not text:
        return False
    return bool(
        re.fullmatch(r"(?:phase|ph\.?|stage|part)\s*[a-z0-9ivx\-]+", text)
        or re.fullmatch(r"第?\s*[一二三四五六七八九十0-9ivx\-]+\s*期", text)
    )


def _split_ids(value: Any) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []
    return list(dict.fromkeys(part.strip() for part in text.split("|") if part.strip()))


def _normalize_date(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    parsed = pd.to_datetime(text, errors="coerce", utc=True)
    if pd.isna(parsed):
        return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else None
    return parsed.date().isoformat()


def _source_urls(*values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        values_to_scan = value if isinstance(value, (list, tuple, set)) else [value]
        for item in values_to_scan:
            text = _clean_text(item)
            if not text:
                continue
            # Adapters often receive a persisted ``source_urls_json`` value.
            # Treat a JSON array as provenance, not as one literal URL.  If it
            # is malformed, retain the original string so provenance is never
            # silently discarded.
            if text.startswith("["):
                try:
                    parsed = json.loads(text)
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed = None
                if isinstance(parsed, list):
                    for nested in parsed:
                        nested_text = _clean_text(nested)
                        if nested_text and nested_text not in result:
                            result.append(nested_text)
                    continue
            if text not in result:
                result.append(text)
    return result


def normalize_developer_catalog(
    profile: DeveloperProfile,
    frame: pd.DataFrame | None,
    *,
    source_adapter: str | None = None,
) -> pd.DataFrame:
    """Normalize an adapter's catalog while retaining unknown fields nowhere."""
    source = frame.copy() if frame is not None else pd.DataFrame()
    source = source.reset_index(drop=True)
    for column in DEVELOPER_PROPERTY_CATALOG_COLUMNS:
        if column not in source.columns:
            source[column] = pd.NA
    source["company_id"] = profile.developer_id
    source["ticker"] = profile.normalized_ticker
    if source_adapter:
        source["source_adapter"] = source_adapter
    if not source.empty and "source_record_id" in source.columns:
        # Do not collapse every record with a missing ID into one row.  Some
        # adapters can discover a valid title/address before the upstream CMS
        # exposes a stable item id; those rows remain separate until an
        # explicit id is available.
        record_ids = source["source_record_id"].astype("string")
        has_id = record_ids.notna() & record_ids.str.strip().ne("")
        dedupe_key = record_ids.where(has_id, "__missing_source_record_id__" + source.index.astype(str))
        source = source.loc[~dedupe_key.duplicated(keep="last")]
    return source.reindex(columns=DEVELOPER_PROPERTY_CATALOG_COLUMNS).reset_index(drop=True)


def _asset_scope_from_row(row: Mapping[str, Any]) -> str:
    explicit = _clean_text(row.get("asset_scope"))
    if explicit:
        return explicit
    asset_type = (_clean_text(row.get("asset_type")) or "").casefold()
    if asset_type == "residential_for_sale":
        return "residential_first_hand"
    if asset_type == "residential_for_lease":
        return "residential_investment"
    if asset_type in {"office", "shopping_mall", "industrial", "hotel"}:
        return "commercial_investment"
    return "residential_first_hand_or_unknown"


def _is_non_first_hand_residential(scope: Any) -> bool:
    value = _clean_text(scope) or ""
    return value in {"residential_investment", "residential_for_lease", "residential_rental"}


def _fallback_project_id(profile: DeveloperProfile, label: Any) -> str:
    """Stable unresolved-project key shared by catalog/pipeline/identity rows."""
    return f"{profile.developer_id}:project:{_normalized_name(label)}"


def build_developer_identity_crosswalk(
    profile: DeveloperProfile,
    observations: pd.DataFrame | None,
    srpe_index: pd.DataFrame | None,
    *,
    registry: pd.DataFrame | None = None,
    source_dataset: str = "developer_property_catalog",
    observed_at: str | None = None,
) -> pd.DataFrame:
    """Conservatively match catalog/pipeline labels to SRPE phases.

    Only exact normalized names or explicit registry aliases are used.  A
    registry hit without an SRPE phase remains ``registry_known_srpe_pending``
    and is never promoted to a sales queue by itself.
    """
    source = observations.copy() if observations is not None else pd.DataFrame()
    srpe = srpe_index.copy() if srpe_index is not None else pd.DataFrame()
    registry_frame = registry.copy() if registry is not None else pd.DataFrame()
    now = observed_at or datetime.now(timezone.utc).isoformat()

    srpe_by_name: dict[str, list[dict[str, Any]]] = {}
    for row in srpe.to_dict("records"):
        for field in ("display_name", "development_name_en", "development_name_zh", "phase_name_en", "phase_name_zh"):
            if field.startswith("phase_name") and _is_generic_phase_label(row.get(field)):
                continue
            key = _normalized_name(row.get(field))
            if key:
                srpe_by_name.setdefault(key, []).append(row)

    registry_by_name: dict[str, list[dict[str, Any]]] = {}
    if not registry_frame.empty:
        ticker_series = registry_frame.get("stock_code", pd.Series(dtype=object)).astype(str).str.zfill(4)
        for record, stock_code in zip(registry_frame.to_dict("records"), ticker_series):
            if stock_code != profile.normalized_ticker.replace(".HK", "").zfill(4):
                continue
            aliases = [record.get("project_name_en"), record.get("project_name_zh")]
            aliases.extend((_clean_text(record.get("project_aliases")) or "").split("|"))
            for value in aliases:
                key = _normalized_name(value)
                if key:
                    registry_by_name.setdefault(key, []).append(record)

    rows: list[dict[str, Any]] = []
    for index, record in enumerate(source.to_dict("records")):
        label = _clean_text(record.get("project_label") or record.get("marketing_name") or record.get("title"))
        if not label:
            continue
        aliases = [record.get("phase_name"), record.get("project_name_en"), record.get("project_name_zh")]
        aliases.extend((_clean_text(record.get("project_aliases")) or "").split("|"))
        name_keys = list(dict.fromkeys(_normalized_name(value) for value in [label, *aliases] if _normalized_name(value)))
        candidates: dict[str, dict[str, Any]] = {}
        for key in name_keys:
            for candidate in srpe_by_name.get(key, []):
                identifier = _clean_text(candidate.get("development_id"))
                if identifier:
                    candidates[identifier] = candidate
        registry_rows = [item for key in name_keys for item in registry_by_name.get(key, [])]
        candidate_ids = list(candidates)
        explicit_ids = _split_ids(record.get("srpe_development_id") or record.get("linked_srpe_development_id"))
        for identifier in explicit_ids:
            if identifier in {str(row.get("development_id")) for row in srpe.to_dict("records")}:  # exact only
                candidate_ids.append(identifier)
        candidate_ids = list(dict.fromkeys(candidate_ids))
        if len(candidate_ids) == 1:
            match_status, confidence = "matched_needs_review", "high"
            srpe_id = candidate_ids[0]
            srpe_row = candidates.get(srpe_id) or next(
                (item for item in srpe.to_dict("records") if str(item.get("development_id")) == srpe_id),
                {},
            )
        elif len(candidate_ids) > 1:
            match_status, confidence, srpe_id, srpe_row = "ambiguous", "low", None, {}
        elif registry_rows:
            match_status, confidence, srpe_id, srpe_row = "registry_known_srpe_pending", "medium", None, {}
        else:
            match_status, confidence, srpe_id, srpe_row = "unmatched", "unmatched", None, {}
        ownership_values = pd.to_numeric(
            pd.Series([item.get("ownership_pct") for item in registry_rows]), errors="coerce"
        ).dropna().tolist()
        ownership = float(pd.Series(ownership_values).median()) if ownership_values else None
        scenario_status = "observed_snapshot_not_interval" if ownership is not None else "not_observed"
        urls = _source_urls(record.get("source_url"), record.get("source_page_url"), record.get("external_project_url"))
        rows.append(
            {
                "identity_evidence_id": f"{profile.developer_id}:identity:{index}:{_normalized_name(label)}",
                "company_id": profile.developer_id,
                "ticker": profile.normalized_ticker,
                "project_label": label,
                "aliases_json": json.dumps(list(dict.fromkeys(_clean_text(value) for value in aliases if _clean_text(value))), ensure_ascii=False),
                "asset_scope": _asset_scope_from_row(record),
                "srpe_development_id": srpe_id,
                "srpe_phase_name": _clean_text(srpe_row.get("phase_name_en") or srpe_row.get("phase_name_zh")),
                "match_status": match_status,
                "match_confidence": confidence,
                "candidate_count": len(candidate_ids),
                "lot_no": _clean_text(record.get("lot_no") or record.get("lot_no_raw")),
                "address": _clean_text(record.get("address") or record.get("development_address") or record.get("district")),
                "ownership_pct_snapshot": ownership,
                "ownership_scenario_status": scenario_status,
                "source_url": urls[0] if urls else None,
                "source_urls_json": json.dumps(urls, ensure_ascii=False),
                "source_dataset": source_dataset,
                "evidence_status": "found" if match_status != "unmatched" else "not_observed",
                "observed_at": now,
                "missing_data_policy": MISSING_DATA_POLICY,
            }
        )
    result = pd.DataFrame(rows, columns=DEVELOPER_IDENTITY_COLUMNS)
    result.attrs["lineage_metadata"] = {
        "lineage_type": "developer_exact_identity_crosswalk",
        "company_id": profile.developer_id,
        "ticker": profile.normalized_ticker,
        "match_policy": "exact_normalized_name_or_explicit_registry_alias_only",
        "ownership_inference": False,
        "missing_data_policy": MISSING_DATA_POLICY,
    }
    return result


def _srpe_lifecycle(row: Mapping[str, Any]) -> str:
    deleted = str(row.get("srpe_is_deleted") or row.get("isDeleted") or "").casefold()
    active = str(row.get("active") or "").casefold()
    if deleted in {"y", "yes", "1", "true"}:
        return "deleted"
    if _clean_text(row.get("srpe_date_complete_sales") or row.get("dateCompleteSales")):
        return "completed"
    if active in {"y", "yes", "1", "true"}:
        return "active"
    if _clean_text(row.get("srpe_date_suspend_sales") or row.get("dateSuspendSales")):
        return "suspended"
    if active in {"n", "no", "0", "false"}:
        return "inactive"
    return "unknown"


def _project_state(value: Any) -> str | None:
    return {
        "planned_launch_10m": "planned_launch",
        "planned_sale_10m": "planned_launch",
        "planned_launch": "planned_launch",
        "under_development": "under_development",
        "planned": "planned_launch",
        "current_listing": "active_catalog_listing",
        "for_sale": "active_catalog_listing",
        "for_lease": "investment_asset_listed",
    }.get((_clean_text(value) or "").casefold())


def build_developer_project_events(
    profile: DeveloperProfile,
    *,
    pipeline: pd.DataFrame | None = None,
    identity: pd.DataFrame | None = None,
    srpe_index: pd.DataFrame | None = None,
    property_catalog: pd.DataFrame | None = None,
    prior_events: pd.DataFrame | None = None,
    ownership_observations: pd.DataFrame | None = None,
    observed_at: str | None = None,
) -> pd.DataFrame:
    """Build the generic append-only event log for one developer."""
    pipeline_frame = pipeline.copy() if pipeline is not None else pd.DataFrame()
    identity_frame = identity.copy() if identity is not None else pd.DataFrame()
    srpe_frame = srpe_index.copy() if srpe_index is not None else pd.DataFrame()
    catalog_frame = property_catalog.copy() if property_catalog is not None else pd.DataFrame()
    prior_frame = prior_events.copy() if prior_events is not None else pd.DataFrame()
    now = observed_at or datetime.now(timezone.utc).isoformat()
    srpe_by_id = {
        str(row.get("development_id")): row
        for row in srpe_frame.to_dict("records")
        if _clean_text(row.get("development_id"))
    }
    identity_by_label: dict[str, list[dict[str, Any]]] = {}
    for row in identity_frame.to_dict("records"):
        key = _normalized_name(row.get("project_label"))
        if key:
            identity_by_label.setdefault(key, []).append(row)
    ownership_by_phase: dict[str, tuple[float | None, float | None, float | None, str]] = {}
    if ownership_observations is not None and not ownership_observations.empty:
        ownership_frame = ownership_observations.copy()
        # A malformed ownership input must not create a synthetic "nan"
        # phase bucket or raise while the rest of the developer run is still
        # usable.  Rows without a phase id are retained by the input audit but
        # are deliberately excluded from phase-level attribution.
        if "srpe_development_id" not in ownership_frame.columns:
            ownership_frame["srpe_development_id"] = pd.NA
        if "ownership_pct" not in ownership_frame.columns:
            ownership_frame["ownership_pct"] = pd.NA
        for phase_id, group in ownership_frame.groupby("srpe_development_id", dropna=False):
            values = pd.to_numeric(group.get("ownership_pct"), errors="coerce").dropna().tolist()
            if values and _clean_text(phase_id):
                ownership_by_phase[str(phase_id)] = (
                    float(min(values)),
                    float(pd.Series(values).median()),
                    float(max(values)),
                    "observed_snapshot_not_interval" if len(set(values)) == 1 else "observed_range_not_interval",
                )

    rows: list[dict[str, Any]] = []

    def ownership(phase_id: Any) -> tuple[float | None, float | None, float | None, str]:
        return ownership_by_phase.get(str(phase_id), (None, None, None, "not_observed"))

    def find_linked_id(record: Mapping[str, Any]) -> str | None:
        explicit = _clean_text(record.get("linked_srpe_development_id") or record.get("srpe_development_id"))
        if explicit and explicit in srpe_by_id:
            return explicit
        candidate_ids = _split_ids(record.get("srpe_candidate_ids"))
        if len(candidate_ids) == 1 and candidate_ids[0] in srpe_by_id:
            return candidate_ids[0]
        matches = {
            _clean_text(item.get("srpe_development_id"))
            for item in identity_by_label.get(_normalized_name(record.get("project_label") or record.get("marketing_name")), [])
            if _clean_text(item.get("srpe_development_id")) and item.get("match_status") not in {"ambiguous", "unmatched"}
        }
        return next(iter(matches)) if len(matches) == 1 else None

    def append_event(
        *,
        canonical_id: str,
        label: Any,
        event_type: str,
        event_date: Any,
        event_date_semantics: str,
        state_after: Any = None,
        srpe_id: Any = None,
        phase_name: Any = None,
        asset_scope: Any = None,
        lot_no: Any = None,
        address: Any = None,
        units: Any = None,
        gfa_sqft: Any = None,
        expected_launch_window: Any = None,
        expected_completion_window: Any = None,
        source_url: Any = None,
        source_urls: Iterable[Any] = (),
        source_dataset: str,
        evidence_status: Any,
        evidence_key: Any,
        sales_queue_status: Any,
        ownership_values: tuple[float | None, float | None, float | None, str],
        aliases: Iterable[Any] = (),
    ) -> None:
        urls = _source_urls(source_url, source_urls)
        date_value = _normalize_date(event_date)
        payload = "|".join(
            _clean_text(value) or ""
            for value in (profile.developer_id, canonical_id, event_type, date_value, evidence_key, srpe_id, state_after)
        )
        key = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        rows.append(
            {
                "company_id": profile.developer_id,
                "ticker": profile.normalized_ticker,
                "event_id": f"{profile.developer_id}-developer-event-{key[:20]}",
                "event_key": key,
                "canonical_project_id": canonical_id,
                "project_label": _clean_text(label),
                "aliases_json": json.dumps(list(dict.fromkeys(_clean_text(value) for value in aliases if _clean_text(value))), ensure_ascii=False),
                "asset_scope": _clean_text(asset_scope) or "residential_first_hand_or_unknown",
                "event_type": event_type,
                "event_date": date_value,
                "event_date_semantics": event_date_semantics,
                "state_before": None,
                "state_after": _clean_text(state_after),
                "lot_no": _clean_text(lot_no),
                "address": _clean_text(address),
                "srpe_development_id": _clean_text(srpe_id),
                "srpe_phase_name": _clean_text(phase_name),
                "units": units,
                "gfa_sqft": gfa_sqft,
                "expected_launch_window": _clean_text(expected_launch_window),
                "expected_completion_window": _clean_text(expected_completion_window),
                "ownership_low_pct": ownership_values[0],
                "ownership_base_pct": ownership_values[1],
                "ownership_high_pct": ownership_values[2],
                "ownership_scenario_status": ownership_values[3],
                "source_url": urls[0] if urls else None,
                "source_urls_json": json.dumps(urls, ensure_ascii=False),
                "source_dataset": source_dataset,
                "evidence_status": _clean_text(evidence_status) or "not_observed",
                "evidence_key": _clean_text(evidence_key),
                "sales_queue_status": _clean_text(sales_queue_status) or "not_evaluated",
                "observed_at": now,
                "missing_data_policy": MISSING_DATA_POLICY,
            }
        )

    # Current company directory observations are events too; they do not imply
    # that a project has an SRPE register or a legal ownership interval.
    for record in catalog_frame.to_dict("records"):
        label = _clean_text(record.get("marketing_name"))
        if not label:
            continue
        linked_id = find_linked_id(record)
        scope = _asset_scope_from_row(record)
        commercial = profile.is_commercial_scope(scope)
        state = _project_state(record.get("listed_status") or record.get("asset_type"))
        queue = (
            "not_applicable_non_residential" if commercial else
            "not_applicable_non_first_hand_residential" if _is_non_first_hand_residential(scope) else
            "eligible_for_recent_srpe_queue" if linked_id and _srpe_lifecycle(srpe_by_id.get(linked_id, {})) == "active" and record.get("asset_type") == "residential_for_sale" else
            "not_ready_srpe_pending"
        )
        append_event(
            canonical_id=f"{profile.developer_id}:srpe:{linked_id}" if linked_id else _fallback_project_id(profile, label),
            label=label,
            event_type="catalog_observation",
            event_date=record.get("fetched_at"),
            event_date_semantics="official_company_catalog_observation",
            state_after=("commercial_listed" if commercial and state else state),
            srpe_id=linked_id,
            phase_name=(srpe_by_id.get(linked_id) or {}).get("phase_name_en"),
            asset_scope=scope,
            address=record.get("address") or record.get("district"),
            source_url=record.get("source_url") or record.get("source_page_url"),
            source_dataset="developer_property_catalog",
            evidence_status="found",
            evidence_key=record.get("source_record_id") or f"{record.get('asset_type') or 'catalog'}:{record.get('source_url') or label}",
            sales_queue_status=queue,
            ownership_values=ownership(linked_id),
            aliases=[record.get("district"), record.get("address")],
        )

    for record in pipeline_frame.to_dict("records"):
        label = _clean_text(record.get("project_label"))
        if not label:
            continue
        linked_id = find_linked_id(record)
        scope = _asset_scope_from_row(record)
        commercial = profile.is_commercial_scope(scope)
        evidence_status = _clean_text(record.get("evidence_status")) or "not_observed"
        state = _project_state(record.get("project_state"))
        if evidence_status in {"not_observed", "not_evaluated", "not_found", "source_empty"} and not linked_id:
            # Keep a configured planned/development state for a source gap only
            # when it came from an issuer disclosure; do not create a state for
            # an entirely unevaluated source.
            if evidence_status in {"not_observed", "not_evaluated", "not_found", "source_empty"}:
                state = None
        queue = (
                "not_applicable_non_residential" if commercial else
                "not_applicable_non_first_hand_residential" if _is_non_first_hand_residential(scope) else
                "eligible_for_recent_srpe_queue" if linked_id and _srpe_lifecycle(srpe_by_id.get(linked_id, {})) == "active" else
                "not_ready_srpe_pending" if evidence_status == "found" else
                "not_evaluated_source_gap"
        )
        append_event(
            canonical_id=f"{profile.developer_id}:srpe:{linked_id}" if linked_id else _fallback_project_id(profile, label),
            label=label,
            event_type="pipeline_disclosure",
            event_date=record.get("publication_date"),
            event_date_semantics="issuer_publication_date",
            state_after=("commercial_under_development" if commercial and state else state),
            srpe_id=linked_id,
            phase_name=(srpe_by_id.get(linked_id) or {}).get("phase_name_en"),
            asset_scope=scope,
            address=record.get("geography"),
            expected_launch_window=record.get("expected_launch_window"),
            expected_completion_window=record.get("expected_completion_window"),
            source_url=record.get("source_url"),
            source_urls=[record.get("source_urls_json")],
            source_dataset=record.get("source_dataset") or "developer_pipeline_disclosures",
            evidence_status=evidence_status,
            evidence_key=record.get("pipeline_registry_key") or label,
            sales_queue_status=queue,
            ownership_values=ownership(linked_id),
            aliases=[record.get("geography")],
        )

    for record in identity_frame.to_dict("records"):
        label = _clean_text(record.get("project_label"))
        linked_id = _clean_text(record.get("srpe_development_id"))
        if not label:
            continue
        scope = _asset_scope_from_row(record)
        append_event(
            canonical_id=f"{profile.developer_id}:srpe:{linked_id}" if linked_id else _fallback_project_id(profile, label),
            label=label,
            event_type="identity_bridge",
            event_date=record.get("observed_at"),
            event_date_semantics="identity_crosswalk_observation",
            srpe_id=linked_id,
            phase_name=record.get("srpe_phase_name"),
            asset_scope=scope,
            lot_no=record.get("lot_no"),
            address=record.get("address"),
            source_url=record.get("source_url"),
            source_urls=[record.get("source_urls_json")],
            source_dataset=record.get("source_dataset") or "developer_identity_crosswalk",
            evidence_status=record.get("evidence_status"),
            evidence_key=record.get("identity_evidence_id") or label,
            sales_queue_status=(
                "not_applicable_non_residential" if profile.is_commercial_scope(scope)
                else "not_applicable_non_first_hand_residential" if _is_non_first_hand_residential(scope)
                else "not_ready_srpe_pending"
            ),
            ownership_values=(
                float(record["ownership_pct_snapshot"]),
                float(record["ownership_pct_snapshot"]),
                float(record["ownership_pct_snapshot"]),
                "observed_snapshot_not_interval",
            ) if pd.notna(record.get("ownership_pct_snapshot")) else ownership(linked_id),
        )

    linked_ids = {
        _clean_text(record.get("srpe_development_id"))
        for record in identity_frame.to_dict("records")
        if _clean_text(record.get("srpe_development_id")) and record.get("match_status") not in {"ambiguous", "unmatched"}
    }
    linked_ids.update(
        find_linked_id(record)
        for record in pipeline_frame.to_dict("records")
        if find_linked_id(record)
    )
    for phase_id in sorted(linked_ids):
        phase = srpe_by_id.get(phase_id)
        if not phase:
            continue
        lifecycle = _srpe_lifecycle(phase)
        state = {
            "active": "srpe_active_prelaunch",
            "suspended": "sales_suspended",
            "completed": "sales_completed",
            "deleted": "deleted",
            "inactive": "srpe_inactive",
            "unknown": "srpe_lifecycle_unknown",
        }[lifecycle]
        event_date = phase.get("srpe_date_complete_sales") or phase.get("srpe_date_suspend_sales") or phase.get("srpe_earliest_publication")
        queue = "eligible_for_recent_srpe_queue" if lifecycle == "active" else "not_eligible_terminal_or_suspended"
        append_event(
            canonical_id=f"{profile.developer_id}:srpe:{phase_id}",
            label=phase.get("development_name_en") or phase.get("display_name") or phase_id,
            event_type="srpe_lifecycle_observation",
            event_date=event_date,
            event_date_semantics=("srpe_completion_date" if lifecycle == "completed" else "srpe_earliest_publication"),
            state_after=state,
            srpe_id=phase_id,
            phase_name=phase.get("phase_name_en") or phase.get("phase_name_zh"),
            asset_scope="residential_first_hand_or_unknown",
            address=phase.get("address_en") or phase.get("address_zh"),
            source_url=phase.get("source_url") or "https://www.srpe.gov.hk/opip/all_development",
            source_dataset="srpe_development_index",
            evidence_status="found",
            evidence_key=f"{profile.developer_id}:srpe:{phase_id}:{lifecycle}",
            sales_queue_status=queue,
            ownership_values=ownership(phase_id),
            aliases=[phase.get("phase_name_en"), phase.get("phase_name_zh")],
        )

    current = pd.DataFrame(rows, columns=DEVELOPER_EVENT_COLUMNS)
    frames: list[pd.DataFrame] = []
    for frame in (prior_frame, current):
        if frame is None or frame.empty:
            continue
        normalized = frame.copy()
        for column in DEVELOPER_EVENT_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = pd.NA
        normalized["company_id"] = profile.developer_id
        normalized["ticker"] = profile.normalized_ticker
        # Early adapter versions used source-specific fallback keys.  Migrate
        # those keys at read time so an append-only refresh does not create
        # duplicate snapshots for the same unresolved project label.  The
        # immutable event_key/event_id remain intact; only the grouping key is
        # corrected.
        if "canonical_project_id" in normalized.columns and "srpe_development_id" in normalized.columns:
            unresolved = normalized["srpe_development_id"].isna() | normalized["srpe_development_id"].astype(str).isin({"", "nan", "None"})
            normalized.loc[unresolved, "canonical_project_id"] = normalized.loc[unresolved, "project_label"].map(
                lambda value: _fallback_project_id(profile, value) if _clean_text(value) else value
            )
        frames.append(normalized.reindex(columns=DEVELOPER_EVENT_COLUMNS))
    merged = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=DEVELOPER_EVENT_COLUMNS)
    if not merged.empty:
        merged = merged.drop_duplicates(subset=["event_key"], keep="last")
        merged = merged.sort_values(["event_date", "canonical_project_id", "event_id"], kind="stable", na_position="last").reset_index(drop=True)
    merged.attrs["lineage_metadata"] = {
        "lineage_type": "developer_project_append_only_events",
        "company_id": profile.developer_id,
        "ticker": profile.normalized_ticker,
        "adapter_version": profile.adapter_version,
        "append_only": True,
        "dedupe_key": "event_key",
        "missing_data_policy": MISSING_DATA_POLICY,
        "ownership_inference": False,
    }
    return merged


def build_developer_project_snapshot(
    profile: DeveloperProfile,
    events: pd.DataFrame | None,
) -> pd.DataFrame:
    """Project the latest state from the append-only event log."""
    frame = events.copy() if events is not None else pd.DataFrame()
    if frame.empty:
        return pd.DataFrame(columns=DEVELOPER_SNAPSHOT_COLUMNS)
    for column in DEVELOPER_EVENT_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    rows: list[dict[str, Any]] = []
    for canonical_id, group in frame.groupby("canonical_project_id", dropna=False, sort=True):
        group = group.copy()
        state_events = group.loc[group["state_after"].notna()].copy()
        if state_events.empty:
            identity_events = group.loc[group["event_type"].eq("identity_bridge")]
            if not identity_events.empty and not profile.is_commercial_scope(identity_events["asset_scope"].iloc[-1]):
                state_event = identity_events.sort_values("observed_at", kind="stable").iloc[-1].to_dict()
                current_state = "srpe_pending"
            else:
                state_event = None
                current_state = None
        else:
            state_events["_event_date"] = pd.to_datetime(state_events["event_date"], errors="coerce", utc=True)
            state_events["_observed"] = pd.to_datetime(state_events["observed_at"], errors="coerce", utc=True)
            state_events = state_events.sort_values(["_event_date", "_observed", "event_id"], kind="stable", na_position="last")
            state_event = state_events.iloc[-1].to_dict()
            current_state = _clean_text(state_event.get("state_after"))
        lifecycle_events = group.loc[group["event_type"].eq("srpe_lifecycle_observation")].copy()
        lifecycle_current_state = None
        lifecycle_current_event = None
        if not lifecycle_events.empty:
            lifecycle_events["_event_date"] = pd.to_datetime(lifecycle_events["event_date"], errors="coerce", utc=True)
            lifecycle_events["_observed"] = pd.to_datetime(lifecycle_events["observed_at"], errors="coerce", utc=True)
            lifecycle_events = lifecycle_events.sort_values(
                ["_event_date", "_observed", "event_id"], kind="stable", na_position="last"
            )
            lifecycle_current_event = lifecycle_events.iloc[-1].to_dict()
            lifecycle_current_state = _clean_text(lifecycle_current_event.get("state_after"))
            # The SRPE lifecycle is the authoritative current sales state;
            # a company directory can continue listing an old project after
            # SRPE marks it completed/suspended.  Do not let that directory
            # observation resurrect a terminal phase in the snapshot.
            if lifecycle_current_state in {"sales_suspended", "sales_completed", "deleted", "srpe_inactive"}:
                current_state = lifecycle_current_state
                state_event = lifecycle_current_event
            elif lifecycle_current_state == "srpe_active_prelaunch" and current_state not in {
                "sales_suspended", "sales_completed", "deleted", "srpe_inactive"
            }:
                current_state = lifecycle_current_state
                state_event = lifecycle_current_event
        latest = group.sort_values("observed_at", kind="stable", na_position="last").iloc[-1].to_dict()
        state_record = state_event or latest
        scope = _clean_text(latest.get("asset_scope")) or _clean_text(state_record.get("asset_scope"))
        known_scopes = {
            _clean_text(value)
            for value in group["asset_scope"].tolist()
            if _clean_text(value) and _clean_text(value) != "residential_first_hand_or_unknown"
        }
        if not scope or scope == "residential_first_hand_or_unknown":
            # SRPE lifecycle rows intentionally use an unknown scope.  Prefer
            # the company catalog/identity scope from the same canonical
            # project so an active first-hand phase is not downgraded to a
            # pending queue merely because the lifecycle row was observed last.
            for preferred in ("residential_first_hand", "residential_investment", "commercial_investment"):
                if preferred in known_scopes:
                    scope = preferred
                    break
        scope = scope or "residential_first_hand_or_unknown"
        commercial = profile.is_commercial_scope(scope) or str(current_state or "").startswith("commercial")
        lifecycle_states = set(
            _clean_text(value)
            for value in group.loc[group["event_type"].eq("srpe_lifecycle_observation"), "state_after"].tolist()
            if _clean_text(value)
        )
        has_active_srpe_lifecycle = "srpe_active_prelaunch" in lifecycle_states
        queue_values = [_clean_text(value) for value in group["sales_queue_status"].tolist() if _clean_text(value)]
        queue = next((value for value in reversed(queue_values) if value == "eligible_for_recent_srpe_queue"), queue_values[-1] if queue_values else "not_evaluated")
        non_first_hand_residential = _is_non_first_hand_residential(scope)
        if commercial:
            queue = "not_applicable_non_residential"
            coverage = "commercial_separate_registry"
        elif non_first_hand_residential:
            queue = "not_applicable_non_first_hand_residential"
            coverage = "residential_investment_separate_registry"
        elif current_state in {"sales_suspended", "sales_completed", "deleted", "srpe_inactive"}:
            queue = "not_eligible_terminal_or_suspended"
            coverage = "terminal_or_suspended_not_queue"
        elif current_state == "srpe_active_prelaunch" or has_active_srpe_lifecycle:
            queue = "eligible_for_recent_srpe_queue"
            coverage = "srpe_identity_known_sales_queue_candidate"
        elif current_state in {"planned_launch", "under_development", "srpe_pending", "srpe_lifecycle_unknown", "active_catalog_listing"}:
            coverage = "future_project_srpe_pending_or_unresolved"
        elif current_state in {"sales_suspended", "sales_completed", "deleted", "srpe_inactive"}:
            coverage = "terminal_or_suspended_not_queue"
        else:
            coverage = "identity_observed_state_unknown"
        urls: list[str] = []
        for value in group["source_urls_json"].tolist():
            try:
                parsed = json.loads(value) if value else []
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = []
            if isinstance(parsed, list):
                urls.extend(str(item) for item in parsed if _clean_text(item))
        urls.extend(str(value) for value in group["source_url"].tolist() if _clean_text(value))
        rows.append(
            {
                "company_id": profile.developer_id,
                "ticker": profile.normalized_ticker,
                "canonical_project_id": _clean_text(canonical_id),
                "project_label": _clean_text(latest.get("project_label")) or _clean_text(state_record.get("project_label")),
                "aliases_json": latest.get("aliases_json"),
                "asset_scope": scope,
                "current_state": current_state,
                "state_event_date": state_record.get("event_date"),
                "state_event_type": state_record.get("event_type"),
                "lot_no": latest.get("lot_no") or state_record.get("lot_no"),
                "address": latest.get("address") or state_record.get("address"),
                "srpe_development_id": latest.get("srpe_development_id") or state_record.get("srpe_development_id"),
                "srpe_phase_name": latest.get("srpe_phase_name") or state_record.get("srpe_phase_name"),
                "units": latest.get("units"),
                "gfa_sqft": latest.get("gfa_sqft"),
                "expected_launch_window": latest.get("expected_launch_window") or state_record.get("expected_launch_window"),
                "expected_completion_window": latest.get("expected_completion_window") or state_record.get("expected_completion_window"),
                "ownership_low_pct": latest.get("ownership_low_pct") if pd.notna(latest.get("ownership_low_pct")) else state_record.get("ownership_low_pct"),
                "ownership_base_pct": latest.get("ownership_base_pct") if pd.notna(latest.get("ownership_base_pct")) else state_record.get("ownership_base_pct"),
                "ownership_high_pct": latest.get("ownership_high_pct") if pd.notna(latest.get("ownership_high_pct")) else state_record.get("ownership_high_pct"),
                "ownership_scenario_status": latest.get("ownership_scenario_status") or state_record.get("ownership_scenario_status") or "not_observed",
                "sales_queue_status": queue,
                "coverage_status": coverage,
                "last_event_id": state_record.get("event_id") or latest.get("event_id"),
                "last_observed_at": latest.get("observed_at"),
                "source_urls_json": json.dumps(list(dict.fromkeys(urls)), ensure_ascii=False),
                "missing_data_policy": MISSING_DATA_POLICY,
            }
        )
    result = pd.DataFrame(rows, columns=DEVELOPER_SNAPSHOT_COLUMNS)
    result.attrs["lineage_metadata"] = {
        "lineage_type": "developer_project_current_snapshot",
        "company_id": profile.developer_id,
        "ticker": profile.normalized_ticker,
        "source_dataset": "developer_project_events",
        "append_only_source": True,
        "missing_data_policy": MISSING_DATA_POLICY,
    }
    return result


def build_developer_sales_queue(
    profile: DeveloperProfile,
    snapshot: pd.DataFrame | None,
    srpe_index: pd.DataFrame | None,
    *,
    last_verified_at: str | None = None,
) -> pd.DataFrame:
    """Route only active, identity-linked residential phases to SRPE queue."""
    current = snapshot.copy() if snapshot is not None else pd.DataFrame()
    srpe = srpe_index.copy() if srpe_index is not None else pd.DataFrame()
    srpe_by_id = {str(row.get("development_id")): row for row in srpe.to_dict("records")}
    verified = last_verified_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for record in current.to_dict("records"):
        scope = _clean_text(record.get("asset_scope")) or "residential_first_hand_or_unknown"
        phase_id = _clean_text(record.get("srpe_development_id"))
        phase = srpe_by_id.get(phase_id, {})
        lifecycle = _srpe_lifecycle(phase) if phase_id else "unknown"
        if profile.is_commercial_scope(scope):
            status, queue, reason = "not_applicable", "not_applicable_non_residential", "commercial/BOT asset is routed outside SRPE residential sales"
        elif _is_non_first_hand_residential(scope):
            status, queue, reason = "not_applicable", "not_applicable_non_first_hand_residential", "investment/residential-for-lease asset is routed outside first-hand SRPE sales"
        elif lifecycle == "active" and phase_id and scope == "residential_first_hand":
            status, queue, reason = "eligible", "eligible_for_recent_srpe_queue", "active SRPE phase with a developer identity bridge"
        elif lifecycle in {"completed", "suspended", "inactive", "deleted"}:
            status, queue, reason = "not_eligible", "not_eligible_terminal_or_suspended", f"SRPE lifecycle is {lifecycle}"
        elif phase_id:
            status, queue, reason = "not_ready", "not_ready_srpe_pending", "SRPE identity exists but lifecycle is not currently active"
        else:
            status, queue, reason = "not_ready", "not_ready_srpe_pending", "developer project is not yet linked to an SRPE phase"
        rows.append(
            {
                "company_id": profile.developer_id,
                "ticker": profile.normalized_ticker,
                "canonical_project_id": record.get("canonical_project_id"),
                "project_label": record.get("project_label"),
                "asset_scope": scope,
                "srpe_development_id": phase_id,
                "srpe_phase_name": record.get("srpe_phase_name") or phase.get("phase_name_en"),
                "eligibility_status": status,
                "queue_status": queue,
                "eligibility_reason": reason,
                "coverage_status": record.get("coverage_status"),
                "source_urls_json": record.get("source_urls_json"),
                "last_verified_at": verified,
                "missing_data_policy": MISSING_DATA_POLICY,
            }
        )
    return pd.DataFrame(rows, columns=DEVELOPER_SALES_QUEUE_COLUMNS)
