from __future__ import annotations

import json
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import dataframe_for_display, format_metric, kpi_card_html, kpi_grid_html
from dashboard.data import DatasetLoadResult
from dashboard.theme import CARD, GRID, MODEL_COLORS, MUTED, TEXT


INCIDENTS_ID = "provider_incidents"
HEALTH_ID = "provider_incident_source_health"
SEVERITY_LABELS = {0: "Unclassified / none", 1: "Minor / low", 2: "Major / medium", 3: "Critical / high"}
SEVERITY_COLORS = {
    "Unclassified / none": "#94A3B8",
    "Minor / low": "#F59E0B",
    "Major / medium": "#F97316",
    "Critical / high": "#DC2626",
}


def _prepare_incidents(result: DatasetLoadResult | None) -> pd.DataFrame:
    if result is None or result.frame.empty:
        return pd.DataFrame()
    frame = result.frame.copy()
    for column in ("started_at", "published_at", "resolved_at"):
        frame[column] = pd.to_datetime(frame[column], format="mixed", errors="coerce", utc=True)
    frame["duration_minutes"] = pd.to_numeric(frame["duration_minutes"], errors="coerce")
    frame["severity_level"] = pd.to_numeric(frame["severity_level"], errors="coerce").fillna(0).clip(0, 3).astype(int)
    frame["severity_label"] = frame["severity_level"].map(SEVERITY_LABELS)
    frame["provider_name"] = frame["provider_name"].fillna(frame["provider_id"])
    frame["normalized_status"] = frame["normalized_status"].fillna("unknown").astype(str)
    frame["is_active_normalized"] = frame["normalized_status"] != "resolved"
    frame["activity_at"] = frame["started_at"].fillna(frame["published_at"]).fillna(frame["resolved_at"])
    return frame.dropna(subset=["activity_at"]).sort_values("activity_at")


def _component_text(value: object) -> str:
    if value is None or pd.isna(value):
        return "—"
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        return str(value)
    return ", ".join(str(item) for item in parsed) if isinstance(parsed, list) and parsed else "—"


def _render_kpis(frame: pd.DataFrame, range_label: str) -> None:
    active = frame[frame["is_active_normalized"]]
    resolved_minutes = frame["duration_minutes"].dropna()
    median_minutes = resolved_minutes.median() if not resolved_minutes.empty else None
    duration_coverage = (len(resolved_minutes) / len(frame) * 100.0) if len(frame) else 0.0
    st.markdown(
        kpi_grid_html(
            kpi_card_html("Active Reports", f"{len(active):,}", delta="provider-reported, not independently verified"),
            kpi_card_html("Affected Providers", f"{active['provider_id'].nunique():,}", delta="currently reporting an active issue"),
            kpi_card_html(f"Incidents · {range_label}", f"{len(frame):,}", delta="matching selected filters"),
            kpi_card_html(
                f"Known Duration · {range_label}",
                format_metric(float(resolved_minutes.sum())) + " min" if not resolved_minutes.empty else "—",
                delta=(
                    f"{duration_coverage:.0f}% duration coverage · median {median_minutes:,.0f} min MTTR"
                    if median_minutes is not None
                    else "duration unavailable"
                ),
            ),
        ),
        unsafe_allow_html=True,
    )


def _nice_integer_dtick(max_value: float, *, target_ticks: int = 8) -> int:
    """Pick an integer axis step that keeps count ticks readable at any scale."""
    if max_value <= target_ticks:
        return 1
    raw_step = max_value / target_ticks
    magnitude = 10 ** math.floor(math.log10(raw_step))
    for step in (1, 2, 5, 10):
        candidate = step * magnitude
        if candidate >= raw_step:
            return max(1, int(candidate))
    return max(1, int(10 * magnitude))


