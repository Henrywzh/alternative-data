from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from dashboard.components import dataframe_for_display, format_metric, kpi_card_html, kpi_grid_html
from dashboard.data import DatasetLoadResult
from dashboard.theme import ACCENT, CARD, GRID, MODEL_COLORS, MUTED, TEXT


DATASET_ID = "market_pulse_daily"
SIGNAL_DATASET_ID = "overview_signal_series"


@st.cache_data(ttl=3600, max_entries=8)
def compute_market_pulse_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    result = datasets.get(DATASET_ID)
    if result is None or result.frame.empty:
        return {}
    pulse = result.frame.copy()
    pulse["pulse_date"] = pd.to_datetime(pulse["pulse_date"], errors="coerce")
    pulse["openrouter_total_tokens"] = pd.to_numeric(pulse["openrouter_total_tokens"], errors="coerce")
    pulse = pulse.dropna(subset=["pulse_date", "openrouter_total_tokens"]).sort_values("pulse_date")
    if pulse.empty:
        return {}

    signal_result = datasets.get(SIGNAL_DATASET_ID)
    signals = signal_result.frame.copy() if signal_result is not None and not signal_result.frame.empty else pd.DataFrame()
    if not signals.empty:
        signals["signal_date"] = pd.to_datetime(signals["signal_date"], errors="coerce")
        signals["value"] = pd.to_numeric(signals["value"], errors="coerce")
        signals["is_complete"] = signals["is_complete"].fillna(True).astype(bool)
        signals = signals.dropna(subset=["signal_date", "value"]).sort_values(["signal_id", "signal_date"])

    latest = pulse.iloc[-1]
    previous = pulse.iloc[-2] if len(pulse) > 1 else None
    dod = None
    if previous is not None and float(previous["openrouter_total_tokens"]) > 0:
        dod = (float(latest["openrouter_total_tokens"]) / float(previous["openrouter_total_tokens"]) - 1.0) * 100.0
    return {"pulse": pulse, "signals": signals, "latest": latest, "dod_pct": dod}


def _safe_float(row: pd.Series, column: str) -> float | None:
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    return float(value)


def _safe_text(row: pd.Series, column: str, fallback: str = "—") -> str:
    value = row.get(column)
    return fallback if value is None or pd.isna(value) or str(value).strip() == "" else str(value)


def _format_as_of(value: object, fallback: str = "—") -> str:
    """Normalize Overview source dates to an ISO calendar date."""
    if value is None or pd.isna(value) or str(value).strip() == "":
        return fallback
    parsed = pd.to_datetime(value, errors="coerce")
    return str(value) if pd.isna(parsed) else pd.Timestamp(parsed).strftime("%Y-%m-%d")


def _signal(signals: pd.DataFrame, signal_id: str, *, complete_only: bool = False) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame(columns=signals.columns)
    result = signals[signals["signal_id"].astype(str).eq(signal_id)].copy()
    if complete_only and "is_complete" in result.columns:
        result = result[result["is_complete"]]
    return result.sort_values("signal_date")


def _latest_signal(signals: pd.DataFrame, signal_id: str, *, complete_only: bool = False) -> pd.Series | None:
    series = _signal(signals, signal_id, complete_only=complete_only)
    return None if series.empty else series.iloc[-1]


def _period_change(series: pd.DataFrame) -> float | None:
    if len(series) < 2:
        return None
    prior = float(series.iloc[-2]["value"])
    return None if prior == 0 else (float(series.iloc[-1]["value"]) / prior - 1.0) * 100.0


