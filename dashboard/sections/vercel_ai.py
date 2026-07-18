"""Vercel AI Gateway section.

Surfaces the Vercel AI Gateway leaderboard as market-share-over-time. The view
is organised the way the public Vercel dashboard is:

- primary toggle: **Top Models** vs **Top Labs** (models vs providers),
- **All / Text / Image / Video** modality sub-tabs,
- within each modality, a metric selector (tokens / requests / spend, plus the
  image/video counts where the modality reports them).

Data comes from the `vercel_model_leaderboard` and `vercel_lab_leaderboard`
datasets, both keyed on `[date, name, metric, modality]`.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components import (
    kpi_card_html,
    kpi_grid_html,
    make_line_chart,
    make_stacked_area_chart,
    render_dataset_guard,
)
from dashboard.data import DatasetLoadResult

ENTITIES = {
    "Top Models": "vercel_model_leaderboard",
    "Top Labs": "vercel_lab_leaderboard",
}

MODALITY_ORDER = ["all", "text", "image", "video"]
MODALITY_LABELS = {"all": "All", "text": "Text", "image": "Image", "video": "Video"}

# Only the three usage metrics are user-facing. Vercel also emits imageCount /
# videoCount, but those are volume counts, not share views, so they are excluded
# from the selector — the modality sub-tabs already scope models by media type.
METRIC_ORDER = ["tokens", "requests", "spend"]
METRIC_LABELS = {"tokens": "Tokens", "requests": "Requests", "spend": "Spend"}

# How many named entities may contribute on each date. The chart retains the
# cumulative union of entities that have entered these daily ranks, while only
# the daily top-N have non-zero named share on any individual date.
TOP_N_BY_ENTITY = {"Top Models": 9, "Top Labs": 20}
DEFAULT_TOP_N = 10

# Residual band label differs by entity: model shares don't sum to 100% (Vercel
# truncates), so the remainder is genuinely unranked; lab shares do sum to 100%,
# so the remainder is simply the smaller labs.
OTHERS_LABEL_BY_ENTITY = {
    "Top Models": "Others (unranked)",
    "Top Labs": "Others (smaller labs)",
}
DEFAULT_OTHERS_LABEL = "Others"

# Reserve a neutral grey exclusively for the residual band so it can never share
# a colour with a real series. NAMED_PALETTE holds enough distinct hues (>= the
# largest TOP_N) that no two named series collide either.
OTHERS_COLOR = "#9CA3AF"
NAMED_PALETTE = [
    "#4285F4", "#FF6B6B", "#00B5A4", "#FF7849", "#8B5CF6", "#EC4899",
    "#84CC16", "#F59E0B", "#06B6D4", "#2563EB", "#DC2626", "#059669",
    "#D97706", "#7C3AED", "#DB2777", "#65A30D", "#0891B2", "#E11D48",
    "#16A34A", "#9333EA", "#CA8A04", "#0D9488", "#F43F5E", "#3B82F6",
]


def _others_label(entity_label: str) -> str:
    return OTHERS_LABEL_BY_ENTITY.get(entity_label, DEFAULT_OTHERS_LABEL)


def _column_colors(columns: list[str], others_label: str) -> list[str]:
    """Map named series to NAMED_PALETTE (stable order) and the residual to grey."""
    palette: list[str] = []
    named_idx = 0
    for column in columns:
        if column == others_label:
            palette.append(OTHERS_COLOR)
        else:
            palette.append(NAMED_PALETTE[named_idx % len(NAMED_PALETTE)])
            named_idx += 1
    return palette


def _prep(result: DatasetLoadResult | None) -> pd.DataFrame:
    if result is None or result.frame.empty:
        return pd.DataFrame()
    frame = result.frame.copy()
    frame["date"] = frame["date"].astype(str)
    frame["share_percent"] = pd.to_numeric(frame["share_percent"], errors="coerce")
    return frame


def _available_modalities(frame: pd.DataFrame) -> list[str]:
    present = set(frame["modality"].dropna()) if not frame.empty else set()
    return [m for m in MODALITY_ORDER if m in present]


def _available_metrics(frame: pd.DataFrame, modality: str) -> list[str]:
    present = set(frame[frame["modality"] == modality]["metric"].dropna())
    return [m for m in METRIC_ORDER if m in present]


def _default_metric(metrics: list[str]) -> int:
    """Prefer tokens; otherwise the first available metric (e.g. requests for video)."""
    return metrics.index("tokens") if "tokens" in metrics else 0


def _pivot(frame: pd.DataFrame, modality: str, metric: str) -> pd.DataFrame:
    subset = frame[(frame["modality"] == modality) & (frame["metric"] == metric)]
    if subset.empty:
        return pd.DataFrame()
    pivot = subset.pivot_table(index="date", columns="name", values="share_percent", aggfunc="sum")
    return pivot.sort_index()


def _daily_ranked(pivot: pd.DataFrame, n: int) -> pd.DataFrame:
    """Union of entities that reached the daily top-N, masked to ranked days.

    Columns are ordered by first top-N appearance and rank on that date. This
    makes the series universe cumulative: a newly ranked entity is added at
    once, while an entity outside the published ranking contributes no named
    share until it re-enters.
    """
    if pivot.empty:
        return pivot.copy()
    ranks = pivot.rank(axis=1, method="first", ascending=False, na_option="bottom")
    ranked = pivot.where(pivot.notna() & ranks.le(n))
    entrants = [column for column in ranked.columns if ranked[column].notna().any()]
    entrants.sort(
        key=lambda column: (
            ranked[column].first_valid_index(),
            float(ranks.loc[ranked[column].first_valid_index(), column]),
            str(column),
        )
    )
    return ranked[entrants]


def _stacked_display(pivot: pd.DataFrame, top_n: int, others_label: str) -> pd.DataFrame:
    """Top-N leaders with an explicit residual so the stack sums to 100%.

    A day where an entity is unranked contributes 0 to its band; its share flows
    into the residual. The residual also absorbs Vercel's unreported long tail,
    so the chart is honest about coverage instead of renormalising the leaders.
    """
    shown = _daily_ranked(pivot, top_n).fillna(0.0)
    residual = (100.0 - shown.sum(axis=1)).clip(lower=0.0)
    shown = shown.copy()
    shown[others_label] = residual
    return shown


def _line_display(pivot: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Cumulative daily top-N entrants with unranked post-debut days at zero."""
    ranked = _daily_ranked(pivot, top_n)
    display = ranked.copy()
    for column in display.columns:
        first = display[column].first_valid_index()
        if first is not None:
            display.loc[first:, column] = display.loc[first:, column].fillna(0.0)
    return display


