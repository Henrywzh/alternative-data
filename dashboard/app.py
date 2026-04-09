from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.checks import CheckResult, run_checks
from dashboard.data import (
    DOMAIN_ORDER,
    DATASET_REGISTRY,
    DatasetLoadResult,
    FreshnessInfo,
    domain_dataset_ids,
    load_all_datasets,
    load_latest_manifest,
)


BASE_DIR = Path(__file__).resolve().parent.parent

# Style 1 (OpenRouter Clean) palette
ACCENT  = "#2563EB"
BG      = "#FFFFFF"
SIDEBAR = "#F7F8FA"
CARD    = "#FFFFFF"
BORDER  = "#E5E7EB"
TEXT    = "#111827"
MUTED   = "#6B7280"
GREEN   = "#16A34A"
RED     = "#DC2626"
YELLOW  = "#D97706"
GRID    = "#F3F4F6"
TICK    = "#9CA3AF"

MODEL_COLORS = [
    "#4285F4", "#FF6B6B", "#00B5A4", "#FF7849",
    "#8B5CF6", "#EC4899", "#84CC16", "#F59E0B",
    "#06B6D4", "#9CA3AF",
]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

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


def load_state() -> tuple[dict[str, DatasetLoadResult], FreshnessInfo, list[CheckResult]]:
    datasets = load_all_datasets(base_dir=BASE_DIR)
    freshness = load_latest_manifest(base_dir=BASE_DIR, datasets=datasets)
    checks = run_checks(datasets, freshness, base_dir=BASE_DIR)
    return datasets, freshness, checks


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


def default_range(values: list[str]) -> tuple[str, str]:
    if not values:
        return ("", "")
    start_index = max(0, len(values) - 30)
    return values[start_index], values[-1]


