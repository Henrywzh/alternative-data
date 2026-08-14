"""Unified Timeline page composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st

from ..components.flight_deck import FlightDeckViewModel, build_flight_deck, render_flight_deck
from ..components.timeline import (
    TimelineMonthGroup,
    catalyst_view_for_event,
    group_timeline_events,
    render_catalyst,
)
from ..filters import apply_event_filters
from ..models import ControlTowerSnapshot, EventFilters


@dataclass(frozen=True, slots=True)
class TimelineViewModel:
    flight_deck: FlightDeckViewModel
    month_groups: tuple[TimelineMonthGroup, ...]
    visible_event_count: int


def build_timeline_view(
    snapshot: ControlTowerSnapshot,
    *,
    filters: EventFilters,
    viewer_timezone: str,
) -> TimelineViewModel:
    filtered = apply_event_filters(snapshot.events, filters)
    base_groups = group_timeline_events(filtered, now_utc=snapshot.now_utc, viewer_timezone=viewer_timezone)
    by_event = filtered.set_index("event_id", drop=False) if not filtered.empty else pd.DataFrame()
    groups: list[TimelineMonthGroup] = []
    for group in base_groups:
        views: list[CatalystView] = []
        for view in group.events:
            if isinstance(by_event, pd.DataFrame) and not by_event.empty and view.event_id in by_event.index:
                enriched = catalyst_view_for_event(snapshot, by_event.loc[view.event_id], now_utc=snapshot.now_utc, viewer_timezone=viewer_timezone)
                if enriched is not None:
                    views.append(enriched)
        if views:
            groups.append(TimelineMonthGroup(group.month_key, group.month_label, tuple(views)))
    return TimelineViewModel(
        flight_deck=build_flight_deck(snapshot, filters=filters, viewer_timezone=viewer_timezone),
        month_groups=tuple(groups),
        visible_event_count=sum(len(group.events) for group in groups),
    )


def render_timeline_page(
    snapshot: ControlTowerSnapshot,
    *,
    filters: EventFilters,
    viewer_timezone: str,
) -> TimelineViewModel:
    model = build_timeline_view(snapshot, filters=filters, viewer_timezone=viewer_timezone)
    render_flight_deck(model.flight_deck)
    st.caption(f"{model.visible_event_count} eligible event(s) · grouped by start month in {viewer_timezone}")
    with st.container(border=True):
        st.markdown('<div class="ct-panel-heading"><h3>Unified timeline</h3><span class="ct-count">company · macro · policy · index · thesis</span></div>', unsafe_allow_html=True)
        if not model.month_groups:
            st.markdown('<div class="ct-empty">No events match these filters.</div>', unsafe_allow_html=True)
        else:
            for group in model.month_groups:
                st.markdown(f'<div class="ct-timeline-month">{group.month_label} <span class="ct-count">{len(group.events)}</span></div>', unsafe_allow_html=True)
                for event in group.events:
                    render_catalyst(event, viewer_timezone=viewer_timezone)
    return model


__all__ = ["TimelineViewModel", "build_timeline_view", "render_timeline_page"]
