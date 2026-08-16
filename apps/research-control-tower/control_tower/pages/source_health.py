"""Source-health classification and the read-only Source Health page."""

from __future__ import annotations

from html import escape
import re
from typing import Mapping

import pandas as pd
import streamlit as st

from ..components.coverage_matrix import coverage_legend_html
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
    "query_attempted",
    "execution_status",
    "completed_at",
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
    "snapshot_from_delayed_source",
    "not_pit",
    # A human transcribed this value into the registry (events.csv) from
    # cited evidence; it was never fetched by a live collector at build
    # time. See build.py's _MACRO_EVIDENCE_CLASS_PIT_LICENSE mapping.
    "registry_transcribed",
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
    "personal_use_terms_unverified": "Personal-use terms unverified",
}

_UTC_COLUMNS = {
    "first_observation_at",
    "latest_observation_at",
    "source_latest_at",
    "retrieved_at_utc",
    "completed_at",
    "age_at_utc",
}

_EXPLICIT_ERROR_GAP_STATUSES = frozenset({
    "gap",
    "unresolved",
    "conflict",
    "failed",
    "error",
    "schema_error",
    "review_required",
    "entitlement_required",
    "entitlement_denied",
})
_WINDOWS_ABS_PATH = re.compile(r"(?<![\w:])[A-Za-z]:[\\/][^;\n]+")
_COLON_ABS_PATH = re.compile(r":(?!//)(?:[\\/][^;\n]+)")
_PLAIN_ABS_PATH = re.compile(r"(?<![:/])/(?:[\w.+-]+/)+[\w.+-]+")


def _text(value: object) -> str:
    if value is None or value is pd.NA:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def display_input_path(value: object) -> str:
    """Return a display-safe input path, basename-only when absolute."""

    text = _text(value)
    if not text:
        return ""
    if text.startswith("/") or _WINDOWS_ABS_PATH.match(text):
        return text.replace("\\", "/").rstrip("/").split("/")[-1]
    return text


def sanitise_source_detail(value: object) -> str:
    """Strip absolute path fragments and deduplicate raw error tokens."""

    text = _text(value)
    if not text:
        return ""
    text = _WINDOWS_ABS_PATH.sub(
        lambda match: match.group(0).replace("\\", "/").rstrip("/").split("/")[-1],
        text,
    )
    text = _COLON_ABS_PATH.sub(
        lambda match: ":" + match.group(0).replace("\\", "/").rstrip("/").split("/")[-1],
        text,
    )
    text = _PLAIN_ABS_PATH.sub(
        lambda match: match.group(0).replace("\\", "/").rstrip("/").split("/")[-1],
        text,
    )
    tokens = [token.strip() for token in text.split(";") if token.strip()]
    seen: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return "; ".join(seen)


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
    if explicit == "partial":
        return "partial"
    if explicit == "no_records":
        return "no_records"
    if explicit == "stale":
        return "stale"
    if explicit == "not_applicable":
        return "not_applicable"
    if explicit == "no_records":
        # ``no_records`` is evidence-derived below. A raw label alone is not
        # proof that a query was attempted and completed.
        return "unclassified"
    if explicit not in {"available", "success", "ok"}:
        return "unclassified"
    if age_days is not None and age_basis != "none":
        if threshold is not None and age_days > threshold:
            return "stale"
        if threshold is not None and age_basis != "retrieval_only":
            return "healthy"
    return "unclassified"


def _display_label(display_status: str, entitlement_status: str, raw_status: str = "") -> str:
    if display_status == "entitlement_error":
        if entitlement_status in {"denied", "adverse"}:
            return "Entitlement denied"
        return "Entitlement required"
    if display_status == "no_records":
        label = "No records"
    elif display_status == "not_applicable":
        label = "Not applicable"
    if display_status == "unclassified" and raw_status in {"available", "success", "ok"}:
        label = "Available · Freshness not classified"
    elif display_status not in {"no_records", "not_applicable"}:
        label = display_status.replace("_", " ").title()
    if entitlement_status == "unknown" and display_status not in {
        "failed",
        "unavailable",
        "no_records",
        "not_applicable",
    }:
        # Keep this explicit in the table; it prevents a license class from
        # being mistaken for an active entitlement.
        return label + " · Entitlement not evidenced"
    return label


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
        "adverse",
    }:
        return explicit
    if status == "entitlement_denied":
        return "denied"
    if status == "entitlement_required":
        return "missing"
    return "unknown"


