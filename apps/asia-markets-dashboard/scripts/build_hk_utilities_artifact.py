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

from src.hk_utilities.sources.clp_electricity import fetch_clp_electricity
from src.hk_utilities.sources.hko_temperature import fetch_hko_temperature
from src.hk_utilities.sources.power_assets_segments import fetch_power_assets_segments
from src.hk_utilities.sources.towngas_proxy import fetch_towngas_proxy


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


def build_artifact(
    raw_clp: pd.DataFrame | None = None,
    raw_towngas: pd.DataFrame | None = None,
    raw_temp: pd.DataFrame | None = None,
    raw_power_assets: pd.DataFrame | None = None,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()

    clp = raw_clp if raw_clp is not None else fetch_clp_electricity()
    towngas = raw_towngas if raw_towngas is not None else fetch_towngas_proxy()
    temp = raw_temp if raw_temp is not None else fetch_hko_temperature()
    power_assets = raw_power_assets if raw_power_assets is not None else fetch_power_assets_segments()

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
        "towngas_history": _records_json_safe(towngas.tail(60)),
        "towngas_type_history": (
            _series_history(towngas.tail(60), "Domestic", "domestic_gas_tj")
            + _series_history(towngas.tail(60), "Commercial", "commercial_gas_tj")
            + _series_history(towngas.tail(60), "Industrial", "industrial_gas_tj")
        ),
        "temp_history": _records_json_safe(temp.tail(180)),
        "power_assets_geography": pa_geography_rows,
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
            "subtitle": "Monthly gas consumption split by Domestic, Commercial, and Industrial user types.",
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
            "title": "Hong Kong Observatory Daily Mean Temperature (°C)",
            "subtitle": "Daily mean temperature history vs monthly averages.",
            "type": "line",
            "dataset": "temp_history",
            "sourceId": "hko_temperature",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "mean_temp_c", "type": "quantitative", "label": "°C"},
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
            "dataset": "power_assets_geography",
            "sourceId": "power_assets_segments",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "geography", "label": "Geography", "type": "text"},
                {"field": "revenue_hkdm", "label": "Segment Revenue (HK$m)", "format": "number"},
                {"field": "segment_profit_hkdm", "label": "Segment Profit (HK$m)", "format": "number"},
                {"field": "jv_associate_results_hkdm", "label": "JV/Associate Results (HK$m)", "format": "number"},
            ],
        }
    ]

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
            "description": "CLP quarterly electricity sales by customer sector, CenStatD town gas consumption, HKO temperature, and Power Assets geographic segment reporting.",
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
                {"id": "power_assets_table", "type": "table", "tableId": "power_assets_geography_table"},
            ],
        },
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready", "datasets": datasets},
        "sources": sources,
        "package_info": {"originUrl": "https://asia-markets-dashboard.pages.dev/sectors/hk-utilities/", "snapshotId": snapshot_id, "dataAsOf": clp_kpi["observation_date"]},
    }

    record_counts = {
        "clp_electricity": len(clp),
        "towngas_proxy": len(towngas),
        "hko_temperature": len(temp),
        "power_assets_segments": len(power_assets),
    }
    latest_observation_dates = {
        "clp_electricity": clp_kpi["observation_date"],
        "towngas_proxy": tg_kpi["observation_date"],
        "hko_temperature": temp_kpi["observation_date"],
        "power_assets_segments": pa_kpi["observation_date"],
    }

    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": artifact["package_info"]["dataAsOf"],
        "overall_status": "Healthy" if pa_available else "Degraded",
        "live_sources": len(PUBLIC_SOURCES),
        "planned_sources": 0,
        "sources": [
            {
                "source": s["label"],
                "dataset": s["id"],
                "type": "Measure",
                "status": "Healthy" if record_counts[s["id"]] > 0 else "Degraded",
                "latest_observation": latest_observation_dates[s["id"]],
                "records": record_counts[s["id"]],
                "freshness": "Live",
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
    args.output.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")
    args.status_output.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "artifact": str(args.output), "snapshot_id": status["snapshot_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
