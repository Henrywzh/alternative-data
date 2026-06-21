from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.data import DATASET_REGISTRY, DatasetLoadResult
from dashboard.theme import (ACCENT, BG, SIDEBAR, CARD, BORDER, TEXT, MUTED, GREEN, RED, YELLOW, GRID, TICK, MODEL_COLORS)


def format_metric(value: float, metric_unit: str | None = None) -> str:
    if pd.isna(value):
        return "-"
    if metric_unit == "share":
        return f"{value:.2f}%"
    abs_v = abs(value)
    if abs_v >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.2f}T"
    if abs_v >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs_v >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs_v >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}"


def _empty_dataset_frame(dataset_id: str) -> pd.DataFrame:
    spec = DATASET_REGISTRY.get(dataset_id, {})
    required_columns = list(spec.get("required_columns", []))
    return pd.DataFrame(columns=required_columns)


def _styler_applymap_compat(styler, func, subset=None):
    if hasattr(styler, "map"):
        return styler.map(func, subset=subset)
    return styler.applymap(func, subset=subset)


WEEKLY_MONTHLY_OTHER_PROVIDERS = {
    "Tngtech",
    "Others",
    "OpenRouter",
    "Microsoft",
    "NousResearch",
    "NVIDIA",
    "Arcee AI",
}


DAILY_OTHER_PROVIDERS = {
    "Microsoft",
    "Meta (Llama)",
    "Mistral AI",
}


US_PROVIDER_ORDER = [
    "OpenAI",
    "Anthropic",
    "Google",
    "Meta (Llama)",
    "xAI (Grok)",
    "Microsoft",
]


CHINA_PROVIDER_ORDER = [
    "DeepSeek",
    "Alibaba (Qwen)",
    "智谱AI (Z.ai)",
    "Moonshot AI",
    "MiniMax",
    "Xiaomi",
    "Tencent",
    "StepFun",
]


def order_provider_columns(pivot_df: pd.DataFrame) -> pd.DataFrame:
    """Apply dashboard-wide provider order for token/revenue displays."""
    if pivot_df.empty:
        return pivot_df.copy()

    columns = list(pivot_df.columns)
    ordered: list[object] = []

    for provider in US_PROVIDER_ORDER + CHINA_PROVIDER_ORDER:
        if provider in columns:
            ordered.append(provider)

    known = set(US_PROVIDER_ORDER + CHINA_PROVIDER_ORDER + ["Others"])
    other_named = sorted((col for col in columns if col not in known), key=lambda value: str(value).casefold())
    ordered.extend(other_named)

    if "Others" in columns:
        ordered.append("Others")

    return pivot_df.loc[:, ordered]


def regroup_provider_pivot_for_display(pivot_df: pd.DataFrame, granularity: str) -> pd.DataFrame:
    """Fold selected provider labels into a display-only Others bucket."""
    if pivot_df.empty:
        return pivot_df.copy()

    if granularity in {"weekly", "monthly"}:
        targets = WEEKLY_MONTHLY_OTHER_PROVIDERS
    elif granularity == "daily":
        targets = DAILY_OTHER_PROVIDERS
    else:
        raise ValueError(f"Unsupported granularity: {granularity}")

    target_keys = {target.casefold() for target in targets}
    matched_cols = [col for col in pivot_df.columns if str(col).casefold() in target_keys]
    if not matched_cols:
        return order_provider_columns(pivot_df.copy())

    kept_cols = [col for col in pivot_df.columns if col not in matched_cols]
    regrouped = pivot_df[kept_cols].copy()
    regrouped["Others"] = pivot_df[matched_cols].sum(axis=1)
    return order_provider_columns(regrouped)


def render_dataset_guard(result: DatasetLoadResult, show_subheader: bool = False) -> bool:
    if show_subheader:
        st.subheader(result.label)
    if result.source_path is None:
        st.error(f"No file found for {result.dataset_id}.")
        return False
    if result.frame.empty:
        st.warning("Dataset is present but empty.")
        return False
    return True


def format_scraped_at_display(value: str | None) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return str(value)
    return timestamp.strftime("%Y-%m-%d %H:%M UTC")


