"""Official and industry sector-level airline outlook observations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR


OUTPUT_PATH = NORMALIZED_DIR / "airline_sector_external_outlook.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "source_organization", "source_document_date", "source_document_type",
    "source_url", "outlook_vintage", "period", "scope", "metric", "value", "unit",
    "status", "source_quality", "source_note", "retrieved_at",
]


# Curated from public IATA/CAAC publications.  These are deliberately kept as
# separate dated observations: later outlook vintages are not overwritten by
# newer numbers, and actuals/schedules are not mixed with forecasts.
OUTLOOK_ROWS = [
    {
        "source_organization": "IATA", "source_document_date": "2025-12-09",
        "source_document_type": "industry_profitability_outlook",
        "source_url": "https://www.iata.org/en/pressroom/2025-releases/2025-12-09-01/",
        "outlook_vintage": "2025-12-09", "period": "2026", "scope": "Asia Pacific",
        "metric": "passenger_demand_rpk_growth", "value": 7.3, "unit": "% YoY",
        "status": "forecast", "source_quality": "iata_primary",
        "source_note": "IATA 2026 Asia-Pacific outlook; retain as a dated forecast vintage.",
    },
    {
        "source_organization": "IATA", "source_document_date": "2025-12-09",
        "source_document_type": "industry_profitability_outlook",
        "source_url": "https://www.iata.org/en/pressroom/2025-releases/2025-12-09-01/",
        "outlook_vintage": "2025-12-09", "period": "2026", "scope": "Asia Pacific",
        "metric": "capacity_ask_growth", "value": 7.1, "unit": "% YoY",
        "status": "forecast", "source_quality": "iata_primary",
        "source_note": "IATA 2026 Asia-Pacific outlook; retain as a dated forecast vintage.",
    },
    {
        "source_organization": "IATA", "source_document_date": "2025-12-09",
        "source_document_type": "industry_profitability_outlook",
        "source_url": "https://www.iata.org/en/pressroom/2025-releases/2025-12-09-01/",
        "outlook_vintage": "2025-12-09", "period": "2026", "scope": "Asia Pacific",
        "metric": "net_profit", "value": 6.6, "unit": "USD billion",
        "status": "forecast", "source_quality": "iata_primary",
        "source_note": "IATA 2026 Asia-Pacific profitability outlook.",
    },
    {
        "source_organization": "IATA", "source_document_date": "2025-12-09",
        "source_document_type": "industry_profitability_outlook",
        "source_url": "https://www.iata.org/en/pressroom/2025-releases/2025-12-09-01/",
        "outlook_vintage": "2025-12-09", "period": "2026", "scope": "Asia Pacific",
        "metric": "net_margin", "value": 2.3, "unit": "%",
        "status": "forecast", "source_quality": "iata_primary",
        "source_note": "IATA 2026 Asia-Pacific profitability outlook.",
    },
    {
        "source_organization": "IATA", "source_document_date": "2026-02-02",
        "source_document_type": "industry_outlook_speech",
        "source_url": "https://www.iata.org/en/pressroom/2026-speeches/2026-02-02-01/",
        "outlook_vintage": "2026-02-02", "period": "2026", "scope": "Global",
        "metric": "passenger_traffic_growth", "value": 4.9, "unit": "% YoY",
        "status": "forecast", "source_quality": "iata_primary",
        "source_note": "IATA speech outlook; metric is passenger traffic rather than RPK and is kept distinct.",
    },
    {
        "source_organization": "IATA", "source_document_date": "2026-02-02",
        "source_document_type": "industry_outlook_speech",
        "source_url": "https://www.iata.org/en/pressroom/2026-speeches/2026-02-02-01/",
        "outlook_vintage": "2026-02-02", "period": "2026", "scope": "Global",
        "metric": "cargo_traffic_growth", "value": 2.4, "unit": "% YoY",
        "status": "forecast", "source_quality": "iata_primary",
        "source_note": "IATA speech outlook; cargo traffic is kept separate from passenger RPK.",
    },
    {
        "source_organization": "IATA", "source_document_date": "2026-02-02",
        "source_document_type": "industry_outlook_speech",
        "source_url": "https://www.iata.org/en/pressroom/2026-speeches/2026-02-02-01/",
        "outlook_vintage": "2026-02-02", "period": "2026", "scope": "Asia Pacific",
        "metric": "passenger_traffic_growth", "value": 7.3, "unit": "% YoY",
        "status": "forecast", "source_quality": "iata_primary",
        "source_note": "IATA speech outlook for Asia-Pacific passenger traffic.",
    },
    {
        "source_organization": "IATA", "source_document_date": "2026-02-02",
        "source_document_type": "industry_outlook_speech",
        "source_url": "https://www.iata.org/en/pressroom/2026-speeches/2026-02-02-01/",
        "outlook_vintage": "2026-02-02", "period": "2026", "scope": "Asia Pacific",
        "metric": "cargo_traffic_growth", "value": 6.0, "unit": "% YoY",
        "status": "forecast", "source_quality": "iata_primary",
        "source_note": "IATA speech outlook for Asia-Pacific cargo traffic.",
    },
    {
        "source_organization": "IATA", "source_document_date": "2026-06-12",
        "source_document_type": "chart_of_the_week",
        "source_url": "https://www.iata.org/en/publications/economics/chart-week/chart-of-the-week-12-june-2026/",
        "outlook_vintage": "2026-06-12", "period": "2026", "scope": "Global",
        "metric": "passenger_demand_rpk_growth", "value": 2.1, "unit": "% YoY",
        "status": "forecast", "source_quality": "iata_primary",
        "source_note": "Later IATA global RPK outlook reflecting the energy/geopolitical shock; not directly interchangeable with passenger traffic growth.",
    },
    {
        "source_organization": "IATA", "source_document_date": "2026-03-31",
        "source_document_type": "quarterly_air_transport_chartbook",
        "source_url": "https://www.iata.org/en/iata-repository/publications/economic-reports/quarterly-air-transport-chartbook-q1-2026/",
        "outlook_vintage": "2026-03-31", "period": "2026Q1", "scope": "Asia Pacific",
        "metric": "passenger_demand_rpk_growth", "value": 7.4, "unit": "% YoY",
        "status": "actual", "source_quality": "iata_primary",
        "source_note": "IATA Q1 2026 Asia-Pacific actual RPK growth.",
    },
    {
        "source_organization": "IATA", "source_document_date": "2026-03-31",
        "source_document_type": "quarterly_air_transport_chartbook",
        "source_url": "https://www.iata.org/en/iata-repository/publications/economic-reports/quarterly-air-transport-chartbook-q1-2026/",
        "outlook_vintage": "2026-03-31", "period": "2026Q1", "scope": "Asia Pacific",
        "metric": "capacity_ask_growth", "value": 5.7, "unit": "% YoY",
        "status": "actual", "source_quality": "iata_primary",
        "source_note": "IATA Q1 2026 Asia-Pacific actual ASK growth.",
    },
    {
        "source_organization": "IATA", "source_document_date": "2026-03-31",
        "source_document_type": "quarterly_air_transport_chartbook",
        "source_url": "https://www.iata.org/en/iata-repository/publications/economic-reports/quarterly-air-transport-chartbook-q1-2026/",
        "outlook_vintage": "2026-03-31", "period": "2026Q1", "scope": "Asia Pacific",
        "metric": "cargo_demand_ctk_growth", "value": 8.9, "unit": "% YoY",
        "status": "actual", "source_quality": "iata_primary",
        "source_note": "IATA Q1 2026 Asia-Pacific actual CTK growth.",
    },
    {
        "source_organization": "IATA", "source_document_date": "2026-03-31",
        "source_document_type": "quarterly_air_transport_chartbook",
        "source_url": "https://www.iata.org/en/iata-repository/publications/economic-reports/quarterly-air-transport-chartbook-q1-2026/",
        "outlook_vintage": "2026-03-31", "period": "2026Q1", "scope": "Asia Pacific",
        "metric": "cargo_capacity_actk_growth", "value": 6.2, "unit": "% YoY",
        "status": "actual", "source_quality": "iata_primary",
        "source_note": "IATA Q1 2026 Asia-Pacific actual ACTK growth.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-03-31",
        "source_document_type": "seasonal_schedule",
        "source_url": "https://www.caac.gov.cn/English/News/202603/t20260331_230393.html",
        "outlook_vintage": "2026-03-31", "period": "2026_summer_schedule", "scope": "China",
        "metric": "planned_weekly_passenger_cargo_flights", "value": 121000, "unit": "flights/week",
        "status": "planned_schedule", "source_quality": "caac_primary",
        "source_note": "CAAC planned summer-season total passenger/cargo flights; not realized traffic.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-03-31",
        "source_document_type": "seasonal_schedule",
        "source_url": "https://www.caac.gov.cn/English/News/202603/t20260331_230393.html",
        "outlook_vintage": "2026-03-31", "period": "2026_summer_schedule", "scope": "China",
        "metric": "international_passenger_flights_growth", "value": 1.2, "unit": "% YoY",
        "status": "planned_schedule", "source_quality": "caac_primary",
        "source_note": "CAAC planned international passenger flights in the summer schedule.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-03-31",
        "source_document_type": "seasonal_schedule",
        "source_url": "https://www.caac.gov.cn/English/News/202603/t20260331_230393.html",
        "outlook_vintage": "2026-03-31", "period": "2026_summer_schedule", "scope": "China",
        "metric": "international_cargo_flights_growth", "value": 3.7, "unit": "% YoY",
        "status": "planned_schedule", "source_quality": "caac_primary",
        "source_note": "CAAC planned international cargo flights in the summer schedule.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-03-17",
        "source_document_type": "spring_festival_transport_actual",
        "source_url": "https://www.caac.gov.cn/English/News/202603/t20260317_230280.html",
        "outlook_vintage": "2026-03-17", "period": "2026_spring_festival", "scope": "China",
        "metric": "passenger_volume_growth", "value": 4.6, "unit": "% YoY",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC realized Spring Festival travel-rush passenger growth.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-02-27",
        "source_document_type": "annual_airport_statistics",
        "source_url": "https://www.caac.gov.cn/big5/www.caac.gov.cn/PHONE/XWZX/MHYW/202602/t20260227_230131.html",
        "outlook_vintage": "2026-02-27", "period": "2025", "scope": "China",
        "metric": "airport_passenger_throughput_growth", "value": 4.8, "unit": "% YoY",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC 2025 airport passenger-throughput growth; airport throughput is not airline RPK.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-02-27",
        "source_document_type": "annual_airport_statistics",
        "source_url": "https://www.caac.gov.cn/big5/www.caac.gov.cn/PHONE/XWZX/MHYW/202602/t20260227_230131.html",
        "outlook_vintage": "2026-02-27", "period": "2025", "scope": "China",
        "metric": "airport_cargo_throughput_growth", "value": 9.0, "unit": "% YoY",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC 2025 airport cargo/mail throughput growth; airport throughput is not airline CTK.",
    },
    # CAAC monthly operating statistics.  The attached table reports both the
    # current month and YTD; preserve the two periods separately rather than
    # annualising or blending them with issuer KPI rows.
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China",
        "metric": "transport_turnover", "value": 133.4, "unit": "亿吨公里",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; quick-report data, final data subject to annual report.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China",
        "metric": "passenger_volume", "value": 5727.0, "unit": "万人",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; quick-report data, final data subject to annual report.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China",
        "metric": "cargo_volume", "value": 88.8, "unit": "万吨",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; quick-report data, final data subject to annual report.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China",
        "metric": "passenger_rpk", "value": 1074.3, "unit": "亿人公里",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; RPK is sector-level passenger demand, not a listed-company KPI.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China",
        "metric": "cargo_ctk", "value": 38.3, "unit": "亿吨公里",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; CTK is sector-level cargo demand, not a listed-company KPI.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China",
        "metric": "aircraft_daily_utilization", "value": 8.2, "unit": "小时/日",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; sector-wide aircraft daily utilization.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China",
        "metric": "scheduled_passenger_load_factor", "value": 84.7, "unit": "%",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; scheduled passenger load factor.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China",
        "metric": "scheduled_cargo_load_factor", "value": 75.7, "unit": "%",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; scheduled cargo load factor.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China",
        "metric": "airport_passenger_throughput", "value": 11386.7, "unit": "万人次",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; airport throughput is not airline RPK.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China",
        "metric": "airport_cargo_throughput", "value": 189.6, "unit": "万吨",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; airport throughput is not airline CTK.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China",
        "metric": "flight_movements", "value": 92.6, "unit": "万架次",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; airport takeoffs/landings, not airline scheduled capacity.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China domestic",
        "metric": "passenger_volume", "value": 5098.8, "unit": "万人",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; domestic route passenger volume.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China international",
        "metric": "passenger_volume", "value": 628.1, "unit": "万人",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; international route passenger volume.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China domestic",
        "metric": "cargo_volume", "value": 48.1, "unit": "万吨",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; domestic route cargo volume.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China international",
        "metric": "cargo_volume", "value": 40.8, "unit": "万吨",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; international route cargo volume.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China domestic",
        "metric": "passenger_rpk", "value": 802.7, "unit": "亿人公里",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; domestic route passenger RPK.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China international",
        "metric": "passenger_rpk", "value": 271.6, "unit": "亿人公里",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; international route passenger RPK.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China domestic",
        "metric": "cargo_ctk", "value": 7.3, "unit": "亿吨公里",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; domestic route cargo CTK.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026-06", "scope": "China international",
        "metric": "cargo_ctk", "value": 30.9, "unit": "亿吨公里",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC June 2026 monthly production statistics; international route cargo CTK.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026H1", "scope": "China",
        "metric": "transport_turnover", "value": 833.7, "unit": "亿吨公里",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC January-June 2026 cumulative production statistics; quick-report data, final data subject to annual report.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026H1", "scope": "China",
        "metric": "passenger_volume", "value": 37552.4, "unit": "万人",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC January-June 2026 cumulative production statistics; quick-report data, final data subject to annual report.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026H1", "scope": "China",
        "metric": "cargo_volume", "value": 507.3, "unit": "万吨",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC January-June 2026 cumulative production statistics; quick-report data, final data subject to annual report.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026H1", "scope": "China",
        "metric": "passenger_rpk", "value": 6998.8, "unit": "亿人公里",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC January-June 2026 cumulative production statistics; quick-report data, final data subject to annual report.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026H1", "scope": "China",
        "metric": "cargo_ctk", "value": 218.6, "unit": "亿吨公里",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC January-June 2026 cumulative production statistics; quick-report data, final data subject to annual report.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026H1", "scope": "China",
        "metric": "aircraft_daily_utilization", "value": 8.9, "unit": "小时/日",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC January-June 2026 cumulative production statistics; quick-report data, final data subject to annual report.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026H1", "scope": "China",
        "metric": "scheduled_passenger_load_factor", "value": 85.7, "unit": "%",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC January-June 2026 cumulative production statistics; quick-report data, final data subject to annual report.",
    },
    {
        "source_organization": "CAAC", "source_document_date": "2026-07-21",
        "source_document_type": "monthly_operating_statistics",
        "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
        "outlook_vintage": "2026-07-21", "period": "2026H1", "scope": "China",
        "metric": "scheduled_cargo_load_factor", "value": 74.0, "unit": "%",
        "status": "actual", "source_quality": "caac_primary",
        "source_note": "CAAC January-June 2026 cumulative production statistics; quick-report data, final data subject to annual report.",
    },
]


# Preserve the change columns from the same official table separately from
# levels.  This is what allows the sector layer to test whether demand is
# keeping up with capacity/utilization rather than comparing unlike units.
CAAC_MONTHLY_CHANGE_ROWS = [
    ("2026-06", "transport_turnover_yoy", 0.2),
    ("2026-06", "passenger_volume_yoy", -6.5),
    ("2026-06", "cargo_volume_yoy", 0.4),
    ("2026-06", "passenger_rpk_yoy", -3.3),
    ("2026-06", "cargo_ctk_yoy", 9.2),
    ("2026-06", "aircraft_daily_utilization_yoy", -0.6),
    ("2026-06", "scheduled_passenger_load_factor_change_pp", 0.0),
    ("2026-06", "scheduled_cargo_load_factor_change_pp", 0.8),
    ("2026H1", "transport_turnover_yoy", 6.4),
    ("2026H1", "passenger_volume_yoy", 1.0),
    ("2026H1", "cargo_volume_yoy", 6.0),
    ("2026H1", "passenger_rpk_yoy", 4.3),
    ("2026H1", "cargo_ctk_yoy", 12.8),
    ("2026H1", "aircraft_daily_utilization_yoy", -0.1),
    ("2026H1", "scheduled_passenger_load_factor_change_pp", 1.6),
    ("2026H1", "scheduled_cargo_load_factor_change_pp", 1.4),
]


def build_airline_sector_external_outlook(*, retrieved_at: str | None = None) -> pd.DataFrame:
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows = [{"dataset_id": "airline_sector_external_outlook", **row, "retrieved_at": retrieved} for row in OUTLOOK_ROWS]
    for period, metric, value in CAAC_MONTHLY_CHANGE_ROWS:
        unit = "percentage points" if metric.endswith("_change_pp") else "% YoY"
        rows.append({
            "dataset_id": "airline_sector_external_outlook",
            "source_organization": "CAAC",
            "source_document_date": "2026-07-21",
            "source_document_type": "monthly_operating_statistics",
            "source_url": "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html",
            "outlook_vintage": "2026-07-21",
            "period": period,
            "scope": "China",
            "metric": metric,
            "value": value,
            "unit": unit,
            "status": "actual",
            "source_quality": "caac_primary",
            "source_note": (
                "CAAC June 2026 monthly production statistics; official table's "
                "month/YTD change column; quick-report data, final data subject to annual report."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_sector_external_outlook() -> pd.DataFrame:
    result = build_airline_sector_external_outlook()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
