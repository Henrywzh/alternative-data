"""Paths and registry for the HK REIT data pipeline.

Scope note: akshare's HK fundamentals functions
(`stock_hk_dividend_payout_em`, `stock_hk_valuation_baidu`,
`stock_hk_financial_indicator_em`) were checked directly against these
REIT tickers before building this pipeline and confirmed to return
empty results or raise on all of them (likely because REITs are trust
units, not standard equity, in the underlying Eastmoney/Baidu data
sources those functions scrape). Only price/quote data
(`stock_hk_spot_em`, `stock_hk_hist`) is confirmed to work for REIT
tickers, so this pipeline is scoped to that alone. Distribution/yield,
occupancy, and rental-reversion data are a documented gap (see
docs/asia-markets/asia-markets-hk-real-estate.md) requiring a different source
(HKEXnews interim/annual filings) — not attempted here.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw" / "hk_reit"
NORMALIZED_DIR = DATA_DIR / "normalized" / "hk_reit"

RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)

# HK REIT universe, per docs/asia-markets/asia-markets-hk-real-estate.md section 1
# ("HK REITs" table). Ticker codes are bare (no .HK suffix), matching
# akshare's convention.
HK_REIT_TICKERS = {
    "00823": "Link REIT",
    "02778": "Champion REIT",
    "00778": "Fortune REIT",
    "00808": "Prosperity REIT",
    "00435": "Sunlight REIT",
    "01881": "Regal REIT",
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}
