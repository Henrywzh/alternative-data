"""Build canonical JSON artifact and Astro status for HK Telecom Sector Monitor."""

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

from src.hk_telecom.sources.hkt_operating_drivers import fetch_hkt_operating_drivers
from src.hk_telecom.sources.hutchison_telecom_operating_drivers import fetch_hutchison_telecom_operating_drivers
from src.hk_telecom.sources.numbering_plan import fetch_numbering_plan
from src.hk_telecom.sources.smartone_operating_drivers import fetch_smartone_operating_drivers


PUBLIC_SOURCES = {
    "hkt_operating_drivers": {
        "id": "hkt_operating_drivers",
        "label": "HKT Trust & HKT Limited (6823.HK) Results Announcements",
        "href": "https://www.hkt.com/en/about-hkt/investor-relations/financial-results/",
        "path": "sources/hkt_operating_drivers.sql",
        "query": {
            "engine": "official HKEX results announcement (PDF)",
            "url": "https://www.hkt.com/en/about-hkt/investor-relations/financial-results/",
            "language": "PDF",
            "description": "Semi-annual Key Operating Drivers table (mobile postpaid/prepaid subscribers, consumer broadband lines, Pay TV base) plus postpaid exit ARPU and FTTH share, extracted from HKT's own results announcement narrative text.",
        },
    },
    "smartone_operating_drivers": {
        "id": "smartone_operating_drivers",
        "label": "SmarTone Telecommunications Holdings (0315.HK) Results Presentations",
        "href": "https://www.smartoneholdings.com/about/investor/results/",
        "path": "sources/smartone_operating_drivers.sql",
        "query": {
            "engine": "official investor-relations results presentation (PDF)",
            "url": "https://www.smartoneholdings.com/about/investor/results/",
            "language": "PDF",
            "description": "Semi-annual mobile postpaid customer count, postpaid ARPU trend, and 5G-vs-4G ARPU ratio from SmarTone's own results presentation deck.",
        },
    },
    "hutchison_telecom_operating_drivers": {
        "id": "hutchison_telecom_operating_drivers",
        "label": "Hutchison Telecom HK Holdings (0215.HK, \"3 HK\") Results Announcements",
        "href": "https://www.hthkh.com/en/ir/fin_results.php",
        "path": "sources/hutchison_telecom_operating_drivers.sql",
        "query": {
            "engine": "official HKEX results announcement (PDF)",
            "url": "https://www.hthkh.com/en/ir/fin_results.php",
            "language": "PDF",
            "description": "Semi-annual Key Performance Indicators table: postpaid/prepaid customers, monthly postpaid churn rate, postpaid gross & net ARPU, and 5G penetration rate.",
        },
    },
    "numbering_plan": {
        "id": "numbering_plan",
        "label": "OFCA Numbering Plan (Mobile Number Block Allocations)",
        "href": "https://www.ofca.gov.hk/filemanager/ofca/common/datagovhk/tel_no_en_tc.csv",
        "path": "sources/numbering_plan.sql",
        "query": {
            "engine": "official open data CSV",
            "url": "https://www.ofca.gov.hk/filemanager/ofca/common/datagovhk/tel_no_en_tc.csv",
            "language": "CSV",
            "description": "Mobile number block allocations by operator, all 4 licensed MNOs plus MVNOs -- a capacity/footprint proxy, not a subscriber-count or time-series metric (see table caveat).",
        },
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _records_json_safe(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a DataFrame to JSON-safe records (NaN/NaT -> null, dates -> ISO strings)."""
    selected = frame.copy()
    for column in selected.columns:
        if pd.api.types.is_datetime64_any_dtype(selected[column]):
            selected[column] = selected[column].dt.strftime("%Y-%m-%d")
    return json.loads(selected.to_json(orient="records", date_format="iso"))


def build_artifact(
    raw_hkt: pd.DataFrame | None = None,
    raw_smartone: pd.DataFrame | None = None,
    raw_hutchison: pd.DataFrame | None = None,
    raw_numbering_plan: pd.DataFrame | None = None,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()

    hkt = raw_hkt if raw_hkt is not None else fetch_hkt_operating_drivers()
    smartone = raw_smartone if raw_smartone is not None else fetch_smartone_operating_drivers()
    hutchison = raw_hutchison if raw_hutchison is not None else fetch_hutchison_telecom_operating_drivers()
    numbering_plan = raw_numbering_plan if raw_numbering_plan is not None else fetch_numbering_plan()

    # Semi-annual reporting periods land on distinct months (e.g. Jun/Dec),
    # so a "YYYY-MM" `month` column is a lossless companion to `date`. Chart
    # x-axes are encoded against `month` rather than `date` because the
    # portable-chart plugin's date-axis formatter always includes the year
    # for month-granularity values but omits it by default for
    # day-granularity ones -- without this, multi-year semi-annual/annual
    # trends (e.g. three "Dec 31" points from three different years) render
    # with identical, year-ambiguous tick labels.
    for frame in (hkt, smartone, hutchison):
        if "date" in frame.columns:
            frame["month"] = frame["date"].dt.strftime("%Y-%m")

    generated_at = now.isoformat().replace("+00:00", "Z")

    hkt_latest = hkt.iloc[-1]
    hkt_prior = hkt.iloc[-2] if len(hkt) > 1 else None
    hkt_prior_arpu = float(hkt_prior["mobile_postpaid_arpu_hkd"]) if hkt_prior is not None and pd.notna(hkt_prior["mobile_postpaid_arpu_hkd"]) else 0.0
    hkt_kpi = {
        "latest_arpu": float(hkt_latest["mobile_postpaid_arpu_hkd"]) if pd.notna(hkt_latest["mobile_postpaid_arpu_hkd"]) else None,
        "postpaid_subscribers_thousands": float(hkt_latest["mobile_postpaid_subscribers_thousands"]) if pd.notna(hkt_latest["mobile_postpaid_subscribers_thousands"]) else None,
        "ftth_share_pct": (
            float(hkt_latest["ftth_share_pct"])
            if pd.notna(hkt_latest.get("ftth_share_pct"))
            else None
        ),
        "ftth_connections_thousands": (
            float(hkt_latest["ftth_connections_thousands"])
            if pd.notna(hkt_latest.get("ftth_connections_thousands"))
            else None
        ),
        "pay_tv_installed_base_thousands": (
            float(hkt_latest["pay_tv_installed_base_thousands"])
            if pd.notna(hkt_latest.get("pay_tv_installed_base_thousands"))
            else None
        ),
        "consumer_broadband_lines_thousands": float(hkt_latest["consumer_broadband_lines_thousands"]) if pd.notna(hkt_latest["consumer_broadband_lines_thousands"]) else None,
        "period_change": (
            round(float(hkt_latest["mobile_postpaid_arpu_hkd"]) / hkt_prior_arpu - 1, 6)
            if hkt_prior_arpu
            else None
        ),
        "observation_date": hkt_latest["date"].strftime("%Y-%m-%d"),
    }

    st_latest = smartone.iloc[-1]
    st_prior = smartone.iloc[-2] if len(smartone) > 1 else None
    st_prior_arpu = float(st_prior["postpaid_arpu_hkd"]) if st_prior is not None and pd.notna(st_prior["postpaid_arpu_hkd"]) else 0.0
    st_kpi = {
        "latest_arpu": float(st_latest["postpaid_arpu_hkd"]) if pd.notna(st_latest["postpaid_arpu_hkd"]) else None,
        "postpaid_subscribers_thousands": float(st_latest["postpaid_subscribers_thousands"]) if pd.notna(st_latest["postpaid_subscribers_thousands"]) else None,
        "arpu_5g_to_4g_ratio": float(st_latest["arpu_5g_to_4g_ratio"]) if pd.notna(st_latest["arpu_5g_to_4g_ratio"]) else None,
        "period_change": (
            round(float(st_latest["postpaid_arpu_hkd"]) / st_prior_arpu - 1, 6)
            if st_prior_arpu
            else None
        ),
        "observation_date": st_latest["date"].strftime("%Y-%m-%d"),
    }

    hu_latest = hutchison.iloc[-1]
    hu_prior = hutchison.iloc[-2] if len(hutchison) > 1 else None
    hu_prior_arpu = float(hu_prior["postpaid_gross_arpu_hkd"]) if hu_prior is not None and pd.notna(hu_prior["postpaid_gross_arpu_hkd"]) else 0.0
    hu_kpi = {
        "latest_gross_arpu": float(hu_latest["postpaid_gross_arpu_hkd"]) if pd.notna(hu_latest["postpaid_gross_arpu_hkd"]) else None,
        "latest_net_arpu": float(hu_latest["postpaid_net_arpu_hkd"]) if pd.notna(hu_latest["postpaid_net_arpu_hkd"]) else None,
        "postpaid_customers_thousands": float(hu_latest["postpaid_customers_thousands"]) if pd.notna(hu_latest["postpaid_customers_thousands"]) else None,
        "churn_rate_pct": float(hu_latest["postpaid_churn_rate_pct"]) if pd.notna(hu_latest["postpaid_churn_rate_pct"]) else None,
        "penetration_5g_pct": float(hu_latest["penetration_5g_pct"]) if pd.notna(hu_latest["penetration_5g_pct"]) else None,
        "period_change": (
            round(float(hu_latest["postpaid_gross_arpu_hkd"]) / hu_prior_arpu - 1, 6)
            if hu_prior_arpu
            else None
        ),
        "observation_date": hu_latest["date"].strftime("%Y-%m-%d"),
    }

    datasets = {
        "kpi_hkt": [hkt_kpi],
        "kpi_smartone": [st_kpi],
        "kpi_hutchison": [hu_kpi],
        "hkt_history": _records_json_safe(hkt),
        "hkt_footprint_history": sorted(
            (
                r for _, row in hkt.iterrows()
                for col, label in [("ftth_connections_thousands", "FTTH connections"), ("pay_tv_installed_base_thousands", "Pay TV base")]
                for val in [row.get(col)]
                if pd.notna(row.get("date")) and pd.notna(val)
                for date_str in [row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])[:10]]
                for month_str in [row.get("month") if pd.notna(row.get("month")) else date_str[:7]]
                for r in [{"date": date_str, "month": str(month_str), "series": label, "value": round(float(val), 2)}]
            ),
            key=lambda r: (r["series"], r["date"]),
        ),
        "smartone_history": _records_json_safe(smartone),
        "hutchison_history": _records_json_safe(hutchison),
        "numbering_plan_snapshot": _records_json_safe(numbering_plan),
    }

    cards = [
        {
            "id": "hkt_card",
            "description": "HKT (6823.HK) postpaid exit ARPU and postpaid subscribers, semi-annual.",
            "dataset": "kpi_hkt",
            "sourceId": "hkt_operating_drivers",
            "metrics": [
                {"label": "Postpaid ARPU (HK$)", "field": "latest_arpu", "format": "number"},
                {"label": "Postpaid Subscribers ('000)", "field": "postpaid_subscribers_thousands", "format": "number"},
                {"label": "Half-on-Half", "field": "period_change", "format": "percent"},
                {
                    "label": "FTTH Share (%)",
                    "field": "ftth_share_pct",
                    "format": "number",
                },
            ],
        },
        {
            "id": "hkt_footprint_card",
            "description": "HKT broadband access lines, FTTH connections, and Pay TV installed base ('000s).",
            "dataset": "kpi_hkt",
            "sourceId": "hkt_operating_drivers",
            "metrics": [
                {"label": "Broadband Lines ('000)", "field": "consumer_broadband_lines_thousands", "format": "number"},
                {"label": "FTTH ('000)", "field": "ftth_connections_thousands", "format": "number"},
                {"label": "Pay TV Base ('000)", "field": "pay_tv_installed_base_thousands", "format": "number"},
                {"label": "FTTH Share (%)", "field": "ftth_share_pct", "format": "number"},
            ],
        },
        {
            "id": "smartone_card",
            "description": "SmarTone (0315.HK) postpaid ARPU and postpaid subscribers, semi-annual.",
            "dataset": "kpi_smartone",
            "sourceId": "smartone_operating_drivers",
            "metrics": [
                {"label": "Postpaid ARPU (HK$)", "field": "latest_arpu", "format": "number"},
                {"label": "Postpaid Subscribers ('000)", "field": "postpaid_subscribers_thousands", "format": "number"},
                {"label": "Year-on-Year", "field": "period_change", "format": "percent"},
            ],
        },
        {
            "id": "hutchison_card",
            "description": "Hutchison Telecom / 3 HK (0215.HK) postpaid gross & net ARPU and churn, semi-annual.",
            "dataset": "kpi_hutchison",
            "sourceId": "hutchison_telecom_operating_drivers",
            "metrics": [
                {"label": "Postpaid Gross ARPU (HK$)", "field": "latest_gross_arpu", "format": "number"},
                {"label": "Postpaid Net ARPU (HK$)", "field": "latest_net_arpu", "format": "number"},
                {"label": "Half-on-Half", "field": "period_change", "format": "percent"},
            ],
        },
    ]

    charts = [
        {
            "id": "hkt_arpu_chart",
            "title": "HKT Postpaid Exit ARPU Trend (HK$)",
            "subtitle": "Semi-annual postpaid exit ARPU, extracted from HKT's own results announcement narrative text.",
            "type": "line",
            "dataset": "hkt_history",
            "sourceId": "hkt_operating_drivers",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Period"},
                "y": {"field": "mobile_postpaid_arpu_hkd", "type": "quantitative", "label": "HK$"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "smartone_arpu_chart",
            "title": "SmarTone Postpaid ARPU & Subscriber Trend",
            "subtitle": "Semi-annual postpaid ARPU (HK$) and postpaid subscriber base ('000s).",
            "type": "line",
            "dataset": "smartone_history",
            "sourceId": "smartone_operating_drivers",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Period"},
                "y": {"field": "postpaid_arpu_hkd", "type": "quantitative", "label": "HK$"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "hutchison_arpu_chart",
            "title": "Hutchison Telecom (3 HK) Gross vs Net Postpaid ARPU",
            "subtitle": "Semi-annual postpaid gross and net ARPU (HK$) -- the richest per-user economics disclosure of the three operators.",
            "type": "line",
            "dataset": "hutchison_history",
            "sourceId": "hutchison_telecom_operating_drivers",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Period"},
                "y": {"field": "postpaid_gross_arpu_hkd", "type": "quantitative", "label": "HK$"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "hkt_footprint_chart",
            "title": "HKT Broadband & Pay TV Footprint ('000s)",
            "subtitle": "Semi-annual FTTH connections and Pay TV installed base.",
            "type": "line",
            "intent": "comparison",
            "dataset": "hkt_footprint_history",
            "sourceId": "hkt_operating_drivers",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Period"},
                "y": {"field": "value", "type": "quantitative", "label": "'000s"},
                "color": {"field": "series", "type": "nominal", "label": "Metric"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
    ]

    tables: list[dict[str, Any]] = [
        {
            "id": "numbering_plan_table",
            "title": "OFCA Mobile Number Block Allocations by Operator",
            "subtitle": (
                "Coarse structural proxy covering all 4 licensed mobile network operators plus MVNOs. "
                "Number blocks are issued mobile-number capacity, not active subscriber counts -- there is no "
                "visibility into what fraction of an allocated block is actually in use, and reassignment is "
                "irregular/event-driven. Treat this as a single capacity snapshot, not a subscriber trend."
            ),
            "dataset": "numbering_plan_snapshot",
            "sourceId": "numbering_plan",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "allocatee", "label": "Operator / Licensee", "type": "text"},
                {"field": "num_blocks", "label": "Number Blocks", "format": "number"},
                {"field": "total_numbers_allocated", "label": "Numbers Allocated", "format": "number"},
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
            "title": "Hong Kong Telecom Sector Monitor",
            "description": "HKT, SmarTone, and Hutchison Telecom (3 HK) semi-annual postpaid subscriber and ARPU disclosures, plus an OFCA all-operator mobile-number-block capacity snapshot.",
            "sector": "hk-telecom",
            "generatedAt": generated_at,
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": sources,
            "blocks": [
                {"id": "kpi_grid", "type": "metric-strip", "cardIds": [c["id"] for c in cards]},
                {"id": "hkt_chart", "type": "chart", "chartId": "hkt_arpu_chart"},
                {"id": "smartone_chart", "type": "chart", "chartId": "smartone_arpu_chart"},
                {"id": "hutchison_chart", "type": "chart", "chartId": "hutchison_arpu_chart"},
                {"id": "numbering_plan_table_block", "type": "table", "tableId": "numbering_plan_table"},
            ],
        },
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready", "datasets": datasets},
        "sources": sources,
        "package_info": {"originUrl": "https://asia-markets-dashboard.pages.dev/sectors/hk-telecom/", "snapshotId": snapshot_id, "dataAsOf": hkt_kpi["observation_date"]},
    }

    record_counts = {
        "hkt_operating_drivers": len(hkt),
        "smartone_operating_drivers": len(smartone),
        "hutchison_telecom_operating_drivers": len(hutchison),
        "numbering_plan": len(numbering_plan),
    }
    latest_observation_dates = {
        "hkt_operating_drivers": hkt_kpi["observation_date"],
        "smartone_operating_drivers": st_kpi["observation_date"],
        "hutchison_telecom_operating_drivers": hu_kpi["observation_date"],
        "numbering_plan": hkt_kpi["observation_date"],
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
                "type": "Measure" if s["id"] != "numbering_plan" else "Context",
                "status": "Healthy" if record_counts[s["id"]] > 0 else "Degraded",
                "latest_observation": latest_observation_dates[s["id"]],
                "records": record_counts[s["id"]],
                "freshness": "Live" if s["id"] != "numbering_plan" else "Snapshot (irregular updates)",
                "notes": s["query"]["description"],
            }
            for s in PUBLIC_SOURCES.values()
        ],
        "attachment_filename": f"hk-telecom-dashboard-{now.date().isoformat()}.html",
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
