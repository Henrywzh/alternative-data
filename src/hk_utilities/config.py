"""Configuration constants for HK Utilities Sector Pipeline."""

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

# CenStatD Theme 91, Table 915-91201 (Gas & Electricity Consumption)
CENSTATD_ENERGY_THEME_ID = "91"
CENSTATD_ENERGY_TABLE_ID = "915-91201"
CENSTATD_ENERGY_GAS_URL = f"https://www.censtatd.gov.hk/data/MDT_{CENSTATD_ENERGY_THEME_ID}_{CENSTATD_ENERGY_TABLE_ID}_GASC_LOCAL_Raw_Tjou_n.csv"
CENSTATD_ENERGY_ELEC_URL = f"https://www.censtatd.gov.hk/data/MDT_{CENSTATD_ENERGY_THEME_ID}_{CENSTATD_ENERGY_TABLE_ID}_ELEC_LOCAL_Raw_Tjou_n.csv"

# HKO Daily Mean Temperature open-data CSV
HKO_MEAN_TEMP_URL = "https://data.weather.gov.hk/weatherAPI/cis/csvfile/HKO/ALL/daily_HKO_TEMP_ALL.csv"

# Data Storage directories
ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "data" / "raw" / "hk_utilities"
NORMALIZED_DIR = ROOT_DIR / "data" / "normalized" / "hk_utilities"
RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
