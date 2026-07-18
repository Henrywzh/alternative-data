import logging
from typing import Any

from .http import build_retrying_session

logger = logging.getLogger(__name__)

class GdeltClient:
    """Client for the GDELT 2.0 DOC API (no API key required).

    GDELT asks that requests be limited to roughly one every 5 seconds
    (https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/); this client is
    called at most once per pipeline run so no internal throttling is added.
    """

    BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = build_retrying_session()

    def fetch_articles(
        self,
        query: str = "finance OR economy OR market",
        max_records: int = 50,
        timespan: str = "2d",
        source_country: str | None = None,
        source_lang: str | None = None,
    ) -> dict[str, Any]:
        query_string = f'"{query}"' if " " in query else query
        if source_country:
            query_string += f" sourcecountry:{source_country}"
        if source_lang:
            query_string += f" sourcelang:{source_lang}"

        params = {
            "query": query_string,
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(min(max_records, 250)),
            "timespan": timespan,
        }
        r = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
        r.raise_for_status()

        # GDELT sometimes answers an invalid/unparseable query with a 200 and
        # a text/html error message instead of JSON.
        content_type = r.headers.get("content-type", "")
        if "application/json" not in content_type:
            logger.warning(f"GDELT returned non-JSON response for query {query!r}: {r.text[:200]}")
            return {"articles": []}
        return r.json()
