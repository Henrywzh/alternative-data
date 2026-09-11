from __future__ import annotations

HKMA_BASE_URL = "https://api.hkma.gov.hk/public/market-data-and-statistics"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}

INTERBANK_LIQUIDITY_PATH = "/daily-monetary-statistics/daily-figures-interbank-liquidity"
HIBOR_PATH = "/daily-monetary-statistics/daily-figures-hibor"

# The HKMA API is the preferred official transport.  HKAB's public page is a
# current fixing page rather than a historical download, so the long history
# fallback used by the backfill is the public Jin10 data-centre artifact that
# AkShare documents for this exact report.  It is labelled as an aggregator in
# the normalized provenance, not silently presented as HKMA-originated data.
HIBOR_HISTORY_FALLBACK_URL = "https://cdn.jin10.com/data_center/reports/il_2.json"
