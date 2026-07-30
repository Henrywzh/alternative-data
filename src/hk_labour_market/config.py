"""Paths and HTTP settings for Hong Kong labour-market data."""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw" / "hk_labour_market"
NORMALIZED_DIR = DATA_DIR / "normalized" / "hk_labour_market"
MARTS_DIR = NORMALIZED_DIR / "marts"

CENSTATD_API_URL = "https://www.censtatd.gov.hk/api/get.php"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,zh-HK;q=0.8",
}

RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
MARTS_DIR.mkdir(parents=True, exist_ok=True)
