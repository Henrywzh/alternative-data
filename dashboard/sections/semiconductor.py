from __future__ import annotations

import hmac
import inspect
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from dashboard import remote
from dashboard.checks import CheckResult, run_checks
from dashboard.data import (
    LazyDatasetMap,DOMAIN_ORDER, DATASET_REGISTRY, DatasetLoadResult, FreshnessInfo, dataset_source_for_domain, domain_dataset_ids, load_domain_datasets, load_latest_manifest, repo_root)
from openrouter_revenue import (build_price_context, build_conservative_provider_economics, estimate_usage_revenue, summarize_economics_coverage)
from semiconductor_memory_data.sources.config import AI_DEMAND_PPI_WEIGHTS
from dashboard.theme import (ACCENT, BG, SIDEBAR, CARD, BORDER, TEXT, MUTED, GREEN, RED, YELLOW, GRID, TICK, MODEL_COLORS)
from dashboard.components import (format_metric, _empty_dataset_frame, _styler_applymap_compat, WEEKLY_MONTHLY_OTHER_PROVIDERS, DAILY_OTHER_PROVIDERS, US_PROVIDER_ORDER, CHINA_PROVIDER_ORDER, order_provider_columns, regroup_provider_pivot_for_display, render_dataset_guard, format_scraped_at_display, dataframe_for_display, make_stacked_bar, make_stacked_area_chart, make_line_chart, kpi_card_html, kpi_grid_html, _top_n_with_others)


AI_DEMAND_PPI_COMPONENT_COLUMNS = {
    "PCU33443344": "ppi_component_pcu33443344_rebased",
    "PCU33423342": "ppi_component_pcu33423342_rebased",
    "PCU335313335313": "ppi_component_pcu335313335313_rebased",
    "PCU334111334111": "ppi_component_pcu334111334111_rebased",
    "PCU3341123341121": "ppi_component_pcu3341123341121_rebased",
}


AI_DEMAND_PPI_LABELS = {
    "PCU33443344": "Semiconductors and Other Electronic Components",
    "PCU33423342": "Communications Equipment",
    "PCU334111334111": "Electronic Computers and Servers",
    "PCU3341123341121": "Storage Devices",
    "PCU335313335313": "Switchgear and Power Distribution Equipment",
}


PRIVATE_PANEL_ACCESS_KEY = "PRIVATE_PANEL_ACCESS_CODE"


def _private_panel_expected_code(secrets: object, environ: dict[str, str]) -> str:
    try:
        secret_value = secrets.get(PRIVATE_PANEL_ACCESS_KEY, "") if secrets is not None else ""
    except Exception:
        secret_value = ""
    return str(secret_value or environ.get(PRIVATE_PANEL_ACCESS_KEY, "") or "")


def _private_panel_code_matches(submitted_code: str, expected_code: str) -> bool:
    submitted = str(submitted_code or "")
    expected = str(expected_code or "")
    return bool(submitted and expected and hmac.compare_digest(submitted, expected))


def _render_private_panel_gate() -> bool:
    if st.session_state.get("private_panel_unlocked"):
        return True

    expected_code = _private_panel_expected_code(st.secrets, os.environ)
    st.markdown('<div class="section-title">TODO</div>', unsafe_allow_html=True)
    if not expected_code:
        st.info("Private view is not configured for this environment.")
        return False

    submitted_code = st.text_input("Access code", type="password", key="private_panel_access_code")
    unlock_clicked = st.button("Unlock", key="private_panel_unlock")
    if unlock_clicked and _private_panel_code_matches(submitted_code, expected_code):
        st.session_state["private_panel_unlocked"] = True
        st.rerun()
    elif unlock_clicked:
        st.error("Access denied.")
    return False