def _entity_kpis(frame: pd.DataFrame) -> dict[str, object]:
    """Headline KPIs for an entity: leader by tokens in the 'all' modality."""
    pivot = _pivot(frame, "all", "tokens")
    if pivot.empty:
        return {}
    dates = list(pivot.index)
    latest = dates[-1]
    row = pivot.loc[latest].dropna().sort_values(ascending=False)
    if row.empty:
        return {}
    leader = str(row.index[0])
    share = float(row.iloc[0])
    wow = None
    if len(dates) >= 2 and leader in pivot.columns:
        prev = pivot.loc[dates[-2], leader]
        if pd.notna(prev):
            wow = share - float(prev)
    return {"latest_date": latest, "leader": leader, "share": share, "wow": wow, "count": int(row.shape[0])}


def compute_vercel_ai_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    frames = {label: _prep(datasets.get(dataset_id)) for label, dataset_id in ENTITIES.items()}
    if all(frame.empty for frame in frames.values()):
        return {}
    return {
        "frames": frames,
        "kpis": {label: _entity_kpis(frame) for label, frame in frames.items()},
    }


def _render_kpi_row(entity_label: str, kpis: dict[str, object]) -> None:
    if not kpis:
        return
    noun = "Model" if entity_label == "Top Models" else "Lab"
    leader = str(kpis["leader"])
    leader_disp = leader if len(leader) <= 26 else leader[:24] + "…"
    wow = kpis.get("wow")
    if wow is None:
        delta_cls, delta_txt = "flat", "—"
    else:
        delta_cls = "up" if wow >= 0 else "down"
        delta_txt = f"{'↑' if wow >= 0 else '↓'} {abs(wow):.1f} pts DoD"
    st.markdown(
        kpi_grid_html(
            kpi_card_html("Latest Date", str(kpis["latest_date"]), delta="tokens share (all)"),
            kpi_card_html(f"Top {noun}", leader_disp, delta="by token share", value_style="font-size:1.1rem;"),
            kpi_card_html("Leader Share", f"{kpis['share']:.1f}%", delta=delta_txt, delta_class=delta_cls),
            kpi_card_html(f"{noun}s Ranked", str(kpis["count"]), delta="latest day · tokens"),
        ),
        unsafe_allow_html=True,
    )


