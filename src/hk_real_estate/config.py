import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw" / "hk_real_estate"
NORMALIZED_DIR = DATA_DIR / "normalized" / "hk_real_estate"

# Ensure directories exist
RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)

# Endpoint URLs — Group A
MIDLAND_MARKET_INSIGHT_URL = "https://www.midland.com.hk/zh-hk/market-insight"
# The JSON endpoint is used instead of evaluating the Nuxt page state.  It is
# published by the same first-party application and contains the CCL chart
# series as ordinary JSON.
CENTALINE_CCI_URL = "https://hk.centanet.com/CCI/index"
CENTALINE_CCL_API_URL = "https://hk.centanet.com/CCI/api/Index/CCL"
HSE28_NEW_PROPERTIES_URL = "https://www.28hse.com/new-properties"

# Endpoint URLs — Group B
RVD_PRICE_1_4M_URL = "http://www.rvd.gov.hk/datagovhk/1.4M.csv"
RVD_RENTAL_1_3M_URL = "http://www.rvd.gov.hk/datagovhk/1.3M.csv"
RVD_OFFICE_RENTAL_2_3M_URL = "http://www.rvd.gov.hk/datagovhk/2.3M.csv"
RVD_RETAIL_3_2M_URL = "http://www.rvd.gov.hk/datagovhk/3.2M.csv"
LANDREG_PRESS_RELEASES_URL = "https://www.landreg.gov.hk/en/public/press.htm"

# Endpoint URLs — Group C
SRPE_OPIP_URL = "https://www.srpe.gov.hk/opip/"
BD_MONTHLY_DIGESTS_URL = "https://www.bd.gov.hk/en/whats-new/monthly-digests/index.html"

# Request Headers
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, impervious/1.0) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,zh-TW;q=0.8,zh;q=0.7',
}