@st.cache_data(ttl=3600, max_entries=8, hash_funcs={LazyDatasetMap: lambda mapping: mapping.cache_key})
def compute_semiconductor_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    views: dict[str, object] = {}

    regime_result = datasets.get("semiconductor_memory_regime_monthly")
    fred_result = datasets.get("fred_semiconductor_ppi")
    ppi_result = datasets.get("fred_semiconductor_ppi_monthly")
    regime_df = regime_result.frame.copy() if regime_result and not regime_result.frame.empty else pd.DataFrame()
    fred_df = fred_result.frame.copy() if fred_result and not fred_result.frame.empty else pd.DataFrame()

    # The PPI panel reads a dedicated FRED-only table so a failure of the ADATA
    # scraper (which shares the regime table) can no longer blank out the PPI
    # signal. Fall back to the regime table's PPI columns during the transition,
    # before the new table has been backfilled.
    ppi_df = ppi_result.frame.copy() if ppi_result and not ppi_result.frame.empty else pd.DataFrame()
    if ppi_df.empty and not regime_df.empty:
        ppi_df = regime_df.dropna(subset=["fred_ppi_value"]).copy()

    if not regime_df.empty:
        regime_df["month"] = regime_df["month"].astype(str)
        regime_df = regime_df.sort_values("month")
        latest_month = regime_df["month"].max()
        latest_data = regime_df[regime_df["month"] == latest_month].iloc[0]
    else:
        latest_month = None
        latest_data = pd.Series(dtype="object")

    if not ppi_df.empty:
        ppi_df["month"] = ppi_df["month"].astype(str)
        ppi_df = ppi_df.sort_values("month")
        proxy_df = ppi_df.dropna(subset=["fred_ppi_value"]).copy()
        component_columns = [
            column for column in AI_DEMAND_PPI_COMPONENT_COLUMNS.values()
            if column in ppi_df.columns
        ]
        if component_columns:
            base_candidates = ppi_df.dropna(subset=["fred_ppi_value", *component_columns]).copy()
        else:
            base_candidates = proxy_df
        base_month = base_candidates["month"].iloc[0] if not base_candidates.empty else None
        latest_proxy_month = proxy_df["month"].max() if not proxy_df.empty else None
        latest_proxy_data = (
            proxy_df[proxy_df["month"] == latest_proxy_month].iloc[0]
            if latest_proxy_month is not None and not proxy_df.empty
            else pd.Series(dtype="object")
        )
        # Partial-month metadata: a month missing one of the five basket
        # components (e.g. storage devices lagging) is still shown, but flagged
        # so it can never be mistaken for a complete observation.
        latest_proxy_coverage = None
        latest_proxy_missing = None
        if latest_proxy_month is not None and not proxy_df.empty:
            latest_proxy_coverage = latest_proxy_data.get("component_coverage")
            latest_proxy_missing = latest_proxy_data.get("missing_components")
            if pd.isna(latest_proxy_coverage) or latest_proxy_coverage in (None, ""):
                latest_proxy_coverage = None
            if pd.isna(latest_proxy_missing) or latest_proxy_missing in (None, ""):
                latest_proxy_missing = None
    else:
        proxy_df = pd.DataFrame()
        component_columns = []
        base_month = None
        latest_proxy_month = None
        latest_proxy_data = pd.Series(dtype="object")
        latest_proxy_coverage = None
        latest_proxy_missing = None

    latest_fred_month = None
    latest_fred_series_names: list[str] = []
    if not fred_df.empty:
        fred_df["date"] = pd.to_datetime(fred_df["date"], errors="coerce")
        fred_df = fred_df.dropna(subset=["date"]).copy()
        if not fred_df.empty:
            fred_df["month"] = fred_df["date"].dt.strftime("%Y-%m")
            latest_fred_month = fred_df["month"].max()
            latest_month_rows = fred_df[fred_df["month"] == latest_fred_month].copy()
            latest_fred_series_names = sorted(
                latest_month_rows["series_name"].fillna(latest_month_rows["series_id"]).astype(str).unique().tolist()
            )

    official_result = datasets.get("semiconductor_official_monthly")
    backup_result = datasets.get("semiconductor_backup_check_monthly")
    source_catalog_result = datasets.get("semiconductor_source_catalog")
    taiwan_revenue_result = datasets.get("tw_monthly_revenue")

    official_df = (
        official_result.frame.copy()
        if official_result and not official_result.frame.empty
        else _empty_dataset_frame("semiconductor_official_monthly")
    )
    backup_df = (
        backup_result.frame.copy()
        if backup_result and not backup_result.frame.empty
        else _empty_dataset_frame("semiconductor_backup_check_monthly")
    )
    source_catalog_df = (
        source_catalog_result.frame.copy()
        if source_catalog_result and not source_catalog_result.frame.empty
        else _empty_dataset_frame("semiconductor_source_catalog")
    )
    taiwan_revenue_df = (
        taiwan_revenue_result.frame.copy()
        if taiwan_revenue_result and not taiwan_revenue_result.frame.empty
        else pd.DataFrame()
    )
    trade_df = pd.DataFrame()
    production_df = pd.DataFrame()
    latest_official_period = None
    latest_backup_period = None
    if not official_df.empty:
        official_df["period"] = official_df["period"].astype(str)
        official_df = official_df.sort_values(["period", "source_region", "metric_type"]).reset_index(drop=True)
        trade_df = official_df[official_df["metric_type"].isin(["exports", "imports", "trade_balance"])].copy()
        production_df = official_df[official_df["metric_type"] == "production"].copy()
        latest_official_period = official_df["period"].max()
    if not backup_df.empty:
        backup_df["period"] = backup_df["period"].astype(str)
        backup_df = backup_df.sort_values(["period", "source_region", "metric_type"]).reset_index(drop=True)
        latest_backup_period = backup_df["period"].max()

    latest_taiwan_revenue_month = None
    latest_taiwan_revenue = pd.DataFrame()
    taiwan_revenue_pivot = pd.DataFrame()
    taiwan_yoy_pivot = pd.DataFrame()
    if not taiwan_revenue_df.empty:
        taiwan_revenue_df["revenue_month"] = taiwan_revenue_df["revenue_month"].astype(str)
        taiwan_revenue_df = taiwan_revenue_df.sort_values(["revenue_month", "company_code"]).reset_index(drop=True)
        latest_taiwan_revenue_month = taiwan_revenue_df["revenue_month"].max()
        latest_taiwan_revenue = (
            taiwan_revenue_df[taiwan_revenue_df["revenue_month"] == latest_taiwan_revenue_month]
            .sort_values("monthly_revenue_ntd", ascending=False)
            .reset_index(drop=True)
        )
        taiwan_revenue_pivot = (
            taiwan_revenue_df.pivot_table(
                index="revenue_month",
                columns="company_name",
                values="monthly_revenue_ntd",
                aggfunc="last",
            )
            .sort_index()
        )
        taiwan_yoy_pivot = (
            taiwan_revenue_df.pivot_table(
                index="revenue_month",
                columns="company_name",
                values="yoy_pct",
                aggfunc="last",
            )
            .sort_index()
        )

    views["regime_df"] = regime_df
    views["ppi_df"] = ppi_df
    views["latest_month"] = latest_month
    views["latest_data"] = latest_data
    views["proxy_df"] = proxy_df
    views["component_columns"] = component_columns
    views["base_month"] = base_month
    views["latest_proxy_month"] = latest_proxy_month
    views["latest_proxy_data"] = latest_proxy_data
    views["latest_proxy_coverage"] = latest_proxy_coverage
    views["latest_proxy_missing"] = latest_proxy_missing
    views["latest_fred_month"] = latest_fred_month
    views["latest_fred_series_names"] = latest_fred_series_names
    views["official_df"] = official_df
    views["backup_df"] = backup_df
    views["source_catalog_df"] = source_catalog_df
    views["trade_df"] = trade_df
    views["production_df"] = production_df
    views["latest_official_period"] = latest_official_period
    views["latest_backup_period"] = latest_backup_period
    views["taiwan_revenue_df"] = taiwan_revenue_df
    views["latest_taiwan_revenue_month"] = latest_taiwan_revenue_month
    views["latest_taiwan_revenue"] = latest_taiwan_revenue
    views["taiwan_revenue_pivot"] = taiwan_revenue_pivot
    views["taiwan_yoy_pivot"] = taiwan_yoy_pivot

    return views


