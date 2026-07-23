import os
from pathlib import Path
from typing import Literal

# Paths
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw" / "hk_local_consumer"
NORMALIZED_DIR = DATA_DIR / "normalized" / "hk_local_consumer"
REGISTRY_DIR = DATA_DIR / "registries"

# Ensure directories exist
RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

# HK Local Consumer Target Tickers
# Full 11-name watchlist per docs/asia-markets-hk-local-consumer.md ("## Watchlist").
# NOTE: "0529" for Fairwood was a transposed-digit bug -- Fairwood Holdings'
# real HKEX code is 0052 (verified against the research doc and akshare).
HK_CONSUMER_TICKERS = {
    "1929": "Chow Tai Fook Jewellery",
    "1913": "Prada",
    "1910": "Samsonite",
    "0590": "Luk Fook Holdings",
    "0116": "Chow Sang Sang Holdings",
    "0341": "Café de Coral Holdings",
    "0178": "Sa Sa International",
    "0709": "Giordano International",
    "6811": "Tai Hing Group",
    "1255": "TATA Health",
    "0052": "Fairwood Holdings",
}

# Data-source honesty labels (bug 5 fix): every fetch function must tag its
# output with one of these so downstream consumers (dashboard, manifest,
# QA) can tell real government/market data apart from a synthetic
# placeholder without having to diff against hardcoded literals in source.
DataSourceLabel = Literal["live", "fallback_sample"]
DATA_SOURCE_LIVE: DataSourceLabel = "live"
DATA_SOURCE_FALLBACK: DataSourceLabel = "fallback_sample"

# Endpoint URLs
# Verified working direct-CSV endpoint (also listed on data.gov.hk under
# hk-afcd-afcdlist-wholesale-prices). The previously configured
# "daily_wholesale_prices.csv" path does not exist and resolves (HTTP 200)
# to an HTML "protected area" placeholder page, not CSV.
AFCD_DAILY_WHOLESALE_URL = "https://www.afcd.gov.hk/english/agriculture/agr_fresh/files/Wholesale_Prices.csv"
AFCD_DATA_GOV_HK_URL = "https://data.gov.hk/en-data/dataset/hk-afcd-afcdlist-wholesale-prices"

# Real HK Consumer Council "Online Price Watch" open-data endpoints
# (dataset id cc-pricewatch-pricewatch on data.gov.hk, documented at
# data.gov.hk/en/help/api-spec). The previously configured
# consumer.org.hk/pricewatch/api/prices URL was a guess that 302-redirects
# to nowhere real.
CONSUMER_COUNCIL_PRICE_WATCH_URL = "https://online-price-watch.consumer.org.hk/opw/opendata/pricewatch_en.csv"
CONSUMER_COUNCIL_PRICE_WATCH_JSON_URL = "https://online-price-watch.consumer.org.hk/opw/opendata/pricewatch.json"
CONSUMER_COUNCIL_DATA_GOV_HK_URL = "https://data.gov.hk/en-data/dataset/cc-pricewatch-pricewatch"

# HK Immigration Department "Statistics on Daily Passenger Traffic" open data CSV
IMMIGRATION_PASSENGER_TRAFFIC_URL = "https://www.immd.gov.hk/opendata/eng/transport/immigration_clearance/statistics_on_daily_passenger_traffic.csv"
IMMIGRATION_DATA_GOV_HK_URL = "https://data.gov.hk/en-data/dataset/hk-immd-stat-stat-passenger-traffic"

# CenStatD "web table" static data files. The web_table.html viewer pages
# are JS-rendered (fetching a bot-block-able HTML shell if requested
# directly), but the underlying per-series CSV files they load are plain,
# unauthenticated static files at censtatd.gov.hk/data/MDT_<theme_id>_
# <table_id>_<series_code>.csv -- verified by inspecting the actual network
# requests the viewer page makes.
CENSTATD_DATA_BASE_URL = "https://www.censtatd.gov.hk/data"

# Legacy generic query endpoint, kept only as a documented dead end: it
# 404s for every table id we tried and is not how CenStatD serves this
# data (see CENSTATD_DATA_BASE_URL above). Retained so any external caller
# referencing it fails loudly instead of silently.
CNSD_API_BASE_URL = "https://www.censtatd.gov.hk/api/post.jsp"

# Retail Sales - Table 620-67002: "Value and value index of retail sales by
# type of retail outlet" (theme id 75). This constant used to be wrongly
# unused -- cnsd_retail.py hardcoded "620-67002" inline instead of
# importing it. It is now the actual source of truth for that module.
CENSTATD_RETAIL_SALES_TABLE_ID = "620-67002"
CENSTATD_RETAIL_SALES_THEME_ID = "75"
# Volume index lives in a sibling table, 620-67003, same theme.
CENSTATD_RETAIL_SALES_VOLUME_TABLE_ID = "620-67003"

# Restaurant Receipts and Purchases survey (theme id 90).
# IMPORTANT FIX: "620-67001" (the old value here) is actually "Total Retail
# Sales" -- a completely different survey. The real restaurant
# receipts/purchases tables are 625-68001 through 625-68011.
# "Fast food shops" is only broken out (via the REST_GRP classification
# variable, code 3) in table 625-68003, "Restaurant receipts by type of
# restaurant" -- verified directly against CenStatD's own published Q1 2026
# figures (value -0.6% YoY / volume -1.5% YoY for REST_GRP=3), which match
# docs/asia-markets-hk-local-consumer.md's independently-sourced numbers.
CENSTATD_RESTAURANT_TABLE_ID = "625-68003"
# Total restaurant purchases are only published sector-wide (not broken
# out by restaurant type) in table 625-68001.
CENSTATD_RESTAURANT_TOTALS_TABLE_ID = "625-68001"
CENSTATD_RESTAURANT_THEME_ID = "90"

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/json,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,zh-HK;q=0.8,zh-TW;q=0.7',
}
