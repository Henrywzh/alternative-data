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
from src.hk_transport.sources.cathay_fleet import fetch_cathay_fleet_history
from src.hk_transport.sources.mtr_patronage import fetch_mtr_patronage
from history_policy import DEFAULT_HISTORY_YEARS, history_window


CHINA_AIRLINE_DATA_PATH = ROOT / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
CHINA_AIRLINE_SOURCE_RECOVERED_DATA_PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_operating_kpi_source_recovered.parquet"
CHINA_AIRLINE_EVENT_DATA_PATH = ROOT / "data" / "processed" / "airline_traffic" / "china_airlines_operating_events.parquet"
AIRLINE_SOURCE_RECOVERY_AUDIT_PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_operating_kpi_source_recovery_audit.csv"
AIRLINE_H1_BACKTEST_COMPARISON_PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_h1_kpi_backtest_raw_vs_imputed.csv"
AIRLINE_H1_BACKTEST_SUMMARY_PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_h1_kpi_backtest_imputed_summary.csv"
AIRLINE_PERIOD_BACKTEST_SUMMARY_PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_period_kpi_backtest_summary.csv"
AIRLINE_PERIOD_BACKTEST_LOGICAL_SUMMARY_PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_period_kpi_backtest_logical_assumptions_summary.csv"
AIRLINE_PERIOD_BACKTEST_COMPARISON_PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_period_kpi_backtest_model_comparison.csv"
AIRLINE_SPRING_MAE_DIAGNOSTIC_PATH = ROOT / "data" / "normalized" / "hk_transport" / "airline_spring_mae_diagnostics.csv"
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
    "occupied_spaces", "vacant_spaces", "listed_spaces",
]
CHINA_AIRLINE_NAMES = {
    "601111": "Air China",
    "600029": "China Southern",
    "600115": "China Eastern",
    "601021": "Spring Airlines",
    "600221": "Hainan Airlines Holdings",
    "603885": "Juneyao Airlines",
}
CHINA_AIRLINE_SHORT_NAMES = {
    "Air China": "AC",
    "China Southern": "CS",
    "China Eastern": "CE",
    "Spring Airlines": "Spring",
    "Hainan Airlines Holdings": "Hainan",
    "Juneyao Airlines": "Juneyao",
}
CHINA_AIRLINE_REPORTING_SCOPE = {
    "Air China": "Group-consolidated operating data",
    "China Southern": "Group-consolidated operating data",
    "China Eastern": "Group-consolidated operating data",
    "Spring Airlines": "Company and subsidiaries",
    "Hainan Airlines Holdings": "Hainan group consolidated; includes eight operating carriers",
    "Juneyao Airlines": "Company and Jiuyuan Airlines consolidated",
}
CHINA_AIRLINE_METRICS = {
    "passengers", "ask", "rpk", "passenger_load_factor_pct",
    "atk", "rtk", "aftk", "rftk", "cargo_tonnes",
    "freight_load_factor_pct", "overall_load_factor_pct",
}
CHINA_AIRLINE_COLUMNS = [
    "month", "date", "airline_code", "airline", "region", "metric", "value", "reporting_scope",
]
CHINA_AIRLINE_EVENT_COLUMNS = ["month", "date", "airline_code", "event_type", "value", "detail"]
CHINA_AIRLINE_EVENT_TYPES = {
    "fleet_added_aircraft", "fleet_retired_aircraft", "fleet_total_aircraft", "new_route_event_count",
}


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
            "description": "HKIA airport monthly aircraft movements, passenger volume, and freight tonnage alongside Cathay Pacific passengers, RPK, ASK, passenger/cargo load factors, cargo tonnage, AFTK/RFTK and reported flight sectors, fetched directly from Cathay's own investor-relations traffic-figures PDFs discovered through the official archive.",
        },
    },
    "cathay_fleet": {
        "id": "cathay_fleet",
        "label": "Cathay Pacific Group Official Fleet Profile (annual/interim reports)",
        "href": "https://www.cathaypacific.com/cx/en_HK/about-us/investor-relations/interim-annual-reports.html",
        "path": "sources/cathay_fleet.sql",
        "query": {
            "engine": "official Cathay annual and interim report Fleet Profile tables",
            "url": "https://www.cathaypacific.com/content/dam/cx/about-us/investor-relations/interim-annual-reports/en/<year>_cx_<annual_report|interim_report>_en.pdf",
            "language": "PDF",
            "description": "Fleet totals at each official report period end for the Company, HK Express, Air Hong Kong and Group grand total. This is a semiannual/annual series, not a monthly traffic-announcement field.",
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
            "description": "Monthly passenger and cargo operating data for six China-listed airline groups, plus sparse PDF-derived fleet additions/retirements, fleet totals and new-route events; passenger fields are split by domestic, international and regional operations. The display layer prefers the verified source-recovered parquet when available, with raw processed data as fallback.",
        },
    },
    "airline_kpi_source_recovery": {
        "id": "airline_kpi_source_recovery",
        "label": "China Listed Airlines Official-PDF KPI Recovery Audit",
        "href": "https://www.cninfo.com.cn/",
        "path": "data/normalized/hk_transport/airline_operating_kpi_source_recovery_audit.csv",
        "query": {
            "engine": "official Cninfo PDF recovery audit",
            "url": "https://www.cninfo.com.cn/",
            "language": "CSV + Parquet",
            "sql": "SELECT status, airline_code, month, metric, region, value, recovery_method, reason, announcement_date, source_pdf_url, companion_parser_metrics, source_text_metric_present, source_text_keyword_matches, parser_metric_present, parser_metric_row_count, disclosure_check FROM airline_operating_kpi_source_recovery_audit",
            "description": "Audit of monthly airline KPI rows restored from cached official Cninfo PDFs, separated from rows that the source PDF genuinely does not disclose. The source-recovered parquet is used for the dashboard's monthly airline charts; no research interpolation is included in that display layer.",
        },
    },
    "airline_h1_kpi_backtest": {
        "id": "airline_h1_kpi_backtest",
        "label": "China Listed Airlines 1H KPI Calibration Backtest",
        "href": "https://www.cninfo.com.cn/",
        "path": "data/normalized/hk_transport/airline_h1_kpi_backtest_raw_vs_imputed.csv",
        "query": {
            "engine": "historical KPI-to-financial calibration bridge",
            "url": "https://www.cninfo.com.cn/",
            "language": "CSV",
            "sql": "SELECT company, raw_revenue_flat_ask_mae_pct, imputed_revenue_flat_ask_mae_pct, raw_operating_cost_flat_ask_mae_pct, imputed_operating_cost_flat_ask_mae_pct, imputed_historical_evaluated_rows, imputed_kpi_future_imputation_historical_rows FROM airline_h1_kpi_backtest_raw_vs_imputed",
            "description": "Historical calibration of flat-ASK revenue and operating-cost errors before and after official-PDF source recovery plus research-only short-gap interpolation. This is not a strict historical point-in-time trading backtest because older financial target rows do not retain issuer announcement dates.",
        },
    },
    "airline_period_kpi_backtest": {
        "id": "airline_period_kpi_backtest",
        "label": "China Listed Airlines H1/H2/FY KPI Calibration",
        "href": "https://www.cninfo.com.cn/",
        "path": "data/normalized/hk_transport/airline_period_kpi_backtest_summary.csv",
        "query": {
            "engine": "historical H1/H2/FY KPI-to-financial calibration bridge",
            "url": "https://www.cninfo.com.cn/",
            "language": "CSV",
            "sql": "SELECT company, period, historical_evaluated_rows, pit_safe_evaluated_rows, revenue_flat_rpk_mae_pct, revenue_spring_recovery_case_mae_pct, operating_cost_flat_ask_mae_pct FROM airline_period_kpi_backtest_summary",
            "description": "Separate H1, H2 and FY calibration summaries. H2 financial actuals are derived as FY minus H1; the logical-assumption layer remains a coverage sensitivity and not a clean point-in-time observation.",
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
        "label": "Transport Department Metered Parking-Space Occupancy",
        "href": "https://portal.csdi.gov.hk/geoportal/?datasetId=td_rcd_1638930345315_81787",
        "path": "sources/td_carpark_occupancy.sql",
        "query": {
            "engine": "official TD CSDI metered-space GeoJSON inventory + live occupancy-status CSV",
            "url": "https://portal.csdi.gov.hk/csdi-webpage/file-api?dataset_id=td_rcd_1638930345315_81787&format=geojson&layer_name=parkingspaces ; https://resource.data.one.gov.hk/td/psiparkingspaces/occupancystatus/occupancystatus.csv",
            "language": "GeoJSON + CSV",
            "description": "Observed occupancy rate for sensor-backed metered/on-street parking spaces. The static inventory supplies the listed-space denominator and the live CSV marks each observed space occupied or vacant; sample_size and listed_spaces remain visible because a small number of status rows may be unmatched.",
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


def load_china_airline_traffic(
    path: Path | None = None,
    *,
    recovered_path: Path | None = None,
) -> pd.DataFrame:
    """Load the Cninfo-backed airline parquet with source-recovery overlays.

    The source-recovered layer has the same normalized monthly keys as the
    processed raw layer, with only verified official-PDF rows overlaid. It can
    lag the monthly scraper, however, so replacing the entire raw layer with
    the recovered snapshot silently hid newer months. Merge raw first and
    recovered second by observation key: audited recoveries win where present,
    while newer issuer rows remain visible. The separate imputed layer remains
    research-only.
    """
    if path is None:
        path = CHINA_AIRLINE_DATA_PATH
        recovered_path = CHINA_AIRLINE_SOURCE_RECOVERED_DATA_PATH
    columns = ["month", "date", "airline_code", "region", "metric", "value"]
    if not path.exists():
        return pd.DataFrame(columns=CHINA_AIRLINE_COLUMNS)

    frames = [pd.read_parquet(path)]
    if recovered_path is not None and recovered_path.exists():
        frames.append(pd.read_parquet(recovered_path))
    frame = pd.concat(frames, ignore_index=True, sort=False)
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(f"China airline traffic is missing columns: {missing}")

    result = frame.loc[:, columns].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["month"] = result["date"].dt.strftime("%Y-%m")
    result["airline_code"] = result["airline_code"].astype(str).str.replace(r"\.0$", "", regex=True)
    result = result.drop_duplicates(
        subset=["month", "airline_code", "region", "metric"],
        keep="last",
    )
    result["airline"] = result["airline_code"].map(CHINA_AIRLINE_NAMES)
    result["reporting_scope"] = result["airline"].map(CHINA_AIRLINE_REPORTING_SCOPE)
    result["metric"] = result["metric"].astype(str)
    result["region"] = result["region"].astype(str)
    result["value"] = pd.to_numeric(result["value"], errors="coerce")

    if result["date"].isna().any() or result["value"].isna().any():
        raise ValueError("China airline traffic contains invalid dates or values")
    if result["airline"].isna().any():
        unknown = sorted(result.loc[result["airline"].isna(), "airline_code"].unique())
        raise ValueError(f"China airline traffic contains unknown carriers: {unknown}")
    if result["reporting_scope"].isna().any():
        unknown = sorted(result.loc[result["reporting_scope"].isna(), "airline"].unique())
        raise ValueError(f"China airline traffic contains unknown reporting scopes: {unknown}")
    unknown_metrics = sorted(set(result["metric"]) - CHINA_AIRLINE_METRICS)
    if unknown_metrics:
        raise ValueError(f"China airline traffic contains unknown metrics: {unknown_metrics}")

    return result[CHINA_AIRLINE_COLUMNS].sort_values(
        ["date", "airline_code", "region", "metric"]
    ).reset_index(drop=True)


def _load_research_csv(path: Path, label: str) -> pd.DataFrame:
    """Load a committed research CSV without turning an absent optional layer into an error."""
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    if frame.empty:
        return frame
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def load_airline_h1_backtest_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load the H1 calibration, nowcast summary and source-recovery audit inputs."""
    return (
        _load_research_csv(AIRLINE_H1_BACKTEST_COMPARISON_PATH, "airline H1 backtest comparison"),
        _load_research_csv(AIRLINE_H1_BACKTEST_SUMMARY_PATH, "airline H1 backtest summary"),
        _load_research_csv(AIRLINE_SOURCE_RECOVERY_AUDIT_PATH, "airline source-recovery audit"),
    )


def build_airline_h1_backtest_views(
    comparison: pd.DataFrame,
    summary: pd.DataFrame,
    recovery_audit: pd.DataFrame,
) -> dict[str, list[dict[str, Any]]]:
    """Build compact dashboard views for recovery coverage and H1 calibration.

    The bar-chart datasets intentionally retain both raw and source-recovered
    plus research-imputed layers. This makes the benefit and the sensitivity
    cost of filling gaps visible rather than silently replacing the raw
    history. The dashboard labels the result as calibration, not a strict
    point-in-time trading backtest.
    """
    empty = {
        "airline_h1_revenue_mae_comparison": [],
        "airline_h1_cost_mae_comparison": [],
        "airline_h1_backtest_coverage": [],
        "airline_h1_backtest_summary": [],
        "airline_h1_nowcast_comparison": [],
        "airline_h1_revenue_nowcast_comparison": [],
        "airline_h1_profit_nowcast_comparison": [],
        "airline_source_recovery_summary": [],
        "airline_source_recovery_audit": [],
        "kpi_airline_source_recovery": [],
    }
    if comparison.empty:
        return empty

    views = dict(empty)
    comparison = comparison.copy()
    comparison["company"] = comparison.get("company", comparison.get("raw_company", "")).fillna("").astype(str)
    comparison["ticker"] = comparison.get("raw_ticker", comparison.get("imputed_ticker", "")).fillna("").astype(str)

    def carrier_name(value: str) -> str:
        return CHINA_AIRLINE_SHORT_NAMES.get(value, value)

    def metric_rows(raw_field: str, recovered_field: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for _, row in comparison.sort_values("company").iterrows():
            company = str(row["company"])
            carrier = carrier_name(company)
            for layer, field in (
                ("Raw observed", raw_field),
                ("Source recovered + imputed", recovered_field),
            ):
                value = pd.to_numeric(pd.Series([row.get(field)]), errors="coerce").iloc[0]
                if pd.isna(value):
                    continue
                rows.append(
                    {
                        "company": company,
                        "carrier": carrier,
                        "ticker": str(row["ticker"]),
                        "layer": layer,
                        "value": round(float(value), 4),
                    }
                )
        return rows

    views["airline_h1_revenue_mae_comparison"] = metric_rows(
        "raw_revenue_flat_ask_mae_pct", "imputed_revenue_flat_ask_mae_pct"
    )
    views["airline_h1_cost_mae_comparison"] = metric_rows(
        "raw_operating_cost_flat_ask_mae_pct", "imputed_operating_cost_flat_ask_mae_pct"
    )

    summary_rows: list[dict[str, Any]] = []
    summary_columns = {
        "historical_rows": "imputed_historical_evaluated_rows",
        "revenue_mae_pct": "imputed_revenue_flat_ask_mae_pct",
        "cost_mae_pct": "imputed_operating_cost_flat_ask_mae_pct",
        "profit_direction_accuracy": "imputed_profit_direction_accuracy",
        "imputation_rows": "imputed_kpi_imputation_used_historical_rows",
        "future_imputation_rows": "imputed_kpi_future_imputation_historical_rows",
        "pit_safe_rows": "imputed_kpi_pit_safe_historical_rows",
    }
    for _, row in comparison.sort_values("company").iterrows():
        company = str(row["company"])
        summary_row: dict[str, Any] = {
            "company": company,
            "carrier": carrier_name(company),
            "ticker": str(row["ticker"]),
            "source_quality": str(row.get("source_quality", "")),
        }
        for output_field, input_field in summary_columns.items():
            value = pd.to_numeric(pd.Series([row.get(input_field)]), errors="coerce").iloc[0]
            summary_row[output_field] = None if pd.isna(value) else round(float(value), 4)
        if summary_row["historical_rows"] is not None:
            summary_row["historical_rows"] = int(summary_row["historical_rows"])
        for field in ("imputation_rows", "future_imputation_rows", "pit_safe_rows"):
            if summary_row[field] is not None:
                summary_row[field] = int(summary_row[field])
        summary_rows.append(summary_row)
    views["airline_h1_backtest_summary"] = summary_rows

    coverage_rows: list[dict[str, Any]] = []
    for _, row in comparison.sort_values("company").iterrows():
        company = str(row["company"])
        carrier = carrier_name(company)
        for layer, field in (
            ("Raw observed", "raw_historical_evaluated_rows"),
            ("Source recovered + imputed", "imputed_historical_evaluated_rows"),
        ):
            value = pd.to_numeric(pd.Series([row.get(field)]), errors="coerce").iloc[0]
            if pd.isna(value):
                continue
            coverage_rows.append(
                {
                    "company": company,
                    "carrier": carrier,
                    "ticker": str(row["ticker"]),
                    "layer": layer,
                    "value": int(value),
                }
            )
    views["airline_h1_backtest_coverage"] = coverage_rows

    if not summary.empty:
        summary = summary.copy()
        summary["company"] = summary.get("company", "").fillna("").astype(str)
        nowcast_rows: list[dict[str, Any]] = []
        for _, row in summary.sort_values("company").iterrows():
            company = str(row["company"])
            carrier = carrier_name(company)
            for measure, flat_field, analyst_field in (
                ("Revenue", "flat_ask_revenue_pred_usd_mn", "analyst_h1_revenue_pred_usd_mn"),
                ("Profit", "flat_ask_profit_pred_usd_mn", "analyst_h1_profit_pred_usd_mn"),
            ):
                for view_name, field in (("Flat ASK", flat_field), ("Analyst overlay", analyst_field)):
                    value = pd.to_numeric(pd.Series([row.get(field)]), errors="coerce").iloc[0]
                    if pd.isna(value):
                        continue
                    nowcast_rows.append(
                        {
                            "company": company,
                            "carrier": carrier,
                            "ticker": str(row.get("ticker", "")),
                            "measure": measure,
                            "view": view_name,
                            "value_usd_mn": round(float(value), 4),
                        }
                    )
        views["airline_h1_nowcast_comparison"] = nowcast_rows
        views["airline_h1_revenue_nowcast_comparison"] = [
            row for row in nowcast_rows if row["measure"] == "Revenue"
        ]
        views["airline_h1_profit_nowcast_comparison"] = [
            row for row in nowcast_rows if row["measure"] == "Profit"
        ]

    if not recovery_audit.empty:
        recovery_audit = recovery_audit.copy()
        recovery_audit["status"] = recovery_audit.get("status", "").fillna("").astype(str)
        status_labels = {
            "recovered_from_cached_official_pdf": "Recovered from official PDF",
            "not_disclosed_in_source_pdf": "Not disclosed in source PDF",
        }
        summary_rows = []
        for status, count in recovery_audit["status"].value_counts().items():
            summary_rows.append(
                {
                    "status": status,
                    "status_label": status_labels.get(status, status),
                    "value": int(count),
                }
            )
        views["airline_source_recovery_summary"] = summary_rows
        audit_columns = [
            "status", "airline_code", "month", "metric", "region", "value",
            "recovery_method", "reason", "announcement_date", "source_pdf_url",
            "companion_parser_metrics", "source_text_metric_present",
            "source_text_keyword_matches", "parser_metric_present",
            "parser_metric_row_count", "parser_metric_regions", "disclosure_check",
        ]
        available = [column for column in audit_columns if column in recovery_audit.columns]
        audit = recovery_audit[available].copy()
        views["airline_source_recovery_audit"] = json.loads(
            audit.to_json(orient="records", date_format="iso")
        )
        recovered = int(recovery_audit["status"].str.startswith("recovered").sum())
        not_disclosed = int(recovery_audit["status"].eq("not_disclosed_in_source_pdf").sum())
        views["kpi_airline_source_recovery"] = [
            {
                "recovered_rows": recovered,
                "not_disclosed_rows": not_disclosed,
                "audit_rows": int(len(recovery_audit)),
            }
        ]
    return views


def load_airline_period_backtest_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load strict/logical H1-H2-FY summaries and Spring diagnostics."""
    return (
        _load_research_csv(AIRLINE_PERIOD_BACKTEST_SUMMARY_PATH, "airline period backtest summary"),
        _load_research_csv(AIRLINE_PERIOD_BACKTEST_LOGICAL_SUMMARY_PATH, "airline logical-assumption period summary"),
        _load_research_csv(AIRLINE_PERIOD_BACKTEST_COMPARISON_PATH, "airline period backtest model comparison"),
        _load_research_csv(AIRLINE_SPRING_MAE_DIAGNOSTIC_PATH, "airline Spring MAE diagnostics"),
    )


def build_airline_period_backtest_views(
    strict_summary: pd.DataFrame,
    logical_summary: pd.DataFrame,
    comparison: pd.DataFrame,
    spring_diagnostics: pd.DataFrame,
) -> dict[str, list[dict[str, Any]]]:
    """Build compact H1/H2/FY and Spring model-risk dashboard views."""
    empty = {
        "airline_period_revenue_mae": [],
        "airline_period_backtest_summary": [],
        "airline_period_assumption_comparison": [],
        "airline_spring_mae_diagnostics": [],
    }
    views = dict(empty)
    if not strict_summary.empty:
        strict = strict_summary.copy()
        strict["company"] = strict.get("company", "").fillna("").astype(str)
        strict["period"] = strict.get("period", "").fillna("").astype(str)
        logical = logical_summary.copy()
        logical_by_key = {}
        if not logical.empty and {"company", "period"}.issubset(logical.columns):
            logical["company"] = logical["company"].fillna("").astype(str)
            logical["period"] = logical["period"].fillna("").astype(str)
            logical_by_key = {
                (str(row["company"]), str(row["period"])): row
                for _, row in logical.iterrows()
            }
        for _, row in strict.sort_values(["period", "company"]).iterrows():
            company = str(row["company"])
            logical_row = logical_by_key.get((company, str(row["period"])))
            views["airline_period_revenue_mae"].append(
                {
                    "company": company,
                    "carrier": CHINA_AIRLINE_SHORT_NAMES.get(company, company),
                    "ticker": f"{next((code for code, name in CHINA_AIRLINE_NAMES.items() if name == company), '')}.SH",
                    "period": str(row["period"]),
                    "evaluated_rows": int(row["historical_evaluated_rows"]),
                    "flat_rpk_revenue_mae_pct": round(float(row["revenue_flat_rpk_mae_pct"]), 4),
                    "recovery_case_revenue_mae_pct": round(float(row["revenue_spring_recovery_case_mae_pct"]), 4),
                }
            )
            views["airline_period_backtest_summary"].append(
                {
                    "company": company,
                    "carrier": CHINA_AIRLINE_SHORT_NAMES.get(company, company),
                    "period": str(row["period"]),
                    "historical_evaluated_rows": int(row["historical_evaluated_rows"]),
                    "pit_safe_evaluated_rows": int(row["pit_safe_evaluated_rows"]),
                    "logical_assumption_rows": int(
                        logical_row["logical_assumption_rows"]
                        if logical_row is not None
                        else row["logical_assumption_rows"]
                    ),
                    "logical_historical_evaluated_rows": int(
                        logical_row["historical_evaluated_rows"]
                        if logical_row is not None
                        else row["historical_evaluated_rows"]
                    ),
                    "flat_ask_revenue_mae_pct": round(float(row["revenue_flat_ask_mae_pct"]), 4),
                    "flat_rpk_revenue_mae_pct": round(float(row["revenue_flat_rpk_mae_pct"]), 4),
                    "recovery_case_revenue_mae_pct": round(float(row["revenue_spring_recovery_case_mae_pct"]), 4),
                    "flat_ask_cost_mae_pct": round(float(row["operating_cost_flat_ask_mae_pct"]), 4),
                    "logical_flat_rpk_revenue_mae_pct": round(
                        float(
                            logical_row["revenue_flat_rpk_mae_pct"]
                            if logical_row is not None
                            else row["revenue_flat_rpk_mae_pct"]
                        ),
                        4,
                    ),
                }
            )
    if not comparison.empty:
        compare = comparison.copy()
        for _, row in compare.sort_values(["period", "company"]).iterrows():
            views["airline_period_assumption_comparison"].append(
                {
                    "company": str(row.get("company", "")),
                    "carrier": CHINA_AIRLINE_SHORT_NAMES.get(str(row.get("company", "")), str(row.get("company", ""))),
                    "period": str(row.get("period", "")),
                    "strict_rows": int(row["strict_historical_evaluated_rows"]),
                    "logical_rows": int(row["logical_historical_evaluated_rows"]),
                    "coverage_delta": int(row["coverage_delta_logical_minus_strict"]),
                    "strict_flat_rpk_mae_pct": round(float(row["strict_revenue_flat_rpk_mae_pct"]), 4),
                    "logical_flat_rpk_mae_pct": round(float(row["logical_revenue_flat_rpk_mae_pct"]), 4),
                }
            )
    if not spring_diagnostics.empty:
        diagnostic = spring_diagnostics.copy()
        for _, row in diagnostic.sort_values(["period", "target_year"]).iterrows():
            views["airline_spring_mae_diagnostics"].append(
                {
                    "statement_period": str(row.get("statement_period", "")),
                    "period": str(row.get("period", "")),
                    "target_year": int(row["target_year"]),
                    "regime": str(row.get("regime", "")),
                    "ask_growth_pct": round(float(row["ask_growth_pct"]), 4),
                    "rpk_growth_pct": round(float(row["rpk_growth_pct"]), 4),
                    "rpk_minus_ask_gap_pp": round(float(row["rpk_minus_ask_growth_gap_pp"]), 4),
                    "load_factor_change_pp": round(float(row["load_factor_change_pp"]), 4),
                    "flat_ask_error_pct": round(float(row["revenue_error_flat_ask_pct"]), 4),
                    "flat_rpk_error_pct": round(float(row["revenue_error_flat_rpk_pct"]), 4),
                    "recovery_case_error_pct": round(float(row["revenue_error_spring_recovery_case_pct"]), 4),
                    "kpi_pit_safe": bool(row["kpi_pit_safe"]),
                }
            )
    return views


def load_china_airline_operating_events(path: Path = CHINA_AIRLINE_EVENT_DATA_PATH) -> pd.DataFrame:
    """Load the separate fleet/route event layer built from official PDFs."""
    if not path.exists():
        return pd.DataFrame(columns=CHINA_AIRLINE_EVENT_COLUMNS)
    frame = pd.read_parquet(path)
    missing = sorted(set(CHINA_AIRLINE_EVENT_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"China airline operating events are missing columns: {missing}")
    result = frame.loc[:, CHINA_AIRLINE_EVENT_COLUMNS].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["month"] = result["date"].dt.strftime("%Y-%m")
    result["airline_code"] = result["airline_code"].astype(str).str.replace(r"\.0$", "", regex=True)
    result["event_type"] = result["event_type"].astype(str)
    result["value"] = pd.to_numeric(result["value"], errors="coerce")
    result["detail"] = result["detail"].fillna("").astype(str)
    if result["date"].isna().any() or result["value"].isna().any():
        raise ValueError("China airline operating events contain invalid dates or values")
    unknown_codes = sorted(set(result["airline_code"]) - set(CHINA_AIRLINE_NAMES))
    if unknown_codes:
        raise ValueError(f"China airline operating events contain unknown carriers: {unknown_codes}")
    unknown_types = sorted(set(result["event_type"]) - CHINA_AIRLINE_EVENT_TYPES)
    if unknown_types:
        raise ValueError(f"China airline operating events contain unknown event types: {unknown_types}")
    if (result["value"] < 0).any():
        raise ValueError("China airline operating events contain negative values")
    return result.sort_values(["date", "airline_code", "event_type"]).reset_index(drop=True)


def build_china_airline_event_views(events: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Build sparse fleet/route signals without filling absent events as zero."""
    empty = {
        "china_airline_fleet_total_history": [],
        "china_airline_fleet_net_change_history": [],
        "china_airline_new_route_history": [],
        "china_airline_operating_events_latest": [],
    }
    if events.empty:
        return empty

    data = events.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["month"] = data["date"].dt.strftime("%Y-%m")
    data["airline_code"] = data["airline_code"].astype(str)
    data["airline"] = data["airline_code"].map(CHINA_AIRLINE_NAMES)
    data["reporting_scope"] = data["airline"].map(CHINA_AIRLINE_REPORTING_SCOPE)
    data["series"] = data["airline"].map(CHINA_AIRLINE_SHORT_NAMES)

    def history(selected: pd.DataFrame) -> list[dict[str, Any]]:
        return [
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "month": row["month"],
                "series": row["series"],
                "airline": row["airline"],
                "value": round(float(row["value"]), 4),
            }
            for _, row in selected.sort_values(["date", "series"]).iterrows()
        ]

    fleet_total = data[data["event_type"].eq("fleet_total_aircraft")]
    fleet_total_history = history(fleet_total)

    fleet_changes = data[data["event_type"].isin({"fleet_added_aircraft", "fleet_retired_aircraft"})]
    if fleet_changes.empty:
        fleet_net_history = []
    else:
        keys = ["date", "month", "airline_code", "airline", "series"]
        pivot = fleet_changes.pivot_table(
            index=keys, columns="event_type", values="value", aggfunc="sum", fill_value=0
        ).reset_index()
        for column in ("fleet_added_aircraft", "fleet_retired_aircraft"):
            if column not in pivot.columns:
                pivot[column] = 0
        pivot["value"] = pivot["fleet_added_aircraft"] - pivot["fleet_retired_aircraft"]
        fleet_net_history = history(pivot)

    route_history = history(data[data["event_type"].eq("new_route_event_count")])

    latest_date = data["date"].max()
    latest = data[data["date"].eq(latest_date)].copy()
    latest["observation_date"] = latest_date.strftime("%Y-%m-%d")
    latest = latest[
        ["airline_code", "airline", "reporting_scope", "event_type", "value", "detail", "observation_date"]
    ].sort_values(["airline", "event_type"])
    return {
        "china_airline_fleet_total_history": fleet_total_history,
        "china_airline_fleet_net_change_history": fleet_net_history,
        "china_airline_new_route_history": route_history,
        "china_airline_operating_events_latest": json.loads(latest.to_json(orient="records", date_format="iso")),
    }


def build_china_airline_views(
    frame: pd.DataFrame,
    events: pd.DataFrame | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build compact chart/table datasets from the normalized airline frame."""
    empty = {
        "china_airline_passengers_history": [],
        "china_airline_ask_history": [],
        "china_airline_rpk_history": [],
        "china_airline_load_factor_history": [],
        "china_airline_region_split_history": [],
        "china_airline_region_by_carrier_history": [],
        "china_airline_latest_snapshot": [],
        "china_airline_cargo_history": [],
        "china_airline_freight_load_factor_history": [],
        "china_airline_overall_load_factor_history": [],
        "china_airline_cargo_latest_snapshot": [],
        "china_airline_fleet_total_history": [],
        "china_airline_fleet_net_change_history": [],
        "china_airline_new_route_history": [],
        "china_airline_operating_events_latest": [],
    }
    if frame.empty:
        return {**empty, **build_china_airline_event_views(events if events is not None else pd.DataFrame())}

    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    if "airline" not in data.columns:
        data["airline_code"] = data["airline_code"].astype(str)
        data["airline"] = data["airline_code"].map(CHINA_AIRLINE_NAMES)
    if "reporting_scope" not in data.columns:
        data["reporting_scope"] = data["airline"].map(CHINA_AIRLINE_REPORTING_SCOPE)
    data["month"] = data["date"].dt.strftime("%Y-%m")

    def total_metric(metric: str) -> pd.DataFrame:
        """Return one all-operation value per carrier/month for a metric.

        Some issuers print a dedicated Total row while others only print
        Domestic/International/Regional rows. Additive cargo and tonne-km
        metrics can safely use the same complete-three-region derivation as
        passengers/ASK/RPK; reported totals always win when both are present.
        Load factors are derived from their numerator/denominator rather than
        averaging percentages.
        """
        keys = ["date", "month", "airline_code", "airline"]
        reported = data[
            data["region"].eq("Total") & data["metric"].eq(metric)
        ][keys + ["value"]].copy()
        additive = {"cargo_tonnes", "aftk", "rftk", "atk", "rtk"}
        if metric in additive:
            regional = data[
                data["region"].ne("Total") & data["metric"].eq(metric)
            ]
            if not regional.empty:
                counts = regional.groupby(keys)["region"].nunique().reset_index(name="region_count")
                derived = regional.groupby(keys, as_index=False)["value"].sum().merge(
                    counts, on=keys
                )
                derived = derived[derived["region_count"] >= 3].drop(columns="region_count")
                result = pd.concat([derived, reported], ignore_index=True)
            else:
                result = reported
        elif metric == "freight_load_factor_pct":
            numerator = total_metric("rftk")
            denominator = total_metric("aftk")
            derived = numerator.merge(
                denominator,
                on=keys,
                suffixes=("_rftk", "_aftk"),
            )
            derived = derived[derived["value_aftk"] > 0].copy()
            derived["value"] = derived["value_rftk"] / derived["value_aftk"] * 100
            derived = derived[keys + ["value"]]
            result = pd.concat([derived, reported], ignore_index=True)
        elif metric == "overall_load_factor_pct":
            numerator = total_metric("rtk")
            denominator = total_metric("atk")
            derived = numerator.merge(
                denominator,
                on=keys,
                suffixes=("_rtk", "_atk"),
            )
            derived = derived[derived["value_atk"] > 0].copy()
            derived["value"] = derived["value_rtk"] / derived["value_atk"] * 100
            derived = derived[keys + ["value"]]
            result = pd.concat([derived, reported], ignore_index=True)
        else:
            result = reported
        if result.empty:
            return result
        return result.drop_duplicates(subset=keys, keep="last").sort_values(keys).reset_index(drop=True)

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
    # chart -- with all 6 carriers now included (see the derivation above),
    # a single chart would need a 12-item legend (6 carriers x 2 metrics),
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

    # Keep the carrier-level drill-down within the portable artifact's
    # per-dataset row limit (18 carrier/region series x roughly 9 years),
    # while the combined region chart above retains the full available
    # history.  This still covers the full 2021-2025 interval under review.
    regional_cutoff = data["date"].max() - pd.DateOffset(years=9)
    regional_by_carrier = data[
        data["region"].ne("Total")
        & data["metric"].eq("passengers")
        & data["date"].ge(regional_cutoff)
    ]
    if regional_by_carrier.empty:
        regional_by_carrier_rows: list[dict[str, Any]] = []
    else:
        regional_by_carrier = (
            regional_by_carrier.groupby(
                ["date", "month", "airline_code", "airline", "region"],
                as_index=False,
            )["value"]
            .sum()
        )
        regional_by_carrier["series"] = (
            regional_by_carrier["airline"].map(CHINA_AIRLINE_SHORT_NAMES)
            + " · "
            + regional_by_carrier["region"]
        )
        regional_by_carrier_rows = [
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "month": row["month"],
                "series": row["series"],
                "airline": row["airline"],
                "region": row["region"],
                "value": round(float(row["value"]), 4),
            }
            for _, row in regional_by_carrier.sort_values(["date", "series"]).iterrows()
        ]
    latest_date = data["date"].max()

    def auxiliary_history(metric: str) -> list[dict[str, Any]]:
        selected = total_metric(metric)
        if selected.empty:
            return []
        selected = selected.copy()
        selected["series"] = selected["airline"].map(CHINA_AIRLINE_SHORT_NAMES)
        return [
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "month": row["month"],
                "series": row["series"],
                "airline": row["airline"],
                "value": round(float(row["value"]), 4),
            }
            for _, row in selected.sort_values(["date", "series"]).iterrows()
        ]

    cargo_history = auxiliary_history("cargo_tonnes")
    freight_load_factor_history = auxiliary_history("freight_load_factor_pct")
    overall_load_factor_history = auxiliary_history("overall_load_factor_pct")

    cargo_metrics = ["cargo_tonnes", "aftk", "rftk", "freight_load_factor_pct", "overall_load_factor_pct"]
    cargo_latest = []
    for metric in cargo_metrics:
        values = total_metric(metric)
        if values.empty:
            continue
        values = values[values["date"].eq(latest_date)].copy()
        if values.empty:
            continue
        values["metric"] = metric
        cargo_latest.append(values)
    if cargo_latest:
        cargo_latest_frame = pd.concat(cargo_latest, ignore_index=True)
        cargo_snapshot = (
            cargo_latest_frame.pivot_table(
                index=["airline_code", "airline"],
                columns="metric",
                values="value",
                aggfunc="last",
            )
            .reset_index()
        )
        for column in cargo_metrics:
            if column not in cargo_snapshot.columns:
                cargo_snapshot[column] = None
        cargo_snapshot["reporting_scope"] = cargo_snapshot["airline"].map(CHINA_AIRLINE_REPORTING_SCOPE)
        cargo_snapshot["observation_date"] = latest_date.strftime("%Y-%m-%d")
        cargo_snapshot = cargo_snapshot[
            [
                "airline_code", "airline", "reporting_scope", "cargo_tonnes", "aftk", "rftk",
                "freight_load_factor_pct", "overall_load_factor_pct", "observation_date",
            ]
        ].sort_values("airline")
    else:
        cargo_snapshot = pd.DataFrame()

    latest = data[data["date"].eq(latest_date)]
    snapshot = (
        latest.pivot_table(
            index=["airline_code", "airline", "reporting_scope", "region"],
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
        [
            "airline_code", "airline", "reporting_scope", "region", "passengers", "ask", "rpk",
            "load_factor_pct", "observation_date",
        ]
    ].sort_values(["airline", "region"])

    return {
        "china_airline_passengers_history": history("passengers"),
        "china_airline_ask_history": ask_history,
        "china_airline_rpk_history": rpk_history,
        "china_airline_load_factor_history": history("passenger_load_factor_pct"),
        "china_airline_region_split_history": region_rows,
        "china_airline_region_by_carrier_history": regional_by_carrier_rows,
        "china_airline_latest_snapshot": json.loads(snapshot.to_json(orient="records", date_format="iso")),
        "china_airline_cargo_history": cargo_history,
        "china_airline_freight_load_factor_history": freight_load_factor_history,
        "china_airline_overall_load_factor_history": overall_load_factor_history,
        "china_airline_cargo_latest_snapshot": json.loads(cargo_snapshot.to_json(orient="records", date_format="iso")) if not cargo_snapshot.empty else [],
        **build_china_airline_event_views(events if events is not None else pd.DataFrame()),
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
    for column in ("sample_size", "capacity_spaces", "occupied_spaces", "vacant_spaces", "listed_spaces"):
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
            parks_with_unknown_count=("park_id", lambda values: int(values[~data.loc[values.index, "exact_count"]].nunique())),
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
            "parks_with_unknown_count": int(row["parks_with_unknown_count"]),
            "participating_parks": int(row["participating_parks"]),
        }
        for _, row in history.iterrows()
    ]

    latest_snapshot = data["snapshot_at"].max()
    current = data[data["snapshot_at"].eq(latest_snapshot)].copy()
    exact = current[current["exact_count"]]
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
        estimate_by_date = (
            selected.assign(date_key=selected["date"].dt.strftime("%Y-%m-%d"))
            .groupby("date_key")["is_estimate"]
            .any()
            .to_dict()
        )
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
                f"({int(row['sample_size'])} observed metered spaces)"
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
    raw_cathay_fleet: pd.DataFrame | None = None,
    raw_china_airline: pd.DataFrame | None = None,
    raw_china_airline_events: pd.DataFrame | None = None,
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
    cathay_fleet = raw_cathay_fleet if raw_cathay_fleet is not None else fetch_cathay_fleet_history()
    china_airline = raw_china_airline if raw_china_airline is not None else load_china_airline_traffic()
    china_airline_events = (
        raw_china_airline_events
        if raw_china_airline_events is not None
        else load_china_airline_operating_events()
    )
    china_airline_views = build_china_airline_views(china_airline, china_airline_events)
    h1_backtest_comparison, h1_backtest_summary, source_recovery_audit = load_airline_h1_backtest_inputs()
    airline_h1_backtest_views = build_airline_h1_backtest_views(
        h1_backtest_comparison,
        h1_backtest_summary,
        source_recovery_audit,
    )
    period_backtest_summary, period_backtest_logical_summary, period_backtest_comparison, spring_mae_diagnostics = load_airline_period_backtest_inputs()
    airline_period_backtest_views = build_airline_period_backtest_views(
        period_backtest_summary,
        period_backtest_logical_summary,
        period_backtest_comparison,
        spring_mae_diagnostics,
    )
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

    cathay_cargo_capacity_demand_history: list[dict[str, Any]] = []
    cathay_cargo_capacity_demand_history.extend(_series_history(cathay, "AFTK ('000)", "cathay_aftk_thousands"))
    cathay_cargo_capacity_demand_history.extend(_series_history(cathay, "RFTK ('000)", "cathay_rftk_thousands"))
    cathay_cargo_capacity_demand_history.sort(key=lambda row: (row["date"], row["series"]))

    cathay_fleet_total_history: list[dict[str, Any]] = []
    if not cathay_fleet.empty:
        fleet = cathay_fleet.copy()
        fleet["date"] = pd.to_datetime(fleet["date"], errors="coerce")
        fleet["fleet_total_aircraft"] = pd.to_numeric(fleet["fleet_total_aircraft"], errors="coerce")
        fleet = fleet.dropna(subset=["date", "fleet_total_aircraft"])
        for scope, scope_frame in fleet.groupby("scope", sort=True):
            cathay_fleet_total_history.extend(
                _series_history(scope_frame, str(scope), "fleet_total_aircraft")
            )
        cathay_fleet_total_history.sort(key=lambda row: (row["date"], row["series"]))

    datasets = {
        "kpi_mtr": [mtr_kpi],
        "kpi_cathay": [cathay_kpi],
        "mtr_history": mtr.to_dict(orient="records"),
        "cathay_history": cathay.to_dict(orient="records"),
        "mtr_service_breakdown_history": mtr_service_breakdown_history,
        "cathay_capacity_demand_history": cathay_capacity_demand_history,
        "cathay_cargo_capacity_demand_history": cathay_cargo_capacity_demand_history,
        "cathay_fleet_total_history": cathay_fleet_total_history,
        **china_airline_views,
        **airline_h1_backtest_views,
        **airline_period_backtest_views,
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
    if parking_views["hk_parking_vacancy_history"]:
        cards.append(
            {
                "id": "parking_card",
                "description": "Current Transport Department parking-vacancy snapshot; exact counts exclude operators that report only availability/no-data status.",
                "dataset": "hk_parking_vacancy_history",
                "sourceId": "td_parking_vacancy",
                "metrics": [
                    {"label": "Exact Vacant Spaces", "field": "value", "format": "number"},
                    {"label": "Parks with Exact Counts", "field": "parks_reporting_exact", "format": "number"},
                    {"label": "Parks in Feed", "field": "participating_parks", "format": "number"},
                ],
            }
        )
    if carpark_occupancy_views["kpi_carpark_occupancy"]:
        cards.append(
            {
                "id": "carpark_occupancy_card",
                "description": "Observed occupancy for TD sensor-backed metered/on-street parking spaces; the listed-space denominator is explicit and unmatched sensor rows remain excluded.",
                "dataset": "kpi_carpark_occupancy",
                "sourceId": "td_carpark_occupancy",
                "metrics": [
                    {"label": "Occupancy", "field": "occupancy_pct", "format": "number"},
                    {"label": "Observed Spaces", "field": "sample_size", "format": "number"},
                    {"label": "Listed Spaces", "field": "listed_spaces", "format": "number"},
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
            "id": "cathay_cargo_tonnage_chart",
            "title": "Cathay Cargo Tonnage Carried",
            "subtitle": "Monthly Cathay Cargo tonnage carried, sourced from Cathay's traffic-figures PDFs; the airport-wide HKIA freight series remains separate.",
            "type": "line",
            "dataset": "cathay_history",
            "sourceId": "cathay_hkia_traffic",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "cathay_cargo_tonnes", "type": "quantitative", "label": "Tonnes"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "cathay_freight_load_factor_chart",
            "title": "Cathay Cargo Load Factor",
            "subtitle": "Monthly cargo load factor from Cathay's disclosed cargo/freight tonne-kilometre measures.",
            "type": "line",
            "dataset": "cathay_history",
            "sourceId": "cathay_hkia_traffic",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "cathay_cargo_load_factor_pct", "type": "quantitative", "label": "Load Factor (%)"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "cathay_cargo_capacity_demand_chart",
            "title": "Cathay Cargo Capacity vs. Demand (AFTK vs. RFTK, '000s)",
            "subtitle": "Available Freight Tonne Kilometres (AFTK) versus Revenue Freight Tonne Kilometres (RFTK); older PDFs use cargo/mail wording for the same concepts.",
            "type": "line",
            "dataset": "cathay_cargo_capacity_demand_history",
            "sourceId": "cathay_hkia_traffic",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "value", "type": "quantitative", "label": "000s"},
                "color": {"field": "series", "type": "nominal", "label": "Metric"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "cathay_flight_sectors_chart",
            "title": "Cathay Reported Flight Sectors",
            "subtitle": "Monthly reported passenger/cargo flight sectors. Older disclosures use a combined 'number of flights' field; newer PDFs split passenger and freighter sectors and are summed when both are available.",
            "type": "line",
            "dataset": "cathay_history",
            "sourceId": "cathay_hkia_traffic",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "cathay_flight_sectors", "type": "quantitative", "label": "Flight sectors"},
            },
            "valueFormat": "number",
            "layout": "full",
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

    if cathay_fleet_total_history:
        charts.append(
            {
                "id": "cathay_fleet_total_chart",
                "title": "Cathay Group Fleet Profile",
                "subtitle": "Official Fleet Profile totals at each annual/interim report period end. The Company, HK Express, Air Hong Kong and Group grand total are reported at semiannual/annual cadence; no monthly interpolation is applied.",
                "type": "line",
                "dataset": "cathay_fleet_total_history",
                "sourceId": "cathay_fleet",
                "encodings": {
                    "x": {"field": "month", "type": "temporal", "label": "Report period"},
                    "y": {"field": "value", "type": "quantitative", "label": "Aircraft"},
                    "color": {"field": "series", "type": "nominal", "label": "Scope"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    if china_airline_views["china_airline_passengers_history"]:
        charts.extend(
            [
                {
                    "id": "china_airline_passengers_chart",
                    "title": "China Listed Airlines Passenger Traffic",
                    "subtitle": "Monthly total passengers carried by six China-listed airline groups: Air China, China Southern, China Eastern, Spring, Hainan and Juneyao.",
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
                    # Two charts (ASK, RPK), not one combined chart -- with all 6
                    # carriers now included, one chart would need a 12-item
                    # legend (6 carriers x 2 metrics), which overflows the
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
                    "subtitle": "Combined passenger traffic across the six carriers, split into domestic, international and regional operations; use the latest-snapshot table for carrier-level values.",
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
                {
                    "id": "china_airline_region_by_carrier_chart",
                    "title": "China Listed Airlines Passenger Traffic by Carrier and Region",
                    "subtitle": "Carrier-level monthly passenger traffic over the latest nine years, split into domestic, international and regional operations; source blanks remain missing and explicit dashes are retained as zero.",
                    "type": "line",
                    "dataset": "china_airline_region_by_carrier_history",
                    "sourceId": "china_airline_traffic",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "Passengers"},
                        "color": {"field": "series", "type": "nominal", "label": "Carrier / Region"},
                    },
                    "valueFormat": "number",
                    "layout": "full",
                    "maxRows": 3000,
                },
                {
                    "id": "china_airline_cargo_chart",
                    "title": "China Listed Airlines Cargo Tonnage",
                    "subtitle": "Monthly cargo and mail tonnage disclosed by the six listed airline groups; values are normalized to tonnes.",
                    "type": "line",
                    "dataset": "china_airline_cargo_history",
                    "sourceId": "china_airline_traffic",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "Tonnes"},
                        "color": {"field": "series", "type": "nominal", "label": "Airline"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
                {
                    "id": "china_airline_freight_load_factor_chart",
                    "title": "China Listed Airlines Freight Load Factor",
                    "subtitle": "Monthly freight/mail load factor by carrier, using each issuer's disclosed total or the normalized RFTK/AFTK ratio.",
                    "type": "line",
                    "dataset": "china_airline_freight_load_factor_history",
                    "sourceId": "china_airline_traffic",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "%"},
                        "color": {"field": "series", "type": "nominal", "label": "Airline"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
            ]
        )

    if china_airline_views["china_airline_fleet_total_history"]:
        charts.extend(
            [
                {
                    "id": "china_airline_fleet_total_chart",
                    "title": "China Listed Airlines Fleet Size",
                    "subtitle": "Monthly aircraft fleet totals explicitly disclosed in operating-data announcements; missing months are not filled by interpolation.",
                    "type": "line",
                    "dataset": "china_airline_fleet_total_history",
                    "sourceId": "china_airline_traffic",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "Aircraft"},
                        "color": {"field": "series", "type": "nominal", "label": "Airline"},
                    },
                    "valueFormat": "number",
                    "layout": "full",
                },
                {
                    "id": "china_airline_fleet_net_change_chart",
                    "title": "China Listed Airlines Monthly Fleet Net Change",
                    "subtitle": "Aircraft introduced minus aircraft retired/returned in months where an event was disclosed; zero is not imputed for absent announcements.",
                    "type": "line",
                    "dataset": "china_airline_fleet_net_change_history",
                    "sourceId": "china_airline_traffic",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "Net aircraft"},
                        "color": {"field": "series", "type": "nominal", "label": "Airline"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
                {
                    "id": "china_airline_new_route_chart",
                    "title": "China Listed Airlines New-Route Events",
                    "subtitle": "Sparse monthly count of new-route phrases found in official announcements; route text remains available in the latest-events table.",
                    "type": "line",
                    "dataset": "china_airline_new_route_history",
                    "sourceId": "china_airline_traffic",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "value", "type": "quantitative", "label": "Route events"},
                        "color": {"field": "series", "type": "nominal", "label": "Airline"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
            ]
        )

    if airline_h1_backtest_views["airline_h1_revenue_mae_comparison"]:
        charts.extend(
            [
                {
                    "id": "airline_h1_revenue_mae_chart",
                    "title": "1H KPI Calibration — Revenue MAE",
                    "subtitle": "Absolute revenue error of the flat-ASK calibration, before and after verified source recovery plus research-only short-gap interpolation. Lower is better.",
                    "type": "bar",
                    "dataset": "airline_h1_revenue_mae_comparison",
                    "sourceId": "airline_h1_kpi_backtest",
                    "encodings": {
                        "x": {"field": "carrier", "type": "nominal", "label": "Airline"},
                        "y": {"field": "value", "type": "quantitative", "label": "Revenue MAE (%)"},
                        "color": {"field": "layer", "type": "nominal", "label": "Input layer"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
                {
                    "id": "airline_h1_cost_mae_chart",
                    "title": "1H KPI Calibration — Operating Cost MAE",
                    "subtitle": "Absolute operating-cost error of the flat-ASK calibration, before and after verified source recovery plus research-only short-gap interpolation. Lower is better.",
                    "type": "bar",
                    "dataset": "airline_h1_cost_mae_comparison",
                    "sourceId": "airline_h1_kpi_backtest",
                    "encodings": {
                        "x": {"field": "carrier", "type": "nominal", "label": "Airline"},
                        "y": {"field": "value", "type": "quantitative", "label": "Operating cost MAE (%)"},
                        "color": {"field": "layer", "type": "nominal", "label": "Input layer"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
            ]
        )
    if airline_period_backtest_views["airline_period_backtest_summary"]:
        charts.append(
            {
                "id": "airline_period_revenue_mae_chart",
                "title": "Airline H1 / H2 / FY KPI Calibration — Revenue MAE",
                "subtitle": "Strict source-recovered flat-RPK revenue MAE by carrier and reporting period. H2 financial actuals are FY minus H1; lower is better.",
                "type": "bar",
                "dataset": "airline_period_backtest_summary",
                "sourceId": "airline_period_kpi_backtest",
                "encodings": {
                    "x": {"field": "carrier", "type": "nominal", "label": "Airline"},
                    "y": {"field": "flat_rpk_revenue_mae_pct", "type": "quantitative", "label": "Revenue MAE (%)"},
                    "color": {"field": "period", "type": "nominal", "label": "Period"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )
    if airline_h1_backtest_views["airline_source_recovery_summary"]:
        charts.append(
            {
                "id": "airline_source_recovery_chart",
                "title": "Airline KPI Source-Recovery Audit",
                "subtitle": "Verified rows restored from cached official PDFs versus rows confirmed as not disclosed in the relevant source PDF.",
                "type": "bar",
                "dataset": "airline_source_recovery_summary",
                "sourceId": "airline_kpi_source_recovery",
                "encodings": {
                    "x": {"field": "status_label", "type": "nominal", "label": "Audit status"},
                    "y": {"field": "value", "type": "quantitative", "label": "Rows"},
                },
                "valueFormat": "number",
                "layout": "half",
            }
        )
    if airline_h1_backtest_views["airline_h1_revenue_nowcast_comparison"]:
        charts.extend(
            [
                {
                    "id": "airline_h1_revenue_nowcast_chart",
                    "title": "H1 2026 Revenue Nowcast — Spring / Juneyao",
                    "subtitle": "Current KPI-based flat-ASK baseline versus analyst yield/fuel/non-fuel overlay; USD million. This is a pre-report nowcast, not an actual result.",
                    "type": "bar",
                    "dataset": "airline_h1_revenue_nowcast_comparison",
                    "sourceId": "airline_h1_kpi_backtest",
                    "encodings": {
                        "x": {"field": "carrier", "type": "nominal", "label": "Airline"},
                        "y": {"field": "value_usd_mn", "type": "quantitative", "label": "Revenue (USD mn)"},
                        "color": {"field": "view", "type": "nominal", "label": "Nowcast view"},
                    },
                    "valueFormat": "number",
                    "layout": "half",
                },
                {
                    "id": "airline_h1_profit_nowcast_chart",
                    "title": "H1 2026 Profit Nowcast — Spring / Juneyao",
                    "subtitle": "Current KPI-based flat-ASK baseline versus analyst overlay; USD million. Compare with the later formal interim result when released.",
                    "type": "bar",
                    "dataset": "airline_h1_profit_nowcast_comparison",
                    "sourceId": "airline_h1_kpi_backtest",
                    "encodings": {
                        "x": {"field": "carrier", "type": "nominal", "label": "Airline"},
                        "y": {"field": "value_usd_mn", "type": "quantitative", "label": "Profit (USD mn)"},
                        "color": {"field": "view", "type": "nominal", "label": "Nowcast view"},
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
                "title": "TD Metered Parking-Space Occupancy",
                "subtitle": "Observed occupancy rate across sensor-backed metered/on-street parking spaces. The chart remains hidden until repeated polls create a genuine time series; unmatched status rows are excluded from the denominator.",
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
    if airline_period_backtest_views["airline_period_backtest_summary"]:
        tables.append(
            {
                "id": "airline_period_backtest_summary_table",
                "title": "Airline H1 / H2 / FY KPI Calibration Summary",
                "subtitle": "Strict source-recovered calibration, with logical-assumption coverage shown separately. H2 financial actuals are derived as FY minus H1; this is calibration evidence, not a strict point-in-time trading backtest.",
                "dataset": "airline_period_backtest_summary",
                "sourceId": "airline_period_kpi_backtest",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "carrier", "label": "Airline", "type": "text"},
                    {"field": "period", "label": "Period", "type": "text"},
                    {"field": "historical_evaluated_rows", "label": "Strict rows", "format": "number"},
                    {"field": "pit_safe_evaluated_rows", "label": "PIT-safe rows", "format": "number"},
                    {"field": "logical_assumption_rows", "label": "Logical-assumption rows", "format": "number"},
                    {"field": "flat_ask_revenue_mae_pct", "label": "Flat-ASK revenue MAE (%)", "format": "number"},
                    {"field": "flat_rpk_revenue_mae_pct", "label": "Flat-RPK revenue MAE (%)", "format": "number"},
                    {"field": "recovery_case_revenue_mae_pct", "label": "Spring recovery-case MAE (%)", "format": "number"},
                    {"field": "flat_ask_cost_mae_pct", "label": "Flat-ASK cost MAE (%)", "format": "number"},
                ],
            }
        )
    if airline_h1_backtest_views["airline_source_recovery_audit"]:
        tables.append(
            {
                "id": "airline_source_recovery_audit_table",
                "title": "Airline KPI Source-Recovery Audit Detail",
                "subtitle": "Official-PDF recoveries and verified non-disclosures. The monthly operating charts use the source-recovered layer; this table records the evidence behind the overlay.",
                "dataset": "airline_source_recovery_audit",
                "sourceId": "airline_kpi_source_recovery",
                "density": "dense",
                "layout": "full",
                "maxRows": 200,
                "columns": [
                    {"field": "status", "label": "Status", "type": "text"},
                    {"field": "airline_code", "label": "Airline code", "type": "text"},
                    {"field": "month", "label": "Month", "type": "text"},
                    {"field": "metric", "label": "Metric", "type": "text"},
                    {"field": "region", "label": "Region", "type": "text"},
                    {"field": "value", "label": "Value", "format": "number"},
                    {"field": "recovery_method", "label": "Recovery method", "type": "text"},
                    {"field": "reason", "label": "Reason", "type": "text"},
                    {"field": "announcement_date", "label": "Announcement date", "type": "text"},
                    {"field": "source_pdf_url", "label": "Official PDF", "type": "url"},
                    {"field": "companion_parser_metrics", "label": "Companion parser metrics", "type": "text"},
                    {"field": "source_text_metric_present", "label": "Metric in source text", "type": "text"},
                    {"field": "source_text_keyword_matches", "label": "Source keyword matches", "type": "text"},
                    {"field": "parser_metric_present", "label": "Metric parsed", "type": "text"},
                    {"field": "parser_metric_row_count", "label": "Parsed row count", "format": "number"},
                    {"field": "parser_metric_regions", "label": "Parsed regions", "type": "text"},
                    {"field": "disclosure_check", "label": "Disclosure check", "type": "text"},
                ],
            }
        )
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
                    {"field": "reporting_scope", "label": "Reporting scope", "type": "text"},
                    {"field": "region", "label": "Region", "type": "text"},
                    {"field": "passengers", "label": "Passengers ('000s)", "format": "number"},
                    {"field": "ask", "label": "ASK ('000s)", "format": "number"},
                    {"field": "rpk", "label": "RPK ('000s)", "format": "number"},
                    {"field": "load_factor_pct", "label": "Load factor (%)", "format": "number"},
                ],
            }
        )
    if china_airline_views["china_airline_cargo_latest_snapshot"]:
        tables.append(
            {
                "id": "china_airline_cargo_latest_snapshot_table",
                "title": "China Listed Airlines Latest Cargo Snapshot",
                "subtitle": "Latest available month, using reported all-operation totals where available and normalized units across issuers.",
                "dataset": "china_airline_cargo_latest_snapshot",
                "sourceId": "china_airline_traffic",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "airline", "label": "Airline", "type": "text"},
                    {"field": "reporting_scope", "label": "Reporting scope", "type": "text"},
                    {"field": "cargo_tonnes", "label": "Cargo / mail (tonnes)", "format": "number"},
                    {"field": "aftk", "label": "AFTK (million tonne-km)", "format": "number"},
                    {"field": "rftk", "label": "RFTK (million tonne-km)", "format": "number"},
                    {"field": "freight_load_factor_pct", "label": "Freight load factor (%)", "format": "number"},
                    {"field": "overall_load_factor_pct", "label": "Overall load factor (%)", "format": "number"},
                ],
            }
        )
    if china_airline_views["china_airline_operating_events_latest"]:
        tables.append(
            {
                "id": "china_airline_operating_events_latest_table",
                "title": "China Listed Airlines Latest Fleet / Route Events",
                "subtitle": "Latest event rows found in the official monthly announcement; event details retain the extracted source phrase and are not a continuous operating series.",
                "dataset": "china_airline_operating_events_latest",
                "sourceId": "china_airline_traffic",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "airline", "label": "Airline", "type": "text"},
                    {"field": "reporting_scope", "label": "Reporting scope", "type": "text"},
                    {"field": "event_type", "label": "Event type", "type": "text"},
                    {"field": "value", "label": "Value", "format": "number"},
                    {"field": "detail", "label": "Source detail", "type": "text"},
                ],
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
                "title": "Metered Parking-Space Occupancy by District",
                "subtitle": "Latest observed occupancy by district for TD sensor-backed metered/on-street spaces.",
                "dataset": "td_carpark_occupancy_latest_district",
                "sourceId": "td_carpark_occupancy",
                "density": "dense",
                "layout": "full",
                "columns": [{"field": "summary", "label": "District Occupancy", "type": "text"}],
            }
        )

    # Keep the portable artifact within the renderer's dataset budget. The
    # research views above may produce helper datasets (for example a long
    # nowcast table or an unrendered auxiliary series), but only datasets that
    # are actually referenced by a card, chart or table belong in the public
    # snapshot. The source CSV/parquet remains the canonical research layer.
    referenced_dataset_ids = {
        item.get("dataset")
        for collection in (cards, charts, tables)
        for item in collection
        if item.get("dataset")
    }
    datasets = {
        dataset_id: rows
        for dataset_id, rows in datasets.items()
        if dataset_id in referenced_dataset_ids
    }

    sources = list(PUBLIC_SOURCES.values())

    def _latest_csv_date(frame: pd.DataFrame, column: str) -> str:
        if frame.empty or column not in frame.columns:
            return "1900-01-01"
        parsed = pd.to_datetime(frame[column], errors="coerce").dropna()
        return parsed.max().strftime("%Y-%m-%d") if not parsed.empty else "1900-01-01"

    source_recovery_as_of = _latest_csv_date(source_recovery_audit, "announcement_date")
    h1_backtest_as_of = _latest_csv_date(h1_backtest_comparison, "imputed_current_kpi_cutoff")
    period_year = pd.to_numeric(period_backtest_summary.get("historical_year_max"), errors="coerce").dropna()
    period_backtest_as_of = f"{int(period_year.max())}-12-31" if not period_year.empty else "1900-01-01"

    snapshot_id = hashlib.sha256(
        json.dumps(datasets, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]

    artifact = {
        "surface": "dashboard",
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "HK Transport & Aviation Sector Monitor",
            "description": "MTR Corporation monthly rail patronage, CAD HKIA airport traffic, Cathay Pacific Group operating statistics, China listed-airline operating data, TD public-transport and private-car series, C&SD cross-boundary movements, EV registrations and metered-space parking occupancy.",
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
                {"id": "cathay_cargo_tonnage_chart_block", "type": "chart", "chartId": "cathay_cargo_tonnage_chart", "layout": "half"},
                {"id": "cathay_freight_load_factor_chart_block", "type": "chart", "chartId": "cathay_freight_load_factor_chart", "layout": "half"},
                {"id": "cathay_cargo_capacity_demand_chart_block", "type": "chart", "chartId": "cathay_cargo_capacity_demand_chart", "layout": "half"},
                {"id": "cathay_flight_sectors_chart_block", "type": "chart", "chartId": "cathay_flight_sectors_chart"},
                *(
                    [{"id": "cathay_fleet_total_chart_block", "type": "chart", "chartId": "cathay_fleet_total_chart"}]
                    if cathay_fleet_total_history
                    else []
                ),
                {"id": "hkia_passengers_chart_block", "type": "chart", "chartId": "hkia_passengers_chart"},
                {"id": "china_airline_passengers_chart_block", "type": "chart", "chartId": "china_airline_passengers_chart"},
                {"id": "china_airline_ask_chart_block", "type": "chart", "chartId": "china_airline_ask_chart", "layout": "half"},
                {"id": "china_airline_rpk_chart_block", "type": "chart", "chartId": "china_airline_rpk_chart", "layout": "half"},
                {"id": "china_airline_load_factor_chart_block", "type": "chart", "chartId": "china_airline_load_factor_chart", "layout": "half"},
                {"id": "china_airline_region_split_chart_block", "type": "chart", "chartId": "china_airline_region_split_chart", "layout": "half"},
                {"id": "china_airline_cargo_chart_block", "type": "chart", "chartId": "china_airline_cargo_chart", "layout": "half"},
                {"id": "china_airline_freight_load_factor_chart_block", "type": "chart", "chartId": "china_airline_freight_load_factor_chart", "layout": "half"},
                {"id": "china_airline_snapshot_table_block", "type": "table", "tableId": "china_airline_latest_snapshot_table"},
                {"id": "china_airline_cargo_snapshot_table_block", "type": "table", "tableId": "china_airline_cargo_latest_snapshot_table"},
                *(
                    [
                        {"id": "china_airline_fleet_total_chart_block", "type": "chart", "chartId": "china_airline_fleet_total_chart"},
                        {"id": "china_airline_fleet_net_change_chart_block", "type": "chart", "chartId": "china_airline_fleet_net_change_chart", "layout": "half"},
                        {"id": "china_airline_new_route_chart_block", "type": "chart", "chartId": "china_airline_new_route_chart", "layout": "half"},
                    ]
                    if china_airline_views["china_airline_fleet_total_history"]
                    else []
                ),
                *(
                    [{"id": "china_airline_operating_events_latest_table_block", "type": "table", "tableId": "china_airline_operating_events_latest_table"}]
                    if china_airline_views["china_airline_operating_events_latest"]
                    else []
                ),
                *(
                    [
                        {"id": "airline_h1_revenue_mae_chart_block", "type": "chart", "chartId": "airline_h1_revenue_mae_chart", "layout": "half"},
                        {"id": "airline_h1_cost_mae_chart_block", "type": "chart", "chartId": "airline_h1_cost_mae_chart", "layout": "half"},
                    ]
                    if airline_h1_backtest_views["airline_h1_revenue_mae_comparison"]
                    else []
                ),
                *(
                    [{"id": "airline_source_recovery_chart_block", "type": "chart", "chartId": "airline_source_recovery_chart", "layout": "half"}]
                    if airline_h1_backtest_views["airline_source_recovery_summary"]
                    else []
                ),
                *(
                    [{"id": "airline_period_revenue_mae_chart_block", "type": "chart", "chartId": "airline_period_revenue_mae_chart"}]
                    if airline_period_backtest_views["airline_period_backtest_summary"]
                    else []
                ),
                *(
                    [
                        {"id": "airline_h1_revenue_nowcast_chart_block", "type": "chart", "chartId": "airline_h1_revenue_nowcast_chart", "layout": "half"},
                        {"id": "airline_h1_profit_nowcast_chart_block", "type": "chart", "chartId": "airline_h1_profit_nowcast_chart", "layout": "half"},
                    ]
                    if airline_h1_backtest_views["airline_h1_revenue_nowcast_comparison"]
                    else []
                ),
                *(
                    [{"id": "airline_period_backtest_summary_table_block", "type": "table", "tableId": "airline_period_backtest_summary_table"}]
                    if airline_period_backtest_views["airline_period_backtest_summary"]
                    else []
                ),
                *(
                    [{"id": "airline_source_recovery_audit_table_block", "type": "table", "tableId": "airline_source_recovery_audit_table"}]
                    if airline_h1_backtest_views["airline_source_recovery_audit"]
                    else []
                ),
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
                cathay_fleet["date"].max().strftime("%Y-%m-%d") if not cathay_fleet.empty else "1900-01-01",
                china_airline["date"].max().strftime("%Y-%m-%d") if not china_airline.empty else "1900-01-01",
                source_recovery_as_of,
                h1_backtest_as_of,
                period_backtest_as_of,
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
        "cathay_fleet": len(cathay_fleet),
        "china_airline_traffic": len(china_airline) + len(china_airline_events),
        "airline_kpi_source_recovery": len(source_recovery_audit),
        "airline_h1_kpi_backtest": len(h1_backtest_comparison),
        "airline_period_kpi_backtest": len(period_backtest_summary),
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
        "cathay_fleet": cathay_fleet["date"].max().strftime("%Y-%m-%d") if not cathay_fleet.empty else "—",
        "china_airline_traffic": china_airline["date"].max().strftime("%Y-%m-%d") if not china_airline.empty else "—",
        "airline_kpi_source_recovery": source_recovery_as_of if source_recovery_as_of != "1900-01-01" else "—",
        "airline_h1_kpi_backtest": h1_backtest_as_of if h1_backtest_as_of != "1900-01-01" else "—",
        "airline_period_kpi_backtest": period_backtest_as_of if period_backtest_as_of != "1900-01-01" else "—",
        "hk_passenger_journeys": passenger_journeys["date"].max().strftime("%Y-%m-%d") if not passenger_journeys.empty else "—",
        "mttd_passenger_journeys": mttd_passenger_journeys["date"].max().strftime("%Y-%m-%d") if not mttd_passenger_journeys.empty else "—",
        "censtatd_boundary_movements": boundary_movements["date"].max().strftime("%Y-%m-%d") if not boundary_movements.empty else "—",
        "hk_vehicle_stock": vehicle_stock["date"].max().strftime("%Y-%m-%d") if not vehicle_stock.empty else "—",
        "hk_private_car_net_growth": net_growth["date"].max().strftime("%Y-%m-%d") if not net_growth.empty else "—",
        "hk_private_car_first_reg": private_car_first_reg["date"].max().strftime("%Y-%m-%d") if not private_car_first_reg.empty else "—",
        "hk_private_car_first_reg_details": private_car_first_reg_models["observation_date"].max().strftime("%Y-%m-%d") if not private_car_first_reg_models.empty else "—",
        "td_parking_vacancy": parking_views["hk_parking_vacancy_history"][-1]["date"] if parking_views["hk_parking_vacancy_history"] else "—",
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
    freshness["td_carpark_occupancy"] = "Live snapshot at build time" if record_counts["td_carpark_occupancy"] else "Metered-space status unavailable"
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
    args.output.write_text(json.dumps(artifact, separators=(",", ":"), default=str), encoding="utf-8")
    args.status_output.write_text(json.dumps(status, separators=(",", ":"), default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "artifact": str(args.output), "snapshot_id": status["snapshot_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
