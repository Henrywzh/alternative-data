"""Build canonical JSON artifact and Astro status for HK REIT Sector Monitor."""

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

from src.hk_reit.sources.reit_price import fetch_reit_spot_quotes, fetch_reit_price_history
from src.hk_reit.sources.linkreit_fundamentals import fetch_linkreit_fundamentals
from src.hk_reit.sources.championreit_fundamentals import fetch_championreit_fundamentals
from src.hk_reit.sources.fortunereit_fundamentals import fetch_fortunereit_fundamentals
from src.hk_reit.sources.prosperityreit_fundamentals import fetch_prosperityreit_fundamentals
from src.hk_reit.sources.sunlightreit_fundamentals import fetch_sunlightreit_fundamentals
from src.hk_reit.sources.regalreit_fundamentals import fetch_regalreit_fundamentals


PUBLIC_SOURCES = {
    "linkreit_fundamentals": {
        "id": "linkreit_fundamentals",
        "label": "Link REIT (0823.HK) Investor Relations Disclosures",
        "href": "https://www.linkreit.com/en/investor-relations/",
        "path": "sources/linkreit_fundamentals.sql",
        "query": {
            "engine": "official IR API",
            "url": "https://www.linkreit.com/en/investor-relations/",
            "language": "JSON",
            "description": "NAV per unit, DPU, Occupancy rate, and Rental Reversion rate for Link REIT.",
        },
    },
    "championreit_fundamentals": {
        "id": "championreit_fundamentals",
        "label": "Champion REIT (2778.HK) Financial Disclosures",
        "href": "https://www.championreit.com/en/investor-relations/",
        "path": "sources/championreit_fundamentals.sql",
        "query": {
            "engine": "official IR API",
            "url": "https://www.championreit.com/en/investor-relations/",
            "language": "JSON",
            "description": "Three Garden Road & Langham Place office/retail NAV/unit, DPU, occupancy, and reversion.",
        },
    },
    "fortunereit_fundamentals": {
        "id": "fortunereit_fundamentals",
        "label": "Fortune REIT (0778.HK) Financial Disclosures",
        "href": "https://www.fortunereit.com/en/investor-relations/",
        "path": "sources/fortunereit_fundamentals.sql",
        "query": {
            "engine": "official IR API",
            "url": "https://www.fortunereit.com/en/investor-relations/",
            "language": "JSON",
            "description": "Suburban HK retail portfolio NAV/unit, DPU, occupancy, and rental reversion.",
        },
    },
    "prosperityreit_fundamentals": {
        "id": "prosperityreit_fundamentals",
        "label": "Prosperity REIT (0808.HK) Financial Disclosures",
        "href": "https://www.prosperityreit.com/en/investor-relations/",
        "path": "sources/prosperityreit_fundamentals.sql",
        "query": {
            "engine": "official IR API",
            "url": "https://www.prosperityreit.com/en/investor-relations/",
            "language": "JSON",
            "description": "Decentralized office and industrial portfolio NAV/unit, DPU, occupancy, and reversion.",
        },
    },
    "sunlightreit_fundamentals": {
        "id": "sunlightreit_fundamentals",
        "label": "Sunlight REIT (0435.HK) Financial Disclosures",
        "href": "https://www.sunlightreit.com/en/investor-relations/",
        "path": "sources/sunlightreit_fundamentals.sql",
        "query": {
            "engine": "official IR API",
            "url": "https://www.sunlightreit.com/en/investor-relations/",
            "language": "JSON",
            "description": "Office and retail portfolio NAV/unit, DPU, occupancy, and rental reversion.",
        },
    },
    "regalreit_fundamentals": {
        "id": "regalreit_fundamentals",
        "label": "Regal REIT (1881.HK) Hotel Performance Disclosures",
        "href": "https://www.regalreit.com/en/investor-relations/",
        "path": "sources/regalreit_fundamentals.sql",
        "query": {
            "engine": "official IR API",
            "url": "https://www.regalreit.com/en/investor-relations/",
            "language": "JSON",
            "description": "Hotel portfolio KPIs: Occupancy (%), Average Daily Rate (ADR HKD), RevPAR (HKD), DPU, and NAV/unit.",
        },
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _records_json_safe(frame: pd.DataFrame) -> list[dict[str, Any]]:
    selected = frame.copy()
    for column in selected.columns:
        if pd.api.types.is_datetime64_any_dtype(selected[column]):
            selected[column] = selected[column].dt.strftime("%Y-%m-%d")
    return json.loads(selected.to_json(orient="records", date_format="iso"))


def build_artifact(
    raw_link: pd.DataFrame | None = None,
    raw_champion: pd.DataFrame | None = None,
    raw_fortune: pd.DataFrame | None = None,
    raw_prosperity: pd.DataFrame | None = None,
    raw_sunlight: pd.DataFrame | None = None,
    raw_regal: pd.DataFrame | None = None,
    raw_spot: pd.DataFrame | None = None,
) -> dict[str, Any]:
    generated_at = _utc_now()
    datestr = generated_at.strftime("%Y%m%d_%H%M%S")

    df_link = raw_link if raw_link is not None else fetch_linkreit_fundamentals()
    df_champion = raw_champion if raw_champion is not None else fetch_championreit_fundamentals()
    df_fortune = raw_fortune if raw_fortune is not None else fetch_fortunereit_fundamentals()
    df_prosperity = raw_prosperity if raw_prosperity is not None else fetch_prosperityreit_fundamentals()
    df_sunlight = raw_sunlight if raw_sunlight is not None else fetch_sunlightreit_fundamentals()
    df_regal = raw_regal if raw_regal is not None else fetch_regalreit_fundamentals()

    # Determine dates and source statuses
    datasets = {
        "linkreit_fundamentals": df_link,
        "championreit_fundamentals": df_champion,
        "fortunereit_fundamentals": df_fortune,
        "prosperityreit_fundamentals": df_prosperity,
        "sunlightreit_fundamentals": df_sunlight,
        "regalreit_fundamentals": df_regal,
    }

    live_count = sum(1 for df in datasets.values() if not df.empty)
    latest_dates = [df["date"].max() for df in datasets.values() if not df.empty and "date" in df.columns]
    data_as_of = max(latest_dates) if latest_dates else generated_at.strftime("%Y-%m-%d")

    status_entries = []
    for key, spec in PUBLIC_SOURCES.items():
        df = datasets.get(key, pd.DataFrame())
        st = "success" if not df.empty else "empty"
        rec_count = len(df)
        max_date = df["date"].max() if not df.empty and "date" in df.columns else None
        status_entries.append({
            "source_id": key,
            "label": spec["label"],
            "status": st,
            "records": rec_count,
            "latest_observation": max_date,
            "freshness": "live" if st == "success" else "stale/unreachable",
            "notes": spec["query"]["description"]
        })

    snapshot_hash = hashlib.sha256(f"hk_reit_{datestr}".encode("utf-8")).hexdigest()[:12]
    snapshot_id = f"hk_reit_{datestr}_{snapshot_hash}"

    manifest_sources = [
        {
            "id": source["id"],
            "label": source["label"],
            "href": source["href"],
            "path": source["path"],
            "query": source.get("query"),
        }
        for source in PUBLIC_SOURCES.values()
    ]

    artifact = {
        "surface": "dashboard",
        "package_info": {
            "sector_id": "hk-reit",
            "sector_name": "Hong Kong REITs Sector Monitor",
            "snapshotId": snapshot_id,
            "generatedAt": generated_at.isoformat(),
        },
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "Hong Kong REITs Sector Monitor",
            "description": "Fundamental disclosures and spot quote indicators for HK-listed REITs.",
            "generatedAt": generated_at.strftime("%Y-%m-%d %H:%M UTC"),
            "dataAsOf": data_as_of,
            "liveSourcesCount": live_count,
            "totalSourcesCount": len(PUBLIC_SOURCES),
            "cards": [],
            "charts": [],
            "tables": [],
            "sources": manifest_sources,
            "blocks": [],
        },
        "sources": manifest_sources,
        "source_health": status_entries,
        "data": {
            "linkreit": _records_json_safe(df_link),
            "championreit": _records_json_safe(df_champion),
            "fortunereit": _records_json_safe(df_fortune),
            "prosperityreit": _records_json_safe(df_prosperity),
            "sunlightreit": _records_json_safe(df_sunlight),
            "regalreit": _records_json_safe(df_regal),
        }
    }
    return artifact


def build_status_json(artifact: dict[str, Any]) -> dict[str, Any]:
    manifest = artifact["manifest"]
    return {
        "sector_id": "hk-reit",
        "sector_name": "Hong Kong REITs",
        "overall_status": "Healthy" if manifest["liveSourcesCount"] == manifest["totalSourcesCount"] else "Degraded",
        "live_sources": manifest["liveSourcesCount"],
        "planned_sources": 0,
        "data_as_of": manifest["dataAsOf"],
        "generated_at": manifest["generatedAt"],
        "sources": [
            {
                "source": entry["label"],
                "dataset": entry["source_id"],
                "type": "Measure",
                "status": "Healthy" if entry["status"] == "success" else "Degraded",
                "latest_observation": entry["latest_observation"] or "—",
                "records": entry["records"],
                "freshness": entry["freshness"],
                "notes": entry["notes"],
            }
            for entry in artifact["source_health"]
        ],
        "attachment_filename": "hk-reit-monitor.html",
    }


def main():
    parser = argparse.ArgumentParser(description="Build HK REIT sector dashboard artifact.")
    parser.add_argument("--output", default=".generated/hk-reit-artifact.json", help="Path to write JSON artifact.")
    parser.add_argument("--status-output", default="src/data/dashboard-status-hk-reit.json", help="Path to write status JSON.")
    args = parser.parse_args()

    artifact = build_artifact()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"Wrote HK REIT artifact to {out_path}")

    status_json = build_status_json(artifact)
    status_path = Path(args.status_output)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status_json, indent=2), encoding="utf-8")
    print(f"Wrote HK REIT status to {status_path}")


if __name__ == "__main__":
    main()
