import logging
from typing import Any

from .http import build_retrying_session

logger = logging.getLogger(__name__)

class CurrentsClient:
    BASE_URL = "https://api.currentsapi.services/v1"

    def __init__(self, api_key: str, timeout: int = 15):
        self.api_key = api_key
        self.timeout = timeout
        self.session = build_retrying_session()

    def fetch_latest(self, category: str = "business", page_size: int = 10) -> dict[str, Any]:
        # `/latest-news` is category-driven, not keyword-searchable; use `/search`
        # with a `keywords` param if free-text querying is needed here later.
        url = f"{self.BASE_URL}/latest-news"
        headers = {
            "Authorization": self.api_key,
        }
        params = {
            "language": "en",
            "category": category,
            "page_size": page_size,
        }
        r = self.session.get(url, headers=headers, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()
