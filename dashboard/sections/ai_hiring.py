from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import dataframe_for_display, format_metric, kpi_card_html, kpi_grid_html
from dashboard.data import DatasetLoadResult
from dashboard.theme import CARD, GRID, MODEL_COLORS, MUTED, TEXT


INDEED_ID = "indeed_ai_posting_share_daily"
DEMAND_ID = "hiring_demand_daily"
JOBS_ID = "hiring_jobs"
HEALTH_ID = "hiring_source_health"

COUNTRY_LABELS = {
    "AU": "Australia",
    "CA": "Canada",
    "DE": "Germany",
    "ES": "Spain",
    "FR": "France",
    "GB": "United Kingdom",
    "IT": "Italy",
    "NL": "Netherlands",
    "US": "United States",
}


def _frame(datasets: dict[str, DatasetLoadResult], dataset_id: str) -> pd.DataFrame:
    result = datasets.get(dataset_id)
    return result.frame.copy() if result is not None and not result.frame.empty else pd.DataFrame()


def _prepare(datasets: dict[str, DatasetLoadResult]) -> dict[str, pd.DataFrame]:
    indeed = _frame(datasets, INDEED_ID)
    demand = _frame(datasets, DEMAND_ID)
    jobs = _frame(datasets, JOBS_ID)
    health = _frame(datasets, HEALTH_ID)

    if not indeed.empty:
        indeed["date"] = pd.to_datetime(indeed["date"], errors="coerce")
        indeed["ai_share_pct"] = pd.to_numeric(indeed["ai_share_pct"], errors="coerce")
        indeed = indeed.dropna(subset=["date", "jobcountry", "ai_share_pct"])
    if not demand.empty:
        demand["snapshot_date"] = pd.to_datetime(demand["snapshot_date"], errors="coerce")
        for column in (
            "active_postings",
            "active_requisitions",
            "ai_role_postings",
            "new_postings_28d",
            "closed_postings_28d",
            "net_posting_flow_28d",
        ):
            demand[column] = pd.to_numeric(demand[column], errors="coerce").fillna(0)
        demand["same_store_28d"] = demand["same_store_28d"].fillna(False).astype(bool)
        demand = demand.dropna(subset=["snapshot_date", "company_name"])
    if not jobs.empty:
        jobs["published_at"] = pd.to_datetime(jobs["published_at"], errors="coerce", utc=True)
        jobs["is_ai_role"] = jobs["is_ai_role"].fillna(False).astype(bool)
        jobs["status"] = jobs["status"].fillna("unknown").astype(str)
    if not health.empty:
        health["row_count"] = pd.to_numeric(health["row_count"], errors="coerce")
        health["response_ms"] = pd.to_numeric(health["response_ms"], errors="coerce")
        health["scraped_at"] = pd.to_datetime(health["scraped_at"], errors="coerce", utc=True)
    return {"indeed": indeed, "demand": demand, "jobs": jobs, "health": health}


