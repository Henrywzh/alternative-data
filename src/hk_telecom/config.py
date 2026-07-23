"""Configuration constants for HK Telecom Sector Pipeline."""

from __future__ import annotations

from pathlib import Path

DEFAULT_TIMEOUT = 15
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# HKT Trust Investor Relations URL
HKT_IR_URL = "https://www.hkt.com/about-hkt/investor-relations"

# SmarTone Investor Relations results index
SMARTONE_IR_URL = "https://www.smartoneholdings.com/about/investor/results/"

# Hutchison Telecom HK Holdings (0215.HK) Investor Relations results index
HTHKH_IR_URL = "https://www.hthkh.com/en/ir/fin_results.php"

# OFCA numbering plan (mobile number block allocations, all operators)
OFCA_NUMBERING_PLAN_URL = "https://www.ofca.gov.hk/filemanager/ofca/common/datagovhk/tel_no_en_tc.csv"

# Data Storage directories
ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "data" / "raw" / "hk_telecom"
NORMALIZED_DIR = ROOT_DIR / "data" / "normalized" / "hk_telecom"
RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