def _render_kpis(latest: pd.Series, signals: pd.DataFrame, dod_pct: float | None) -> None:
    tokens = _safe_float(latest, "openrouter_total_tokens")
    token_delta = "official full market" if dod_pct is None else f"{'↑' if dod_pct >= 0 else '↓'} {abs(dod_pct):.1f}% DoD"
    token_class = "flat" if dod_pct is None else "up" if dod_pct >= 0 else "down"

    revenue_series = _signal(signals, "openrouter_estimated_revenue", complete_only=True)
    revenue_latest = None if revenue_series.empty else float(revenue_series.iloc[-1]["value"])
    revenue_change = _period_change(revenue_series)
    revenue_delta = "tracked providers · modeled" if revenue_change is None else f"{'↑' if revenue_change >= 0 else '↓'} {abs(revenue_change):.1f}% DoD"

    adoption = _safe_float(latest, "ramp_ai_adoption_pct")
    adoption_yoy = _safe_float(latest, "ramp_ai_adoption_yoy_pp")
    ppi = _safe_float(latest, "ai_demand_ppi")
    ppi_mom = _safe_float(latest, "ai_demand_ppi_mom_pct")
    frontier_us = _latest_signal(signals, "frontier_intelligence_us")
    frontier_china = _latest_signal(signals, "frontier_intelligence_china")
    hiring = _latest_signal(signals, "ai_hiring_active_postings")
    frontier_value = "—"
    frontier_label = "Artificial Analysis"
    if frontier_us is not None and frontier_china is not None:
        frontier_value = f"{float(frontier_us['value']):.1f} / {float(frontier_china['value']):.1f}"
        frontier_label = "US / China index"

    st.markdown(
        kpi_grid_html(
            kpi_card_html(
                "OpenRouter Daily Tokens",
                format_metric(tokens) if tokens is not None else "—",
                delta=token_delta,
                delta_class=token_class,
            ),
            kpi_card_html(
                "Estimated Daily Revenue",
                f"${format_metric(revenue_latest)}" if revenue_latest is not None else "—",
                delta=revenue_delta,
                delta_class="flat" if revenue_change is None else "up" if revenue_change >= 0 else "down",
            ),
            kpi_card_html(
                "AI Demand PPI",
                f"{ppi:.1f}" if ppi is not None else "—",
                delta=f"{ppi_mom:+.2f}% MoM" if ppi_mom is not None else "weighted FRED basket",
                delta_class="up" if ppi_mom is not None and ppi_mom >= 0 else "down" if ppi_mom is not None else "flat",
            ),
            kpi_card_html(
                "Business AI Adoption",
                f"{adoption:.1f}%" if adoption is not None else "—",
                delta=f"{adoption_yoy:+.1f} pts YoY · Ramp" if adoption_yoy is not None else "Ramp AI Index",
                delta_class="up" if adoption_yoy is not None and adoption_yoy >= 0 else "down" if adoption_yoy is not None else "flat",
            ),
            kpi_card_html(
                "US vs China Frontier",
                frontier_value,
                delta=frontier_label,
            ),
            kpi_card_html(
                "Tracked AI Hiring",
                format_metric(float(hiring["value"])) if hiring is not None else "—",
                delta="active postings · new tracker",
            ),
        ),
        unsafe_allow_html=True,
    )


def _base_layout(*, height: int, legend_y: float = -0.16) -> dict:
    return {
        "template": "plotly_white",
        "height": height,
        "margin": dict(l=0, r=8, t=24, b=50),
        "paper_bgcolor": CARD,
        "plot_bgcolor": CARD,
        "font": dict(color=TEXT, size=12),
        "legend": dict(orientation="h", y=legend_y, x=0),
        "hovermode": "x unified",
    }


