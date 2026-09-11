from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .models import MsciReviewEvent


class MsciIndexReviewStorage:
    COLS = [
        "review_cycle", "announcement_date", "effective_date", "action", "index_name",
        "country", "ticker", "security_name", "size_segment", "sedol", "isin", "ric", "fetched_at",
        "source_url",
    ]

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "msci_reviews"
        self.normalized_root = base_dir / "data" / "normalized" / "msci_reviews"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_payload(self, run_id: str, name: str, data: Any) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def load_events(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "msci_rebalance_events.parquet"
        csv_path = self.normalized_root / "msci_rebalance_events.csv"
        if parquet_path.exists():
            return pd.read_parquet(parquet_path)[self.COLS]
        if csv_path.exists():
            return pd.read_csv(csv_path)[self.COLS]
        return pd.DataFrame(columns=self.COLS)

    def upsert_events(self, records: Iterable[MsciReviewEvent]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.COLS)
        if incoming.empty:
            return self.load_events()
        existing = self.load_events()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        # Public MSCI lists normally expose names, not exchange tickers.  Use
        # the ticker when one is available (so a later name correction still
        # replaces the same event), otherwise use the security name so a full
        # name-only table is not collapsed into one blank-ticker row.
        merged["_security_key"] = merged["ticker"].where(
            merged["ticker"].fillna("").astype(str).str.strip().ne(""),
            merged["security_name"],
        )
        merged = merged.drop_duplicates(
            subset=["review_cycle", "index_name", "action", "country", "_security_key"],
            keep="last",
        ).drop(columns=["_security_key"])
        merged = merged.sort_values(by=["effective_date", "index_name", "action", "ticker"]).reset_index(drop=True)
        # No CSV twin: `*.csv` is gitignored repo-wide, so the twin was never
        # published -- it only cost local disk (151 MB against a 12 MB parquet
        # for the largest lane) and doubled the write on every refresh.
        merged.to_parquet(self.normalized_root / "msci_rebalance_events.parquet", index=False)
        return merged
