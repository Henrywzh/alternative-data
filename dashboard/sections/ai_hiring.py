from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import dataframe_for_display, format_metric, kpi_card_html, kpi_grid_html
from dashboard.data import DatasetLoadResult
from dashboard.theme import CARD, GRID, MODEL_COLORS, MUTED, TEXT
from ai_hiring_data.classify import CLASSIFIER_VERSION, classify_seniority
from ai_hiring_data.analytics import (
    SENIORITY_LEVELS,
    build_company_intensity,
    build_early_cohort_trend,
    build_role_seniority_matrix,
    build_seniority_totals,
)
from ai_hiring_data.segments import PARENT_SEGMENTS, PARENT_SEGMENT_BY_COMPANY


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
        # Migrate older normalized snapshots at read time so a deployed
        # dashboard cannot silently render zeroes for the new seniority
        # columns while the next pipeline backfill is pending.
        if "title" in jobs.columns:
            versions = jobs.get("classifier_version", pd.Series(index=jobs.index, dtype="string")).astype("string")
            if not versions.eq(CLASSIFIER_VERSION).all():
                jobs["seniority"] = jobs["title"].map(classify_seniority)
                jobs["classifier_version"] = CLASSIFIER_VERSION
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
                delta=f"{format_metric(active_postings)} public postings · 70-company fixed cohort",
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
        '<div class="section-subtitle">Indeed Hiring Lab macro series — share of public Indeed job postings that mention AI. Daily observations, refreshed monthly; this is posting demand, not hires or employment.</div>',
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
        f"Source: Indeed Hiring Lab public AI tracker CSV · latest observation {latest_source_date:%Y-%m-%d} · refreshed monthly · CC BY 4.0. The 28-day view is display-only; daily source rows remain available via the selector. This series is separate from the company ATS tracker below."
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


def _render_company_footprint(demand: pd.DataFrame) -> None:
    """Show current company scale with an explicit display-only parent grouping."""

    latest, latest_date = _company_snapshot(demand)
    if latest.empty:
        st.info("No company demand snapshot is available yet.")
        return
    latest = latest.copy()
    latest["Parent segment"] = latest["company_id"].map(PARENT_SEGMENT_BY_COMPANY).fillna("Unmapped")
    latest["AI / ML share"] = latest["ai_role_share_pct"].fillna(0)
    metric_options = {
        "Active requisitions": "active_requisitions",
        "Public postings": "active_postings",
        "AI / ML-titled roles": "ai_role_postings",
    }
    controls = st.columns([1.2, 2.2], vertical_alignment="bottom")
    with controls[0]:
        metric_label = st.selectbox("Footprint metric", tuple(metric_options), key="ai_hiring_footprint_metric")
    with controls[1]:
        selected_segments = st.multiselect(
            "Parent segment",
            list(PARENT_SEGMENTS),
            default=list(PARENT_SEGMENTS),
            key="ai_hiring_parent_segments",
        )
    scoped = latest[latest["Parent segment"].isin(selected_segments)].copy()
    if scoped.empty:
        st.info("Select at least one parent segment.")
        return
    metric = metric_options[metric_label]
    company_rows = scoped.sort_values(metric, ascending=True)
    display = pd.DataFrame(
        {
            "Company": company_rows["company_name"].astype(str),
            "Parent segment": company_rows["Parent segment"].astype(str),
            "Source segment": company_rows["company_segment"].astype(str),
            "Selected metric": company_rows[metric],
            "Active requisitions": company_rows["active_requisitions"],
            "Public postings": company_rows["active_postings"],
            "AI / ML-titled": company_rows["ai_role_postings"],
            "AI / ML share": company_rows["AI / ML share"],
        }
    )
    # Keep this defensive guard because older cached Streamlit sessions can
    # otherwise retain a pre-refactor duplicate metric column.
    display = display.loc[:, ~display.columns.duplicated()]
    st.dataframe(
        dataframe_for_display(display),
        width="stretch", height=410, hide_index=True,
        column_config={
            "Selected metric": st.column_config.NumberColumn(f"Selected · {metric_label}", format="%d"),
            "AI / ML share": st.column_config.NumberColumn("AI / ML share", format="%.1f%%"),
        },
    )
    st.caption(f"Latest public ATS snapshot · {latest_date:%Y-%m-%d}. Ranked by {metric_label.lower()}; parent segments are display-only rollups and the source segment remains available.")


