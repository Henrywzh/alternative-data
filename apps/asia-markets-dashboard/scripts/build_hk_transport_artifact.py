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
TRANSPORT_DATA_DIR = ROOT / "data" / "processed" / "transport"
PASSENGER_JOURNEYS_DATA_PATH = TRANSPORT_DATA_DIR / "hk_passenger_journeys_monthly.parquet"
MTTD_PASSENGER_JOURNEYS_DATA_PATH = TRANSPORT_DATA_DIR / "mttd_passenger_journeys_monthly.parquet"
BOUNDARY_MOVEMENTS_DATA_PATH = TRANSPORT_DATA_DIR / "censtatd_boundary_movements_monthly.parquet"
VEHICLE_STOCK_DATA_PATH = TRANSPORT_DATA_DIR / "hk_vehicle_stock_monthly.parquet"
NET_GROWTH_DATA_PATH = TRANSPORT_DATA_DIR / "hk_private_car_net_growth_monthly.parquet"
PRIVATE_CAR_FIRST_REG_DATA_PATH = TRANSPORT_DATA_DIR / "hk_private_car_first_reg_monthly.parquet"
PRIVATE_CAR_FIRST_REG_MODEL_DATA_PATH = TRANSPORT_DATA_DIR / "hk_private_car_first_reg_model_latest.parquet"
PARKING_VACANCY_DATA_PATH = TRANSPORT_DATA_DIR / "hk_parking_vacancy_snapshots.parquet"
CARPARK_OCCUPANCY_DATA_PATH = TRANSPORT_DATA_DIR / "hk_carpark_occupancy_snapshots.parquet"

