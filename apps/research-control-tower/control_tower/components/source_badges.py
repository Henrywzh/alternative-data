"""Source, certainty and PIT display grammar for Control Tower events."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Mapping

import pandas as pd
import streamlit as st


@dataclass(frozen=True, slots=True)
class SourceBadgeView:
    source_id: str | None
    source_label: str
    source_url: str | None
    source_timezone: str | None
    last_verified_at: pd.Timestamp | None
    source_published_at: pd.Timestamp | None
    retrieved_at_utc: pd.Timestamp | None
    pit_class: str | None
    license_class: str | None
    status: str | None
    evidence_class: str | None


_CERTAINTY_LABELS = {
    "hard": "Confirmed",
    "provisional": "Provisional",
    "thesis_checkpoint": "Thesis window",
    "observed": "Observed",
}

_PIT_LABELS = {
    "true_pit": "PIT · true",
    "snapshot_from_live_source": "PIT · live snapshot",
    "snapshot_from_delayed_source": "Snapshot · delayed source",
    "dated_public_broker_report": "PIT · dated broker",
    "reconstructed_sparse": "PIT · reconstructed",
    "repository_captured": "PIT · captured",
    "current_vintage": "PIT · current vintage",
    "not_pit": "Not PIT",
}


def _text(value: object) -> str:
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _timestamp(value: object) -> pd.Timestamp | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed) or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.tz_convert("UTC")


def certainty_label(value: object) -> str:
    certainty = _text(value).lower()
    return _CERTAINTY_LABELS.get(certainty, "Unclassified")


def _safe_url(value: object) -> str | None:
    url = _text(value)
    if url.startswith(("https://", "http://")):
        return url
    return None


def source_badges_for_event(
    snapshot: Any,
    event: Mapping[str, Any],
) -> tuple[SourceBadgeView, ...]:
    """Resolve event source metadata through the stable ``source_id`` key.

    No PIT classification is inferred.  If the source-health join is absent,
    the renderer receives ``None`` and shows ``PIT unavailable``.
    """

    source_id = _text(event.get("source_id")) or None
    health = getattr(snapshot, "source_health", pd.DataFrame())
    rows = health.loc[health["source_id"].astype("string").eq(source_id)].to_dict("records") if (
        source_id and not health.empty and "source_id" in health.columns
    ) else []
    health_row = rows[0] if rows else {}
    source_url = _safe_url(event.get("source_url")) or _safe_url(health_row.get("source_url"))
    source_label = source_id or "Source unavailable"
    if _text(health_row.get("detail")) and _text(health_row.get("status")) in {
        "failed", "conflicted", "stale", "unavailable", "review_required"
    }:
        source_label = f"{source_label} · {_text(health_row.get('status')).lower()}"
    status = _text(health_row.get("status")) or None
    pit_class = _text(health_row.get("pit_class")) or None
    license_class = _text(health_row.get("source_license_class")) or None
    if not rows:
        status = None
    return (
        SourceBadgeView(
            source_id=source_id,
            source_label=source_label,
            source_url=source_url,
            source_timezone=_text(event.get("source_timezone")) or None,
            last_verified_at=_timestamp(event.get("last_verified_at")),
            source_published_at=_timestamp(event.get("source_published_at")),
            retrieved_at_utc=_timestamp(health_row.get("retrieved_at_utc")),
            pit_class=pit_class,
            license_class=license_class,
            status=status,
            evidence_class=_text(event.get("evidence_class")) or None,
        ),
    )


def _format_timestamp(value: pd.Timestamp | None, viewer_timezone: str | None = None) -> str:
    if value is None:
        return "verification unavailable"
    try:
        displayed = value.tz_convert(viewer_timezone) if viewer_timezone else value
    except Exception:
        displayed = value
    return displayed.strftime("%d %b %Y %H:%M %Z")


def source_badges_html(
    badges: tuple[SourceBadgeView, ...],
    *,
    viewer_timezone: str | None = None,
) -> str:
    """Return escaped, compact source/PIT metadata HTML."""

    chunks: list[str] = []
    for badge in badges:
        source = escape(badge.source_label or "Source unavailable")
        if badge.source_url:
            source = f'<a href="{escape(badge.source_url, quote=True)}" target="_blank" rel="noopener">{source}</a>'
        else:
            source = f"{source} · Source link unavailable"
        chunks.append(f'<span class="ct-badge">Source · {source}</span>')
        certainty = _PIT_LABELS.get(badge.pit_class or "", "PIT unavailable")
        pit_class = "ct-badge--warning" if certainty in {"PIT unavailable", "Not PIT", "PIT · reconstructed"} else ""
        chunks.append(f'<span class="ct-badge {pit_class}">{escape(certainty)}</span>')
        if badge.source_timezone:
            chunks.append(f'<span class="ct-badge">TZ · {escape(badge.source_timezone)}</span>')
        if badge.evidence_class:
            chunks.append(f'<span class="ct-badge">Evidence · {escape(badge.evidence_class)}</span>')
        if badge.license_class:
            chunks.append(f'<span class="ct-badge">License · {escape(badge.license_class)}</span>')
        if badge.status and badge.status.lower() not in {"available", "ok", "healthy"}:
            chunks.append(f'<span class="ct-badge ct-badge--warning">Health · {escape(badge.status)}</span>')
        chunks.append(f'<div class="ct-source-line">Source published · {escape(_format_timestamp(badge.source_published_at, viewer_timezone))} · Retrieved · {escape(_format_timestamp(badge.retrieved_at_utc, viewer_timezone))} · Last verified · {escape(_format_timestamp(badge.last_verified_at, viewer_timezone))}</div>')
    return '<div class="ct-badges">' + "".join(chunks) + "</div>"


def render_source_badges(
    badges: tuple[SourceBadgeView, ...],
    *,
    viewer_timezone: str | None = None,
) -> None:
    st.markdown(source_badges_html(badges, viewer_timezone=viewer_timezone), unsafe_allow_html=True)


__all__ = [
    "SourceBadgeView",
    "certainty_label",
    "render_source_badges",
    "source_badges_for_event",
    "source_badges_html",
]
