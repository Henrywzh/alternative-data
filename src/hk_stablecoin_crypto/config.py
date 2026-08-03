"""Configuration constants for HK Stablecoin & Crypto Sector Pipeline."""

from __future__ import annotations

from pathlib import Path

DEFAULT_TIMEOUT = 15
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "data" / "raw" / "hk_stablecoin_crypto"
NORMALIZED_DIR = ROOT_DIR / "data" / "normalized" / "hk_stablecoin_crypto"
RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)

HKMA_REGISTER_URL = "https://www.hkma.gov.hk/eng/regulatory-resources/registers/register-of-licensed-stablecoin-issuers/"
SFC_VATP_URL = "https://www.sfc.hk/en/Welcome-to-the-Fintech-Contact-Point/Virtual-assets/Virtual-asset-trading-platforms-operators/Lists-of-virtual-asset-trading-platforms"

# SFC news search API — confirmed live via browser network inspection of the
# React SPA at https://apps.sfc.hk/edistributionWeb/gateway/EN/news-and-announcements/news/.
# POST body shape mirrors the SPA's own state object (see sources/sfc_news.py).
SFC_NEWS_API_URL = "https://apps.sfc.hk/edistributionWeb/api/news/search"
SFC_NEWS_REFERER = "https://apps.sfc.hk/edistributionWeb/gateway/EN/news-and-announcements/news/"

# HKMA official Open API for press releases — documented at
# https://apidocs.hkma.gov.hk/documentation/press-releases/. Plain GET, JSON,
# no auth, paginated via offset (100 records/page).
HKMA_NEWS_URL = "https://api.hkma.gov.hk/public/press-releases"

# Keyword filter shared by both news sources to narrow the all-of-finance /
# all-of-banking firehose down to stablecoin/virtual-asset/crypto relevance.
CRYPTO_NEWS_KEYWORDS = [
    "stablecoin",
    "virtual asset",
    "vatp",
    "crypto",
    "digital asset",
    "web3",
    "virtual currency",
    "tokeni",  # matches tokenise/tokenize/tokenisation/tokenization
    "blockchain",
]

# HKEXnews title search (company announcements/disclosures).
# IMPORTANT: titleSearchServlet.do's `stockId` param does NOT accept the plain
# numeric stock code -- it silently ignores it and returns an unrelated
# company's announcements (confirmed: stockId=700 returned data for
# STOCK_CODE 00362 "C ZENITH CHEM", not Tencent). The servlet needs the
# internal numeric stockId that prefix.do resolves a stock code to. Always
# resolve via HKEXNEWS_PREFIX_URL first, then call HKEXNEWS_TITLE_SEARCH_URL
# with the resolved id, and verify the returned STOCK_CODE matches what was
# requested before trusting any row.
HKEXNEWS_TITLE_SEARCH_URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
HKEXNEWS_PREFIX_URL = "https://www1.hkexnews.hk/search/prefix.do"
HKEXNEWS_SEARCH_REFERER = "https://www1.hkexnews.hk/search/titlesearch.xhtml"

DEFILLAMA_URL = "https://stablecoins.llama.fi/stablecoins?includePrices=true"
HKEX_ETF_API_BASE = "https://ifp.hkex.com.hk/ifp/api/v1/fund/getFundSizeList"

HKEX_ETF_FUNDS = [
    {"name": "Bosera HashKey Bitcoin ETF", "ticker": "3008.HK", "fund_id": "BUU104"},
    {"name": "Bosera HashKey Ether ETF", "ticker": "3009.HK", "fund_id": "BUU105"},
    {"name": "ChinaAMC Bitcoin ETF", "ticker": "3042.HK", "fund_id": "BUU163"},
    {"name": "ChinaAMC Ether ETF", "ticker": "3046.HK", "fund_id": "BUU164"},
    {"name": "Harvest Bitcoin Spot ETF", "ticker": "3439.HK", "fund_id": "BUT244"},
    {"name": "Harvest Ether Spot ETF", "ticker": "3179.HK", "fund_id": None, "needs_lookup": True, "lookup_note": "fundId unknown — BUT245 guessed and 404'd. Look up via ifp.hkex.com.hk fund page before wiring."},
]

