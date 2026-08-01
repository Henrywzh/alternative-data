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
from src.hk_commercial_aerospace.sources.launch_library import (
    build_monthly_launch_summary,
    build_monthly_launch_total_summary,
    fetch_chinese_commercial_launches,
    fetch_state_launch_enrichment,
    fetch_upcoming_launches,
)
from src.hk_commercial_aerospace.sources.china_launch_records import (
    build_china_launch_monthly,
    build_rocket_family_summary,
    enrich_with_ll2,
    fetch_official_china_launches,
    persist_china_launch_history,
)
from src.hk_commercial_aerospace.sources.celestrak_satellites import (
    fetch_all_constellations,
    load_constellation_history,
)
from src.hk_commercial_aerospace.sources.google_patents import fetch_all_patent_counts
from src.hk_commercial_aerospace.sources.szse_ipo_status import fetch_aerospace_ipo_projects
from src.hk_commercial_aerospace.sources.faa_commercial_space import fetch_faa_commercial_space_kpis
from src.hk_commercial_aerospace.sources.usaspending import fetch_commercial_space_contracts
from src.hk_commercial_aerospace.sources.global_space_benchmark import fetch_global_objects_launched
from src.hk_commercial_aerospace.sources.global_object_catalog import (
    build_monthly_catalog_summary,
    fetch_celestrak_satcat,
    persist_monthly_summary,
)
from src.hk_commercial_aerospace.sources.wikimedia_pageviews import (
    build_agent_monthly_summary,
    build_agent_weekly_summary,
    build_latest_page_agent_summary,
    build_user_page_monthly_summary,
    fetch_wikipedia_aerospace_pageviews,
    fetch_wikipedia_aerospace_pageviews_daily,
)
from src.hk_commercial_aerospace.sources.sec_space_companies import fetch_sec_space_company_filings
from src.hk_commercial_aerospace.config import (
    HK_AEROSPACE_WATCHLIST,
    POLICY_MILESTONES,
    IPO_RACE_COMPANIES,
    CHINESE_LAUNCH_AGENCIES,
)

WIKIMEDIA_WEEKLY_ARTIFACT_WEEKS = 500