def _official_trade_unit_config(unit: str) -> tuple[float, str]:
    normalized = str(unit or "").strip().lower()
    if normalized == "usd":
        return 1e9, "USD Billion"
    if normalized == "usd_thousand":
        return 1e6, "USD Billion"
    if normalized == "jpy_thousand":
        return 1e6, "JPY Billion"
    if normalized == "hkd_thousand":
        return 1e6, "HKD Billion"
    if normalized == "eur":
        return 1e9, "EUR Billion"
    return 1.0, normalized or "Native Unit"


@st.cache_data(ttl=86400, show_spinner=False, max_entries=8)
def _fetch_monthly_fx_to_usd(start_period: str, end_period: str) -> pd.DataFrame:
    start_date = (pd.Period(start_period, freq="M") - 1).to_timestamp(how="end").strftime("%Y-%m-%d")
    end_date = (pd.Period(end_period, freq="M") + 1).to_timestamp(how="end").strftime("%Y-%m-%d")
    symbol_map = {
        "JPY": ("USDJPY=X", lambda close: 1.0 / close),
        "HKD": ("USDHKD=X", lambda close: 1.0 / close),
        "EUR": ("EURUSD=X", lambda close: close),
    }
    rows: list[pd.DataFrame] = []
    for currency, (symbol, transform) in symbol_map.items():
        try:
            frame = yf.download(symbol, start=start_date, end=end_date, auto_adjust=False, progress=False)
        except Exception:
            continue
        if frame.empty:
            continue
        if isinstance(frame.columns, pd.MultiIndex):
            close = frame["Close"].iloc[:, 0]
        else:
            close = frame["Close"]
        month_end = close.resample("ME").last().dropna()
        if month_end.empty:
            continue
        fx_frame = pd.DataFrame({
            "period": month_end.index.to_period("M").strftime("%Y-%m"),
            "currency": currency,
            "fx_to_usd": month_end.map(transform).astype(float),
        })
        rows.append(fx_frame)
    if not rows:
        return pd.DataFrame(columns=["period", "currency", "fx_to_usd"])
    return pd.concat(rows, ignore_index=True)


