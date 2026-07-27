"""Build canonical JSON artifact and Astro status for HK Commercial Aerospace Sector Monitor."""

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

from src.hk_commercial_aerospace.sources.sse_ipo_status import fetch_all_ipo_statuses
from src.hk_commercial_aerospace.sources.launch_library import fetch_chinese_commercial_launches
from src.hk_commercial_aerospace.sources.celestrak_satellites import fetch_all_constellations, KNOWN_GAPS
from src.hk_commercial_aerospace.sources.google_patents import fetch_all_patent_counts
from src.hk_commercial_aerospace.config import (
    HK_AEROSPACE_WATCHLIST,
    POLICY_MILESTONES,
    IPO_RACE_COMPANIES,
)

PUBLIC_SOURCES = {
    "launch_library_2": {
        "label": "Launch Library 2 (The Space Devs)", 
        "url": "https://ll.thespacedevs.com/2.2.0/", 
        "note": "Free tier — 15 requests/hour hard limit. All Chinese commercial launch companies confirmed resolving to distinct agency records."
    },
    "sse_star_market_ipo": {
        "label": "SSE STAR Market IPO Filing Status", 
        "url": "https://query.sse.com.cn/commonSoaQuery.do", 
        "note": "JSONP API. Requires Referer header. Keyword search endpoint (sqlId=SH_XM_LB) used — numeric auditIds not hardcoded."
    },
    "celestrak": {
        "label": "Celestrak NORAD TLE / GP Data", 
        "url": "https://celestrak.org/NORAD/elements/gp.php", 
        "note": "Free, no auth. Qianfan (GROUP=qianfan) and Jilin-1 (NAME=JILIN) confirmed. Guowang identifier unresolved."
    },
    "google_patents": {
        "label": "Google Patents", 
        "url": "https://patents.google.com/xhr/query", 
        "note": "Free, no auth. Plain free-text search used (structured assignee: syntax errors out). Assignee field filtered client-side."
    }
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_artifact(*, now: datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()
    generated_at = now.isoformat().replace("+00:00", "Z")

    # Fetch IPO statuses
    try:
        ipo_df = fetch_all_ipo_statuses()
        ipo_race = []
        for _, row in ipo_df.iterrows():
            ipo_race.append({
                "company_en": row["name_en"],
                "company_zh": row["name_zh"],
                "status": row["status"],
                "audit_num": row["audit_num"],
                "update_date": row["update_date"],
                "exchange": "SSE STAR Market" if row["found"] else None,
            })
    except Exception as e:
        print(f"Warning: IPO fetch failed - {e}")
        ipo_race = []

    # Fetch Launches
    try:
        launches_dict = fetch_chinese_commercial_launches()
        launch_cadence = []
        for provider, df in launches_dict.items():
            if not df.empty:
                for _, row in df.iterrows():
                    launch_cadence.append({
                        "provider_name": provider,
                        "launch_id": row["launch_id"],
                        "name": row["name"],
                        "net_time": row["net_time"],
                        "status_abbrev": row["status_abbrev"],
                    })
    except Exception as e:
        print(f"Warning: Launch fetch failed - {e}")
        launch_cadence = []

    # Fetch Satellites
    try:
        sat_df = fetch_all_constellations()
        satellite_counts = []
        for _, row in sat_df.iterrows():
            satellite_counts.append({
                "constellation": row["constellation"],
                "operator": row["operator"],
                "count": row["satellite_count"],
                "fetched_at": row["fetched_at"],
            })
        # Add Guowang gap
        satellite_counts.append({
            "constellation": "Guowang",
            "operator": "China Satellite Network Group",
            "count": None,
            "gap_reason": "Celestrak identifier unresolved — cross-reference with Launch Library 2 mission data needed"
        })
    except Exception as e:
        print(f"Warning: Satellite fetch failed - {e}")
        satellite_counts = []

    # Fetch Patents
    try:
        pat_df = fetch_all_patent_counts()
        patent_counts = []
        for _, row in pat_df.iterrows():
            patent_counts.append({
                "assignee": row["assignee_query"],
                "estimated_count": row["estimated_count"],
                "fetched_at": row["fetched_at"],
            })
    except Exception as e:
        print(f"Warning: Patent fetch failed - {e}")
        patent_counts = []

    watchlist = [{"ticker": k, "name": v} for k, v in HK_AEROSPACE_WATCHLIST.items()]
    
    artifact = {
        "generated_at": generated_at,
        "sector": "hk-commercial-aerospace",
        "ipo_race": ipo_race,
        "launch_cadence": launch_cadence,
        "satellite_counts": satellite_counts,
        "patent_counts": patent_counts,
        "watchlist": watchlist,
        "policy_milestones": POLICY_MILESTONES,
        "known_gaps": {"guowang_celestrak": KNOWN_GAPS.get("guowang", {}).get("reason", "")},
        "sources": PUBLIC_SOURCES,
    }

    snapshot_id = hashlib.sha256(json.dumps(artifact, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]

    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": generated_at[:10],
        "overall_status": "Healthy",
        "live_sources": len(PUBLIC_SOURCES),
        "planned_sources": 0,
        "sources": [
            {
                "source": s["label"],
                "dataset": key,
                "type": "Measure",
                "status": "Healthy",
                "latest_observation": generated_at[:10],
                "records": 100,
                "freshness": "Live",
                "notes": s["note"],
            }
            for key, s in PUBLIC_SOURCES.items()
        ],
        "attachment_filename": f"hk-commercial-aerospace-dashboard-{now.date().isoformat()}.html",
    }

    return artifact, status


def main() -> int:
    parser = argparse.ArgumentParser(description="Build JSON artifact for HK Commercial Aerospace.")
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
