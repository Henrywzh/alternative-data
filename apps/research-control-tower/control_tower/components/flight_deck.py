"""Flight-deck view model and renderer."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Literal

import pandas as pd
import streamlit as st

from ..filters import apply_event_filters
from ..models import ControlTowerSnapshot, EventFilters
from .timeline import (
    CatalystView,
    catalyst_view_for_event,
    is_active_catalyst,
    select_next_catalyst,
)


@dataclass(frozen=True, slots=True)
class BreadthMetric:
    label: str
    covered: int | None
    total: int | None
    status: Literal["available", "unavailable", "degraded"]
    detail: str


@dataclass(frozen=True, slots=True)
class FlightDeckViewModel:
    universe_label: str
    horizon_label: str
    evidence: BreadthMetric
    revisions: BreadthMetric
    next_catalyst: CatalystView | None
    catalyst_timing_state: Literal["active", "future", "none"]
    snapshot_state: Literal["delta", "initial_snapshot"]
    repository_status: Literal["success", "degraded"]


def _text(value: object) -> str:
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _universe_label(snapshot: ControlTowerSnapshot, filters: EventFilters) -> str:
    selected = tuple(filters.basket_id)
    baskets = snapshot.baskets
    if not selected:
        if filters.country:
            return f"All baskets · {len(filters.country)} countries"
        return "All baskets"
    names: list[str] = []
    if not baskets.empty:
        for basket_id in selected:
            rows = baskets.loc[baskets["basket_id"].astype("string").str.upper().eq(basket_id.upper())]
            if not rows.empty:
                names.append(_text(rows.iloc[0].get("display_name")) or basket_id)
    if len(names) == 1:
        return names[0]
    return f"{len(selected)} baskets · {len(filters.country)} countries" if filters.country else f"{len(selected)} baskets"


def _horizon_label(horizon: str) -> str:
    return {"7d": "7d", "30d": "30d", "90d": "90d", "long_range": "Long range", "all": "All"}.get(horizon, horizon)


def _evidence_metric(events: pd.DataFrame) -> BreadthMetric:
    tracked = len(events)
    if tracked == 0:
        return BreadthMetric("Evidence", None, None, "unavailable", "No eligible event evidence")
    covered_mask = events.get("source_id", pd.Series("", index=events.index)).astype("string").str.strip().ne("") | events.get("evidence_class", pd.Series("", index=events.index)).astype("string").str.strip().ne("")
    covered = int(covered_mask.sum())
    external = int(events.get("evidence_class", pd.Series("", index=events.index)).astype("string").str.contains("official_external|source_observation", case=False, regex=True, na=False).sum())
    internal = int(events.get("evidence_class", pd.Series("", index=events.index)).astype("string").str.contains("internal_research", case=False, regex=True, na=False).sum())
    return BreadthMetric("Evidence", covered, tracked, "available" if covered == tracked else "degraded", f"External/source {external} · internal {internal}")


def _revision_metric(snapshot: ControlTowerSnapshot, filters: EventFilters) -> BreadthMetric:
    if filters.scope and "company" not in filters.scope:
        return BreadthMetric(
            "Revisions",
            None,
            None,
            "unavailable",
            "Not applicable to selected scope",
        )
    frame = snapshot.consensus_revisions
    if "consensus_revisions" in snapshot.missing_optional or frame.empty:
        if "consensus_revisions" in snapshot.missing_optional:
            return BreadthMetric("Revisions", None, None, "unavailable", "Revision unavailable")
        return BreadthMetric("Revisions", None, None, "degraded", "No comparable history")
    current = frame.get("current_value", pd.Series(pd.NA, index=frame.index)).notna()
    comparable = current & frame.get("prior_value", pd.Series(pd.NA, index=frame.index)).notna()
    covered = int(current.sum())
    comparable_count = int(comparable.sum())
    if comparable_count == 0:
        return BreadthMetric("Revisions", None, None, "degraded", "No comparable history")
    return BreadthMetric("Revisions", covered, comparable_count, "available", "Current rows · comparable prior rows")


def build_flight_deck(
    snapshot: ControlTowerSnapshot,
    *,
    filters: EventFilters,
    viewer_timezone: str,
) -> FlightDeckViewModel:
    filtered = apply_event_filters(snapshot.events, filters)
    row = select_next_catalyst(filtered, snapshot.now_utc)
    catalyst = catalyst_view_for_event(snapshot, row, now_utc=snapshot.now_utc, viewer_timezone=viewer_timezone) if row is not None else None
    timing_state: Literal["active", "future", "none"] = "none"
    if catalyst is not None:
        if is_active_catalyst(catalyst.starts_at, catalyst.ends_at, snapshot.now_utc):
            timing_state = "active"
        else:
            timing_state = "future"
    return FlightDeckViewModel(
        universe_label=_universe_label(snapshot, filters),
        horizon_label=_horizon_label(filters.horizon),
        evidence=_evidence_metric(filtered),
        revisions=_revision_metric(snapshot, filters),
        next_catalyst=catalyst,
        catalyst_timing_state=timing_state,
        snapshot_state="delta" if snapshot.previous_build_at is not None else "initial_snapshot",
        repository_status=snapshot.status,
    )


def _metric_html(metric: BreadthMetric) -> str:
    if metric.status == "unavailable":
        value = metric.detail
    elif metric.covered is None or metric.total is None:
        value = metric.detail
    else:
        value = f"{metric.covered} / {metric.total}"
    return f'<div class="ct-flight-slot"><div class="ct-metric-label">{escape(metric.label)}</div><div class="ct-metric-value">{escape(value)}</div><div class="ct-metric-detail">{escape(metric.detail)}</div></div>'


def flight_deck_html(model: FlightDeckViewModel) -> str:
    catalyst = model.next_catalyst
    if catalyst is None:
        catalyst_html = '<div class="ct-flight-slot ct-flight-slot--catalyst"><div class="ct-metric-label">Next catalyst</div><div class="ct-metric-value">No eligible catalyst</div><div class="ct-metric-detail">No eligible catalyst in the selected horizon</div></div>'
    else:
        is_active = model.catalyst_timing_state == "active"
        metric_label = "Active catalyst" if is_active else "Next catalyst"
        timing_text = "Active window" if is_active else catalyst.t_minus
        catalyst_html = (
            '<div class="ct-flight-slot ct-flight-slot--catalyst">'
            f'<div class="ct-metric-label">{escape(metric_label)}</div>'
            f'<div class="ct-metric-value">{escape(catalyst.title)}</div>'
            f'<div class="ct-metric-detail">{escape(catalyst.display_window)} · {escape(timing_text)} · {escape(catalyst.certainty_class.title() or "Unclassified")} · Importance · {escape(catalyst.importance or "unclassified")}</div>'
            '</div>'
        )
    universe = f'<div class="ct-flight-slot"><div class="ct-metric-label">Universe</div><div class="ct-metric-value">{escape(model.universe_label)}</div><div class="ct-metric-detail">{escape(model.snapshot_state.replace("_", " ").title())} · {escape(model.repository_status)}</div></div>'
    horizon = f'<div class="ct-flight-slot"><div class="ct-metric-label">Horizon</div><div class="ct-metric-value">{escape(model.horizon_label)}</div><div class="ct-metric-detail">Calendar events and thesis windows</div></div>'
    return '<div class="ct-flight-deck">' + universe + horizon + _metric_html(model.evidence) + _metric_html(model.revisions) + catalyst_html + '</div>'


def render_flight_deck(model: FlightDeckViewModel) -> None:
    st.markdown(flight_deck_html(model), unsafe_allow_html=True)


__all__ = ["BreadthMetric", "FlightDeckViewModel", "build_flight_deck", "flight_deck_html", "render_flight_deck"]