COINBASE_TICKER_URL = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=3"
POLYMARKET_SEARCH_URL = "https://gamma-api.polymarket.com/public-search"

WIKIMEDIA_PAGEVIEWS_API_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
WIKIMEDIA_PAGEVIEWS_PROJECT = "en.wikipedia.org"
WIKIMEDIA_PAGEVIEWS_START_DATE = "20150701"
WIKIMEDIA_PAGEVIEWS_AGENTS = ("user", "spider", "automated", "all-agents")
WIKIMEDIA_PAGEVIEWS_REQUEST_DELAY_SECONDS = 0.75

# A stable, topic-focused English Wikipedia basket for global crypto attention.
# This is an attention proxy, not a measure of unique users, trading activity,
# or Hong Kong adoption.
WIKIMEDIA_CRYPTO_PAGES = (
    {"page_id": "bitcoin", "title": "Bitcoin", "label": "Bitcoin", "topic_group": "Market"},
    {"page_id": "ethereum", "title": "Ethereum", "label": "Ethereum", "topic_group": "Market"},
    {"page_id": "cryptocurrency", "title": "Cryptocurrency", "label": "Cryptocurrency", "topic_group": "Market"},
    {"page_id": "stablecoin", "title": "Stablecoin", "label": "Stablecoin", "topic_group": "Stablecoin"},
    {"page_id": "tether", "title": "Tether (cryptocurrency)", "label": "Tether", "topic_group": "Stablecoin"},
    {"page_id": "usd_coin", "title": "USD Coin", "label": "USD Coin", "topic_group": "Stablecoin"},
    {"page_id": "decentralized_finance", "title": "Decentralized finance", "label": "Decentralized finance", "topic_group": "DeFi"},
    {"page_id": "decentralized_exchange", "title": "Decentralized exchange", "label": "Decentralized exchange", "topic_group": "DeFi"},
)

HK_CHINA_STABLECOINS_TO_WATCH = ["AxCNH", "HKDAP"]

NAMING_COLLISION_NOTE = "Anchorpoint Financial (HKMA licence FRS01, SCB+Animoca+HKT JV, HKD-pegged HKDAP) is DIFFERENT from AnchorX (Jinyong Investment/01328.HK, CNH-pegged AxCNH). Do NOT conflate."
COIN_CRCL_SIGNAL_NOTE = "COIN/CRCL price+volume is a confirmed leading indicator for MACRO/REGULATORY-CATALYST-DRIVEN sector-wide moves (~1 week lead, n=2: GENIUS Act case confirmed, Jinyong/AnchorX case does NOT show this pattern). NOT predictive of idiosyncratic single-company deal announcements. Do not treat as a blanket predictor."

