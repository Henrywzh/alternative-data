from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class EdgarFilingHit:
    """A single filing matched by an EDGAR full-text search query."""
    query: str
    accession_no: str
    cik: str
    company_name: str
    form: str
    file_date: str
    filing_url: str
    fetched_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