def dataframe_for_display(frame: pd.DataFrame, missing_text: str = "") -> pd.DataFrame:
    """Fill display placeholders only for text-like columns to preserve numeric Arrow types."""
    display = frame.copy()
    if display.empty:
        return display
    for column in display.columns:
        series = display[column]
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            display[column] = series.where(series.notna(), missing_text)
        elif pd.api.types.is_datetime64_any_dtype(series):
            display[column] = series.astype("string").where(series.notna(), missing_text)
    return display


def make_stacked_bar(
    pivot_df: pd.DataFrame,
    colors: list[str],
    title: str = "",
    y_title: str = "",
    pct: bool = False,
    height: int = 380,
) -> go.Figure:
    fig = go.Figure()
    for i, col in enumerate(pivot_df.columns):
        fig.add_trace(go.Bar(
            name=col,
            x=pivot_df.index,
            y=pivot_df[col],
            marker_color=colors[i % len(colors)],
            hovertemplate=f"<b>{col}</b><br>%{{x}}<br>%{{y:,.2f}}<extra></extra>",
        ))
    layout: dict = dict(
        barmode="stack",
        template="plotly_white",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color=TEXT, size=12),
        legend=dict(orientation="h", y=-0.18, font=dict(size=11)),
        xaxis=dict(gridcolor=GRID, tickcolor=TICK, showgrid=False, tickfont=dict(size=11)),
        yaxis=dict(gridcolor=GRID, tickcolor=TICK, title=y_title, tickfont=dict(size=11)),
        height=height,
        margin=dict(l=0, r=0, t=40 if title else 10, b=80),
    )
    if title:
        layout["title"] = dict(text=title, font=dict(size=14, color=TEXT))
    fig.update_layout(**layout)
    if pct:
        fig.update_yaxes(ticksuffix="%")
    return fig


def make_stacked_area_chart(
    pivot_df: pd.DataFrame,
    display_index: list,
    colors: list[str],
    x_title: str = "",
    y_title: str = "",
    height: int = 400,
    value_format: str = ",.2f",
    hover_prefix: str = "",
    hover_suffix: str = "",
) -> go.Figure:
    """Stacked area chart factory for time-series metrics."""
    fig = go.Figure()
    suffix = f" {hover_suffix}" if hover_suffix else ""
    for i, col in enumerate(pivot_df.columns):
        fig.add_trace(go.Scatter(
            x=display_index, y=pivot_df[col], name=col,
            mode="lines+markers", stackgroup="one",
            line=dict(width=0.5, color=colors[i % len(colors)]),
            hovertemplate=f"<b>{col}</b><br>%{{x}}<br>{hover_prefix}%{{y:{value_format}}}{suffix}<extra></extra>",
        ))
    fig.update_layout(
        template="plotly_white", xaxis_title=x_title, yaxis_title=y_title,
        legend=dict(orientation="h", y=-0.2), height=height,
        margin=dict(l=0, r=0, t=20, b=80),
    )
    return fig


def make_line_chart(
    pivot_df: pd.DataFrame,
    colors: list[str],
    title: str = "",
    y_title: str = "",
    x_title: str = "Date",
    hover_suffix: str = "",
    height: int = 360,
    connect_gaps: bool = False,
) -> go.Figure:
    """Line chart factory — mirrors make_stacked_bar for time-series line charts."""
    fig = go.Figure()
    suffix = f" {hover_suffix}" if hover_suffix else ""
    for i, col in enumerate(pivot_df.columns):
        fig.add_trace(go.Scatter(
            x=pivot_df.index,
            y=pivot_df[col],
            name=col,
            mode="lines+markers",
            line=dict(width=3, color=colors[i % len(colors)]),
            connectgaps=connect_gaps,
            hovertemplate=f"<b>{col}</b><br>%{{x}}<br>%{{y:,.0f}}{suffix}<extra></extra>",
        ))
    layout: dict = dict(
        template="plotly_white",
        xaxis_title=x_title,
        yaxis_title=y_title,
        legend=dict(orientation="h", y=-0.2),
        height=height,
        margin=dict(l=0, r=0, t=40, b=80),
    )
    if title:
        layout["title"] = title
    fig.update_layout(**layout)
    return fig


