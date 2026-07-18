import json
import logging
from pathlib import Path
from typing import Any, Iterable
import pandas as pd
from .models import EdgarFilingHit

logger = logging.getLogger(__name__)

class EdgarStorage:
    FILINGS_COLS = ["query", "accession_no", "cik", "company_name", "form", "file_date", "filing_url", "fetched_at"]

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "sec_edgar"
        self.normalized_root = base_dir / "data" / "normalized" / "sec_edgar"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_payload(self, run_id: str, name: str, data: Any) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return path

    def load_filings(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "edgar_filings.parquet"
        csv_path = self.normalized_root / "edgar_filings.csv"
        if parquet_path.exists():
            df = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            return pd.DataFrame(columns=self.FILINGS_COLS)
        return df[self.FILINGS_COLS]

    def upsert_filings(self, records: Iterable[EdgarFilingHit]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.FILINGS_COLS)
        if incoming.empty:
            return self.load_filings()

        existing = self.load_filings()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()

        merged = merged.drop_duplicates(subset=["query", "accession_no"], keep="last")
        merged = merged.sort_values(by=["file_date", "query", "accession_no"], ascending=[False, True, True]).reset_index(drop=True)

        parquet_path = self.normalized_root / "edgar_filings.parquet"
        csv_path = self.normalized_root / "edgar_filings.csv"
        merged.to_parquet(parquet_path, index=False)
        merged.to_csv(csv_path, index=False)
        return merged
