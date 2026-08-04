from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import dataframe_for_display, format_metric, kpi_card_html, kpi_grid_html
from dashboard.data import DatasetLoadResult
from dashboard.theme import CARD, GRID, MODEL_COLORS, MUTED, TEXT


CATALOG_ID = "replicate_model_catalog"
COLLECTIONS_ID = "replicate_collections_summary"


def _frame(datasets: dict[str, DatasetLoadResult], dataset_id: str) -> pd.DataFrame:
    result = datasets.get(dataset_id)
    return result.frame.copy() if result is not None and not result.frame.empty else pd.DataFrame()


def _prepare(datasets: dict[str, DatasetLoadResult]) -> dict[str, pd.DataFrame]:
    """Return full history (all snapshot_dates), typed but not filtered to latest.

    Callers that only want the current state should filter with
    ``_latest_snapshot``; the day-over-day delta view needs the full history.
    """
    catalog = _frame(datasets, CATALOG_ID)
    collections = _frame(datasets, COLLECTIONS_ID)

    if not catalog.empty:
        catalog["run_count"] = pd.to_numeric(catalog["run_count"], errors="coerce").fillna(0)
        catalog["is_official"] = catalog["is_official"].fillna(False).astype(bool)
    if not collections.empty:
        collections["total_models"] = pd.to_numeric(collections["total_models"], errors="coerce").fillna(0)

    return {"catalog": catalog, "collections": collections}


def _latest_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    latest_date = frame["snapshot_date"].max()
    return frame[frame["snapshot_date"] == latest_date]


def compute_run_count_deltas(catalog: pd.DataFrame) -> dict[str, object]:
    """Day-over-day run_count change, comparing the two most recent distinct snapshots.

    run_count is Replicate's own cumulative all-time counter, so the delta
    between two daily snapshots is a real, meaningful "how much did this model
    grow" signal -- but only for models present in *both* snapshots. Models
    that only appear in one side (newly added to our crawl, or dropped out of
    it) are excluded from the delta table and reported as counts instead,
    since a delta against a missing prior value would be fabricated, not
    computed. Deltas are never clamped at zero: a negative value is surfaced
    as-is (most likely a model rename/slug change or a counter recalibration
    on Replicate's side), since silently hiding it would be less accurate,
    not more.
    """
    if catalog.empty:
        return {"available": False, "reason": "no_data"}

    distinct_dates = sorted(catalog["snapshot_date"].dropna().unique())
    if len(distinct_dates) < 2:
        return {"available": False, "reason": "single_snapshot", "snapshot_date": distinct_dates[-1] if distinct_dates else None}

    latest_date, previous_date = distinct_dates[-1], distinct_dates[-2]
    # Multiple runs on the same calendar date upsert to one row per
    # (snapshot_date, slug) already (see storage.py NATURAL_KEYS), but guard
    # defensively against any duplicate slug within a single date rather than
    # let a join silently fan out.
    latest = catalog[catalog["snapshot_date"] == latest_date].drop_duplicates(subset="slug", keep="last")
    previous = catalog[catalog["snapshot_date"] == previous_date].drop_duplicates(subset="slug", keep="last")

    latest_slugs = set(latest["slug"])
    previous_slugs = set(previous["slug"])
    new_count = len(latest_slugs - previous_slugs)
    removed_count = len(previous_slugs - latest_slugs)

    merged = latest.merge(
        previous[["slug", "run_count"]].rename(columns={"run_count": "run_count_previous"}),
        on="slug", how="inner",
    )
    merged["delta"] = merged["run_count"] - merged["run_count_previous"]
    merged["pct_delta"] = merged["delta"] / merged["run_count_previous"].replace(0, pd.NA)

    return {
        "available": True,
        "latest_date": latest_date,
        "previous_date": previous_date,
        "deltas": merged,
        "new_count": new_count,
        "removed_count": removed_count,
    }