def _render_kpis(indeed: pd.DataFrame, demand: pd.DataFrame, health: pd.DataFrame) -> None:
    us = (
        indeed[indeed["jobcountry"].astype(str) == "US"].sort_values("date")
        if not indeed.empty
        else pd.DataFrame()
    )
    us_latest = us.iloc[-1] if not us.empty else None

    latest_date = demand["snapshot_date"].max() if not demand.empty else None
    latest = demand[
        (demand["snapshot_date"] == latest_date) & (demand["role_family"].astype(str) == "All roles")
    ] if latest_date is not None else pd.DataFrame()
    active_requisitions = int(latest["active_requisitions"].sum()) if not latest.empty else 0
    active_postings = int(latest["active_postings"].sum()) if not latest.empty else 0
    ai_postings = int(latest["ai_role_postings"].sum()) if not latest.empty else 0
    ai_share = (ai_postings / active_postings * 100.0) if active_postings else 0.0

    boards = health[health["source_kind"].astype(str) == "job_board"] if not health.empty else health
    healthy_boards = int((boards["status"].astype(str) == "ok").sum()) if not boards.empty else 0
    board_count = len(boards)
    st.markdown(
        kpi_grid_html(
            kpi_card_html(
                "US AI Posting Share",
                f"{float(us_latest['ai_share_pct']):.2f}%" if us_latest is not None else "—",
                delta=(
                    f"Indeed · {us_latest['date']:%b %Y} · monthly source refresh"
                    if us_latest is not None
                    else "Indeed series unavailable"
                ),
            ),
            kpi_card_html(
                "Active Requisitions",
                format_metric(active_requisitions),
                delta=f"{format_metric(active_postings)} public postings · fixed 10-company cohort",
            ),
            kpi_card_html(
                "AI / ML-Titled Roles",
                f"{ai_share:.1f}%",
                delta=f"{format_metric(ai_postings)} postings · deterministic title taxonomy",
            ),
            kpi_card_html(
                "Healthy Company Boards",
                f"{healthy_boards}/{board_count}" if board_count else "—",
                delta="official public Ashby and Greenhouse endpoints",
            ),
        ),
        unsafe_allow_html=True,
    )