def make_yoy_growth_chart(
    yoy_df: pd.DataFrame,
    colors: list[str],
    height: int = 400,
) -> go.Figure:
    fig = go.Figure()
    
    cols = [col for col in yoy_df.columns if col != "Aggregated"]
    for i, col in enumerate(cols):
        color = colors[i % len(colors)]
        fig.add_trace(go.Scatter(
            x=yoy_df.index,
            y=yoy_df[col],
            name=col,
            mode="lines+markers",
            line=dict(width=2, color=color),
            marker=dict(size=5),
            hovertemplate=f"<b>{col}</b><br>%{{x}}<br>%{{y:+.1f}}%<extra></extra>",
        ))
        
    if "Aggregated" in yoy_df.columns:
        fig.add_trace(go.Scatter(
            x=yoy_df.index,
            y=yoy_df["Aggregated"],
            name="Aggregated (Total)",
            mode="lines+markers",
            line=dict(width=4, color=TEXT, dash="dash"),
            marker=dict(size=7, symbol="diamond"),
            hovertemplate=f"<b>Aggregated (Total)</b><br>%{{x}}<br>%{{y:+.1f}}%<extra></extra>",
        ))
        
    fig.update_layout(
        template="plotly_white",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color=TEXT, size=12),
        legend=dict(orientation="h", y=-0.18, font=dict(size=11)),
        xaxis=dict(gridcolor=GRID, tickcolor=TICK, showgrid=False, tickfont=dict(size=11)),
        yaxis=dict(gridcolor=GRID, tickcolor=TICK, title="YoY Growth (%)", tickfont=dict(size=11), ticksuffix="%"),
        height=height,
        margin=dict(l=0, r=0, t=20, b=80),
    )
    return fig


def kpi_card_html(
    label: str,
    value: str,
    delta: str = "",
    delta_class: str = "flat",
    card_style: str = "",
    value_style: str = "",
) -> str:
    """Return a single .kpi-card HTML block. Wrap multiple cards in a .kpi-grid div."""
    card_attr = f' style="{card_style}"' if card_style else ""
    value_attr = f' style="{value_style}"' if value_style else ""
    delta_html = f'<div class="kpi-delta-{delta_class}">{delta}</div>' if delta else ""
    return (
        f'<div class="kpi-card"{card_attr}>'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value"{value_attr}>{value}</div>'
        f'{delta_html}'
        f'</div>'
    )


def kpi_grid_html(*cards: str) -> str:
    """Wrap kpi_card_html() outputs in a .kpi-grid container."""
    return '<div class="kpi-grid">' + "".join(cards) + "</div>"


def _top_n_with_others(pivot_df: pd.DataFrame, *, top_n_count: int = 15, exclude_others_named: bool = False, pct: bool = False) -> pd.DataFrame:
    if pivot_df.empty:
        return pivot_df.copy()

    if exclude_others_named:
        named_cols = [c for c in pivot_df.columns if str(c).lower() != "others"]
        other_cols = [c for c in pivot_df.columns if str(c).lower() == "others"]
        top_n_named = pivot_df[named_cols].sum().nlargest(top_n_count).index.tolist()
        rest_cols = [c for c in named_cols if c not in top_n_named] + other_cols
        base = pivot_df.copy()
        if pct:
            row_totals = base.sum(axis=1)
            base = base.div(row_totals, axis=0).mul(100).fillna(0)
        top = base[top_n_named].copy()
        if rest_cols:
            top["Others"] = base[rest_cols].sum(axis=1)
        return top

    top_n_cols = pivot_df.sum().nlargest(top_n_count).index.tolist()
    other_cols = [c for c in pivot_df.columns if c not in top_n_cols]
    top = pivot_df[top_n_cols].copy()
    if other_cols:
        existing_others = top["Others"].copy() if "Others" in top.columns else 0
        top["Others"] = existing_others + pivot_df[other_cols].sum(axis=1)
    return top
