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

# Data Storage directories
ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "data" / "raw" / "hk_transport"
NORMALIZED_DIR = ROOT_DIR / "data" / "normalized" / "hk_transport"
RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
