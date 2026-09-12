from __future__ import annotations

BIS_SDMX_BASE_URL = "https://data.bis.org/api/v1/data"
BIS_BULK_BASE_URL = "https://data.bis.org/static/bulk"
BIS_CREDIT_GAP_BULK_URL = f"{BIS_BULK_BASE_URL}/WS_CREDIT_GAP_csv_flat.zip"
DEFAULT_TARGET_AREAS = ["US", "CN", "HK", "JP", "XM", "GB", "KR"]
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json, text/csv",
}
