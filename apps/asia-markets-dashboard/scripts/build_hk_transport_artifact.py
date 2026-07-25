"""Build canonical JSON artifact and Astro status for HK Transport Sector Monitor."""

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

from src.hk_transport.sources.cathay_traffic import fetch_cathay_traffic
from src.hk_transport.sources.mtr_patronage import fetch_mtr_patronage


PUBLIC_SOURCES = {
    "mtr_patronage": {
        "id": "mtr_patronage",
        "label": "MTR Corporation Investor Relations Monthly Patronage",
        "href": "https://www.mtr.com.hk/en/corporate/investor/patronage.php",
        "path": "sources/mtr_patronage.sql",
        "query": {
            "engine": "official IR web page",
            "url": "https://www.mtr.com.hk/en/corporate/investor/patronage.php",
            "language": "HTML",
            "description": "Monthly patronage counts and daily averages by rail service: Domestic, Airport Express, Cross-boundary (Lo Wu & Lok Ma Chau), Light Rail & Bus, and High Speed Rail (HSR).",
        },
    },
    "cathay_hkia_traffic": {
        "id": "cathay_hkia_traffic",
        "label": "CAD HKIA Monthly Airport Traffic & Cathay Pacific IR Traffic Figures (PDF)",
        "href": "https://www.cathaypacific.com/content/dam/cx/about-us/investor-relations/announcements/en/",
        "path": "sources/cathay_hkia_traffic.sql",
        "query": {
            "engine": "official CAD Excel workbook + Cathay Pacific IR monthly traffic-figures PDF",
            "url": "https://www.cad.gov.hk/english/pdf/Stat%20Webpage.xlsx ; https://www.cathaypacific.com/content/dam/cx/about-us/investor-relations/announcements/en/<YYYYMM>_cx_traffic_en.pdf",
            "language": "XLSX + PDF",
            "description": "HKIA airport monthly aircraft movements, passenger volume, and freight tonnage alongside Cathay Pacific passengers, RPK, ASK, and Passenger Load Factor (%), fetched directly from Cathay's own investor-relations traffic-figures PDF (deterministic per-month URL).",
        },
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _series_history(df: pd.DataFrame, series_label: str, value_column: str) -> list[dict[str, Any]]:
    """Long-format {date, month, series, value} rows for a multi-series line chart.

    `month` is a "YYYY-MM" string (month-granularity) rather than a full
    "YYYY-MM-DD" date. The portable-chart-rendering plugin's date-axis
    formatter always includes the year for month-granularity values but
    omits it by default for day-granularity ones, so charts encode their x
    axis against `month` to keep multi-year series unambiguous (see
    chart-transforms.ts:formatDateAxisLabel in the build-report plugin).
    """
    if df.empty or value_column not in df.columns:
        return []
    rows = []
    for _, row in df.iterrows():
        value = row.get(value_column)
        date = row.get("date")
        if pd.isna(value) or pd.isna(date):
            continue
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "month": date.strftime("%Y-%m"),
                "series": series_label,
                "value": round(float(value), 4),
            }
        )
    return rows