def _render_indeed(indeed: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Economy-Wide AI Hiring Signal</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Share of public Indeed job postings that mention AI. Daily observations, refreshed monthly by Indeed Hiring Lab; this is posting demand, not hires or employment.</div>',
        unsafe_allow_html=True,
    )
    if indeed.empty:
        st.info("The Indeed Hiring Lab series is not available yet.")
        return

    countries = sorted(indeed["jobcountry"].dropna().astype(str).unique())
    default_countries = [country for country in ("US", "GB", "CA") if country in countries]
    country_col, range_col, smoothing_col = st.columns([2, 1, 1], vertical_alignment="bottom")
    with country_col:
        selected = st.multiselect(
            "Countries",
            countries,
            default=default_countries,
            format_func=lambda code: COUNTRY_LABELS.get(code, code),
            key="ai_hiring_indeed_countries",
        )
    with range_col:
        history = st.selectbox("History", ("2 years", "5 years", "All"), index=0, key="ai_hiring_macro_history")
    with smoothing_col:
        frequency = st.selectbox("Display", ("28-day average", "Daily"), key="ai_hiring_macro_frequency")

    scoped = indeed[indeed["jobcountry"].isin(selected)].copy()
    days = {"2 years": 730, "5 years": 1826}.get(history)
    if days is not None and not scoped.empty:
        scoped = scoped[scoped["date"] >= scoped["date"].max() - pd.Timedelta(days=days)]
    scoped = scoped.sort_values(["jobcountry", "date"])
    if frequency == "28-day average":
        scoped["display_share"] = scoped.groupby("jobcountry")["ai_share_pct"].transform(
            lambda values: values.rolling(28, min_periods=1).mean()
        )
    else:
        scoped["display_share"] = scoped["ai_share_pct"]

    if scoped.empty:
        st.info("Select at least one country to display the series.")
        return
    figure = go.Figure()
    for index, country in enumerate(selected):
        country_rows = scoped[scoped["jobcountry"] == country]
        if country_rows.empty:
            continue
        figure.add_trace(
            go.Scatter(
                x=country_rows["date"],
                y=country_rows["display_share"],
                name=COUNTRY_LABELS.get(country, country),
                mode="lines",
                line=dict(color=MODEL_COLORS[index % len(MODEL_COLORS)], width=2),
                customdata=country_rows[["ai_share_pct"]],
                hovertemplate=(
                    "%{x|%b %d, %Y}<br><b>%{y:.2f}%</b> displayed"
                    "<br>%{customdata[0]:.2f}% daily<extra>%{fullData.name}</extra>"
                ),
            )
        )
    figure.update_layout(
        template="plotly_white",
        height=410,
        margin=dict(l=0, r=0, t=12, b=65),
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        font=dict(color=TEXT, size=12),
        legend=dict(orientation="h", y=-0.18),
        xaxis=dict(showgrid=False),
        yaxis=dict(gridcolor=GRID, title="AI share of job postings", ticksuffix="%"),
        hovermode="x unified",
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    latest_source_date = scoped["date"].max()
    st.caption(
        f"Latest source observation: {latest_source_date:%Y-%m-%d}. The 28-day view is a display-only rolling average; daily source rows remain available via the selector. Source license: CC BY 4.0."
    )


def _company_snapshot(demand: pd.DataFrame) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    if demand.empty:
        return pd.DataFrame(), None
    latest_date = demand["snapshot_date"].max()
    latest = demand[
        (demand["snapshot_date"] == latest_date) & (demand["role_family"].astype(str) == "All roles")
    ].copy()
    latest["ai_role_share_pct"] = latest["ai_role_postings"].div(latest["active_postings"].replace(0, pd.NA)).mul(100)
    return latest.sort_values("active_requisitions", ascending=False), latest_date


def _render_company_history(demand: pd.DataFrame) -> None:
    totals = demand[demand["role_family"].astype(str) == "All roles"].copy()
    if totals["snapshot_date"].nunique() < 2:
        coverage_start = totals["snapshot_date"].min()
        label = coverage_start.strftime("%Y-%m-%d") if pd.notna(coverage_start) else "the first successful run"
        st.info(
            f"Company lifecycle history begins {label}. The initial board snapshot is seeded as a baseline, so it is not counted as new hiring demand; daily opening and closure trends will build from subsequent runs."
        )
        return

    use_same_store = st.toggle(
        "Use 28-day same-store cohort",
        value=True,
        help="Includes only company boards with a healthy source and at least 28 days of uninterrupted coverage.",
        key="ai_hiring_same_store",
    )
    scoped = totals[totals["same_store_28d"]] if use_same_store else totals
    if scoped.empty:
        st.info("The 28-day same-store cohort is not mature yet. Turn off the same-store filter to inspect available history.")
        return

    figure = go.Figure()
    for index, company in enumerate(sorted(scoped["company_name"].dropna().astype(str).unique())):
        company_rows = scoped[scoped["company_name"].astype(str) == company].sort_values("snapshot_date")
        figure.add_trace(
            go.Scatter(
                x=company_rows["snapshot_date"],
                y=company_rows["active_requisitions"],
                name=company,
                mode="lines",
                line=dict(color=MODEL_COLORS[index % len(MODEL_COLORS)], width=2),
                hovertemplate="%{x|%b %d, %Y}<br><b>%{y:,.0f} requisitions</b><extra>%{fullData.name}</extra>",
            )
        )
    figure.update_layout(
        template="plotly_white",
        height=400,
        margin=dict(l=0, r=0, t=12, b=80),
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        font=dict(color=TEXT, size=12),
        legend=dict(orientation="h", y=-0.22),
        xaxis=dict(showgrid=False),
        yaxis=dict(gridcolor=GRID, title="Active requisitions"),
        hovermode="x unified",
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def _render_company_snapshot(demand: pd.DataFrame) -> None:
    latest, latest_date = _company_snapshot(demand)
    if latest.empty:
        st.info("No company demand snapshot is available yet.")
        return
    st.caption(f"Current public job-board snapshot · {latest_date:%Y-%m-%d} · all 10 companies shown")
    chart_col, role_col = st.columns([1, 1.45])
    with chart_col:
        ordered = latest.sort_values("active_requisitions", ascending=True)
        figure = go.Figure(
            go.Bar(
                x=ordered["active_requisitions"],
                y=ordered["company_name"],
                orientation="h",
                marker_color=MODEL_COLORS[0],
                customdata=ordered[["active_postings", "source_status"]],
                hovertemplate=(
                    "%{y}<br><b>%{x:,.0f} requisitions</b>"
                    "<br>%{customdata[0]:,.0f} public postings"
                    "<br>source: %{customdata[1]}<extra></extra>"
                ),
            )
        )
        figure.update_layout(
            template="plotly_white",
            height=430,
            margin=dict(l=0, r=10, t=12, b=45),
            paper_bgcolor=CARD,
            plot_bgcolor=CARD,
            font=dict(color=TEXT, size=12),
            xaxis=dict(gridcolor=GRID, title="Active requisitions"),
            yaxis=dict(showgrid=False),
        )
        st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})

    with role_col:
        role_rows = demand[
            (demand["snapshot_date"] == latest_date) & (demand["role_family"].astype(str) != "All roles")
        ].copy()
        pivot = role_rows.pivot_table(
            index="company_name", columns="role_family", values="active_postings", aggfunc="sum", fill_value=0
        ).reindex(latest["company_name"])
        figure = go.Figure()
        for index, role in enumerate(pivot.columns):
            figure.add_trace(
                go.Bar(
                    x=pivot.index,
                    y=pivot[role],
                    name=str(role),
                    marker_color=MODEL_COLORS[index % len(MODEL_COLORS)],
                    hovertemplate="%{x}<br><b>%{y:,.0f} postings</b><extra>" + str(role) + "</extra>",
                )
            )
        figure.update_layout(
            template="plotly_white",
            barmode="stack",
            height=430,
            margin=dict(l=0, r=0, t=12, b=105),
            paper_bgcolor=CARD,
            plot_bgcolor=CARD,
            font=dict(color=TEXT, size=12),
            legend=dict(orientation="h", y=-0.32),
            xaxis=dict(showgrid=False, tickangle=-30),
            yaxis=dict(gridcolor=GRID, title="Active public postings"),
        )
        st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})

    summary = latest.rename(
        columns={
            "company_name": "Company",
            "company_segment": "Segment",
            "active_requisitions": "Active requisitions",
            "active_postings": "Public postings",
            "ai_role_postings": "AI / ML-titled",
            "ai_role_share_pct": "AI / ML-titled share",
            "source_status": "Source health",
        }
    )
    mature = latest["same_store_28d"].fillna(False).astype(bool)
    summary["New · 28d"] = latest["new_postings_28d"].where(mature)
    summary["Closed · 28d"] = latest["closed_postings_28d"].where(mature)
    st.dataframe(
        dataframe_for_display(
            summary[
                [
                    "Company", "Segment", "Active requisitions", "Public postings", "AI / ML-titled",
                    "AI / ML-titled share", "New · 28d", "Closed · 28d", "Source health",
                ]
            ]
        ),
        width="stretch",
        hide_index=True,
        column_config={
            "AI / ML-titled share": st.column_config.NumberColumn("AI / ML-titled share", format="%.1f%%"),
            "New · 28d": st.column_config.NumberColumn("New · 28d", format="%d"),
            "Closed · 28d": st.column_config.NumberColumn("Closed · 28d", format="%d"),
        },
    )
    st.caption("28-day flows remain blank until a company has 28 days of healthy same-store coverage.")


