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

# Keep the H-share code in the same four-digit display form across all
# research layers.  Some upstream public pages historically emitted 00670.HK
# for China Eastern; the canonical market/bridge key is 0670.HK.
AIRLINE_TICKER_ALIASES = {
    "00670.HK": "0670.HK",
    "00670.HK / 600115.SH": "0670.HK / 600115.SH",
}

# MTR Corporation Investor Relations Patronage URL
MTR_PATRONAGE_URL = "https://www.mtr.com.hk/en/corporate/investor/patronage.php"

# EIA publishes the same spot-price workbook at daily and weekly frequency.
# The workbook is free to download and includes WTI, Brent and U.S. Gulf Coast
# kerosene-type jet fuel.  It is a transparent benchmark for airline cost
# shocks; company accounting cost still requires fuel volume, hedging and lag
# adjustments from issuer disclosures.
EIA_SPOT_PRICES_URLS = {
    "daily": "https://www.eia.gov/dnav/pet/xls/PET_PRI_SPT_S1_D.xls",
    "weekly": "https://www.eia.gov/dnav/pet/xls/PET_PRI_SPT_S1_W.xls",
}

# MOFCOM Data Center's open monthly goods-trade page exposes a free JSON
# endpoint used as a broad cargo/trade-cycle proxy for airline research.  The
# endpoint does not expose an announcement vintage, so the source module keeps
# retrieval date and explicitly labels the data as a latest-snapshot series.
MOFCOM_MONTHLY_TRADE_PAGE_URL = "https://data.mofcom.gov.cn/hwmy/imexmonth.shtml"
MOFCOM_MONTHLY_TRADE_QUERY_URL = (
    "https://data.mofcom.gov.cn/datamofcom/front/totalmonth/query"
)

# State Post Bureau official national postal/express operating-statistics
# articles. These are cumulative and latest-month snapshots rather than an
# airline cargo series; the source module preserves article dates and scope.
SPB_STATS_INDEX_URL = "https://www.spb.gov.cn/gjyzj/c100276/common_list.shtml"
SPB_2026_JAN_APR_URL = (
    "https://www.spb.gov.cn/gjyzj/c100015/c100016/202605/"
    "37b00bd92ee94f59b15a17f1d803eb84.shtml"
)
SPB_2026_H1_URL = (
    "https://www.spb.gov.cn/gjyzj/c100015/c100016/202607/"
    "a31abbec99be4e0d80188b1a25fe1fe6.shtml"
)
SPB_2025_H1_URL = (
    "https://www.spb.gov.cn/gjyzj/c100015/c100016/202507/"
    "433736ca3a9043b5a8b5e8bef1d9c4ed.shtml"
)

# Official holiday/travel demand control articles.  These are low-frequency
# event observations, not monthly airline traffic.  Keep each URL as a dated
# source so model cutoffs can exclude articles published later than the
# as-of-date.
MOT_2026_SPRING_TRANSPORT_URL = (
    "https://www.mot.gov.cn/zhuanti/2026chunyun/gongzuobushu/202603/"
    "t20260316_4201910.html"
)
MCT_2026_SPRING_TOURISM_URL = (
    "https://mct.gov.cn/whzx/whyw/202602/t20260224_964790.htm"
)
MCT_2026_MAY_TOURISM_URL = (
    "https://www.mct.gov.cn/whzx/whyw/202605/t20260506_965708.htm"
)
MCT_2026_DRAGON_BOAT_TOURISM_URL = (
    "https://www.mct.gov.cn/wlbphone/wlbydd/xxfb/jiaodianxinwen/202606/"
    "t20260622_966305.html"
)
MCT_2025_MAY_TOURISM_URL = (
    "https://www.mct.gov.cn/whzx/whyw/202505/t20250506_959793.htm"
)

