"""OpenRouter-style Plotly factories for the Research Control Tower company cockpit."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ACCENT = "#2563EB"
TEXT = "#111827"
MUTED = "#6B7280"
GREEN = "#16A34A"
RED = "#DC2626"
YELLOW = "#D97706"
GRID = "#F3F4F6"
TICK = "#9CA3AF"
MODEL_COLORS = [
    "#4285F4", "#FF6B6B", "#00B5A4", "#FF7849",
    "#8B5CF6", "#EC4899", "#84CC16", "#F59E0B",
]
PARTIAL_FILL = "rgba(37, 99, 235, 0.28)"

# Plotly paints the plot background and tick text into the figure itself, so the
# app's Light/Dark CSS tokens cannot reach them and st.plotly_chart is called
# with theme=None. Mirror the two token sets here and apply one of them per
# figure; see apply_theme below.
LIGHT_CHART = {
    "paper": "#ffffff",
    "plot": "#ffffff",
    "ink": "#111827",
    "muted": "#6B7280",
    "grid": "#F3F4F6",
    "tick": "#9CA3AF",
}
DARK_CHART = {
    "paper": "#161b22",   # --ct-surface
    "plot": "#161b22",
    "ink": "#f0f2f6",     # --ct-ink
    "muted": "#94a3b8",   # --ct-muted
    "grid": "#252b36",    # --ct-surface-muted
    "tick": "#64748b",
}


def apply_theme(fig: go.Figure, dark: bool) -> go.Figure:
    """Repaint a finished figure for the active app theme, in place."""
    palette = DARK_CHART if dark else LIGHT_CHART
    fig.update_layout(
        template="plotly_dark" if dark else "plotly_white",
        paper_bgcolor=palette["paper"],
        plot_bgcolor=palette["plot"],
        font=dict(color=palette["ink"]),
        legend=dict(font=dict(color=palette["ink"])),
    )
    # update_xaxes/yaxes reach the secondary axis of the dual-axis figures too,
    # which a plain update_layout(yaxis=...) would leave on the light palette.
    fig.update_xaxes(tickfont=dict(color=palette["muted"]), tickcolor=palette["tick"], title_font=dict(color=palette["ink"]))
    fig.update_yaxes(tickfont=dict(color=palette["muted"]), tickcolor=palette["tick"], title_font=dict(color=palette["ink"]))
    fig.for_each_yaxis(lambda axis: axis.update(gridcolor=palette["grid"]) if axis.showgrid is not False else None)
    return fig


def _base_layout(
    *,
    title: str = "",
    y_title: str = "",
    x_title: str = "",
    height: int = 360,
    tickformat: str | None = "%b %Y",
) -> dict[str, Any]:
    layout: dict[str, Any] = dict(
        template="plotly_white",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color=TEXT, size=12),
        legend=dict(orientation="h", y=-0.22, font=dict(size=11)),
        xaxis=dict(
            title=x_title or None,
            gridcolor=GRID,
            tickcolor=TICK,
            showgrid=False,
            tickfont=dict(size=11),
            tickformat=tickformat,
        ),
        yaxis=dict(
            title=y_title or None,
            gridcolor=GRID,
            tickcolor=TICK,
            tickfont=dict(size=11),
        ),
        height=height,
        margin=dict(l=0, r=12, t=40 if title else 12, b=80),
        hovermode="x unified",
    )
    if title:
        layout["title"] = dict(text=title, font=dict(size=14, color=TEXT))
    return layout


def line_chart(
    frame: pd.DataFrame,
    *,
    colors: list[str] | None = None,
    title: str = "",
    y_title: str = "",
    x_title: str = "",
    height: int = 360,
    value_format: str = ",.2f",
    hover_suffix: str = "",
    tickformat: str | None = "%b %Y",
    connect_gaps: bool = False,
    mode: str = "lines",
) -> go.Figure:
    palette = colors or MODEL_COLORS
    fig = go.Figure()
    suffix = f" {hover_suffix}" if hover_suffix else ""
    for i, column in enumerate(frame.columns):
        fig.add_trace(
            go.Scatter(
                x=frame.index,
                y=frame[column],
                name=str(column),
                mode=mode,
                line=dict(width=3, color=palette[i % len(palette)]),
                connectgaps=connect_gaps,
                hovertemplate=f"<b>{column}</b><br>%{{x|%Y-%m-%d}}<br>%{{y:{value_format}}}{suffix}<extra></extra>",
            )
        )
    fig.update_layout(**_base_layout(title=title, y_title=y_title, x_title=x_title, height=height, tickformat=tickformat))
    return fig


def bar_chart(
    frame: pd.DataFrame,
    *,
    colors: list[str] | None = None,
    title: str = "",
    y_title: str = "",
    height: int = 320,
    value_format: str = ",.2f",
    hover_suffix: str = "",
    tickformat: str | None = "%b %Y",
    partial_mask: pd.Series | None = None,
) -> go.Figure:
    palette = colors or MODEL_COLORS
    fig = go.Figure()
    suffix = f" {hover_suffix}" if hover_suffix else ""
    for i, column in enumerate(frame.columns):
        marker_color = palette[i % len(palette)]
        if partial_mask is not None:
            colors_row = [PARTIAL_FILL if bool(flag) else marker_color for flag in partial_mask.reindex(frame.index).fillna(False)]
        else:
            colors_row = marker_color
        fig.add_trace(
            go.Bar(
                name=str(column),
                x=frame.index,
                y=frame[column],
                marker_color=colors_row,
                hovertemplate=f"<b>{column}</b><br>%{{x|%Y-%m-%d}}<br>%{{y:{value_format}}}{suffix}<extra></extra>",
            )
        )
    fig.update_layout(**_base_layout(title=title, y_title=y_title, height=height, tickformat=tickformat))
    return fig


def stacked_share_chart(
    frame: pd.DataFrame,
    *,
    colors: list[str] | None = None,
    title: str = "",
    y_title: str = "% of disclosed segment revenue",
    height: int = 320,
) -> go.Figure:
    palette = colors or ["#FF6B6B", "#93c5fd", "#2563EB"]
    fig = go.Figure()
    for i, column in enumerate(frame.columns):
        fig.add_trace(
            go.Bar(
                name=str(column),
                x=frame.index.astype(str),
                y=frame[column],
                marker_color=palette[i % len(palette)],
                hovertemplate=f"<b>{column}</b><br>%{{x}}<br>%{{y:.1f}}%<extra></extra>",
            )
        )
    layout = _base_layout(title=title, y_title=y_title, height=height, tickformat=None)
    layout["barmode"] = "stack"
    layout["xaxis"]["showgrid"] = False
    fig.update_layout(**layout)
    fig.update_yaxes(range=[0, 100], ticksuffix="%")
    return fig


def dual_axis_bar_line(
    frame: pd.DataFrame,
    *,
    bar_column: str,
    line_columns: list[str],
    bar_title: str,
    line_title: str,
    title: str = "",
    height: int = 340,
    bar_format: str = ",.1f",
    line_format: str = "+.1f",
    line_suffix: str = "%",
    bar_name: str | None = None,
    line_names: dict[str, str] | None = None,
) -> go.Figure:
    """``bar_name``/``line_names`` supply legend labels.

    Without them the legend showed the caller's internal column identifiers --
    ``revenue_rmb_b``, ``operating_profit_non_ifrs_rmb_b``, ``yoy_pct`` -- which
    is what the reader saw next to the line, beside a correctly worded axis.
    """
    display = dict(line_names or {})
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=frame.index.astype(str),
            y=frame[bar_column],
            name=bar_name or bar_column,
            marker_color="#93c5fd",
            hovertemplate=f"<b>{bar_name or bar_column}</b><br>%{{x}}<br>%{{y:{bar_format}}}<extra></extra>",
        ),
        secondary_y=False,
    )
    line_colors = [RED, YELLOW, GREEN]
    for i, column in enumerate(line_columns):
        fig.add_trace(
            go.Scatter(
                x=frame.index.astype(str),
                y=frame[column],
                name=display.get(column, column),
                mode="lines+markers",
                line=dict(width=3, color=line_colors[i % len(line_colors)], dash="solid" if i == 0 else "dash"),
                hovertemplate=f"<b>{display.get(column, column)}</b><br>%{{x}}<br>%{{y:{line_format}}}{line_suffix}<extra></extra>",
            ),
            secondary_y=True,
        )
    fig.update_layout(**_base_layout(title=title, height=height, tickformat=None))
    fig.update_yaxes(title_text=bar_title, secondary_y=False, gridcolor=GRID, tickcolor=TICK)
    fig.update_yaxes(title_text=line_title, secondary_y=True, showgrid=False, ticksuffix=line_suffix)
    fig.update_xaxes(showgrid=False, tickcolor=TICK)
    return fig