def _render_job_explorer(jobs: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Public Job Explorer</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Current public postings from the tracked company boards. “AI / ML-titled” is a conservative deterministic title/team classification, not a claim that other roles do not support AI work.</div>',
        unsafe_allow_html=True,
    )
    if jobs.empty:
        st.info("No public job rows are available yet.")
        return
    active = jobs[jobs["status"] == "active"].copy()
    companies = sorted(active["company_name"].dropna().astype(str).unique())
    roles = sorted(active["role_family"].dropna().astype(str).unique())
    company_col, role_col, ai_col = st.columns([2, 1.4, 1], vertical_alignment="bottom")
    with company_col:
        selected_companies = st.multiselect(
            "Companies", companies, default=companies, key="ai_hiring_job_companies"
        )
    with role_col:
        selected_role = st.selectbox("Role family", ("All roles", *roles), key="ai_hiring_job_role")
    with ai_col:
        ai_only = st.toggle("AI / ML-titled only", value=False, key="ai_hiring_job_ai_only")
    keyword = st.text_input("Title keyword", placeholder="e.g. inference, policy, sales", key="ai_hiring_job_keyword")

    scoped = active[active["company_name"].isin(selected_companies)]
    if selected_role != "All roles":
        scoped = scoped[scoped["role_family"].astype(str) == selected_role]
    if ai_only:
        scoped = scoped[scoped["is_ai_role"]]
    if keyword.strip():
        scoped = scoped[scoped["title"].astype(str).str.contains(keyword.strip(), case=False, regex=False, na=False)]
    scoped = scoped.sort_values(["published_at", "company_name"], ascending=[False, True], na_position="last")
    st.caption(f"{len(scoped):,} matching active public postings")
    table = scoped.rename(
        columns={
            "company_name": "Company",
            "title": "Title",
            "role_family": "Role family",
            "location_raw": "Location",
            "workplace_type": "Workplace",
            "published_at": "Published",
            "job_url": "Job page",
        }
    )[["Company", "Title", "Role family", "Location", "Workplace", "Published", "Job page"]]
    st.dataframe(
        dataframe_for_display(table),
        width="stretch",
        height=520,
        hide_index=True,
        column_config={
            "Published": st.column_config.DatetimeColumn("Published", format="YYYY-MM-DD"),
            "Job page": st.column_config.LinkColumn("Job page", display_text="Open role"),
        },
    )