# CAAC's public monthly transport-statistics index and the linked PDF reports.
# The index is used to discover the current month/announcement/PDF URL rather
# than hard-coding one attachment ID in the model layer.
CAAC_MONTHLY_KPI_INDEX_URL = (
    "https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/TJSJ_1/"
)
CAAC_ENGLISH_MONTHLY_KPI_INDEX_URL_TEMPLATE = (
    "https://www.caac.gov.cn/English/Research/Data/KPIS/{year}year/"
)
CAAC_CHINESE_MONTHLY_KPI_LIST_URL = (
    "https://www.caac.gov.cn/XXGK/XXGK/TJSJ/index_1215.html"
)
# CAAC public summer/autumn 2026 domestic route-licence table.  This is a
# dated planned-supply event document, not an actual-flight or realized-ASK
# feed.  Keep the URL in configuration so a later season can be added as a
# separate vintage rather than overwriting this one.
CAAC_2026_SUMMER_ROUTE_LICENCE_URL = (
    "https://www.caac.gov.cn/XXGK/XXGK/TZTG/202603/"
    "P020260323513975216641.pdf"
)

# Issuer monthly production-statistics bulletins on CNINFO. These are the
# same primary-issuer PDFs used by the airport operators for monthly traffic
# disclosure; keep announcement URLs in configuration so each month can be
# added as a separate dated vintage.
SHA_2026_06_TRAFFIC_URL = (
    "https://static.cninfo.com.cn/finalpage/2026-07-15/1225422839.PDF"
)
SZX_2026_05_TRAFFIC_URL = (
    "https://static.cninfo.com.cn/finalpage/2026-06-13/1225367315.PDF"
)
SZX_2026_06_TRAFFIC_URL = (
    "https://static.cninfo.com.cn/finalpage/2026-07-10/1225416741.PDF"
)
CAN_2026_05_TRAFFIC_URL = (
    "https://static.cninfo.com.cn/finalpage/2026-06-16/1225371938.PDF"
)
CAN_2026_06_TRAFFIC_URL = (
    "https://static.cninfo.com.cn/finalpage/2026-07-15/1225423217.PDF"
)

# Beijing Capital International Airport (00694.HK) publishes a monthly
# operating-data fast report on its investor-relations page with an explicit
# release date.  These are the six H1-2026 monthly Chinese-language PDFs.
BCIA_TRAFFIC_URLS = {
    "2026-01": (
        "http://www.bcia.com.cn/userfiles/files/article/images/2026/02/"
        "2026_Jan_Traffic_Data_Chi.pdf"
    ),
    "2026-02": (
        "http://www.bcia.com.cn/userfiles/files/article/images/2026/03/"
        "Feb_Traffic_Data_Chi_2026.pdf"
    ),
    "2026-03": (
        "http://www.bcia.com.cn/userfiles/files/article/images/2026/04/"
        "Mar_Traffic_Data_Chi_2026.pdf"
    ),
    "2026-04": (
        "http://www.bcia.com.cn/userfiles/files/article/images/2026/05/"
        "April_Traffic_Data_Chi_2026.pdf"
    ),
    "2026-05": (
        "http://www.bcia.com.cn/userfiles/files/article/images/2026/06/"
        "May_Traffic_Data_C_2026.pdf"
    ),
    "2026-06": (
        "http://www.bcia.com.cn/userfiles/files/article/images/2026/07/"
        "202606_Traffic_Data_Chi.pdf"
    ),
}

# Official release dates for each BCIA monthly fast report (first line of the
# PDF: "实时发布 YYYY年M月D日").  Kept in configuration as dated vintages so a
# future month is added as a new dated source rather than overwriting history.
BCIA_TRAFFIC_RELEASE_DATES = {
    "2026-01": "2026-02-10",
    "2026-02": "2026-03-10",
    "2026-03": "2026-04-09",
    "2026-04": "2026-05-09",
    "2026-05": "2026-06-09",
    "2026-06": "2026-07-08",
}

# ECB daily reference rates are free and cover the reporting currencies needed
# to translate USD fuel benchmarks into CNY and HKD.  The parser derives the
# cross rates from the same-day EUR reference observations.
ECB_REFERENCE_RATES_URL = (
    "https://data-api.ecb.europa.eu/service/data/EXR/"
    "D.USD+CNY+HKD.EUR.SP00.A?format=csvdata"
)

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
AIRLINE_REPORTS_DIR = ROOT_DIR / "data" / "raw" / "airline_reports"
RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
AIRLINE_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
