import os
from pathlib import Path
from typing import Literal

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw" / "hk_population_migration"
NORMALIZED_DIR = DATA_DIR / "normalized" / "hk_population_migration"
REGISTRY_DIR = DATA_DIR / "registries"

RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
}

# Open Data Endpoints
IMMD_DAILY_TRAFFIC_URL = "https://www.immd.gov.hk/opendata/eng/transport/immigration_clearance/statistics_on_daily_passenger_traffic.csv"
# 110-00001 does not exist ("Table ID (110-00001) is not defined") -- the two
# real C&SD tables covering population estimates and net movement are
# 110-01001 (population by sex/age) and 110-01003 (vital events + net
# movement, broken out by One-way Permit holders vs. others).
CSD_POPULATION_ESTIMATES_API_URL = "https://www.censtatd.gov.hk/api/get.php?id=110-01001&lang=en&full_series=1"
CSD_VITAL_EVENTS_API_URL = "https://www.censtatd.gov.hk/api/get.php?id=110-01003&lang=en&full_series=1"
# The UGC's own CSV endpoint (previously ...ugc.edu.hk/.../enrolment_origin.csv)
# 404s -- the site was restructured. The real, verified-live dataset is
# published on the government's CSDI (Common Spatial Data Infrastructure)
# portal as an Esri FeatureServer -- "Student Enrolment of UGC-funded
# Programmes by University, Level of Study, Place of Origin and Mode of
# Study", 1,459 records, 2010/11-2025/26 at last check.
UGC_STUDENT_ENROLMENT_FEATURESERVER_URL = (
    "https://portal.csdi.gov.hk/server/rest/services/common/ugc_rcd_1697186814214_75295/FeatureServer/0/query"
)
# Transport Department's Monthly Traffic and Transport Digest, published as
# CSV on data.gov.hk. table81e = HZMB vehicular traffic by vehicle class;
# table82 = cross-boundary passenger traffic by control point (includes
# ERLWK = Express Rail Link West Kowloon, and HKZMB).
TD_HZMB_VEHICULAR_TRAFFIC_URL = "https://www.td.gov.hk/datagovhk_tis/mttd-csv/en/table81e_eng.csv"
TD_CROSS_BOUNDARY_PASSENGER_URL = "https://www.td.gov.hk/datagovhk_tis/mttd-csv/en/table82_eng.csv"

# MPFA quarterly "Statistical Digest" PDFs. The listing page enumerates every
# published issue (so we discover URLs rather than hardcode a fixed date
# range); the current (2020-present) URL scheme is
# .../mpf-schemes/{month}_{year}_issue.pdf with lowercase month name
# (march/june/september/december). Older issues (pre-2020) use a different,
# inconsistent filename scheme under /pdf/eng/... and are not handled here.
MPFA_QUARTERLY_DIGEST_LISTING_URL = "https://www.mpfa.org.hk/en/info-centre/research-reports/quarterly-reports/mpf-schemes"
MPFA_QUARTERLY_DIGEST_BASE_URL = "https://www.mpfa.org.hk"

DataSourceLabel = Literal["live", "fallback_sample"]
DATA_SOURCE_LIVE: DataSourceLabel = "live"
