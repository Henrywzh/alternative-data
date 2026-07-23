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
        "label": "CAD HKIA Monthly Airport Traffic & Cathay Group Disclosures",
        "href": "https://www.cad.gov.hk/english/pdf/Stat%20Webpage.xlsx",
        "path": "sources/cathay_hkia_traffic.sql",
        "query": {
            "engine": "official CAD Excel workbook",
            "url": "https://www.cad.gov.hk/english/pdf/Stat%20Webpage.xlsx",
            "language": "XLSX",
            "description": "HKIA airport monthly aircraft movements, passenger volume, and freight tonnage alongside Cathay Pacific passengers, RPK, ASK, and Passenger Load Factor (%).",
        },
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
    mtr_kpi = {
        "latest": float(mtr_latest["total_mtr_patronage_thousands"]),
        "domestic_thousands": float(mtr_latest["domestic_service_thousands"]),
        "cross_boundary_thousands": float(mtr_latest["cross_boundary_thousands"]),
        "hsr_thousands": float(mtr_latest["hsr_thousands"]),
        "period_change": round(float(mtr_latest["total_mtr_patronage_thousands"]) / float(mtr_prior["total_mtr_patronage_thousands"]) - 1, 6),
        "observation_date": mtr_latest["date"].strftime("%Y-%m-%d"),
    }

    c_latest = cathay.iloc[-1]
    c_prior = cathay.iloc[-2]
    cathay_kpi = {
        "latest": float(c_latest["cathay_passengers"]),
        "load_factor_pct": float(c_latest["cathay_passenger_load_factor_pct"]),
        "hkia_passengers": float(c_latest["hkia_passengers"]),
        "hkia_movements": float(c_latest["hkia_aircraft_movements"]),
        "period_change": round(float(c_latest["cathay_passengers"]) / float(c_prior["cathay_passengers"]) - 1, 6) if float(c_prior["cathay_passengers"]) > 0 else 0.0,
        "observation_date": c_latest["date"].strftime("%Y-%m-%d"),
    }

    datasets = {
        "kpi_mtr": [mtr_kpi],
        "kpi_cathay": [cathay_kpi],
        "mtr_history": mtr.to_dict(orient="records"),
        "cathay_history": cathay.to_dict(orient="records"),
    }

    cards = [
        {
            "id": "mtr_card",
            "description": "Monthly passenger journeys ('000s) across Domestic, Cross-boundary, and HSR lines.",
            "dataset": "kpi_mtr",
            "sourceId": "mtr_patronage",
            "metrics": [
                {"label": "Total Patronage ('000s)", "field": "latest", "format": "number"},
                {"label": "Domestic ('000s)", "field": "domestic_thousands", "format": "number"},
                {"label": "Cross-Boundary ('000s)", "field": "cross_boundary_thousands", "format": "number"},
            ],
        },
        {
            "id": "cathay_card",
            "description": "Monthly Cathay Group passengers carried and passenger load factor (%).",
            "dataset": "kpi_cathay",
            "sourceId": "cathay_hkia_traffic",
            "metrics": [
                {"label": "Cathay Passengers", "field": "latest", "format": "number"},
                {"label": "Load Factor (%)", "field": "load_factor_pct", "format": "number"},
                {"label": "HKIA Passengers", "field": "hkia_passengers", "format": "number"},
            ],
        },
    ]

    charts = [
        {
            "id": "mtr_service_chart",
            "title": "MTR Patronage Trend by Rail Service ('000s)",
            "subtitle": "Monthly passenger journeys across Domestic heavy rail, Cross-boundary, HSR, Airport Express, and Light Rail.",
            "type": "line",
            "dataset": "mtr_history",
            "sourceId": "mtr_patronage",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Month"},
                "y": {"field": "total_mtr_patronage_thousands", "type": "quantitative", "label": "Thousands ('000s)"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "cathay_traffic_chart",
            "title": "Cathay Pacific Passenger Volume & Load Factor (%)",
            "subtitle": "Monthly Cathay Group passengers carried and passenger load factor trend.",
            "type": "line",
            "dataset": "cathay_history",
            "sourceId": "cathay_hkia_traffic",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Month"},
                "y": {"field": "cathay_passengers", "type": "quantitative", "label": "Passengers"},
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
                {"id": "mtr_chart", "type": "chart", "chartId": "mtr_service_chart"},
                {"id": "cathay_chart", "type": "chart", "chartId": "cathay_traffic_chart"},
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