def _render_kpis(catalog: pd.DataFrame, collections: pd.DataFrame) -> None:
    total_models = len(catalog)
    total_collections = len(collections)
    top_model = "—"
    top_model_runs = None
    if not catalog.empty:
        top_row = catalog.sort_values("run_count", ascending=False).iloc[0]
        top_model = str(top_row["slug"])
        top_model_runs = float(top_row["run_count"])
    top_collection = "—"
    if not collections.empty:
        top_collection = str(collections.sort_values("total_models", ascending=False).iloc[0]["collection_slug"])
    latest_date = str(catalog["snapshot_date"].iloc[0]) if not catalog.empty else "—"

    st.markdown(
        kpi_grid_html(
            kpi_card_html("Tracked Models", format_metric(total_models), delta=f"snapshot {latest_date}"),
            kpi_card_html("Collections", format_metric(total_collections), delta="hosted model categories"),
            kpi_card_html(
                "Top Model by Runs", top_model,
                delta=f"{format_metric(top_model_runs)} cumulative runs" if top_model_runs is not None else "—",
            ),
            kpi_card_html("Largest Collection", top_collection, delta="by hosted model count"),
        ),
        unsafe_allow_html=True,
    )


def _render_collections(collections: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Collections by Hosted Model Count</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Number of models Replicate hosts in each collection, latest snapshot.</div>',
        unsafe_allow_html=True,
    )
    if collections.empty:
        st.info("No collections snapshot is available yet.")
        return
    scoped = collections.sort_values("total_models", ascending=False).head(15)
    scoped = scoped.sort_values("total_models", ascending=True)
    figure = go.Figure(go.Bar(
        x=scoped["total_models"], y=scoped["collection_slug"], orientation="h",
        marker_color=MODEL_COLORS[1],
        text=scoped["total_models"], texttemplate="%{text:.0f}", textposition="outside", cliponaxis=False,
        hovertemplate="%{y}<br><b>%{x:.0f}</b> models<extra></extra>",
    ))
    figure.update_layout(
        template="plotly_white", height=max(320, 28 * len(scoped)), margin=dict(l=0, r=30, t=12, b=30),
        paper_bgcolor=CARD, plot_bgcolor=CARD, font=dict(color=TEXT, size=12),
        xaxis=dict(gridcolor=GRID, title="Hosted models"), yaxis=dict(showgrid=False),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def _render_top_models(catalog: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Top Models by Cumulative Runs</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Most-executed hosted models across all of Replicate, latest snapshot.</div>',
        unsafe_allow_html=True,
    )
    if catalog.empty:
        st.info("No model catalog snapshot is available yet.")
        return
    scoped = catalog.sort_values("run_count", ascending=False).head(20)
    scoped = scoped.sort_values("run_count", ascending=True)
    figure = go.Figure(go.Bar(
        x=scoped["run_count"], y=scoped["slug"], orientation="h",
        marker_color=MODEL_COLORS[3],
        hovertemplate="%{y}<br><b>%{x:,.0f}</b> runs<extra></extra>",
    ))
    figure.update_layout(
        template="plotly_white", height=max(420, 24 * len(scoped)), margin=dict(l=0, r=30, t=12, b=30),
        paper_bgcolor=CARD, plot_bgcolor=CARD, font=dict(color=TEXT, size=11),
        xaxis=dict(gridcolor=GRID, title="Cumulative runs", type="log"), yaxis=dict(showgrid=False),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    st.caption("Run-count axis is log-scaled: a handful of models dominate total execution volume.")


def _render_catalog_table(catalog: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Model Catalog Explorer</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Every tracked model, filterable by collection and sorted by execution volume.</div>',
        unsafe_allow_html=True,
    )
    if catalog.empty:
        st.info("No model catalog snapshot is available yet.")
        return
    collections = sorted(catalog["collection"].dropna().astype(str).unique())
    selected = st.multiselect("Collections", collections, default=[], key="replicate_catalog_collections")
    scoped = catalog[catalog["collection"].isin(selected)] if selected else catalog
    scoped = scoped.sort_values("run_count", ascending=False)
    table = scoped.rename(
        columns={
            "slug": "Model", "owner": "Owner", "collection": "Collection", "run_count": "Runs",
            "hardware": "Hardware", "price": "Price", "is_official": "Official",
        }
    )[["Model", "Owner", "Collection", "Runs", "Hardware", "Price", "Official"]]
    st.caption(f"{len(table):,} models" + (f" across {len(selected)} selected collection(s)" if selected else ""))
    st.dataframe(
        dataframe_for_display(table),
        width="stretch", hide_index=True, height=460,
        column_config={"Runs": st.column_config.NumberColumn("Runs", format="%d")},
    )


def _render_trending(catalog: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Trending: Day-over-Day Run Growth</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Change in cumulative run_count between the two most recent daily snapshots -- the closest thing to an "over time" view until more history accumulates.</div>',
        unsafe_allow_html=True,
    )
    result = compute_run_count_deltas(catalog)
    if not result["available"]:
        if result["reason"] == "no_data":
            st.info("No model catalog snapshot is available yet.")
        else:
            st.info(
                f"Only one daily snapshot exists so far ({result['snapshot_date']}). "
                "Day-over-day growth will appear automatically once a second day's scrape lands."
            )
        return

    deltas = result["deltas"].copy()
    # compute_run_count_deltas returns pct_delta as a fraction (0.5 == 50%,
    # matching this repo's adoption_rate convention); the column format
    # string below just appends "%" to the raw number rather than scaling
    # it, so multiply here at the display layer only.
    deltas["pct_delta"] = deltas["pct_delta"] * 100
    table = deltas.rename(
        columns={
            "slug": "Model", "owner": "Owner", "collection": "Collection",
            "run_count": "Runs (latest)", "delta": "Δ Runs", "pct_delta": "Δ %",
        }
    )[["Model", "Owner", "Collection", "Runs (latest)", "Δ Runs", "Δ %"]].sort_values("Δ Runs", ascending=False)
    st.dataframe(
        dataframe_for_display(table),
        width="stretch", hide_index=True, height=420,
        column_config={
            "Runs (latest)": st.column_config.NumberColumn("Runs (latest)", format="%d"),
            "Δ Runs": st.column_config.NumberColumn("Δ Runs", format="%+d"),
            "Δ %": st.column_config.NumberColumn("Δ %", format="%+.1f%%"),
        },
    )
    caveats = []
    if result["new_count"]:
        caveats.append(f"{result['new_count']} model(s) newly appeared and have no prior-day value to compare against")
    if result["removed_count"]:
        caveats.append(f"{result['removed_count']} model(s) from the prior snapshot no longer appear")
    caveat_text = f" {'; '.join(caveats)}, so they're excluded from this table." if caveats else ""
    st.caption(
        f"Comparing {result['previous_date']} → {result['latest_date']}, {len(table):,} models present in both snapshots.{caveat_text} "
        "A negative Δ most likely reflects a model rename/slug change rather than an actual usage decline, since run_count is a cumulative counter."
    )


def render(domain_states, datasets: dict[str, DatasetLoadResult]) -> None:
    _ = domain_states
    st.markdown('<div class="section-title" style="margin-top:0.25rem;">Replicate Multimodal AI</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Hosted model catalog and execution volume across image, video, audio, speech, vision, and language models on Replicate.</div>',
        unsafe_allow_html=True,
    )
    frames = _prepare(datasets)
    catalog_full = frames["catalog"]
    collections_full = frames["collections"]
    catalog = _latest_snapshot(catalog_full)
    collections = _latest_snapshot(collections_full)

    if catalog.empty and collections.empty:
        st.info("Run the Replicate scrape pipeline to populate this page.")
        return

    _render_kpis(catalog, collections)
    _render_trending(catalog_full)
    _render_collections(collections)
    _render_top_models(catalog)
    _render_catalog_table(catalog)
    st.caption("Source: replicate.com (unofficial catalog scrape) · refreshed daily. History accumulates day over day; trend views will follow once enough daily snapshots exist.")