def _render_coverage(health: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Coverage & Definitions</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Company counts come from a fixed, versioned cohort of official public ATS boards. Board health is shown so a source outage is not mistaken for a hiring contraction.</div>',
        unsafe_allow_html=True,
    )
    if health.empty:
        st.warning("Source-health data is not available yet.")
        return
    coverage = pd.DataFrame(
        {
            "Source": health["company_name"].fillna("Indeed Hiring Lab"),
            "Type": health["source_kind"].map({"job_board": "Company job board", "macro_csv": "Macro series"}).fillna(health["source_kind"]),
            "Collection": health["status"].str.title(),
            "Rows": health["row_count"],
            "Response (ms)": health["response_ms"],
            "Collected": health["scraped_at"],
            "Official source": health["source_url"],
            "Detail": health["detail"],
        }
    ).sort_values(["Type", "Source"])
    st.dataframe(
        dataframe_for_display(coverage),
        width="stretch",
        hide_index=True,
        column_config={
            "Collected": st.column_config.DatetimeColumn("Collected", format="YYYY-MM-DD HH:mm"),
            "Official source": st.column_config.LinkColumn("Official source", display_text="Open source"),
        },
    )
    st.caption(
        "Active postings are public URLs; active requisitions deduplicate location variants where the ATS exposes a requisition identity. A posting must disappear on two consecutive successful collections before it is marked closed. Failed or collapsed sources preserve their last-good job state."
    )


def render(domain_states, datasets: dict[str, DatasetLoadResult]) -> None:
    _ = domain_states
    st.markdown('<div class="section-title" style="margin-top:0.25rem;">AI Hiring Demand</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Economy-wide AI posting share plus daily public job-board demand from a fixed cohort of 10 AI companies. These are demand signals—not hires, headcount, or vacancies filled.</div>',
        unsafe_allow_html=True,
    )
    frames = _prepare(datasets)
    indeed = frames["indeed"]
    demand = frames["demand"]
    jobs = frames["jobs"]
    health = frames["health"]
    if indeed.empty and demand.empty and jobs.empty:
        st.info("Run the AI hiring pipeline to populate the macro series and company job-board tracker.")
        _render_coverage(health)
        return

    _render_kpis(indeed, demand, health)
    _render_indeed(indeed)
    st.markdown('<div class="section-title">AI Company Hiring Demand</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Daily public openings at AI-native companies. Company totals include every public role; the role mix and AI / ML-title fields are analytical classifications shown separately.</div>',
        unsafe_allow_html=True,
    )
    if demand.empty:
        st.info("No company demand snapshots are available yet.")
    else:
        _render_company_history(demand)
        _render_company_snapshot(demand)
    _render_job_explorer(jobs)
    _render_coverage(health)