def _query_attempted(value: object) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    if isinstance(value, (int, float)) and not pd.isna(value):
        return int(value) == 1
    return False


def _has_completed_execution(
    row: Mapping[str, object],
    *,
    reference: pd.Timestamp,
) -> tuple[bool, pd.Timestamp | None]:
    """Return explicit successful completion proof for a source query.

    The minimal compatible contract is:
    ``query_attempted=true``, ``execution_status=completed`` and a
    timezone-aware ``completed_at`` no later than the bundle reference time.
    Legacy bundles without these optional fields remain unclassified.
    """

    completed_at = _timestamp(row.get("completed_at"))
    completed = (
        _query_attempted(row.get("query_attempted"))
        and _text(row.get("execution_status")).lower() == "completed"
        and completed_at is not None
        and completed_at <= reference
    )
    return completed, completed_at


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

        quote_timestamp = _timestamp(row.get("quote_timestamp"))
        source_latest = _timestamp(row.get("source_latest_at"))
        latest_observation = _timestamp(row.get("latest_observation_at"))
        retrieved = _timestamp(row.get("retrieved_at_utc"))
        if _text(row.get("source_kind")).lower() == "market":
            if quote_timestamp is not None:
                age_at = quote_timestamp
            elif source_latest is not None:
                # The builder stores the quote timestamp in source_latest_at
                # because the published source-health schema is shared by all
                # optional inputs.  Preserve that market-specific meaning in
                # the display contract; retrieval remains a separate field.
                age_at = source_latest
            else:
                age_at = None
            age_basis = "quote_timestamp" if age_at is not None else "none"
        elif source_latest is not None:
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

        raw_row_count = row.get("row_count")
        row_count_value = None if raw_row_count is None or pd.isna(raw_row_count) else raw_row_count
        try:
            reported_rows = None if row_count_value is None else int(row_count_value)
        except (TypeError, ValueError):
            reported_rows = None

        execution_completed, completed_at = _has_completed_execution(
            row, reference=reference
        )
        entitlement = _entitlement_status(row, status)
        base_status = _status_class(
            status,
            age_days=age_days,
            threshold=threshold,
            age_basis=age_basis,
        )
        adverse_entitlement = entitlement in {
            "denied",
            "missing",
            "entitlement_required",
            "terms_unverified",
            "adverse",
        }
        explicit_adverse_statuses = {
            "failed",
            "conflicted",
            "review_required",
            "entitlement_error",
            "unavailable",
            "degraded",
            "stale",
            "not_applicable",
        }
        if adverse_entitlement and base_status not in explicit_adverse_statuses:
            display_status = "entitlement_error"
        elif base_status in explicit_adverse_statuses:
            display_status = base_status
        elif future or (
            completed_at is not None and completed_at > reference
        ):
            display_status = "clock_skew"
        elif (
            reported_rows == 0
            and status in {"available", "success", "ok", "no_records"}
            and not execution_completed
        ):
            display_status = "review_required"
        elif (
            reported_rows == 0
            and status in {"available", "success", "ok", "no_records"}
            and execution_completed
        ):
            display_status = "no_records"
        else:
            display_status = base_status
        output = {column: row.get(column, pd.NA) for column in SOURCE_HEALTH_COLUMNS}
        output.update(
            {
                "source_id": _text(row.get("source_id")),
                "input_path": display_input_path(row.get("input_path")),
                "source_kind": _text(row.get("source_kind")),
                "status": _text(row.get("status")),
                "display_status": display_status,
                "display_label": _display_label(display_status, entitlement, status),
                "query_attempted": _query_attempted(row.get("query_attempted")),
                "execution_status": _text(row.get("execution_status")).lower(),
                "completed_at": (
                    completed_at if completed_at is not None else pd.NaT
                ),
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
                "detail": sanitise_source_detail(row.get("detail")),
            }
        )
        rows.append(output)

    if not rows:
        data: dict[str, pd.Series] = {}
        for column in SOURCE_HEALTH_COLUMNS:
            if column in _UTC_COLUMNS:
                dtype = "datetime64[ns, UTC]"
            elif column == "age_days":
                dtype = "Float64"
            elif column == "query_attempted":
                dtype = "boolean"
            else:
                dtype = "object"
            data[column] = pd.Series([], dtype=dtype)
        return pd.DataFrame(data)
    result = pd.DataFrame(rows, columns=SOURCE_HEALTH_COLUMNS)
    for column in _UTC_COLUMNS:
        result[column] = pd.to_datetime(result[column], utc=True, errors="coerce")
    result["age_days"] = pd.to_numeric(result["age_days"], errors="coerce").astype("Float64")
    result["stale_after_days"] = pd.to_numeric(result["stale_after_days"], errors="coerce").astype("Int64")
    result["query_attempted"] = result["query_attempted"].astype("boolean")
    return result


