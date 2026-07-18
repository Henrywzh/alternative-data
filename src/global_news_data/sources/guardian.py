import logging
from typing import Any

from .http import build_retrying_session

logger = logging.getLogger(__name__)

class GuardianClient:
    BASE_URL = "https://content.guardianapis.com"

    def __init__(self, api_key: str, timeout: int = 15):
        self.api_key = api_key
        self.timeout = timeout
        self.session = build_retrying_session()

    def fetch_articles(self, query: str = "finance OR economy OR market", page_size: int = 10) -> dict[str, Any]:
        url = f"{self.BASE_URL}/search"
        params = {
            "api-key": self.api_key,
            "q": query,
            "page-size": page_size,
            "show-fields": "bodyText",
        }
        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()