def _render_hiring_intensity(demand: pd.DataFrame) -> None:
    """Compare company scale with AI-role concentration using observed latest rows."""

    intensity = build_company_intensity(demand, PARENT_SEGMENT_BY_COMPANY)
    st.markdown('<div class="section-title">Hiring intensity</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Company scale versus AI-role concentration. Bubble area represents active public postings; positions are the latest observed board snapshot.</div>',
        unsafe_allow_html=True,
    )
    if intensity.empty:
        st.info("No latest company snapshot is available for the intensity view.")
        return
    colors = {segment: MODEL_COLORS[index % len(MODEL_COLORS)] for index, segment in enumerate(PARENT_SEGMENTS)}
    figure = go.Figure()
    for segment in (*PARENT_SEGMENTS, "Unmapped"):
        rows = intensity[intensity["parent_segment"].eq(segment)]
        if rows.empty:
            continue
        sizes = (rows["active_postings"].clip(lower=1).pow(0.5) * 3.2).clip(lower=7, upper=42)
        figure.add_trace(
            go.Scatter(
                x=rows["active_requisitions"], y=rows["ai_role_share_pct"], mode="markers+text",
                name=segment, marker=dict(size=sizes, color=colors.get(segment, MUTED), opacity=0.78, line=dict(color=CARD, width=1)),
                text=rows["company_name"], textposition="top center", textfont=dict(size=9, color=TEXT), cliponaxis=False,
                customdata=rows[["active_postings", "ai_role_postings"]],
                hovertemplate=("<b>%{text}</b><br>%{x:,.0f} active requisitions<br>"
                               "%{y:.1f}% AI / ML-titled<br>%{customdata[0]:,.0f} public postings<extra>%{fullData.name}</extra>"),
            )
        )
    figure.update_layout(
        template="plotly_white", height=470, margin=dict(l=0, r=0, t=12, b=55),
        paper_bgcolor=CARD, plot_bgcolor=CARD, font=dict(color=TEXT, size=12),
        xaxis=dict(gridcolor=GRID, title="Active requisitions", zeroline=False),
        yaxis=dict(gridcolor=GRID, title="AI / ML-titled share", ticksuffix="%", zeroline=False),
        legend=dict(orientation="h", y=-0.18), hovermode="closest",
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    st.caption("This is a cross-sectional comparison, not a hiring-growth forecast. A high AI-role share can reflect a smaller company with a specialized board.")


def _render_early_cohort_trend(demand: pd.DataFrame) -> None:
    trend = build_early_cohort_trend(demand, min_observations=2)
    st.markdown('<div class="section-title">Early-cohort trend</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Observed history for the original companies with repeated successful snapshots. Newer boards are deliberately excluded until their time series matures.</div>',
        unsafe_allow_html=True,
    )
    if trend.empty or trend["company_count"].max() < 2:
        st.info("The repeated-observation cohort is not mature enough for a trend yet.")
        return
    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=trend["snapshot_date"], y=trend["active_requisitions"], mode="lines+markers",
        name="Active requisitions", line=dict(color=MODEL_COLORS[0], width=2.5),
        hovertemplate="%{x|%b %d, %Y}<br><b>%{y:,.0f}</b> active requisitions<extra></extra>",
    ))
    figure.add_trace(go.Scatter(
        x=trend["snapshot_date"], y=trend["active_postings"], mode="lines+markers",
        name="Public postings", line=dict(color=MODEL_COLORS[2], width=2),
        hovertemplate="%{x|%b %d, %Y}<br><b>%{y:,.0f}</b> public postings<extra></extra>",
    ))
    figure.update_layout(
        template="plotly_white", height=330, margin=dict(l=0, r=0, t=12, b=58),
        paper_bgcolor=CARD, plot_bgcolor=CARD, font=dict(color=TEXT, size=12),
        xaxis=dict(showgrid=False, title="Snapshot date"), yaxis=dict(gridcolor=GRID, title="Observed roles"),
        legend=dict(orientation="h", y=-0.2), hovermode="x unified",
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    st.caption(f"{int(trend['company_count'].min())}–{int(trend['company_count'].max())} companies contribute to each observed date. The 28-day same-store trend will remain unavailable until the cohort has 28 days of healthy coverage.")


def _render_role_seniority(jobs: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Where the demand concentrates</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Current active requisitions by role family and production seniority taxonomy. This uses the live job rows, not a synthetic allocation.</div>',
        unsafe_allow_html=True,
    )
    mode = st.radio("Heatmap display", ("Raw count", "% within role family"), horizontal=True, key="ai_hiring_heatmap_mode")
    matrix = build_role_seniority_matrix(jobs, mode="share" if mode.startswith("%") else "count")
    raw_matrix = build_role_seniority_matrix(jobs, mode="count")
    if matrix.empty or float(raw_matrix.to_numpy().sum()) == 0:
        st.info("No active job rows are available for the role/seniority mix yet.")
        return
    heat_col, total_col = st.columns([1.75, 1], gap="large")
    with heat_col:
        text = matrix.round(1).astype(str).map(lambda value: value.rstrip("0").rstrip(".") if "." in value else value)
        figure = go.Figure(go.Heatmap(
            z=matrix.to_numpy(), x=list(matrix.columns), y=list(matrix.index),
            colorscale="Blues", colorbar=dict(title="%" if mode.startswith("%") else "Roles"),
            text=text.to_numpy(), texttemplate="%{text}", hovertemplate="%{y}<br>%{x}: <b>%{z:.1f}</b><extra></extra>",
        ))
        figure.update_layout(
            template="plotly_white", height=490, margin=dict(l=0, r=0, t=12, b=75),
            paper_bgcolor=CARD, plot_bgcolor=CARD, font=dict(color=TEXT, size=11),
            xaxis=dict(side="bottom", tickangle=-18), yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    with total_col:
        totals = build_seniority_totals(raw_matrix)
        figure = go.Figure(go.Bar(
            x=totals["active_postings"], y=totals["seniority"], orientation="h",
            marker_color=MODEL_COLORS[3],
            text=totals["active_postings"], texttemplate="%{text:,.0f}", textposition="outside", cliponaxis=False,
            hovertemplate="%{y}<br><b>%{x:,.0f}</b> active postings<extra></extra>",
        ))
        figure.update_layout(
            template="plotly_white", height=490, margin=dict(l=0, r=0, t=12, b=45),
            paper_bgcolor=CARD, plot_bgcolor=CARD, font=dict(color=TEXT, size=11),
            xaxis=dict(gridcolor=GRID, title="Active postings"), yaxis=dict(showgrid=False),
        )
        st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
        st.caption("Seniority is inferred from job titles: explicit IC roles are separated from titles with no seniority signal, while senior/staff/principal and manager/director/executive markers are grouped. Exact titles remain available in the explorer below.")


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
        '<div class="section-subtitle">Economy-wide AI posting share plus daily public job-board demand from a fixed cohort of 70 tech & AI companies. These are demand signals—not hires, headcount, or vacancies filled.</div>',
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
        '<div class="section-subtitle">Daily public openings at a fixed cohort of 70 companies. Company totals include every public role; parent segments are display-only rollups and the source segment remains visible below.</div>',
        unsafe_allow_html=True,
    )
    if demand.empty:
        st.info("No company demand snapshots are available yet.")
    else:
        _render_company_footprint(demand)
        _render_hiring_intensity(demand)
        _render_early_cohort_trend(demand)
        _render_role_seniority(jobs)
        st.info(
            "Data sources: the economy-wide signal above is Indeed Hiring Lab's public GitHub CSV; company demand is collected from official public Ashby and Greenhouse boards. Company means the hiring company, not a model-serving provider. Latest board snapshots may be partial while a run is in progress."
        )
    _render_job_explorer(jobs)
    _render_coverage(health)