def _render_modality_tab(frame: pd.DataFrame, entity_label: str, modality: str) -> None:
    metrics = _available_metrics(frame, modality)
    if not metrics:
        st.info(f"No {MODALITY_LABELS[modality]} data available for {entity_label.lower()}.")
        return

    controls = st.columns([2, 1])
    with controls[0]:
        metric = st.radio(
            "Metric",
            metrics,
            index=_default_metric(metrics),
            horizontal=True,
            format_func=lambda m: METRIC_LABELS.get(m, m),
            key=f"vercel_metric_{modality}",
        )
    with controls[1]:
        view_mode = st.radio(
            "View",
            ["Share over time", "Lines"],
            horizontal=True,
            key=f"vercel_view_{modality}",
        )

    pivot = _pivot(frame, modality, metric)
    if pivot.empty:
        st.info(f"No {METRIC_LABELS.get(metric, metric)} data for {MODALITY_LABELS[modality]} {entity_label.lower()}.")
        return

    noun = "models" if entity_label == "Top Models" else "labs"
    top_n = TOP_N_BY_ENTITY.get(entity_label, DEFAULT_TOP_N)
    others_label = _others_label(entity_label)

    if view_mode == "Share over time":
        display_pivot = _stacked_display(pivot, top_n, others_label)
        fig = make_stacked_area_chart(
            display_pivot,
            display_index=list(display_pivot.index),
            colors=_column_colors(list(display_pivot.columns), others_label),
            x_title="Date",
            y_title="Share (%)",
            value_format=".2f",
            hover_suffix="%",
        )
        if entity_label == "Top Models":
            residual = f" *{others_label}* is everything outside the displayed top {top_n}; Vercel presents this residual as rank {top_n + 1}."
        else:
            residual = f" *{others_label}* groups every provider outside the top {top_n}."
    else:
        display_pivot = _line_display(pivot, top_n)
        fig = make_line_chart(
            display_pivot,
            colors=_column_colors(list(display_pivot.columns), others_label),
            y_title="Share (%)",
            x_title="Date",
            hover_suffix="%",
        )
        residual = (
            " Before a model's first ranked appearance its line is absent; after debut, zero means it was "
            "not in Vercel's published ranking and its unreported share is included in Others—not necessarily zero usage."
        )
    st.plotly_chart(fig, width="stretch", theme=None)
    st.caption(
        f"Daily **{METRIC_LABELS.get(metric, metric).lower()}** share of Vercel AI Gateway "
        f"{MODALITY_LABELS[modality]} {noun} (daily top {top_n}, cumulative entrants).{residual} "
        f"**Tracking note:** after first entry, an entity remains in the cumulative series set; "
        f"an unranked day is filled as 0 and assigned to {others_label}, and a later re-entry "
        "continues the same series. This 0 means *not separately reported*, not confirmed zero usage."
    )


def render(domain_states, datasets) -> None:
    st.markdown('<div class="section-title">Vercel AI Gateway Leaderboard</div>', unsafe_allow_html=True)

    model_leaderboard = datasets.get("vercel_model_leaderboard")
    if not model_leaderboard or not render_dataset_guard(model_leaderboard):
        return

    views = compute_vercel_ai_views(datasets)
    frames: dict[str, pd.DataFrame] = views.get("frames", {})  # type: ignore[assignment]
    if not frames:
        st.info("No Vercel leaderboard data available yet.")
        return

    entity_label = st.radio(
        "View", list(ENTITIES.keys()), horizontal=True, key="vercel_entity",
    )
    frame = frames.get(entity_label, pd.DataFrame())
    if frame.empty:
        st.info(f"No data available for {entity_label.lower()}.")
        return

    _render_kpi_row(entity_label, views.get("kpis", {}).get(entity_label, {}))  # type: ignore[union-attr]

    modalities = _available_modalities(frame)
    tabs = st.tabs([MODALITY_LABELS[m] for m in modalities])
    for tab, modality in zip(tabs, modalities):
        with tab:
            _render_modality_tab(frame, entity_label, modality)