def _prepare_official_trade_display(official_trade: pd.DataFrame, scale_mode: str) -> tuple[pd.DataFrame, str, bool]:
    if official_trade.empty:
        return pd.DataFrame(), "Native Unit", False

    chart_frame = official_trade.copy()
    if scale_mode == "USD Normalized (PT FX)":
        start_period = str(chart_frame["period"].min())
        end_period = str(chart_frame["period"].max())
        fx_df = _fetch_monthly_fx_to_usd(start_period, end_period)
        chart_frame["display_value"] = np.nan

        # Scale by the unit, not the currency. A USD series still has to say
        # whether it counts dollars or thousands of them, and keying off
        # currency alone silently plotted Korea's thousand-USD figures a
        # thousandfold too small next to Hong Kong and Japan.
        units = chart_frame["unit"].astype(str).str.strip().str.lower()
        currencies = chart_frame["currency"].astype(str).str.upper()
        usd_mask = (currencies == "USD") & (units != "usd_thousand")
        chart_frame.loc[usd_mask, "display_value"] = chart_frame.loc[usd_mask, "value"] / 1e9
        usd_thousand_mask = units == "usd_thousand"
        chart_frame.loc[usd_thousand_mask, "display_value"] = (
            chart_frame.loc[usd_thousand_mask, "value"] / 1e6
        )

        if not fx_df.empty:
            merged = chart_frame.merge(fx_df, on=["period", "currency"], how="left")
            local_mask_thousand = merged["currency"].astype(str).str.upper().isin(["JPY", "HKD"])
            merged.loc[local_mask_thousand, "display_value"] = (
                merged.loc[local_mask_thousand, "value"] * merged.loc[local_mask_thousand, "fx_to_usd"] / 1e6
            )
            local_mask_eur = merged["currency"].astype(str).str.upper() == "EUR"
            merged.loc[local_mask_eur, "display_value"] = (
                merged.loc[local_mask_eur, "value"] * merged.loc[local_mask_eur, "fx_to_usd"] / 1e9
            )
            chart_frame = merged

        has_complete_fx = chart_frame["display_value"].notna().all()
        chart_frame = chart_frame.dropna(subset=["display_value"]).copy()
        return chart_frame, "USD Billion", has_complete_fx

    chart_frame["display_value"] = chart_frame["value"]
    return chart_frame, "Native Unit", True


def _render_official_trade_chart(official_trade: pd.DataFrame, category_choice: str) -> None:
    if official_trade.empty:
        return

    for unit, unit_frame in official_trade.groupby("unit", dropna=False):
        scale, y_title = _official_trade_unit_config(str(unit))
        chart_frame = unit_frame.copy()
        chart_frame["display_value"] = chart_frame["value"] / scale
        official_pivot = chart_frame.pivot_table(
            index="period",
            columns="country_name",
            values="display_value",
            aggfunc="last",
        ).sort_index()
        unit_suffix = f" ({str(unit)})" if str(unit) else ""
        st.plotly_chart(
            make_line_chart(
                official_pivot,
                MODEL_COLORS[:len(official_pivot.columns)],
                title=f"Official {category_choice} Exports{unit_suffix}",
                y_title=y_title,
                x_title="Month",
                height=340,
                connect_gaps=True,
            ),
            width="stretch",
        )


def _render_trade_yoy_chart(chart_frame: pd.DataFrame, category_choice: str, title_prefix: str) -> None:
    if chart_frame.empty:
        return
    yoy_pivot = chart_frame.pivot_table(
        index="period",
        columns="country_name",
        values="display_value",
        aggfunc="last",
    ).sort_index()
    # Index by calendar month, not by row position: countries publish on
    # different schedules, so the twelfth row back is only the same month a
    # year earlier when every country happens to have reported every month.
    # And never pad -- pandas' deprecated default carried the previous month
    # forward, which invented a YoY point for a country that had not reported
    # yet. On the IC-only panel that drew Hong Kong at +57.75% and Japan at
    # +25.25% for 2026-07, a month neither had published: June's value over
    # July a year earlier. Both land in the range the real series occupies,
    # so nothing about the chart looks wrong.
    try:
        monthly_index = pd.PeriodIndex(yoy_pivot.index.astype(str), freq="M")
    except (TypeError, ValueError):
        monthly_index = None
    if monthly_index is not None:
        yoy_pivot = yoy_pivot.set_axis(monthly_index).reindex(
            pd.period_range(monthly_index.min(), monthly_index.max(), freq="M")
        )
    yoy_pivot = yoy_pivot.pct_change(12, fill_method=None) * 100.0
    if monthly_index is not None:
        yoy_pivot.index = yoy_pivot.index.strftime("%Y-%m")
    yoy_pivot = yoy_pivot.dropna(how="all")
    if yoy_pivot.empty:
        return
    st.plotly_chart(
        make_line_chart(
            yoy_pivot,
            MODEL_COLORS[:len(yoy_pivot.columns)],
            title=f"{title_prefix} {category_choice} Exports YoY",
            y_title="YoY %",
            x_title="Month",
            height=320,
            connect_gaps=True,
        ),
        width="stretch",
    )


