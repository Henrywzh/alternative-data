from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .models import FactsetEarningsObservation


class FactsetEarningsStorage:
    COLS = [
        "report_date",
        "reference_quarter",
        "blended_earnings_growth_yoy",
        "blended_revenue_growth_yoy",
        "eps_beat_rate",
        "eps_surprise_pct",
        "revenue_beat_rate",
        "revenue_surprise_pct",
        "forward_12m_pe",
        "forward_12m_pe_10y_avg",
        "revision_breadth_score",
        "sector_growth_json",
        "fetched_at",
        "source_url",
    ]

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "factset_earnings"
        self.normalized_root = base_dir / "data" / "normalized" / "factset_earnings"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_payload(self, run_id: str, name: str, data: Any) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def load_observations(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "factset_sp500_earnings_regime.parquet"
        csv_path = self.normalized_root / "factset_sp500_earnings_regime.csv"
        if parquet_path.exists():
            return pd.read_parquet(parquet_path)[self.COLS]
        if csv_path.exists():
            return pd.read_csv(csv_path)[self.COLS]
        return pd.DataFrame(columns=self.COLS)

    def upsert_observations(self, records: Iterable[FactsetEarningsObservation]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.COLS)
        if incoming.empty:
            return self.load_observations()
        existing = self.load_observations()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        for col in ["blended_earnings_growth_yoy", "blended_revenue_growth_yoy", "eps_beat_rate", "eps_surprise_pct", "forward_12m_pe"]:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")
        # A rerun can repair a parser-derived field (notably the reference
        # quarter) for the same public article.  Remove the prior version by
        # article URL before applying the normal date/quarter key.  The test
        # fixture uses the package root URL as a placeholder, so only real
        # article URLs participate in this first pass.
        real_source = merged["source_url"].fillna("").astype(str).str.strip()
        article_mask = real_source.str.startswith("https://insight.factset.com/") & ~real_source.eq("https://insight.factset.com/")
        if article_mask.any():
            article_rows = merged.loc[article_mask].drop_duplicates(subset=["source_url"], keep="last")
            non_article_rows = merged.loc[~article_mask]
            merged = pd.concat([non_article_rows, article_rows], ignore_index=True)
        merged = merged.drop_duplicates(subset=["report_date", "reference_quarter"], keep="last")
        merged = merged.sort_values(by=["report_date"]).reset_index(drop=True)
        # No CSV twin: `*.csv` is gitignored repo-wide, so the twin was never
        # published -- it only cost local disk (151 MB against a 12 MB parquet
        # for the largest lane) and doubled the write on every refresh.
        merged.to_parquet(self.normalized_root / "factset_sp500_earnings_regime.parquet", index=False)
        return merged
