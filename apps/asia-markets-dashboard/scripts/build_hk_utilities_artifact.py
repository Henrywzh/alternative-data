"""Build canonical JSON artifact and Astro status for HK Utilities Sector Monitor."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from src.hk_utilities.sources.clp_electricity import fetch_clp_electricity
from src.hk_utilities.sources.dsd_sewage_flow_lab import fetch_dsd_sewage_flow_lab
from src.hk_utilities.sources.hko_temperature import fetch_hko_temperature
from src.hk_utilities.sources.power_assets_segments import fetch_power_assets_segments
from src.hk_utilities.sources.towngas_proxy import fetch_towngas_proxy
from src.hk_utilities.sources.wsd_water_suspension import fetch_wsd_water_suspension
from history_policy import DEFAULT_HISTORY_YEARS, history_window


PUBLIC_SOURCES = {
    "clp_electricity": {
        "id": "clp_electricity",
        "label": "CLP Power Hong Kong Electricity Sales Disclosures",
        "href": "https://www.clpgroup.com/en/investors/financial-reports.html",
        "path": "sources/clp_electricity.sql",
        "query": {
            "engine": "official HKEX statement",
            "url": "https://www.clpgroup.com/en/investors/financial-reports.html",
            "language": "PDF",
            "description": "Quarterly electricity sales in GWh broken down by customer sector (Residential, Commercial, Infrastructure & Public Services, Manufacturing) plus AI Data-Centre demand growth.",
        },
    },
    "towngas_proxy": {
        "id": "towngas_proxy",
        "label": "CenStatD HK Energy Statistics (Gas Consumption)",
        "href": "https://www.censtatd.gov.hk/en/web_table.html?id=915-91201",
        "path": "sources/towngas_proxy.sql",
        "query": {
            "engine": "official MDT CSV",
            "url": "https://www.censtatd.gov.hk/data/MDT_91_915-91201_GASC_LOCAL_Raw_Tjou_n.csv",
            "language": "CSV",
            "description": "Monthly town gas consumption in Terajoules (TJ) by user type (Domestic, Commercial, Industrial) — de facto Towngas monopoly operational proxy.",
        },
    },
    "hko_temperature": {
        "id": "hko_temperature",
        "label": "Hong Kong Observatory Daily Mean Temperature",
        "href": "https://data.weather.gov.hk/weatherAPI/cis/csvfile/HKO/ALL/daily_HKO_TEMP_ALL.csv",
        "path": "sources/hko_temperature.sql",
        "query": {
            "engine": "official open data CSV",
            "url": "https://data.weather.gov.hk/weatherAPI/cis/csvfile/HKO/ALL/daily_HKO_TEMP_ALL.csv",
            "language": "CSV",
            "description": "Daily mean temperature (°C) and monthly averages — primary physical weather driver for air-conditioning power load.",
        },
    },
    "power_assets_segments": {
        "id": "power_assets_segments",
        "label": "Power Assets Holdings Geographic Segment Reporting",
        "href": "https://www.powerassets.com/en/investor-relations/financial-reports",
        "path": "sources/power_assets_segments.sql",
        "query": {
            "engine": "official HKEX interim report note",
            "url": "https://www.powerassets.com/en/investor-relations/financial-reports",
            "language": "PDF",
            "description": "Semi-annual geographic segment reporting note (revenue, segment profit, share of JV/associate results) broken out by Investment in HKEI, United Kingdom, Australia, and Others.",
        },
    },
    "dsd_sewage_flow_lab": {
        "id": "dsd_sewage_flow_lab",
        "label": "DSD Daily Sewage Flow and Effluent Laboratory Data",
        "href": "https://portal.csdi.gov.hk/csdi-webpage/dataset/dsd_rcd_1636622115573_60635",
        "path": "sources/dsd_sewage_flow_lab.sql",
        "query": {
            "engine": "official DSD CSV catalogued by CSDI",
            "url": "https://www.dsd.gov.hk/datagovhk/data/shatin_lab_open_data_eng.csv",
            "language": "UTF-16 tab-delimited CSV",
            "description": "Daily final-effluent flow and sparse laboratory observations (BOD, TSS, nitrogen, oil/grease, pH and E. coli) by sewage treatment works; treatment-works coverage changes over time.",
        },
    },
    "wsd_water_suspension": {
        "id": "wsd_water_suspension",
        "label": "WSD Temporary Water Suspension Notices",
        "href": "https://portal.csdi.gov.hk/csdi-webpage/dataset/wsd_rcd_1696485865245_52313",
        "path": "sources/wsd_water_suspension.sql",
        "query": {
            "engine": "official WSD event feed catalogued by CSDI",
            "url": "https://www.esd.wsd.gov.hk/wsms_open_data/WSMS_OPEN_DATA(all).csv",
            "language": "Pipe-delimited CSV",
            "description": "Current planned and emergency water-suspension notices with district, affected address, start/resumption time, cause and current status; refreshed every five minutes and not a continuous consumption series.",
        },
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _series_history(df: pd.DataFrame, series_label: str, value_column: str) -> list[dict[str, Any]]:
    """Long-format {date, month, series, value} rows for a multi-series line chart."""
    if df.empty or value_column not in df.columns:
        return []
    rows = []
    for _, row in df.iterrows():
        value = row.get(value_column)
        date = row.get("date")
        if pd.isna(value) or pd.isna(date):
            continue
        date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)[:10]
        month_str = row.get("month", date_str[:7])
        rows.append(
            {
                "date": date_str,
                "month": str(month_str) if pd.notna(month_str) else date_str[:7],
                "series": series_label,
                "value": round(float(value), 4),
            }
        )
    return rows


def _records_json_safe(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a DataFrame to records with NaN/NaT replaced by JSON null.

    pandas' to_dict(orient="records") leaves NaN as a Python float('nan'),
    which json.dumps serializes as the bare token `NaN` -- not valid JSON,
    which downstream JS `JSON.parse` calls reject outright. Optional fields
    (e.g. CLP's ai_data_centre_yoy_pct, absent for most quarters) need to
    become JSON `null` instead.
    """
    selected = frame.copy()
    for column in selected.columns:
        if pd.api.types.is_datetime64_any_dtype(selected[column]):
            selected[column] = selected[column].dt.strftime("%Y-%m-%d")
    return json.loads(selected.to_json(orient="records", date_format="iso"))


