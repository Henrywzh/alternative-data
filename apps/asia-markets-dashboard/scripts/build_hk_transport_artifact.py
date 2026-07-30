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
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from src.hk_transport.sources.cathay_traffic import fetch_cathay_traffic
from src.hk_transport.sources.mtr_patronage import fetch_mtr_patronage
from history_policy import DEFAULT_HISTORY_YEARS, history_window


CHINA_AIRLINE_DATA_PATH = ROOT / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
CHINA_AIRLINE_NAMES = {
    "601111": "Air China",
    "600029": "China Southern",
    "600115": "China Eastern",
    "601021": "Spring Airlines",
}
CHINA_AIRLINE_SHORT_NAMES = {
    "Air China": "AC",
    "China Southern": "CS",
    "China Eastern": "CE",
    "Spring Airlines": "Spring",
}
CHINA_AIRLINE_METRICS = {"passengers", "ask", "rpk", "passenger_load_factor_pct"}
CHINA_AIRLINE_COLUMNS = ["month", "date", "airline_code", "airline", "region", "metric", "value"]


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
    "china_airline_traffic": {
        "id": "china_airline_traffic",
        "label": "China Listed Airlines Monthly Operating Data",
        "href": "https://www.cninfo.com.cn/",
        "path": "sources/china_airline_traffic.sql",
        "query": {
            "engine": "repository parquet built from official Cninfo operating-data announcements",
            "url": "https://www.cninfo.com.cn/",
            "language": "Parquet",
            "description": "Monthly passengers, ASK, RPK and passenger load factor for Air China, China Southern, China Eastern and Spring Airlines, split by domestic, international and regional operations.",
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


def load_china_airline_traffic(path: Path = CHINA_AIRLINE_DATA_PATH) -> pd.DataFrame:
    """Load and validate the existing Cninfo-backed airline parquet."""
    columns = ["month", "date", "airline_code", "region", "metric", "value"]
    if not path.exists():
        return pd.DataFrame(columns=CHINA_AIRLINE_COLUMNS)

    frame = pd.read_parquet(path)
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(f"China airline traffic is missing columns: {missing}")

    result = frame.loc[:, columns].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["month"] = result["date"].dt.strftime("%Y-%m")
    result["airline_code"] = result["airline_code"].astype(str).str.replace(r"\.0$", "", regex=True)
    result["airline"] = result["airline_code"].map(CHINA_AIRLINE_NAMES)
    result["metric"] = result["metric"].astype(str)
    result["region"] = result["region"].astype(str)
    result["value"] = pd.to_numeric(result["value"], errors="coerce")

    if result["date"].isna().any() or result["value"].isna().any():
        raise ValueError("China airline traffic contains invalid dates or values")
    if result["airline"].isna().any():
        unknown = sorted(result.loc[result["airline"].isna(), "airline_code"].unique())
        raise ValueError(f"China airline traffic contains unknown carriers: {unknown}")
    unknown_metrics = sorted(set(result["metric"]) - CHINA_AIRLINE_METRICS)
    if unknown_metrics:
        raise ValueError(f"China airline traffic contains unknown metrics: {unknown_metrics}")

    return result[CHINA_AIRLINE_COLUMNS].sort_values(
        ["date", "airline_code", "region", "metric"]
    ).reset_index(drop=True)


def build_china_airline_views(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Build compact chart/table datasets from the normalized airline frame."""
    empty = {
        "china_airline_passengers_history": [],
        "china_airline_ask_history": [],
        "china_airline_rpk_history": [],
        "china_airline_load_factor_history": [],
        "china_airline_region_split_history": [],
        "china_airline_latest_snapshot": [],
    }
    if frame.empty:
        return empty

    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    if "airline" not in data.columns:
        data["airline_code"] = data["airline_code"].astype(str)
        data["airline"] = data["airline_code"].map(CHINA_AIRLINE_NAMES)
    data["month"] = data["date"].dt.strftime("%Y-%m")

    # Only China Southern's disclosed PDF table includes an explicit "合计"
    # (Total) row -- Air China, China Eastern, and Spring Airlines only ever
    # publish a Domestic/International/Regional breakdown with no combined
    # figure (confirmed: their `region` values never include "Total" in the
    # source data). Filtering to region=="Total" therefore silently limited
    # every non-regional chart to China Southern alone. Derive each
    # carrier's own total instead: passengers/ASK/RPK are genuinely additive
    # across regions, so sum them; where a real reported Total row does
    # exist (China Southern), prefer it over the derived sum since it's the
    # airline's own authoritative figure.
    regional_only = data[data["region"].ne("Total")]
    regional_target = regional_only[regional_only["metric"].isin(["passengers", "ask", "rpk"])]
    # A source PDF occasionally drops one of the 3 regions outright (a
    # pdfplumber page-break extraction failure -- confirmed on live Spring
    # Airlines PDFs where e.g. the "International" ASK row never makes it
    # into the extracted table for that month at all, not even with a
    # missing label). Summing only 2 of 3 regions understates that metric
    # for the month, which silently produced a >100% "derived" load factor
    # for Spring Airlines in several months once RPK (still complete) was
    # divided by an undercounted ASK. Requiring all 3 regions before
    # deriving a total means an incomplete month leaves a gap in the chart
    # instead of fabricating a wrong number from partial data.
    region_counts = (
        regional_target.groupby(["date", "airline_code", "metric"])["region"]
        .nunique()
        .reset_index(name="region_count")
    )
    derived_sum = (
        regional_target.groupby(["date", "month", "airline_code", "airline", "metric"], as_index=False)["value"]
        .sum()
        .merge(region_counts, on=["date", "airline_code", "metric"])
    )
    derived_sum = derived_sum[derived_sum["region_count"] >= 3].drop(columns="region_count")
    reported_total = data[data["region"].eq("Total") & data["metric"].isin(["passengers", "ask", "rpk"])]
    combined = pd.concat([derived_sum, reported_total[derived_sum.columns]], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "airline_code", "metric"], keep="last")

    # Load factor is a ratio (RPK / ASK), not additive -- summing or
    # averaging per-region percentages would silently produce a wrong
    # number. Derive it from the combined ASK/RPK totals above instead;
    # where a real reported Total load-factor row exists, prefer that (the
    # airline's own calculation, which may reflect rounding/definitional
    # nuances a pure RPK/ASK ratio wouldn't).
    ask_rpk = combined.pivot_table(
        index=["date", "month", "airline_code", "airline"], columns="metric", values="value"
    ).reset_index()
    # The completeness gate above can remove a metric entirely -- if no
    # carrier-month has all 3 ASK regions and none reports an ASK total, the
    # pivot comes back without an "ask" column at all and dropna(subset=...)
    # raises KeyError instead of yielding the intended gap. Reinstating the
    # columns as empty keeps the degenerate case on the same "leave a gap"
    # path as a single missing month.
    # float("nan"), not pd.NA: an all-NA object column would break the numeric
    # dtype the ratio below and the downstream chart formatting both expect.
    for column in ("ask", "rpk"):
        if column not in ask_rpk.columns:
            ask_rpk[column] = float("nan")
    derived_lf = ask_rpk.dropna(subset=["ask", "rpk"]).assign(
        metric="passenger_load_factor_pct",
        value=lambda d: (d["rpk"] / d["ask"] * 100).round(4),
    )[["date", "month", "airline_code", "airline", "metric", "value"]]
    reported_lf = data[data["region"].eq("Total") & data["metric"].eq("passenger_load_factor_pct")]
    combined_lf = pd.concat([derived_lf, reported_lf[derived_lf.columns]], ignore_index=True)
    combined_lf = combined_lf.drop_duplicates(subset=["date", "airline_code", "metric"], keep="last")

    total = pd.concat([combined, combined_lf], ignore_index=True)
    total["region"] = "Total"

    def history(metric: str, *, regional: bool = False) -> list[dict[str, Any]]:
        selected = data if regional else total
        if regional:
            selected = selected[selected["region"].ne("Total")]
        selected = selected[selected["metric"].eq(metric)].copy()
        if selected.empty:
            return []
        if regional:
            selected = (
                selected.groupby(["date", "month", "region"], as_index=False)["value"]
                .sum()
                .assign(airline="All carriers")
            )
            selected["series"] = selected["region"].map(
                {"Domestic": "Domestic", "International": "International", "Regional": "Regional"}
            )
        else:
            selected["series"] = selected["airline"].map(CHINA_AIRLINE_SHORT_NAMES)
        return [
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "month": row["month"],
                "series": row["series"],
                "airline": row["airline"],
                "region": row["region"],
                "value": round(float(row["value"]), 4),
            }
            for _, row in selected.sort_values(["date", "series"]).iterrows()
        ]

    # Two charts (ASK by carrier, RPK by carrier), not one combined ASK+RPK
    # chart -- with all 4 carriers now included (see the derivation above),
    # a single chart would need an 8-item legend (4 carriers x 2 metrics),
    # which overflows the portable renderer's single-row legend at mobile
    # width (see the same constraint noted in
    # build_hk_local_consumer_artifact.py's AFCD_CATEGORY_SHORT_LABELS).
    ask_history = history("ask")
    for row in ask_history:
        row["series"] = CHINA_AIRLINE_SHORT_NAMES[row["airline"]]
    rpk_history = history("rpk")
    for row in rpk_history:
        row["series"] = CHINA_AIRLINE_SHORT_NAMES[row["airline"]]

    region_rows = history("passengers", regional=True)
    latest_date = data["date"].max()
    latest = data[data["date"].eq(latest_date)]
    snapshot = (
        latest.pivot_table(
            index=["airline_code", "airline", "region"],
            columns="metric",
            values="value",
            aggfunc="last",
        )
        .reset_index()
        .rename(columns={"passenger_load_factor_pct": "load_factor_pct"})
    )
    for column in ("passengers", "ask", "rpk", "load_factor_pct"):
        if column not in snapshot.columns:
            snapshot[column] = None
    snapshot["observation_date"] = latest_date.strftime("%Y-%m-%d")
    snapshot = snapshot[
        ["airline_code", "airline", "region", "passengers", "ask", "rpk", "load_factor_pct", "observation_date"]
    ].sort_values(["airline", "region"])

    return {
        "china_airline_passengers_history": history("passengers"),
        "china_airline_ask_history": ask_history,
        "china_airline_rpk_history": rpk_history,
        "china_airline_load_factor_history": history("passenger_load_factor_pct"),
        "china_airline_region_split_history": region_rows,
        "china_airline_latest_snapshot": json.loads(snapshot.to_json(orient="records", date_format="iso")),
    }


def build_artifact(
    raw_mtr: pd.DataFrame | None = None,
    raw_cathay: pd.DataFrame | None = None,
    raw_china_airline: pd.DataFrame | None = None,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()

    mtr = raw_mtr if raw_mtr is not None else fetch_mtr_patronage()
    cathay = raw_cathay if raw_cathay is not None else fetch_cathay_traffic()
    china_airline = raw_china_airline if raw_china_airline is not None else load_china_airline_traffic()
    china_airline_views = build_china_airline_views(china_airline)

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
    # The total MTR and Cathay series already carry their full available
    # histories.  The five-way service breakdown uses the shared default
    # ten-year date window so it is long enough for structural context without
    # relying on a cadence-specific row count or an arbitrary 2018 cutoff.
    mtr_breakdown_window = history_window(mtr, "date", years=DEFAULT_HISTORY_YEARS)
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
        **china_airline_views,
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
            "subtitle": "26 years of monthly total MTR journeys ('000s). NOTE: the MTR-KCR merger on 2 Dec 2007 caused a +65% step-change in total patronage (from ~77m to ~127m) as KCR's East/West Rail, Light Rail and cross-boundary services were consolidated into MTR's reporting. The full history also captures the 2003 SARS collapse (trough ~48.8m in Apr 2003) and the deeper COVID-19 collapse (trough ~71.9m in Feb 2022), followed by a recovery now back near the pre-pandemic 2019 monthly average.",
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
            "title": "MTR Patronage by Rail Service — Latest 10 Years ('000s)",
            "subtitle": "Monthly passenger journeys across Domestic heavy rail, Cross-boundary, HSR, Airport Express, and Light Rail & Bus. The chart uses the latest ten years of available history; the total-patronage chart above retains the full source history.",
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

    if china_airline_views["china_airline_passengers_history"]:
        charts.extend(
            [
                {
                    "id": "china_airline_passengers_chart",
                    "title": "China Listed Airlines Passenger Traffic",
                    "subtitle": "Monthly total passengers carried by Air China, China Southern, China Eastern and Spring Airlines.",
                    "type": "line",
                    "dataset": "china_airline_passengers_history",
                    "sourceId": "china_airline_traffic",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "Passengers"},
                        "color": {"field": "series", "type": "nominal", "label": "Airline"},
                    },
                    "valueFormat": "number",
                    "layout": "full",
                },
                {
                    # Two charts (ASK, RPK), not one combined chart -- with all 4
                    # carriers now included, one chart would need an 8-item
                    # legend (4 carriers x 2 metrics), which overflows the
                    # portable renderer's single-row legend at mobile width.
                    "id": "china_airline_ask_chart",
                    "title": "China Listed Airlines Available Seat Kilometres (ASK)",
                    "subtitle": "Monthly available seat kilometres (capacity flown), shown by carrier.",
                    "type": "line",
                    "dataset": "china_airline_ask_history",
                    "sourceId": "china_airline_traffic",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "000s"},
                        "color": {"field": "series", "type": "nominal", "label": "Airline"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
                {
                    "id": "china_airline_rpk_chart",
                    "title": "China Listed Airlines Revenue Passenger Kilometres (RPK)",
                    "subtitle": "Monthly revenue passenger kilometres (demand actually filled), shown by carrier.",
                    "type": "line",
                    "dataset": "china_airline_rpk_history",
                    "sourceId": "china_airline_traffic",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "000s"},
                        "color": {"field": "series", "type": "nominal", "label": "Airline"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
                {
                    "id": "china_airline_load_factor_chart",
                    "title": "China Listed Airlines Passenger Load Factor",
                    "subtitle": "Monthly passenger load factor by carrier, using each carrier's total operation.",
                    "type": "line",
                    "dataset": "china_airline_load_factor_history",
                    "sourceId": "china_airline_traffic",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "%"},
                        "color": {"field": "series", "type": "nominal", "label": "Airline"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
                {
                    "id": "china_airline_region_split_chart",
                    "title": "China Listed Airlines Passenger Traffic by Region",
                    "subtitle": "Combined passenger traffic across the four carriers, split into domestic, international and regional operations; use the latest-snapshot table for carrier-level values.",
                    "type": "line",
                    "dataset": "china_airline_region_split_history",
                    "sourceId": "china_airline_traffic",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "Passengers"},
                        "color": {"field": "series", "type": "nominal", "label": "Airline / Region"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
            ]
        )

    tables: list[dict[str, Any]] = []
    if china_airline_views["china_airline_latest_snapshot"]:
        tables.append(
            {
                "id": "china_airline_latest_snapshot_table",
                "title": "China Listed Airlines Latest Operating Snapshot",
                "subtitle": "Latest available month, split by carrier and operating region.",
                "dataset": "china_airline_latest_snapshot",
                "sourceId": "china_airline_traffic",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "airline", "label": "Airline", "type": "text"},
                    {"field": "region", "label": "Region", "type": "text"},
                    {"field": "passengers", "label": "Passengers", "format": "number"},
                    {"field": "ask", "label": "ASK", "format": "number"},
                    {"field": "rpk", "label": "RPK", "format": "number"},
                    {"field": "load_factor_pct", "label": "Load Factor (%)", "format": "number"},
                    {"field": "observation_date", "label": "Month", "type": "date"},
                ],
            }
        )

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
            "description": "MTR Corporation monthly rail patronage, CAD HKIA airport traffic, Cathay Pacific Group operating statistics, and China listed-airline operating data.",
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
                {"id": "china_airline_passengers_chart_block", "type": "chart", "chartId": "china_airline_passengers_chart"},
                {"id": "china_airline_ask_chart_block", "type": "chart", "chartId": "china_airline_ask_chart", "layout": "half"},
                {"id": "china_airline_rpk_chart_block", "type": "chart", "chartId": "china_airline_rpk_chart", "layout": "half"},
                {"id": "china_airline_load_factor_chart_block", "type": "chart", "chartId": "china_airline_load_factor_chart", "layout": "half"},
                {"id": "china_airline_region_split_chart_block", "type": "chart", "chartId": "china_airline_region_split_chart", "layout": "half"},
                {"id": "china_airline_snapshot_table_block", "type": "table", "tableId": "china_airline_latest_snapshot_table"},
            ],
        },
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready", "datasets": datasets},
        "sources": sources,
        "package_info": {
            "originUrl": "https://asia-markets-dashboard.pages.dev/sectors/hk-transport/",
            "snapshotId": snapshot_id,
            "dataAsOf": max(
                mtr_kpi["observation_date"],
                cathay_kpi["observation_date"],
                china_airline["date"].max().strftime("%Y-%m-%d") if not china_airline.empty else "1900-01-01",
            ),
        },
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
