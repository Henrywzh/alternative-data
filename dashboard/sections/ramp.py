"""Ramp vendor-intelligence section.

Surfaces Ramp's vendor adoption data (from ``ramp.com/vendors``) as adoption
share over time, scoped by Ramp's own product categories:

- a **category** selector (or all tracked vendors),
- a **metric** toggle (adoption rate / competitor switch rate / new-adopter
  share), all reported as a share of businesses on Ramp,
- a multi-line trend of the leading vendors, plus a latest-month leaderboard.

Data comes from ``ramp_vendor_adoption_monthly`` (the monthly time series, keyed
on ``[vendor_slug, spend_month]``) and ``ramp_category_vendors`` (the current
category membership snapshot, keyed on ``[category_slug, vendor_slug]``). Ramp's
rates are fractions in [0, 1]; the section renders them as percentages.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import (
    dataframe_for_display,
    kpi_card_html,
    kpi_grid_html,
    make_line_chart,
    render_dataset_guard,
)
from dashboard.data import DatasetLoadResult

# AI Index adoption datasets: label -> (dataset_id, breakdown column). Overall has
# no breakdown (single series); the rest pivot date_month x <breakdown>.
AI_ADOPTION_VIEWS = {
    "Overall": ("ramp_ai_adoption_overall", None),
    "By business size": ("ramp_ai_adoption_by_size", "business_size"),
    "By sector": ("ramp_ai_adoption_by_sector", "naics_sector"),
    "By vendor": ("ramp_ai_adoption_by_vendor", "vendor"),
    "By state": ("ramp_ai_adoption_by_state", "state_code"),
}
JOBS_ID = "ramp_ai_jobs_impact"

MONTHLY_ID = "ramp_vendor_adoption_monthly"
CATEGORY_ID = "ramp_category_vendors"

ALL_VENDORS = "All tracked vendors"

# Fraction-valued metrics, rendered as percentages.
METRIC_LABELS = {
    "adoption_rate": "Adoption rate",
    "competitor_switch_rate": "Competitor switch rate",
    "new_adopter_share": "New-adopter share",
}

TOP_N = 12

PALETTE = [
    "#4285F4", "#FF6B6B", "#00B5A4", "#FF7849", "#8B5CF6", "#EC4899",
    "#84CC16", "#F59E0B", "#06B6D4", "#2563EB", "#DC2626", "#059669",
]


def _prep_monthly(result: DatasetLoadResult | None) -> pd.DataFrame:
    if result is None or result.frame.empty:
        return pd.DataFrame()
    frame = result.frame.copy()
    frame["spend_month"] = frame["spend_month"].astype(str)
    frame["display_name"] = frame["vendor_name"].fillna(frame["vendor_slug"])
    return frame


def _prep_category(result: DatasetLoadResult | None) -> pd.DataFrame:
    if result is None or result.frame.empty:
        return pd.DataFrame()
    return result.frame.copy()


def _category_options(category_frame: pd.DataFrame) -> list[str]:
    """Category names ordered by vendor count (most populated first)."""
    if category_frame.empty:
        return []
    counts = (
        category_frame.dropna(subset=["category_name"])
        .groupby("category_name")["vendor_slug"]
        .nunique()
        .sort_values(ascending=False)
    )
    return counts.index.tolist()


def _scope_slugs(category_frame: pd.DataFrame, category_name: str) -> set[str] | None:
    """Vendor slugs in the chosen category, or None for the full universe."""
    if category_name == ALL_VENDORS or category_frame.empty:
        return None
    subset = category_frame[category_frame["category_name"] == category_name]
    return set(subset["vendor_slug"].dropna())


def _latest_leaders(scoped: pd.DataFrame, metric: str, n: int) -> list[str]:
    latest_month = scoped["spend_month"].max()
    latest = scoped[scoped["spend_month"] == latest_month]
    ranked = (
        latest.dropna(subset=[metric])
        .sort_values(metric, ascending=False)
        .drop_duplicates("display_name")
    )
    return ranked["display_name"].head(n).tolist()


def _pivot(scoped: pd.DataFrame, metric: str, leaders: list[str]) -> pd.DataFrame:
    subset = scoped[scoped["display_name"].isin(leaders)]
    pivot = subset.pivot_table(
        index="spend_month", columns="display_name", values=metric, aggfunc="mean"
    ).sort_index()
    # Percentages, ordered by the leader ranking so colours stay stable.
    ordered = [name for name in leaders if name in pivot.columns]
    return (pivot[ordered] * 100.0) if ordered else pivot


def _kpis(monthly: pd.DataFrame, scoped: pd.DataFrame, category_count: int) -> dict[str, object]:
    latest_month = scoped["spend_month"].max()
    latest = scoped[scoped["spend_month"] == latest_month].dropna(subset=["adoption_rate"])
    if latest.empty:
        return {}
    top = latest.sort_values("adoption_rate", ascending=False).iloc[0]
    return {
        "latest_month": latest_month,
        "vendors": int(scoped["vendor_slug"].nunique()),
        "categories": category_count,
        "leader": str(top["display_name"]),
        "leader_share": float(top["adoption_rate"]) * 100.0,
    }


def compute_ramp_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    monthly = _prep_monthly(datasets.get(MONTHLY_ID))
    category = _prep_category(datasets.get(CATEGORY_ID))
    if monthly.empty:
        return {}
    return {"monthly": monthly, "category": category}


def _render_kpi_row(kpis: dict[str, object]) -> None:
    if not kpis:
        return
    leader = str(kpis["leader"])
    leader_disp = leader if len(leader) <= 26 else leader[:24] + "…"
    st.markdown(
        kpi_grid_html(
            kpi_card_html("Latest Month", str(kpis["latest_month"]), delta="adoption share"),
            kpi_card_html("Vendors Tracked", f"{kpis['vendors']:,}", delta="in scope"),
            kpi_card_html("Top Vendor", leader_disp, delta="by adoption rate", value_style="font-size:1.1rem;"),
            kpi_card_html("Leader Adoption", f"{kpis['leader_share']:.1f}%", delta="of businesses on Ramp"),
        ),
        unsafe_allow_html=True,
    )


def _render_leaderboard(scoped: pd.DataFrame) -> None:
    latest_month = scoped["spend_month"].max()
    latest = scoped[scoped["spend_month"] == latest_month].copy()
    if latest.empty:
        return
    latest = latest.sort_values("adoption_rate", ascending=False).drop_duplicates("display_name")
    table = pd.DataFrame(
        {
            "Vendor": latest["display_name"],
            "Domain": latest["vendor_domain"],
            "Adoption %": (latest["adoption_rate"] * 100.0).round(1),
            "YoY (pts)": (latest["adoption_rate_yoy"] * 100.0).round(1),
            "Rank": latest["adoption_rank"],
            "Switch %": (latest["competitor_switch_rate"] * 100.0).round(1),
        }
    ).head(30)
    st.caption(f"Latest-month leaderboard ({latest_month}) — adoption share of businesses on Ramp.")
    st.dataframe(dataframe_for_display(table), width="stretch", hide_index=True)


def _render_vendors(datasets) -> None:
    monthly_result = datasets.get(MONTHLY_ID)
    if not monthly_result or not render_dataset_guard(monthly_result):
        return

    views = compute_ramp_views(datasets)
    monthly: pd.DataFrame = views.get("monthly", pd.DataFrame())  # type: ignore[assignment]
    category: pd.DataFrame = views.get("category", pd.DataFrame())  # type: ignore[assignment]
    if monthly.empty:
        st.info("No Ramp vendor data available yet.")
        return

    options = [ALL_VENDORS] + _category_options(category)
    controls = st.columns([2, 2])
    with controls[0]:
        selected_category = st.selectbox("Category", options, index=min(1, len(options) - 1), key="ramp_category")
    with controls[1]:
        metric = st.radio(
            "Metric",
            list(METRIC_LABELS.keys()),
            horizontal=True,
            format_func=lambda m: METRIC_LABELS[m],
            key="ramp_metric",
        )

    slugs = _scope_slugs(category, selected_category)
    scoped = monthly if slugs is None else monthly[monthly["vendor_slug"].isin(slugs)]
    if scoped.empty:
        st.info(f"No vendor data for {selected_category}.")
        return

    _render_kpi_row(_kpis(monthly, scoped, len(_category_options(category))))

    leaders = _latest_leaders(scoped, metric, TOP_N)
    pivot = _pivot(scoped, metric, leaders)
    if pivot.empty:
        st.info(f"No {METRIC_LABELS[metric].lower()} data for {selected_category}.")
        return

    fig = make_line_chart(
        pivot,
        colors=PALETTE,
        y_title=f"{METRIC_LABELS[metric]} (%)",
        x_title="Month",
        hover_suffix="%",
        connect_gaps=True,
    )
    st.plotly_chart(fig, width="stretch", theme=None)
    scope_label = "all tracked vendors" if slugs is None else f"the {selected_category} category"
    st.caption(
        f"Monthly **{METRIC_LABELS[metric].lower()}** for the top {len(leaders)} vendors in {scope_label}, "
        f"as a share of businesses transacting on Ramp."
    )

    _render_leaderboard(scoped)


# ------------------------------------------------------------------ AI Index

def _latest(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["date_month"] == frame["date_month"].max()]


def _render_ai_index(datasets) -> None:
    overall = datasets.get("ramp_ai_adoption_overall")
    if not overall or overall.frame.empty:
        st.info("No Ramp AI Index data available yet.")
        return

    view = st.radio(
        "View",
        ["Adoption", "Spend per employee", "Spend share", "Model share"],
        horizontal=True,
        key="ramp_ai_view",
    )

    if view == "Adoption":
        dim_label = st.selectbox("Breakdown", list(AI_ADOPTION_VIEWS.keys()), key="ramp_ai_dim")
        dataset_id, breakdown = AI_ADOPTION_VIEWS[dim_label]
        result = datasets.get(dataset_id)
        if not result or result.frame.empty:
            st.info(f"No data for {dim_label.lower()}.")
            return
        frame = result.frame.copy()
        frame["date_month"] = frame["date_month"].astype(str)
        frame["adoption_rate_pct"] = pd.to_numeric(frame["adoption_rate_pct"], errors="coerce")
        if breakdown is None:
            pivot = frame.set_index("date_month")[["adoption_rate_pct"]].rename(
                columns={"adoption_rate_pct": "Overall"}
            ).sort_index()
        else:
            pivot = frame.pivot_table(
                index="date_month", columns=breakdown, values="adoption_rate_pct", aggfunc="mean"
            ).sort_index()
            # Cap series to the top 12 by latest value so the chart stays legible.
            leaders = pivot.iloc[-1].sort_values(ascending=False).head(12).index.tolist()
            pivot = pivot[leaders]
        fig = make_line_chart(pivot, colors=PALETTE, y_title="AI adoption (%)", x_title="Month",
                              hover_suffix="%", connect_gaps=True)
        st.plotly_chart(fig, width="stretch", theme=None)
        st.caption(f"Share of businesses on Ramp adopting AI, {dim_label.lower()} (monthly).")

    elif view == "Spend per employee":
        result = datasets.get("ramp_ai_pepm_spend")
        if not result or result.frame.empty:
            st.info("No spend-per-employee data.")
            return
        frame = result.frame.copy()
        frame["date_month"] = frame["date_month"].astype(str)
        cols = {"median_pepm": "Median", "p90_pepm": "90th pct", "p99_pepm": "99th pct"}
        pivot = frame.set_index("date_month")[list(cols)].rename(columns=cols).sort_index()
        fig = make_line_chart(pivot, colors=PALETTE, y_title="AI spend per employee ($/mo)",
                              x_title="Month", hover_suffix="", connect_gaps=True)
        st.plotly_chart(fig, width="stretch", theme=None)
        st.caption("Monthly AI spend per employee (PEPM) across businesses on Ramp.")

    elif view == "Spend share":
        result = datasets.get("ramp_ai_spend_share_by_category")
        if not result or result.frame.empty:
            st.info("No spend-share data.")
            return
        frame = _latest(result.frame.copy())
        frame = frame[frame["dimension_value"] == frame["dimension_value"].iloc[0]]
        table = (
            frame[["spend_category", "spend_share"]]
            .assign(spend_share=lambda d: pd.to_numeric(d["spend_share"], errors="coerce") * 100.0)
            .sort_values("spend_share", ascending=False)
            .set_index("spend_category")
        )
        st.bar_chart(table["spend_share"])
        st.caption(f"AI spend share by category, latest month ({result.frame['date_month'].max()}).")

    else:  # Model share
        result = datasets.get("ramp_ai_provider_model_share")
        if not result or result.frame.empty:
            st.info("No model-share data.")
            return
        frame = _latest(result.frame.copy())
        frame = frame[frame["dimension_value"] == frame["dimension_value"].iloc[0]]
        frame["label"] = frame["ai_provider"].astype(str) + " · " + frame["model_label"].astype(str)
        table = (
            frame.assign(model_share=lambda d: pd.to_numeric(d["model_share"], errors="coerce") * 100.0)
            .sort_values("model_share", ascending=False)
            .head(15)
            .set_index("label")
        )
        st.bar_chart(table["model_share"])
        st.caption(f"AI provider/model spend share, latest month ({result.frame['date_month'].max()}).")


# --------------------------------------------------------------- Jobs Impact

def _render_jobs_impact(datasets) -> None:
    result = datasets.get(JOBS_ID)
    if not result or result.frame.empty:
        st.info("No AI jobs-impact data available yet. Run `ramp-data jobs-impact` to populate it.")
        return
    frame = result.frame.copy()
    for col in ["month_relative_to_adoption", "high_intensity_effect", "high_intensity_ci_low",
                "high_intensity_ci_high", "low_intensity_effect", "low_intensity_ci_low", "low_intensity_ci_high"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    figures = sorted(frame["figure"].dropna().unique().tolist())
    figure = figures[0] if len(figures) == 1 else st.selectbox("Figure", figures, key="ramp_jobs_fig")
    fig_df = frame[frame["figure"] == figure].sort_values("month_relative_to_adoption")
    x = fig_df["month_relative_to_adoption"].tolist()

    chart = go.Figure()
    series = [
        ("High-intensity adopters", "high_intensity_effect", "high_intensity_ci_low",
         "high_intensity_ci_high", "#4285F4", "rgba(66,133,244,0.15)"),
        ("Low-intensity adopters", "low_intensity_effect", "low_intensity_ci_low",
         "low_intensity_ci_high", "#FF7849", "rgba(255,120,73,0.15)"),
    ]
    for name, eff, lo, hi, color, fill in series:
        chart.add_trace(go.Scatter(x=x, y=fig_df[hi], line=dict(width=0), showlegend=False, hoverinfo="skip"))
        chart.add_trace(go.Scatter(x=x, y=fig_df[lo], fill="tonexty", fillcolor=fill, line=dict(width=0),
                                   showlegend=False, hoverinfo="skip"))
        chart.add_trace(go.Scatter(x=x, y=fig_df[eff], name=name, mode="lines+markers",
                                   line=dict(color=color, width=3),
                                   hovertemplate=f"<b>{name}</b><br>month %{{x}}<br>%{{y:.2f}}<extra></extra>"))
    chart.add_hline(y=0, line=dict(color="#9CA3AF", width=1))
    chart.add_vline(x=0, line=dict(color="#9CA3AF", width=1, dash="dash"))
    chart.update_layout(template="plotly_white", height=420,
                        xaxis_title="Months relative to AI adoption",
                        yaxis_title="Effect on headcount (log points × 100)",
                        legend=dict(orientation="h", y=-0.2), margin=dict(l=0, r=0, t=30, b=80))
    st.plotly_chart(chart, width="stretch", theme=None)
    st.caption(
        "Event study of headcount change after AI adoption (Ramp × Revelio Labs, 21,559 US firms). "
        "Shaded bands are 95% confidence intervals; month 0 is adoption. Effects in log points × 100."
    )
    with st.expander("Data table"):
        st.dataframe(dataframe_for_display(fig_df.drop(columns=["dataset_id", "source_url", "source_run_id", "scraped_at"], errors="ignore")),
                     width="stretch", hide_index=True)


def render(domain_states, datasets) -> None:
    st.markdown('<div class="section-title">Ramp Vendor Intelligence</div>', unsafe_allow_html=True)
    vendors_tab, ai_index_tab, jobs_tab = st.tabs(["Vendors", "AI Index", "Jobs Impact"])
    with vendors_tab:
        _render_vendors(datasets)
    with ai_index_tab:
        _render_ai_index(datasets)
    with jobs_tab:
        _render_jobs_impact(datasets)
