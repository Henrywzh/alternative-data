import logging
import time
from datetime import datetime, timezone
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .models import EdgarFilingHit

logger = logging.getLogger(__name__)

def _build_retrying_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    retry = Retry(
        total=4,
        connect=3,
        read=3,
        status=4,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


# Public alias so sibling collectors (e.g. the Research Control Tower Batch 2
# SEC submissions adapter) reuse the same retry/throttle behaviour without
# reaching into a private name.
build_retrying_session = _build_retrying_session

class EdgarFullTextSearchClient:
    """Thin client for the SEC EDGAR full-text search API (efts.sec.gov).

    No API key is required, but SEC asks for a descriptive User-Agent and
    enforces a 10 req/sec rate limit across all EDGAR subdomains
    (https://www.sec.gov/os/webmaster-faq#developers).
    """

    BASE_URL = "https://efts.sec.gov/LATEST/search-index"
    MIN_REQUEST_INTERVAL = 0.15  # keeps us comfortably under 10 req/sec

    def __init__(self, user_agent: str, timeout: int = 15):
        self.timeout = timeout
        self.session = _build_retrying_session(user_agent)
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_at = time.monotonic()

    def search(
        self,
        query: str,
        forms: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        size: int = 100,
    ) -> dict:
        self._throttle()
        params: dict[str, str] = {"q": query, "size": str(size)}
        if forms:
            params["forms"] = ",".join(forms)
        if start_date and end_date:
            params["dateRange"] = "custom"
            params["startdt"] = start_date
            params["enddt"] = end_date

        r = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def extract(self, payload: dict, query: str) -> list[EdgarFilingHit]:
        fetched_at = datetime.now(timezone.utc).isoformat()
        hits = payload.get("hits", {}).get("hits", [])
        records: list[EdgarFilingHit] = []
        for hit in hits:
            source = hit.get("_source", {})
            accession_no = source.get("adsh", "")
            ciks = source.get("ciks") or []
            cik = ciks[0] if ciks else ""
            display_names = source.get("display_names") or []
            company_name = display_names[0] if display_names else ""
            form = source.get("form", "")
            file_date = source.get("file_date", "")

            filing_url = ""
            hit_id = hit.get("_id", "")
            if accession_no and cik and ":" in hit_id:
                filename = hit_id.split(":", 1)[1]
                accession_no_nodash = accession_no.replace("-", "")
                cik_nolead = str(int(cik)) if cik.isdigit() else cik
                filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_nolead}/{accession_no_nodash}/{filename}"

            if not accession_no:
                logger.warning(f"Skipping EDGAR hit with missing accession number for query {query!r}.")
                continue

            records.append(EdgarFilingHit(
                query=query,
                accession_no=accession_no,
                cik=cik,
                company_name=company_name,
                form=form,
                file_date=file_date,
                filing_url=filing_url,
                fetched_at=fetched_at,
            ))
        return records
