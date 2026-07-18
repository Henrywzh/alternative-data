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
    make_stacked_area_chart,
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

# The spend/model sub-tabs share one set of filter dimensions (label -> dimension_type).
# "Overall" is the un-filtered aggregate.
SPEND_DIMENSIONS = {
    "Overall": None,
    "By state": "business_office_state",
    "By sector": "naics_sector",
    "By financing": "company_financing_status",
    "By company size": "fte_segment",
}

# "Filter mode" combines all four dimensions at once against the cohort timeseries
# endpoints (ramp_ai_filter_*), which — unlike the single-month by-dimension views
# above — carry the full monthly history for every filter combination.
FILTER_MODE_LABEL = "Filter mode (combine filters)"
FILTER_DIM_ORDER = ["business_office_state", "fte_segment", "naics_sector", "company_financing_status"]
FILTER_DIM_LABELS = {
    "business_office_state": "State",
    "fte_segment": "Company size",
    "naics_sector": "Sector",
    "company_financing_status": "Financing",
}
SPEND_TYPE_LABELS = {
    "api": "API usage",
    "chat_subscription": "Chat subscription",
    "coding_agent": "Coding agent",
    "other_ai": "Other AI",
}
# Fixed stacking order so a spend type keeps the same colour across every panel.
SPEND_TYPE_ORDER = ["api", "chat_subscription", "coding_agent", "other_ai"]

