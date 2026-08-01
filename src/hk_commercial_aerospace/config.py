"""Configuration constants for HK Commercial Aerospace Sector Pipeline."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_TIMEOUT = 15
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# Data Storage directories
ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "data" / "raw" / "hk_commercial_aerospace"
NORMALIZED_DIR = ROOT_DIR / "data" / "normalized" / "hk_commercial_aerospace"
RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)

# APIs
LAUNCH_LIBRARY_BASE = "https://ll.thespacedevs.com/2.2.0"
LL2_MAX_REQUESTS_PER_HOUR = 15

SSE_SOAQUERY_URL = "https://query.sse.com.cn/commonSoaQuery.do"
SSE_REFERER = "https://www.sse.com.cn/"

CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php"
CELESTRAK_SATCAT_URL = "https://celestrak.org/pub/satcat.csv"
GOOGLE_PATENTS_URL = "https://patents.google.com/xhr/query"
SZSE_PROJECT_API_URL = "https://listing.szse.cn/api/ras/projectrends/query"
FAA_COMMERCIAL_SPACE_NUMBERS_URL = "https://www.faa.gov/node/52196"
USASPENDING_SPENDING_BY_AWARD_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
OWID_OBJECTS_LAUNCHED_URL = (
    "https://ourworldindata.org/grapher/"
    "yearly-number-of-objects-launched-into-outer-space.csv"
    "?v=1&csvType=full&useColumnShortNames=false"
)
WIKIMEDIA_PAGEVIEWS_API_BASE = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
)
WIKIMEDIA_PAGEVIEWS_START_DATE = "20150701"
WIKIMEDIA_PAGEVIEWS_AGENTS = ("user", "spider", "automated", "all-agents")
WIKIMEDIA_PAGEVIEWS_PROJECT = "en.wikipedia.org"
WIKIMEDIA_PAGEVIEWS_REQUEST_DELAY_SECONDS = 0.75

# Keep the first aerospace attention basket small and explicit. Massviews is
# used for discovery, but a curated page list is the stable production
# contract: Wikipedia categories mix companies, laws, missions and unrelated
# historical pages.
WIKIMEDIA_AEROSPACE_PAGES = (
    {"page_id": "spacex", "title": "SpaceX", "label": "SpaceX", "topic_group": "Company"},
    {"page_id": "starlink", "title": "Starlink", "label": "Starlink", "topic_group": "Constellation"},
    {"page_id": "rocket_lab", "title": "Rocket Lab", "label": "Rocket Lab", "topic_group": "Company"},
    {"page_id": "falcon_9", "title": "Falcon 9", "label": "Falcon 9", "topic_group": "Rocket"},
    {"page_id": "new_glenn", "title": "New Glenn", "label": "New Glenn", "topic_group": "Rocket"},
    {"page_id": "long_march", "title": "Long March (rocket family)", "label": "Long March", "topic_group": "Rocket"},
    {"page_id": "chinese_space_program", "title": "Chinese space program", "label": "Chinese space program", "topic_group": "China"},
    {"page_id": "satellite_constellation", "title": "Satellite constellation", "label": "Satellite constellation", "topic_group": "Constellation"},
    {"page_id": "commercial_spaceflight", "title": "Commercial spaceflight", "label": "Commercial spaceflight", "topic_group": "Industry"},
)
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "AsiaMarketsData/1.0")

# Constants
HK_AEROSPACE_WATCHLIST = {
    "00031": "China Aerospace International Holdings (航天控股)",
    "00232": "Continental Aerospace Technologies (大陆航空科技控股)",
    "01045": "APT Satellite (亚太卫星)",
    "02357": "AVIC Aviation Industry (中航科工)",
    "02507": "Cirrus Aircraft (西锐)",
    "06613": "Lens Technology (蓝思科技)",
    "02208": "Goldwind (金风科技) [NOTE: sector tag says environmental engineering, not aerospace — verify before treating as core]",
    "07688": "Topu CNC (拓璞数控)",
    "02865": "Junda Co. (钧达股份) [NOTE: sector tag says new energy materials, not aerospace — verify before treating as core]",
}

IPO_RACE_COMPANIES = [
    {"name_en": "LandSpace", "name_zh": "蓝箭航天", "audit_num": 2174, "known_status": "已问询", "update_date": "2026-06-29"},
    {"name_en": "CAS Space", "name_zh": "中科宇航", "audit_num": 2180, "known_status": "已问询", "update_date": "2026-06-29"},
    {"name_en": "Galactic Energy", "name_zh": "星河动力", "audit_num": None, "known_status": "no_shanghai_filing", "update_date": None},
    {"name_en": "Space Pioneer", "name_zh": "天兵科技", "audit_num": None, "known_status": "no_shanghai_filing", "update_date": None},
    {"name_en": "i-Space", "name_zh": "星际荣耀", "audit_num": None, "known_status": "no_shanghai_filing", "update_date": None},
]

SATELLITE_CONSTELLATIONS = {
    "qianfan": {"param": "GROUP=qianfan", "operator": "Shanghai Spacecom Satellite Technology"},
    "jilin1": {"param": "NAME=JILIN", "operator": "Chang Guang Satellite Technology"},
}

GUOWANG_GAP_REASON = "Guowang/国网 (SatNet) has no confirmed Celestrak GROUP or NAME string — tried guowang, SATNET, SATNET GROUP, GW- (all failed). Current hypothesis: satellites cataloged under generic international designators. Cross-reference against Launch Library 2 mission data needed. Not a blocker."

CHINESE_LAUNCH_AGENCIES = [
    "LandSpace",
    "Galactic Energy",
    "CAS Space",
    "Orienspace",
    "Deep Blue Aerospace",
    "i-Space",
    "Space Pioneer",
]

# Stable Launch Library 2 agency IDs. These are used instead of the broad
# `search=` parameter, which searches mission names and payload text too.
CHINESE_LAUNCH_AGENCY_IDS = {
    "LandSpace": 259,
    "Galactic Energy": 1021,
    "CAS Space": 1040,
    "Orienspace": 1080,
    "Deep Blue Aerospace": 1102,
    "i-Space": 274,
    "Space Pioneer": 1049,
}

# Launch Library 2 provider IDs used only to enrich the first-party national
# baseline. They are intentionally separate from CHINESE_LAUNCH_AGENCY_IDS so
# the existing commercial-provider series keeps its original meaning.
STATE_LAUNCH_PROVIDER_IDS = {
    "China Aerospace Science and Technology Corporation": 88,
    "China Rocket Co. Ltd.": 272,
}

SEC_SPACE_COMPANIES = {
    "RKLB": {"cik": "0001819994", "name": "Rocket Lab"},
    "ASTS": {"cik": "0001780312", "name": "AST SpaceMobile"},
    "PL": {"cik": "0001836833", "name": "Planet Labs"},
    "LUNR": {"cik": "0001844452", "name": "Intuitive Machines"},
    "RDW": {"cik": "0001819810", "name": "Redwire"},
}

POLICY_MILESTONES = [
    {"date": "2023-12", "event": "Central Economic Work Conference designates commercial space a strategic emerging industry"},
    {"date": "2024-03", "event": "2024 Government Work Report names commercial space a 'new engine of economic growth' (first appearance)"},
    {"date": "2025-03", "event": "2025 Government Work Report continues commercial space mention (two-year progression)"},
    {"date": "2025-11-25", "event": "CNSA publishes Action Plan for Promoting High-Quality and Safe Development of Commercial Space (2025–2027)"},
]
