from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from uuid import uuid4
from .client import EdgarFullTextSearchClient
from .config import resolve_user_agent
from .storage import EdgarStorage

logger = logging.getLogger(__name__)

class EdgarPipeline:
    # Keyword watchlist mirroring the mention-tracking pattern used in
    # semiconductor_memory_data, applied here across all EDGAR filers.
    DEFAULT_QUERIES = [
        "chip shortage",
        "supply chain disruption",
        "export controls",
        "capacity constraint",
        "artificial intelligence demand",
    ]
    DEFAULT_FORMS = ["8-K", "10-Q", "10-K"]
    DEFAULT_LOOKBACK_DAYS = 7  # overlaps across runs; dedup on (query, accession_no) handles re-fetches

    def __init__(self, base_dir: Path, client: EdgarFullTextSearchClient | None = None) -> None:
        self.base_dir = base_dir
        self.storage = EdgarStorage(base_dir)
        self.client = client or EdgarFullTextSearchClient(user_agent=resolve_user_agent(base_dir))

    def run(
        self,
        queries: list[str] | None = None,
        forms: list[str] | None = None,
        lookback_days: int | None = None,
    ) -> dict:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        logger.info(f"Starting SEC EDGAR Full-Text Search Run: {run_id}")

        target_queries = queries or self.DEFAULT_QUERIES
        target_forms = forms if forms is not None else self.DEFAULT_FORMS
        window_days = lookback_days if lookback_days is not None else self.DEFAULT_LOOKBACK_DAYS

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=window_days)

        filing_records = []
        fetched_counts: dict[str, int] = {}
        errors: dict[str, str] = {}

        for query in target_queries:
            logger.info(f"Searching EDGAR full-text index for: {query!r}")
            try:
                payload = self.client.search(
                    query=query,
                    forms=target_forms,
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
                )
                self.storage.write_raw_payload(run_id, f"search_{query.replace(' ', '_')}", payload)

                records = self.client.extract(payload, query=query)
                filing_records.extend(records)
                fetched_counts[query] = len(records)
                logger.info(f"Found {len(records)} filings for {query!r}.")
            except Exception as e:
                logger.error(f"Error searching EDGAR for {query!r}: {e}")
                errors[query] = str(e)

        filings_written = 0
        if filing_records:
            df = self.storage.upsert_filings(filing_records)
            filings_written = len(df)
            logger.info(f"Upserted EDGAR filings. Total rows: {filings_written}")

        return {
            "fetched": fetched_counts,
            "filings_written": filings_written,
            "errors": errors,
        }