WATCHLIST = {
    "TIER_1": [
        {"ticker": "00863.HK", "name_en": "OSL Group", "name_zh": "OSL集团", "tier": 1, "regulatory_note": "SFC VATP-licensed exchange operator since 15/12/2020"},
        {"ticker": "03887.HK", "name_en": "HashKey Holdings", "name_zh": "HashKey", "tier": 1, "regulatory_note": "SFC VATP-licensed exchange operator since 09/11/2022"},
        {"ticker": "01788.HK", "name_en": "Guotai Junan International", "name_zh": "国泰君安国际", "tier": 1, "regulatory_note": "Licensed to deal in virtual assets — NOT a VATP exchange operator (different, lesser regulatory status)"},
        {"ticker": "08540.HK", "name_en": "Victory Securities", "name_zh": "胜利证券", "tier": 1, "regulatory_note": "Licensed to deal in virtual assets — NOT a VATP exchange operator (different, lesser regulatory status)"},
        {"ticker": "01499.HK", "name_en": "OKG Technology", "name_zh": "欧科云链", "tier": 1, "regulatory_note": "Infrastructure/data; linked to OKX, but OKX withdrew its HK VATP application in May 2024"},
        {"ticker": "01611.HK", "name_en": "Sinohope", "name_zh": "新火集团", "tier": 1, "regulatory_note": "Asset management and tech solutions (SFO Type 1/4/9 licensed)"},
    ],
    "TIER_2": [
        {"ticker": "00005.HK", "name_en": "HSBC Holdings", "name_zh": "汇丰控股", "tier": 2, "regulatory_note": "HKMA stablecoin issuer licence FRS02 effective 10/04/2026"},
        {"ticker": "02888.HK", "name_en": "Standard Chartered", "name_zh": "渣打集团", "tier": 2, "regulatory_note": "HKMA stablecoin issuer licence FRS01 effective 10/04/2026 via Anchorpoint Financial JV"},
        {"ticker": "06823.HK", "name_en": "HKT", "name_zh": "香港电讯", "tier": 2, "regulatory_note": "Partner in Anchorpoint Financial JV (FRS01)"},
        {"ticker": "02388.HK", "name_en": "BOC Hong Kong", "name_zh": "中银香港", "tier": 2, "regulatory_note": "Linked to HKMA stablecoin issuer sandbox"},
        {"ticker": "09988.HK", "name_en": "Alibaba", "name_zh": "阿里巴巴", "tier": 2, "regulatory_note": "Ant International reportedly pursuing stablecoin initiatives"},
        {"ticker": "09618.HK", "name_en": "JD.com", "name_zh": "京东集团", "tier": 2, "regulatory_note": "Pursuing stablecoin initiatives"},
    ],
    "TIER_3": [
        {"ticker": "01328.HK", "name_en": "Jinyong Investment", "name_zh": "金涌投资", "tier": 3, "regulatory_note": "Partnered with AnchorX for AxCNH stablecoin (DO NOT CONFLATE WITH ANCHORPOINT)"},
        {"ticker": "08087.HK", "name_en": "China 33 Group", "name_zh": "中国三三传媒", "tier": 3, "regulatory_note": "Announced plans to apply for a HK stablecoin license"},
        {"ticker": "02477.HK", "name_en": "Jingwei Tiandi", "name_zh": "经纬天地", "tier": 3, "regulatory_note": "Launched Fopay stablecoin payment app"},
        {"ticker": "00290.HK", "name_en": "Guofu Quantum", "name_zh": "国富创新", "tier": 3, "regulatory_note": "Investing in RWA tokenization platforms"},
        {"ticker": "00399.HK", "name_en": "Starcoin Group", "name_zh": "星太链集团", "tier": 3, "regulatory_note": "Gold RWA-tokenization framework agreement, token airdrop MOU"},
        {"ticker": "01647.HK", "name_en": "Xiongan Technology", "name_zh": "雄岸科技", "tier": 3, "regulatory_note": "Partnership with Lion Group for crypto trading platform"},
        {"ticker": "00736.HK", "name_en": "China Properties Investment", "name_zh": "中国置业投资", "tier": 3, "regulatory_note": "TokenMarket tie-up, purchasing digital assets"},
    ],
    "TIER_4": [
        {"ticker": "00434.HK", "name_en": "Boyaa Interactive", "name_zh": "博雅互动", "tier": 4, "regulatory_note": "BTC/ETH treasury play"},
        {"ticker": "08267.HK", "name_en": "Lion Rock", "name_zh": "蓝港互动", "tier": 4, "regulatory_note": "BTC/ETH/SOL treasury play and staking"},
        {"ticker": "02440.HK", "name_en": "MemeStrategy", "name_zh": "迷策略", "tier": 4, "regulatory_note": "Solana treasury play, Moonit trading system"},
    ],
}
