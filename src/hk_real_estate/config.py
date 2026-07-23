import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw" / "hk_real_estate"
NORMALIZED_DIR = DATA_DIR / "normalized" / "hk_real_estate"

REGISTRY_DIR = DATA_DIR / "registries"

# Ensure directories exist
RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

# Endpoint URLs — Group A
MIDLAND_MARKET_INSIGHT_URL = "https://www.midland.com.hk/zh-hk/market-insight"
CENTALINE_CCI_URL = "https://hk.centanet.com/CCI/index"
CENTALINE_CCL_API_URL = "https://hk.centanet.com/CCI/api/Index/CCL"
HSE28_NEW_PROPERTIES_URL = "https://www.28hse.com/new-properties"
HSE28_ESTATE_INDEX_URL = "https://www.28hse.com/estate/"
HSE28_EPI_URL = "https://www.28hse.com/epi/"
HSE28_EPI_HISTORY_URL = "https://www.28hse.com/epi/historical_data"
HSE28_EPI_HISTORY_ACTION_URL = "https://www.28hse.com/epi/historical_data/doaction"

# Endpoint URLs — Group B
RVD_PRICE_1_4M_URL = "http://www.rvd.gov.hk/datagovhk/1.4M.csv"
RVD_RENTAL_1_3M_URL = "http://www.rvd.gov.hk/datagovhk/1.3M.csv"
RVD_OFFICE_RENTAL_2_3M_URL = "http://www.rvd.gov.hk/datagovhk/2.3M.csv"
RVD_RETAIL_3_2M_URL = "http://www.rvd.gov.hk/datagovhk/3.2M.csv"
LANDREG_PRESS_RELEASES_URL = "https://www.landreg.gov.hk/en/public/press.htm"
LANDREG_MONTHLY_URL = "https://www.landreg.gov.hk/en/monthly/monthly.htm"
LANDREG_MONTHLY_JSON_BASE = "https://www.landreg.gov.hk/json/monthly_stat/monthly"

# Endpoint URLs — Group C & Stage 2
SRPE_OPIP_URL = "https://www.srpe.gov.hk/opip/"
BD_MONTHLY_DIGESTS_URL = "https://www.bd.gov.hk/en/whats-new/monthly-digests/index.html"
BD_MONTHLY_DIGEST_XLS_BASE = "https://www.bd.gov.hk/doc/en/whats-new/monthly-digests"

# Stage 2 Credit & HKEX Endpoints
HKMA_RMS_API_URL = "https://vapi.hkma.gov.hk/v1/market-data-and-statistics/monthly-statistical-bulletin/banking/residential-mortgage-survey"
HKEX_NEWS_SEARCH_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml"

# Request Headers
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, impervious/1.0) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,zh-TW;q=0.8,zh;q=0.7',
}