PASSENGER_JOURNEYS_COLUMNS = [
    "date", "kmb_k", "citybus_subtotal_k", "nwfb_k", "lwb_k", "nlb_k", "bus_subtotal_k",
    "mtr_heavy_rail_k", "airport_express_k", "light_rail_k", "tramways_k", "rail_subtotal_k",
    "plb_subtotal_k", "ferry_subtotal_k", "taxis_k", "total_k",
]
MTTD_PASSENGER_JOURNEYS_COLUMNS = [
    "date", "month", "bus_rail", "pto_code", "franchise_type", "rail_line",
    "pax_hk_k", "pax_kln_nt_k", "pax_cross_harbour_k", "total_passenger_journeys_k",
]
BOUNDARY_MOVEMENTS_COLUMNS = [
    "date", "month", "aircraft_arrivals", "aircraft_departures", "aircraft_total",
    "ocean_vessels_arrivals", "ocean_vessels_departures", "ocean_vessels_arrival_thousand_nt",
    "ocean_vessels_departure_thousand_nt", "river_vessels_prc_arrivals",
    "river_vessels_prc_departures", "river_vessels_prc_arrival_thousand_nt",
    "river_vessels_prc_departure_thousand_nt", "river_vessels_macao_arrivals",
    "river_vessels_macao_departures", "river_vessels_macao_arrival_thousand_nt",
    "river_vessels_macao_departure_thousand_nt", "cargo_vessels_arrivals",
    "cargo_vessels_departures", "cargo_vessels_arrival_thousand_nt",
    "cargo_vessels_departure_thousand_nt", "goods_vehicles_arrivals",
    "goods_vehicles_departures", "goods_vehicles_total", "passenger_vehicles_arrivals",
    "passenger_vehicles_departures", "passenger_vehicles_total", "passenger_trains_arrivals",
    "passenger_trains_departures", "passenger_trains_total", "is_estimate",
]
VEHICLE_STOCK_COLUMNS = [
    "date", "petrol_total_registered", "electric_total_registered",
    "diesel_total_registered", "other_total_registered", "all_fuel_total_registered",
    "all_fuel_total_licensed",
]
NET_GROWTH_COLUMNS = ["date", "gross_first_registrations", "deregistrations", "net_first_registrations"]
PRIVATE_CAR_FIRST_REG_COLUMNS = ["date", "month", "make", "fuel_type", "first_reg"]
PRIVATE_CAR_FIRST_REG_MODEL_COLUMNS = [
    "observation_date", "vehicle_make", "vehicle_model", "fuel_type", "first_reg_count"
]
PARKING_VACANCY_COLUMNS = [
    "snapshot_at", "park_id", "name_en", "name_tc", "district_en", "district_tc",
    "latitude", "longitude", "vehicle_type", "service_category", "vacancy_type",
    "vacancy", "lastupdate",
]
CARPARK_OCCUPANCY_COLUMNS = [
    "snapshot_at", "district", "occupancy_rate", "sample_size", "capacity_spaces",
    "vacant_spaces", "exact_vacancy_parks", "participating_parks",
]
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
    "hk_passenger_journeys": {
        "id": "hk_passenger_journeys",
        "label": "Transport Department Monthly Traffic and Transport Digest — Table 2.1",
        "href": "https://www.td.gov.hk/en/transport_in_hong_kong/transport_figures/monthly_traffic_and_transport_digest/index.html",
        "path": "sources/hk_passenger_journeys.sql",
        "query": {
            "engine": "official Table 2.1 workbook (table21.xls), both sheets",
            "url": "https://www.td.gov.hk/filemanager/en/content_5404/table21.xls",
            "language": "XLS",
            "description": "Monthly public transport passenger journeys ('000s) by operator: KMB, Citybus, LWB, NLB (franchised buses), MTR heavy rail, Airport Express, Light Rail, Tramways, public light buses, ferries, taxis, and the territory-wide total.",
            "tables_used": [
                "table21.xls sheet 1 (operator rows)",
                "table21.xls sheet 2 (mode totals)",
            ],
            "metric_definitions": [
                "KMB is read from the header-validated KMB row on sheet 1, column 2.",
                "The territory-wide total is read from the keyword-distinguished total row on sheet 2, column 22; subtotal rows are not used as the total.",
                "The accepted workbook row must reconcile the published mode components to the reported total within 0.5 thousand journeys.",
            ],
        },
    },
    "mttd_passenger_journeys": {
        "id": "mttd_passenger_journeys",
        "label": "Transport Department Monthly Traffic and Transport Digest — Table 2.3",
        "href": "https://data.gov.hk/en-data/dataset/hk-td-tis_17-monthly-traffic-and-transport-digest-csv",
        "path": "sources/mttd_passenger_journeys.sql",
        "query": {
            "engine": "official MTTD Table 2.3 CSV",
            "url": "https://www.td.gov.hk/datagovhk_tis/mttd-csv/en/table23_eng.csv",
            "language": "CSV",
            "description": "Monthly passenger journeys ('000s) for MTRC rail lines and franchised-bus operators, with HK Island, Kowloon/New Territories and cross-harbour geography where reported. Publication lags the current month by roughly two to three months.",
        },
    },
    "censtatd_boundary_movements": {
        "id": "censtatd_boundary_movements",
        "label": "C&SD Table E705 — Cross-Boundary Aircraft, Vessel, Vehicle and Train Movements",
        "href": "https://www.censtatd.gov.hk/en/data/stat_report/subject/340/report_index.json",
        "path": "sources/censtatd_boundary_movements.sql",
        "query": {
            "engine": "official C&SD Table E705 XLSX discovered through the subject report index",
            "url": "https://www.censtatd.gov.hk/en/data/stat_report/subject/340/report_index.json ; https://www.censtatd.gov.hk/en/data/stat_report/product/D7000005/att/<latest-file>",
            "language": "XLSX",
            "description": "Monthly inward and outward movements of aircraft, ocean/river/cargo vessels, goods/passenger vehicles and passenger trains. Some latest-year cells may be provisional estimates or N.A.; monthly history begins in 2023 in the current workbook.",
        },
    },
    "hk_vehicle_stock": {
        "id": "hk_vehicle_stock",
        "label": "Transport Department Registration and Licensing of Vehicles — Table 4.1(a), Private Cars",
        "href": "https://www.td.gov.hk/en/transport_in_hong_kong/transport_figures/monthly_traffic_and_transport_digest/index.html",
        "path": "sources/hk_vehicle_stock.sql",
        "query": {
            "engine": "official Table 4.1(a) workbook (table41a.xls), Private Cars sheet",
            "url": "https://www.td.gov.hk/filemanager/en/content_4883/table41a.xls",
            "language": "XLS",
            "description": "Monthly private car fleet stock (total registered and licensed) split by fuel type -- Petrol, Electric, Diesel, Other -- the basis for the EV road-fleet registered-share chart.",
            "tables_used": [
                "table41a.xls sheet whose header identifies Private Cars / 私家车",
            ],
            "metric_definitions": [
                "The Private Cars sheet is located by matching its own header text rather than relying on a fixed sheet index.",
                "EV fleet share is electric total registered divided by all-fuel total registered.",
                "The all-fuel total is accepted only when it reconciles to the sum of the four per-fuel total-registration columns.",
            ],
        },
    },
    "hk_private_car_net_growth": {
        "id": "hk_private_car_net_growth",
        "label": "Transport Department Net First Registration of Private Cars — Table 4.1(c)",
        "href": "https://www.td.gov.hk/en/transport_in_hong_kong/transport_figures/monthly_traffic_and_transport_digest/index.html",
        "path": "sources/hk_private_car_net_growth.sql",
        "query": {
            "engine": "official Table 4.1(c) workbook (table41c.xls)",
            "url": "https://www.td.gov.hk/filemanager/en/content_4884/table41c.xls",
            "language": "XLS",
            "description": "Monthly gross first registrations, deregistrations (all reasons, per TD's own header -- not scrappage specifically) and net first registration of private cars.",
        },
    },
    "hk_private_car_first_reg": {
        "id": "hk_private_car_first_reg",
        "label": "Transport Department Monthly Private-Car First Registrations by Make and Fuel",
        "href": "https://data.gov.hk/en-data/dataset/hk-td-tis_17-monthly-traffic-and-transport-digest-csv/resource/472658ca-1640-4fc2-be5c-eae62f9bf547",
        "path": "sources/hk_private_car_first_reg.sql",
        "query": {
            "engine": "official TD Monthly Traffic and Transport Digest CSV — Table 4.1(e)",
            "url": "https://www.td.gov.hk/datagovhk_tis/mttd-csv/en/table41e_eng.csv",
            "language": "CSV",
            "description": "Monthly first registrations of private cars by make, fuel type, first-registration status and body type; a genuine time series from May 2016 onward.",
        },
    },
    "hk_private_car_first_reg_details": {
        "id": "hk_private_car_first_reg_details",
        "label": "Transport Department Latest Private-Car First-Registration Make/Model Details",
        "href": "https://www.td.gov.hk/en/public_services/licences_and_permits/vehicle_first_registration/vehicle_particulars/index.html",
        "path": "sources/hk_private_car_first_reg_details.sql",
        "query": {
            "engine": "official TD monthly particulars of first registered vehicles CSV",
            "url": "https://www.td.gov.hk/datagovhk_td/first-reg-vehicle/resources/en/particulars_of_first_registered_vehicle_{month}_{year}_eng.csv",
            "language": "CSV",
            "description": "Latest available monthly private-car make/model detail; used as a bounded lookup snapshot, while the make/fuel history above supplies the time-series chart.",
        },
    },
    "td_parking_vacancy": {
        "id": "td_parking_vacancy",
        "label": "Transport Department Real-Time Parking Vacancy",
        "href": "https://resource.data.one.gov.hk/td/carpark/TD_Parking_Vacancy_Data_Specification.pdf",
        "path": "sources/td_parking_vacancy.sql",
        "query": {
            "engine": "official TD real-time vacancy and basic-information JSON feeds",
            "url": "https://resource.data.one.gov.hk/td/carpark/vacancy_all.json ; https://resource.data.one.gov.hk/td/carpark/basic_info_all.json",
            "language": "JSON",
            "description": "Current vacancy by participating car park, vehicle type and vacancy status; the collection script appends snapshots for a genuine high-frequency history and does not treat unknown vacancy as zero.",
        },
    },
    "td_carpark_occupancy": {
        "id": "td_carpark_occupancy",
        "label": "Transport Department Car-Park Occupancy Signal",
        "href": "https://api.data.gov.hk/v1/carpark-info-vacancy",
        "path": "sources/td_carpark_occupancy.sql",
        "query": {
            "engine": "official TD live vacancy JSON joined to Digital Policy Office One-Stop static capacity JSON",
            "url": "https://resource.data.one.gov.hk/td/carpark/vacancy_all.json ; https://resource.data.one.gov.hk/td/carpark/basic_info_all.json ; https://api.data.gov.hk/v1/carpark-info-vacancy",
            "language": "JSON",
            "description": "Capacity-weighted private-car occupancy rate from exact hourly vacancy counts. The denominator is available only for a capacity-covered subset of TD car parks; sample_size and coverage are retained, and the signal is not presented as all-park occupancy.",
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


def _display_number(value: Any) -> str:
    """Format a scalar for compact summary tables."""
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return "n/a"
    if isinstance(value, (int, float)):
        formatted = f"{float(value):,.1f}"
        return formatted.rstrip("0").rstrip(".")
    return str(value)


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


def _load_transport_monthly(path: Path, columns: list[str], label: str) -> pd.DataFrame:
    """Shared loader for the three TD Table 2.1/4.1(a)/4.1(c) parquets.

    All three are already validated at scrape time (scripts/scrape_hk_*.py
    recompute TD's own published subtotals from their parts and refuse to
    write output that doesn't reconcile), so this loader's job is narrower:
    confirm the expected columns exist and the date column parses, not
    re-derive anything. `date` here is a "YYYY-MM" string (month grain, no
    day), unlike china_airline's full "YYYY-MM-DD" -- appending "-01" gives
    a canonical first-of-month date consistent with how the rest of this
    file treats `date`/`month`.
    """
    if not path.exists():
        return pd.DataFrame(columns=columns)

    frame = pd.read_parquet(path)
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing columns: {missing}")

    result = frame.loc[:, columns].copy()
    # Older materializers store month-grain dates as YYYY-MM strings; the
    # reusable source fetchers store the same month as a Timestamp.  Accept
    # both representations without making the artifact depend on one writer.
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    if result["date"].isna().any():
        raise ValueError(f"{label} contains unparseable dates")
    return result.sort_values("date").reset_index(drop=True)


def load_passenger_journeys(path: Path = PASSENGER_JOURNEYS_DATA_PATH) -> pd.DataFrame:
    return _load_transport_monthly(path, PASSENGER_JOURNEYS_COLUMNS, "HK passenger journeys")


def load_mttd_passenger_journeys(path: Path = MTTD_PASSENGER_JOURNEYS_DATA_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=MTTD_PASSENGER_JOURNEYS_COLUMNS)
    frame = pd.read_parquet(path)
    missing = sorted(set(MTTD_PASSENGER_JOURNEYS_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"MTTD Table 2.3 is missing columns: {missing}")
    result = frame.loc[:, MTTD_PASSENGER_JOURNEYS_COLUMNS].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["month"] = result["date"].dt.strftime("%Y-%m")
    if result["date"].isna().any():
        raise ValueError("MTTD Table 2.3 contains invalid dates")
    result["total_passenger_journeys_k"] = pd.to_numeric(
        result["total_passenger_journeys_k"], errors="coerce"
    )
    return result.dropna(subset=["total_passenger_journeys_k"]).sort_values(
        ["date", "bus_rail", "pto_code", "rail_line"]
    ).reset_index(drop=True)


def load_boundary_movements(path: Path = BOUNDARY_MOVEMENTS_DATA_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=BOUNDARY_MOVEMENTS_COLUMNS)
    frame = pd.read_parquet(path)
    missing = sorted(set(BOUNDARY_MOVEMENTS_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"C&SD Table E705 is missing columns: {missing}")
    result = frame.loc[:, BOUNDARY_MOVEMENTS_COLUMNS].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["month"] = result["date"].dt.strftime("%Y-%m")
    numeric_columns = [column for column in BOUNDARY_MOVEMENTS_COLUMNS if column not in {"date", "month", "is_estimate"}]
    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["is_estimate"] = result["is_estimate"].fillna(False).astype(bool)
    if result["date"].isna().any():
        raise ValueError("C&SD Table E705 contains invalid dates")
    return result.sort_values("date").reset_index(drop=True)


def load_vehicle_stock(path: Path = VEHICLE_STOCK_DATA_PATH) -> pd.DataFrame:
    return _load_transport_monthly(path, VEHICLE_STOCK_COLUMNS, "HK private car fleet stock")


def load_net_growth(path: Path = NET_GROWTH_DATA_PATH) -> pd.DataFrame:
    return _load_transport_monthly(path, NET_GROWTH_COLUMNS, "HK private car net growth")


def load_private_car_first_reg(path: Path = PRIVATE_CAR_FIRST_REG_DATA_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=PRIVATE_CAR_FIRST_REG_COLUMNS)
    frame = pd.read_parquet(path)
    missing = sorted(set(PRIVATE_CAR_FIRST_REG_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"HK private-car first-registration history is missing columns: {missing}")
    result = frame.loc[:, PRIVATE_CAR_FIRST_REG_COLUMNS].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["month"] = result["date"].dt.strftime("%Y-%m")
    result["make"] = result["make"].astype(str).str.strip().str.upper()
    result["fuel_type"] = result["fuel_type"].astype(str).str.strip().str.upper()
    result["first_reg"] = pd.to_numeric(result["first_reg"], errors="coerce")
    if result["date"].isna().any() or result["first_reg"].isna().any():
        raise ValueError("HK private-car first-registration history contains invalid dates or counts")
    return result.sort_values(["date", "make", "fuel_type"]).reset_index(drop=True)


def load_private_car_first_reg_models(path: Path = PRIVATE_CAR_FIRST_REG_MODEL_DATA_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=PRIVATE_CAR_FIRST_REG_MODEL_COLUMNS)
    frame = pd.read_parquet(path)
    missing = sorted(set(PRIVATE_CAR_FIRST_REG_MODEL_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"HK private-car make/model detail is missing columns: {missing}")
    result = frame.loc[:, PRIVATE_CAR_FIRST_REG_MODEL_COLUMNS].copy()
    result["observation_date"] = pd.to_datetime(result["observation_date"], errors="coerce")
    for column in ("vehicle_make", "vehicle_model", "fuel_type"):
        result[column] = result[column].astype(str).str.strip()
    result["first_reg_count"] = pd.to_numeric(result["first_reg_count"], errors="coerce")
    if result["observation_date"].isna().any() or result["first_reg_count"].isna().any():
        raise ValueError("HK private-car make/model detail contains invalid dates or counts")
    return result.sort_values("first_reg_count", ascending=False).reset_index(drop=True)


def load_parking_vacancy(path: Path = PARKING_VACANCY_DATA_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=PARKING_VACANCY_COLUMNS)
    frame = pd.read_parquet(path)
    missing = sorted(set(PARKING_VACANCY_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"HK parking vacancy history is missing columns: {missing}")
    result = frame.loc[:, PARKING_VACANCY_COLUMNS].copy()
    result["snapshot_at"] = pd.to_datetime(result["snapshot_at"], errors="coerce")
    result["lastupdate"] = pd.to_datetime(result["lastupdate"], errors="coerce")
    result["vacancy"] = pd.to_numeric(result["vacancy"], errors="coerce")
    result["vehicle_type"] = result["vehicle_type"].astype(str).str.strip()
    result["service_category"] = result["service_category"].astype(str).str.strip()
    result["vacancy_type"] = result["vacancy_type"].astype(str).str.strip().str.upper()
    if result["snapshot_at"].isna().any():
        raise ValueError("HK parking vacancy history contains invalid snapshot timestamps")
    return result.sort_values(["snapshot_at", "park_id", "vehicle_type"]).reset_index(drop=True)


def load_carpark_occupancy(path: Path = CARPARK_OCCUPANCY_DATA_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=CARPARK_OCCUPANCY_COLUMNS)
    frame = pd.read_parquet(path)
    missing = sorted(set(CARPARK_OCCUPANCY_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"TD car-park occupancy history is missing columns: {missing}")
    result = frame.loc[:, CARPARK_OCCUPANCY_COLUMNS].copy()
    result["snapshot_at"] = pd.to_datetime(result["snapshot_at"], errors="coerce")
    for column in ("occupancy_rate", "capacity_spaces", "vacant_spaces"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    for column in ("sample_size", "exact_vacancy_parks", "participating_parks"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if result["snapshot_at"].isna().any() or result["occupancy_rate"].isna().any():
        raise ValueError("TD car-park occupancy history contains invalid values")
    return result.sort_values(["snapshot_at", "district"]).reset_index(drop=True)


def build_passenger_journeys_views(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    empty = {
        "hk_total_transport_journeys_history": [],
        "hk_modal_split_history": [],
        "hk_franchised_bus_operator_history": [],
    }
    if frame.empty:
        return empty

    data = frame.copy()
    data["month"] = data["date"].dt.strftime("%Y-%m")

    modal_split: list[dict[str, Any]] = []
    for series_label, column in [
        ("Bus", "bus_subtotal_k"),
        ("Rail", "rail_subtotal_k"),
        ("PLB", "plb_subtotal_k"),
        ("Ferry", "ferry_subtotal_k"),
        ("Taxi", "taxis_k"),
    ]:
        modal_split.extend(_series_history(data, series_label, column))
    modal_split.sort(key=lambda row: (row["date"], row["series"]))

    bus_operators: list[dict[str, Any]] = []
    for series_label, column in [
        ("KMB", "kmb_k"),
        ("Citybus", "citybus_subtotal_k"),
        ("LWB", "lwb_k"),
        ("NLB", "nlb_k"),
    ]:
        bus_operators.extend(_series_history(data, series_label, column))
    bus_operators.sort(key=lambda row: (row["date"], row["series"]))

    return {
        "hk_total_transport_journeys_history": _series_history(data, "Total", "total_k"),
        "hk_modal_split_history": modal_split,
        "hk_franchised_bus_operator_history": bus_operators,
    }


def build_vehicle_stock_views(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    empty = {"hk_private_car_fleet_by_fuel_history": []}
    if frame.empty:
        return empty

    data = frame.copy()
    data["month"] = data["date"].dt.strftime("%Y-%m")

    by_fuel: list[dict[str, Any]] = []
    for series_label, column in [
        ("Petrol", "petrol_total_registered"),
        ("Electric", "electric_total_registered"),
        ("Diesel", "diesel_total_registered"),
        ("Other", "other_total_registered"),
    ]:
        by_fuel.extend(_series_history(data, series_label, column))
    by_fuel.sort(key=lambda row: (row["date"], row["series"]))

    return {"hk_private_car_fleet_by_fuel_history": by_fuel}


def build_vehicle_fleet_ev_share_view(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return EV share of registered private-car stock as a single series."""
    if frame.empty:
        return []
    data = frame.copy()
    data["ev_share_pct"] = (
        data["electric_total_registered"]
        / data["all_fuel_total_registered"].replace(0, pd.NA)
        * 100
    )
    data = data.dropna(subset=["ev_share_pct"]).copy()
    return [
        {
            "date": row["date"].strftime("%Y-%m-%d"),
            "month": row["date"].strftime("%Y-%m"),
            "value": round(float(row["ev_share_pct"]), 4),
        }
        for _, row in data.sort_values("date").iterrows()
    ]


def build_net_growth_views(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    empty = {"hk_private_car_net_growth_history": []}
    if frame.empty:
        return empty

    data = frame.copy()
    data["month"] = data["date"].dt.strftime("%Y-%m")
    return {"hk_private_car_net_growth_history": _series_history(data, "Net first registrations", "net_first_registrations")}


def build_private_car_first_reg_views(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    empty = {
        "kpi_private_car_first_reg": [],
        "hk_private_car_ev_make_history": [],
        "hk_private_car_ev_share_history": [],
        "hk_private_car_ev_make_latest": [],
    }
    if frame.empty:
        return empty

    data = frame.copy()
    data["is_electric"] = data["fuel_type"].str.upper().eq("ELECTRIC")
    monthly = (
        data.groupby("date", as_index=False)
        .agg(
            total_first_reg=("first_reg", "sum"),
            electric_first_reg=("first_reg", lambda values: float(values[data.loc[values.index, "is_electric"]].sum())),
        )
        .sort_values("date")
    )
    monthly["ev_share_pct"] = (
        monthly["electric_first_reg"] / monthly["total_first_reg"].replace(0, pd.NA) * 100
    ).round(4)
    monthly["month"] = monthly["date"].dt.strftime("%Y-%m")
    latest = monthly.iloc[-1]
    prior = monthly.iloc[-2] if len(monthly) > 1 else None
    kpi = {
        "total_first_reg": float(latest["total_first_reg"]),
        "electric_first_reg": float(latest["electric_first_reg"]),
        "ev_share_pct": float(latest["ev_share_pct"]) if pd.notna(latest["ev_share_pct"]) else None,
        "ev_share_change_pp": (
            float(latest["ev_share_pct"] - prior["ev_share_pct"])
            if prior is not None and pd.notna(latest["ev_share_pct"]) and pd.notna(prior["ev_share_pct"])
            else None
        ),
        "observation_date": latest["date"].strftime("%Y-%m-%d"),
    }

    ev = data[data["is_electric"]].copy()
    primary_makes = {"BYD", "TESLA"}
    make_rows: list[dict[str, Any]] = []
    for label, selected in (("BYD", ev[ev["make"].eq("BYD")]), ("Tesla", ev[ev["make"].eq("TESLA")])):
        if not selected.empty:
            grouped = selected.groupby("date", as_index=False)["first_reg"].sum().rename(columns={"first_reg": "value"})
            grouped["series"] = label
            make_rows.extend(_series_history(grouped, label, "value"))
    other = ev[~ev["make"].isin(primary_makes)]
    if not other.empty:
        grouped = other.groupby("date", as_index=False)["first_reg"].sum().rename(columns={"first_reg": "value"})
        make_rows.extend(_series_history(grouped, "Other EV makes", "value"))
    make_rows.sort(key=lambda row: (row["date"], row["series"]))

    ev_share = monthly[["date", "month", "ev_share_pct"]].rename(columns={"ev_share_pct": "value"})
    ev_share_history = [
        {
            "date": row["date"].strftime("%Y-%m-%d"),
            "month": row["month"],
            "value": round(float(row["value"]), 4),
        }
        for _, row in ev_share.dropna(subset=["value"]).iterrows()
    ]

    latest_make = (
        ev[ev["date"].eq(latest["date"])]
        .groupby("make", as_index=False)["first_reg"]
        .sum()
        .sort_values("first_reg", ascending=False)
        .head(12)
    )
    latest_make_rows = [
        {
            "summary": f"{row['make']}: {int(row['first_reg']):,} electric first registrations ({kpi['observation_date']})"
        }
        for _, row in latest_make.iterrows()
    ]
    return {
        "kpi_private_car_first_reg": [kpi],
        "hk_private_car_ev_make_history": make_rows,
        "hk_private_car_ev_share_history": ev_share_history,
        "hk_private_car_ev_make_latest": latest_make_rows,
    }


def build_private_car_model_views(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    if frame.empty:
        return {"hk_private_car_ev_model_latest": []}
    latest_date = frame["observation_date"].max()
    latest = frame[
        frame["observation_date"].eq(latest_date)
        & frame["fuel_type"].str.upper().eq("ELECTRIC")
    ].copy()
    latest = latest.sort_values("first_reg_count", ascending=False).head(20)
    return {
        "hk_private_car_ev_model_latest": [
            {
                "summary": (
                    f"{row['vehicle_make']} {row['vehicle_model']}: "
                    f"{int(row['first_reg_count']):,} first registrations ({latest_date.strftime('%Y-%m')})"
                )
            }
            for _, row in latest.iterrows()
        ]
    }


def build_parking_vacancy_views(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    empty = {
        "kpi_parking": [],
        "hk_parking_vacancy_history": [],
        "hk_parking_current_district": [],
    }
    if frame.empty:
        return empty
    data = frame[
        frame["vehicle_type"].eq("P")
        & frame["service_category"].str.upper().eq("HOURLY")
    ].copy()
    if data.empty:
        return empty
    data["exact_count"] = data["vacancy_type"].eq("A") & data["vacancy"].ge(0)
    history = (
        data.groupby("snapshot_at", as_index=False)
        .agg(
            value=("vacancy", lambda values: float(values[data.loc[values.index, "exact_count"]].sum())),
            parks_reporting_exact=("park_id", lambda values: int(values[data.loc[values.index, "exact_count"]].nunique())),
            participating_parks=("park_id", "nunique"),
        )
        .sort_values("snapshot_at")
    )
    history["date"] = history["snapshot_at"]
    history["month"] = history["snapshot_at"].dt.strftime("%Y-%m")
    history_rows = [
        {
            "date": row["date"].strftime("%Y-%m-%d %H:%M"),
            "month": row["month"],
            "value": round(float(row["value"]), 1),
            "parks_reporting_exact": int(row["parks_reporting_exact"]),
            "participating_parks": int(row["participating_parks"]),
        }
        for _, row in history.iterrows()
    ]

    latest_snapshot = data["snapshot_at"].max()
    current = data[data["snapshot_at"].eq(latest_snapshot)].copy()
    exact = current[current["exact_count"]]
    unknown = current[~current["exact_count"]]
    kpi = {
        "available_spaces": int(exact["vacancy"].sum()),
        "parks_reporting_exact": int(exact["park_id"].nunique()),
        "parks_with_unknown_count": int(unknown["park_id"].nunique()),
        "participating_parks": int(current["park_id"].nunique()),
        "snapshot_at": latest_snapshot.strftime("%Y-%m-%d %H:%M"),
        "observation_date": latest_snapshot.strftime("%Y-%m-%d"),
    }
    district = (
        exact.assign(district_en=exact["district_en"].replace("", "Unknown"))
        .groupby("district_en", as_index=False)
        .agg(available_spaces=("vacancy", "sum"), parks_reporting_exact=("park_id", "nunique"))
        .sort_values("available_spaces", ascending=False)
    )
    district_rows = [
        {
            "summary": (
                f"{row['district_en']}: {int(row['available_spaces']):,} exact vacant spaces "
                f"across {int(row['parks_reporting_exact']):,} car parks"
            )
        }
        for _, row in district.head(18).iterrows()
    ]
    return {
        "kpi_parking": [kpi],
        "hk_parking_vacancy_history": history_rows,
        "hk_parking_current_district": district_rows,
    }


def build_mttd_passenger_journey_views(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Build a compact three-series view from the MTTD Table 2.3 grain."""
    empty = {
        "mttd_passenger_journeys_history": [],
        "mttd_passenger_journeys_latest": [],
    }
    if frame.empty:
        return empty
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["total_passenger_journeys_k"] = pd.to_numeric(
        data["total_passenger_journeys_k"], errors="coerce"
    )
    series_frames = [
        (
            "MTR Local",
            data[data["bus_rail"].eq("MTRC") & data["rail_line"].eq("Local")],
        ),
        (
            "MTR Airport / LRT / feeder",
            data[data["bus_rail"].eq("MTRC") & ~data["rail_line"].eq("Local")],
        ),
        ("Franchised buses", data[data["bus_rail"].eq("Fran_Bus")]),
    ]
    history: list[dict[str, Any]] = []
    for label, selected in series_frames:
        if selected.empty:
            continue
        grouped = selected.groupby("date", as_index=False)["total_passenger_journeys_k"].sum()
        grouped = grouped.rename(columns={"total_passenger_journeys_k": "value"})
        history.extend(_series_history(grouped, label, "value"))
    history.sort(key=lambda row: (row["date"], row["series"]))
    latest = data["date"].max()
    latest_rows = [
        {
            "summary": f"{label}: {float(selected.loc[selected['date'].eq(latest), 'total_passenger_journeys_k'].sum()):,.1f} thousand journeys ({latest.strftime('%Y-%m')})"
        }
        for label, selected in series_frames
        if not selected.empty and not selected.loc[selected["date"].eq(latest)].empty
    ]
    return {
        "mttd_passenger_journeys_history": history,
        "mttd_passenger_journeys_latest": latest_rows,
    }


def build_boundary_movement_views(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Build three capped series plus a latest-row summary from C&SD E705."""
    empty = {
        "censtatd_boundary_movements_history": [],
        "censtatd_boundary_movements_latest": [],
    }
    if frame.empty:
        return empty
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    series_frames = [
        ("Aircraft", "aircraft_total"),
        ("Passenger vehicles", "passenger_vehicles_total"),
        ("Goods vehicles", "goods_vehicles_total"),
    ]
    history: list[dict[str, Any]] = []
    for label, column in series_frames:
        if column not in data.columns:
            continue
        selected = data[["date", column, "is_estimate"]].rename(columns={column: "value"})
        selected = selected.dropna(subset=["value"])
        if selected.empty:
            continue
        rows = _series_history(selected, label, "value")
        estimate_by_date = {
            row["date"]: bool(estimate)
            for row, estimate in zip(
                rows,
                selected.sort_values("date")["is_estimate"].tolist(),
            )
        }
        for row in rows:
            row["is_estimate"] = estimate_by_date.get(row["date"], False)
        history.extend(rows)
    history.sort(key=lambda row: (row["date"], row["series"]))
    latest = data["date"].max()
    latest_rows = []
    for label, column in series_frames:
        if column not in data.columns:
            continue
        row = data.loc[data["date"].eq(latest)].iloc[-1]
        value = row.get(column)
        if pd.isna(value):
            continue
        estimate = "; provisional estimate" if bool(row.get("is_estimate", False)) else ""
        latest_rows.append({"summary": f"{label}: {float(value):,.1f} movements ({latest.strftime('%Y-%m')}){estimate}"})
    return {
        "censtatd_boundary_movements_history": history,
        "censtatd_boundary_movements_latest": latest_rows,
    }


def build_carpark_occupancy_views(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    empty = {
        "kpi_carpark_occupancy": [],
        "td_carpark_occupancy_history": [],
        "td_carpark_occupancy_latest_district": [],
    }
    if frame.empty:
        return empty
    data = frame.copy()
    data["snapshot_at"] = pd.to_datetime(data["snapshot_at"], errors="coerce")
    data["occupancy_rate"] = pd.to_numeric(data["occupancy_rate"], errors="coerce")
    data = data.dropna(subset=["snapshot_at", "occupancy_rate"])
    all_hk = data[data["district"].eq("All Hong Kong")].sort_values("snapshot_at")
    if all_hk.empty:
        return empty
    history_rows = []
    for _, row in all_hk.iterrows():
        history_rows.append(
            {
                "date": row["snapshot_at"].strftime("%Y-%m-%d %H:%M"),
                "month": row["snapshot_at"].strftime("%Y-%m"),
                "value": round(float(row["occupancy_rate"]) * 100, 4),
                "sample_size": int(row["sample_size"]),
                "capacity_spaces": float(row["capacity_spaces"]),
                "vacant_spaces": float(row["vacant_spaces"]),
            }
        )
    latest_snapshot = all_hk.iloc[-1]
    latest_timestamp = latest_snapshot["snapshot_at"]
    latest_district = data[
        data["snapshot_at"].eq(latest_timestamp) & ~data["district"].eq("All Hong Kong")
    ].sort_values("occupancy_rate", ascending=False)
    district_rows = [
        {
            "summary": (
                f"{row['district']}: {float(row['occupancy_rate']) * 100:.1f}% occupied "
                f"({int(row['sample_size'])} capacity-covered parks)"
            )
        }
        for _, row in latest_district.head(18).iterrows()
    ]
    kpi = {
        "occupancy_pct": round(float(latest_snapshot["occupancy_rate"]) * 100, 4),
        "capacity_spaces": float(latest_snapshot["capacity_spaces"]),
        "vacant_spaces": float(latest_snapshot["vacant_spaces"]),
        "sample_size": int(latest_snapshot["sample_size"]),
        "observation_date": latest_timestamp.strftime("%Y-%m-%d %H:%M"),
    }
    return {
        "kpi_carpark_occupancy": [kpi],
        "td_carpark_occupancy_history": history_rows,
        "td_carpark_occupancy_latest_district": district_rows,
    }


def build_artifact(
    raw_mtr: pd.DataFrame | None = None,
    raw_cathay: pd.DataFrame | None = None,
    raw_china_airline: pd.DataFrame | None = None,
    raw_passenger_journeys: pd.DataFrame | None = None,
    raw_mttd_passenger_journeys: pd.DataFrame | None = None,
    raw_boundary_movements: pd.DataFrame | None = None,
    raw_vehicle_stock: pd.DataFrame | None = None,
    raw_net_growth: pd.DataFrame | None = None,
    raw_private_car_first_reg: pd.DataFrame | None = None,
    raw_private_car_first_reg_models: pd.DataFrame | None = None,
    raw_parking_vacancy: pd.DataFrame | None = None,
    raw_carpark_occupancy: pd.DataFrame | None = None,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()

    mtr = raw_mtr if raw_mtr is not None else fetch_mtr_patronage()
    cathay = raw_cathay if raw_cathay is not None else fetch_cathay_traffic()
    china_airline = raw_china_airline if raw_china_airline is not None else load_china_airline_traffic()
    china_airline_views = build_china_airline_views(china_airline)
    china_airline_snapshot_summary = [
        {
            "summary": (
                f"{row.get('airline', row.get('airline_code', 'n/a'))} / {row.get('region', 'n/a')}: "
                f"passengers {_display_number(row.get('passengers'))}; "
                f"ASK {_display_number(row.get('ask'))}; RPK {_display_number(row.get('rpk'))}; "
                f"load factor {_display_number(row.get('load_factor_pct'))}%"
            )
        }
        for row in china_airline_views["china_airline_latest_snapshot"]
    ]
    passenger_journeys = raw_passenger_journeys if raw_passenger_journeys is not None else load_passenger_journeys()
    passenger_journeys_views = build_passenger_journeys_views(passenger_journeys)
    mttd_passenger_journeys = (
        raw_mttd_passenger_journeys
        if raw_mttd_passenger_journeys is not None
        else load_mttd_passenger_journeys()
    )
    mttd_passenger_journeys_views = build_mttd_passenger_journey_views(mttd_passenger_journeys)
    boundary_movements = (
        raw_boundary_movements
        if raw_boundary_movements is not None
        else load_boundary_movements()
    )
    boundary_movement_views = build_boundary_movement_views(boundary_movements)
    vehicle_stock = raw_vehicle_stock if raw_vehicle_stock is not None else load_vehicle_stock()
    vehicle_stock_views = build_vehicle_stock_views(vehicle_stock)
    vehicle_fleet_ev_share_history = build_vehicle_fleet_ev_share_view(vehicle_stock)
    net_growth = raw_net_growth if raw_net_growth is not None else load_net_growth()
    net_growth_views = build_net_growth_views(net_growth)
    private_car_first_reg = (
        raw_private_car_first_reg
        if raw_private_car_first_reg is not None
        else load_private_car_first_reg()
    )
    private_car_first_reg_views = build_private_car_first_reg_views(private_car_first_reg)
    private_car_first_reg_models = (
        raw_private_car_first_reg_models
        if raw_private_car_first_reg_models is not None
        else load_private_car_first_reg_models()
    )
    private_car_model_views = build_private_car_model_views(private_car_first_reg_models)
    parking_vacancy = raw_parking_vacancy if raw_parking_vacancy is not None else load_parking_vacancy()
    parking_views = build_parking_vacancy_views(parking_vacancy)
    carpark_occupancy = (
        raw_carpark_occupancy
        if raw_carpark_occupancy is not None
        else load_carpark_occupancy()
    )
    carpark_occupancy_views = build_carpark_occupancy_views(carpark_occupancy)

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

    # KMB is a Transport International (00062.HK) subsidiary; MTR ridership
    # already has its own authoritative KPI above from MTR's own investor
    # disclosures (mtr_patronage), so this card focuses on what TD's Table 2.1
    # adds that isn't covered elsewhere: KMB specifically, and the
    # territory-wide total across every public transport mode.
    journeys_kpi = None
    if not passenger_journeys.empty:
        j_latest = passenger_journeys.iloc[-1]
        j_prior = passenger_journeys.iloc[-2] if len(passenger_journeys) > 1 else None
        journeys_kpi = {
            "kmb_k": float(j_latest["kmb_k"]),
            "total_k": float(j_latest["total_k"]),
            "period_change": (
                round(float(j_latest["total_k"]) / float(j_prior["total_k"]) - 1, 6)
                if j_prior is not None and float(j_prior["total_k"]) > 0
                else 0.0
            ),
            "observation_date": j_latest["date"].strftime("%Y-%m-%d"),
        }

    # EV share is of the REGISTERED fleet (cumulative stock), not the
    # licensed/on-road fleet -- a car can be registered but not currently
    # licensed (e.g. laid up), so registered is the more stable denominator
    # for an adoption-curve reading.
    fleet_kpi = None
    if not vehicle_stock.empty:
        v_latest = vehicle_stock.iloc[-1]
        v_prior = vehicle_stock.iloc[-2] if len(vehicle_stock) > 1 else None
        ev_share = (
            float(v_latest["electric_total_registered"]) / float(v_latest["all_fuel_total_registered"])
            if float(v_latest["all_fuel_total_registered"]) > 0
            else None
        )
        ev_share_prior = (
            float(v_prior["electric_total_registered"]) / float(v_prior["all_fuel_total_registered"])
            if v_prior is not None and float(v_prior["all_fuel_total_registered"]) > 0
            else None
        )
        fleet_kpi = {
            "total_registered": float(v_latest["all_fuel_total_registered"]),
            "ev_share_pct": round(ev_share * 100, 4) if ev_share is not None else None,
            # A percentage-point change, not a period_change ratio, since
            # ev_share is already a ratio -- ratio-of-ratios would be
            # harder to read as "EV adoption is accelerating/slowing".
            "ev_share_change_pp": (
                round((ev_share - ev_share_prior) * 100, 4)
                if ev_share is not None and ev_share_prior is not None
                else None
            ),
            "observation_date": v_latest["date"].strftime("%Y-%m-%d"),
        }

    net_growth_kpi = None
    if not net_growth.empty:
        n_latest = net_growth.iloc[-1]
        net_growth_kpi = {
            "gross_first_registrations": float(n_latest["gross_first_registrations"]),
            "deregistrations": float(n_latest["deregistrations"]),
            "net_first_registrations": float(n_latest["net_first_registrations"]),
            "observation_date": n_latest["date"].strftime("%Y-%m-%d"),
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
        "china_airline_latest_snapshot_summary": china_airline_snapshot_summary,
        **({"kpi_journeys": [journeys_kpi]} if journeys_kpi else {}),
        **({"kpi_fleet": [fleet_kpi]} if fleet_kpi else {}),
        **({"kpi_net_growth": [net_growth_kpi]} if net_growth_kpi else {}),
        **passenger_journeys_views,
        **mttd_passenger_journeys_views,
        **boundary_movement_views,
        **vehicle_stock_views,
        "hk_private_car_fleet_ev_share_history": vehicle_fleet_ev_share_history,
        **net_growth_views,
        **private_car_first_reg_views,
        **private_car_model_views,
        **parking_views,
        **carpark_occupancy_views,
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

    if journeys_kpi:
        cards.append(
            {
                "id": "journeys_card",
                "description": "Monthly KMB (Transport International, 00062.HK) passenger journeys, and the territory-wide public transport total across every mode.",
                "dataset": "kpi_journeys",
                "sourceId": "hk_passenger_journeys",
                "metrics": [
                    {"label": "KMB ('000s)", "field": "kmb_k", "format": "number"},
                    {"label": "All-Mode Total ('000s)", "field": "total_k", "format": "number"},
                    {"label": "MoM Change (Total)", "field": "period_change", "format": "percent"},
                ],
            }
        )
    if fleet_kpi:
        cards.append(
            {
                "id": "fleet_card",
                "description": "Private car fleet stock and electric vehicle share of the registered fleet.",
                "dataset": "kpi_fleet",
                "sourceId": "hk_vehicle_stock",
                "metrics": [
                    {"label": "Registered Private Cars", "field": "total_registered", "format": "number"},
                    {"label": "EV Share of Fleet", "field": "ev_share_pct", "format": "number"},
                    {"label": "EV Share Change (pp)", "field": "ev_share_change_pp", "format": "number"},
                ],
            }
        )
    if net_growth_kpi:
        cards.append(
            {
                "id": "net_growth_card",
                "description": "Monthly private-car net first registration: gross first registrations less cumulative deregistrations reported by TD.",
                "dataset": "kpi_net_growth",
                "sourceId": "hk_private_car_net_growth",
                "metrics": [
                    {"label": "Gross First Registrations", "field": "gross_first_registrations", "format": "number"},
                    {"label": "Deregistrations", "field": "deregistrations", "format": "number"},
                    {"label": "Net First Registration", "field": "net_first_registrations", "format": "number"},
                ],
            }
        )
    if private_car_first_reg_views["kpi_private_car_first_reg"]:
        cards.append(
            {
                "id": "private_car_first_reg_card",
                "description": "Monthly private-car first registrations by make and fuel type; the electric share is a flow share, not the cumulative fleet share.",
                "dataset": "kpi_private_car_first_reg",
                "sourceId": "hk_private_car_first_reg",
                "metrics": [
                    {"label": "Private-Car First Registrations", "field": "total_first_reg", "format": "number"},
                    {"label": "Electric First Registrations", "field": "electric_first_reg", "format": "number"},
                    {"label": "EV Share of Monthly Registrations", "field": "ev_share_pct", "format": "number"},
                ],
            }
        )
    if parking_views["kpi_parking"]:
        cards.append(
            {
                "id": "parking_card",
                "description": "Current Transport Department parking-vacancy snapshot; exact counts exclude operators that report only availability/no-data status.",
                "dataset": "kpi_parking",
                "sourceId": "td_parking_vacancy",
                "metrics": [
                    {"label": "Exact Vacant Spaces", "field": "available_spaces", "format": "number"},
                    {"label": "Parks with Exact Counts", "field": "parks_reporting_exact", "format": "number"},
                    {"label": "Parks in Feed", "field": "participating_parks", "format": "number"},
                ],
            }
        )
    if carpark_occupancy_views["kpi_carpark_occupancy"]:
        cards.append(
            {
                "id": "carpark_occupancy_card",
                "description": "Capacity-weighted occupancy for the exact-vacancy, capacity-covered subset of TD private-car hourly car parks; not an all-park estimate.",
                "dataset": "kpi_carpark_occupancy",
                "sourceId": "td_carpark_occupancy",
                "metrics": [
                    {"label": "Occupancy", "field": "occupancy_pct", "format": "number"},
                    {"label": "Capacity-Covered Parks", "field": "sample_size", "format": "number"},
                    {"label": "Capacity Spaces", "field": "capacity_spaces", "format": "number"},
                ],
            }
        )

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

    if passenger_journeys_views["hk_total_transport_journeys_history"]:
        charts.extend(
            [
                {
                    "id": "hk_total_transport_journeys_chart",
                    "title": "Hong Kong Public Transport Journeys — All Modes ('000s)",
                    "subtitle": "Territory-wide monthly passenger journeys across franchised buses, MTR (heavy rail, Airport Express, Light Rail), Tramways, public light buses, ferries and taxis.",
                    "type": "line",
                    "dataset": "hk_total_transport_journeys_history",
                    "sourceId": "hk_passenger_journeys",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "Thousands ('000s)"},
                    },
                    "valueFormat": "number",
                    "layout": "full",
                },
                {
                    "id": "hk_modal_split_chart",
                    "title": "Hong Kong Public Transport Journeys by Mode ('000s)",
                    "subtitle": "Franchised buses, rail (MTR heavy rail + Airport Express + Light Rail + Tramways combined), public light buses, ferries and taxis.",
                    "type": "line",
                    "dataset": "hk_modal_split_history",
                    "sourceId": "hk_passenger_journeys",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "Thousands ('000s)"},
                        "color": {"field": "series", "type": "nominal", "label": "Mode"},
                    },
                    "valueFormat": "number",
                    "layout": "full",
                },
                {
                    "id": "hk_franchised_bus_operator_chart",
                    "title": "Hong Kong Franchised Bus Journeys by Operator ('000s)",
                    "subtitle": "KMB (Transport International, 00062.HK), Citybus, LWB and NLB. NWFB is not shown separately after it folded into Citybus's own reporting.",
                    "type": "line",
                    "dataset": "hk_franchised_bus_operator_history",
                    "sourceId": "hk_passenger_journeys",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "Thousands ('000s)"},
                        "color": {"field": "series", "type": "nominal", "label": "Operator"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
            ]
        )

    if vehicle_fleet_ev_share_history:
        charts.append(
            {
                "id": "hk_private_car_fleet_ev_share_chart",
                "title": "EV Share of Hong Kong Private-Car Fleet",
                "subtitle": "Electric vehicles as a share of the cumulative registered private-car fleet. This is a stock/adoption measure, distinct from the monthly first-registration flow share below.",
                "type": "line",
                "dataset": "hk_private_car_fleet_ev_share_history",
                "sourceId": "hk_vehicle_stock",
                "encodings": {
                    "x": {"field": "month", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "EV Share (%)"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    if net_growth_views["hk_private_car_net_growth_history"]:
        charts.append(
            {
                "id": "hk_private_car_net_growth_chart",
                "title": "Hong Kong Private Car Net Fleet Growth ('000s)",
                "subtitle": "Monthly net first registrations (gross first registrations minus deregistrations for any reason) -- the fleet's net monthly addition.",
                "type": "bar",
                "dataset": "hk_private_car_net_growth_history",
                "sourceId": "hk_private_car_net_growth",
                "encodings": {
                    "x": {"field": "month", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "Net New Registrations"},
                },
                "valueFormat": "number",
                "layout": "half",
            }
        )

    if private_car_first_reg_views["hk_private_car_ev_make_history"]:
        charts.extend(
            [
                {
                    "id": "hk_private_car_ev_make_chart",
                    "title": "Hong Kong Private-Car EV First Registrations by Make",
                    "subtitle": "Monthly electric private-car first registrations: BYD, Tesla and all other electric makes combined. This is a registration-flow signal, not cumulative fleet stock.",
                    "type": "line",
                    "intent": "trend",
                    "dataset": "hk_private_car_ev_make_history",
                    "sourceId": "hk_private_car_first_reg",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "First Registrations"},
                        "color": {"field": "series", "type": "nominal", "label": "Make"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
                {
                    "id": "hk_private_car_ev_share_chart",
                    "title": "EV Share of Monthly Private-Car First Registrations",
                    "subtitle": "Electric first registrations divided by all private-car first registrations in each month; separate from the cumulative registered-fleet EV share above.",
                    "type": "line",
                    "intent": "trend",
                    "dataset": "hk_private_car_ev_share_history",
                    "sourceId": "hk_private_car_first_reg",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "EV Share (%)"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
            ]
        )

    parking_snapshot_dates = {
        row["date"]
        for row in parking_views["hk_parking_vacancy_history"]
        if row.get("date")
    }
    if len(parking_snapshot_dates) >= 2:
        charts.append(
            {
                "id": "hk_parking_vacancy_history_chart",
                "title": "Real-Time Parking Vacancy — Exact Vacant Spaces",
                "subtitle": "Aggregated across participating private-car hourly parking feeds. The history appears only after repeated collection runs; vacancy types without an exact count are excluded from the total.",
                "type": "line",
                "intent": "trend",
                "dataset": "hk_parking_vacancy_history",
                "sourceId": "td_parking_vacancy",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Timestamp"},
                    "y": {"field": "value", "type": "quantitative", "label": "Exact Vacant Spaces"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 2000,
            }
        )

    if mttd_passenger_journeys_views["mttd_passenger_journeys_history"]:
        charts.append(
            {
                "id": "mttd_passenger_journeys_chart",
                "title": "MTTD Table 2.3 Passenger Journeys ('000s)",
                "subtitle": "Monthly MTR Local, MTR Airport/LRT/feeder and franchised-bus journeys from the TD digest. Table 2.3 is a separate geographic/operator cross-check to the broader Table 2.1 modal totals above.",
                "type": "line",
                "dataset": "mttd_passenger_journeys_history",
                "sourceId": "mttd_passenger_journeys",
                "encodings": {
                    "x": {"field": "month", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "Thousands ('000s)"},
                    "color": {"field": "series", "type": "nominal", "label": "Source grouping"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    if boundary_movement_views["censtatd_boundary_movements_history"]:
        charts.append(
            {
                "id": "censtatd_boundary_movements_chart",
                "title": "Hong Kong Cross-Boundary Movements — E705",
                "subtitle": "Monthly aircraft, passenger-vehicle and goods-vehicle movements. The latest C&SD cells may be provisional estimates; the full E705 dataset also retains vessels and passenger trains.",
                "type": "line",
                "dataset": "censtatd_boundary_movements_history",
                "sourceId": "censtatd_boundary_movements",
                "encodings": {
                    "x": {"field": "month", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "Movements"},
                    "color": {"field": "series", "type": "nominal", "label": "Movement type"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 500,
            }
        )

    occupancy_snapshot_dates = {
        row["date"]
        for row in carpark_occupancy_views["td_carpark_occupancy_history"]
        if row.get("date")
    }
    if len(occupancy_snapshot_dates) >= 2:
        charts.append(
            {
                "id": "td_carpark_occupancy_chart",
                "title": "TD Capacity-Covered Car-Park Occupancy",
                "subtitle": "Weighted occupancy rate across private-car hourly parks with both exact vacancy and published capacity. The chart remains hidden until repeated polls create a genuine time series; it is not an all-park estimate.",
                "type": "line",
                "intent": "trend",
                "dataset": "td_carpark_occupancy_history",
                "sourceId": "td_carpark_occupancy",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Timestamp"},
                    "y": {"field": "value", "type": "quantitative", "label": "Occupancy (%)"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 2000,
            }
        )

    tables: list[dict[str, Any]] = []
    if china_airline_views["china_airline_latest_snapshot"]:
        tables.append(
            {
                "id": "china_airline_latest_snapshot_table",
                "title": "China Listed Airlines Latest Operating Snapshot",
                "subtitle": "Latest available month, split by carrier and operating region.",
                "dataset": "china_airline_latest_snapshot_summary",
                "sourceId": "china_airline_traffic",
                "density": "dense",
                "layout": "full",
                "columns": [{"field": "summary", "label": "Airline Operating Summary", "type": "text"}],
            }
        )
    if private_car_model_views["hk_private_car_ev_model_latest"]:
        tables.append(
            {
                "id": "hk_private_car_ev_model_table",
                "title": "Latest Electric Private-Car Make/Model Snapshot",
                "subtitle": "Top electric private-car make/model combinations in the latest available monthly detail file. The monthly time-series charts use the separate TD Table 4.1(e) history.",
                "dataset": "hk_private_car_ev_model_latest",
                "sourceId": "hk_private_car_first_reg_details",
                "density": "dense",
                "layout": "full",
                "columns": [{"field": "summary", "label": "Make / Model Summary", "type": "text"}],
            }
        )
    if parking_views["hk_parking_current_district"]:
        tables.append(
            {
                "id": "hk_parking_current_district_table",
                "title": "Current Exact Parking Vacancy by District",
                "subtitle": "Current private-car hourly vacancy aggregated by district. Vacancy types B/C and negative values are not counted as exact vacant spaces.",
                "dataset": "hk_parking_current_district",
                "sourceId": "td_parking_vacancy",
                "density": "dense",
                "layout": "full",
                "columns": [{"field": "summary", "label": "District Summary", "type": "text"}],
            }
        )
    if mttd_passenger_journeys_views["mttd_passenger_journeys_latest"]:
        tables.append(
            {
                "id": "mttd_passenger_journeys_latest_table",
                "title": "MTTD Table 2.3 Latest Passenger-Journey Summary",
                "subtitle": "Latest available month by the compact grouping used in the chart; the underlying snapshot retains the source geography and operator dimensions.",
                "dataset": "mttd_passenger_journeys_latest",
                "sourceId": "mttd_passenger_journeys",
                "density": "dense",
                "layout": "full",
                "columns": [{"field": "summary", "label": "Journey Summary", "type": "text"}],
            }
        )
    if boundary_movement_views["censtatd_boundary_movements_latest"]:
        tables.append(
            {
                "id": "censtatd_boundary_movements_latest_table",
                "title": "C&SD E705 Latest Movement Summary",
                "subtitle": "Latest monthly aircraft, vehicle and other headline movement totals; provisional cells are marked in the source-derived summary.",
                "dataset": "censtatd_boundary_movements_latest",
                "sourceId": "censtatd_boundary_movements",
                "density": "dense",
                "layout": "full",
                "columns": [{"field": "summary", "label": "Movement Summary", "type": "text"}],
            }
        )
    if carpark_occupancy_views["td_carpark_occupancy_latest_district"]:
        tables.append(
            {
                "id": "td_carpark_occupancy_latest_district_table",
                "title": "Capacity-Covered Car-Park Occupancy by District",
                "subtitle": "Latest weighted occupancy by district for the capacity-covered subset only.",
                "dataset": "td_carpark_occupancy_latest_district",
                "sourceId": "td_carpark_occupancy",
                "density": "dense",
                "layout": "full",
                "columns": [{"field": "summary", "label": "District Occupancy", "type": "text"}],
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
            "description": "MTR Corporation monthly rail patronage, CAD HKIA airport traffic, Cathay Pacific Group operating statistics, China listed-airline operating data, TD public-transport and private-car series, C&SD cross-boundary movements, EV registrations and capacity-covered real-time car-park occupancy.",
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
                *(
                    [
                        {"id": "hk_total_transport_journeys_chart_block", "type": "chart", "chartId": "hk_total_transport_journeys_chart"},
                        {"id": "hk_modal_split_chart_block", "type": "chart", "chartId": "hk_modal_split_chart"},
                        {"id": "hk_franchised_bus_operator_chart_block", "type": "chart", "chartId": "hk_franchised_bus_operator_chart", "layout": "half"},
                    ]
                    if passenger_journeys_views["hk_total_transport_journeys_history"]
                    else []
                ),
                *(
                    [{"id": "hk_private_car_fleet_ev_share_chart_block", "type": "chart", "chartId": "hk_private_car_fleet_ev_share_chart"}]
                    if vehicle_fleet_ev_share_history
                    else []
                ),
                *(
                    [{"id": "hk_private_car_net_growth_chart_block", "type": "chart", "chartId": "hk_private_car_net_growth_chart", "layout": "half"}]
                    if net_growth_views["hk_private_car_net_growth_history"]
                    else []
                ),
                *(
                    [
                        {"id": "hk_private_car_ev_make_chart_block", "type": "chart", "chartId": "hk_private_car_ev_make_chart", "layout": "half"},
                        {"id": "hk_private_car_ev_share_chart_block", "type": "chart", "chartId": "hk_private_car_ev_share_chart", "layout": "half"},
                    ]
                    if private_car_first_reg_views["hk_private_car_ev_make_history"]
                    else []
                ),
                *(
                    [{"id": "hk_parking_vacancy_history_chart_block", "type": "chart", "chartId": "hk_parking_vacancy_history_chart"}]
                    if len(parking_snapshot_dates) >= 2
                    else []
                ),
                *(
                    [{"id": "mttd_passenger_journeys_chart_block", "type": "chart", "chartId": "mttd_passenger_journeys_chart"}]
                    if mttd_passenger_journeys_views["mttd_passenger_journeys_history"]
                    else []
                ),
                *(
                    [{"id": "censtatd_boundary_movements_chart_block", "type": "chart", "chartId": "censtatd_boundary_movements_chart"}]
                    if boundary_movement_views["censtatd_boundary_movements_history"]
                    else []
                ),
                *(
                    [{"id": "td_carpark_occupancy_chart_block", "type": "chart", "chartId": "td_carpark_occupancy_chart"}]
                    if len(occupancy_snapshot_dates) >= 2
                    else []
                ),
                *(
                    [{"id": "hk_private_car_ev_model_table_block", "type": "table", "tableId": "hk_private_car_ev_model_table"}]
                    if private_car_model_views["hk_private_car_ev_model_latest"]
                    else []
                ),
                *(
                    [{"id": "hk_parking_current_district_table_block", "type": "table", "tableId": "hk_parking_current_district_table"}]
                    if parking_views["hk_parking_current_district"]
                    else []
                ),
                *(
                    [{"id": "mttd_passenger_journeys_latest_table_block", "type": "table", "tableId": "mttd_passenger_journeys_latest_table"}]
                    if mttd_passenger_journeys_views["mttd_passenger_journeys_latest"]
                    else []
                ),
                *(
                    [{"id": "censtatd_boundary_movements_latest_table_block", "type": "table", "tableId": "censtatd_boundary_movements_latest_table"}]
                    if boundary_movement_views["censtatd_boundary_movements_latest"]
                    else []
                ),
                *(
                    [{"id": "td_carpark_occupancy_latest_district_table_block", "type": "table", "tableId": "td_carpark_occupancy_latest_district_table"}]
                    if carpark_occupancy_views["td_carpark_occupancy_latest_district"]
                    else []
                ),
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
                passenger_journeys["date"].max().strftime("%Y-%m-%d") if not passenger_journeys.empty else "1900-01-01",
                mttd_passenger_journeys["date"].max().strftime("%Y-%m-%d") if not mttd_passenger_journeys.empty else "1900-01-01",
                boundary_movements["date"].max().strftime("%Y-%m-%d") if not boundary_movements.empty else "1900-01-01",
                vehicle_stock["date"].max().strftime("%Y-%m-%d") if not vehicle_stock.empty else "1900-01-01",
                net_growth["date"].max().strftime("%Y-%m-%d") if not net_growth.empty else "1900-01-01",
                private_car_first_reg["date"].max().strftime("%Y-%m-%d") if not private_car_first_reg.empty else "1900-01-01",
                private_car_first_reg_models["observation_date"].max().strftime("%Y-%m-%d") if not private_car_first_reg_models.empty else "1900-01-01",
                carpark_occupancy["snapshot_at"].max().strftime("%Y-%m-%d") if not carpark_occupancy.empty else "1900-01-01",
            ),
        },
    }

    record_counts = {
        "mtr_patronage": len(mtr),
        "cathay_hkia_traffic": len(cathay),
        "china_airline_traffic": len(china_airline),
        "hk_passenger_journeys": len(passenger_journeys),
        "mttd_passenger_journeys": len(mttd_passenger_journeys),
        "censtatd_boundary_movements": len(boundary_movements),
        "hk_vehicle_stock": len(vehicle_stock),
        "hk_private_car_net_growth": len(net_growth),
        "hk_private_car_first_reg": len(private_car_first_reg),
        "hk_private_car_first_reg_details": len(private_car_first_reg_models),
        "td_parking_vacancy": len(parking_vacancy),
        "td_carpark_occupancy": len(carpark_occupancy),
    }
    latest_observations = {
        "mtr_patronage": mtr_kpi["observation_date"],
        "cathay_hkia_traffic": cathay_kpi["observation_date"],
        "china_airline_traffic": china_airline["date"].max().strftime("%Y-%m-%d") if not china_airline.empty else "—",
        "hk_passenger_journeys": passenger_journeys["date"].max().strftime("%Y-%m-%d") if not passenger_journeys.empty else "—",
        "mttd_passenger_journeys": mttd_passenger_journeys["date"].max().strftime("%Y-%m-%d") if not mttd_passenger_journeys.empty else "—",
        "censtatd_boundary_movements": boundary_movements["date"].max().strftime("%Y-%m-%d") if not boundary_movements.empty else "—",
        "hk_vehicle_stock": vehicle_stock["date"].max().strftime("%Y-%m-%d") if not vehicle_stock.empty else "—",
        "hk_private_car_net_growth": net_growth["date"].max().strftime("%Y-%m-%d") if not net_growth.empty else "—",
        "hk_private_car_first_reg": private_car_first_reg["date"].max().strftime("%Y-%m-%d") if not private_car_first_reg.empty else "—",
        "hk_private_car_first_reg_details": private_car_first_reg_models["observation_date"].max().strftime("%Y-%m-%d") if not private_car_first_reg_models.empty else "—",
        "td_parking_vacancy": parking_views["kpi_parking"][0]["snapshot_at"] if parking_views["kpi_parking"] else "—",
        "td_carpark_occupancy": carpark_occupancy["snapshot_at"].max().strftime("%Y-%m-%d %H:%M") if not carpark_occupancy.empty else "—",
    }
    freshness = {
        source_id: "Live" for source_id in PUBLIC_SOURCES
    }
    if latest_observations["hk_private_car_first_reg"] != "—":
        age_days = max(0, (now.replace(tzinfo=None).date() - pd.Timestamp(latest_observations["hk_private_car_first_reg"]).date()).days)
        freshness["hk_private_car_first_reg"] = f"{age_days}d old"
    if latest_observations["hk_private_car_first_reg_details"] != "—":
        age_days = max(0, (now.replace(tzinfo=None).date() - pd.Timestamp(latest_observations["hk_private_car_first_reg_details"]).date()).days)
        freshness["hk_private_car_first_reg_details"] = f"{age_days}d old"
    freshness["td_parking_vacancy"] = "Live snapshot at build time" if record_counts["td_parking_vacancy"] else "Endpoint returns no data"
    freshness["td_carpark_occupancy"] = "Live snapshot at build time" if record_counts["td_carpark_occupancy"] else "Capacity-covered subset unavailable"
    source_status = {
        source_id: "Healthy" if record_counts[source_id] > 0 else "Degraded"
        for source_id in PUBLIC_SOURCES
    }
    type_by_source = {
        "hk_private_car_first_reg_details": "Snapshot",
        "td_parking_vacancy": "Snapshot",
        "td_carpark_occupancy": "Snapshot",
    }

    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": artifact["package_info"]["dataAsOf"],
        "overall_status": "Healthy" if all(value == "Healthy" for value in source_status.values()) else "Degraded",
        "live_sources": sum(value == "Healthy" for value in source_status.values()),
        "planned_sources": 0,
        "sources": [
            {
                "source": s["label"],
                "dataset": s["id"],
                "type": type_by_source.get(s["id"], "Measure"),
                "status": source_status[s["id"]],
                "latest_observation": latest_observations[s["id"]],
                "records": record_counts[s["id"]],
                "freshness": freshness[s["id"]],
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
