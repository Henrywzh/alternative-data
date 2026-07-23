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
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_artifact(
    raw_clp: pd.DataFrame | None = None,
    raw_towngas: pd.DataFrame | None = None,
    raw_temp: pd.DataFrame | None = None,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()

    clp = raw_clp if raw_clp is not None else fetch_clp_electricity()
    towngas = raw_towngas if raw_towngas is not None else fetch_towngas_proxy()
    temp = raw_temp if raw_temp is not None else fetch_hko_temperature()

    generated_at = now.isoformat().replace("+00:00", "Z")

    clp_latest = clp.iloc[-1]
    clp_prior = clp.iloc[-2]
    clp_kpi = {
        "latest": float(clp_latest["total_local_gwh"]),
        "commercial_gwh": float(clp_latest["commercial_gwh"]),
        "ai_data_centre_yoy_pct": float(clp_latest["ai_data_centre_yoy_pct"]),
        "period_change": round(float(clp_latest["total_local_gwh"]) / float(clp_prior["total_local_gwh"]) - 1, 6),
        "observation_date": clp_latest["date"].strftime("%Y-%m-%d"),
    }

    tg_latest = towngas.iloc[-1]
    tg_prior = towngas.iloc[-2]
    tg_kpi = {
        "latest": float(tg_latest["total_gas_tj"]),
        "domestic_tj": float(tg_latest["domestic_gas_tj"]),
        "commercial_tj": float(tg_latest["commercial_gas_tj"]),
        "period_change": round(float(tg_latest["total_gas_tj"]) / float(tg_prior["total_gas_tj"]) - 1, 6),
        "observation_date": tg_latest["date"].strftime("%Y-%m-%d"),
    }

    temp_latest = temp.iloc[-1]
    temp_kpi = {
        "latest": float(temp_latest["mean_temp_c"]),
        "month_avg": float(temp_latest["month_avg_temp_c"]),
        "observation_date": temp_latest["date"].strftime("%Y-%m-%d"),
    }

    datasets = {
        "kpi_clp": [clp_kpi],
        "kpi_towngas": [tg_kpi],
        "kpi_temp": [temp_kpi],
        "clp_history": clp.to_dict(orient="records"),
        "towngas_history": towngas.tail(60).to_dict(orient="records"),
        "temp_history": temp.tail(180).to_dict(orient="records"),
    }

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
    ]

    charts = [
        {
            "id": "clp_sector_chart",
            "title": "CLP Electricity Sales by Sector (GWh)",
            "subtitle": "Quarterly sales across Residential, Commercial, Infrastructure & Public Services, and Manufacturing.",
            "type": "line",
            "dataset": "clp_history",
            "sourceId": "clp_electricity",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Quarter"},
                "y": {"field": "total_local_gwh", "type": "quantitative", "label": "GWh"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "towngas_trend_chart",
            "title": "Hong Kong Town Gas Consumption Trend (TJ)",
            "subtitle": "Monthly gas consumption split by Domestic, Commercial, and Industrial user types.",
            "type": "line",
            "dataset": "towngas_history",
            "sourceId": "towngas_proxy",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Month"},
                "y": {"field": "total_gas_tj", "type": "quantitative", "label": "Terajoules (TJ)"},
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

    tables: list[dict[str, Any]] = []

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
            "description": "CLP quarterly electricity sales by customer sector, CenStatD town gas consumption, and HKO temperature.",
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
            ],
        },
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready", "datasets": datasets},
        "sources": sources,
        "package_info": {"originUrl": "https://asia-markets-dashboard.pages.dev/sectors/hk-utilities/", "snapshotId": snapshot_id, "dataAsOf": clp_kpi["observation_date"]},
    }

    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": artifact["package_info"]["dataAsOf"],
        "overall_status": "Healthy",
        "live_sources": len(PUBLIC_SOURCES),
        "planned_sources": 0,
        "sources": [
            {
                "source": s["label"],
                "dataset": s["id"],
                "type": "Measure",
                "status": "Healthy",
                "latest_observation": artifact["package_info"]["dataAsOf"],
                "records": 100,
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
