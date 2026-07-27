"""Configuration constants for HK Commercial Aerospace Sector Pipeline."""

from __future__ import annotations

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
GOOGLE_PATENTS_URL = "https://patents.google.com/xhr/query"

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

POLICY_MILESTONES = [
    {"date": "2023-12", "event": "Central Economic Work Conference designates commercial space a strategic emerging industry"},
    {"date": "2024-03", "event": "2024 Government Work Report names commercial space a 'new engine of economic growth' (first appearance)"},
    {"date": "2025-03", "event": "2025 Government Work Report continues commercial space mention (two-year progression)"},
    {"date": "2025-01", "event": "CNSA publishes Action Plan for Promoting High-Quality and Safe Development of Commercial Space (2025–2027)"},
]
