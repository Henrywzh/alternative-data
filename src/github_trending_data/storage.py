import os
import logging
from pathlib import Path
from typing import List, Dict, Any
import pandas as pd
from dataclasses import asdict

from .models import TrendingRepo

logger = logging.getLogger(__name__)

class GithubTrendingStorage:
    RETENTION_RULES = {
        'daily': 5,
        'weekly': 5,
        'monthly': 50
    }
    
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.raw_dir = self.base_dir / "raw" / "github_trending"
        self.norm_dir = self.base_dir / "normalized" / "github_trending"
        
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.norm_dir.mkdir(parents=True, exist_ok=True)
        
    def _enforce_retention(self, df: pd.DataFrame, period: str) -> pd.DataFrame:
        """
        Keeps only the most recent N days based on scrape_date for the given period.
        """
        if df.empty:
            return df
            
        retention_days = self.RETENTION_RULES.get(period, 5)
        
        # Pandas may return an Arrow-backed extension array here, which does not
        # implement in-place ``sort()``. Normalize to a plain sorted Python list.
        unique_dates = sorted(
            value
            for value in df["scrape_date"].dropna().astype(str).unique().tolist()
        )
        recent_dates = unique_dates[-retention_days:]
        
        filtered = df[df['scrape_date'].isin(recent_dates)].copy()
        logger.info(f"Retained {len(recent_dates)} unique dates for {period} (Policy: {retention_days} days). Rows: {len(filtered)}")
        return filtered

    def _write_manifest(self, run_id: str, scraped_at: str):
        """
        Creates a manifest.json file for the current run to satisfy health checks.
        """
        run_dir = self.raw_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        manifest = {
            "run_id": run_id,
            "scraped_at": scraped_at,
            "source": "github_trending"
        }
        
        manifest_path = run_dir / "manifest.json"
        with open(manifest_path, "w") as f:
            import json
            json.dump(manifest, f, indent=2)
        logger.info(f"Created run manifest at {manifest_path}")

    def save(self, period: str, repos: List[TrendingRepo]):
        """
        Saves the new repos and deduplicates/cleans older data for the given period.
        """
        if not repos:
            logger.warning(f"No repositories to save for {period}")
            return
            
        file_path = self.norm_dir / f"github_trending_{period}.parquet"
        
        # Capture run metadata from the first repo to create a manifest
        # (All repos in this call share the same run_id and scraped_at)
        run_id = repos[0].source_run_id
        scraped_at = repos[0].scraped_at
        self._write_manifest(run_id, scraped_at)
        
        # Load existing data if file exists
        if file_path.exists():
            existing_df = pd.read_parquet(file_path)
            logger.info(f"Loaded existing data from {file_path}: {len(existing_df)} rows")
        else:
            existing_df = pd.DataFrame()
            
        # Convert new repos to DataFrame
        new_df = pd.DataFrame([asdict(r) for r in repos])
        
        # Concatenate
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        
        # Deduplicate: Keep the last entry for a specific repo on a specific scrape_date
        subset_cols = ['scrape_date', 'period', 'author', 'name']
        combined = combined.drop_duplicates(subset=subset_cols, keep='last')
        
        # Enforce retention policy
        combined = self._enforce_retention(combined, period)
        
        # Save to Parquet
        combined.to_parquet(file_path, index=False)
        logger.info(f"Saved {len(combined)} rows to {file_path}")