def domain_ranges(datasets: dict[str, DatasetLoadResult]) -> dict[str, tuple[str | None, str | None]]:
    ranges: dict[str, tuple[str | None, str | None]] = {}
    for domain, ids in DOMAIN_ORDER.items():
        first_dates  = [datasets[d].first_date  for d in ids if datasets[d].first_date]
        latest_dates = [datasets[d].latest_date for d in ids if datasets[d].latest_date]
        ranges[domain] = (
            min(first_dates)  if first_dates  else None,
            max(latest_dates) if latest_dates else None,
        )
    return ranges


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


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        /* ---- global ---- */
        .stApp {{ background: transparent; }}
        .block-container {{ padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1360px; }}

        /* ---- KPI cards ---- */
        .kpi-grid {{ display: flex; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; }}
        .kpi-card {{
            flex: 1 1 200px;
            background: rgba(128, 128, 128, 0.05);
            border: 1px solid rgba(128, 128, 128, 0.2);
            border-radius: 12px;
            padding: 1.1rem 1.3rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        }}
        .kpi-label {{
            font-size: 0.72rem;
            color: {MUTED};
            text-transform: uppercase;
            letter-spacing: 0.1em;
            margin-bottom: 0.35rem;
            font-weight: 600;
        }}
        .kpi-value {{
            font-size: 2rem;
            font-weight: 800;
            line-height: 1.1;
        }}
        .kpi-delta-up   {{ font-size: 0.82rem; color: {GREEN}; margin-top: 0.2rem; font-weight: 600; }}
        .kpi-delta-down {{ font-size: 0.82rem; color: {RED};   margin-top: 0.2rem; font-weight: 600; }}
        .kpi-delta-flat {{ font-size: 0.82rem; color: {MUTED}; margin-top: 0.2rem; }}

        /* ---- section headers ---- */
        .section-title {{
            font-size: 1.25rem;
            font-weight: 800;
            margin: 2rem 0 1rem 0;
            padding-bottom: 0.45rem;
            border-bottom: 2px solid rgba(128, 128, 128, 0.15);
        }}

        /* ---- Market Share Legend ---- */
        .ms-legend {{ display: flex; flex-direction: column; gap: 0.4rem; margin-top: 0.5rem; }}
        .ms-row {{ display: flex; align-items: center; gap: 0.6rem; padding: 0.35rem 0.5rem; border-radius: 6px; transition: background 0.2s; }}
        .ms-row:hover {{ background: rgba(0,0,0,0.03); }}
        .ms-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
        .ms-name {{ flex: 1; font-size: 0.82rem; font-weight: 500; color: {TEXT}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
        .ms-tokens {{ font-size: 0.78rem; color: {MUTED}; min-width: 50px; text-align: right; }}
        .ms-pct {{ font-size: 0.82rem; font-weight: 700; color: {TEXT}; min-width: 45px; text-align: right; }}

        /* ---- Leaderboard Cards ---- */
        .lb-card {{
            display: flex;
            align-items: center;
            gap: 1rem;
            background: {CARD};
            border: 1px solid {BORDER};
            border-radius: 10px;
            padding: 0.8rem 1rem;
            margin-bottom: 0.6rem;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .lb-card:hover {{ transform: translateY(-1px); box-shadow: 0 4px 6px -1px rgba(0,0,0,0.08); }}
        .lb-rank {{
            width: 28px;
            height: 28px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: {SIDEBAR};
            color: {MUTED};
            border-radius: 50%;
            font-size: 0.85rem;
            font-weight: 800;
        }}
        .lb-rank-top {{ background: {ACCENT}; color: white; }}
        .lb-model {{ flex: 1; }}
        .lb-model-name {{ font-size: 0.92rem; font-weight: 700; color: {TEXT}; line-height: 1.2; }}
        .lb-model-author {{ font-size: 0.72rem; color: {MUTED}; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }}
        .lb-tokens {{ font-weight: 700; font-size: 0.95rem; color: {TEXT}; }}
        
        /* ---- Badges ---- */
        .lb-badge-up   {{ font-size: 0.7rem; font-weight: 800; color: {GREEN}; background: rgba(22, 163, 74, 0.1); padding: 2px 6px; border-radius: 4px; min-width: 32px; text-align: center; }}
        .lb-badge-down {{ font-size: 0.7rem; font-weight: 800; color: {RED};   background: rgba(220, 38, 38, 0.1); padding: 2px 6px; border-radius: 4px; min-width: 32px; text-align: center; }}
        .lb-badge-flat {{ font-size: 0.7rem; font-weight: 800; color: {MUTED}; background: rgba(107, 114, 128, 0.1); padding: 2px 6px; border-radius: 4px; min-width: 32px; text-align: center; }}
        .lb-badge-new  {{ font-size: 0.65rem; font-weight: 900; color: white;   background: {ACCENT}; padding: 2px 6px; border-radius: 4px; }}

        /* ---- Health Checks ---- */
        .chk-ok      {{ color: {GREEN}; font-weight: 700; font-size: 0.9rem; margin-top: 0.5rem; }}
        .chk-warning {{ color: {YELLOW}; font-weight: 700; font-size: 0.9rem; margin-top: 0.5rem; }}
        .chk-error   {{ color: {RED}; font-weight: 700; font-size: 0.9rem; margin-top: 0.5rem; }}

        /* ---- Hide Streamlit elements to lock theme ---- */
        [data-testid="stToolbar"], #MainMenu, footer, header {{ visibility: hidden; display: none !important; }}
        .stDeployButton {{ display: none; }}
        
        /* Force Light Mode background and text */
        body, .stApp {{
            background-color: {BG} !important;
            color: {TEXT} !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def render_header(freshness: FreshnessInfo) -> None:
    updated = freshness.latest_scraped_at or "Unknown"
    st.markdown(
        f"""
        <div style="margin-bottom:1.2rem;">
          <h1 style="font-size:1.9rem;font-weight:800;color:{TEXT};margin:0 0 0.2rem 0;">
            Alternative Data Dashboard
          </h1>
          <span style="color:{MUTED};font-size:0.88rem;">
            Last updated: {updated}
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_row(datasets: dict[str, DatasetLoadResult]) -> None:
    tm_result = datasets.get("top_models")
    ms_result = datasets.get("market_share")

    # --- top models KPIs ---
    total_latest = None
    wow_pct      = None
    top_model    = None

    if tm_result and not tm_result.frame.empty:
        tm = tm_result.frame.copy()
        tm["week_start_date"] = tm["week_start_date"].astype(str)
        sorted_weeks = sorted(tm["week_start_date"].unique())
        if sorted_weeks:
            latest_wk = sorted_weeks[-1]
            total_latest = tm[tm["week_start_date"] == latest_wk]["metric_value"].sum()
            tm_latest_named = (
                tm[
                    (tm["week_start_date"] == latest_wk) &
                    (tm["entity_id"].str.lower() != "others") &
                    (tm["entity_id"].str.contains("/", na=False))
                ]
                .groupby("entity_id", as_index=False)["metric_value"]
                .sum()
                .sort_values("metric_value", ascending=False)
            )
            top_model = tm_latest_named.iloc[0]["entity_id"] if not tm_latest_named.empty else None
            if len(sorted_weeks) >= 2:
                prev_wk    = sorted_weeks[-2]
                total_prev = tm[tm["week_start_date"] == prev_wk]["metric_value"].sum()
                if total_prev > 0:
                    wow_pct = (total_latest - total_prev) / total_prev * 100

    # --- market share leader ---
    leader_author = None
    leader_pct    = None

    if ms_result and not ms_result.frame.empty:
        ms = ms_result.frame.copy()
        ms["week_start_date"] = ms["week_start_date"].astype(str)
        latest_ms_wk = ms["week_start_date"].max()
        ms_latest    = ms[ms["week_start_date"] == latest_ms_wk].groupby("entity_id", as_index=False)["metric_value"].sum()
        ms_latest_named = ms_latest[ms_latest["entity_id"].str.lower() != "others"].copy()
        if not ms_latest_named.empty:
            ms_total = ms_latest["metric_value"].sum()
            ms_latest_named = ms_latest_named.sort_values("metric_value", ascending=False)
            leader_author = ms_latest_named.iloc[0]["entity_id"]
            if ms_total > 0:
                leader_pct = ms_latest_named.iloc[0]["metric_value"] / ms_total * 100

    # --- render ---
    if wow_pct is not None:
        delta_cls  = "kpi-delta-up" if wow_pct >= 0 else "kpi-delta-down"
        delta_icon = "↑" if wow_pct >= 0 else "↓"
        delta_html = f'<div class="{delta_cls}">{delta_icon} {abs(wow_pct):.1f}% WoW</div>'
    else:
        delta_html = f'<div class="kpi-delta-flat">—</div>'

    tokens_fmt   = format_metric(total_latest) if total_latest is not None else "—"
    leader_label = f"{leader_author} ({leader_pct:.1f}%)" if leader_author and leader_pct else leader_author or "—"
    model_label  = top_model or "—"
    # truncate long model names
    if len(model_label) > 28:
        model_label = model_label[:26] + "…"

    st.markdown(
        f"""
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">Total Tokens (Latest Week)</div>
            <div class="kpi-value">{tokens_fmt}</div>
            {delta_html}
          </div>
          <div class="kpi-card">
            <div class="kpi-label">WoW Change</div>
            <div class="kpi-value">{"+" if wow_pct and wow_pct >= 0 else ""}{f"{wow_pct:.1f}%" if wow_pct is not None else "—"}</div>
            <div class="kpi-delta-flat">vs prior week</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Top Model</div>
            <div class="kpi-value" style="font-size:1.1rem;">{model_label}</div>
            <div class="kpi-delta-flat">by tokens this week</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Market Leader</div>
            <div class="kpi-value" style="font-size:1.1rem;">{leader_label}</div>
            <div class="kpi-delta-flat">latest week share</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_top_models_chart(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">Top Models — Weekly Token Usage</div>', unsafe_allow_html=True)
    result = datasets.get("top_models")
    if not result or not render_dataset_guard(result):
        return

    tm = result.frame.copy()
    tm["week_start_date"] = tm["week_start_date"].astype(str)
    
    # --- Period Selector & Total ---
    weeks = sorted(tm["week_start_date"].unique(), reverse=True)
    sel_week = st.selectbox("Analyze week", options=weeks, index=0, key="tm_week_sel")
    week_total = tm[tm["week_start_date"] == sel_week]["metric_value"].sum()
    st.markdown(
        f'<div class="kpi-card" style="margin-bottom:1rem; max-width: 300px;">'
        f'<div class="kpi-label">Total Tokens ({sel_week})</div>'
        f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(week_total)}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    pivot = (
        tm.pivot_table(index="week_start_date", columns="entity_id", values="metric_value", aggfunc="sum")
        .fillna(0)
        .sort_index()
    )

    # Increase Top N from 9 to 15
    top_n_count = 15
    top_n_cols = pivot.sum().nlargest(top_n_count).index.tolist()
    other_cols = [c for c in pivot.columns if c not in top_n_cols]
    pivot_top = pivot[top_n_cols].copy()
    if other_cols:
        pivot_top["Others"] = pivot[other_cols].sum(axis=1)

    fig = make_stacked_bar(pivot_top, MODEL_COLORS, y_title="Tokens")
    st.plotly_chart(fig, use_container_width=True, theme=None)


def render_market_share_section(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">Market Share — Token Distribution by Author</div>', unsafe_allow_html=True)
    result = datasets.get("market_share")
    if not result or not render_dataset_guard(result):
        return

    ms = result.frame.copy()
    ms["week_start_date"] = ms["week_start_date"].astype(str)

    # --- Period Selector ---
    ms_weeks = sorted(ms["week_start_date"].unique(), reverse=True)
    sel_ms_wk = st.selectbox("Analyze week", options=ms_weeks, index=0, key="ms_week_sel")
    ms_wk_total = ms[ms["week_start_date"] == sel_ms_wk]["metric_value"].sum()
    st.markdown(
        f'<div class="kpi-card" style="margin-bottom:1rem; max-width: 300px;">'
        f'<div class="kpi-label">Total Tokens ({sel_ms_wk})</div>'
        f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(ms_wk_total)}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    ms_pivot = (
        ms.pivot_table(index="week_start_date", columns="entity_id", values="metric_value", aggfunc="sum")
        .fillna(0)
        .sort_index()
    )
    # exclude the catch-all "others" column from the normalisation base if present
    # Increase Top N from 8 to 15
    top_n_count = 15
    named_cols  = [c for c in ms_pivot.columns if c.lower() != "others"]
    other_col   = [c for c in ms_pivot.columns if c.lower() == "others"]
    top_n_named = ms_pivot[named_cols].sum().nlargest(top_n_count).index.tolist()
    rest_cols   = [c for c in named_cols if c not in top_n_named] + other_col

    pct_df = ms_pivot.copy()
    row_totals = pct_df.sum(axis=1)
    pct_df = pct_df.div(row_totals, axis=0).mul(100).fillna(0)

    pct_top = pct_df[top_n_named].copy()
    if rest_cols:
        pct_top["Others"] = pct_df[rest_cols].sum(axis=1)

    chart_col, legend_col = st.columns([2, 1], gap="large")

    with chart_col:
        fig = make_stacked_bar(pct_top, MODEL_COLORS, y_title="Share (%)", pct=True)
        fig.update_yaxes(range=[0, 100])
        st.plotly_chart(fig, use_container_width=True, theme=None)

    with legend_col:
        ms_latest  = ms[ms["week_start_date"] == sel_ms_wk].groupby("entity_id", as_index=False)["metric_value"].sum()
        wk_total   = ms_latest["metric_value"].sum()
        ms_named   = ms_latest[ms_latest["entity_id"].str.lower() != "others"].sort_values("metric_value", ascending=False)
        cum_total  = ms[ms["entity_id"].str.lower() != "others"].groupby("entity_id")["metric_value"].sum()

        st.markdown(f'<div style="font-weight:700;font-size:1rem;margin-bottom:0.8rem;">Week: {sel_ms_wk} Leaders</div>', unsafe_allow_html=True)
        rows_html = '<div class="ms-legend">'
        for rank_i, (_, row) in enumerate(ms_named.head(8).iterrows()):
            color  = MODEL_COLORS[rank_i % len(MODEL_COLORS)]
            author = row["entity_id"]
            pct_v  = row["metric_value"] / wk_total * 100 if wk_total > 0 else 0
            cum_v  = format_metric(cum_total.get(author, 0))
            rows_html += f"""
            <div class="ms-row">
              <span style="color:{MUTED};font-size:0.72rem;min-width:16px;">{rank_i+1}</span>
              <span class="ms-dot" style="background:{color};"></span>
              <span class="ms-name">{author}</span>
              <span class="ms-tokens">{cum_v}</span>
              <span class="ms-pct">{pct_v:.1f}%</span>
            </div>"""
        rows_html += "</div>"
        st.markdown(rows_html, unsafe_allow_html=True)


def render_leaderboard(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">Model Leaderboard</div>', unsafe_allow_html=True)
    result = datasets.get("top_models")
    if not result or not render_dataset_guard(result):
        return

    tm = result.frame.copy()
    tm["week_start_date"] = tm["week_start_date"].astype(str)
    sorted_weeks = sorted(tm["week_start_date"].unique())
    if len(sorted_weeks) < 1:
        st.info("Not enough weekly data for leaderboard.")
        return

    latest_wk = sorted_weeks[-1]
    prev_wk   = sorted_weeks[-2] if len(sorted_weeks) >= 2 else None

    def _agg_named(frame: pd.DataFrame) -> pd.DataFrame:
        """Aggregate by entity_id, excluding catch-all 'Others' buckets."""
        named = frame[
            (frame["entity_id"].str.lower() != "others") &
            (frame["entity_id"].str.contains("/", na=False))
        ]
        return (
            named.groupby("entity_id", as_index=False)["metric_value"]
            .sum()
            .sort_values("metric_value", ascending=False)
            .reset_index(drop=True)
        )

    latest_agg = _agg_named(tm[tm["week_start_date"] == latest_wk])
    latest_agg["curr_rank"] = range(1, len(latest_agg) + 1)

    if prev_wk:
        prev_agg = _agg_named(tm[tm["week_start_date"] == prev_wk])
        prev_agg["prev_rank"] = range(1, len(prev_agg) + 1)
        rank_map = dict(zip(prev_agg["entity_id"], prev_agg["prev_rank"]))
    else:
        rank_map = {}

    # extract author from entity_id (format: "author/model-name")
    def split_entity(eid: str):
        parts = eid.split("/", 1)
        return (parts[0], parts[1]) if len(parts) == 2 else ("", eid)

    top10 = latest_agg.head(10)
    cards = []
    for _, row in top10.iterrows():
        eid    = row["entity_id"]
        author, model_name = split_entity(eid)
        tokens = format_metric(row["metric_value"])
        rank   = row["curr_rank"]
        prev_r = rank_map.get(eid)

        if prev_r is None:
            badge = '<span class="lb-badge-new">NEW</span>'
        else:
            delta = prev_r - rank  # positive → moved up
            if delta > 0:
                badge = f'<span class="lb-badge-up">↑{delta}</span>'
            elif delta < 0:
                badge = f'<span class="lb-badge-down">↓{abs(delta)}</span>'
            else:
                badge = '<span class="lb-badge-flat">—</span>'

        rank_cls   = "lb-rank lb-rank-top" if rank <= 3 else "lb-rank"
        model_disp = model_name[:32] + "…" if len(model_name) > 32 else model_name

        cards.append(
            f"""<div class="lb-card">
              <div class="{rank_cls}">{rank}</div>
              <div class="lb-model">
                <div class="lb-model-name">{model_disp}</div>
                <div class="lb-model-author">{author}</div>
              </div>
              <div class="lb-tokens">{tokens}</div>
              {badge}
            </div>"""
        )

    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        st.markdown("".join(cards[:5]), unsafe_allow_html=True)
    with col_b:
        st.markdown("".join(cards[5:]), unsafe_allow_html=True)


def render_app_usage_chart(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">App Intelligence — Daily Model Usage</div>', unsafe_allow_html=True)

    # prefer app_top_models_daily_snapshot, fall back to app_usage_daily
    result = datasets.get("app_top_models_daily_snapshot")
    use_daily = False
    if not result or result.frame.empty:
        result = datasets.get("app_usage_daily")
        use_daily = True

    if not result or not render_dataset_guard(result):
        return

    frame = result.frame.copy()

    if use_daily:
        date_col  = "usage_date"
        model_col = "model_permaslug"
        val_col   = "total_tokens"
    else:
        date_col  = "snapshot_date"
        model_col = "model_permaslug"
        val_col   = "total_tokens"

    frame[date_col] = frame[date_col].astype(str)

    # --- Period Selector & Total ---
    days = sorted(frame[date_col].unique(), reverse=True)
    sel_day = st.selectbox("Analyze day", options=days, index=0, key="app_day_sel")
    day_total = frame[frame[date_col] == sel_day][val_col].sum()
    st.markdown(
        f'<div class="kpi-card" style="margin-bottom:1rem; max-width: 300px;">'
        f'<div class="kpi-label">Total Tokens ({sel_day})</div>'
        f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(day_total)}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    pivot = (
        frame.pivot_table(index=date_col, columns=model_col, values=val_col, aggfunc="sum")
        .fillna(0)
        .sort_index()
    )

    # Increase Top N from 7 to 15
    top_n_count = 15
    top_n_cols = pivot.sum().nlargest(top_n_count).index.tolist()
    rest_cols = [c for c in pivot.columns if c not in top_n_cols]
    pivot_top = pivot[top_n_cols].copy()
    if rest_cols:
        pivot_top["Others"] = pivot[rest_cols].sum(axis=1)

    fig = make_stacked_bar(pivot_top, MODEL_COLORS, y_title="Tokens", height=340)
    st.plotly_chart(fig, use_container_width=True, theme=None)


def render_apps_tables(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">App Rankings & Trends</div>', unsafe_allow_html=True)

    tabs = st.tabs(["Global Rankings", "Trending Apps", "Monitored Apps"])

    with tabs[0]:
        result = datasets.get("apps_global_ranking_snapshots")
        if result and render_dataset_guard(result):
            frame = result.frame.copy()
            periods = sorted(frame["period"].dropna().astype(str).unique().tolist())
            period  = st.selectbox("Period", options=periods, index=0 if periods else None, key="lb_period")
            if period:
                frame = frame[frame["period"] == period]
            latest_date = frame["snapshot_date"].max()
            latest = frame[frame["snapshot_date"] == latest_date].sort_values("rank").head(25)
            tbl = latest[["rank", "app_name", "categories", "tokens"]].copy()
            total_top25 = tbl["tokens"].sum()
            
            summary_col, _ = st.columns([1, 2])
            with summary_col:
                st.markdown(
                    f'<div class="kpi-card" style="margin-bottom:1rem;">'
                    f'<div class="kpi-label">Tokens in Top 25 ({latest_date})</div>'
                    f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(total_top25)}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                
            tbl["tokens"] = tbl["tokens"].map(format_metric)
            st.dataframe(tbl.fillna(""), use_container_width=True, hide_index=True)

    with tabs[1]:
        result = datasets.get("apps_trending_snapshots")
        if result and render_dataset_guard(result):
            frame = result.frame.copy()
            latest_date = frame["snapshot_date"].max()
            latest = frame[frame["snapshot_date"] == latest_date].sort_values("rank").head(25)
            st.caption(f"Snapshot: {latest_date}")
            tbl = latest[["rank", "app_name", "categories", "growth_percent"]].copy()
            tbl["growth_percent"] = tbl["growth_percent"].map(
                lambda v: "-" if pd.isna(v) else f"{v:,.0f}%"
            )
            st.dataframe(tbl.fillna(""), use_container_width=True, hide_index=True)

    with tabs[2]:
        meta_result  = datasets.get("app_metadata_snapshots")
        usage_result = datasets.get("app_usage_daily")
        if meta_result and render_dataset_guard(meta_result):
            latest_date   = meta_result.latest_date
            latest_meta   = meta_result.frame.copy()
            if latest_date:
                latest_meta = latest_meta[latest_meta["scrape_date"] == latest_date]
            st.caption(f"Metadata snapshot: {latest_date or 'n/a'}")
            st.dataframe(
                latest_meta[["app_name", "app_id", "origin_url", "categories", "description"]].fillna(""),
                use_container_width=True,
                hide_index=True,
            )

        if usage_result and render_dataset_guard(usage_result, show_subheader=False):
            usage = usage_result.frame.copy()
            app_names = sorted(usage["app_name"].dropna().astype(str).unique().tolist())
            selected  = st.multiselect("Apps", options=app_names, default=app_names[:3], key="mon_apps")
            if selected:
                usage = usage[usage["app_name"].isin(selected)]
            if not usage.empty:
                app_total = usage["total_tokens"].sum()
                st.markdown(
                    f'<div class="kpi-card" style="margin-bottom:1rem; max-width: 300px;">'
                    f'<div class="kpi-label">Cumulative Selection Usage</div>'
                    f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(app_total)}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                
                pivot_u = (
                    usage.pivot_table(index="usage_date", columns="model_permaslug", values="total_tokens", aggfunc="sum")
                    .fillna(0)
                    .sort_index()
                )
                top_m = pivot_u.sum().nlargest(15).index.tolist()
                pivot_u = pivot_u[top_m]
                fig_u = make_stacked_bar(pivot_u, MODEL_COLORS, y_title="Tokens", height=300)
                st.plotly_chart(fig_u, use_container_width=True, theme=None)


def render_github_trending_section(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">GitHub Trending Repositories</div>', unsafe_allow_html=True)
    
    # 1. Period Selector
    period_label = st.radio("Trending period", options=["Daily", "Weekly", "Monthly"], horizontal=True, label_visibility="collapsed")
    dataset_id = f"github_trending_{period_label.lower()}"
    
    result = datasets.get(dataset_id)
    if not result or not render_dataset_guard(result):
        return

    df = result.frame.copy()
    if df.empty:
        st.info(f"No data available for {period_label.lower()}.")
        return

    # Ensure dates are strings for sorting
    df["scrape_date"] = df["scrape_date"].astype(str)
    latest_date = df["scrape_date"].max()
    latest_df = df[df["scrape_date"] == latest_date].copy()
    latest_df["stars_today"] = pd.to_numeric(latest_df["stars_today"], errors="coerce").fillna(0)
    latest_df = latest_df.sort_values("stars_today", ascending=False)

    # --- KPIs ---
    top_repo = latest_df.iloc[0] if not latest_df.empty else None
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Top Gainer ({period_label})</div>'
            f'<div class="kpi-value" style="font-size: 1.3rem;">{top_repo["name"] if top_repo is not None else "—"}</div>'
            f'<div class="kpi-delta-up">+{format_metric(top_repo["stars_today"]) if top_repo is not None else "0"} stars</div>'
            f'</div>',
            unsafe_allow_html=True
        )
    with col2:
        total_gained = latest_df["stars_today"].sum()
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Total Stars Gained (Top 15)</div>'
            f'<div class="kpi-value">{format_metric(total_gained)}</div>'
            f'<div class="kpi-delta-flat">across trending list</div>'
            f'</div>',
            unsafe_allow_html=True
        )
    with col3:
        unique_repos = df["name"].nunique()
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Unique Repos Tracked</div>'
            f'<div class="kpi-value">{unique_repos}</div>'
            f'<div class="kpi-delta-flat">in history</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    # --- Charts & Leaderboard ---
    chart_tab, list_tab = st.tabs(["Historical Growth", "Latest Leaderboard"])

    with chart_tab:
        # Plot top 5 growth over time
        top_5_names = latest_df.head(5)["name"].tolist()
        hist_df = df[df["name"].isin(top_5_names)].copy()
        
        if not hist_df.empty:
            pivot_h = hist_df.pivot_table(index="scrape_date", columns="name", values="stars_today", aggfunc="sum").fillna(0)
            
            fig = go.Figure()
            for i, repo_name in enumerate(pivot_h.columns):
                fig.add_trace(go.Scatter(
                    x=pivot_h.index,
                    y=pivot_h[repo_name],
                    name=repo_name,
                    mode='lines+markers',
                    line=dict(width=3, color=MODEL_COLORS[i % len(MODEL_COLORS)]),
                    hovertemplate=f"<b>{repo_name}</b><br>%{{x}}<br>%{{y:,.0f}} stars gained<extra></extra>"
                ))
            
            fig.update_layout(
                template="plotly_white",
                title=f"Star Growth - Top 5 {period_label} Repos",
                xaxis_title="Scrape Date",
                yaxis_title="Stars Gained",
                legend=dict(orientation="h", y=-0.2),
                height=400,
                margin=dict(l=0, r=0, t=40, b=80)
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Not enough historical data to show growth.")

    with list_tab:
        st.markdown(f'<div style="font-weight:700;font-size:1.1rem;margin-bottom:1rem;">Top Gaining Repositories ({latest_date})</div>', unsafe_allow_html=True)
        
        cols = st.columns(2)
        for i, (_, row) in enumerate(latest_df.head(10).iterrows()):
            col_idx = i % 2
            with cols[col_idx]:
                description = str(row.get('description', ''))
                if description in ['nan', 'None', 'NULL']:
                    description = ""
                
                desc_display = (description[:100] + '...') if len(description) > 100 else description
                
                st.markdown(
                    f"""<div class="lb-card">
                      <div class="lb-rank {'lb-rank-top' if i < 3 else ''}">{i+1}</div>
                      <div class="lb-model">
                        <div class="lb-model-name"><a href="{row['link']}" target="_blank">{row['name']}</a></div>
                        <div class="lb-model-author">{row['author']}</div>
                        <div style="font-size:0.75rem; color:{MUTED}; margin-top:2px;">{desc_display}</div>
                      </div>
                      <div class="lb-tokens" style="color:{GREEN};">+{format_metric(row['stars_today'])}</div>
                      <div style="font-size:0.7rem; color:{MUTED}; min-width:50px; text-align:right;">Total: {format_metric(row['total_stars'])}</div>
                    </div>""",
                    unsafe_allow_html=True
                )


def render_provider_adoption_section(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">Provider Adoption Signals</div>', unsafe_allow_html=True)

    pypi_result = datasets.get("pypi_downloads_daily")
    github_candidates_result = datasets.get("github_repo_candidates_daily")
    github_rollup_result = datasets.get("github_repo_rollup_daily")
    github_signals_result = datasets.get("github_provider_signals_daily")

    if not pypi_result or not render_dataset_guard(pypi_result):
        st.info("Run the provider-adoption pipeline to populate GitHub + PyPI scraped data.")
        return

    pypi = pypi_result.frame.copy()
    pypi = pypi[pypi["with_mirrors"] == False].copy()
    if pypi.empty:
        st.info("No PyPI provider data available yet.")
        return

    pypi_grouped = (
        pypi.groupby(["download_date", "provider_display_name"], dropna=False)["downloads"].sum().reset_index()
        if not pypi.empty
        else pd.DataFrame(columns=["download_date", "provider_display_name", "downloads"])
    )
    pypi_grouped["download_date"] = pypi_grouped["download_date"].astype(str)
    latest_pypi_date = pypi_grouped["download_date"].max()
    latest_pypi = pypi_grouped[pypi_grouped["download_date"] == latest_pypi_date].copy()

    provider_order = sorted(latest_pypi["provider_display_name"].dropna().astype(str).unique().tolist())
    if not provider_order:
        st.info("No provider rows available yet.")
        return

    github_candidates = (
        github_candidates_result.frame.copy()
        if github_candidates_result and github_candidates_result.frame is not None
        else pd.DataFrame()
    )
    github_rollup = (
        github_rollup_result.frame.copy()
        if github_rollup_result and github_rollup_result.frame is not None
        else pd.DataFrame()
    )
    github_signals = (
        github_signals_result.frame.copy()
        if github_signals_result and github_signals_result.frame is not None
        else pd.DataFrame()
    )

    if not github_candidates.empty:
        github_candidates = github_candidates[github_candidates["provider_display_name"].isin(provider_order)].copy()
        github_candidates["repo_created_date"] = github_candidates["repo_created_date"].astype(str)
    if not github_rollup.empty:
        github_rollup = github_rollup[github_rollup["provider_display_name"].isin(provider_order)].copy()
        github_rollup["signal_date"] = github_rollup["signal_date"].astype(str)
    if not github_signals.empty:
        github_signals = github_signals[github_signals["provider_display_name"].isin(provider_order)].copy()
        github_signals["signal_date"] = github_signals["signal_date"].astype(str)

    latest_github_date = None
    if not github_candidates.empty:
        latest_github_date = github_candidates["repo_created_date"].max()

    top_download_row = latest_pypi.sort_values("downloads", ascending=False).iloc[0] if not latest_pypi.empty else None
    total_latest_downloads = latest_pypi["downloads"].sum() if not latest_pypi.empty else 0
    latest_candidate_count = (
        github_candidates[github_candidates["repo_created_date"] == latest_github_date]["repo_full_name"].nunique()
        if latest_github_date and not github_candidates.empty
        else 0
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Top PyPI Provider</div>'
            f'<div class="kpi-value" style="font-size: 1.3rem;">{top_download_row["provider_display_name"] if top_download_row is not None else "—"}</div>'
            f'<div class="kpi-delta-flat">latest daily downloads</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Latest PyPI Downloads</div>'
            f'<div class="kpi-value">{format_metric(total_latest_downloads)}</div>'
            f'<div class="kpi-delta-flat">{latest_pypi_date or "n/a"}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Latest GitHub Repo Candidates</div>'
            f'<div class="kpi-value">{format_metric(latest_candidate_count)}</div>'
            f'<div class="kpi-delta-flat">{latest_github_date or "n/a"}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    downloads_tab, share_tab, github_tab, summary_tab = st.tabs(
        ["PyPI Downloads", "PyPI Share", "GitHub Signals", "Latest Summary"]
    )

    with downloads_tab:
        pivot_downloads = (
            pypi_grouped.pivot_table(index="download_date", columns="provider_display_name", values="downloads", aggfunc="last")
            .fillna(0)
            .sort_index()
        )
        fig = go.Figure()
        for i, provider_name in enumerate(pivot_downloads.columns):
            fig.add_trace(
                go.Scatter(
                    x=pivot_downloads.index,
                    y=pivot_downloads[provider_name],
                    name=provider_name,
                    mode="lines+markers",
                    line=dict(width=3, color=MODEL_COLORS[i % len(MODEL_COLORS)]),
                    hovertemplate=f"<b>{provider_name}</b><br>%{{x}}<br>%{{y:,.0f}} downloads<extra></extra>",
                )
            )
        fig.update_layout(
            template="plotly_white",
            title="PyPI Daily Download History (Without Mirrors)",
            xaxis_title="Date",
            yaxis_title="Downloads",
            legend=dict(orientation="h", y=-0.2),
            height=360,
            margin=dict(l=0, r=0, t=40, b=80),
        )
        st.plotly_chart(fig, use_container_width=True, theme=None)

    with share_tab:
        totals = pypi_grouped.groupby("download_date")["downloads"].sum().rename("total").reset_index()
        share = pypi_grouped.merge(totals, on="download_date", how="left")
        share["share"] = share["downloads"] / share["total"].where(share["total"] != 0)
        pivot_share = (
            share.pivot_table(index="download_date", columns="provider_display_name", values="share", aggfunc="last")
            .fillna(0)
            .sort_index()
        )
        st.plotly_chart(
            make_stacked_bar(
                pivot_share * 100,
                MODEL_COLORS,
                title="PyPI Daily Download Share (Without Mirrors)",
                y_title="Share",
                pct=True,
                height=340,
            ),
            use_container_width=True,
            theme=None,
        )

    with github_tab:
        if github_candidates.empty or github_rollup.empty:
            st.info("No GitHub provider signal data available yet.")
        else:
            candidates_daily = (
                github_candidates.groupby(["repo_created_date", "provider_display_name"], dropna=False)["repo_full_name"]
                .nunique()
                .reset_index(name="repo_candidates")
            )
            rollup_daily = (
                github_rollup.groupby(["signal_date", "provider_display_name"], dropna=False)
                .agg(
                    signal_repos=("repo_full_name", "nunique"),
                    manifest_repos=("has_manifest_dependency", "sum"),
                    import_repos=("has_code_import", "sum"),
                    env_repos=("has_env_var", "sum"),
                    model_repos=("has_model_name", "sum"),
                )
                .reset_index()
            )

            col_left, col_right = st.columns(2)
            with col_left:
                pivot_candidates = (
                    candidates_daily.pivot_table(
                        index="repo_created_date",
                        columns="provider_display_name",
                        values="repo_candidates",
                        aggfunc="last",
                    )
                    .fillna(0)
                    .sort_index()
                )
                fig_candidates = go.Figure()
                for i, provider_name in enumerate(pivot_candidates.columns):
                    fig_candidates.add_trace(
                        go.Scatter(
                            x=pivot_candidates.index,
                            y=pivot_candidates[provider_name],
                            name=provider_name,
                            mode="lines+markers",
                            line=dict(width=3, color=MODEL_COLORS[i % len(MODEL_COLORS)]),
                            hovertemplate=f"<b>{provider_name}</b><br>%{{x}}<br>%{{y:,.0f}} repos<extra></extra>",
                        )
                    )
                fig_candidates.update_layout(
                    template="plotly_white",
                    title="GitHub New Repo Candidates by Day",
                    xaxis_title="Date",
                    yaxis_title="Repos",
                    legend=dict(orientation="h", y=-0.25),
                    height=340,
                    margin=dict(l=0, r=0, t=40, b=80),
                )
                st.plotly_chart(fig_candidates, use_container_width=True, theme=None)

            with col_right:
                pivot_signals = (
                    rollup_daily.pivot_table(
                        index="signal_date",
                        columns="provider_display_name",
                        values="signal_repos",
                        aggfunc="last",
                    )
                    .fillna(0)
                    .sort_index()
                )
                fig_signals = go.Figure()
                for i, provider_name in enumerate(pivot_signals.columns):
                    fig_signals.add_trace(
                        go.Scatter(
                            x=pivot_signals.index,
                            y=pivot_signals[provider_name],
                            name=provider_name,
                            mode="lines+markers",
                            line=dict(width=3, color=MODEL_COLORS[i % len(MODEL_COLORS)]),
                            hovertemplate=f"<b>{provider_name}</b><br>%{{x}}<br>%{{y:,.0f}} repos<extra></extra>",
                        )
                    )
                fig_signals.update_layout(
                    template="plotly_white",
                    title="GitHub Signal-Bearing Repos by Day",
                    xaxis_title="Date",
                    yaxis_title="Repos",
                    legend=dict(orientation="h", y=-0.25),
                    height=340,
                    margin=dict(l=0, r=0, t=40, b=80),
                )
                st.plotly_chart(fig_signals, use_container_width=True, theme=None)

    with summary_tab:
        pypi_window = pypi_grouped.copy()
        pypi_window["download_date"] = pd.to_datetime(pypi_window["download_date"], errors="coerce")
        latest_pypi_ts = pd.to_datetime(latest_pypi_date, errors="coerce")
        trailing_start = latest_pypi_ts - pd.Timedelta(days=6) if pd.notna(latest_pypi_ts) else None

        if trailing_start is not None:
            window = pypi_window[pypi_window["download_date"] >= trailing_start].copy()
        else:
            window = pypi_window.copy()

        pypi_7d = (
            window.groupby("provider_display_name", dropna=False)["downloads"].mean().rename("PyPI 7d Avg").reset_index()
            if not window.empty
            else pd.DataFrame(columns=["provider_display_name", "PyPI 7d Avg"])
        )
        latest_pypi_summary = latest_pypi.rename(
            columns={
                "provider_display_name": "Provider",
                "downloads": "Latest PyPI Downloads",
            }
        )[["Provider", "Latest PyPI Downloads"]]

        summary = latest_pypi_summary.merge(
            pypi_7d.rename(columns={"provider_display_name": "Provider"}),
            on="Provider",
            how="left",
        )

        if latest_github_date and not github_candidates.empty:
            latest_candidates = (
                github_candidates[github_candidates["repo_created_date"] == latest_github_date]
                .groupby("provider_display_name", dropna=False)["repo_full_name"]
                .nunique()
                .rename("Latest GitHub Repo Candidates")
                .reset_index()
                .rename(columns={"provider_display_name": "Provider"})
            )
            summary = summary.merge(latest_candidates, on="Provider", how="left")

        if latest_github_date and not github_rollup.empty:
            latest_rollup = github_rollup[github_rollup["signal_date"] == latest_github_date].copy()
            rollup_summary = (
                latest_rollup.groupby("provider_display_name", dropna=False)
                .agg(
                    **{
                        "Latest GitHub Signal Repos": ("repo_full_name", "nunique"),
                        "Latest Manifest Repos": ("has_manifest_dependency", "sum"),
                        "Latest Import Repos": ("has_code_import", "sum"),
                        "Latest Env Repos": ("has_env_var", "sum"),
                        "Latest Model Repos": ("has_model_name", "sum"),
                    }
                )
                .reset_index()
                .rename(columns={"provider_display_name": "Provider"})
            )
            summary = summary.merge(rollup_summary, on="Provider", how="left")

        summary = summary.sort_values("Latest PyPI Downloads", ascending=False)
        display_date = latest_github_date or latest_pypi_date
        st.caption(f"Latest provider snapshot: {display_date or 'n/a'}")
        st.dataframe(summary.fillna(""), use_container_width=True, hide_index=True)


def render_checks(checks: list[CheckResult]) -> None:
    ok_count   = sum(1 for c in checks if c.status == "ok")
    warn_count = sum(1 for c in checks if c.status == "warning")
    err_count  = sum(1 for c in checks if c.status == "error")

    label = f"Data Health — {ok_count} ok · {warn_count} warning · {err_count} error"
    with st.expander(label, expanded=(err_count > 0)):
        for chk in checks:
            css = f"chk-{chk.status}"
            domain_label = "" if chk.domain == "global" else f"[{chk.domain}] "
            st.markdown(
                f'<div class="{css}">{domain_label}{chk.title}</div>'
                f'<div style="color:{MUTED};margin-bottom:0.8rem;font-size:0.85rem;">{chk.detail}</div>',
                unsafe_allow_html=True,
            )


@st.cache_data(ttl=3600)
def load_state_cached(base_dir: Path) -> tuple[dict[str, DatasetLoadResult], FreshnessInfo, list[CheckResult]]:
    """Cached version of load_state to avoid re-running on every health check/refresh."""
    datasets = load_all_datasets(base_dir=base_dir)
    freshness = load_latest_manifest(base_dir=base_dir, datasets=datasets)
    checks = run_checks(datasets, freshness, base_dir=base_dir)
    return datasets, freshness, checks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # 1. Immediate call to set_page_config
    st.set_page_config(page_title="Alternative Data Dashboard", layout="wide", page_icon="📊")
    
    # 2. Startup logging for deployment debugging
    print("Main script execution started: alternative-data dashboard")
    
    inject_css()

    # 3. Use cached state
    datasets, freshness, checks = load_state_cached(BASE_DIR)

    render_header(freshness)
    
    main_tabs = st.tabs(["OpenRouter Intelligence", "GitHub Trending", "Provider Adoption"])
    
    with main_tabs[0]:
        render_kpi_row(datasets)
        render_top_models_chart(datasets)
        render_market_share_section(datasets)
        render_leaderboard(datasets)
        render_app_usage_chart(datasets)
        render_apps_tables(datasets)
    
    with main_tabs[1]:
        render_github_trending_section(datasets)

    with main_tabs[2]:
        render_provider_adoption_section(datasets)
        
    render_checks(checks)


if __name__ == "__main__":
    main()