def _render_openrouter_economics(signals: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">AI Usage &amp; Economics</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Official full-market tokens reconciled with tracked-provider volume and modeled daily revenue. '
        'Only completed UTC days are plotted.</div>',
        unsafe_allow_html=True,
    )
    window = st.segmented_control(
        "History",
        options=["35 days", "90 days", "180 days"],
        default="90 days",
        key="overview_economics_window",
    )
    days = {"35 days": 35, "90 days": 90, "180 days": 180}.get(str(window), 90)
    full = _signal(signals, "openrouter_full_market_tokens", complete_only=True)
    tracked = _signal(signals, "openrouter_tracked_tokens", complete_only=True)
    revenue = _signal(signals, "openrouter_estimated_revenue", complete_only=True)
    available = pd.concat([frame[["signal_date"]] for frame in (full, tracked, revenue) if not frame.empty], ignore_index=True)
    if available.empty:
        st.info("The compact OpenRouter economics series has not been generated yet.")
        return
    cutoff = available["signal_date"].max() - pd.Timedelta(days=days - 1)
    full = full[full["signal_date"] >= cutoff]
    tracked = tracked[tracked["signal_date"] >= cutoff]
    revenue = revenue[revenue["signal_date"] >= cutoff]

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.10,
        row_heights=[0.58, 0.42],
        subplot_titles=("Daily Token Volume", "Estimated Daily Revenue"),
    )
    if not tracked.empty:
        fig.add_trace(
            go.Scatter(
                x=tracked["signal_date"],
                y=tracked["value"],
                name="Tracked providers",
                mode="lines",
                line=dict(color=MODEL_COLORS[2], width=2),
                hovertemplate="%{x|%b %d}<br>%{y:,.0f} tokens<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if not full.empty:
        fig.add_trace(
            go.Scatter(
                x=full["signal_date"],
                y=full["value"],
                name="Official full market",
                mode="lines",
                line=dict(color=ACCENT, width=2.5),
                hovertemplate="%{x|%b %d}<br>%{y:,.0f} tokens<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if not revenue.empty:
        backcast = revenue[revenue["detail_label"].astype(str).eq("backcast_earliest_pricing")]
        as_of = revenue[~revenue.index.isin(backcast.index)]
        if not backcast.empty and not as_of.empty:
            backcast = pd.concat([backcast, as_of.head(1)], ignore_index=True)
        if not backcast.empty:
            fig.add_trace(
                go.Scatter(
                    x=backcast["signal_date"],
                    y=backcast["value"],
                    name="Revenue · backcast",
                    mode="lines",
                    line=dict(color=MODEL_COLORS[4], width=2, dash="dot"),
                    hovertemplate="%{x|%b %d}<br>$%{y:,.0f}<br>Earliest known pricing backcast<extra></extra>",
                ),
                row=2,
                col=1,
            )
        fig.add_trace(
            go.Scatter(
                x=as_of["signal_date"],
                y=as_of["value"],
                name="Revenue · as-of pricing",
                mode="lines",
                fill="tozeroy",
                line=dict(color=MODEL_COLORS[4], width=2),
                fillcolor="rgba(139,92,246,0.10)",
                hovertemplate="%{x|%b %d}<br>$%{y:,.0f}<extra></extra>",
            ),
            row=2,
            col=1,
        )
        if not backcast.empty and not as_of.empty:
            pricing_start = as_of["signal_date"].min()
            fig.add_vrect(
                x0=revenue["signal_date"].min(),
                x1=pricing_start,
                fillcolor="rgba(139,92,246,0.055)",
                line_width=0,
                layer="below",
                row=2,
                col=1,
            )
            fig.add_vline(
                x=pricing_start,
                line=dict(color=MUTED, width=1, dash="dash"),
                row=2,
                col=1,
            )
    fig.update_yaxes(title_text="Tokens", tickformat="~s", gridcolor=GRID, row=1, col=1)
    fig.update_yaxes(title_text="USD", tickprefix="$", tickformat="~s", gridcolor=GRID, row=2, col=1)
    fig.update_xaxes(showgrid=False)
    fig.update_layout(**_base_layout(height=570, legend_y=-0.12))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    common_dates = sorted(set(full["signal_date"]) & set(tracked["signal_date"]))
    if common_dates:
        common_date = common_dates[-1]
        full_value = float(full.loc[full["signal_date"].eq(common_date), "value"].iloc[-1])
        tracked_value = float(tracked.loc[tracked["signal_date"].eq(common_date), "value"].iloc[-1])
        share = tracked_value / full_value if full_value else 0.0
        # The backcast/as-of split date isn't fixed -- it's wherever priced-model
        # history actually starts, so derive the caption from the real data
        # rather than hardcoding a date that goes stale as pricing history grows.
        backcast_caption = "Solid revenue uses as-of pricing throughout the plotted history."
        if not revenue.empty:
            backcast_rows = revenue[revenue["detail_label"].astype(str).eq("backcast_earliest_pricing")]
            as_of_rows = revenue[~revenue.index.isin(backcast_rows.index)]
            if not backcast_rows.empty and not as_of_rows.empty:
                pricing_start_label = as_of_rows["signal_date"].min().strftime("%b %d")
                backcast_caption = (
                    f"Dotted revenue before {pricing_start_label} uses the earliest known price snapshot as a "
                    "backcast; solid revenue uses as-of pricing."
                )
        st.caption(
            f"On {common_date:%b %d}, configured providers represented {share:.1%} of official full-market tokens. "
            "OpenRouter’s ‘Other’ bucket is the model long tail below the daily top 50, not an other-provider bucket. "
            f"{backcast_caption}"
        )


def _line_chart(
    series: list[tuple[pd.DataFrame, str, str, str]],
    *,
    y_title: str,
    height: int = 360,
    tick_suffix: str = "",
) -> go.Figure:
    fig = go.Figure()
    for frame, name, color, dash in series:
        if frame.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=frame["signal_date"],
                y=frame["value"],
                name=name,
                mode="lines",
                line=dict(color=color, width=2.2, dash=dash),
                hovertemplate=f"%{{x|%b %Y}}<br>%{{y:,.2f}}{tick_suffix}<extra></extra>",
            )
        )
    fig.update_layout(**_base_layout(height=height))
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(title=y_title, gridcolor=GRID, ticksuffix=tick_suffix)
    return fig


def _render_adoption_and_demand(signals: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Demand &amp; Adoption</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Infrastructure pricing pressure alongside business adoption and spend intensity.</div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### AI Demand PPI")
        ppi = _signal(signals, "ai_demand_ppi").tail(48)
        trend = _signal(signals, "ai_demand_ppi_3m_trend").tail(48)
        st.plotly_chart(
            _line_chart(
                [(ppi, "AI Demand PPI", ACCENT, "solid"), (trend, "3-month trend", MODEL_COLORS[4], "dash")],
                y_title="Index",
            ),
            width="stretch",
            config={"displayModeBar": False},
        )
        st.caption("Weighted FRED producer-price basket for semiconductors, storage, compute equipment, and related inputs.")
    with right:
        st.markdown("#### Business AI Adoption & Spend")
        adoption = _signal(signals, "ramp_ai_adoption")
        pepm = _signal(signals, "ramp_ai_median_pepm")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Scatter(
                x=adoption["signal_date"], y=adoption["value"], name="AI adoption",
                mode="lines", line=dict(color=ACCENT, width=2.4),
                hovertemplate="%{x|%b %Y}<br>%{y:.1f}%<extra></extra>",
            ),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                x=pepm["signal_date"], y=pepm["value"], name="Median spend / employee",
                mode="lines", line=dict(color=MODEL_COLORS[3], width=2, dash="dot"),
                hovertemplate="%{x|%b %Y}<br>$%{y:.2f}<extra></extra>",
            ),
            secondary_y=True,
        )
        fig.update_layout(**_base_layout(height=360))
        fig.update_xaxes(showgrid=False)
        fig.update_yaxes(title_text="Adoption (%)", ticksuffix="%", gridcolor=GRID, secondary_y=False)
        fig.update_yaxes(title_text="USD / employee / month", tickprefix="$", secondary_y=True)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.caption("Ramp’s observed business adoption rate and median monthly AI spend per employee.")


def _render_frontier_and_reliability(signals: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Frontier Progress &amp; Reliability</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Model capability progression and provider-reported operational incidents.</div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### Frontier Intelligence · US vs China")
        fig = go.Figure()
        for signal_id, country, color in (
            ("frontier_intelligence_us", "United States", "#2563EB"),
            ("frontier_intelligence_china", "China", "#DC2626"),
        ):
            frontier = _signal(signals, signal_id)
            fig.add_trace(
                go.Scatter(
                    x=frontier["signal_date"],
                    y=frontier["value"],
                    customdata=frontier["detail_label"],
                    name=country,
                    mode="lines+markers",
                    line=dict(color=color, width=2.4, shape="hv"),
                    marker=dict(size=6),
                    hovertemplate=(
                        "%{x|%b %d, %Y}<br>Index %{y:.1f}<br>"
                        "%{customdata}<extra>%{fullData.name}</extra>"
                    ),
                )
            )
        fig.update_layout(**_base_layout(height=360))
        fig.update_xaxes(showgrid=False)
        fig.update_yaxes(title="Artificial Analysis index", gridcolor=GRID)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.caption(
            "Country frontier by model release date. Each line steps up only when a newly released model from that country raises its intelligence high-water mark; geography uses Artificial Analysis metadata with its provider-slug fallback."
        )
    with right:
        st.markdown("#### Provider Incidents")
        incidents = _signal(signals, "provider_incidents")
        colors = [ACCENT if bool(value) else "rgba(37,99,235,0.35)" for value in incidents["is_complete"]]
        fig = go.Figure(
            go.Bar(
                x=incidents["signal_date"],
                y=incidents["value"],
                customdata=incidents["detail_label"],
                marker_color=colors,
                name="Incidents",
                hovertemplate="%{x|%b %Y}<br>%{y:.0f} incidents<br>%{customdata}<extra></extra>",
            )
        )
        fig.update_layout(**_base_layout(height=360))
        fig.update_xaxes(showgrid=False)
        fig.update_yaxes(title="Incidents", gridcolor=GRID, rangemode="tozero")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.caption("Provider-reported public incidents by start or publication month. The lighter final bar is month-to-date.")


def _render_latest_signals(latest: pd.Series, signals: pd.DataFrame) -> None:
    momentum = _latest_signal(signals, "developer_momentum_leader")
    hiring = _latest_signal(signals, "ai_hiring_active_postings")
    ai_roles = _latest_signal(signals, "ai_hiring_ai_roles")
    incident = _latest_signal(signals, "provider_incidents")
    app_tokens = _safe_float(latest, "top_app_tokens")
    task_share = _safe_float(latest, "top_task_share_pct")
    top_model_share = _safe_float(latest, "openrouter_top_model_share_pct")

    rows = [
        {
            "Area": "AI Usage",
            "Signal": "Top OpenRouter model",
            "Reading": _safe_text(latest, "openrouter_top_model"),
            "Context": f"{top_model_share:.1f}% of daily full-market tokens" if top_model_share is not None else "Daily leader",
            "As of": _format_as_of(latest.get("pulse_date")),
        },
        {
            "Area": "AI Usage",
            "Signal": "Top public app",
            "Reading": _safe_text(latest, "top_app"),
            "Context": f"{format_metric(app_tokens)} tokens in official ranking window" if app_tokens is not None else "Official app ranking",
            "As of": _format_as_of(latest.get("top_app_as_of")),
        },
        {
            "Area": "Use Cases",
            "Signal": "Leading task",
            "Reading": _safe_text(latest, "top_task"),
            "Context": f"{task_share:.1f}% of sampled requests" if task_share is not None else "7-day sample",
            "As of": _format_as_of(latest.get("top_task_as_of")),
        },
    ]
    if momentum is not None:
        rows.append(
            {
                "Area": "Adoption",
                "Signal": "Developer momentum",
                "Reading": str(momentum.get("detail_label") or "—"),
                "Context": f"Composite score {float(momentum['value']):.2f}",
                "As of": _format_as_of(momentum.get("signal_date")),
            }
        )
    if hiring is not None:
        ai_role_value = float(ai_roles["value"]) if ai_roles is not None else None
        rows.append(
            {
                "Area": "Hiring",
                "Signal": "Tracked company demand",
                "Reading": f"{float(hiring['value']):,.0f} active postings",
                "Context": f"{ai_role_value:,.0f} explicitly AI/ML" if ai_role_value is not None else "Coverage history is building",
                "As of": _format_as_of(hiring.get("signal_date")),
            }
        )
    if incident is not None:
        rows.append(
            {
                "Area": "Reliability",
                "Signal": "Provider incidents",
                "Reading": f"{float(incident['value']):,.0f} month-to-date",
                "Context": str(incident.get("detail_label") or "provider-reported sources"),
                "As of": _format_as_of(incident.get("signal_date")),
            }
        )

    st.dataframe(dataframe_for_display(pd.DataFrame(rows)), width="stretch", hide_index=True, height=248)


def _render_sources(latest: pd.Series, signals: pd.DataFrame) -> None:
    rows = [
        {"Signal": "OpenRouter full market", "As of": _format_as_of(latest.get("pulse_date")), "Dataset": "official_model_rankings_daily", "Source": latest.get("openrouter_source_url")},
        {"Signal": "OpenRouter economics", "As of": None, "Dataset": "provider_revenue_estimates", "Source": "Derived from provider activity and OpenRouter pricing"},
        {"Signal": "Ramp AI adoption", "As of": _format_as_of(latest.get("ramp_as_of")), "Dataset": "ramp_ai_adoption_overall", "Source": latest.get("ramp_source_url")},
        {"Signal": "AI demand PPI", "As of": _format_as_of(latest.get("semiconductor_as_of")), "Dataset": "fred_semiconductor_ppi_monthly", "Source": latest.get("semiconductor_source_url")},
        {"Signal": "Frontier intelligence", "As of": _format_as_of(latest.get("frontier_as_of")), "Dataset": "artificial_analysis_models_daily", "Source": latest.get("frontier_source_url")},
    ]
    if not signals.empty:
        source_dates = signals.groupby("source_dataset")["signal_date"].max()
        for row in rows:
            source_date = source_dates.get(row["Dataset"])
            if row["As of"] is None and pd.notna(source_date):
                row["As of"] = _format_as_of(source_date)
    st.dataframe(
        dataframe_for_display(pd.DataFrame(rows)),
        width="stretch",
        hide_index=True,
        column_config={
            "Signal": st.column_config.TextColumn(width="medium"),
            "Dataset": st.column_config.TextColumn(width="medium"),
            "Source": st.column_config.TextColumn(width="large"),
        },
    )


def render(domain_states, datasets: dict[str, DatasetLoadResult]) -> None:
    _ = domain_states
    views = compute_market_pulse_views(datasets)
    if not views:
        st.info("The compact Overview marts have not been generated yet. Detailed dashboard sections are still available.")
        return
    latest: pd.Series = views["latest"]  # type: ignore[assignment]
    signals: pd.DataFrame = views["signals"]  # type: ignore[assignment]
    _render_kpis(latest, signals, views["dod_pct"])  # type: ignore[arg-type]

    if signals.empty:
        st.info("Historical cross-dashboard signals will appear after the next daily Overview refresh.")
    else:
        _render_openrouter_economics(signals)
        _render_adoption_and_demand(signals)
        _render_frontier_and_reliability(signals)

    st.markdown('<div class="section-title">Latest Cross-Market Signals</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Current leaders and operating readings retained at each source’s own publication date.</div>',
        unsafe_allow_html=True,
    )
    _render_latest_signals(latest, signals)

    with st.expander("Source dates and lineage"):
        st.caption("Independent datasets publish on different schedules; Overview does not force their dates to match.")
        _render_sources(latest, signals)
