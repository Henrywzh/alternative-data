"""Configuration constants for HK Transport Sector Pipeline."""

from __future__ import annotations

from pathlib import Path

DEFAULT_TIMEOUT = 15
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# MTR Corporation Investor Relations Patronage URL
MTR_PATRONAGE_URL = "https://www.mtr.com.hk/en/corporate/investor/patronage.php"

# Civil Aviation Department (CAD) HKIA Monthly Airport Traffic Excel Workbook
CAD_HKIA_XLSX_URL = "https://www.cad.gov.hk/english/pdf/Stat%20Webpage.xlsx"

# Transport Department monthly private-car first-registration breakdown by
# make, fuel type and body type. The source has a genuine monthly history.
TD_PRIVATE_CAR_FIRST_REG_URL = "https://www.td.gov.hk/datagovhk_tis/mttd-csv/en/table41e_eng.csv"

# Transport Department Table 4.1(a): monthly private-car fleet stock by fuel
# type. The workbook is refreshed as part of the monthly traffic digest.
TD_VEHICLE_FLEET_STOCK_URL = "https://www.td.gov.hk/filemanager/en/content_4883/table41a.xls"

# Transport Department Table 4.1(c): private-car gross registrations,
# deregistrations and net first-registration growth.
TD_PRIVATE_CAR_NET_REGISTRATION_URL = "https://www.td.gov.hk/filemanager/en/content_4884/table41c.xls"

# Transport Department Monthly Traffic and Transport Digest Table 2.3.
MTTD_PASSENGER_JOURNEYS_URL = "https://www.td.gov.hk/datagovhk_tis/mttd-csv/en/table23_eng.csv"
CENSTATD_BOUNDARY_REPORT_INDEX_URL = (
    "https://www.censtatd.gov.hk/en/data/stat_report/subject/340/report_index.json"
)
CENSTATD_BOUNDARY_PRODUCT_URL = (
    "https://www.censtatd.gov.hk/en/data/stat_report/product/D7000005/att/{filename}"
)

# Transport Department's latest per-vehicle first-registration detail feed.
# The month is substituted as a lowercase English abbreviation (for example,
# ``jun``) by the source module, which walks backwards until a published CSV
# is found.
TD_FIRST_REGISTERED_VEHICLE_URL_TEMPLATE = (
    "https://www.td.gov.hk/datagovhk_td/first-reg-vehicle/resources/en/"
    "particulars_of_first_registered_vehicle_{month}_{year}_eng.csv"
)
TD_FIRST_REGISTERED_VEHICLE_INDEX_URL = (
    "https://www.td.gov.hk/en/public_services/licences_and_permits/vehicle_first_registration/"
    "vehicle_particulars/index.html"
)

# Transport Department online parking-vacancy feeds. Vacancy is a current
# operational snapshot; the collection script appends snapshots to a local
# parquet history so the dashboard can show a genuine time series once runs
# accumulate.
TD_PARKING_VACANCY_URL = "https://resource.data.one.gov.hk/td/carpark/vacancy_all.json"
TD_PARKING_BASIC_INFO_URL = "https://resource.data.one.gov.hk/td/carpark/basic_info_all.json"
# TD metered/on-street parking-space inventory and live sensor status. Unlike
# the 548-car-park vacancy feed above, this pair exposes a real denominator:
# the inventory is the listed space universe and the status CSV marks each
# observed space occupied (O) or vacant (V).
TD_METERED_PARKING_SPACES_URL = (
    "https://portal.csdi.gov.hk/csdi-webpage/file-api?"
    "dataset_id=td_rcd_1638930345315_81787&format=geojson&layer_name=parkingspaces"
)
TD_METERED_PARKING_OCCUPANCY_URL = (
    "https://resource.data.one.gov.hk/td/psiparkingspaces/occupancystatus/occupancystatus.csv"
)

# Data Storage directories
ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "data" / "raw" / "hk_transport"
NORMALIZED_DIR = ROOT_DIR / "data" / "normalized" / "hk_transport"
RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