def _render_private_company_revenue(semi_views: dict[str, object], cutoff_month: str | None) -> None:
    taiwan_revenue_df = semi_views.get("taiwan_revenue_df", pd.DataFrame())
    latest_taiwan_revenue_month = semi_views.get("latest_taiwan_revenue_month")
    latest_taiwan_revenue = semi_views.get("latest_taiwan_revenue", pd.DataFrame())
    taiwan_revenue_pivot = semi_views.get("taiwan_revenue_pivot", pd.DataFrame())
    taiwan_yoy_pivot = semi_views.get("taiwan_yoy_pivot", pd.DataFrame())

    if not taiwan_revenue_df.empty:
        min_date = cutoff_month
        if min_date:
            taiwan_revenue_df = taiwan_revenue_df[taiwan_revenue_df["revenue_month"] >= min_date].copy()
            taiwan_revenue_pivot = taiwan_revenue_pivot[taiwan_revenue_pivot.index >= min_date].copy()
            taiwan_yoy_pivot = taiwan_yoy_pivot[taiwan_yoy_pivot.index >= min_date].copy()

    if taiwan_revenue_df.empty:
        st.warning("No private company revenue data available.")
        return

    st.markdown('<div class="section-title">Company Revenue Tracker</div>', unsafe_allow_html=True)
    st.caption(
        "Authoritative monthly operating revenue disclosures for selected semiconductor companies. "
        "Figures are reported in thousands of New Taiwan dollars."
    )

    latest_snapshot = latest_taiwan_revenue.copy()
    if not latest_snapshot.empty:
        latest_snapshot["monthly_revenue_ntd_b"] = latest_snapshot["monthly_revenue_ntd"] / 1e6
        leader = latest_snapshot.iloc[0]
        avg_yoy = latest_snapshot["yoy_pct"].mean()
        avg_ytd = latest_snapshot["ytd_yoy_pct"].mean()
        st.markdown(
            kpi_grid_html(
                kpi_card_html("Latest Month", latest_taiwan_revenue_month or "—", delta=f"{len(latest_snapshot)} companies", delta_class="flat"),
                kpi_card_html("Top Reporter", str(leader.get("company_name", "—")), delta=f"NT${leader.get('monthly_revenue_ntd_b', 0):,.1f}B", delta_class="flat"),
                kpi_card_html("Average YoY", f"{avg_yoy:.1f}%" if pd.notna(avg_yoy) else "—", delta="latest month", delta_class="up" if pd.notna(avg_yoy) and avg_yoy >= 0 else "down"),
                kpi_card_html("Average YTD YoY", f"{avg_ytd:.1f}%" if pd.notna(avg_ytd) else "—", delta="latest month", delta_class="up" if pd.notna(avg_ytd) and avg_ytd >= 0 else "down"),
            ),
            unsafe_allow_html=True,
        )

        latest_display = latest_snapshot[
            ["company_code", "company_name", "market", "revenue_month", "monthly_revenue_ntd", "yoy_pct", "ytd_revenue_ntd", "ytd_yoy_pct"]
        ].copy()
        latest_display["monthly_revenue_ntd"] = latest_display["monthly_revenue_ntd"] / 1e6
        latest_display["ytd_revenue_ntd"] = latest_display["ytd_revenue_ntd"] / 1e6
        latest_display = latest_display.rename(
            columns={
                "company_code": "Code",
                "company_name": "Company",
                "market": "Market",
                "revenue_month": "Month",
                "monthly_revenue_ntd": "Monthly Revenue (NT$ B)",
                "yoy_pct": "YoY %",
                "ytd_revenue_ntd": "YTD Revenue (NT$ B)",
                "ytd_yoy_pct": "YTD YoY %",
            }
        )
        st.dataframe(
            latest_display.style.format(
                {
                    "Monthly Revenue (NT$ B)": "{:,.2f}",
                    "YoY %": "{:,.2f}",
                    "YTD Revenue (NT$ B)": "{:,.2f}",
                    "YTD YoY %": "{:,.2f}",
                }
            ),
            width="stretch",
            hide_index=True,
        )

    if not taiwan_revenue_pivot.empty:
        revenue_plot = (taiwan_revenue_pivot / 1e6).copy()
        st.plotly_chart(
            make_line_chart(
                revenue_plot,
                MODEL_COLORS[:len(revenue_plot.columns)],
                title="Monthly Revenue",
                y_title="NT$ Billion",
                x_title="Month",
                height=360,
                connect_gaps=True,
            ),
            width="stretch",
        )

    if not taiwan_yoy_pivot.empty:
        st.plotly_chart(
            make_line_chart(
                taiwan_yoy_pivot,
                MODEL_COLORS[:len(taiwan_yoy_pivot.columns)],
                title="Monthly Revenue YoY Growth",
                y_title="YoY %",
                x_title="Month",
                height=320,
                connect_gaps=True,
            ),
            width="stretch",
        )


