"""Source-health classification and the read-only Source Health page."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Mapping

import pandas as pd
import streamlit as st

from ..models import ControlTowerSnapshot


DEFAULT_STALE_AFTER_DAYS: dict[str, int | None] = {
    "daily": 3,
    "weekly": 10,
    "monthly": 45,
    "quarterly": 120,
    "annual": 400,
    "event_driven": 14,
    "on_build": None,
    "versioned": None,
    "irregular": None,
}

SOURCE_HEALTH_COLUMNS = (
    "source_id",
    "input_path",
    "source_kind",
    "status",
    "display_status",
    "display_label",
    "required",
    "row_count",
    "first_observation_at",
    "latest_observation_at",
    "source_latest_at",
    "retrieved_at_utc",
    "age_basis",
    "age_at_utc",
    "age_days",
    "cadence",
    "stale_after_days",
    "source_url",
    "pit_class",
    "pit_display",
    "source_license_class",
    "license_display",
    "entitlement_status",
    "entitlement_evidence",
    "entitlement_ref",
    "input_sha256",
    "schema_version",
    "missing_geographies",
    "detail",
)

_PIT_CLASSES = {
    "true_pit",
    "snapshot_from_live_source",
    "dated_public_broker_report",
    "reconstructed_sparse",
    "current_vintage",
    "not_pit",
}

_LICENSE_LABELS = {
    "official_public": "Official public metadata",
    "public_metadata": "Public metadata",
    "internal_research": "Private research evidence",
    "private": "Private research evidence",
    "discovery": "Discovery/context only",
    "entitled_metadata": "Entitled metadata",
    "local_private_research": "Local/private research only",
    "research_use_only": "Research use only",
    "private_research": "Private research only",
    "restricted_body": "Restricted body · metadata only",
    "public": "Public metadata",
}

_UTC_COLUMNS = {
    "first_observation_at",
    "latest_observation_at",
    "source_latest_at",
    "retrieved_at_utc",
    "age_at_utc",
}

_NON_ISSUE_DISPLAY_STATUSES = frozenset({"healthy", "unclassified"})
_EXPLICIT_ERROR_GAP_STATUSES = frozenset({"gap", "unresolved", "conflict"})


def _text(value: object) -> str:
    if value is None or value is pd.NA:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _timestamp(value: object) -> pd.Timestamp | None:
    if value is None or value is pd.NaT:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed) or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.tz_convert("UTC")


def _status_class(status: str, *, age_days: float | None, threshold: int | None, age_basis: str) -> str:
    explicit = status.lower().strip()
    if explicit in {"failed", "error", "schema_error"}:
        return "failed"
    if explicit == "conflicted":
        return "conflicted"
    if explicit == "review_required":
        return "review_required"
    if explicit in {"entitlement_required", "entitlement_denied"}:
        return "entitlement_error"
    if explicit == "unavailable":
        return "unavailable"
    if explicit == "degraded":
        return "degraded"
    if explicit == "stale":
        return "stale"
    if explicit not in {"available", "success", "ok"}:
        return "unclassified"
    if age_days is not None and age_basis != "none":
        if threshold is not None and age_days > threshold:
            return "stale"
        if threshold is not None and age_basis != "retrieval_only":
            return "healthy"
    return "unclassified"


def _display_label(display_status: str, entitlement_status: str) -> str:
    if display_status == "entitlement_error":
        if entitlement_status == "denied":
            return "Entitlement denied"
        return "Entitlement required"
    if entitlement_status == "unknown" and display_status not in {"failed", "unavailable"}:
        # Keep this explicit in the table; it prevents a license class from
        # being mistaken for an active entitlement.
        return display_status.replace("_", " ").title() + " · Entitlement not evidenced"
    return display_status.replace("_", " ").title()


def _pit_display(value: object) -> str:
    text = _text(value).lower()
    return text if text in _PIT_CLASSES else "PIT unavailable"


def _license_display(value: object) -> str:
    text = _text(value).lower()
    return _LICENSE_LABELS.get(text, "License unavailable")


def _entitlement_status(row: Mapping[str, object], status: str) -> str:
    explicit = _text(row.get("entitlement_status")).lower()
    if explicit in {
        "active", "missing", "denied", "unknown", "not_applicable",
        "terms_unverified", "permitted_local_private", "entitlement_required",
    }:
        return explicit
    if status == "entitlement_denied":
        return "denied"
    if status == "entitlement_required":
        return "missing"
    return "unknown"


def classify_source_health(
    source_health: pd.DataFrame,
    *,
    now_utc: pd.Timestamp,
    cadence_thresholds: Mapping[str, int | None] = DEFAULT_STALE_AFTER_DAYS,
) -> pd.DataFrame:
    """Classify source-health rows without reading, writing, or using the clock."""

    reference = _timestamp(now_utc)
    if reference is None:
        raise ValueError("now_utc must be timezone-aware")

    rows: list[dict[str, object]] = []
    for _, raw in source_health.iterrows():
        row = raw.to_dict()
        status = _text(row.get("status")).lower()
        cadence = _text(row.get("cadence")).lower()
        threshold_value = row.get("stale_after_days")
        try:
            threshold = None if pd.isna(threshold_value) else int(threshold_value)
        except (TypeError, ValueError):
            threshold = cadence_thresholds.get(cadence)
        if "stale_after_days" not in row or threshold_value is None or (isinstance(threshold_value, str) and not threshold_value.strip()):
            threshold = cadence_thresholds.get(cadence)

        source_latest = _timestamp(row.get("source_latest_at"))
        latest_observation = _timestamp(row.get("latest_observation_at"))
        retrieved = _timestamp(row.get("retrieved_at_utc"))
        if source_latest is not None:
            age_at = source_latest
            age_basis = "source_latest_at"
        elif latest_observation is not None:
            age_at = latest_observation
            age_basis = "latest_observation_at"
        elif retrieved is not None:
            age_at = retrieved
            age_basis = "retrieval_only"
        else:
            age_at = None
            age_basis = "none"

        future = age_at is not None and age_at > reference
        if age_at is None:
            age_days: float | None = None
        elif future:
            age_days = 0.0
        else:
            age_days = max(0.0, float((reference - age_at).total_seconds() / 86400.0))

        if future and status not in {
            "failed", "error", "schema_error", "conflicted", "review_required",
            "entitlement_required", "entitlement_denied", "unavailable", "degraded", "stale",
        }:
            display_status = "clock_skew"
        else:
            display_status = _status_class(
                status,
                age_days=age_days,
                threshold=threshold,
                age_basis=age_basis,
            )
        entitlement = _entitlement_status(row, status)
        output = {column: row.get(column, pd.NA) for column in SOURCE_HEALTH_COLUMNS}
        output.update(
            {
                "source_id": _text(row.get("source_id")),
                "input_path": _text(row.get("input_path")),
                "source_kind": _text(row.get("source_kind")),
                "status": _text(row.get("status")),
                "display_status": display_status,
                "display_label": _display_label(display_status, entitlement),
                "age_basis": age_basis,
                "age_at_utc": age_at if age_at is not None else pd.NaT,
                "age_days": age_days,
                "cadence": cadence,
                "stale_after_days": threshold,
                "pit_class": _text(row.get("pit_class")),
                "pit_display": _pit_display(row.get("pit_class")),
                "source_license_class": _text(row.get("source_license_class")),
                "license_display": _license_display(row.get("source_license_class")),
                "entitlement_status": entitlement,
                "entitlement_evidence": _text(row.get("entitlement_evidence")),
                "entitlement_ref": _text(row.get("entitlement_ref")),
                "source_url": _text(row.get("source_url")),
                "detail": _text(row.get("detail")),
            }
        )
        rows.append(output)

    if not rows:
        data: dict[str, pd.Series] = {}
        for column in SOURCE_HEALTH_COLUMNS:
            data[column] = pd.Series(
                [],
                dtype="datetime64[ns, UTC]" if column in _UTC_COLUMNS else "Float64" if column == "age_days" else "object",
            )
        return pd.DataFrame(data)
    result = pd.DataFrame(rows, columns=SOURCE_HEALTH_COLUMNS)
    for column in _UTC_COLUMNS:
        result[column] = pd.to_datetime(result[column], utc=True, errors="coerce")
    result["age_days"] = pd.to_numeric(result["age_days"], errors="coerce").astype("Float64")
    result["stale_after_days"] = pd.to_numeric(result["stale_after_days"], errors="coerce").astype("Int64")
    return result


def source_health_counts(classified: pd.DataFrame) -> dict[str, int]:
    """Return headline counts without treating unclassified rows as errors."""

    display_status = classified.get(
        "display_status", pd.Series("", index=classified.index, dtype="string")
    ).map(_text).str.lower()
    raw_status = classified.get(
        "status", pd.Series("", index=classified.index, dtype="string")
    ).map(_text).str.lower()
    issue_rows = (
        display_status.ne("")
        & ~display_status.isin(_NON_ISSUE_DISPLAY_STATUSES)
    ) | raw_status.isin(_EXPLICIT_ERROR_GAP_STATUSES)
    return {
        "sources": int(len(classified)),
        "available": int(raw_status.eq("available").sum()),
        "unavailable": int(raw_status.eq("unavailable").sum()),
        "degraded": int(raw_status.eq("degraded").sum()),
        "healthy": int(display_status.eq("healthy").sum()),
        "stale": int(display_status.eq("stale").sum()),
        "errors_gaps": int(issue_rows.sum()),
    }


def _format_time(value: object, timezone: str) -> str:
    timestamp = _timestamp(value)
    if timestamp is None:
        return "Unavailable"
    try:
        return timestamp.tz_convert(timezone).strftime("%d %b %Y %H:%M %Z")
    except Exception:
        return timestamp.strftime("%d %b %Y %H:%M UTC")


def _safe_link(value: object, label: str) -> str:
    url = _text(value)
    if not url.startswith(("http://", "https://")):
        return f"{escape(label)} · source link unavailable"
    return f'<a class="ct-inline-link" href="{escape(url, quote=True)}" target="_blank" rel="noopener">{escape(label)}</a>'


def render_source_health_page(
    snapshot: ControlTowerSnapshot,
    *,
    viewer_timezone: str,
) -> pd.DataFrame:
    """Render source metadata and classification only; never source bodies."""

    classified = classify_source_health(snapshot.source_health, now_utc=snapshot.now_utc)
    st.markdown("### Source Health")
    st.caption("Collector/provider state · freshness · schema and entitlement caveats · metadata only")
    if classified.empty:
        st.info("No source-health rows are available in this snapshot.")
        return classified

    counts = source_health_counts(classified)
    cols = st.columns(4)
    cols[0].metric("Sources", counts["sources"])
    cols[1].metric("Healthy", counts["healthy"])
    cols[2].metric("Stale", counts["stale"])
    cols[3].metric("Errors / gaps", counts["errors_gaps"])

    display_columns = (
        "source_id",
        "input_path",
        "source_kind",
        "status",
        "display_status",
        "display_label",
        "latest_observation_at",
        "source_latest_at",
        "retrieved_at_utc",
        "age_days",
        "cadence",
        "stale_after_days",
        "row_count",
        "schema_version",
        "pit_display",
        "license_display",
        "entitlement_status",
        "entitlement_evidence",
        "entitlement_ref",
        "missing_geographies",
        "detail",
    )
    table = classified.loc[:, display_columns].copy()
    table["mapping_indicator"] = table["detail"].map(
        lambda value: "unresolved mapping" if any(token in _text(value).lower() for token in ("unresolved_mapping", "mapping_unresolved", "unresolved mapping")) else "not reported"
    )
    table["conflict_indicator"] = table["display_status"].map(
        lambda value: "conflict" if value == "conflicted" else "review required" if value == "review_required" else "none"
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
    for _, row in classified.iterrows():
        source_id = _text(row.get("source_id")) or "source unavailable"
        status = _text(row.get("display_label")) or _text(row.get("display_status"))
        detail = _text(row.get("detail")) or "No schema/error detail supplied."
        age = "age unavailable" if pd.isna(row.get("age_days")) else f"age {float(row['age_days']):.2f}d"
        source = _safe_link(row.get("source_url"), source_id)
        mapping_indicator = "unresolved mapping" if any(token in detail.lower() for token in ("unresolved_mapping", "mapping_unresolved", "unresolved mapping")) else "mapping not reported"
        conflict_indicator = "conflicted" if _text(row.get("display_status")) == "conflicted" else "review required" if _text(row.get("display_status")) == "review_required" else "no conflict flagged"
        st.markdown(
            f'<div class="ct-change"><div class="ct-change-title">{escape(source_id)} · {escape(status)}</div>'
            f'<div class="ct-change-detail">{escape(detail)} · {escape(age)} · cadence {escape(_text(row.get("cadence")) or "unclassified")} · '
            f'stale after {escape(_text(row.get("stale_after_days")) or "unclassified")} · input {escape(_text(row.get("input_path")) or "unavailable")} · '
            f'schema {escape(_text(row.get("schema_version")) or "unavailable")} · {escape(mapping_indicator)} · {escape(conflict_indicator)}</div>'
            f'<div class="ct-source-line">{source} · latest observation {_format_time(row.get("latest_observation_at"), viewer_timezone)} · '
            f'source latest {_format_time(row.get("source_latest_at"), viewer_timezone)} · retrieved {_format_time(row.get("retrieved_at_utc"), viewer_timezone)} · '
            f'PIT {escape(_text(row.get("pit_display")))} · license {escape(_text(row.get("license_display")))} · '
            f'entitlement {escape(_text(row.get("entitlement_status")))} · evidence {escape(_text(row.get("entitlement_ref")) or "unavailable")}</div></div>',
            unsafe_allow_html=True,
        )
    return classified


__all__ = [
    "DEFAULT_STALE_AFTER_DAYS",
    "SOURCE_HEALTH_COLUMNS",
    "classify_source_health",
    "source_health_counts",
    "render_source_health_page",
]
