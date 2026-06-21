"""
Storage layer: save/load raw + processed Parquet files.
"""
import json
import logging
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from typing import List

import pandas as pd

from .models import TrendsDataPoint, StockDataPoint

logger = logging.getLogger(__name__)


class GoogleTrendsStorage:
    """
    Persists Google Trends and stock data to Parquet files.

    Directory layout:
        data/
          raw/google_trends/
            {keyword}_{geo}_trends.parquet
            {ticker}_stock_daily.parquet
          processed/google_trends/
            {keyword}_{geo}_{ticker}_combined.parquet
    """

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.raw_dir = self.base_dir / "raw" / "google_trends"
        self.processed_dir = self.base_dir / "processed" / "google_trends"

        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    # ── Trends ───────────────────────────────────────────────────────────────
    def save_trends(self, keyword: str, geo: str, records: List[TrendsDataPoint]):
        """Append-deduplicate and persist trends records."""
        slug = self._slug(keyword)
        geo_tag = geo if geo else "worldwide"
        path = self.raw_dir / f"{slug}_{geo_tag}_trends.parquet"

        new_df = pd.DataFrame([asdict(r) for r in records])
        combined = self._merge_parquet(path, new_df, dedup_cols=["date", "keyword", "geo"])
        combined.to_parquet(path, index=False)
        logger.info(f"Saved {len(combined)} trends rows → {path}")

    def load_trends(self, keyword: str, geo: str) -> pd.DataFrame:
        slug = self._slug(keyword)
        geo_tag = geo if geo else "worldwide"
        path = self.raw_dir / f"{slug}_{geo_tag}_trends.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    # ── Stock ────────────────────────────────────────────────────────────────
    def save_stock(self, ticker: str, records: List[StockDataPoint]):
        """Append-deduplicate and persist daily stock records."""
        slug = self._slug(ticker)
        path = self.raw_dir / f"{slug}_stock_daily.parquet"

        new_df = pd.DataFrame([asdict(r) for r in records])
        combined = self._merge_parquet(path, new_df, dedup_cols=["date", "ticker"])
        combined.to_parquet(path, index=False)
        logger.info(f"Saved {len(combined)} stock rows → {path}")

    def load_stock(self, ticker: str) -> pd.DataFrame:
        slug = self._slug(ticker)
        path = self.raw_dir / f"{slug}_stock_daily.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    # ── Combined signal ──────────────────────────────────────────────────────
    def save_combined(self, keyword: str, geo: str, ticker: str, df: pd.DataFrame):
        slug_kw = self._slug(keyword)
        slug_tk = self._slug(ticker)
        geo_tag = geo if geo else "worldwide"
        path = self.processed_dir / f"{slug_kw}_{geo_tag}_{slug_tk}_combined.parquet"
        df.to_parquet(path, index=False)
        logger.info(f"Saved {len(df)} combined rows → {path}")

    def load_combined(self, keyword: str, geo: str, ticker: str) -> pd.DataFrame:
        slug_kw = self._slug(keyword)
        slug_tk = self._slug(ticker)
        geo_tag = geo if geo else "worldwide"
        path = self.processed_dir / f"{slug_kw}_{geo_tag}_{slug_tk}_combined.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    # ── Helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    def _slug(name: str) -> str:
        return name.lower().replace(" ", "_").replace(".", "_").replace("/", "_")

    @staticmethod
    def _merge_parquet(
        path: Path,
        new_df: pd.DataFrame,
        dedup_cols: List[str],
    ) -> pd.DataFrame:
        if path.exists():
            existing = pd.read_parquet(path)
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df
        combined = combined.drop_duplicates(subset=dedup_cols, keep="last")
        return combined