def _display_value(value: Any) -> str:
    """Format a scalar for compact, mobile-safe summary table rows."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return "n/a"
    if isinstance(value, (int, float)):
        formatted = f"{float(value):,.1f}"
        return formatted.rstrip("0").rstrip(".")
    return str(value)


def build_artifact(
    raw_clp: pd.DataFrame | None = None,
    raw_towngas: pd.DataFrame | None = None,
    raw_temp: pd.DataFrame | None = None,
    raw_power_assets: pd.DataFrame | None = None,
    raw_sewage: pd.DataFrame | None = None,
    raw_water_suspension: pd.DataFrame | None = None,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()

    clp = raw_clp if raw_clp is not None else fetch_clp_electricity()
    towngas = raw_towngas if raw_towngas is not None else fetch_towngas_proxy()
    temp = raw_temp if raw_temp is not None else fetch_hko_temperature()
    power_assets = raw_power_assets if raw_power_assets is not None else fetch_power_assets_segments()
    sewage = raw_sewage if raw_sewage is not None else fetch_dsd_sewage_flow_lab()
    water_suspension = (
        raw_water_suspension
        if raw_water_suspension is not None
        else fetch_wsd_water_suspension()
    )

    # CLP's existing `quarter` column (e.g. "2023 Q1") repeats the same
    # quarter label across different years (all 4 rows are "Q1"), and its
    # `date` column is quarter-end day-granularity, which the portable-chart
    # plugin's date-axis formatter renders without a year by default. A
    # "YYYY-MM" `month` column is unambiguous across years (each quarter-end
    # lands on a distinct month) and gets the year on every tick for free,
    # since the plugin always includes the year for month-granularity values.
    if "date" in clp.columns:
        clp["month"] = clp["date"].dt.strftime("%Y-%m")

    generated_at = now.isoformat().replace("+00:00", "Z")

    clp_latest = clp.iloc[-1]
    clp_prior = clp.iloc[-2] if len(clp) > 1 else None
    clp_prior_total = float(clp_prior["total_local_gwh"]) if clp_prior is not None else 0.0
    clp_kpi = {
        "latest": float(clp_latest["total_local_gwh"]),
        "commercial_gwh": float(clp_latest["commercial_gwh"]),
        "ai_data_centre_yoy_pct": (
            float(clp_latest["ai_data_centre_yoy_pct"])
            if pd.notna(clp_latest["ai_data_centre_yoy_pct"])
            else None
        ),
        "period_change": (
            round(float(clp_latest["total_local_gwh"]) / clp_prior_total - 1, 6)
            if clp_prior_total
            else None
        ),
        "observation_date": clp_latest["date"].strftime("%Y-%m-%d"),
    }

    tg_latest = towngas.iloc[-1]
    tg_prior = towngas.iloc[-2] if len(towngas) > 1 else None
    tg_prior_total = float(tg_prior["total_gas_tj"]) if tg_prior is not None else 0.0
    tg_kpi = {
        "latest": float(tg_latest["total_gas_tj"]),
        "domestic_tj": float(tg_latest["domestic_gas_tj"]),
        "commercial_tj": float(tg_latest["commercial_gas_tj"]),
        "period_change": (
            round(float(tg_latest["total_gas_tj"]) / tg_prior_total - 1, 6)
            if tg_prior_total
            else None
        ),
        "observation_date": tg_latest["date"].strftime("%Y-%m-%d"),
    }

    temp_latest = temp.iloc[-1]
    temp_kpi = {
        "latest": float(temp_latest["mean_temp_c"]),
        "month_avg": float(temp_latest["month_avg_temp_c"]),
        "observation_date": temp_latest["date"].strftime("%Y-%m-%d"),
    }

    pa_available = not power_assets.empty
    pa_latest = power_assets.iloc[-1] if pa_available else None
    pa_prior = power_assets.iloc[-2] if pa_available and len(power_assets) > 1 else None
    pa_prior_revenue = float(pa_prior["revenue_total_hkdm"]) if pa_prior is not None else 0.0
    pa_kpi = {
        "period": pa_latest["period"] if pa_available else None,
        "revenue_total_hkdm": float(pa_latest["revenue_total_hkdm"]) if pa_available else None,
        "segment_profit_total_hkdm": float(pa_latest["segment_profit_total_hkdm"]) if pa_available else None,
        "jv_associate_results_total_hkdm": (
            float(pa_latest["jv_associate_results_total_hkdm"]) if pa_available else None
        ),
        "period_change": (
            round(float(pa_latest["revenue_total_hkdm"]) / pa_prior_revenue - 1, 6)
            if pa_available and pa_prior_revenue
            else None
        ),
        "observation_date": pa_latest["date"].strftime("%Y-%m-%d") if pa_available else None,
    }

    # Reshape the latest period's wide geography columns into one row per
    # geography for the breakdown table.
    pa_geography_rows: list[dict[str, Any]] = []
    if pa_available:
        for geo_label, geo_key in (
            ("Investment in HKEI", "hkei"),
            ("United Kingdom", "uk"),
            ("Australia", "australia"),
            ("Others", "others"),
        ):
            pa_geography_rows.append(
                {
                    "geography": geo_label,
                    "revenue_hkdm": float(pa_latest[f"revenue_{geo_key}_hkdm"]),
                    "segment_profit_hkdm": float(pa_latest[f"segment_profit_{geo_key}_hkdm"]),
                    "jv_associate_results_hkdm": float(pa_latest[f"jv_associate_results_{geo_key}_hkdm"]),
                }
            )
    pa_geography_summary = [
        {
            "summary": (
                f"{row['geography']}: revenue HK${_display_value(row['revenue_hkdm'])}m; "
                f"segment profit HK${_display_value(row['segment_profit_hkdm'])}m; "
                f"JV/associate results HK${_display_value(row['jv_associate_results_hkdm'])}m"
            )
        }
        for row in pa_geography_rows
    ]

    sewage_available = not sewage.empty and {"date", "plant", "daily_flow_cum_d"}.issubset(sewage.columns)
    sewage_history_window = history_window(sewage, "date") if sewage_available else sewage.iloc[0:0].copy()
    if sewage_available:
        sewage_monthly = (
            sewage_history_window.dropna(subset=["daily_flow_cum_d"])
            .assign(month=sewage_history_window["date"].dt.strftime("%Y-%m"))
            .groupby(["month", "plant"], as_index=False)
            .agg(
                date=("date", "min"),
                value=("daily_flow_cum_d", "mean"),
                observations=("daily_flow_cum_d", "count"),
            )
            .sort_values(["plant", "month"])
        )
        sewage_monthly["value"] = sewage_monthly["value"].round(1)
        sewage_monthly["series"] = sewage_monthly["plant"]
        sewage_chart = (
            sewage_monthly.groupby("month", as_index=False)
            .agg(
                date=("date", "min"),
                value=("value", "sum"),
                observations=("observations", "sum"),
                treatment_works=("plant", "nunique"),
            )
            .sort_values("month")
        )
        sewage_chart["value"] = sewage_chart["value"].round(1)
        sewage_latest = (
            sewage.dropna(subset=["date"])
            .sort_values(["plant", "date"])
            .groupby("plant", as_index=False, sort=False)
            .tail(1)
            .sort_values("plant")
        )
    else:
        sewage_monthly = pd.DataFrame(columns=["month", "plant", "date", "value", "observations", "series"])
        sewage_chart = pd.DataFrame(columns=["date", "month", "value", "observations", "treatment_works"])
        sewage_latest = sewage.iloc[0:0].copy()
    sewage_latest_summary = [
        {
            "summary": (
                f"{row['plant']} ({pd.Timestamp(row['date']).strftime('%Y-%m-%d')}): "
                f"flow {_display_value(row.get('daily_flow_cum_d'))} CuM/d; "
                f"BOD {_display_value(row.get('bod_mg_o2_l'))}; "
                f"TSS {_display_value(row.get('tss_mg_l'))}; "
                f"NH3-N {_display_value(row.get('nh3_n_mg_l'))}; "
                f"NOx-N {_display_value(row.get('nox_n_mg_l'))}; "
                f"oil/grease {_display_value(row.get('og_mg_l'))}; "
                f"TN {_display_value(row.get('tn_mg_l'))}; "
                f"pH {_display_value(row.get('ph'))}; "
                f"E. coli {_display_value(row.get('e_coli_cfu_100ml'))}"
            )
        }
        for _, row in sewage_latest.iterrows()
    ]

    water_available = not water_suspension.empty and {
        "suspension_id",
        "suspension_start",
        "nature",
        "status",
        "is_active",
    }.issubset(water_suspension.columns)
    if water_available:
        water_recent_cutoff = pd.Timestamp(now.replace(tzinfo=None)) - pd.Timedelta(days=7)
        water_emergency_recent = int(
            (
                water_suspension["nature"].eq("Emergency")
                & water_suspension["suspension_start"].ge(water_recent_cutoff)
            ).sum()
        )
        water_kpi = {
            "active_notices": int(water_suspension["is_active"].fillna(False).sum()),
            "total_notices": int(len(water_suspension)),
            "recent_emergency_notices": water_emergency_recent,
            "observation_date": now.date().isoformat(),
        }
        water_events = water_suspension.sort_values(
            "suspension_start", ascending=False, na_position="last"
        ).copy()
    else:
        water_kpi = {
            "active_notices": 0,
            "total_notices": 0,
            "recent_emergency_notices": 0,
            "observation_date": now.date().isoformat(),
        }
        water_events = water_suspension.copy()

    water_events_for_artifact = water_events.copy()
    for column in ("suspension_start", "actual_resumption"):
        if column in water_events_for_artifact.columns:
            parsed = pd.to_datetime(water_events_for_artifact[column], errors="coerce")
            water_events_for_artifact[column] = parsed.dt.strftime("%Y-%m-%d %H:%M")
    if "suspension_date" in water_events_for_artifact.columns:
        parsed_date = pd.to_datetime(water_events_for_artifact["suspension_date"], errors="coerce")
        water_events_for_artifact["suspension_date"] = parsed_date.dt.strftime("%Y-%m-%d")
    water_suspension_summary = [
        {
            "summary": (
                f"{row['suspension_id']} ({row.get('suspension_start') or 'n/a'}): "
                f"{row.get('district') or 'n/a'}; {row.get('water_type') or 'n/a'}; "
                f"{row.get('nature') or 'n/a'}; {row.get('status') or 'n/a'}"
            )
        }
        for _, row in water_events_for_artifact.iterrows()
    ]

    towngas_history_window = history_window(towngas, "date", years=DEFAULT_HISTORY_YEARS)
    temperature_history_window = history_window(temp, "date", years=DEFAULT_HISTORY_YEARS)
    temperature_chart = (
        temperature_history_window.assign(month=temperature_history_window["date"].dt.strftime("%Y-%m"))
        .groupby("month", as_index=False)
        .agg(
            date=("date", "min"),
            mean_temp_c=("mean_temp_c", "mean"),
            month_avg_temp_c=("month_avg_temp_c", "first"),
        )
        .sort_values("month")
    )
    temperature_chart["mean_temp_c"] = temperature_chart["mean_temp_c"].round(1)
    temperature_chart["month_avg_temp_c"] = temperature_chart["month_avg_temp_c"].round(1)

    datasets = {
        "kpi_clp": [clp_kpi],
        "kpi_towngas": [tg_kpi],
        "kpi_temp": [temp_kpi],
        "kpi_power_assets": [pa_kpi],
        "clp_history": _records_json_safe(clp),
        "clp_sector_history": (
            _series_history(clp, "Residential", "residential_gwh")
            + _series_history(clp, "Commercial", "commercial_gwh")
            + _series_history(clp, "Infra & Public", "infrastructure_public_gwh")
            + _series_history(clp, "Manufacturing", "manufacturing_gwh")
        ),
        "towngas_history": _records_json_safe(towngas_history_window),
        "towngas_type_history": (
            _series_history(towngas_history_window, "Domestic", "domestic_gas_tj")
            + _series_history(towngas_history_window, "Commercial", "commercial_gas_tj")
            + _series_history(towngas_history_window, "Industrial", "industrial_gas_tj")
        ),
        "temp_history": _records_json_safe(temperature_chart),
        "power_assets_geography": pa_geography_rows,
        "power_assets_geography_summary": pa_geography_summary,
        "kpi_water_suspension": [water_kpi],
        "sewage_flow_history": _records_json_safe(
            sewage_monthly[["date", "month", "series", "value", "observations"]]
            if not sewage_monthly.empty
            else sewage_monthly
        ),
        "sewage_flow_chart_history": _records_json_safe(sewage_chart),
        "sewage_latest_lab": _records_json_safe(sewage_latest),
        "sewage_latest_summary": sewage_latest_summary,
        "water_suspension_events": _records_json_safe(water_events_for_artifact),
        "water_suspension_summary": water_suspension_summary,
    }
    # Sort the multi-series datasets by (series, date) so each series'
    # points are contiguous in the array (same requirement as REIT charts)
    clp_sector_sorted = sorted(datasets.get("clp_sector_history", []), key=lambda r: (r.get("series", ""), r.get("date", "")))
    towngas_type_sorted = sorted(datasets.get("towngas_type_history", []), key=lambda r: (r.get("series", ""), r.get("date", "")))
    if clp_sector_sorted:
        datasets["clp_sector_history"] = clp_sector_sorted
    if towngas_type_sorted:
        datasets["towngas_type_history"] = towngas_type_sorted

    cards = [
        {
            "id": "clp_card",
            "description": "Quarterly electricity sales in GWh and AI Data-Centre growth.",
            "dataset": "kpi_clp",
            "sourceId": "clp_electricity",
            "metrics": [
                {"label": "Total Local GWh", "field": "latest", "format": "number"},
                {"label": "Commercial GWh", "field": "commercial_gwh", "format": "number"},
                {"label": "AI Data Centre YoY", "field": "ai_data_centre_yoy_pct", "format": "percent"},
            ],
        },
        {
            "id": "towngas_card",
            "description": "Monthly town gas consumption in Terajoules (TJ).",
            "dataset": "kpi_towngas",
            "sourceId": "towngas_proxy",
            "metrics": [
                {"label": "Total Gas (TJ)", "field": "latest", "format": "number"},
                {"label": "Domestic Gas (TJ)", "field": "domestic_tj", "format": "number"},
                {"label": "Commercial Gas (TJ)", "field": "commercial_tj", "format": "number"},
            ],
        },
        {
            "id": "temp_card",
            "description": "Daily mean temperature and monthly average (°C).",
            "dataset": "kpi_temp",
            "sourceId": "hko_temperature",
            "metrics": [
                {"label": "Latest Temp (°C)", "field": "latest", "format": "number"},
                {"label": "Month Avg (°C)", "field": "month_avg", "format": "number"},
            ],
        },
        {
            "id": "power_assets_card",
            "description": "Power Assets semi-annual geographic segment revenue and profit (HK$ million).",
            "dataset": "kpi_power_assets",
            "sourceId": "power_assets_segments",
            "metrics": [
                {"label": "Total Segment Revenue (HK$m)", "field": "revenue_total_hkdm", "format": "number"},
                {"label": "Total Segment Profit (HK$m)", "field": "segment_profit_total_hkdm", "format": "number"},
                {"label": "JV/Associate Results (HK$m)", "field": "jv_associate_results_total_hkdm", "format": "number"},
            ],
        },
        {
            "id": "water_suspension_card",
            "description": "Current WSD planned and emergency water-suspension event feed.",
            "dataset": "kpi_water_suspension",
            "sourceId": "wsd_water_suspension",
            "metrics": [
                {"label": "Active Notices", "field": "active_notices", "format": "number"},
                {"label": "Feed Rows", "field": "total_notices", "format": "number"},
                {"label": "Emergency (7d)", "field": "recent_emergency_notices", "format": "number"},
            ],
        },
    ]

    charts = [
        {
            "id": "clp_sector_chart",
            "title": "CLP Electricity Sales by Sector (GWh)",
            "subtitle": "Quarterly sales across Residential, Commercial, Infrastructure & Public Services, and Manufacturing.",
            "type": "line",
            "intent": "comparison",
            "dataset": "clp_sector_history",
            "sourceId": "clp_electricity",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Quarter"},
                "y": {"field": "value", "type": "quantitative", "label": "GWh"},
                "color": {"field": "series", "type": "nominal", "label": "Sector"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "towngas_trend_chart",
            "title": "Hong Kong Town Gas Consumption Trend (TJ)",
            "subtitle": "Monthly gas consumption split by Domestic, Commercial, and Industrial user types; latest ten years of available history by default.",
            "type": "line",
            "intent": "comparison",
            "dataset": "towngas_type_history",
            "sourceId": "towngas_proxy",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "value", "type": "quantitative", "label": "Terajoules (TJ)"},
                "color": {"field": "series", "type": "nominal", "label": "User Type"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "temp_trend_chart",
            "title": "Hong Kong Observatory Monthly Mean Temperature (°C)",
            "subtitle": "Monthly average of HKO daily mean temperatures; latest ten years of available history by default. Daily source observations remain at source cadence outside this compact public chart.",
            "type": "line",
            "dataset": "temp_history",
            "sourceId": "hko_temperature",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "mean_temp_c", "type": "quantitative", "label": "°C"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "sewage_flow_chart",
            "title": "Reported Sewage Flow across Treatment Works (Monthly Sum)",
            "subtitle": "Monthly sum of daily final-effluent flow reported by the treatment works available in each month; the source remains daily and coverage changes over time. Per-works history remains in the dataset.",
            "type": "line",
            "intent": "comparison",
            "dataset": "sewage_flow_chart_history",
            "sourceId": "dsd_sewage_flow_lab",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "value", "type": "quantitative", "label": "Reported Daily Flow (CuM/d)"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
    ]

    tables: list[dict[str, Any]] = [
        {
            "id": "power_assets_geography_table",
            "title": "Power Assets Geographic Segment Breakdown",
            "subtitle": (
                f"Semi-annual segment reporting ({pa_kpi['period']}), HK$ million. "
                "'Investment in HKEI' is equity-accounted and reports nil consolidated revenue/segment profit "
                "under this note; its contribution appears in the JV/associate results column instead."
                if pa_available
                else "No Power Assets interim segment filing available yet for the current period."
            ),
            "dataset": "power_assets_geography_summary",
            "sourceId": "power_assets_segments",
            "density": "dense",
            "layout": "full",
            "columns": [{"field": "summary", "label": "Geographic Segment Summary", "type": "text"}],
        },
        {
            "id": "sewage_latest_lab_table",
            "title": "Latest Sewage Treatment Works Flow and Laboratory Observations",
            "subtitle": "Latest available row for each treatment works. Core lab fields are shown; additional source-sparse lab fields remain in the dataset and are not imputed.",
            "dataset": "sewage_latest_summary",
            "sourceId": "dsd_sewage_flow_lab",
            "density": "dense",
            "layout": "full",
            "columns": [{"field": "summary", "label": "Treatment Works and Latest Metrics", "type": "text"}],
        },
        {
            "id": "water_suspension_events_table",
            "title": "Current Water Suspension Notices",
            "subtitle": "Current WSD planned/emergency notices, including scheduled future notices. Start/status fields are shown; source address and cause fields remain in the dataset. This is an event snapshot, not a water-consumption time series.",
            "dataset": "water_suspension_summary",
            "sourceId": "wsd_water_suspension",
            "density": "dense",
            "layout": "full",
            "columns": [{"field": "summary", "label": "Notice Summary", "type": "text"}],
        },
    ]

    data_as_of_candidates = [
        clp_kpi.get("observation_date"),
        tg_kpi.get("observation_date"),
        temp_kpi.get("observation_date"),
        pa_kpi.get("observation_date"),
    ]
    if sewage_available and sewage["date"].notna().any():
        data_as_of_candidates.append(sewage["date"].max().strftime("%Y-%m-%d"))
    data_as_of = max(value for value in data_as_of_candidates if value)

    sources = list(PUBLIC_SOURCES.values())

    snapshot_id = hashlib.sha256(
        json.dumps(datasets, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]

    artifact = {
        "surface": "dashboard",
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "HK Utilities & Infrastructure Sector Monitor",
            "description": "CLP quarterly electricity sales by customer sector, CenStatD town gas consumption, HKO temperature, Power Assets geographic segment reporting, DSD sewage flow/laboratory data and WSD water-suspension notices.",
            "sector": "hk-utilities",
            "generatedAt": generated_at,
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": sources,
            "blocks": [
                {"id": "kpi_grid", "type": "metric-strip", "cardIds": [c["id"] for c in cards]},
                {"id": "clp_chart", "type": "chart", "chartId": "clp_sector_chart"},
                {"id": "towngas_chart", "type": "chart", "chartId": "towngas_trend_chart"},
                {"id": "temp_chart", "type": "chart", "chartId": "temp_trend_chart"},
                {"id": "sewage_chart", "type": "chart", "chartId": "sewage_flow_chart"},
                {"id": "power_assets_table", "type": "table", "tableId": "power_assets_geography_table"},
                {"id": "sewage_table", "type": "table", "tableId": "sewage_latest_lab_table"},
                {"id": "water_table", "type": "table", "tableId": "water_suspension_events_table"},
            ],
        },
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready", "datasets": datasets},
        "sources": sources,
        "package_info": {"originUrl": "https://asia-markets-dashboard.pages.dev/sectors/hk-utilities/", "snapshotId": snapshot_id, "dataAsOf": data_as_of},
    }

    record_counts = {
        "clp_electricity": len(clp),
        "towngas_proxy": len(towngas),
        "hko_temperature": len(temp),
        "power_assets_segments": len(power_assets),
        "dsd_sewage_flow_lab": len(sewage),
        "wsd_water_suspension": len(water_suspension),
    }
    sewage_latest_observation = (
        sewage["date"].max().strftime("%Y-%m-%d")
        if sewage_available and sewage["date"].notna().any()
        else "—"
    )
    # The feed contains future scheduled notices. Source health should report
    # the build date, not the furthest future scheduled start date, as the
    # latest observation.
    water_latest_observation = now.date().isoformat() if water_available else "—"
    latest_observation_dates = {
        "clp_electricity": clp_kpi["observation_date"],
        "towngas_proxy": tg_kpi["observation_date"],
        "hko_temperature": temp_kpi["observation_date"],
        "power_assets_segments": pa_kpi["observation_date"],
        "dsd_sewage_flow_lab": sewage_latest_observation,
        "wsd_water_suspension": water_latest_observation,
    }
    sewage_age_days = None
    if sewage_latest_observation != "—":
        sewage_age_days = max(
            0,
            (now.replace(tzinfo=None).date() - pd.Timestamp(sewage_latest_observation).date()).days,
        )
    freshness_by_source = {
        "clp_electricity": "Live",
        "towngas_proxy": "Live",
        "hko_temperature": "Live",
        "power_assets_segments": "Live",
        "dsd_sewage_flow_lab": f"{sewage_age_days}d old" if sewage_age_days is not None else "Endpoint returns no data",
        "wsd_water_suspension": "Live at build time" if water_available else "Endpoint returns no data",
    }
    type_by_source = {
        "wsd_water_suspension": "Event",
    }
    source_status_by_id = {
        source_id: "Healthy" if record_counts[source_id] > 0 else "Degraded"
        for source_id in record_counts
    }

    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": artifact["package_info"]["dataAsOf"],
        "overall_status": "Healthy" if all(value == "Healthy" for value in source_status_by_id.values()) else "Degraded",
        "live_sources": len(PUBLIC_SOURCES),
        "planned_sources": 0,
        "sources": [
            {
                "source": s["label"],
                "dataset": s["id"],
                "type": type_by_source.get(s["id"], "Measure"),
                "status": source_status_by_id[s["id"]],
                "latest_observation": latest_observation_dates[s["id"]],
                "records": record_counts[s["id"]],
                "freshness": freshness_by_source[s["id"]],
                "notes": s["query"]["description"],
            }
            for s in PUBLIC_SOURCES.values()
        ],
        "attachment_filename": f"hk-utilities-dashboard-{now.date().isoformat()}.html",
    }

    return artifact, status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--status-output", type=Path, required=True)
    args = parser.parse_args()

    artifact, status = build_artifact()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.status_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, separators=(",", ":"), default=str), encoding="utf-8")
    args.status_output.write_text(json.dumps(status, separators=(",", ":"), default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "artifact": str(args.output), "snapshot_id": status["snapshot_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