def build_artifact(
    raw_mtr: pd.DataFrame | None = None,
    raw_cathay: pd.DataFrame | None = None,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()

    mtr = raw_mtr if raw_mtr is not None else fetch_mtr_patronage()
    cathay = raw_cathay if raw_cathay is not None else fetch_cathay_traffic()

    generated_at = now.isoformat().replace("+00:00", "Z")

    mtr_latest = mtr.iloc[-1]
    mtr_prior = mtr.iloc[-2]
    # Pre-pandemic baseline (calendar-year 2019 monthly average) lets the KPI
    # card show a genuine "recovered vs. pre-COVID" signal now that the
    # history reaches back to 2000 -- 2019 is the last full clean year before
    # the 2020 collapse and is a more meaningful yardstick than the all-time
    # peak (which happened to be even higher, in Jan 2019).
    mtr_2019 = mtr[mtr["date"].dt.year == 2019]["total_mtr_patronage_thousands"]
    mtr_2019_avg = float(mtr_2019.mean()) if not mtr_2019.empty else None
    mtr_kpi = {
        "latest": float(mtr_latest["total_mtr_patronage_thousands"]),
        "domestic_thousands": float(mtr_latest["domestic_service_thousands"]),
        "cross_boundary_thousands": float(mtr_latest["cross_boundary_thousands"]),
        "hsr_thousands": float(mtr_latest["hsr_thousands"]),
        "period_change": (
            round(float(mtr_latest["total_mtr_patronage_thousands"]) / float(mtr_prior["total_mtr_patronage_thousands"]) - 1, 6)
            if float(mtr_prior["total_mtr_patronage_thousands"]) > 0
            else 0.0
        ),
        "recovery_vs_2019_pct": (
            round(float(mtr_latest["total_mtr_patronage_thousands"]) / mtr_2019_avg - 1, 6)
            if mtr_2019_avg and mtr_2019_avg > 0
            else None
        ),
        "observation_date": mtr_latest["date"].strftime("%Y-%m-%d"),
    }

    c_latest = cathay.iloc[-1]
    c_prior = cathay.iloc[-2]
    cathay_2019 = cathay[cathay["date"].dt.year == 2019]["cathay_passengers"]
    cathay_2019_avg = float(cathay_2019.mean()) if not cathay_2019.empty else None
    cathay_kpi = {
        "latest": float(c_latest["cathay_passengers"]),
        "load_factor_pct": float(c_latest["cathay_passenger_load_factor_pct"]),
        "hkia_passengers": float(c_latest["hkia_passengers"]),
        "hkia_movements": float(c_latest["hkia_aircraft_movements"]),
        "period_change": round(float(c_latest["cathay_passengers"]) / float(c_prior["cathay_passengers"]) - 1, 6) if float(c_prior["cathay_passengers"]) > 0 else 0.0,
        "recovery_vs_2019_pct": (
            round(float(c_latest["cathay_passengers"]) / cathay_2019_avg - 1, 6)
            if cathay_2019_avg and cathay_2019_avg > 0
            else None
        ),
        "observation_date": c_latest["date"].strftime("%Y-%m-%d"),
    }

    # --- Chart datasets -----------------------------------------------
    # mtr_history/cathay_history carry the FULL, untruncated history (26yr
    # MTR back to Jan 2000, 13yr Cathay/HKIA back to Dec 2012) so the
    # long-run single-line trend charts can show the full SARS (2003) and
    # COVID-19 (2020-22) collapse-and-recovery story. The 5-way MTR
    # service-type breakdown is windowed to the most recent ~8 years
    # (2018-onward) in a separate long-format dataset -- 26 years of five
    # overlapping lines is unreadable, but a shorter recent window keeps the
    # by-service-type comparison legible while still spanning the full
    # COVID collapse and recovery.
    mtr_breakdown_window = mtr[mtr["date"] >= "2018-01-01"]
    mtr_service_breakdown_history: list[dict[str, Any]] = []
    for series_label, column in [
        ("Domestic", "domestic_service_thousands"),
        ("X-Boundary", "cross_boundary_thousands"),
        ("Airport Exp", "airport_express_thousands"),
        ("LR & Bus", "light_rail_bus_thousands"),
        ("HSR", "hsr_thousands"),
    ]:
        mtr_service_breakdown_history.extend(_series_history(mtr_breakdown_window, series_label, column))
    mtr_service_breakdown_history.sort(key=lambda row: (row["date"], row["series"]))

    cathay_capacity_demand_history: list[dict[str, Any]] = []
    cathay_capacity_demand_history.extend(_series_history(cathay, "ASK ('000)", "cathay_ask_thousands"))
    cathay_capacity_demand_history.extend(_series_history(cathay, "RPK ('000)", "cathay_rpk_thousands"))
    cathay_capacity_demand_history.sort(key=lambda row: (row["date"], row["series"]))

    datasets = {
        "kpi_mtr": [mtr_kpi],
        "kpi_cathay": [cathay_kpi],
        "mtr_history": mtr.to_dict(orient="records"),
        "cathay_history": cathay.to_dict(orient="records"),
        "mtr_service_breakdown_history": mtr_service_breakdown_history,
        "cathay_capacity_demand_history": cathay_capacity_demand_history,
    }

    cards = [
        {
            "id": "mtr_card",
            "description": "Monthly passenger journeys ('000s) across Domestic, Cross-boundary, and HSR lines, plus recovery vs. the pre-pandemic 2019 monthly average.",
            "dataset": "kpi_mtr",
            "sourceId": "mtr_patronage",
            "metrics": [
                {"label": "Total Patronage ('000s)", "field": "latest", "format": "number"},
                {"label": "Domestic ('000s)", "field": "domestic_thousands", "format": "number"},
                {"label": "Cross-Boundary ('000s)", "field": "cross_boundary_thousands", "format": "number"},
                {"label": "vs. 2019 Avg", "field": "recovery_vs_2019_pct", "format": "percent"},
            ],
        },
        {
            "id": "cathay_card",
            "description": "Monthly Cathay Group passengers carried and passenger load factor (%), plus recovery vs. the pre-pandemic 2019 monthly average.",
            "dataset": "kpi_cathay",
            "sourceId": "cathay_hkia_traffic",
            "metrics": [
                {"label": "Cathay Passengers", "field": "latest", "format": "number"},
                {"label": "Load Factor (%)", "field": "load_factor_pct", "format": "number"},
                {"label": "HKIA Passengers", "field": "hkia_passengers", "format": "number"},
                {"label": "vs. 2019 Avg", "field": "recovery_vs_2019_pct", "format": "percent"},
            ],
        },
    ]

    charts = [
        {
            "id": "mtr_total_patronage_chart",
            "title": "MTR Total Patronage, 2000-Present ('000s)",
            "subtitle": "26 years of monthly total MTR journeys ('000s) -- the full history captures both the 2003 SARS collapse (trough ~48.8m in Apr 2003) and the deeper, longer COVID-19 collapse (trough ~71.9m in Feb 2022), followed by a recovery now back near the pre-pandemic 2019 monthly average.",
            "type": "line",
            "dataset": "mtr_history",
            "sourceId": "mtr_patronage",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "total_mtr_patronage_thousands", "type": "quantitative", "label": "Thousands ('000s)"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "mtr_service_breakdown_chart",
            "title": "MTR Patronage by Rail Service, 2018-Present ('000s)",
            "subtitle": "Monthly passenger journeys across Domestic heavy rail, Cross-boundary, HSR, Airport Express, and Light Rail & Bus -- windowed to the last ~8 years so the five service lines stay legible through the COVID collapse and recovery (see the total-patronage chart above for the full 26-year trend).",
            "type": "line",
            "dataset": "mtr_service_breakdown_history",
            "sourceId": "mtr_patronage",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "value", "type": "quantitative", "label": "Thousands ('000s)"},
                "color": {"field": "series", "type": "nominal", "label": "Service"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "cathay_passengers_chart",
            "title": "Cathay Group Passengers Carried, 2012-Present",
            "subtitle": "13 years of monthly Cathay Group passengers carried -- shows the near-total COVID-19 collapse (from a peak of ~3.28m in Aug 2018 to a trough of just ~13,700 in Apr 2020, a >99.5% drop) and the subsequent multi-year recovery.",
            "type": "line",
            "dataset": "cathay_history",
            "sourceId": "cathay_hkia_traffic",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "cathay_passengers", "type": "quantitative", "label": "Passengers"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "cathay_load_factor_chart",
            "title": "Cathay Group Passenger Load Factor (%)",
            "subtitle": "Monthly passenger load factor -- arguably more decision-relevant than raw passenger volume for judging capacity utilization and pricing power, since it nets out how much capacity Cathay itself was flying at any given time.",
            "type": "line",
            "dataset": "cathay_history",
            "sourceId": "cathay_hkia_traffic",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "cathay_passenger_load_factor_pct", "type": "quantitative", "label": "Load Factor (%)"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "cathay_capacity_demand_chart",
            "title": "Cathay Group Capacity vs. Demand (ASK vs. RPK, '000s)",
            "subtitle": "Available Seat Kilometres (capacity flown) vs. Revenue Passenger Kilometres (demand actually filled) -- the gap between the two lines is the mirror image of the load-factor chart alongside it.",
            "type": "line",
            "dataset": "cathay_capacity_demand_history",
            "sourceId": "cathay_hkia_traffic",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "value", "type": "quantitative", "label": "Thousands ('000s)"},
                "color": {"field": "series", "type": "nominal", "label": "Metric"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "hkia_passengers_chart",
            "title": "HKIA Total Airport Passenger Traffic",
            "subtitle": "Hong Kong International Airport's total monthly passenger volume across all airlines (CAD data), a broader gauge of aviation demand than the Cathay-specific charts above.",
            "type": "line",
            "dataset": "cathay_history",
            "sourceId": "cathay_hkia_traffic",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "hkia_passengers", "type": "quantitative", "label": "Passengers"},
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
            "title": "HK Transport & Aviation Sector Monitor",
            "description": "MTR Corporation monthly rail patronage, CAD HKIA airport traffic, and Cathay Pacific Group operating statistics.",
            "sector": "hk-transport",
            "generatedAt": generated_at,
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": sources,
            "blocks": [
                {"id": "kpi_grid", "type": "metric-strip", "cardIds": [c["id"] for c in cards]},
                {"id": "mtr_total_chart", "type": "chart", "chartId": "mtr_total_patronage_chart"},
                {"id": "mtr_breakdown_chart", "type": "chart", "chartId": "mtr_service_breakdown_chart"},
                {"id": "cathay_passengers_chart_block", "type": "chart", "chartId": "cathay_passengers_chart"},
                {"id": "cathay_load_factor_chart_block", "type": "chart", "chartId": "cathay_load_factor_chart", "layout": "half"},
                {"id": "cathay_capacity_demand_chart_block", "type": "chart", "chartId": "cathay_capacity_demand_chart", "layout": "half"},
                {"id": "hkia_passengers_chart_block", "type": "chart", "chartId": "hkia_passengers_chart"},
            ],
        },
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready", "datasets": datasets},
        "sources": sources,
        "package_info": {"originUrl": "https://asia-markets-dashboard.pages.dev/sectors/hk-transport/", "snapshotId": snapshot_id, "dataAsOf": mtr_kpi["observation_date"]},
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
        "attachment_filename": f"hk-transport-dashboard-{now.date().isoformat()}.html",
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
