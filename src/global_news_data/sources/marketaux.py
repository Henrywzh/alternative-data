import logging
from typing import Any

from .http import build_retrying_session

logger = logging.getLogger(__name__)

class MarketauxClient:
    BASE_URL = "https://api.marketaux.com/v1"
    # Marketaux free tier rejects `limit` above this value; paid tiers can raise it.
    FREE_TIER_LIMIT = 3

    def __init__(self, api_key: str, timeout: int = 15, max_limit: int = FREE_TIER_LIMIT):
        self.api_key = api_key
        self.timeout = timeout
        self.max_limit = max_limit
        self.session = build_retrying_session()

    def fetch_news(self, symbols: str = "AAPL,MSFT,NVDA,AMZN,GOOGL", limit: int = 10) -> dict[str, Any]:
        url = f"{self.BASE_URL}/news/all"
        capped_limit = min(limit, self.max_limit)
        if capped_limit < limit:
            logger.warning(
                f"Marketaux limit {limit} capped to {capped_limit} (max_limit={self.max_limit})."
            )
        params = {
            "api_token": self.api_key,
            "symbols": symbols,
            "limit": capped_limit,
        }
        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()