def _render_weekly_chart(frame: pd.DataFrame) -> None:
    weekly = (
        frame.assign(week=frame["activity_at"].dt.tz_convert(None).dt.to_period("W").dt.start_time)
        .groupby(["week", "severity_label"], observed=True)
        .size()
        .unstack(fill_value=0)
        .sort_index()
    )
    figure = go.Figure()
    for label in SEVERITY_LABELS.values():
        if label not in weekly.columns:
            continue
        figure.add_trace(
            go.Bar(
                x=weekly.index,
                y=weekly[label],
                name=label,
                marker_color=SEVERITY_COLORS[label],
                hovertemplate="%{x|%b %d, %Y}<br>%{y} incidents<extra>" + label + "</extra>",
            )
        )
    figure.update_layout(
        template="plotly_white",
        barmode="stack",
        height=350,
        margin=dict(l=0, r=0, t=12, b=55),
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        font=dict(color=TEXT, size=12),
        legend=dict(orientation="h", y=-0.18),
        xaxis=dict(showgrid=False),
        yaxis=dict(
            gridcolor=GRID,
            dtick=_nice_integer_dtick(float(weekly.sum(axis=1).max())),
            title="Provider-reported incidents",
        ),
        hovermode="x unified",
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def _render_provider_chart(frame: pd.DataFrame) -> None:
    counts = frame.groupby("provider_name").size().sort_values(ascending=True)
    figure = go.Figure(
        go.Bar(
            x=counts.values,
            y=counts.index,
            orientation="h",
            marker_color=MODEL_COLORS[0],
            hovertemplate="%{y}<br><b>%{x} incidents</b><extra></extra>",
        )
    )
    figure.update_layout(
        template="plotly_white",
        height=max(300, 34 * len(counts) + 90),
        margin=dict(l=0, r=15, t=12, b=45),
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        font=dict(color=TEXT, size=12),
        xaxis=dict(
            gridcolor=GRID,
            dtick=_nice_integer_dtick(float(counts.max())),
            title="Incidents in selected period",
        ),
        yaxis=dict(showgrid=False),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def _render_duration_chart(frame: pd.DataFrame) -> None:
    valid_duration = frame[frame["duration_minutes"].notna()].copy()
    if valid_duration.empty:
        st.info("No duration metadata is available for the selected providers or period.")
        return

    figure = go.Figure()
    for label in SEVERITY_LABELS.values():
        subset = valid_duration[valid_duration["severity_label"] == label]
        if subset.empty:
            continue
        figure.add_trace(
            go.Scatter(
                x=subset["activity_at"],
                y=subset["duration_minutes"],
                mode="markers",
                name=label,
                marker=dict(size=9, color=SEVERITY_COLORS[label], opacity=0.85),
                text=subset["title"],
                customdata=subset[["provider_name", "normalized_status"]].values,
                hovertemplate=(
                    "<b>%{customdata[0]}</b> - %{text}<br>"
                    "Date: %{x|%b %d, %Y %H:%M}<br>"
                    "Duration: <b>%{y:,.1f} mins</b> (%{customdata[1]})<extra>" + label + "</extra>"
                ),
            )
        )
    figure.update_layout(
        template="plotly_white",
        height=350,
        margin=dict(l=0, r=15, t=12, b=50),
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        font=dict(color=TEXT, size=12),
        legend=dict(orientation="h", y=-0.2),
        xaxis=dict(showgrid=False, title="Incident Start Date"),
        yaxis=dict(
            gridcolor=GRID,
            title="Outage Duration (Minutes, Log Scale)",
            type="log",
        ),
        hovermode="closest",
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def _render_downtime_by_provider(frame: pd.DataFrame) -> None:
    duration_stats = (
        frame.groupby("provider_name")["duration_minutes"]
        .agg(total_downtime="sum", median_mttr="median", count="count")
        .sort_values("total_downtime", ascending=True)
    )
    if duration_stats.empty or duration_stats["total_downtime"].sum() == 0:
        st.info("No known-duration incidents are available for the selected providers or period.")
        return

    figure = go.Figure(
        go.Bar(
            x=duration_stats["total_downtime"].values,
            y=duration_stats.index,
            orientation="h",
            marker_color=MODEL_COLORS[1],
            customdata=duration_stats["median_mttr"].values,
            hovertemplate="%{y}<br>Total Downtime: <b>%{x:,.0f} mins</b><br>Median MTTR: <b>%{customdata:,.0f} mins</b><extra></extra>",
        )
    )
    figure.update_layout(
        template="plotly_white",
        height=max(300, 34 * len(duration_stats) + 90),
        margin=dict(l=0, r=15, t=12, b=45),
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        font=dict(color=TEXT, size=12),
        xaxis=dict(
            gridcolor=GRID,
            title="Total Known Downtime (Minutes)",
        ),
        yaxis=dict(showgrid=False),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def _render_table(frame: pd.DataFrame) -> None:
    table = pd.DataFrame(
        {
            "Provider": frame["provider_name"],
            "Incident": frame["title"],
            "Status": frame["normalized_status"].str.replace("_", " ").str.title(),
            "Severity": frame["severity_label"],
            "Started": frame["started_at"],
            "Published": frame["published_at"],
            "Resolved": frame["resolved_at"],
            "Minutes": frame["duration_minutes"].round(0),
            "Affected services": frame["affected_components_json"].map(_component_text),
            "Source": frame["incident_url"],
        }
    ).assign(_activity_at=frame["activity_at"].values).sort_values("_activity_at", ascending=False).drop(columns="_activity_at")
    st.dataframe(
        dataframe_for_display(table),
        width="stretch",
        hide_index=True,
        column_config={
            "Source": st.column_config.LinkColumn("Source", display_text="Open report"),
            "Minutes": st.column_config.NumberColumn("Minutes", format="%.0f"),
            "Started": st.column_config.DatetimeColumn("Started", format="YYYY-MM-DD HH:mm"),
            "Published": st.column_config.DatetimeColumn("Published", format="YYYY-MM-DD HH:mm"),
            "Resolved": st.column_config.DatetimeColumn("Resolved", format="YYYY-MM-DD HH:mm"),
        },
    )


def _render_coverage(result: DatasetLoadResult | None) -> None:
    st.markdown('<div class="section-title">Coverage & Definitions</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">This tracker records what providers publish on their own status pages. Feed coverage and disclosure practices differ, so incident counts are not a provider reliability ranking.</div>',
        unsafe_allow_html=True,
    )
    if result is None or result.frame.empty:
        st.warning("Source-health data is not available yet.")
        return
    health = result.frame.copy().sort_values("provider_name")
    coverage = pd.DataFrame(
        {
            "Provider": health["provider_name"],
            "Feed": health["source_system"],
            "Collection": health["status"].str.title(),
            "Incidents in current feed": pd.to_numeric(health["incident_rows"], errors="coerce"),
            "Feed state last changed": health["scraped_at"],
            "Official source": health["source_url"],
            "Detail": health["detail"],
        }
    )
    st.dataframe(
        dataframe_for_display(coverage),
        width="stretch",
        hide_index=True,
        column_config={"Official source": st.column_config.LinkColumn("Official source", display_text="Open feed")},
    )
    st.caption(
        "Known duration is the sum of published incident durations, not measured user impact or downtime. It is calculated only when a source publishes usable start and resolution timestamps; RSS/Atom-only providers may expose less history or severity detail."
    )


def render(domain_states, datasets: dict[str, DatasetLoadResult]) -> None:
    _ = domain_states
    st.markdown('<div class="section-title" style="margin-top:0.25rem;">AI Provider Incidents</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Provider-reported API and model-service incidents from ten official public status feeds. This is an operational disclosure tracker, not independent uptime measurement.</div>',
        unsafe_allow_html=True,
    )
    incidents = _prepare_incidents(datasets.get(INCIDENTS_ID))
    if incidents.empty:
        st.info("No provider incident history has been collected yet. The collector can still show source coverage after its first run.")
        _render_coverage(datasets.get(HEALTH_ID))
        return

    provider_options = sorted(incidents["provider_name"].dropna().astype(str).unique())
    filter_col, range_col, maintenance_col = st.columns([2, 1, 1], vertical_alignment="bottom")
    with filter_col:
        selected_providers = st.multiselect("Providers", provider_options, default=provider_options)
    with range_col:
        range_label = st.selectbox("History", ("30 days", "90 days", "1 year", "All"), index=1)
    with maintenance_col:
        include_maintenance = st.toggle("Include maintenance", value=False)

    scoped = incidents[incidents["provider_name"].isin(selected_providers)].copy()
    days = {"30 days": 30, "90 days": 90, "1 year": 365}.get(range_label)
    if days is not None:
        scoped = scoped[scoped["activity_at"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)]
    if not include_maintenance:
        scoped = scoped[scoped["incident_type"] != "maintenance"]

    _render_kpis(scoped, range_label)

    if scoped.empty:
        st.info("No provider-reported incidents match these filters.")
    else:
        st.markdown('<div class="section-title">Incident Activity</div>', unsafe_allow_html=True)
        st.caption("Severity labels preserve provider terminology where available; feed-only sources may use title-based classification.")
        chart_col, provider_col = st.columns([2, 1])
        with chart_col:
            _render_weekly_chart(scoped)
        with provider_col:
            _render_provider_chart(scoped)

        st.markdown('<div class="section-title">Incident Duration & MTTR Analysis</div>', unsafe_allow_html=True)
        st.caption("Logarithmic duration scatter plot per incident alongside total known downtime per provider.")
        dur_col, downtime_col = st.columns([2, 1])
        with dur_col:
            _render_duration_chart(scoped)
        with downtime_col:
            _render_downtime_by_provider(scoped)

        st.markdown('<div class="section-title">Incident Timeline</div>', unsafe_allow_html=True)
        _render_table(scoped)

    _render_coverage(datasets.get(HEALTH_ID))