def render_semiconductor_section(datasets: dict[str, DatasetLoadResult], semi_views: dict[str, object]) -> None:
    _ppi_range = st.radio(
        "Time range",
        options=["YTD", "1yr", "2yr", "5yr", "All"],
        index=2,
        horizontal=True,
        key="semi_ppi_range",
    )
    _now = datetime.now()
    _cutoffs = {
        "YTD": f"{_now.year}-01",
        "1yr": (_now - pd.DateOffset(months=12)).strftime("%Y-%m"),
        "2yr": (_now - pd.DateOffset(months=24)).strftime("%Y-%m"),
        "5yr": (_now - pd.DateOffset(months=60)).strftime("%Y-%m"),
    }
    _cutoff = _cutoffs.get(_ppi_range)

    tab_ppi, tab_private, tab_trade = st.tabs(
        ["AI Demand PPI (FRED)", "TODO", "Tiered Trade & Production Tracker"]
    )

    with tab_ppi:
        ppi_df = semi_views.get("ppi_df", pd.DataFrame())
        component_columns = semi_views.get("component_columns", [])
        base_month = semi_views.get("base_month")
        latest_proxy_month = semi_views.get("latest_proxy_month")
        latest_proxy_data = semi_views.get("latest_proxy_data", pd.Series(dtype="object"))
        latest_proxy_coverage = semi_views.get("latest_proxy_coverage")
        latest_proxy_missing = semi_views.get("latest_proxy_missing")
        latest_fred_month = semi_views.get("latest_fred_month")
        latest_fred_series_names = semi_views.get("latest_fred_series_names", [])

        if ppi_df.empty:
            st.warning("No AI Demand PPI data available.")
        else:
            st.markdown('<div class="section-title">Market Intelligence Hub</div>', unsafe_allow_html=True)

            active_month = latest_proxy_month or semi_views.get("latest_month")
            current_data = latest_proxy_data if not latest_proxy_data.empty else semi_views.get("latest_data", pd.Series(dtype="object"))

            # --- PPI cards with lag handling ---
            ppi_val = current_data.get("fred_ppi_value")
            ppi_mom = current_data.get("fred_ppi_mom_pct")
            ppi_trend = current_data.get("fred_ppi_3m_trend")

            ppi_display_val = "—"
            if pd.notna(ppi_val):
                ppi_display_val = f"{ppi_val:.1f}"

            if pd.notna(ppi_mom):
                ppi_delta_cls = "up" if ppi_mom >= 0 else "down"
                ppi_delta_text = f"{'↑' if ppi_mom >= 0 else '↓'} {abs(ppi_mom):.1f}% MoM"
            else:
                ppi_delta_cls, ppi_delta_text = "flat", "latest complete basket month"

            partial_month = bool(latest_proxy_coverage) and latest_proxy_coverage != f"{len(AI_DEMAND_PPI_WEIGHTS)}/{len(AI_DEMAND_PPI_WEIGHTS)}"
            if partial_month:
                ppi_delta_cls = "flat"
                ppi_delta_text = f"{latest_proxy_coverage} basket · provisional"

            trend_display_val = f"{ppi_trend:.1f}" if pd.notna(ppi_trend) else "—"
            snapshot_delta = "latest complete basket month"
            if latest_fred_month and active_month and latest_fred_month > active_month:
                updated_count = len(latest_fred_series_names)
                noun = "series" if updated_count != 1 else "series"
                snapshot_delta = f"Using {active_month}; {latest_fred_month} has {updated_count} updated {noun}, but the basket is incomplete"
            if partial_month:
                snapshot_delta = f"{active_month} is a partial basket ({latest_proxy_coverage} components)"

            st.markdown(
                kpi_grid_html(
                    kpi_card_html("Snapshot Month", active_month or "—", delta=snapshot_delta, delta_class="flat"),
                    kpi_card_html("AI Demand PPI", ppi_display_val, delta=ppi_delta_text, delta_class=ppi_delta_cls),
                    kpi_card_html("3M Trend", trend_display_val, delta="rebased index average", delta_class="flat"),
                    kpi_card_html("Proxy Base Month", base_month or "—", delta=f"{len(AI_DEMAND_PPI_WEIGHTS)} weighted PPIs", delta_class="flat"),
                ),
                unsafe_allow_html=True,
            )

            if partial_month:
                missing_label = latest_proxy_missing or "one basket component"
                st.caption(
                    f"⚠️ {active_month} AI Demand PPI is **partial ({latest_proxy_coverage} of 5 components)** — "
                    f"FRED has not yet published **{missing_label}**. The renormalized value is provisional "
                    "and may be revised when the missing component lands."
                )

            st.markdown(
                "[ADATA Industrial Market Watch](https://industrial.adata.com/en/edm)",
                unsafe_allow_html=False,
            )
            weight_note = ", ".join(
                f"{AI_DEMAND_PPI_LABELS.get(series_id, series_id)}: {int(weight * 100)}%"
                for series_id, weight in AI_DEMAND_PPI_WEIGHTS.items()
            )
            st.caption(
                "AI Demand PPI is a weighted basket rebased to 100 at the first common month. "
                f"Weights: {weight_note}"
            )
            if latest_fred_month and active_month and latest_fred_month > active_month:
                st.info(
                    f"Latest raw PPI updates reach {latest_fred_month}, but the weighted AI Demand PPI remains on {active_month} "
                    "until all five component series have updated for the same month."
                )

            _plot_df = ppi_df[ppi_df["month"] >= _cutoff].copy() if _cutoff else ppi_df.copy()

            proxy_pivot = _plot_df[["month", "fred_ppi_value"]].set_index("month").rename(columns={"fred_ppi_value": "AI Demand PPI"})
            st.plotly_chart(
                make_line_chart(proxy_pivot, [ACCENT], title="AI Demand PPI Trend", y_title="Rebased Index", x_title="Month", height=350),
                width="stretch",
            )

            available_component_columns = [column for column in component_columns if column in _plot_df.columns]
            if available_component_columns:
                component_labels = {
                    AI_DEMAND_PPI_COMPONENT_COLUMNS[series_id]: AI_DEMAND_PPI_LABELS.get(series_id, series_id)
                    for series_id in AI_DEMAND_PPI_WEIGHTS
                }
                component_pivot = _plot_df[["month", *available_component_columns]].set_index("month").rename(columns=component_labels)
                st.plotly_chart(
                    make_line_chart(
                        component_pivot,
                        MODEL_COLORS[:len(component_pivot.columns)],
                        title="Component PPIs (Rebased)",
                        y_title="Rebased Index",
                        x_title="Month",
                        height=380,
                    ),
                    width="stretch",
                )

    with tab_private:
        if _render_private_panel_gate():
            _render_private_company_revenue(semi_views, _cutoff)

    with tab_trade:
        official_df = semi_views.get("official_df", pd.DataFrame())
        backup_df = semi_views.get("backup_df", pd.DataFrame())
        production_df = semi_views.get("production_df", pd.DataFrame())
        source_catalog_df = semi_views.get("source_catalog_df", pd.DataFrame())

        min_date = _cutoff

        if not official_df.empty:
            official_df = official_df.sort_values("period")
            if min_date:
                official_df = official_df[official_df["period"] >= min_date].copy()
        if not backup_df.empty:
            backup_df = backup_df.sort_values("period")
            if min_date:
                backup_df = backup_df[backup_df["period"] >= min_date].copy()
        if not production_df.empty:
            production_df = production_df.sort_values("period")
            if min_date:
                production_df = production_df[production_df["period"] >= min_date].copy()

        if official_df.empty and backup_df.empty and production_df.empty:
            st.warning("No tiered semiconductor trade or production data available.")
        else:
            st.markdown('<div class="section-title">Tiered Semiconductor Tracker</div>', unsafe_allow_html=True)
            source_tier = st.radio(
                "Source tier",
                options=["Official", "Backup Check", "Both"],
                horizontal=True,
                key="semi_source_tier",
            )
            category_choice = st.selectbox(
                "Category",
                options=["IC-only", "Broad Semiconductor", "Lithography Equipment", "Production", "Company Revenue"],
                index=0,
                key="semi_category_choice",
            )

            latest_official = semi_views.get("latest_official_period") or "—"
            latest_backup = semi_views.get("latest_backup_period") or "—"
            official_freshness = official_df[
                (official_df["metric_type"] == "exports") & (official_df["partner_scope"] == "world")
            ].groupby("country_name")["period"].max() if not official_df.empty else pd.Series(dtype="object")
            freshness_bits = [f"{country}: {period}" for country, period in official_freshness.sort_index().items()]
            freshness_text = " · ".join(freshness_bits) if freshness_bits else "No official country snapshots"
            st.caption(
                f"Official latest: {latest_official}. Backup latest: {latest_backup}. "
                f"Latest official by country: {freshness_text}. "
                "Official/native series are the primary view; Comtrade is a cross-check."
            )

            selected_category_id = {
                "IC-only": "ic_only",
                "Broad Semiconductor": "broad_semiconductor",
                "Lithography Equipment": "lithography",
                "Production": "ic_only",
            }.get(category_choice)

            show_official = source_tier in {"Official", "Both"}
            show_backup = source_tier in {"Backup Check", "Both"}

            if category_choice in {"IC-only", "Broad Semiconductor", "Lithography Equipment"}:
                official_trade = official_df[
                    (official_df["metric_type"] == "exports")
                    & (official_df["partner_scope"] == "world")
                    & (official_df["category_id"] == selected_category_id)
                ].copy()
                backup_trade = backup_df[
                    (backup_df["metric_type"] == "exports")
                    & (backup_df["partner_scope"] == "world")
                    & (backup_df["category_id"] == selected_category_id)
                ].copy()
                scale_mode = st.radio(
                    "Scale",
                    options=["Native", "USD Normalized (PT FX)"],
                    horizontal=True,
                    key="semi_trade_scale",
                )

                if show_official and not official_trade.empty:
                    official_chart_frame = pd.DataFrame()
                    if scale_mode == "Native":
                        _render_official_trade_chart(official_trade, category_choice)
                        official_chart_frame = official_trade.copy()
                        official_chart_frame["display_value"] = official_chart_frame["value"]
                    else:
                        official_chart_frame, y_title, has_complete_fx = _prepare_official_trade_display(official_trade, scale_mode)
                        if official_chart_frame.empty:
                            st.warning("USD-normalized comparison is unavailable because monthly FX rates could not be loaded.")
                        else:
                            if not has_complete_fx:
                                st.info("Some monthly FX points were unavailable, so the USD-normalized chart may omit a few country-month observations.")
                            official_pivot = official_chart_frame.pivot_table(
                                index="period",
                                columns="country_name",
                                values="display_value",
                                aggfunc="last",
                            ).sort_index()
                            st.plotly_chart(
                                make_line_chart(
                                    official_pivot,
                                    MODEL_COLORS[:len(official_pivot.columns)],
                                    title=f"Official {category_choice} Exports (USD Normalized)",
                                    y_title=y_title,
                                    x_title="Month",
                                    height=340,
                                    connect_gaps=True,
                                ),
                                width="stretch",
                            )
                    if not official_chart_frame.empty:
                        _render_trade_yoy_chart(official_chart_frame, category_choice, "Official")

                if show_backup and not backup_trade.empty:
                    backup_trade["value_b"] = backup_trade["value"] / 1e9
                    backup_pivot = backup_trade.pivot_table(
                        index="period",
                        columns="country_name",
                        values="value_b",
                        aggfunc="last",
                    ).sort_index()
                    st.plotly_chart(
                        make_line_chart(
                            backup_pivot,
                            MODEL_COLORS[:len(backup_pivot.columns)],
                            title=f"Backup Check {category_choice} Exports",
                            y_title="USD Billion",
                            x_title="Month",
                            height=340,
                            connect_gaps=True,
                        ),
                        width="stretch",
                    )
                    backup_trade["display_value"] = backup_trade["value_b"]
                    _render_trade_yoy_chart(backup_trade, category_choice, "Backup Check")

                if show_official and show_backup and not official_trade.empty and not backup_trade.empty:
                    gap_df = official_trade.merge(
                        backup_trade[
                            ["source_region", "period", "category_id", "value", "comparison_gap_pct"]
                        ].rename(columns={"value": "backup_value"}),
                        on=["source_region", "period", "category_id"],
                        how="inner",
                    )
                    if not gap_df.empty:
                        gap_display = gap_df[
                            ["country_name", "period", "value", "backup_value", "comparison_gap_pct"]
                        ].rename(
                            columns={
                                "country_name": "Country",
                                "period": "Month",
                                "value": "Official Value",
                                "backup_value": "Backup Value",
                                "comparison_gap_pct": "Gap %",
                            }
                        )
                        st.dataframe(dataframe_for_display(gap_display, "-"), width="stretch", hide_index=True)

                if not source_catalog_df.empty:
                    latest_catalog = source_catalog_df[
                        ["source_region", "source_name", "source_tier", "metric_type", "category_label", "latest_period", "expected_release_window_days"]
                    ].copy()
                    latest_catalog = latest_catalog.rename(
                        columns={
                            "source_region": "Region",
                            "source_name": "Source",
                            "source_tier": "Tier",
                            "metric_type": "Metric",
                            "category_label": "Category",
                            "latest_period": "Latest Period",
                            "expected_release_window_days": "Expected Lag (Days)",
                        }
                    )
                    st.dataframe(latest_catalog, width="stretch", hide_index=True)

            if category_choice == "Production" and not production_df.empty:
                prod_pivot = production_df.pivot_table(
                    index="period",
                    columns="country_name",
                    values="value",
                    aggfunc="last",
                ).sort_index()
                st.plotly_chart(
                    make_line_chart(
                        prod_pivot,
                        [MODEL_COLORS[4], MODEL_COLORS[1], MODEL_COLORS[2]][:len(prod_pivot.columns)],
                        title="Official Semiconductor Production",
                        y_title="Native Unit",
                        x_title="Month",
                        height=340,
                    ),
                    width="stretch",
                )

            if category_choice == "Company Revenue":
                st.info("Use the TODO tab for company-level monthly revenue disclosures.")


def render(domain_states, datasets) -> None:
    combined = {
        **domain_states["semiconductor_memory"][0],
        **domain_states["semiconductor_proxies"][0],
        **domain_states["taiwan_semiconductor_revenue"][0],
    }
    semi_views = compute_semiconductor_views(combined)
    render_semiconductor_section(datasets, semi_views)
