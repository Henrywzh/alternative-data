"""SEC filing event feed for listed commercial-space companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from ..config import DEFAULT_TIMEOUT, SEC_SPACE_COMPANIES, SEC_SUBMISSIONS_URL, SEC_USER_AGENT
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "ticker",
    "company_name",
    "form",
    "filing_date",
    "report_date",
    "accession_number",
    "primary_document",
    "primary_doc_description",
    "filing_url",
    "fetched_at",
]

EVENT_FORMS = {"8-K", "10-K", "10-Q", "20-F", "6-K", "S-1", "S-3", "424B4"}


def fetch_sec_space_company_filings(*, recent_per_company: int = 30) -> pd.DataFrame:
    """Fetch recent official SEC filing metadata, not inferred order amounts."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    headers = {
        "User-Agent": SEC_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov",
    }
    rows = []
    for ticker, company in SEC_SPACE_COMPANIES.items():
        try:
            url = SEC_SUBMISSIONS_URL.format(cik=company["cik"])
            response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT * 2)
            response.raise_for_status()
            payload = response.json()
            save_raw_snapshot(f"sec_submissions_{ticker}", payload, source_url=url)
            recent = payload.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            for idx, form in enumerate(forms):
                if form not in EVENT_FORMS:
                    continue
                accession = recent.get("accessionNumber", [""])[idx]
                accession_compact = accession.replace("-", "")
                primary_document = recent.get("primaryDocument", [""])[idx]
                rows.append({
                    "ticker": ticker,
                    "company_name": company["name"],
                    "form": form,
                    "filing_date": recent.get("filingDate", [""])[idx],
                    "report_date": recent.get("reportDate", [""])[idx],
                    "accession_number": accession,
                    "primary_document": primary_document,
                    "primary_doc_description": recent.get("primaryDocDescription", [""])[idx],
                    "filing_url": f"https://www.sec.gov/Archives/edgar/data/{int(company['cik'])}/{accession_compact}/{primary_document}",
                    "fetched_at": fetched_at,
                })
                if sum(row["ticker"] == ticker for row in rows) >= recent_per_company:
                    break
        except Exception as exc:
            logger.warning("Failed to fetch SEC submissions for %s: %s", ticker, exc)
    if not rows:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
    return pd.DataFrame(rows, columns=SCHEMA_COLUMNS).sort_values(
        ["filing_date", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)