# Natural (non-alphabetical) ordering for the small categorical dimensions.
DIM_VALUE_ORDER = {
    "fte_segment": ["Small", "Medium", "Large"],
    "company_financing_status": ["VC-backed", "PE-backed", "Other"],
}

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

    if selected_category != ALL_VENDORS:
        view_mode = st.radio(
            "View by",
            ["Adoption Over Time", "Share of Spend", "Adoption YoY"],
            horizontal=True,
            key="ramp_category_view_mode",
        )
    else:
        view_mode = "Adoption Over Time"

    category_slug = None
    if selected_category != ALL_VENDORS and not category.empty:
        cat_row = category[category["category_name"] == selected_category]
        if not cat_row.empty:
            category_slug = cat_row.iloc[0]["category_slug"]

    if view_mode == "Adoption Over Time":
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

    elif view_mode == "Share of Spend":
        result = datasets.get("ramp_category_spend_share_quarterly")
        if not result or result.frame.empty:
            st.info("No Share of Spend data available. Run the category-charts scraping pipeline first.")
            return
        frame = result.frame
        filtered = frame[frame["category_slug"] == category_slug].copy()
        if filtered.empty:
            st.info(f"No Share of Spend data for {selected_category}.")
            return

        import plotly.express as px
        filtered["spend_share_pct"] = pd.to_numeric(filtered["spend_share"], errors="coerce") * 100.0
        filtered = filtered.sort_values(by=["quarter", "spend_share_pct"], ascending=[True, False])

        fig = px.bar(
            filtered,
            x="quarter",
            y="spend_share_pct",
            color="vendor_name",
            title=f"Quarterly Share of Spend in {selected_category}",
            labels={"quarter": "Quarter", "spend_share_pct": "Share of Spend (%)", "vendor_name": "Vendor"},
            color_discrete_sequence=PALETTE,
        )
        fig.update_layout(
            margin=dict(l=40, r=40, t=40, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(type='category')
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Quarterly share of total category spend captured by each vendor in the {selected_category} category.")

    elif view_mode == "Adoption YoY":
        result = datasets.get("ramp_category_adoption_yoy_comparison")
        if not result or result.frame.empty:
            st.info("No YoY comparison data available. Run the category-charts scraping pipeline first.")
            return
        frame = result.frame
        filtered = frame[frame["category_slug"] == category_slug].copy()
        if filtered.empty:
            st.info(f"No YoY comparison data for {selected_category}.")
            return

        import plotly.express as px
        filtered["adoption_rate_pct"] = pd.to_numeric(filtered["adoption_rate"], errors="coerce") * 100.0
        filtered["period"] = pd.to_datetime(filtered["date_month"]).dt.strftime("%b %Y")

        fig = px.bar(
            filtered,
            x="vendor_name",
            y="adoption_rate_pct",
            color="period",
            barmode="group",
            title=f"Year-over-Year Adoption Rate Comparison in {selected_category}",
            labels={"vendor_name": "Vendor", "adoption_rate_pct": "Adoption Rate (%)", "period": "Period"},
            color_discrete_sequence=PALETTE,
        )
        fig.update_layout(
            margin=dict(l=40, r=40, t=40, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Year-over-year comparative adoption rate snapshot for vendors in the {selected_category} category.")


# ------------------------------------------------------------------ AI Index

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
        dim_label = st.selectbox("Breakdown", [*SPEND_DIMENSIONS, FILTER_MODE_LABEL], key="ramp_pepm_dim")
        if dim_label == FILTER_MODE_LABEL:
            _render_filter_mode(datasets, kind="pepm")
            return
        dim_type = SPEND_DIMENSIONS[dim_label]
        if dim_type is None:
            result = datasets.get("ramp_ai_pepm_spend")
            if not result or result.frame.empty:
                st.info("No spend-per-employee data.")
                return
            frame = result.frame.copy()
            frame["date_month"] = frame["date_month"].astype(str)
            cols = {"median_pepm": "Median", "p90_pepm": "90th pct", "p99_pepm": "99th pct"}
            pivot = frame.set_index("date_month")[list(cols)].rename(columns=cols).sort_index()
            caption = "Monthly AI spend per employee (PEPM) across businesses on Ramp."
        else:
            # PEPM is a level, so by-dimension IS a genuine monthly time series.
            result = datasets.get("ramp_ai_pepm_spend_by_dimension")
            if not result or result.frame.empty:
                st.info("No by-dimension PEPM data.")
                return
            frame = result.frame[result.frame["dimension_type"] == dim_type].copy()
            frame["date_month"] = frame["date_month"].astype(str)
            frame["median_pepm"] = pd.to_numeric(frame["median_pepm"], errors="coerce")
            pivot = frame.pivot_table(index="date_month", columns="dimension_label",
                                      values="median_pepm", aggfunc="mean").sort_index()
            caption = f"Monthly median AI spend per employee (PEPM) {dim_label.lower()}."
        fig = make_line_chart(pivot, colors=PALETTE, y_title="AI spend per employee ($/mo)",
                              x_title="Month", hover_suffix="", connect_gaps=True)
        st.plotly_chart(fig, width="stretch", theme=None)
        st.caption(caption)

    elif view == "Spend share":
        dim_label = st.selectbox("Breakdown", [*SPEND_DIMENSIONS, FILTER_MODE_LABEL], key="ramp_spendshare_dim")
        if dim_label == FILTER_MODE_LABEL:
            _render_filter_mode(datasets, kind="spend")
            return
        dim_type = SPEND_DIMENSIONS[dim_label]
        if dim_type is None:
            result = datasets.get("ramp_ai_spend_breakdown")
            if not result or result.frame.empty:
                st.info("No spend-breakdown data.")
                return
            frame = result.frame.copy()
            frame["date_month"] = frame["date_month"].astype(str)
            frame["spend_usd"] = pd.to_numeric(frame["spend_usd"], errors="coerce")
            dollars = frame.pivot_table(index="date_month", columns="spend_category",
                                        values="spend_usd", aggfunc="sum").sort_index()
            # Normalize each month to a 100% share of AI spend by type.
            share = dollars.div(dollars.sum(axis=1).replace(0, pd.NA), axis=0) * 100.0
            fig = make_stacked_area_chart(share, display_index=list(share.index), colors=PALETTE,
                                          x_title="Month", y_title="Share of AI spend (%)",
                                          value_format=".1f", hover_suffix="%")
            st.plotly_chart(fig, width="stretch", theme=None)
            st.caption("Share of AI spend by spend type over time (API usage, chat/coding subscriptions, other AI).")
        else:
            _render_dimension_history(datasets, kind="spend", dim_type=dim_type, dim_label=dim_label)

    else:  # Model share
        dim_label = st.selectbox("Breakdown", [*SPEND_DIMENSIONS, FILTER_MODE_LABEL], key="ramp_modelshare_dim")
        if dim_label == FILTER_MODE_LABEL:
            _render_filter_mode(datasets, kind="model")
            return
        dim_type = SPEND_DIMENSIONS[dim_label]
        if dim_type is None:
            result = datasets.get("ramp_ai_model_breakdown")
            if not result or result.frame.empty:
                st.info("No model-breakdown data.")
                return
            frame = result.frame.copy()
            frame["date_month"] = frame["date_month"].astype(str)
            frame["model_share"] = pd.to_numeric(frame["model_share"], errors="coerce")
            frame["label"] = frame["ai_provider"].astype(str) + " · " + frame["model_label"].astype(str)
            pivot = frame.pivot_table(index="date_month", columns="label",
                                      values="model_share", aggfunc="sum").sort_index() * 100.0
            leaders = pivot.iloc[-1].sort_values(ascending=False).head(12).index.tolist()
            fig = make_line_chart(pivot[leaders], colors=PALETTE, y_title="Share of AI model spend (%)",
                                  x_title="Month", hover_suffix="%", connect_gaps=True)
            st.plotly_chart(fig, width="stretch", theme=None)
            st.caption("Share of AI model spend by provider/model over time (top 12 by latest month).")
        else:
            _render_dimension_history(datasets, kind="model", dim_type=dim_type, dim_label=dim_label)


_FILTER_MODE_DATASETS = {
    "spend": "ramp_ai_filter_spend_share",
    "model": "ramp_ai_filter_model_share",
    "pepm": "ramp_ai_filter_pepm",
}


def _render_filter_mode(datasets, *, kind: str) -> None:
    """Cohort filter mode: four combinable dimension dropdowns over the full monthly
    timeseries (ramp_ai_filter_* endpoints). "All" on a dimension means unfiltered."""
    result = datasets.get(_FILTER_MODE_DATASETS[kind])
    if not result or result.frame.empty:
        st.info("No filter-mode data available. Run `ramp-data filter-mode` to populate it.")
        return
    frame = result.frame.copy()

    # One selectbox per dimension; "ALL" (shown as "All") keeps the cohort open.
    cols = st.columns(len(FILTER_DIM_ORDER))
    selected: dict[str, str] = {}
    for col, dim in zip(cols, FILTER_DIM_ORDER):
        values = [v for v in frame[dim].dropna().unique() if v != "ALL"]
        options = ["ALL", *sorted(values)]
        with col:
            selected[dim] = st.selectbox(
                FILTER_DIM_LABELS[dim], options,
                format_func=lambda v: "All" if v == "ALL" else v,
                key=f"ramp_fm_{kind}_{dim}",
            )

    cohort = frame
    for dim, value in selected.items():
        cohort = cohort[cohort[dim] == value]
    if cohort.empty:
        st.info("No data for this filter combination — try widening a filter.")
        return
    cohort = cohort.copy()
    cohort["date_month"] = cohort["date_month"].astype(str)

    active = [f"{FILTER_DIM_LABELS[d]}: {v}" for d, v in selected.items() if v != "ALL"]
    cohort_label = ", ".join(active) if active else "all businesses"

    if kind == "spend":
        cohort["spend_share"] = pd.to_numeric(cohort["spend_share"], errors="coerce") * 100.0
        pivot = cohort.pivot_table(index="date_month", columns="pepm_spend_type",
                                   values="spend_share", aggfunc="sum").sort_index()
        pivot = pivot.rename(columns=SPEND_TYPE_LABELS)
        fig = make_stacked_area_chart(pivot, display_index=list(pivot.index), colors=PALETTE,
                                      x_title="Month", y_title="Share of AI spend (%)",
                                      value_format=".1f", hover_suffix="%")
        st.plotly_chart(fig, width="stretch", theme=None)
        st.caption(f"Monthly AI spend share by type for **{cohort_label}**.")
    elif kind == "model":
        cohort["model_share"] = pd.to_numeric(cohort["model_share"], errors="coerce") * 100.0
        cohort["label"] = cohort["ai_provider"].astype(str) + " · " + cohort["model_label"].astype(str)
        pivot = cohort.pivot_table(index="date_month", columns="label",
                                   values="model_share", aggfunc="sum").sort_index()
        leaders = pivot.iloc[-1].sort_values(ascending=False).head(12).index.tolist()
        fig = make_line_chart(pivot[leaders], colors=PALETTE, y_title="Share of AI model spend (%)",
                              x_title="Month", hover_suffix="%", connect_gaps=True)
        st.plotly_chart(fig, width="stretch", theme=None)
        st.caption(f"Monthly AI model spend share (top 12) for **{cohort_label}**.")
    else:  # pepm
        labels = {"median_pepm": "Median", "p90_pepm": "90th pct", "p99_pepm": "99th pct"}
        for col_name in labels:
            cohort[col_name] = pd.to_numeric(cohort[col_name], errors="coerce")
        pivot = cohort.set_index("date_month")[list(labels)].rename(columns=labels).sort_index()
        fig = make_line_chart(pivot, colors=PALETTE, y_title="AI spend per employee ($/mo)",
                              x_title="Month", hover_suffix="", connect_gaps=True)
        st.plotly_chart(fig, width="stretch", theme=None)
        st.caption(f"Monthly AI spend per employee (PEPM) for **{cohort_label}**.")


def _ordered_dim_values(cohort: pd.DataFrame, dim_type: str) -> list[str]:
    values = [v for v in cohort[dim_type].dropna().unique() if v != "ALL"]
    order = DIM_VALUE_ORDER.get(dim_type)
    if order:
        return [v for v in order if v in values] + [v for v in values if v not in order]
    return sorted(values)


def _render_dimension_history(datasets, *, kind: str, dim_type: str, dim_label: str) -> None:
    """Small multiples: one 100%-stacked-area composition per dimension value, so the
    spend/model *mix* is preserved (unlike a single-series line) and cohorts can be
    compared side by side. Uses the single-dimension filter cohorts (chosen dim
    varies, the other three are "ALL")."""
    result = datasets.get(_FILTER_MODE_DATASETS[kind])
    if not result or result.frame.empty:
        st.info("No filter-mode data available. Run `ramp-data filter-mode` to populate it.")
        return
    frame = result.frame
    others = [d for d in FILTER_DIM_ORDER if d != dim_type]
    cohort = frame[(frame[dim_type] != "ALL") & (frame[others].eq("ALL").all(axis=1))].copy()
    if cohort.empty:
        st.info(f"No data for {dim_label.lower()}.")
        return
    cohort["date_month"] = cohort["date_month"].astype(str)

    if kind == "spend":
        cohort["value"] = pd.to_numeric(cohort["spend_share"], errors="coerce")
        cat_col = "pepm_spend_type"
        cat_order = SPEND_TYPE_ORDER
        cat_labels = SPEND_TYPE_LABELS
        noun, comp = "AI spend", "spend type"
    else:
        cohort["value"] = pd.to_numeric(cohort["model_share"], errors="coerce")
        # Collapse the long tail of providers into "Other" so each panel stays readable.
        totals = cohort.groupby("ai_provider")["value"].sum().sort_values(ascending=False)
        top = totals.head(6).index.tolist()
        cohort["provider_grp"] = cohort["ai_provider"].where(cohort["ai_provider"].isin(top), "Other")
        cat_col = "provider_grp"
        cat_order = [*top, "Other"]
        cat_labels = {c: c for c in cat_order}
        noun, comp = "AI model spend", "provider"

    color_map = {cat: PALETTE[i % len(PALETTE)] for i, cat in enumerate(cat_order)}
    values = _ordered_dim_values(cohort, dim_type)
    capped = len(values) > 12
    values = values[:12]
    seg = dim_label.replace("By ", "").lower()

    st.caption(
        f"Monthly {noun} composition by {comp} — one panel per {seg}, each stacked to 100%."
        + (f" Top 12 {seg} values shown." if capped else "")
    )

    def _panel(val: str):
        sub = cohort[cohort[dim_type] == val]
        pivot = sub.pivot_table(index="date_month", columns=cat_col, values="value", aggfunc="sum").sort_index()
        pivot = pivot.reindex(columns=[c for c in cat_order if c in pivot.columns])
        pivot = pivot.div(pivot.sum(axis=1).replace(0, pd.NA), axis=0) * 100.0
        colors = [color_map[c] for c in pivot.columns]
        pivot = pivot.rename(columns=cat_labels)
        return make_stacked_area_chart(
            pivot, display_index=list(pivot.index), colors=colors,
            x_title="", y_title="Share (%)", height=260, value_format=".0f", hover_suffix="%",
        )

    for row_start in range(0, len(values), 2):
        grid = st.columns(2)
        for col, val in zip(grid, values[row_start:row_start + 2]):
            with col:
                st.markdown(f"**{val}**")
                st.plotly_chart(_panel(val), width="stretch", theme=None)


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
