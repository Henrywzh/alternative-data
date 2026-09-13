"""Constants and paths for the global market-regime radar."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

RAW_DIR = REPO_ROOT / "data" / "raw" / "global_market_regime"
NORMALIZED_DIR = REPO_ROOT / "data" / "normalized" / "global_market_regime"
DERIVED_DIR = REPO_ROOT / "data" / "derived" / "global_market_regime"
ALERT_STATE_PATH = DERIVED_DIR / "alert_state.json"

MARKET_TIMEZONE = "Asia/Taipei"
RUN_RETENTION = 5
HISTORY_START = "2015-01-01"
ZSCORE_WINDOW = 20
ZSCORE_MIN_PERIODS = 15
CHANGE_DAYS = 5

# Observation freshness: FRED H.15 and Atlanta MPT are previous-session
# publications. Seven calendar days covers weekends plus a delayed release
# without treating a two-day holiday gap as a stalled source.
STALE_AFTER_CALENDAR_DAYS = 7
# Persistence is an observation-based rule, but a long source outage must not
# let two isolated observations months apart count as consecutive evidence.
MAX_CONDITION_GAP_DAYS = 7
FRESH_CONDITION_STATUSES = frozenset(
    {"Current session", "Last session", "Recent"}
)

FRED_SERIES = (
    {
        "series_id": "DCOILBRENTEU",
        "indicator_id": "brent",
        "label_en": "Brent crude",
        "label_zh": "布伦特原油",
        "unit": "USD/bbl",
        "source": "FRED / EIA",
        "href": "https://fred.stlouisfed.org/series/DCOILBRENTEU",
    },
    {
        "series_id": "DGS10",
        "indicator_id": "us10y",
        "label_en": "US 10-year yield",
        "label_zh": "美国10年期国债收益率",
        "unit": "percent",
        "source": "FRED / Treasury H.15",
        "href": "https://fred.stlouisfed.org/series/DGS10",
    },
    {
        "series_id": "DGS2",
        "indicator_id": "us2y",
        "label_en": "US 2-year yield",
        "label_zh": "美国2年期国债收益率",
        "unit": "percent",
        "source": "FRED / Treasury H.15",
        "href": "https://fred.stlouisfed.org/series/DGS2",
    },
    {
        "series_id": "DGS1MO",
        "indicator_id": "us1m",
        "label_en": "US 1-month yield",
        "label_zh": "美国1个月国债收益率",
        "unit": "percent",
        "source": "FRED / Treasury H.15",
        "href": "https://fred.stlouisfed.org/series/DGS1MO",
    },
    {
        "series_id": "DGS3MO",
        "indicator_id": "us3m",
        "label_en": "US 3-month yield",
        "label_zh": "美国3个月国债收益率",
        "unit": "percent",
        "source": "FRED / Treasury H.15",
        "href": "https://fred.stlouisfed.org/series/DGS3MO",
    },
    {
        "series_id": "DGS6MO",
        "indicator_id": "us6m",
        "label_en": "US 6-month yield",
        "label_zh": "美国6个月国债收益率",
        "unit": "percent",
        "source": "FRED / Treasury H.15",
        "href": "https://fred.stlouisfed.org/series/DGS6MO",
    },
    {
        "series_id": "DGS1",
        "indicator_id": "us1y",
        "label_en": "US 1-year yield",
        "label_zh": "美国1年期国债收益率",
        "unit": "percent",
        "source": "FRED / Treasury H.15",
        "href": "https://fred.stlouisfed.org/series/DGS1",
    },
    {
        "series_id": "DGS3",
        "indicator_id": "us3y",
        "label_en": "US 3-year yield",
        "label_zh": "美国3年期国债收益率",
        "unit": "percent",
        "source": "FRED / Treasury H.15",
        "href": "https://fred.stlouisfed.org/series/DGS3",
    },
    {
        "series_id": "DGS5",
        "indicator_id": "us5y",
        "label_en": "US 5-year yield",
        "label_zh": "美国5年期国债收益率",
        "unit": "percent",
        "source": "FRED / Treasury H.15",
        "href": "https://fred.stlouisfed.org/series/DGS5",
    },
    {
        "series_id": "DGS7",
        "indicator_id": "us7y",
        "label_en": "US 7-year yield",
        "label_zh": "美国7年期国债收益率",
        "unit": "percent",
        "source": "FRED / Treasury H.15",
        "href": "https://fred.stlouisfed.org/series/DGS7",
    },
    {
        "series_id": "DGS20",
        "indicator_id": "us20y",
        "label_en": "US 20-year yield",
        "label_zh": "美国20年期国债收益率",
        "unit": "percent",
        "source": "FRED / Treasury H.15",
        "href": "https://fred.stlouisfed.org/series/DGS20",
    },
    {
        "series_id": "DGS30",
        "indicator_id": "us30y",
        "label_en": "US 30-year yield",
        "label_zh": "美国30年期国债收益率",
        "unit": "percent",
        "source": "FRED / Treasury H.15",
        "href": "https://fred.stlouisfed.org/series/DGS30",
    },
    {
        "series_id": "VIXCLS",
        "indicator_id": "vix",
        "label_en": "VIX",
        "label_zh": "VIX 波动率",
        "unit": "index",
        "source": "FRED / CBOE",
        "href": "https://fred.stlouisfed.org/series/VIXCLS",
    },
    {
        "series_id": "BAMLH0A0HYM2",
        "indicator_id": "hy_oas",
        "label_en": "US high-yield OAS",
        "label_zh": "美国高收益债利差",
        "unit": "percent",
        "source": "FRED / ICE BofA",
        "href": "https://fred.stlouisfed.org/series/BAMLH0A0HYM2",
    },
    {
        "series_id": "DCOILWTICO",
        "indicator_id": "wti",
        "label_en": "WTI crude",
        "label_zh": "WTI原油",
        "unit": "USD/bbl",
        "source": "FRED / EIA",
        "href": "https://fred.stlouisfed.org/series/DCOILWTICO",
    },
    {
        "series_id": "DTWEXAFEGS",
        "indicator_id": "usd_afe",
        "label_en": "USD advanced-economy index",
        "label_zh": "美元发达经济体指数",
        "unit": "index",
        "source": "FRED / Federal Reserve",
        "href": "https://fred.stlouisfed.org/series/DTWEXAFEGS",
    },
)

ATLANTA_MPT_URL = (
    "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/"
    "cenfis/market-probability-tracker/mpt_histdata.xlsx"
)

# Thresholds are the V1 defensive radar, not trading signals.
BRENT_ENTER = 100.0
US10Y_ENTER = 4.82
HIKE_ENTER = 65.0
HIKE_EXIT = 55.0
HIKE_ESCALATE = 75.0
CONFIRM_DAYS = 2
EXIT_DAYS = 2
OIL_PERSISTENT_WINDOW = 5
OIL_PERSISTENT_COUNT = 4
SYNC_ZSCORE = 1.0

STATES = ("Normal", "Watch", "Confirmed", "Escalating", "Improving")
STATE_SEVERITY = {
    "Normal": 0,
    "Improving": 1,
    "Watch": 2,
    "Confirmed": 3,
    "Escalating": 4,
}

DOMAIN_RULES = {
    "inflation_supply": {
        "label_en": "Inflation / supply",
        "label_zh": "通胀／供给",
        "indicator_ids": ("brent",),
    },
    "rates_policy": {
        "label_en": "Rates / policy",
        "label_zh": "利率／政策",
        "indicator_ids": ("us10y", "hike_prob", "fomc_hike"),
    },
    "financial_stress": {
        "label_en": "Financial stress",
        "label_zh": "金融压力",
        "indicator_ids": ("credit_vix",),
    },
}

COT_STALE_AFTER_CALENDAR_DAYS = 16
FOMC_STALE_AFTER_CALENDAR_DAYS = 3
FOMC_HIKE_ENTER = 65.0
FOMC_HIKE_EXIT = 55.0
FOMC_HIKE_ESCALATE = 75.0

# Shared presentation/evaluation metadata. The state engine owns the threshold
# values; the artifact and Streamlit page read this registry instead of
# restating the rules.
CONDITION_RULES = {
    "brent": {
        "domain_id": "inflation_supply",
        "threshold": BRENT_ENTER,
        "value_unit": "USD/bbl",
        "distance_unit": "USD/bbl",
        "confirmation_required": CONFIRM_DAYS,
        "persistence_window": OIL_PERSISTENT_WINDOW,
        "persistence_required": OIL_PERSISTENT_COUNT,
        "rule_en": "Above $100 for two observations or four of five observations",
        "rule_zh": "连续两次高于100美元，或最近五次中四次高于门槛",
    },
    "us10y": {
        "domain_id": "rates_policy",
        "threshold": US10Y_ENTER,
        "value_unit": "percent",
        "distance_unit": "bp",
        "confirmation_required": CONFIRM_DAYS,
        "rule_en": "Above 4.82% for two observations",
        "rule_zh": "连续两次高于4.82%",
    },
    "hike_prob": {
        "domain_id": "rates_policy",
        "threshold": HIKE_ENTER,
        "value_unit": "percent",
        "distance_unit": "pp",
        "confirmation_required": CONFIRM_DAYS,
        "rule_en": "Atlanta SOFR above-target probability above 65%",
        "rule_zh": "Atlanta SOFR高于目标区间概率超过65%",
    },
    "fomc_hike": {
        "domain_id": "rates_policy",
        "threshold": FOMC_HIKE_ENTER,
        "value_unit": "percent",
        "distance_unit": "pp",
        "confirmation_required": CONFIRM_DAYS,
        "rule_en": "Polymarket next-meeting hike probability above 65%",
        "rule_zh": "Polymarket下次会议加息概率超过65%",
    },
    "credit_vix": {
        "domain_id": "financial_stress",
        "threshold": SYNC_ZSCORE,
        "value_unit": "z-score",
        "distance_unit": "z",
        "confirmation_required": CONFIRM_DAYS,
        "rule_en": "Both 20-day z-scores above +1 and both five-day changes positive",
        "rule_zh": "两个20日z分数均高于+1，且两个五日变化均为正",
    },
}

ALERT_STATE_VERSION = 1
ALERT_STATE_MAX_KEYS = 64

CFTC_TFF_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
CFTC_DISAGG_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
POLYMARKET_SEARCH_URL = "https://gamma-api.polymarket.com/public-search"
POLYMARKET_CLOB_HISTORY_URL = "https://clob.polymarket.com/prices-history"

# Exact CFTC market names. TFF = Traders in Financial Futures (leveraged money);
# disaggregated = managed money. These are not interchangeable.
CFTC_TFF_CONTRACTS = (
    {"contract_id": "dxy", "label_en": "USD Index", "label_zh": "美元指数", "group": "fx", "market_and_exchange_names": "USD INDEX - ICE FUTURES U.S."},
    {"contract_id": "spx", "label_en": "S&P 500", "label_zh": "标普500", "group": "index", "market_and_exchange_names": "S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE"},
    {"contract_id": "ndx", "label_en": "Nasdaq 100", "label_zh": "纳斯达克100", "group": "index", "market_and_exchange_names": "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE"},
    {"contract_id": "btc", "label_en": "Bitcoin", "label_zh": "比特币", "group": "crypto", "market_and_exchange_names": "BITCOIN - CHICAGO MERCANTILE EXCHANGE"},
    {"contract_id": "eth", "label_en": "Ether", "label_zh": "以太坊", "group": "crypto", "market_and_exchange_names": "ETHER CASH SETTLED - CHICAGO MERCANTILE EXCHANGE"},
)
CFTC_DISAGG_CONTRACTS = (
    {"contract_id": "gold", "label_en": "Gold", "label_zh": "黄金", "group": "commodity", "market_and_exchange_names": "GOLD - COMMODITY EXCHANGE INC."},
    {"contract_id": "wti", "label_en": "WTI crude", "label_zh": "WTI原油", "group": "commodity", "market_and_exchange_names": "WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE"},
)
CROSS_ASSET_EXPOSURES = (
    "sp500",
    "ndx",
    "csi300",
    "csi500",
    "hsi",
    "hstech",
    "nikkei225",
    "kospi",
)
# US sector ETFs reused from market-monitor for the Regime leadership table.
# These are wrappers (XLK/XLF-style), not official SPY weights.
SECTOR_LEADERSHIP_EXPOSURES = (
    "us_tech",
    "us_discretionary",
    "us_communication",
    "us_healthcare",
    "us_staples",
    "us_utilities",
)
SECTOR_LEADERSHIP_BENCHMARK = "us_broad"

# Constant-maturity Treasury curve for the Fixed Income tab. These points are
# the standard FRED H.15 tenors. Shepherd's 1.5M / 2M / 4M par-curve knots are
# omitted in V1; the 2Y-10Y shape does not depend on them.
TREASURY_CURVE_POINTS = (
    {"indicator_id": "us1m", "maturity": "1M", "tenor_months": 1, "label_en": "1 Mo", "label_zh": "1个月"},
    {"indicator_id": "us3m", "maturity": "3M", "tenor_months": 3, "label_en": "3 Mo", "label_zh": "3个月"},
    {"indicator_id": "us6m", "maturity": "6M", "tenor_months": 6, "label_en": "6 Mo", "label_zh": "6个月"},
    {"indicator_id": "us1y", "maturity": "1Y", "tenor_months": 12, "label_en": "1 Yr", "label_zh": "1年"},
    {"indicator_id": "us2y", "maturity": "2Y", "tenor_months": 24, "label_en": "2 Yr", "label_zh": "2年"},
    {"indicator_id": "us3y", "maturity": "3Y", "tenor_months": 36, "label_en": "3 Yr", "label_zh": "3年"},
    {"indicator_id": "us5y", "maturity": "5Y", "tenor_months": 60, "label_en": "5 Yr", "label_zh": "5年"},
    {"indicator_id": "us7y", "maturity": "7Y", "tenor_months": 84, "label_en": "7 Yr", "label_zh": "7年"},
    {"indicator_id": "us10y", "maturity": "10Y", "tenor_months": 120, "label_en": "10 Yr", "label_zh": "10年"},
    {"indicator_id": "us20y", "maturity": "20Y", "tenor_months": 240, "label_en": "20 Yr", "label_zh": "20年"},
    {"indicator_id": "us30y", "maturity": "30Y", "tenor_months": 360, "label_en": "30 Yr", "label_zh": "30年"},
)
TREASURY_CURVE_SNAPSHOT_LABELS = (
    {"snapshot_id": "latest", "label_en": "Latest published", "label_zh": "最新公布"},
    {"snapshot_id": "week_ago", "label_en": "1 week ago", "label_zh": "一周前"},
    {"snapshot_id": "month_ago", "label_en": "1 month ago", "label_zh": "一个月前"},
    {"snapshot_id": "year_start", "label_en": "Start of year", "label_zh": "年初"},
)