def source_health_counts(classified: pd.DataFrame) -> dict[str, int]:
    """Return headline counts without treating unclassified rows as errors.

    Buckets are: available (status-level), healthy / freshness-unclassified /
    stale (freshness-level), unavailable-degraded (status-level) and
    errors_gaps (explicit issues only; cadence-unconfigured rows are never
    counted here).
    """

    display_status = classified.get(
        "display_status", pd.Series("", index=classified.index, dtype="string")
    ).map(_text).str.lower()
    raw_status = classified.get(
        "status", pd.Series("", index=classified.index, dtype="string")
    ).map(_text).str.lower()
    issue_rows = raw_status.isin(_EXPLICIT_ERROR_GAP_STATUSES) | display_status.isin(
        {"conflicted", "review_required", "entitlement_error", "clock_skew"}
    )
    return {
        "sources": int(len(classified)),
        "available": int(raw_status.eq("available").sum()),
        "healthy": int(display_status.eq("healthy").sum()),
        "freshness_unclassified": int(display_status.eq("unclassified").sum()),
        "stale": int(display_status.eq("stale").sum()),
        "no_records": int(display_status.eq("no_records").sum()),
        "not_applicable": int(display_status.eq("not_applicable").sum()),
        "unavailable_degraded": int(
            raw_status.isin({"unavailable", "degraded", "partial", "no_records"}).sum()
        ),
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


def _source_display_name(value: object) -> str:
    """Translate registry/source ids into a compact lineage label."""

    text = _text(value)
    labels = {
        "consensus_export": "Consensus export",
        "sec_edgar": "SEC EDGAR",
        "filings_sec_edgar": "SEC EDGAR coverage",
        "official_ai_rss": "Official AI RSS",
        "news_official_ai_rss": "Official AI RSS coverage",
        "fred_observations": "FRED observations",
        "fred_series_meta": "FRED series metadata",
        "ecb_fx_rates": "ECB FX reference rates",
        "ofr_mnemonics": "OFR market-data mnemonics",
        "ofr_timeseries": "OFR market time series",
        "tw_monthly_revenue": "Taiwan monthly revenue",
    }
    if text in labels:
        return labels[text]
    if text.startswith("artifact:"):
        return "Artifact · " + text.removeprefix("artifact:").replace("_", " ").title()
    if text.startswith("events:"):
        return "Event registry · " + text.removeprefix("events:").replace("_", " ").title()
    if text.startswith("registry:"):
        return "Registry · " + text.removeprefix("registry:").replace("_", " ").title()
    return text.replace("_", " ").replace(":", " · ").title() or "Source unavailable"


def _render_stage1_coverage_matrix(snapshot: ControlTowerSnapshot) -> None:
    """Render the deterministic Stage 1 entity/listing coverage matrix."""

    from ..components.coverage_matrix import (
        render_stage1_coverage_matrix as render_matrix,
    )
    from ..coverage import build_stage1_coverage_matrix

    matrix = build_stage1_coverage_matrix(snapshot)
    st.markdown("### Stage 1 coverage matrix")
    st.caption(
        "Per-entity and per-listing status across the focus universe · derived "
        "from artifact presence, row counts, linkage, freshness and source "
        "health · read-only, no provider queries"
    )
    st.markdown(coverage_legend_html(), unsafe_allow_html=True)
    render_matrix(matrix)


def render_source_health_page(
    snapshot: ControlTowerSnapshot,
    *,
    viewer_timezone: str,
) -> pd.DataFrame:
    """Render source metadata and classification only; never source bodies."""

    classified = classify_source_health(snapshot.source_health, now_utc=snapshot.now_utc)
    st.markdown("### Source Health")
    st.caption(
        "Collector/provider state · freshness · schema and entitlement "
        "caveats · metadata only"
    )
    if classified.empty:
        st.info("No source-health rows are available in this snapshot.")
        _render_stage1_coverage_matrix(snapshot)
        return classified

    counts = source_health_counts(classified)
    st.markdown(coverage_legend_html(), unsafe_allow_html=True)
    status_cols = st.columns(4)
    status_cols[0].metric("Sources", counts["sources"])
    status_cols[1].metric("Available", counts["available"])
    status_cols[2].metric("Healthy", counts["healthy"])
    status_cols[3].metric("Freshness unclassified", counts["freshness_unclassified"])
    issue_cols = st.columns(3)
    issue_cols[0].metric("Stale", counts["stale"])
    issue_cols[1].metric("Unavailable / degraded", counts["unavailable_degraded"])
    issue_cols[2].metric("Explicit errors / gaps", counts["errors_gaps"])

    display_columns = (
        "source_id", "display_label", "latest_observation_at", "age_days",
        "cadence", "row_count",
    )
    table = classified.loc[:, display_columns].copy()
    table["source_id"] = table["source_id"].map(_source_display_name)
    table = table.rename(columns={
        "source_id": "Source",
        "display_label": "Status",
        "latest_observation_at": "Latest observation",
        "age_days": "Age (days)",
        "cadence": "Cadence",
        "row_count": "Rows",
    })
    st.dataframe(table, width="stretch", hide_index=True)
    with st.expander("Source details", expanded=False):
        for _, row in classified.iterrows():
            source_id = _text(row.get("source_id")) or "source unavailable"
            status = _text(row.get("display_label")) or _text(row.get("display_status"))
            detail = _text(row.get("detail")) or "No schema/error detail supplied."
            age = "age unavailable" if pd.isna(row.get("age_days")) else f"age {float(row['age_days']):.2f}d"
            source = _safe_link(row.get("source_url"), "source link")
            st.markdown(
                f'<div class="ct-change"><div class="ct-change-title">{escape(_source_display_name(source_id))} · {escape(status)}</div>'
                f'<div class="ct-change-detail">{escape(detail)} · {escape(age)} · age basis {escape(_text(row.get("age_basis")) or "unclassified")} · cadence {escape(_text(row.get("cadence")) or "unclassified")} · '
                f'stale after {escape(_text(row.get("stale_after_days")) or "unclassified")} · schema {escape(_text(row.get("schema_version")) or "unavailable")}</div>'
                f'<div class="ct-source-line">internal id {escape(source_id)} · {source} · latest observation {_format_time(row.get("latest_observation_at"), viewer_timezone)} · '
                f'source latest {_format_time(row.get("source_latest_at"), viewer_timezone)} · retrieved {_format_time(row.get("retrieved_at_utc"), viewer_timezone)} · '
                f'execution {escape(_text(row.get("execution_status")) or "unavailable")} · completed {_format_time(row.get("completed_at"), viewer_timezone)} · '
                f'PIT {escape(_text(row.get("pit_display")))} · license {escape(_text(row.get("license_display")))} · '
                f'entitlement {escape(_text(row.get("entitlement_status")))} · evidence {escape(_text(row.get("entitlement_ref")) or "unavailable")}</div></div>',
                unsafe_allow_html=True,
            )
    _render_stage1_coverage_matrix(snapshot)
    return classified


__all__ = [
    "DEFAULT_STALE_AFTER_DAYS",
    "SOURCE_HEALTH_COLUMNS",
    "classify_source_health",
    "display_input_path",
    "sanitise_source_detail",
    "source_health_counts",
    "render_source_health_page",
]