PUBLIC_SOURCES = {
    "sse_star_market_ipo": {
        "id": "sse_star_market_ipo",
        "label": "SSE STAR Market IPO Filing Status (JSONP)",
        "href": "https://www.sse.com.cn/",
        "path": "sources/sse_star_market_ipo.sql",
        "query": {
            "engine": "SSE commonSoaQuery SH_XM_LB",
            "url": "https://query.sse.com.cn/commonSoaQuery.do",
            "language": "JSONP",
            "sql": "SELECT company_en, company_zh, status, audit_num, update_date FROM sse_star_market_ipo;",
            "description": "Filing status, numeric audit numbers (stockAuditNum), and update dates for Chinese commercial launch companies.",
        },
    },
    "launch_library_2": {
        "id": "launch_library_2",
        "label": "Launch Library 2 (The Space Devs)",
        "href": "https://ll.thespacedevs.com/",
        "path": "sources/launch_library_2.sql",
        "query": {
            "engine": "The Space Devs REST API v2.2.0",
            "url": "https://ll.thespacedevs.com/2.2.0/launch/previous/",
            "language": "REST",
            "sql": "SELECT provider, launch_id, name, net_time, status_abbrev FROM launch_library_2;",
            "description": "Launch history for Chinese commercial launch providers (LandSpace, CAS Space, Galactic Energy, Space Pioneer, etc.).",
        },
    },
    "official_china_launch_records": {
        "id": "official_china_launch_records",
        "label": "CALT / CASC Official Chinese Launch Records",
        "href": "https://calt.spacechina.com/n482/n505/index.html",
        "path": "sources/china_launch_records.sql",
        "query": {
            "engine": "CALT launch-record archive plus CASC Long March table",
            "url": "https://calt.spacechina.com/n482/n505/index.html",
            "language": "HTML",
            "sql": "SELECT event_id, launch_date, rocket_name, payload_summary, launch_site, outcome FROM official_china_launch_records;",
            "description": "First-party Long March and Jielong event baseline; official records decide inclusion in the national/state-owned monthly series.",
        },
    },
    "launch_library_2_national_enrichment": {
        "id": "launch_library_2_national_enrichment",
        "label": "Launch Library 2 National/State Provider Enrichment",
        "href": "https://ll.thespacedevs.com/",
        "path": "sources/launch_library_2_national_enrichment.sql",
        "query": {
            "engine": "The Space Devs REST API v2.2.0",
            "url": "https://ll.thespacedevs.com/2.2.0/launch/previous/",
            "language": "REST",
            "sql": "SELECT launch_id, provider_name, net_time, rocket_name, pad_name, orbit_abbrev FROM launch_library_2_national_enrichment;",
            "description": "Structured fields for matching official Long March/Jielong events; LL2-only rows are never counted as official launches.",
        },
    },
    "celestrak": {
        "id": "celestrak",
        "label": "Celestrak NORAD TLE / GP Orbit Data",
        "href": "https://celestrak.org/",
        "path": "sources/celestrak_satellites.sql",
        "query": {
            "engine": "Celestrak GP API",
            "url": "https://celestrak.org/NORAD/elements/gp.php",
            "language": "JSON",
            "sql": "SELECT constellation, operator, satellite_count FROM celestrak_satellites;",
            "description": "Active satellite counts for Qianfan (G60) and Jilin-1 constellations.",
        },
    },
    "google_patents": {
        "id": "google_patents",
        "label": "Google Patents Search",
        "href": "https://patents.google.com/",
        "path": "sources/google_patents.sql",
        "query": {
            "engine": "Google Patents XHR Query",
            "url": "https://patents.google.com/xhr/query",
            "language": "JSON",
            "sql": "SELECT assignee, estimated_count FROM google_patents;",
            "description": "Estimated patent filing counts for Chinese commercial space companies.",
        },
    },
    "szse_aerospace_ipo": {
        "id": "szse_aerospace_ipo",
        "label": "SZSE ChiNext Aerospace-Industry IPO Projects",
        "href": "https://www.szse.cn/listing/projectdynamic/ipo/index.html",
        "path": "sources/szse_ipo_status.sql",
        "query": {
            "engine": "SZSE projectrends REST endpoint",
            "url": "https://listing.szse.cn/api/ras/projectrends/query",
            "language": "REST",
            "sql": "SELECT company_name, board, status, industry, update_date FROM szse_aerospace_ipo;",
            "description": "Current IPO projects classified by SZSE under rail, ship, aviation, aerospace and other transport equipment manufacturing.",
        },
    },
    "faa_commercial_space": {
        "id": "faa_commercial_space",
        "label": "FAA Commercial Space By the Numbers",
        "href": "https://www.faa.gov/node/52196",
        "path": "sources/faa_commercial_space.sql",
        "query": {
            "engine": "FAA official HTML KPI page",
            "url": "https://www.faa.gov/node/52196",
            "language": "HTML",
            "sql": "SELECT metric, value, observed_date FROM faa_commercial_space;",
            "description": "Cumulative licensed launches, reentries, spaceport licenses, experimental launches, safety approvals and active launch licenses.",
        },
    },
    "usaspending_contracts": {
        "id": "usaspending_contracts",
        "label": "USAspending Commercial Space Contracts",
        "href": "https://www.usaspending.gov/search",
        "path": "sources/usaspending.sql",
        "query": {
            "engine": "USAspending v2 spending_by_award",
            "url": "https://api.usaspending.gov/api/v2/search/spending_by_award/",
            "language": "REST",
            "sql": "SELECT award_id, recipient_name, award_amount, awarding_agency, description FROM usaspending_contracts;",
            "description": "Recent federal awards discovered using commercial-space, commercial-satellite and launch-services keywords.",
        },
    },
    "sec_space_company_filings": {
        "id": "sec_space_company_filings",
        "label": "SEC Commercial Space Company Filings",
        "href": "https://www.sec.gov/edgar/search/",
        "path": "sources/sec_space_companies.sql",
        "query": {
            "engine": "SEC submissions JSON",
            "url": "https://data.sec.gov/submissions/CIK{cik}.json",
            "language": "REST",
            "sql": "SELECT ticker, company_name, form, filing_date, primary_doc_description FROM sec_space_company_filings;",
            "description": "Official filing-event feed for Rocket Lab, AST SpaceMobile, Planet Labs, Intuitive Machines and Redwire; no inferred order amount.",
        },
    },
    "global_space_benchmark": {
        "id": "global_space_benchmark",
        "label": "Global Objects Launched into Space",
        "href": "https://ourworldindata.org/grapher/yearly-number-of-objects-launched-into-outer-space",
        "path": "sources/global_space_benchmark.sql",
        "query": {
            "engine": "UNOOSA data via Our World in Data CSV",
            "url": "https://ourworldindata.org/grapher/yearly-number-of-objects-launched-into-outer-space.csv",
            "language": "CSV",
            "sql": "SELECT entity, year, objects_launched FROM global_space_benchmark;",
            "description": "Annual objects launched for World, China and the United States. This is payload/object activity, not rocket launch count.",
        },
    },
    "global_object_catalog": {
        "id": "global_object_catalog",
        "label": "CelesTrak SATCAT Global Object Launch Catalog",
        "href": "https://celestrak.org/satcat/",
        "path": "sources/global_object_catalog.sql",
        "query": {
            "engine": "CelesTrak SATCAT CSV",
            "url": "https://celestrak.org/pub/satcat.csv",
            "language": "CSV",
            "sql": "SELECT launch_month, object_type, object_count FROM global_object_catalog_monthly;",
            "description": "Monthly counts derived from catalogued objects with known launch dates; payloads are closest to the UNOOSA object definition, while rocket bodies, debris and unknown objects remain separate.",
        },
    },
    "wikimedia_pageviews": {
        "id": "wikimedia_pageviews",
        "label": "Wikimedia Wikipedia Pageviews",
        "href": "https://pageviews.wmcloud.org/",
        "path": "sources/wikimedia_pageviews.sql",
        "query": {
            "engine": "Wikimedia Analytics Pageviews REST API",
            "url": "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article",
            "language": "REST",
            "sql": "SELECT page_id, agent, date, views FROM wikimedia_aerospace_pageviews_daily;",
            "description": "Daily English Wikipedia pageviews for a curated aerospace page basket, aggregated into monthly and complete Monday-Sunday weekly views; user, search-engine spider, automated and all-agent traffic remain separate.",
        },
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _latest_observation(rows: list[dict], field: str, fallback: str | None = None) -> str | None:
    values = [str(row.get(field, ""))[:10] for row in rows if row.get(field)]
    return max(values) if values else fallback


def _normalize_launch_outcome(value: object) -> str:
    text = str(value or "").lower()
    if any(token in text for token in ("success", "successful", "成功")):
        return "Success"
    if any(token in text for token in ("failure", "failed", "失利", "失败")):
        return "Failure"
    return "Unknown"


def _commercial_event_rows(launch_frame: pd.DataFrame) -> list[dict]:
    """Adapt existing exact-provider LL2 rows to the canonical event schema."""
    if launch_frame.empty:
        return []
    rows = []
    for row in launch_frame.to_dict(orient="records"):
        launch_id = str(row.get("launch_id") or "")
        if not launch_id:
            continue
        rows.append({
            "event_id": f"ll2-commercial-{launch_id}",
            "official_source_id": None,
            "official_sequence": None,
            "launch_date": row.get("date"),
            "launch_time": row.get("net_time"),
            "launch_time_precision": "timestamp" if row.get("net_time") else "date",
            "rocket_name": row.get("rocket_name"),
            "rocket_family": row.get("rocket_family") or row.get("rocket_name") or "Unknown",
            "rocket_variant": row.get("rocket_name"),
            "mission_name": row.get("name"),
            "launch_site": row.get("pad_name"),
            "launch_pad": row.get("pad_name"),
            "target_orbit": row.get("orbit"),
            "mission_type": row.get("mission_type"),
            "outcome": row.get("status_name") or row.get("status"),
            "outcome_normalized": _normalize_launch_outcome(row.get("status_name") or row.get("status")),
            "program_class": "commercial_provider",
            "classification_status": "verified",
            "payload_summary": row.get("name"),
            "payload_count": None,
            "official_source_url": None,
            "official_source_kind": None,
            "ll2_launch_id": launch_id,
            "ll2_match_status": "source_event",
            "ll2_match_confidence": "high",
            "ll2_provider_name": row.get("provider"),
            "source_snapshot": None,
            "fetched_at": row.get("fetched_at") or row.get("last_updated"),
            "parser_version": "ll2-commercial-adapter-v1",
        })
    return rows


def build_artifact(*, now: datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()
    generated_at = now.isoformat().replace("+00:00", "Z")
    data_as_of = now.strftime("%Y-%m-%d")

    empty_source_frame = pd.DataFrame()

    # 1. Fetch IPO status
    ipo_rows = []
    ipo_df = empty_source_frame
    szse_ipo_df = empty_source_frame
    landspace_status = "Unknown"
    landspace_audit = None
    cas_space_status = "Unknown"
    cas_space_audit = None

    try:
        ipo_df = fetch_all_ipo_statuses()
        if not ipo_df.empty:
            for _, row in ipo_df.iterrows():
                comp_en = row["name_en"]
                comp_zh = row["name_zh"]
                status = row["status"]
                audit_num = row["audit_num"]
                
                if comp_en == "LandSpace":
                    landspace_status = status
                    landspace_audit = audit_num
                elif comp_en == "CAS Space":
                    cas_space_status = status
                    cas_space_audit = audit_num

                ipo_rows.append({
                    "company_en": comp_en,
                    "company_zh": comp_zh,
                    "status": status,
                    "audit_num": audit_num if audit_num is not None else None,
                    "update_date": row["update_date"] if row["update_date"] else None,
                    "exchange": "SSE STAR Market" if row["found"] else "N/A",
                })
    except Exception as e:
        print(f"Warning: IPO fetch failed - {e}")
        for comp in IPO_RACE_COMPANIES:
            ipo_rows.append({
                "company_en": comp["name_en"],
                "company_zh": comp["name_zh"],
                "status": comp.get("known_status", "no_shanghai_filing"),
                "audit_num": comp.get("audit_num"),
                "update_date": comp.get("update_date"),
                "exchange": "SSE STAR Market" if comp.get("audit_num") else "N/A",
            })

    # 1b. Fetch SZSE aerospace-industry IPO projects.
    szse_ipo_rows = []
    try:
        szse_ipo_df = fetch_aerospace_ipo_projects()
        if not szse_ipo_df.empty:
            szse_ipo_rows = szse_ipo_df.to_dict(orient="records")
    except Exception as e:
        print(f"Warning: SZSE IPO fetch failed - {e}")

    # 2. Fetch Launches
    launch_rows = []
    total_launches = 0
    launch_source = "unavailable"
    try:
        launches_dict = fetch_chinese_commercial_launches()
        launch_sources = {
            frame.attrs.get("source", "unavailable")
            for frame in launches_dict.values()
        }
        if "live" in launch_sources:
            launch_source = "live"
        elif "cache" in launch_sources:
            launch_source = "cache"
        elif "history" in launch_sources:
            launch_source = "history"

        for provider, df in launches_dict.items():
            if not df.empty:
                for _, row in df.iterrows():
                    net_str = str(row.get("net_time", ""))
                    year_str = net_str[:4] if len(net_str) >= 4 else "2025"
                    year_month = net_str[:7] if len(net_str) >= 7 else "2025-01"
                    launch_rows.append({
                        "provider": provider,
                        "launch_id": row["launch_id"],
                        "name": row["name"],
                        "date": net_str[:10] if len(net_str) >= 10 else net_str,
                        "net_time": net_str,
                        "month": year_month,
                        "year": year_str,
                        "status": row["status_abbrev"],
                        "status_name": row.get("status_name"),
                        "provider_id": row.get("provider_id"),
                        "rocket_name": row.get("rocket_name"),
                        "rocket_family": row.get("rocket_family"),
                        "pad_name": row.get("pad_name"),
                        "orbit": row.get("orbit_abbrev"),
                        "mission_type": row.get("mission_type"),
                        "launch_designator": row.get("launch_designator"),
                        "country_code": row.get("country_code"),
                        "last_updated": row.get("last_updated"),
                        "fetched_at": row.get("fetched_at"),
                    })
                    total_launches += 1
    except Exception as e:
        print(f"Warning: Launch fetch failed - {e}")

    # 2b. Fetch Upcoming Launch Calendar
    upcoming_rows = []
    upcoming_source = "unavailable"
    try:
        up_df = fetch_upcoming_launches(100)
        upcoming_source = up_df.attrs.get("source", "live")
        if not up_df.empty:
            cn_keywords = ['China', 'CASC', 'LandSpace', 'Space Pioneer', 'Galactic Energy', 'CAS Space', 'Orienspace', 'i-Space', 'ExPace', 'Shanghai Spacecom']
            pattern = '|'.join(cn_keywords)
            cn_up = up_df[
                up_df['provider_name'].str.contains(pattern, case=False, na=False) |
                up_df['name'].str.contains(pattern, case=False, na=False)
            ]
            for _, r in cn_up.head(10).iterrows():
                net_raw = str(r.get("net_time", ""))
                net_date = net_raw[:10] if len(net_raw) >= 10 else net_raw
                upcoming_rows.append({
                    "net_date": net_date,
                    "provider": str(r.get("provider_name", "Unknown")),
                    "mission": str(r.get("name", "Unknown Mission")),
                    "pad_name": str(r.get("pad_name", "N/A")),
                    "orbit": str(r.get("orbit_abbrev")) if r.get("orbit_abbrev") else "N/A",
                    "status": str(r.get("status_name", "Scheduled")),
                })
    except Exception as e:
        print(f"Warning: Upcoming launch fetch failed - {e}")

    launch_frame = pd.DataFrame(launch_rows)
    if not launch_frame.empty:
        launch_frame = launch_frame.drop_duplicates("launch_id")
        total_launches = len(launch_frame)

    launch_monthly_df = build_monthly_launch_summary(
        pd.DataFrame([
            {
                "launch_id": row.get("launch_id"),
                "net_time": row.get("date"),
                "provider_name": row.get("provider"),
                "status_abbrev": row.get("status"),
            }
            for row in (launch_frame.to_dict(orient="records") if not launch_frame.empty else [])
        ])
    )
    launch_monthly_total_df = build_monthly_launch_total_summary(
        pd.DataFrame([
            {
                "launch_id": row.get("launch_id"),
                "net_time": row.get("date"),
                "provider_name": row.get("provider"),
                "status_abbrev": row.get("status"),
            }
            for row in (launch_frame.to_dict(orient="records") if not launch_frame.empty else [])
        ])
    )

    # 2a. Fetch the first-party Long March/Jielong baseline, then enrich only
    # those verified events with structured LL2 fields. Official rows remain
    # the inclusion authority; LL2-only rows are never added here.
    official_launch_df = empty_source_frame
    official_launch_source = "unavailable"
    state_enrichment_df = empty_source_frame
    state_enrichment_source = "unavailable"
    canonical_official_df = empty_source_frame
    try:
        official_launch_df = fetch_official_china_launches()
        official_launch_source = official_launch_df.attrs.get("source", "unavailable")
    except Exception as e:
        print(f"Warning: Official China launch-record fetch failed - {e}")
    try:
        state_enrichment_df = fetch_state_launch_enrichment()
        state_enrichment_source = state_enrichment_df.attrs.get("source", "unavailable")
    except Exception as e:
        print(f"Warning: LL2 national enrichment fetch failed - {e}")

    if not official_launch_df.empty:
        try:
            canonical_official_df = enrich_with_ll2(official_launch_df, state_enrichment_df)
            persist_china_launch_history(canonical_official_df)
        except Exception as e:
            print(f"Warning: Official launch enrichment failed - {e}")
            canonical_official_df = official_launch_df

    canonical_event_rows = (
        canonical_official_df.to_dict(orient="records") if not canonical_official_df.empty else []
    )
    canonical_event_rows.extend(_commercial_event_rows(launch_frame))
    canonical_events_df = pd.DataFrame(canonical_event_rows)
    if not canonical_events_df.empty:
        canonical_events_df = canonical_events_df.drop_duplicates("event_id").reset_index(drop=True)
    china_launch_monthly_full_df = build_china_launch_monthly(canonical_events_df)
    # The normalized event history retains the full 1970-present baseline.
    # The portable renderer caps one dataset at 2,000 rows, so publish the
    # latest ten years of the already-zero-filled comparison grid (120 months
    # x 3 classes = 360 rows) and expose the full source range in the caveat.
    china_launch_monthly_df = china_launch_monthly_full_df
    if not china_launch_monthly_full_df.empty:
        latest_month = pd.Period(str(china_launch_monthly_full_df["month"].max()), freq="M")
        first_display_month = str(latest_month - 119)
        china_launch_monthly_df = china_launch_monthly_full_df[
            china_launch_monthly_full_df["month"].ge(first_display_month)
        ].reset_index(drop=True)
    rocket_family_summary_df = build_rocket_family_summary(canonical_events_df)

    # Aggregated launch cadence by provider (total launches per company)
    launch_cadence_summary = []
    provider_counts: dict[str, int] = {}
    if not launch_frame.empty:
        for provider, count in launch_frame["provider"].value_counts().items():
            provider_counts[provider] = int(count)
    for p in CHINESE_LAUNCH_AGENCIES:
        cnt = provider_counts.get(p, 0)
        launch_cadence_summary.append({"provider": p, "launch_count": cnt})

    # 3. Fetch Satellites
    sat_rows = []
    sat_df = empty_source_frame
    satellite_history_df = empty_source_frame
    satellite_source = "unavailable"
    satellite_partial = False
    qianfan_count = None
    jilin1_count = None
    try:
        sat_df = fetch_all_constellations()
        satellite_source = sat_df.attrs.get("source", "unavailable")
        satellite_partial = bool(sat_df.attrs.get("partial", False))
        if not sat_df.empty:
            for _, row in sat_df.iterrows():
                c_name = row["constellation"]
                cnt = row["satellite_count"]
                if c_name.lower() == "qianfan":
                    qianfan_count = cnt
                elif c_name.lower() == "jilin1":
                    jilin1_count = cnt
                sat_rows.append({
                    "constellation": c_name,
                    "operator": row["operator"],
                    "count": cnt,
                    "as_of": row["fetched_at"][:10] if row.get("fetched_at") else data_as_of,
                })
        satellite_history_df = load_constellation_history()
        sat_rows.append({
            "constellation": "Guowang",
            "operator": "China Satellite Network Group",
            "count": None,
            "as_of": data_as_of,
        })
    except Exception as e:
        print(f"Warning: Satellite fetch failed - {e}")

    # 4. Fetch Patents
    patent_rows = []
    pat_df = empty_source_frame
    try:
        pat_df = fetch_all_patent_counts()
        if not pat_df.empty and pat_df["estimated_count"].notna().any():
            for _, row in pat_df.iterrows():
                cnt = row["estimated_count"]
                if pd.notna(cnt):
                    patent_rows.append({
                        "assignee": str(row["assignee_query"]),
                        "estimated_count": int(cnt),
                    })
    except Exception as e:
        print(f"Warning: Patent fetch failed - {e}")

    # 5. Stage 2 public global/US feeds.
    faa_df = empty_source_frame
    contracts_df = empty_source_frame
    sec_filings_df = empty_source_frame
    global_benchmark_df = empty_source_frame
    global_object_catalog_df = empty_source_frame
    global_object_catalog_source = "unavailable"
    wikipedia_pageviews_df = empty_source_frame
    wikipedia_pageviews_source = "unavailable"
    wikipedia_pageviews_daily_df = empty_source_frame
    wikipedia_pageviews_daily_source = "unavailable"
    try:
        faa_df = fetch_faa_commercial_space_kpis()
    except Exception as e:
        print(f"Warning: FAA commercial-space fetch failed - {e}")
    try:
        contracts_df = fetch_commercial_space_contracts()
    except Exception as e:
        print(f"Warning: USAspending fetch failed - {e}")
    try:
        sec_filings_df = fetch_sec_space_company_filings()
    except Exception as e:
        print(f"Warning: SEC space-company fetch failed - {e}")
    try:
        global_benchmark_df = fetch_global_objects_launched()
    except Exception as e:
        print(f"Warning: Global benchmark fetch failed - {e}")
    try:
        satcat_objects_df = fetch_celestrak_satcat()
        global_object_catalog_source = satcat_objects_df.attrs.get("source", "unavailable")
        if not satcat_objects_df.empty:
            global_object_catalog_df = build_monthly_catalog_summary(satcat_objects_df, lookback_months=120)
            persist_monthly_summary(
                global_object_catalog_df,
                fetched_at=satcat_objects_df.attrs.get("fetched_at"),
            )
    except Exception as e:
        print(f"Warning: Global object catalog fetch failed - {e}")
    try:
        wikipedia_pageviews_df = fetch_wikipedia_aerospace_pageviews()
        wikipedia_pageviews_source = wikipedia_pageviews_df.attrs.get("source", "unavailable")
    except Exception as e:
        print(f"Warning: Wikimedia pageviews fetch failed - {e}")
    try:
        wikipedia_pageviews_daily_df = fetch_wikipedia_aerospace_pageviews_daily()
        wikipedia_pageviews_daily_source = wikipedia_pageviews_daily_df.attrs.get("source", "unavailable")
    except Exception as e:
        print(f"Warning: Wikimedia daily pageviews fetch failed - {e}")

    wikipedia_agent_monthly_df = build_agent_monthly_summary(wikipedia_pageviews_df)
    wikipedia_user_page_monthly_df = build_user_page_monthly_summary(wikipedia_pageviews_df)
    wikipedia_latest_page_agent_df = build_latest_page_agent_summary(wikipedia_pageviews_df)
    wikipedia_agent_weekly_df = wikipedia_pageviews_daily_df.attrs.get("weekly_summary")
    if not isinstance(wikipedia_agent_weekly_df, pd.DataFrame):
        wikipedia_agent_weekly_df = build_agent_weekly_summary(wikipedia_pageviews_daily_df)
    if not wikipedia_agent_weekly_df.empty:
        weekly_periods = sorted(wikipedia_agent_weekly_df["week"].dropna().unique())
        if len(weekly_periods) > WIKIMEDIA_WEEKLY_ARTIFACT_WEEKS:
            first_display_week = weekly_periods[-WIKIMEDIA_WEEKLY_ARTIFACT_WEEKS]
            wikipedia_agent_weekly_df = wikipedia_agent_weekly_df[
                wikipedia_agent_weekly_df["week"].ge(first_display_week)
            ].reset_index(drop=True)
    # 6. HK-listed Watchlist
    watchlist_rows = []
    for ticker, desc in HK_AEROSPACE_WATCHLIST.items():
        is_core = "[NOTE:" not in desc
        clean_name = desc.split(" [NOTE:")[0] if "[NOTE:" in desc else desc
        note = desc.split(" [NOTE: ")[1].rstrip("]") if "[NOTE:" in desc else "Core Aerospace / Defense"
        watchlist_rows.append({
            "ticker": f"{ticker}.HK",
            "company_name": clean_name,
            "category": "Core Aerospace" if is_core else "Adjacent / Non-Core",
            "notes": note,
        })

    # 6. Policy Milestones
    policy_rows = [
        {"date": item["date"], "event": item["event"]}
        for item in POLICY_MILESTONES
    ]

    # Datasets dictionary for snapshot
    datasets = {
        "ipo_race": ipo_rows,
        "upcoming_launches": upcoming_rows,
        "launch_cadence": launch_rows,
        "launch_monthly": launch_monthly_df.to_dict(orient="records"),
        "launch_monthly_total": launch_monthly_total_df.to_dict(orient="records"),
        "china_launch_monthly": china_launch_monthly_df.to_dict(orient="records"),
        "china_launch_family_summary": rocket_family_summary_df.to_dict(orient="records"),
        "china_launch_events": (
            canonical_events_df.sort_values(["launch_date", "event_id"], ascending=[False, True]).to_dict(orient="records")
            if not canonical_events_df.empty else []
        ),
        "launch_cadence_summary": launch_cadence_summary,
        "satellite_counts": sat_rows,
        "satellite_history": satellite_history_df.to_dict(orient="records") if not satellite_history_df.empty else [],
        "patent_counts": patent_rows,
        "szse_ipo_projects": szse_ipo_rows,
        "faa_commercial_space": faa_df.to_dict(orient="records") if not faa_df.empty else [],
        "usaspending_contracts": contracts_df.to_dict(orient="records") if not contracts_df.empty else [],
        "sec_space_filings": sec_filings_df.to_dict(orient="records") if not sec_filings_df.empty else [],
        "global_space_benchmark": global_benchmark_df.to_dict(orient="records") if not global_benchmark_df.empty else [],
        "global_object_catalog_monthly": global_object_catalog_df.to_dict(orient="records") if not global_object_catalog_df.empty else [],
        "wikipedia_attention_agent_monthly": wikipedia_agent_monthly_df.to_dict(orient="records") if not wikipedia_agent_monthly_df.empty else [],
        "wikipedia_attention_agent_weekly": wikipedia_agent_weekly_df.to_dict(orient="records") if not wikipedia_agent_weekly_df.empty else [],
        "wikipedia_user_attention_monthly": wikipedia_user_page_monthly_df.to_dict(orient="records") if not wikipedia_user_page_monthly_df.empty else [],
        "wikipedia_attention_latest": wikipedia_latest_page_agent_df.to_dict(orient="records") if not wikipedia_latest_page_agent_df.empty else [],
        "aerospace_watchlist": watchlist_rows,
        "policy_milestones": policy_rows,
        "kpi_summary": [{
            "landspace_status": landspace_status,
            "landspace_audit": landspace_audit,
            "cas_space_status": cas_space_status,
            "cas_space_audit": cas_space_audit,
            "qianfan_count": qianfan_count,
            "jilin1_count": jilin1_count,
            "total_launches": total_launches,
        }],
    }

    # Cards
    cards = [
        {
            "id": "ipo_race_card",
            "description": "SSE STAR Market IPO filing status for top commercial rocket makers.",
            "dataset": "kpi_summary",
            "sourceId": "sse_star_market_ipo",
            "metrics": [
                {"label": "LandSpace Status", "field": "landspace_status", "format": "text"},
                {"label": "LandSpace Audit #", "field": "landspace_audit", "format": "text"},
                {"label": "CAS Space Status", "field": "cas_space_status", "format": "text"},
                {"label": "CAS Space Audit #", "field": "cas_space_audit", "format": "text"},
            ],
        },
        {
            "id": "constellations_card",
            "description": "LEO satellite constellation counts from Celestrak tracking data.",
            "dataset": "kpi_summary",
            "sourceId": "celestrak",
            "metrics": [
                {"label": "Qianfan Constellation (Count)", "field": "qianfan_count", "format": "number"},
                {"label": "Jilin-1 Constellation (Count)", "field": "jilin1_count", "format": "number"},
                {"label": "Total Commercial Launches", "field": "total_launches", "format": "number"},
            ],
        },
    ]

    # Charts
    charts = [
        {
            "id": "satellite_count_chart",
            "title": "Chinese Commercial Satellite Constellations",
            "subtitle": "Tracked active satellites for Qianfan (G60) and Jilin-1 constellations via Celestrak.",
            "type": "bar",
            "dataset": "satellite_counts",
            "sourceId": "celestrak",
            "encodings": {
                "x": {"field": "constellation", "type": "nominal", "label": "Constellation"},
                "y": {"field": "count", "type": "quantitative", "label": "Satellites"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "patent_count_chart",
            "title": "Patent Filings by Commercial Launch Provider",
            "subtitle": "Estimated patent filings across rocket manufacturers.",
            "type": "bar",
            "dataset": "patent_counts",
            "sourceId": "google_patents",
            "encodings": {
                "x": {"field": "assignee", "type": "nominal", "label": "Company"},
                "y": {"field": "estimated_count", "type": "quantitative", "label": "Patents"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "launch_cadence_chart",
            "title": "Commercial Launch Count by Provider",
            "subtitle": "Historical commercial launches tracked per rocket agency.",
            "type": "bar",
            "dataset": "launch_cadence_summary",
            "sourceId": "launch_library_2",
            "encodings": {
                "x": {"field": "provider", "type": "nominal", "label": "Provider"},
                "y": {"field": "launch_count", "type": "quantitative", "label": "Launches"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "launch_monthly_chart",
            "title": "Chinese Commercial Launches by Month",
            "subtitle": "Monthly total for the configured Chinese commercial launch providers; months without a matched launch are shown as zero. National-program launches are excluded.",
            "type": "line",
            "dataset": "launch_monthly_total",
            "sourceId": "launch_library_2",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "launch_count", "type": "quantitative", "label": "Launches"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "china_launch_monthly_chart",
            "title": "China Launches by Program Class",
            "subtitle": "Latest-ten-year view of the zero-filled monthly counts from the verified Long March/Jielong first-party baseline plus the existing exact-provider commercial series; normalized event history begins in 1970 and LL2-only candidates are excluded.",
            "type": "line",
            "dataset": "china_launch_monthly",
            "sourceId": "official_china_launch_records",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "launch_count", "type": "quantitative", "label": "Launches"},
                "color": {"field": "program_class", "type": "nominal", "label": "Program Class"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "china_launch_family_chart",
            "title": "Verified Launch Count by Rocket Family",
            "subtitle": "Canonical launch events grouped by rocket family; this counts rocket launches, not payloads or satellites.",
            "type": "bar",
            "dataset": "china_launch_family_summary",
            "sourceId": "official_china_launch_records",
            "encodings": {
                "x": {"field": "rocket_family", "type": "nominal", "label": "Rocket Family"},
                "y": {"field": "launch_count", "type": "quantitative", "label": "Launches"},
                "color": {"field": "program_class", "type": "nominal", "label": "Program Class"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "satellite_history_chart",
            "title": "Tracked Chinese Commercial Constellation History",
            "subtitle": "Daily CelesTrak snapshots; the current history is a short observed run, and tracked objects are not guaranteed operational satellites.",
            "type": "line",
            "dataset": "satellite_history",
            "sourceId": "celestrak",
            "encodings": {
                "x": {"field": "as_of", "type": "temporal", "label": "Date"},
                "y": {"field": "satellite_count", "type": "quantitative", "label": "Tracked Objects"},
                "color": {"field": "constellation", "type": "nominal", "label": "Constellation"},
            },
            "settings": {"showPoints": "always"},
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "global_space_benchmark_chart",
            "title": "Global Objects Launched into Space",
            "subtitle": "Annual UNOOSA-based benchmark: World total alongside China and United States; this counts objects, not rocket launches.",
            "type": "line",
            "dataset": "global_space_benchmark",
            "sourceId": "global_space_benchmark",
            "encodings": {
                "x": {"field": "year", "type": "nominal", "label": "Year"},
                "y": {"field": "objects_launched", "type": "quantitative", "label": "Objects"},
                "color": {"field": "entity", "type": "nominal", "label": "Entity"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "global_object_catalog_monthly_chart",
            "title": "Global Cataloged Objects Launched by Month",
            "subtitle": "CelesTrak SATCAT launch-date counts, shown for the latest ten years. Payloads are closest to the UNOOSA benchmark; rocket bodies, debris and unknown objects are separate catalogue classes and are not equivalent to registered objects.",
            "type": "line",
            "dataset": "global_object_catalog_monthly",
            "sourceId": "global_object_catalog",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "object_count", "type": "quantitative", "label": "Cataloged Objects"},
                "color": {"field": "object_type", "type": "nominal", "label": "Object Type"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "wikipedia_attention_agent_weekly_chart",
            "title": "Aerospace Wikipedia Attention by Week",
            "subtitle": "Latest 500 complete Monday-Sunday weeks derived from daily views across the curated English Wikipedia aerospace page basket; the current partial week is excluded. The monthly chart retains the longer history.",
            "type": "line",
            "dataset": "wikipedia_attention_agent_weekly",
            "sourceId": "wikimedia_pageviews",
            "encodings": {
                "x": {"field": "week", "type": "temporal", "label": "Week starting"},
                "y": {"field": "views", "type": "quantitative", "label": "Pageviews"},
                "color": {"field": "agent", "type": "nominal", "label": "Traffic Agent"},
            },
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 2500,
        },
        {
            "id": "wikipedia_attention_agent_monthly_chart",
            "title": "Aerospace Wikipedia Attention by Traffic Agent",
            "subtitle": "Monthly views summed across the curated English Wikipedia aerospace page basket; user, search-engine spider, automated and all-agent traffic remain separate.",
            "type": "line",
            "dataset": "wikipedia_attention_agent_monthly",
            "sourceId": "wikimedia_pageviews",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "views", "type": "quantitative", "label": "Pageviews"},
                "color": {"field": "agent", "type": "nominal", "label": "Traffic Agent"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "wikipedia_user_attention_monthly_chart",
            "title": "Aerospace Wikipedia User Views by Page",
            "subtitle": "Monthly user pageviews for the curated English Wikipedia aerospace basket; latest-ten-year history where available.",
            "type": "line",
            "dataset": "wikipedia_user_attention_monthly",
            "sourceId": "wikimedia_pageviews",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "views", "type": "quantitative", "label": "User Pageviews"},
                "color": {"field": "page_label", "type": "nominal", "label": "Wikipedia Page"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
    ]

    # Tables
    tables = [
        {
            "id": "ipo_race_table",
            "title": "SSE STAR Market Commercial Space IPO Race",
            "subtitle": "Review status, audit numbers, and filing updates for top commercial rocket makers.",
            "dataset": "ipo_race",
            "sourceId": "sse_star_market_ipo",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "company_en", "label": "Company (EN)", "type": "text"},
                {"field": "company_zh", "label": "Company (ZH)", "type": "text"},
                {"field": "status", "label": "Status", "type": "text"},
                {"field": "audit_num", "label": "Audit #", "format": "text"},
                {"field": "update_date", "label": "Update Date", "type": "text"},
                {"field": "exchange", "label": "Exchange", "type": "text"},
            ],
        },
        {
            "id": "upcoming_launches_table",
            "title": "Upcoming Chinese Rocket & Satellite Launch Schedule",
            "subtitle": "Target launch dates (NET), providers, mission names, launch sites, and operational status from Launch Library 2.",
            "dataset": "upcoming_launches",
            "sourceId": "launch_library_2",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "net_date", "label": "Target Date (NET)", "type": "text"},
                {"field": "provider", "label": "Provider / Agency", "type": "text"},
                {"field": "mission", "label": "Mission / Rocket", "type": "text"},
                {"field": "pad_name", "label": "Launch Site", "type": "text"},
                {"field": "orbit", "label": "Orbit", "type": "text"},
                {"field": "status", "label": "Status", "type": "text"},
            ],
        },
        {
            "id": "china_launch_events_table",
            "title": "Verified China Launch Mission Details",
            "subtitle": "One row per canonical launch; the official first-party baseline determines inclusion and LL2 fields are shown only when matched.",
            "dataset": "china_launch_events",
            "sourceId": "official_china_launch_records",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "launch_date", "label": "Launch Date", "type": "text"},
                {"field": "mission_name", "label": "Mission / Payload", "type": "text"},
                {"field": "rocket_name", "label": "Rocket", "type": "text"},
                {"field": "program_class", "label": "Program Class", "type": "text"},
                {"field": "launch_site", "label": "Launch Site", "type": "text"},
                {"field": "payload_summary", "label": "Payload Summary", "type": "text"},
                {"field": "payload_count", "label": "Payload Count", "type": "number"},
                {"field": "outcome", "label": "Outcome", "type": "text"},
                {"field": "ll2_match_status", "label": "LL2 Match", "type": "text"},
            ],
        },
        {
            "id": "aerospace_watchlist_table",
            "title": "HK-Listed Commercial Aerospace & Defense Watchlist",
            "subtitle": "Stock watchlist of Hong Kong listed aerospace, satellite, and defense supply-chain companies.",
            "dataset": "aerospace_watchlist",
            "sourceId": "sse_star_market_ipo",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "ticker", "label": "Ticker", "type": "text"},
                {"field": "company_name", "label": "Company Name", "type": "text"},
                {"field": "category", "label": "Category", "type": "text"},
                {"field": "notes", "label": "Notes", "type": "text"},
            ],
        },
        {
            "id": "policy_milestones_table",
            "title": "China Commercial Space Policy Progression",
            "subtitle": "Central Government Work Report designations and CNSA action plans.",
            "dataset": "policy_milestones",
            "sourceId": "sse_star_market_ipo",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "date", "label": "Date", "type": "text"},
                {"field": "event", "label": "Policy Milestone", "type": "text"},
            ],
        },
        {
            "id": "szse_ipo_table",
            "title": "SZSE Aerospace-Industry IPO Projects",
            "subtitle": "The classification is broader than pure commercial space; industry remains visible for review.",
            "dataset": "szse_ipo_projects",
            "sourceId": "szse_aerospace_ipo",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "company_name", "label": "Company", "type": "text"},
                {"field": "board", "label": "Board", "type": "text"},
                {"field": "status", "label": "Status", "type": "text"},
                {"field": "industry", "label": "Industry", "type": "text"},
                {"field": "update_date", "label": "Updated", "type": "text"},
                {"field": "accept_date", "label": "Accepted", "type": "text"},
            ],
        },
        {
            "id": "faa_kpi_table",
            "title": "FAA Commercial Space Regulatory KPIs",
            "subtitle": "Official cumulative and active authorization metrics.",
            "dataset": "faa_commercial_space",
            "sourceId": "faa_commercial_space",
            "density": "dense",
            "layout": "half",
            "columns": [
                {"field": "metric", "label": "Metric", "type": "text"},
                {"field": "value", "label": "Value", "type": "number"},
                {"field": "observed_date", "label": "Observed", "type": "text"},
            ],
        },
        {
            "id": "usaspending_contracts_table",
            "title": "US Commercial Space Contract Discovery",
            "subtitle": "Federal awards discovered by keyword; amounts are award amounts, not company revenue.",
            "dataset": "usaspending_contracts",
            "sourceId": "usaspending_contracts",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "award_id", "label": "Award ID", "type": "text"},
                {"field": "recipient_name", "label": "Recipient", "type": "text"},
                {"field": "award_amount", "label": "Award Amount", "type": "number"},
                {"field": "awarding_agency", "label": "Agency", "type": "text"},
                {"field": "start_date", "label": "Start", "type": "text"},
                {"field": "keyword", "label": "Matched Keyword", "type": "text"},
            ],
        },
        {
            "id": "sec_space_filings_table",
            "title": "Listed Commercial Space Company Filings",
            "subtitle": "Official SEC filing events for global listed space companies; filing metadata only.",
            "dataset": "sec_space_filings",
            "sourceId": "sec_space_company_filings",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "ticker", "label": "Ticker", "type": "text"},
                {"field": "company_name", "label": "Company", "type": "text"},
                {"field": "form", "label": "Form", "type": "text"},
                {"field": "filing_date", "label": "Filing Date", "type": "text"},
                {"field": "primary_doc_description", "label": "Description", "type": "text"},
                {"field": "filing_url", "label": "Filing", "type": "text"},
            ],
        },
        {
            "id": "wikipedia_attention_latest_table",
            "title": "Latest Wikipedia Aerospace Attention by Page and Agent",
            "subtitle": "Latest complete month and trailing-12-month pageviews for the curated English Wikipedia basket; user and automated traffic are not unique people.",
            "dataset": "wikipedia_attention_latest",
            "sourceId": "wikimedia_pageviews",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "page_label", "label": "Wikipedia Page", "type": "text"},
                {"field": "topic_group", "label": "Topic Group", "type": "text"},
                {"field": "agent", "label": "Traffic Agent", "type": "text"},
                {"field": "latest_month", "label": "Latest Month", "type": "text"},
                {"field": "latest_views", "label": "Latest Views", "type": "number"},
                {"field": "trailing_12m_views", "label": "Trailing 12M Views", "type": "number"},
            ],
        },
    ]

    manifest_sources = list(PUBLIC_SOURCES.values())

    launch_history_latest = _latest_observation(launch_rows, "date")
    official_launch_latest = _latest_observation(
        canonical_events_df.to_dict(orient="records") if not canonical_events_df.empty else [],
        "launch_date",
    )
    upcoming_latest = _latest_observation(upcoming_rows, "net_date")
    satellite_history_latest = _latest_observation(
        satellite_history_df.to_dict(orient="records") if not satellite_history_df.empty else [],
        "as_of",
    )

    # Build dynamic source_health entries based on actual fetch results
    source_stats = {
        "sse_star_market_ipo": {
            "status": "success" if (not ipo_df.empty) else "degraded",
            "records": len(ipo_df) if (not ipo_df.empty) else 0,
            "freshness": "live" if (not ipo_df.empty) else "unavailable",
            "latest_observation": _latest_observation(ipo_rows, "update_date", data_as_of if not ipo_df.empty else None),
        },
        "launch_library_2": {
            "status": "success" if (launch_source == "live" or upcoming_source == "live") else "degraded",
            "records": total_launches + len(upcoming_rows),
            "freshness": (
                "live" if (launch_source == "live" or upcoming_source == "live")
                else "stale" if (total_launches > 0 or len(upcoming_rows) > 0)
                else "unavailable"
            ),
            "latest_observation": launch_history_latest or upcoming_latest,
        },
        "official_china_launch_records": {
            "status": "success" if not canonical_official_df.empty else "degraded",
            "records": len(canonical_official_df) if not canonical_official_df.empty else 0,
            "freshness": "live" if official_launch_source == "live" else "stale" if not canonical_official_df.empty else "unavailable",
            "latest_observation": _latest_observation(
                canonical_official_df.to_dict(orient="records") if not canonical_official_df.empty else [],
                "launch_date",
            ),
        },
        "launch_library_2_national_enrichment": {
            "status": "success" if not state_enrichment_df.empty else "degraded",
            "records": len(state_enrichment_df),
            "freshness": "live" if state_enrichment_source == "live" else "stale" if not state_enrichment_df.empty else "unavailable",
            "latest_observation": _latest_observation(
                state_enrichment_df.to_dict(orient="records") if not state_enrichment_df.empty else [],
                "net_time",
            ),
        },
        "celestrak": {
            "status": (
                "degraded" if satellite_partial
                else "success" if satellite_source == "live"
                else "degraded"
            ),
            "records": len(sat_df) if (not sat_df.empty) else 0,
            "freshness": "live" if satellite_source == "live" else "unavailable",
            "latest_observation": _latest_observation(
                sat_df.to_dict(orient="records") if satellite_source == "live" else [],
                "fetched_at",
                satellite_history_latest,
            ),
        },
        "google_patents": {
            "status": "success" if (not pat_df.empty and pat_df["estimated_count"].notna().any()) else "failed",
            "records": int(pat_df["estimated_count"].notna().sum()) if not pat_df.empty else 0,
            "freshness": "live" if (not pat_df.empty and pat_df["estimated_count"].notna().any()) else "unavailable",
            "latest_observation": data_as_of if (not pat_df.empty and pat_df["estimated_count"].notna().any()) else None,
        },
        "szse_aerospace_ipo": {
            "status": "success" if not szse_ipo_df.empty else "degraded",
            "records": len(szse_ipo_df),
            "freshness": "live" if not szse_ipo_df.empty else "unavailable",
            "latest_observation": _latest_observation(szse_ipo_rows, "update_date", data_as_of if not szse_ipo_df.empty else None),
        },
        "faa_commercial_space": {
            "status": "success" if not faa_df.empty else "degraded",
            "records": len(faa_df),
            "freshness": "live" if not faa_df.empty else "unavailable",
            "latest_observation": _latest_observation(faa_df.to_dict(orient="records"), "observed_date", data_as_of if not faa_df.empty else None),
        },
        "usaspending_contracts": {
            "status": "success" if not contracts_df.empty else "degraded",
            "records": len(contracts_df),
            "freshness": "live" if not contracts_df.empty else "unavailable",
            "latest_observation": data_as_of if not contracts_df.empty else None,
        },
        "sec_space_company_filings": {
            "status": "success" if not sec_filings_df.empty else "degraded",
            "records": len(sec_filings_df),
            "freshness": "live" if not sec_filings_df.empty else "unavailable",
            "latest_observation": _latest_observation(sec_filings_df.to_dict(orient="records"), "filing_date", data_as_of if not sec_filings_df.empty else None),
        },
        "global_space_benchmark": {
            "status": "success" if not global_benchmark_df.empty else "degraded",
            "records": len(global_benchmark_df),
            "freshness": "live" if not global_benchmark_df.empty else "unavailable",
            "latest_observation": _latest_observation(global_benchmark_df.to_dict(orient="records"), "year", data_as_of if not global_benchmark_df.empty else None),
        },
        "global_object_catalog": {
            "status": "success" if not global_object_catalog_df.empty else "degraded",
            "records": len(global_object_catalog_df),
            "freshness": "live" if global_object_catalog_source == "live" else "unavailable",
            "latest_observation": _latest_observation(
                global_object_catalog_df.to_dict(orient="records") if not global_object_catalog_df.empty else [],
                "month",
                data_as_of if not global_object_catalog_df.empty else None,
            ),
        },
        "wikimedia_pageviews": {
            "status": "success" if wikipedia_pageviews_source == "live" and wikipedia_pageviews_daily_source == "live" else "degraded",
            "records": len(wikipedia_pageviews_df) + len(wikipedia_pageviews_daily_df),
            "freshness": (
                "live" if wikipedia_pageviews_source == "live" and wikipedia_pageviews_daily_source == "live"
                else "stale" if wikipedia_pageviews_source in {"partial", "cache"} or wikipedia_pageviews_daily_source in {"partial", "cache"}
                else "unavailable"
            ),
            "latest_observation": max(
                _latest_observation(
                    wikipedia_pageviews_df.to_dict(orient="records") if not wikipedia_pageviews_df.empty else [],
                    "month",
                ) or "",
                _latest_observation(
                    wikipedia_pageviews_daily_df.to_dict(orient="records") if not wikipedia_pageviews_daily_df.empty else [],
                    "date",
                ) or "",
            ) or None,
        },
    }

    status_entries = [
        {
            "source_id": key,
            "label": s["label"],
            "status": source_stats[key]["status"],
            "records": source_stats[key]["records"],
            "latest_observation": source_stats[key].get("latest_observation"),
            "freshness": source_stats[key]["freshness"],
            "notes": s["query"]["description"],
        }
        for key, s in PUBLIC_SOURCES.items()
    ]

    snapshot_payload = {
        "datasets": datasets,
        "source_urls": [s.get("href") for s in PUBLIC_SOURCES.values() if s.get("href")],
    }
    snapshot_id = hashlib.sha256(
        json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()[:16]

    blocks = [
        {
            "id": "snapshot_context",
            "type": "markdown",
            "body": (
                f"**Data snapshot:** `{snapshot_id}` · generated {generated_at}.  "
                "Official disclosures and public tracking data."
            ),
        },
        {"id": "kpi_grid", "type": "metric-strip", "cardIds": [c["id"] for c in cards]},
        {"id": "ipo_table_block", "type": "table", "tableId": "ipo_race_table"},
    ]
    if upcoming_rows:
        blocks.append({"id": "upcoming_table_block", "type": "table", "tableId": "upcoming_launches_table"})
    if not china_launch_monthly_df.empty:
        blocks.append({"id": "china_launch_monthly_chart_block", "type": "chart", "chartId": "china_launch_monthly_chart"})
    if not rocket_family_summary_df.empty:
        blocks.append({"id": "china_launch_family_chart_block", "type": "chart", "chartId": "china_launch_family_chart"})
    if not canonical_events_df.empty:
        blocks.append({"id": "china_launch_events_table_block", "type": "table", "tableId": "china_launch_events_table"})
    blocks.append({"id": "satellite_chart_block", "type": "chart", "chartId": "satellite_count_chart", "layout": "half" if patent_rows else "full"})
    if patent_rows:
        blocks.append({"id": "patent_chart_block", "type": "chart", "chartId": "patent_count_chart", "layout": "half"})
    blocks.extend([
        {"id": "launch_chart_block", "type": "chart", "chartId": "launch_cadence_chart"},
        {"id": "watchlist_table_block", "type": "table", "tableId": "aerospace_watchlist_table"},
        {"id": "policy_table_block", "type": "table", "tableId": "policy_milestones_table"},
        {
            "id": "methodology",
            "type": "markdown",
            "body": (
                "## Reading the Commercial Aerospace Monitor\n\n"
                "China's commercial aerospace sector is driven by twin catalysts: SSE STAR Market IPO filings "
                "(LandSpace #2174, CAS Space #2180) and satellite constellation deployment (Qianfan G60, Jilin-1). "
                "The launch comparison uses first-party Long March/Jielong records as the inclusion baseline and keeps "
                "the existing exact-provider commercial series separate; Launch Library 2 only enriches matched official events. "
                "Guowang (SatNet) Celestrak identifiers remain unresolved and are tracked as a documented data gap. "
                "This monitor tracks regulatory filings, launch cadence, constellation counts, HK-listed "
                "supply-chain tickers and Wikipedia pageview attention. Wikipedia views are page loads, not "
                "unique people or domestic mainland-China demand. No stock recommendation is produced."
            ),
        },
    ])
    if not launch_monthly_df.empty:
        blocks.append({"id": "launch_monthly_chart_block", "type": "chart", "chartId": "launch_monthly_chart"})
    if not satellite_history_df.empty:
        blocks.append({"id": "satellite_history_chart_block", "type": "chart", "chartId": "satellite_history_chart"})
    if szse_ipo_rows:
        blocks.append({"id": "szse_ipo_table_block", "type": "table", "tableId": "szse_ipo_table"})
    if not faa_df.empty:
        blocks.append({"id": "faa_kpi_table_block", "type": "table", "tableId": "faa_kpi_table"})
    if not contracts_df.empty:
        blocks.append({"id": "usaspending_contracts_table_block", "type": "table", "tableId": "usaspending_contracts_table"})
    if not sec_filings_df.empty:
        blocks.append({"id": "sec_space_filings_table_block", "type": "table", "tableId": "sec_space_filings_table"})
    if not global_benchmark_df.empty:
        blocks.append({"id": "global_space_benchmark_chart_block", "type": "chart", "chartId": "global_space_benchmark_chart"})
    if not global_object_catalog_df.empty:
        blocks.append({"id": "global_object_catalog_monthly_chart_block", "type": "chart", "chartId": "global_object_catalog_monthly_chart"})
    if not wikipedia_pageviews_df.empty or not wikipedia_agent_weekly_df.empty:
        blocks.extend([
            {"id": "wikipedia_attention_agent_weekly_chart_block", "type": "chart", "chartId": "wikipedia_attention_agent_weekly_chart"},
            {"id": "wikipedia_attention_agent_monthly_chart_block", "type": "chart", "chartId": "wikipedia_attention_agent_monthly_chart"},
            {"id": "wikipedia_user_attention_monthly_chart_block", "type": "chart", "chartId": "wikipedia_user_attention_monthly_chart"},
            {"id": "wikipedia_attention_latest_table_block", "type": "table", "tableId": "wikipedia_attention_latest_table"},
        ])

    artifact = {
        "surface": "dashboard",
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "Hong Kong Commercial Aerospace Sector Monitor",
            "description": "Official Chinese Long March/Jielong launch baseline, Launch Library 2 commercial and enrichment data, Celestrak satellite counts, Wikimedia Wikipedia attention, IPO status, and broader commercial-space indicators.",
            "sector": "hk-commercial-aerospace",
            "generatedAt": generated_at,
            "dataAsOf": data_as_of,
            "liveSourcesCount": sum(item["status"] == "success" for item in source_stats.values()),
            "totalSourcesCount": len(PUBLIC_SOURCES),
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": manifest_sources,
            "blocks": blocks,
        },
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready", "datasets": datasets},
        "sources": manifest_sources,
        "source_health": status_entries,
        "package_info": {
            "originUrl": "https://asia-markets-dashboard.pages.dev/sectors/hk-commercial-aerospace/",
            "sector_id": "hk-commercial-aerospace",
            "sector_name": "Hong Kong Commercial Aerospace Sector Monitor",
            "snapshotId": snapshot_id,
            "generatedAt": generated_at,
            "dataAsOf": data_as_of,
        },
    }

    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": data_as_of,
        "overall_status": "Healthy" if all(item["status"] == "success" for item in source_stats.values()) else "Degraded",
        "live_sources": sum(item["status"] == "success" for item in source_stats.values()),
        "planned_sources": 0,
        "sources": [
            {
                "source": s["label"],
                "dataset": key,
                "type": "Measure",
                "status": "Healthy" if source_stats[key]["status"] == "success" else "Degraded",
                "latest_observation": source_stats[key].get("latest_observation") or data_as_of,
                "records": source_stats[key]["records"],
                "freshness": {"live": "Live", "stale": "Stale"}.get(source_stats[key]["freshness"], "Unavailable"),
                "notes": s["query"]["description"],
            }
            for key, s in PUBLIC_SOURCES.items()
        ],
        "attachment_filename": f"hk-commercial-aerospace-dashboard-{now.date().isoformat()}.html",
    }

    return artifact, status


def _clean_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _clean_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_json(v) for v in obj]
    elif pd.isna(obj):
        return None
    return obj


def main() -> int:
    parser = argparse.ArgumentParser(description="Build JSON artifact for HK Commercial Aerospace.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--status-output", type=Path, required=True)
    args = parser.parse_args()

    artifact, status = build_artifact()
    artifact = _clean_json(artifact)
    status = _clean_json(status)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.status_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")
    args.status_output.write_text(json.dumps(status, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "artifact": str(args.output), "snapshot_id": status["snapshot_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
