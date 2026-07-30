#!/usr/bin/env python3
import argparse
import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.hk_population_migration.sources.immd_daily_traffic import fetch_immd_daily_traffic
from src.hk_population_migration.sources.csd_population import fetch_csd_population_estimates
from src.hk_population_migration.sources.mpfa_claims import fetch_mpfa_permanent_departure_claims
from src.hk_population_migration.sources.ugc_students import fetch_ugc_nonlocal_students
from src.hk_population_migration.sources.td_cross_border import fetch_td_cross_border_traffic
from src.hk_population_migration.storage import load_latest_normalized
# IA Mainland Visitor premiums are intentionally not wired in here: the
# regulator suspended this series (every release since Q1 2025 states it is
# under review), and there is no real substitute source, so this sector does
# not ship a premiums card/chart/table rather than show suspended/fabricated
# data. See src/hk_population_migration/sources/ia_premiums.py.

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

PUBLIC_SOURCES = {
    "immd": {
        "id": "immd",
        "label": "Immigration Department Daily Passenger Traffic",
        "href": "https://www.immd.gov.hk/opendata/eng/transport/immigration_clearance/statistics_on_daily_passenger_traffic.csv",
        "query": {
            "engine": "official open data CSV",
            "url": "https://www.immd.gov.hk/opendata/eng/transport/immigration_clearance/statistics_on_daily_passenger_traffic.csv",
            "language": "CSV",
            "sql": "SELECT date, control_point, arrival_departure, hk_resident_net_flow, mainland_visitor_net_retention FROM immd_daily_passenger_traffic;",
            "description": "Daily passenger clearance by control point, direction and residency, used to derive HK-resident net flow and Mainland-visitor net retention.",
        },
    },
    "csd": {
        "id": "csd",
        "label": "Census & Statistics Department Population Estimates",
        "href": "https://www.censtatd.gov.hk/en/web_table.html?id=110-01001",
        "query": {
            "engine": "official Web Table API",
            "url": "https://www.censtatd.gov.hk/api/get.php?id=110-01001&lang=en&full_series=1",
            "language": "JSON",
            "sql": "SELECT period, mid_year_population_thousands, natural_growth_thousands, net_movement_thousands FROM csd_population_estimates;",
            "description": "Half-yearly population estimates, natural change and net movement (One-way Permit holders vs. others), 1961-present.",
        },
    },
    "mpfa": {
        "id": "mpfa",
        "label": "MPFA Statistical Digest",
        "href": "https://www.mpfa.org.hk/en/info-centre/research-reports/quarterly-reports/mpf-schemes",
        "query": {
            "engine": "official quarterly PDF digest",
            "url": "https://www.mpfa.org.hk/en/info-centre/research-reports/quarterly-reports/mpf-schemes",
            "language": "PDF",
            "sql": "SELECT quarter, claims_count, amount_mhkd FROM mpfa_permanent_departure_claims;",
            "description": "Quarterly MPF claims for permanent departure from Hong Kong (count and amount), parsed from the official Statistical Digest.",
        },
    },
    "ugc": {
        "id": "ugc",
        "label": "UGC Student Enrolment by Place of Origin",
        "href": "https://portal.csdi.gov.hk/geoportal/?datasetId=ugc_rcd_1697186814214_75295",
        "query": {
            "engine": "CSDI Esri FeatureServer",
            "url": "https://portal.csdi.gov.hk/server/rest/services/common/ugc_rcd_1697186814214_75295/FeatureServer/0/query",
            "language": "JSON",
            "sql": "SELECT academic_year, mainland_students, other_non_local_students, total_non_local FROM ugc_student_enrolment;",
            "description": "Annual UGC-funded programme enrolment by university, level of study, mode of study and place of origin, 2010/11-present.",
        },
    },
    "td": {
        "id": "td",
        "label": "Transport Department Monthly Traffic and Transport Digest",
        "href": "https://www.td.gov.hk/datagovhk_tis/mttd-csv/en/mttd_dataspec_eng.pdf",
        "query": {
            "engine": "official open data CSV",
            "url": "https://www.td.gov.hk/datagovhk_tis/mttd-csv/en/table81e_eng.csv",
            "language": "CSV",
            "sql": "SELECT month, hzmb_vehicular_traffic, hzmb_northbound_hk_vehicles, express_rail_passengers FROM td_cross_border_traffic;",
            "description": "Monthly HZMB vehicular traffic (incl. Northbound Travel for HK Vehicles 港车北上) and cross-boundary passenger traffic incl. Express Rail West Kowloon.",
        },
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_normalized_or_fetch(dataset_name: str, fetcher) -> pd.DataFrame:
    """Use a durable normalized run first; only bootstrap by fetching when absent."""
    normalized = load_latest_normalized(dataset_name)
    return normalized if not normalized.empty else fetcher()


def _long_series_rows(
    rows: list[dict[str, Any]],
    *,
    period_field: str,
    series_fields: dict[str, str],
) -> list[dict[str, Any]]:
    """Make chart-specific tidy rows without discarding the source-wide dataset."""
    result = []
    for row in rows:
        period = row.get(period_field)
        if period is None:
            continue
        for field, label in series_fields.items():
            value = row.get(field)
            if value is not None and pd.notna(value):
                result.append({period_field: period, "series": label, "value": value})
    return sorted(result, key=lambda row: (str(row[period_field]), row["series"]))


def _observation_timestamp(value: str) -> pd.Timestamp | None:
    """Return an ordering timestamp while retaining the source's own period label."""
    if re.fullmatch(r"\d{4}-Q[1-4]", value):
        year, quarter = int(value[:4]), int(value[-1])
        return pd.Timestamp(year=year, month=quarter * 3, day=1) + pd.offsets.MonthEnd(0)
    if re.fullmatch(r"\d{4}/\d{2}", value):
        return pd.Timestamp(year=int(value[:4]), month=9, day=1)
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed


def _latest_observation(rows: list[dict[str, Any]], period_field: str) -> str:
    candidates = [str(row[period_field]) for row in rows if row.get(period_field) is not None]
    dated = [(value, _observation_timestamp(value)) for value in candidates]
    dated = [(value, timestamp) for value, timestamp in dated if timestamp is not None]
    return max(dated, key=lambda item: item[1])[0] if dated else "—"


def build_artifact(
    raw_immd: pd.DataFrame | None = None,
    raw_pop: pd.DataFrame | None = None,
    raw_mpfa: pd.DataFrame | None = None,
    raw_ugc: pd.DataFrame | None = None,
    raw_td: pd.DataFrame | None = None,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    df_immd = raw_immd if raw_immd is not None else _load_normalized_or_fetch("immd_daily_traffic", fetch_immd_daily_traffic)
    df_pop = raw_pop if raw_pop is not None else _load_normalized_or_fetch("csd_population_estimates", fetch_csd_population_estimates)
    df_mpfa = raw_mpfa if raw_mpfa is not None else _load_normalized_or_fetch("mpfa_departure_claims", fetch_mpfa_permanent_departure_claims)
    df_ugc = raw_ugc if raw_ugc is not None else _load_normalized_or_fetch("ugc_nonlocal_students", fetch_ugc_nonlocal_students)
    df_td = raw_td if raw_td is not None else _load_normalized_or_fetch("td_cross_border_traffic", fetch_td_cross_border_traffic)

    generated_at = now.isoformat().replace("+00:00", "Z")

    # 1. ImmD Daily Net Flow Records (recent 365 days for smooth charting)
    immd_rows: list[dict[str, Any]] = []
    if not df_immd.empty:
        recent_immd = df_immd.tail(365)
        for _, r in recent_immd.iterrows():
            immd_rows.append({
                "date": str(r["date"])[:10],
                "hk_resident_net_flow": float(r["hk_resident_net_flow"]) if pd.notna(r.get("hk_resident_net_flow")) else None,
                "mainland_visitor_net_retention": float(r["mainland_visitor_net_retention"]) if pd.notna(r.get("mainland_visitor_net_retention")) else None,
                "hk_resident_departures_7d_ma": float(r["hk_resident_departures_7d_ma"]) if pd.notna(r.get("hk_resident_departures_7d_ma")) else None,
                "mainland_visitor_arrivals_7d_ma": float(r["mainland_visitor_arrivals_7d_ma"]) if pd.notna(r.get("mainland_visitor_arrivals_7d_ma")) else None,
            })

    # 2. Population Estimates (C&SD)
    pop_rows: list[dict[str, Any]] = []
    if not df_pop.empty:
        for _, r in df_pop.iterrows():
            pop_rows.append({
                "period": str(r["period"]),
                "mid_year_population_thousands": float(r["mid_year_population_thousands"]) if pd.notna(r.get("mid_year_population_thousands")) else None,
                "natural_growth_thousands": float(r["natural_growth_thousands"]) if pd.notna(r.get("natural_growth_thousands")) else None,
                "net_movement_thousands": float(r["net_movement_thousands"]) if pd.notna(r.get("net_movement_thousands")) else None,
            })

    # 3. MPFA Claims
    mpfa_rows: list[dict[str, Any]] = []
    if not df_mpfa.empty:
        for _, r in df_mpfa.iterrows():
            mpfa_rows.append({
                "quarter": str(r["quarter"]),
                "claims_count": int(r["claims_count"]) if pd.notna(r.get("claims_count")) else None,
                "amount_mhkd": float(r["amount_mhkd"]) if pd.notna(r.get("amount_mhkd")) else None,
            })

    # 4. UGC Students
    ugc_rows: list[dict[str, Any]] = []
    if not df_ugc.empty:
        for _, r in df_ugc.iterrows():
            ugc_rows.append({
                "academic_year": str(r["academic_year"]),
                "mainland_students": int(r["mainland_students"]) if pd.notna(r.get("mainland_students")) else 0,
                "other_non_local_students": int(r["other_non_local_students"]) if pd.notna(r.get("other_non_local_students")) else 0,
                "total_non_local": int(r["total_non_local"]) if pd.notna(r.get("total_non_local")) else 0,
            })

    # 5. TD Cross-Border
    td_rows: list[dict[str, Any]] = []
    if not df_td.empty:
        for _, r in df_td.iterrows():
            td_rows.append({
                "month": str(r["month"]),
                "hzmb_vehicular_traffic": int(r["hzmb_vehicular_traffic"]) if pd.notna(r.get("hzmb_vehicular_traffic")) else 0,
                "hzmb_northbound_hk_vehicles": int(r["hzmb_northbound_hk_vehicles"]) if pd.notna(r.get("hzmb_northbound_hk_vehicles")) else 0,
                "express_rail_passengers": int(r["express_rail_passengers"]) if pd.notna(r.get("express_rail_passengers")) else 0,
            })

    immd_chart_rows = _long_series_rows(
        immd_rows,
        period_field="date",
        series_fields={
            "hk_resident_net_flow": "HK Resident Net Flow",
            "mainland_visitor_net_retention": "Mainland Visitor Net Retention",
        },
    )
    population_chart_rows = _long_series_rows(
        pop_rows,
        period_field="period",
        series_fields={
            "mid_year_population_thousands": "Population",
            "net_movement_thousands": "Net Movement",
        },
    )
    ugc_chart_rows = _long_series_rows(
        ugc_rows,
        period_field="academic_year",
        series_fields={
            "mainland_students": "Mainland Students",
            "other_non_local_students": "Other Non-local Students",
        },
    )
    td_chart_rows = _long_series_rows(
        td_rows,
        period_field="month",
        series_fields={
            "hzmb_northbound_hk_vehicles": "Northbound HK Vehicles",
            "express_rail_passengers": "Express Rail Passengers",
        },
    )

    # Latest KPI values, backing the metric-strip cards below
    latest_pop = pop_rows[-1]["mid_year_population_thousands"] if pop_rows else None
    latest_net_mov = pop_rows[-1]["net_movement_thousands"] if pop_rows else None
    latest_mpfa = mpfa_rows[-1]["amount_mhkd"] if mpfa_rows else None
    latest_ugc = ugc_rows[-1]["mainland_students"] if ugc_rows else None

    cards = [
        {
            "id": "kpi_total_pop",
            "description": "Official C&SD half-yearly population estimate.",
            "dataset": "market_kpi_summary",
            "sourceId": "csd",
            "metrics": [{"label": "HK Total Population ('000, Mid/End-Year)", "field": "latest_pop", "format": "number"}],
        },
        {
            "id": "kpi_net_mov",
            "description": "Net population movement (One-way Permit holders + others), latest half-year.",
            "dataset": "market_kpi_summary",
            "sourceId": "csd",
            "metrics": [{"label": "Net Population Movement ('000)", "field": "latest_net_mov", "format": "number"}],
        },
        {
            "id": "kpi_mpfa_claims",
            "description": "MPF claims paid for permanent departure from Hong Kong, latest quarter.",
            "dataset": "market_kpi_summary",
            "sourceId": "mpfa",
            "metrics": [{"label": "Quarterly MPF Departure Claims (HK$m)", "field": "latest_mpfa", "format": "number"}],
        },
        {
            "id": "kpi_ugc_students",
            "description": "Mainland students enrolled in UGC-funded university programmes, latest academic year.",
            "dataset": "market_kpi_summary",
            "sourceId": "ugc",
            "metrics": [{"label": "Mainland Students in HK Universities", "field": "latest_ugc", "format": "number"}],
        },
    ]

    charts = [
        {
            "id": "immd_net_flow_chart",
            "title": "ImmD High-Frequency Net Passenger Movement (Daily)",
            "subtitle": "HK Resident Net Flow (Outflow/Return) vs Mainland Visitor Net Retention.",
            "type": "line",
            "intent": "comparison",
            "dataset": "immd_net_flow_history",
            "sourceId": "immd",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "value", "type": "quantitative", "label": "Net Persons"},
                "color": {"field": "series", "type": "nominal", "label": "Measure"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "csd_population_chart",
            "title": "C&SD Population & Net Movement Trends",
            "subtitle": "Half-yearly mid/end-year population estimates and net population movement (thousands).",
            "type": "line",
            "intent": "trend",
            "dataset": "csd_population_movement_history",
            "sourceId": "csd",
            "encodings": {
                "x": {"field": "period", "type": "temporal", "label": "Period"},
                "y": {"field": "value", "type": "quantitative", "label": "'000 persons"},
                "color": {"field": "series", "type": "nominal", "label": "Measure"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "mpfa_claims_chart",
            "title": "MPFA Quarterly Permanent Departure Claims (HK$ Million)",
            "subtitle": "Total funds withdrawn from MPF accounts due to permanent departure from HK.",
            "type": "bar",
            "intent": "trend",
            "dataset": "mpfa_claims",
            "sourceId": "mpfa",
            "encodings": {
                "x": {"field": "quarter", "type": "nominal", "label": "Quarter"},
                "y": {"field": "amount_mhkd", "type": "quantitative", "label": "HK$ Million"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "mpfa_claims_count_chart",
            "title": "MPFA Quarterly Permanent Departure Claims (Count)",
            "subtitle": "Number of MPF claims paid for permanent departure from Hong Kong; shown separately from monetary amounts.",
            "type": "bar",
            "intent": "trend",
            "dataset": "mpfa_claims",
            "sourceId": "mpfa",
            "encodings": {
                "x": {"field": "quarter", "type": "nominal", "label": "Quarter"},
                "y": {"field": "claims_count", "type": "quantitative", "label": "Claims"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "ugc_students_chart",
            "title": "Mainland & Non-Local Students in HK Universities",
            "subtitle": "Academic year headcount in UGC-funded university programmes.",
            "type": "bar",
            "intent": "trend",
            "dataset": "ugc_students_comparison_history",
            "sourceId": "ugc",
            "encodings": {
                "x": {"field": "academic_year", "type": "nominal", "label": "Academic Year"},
                "y": {"field": "value", "type": "quantitative", "label": "Students"},
                "color": {"field": "series", "type": "nominal", "label": "Place of origin"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "td_cross_border_chart",
            "title": "Transport Department — GBA Cross-Border Vehicle & Train Traffic",
            "subtitle": "HZMB HK Vehicles ('Northbound Travel' 港车北上) and High-Speed Rail West Kowloon Passengers.",
            "type": "line",
            "intent": "trend",
            "dataset": "td_cross_border_comparison_history",
            "sourceId": "td",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "value", "type": "quantitative", "label": "Persons / vehicles"},
                "color": {"field": "series", "type": "nominal", "label": "Measure"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
    ]
    tables: list[dict[str, Any]] = []

    manifest_sources = [
        {
            "id": s["id"],
            "label": s["label"],
            "href": s["href"],
            "query": s["query"],
        }
        for s in PUBLIC_SOURCES.values()
    ]

    source_row_counts = {
        "immd": len(immd_rows),
        "csd": len(pop_rows),
        "mpfa": len(mpfa_rows),
        "ugc": len(ugc_rows),
        "td": len(td_rows),
    }
    source_latest_observation = {
        "immd": _latest_observation(immd_rows, "date"),
        "csd": _latest_observation(pop_rows, "period"),
        "mpfa": _latest_observation(mpfa_rows, "quarter"),
        "ugc": _latest_observation(ugc_rows, "academic_year"),
        "td": _latest_observation(td_rows, "month"),
    }
    source_health = [
        {
            "id": s["id"],
            "label": s["label"],
            "status": "success" if source_row_counts[key] > 0 else "degraded",
            "records": source_row_counts[key],
            "latest_observation": source_latest_observation[key],
            "freshness": "dated" if source_row_counts[key] > 0 else "unavailable",
            "notes": s["query"]["description"],
        }
        for key, s in PUBLIC_SOURCES.items()
    ]

    datasets = {
        "immd_daily_traffic": immd_rows,
        "immd_net_flow_history": immd_chart_rows,
        "csd_population": pop_rows,
        "csd_population_movement_history": population_chart_rows,
        "mpfa_claims": mpfa_rows,
        "ugc_students": ugc_rows,
        "ugc_students_comparison_history": ugc_chart_rows,
        "td_cross_border": td_rows,
        "td_cross_border_comparison_history": td_chart_rows,
        "market_kpi_summary": [{
            "latest_pop": latest_pop,
            "latest_net_mov": latest_net_mov,
            "latest_mpfa": latest_mpfa,
            "latest_ugc": latest_ugc,
        }],
    }

    snapshot_payload = {
        "datasets": datasets,
        "source_urls": [s.get("href") for s in PUBLIC_SOURCES.values() if s.get("href")],
    }
    snapshot_id = hashlib.sha256(
        json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()[:16]

    latest_candidates = [
        (entry["latest_observation"], _observation_timestamp(entry["latest_observation"]))
        for entry in source_health
        if entry["latest_observation"] != "—"
    ]
    data_as_of = max(latest_candidates, key=lambda item: item[1])[0] if latest_candidates else generated_at[:10]
    overall_status = "Healthy" if all(entry["status"] == "success" for entry in source_health) else "Degraded"

    blocks: list[dict[str, Any]] = [
        {
            "id": "snapshot_context",
            "type": "markdown",
            "body": (
                f"**Data snapshot:** `{snapshot_id}` · generated {generated_at}.  "
                "This is a published snapshot, not a live connection. Official ImmD, C&SD, MPFA, UGC and TD open data."
            ),
        },
        {"id": "kpi_grid", "type": "metric-strip", "cardIds": [c["id"] for c in cards]},
    ]
    if immd_rows:
        blocks.append({"id": "immd_chart_block", "type": "chart", "chartId": "immd_net_flow_chart"})
    if pop_rows:
        blocks.append({"id": "csd_population_chart_block", "type": "chart", "chartId": "csd_population_chart"})
    if td_rows:
        blocks.append({"id": "td_cross_border_chart_block", "type": "chart", "chartId": "td_cross_border_chart"})
    if mpfa_rows:
        blocks.append({"id": "mpfa_claims_chart_block", "type": "chart", "chartId": "mpfa_claims_chart", "layout": "half"})
        blocks.append({"id": "mpfa_claims_count_chart_block", "type": "chart", "chartId": "mpfa_claims_count_chart", "layout": "half"})
    if ugc_rows:
        blocks.append({"id": "ugc_students_chart_block", "type": "chart", "chartId": "ugc_students_chart", "layout": "full"})

    blocks.append(
        {
            "id": "methodology",
            "type": "markdown",
            "body": (
                "## Reading the Population, Migration & Cross-Border Monitor\n\n"
                "This monitor combines high-frequency daily cross-border passenger flow (ImmD) with official low-frequency "
                "structural series: C&SD half-yearly population estimates and net movement (One-way Permit holders vs. "
                "others), MPFA quarterly permanent-departure claims, UGC non-local student enrolment, and Transport "
                "Department cross-boundary vehicle/rail traffic. Insurance Authority Mainland Visitor premium statistics "
                "are not shown: the regulator suspended that series from Q1 2025 pending a review of scope and criteria, "
                "and no real substitute source exists. No investment recommendation is produced."
            ),
        }
    )

    artifact = {
        "surface": "dashboard",
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "Hong Kong Population, Migration & Cross-Border Data Monitor",
            "description": "High-frequency passenger net flow, population estimates, MPF departure claims, Mainland student enrolment & GBA transport signals.",
            "sector": "hk-population-migration",
            "generatedAt": generated_at,
            "dataAsOf": data_as_of,
            "liveSourcesCount": sum(1 for entry in source_health if entry["status"] == "success"),
            "totalSourcesCount": len(PUBLIC_SOURCES),
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": manifest_sources,
            "blocks": blocks,
        },
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready" if overall_status == "Healthy" else "partial", "datasets": datasets},
        "sources": manifest_sources,
        "source_health": source_health,
        "package_info": {
            "originUrl": "https://asia-markets-dashboard.pages.dev/sectors/hk-population-migration/",
            "sector_id": "hk-population-migration",
            "sector_name": "Hong Kong Population, Migration & Cross-Border Data Monitor",
            "snapshotId": snapshot_id,
            "generatedAt": generated_at,
            "dataAsOf": data_as_of,
        },
    }

    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": artifact["package_info"]["dataAsOf"],
        "overall_status": overall_status,
        "live_sources": sum(1 for entry in source_health if entry["status"] == "success"),
        "planned_sources": 0,
        "sources": [
            {
                "source": entry["label"],
                "dataset": entry["id"],
                "type": "Monitor",
                "status": "Healthy" if entry["status"] == "success" else "Degraded",
                "latest_observation": entry["latest_observation"],
                "records": entry["records"],
                "freshness": "Dated snapshot" if entry["freshness"] == "dated" else "Unavailable",
                "notes": entry["notes"],
            }
            for entry in source_health
        ],
        "attachment_filename": f"hk-population-migration-dashboard-{now.date().isoformat()}.html",
    }

    return artifact, status


def _clean_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _clean_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_json(v) for v in obj]
    if isinstance(obj, float) and pd.isna(obj):
        return None
    return obj


def main() -> int:
    parser = argparse.ArgumentParser(description="Build HK Population & Migration Sector Artifact")
    parser.add_argument("--output", required=True, help="Canonical artifact JSON output path")
    parser.add_argument("--status-output", required=True, help="Compact status JSON output path")
    args = parser.parse_args()

    logger.info("Building HK Population & Migration Artifact...")
    artifact, status = build_artifact()

    artifact_clean = _clean_json(artifact)
    status_clean = _clean_json(status)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact_clean, indent=2, ensure_ascii=False), encoding="utf-8")

    status_path = Path(args.status_output)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status_clean, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({"ok": True, "artifact": args.output, "snapshot_id": status_clean["snapshot_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
